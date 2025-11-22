# Hyperparameter Sweep Overview

## Purpose and Context
- `run_sweep.sh` orchestrates one-factor-at-a-time (OFAT) replicates over SC-LIO-SAM parameters before any reinforcement learning took control. Each sweep keeps MulRan playback, SC-LIO-SAM, and the evaluation tooling identical so we can isolate how a single knob affects APE/RPE.
- Every configuration is executed via `run_eval_ros1.sh`, which launches MulRan’s headless player, SC-LIO-SAM, rosbag recorders, `odom_to_tum.py`, and `evo`. Each run appends one row to `/output/results_v8/logs/results_v2.csv`, captures logs under `/output/results_v8/logs/<run_base>/`, and writes `metrics.json` plus `.tum` files. A complete example lives under `output/results_v8/runs/KAIST01_base_6acbdfa7_20250927-124543/`.
- Replicates (`REPS=10` by default) reduce stochasticity from real-time ROS timing. After the sweep, the script aggregates per-configuration mean/std into `results_v2_<SWEEP_ID>_avg.csv` and a rolling `results_v2_avg.csv`. These tables feed the downstream correlation analysis.

## Hyperparameters Covered
The Bash arrays inside `run_sweep.sh` enumerate every knob that was explored. Baseline values default to the middle entry of each list, but can be overridden via environment variables such as `OD_BASE=0.5`.

| Parameter (YAML key) | Script variable | Default sweep values | Notes |
| --- | --- | --- | --- |
| `lio_sam.odometrySurfLeafSize` | `ODOM_SURF` | `0.4 0.5 0.6 0.65 0.7` | Front-end surf downsampling during odometry. |
| `lio_sam.mappingCornerLeafSize` | `MAP_CORNER` | `0.25 0.3 0.325 0.35 0.375` | Corner voxel grid for the map-optimization stage. |
| `lio_sam.mappingSurfLeafSize` | `MAP_SURF` | `0.4 0.5 0.55 0.6 0.65 0.7` | Surf voxel grid; later chosen as the RL control variable. |
| `lio_sam.edgeFeatureMinValidNum` | `EDGE_MIN` | `20` | Minimum valid edge features. |
| `lio_sam.surfFeatureMinValidNum` | `SURF_MIN` | `100` | Minimum valid surf features. |
| `lio_sam.edgeThreshold` | `EDGE_THR` | `1.0` | Curvature threshold when classifying corners. |
| `lio_sam.surfThreshold` | `SURF_THR` | `0.10` | Curvature threshold when classifying surf points. |

Each loop in `run_sweep.sh` skips the baseline value to avoid duplicate work; `sanitize_label()` turns the configuration tuple into a filesystem-safe label (periods become `p`).

## Sweep Pipeline
1. **Baseline replicates**: The script copies `$(rospack find lio_sam)/config/params_mulran.yaml` into a temp file, injects the baseline values via `yq`, and runs `run_eval_ros1.sh` `REPS` times.
2. **One-factor sweeps**: `do_run()` is invoked once per candidate value for each parameter, keeping the other knobs locked at their baseline. Every call spawns MulRan playback, SC-LIO-SAM, rosbag recording, `odom_to_tum.py`, and `evo_*` to produce per-run metrics.
3. **Per-run storage**: Each run receives a unique `run_base = <SEQ>_<LABEL>_<PARAM_HASH>_<timestamp>` that names the folders, `.bag`, and `.tum` files under `/output/results_v8/`.
4. **Aggregation**: After all runs, the embedded Python block reads `/output/results_v8/logs/results_v2.csv`, filters by `sweep_id`, and writes mean/std summaries (`results_v2_<SWEEP_ID>_avg.csv` and `results_v2_avg.csv`).
5. **Correlation prep**: The tidy CSV (per-run or averaged) is later consumed by `helpers/evo_graph_suite.py`, which plots scatter series, parameter-conditioned medians, and Spearman correlation bar charts.
6. **Selection**: The RL stack ultimately modulates `mappingSurfLeafSize` via `/lio_sam/params/mapping_surf_leaf_size` (`docs/slam_and_dependencies.md`). Even when Spearman analysis (e.g., `santiago_thesis/Chapter3/spearman_correlations.png`) highlighted both `mappingCornerLeafSize` and `mappingSurfLeafSize`, only the surf leaf size exposes a runtime ROS hook, so it became the RL action.

## Mermaid Pipeline Diagram
```mermaid
graph LR
    MulRan --> SC_LIO_SAM
    SC_LIO_SAM --> Metrics
    Metrics --> Logs
    Logs -->|run_eval_ros1.sh| Evo
    Evo --> APE_Results
    APE_Results --> SpearmanAnalysis
    SpearmanAnalysis --> HyperparameterSelection
```

Refer to the companion documents for implementation specifics:
- [`docs/hyperparameter_sweep_scripts.md`](hyperparameter_sweep_scripts.md) – shell script walkthroughs.
- [`docs/hyperparameter_sweep_dataflow.md`](hyperparameter_sweep_dataflow.md) – file- and folder-level flow.
- [`docs/hyperparameter_sweep_spearman_analysis.md`](hyperparameter_sweep_spearman_analysis.md) – plotting and correlation tooling.
