# Module Overview

## Changelog
- 2025-11-16 – Added explicit references to `run_eval_ros1.sh` / `run_sweep.sh` so the evaluation stack matches the actual scripts in this repository (the previously documented Python wrapper no longer exists).

## Top-Level Layout
| Path | Description |
| --- | --- |
| ``rl_vo`` | RL training package: Hydra config, custom PPO, ROS-aware batched environment, launch files for rosbridge + SC-LIO-SAM. |
| ``SC-LIO-SAM/SC-LIO-SAM`` | Fork of SC-LIO-SAM ROS1 package built on GTSAM; includes ``mapOptimization`` node that exposes runtime leaf-size updates. |
| ``gtsam`` | Upstream GTSAM dependency (C++ factor graph library) vendored as a submodule. |
| ``file_player_mulran`` | ROS package that replays MulRan sequences (GUI + headless binaries). The RL system uses ``file_player_headless``. |
| ``metric_pkg`` | Simple ROS1 package that exports ``metrics_exporter.py`` node and Trigger services for RL observations. |
| ``run_eval_ros1.sh`` / ``run_sweep.sh`` | Bash entry points used for individual evaluations and OFAT sweeps. They launch MulRan playback, SC-LIO-SAM, evo metrics, and write CSV logs; see `docs/hyperparameter_sweep_scripts.md`. |
| ``helpers`` | Offline evaluation and plotting scripts (``evo_graph_suite.py``, ``aggregate_evo_results.py``) that post-process `results_v2*.csv`. |
| ``mulran``, ``mulran_eval`` | Dataset helpers and evaluation notebooks/scripts for MulRan benchmarks. |
| ``odom_to_tum.py`` | Standalone ROS utility that records odometry to TUM format for evo-based scoring. |
| ``docs`` | Generated documentation (this folder). |
| ``Dockerfile*``, ``docker-compose.yml`` | Container recipes for building gtsam base images and SC-LIO-SAM runtime. |

## ROS Packages and Launchables
| Package | Nodes / Launch | Notes |
| --- | --- | --- |
| ``SC-LIO-SAM`` | ``mapOptmization``, ``imuPreintegration``, ``transformFusion`` etc via ``lio_stack.launch`` | Primary SLAM backend; ``mapOptmization`` subscribes to ``lio_sam/params/mapping_surf_leaf_size`` for RL tuning. |
| ``metric_pkg`` | ``metrics_exporter.py`` | Provides ``/rl_metrics/reset`` and ``/rl_metrics/commit`` services plus JSON file output. |
| ``file_player_mulran`` | ``file_player_headless`` | Streams MulRan logs to ROS topics; accepts ``--start-percent`` from orchestrator. |
| ``rosbridge_server`` | ``rosbridge_websocket`` | Bridges RL process to ROS graph. Configured in ``rl_vo/launch/core.launch``. |
| ``rl_vo`` (launch assets) | ``core.launch``, ``lio_stack.launch`` | ``core`` is persistent infrastructure; ``lio_stack`` is relaunched each episode by ``EpisodeOrchestrator``. |

## Python Modules
| Module | Key Files | Purpose |
| --- | --- | --- |
| RL entrypoint | ``rl_vo/train.py`` | Hydra-configured PPO training script; builds ``RLBatchedEnv`` for SC-LIO-SAM. |
| Environment orchestration | ``rl_vo/env/rl_env.py``, ``env/episode_orchestrator.py`` | Maintains ROS processes, converts metrics to observations, computes rewards, publishes ``surf_leaf_size`` actions. |
| Rosbridge interface | ``rl_vo/env/rosbridge_client.py`` | Minimal WebSocket client used by orchestrator and env to call services/publish floats. |
| PPO implementation | ``rl_vo/rl_algorithms/*.py`` | Lightweight fork of SB3 PPO with wandb hooks. |
| Metrics handling | ``metric_pkg/scripts/metrics_exporter.py`` | ROS node that aggregates statistics and writes JSON consumed by the environment. |
| Evaluation utilities | ``helpers/*.py``, ``mulran_global_pose_to_tum.py`` | Offline dataset conversion, evaluation sweeps, plotting. |

## Key Files and Responsibilities
| File | Responsibility |
| --- | --- |
| ``rl_vo/train.py`` | Seeds RNGs, instantiates ``RLBatchedEnv``/validation env, configures ``CustomActorCriticPolicy``, creates PPO agent, handles checkpoint restores, runs ``model.learn``. |
| ``rl_vo/env/rl_env.py`` | Defines ``RLBatchedEnv`` (VecEnv) that normalises stats, tracks step horizon, converts PPO actions to physical leaf sizes, and interfaces with ``EpisodeOrchestrator``. |
| ``rl_vo/env/episode_orchestrator.py`` | Spawns ``roslaunch`` for core + LIO stack, restarts file player + ``odom_to_tum`` each episode, calls rosbridge services, and streams metrics/logs. |
| ``rl_vo/env/rosbridge_client.py`` | WebSocket-based helper for publishing ``std_msgs/Float32`` and calling Trigger services via rosbridge. |
| ``metric_pkg/scripts/metrics_exporter.py`` | Subscribes to point clouds, odometry, IMU topics; computes mean/std + "variable tokens"; serves reset/commit services and writes ``metrics.json``. |
| ``file_player_mulran/src/headless_player.cpp`` | Headless MulRan player node used in training; publishes `/clock`, `/os1_points`, `/imu/data_raw`, `/gps/fix`, `/radar/polar`. |
| ``SC-LIO-SAM/SC-LIO-SAM/src/mapOptmization.cpp`` | Houses ``mapOptimization`` class, publishes odometry, subscribes to ``lio_sam/params/mapping_surf_leaf_size`` to reconfigure voxel filters at runtime. |
| ``odom_to_tum.py`` | Converts ``nav_msgs/Odometry`` to TUM trajectories consumed by ``env/utils/ape.py`` for reward computation. |
