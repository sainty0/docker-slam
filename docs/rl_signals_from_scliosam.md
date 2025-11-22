# RL Signals from SC-LIO-SAM

The PPO agent in `rl_vo/train.py` closes a control loop around SC-LIO-SAM by monitoring lightweight metrics and adjusting the surface voxel size. The components in this loop live entirely inside this repository, so every signal can be traced to its code location.

## Feedback Loop
1. **Episode orchestration** (`rl_vo/env/episode_orchestrator.py`): keeps a persistent ROS core alive (`core.launch`), respawns `rl_vo/launch/lio_stack.launch` every episode, restarts the MulRan file player, and ensures `/rl_metrics/reset` is called before data starts streaming (lines 123‑159, 205‑247).
2. **Metrics capture** (`metric_pkg/scripts/metrics_exporter.py`): subscribes to SC-LIO-SAM topics, tracks running stats, and writes `/tmp/rlvo/metrics.json` when `/rl_metrics/commit` is triggered (lines 39‑203 and 262‑331).
3. **RL environment** (`rl_vo/env/rl_env.py`): every `step_len_s` seconds (default 1 s) the environment publishes an action to `/lio_sam/params/mapping_surf_leaf_size`, waits for ROS to advance, calls `/rl_metrics/commit`, and turns the resulting JSON entries into a normalised observation vector (lines 92‑196, 232‑308).
4. **Action application**: `mapOptimization::mappingSurfLeafSizeHandler` (`SC-LIO-SAM/src/mapOptmization.cpp:610‑627`) receives the Float32 message, guards against non-positive values, updates `mappingSurfLeafSize`, and reconfigures `downSizeFilterSurf` and `downSizeFilterICP` under mutex so the next scan-to-map optimisation uses the requested voxel size.

```mermaid
graph LR
    Player[file_player_headless<br/>MulRan logs] -->|/os1_points + /imu/data_raw| LIO[SC-LIO-SAM nodes]
    LIO -->|deskewed clouds,<br/>corner/surf features,<br/>incremental odom| Metrics(metric_pkg/metrics_exporter)
    Metrics -->|/rl_metrics/commit<br/>metrics.json| Env[RLBatchedEnv]
    Env -->|observations| PPO[train.py (PPO)]
    PPO -->|scalar action| Env
    Env -->|Float32 /lio_sam/params/mapping_surf_leaf_size<br/>(rosbridge publish)| Rosbridge[rosbridge_websocket]
    Rosbridge -->|topic relay| LIO
    LIO -->|/lio_sam/mapping/odometry_incremental| OdomToTUM[odom_to_tum.py]
    OdomToTUM -->|est.tum paths| Env
    Env -->|APE reward (`env/utils/ape.py`)| PPO
```

## Observation Channels
`metric_pkg/scripts/metrics_exporter.py` produces all observation values consumed by `RLBatchedEnv._obs_from_stats()`:

