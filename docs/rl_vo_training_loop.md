# RL-VO Training Loop

This document stitches together the ROS-facing environment, PPO core, and SC-LIO-SAM processes described throughout `rl_vo/`. It should be the go-to reference for understanding how training actually runs on this repo.

## 1. Initialisation (`rl_vo/train.py`)
1. **Hydra config**: `@hydra.main` loads `rl_vo/config/config.yaml`. Key sections:
   - `vo_algorithm`: currently only `"SCLSAM"` is supported.
   - `mulran`: dataset root and sequence names.
   - `file_player`: playback rate plus randomisation range for start percentages.
   - `tokens`, `agent`, `timing`: observation layout and PPO hyperparameters.
2. **Environment construction**:
   - Training env: `env = RLBatchedEnv(cfg_dict, num_envs=n_envs, mock_rosbridge=DRY_RUN)` (see `rl_vo/env/rl_env.py`).
   - Validation env: same class but optionally overrides sequences via `config.eval.sequences`.
3. **Policy definition**:
   - Encoder kwargs introspected from `env` to size the attention network correctly.
   - `policy_kwargs` set `activation_fn=torch.nn.ReLU`, `net_arch=dict(pi=[256,256], vf=[256,256])`, `log_std_init=0.0`.
4. **Seeding and logging**:
   - `configure_random_seed(config.seed, env)` touches NumPy, PyTorch, and env RNGs.
   - Logging directory computed from `config.log_path`, timestamp, and optional `wandb_tag/group`.
5. **Checkpoint restore (optional)**:
   - If `config.policy_path` exists, load both `policy.state_dict()` and `<policy_path>_rms.npz` (running mean/std snapshot).
6. **PPO instantiation**:
   - `PPO(policy, env, learning_rate=get_linear_fn(3e-4, 3e-5, 1.0), clip_range=0.2, n_steps=config.agent.n_steps, …)` selects CUDA if available.
   - When `wandb_logging` is `true`, `PPO.__init__` creates a run tagged with seed and `wandb_tag`.

## 2. Episode & ROS Lifecycle (`rl_vo/env/rl_env.py`, `env/episode_orchestrator.py`)
1. `RLBatchedEnv.reset()`:
   - Randomly picks `seq ∈ mulran.seqs` and `start_percent ∈ [start_percent_min, start_percent_max]`.
   - Calls `EpisodeOrchestrator.begin_episode()` which:
     - Ensures `rl_vo/launch/core.launch` (rosbridge + metrics exporter) is running.
     - Restarts `rl_vo/launch/lio_stack.launch`, `odom_to_tum.py`, and `file_player_headless`.
     - Publishes a safe `surf_leaf_size = 0.40` m and triggers `/rl_metrics/reset`.
   - Waits for `/tmp/rlvo/metrics.json` to become non-empty before emitting the first normalised observation. If metrics are still empty after 1 s, `self._pending_rms_update` defers the RMS update until real data arrives.
2. **Observation construction**:
   - `EpisodeOrchestrator.commit_metrics()` calls `/rl_metrics/commit` through rosbridge, then loads the JSON file produced by `metric_pkg/scripts/metrics_exporter.py`. Fields include:
     - Fixed stats (means/stds, rates, IMU RMS, `action_last`).
     - `variable_tokens`: `[surf_pts, corner_pts, vel_norm]` sequences.
     - `critique_tail`: 4-D context appended only to the critic.
   - `_obs_from_stats()` concatenates `[fixed, var_flattened, tail]`, updates `RunningMeanStdLite`, and stores the normalised vector in `self._last_obs`.
3. **Action publication**:
   - PPO produces `a ∈ [0,1]`. `action_to_leaf()` log-interpolates between `LEAF_MIN=0.0005` m and `LEAF_MAX=1.0` m.
   - `EpisodeOrchestrator.set_leaf()` uses `RosbridgeClient.publish_float` to send `/lio_sam/params/mapping_surf_leaf_size`.
   - `metric_pkg` subscribes to the same topic so the next observation contains `action_last`.
4. **Timing**:
   - `EpisodeOrchestrator.tick(step_len_s)` (default 1 s) keeps SC-LIO-SAM running before fetching metrics again.
   - When playback reaches the end or comms drop, `step()` restarts only the episode actors and signals `done=True` so PPO sees an episode boundary while reusing the ROS core.

## 3. Reward Computation
- `RLBatchedEnv.step()` resolves the GT TUM path via `_resolve_gt_path()`:
  - Normal MulRan runs use `<mulran.root>/<seq>/<seq>_gt.tum`.
  - DRY_RUN mode writes synthetic GT files inside `paths.run_root`.
- `env/utils/ape.py::ape_rmse(est_path, gt_path, score_last_seconds=self.score_win_s)` aligns recent poses and outputs RMSE (metres).
- Reward formula: `r = -0.1 * ape - 0.001 * runtime_s - 0.01 * abs(a - last_action)`.
- If GT is missing or `metrics_exporter` hasn’t produced tokens yet, the env leaves `valid_mask=False` and returns `reward=0` to ensure PPO ignores the transition. This also covers the warmup just after resets.

## 4. PPO Update Cycle (`rl_algorithms/on_policy_algorithm.py`, `rl_algorithms/ppo.py`)
1. **Rollout collection**:
   - `collect_rollouts()` loops until `n_steps` transitions are gathered.
   - Each step calls the policy, clips/unscales actions to env bounds, and forwards them to the env.
   - `valid_mask` from the env is forwarded into `MaskedRolloutBuffer.add()`.
   - Episode truncations due to ROS restarts use `infos[idx]["terminal_observation"]` to bootstrap the critic.
