# Training Loop (``rl_vo/train.py``)

## Purpose
``train.py`` is the single entrypoint for PPO-based policy training against SC-LIO-SAM. It:
1. Loads Hydra config (``rl_vo/config/config.yaml`` by default).
2. Builds one training ``RLBatchedEnv`` and a smaller validation ``RLBatchedEnv`` that share the same ROS orchestration code.
3. Creates a ``CustomActorCriticPolicy`` with attention-based encoder sized to the environment's fixed/variable observation layout.
4. Instantiates the local PPO implementation (``rl_vo/rl_algorithms/ppo.py``) with wandb-aware logging.
5. Optionally restores running statistics/policy weights, then trains until ``total_timesteps`` or interruption.

## Execution Flow
1. **Hydra bootstrap** (`rl_vo/train.py:22-25`): Decorated ``main`` resolves configs and initialises PyTorch thread pools.
2. **Environment selection** (`rl_vo/train.py:26-49`): For ``vo_algorithm == "SCLSAM"`` it instantiates training/validation ``RLBatchedEnv`` with `mock_rosbridge` derived from ``DRY_RUN``. Validation env inherits config but honours ``config.eval.sequences`` overrides.
3. **Policy config** (`rl_vo/train.py:50-63`): Encoder kwargs query runtime dims exposed by the env (``agent_obs_dim_fixed``, ``agent_obs_dim_variable``, ``critique_dim``). ``CustomActorCriticPolicy`` receives SB3-compatible kwargs (ReLU activations, two 256-unit layers for policy/value heads).
4. **Seeding & logging** (`rl_vo/train.py:67-86`): ``configure_random_seed`` seeds NumPy, PyTorch, and env RNGs. Logging directories depend on wandb toggles.
5. **Device & RMS restore** (`rl_vo/train.py:87-98`): Chooses CUDA if present and reloads observation running-mean/std snapshots when ``policy_path`` is provided.
6. **PPO instantiation** (`rl_vo/train.py:99-123`): Wires env, policy, SB3 hyperparameters, and a linear LR schedule (``get_linear_fn(3e-4, 3e-5, 1.0)``). Adds wandb metadata.
7. **Policy restore** (`rl_vo/train.py:125-129`): If ``policy_path`` exists, loads ``state_dict`` and places policy on the selected device.
8. **Learning & teardown** (`rl_vo/train.py:131-147``): Calls ``model.learn`` with training/validation envs and evaluation interval, catches ``KeyboardInterrupt``, and ensures ``env.close()``/``val_env.close()`` run.

## Environment Details (``rl_vo/env/rl_env.py``)
- **Observation structure**: concatenation of 16 fixed stats (point counts, rates, IMU RMS, previous action), up to ``max_tokens``×``variable_feature_dim`` "tokens" (surf/corner/velocity aligned on scan timestamps), and ``critique_dim`` tail features (odom rate, dropouts, scan rate, mean points). ``RunningMeanStdLite`` normalises the full vector.
- **Action mapping**: ``action_to_leaf`` logarithmically maps PPO scalar actions (0–1) into physical voxel sizes ``[5e-4, 1.0]`` meters before publishing to ``/lio_sam/params/mapping_surf_leaf_size``.
- **Reward**: After each ``step_len_s`` tick, RL env computes APE RMSE (``env/utils/ape.py``) between ``est_tum`` (from ``odom_to_tum.py``) and MulRan GT ``<seq>/<seq>_gt.tum`` over the last ``score_win_s`` seconds. Reward combines negative scaled APE, runtime penalty, and action-smoothness penalty.
- **Episode orchestration**: ``EpisodeOrchestrator`` handles all ROS subprocesses. ``reset()`` picks a random MulRan sequence and start percent, restarts ``file_player_headless`` + SC-LIO-SAM + ``odom_to_tum``, issues ``/rl_metrics/reset``, and waits for metrics readiness.
- **Metrics ingestion**: ``commit_metrics()`` triggers ``/rl_metrics/commit`` via rosbridge, reads ``/tmp/rlvo/metrics.json``, builds observations, and sets a ``valid_mask`` bit so PPO ignores steps without GT or stats. RMS updates are deferred until valid stats arrive.

## RL-Specific References
- [RL-VO Overview](rl_vo_overview.md) — high-level wiring between SC-LIO-SAM, rosbridge, PPO, and the attention encoder.
- [RL Attention Encoder](rl_vo_attention.md) — explains how fixed stats, variable tokens, and the critique tail are processed.
- [RL PPO Implementation](rl_vo_ppo.md) — loss terms, hyperparameters, and how ROS-specific masks feed into optimisation.
- [RL Rollout Buffer](rl_vo_buffer.md) — storage layout for masked transitions.
- [RL Training Loop](rl_vo_training_loop.md) — step-by-step breakdown of the ROS-driven interaction cycle.

## ROS & External Interfaces
- **Rosbridge** (``rl_vo/env/rosbridge_client.py``): ``RosbridgeClient.publish_float`` sends Float32 actions; ``call_service`` drives ``/rl_metrics/reset``/``commit`` with retry/timeout logic.
- **Services used**: ``/rl_metrics/reset`` clears exporter state on episode start; ``/rl_metrics/commit`` flushes metrics to JSON each step.
- **Topics published**: Only ``/lio_sam/params/mapping_surf_leaf_size`` (Float32). ``EpisodeOrchestrator`` ensures SC-LIO-SAM subscribes via ``mapOptimization::mappingSurfLeafSizeHandler``.
- **Artifacts**: ``est_tum`` path (from ``paths.est_tum``) is overwritten by ``odom_to_tum.py`` each episode; Hydra ``log_path`` collects PPO checkpoints and optional wandb runs.

## Validation Path
``val_env`` mirrors the training env but typically runs with fewer parallel copies (`min(4, n_envs)`). ``model.learn`` receives both ``eval_interval`` and ``val_env`` so PPO periodically pauses training to gather metrics on held-out sequences via the same ROS orchestration.

## Failure Handling
- ``EpisodeOrchestrator`` monitors ROS process groups; if ``rosbridge`` or ``file_player`` die, ``step()`` flags ``done`` and immediately restarts actors without destroying the persistent core.
- ``MockRosbridge`` mode (``DRY_RUN=1``) generates synthetic metrics, writes fake GT, and logs actions without hitting ROS — useful for integration tests of ``train.py``.