| RL Feature | Source Topic(s) | Where it is computed | Notes |
|---|---|---|---|
| `pts_per_scan_mean/std`, `scan_rate_hz` | `/lio_sam/deskew/cloud_deskewed` | `cb_scan`, `_rate_from_times` | Counts (`width*height`) and cadence of full deskewed clouds. Smaller `surf_leaf_size` indirectly increases remaining points by making scan-to-map tighter. |
| `surf_pts_mean/std` | `/lio_sam/feature/cloud_surface` | `cb_surf` | Downsampled surf features produced with `odometrySurfLeafSize`; sensitive to voxel size and curvature thresholds. |
| `corner_pts_mean/std` | `/lio_sam/feature/cloud_corner` | `cb_corner` | Tracks the number of usable edge features — spikes when the leaf size shrinks or thresholds go down. |
| `odom_rate_hz`, `vel_norm_mean/std`, `pose_dropouts_s`, `acc_jolt_mean` | `/lio_sam/mapping/odometry_incremental` | `cb_odom` | Velocity estimates and Δt measurements reflect whether scan-to-map can keep up. If RL lowers `surf_leaf_size` too far, processing slows, Δt grows, and `pose_dropouts_s` penalises the reward. |
| `imu_ang_vel_rms`, `imu_lin_acc_rms` | `/imu/data_raw` | `cb_imu` | Provide motion context so the policy can distinguish between static and aggressive driving segments. |
| `planarity_ratio_mean` | Derived from `surf_pts_mean` vs total features | `_make_dict` | Acts as a proxy for environment type (planar vs cluttered). RL learns when finer voxels matter more. |
| `action_last` | `/lio_sam/params/mapping_surf_leaf_size` | `_on_leaf_update` | Echoes the previously published leaf size so PPO can smooth actions (`action_smooth_penalty`). |
| `variable_tokens` (`max_tokens` × 3) | Combined | `_build_variable_tokens` | Each token bundles `[surf_pts, corner_pts, vel_norm]` aligned in time, so PPO sees short histories. |
| `critique_tail` (4 values) | Derived mix (`odom_rate_hz`, `pose_dropouts_s`, `scan_rate_hz`, `pts_per_scan_mean`) | `_make_dict` | Supplementary context appended to obs vector. |

The JSON is read back by `EpisodeOrchestrator.commit_metrics()`, which first calls `/rl_metrics/commit` over rosbridge (lines 180‑201) and then loads the file. `RLBatchedEnv` normalises the flattened observation via `RunningMeanStdLite` (lines 264‑304).

## Reward Signal
- `RLBatchedEnv.step()` (lines 205‑251) writes the current `est.tum` path from `/lio_sam/mapping/odometry_incremental` via `odom_to_tum.py` (launched per episode). It computes APE every `score_win_s` seconds (default 3 s) by comparing the last segment of `est.tum` to a MulRan ground-truth file through `env/utils/ape.py`.
- Reward is `0.1 * (-APE)` minus small runtime and action-change penalties (lines 247‑263). Episodes are invalidated (mask cleared) when GT files are missing or when metrics are unavailable, so training only uses consistent, data-backed steps.

## Action Mapping and Effects
- PPO outputs `a ∈ [0,1]`. `action_to_leaf()` (`env/rl_env.py:17-24`) logarithmically maps this to `[5e-4, 1.0]` m, clamping extremes so rosbridge never sends invalid data.
- `EpisodeOrchestrator.set_leaf()` sends the Float32 through rosbridge (`env/rosbridge_client.py:18-44`). During reset, `EpisodeOrchestrator.begin_episode()` sends a safe `0.40` m value before replay starts (line 135).
- `mapOptimization::mappingSurfLeafSizeHandler` rejects `≤0` inputs, updates `mappingSurfLeafSize`, and calls `pcl::VoxelGrid::setLeafSize` for both `downSizeFilterSurf` and `downSizeFilterICP`. This immediately changes how many surf map points exist and how fine-grained the ICP residuals are.
  - **Smaller value** → denser surf map → more constraints → higher CPU cost but potentially lower APE. RL learns to apply this when `planarity_ratio` is low (cluttered scenes) or when `odom_rate_hz` drops.
  - **Larger value** → sparser map → faster runtime, worse alignment. Useful when `pts_per_scan_mean` is extremely high and processing falls behind (reflected via `pose_dropouts_s`).

## How Signals Flow Through rosbridge/metrics
- `core.launch` runs rosbridge and metrics exporter exactly once. All RL communication uses rosbridge WebSocket:
  - `publish_float` for `/lio_sam/params/mapping_surf_leaf_size`.
  - `call_service` for `/rl_metrics/reset` and `/rl_metrics/commit`.
- `EpisodeOrchestrator.tick()` keeps ROS spinning between commits; it also ensures `file_player_headless` keeps publishing until `max_steps` or EOF.
- Because SC-LIO-SAM topics stay in the ROS graph, nothing inside the RL process needs `rospy` or `roscpp`. This strict separation lets you inspect each signal (topic or service) independently when debugging RL behaviour.
