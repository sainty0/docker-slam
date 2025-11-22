# SC-LIO-SAM Hyperparameters

## Changelog
- 2025-11-16 – Documented that the voxel-leaf parameters were prioritised via `run_sweep.sh` OFAT sweeps (see `docs/hyperparameter_sweep_overview.md`), and clarified that `mappingSurfLeafSize` became the RL action because it combines strong APE sensitivity with an exposed runtime topic.

## Architectural Snapshot
- **Param server**: `SC-LIO-SAM/include/utility.h` centralises ROS parameters. Every major node (`imageProjection`, `featureExtraction`, `imuPreintegration`, `mapOptmization`) derives from `ParamServer`, so the same values from `config/params_mulran.yaml` (loaded by `rl_vo/launch/lio_stack.launch`) are available everywhere.
- **Front‑end** (`src/imageProjection.cpp`, `src/featureExtraction.cpp`): deskews raw LiDAR scans using IMU/odometry queues, builds a range image, extracts edge/surface features, and publishes them plus `lio_sam/cloud_info`.
- **Back‑end** (`src/mapOptmization.cpp`): runs scan‑to‑map optimization, downsampling filters, GTSAM factor updates, Scancontext loop closure, and runtime surf leaf-size updates via `mappingSurfLeafSizeHandler`.
- **IMU/GPS fusion** (`src/imuPreintegration.cpp`): builds the IMU factor graph (`IMUPreintegration`), publishes incremental odometry, and fuses mapping odometry with IMU (`TransformFusion`).
- **Loop closure** (`include/Scancontext.h`, `src/Scancontext.cpp`): Scancontext maintains polar descriptors with internal constants (rings, sectors, thresholds) that can be tuned at compile time.

## Configuration Philosophy
- **Single YAML source**: Every launch uses the same parameter file; for RL experiments we use `config/params_mulran.yaml`. Keeping one canonical file makes it easy to reason about RL-induced changes versus nominal behaviour.
- **Compute budget first**: Voxel filters (`odometrySurfLeafSize`, `mappingCornerLeafSize`, `mappingSurfLeafSize`) and throttling (`mappingProcessInterval`, `numberOfCores`) guard real-time performance; the RL agent only modulates `mappingSurfLeafSize` at runtime to stay within this budget.
- **Sweep-backed priorities**: Before exposing any knob to RL, `run_sweep.sh` executed OFAT sweeps across the voxel sizes, feature count minima, and curvature thresholds. Spearman analysis (see `docs/hyperparameter_sweep_spearman_analysis.md`) highlighted the voxel-leaf trio as the dominant contributors to APE, so only the surf leaf size—accessible at runtime via `/lio_sam/params/mapping_surf_leaf_size`—was left adjustable online.
- **Safety rails**: Parameters such as `gpsCovThreshold`, `edgeFeatureMinValidNum`, `historyKeyframeFitnessScore`, and IMU/gps usage flags gate when external measurements are fused, reducing the risk of RL destabilising the estimator.

## Parameter Tables (defaults from `SC-LIO-SAM/SC-LIO-SAM/config/params_mulran.yaml`)

### I/O, Frames, and Sensor Setup
| Name | Type | Default | Module(s) | Description | RL Relevance |
|---|---|---|---|---|---|
| `pointCloudTopic` | string | `/os1_points` | imageProjection | LiDAR packet stream turned into range image and deskewed clouds (`src/imageProjection.cpp`). | Medium – metrics exporter computes scan density from its output. |
| `imuTopic` | string | `/imu/data_raw` | imageProjection, IMUPreintegration | Raw IMU feed used for deskew and preintegration. | Medium – IMU norms feed RL metrics. |
| `odomTopic` | string | `odometry/imu` | IMUPreintegration, TransformFusion, imageProjection | Base namespace for IMU odometry outputs (`odometry/imu` and `_incremental`). | High – `/odometry/imu_incremental` becomes `/lio_sam/mapping/odometry_incremental`, the primary RL signal. |
| `gpsTopic` | string | `odometry/gpsz` | mapOptimization | Navsat / EKF odometry fused when covariances below thresholds. | Low – GPS only stabilises drift. |
| `lidarFrame`/`baselinkFrame` | string | `base_link` | all nodes | Source and body frames for clouds/TFs. | Low. |
| `odometryFrame`/`mapFrame` | string | `odom` / `map` | TransformFusion, mapOptimization | Defines published TF tree (`map→odom→base_link`). | Medium – consistent frames needed for odom export / RL reward. |
| `sensor` | enum | `mulran` | imageProjection | Selects point type to parse (Velodyne/Ouster/MulRan). | Medium – wrong struct corrupts stats consumed by RL. |
| `N_SCAN`, `Horizon_SCAN` | int | `64`, `1024` | imageProjection | Range image shape used during projection. | Medium – determines per-scan token layout in metrics. |
| `downsampleRate` | int | `1` | imageProjection | Optional scan decimation before projection. | Low. |
| `lidarMinRange` / `lidarMaxRange` | float | `1.0` / `1000.0` | imageProjection | Clamps ranges before feature extraction. | Medium – affects feature counts (RL observation). |

