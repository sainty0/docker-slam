# Metrics and Logging

## Metrics Exporter (``metric_pkg/scripts/metrics_exporter.py``)
- **Subscriptions**:
  - ``/lio_sam/deskew/cloud_deskewed`` → total points per scan & scan timestamps.
  - ``/lio_sam/feature/cloud_surface`` / ``cloud_corner`` → surf/corner counts for stats + variable tokens.
  - ``/lio_sam/mapping/odometry_incremental`` → odom rate, velocity magnitudes, pose dropout detection (> ``dropout_thresh``).
  - ``/imu/data_raw`` → angular/linear RMS.
  - ``/lio_sam/params/mapping_surf_leaf_size`` → captures latest action to echo into observations.
- **Services**:
  - ``/rl_metrics/reset`` resets all Welford accumulators and history deques (scan/surf/corner/vel) so each episode starts clean.
  - ``/rl_metrics/commit`` creates ``/tmp/rlvo/metrics.json`` (overridable via ``~out_file``) containing:
    - Scalar stats: means/stds, odom/scan rates, pose dropouts, jolt, planarity ratio, IMU RMS, ``action_last``.
    - ``variable_tokens``: downsampled time-aligned triples ``[surf_pts, corner_pts, vel_norm]`` up to ``max_tokens``.
    - ``variable_tokens_n`` and ``token_feature_names`` metadata.
    - ``critique_tail``: four derived features that duplicate high-level signals for the policy tail encoder.
- **Implementation notes**: Stats use Welford accumulators (`Welford` dataclass) for numerical stability. Velocity history is capped (``deque``) to prevent unbounded memory.

## Observation Construction (``rl_vo/env/rl_env.py``)
- ``_fixed_keys`` (16 entries) align with metrics dict keys; missing values default to 0. ``action_last`` ensures the policy sees previous action.
- ``variable_tokens`` are padded/truncated to ``max_tokens`` × ``variable_feature_dim`` and flattened.
- ``critique_tail`` falls back to derived values if exporter did not provide enough entries.
- ``RunningMeanStdLite`` (per env) normalises the concatenated tensor; RMS snapshots can be restored via ``policy_path``.

## Reward and Validation Signals
- ``env/utils/ape.py`` computes RMSE over the last ``score_win_s`` seconds comparing ``est_tum`` (written by ``odom_to_tum.py``) with GT TUM logs.
- Reward formula (simplified): ``0.1 * (-APE) - 0.001*runtime_s - 0.01*|a - last_a|``. If GT is missing (env fallback) or ``variable_tokens_n == 0``, ``valid_mask`` is False so PPO can skip the sample.
- ``EpisodeOrchestrator`` ensures ``metrics.json`` is populated (``_wait_for_metrics_ready``) after restarting actors so the first observations already include real stats.

## Logging and Artifacts
- **Metrics JSON**: Written at ``paths.run_root`` (default ``/tmp/rlvo``). ``EpisodeOrchestrator`` streams logs for each process (``roslaunch.log``, ``file_player.log``, ``lio_stack.log``) to the same directory for debugging.
- **TUM files**: ``est_tum`` path (default ``/tmp/est.tum``) is overwritten every episode; ground-truth files are expected under ``<mulran.root>/<SEQ>/<SEQ>_gt.tum``.
- **Training logs**: ``train.py`` writes wandb runs under ``<log_path>/<group>/<timestamp_tag>`` when ``wandb_logging`` is enabled; otherwise only PPO checkpoints/diagnostics land under ``log_path``.
- **Hydra configs**: Each run records its resolved config in ``rl_vo/outputs/<timestamp>/.hydra/config.yaml`` for reproducibility.

## Metrics Consumption by RL
1. ``EpisodeOrchestrator.commit_metrics`` calls ``/rl_metrics/commit`` (rosbridge service) and reads the JSON file.
2. ``RLBatchedEnv._obs_from_stats`` converts JSON to NumPy arrays, normalises them, and caches as ``_last_obs``.
3. ``valid_mask`` indicates whether the observation included real stats/GT; PPO training ignores invalid transitions to avoid corrupting rollouts.
4. Info dict returned from ``step`` includes ``ape_rmse``, ``leaf`` applied, ``seq`` name, and ``done_reason`` to aid debugging or evaluation scripts.

## Rosbridge Explorer / Instrumentation Notes
- There is no standalone "rosbridge explorer" package; rosbridge interaction is encapsulated by ``env/rosbridge_client.py`` which publishes Float32 parameters and calls Trigger services over WebSocket.
- ``MockRosbridge`` (used during ``DRY_RUN``) prints actions to stdout and synthesises metrics JSON/GT files, enabling deterministic dry tests without ROS.
