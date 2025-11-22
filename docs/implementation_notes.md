# Implementation Notes & Assumptions

## Design Choices
- **Persistent ROS core**: ``EpisodeOrchestrator`` never tears down the ``core.launch`` (rosbridge + metrics exporter). Only the LIO stack, ``odom_to_tum``, and file player are recycled per episode, drastically reducing startup latency while preserving deterministic resets.
- **External control plane**: RL code never joins the ROS graph. All interactions happen through rosbridge WebSocket calls (`publish_float`, `call_service`), which keeps the training process portable (can run on bare metal, containers, or even mock mode).
- **Log-space action scaling**: ``action_to_leaf`` converts bounded actions into real voxel sizes logarithmically to give PPO higher resolution at small leaf sizes without violating SC-LIO-SAM's stability constraints (``LEAF_MIN``/``LEAF_MAX``).
- **File-based metric exchange**: Rather than streaming statistics over ROS topics, ``metrics_exporter`` writes JSON to disk. ``EpisodeOrchestrator`` synchronously triggers writes via services so RL always reads coherent snapshots.

## Assumptions
- MulRan dataset directories follow ``<mulran.root>/<SEQ>`` with GT TUM files named ``<SEQ>_gt.tum``. If not, rewards drop to zero because the env falls back to ``est_tum``.
- ROS 1 environment already has ``rosbridge_server``, ``metric_pkg``, ``file_player_mulran``, and ``lio_sam`` built + discoverable via ``roslaunch``. ``EpisodeOrchestrator._preflight_checks`` only warns when binaries/launch files are missing.
- The "rosbridge explorer" mentioned in project goals is represented by ``env/rosbridge_client.py`` + ``MockRosbridge``; no GUI explorer is bundled.

## Limitations / TODOs
- Only ``mapping_surf_leaf_size`` is tuned online. Extending RL control to other SC-LIO-SAM parameters would require exposing additional ROS params/topics and updating ``metrics_exporter`` to log them.
- ``RosbridgeClient`` currently lacks automatic reconnect logic; if rosbridge restarts mid-episode the orchestrator marks ``_ros_down`` and restarts everything rather than retrying the socket.
- ``metric_pkg`` writes a single JSON file; concurrent readers/writers are coordinated by services but there's no file-locking. Corruption is unlikely yet possible if external tools touch ``metrics.json``.
- Rewards depend on evo-compatible GT files. When GT is missing the env silently sets ``valid_mask=False``; additional alerts or dataset validation could prevent silent training plateaus.
- ``MockRosbridge`` only logs actions; it does not simulate SC-LIO-SAM dynamics, so policies trained in dry-run mode won't transfer.
