# SLAM Stack and Dependencies

## SC-LIO-SAM Integration
- **Package location**: ``SC-LIO-SAM/SC-LIO-SAM`` contains the ROS1 package built around ``mapOptimization`` (``src/mapOptmization.cpp``), ScanContext loop closure, IMU/GPS fusion, and ROS publishers/subscribers defined across ``launch``/``config``.
- **Launch orchestration**: ``rl_vo/launch/lio_stack.launch`` loads MulRan parameters (``$(find lio_sam)/config/params_mulran.yaml``) and starts the LOAM front-end, robot_state_publisher, and navsat chain. ``EpisodeOrchestrator`` respawns this launch file at every RL episode to ensure state resets while rosbridge/metrics stay alive.
- **Runtime parameter hook**: ``mapOptimization`` subscribes to ``lio_sam/params/mapping_surf_leaf_size`` (`SC-LIO-SAM/SC-LIO-SAM/src/mapOptmization.cpp:232`), invoking ``mappingSurfLeafSizeHandler`` (`lines 610-628`). When RL publishes a positive Float32 value, the handler locks the main mutex, updates ``mappingSurfLeafSize``, and reconfigures ``downSizeFilterSurf`` + ``downSizeFilterICP`` before logging the change. Invalid (≤0) updates are ignored with a warning.
- **Outputs**: ``mapOptimization`` publishes ``/lio_sam/mapping/odometry_incremental`` (incremental odometry), ``/lio_sam/mapping/path`` (nav_msgs/Path), and feature clouds consumed both by downstream modules and ``metric_pkg``.
- **Loop closure augmentation**: ScanContext loop closure additions (``performSCLoopClosure`` etc.) remain untouched; RL only modulates surf voxel size.
- **Deep dives**: [sc_lio_sam_hyperparameters.md](sc_lio_sam_hyperparameters.md) enumerates every configurable knob, and [sc_lio_sam_topics.md](sc_lio_sam_topics.md) maps all publishers/subscribers plus their RL relevance.

## GTSAM Dependency
- **Location**: ``gtsam`` submodule houses the full C++ GTSAM library, including ISAM2, IMU factors, geometry primitives, and third-party dependencies (Eigen, GeographicLib). SC-LIO-SAM compiles against this tree.
- **Usage**: ``mapOptimization`` constructs ``NonlinearFactorGraph``/``Values`` objects, adds IMU/GPS/loop-closure factors, and triggers ``ISAM2`` updates each scan. RL-driven parameter changes influence the density of surf features entering this graph, indirectly affecting factor conditioning and optimization cadence.
- **Build**: Dockerfiles (``Dockerfile.gtsam*``) set up toolchains for compiling GTSAM + SC-LIO-SAM. No RL-specific changes are made to GTSAM; it is treated as a vendor dependency.

## Runtime Data Dependencies
- **MulRan sequences**: Configured via ``config/config.yaml`` (``mulran.root`` + ``mulran.seqs``). ``EpisodeOrchestrator`` picks a sequence/start percent and invokes ``file_player_headless --dir <seq> --start-percent <p>``.
- **Ground truth**: ``RLBatchedEnv._resolve_gt_path`` expects ``<mulran.root>/<SEQ>/<SEQ>_gt.tum``; if missing and ``DRY_RUN`` is not set, it falls back to ``est_tum`` (reward becomes zero). In dry-run mode it writes synthetic GT files for integration testing.
- **Odometry export**: ``odom_to_tum.py`` subscribes to ``/lio_sam/mapping/odometry_incremental`` and writes ``est.tum`` that ``env/utils/ape.py`` consumes when computing rewards.

## Interaction with RL Controls
1. PPO outputs scalar ``a∈[0,1]`` → ``action_to_leaf`` transforms it logarithmically into ``leaf∈[5e-4, 1.0]`` meters.
2. ``EpisodeOrchestrator.set_leaf`` publishes ``leaf`` to ``/lio_sam/params/mapping_surf_leaf_size`` via rosbridge; SC-LIO-SAM's handler reconfigures voxel grids immediately.
3. ``rl_metrics_exporter`` is subscribed to the same topic solely to log ``action_last`` in ``metrics.json``, letting the environment feed previous action back to the policy.
4. Adjusting ``mappingSurfLeafSize`` changes downsample density, which influences surf feature counts (observed in metrics) and ultimately pose quality (observed as APE in rewards).

## Assumptions & Gaps
- ``rosbridge explorer`` referenced in the project overview is represented here by ``env/rosbridge_client.py`` and the rosbridge server launched in ``core.launch``; no standalone explorer package exists in the repo.
- Only ``mapping_surf_leaf_size`` is tuned at runtime. ``SC-LIO-SAM`` exposes other parameters (e.g., ``mapping_corner_leaf``), but no ROS topics or dynamic reconfigure hooks are wired for them yet.