### IMU/Extrinsics and Feature Extraction
| Name | Type | Default | Module(s) | Description | RL Relevance |
|---|---|---|---|---|---|
| `imuAccNoise`, `imuGyrNoise` | float | `9.94e-06`, `5.64e-06` | IMUPreintegration | Continuous white noise terms fed into GTSAM `PreintegrationParams`. | Low – static. |
| `imuAccBiasN`, `imuGyrBiasN` | float | `6.44e-04`, `3.56e-04` | IMUPreintegration | Bias random walk covariance (`noiseModelBetweenBias`). | Low. |
| `imuGravity` | float | `9.80511` | IMUPreintegration | Gravity magnitude for navigation state prediction. | Low. |
| `imuRPYWeight` | float | `0.01` | mapOptimization | Slerp weight in `transformUpdate()` when blending IMU roll/pitch (line 1560). | Medium – higher weight trusts IMU more; ties into odometry smoothness RL observes. |
| `extrinsicTrans`, `extrinsicRot`, `extrinsicRPY` | vector | `[1.77, -0.0, -0.05]`, rotation matrices | ParamServer | LiDAR→IMU calibration used in IMU conversion and GTSAM pose composition. | Medium – misalignment affects odom quality. |
| `edgeThreshold`, `surfThreshold` | float | `1.0`, `0.1` | featureExtraction | Min curvature magnitude when labelling corner/surf features. | High – directly controls how many points end up in the surf cloud that RL monitors. |
| `edgeFeatureMinValidNum`, `surfFeatureMinValidNum` | int | `10`, `100` | mapOptimization | Minimum downsampled features before scan-to-map optimization runs; otherwise warns and skips. | High – RL can detect low counts and react. |
| `odometrySurfLeafSize` | float | `0.4` | featureExtraction | Voxel leaf for surface cloud downsizing before publishing. | Medium – affects surface point counts in metrics. |

### Mapping, Downsampling, and Loop Closure
| Name | Type | Default | Module(s) | Description | RL Relevance |
|---|---|---|---|---|---|
| `mappingCornerLeafSize` | float | `0.2` | mapOptimization | Leaf size for map-side corner downsampling (`downSizeFilterCorner`). | Medium – influences optimization cost. |
| `mappingSurfLeafSize` | float | `0.4` | mapOptimization | Leaf size for surf map voxels and ICP map. Runtime-updated via `/lio_sam/params/mapping_surf_leaf_size`. | **High – RL directly writes this topic each step.** |
| `z_tollerance`, `rotation_tollerance` | float | `1000`, `1000` | mapOptimization | Used in `transformUpdate()` to clamp vertical drift and roll/pitch (lines 1570+). | Low. |
| `numberOfCores` | int | `4` | mapOptimization | OpenMP `num_threads` for map extraction/downsampling loops. | Low. |
| `mappingProcessInterval` | double | `0.15` | mapOptimization | Minimum seconds between `run()` iterations (line 381). | Medium – relates to RL step cadence (default env step is 1 s). |
| `surroundingkeyframeAddingDistThreshold` | float | `1.0` | mapOptimization | Position delta before adding a new keyframe (lines 1608–1611). | Medium – controls map growth observed by RL metrics. |
| `surroundingkeyframeAddingAngleThreshold` | float | `0.2` rad | mapOptimization | Rotation delta gating keyframe creation. | Medium. |
| `surroundingKeyframeDensity` | float | `2.0` | mapOptimization | Leaf size when downsampling nearby key poses (line 248). | Low. |
| `surroundingKeyframeSearchRadius` | float | `50.0` | mapOptimization | Radius for finding active submap around the latest key pose (lines 1104–1135). | Medium. |
| `loopClosureEnableFlag` | bool | `false` (MulRan) | mapOptimization | Enables Scancontext + RANSAC loop closure thread. | Medium – enabling changes odom drift RL sees. |
| `loopClosureFrequency` | float | `1.0` Hz | mapOptimization | Sleep rate for `loopClosureThread()` (line 588). | Low. |
| `surroundingKeyframeSize` | int | `50` | mapOptimization | Number of keyframes to include when loop closure is active. | Low. |
| `historyKeyframeSearchRadius` | float | `15.0` | mapOptimization | Radius for candidate loop closures (line 1111). | Medium. |
| `historyKeyframeSearchTimeDiff` | float | `30.0` s | mapOptimization | Minimum time separation for loop closure (line 843). | Low. |
| `historyKeyframeSearchNum` | int | `25` | mapOptimization | Submap size used in loop ICP (line 676). | Low. |
| `historyKeyframeFitnessScore` | float | `0.3` | mapOptimization | ICP fitness threshold to accept loop closures (lines 677, 769). | Medium – impacts loop corrections. |
| `globalMapVisualizationSearchRadius` | float | `1000.0` | mapOptimization | Radius when building map output for visualization thread (lines 560+). | Low. |
| `globalMapVisualizationPoseDensity` | float | `10.0` | mapOptimization | Downsample spacing for displayed pose cloud. | Low. |
| `globalMapVisualizationLeafSize` | float | `0.2` | mapOptimization | Leaf size for global visualization cloud. | Low. |
| `savePCD`, `savePCDDirectory` | bool/string | `false`, path | mapOptimization | Control whether optimized poses + map clouds are saved on shutdown (lines 480+). | Low. |