2. **GAE**:
   - After the rollout, `rollout_buffer.compute_returns_and_advantage(last_values, dones, valid_mask)` fills the TD targets.
3. **Training**:
   - `PPO.train()` runs `n_epochs` passes over only the valid samples, computing the clipped objective, value loss, entropy bonus, and gradient clip.
   - Metrics (losses, entropy, clip fraction, KL, explained variance) are logged to WANDB when enabled.
4. **Iteration bookkeeping**:
   - `self.iteration` increments each rollout. Every 10 iterations, the env’s observation RMS is copied into the validation env so its normalisation matches training.
   - `evaluation_epoch_sclsam(val_env, n_episodes)` runs deterministic rollouts that reset the env, issue one action, and report mean reward/APEs/timeouts.
   - When `eval_interval` divides the iteration count, PPO saves `policy.save(log_dir/Policy/iter_XXXXX.pth)` and `env.save_rms(…_rms.npz)` (if implemented) for future restarts.

## 5. Integration Touch Points
- **Topics**:
  - `/lio_sam/params/mapping_surf_leaf_size`: action channel (Float32).
  - `/lio_sam/mapping/odometry_incremental`: consumed by both `odom_to_tum.py` (to write `est.tum`) and `metric_pkg` (odom rates, velocities, dropouts).
  - `/lio_sam/feature/cloud_surface`, `/lio_sam/feature/cloud_corner`, `/lio_sam/deskew/cloud_deskewed`: populate surface/corner/scan counts for observations.
  - `/imu/data_raw`: IMU RMS features.
- **Services**:
  - `/rl_metrics/reset`: clears exporter accumulators on every new episode.
  - `/rl_metrics/commit`: instructs the exporter to dump its latest JSON snapshot, which the env immediately ingests.
- **Processes**:
  - `EpisodeOrchestrator` uses process groups (`os.setsid`) so that `close_all()` cleanly tears down roslaunch, SC-LIO-SAM, file player, and odom recorder when training finishes.
  - Logs for each subprocess land in `<paths.run_root>/<run_id>/*.log`, making it easy to inspect SC-LIO-SAM behaviour that produced a particular reward curve.

## 6. Validation & Logging
- `val_env` mirrors the training env but can run multiple episodes back-to-back using the same orchestrator. It shares the same observation normalisation to keep PPO/eval metrics comparable.
- `OnPolicyAlgorithm.evaluation_epoch()` (legacy SVO path) is still available, but `evaluation_epoch_sclsam()` is the default for this project.
- When `wandb_logging=true`, the following are recorded:
  - **Training**: entropy, policy gradient loss, value loss, KL, clip fraction, latent std, explained variance.
  - **Rollouts**: reward sums, ratio of valid stages, average action magnitude.
  - **Evaluation**: mean reward/APE, timeout/divergence rates, histograms per sequence.

## 7. DRY_RUN Mode
Setting `DRY_RUN=1`:
- Forces `RLBatchedEnv` to use `MockRosbridge`.
- `EpisodeOrchestrator` skips launching ROS and instead writes synthetic TUM files, metrics, and random tokens.
- Enables quick integration testing of PPO/attention/normalisation code without GPU LiDAR playback.

## 8. Evaluation & 0.4 Baseline Comparison
1. **Reuse the saved config + checkpoint**  
   Each training directory contains the resolved Hydra config under `<log_dir>/.hydra/config.yaml` plus checkpoints under `<log_dir>/Policy/iter_XXXXX.pth` (with matching `_rms.npz`). To evaluate an already-trained agent, rerun `python rl_vo/train.py` while pointing `--config-dir` at that `.hydra` folder, `policy_path` at the checkpoint you care about, and overriding `total_timesteps=0` (or another tiny value). With `val_interval=1` the process instantly performs the evaluation loop, writes the estimated trajectory to `paths.est_tum`, and records the same `/tmp/rlvo/metrics.json` APE statistics that drove the reward.
2. **Record the trained-agent APE**  
   Consume the resulting `metrics.json` or rerun evo on the produced TUM file vs. the MulRan GT to capture `ape_rmse_m` for each sequence. Because you have reused the identical config, the dataset splits, start percentages, and timing windows match the training run.
3. **Freeze the hyperparameter at 0.4**  
   For the baseline pass, lock the mapping surface leaf size so the RL policy cannot change it. The fastest approach is to temporarily make `rl_vo/env/rl_env.py::action_to_leaf()` return `0.40` (or guard it with a config flag) before launching the evaluation command again. That forces `RLBatchedEnv.step()` and `EpisodeOrchestrator.set_leaf()` to keep publishing 0.4 for the entire episode, effectively mimicking the hand-tuned baseline without touching the rest of the ROS stack.
4. **Compare metrics**  
   Run the evaluation command a second time with the forced 0.4 behaviour. You now have two comparable runs—trained policy vs. frozen baseline—with consistent tooling. Compare their `ape_rmse_m` (and any other evo metrics) per MulRan sequence to report the improvement from learning.

Together, these steps describe the entire RL-to-SC-LIO-SAM training pipeline. See [rl_vo_overview.md](rl_vo_overview.md) for the component map, [rl_vo_attention.md](rl_vo_attention.md) for the encoder internals, [rl_vo_ppo.md](rl_vo_ppo.md) for optimisation details, and [rl_vo_buffer.md](rl_vo_buffer.md) for rollout storage semantics.
