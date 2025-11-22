# Architecture Overview

## System Goals
- Replay MulRan sequences into SC-LIO-SAM, keep ROS core running, and adapt voxel map parameters on the fly.
- Expose lightweight metrics (point counts, odom rates, IMU stats, dynamic tokens) that summarise SLAM health.
- Train a PPO-based reinforcement learning (RL) policy (``rl_vo/train.py``) that tweaks ``mapping_surf_leaf_size`` via rosbridge using those metrics as observations and APE-based rewards.

## Major Components
| Component | Location | Role |
| --- | --- | --- |
| RL training stack | ``rl_vo`` | Hydra-driven entrypoint (``train.py``), custom PPO policy, batched ROS-aware environment, rosbridge client. |
| Episode orchestrator | ``rl_vo/env/episode_orchestrator.py`` | Keeps ROS core and rosbridge alive, restarts SC-LIO-SAM + file player per episode, coordinates metrics commits, streams logs. |
| ROS core launch | ``rl_vo/launch/core.launch`` | Starts rosbridge server and ``metric_pkg`` exporter once per training job. |
| SC-LIO-SAM | ``SC-LIO-SAM/SC-LIO-SAM`` | Full lidar-inertial SLAM implementation backed by GTSAM; subscribes to runtime ``mappingSurfLeafSize`` updates. |
| MulRan file player | ``file_player_mulran/src/headless_player.cpp`` | Headless ROS node that publishes recorded lidar/IMU/GPS/radar topics at configurable rate and offset. |
| Metrics exporter | ``metric_pkg/scripts/metrics_exporter.py`` | ROS1 node that aggregates low-cost stats and writes ``/tmp/rlvo/metrics.json`` upon ``/rl_metrics/commit``. |
| Metric consumers | ``rl_vo/env/rl_env.py`` | Normalises stats into RL observations, computes APE rewards via ``env/utils/ape.py``, and maps actions to ROS parameter updates. |
| GTSAM | ``gtsam`` submodule | Provides nonlinear factor graph solvers, IMU factors, etc., consumed by SC-LIO-SAM's ``mapOptimization`` node. |
| Support tooling | ``odom_to_tum.py``, ``helpers/*.py`` | Converts odometry to TUM logs, runs evaluations/plots, etc. |

## Detailed SC-LIO-SAM References
- [SC-LIO-SAM Hyperparameters](sc_lio_sam_hyperparameters.md) captures every ROS/YAML parameter, including `mappingSurfLeafSize`, and explains how they map to the C++ nodes.
- [SC-LIO-SAM ROS Interfaces](sc_lio_sam_topics.md) enumerates all publishers/subscribers and highlights which ones the metrics exporter and rosbridge touch.
- [RL Signals from SC-LIO-SAM](rl_signals_from_scliosam.md) traces how observations, rewards, and `surf_leaf_size` actions travel through rosbridge + metrics on each PPO step.
- RL deep dives:
  - [RL-VO Overview](rl_vo_overview.md) summarises the PPO stack, env, and ROS integration points.
  - [RL Attention Encoder](rl_vo_attention.md) details how multi-head attention consumes SC-LIO-SAM metrics.
  - [RL PPO + Buffer + Training Loop](rl_vo_ppo.md), [rl_vo_buffer.md], and [rl_vo_training_loop.md] break down optimisation, storage, and orchestration.

## Episode Lifecycle
1. ``RLBatchedEnv`` builds an ``EpisodeOrchestrator`` using ROS launch/cfg paths from ``config/config.yaml``.
2. ``begin_episode()`` ensures the persistent ``core.launch`` (rosbridge + metrics exporter) is up, then relaunches the SC-LIO-SAM stack, ``odom_to_tum.py`` converter, and ``file_player_headless`` for a random MulRan sequence/start percentage.
3. A ``/rl_metrics/reset`` service call clears exporter accumulators; a safe ``mapping_surf_leaf_size`` is published so SC-LIO-SAM starts stable.
4. Training loop samples an action, ``action_to_leaf()`` log-scales it into meters, and ``EpisodeOrchestrator.set_leaf()`` publishes over rosbridge.
5. ``tick()`` lets SC-LIO-SAM ingest replay data for ``step_len_s`` while ``metrics_exporter`` streams stats to disk.
6. ``commit_metrics()`` triggers ``/rl_metrics/commit`` and reads ``metrics.json`` to update observations; ``ape_rmse`` between ``est.tum`` and GT drives the reward.
7. When MulRan playback ends or comms fail, the orchestrator restarts only the episode actors (player + odom writer + SC-LIO-SAM) while core processes stay alive.

## Training Feedback Loop
```mermaid
graph LR
    Player[file_player_headless] -->|MulRan lidar/IMU/GPS| LIO[SC-LIO-SAM]
    LIO -->|/lio_sam/mapping/odometry_incremental| OdomToTUM[odom_to_tum.py]
    OdomToTUM -->|est.tum| Env[RLBatchedEnv]
    LIO -->|surf/corner clouds + IMU + odom| Metrics[metric_pkg/metrics_exporter]
    Metrics -->|/tmp/rlvo/metrics.json<br/>/rl_metrics/commit| Env
    Env -->|observations| PPO[train.py]
    PPO -->|actions (scalar)| Env
    Env -->|/lio_sam/params/mapping_surf_leaf_size<br/>(rosbridge Float32)| Rosbridge[rosbridge_websocket]
    Rosbridge --> LIO
```

## Processes and Launch Context
- ``rl_vo/launch/core.launch`` is the only long-lived ROS launch; ``EpisodeOrchestrator`` uses ``roslaunch`` CLI directly per process to keep logs under ``run_root``.
- ``rl_vo/launch/lio_stack.launch`` wraps SC-LIO-SAM modules (point cloud odometry, robot_state_publisher, navsat bridge) and loads ``lio_sam`` MulRan parameters.
- ``file_player_headless`` binaries come from the ``file_player_mulran`` package; ``EpisodeOrchestrator`` invokes them headlessly with ``--dir``, ``--rate`` and ``--start-percent``.
- ``rosbridge_client.py`` is the only non-ROS Python dependency—the RL process stays outside ROS graph and interacts purely over WebSocket services/publish calls.

## Deployment Considerations
- Environment variables (``FILE_PLAYER_CMD``, ``ODOM_TO_TUM_CMD``, ``LIO_SAM_LAUNCH_CMD``) let you override binaries without changing code.
- ``EpisodeOrchestrator`` writes per-run logs (``roslaunch.log``, ``lio_stack.log``, ``file_player.log``) and ``metrics.json`` under ``run_root`` to simplify debugging.
- ``MockRosbridge`` mode (``DRY_RUN=1``) allows exercising the RL stack without launching ROS by generating synthetic metrics/GT.