### GPS, IMU Heading, and Safety Thresholds
| Name | Type | Default | Module(s) | Description | RL Relevance |
|---|---|---|---|---|---|
| `useImuHeadingInitialization` | bool | `true` | mapOptimization | When `false`, yaw is zeroed during first pose guess (lines 1018‑1034). | Medium – influences startup stability that RL episodes rely on. |
| `useGpsElevation` | bool | `false` | mapOptimization | When false, GPS Z is ignored (lines 1682+). | Low. |
| `gpsCovThreshold`, `poseCovThreshold` | float | `2.0`, `25.0` | mapOptimization | Covariance gates before pushing GPS factors onto `gpsQueue`. | Low. |

### Scancontext Loop Closure Constants (compile-time, `include/Scancontext.h`)
| Name | Type | Default | Module(s) | Description | RL Relevance |
|---|---|---|---|---|---|
| `PC_NUM_RING`, `PC_NUM_SECTOR` | int | `20`, `60` | Scancontext | Resolution of polar descriptor bins. | Low – compile-time. |
| `PC_MAX_RADIUS` | float | `80.0` m | Scancontext | Max radius encoded in descriptor. | Low. |
| `SC_DIST_THRES` | float | `0.3` | Scancontext | Distance threshold for accepting a Scancontext match (lines 52‑78). | Medium – when low, more loops correct the map RL judges. |
| `TREE_MAKING_PERIOD_` | int | `10` | Scancontext | How often KD-tree is rebuilt (seconds). | Low. |
| `NUM_EXCLUDE_RECENT` | int | `30` | Scancontext | Excludes most recent keyframes from loop candidates. | Low. |
| `NUM_CANDIDATES_FROM_TREE` | int | `3` | Scancontext | Maximum tree hits to evaluate before ICP. | Low. |

## Key Tuning Notes
- **`mappingSurfLeafSize` runtime hook**: `mapOptimization` subscribes to `/lio_sam/params/mapping_surf_leaf_size` and reconfigures both `downSizeFilterSurf` and `downSizeFilterICP` under mutex (`src/mapOptmization.cpp:232`, `610‑627`). RL trains by publishing new Float32 values every `step_len_s`.
- **Feature thresholds**: `edgeThreshold`/`surfThreshold` are applied while sorting `cloudSmoothness` values per ring (`featureExtraction.cpp:104‑190`). Lowering them increases feature counts but also increases computation and may degrade optimization stability.
- **Keyframe throttling**: `surroundingkeyframeAdding*` parameters are checked in `saveKeyFramesAndFactor()` (~line 1600) to avoid redundant keyframes; loosening them makes the factor graph denser and can slow down RL episodes.
- **IMU blending**: `imuRPYWeight`, `rotation_tollerance`, and `z_tollerance` serve as "soft constraints" after each scan-to-map iteration, keeping the pose close to IMU priors and preventing RL-induced voxel changes from sending the optimizer astray.
- **Loop closure costs**: `historyKeyframeFitnessScore` directly gates whether ICP-aligned loop closures are accepted. When RL experiments rely on consistent APE rewards, keeping this threshold conservative avoids sudden jumps that look like outliers to the RL agent.

## RL-Sensitive Parameters
- **Directly controlled**: `mappingSurfLeafSize` is the scalar RL action. Smaller voxels densify the surf map, increasing per-scan surf points and often lowering APE at the cost of runtime; larger voxels do the opposite.
- **Strongly observed**: `edgeThreshold`, `surfThreshold`, `odometrySurfLeafSize`, and `surroundingKeyframe*` parameters shape the `surf_pts_*`, `corner_pts_*`, `planarity_ratio_mean`, and odom dropout metrics exported by `metric_pkg/scripts/metrics_exporter.py`. Changing them shifts the observation distribution the agent was trained on.
- **Episode survival**: `mappingProcessInterval` and `numberOfCores` limit how fast `mapOptimization` iterates. If RL pushes `mappingSurfLeafSize` too low, processing latency may exceed the `EpisodeOrchestrator.step_len_s`, causing odom rate drops that show up as penalties in reward.

Use this table to decide whether a parameter should be held constant during RL sweeps (most entries marked Low/Medium) or can be surfaced alongside `mappingSurfLeafSize` for future multi-dimensional control.
