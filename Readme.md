# Docker SLAM Evaluation Toolkit

This repository provides a reproducible environment to evaluate SC-LIO-SAM on MulRan sequences, export odometry to TUM format, compute APE/RPE with evo, and run one-factor-at-a-time (OFAT) parameter sweeps with replicates.

The original shell scripts have been converted and refactored into a modular Python package under `scripts/eval_sweep/`. A thin wrapper (`scripts/eval_sweep.py`) is kept for backward compatibility.

- Single-run evaluator (replacement for `run_eval_ros1.sh`)
- OFAT sweep with replicates and optional parallel workers (replacement for `run_sweep.sh`)

## Setup 
### Clone Repo
- git clone --recurse-submodules -b ros2 https://github.com/sainty0/docker-slam.git
- cd docker-slam
- git submodule update --init --recursive

### Setup X11

**For Mac**
Follow this guide: https://gist.github.com/devnoname120/ce02ef43da968e15340427c2f1c286a7

```
# Run this once per login (or put it in a small script)
export DISPLAY=:0
# Install socat if you don’t have it: brew install socat
socat TCP-LISTEN:6000,reuseaddr,fork UNIX-CLIENT:"$DISPLAY"

```
### Build Docker
- docker compose build gtsam-base
- docker compose build sc-lio

## Quickstart

### Start a shell in the container
```bash
# For linux 
docker compose --profile linux run --rm sc-lio-linux
# For mac
docker compose --profile mac run --rm sc-lio-mac
# or attach to a running one
docker compose exec sc-lio bash
```

### Ensure MulRan data and GT
- Place MulRan sequences under `/data/mulran/<SEQ>` (inside the container).
- Ensure a GT TUM file exists at `/output/gts/<SEQ>_gt.tum`.

If you have MulRan global pose CSV, you can convert to TUM format with:
```bash
python3 mulran_global_pose_to_tum.py \
  --in ~/Downloads/mulran/Riverside01/global_pose.csv \
  --out ~/docker-slam/output/gts/Riverside01_gt.tum \
  --timestamp-unit ns \
  --offset-origin \
  --enforce-orthonormal
```


## New Python CLI

You can run either via the wrapper or as a module:
- Wrapper: `python3 scripts/eval_sweep.py ...`
- Module:  `python3 -m scripts.eval_sweep ...`

Show help:
```bash
python3 scripts/eval_sweep.py --help
python3 -m scripts.eval_sweep --help
```

### Single evaluation (replacement for `run_eval_ros1.sh`)
Runs SC-LIO-SAM + headless player + rosbag recorder + odom_to_tum, then evaluates with evo and writes metrics.

Example (fixed-duration):
```bash
python3 -m scripts.eval_sweep eval \
  -s KAIST01 \
  --seq-root /data/mulran \
  -r 1.0 \
  -t 160 \
  -o /output \
  -d /lio_sam/mapping/odometry \
  -G /output/gts \
  -p odom_to_tum.py \
  -P $(rospack find lio_sam)/config/params_mulran.yaml \
  -L base
```

Full-sequence mode:
```bash
python3 -m scripts.eval_sweep eval \
  -s KAIST01 -F \
  -o /output \
  -P /path/to/params.yaml \
  -L full
```

Key outputs:
- Per-run logs and artifacts: `/output/logs/<SEQ>_<label>_<param_hash>_<timestamp>/`
- Estimated bag: `/output/bags/<SEQ>_<label>_<param_hash>_<timestamp>.bag`
- Estimated TUM: `<run_dir>/<...>.tum`
- metrics.json: `<run_dir>/metrics.json`
- CSV append: `/output/logs/results_v2.csv`
- JSONL append: `/output/logs/results.jsonl`

Notes:
- `--seq-root` defaults to `/data/mulran`
- `--gt-tum-root` defaults to `/output/gts` and expects `<SEQ>_gt.tum`
- `-P/--params-file` injects YAML parameters into the launch (recommended)


### OFAT Sweep (replacement for `run_sweep.sh`)
Runs a baseline configuration `REPS` times, then varies each parameter across a list while keeping others at baseline, again with replicates. Aggregates per-configuration mean/std into per-sweep and rolling CSVs.

Sequential example:
```bash
python3 -m scripts.eval_sweep sweep \
  --base-yaml $(rospack find lio_sam)/config/params_mulran.yaml \
  -s Riverside01 \
  -r 1.0 \
  -t 300 \
  --reps 10 \
  --workers 1 \
  --out-root /output/results_v8
```

Parallel workers example:
```bash
python3 -m scripts.eval_sweep sweep \
  --base-yaml $(rospack find lio_sam)/config/params_mulran.yaml \
  -s Riverside01 \
  -r 1.0 \
  -t 300 \
  --reps 10 \
  --workers 4 \
  --out-root /output/results_v8
```

Aggregation outputs (requires pandas):
- Per-sweep: `/output/results_v8/logs/results_v2_<SWEEP_ID>_avg.csv`
- Rolling:    `/output/results_v8/logs/results_v2_avg.csv` (dedupes current sweep)

Parameter lists and baselines can be overridden. Defaults:
- `--odometry-surf "0.4 0.5 0.6 0.65 0.7"`
- `--mapping-corner "0.25 0.3 0.325 0.35 0.375"`
- `--mapping-surf "0.4 0.5 0.55 0.6 0.65 0.7"`
- `--edge-min "20"`
- `--surf-min "100"`
- `--edge-thr "1.0"`
- `--surf-thr "0.10"`
- Baseline picks the middle item from each list unless an explicit `--*-base` is provided.

Important: ROS concurrency
- Each eval launches `roslaunch` and typically a ROS master. Running multiple evals on a single host can conflict.
- Use `--workers 1` locally, or isolate each worker (separate containers/VMs) before raising `--workers`.


## Plotting and Analysis

The helper below can generate plots from the per-run CSV or aggregated CSV. Adjust `--csv` and `--out` paths to your run.

From per-run CSV:
```bash
python3 /helpers/evo_graph_suite.py \
  --csv /output/results_v7/logs/results_v2.csv \
  --out /output/results_v7/graphs \
  --metric ape_rmse_m \
  --where "full_seq==0 and rate==1.0" \
  --per-param-groups 12 \
  --max-heatmaps 8 \
  --param-cols "odom_surf_leaf,mapping_corner_leaf,mapping_surf_leaf,edge_min_valid,surf_min_valid,edge_threshold,surf_threshold"
```

From aggregated CSV:
```bash
python3 /helpers/evo_graph_suite.py \
  --csv /output/results_v6/logs/results_v2_avg.csv \
  --out /output/results_v6/graphs \
  --metric ape_rmse_m_mean \
  --where "full_seq==0 and rate==1.0" \
  --per-param-groups 12 \
  --max-heatmaps 8 \
  --param-cols "odom_surf_leaf,mapping_corner_leaf,mapping_surf_leaf,edge_min_valid,surf_min_valid,edge_threshold,surf_threshold"
```


## MulRan File Player: Stepper and Seek Tests (with visualization)

Two helper test scripts are provided to validate and visually inspect the MulRan file player behavior. They can optionally launch SC-LIO-SAM (via roslaunch) and RViz so you can watch playback while the test runs.

Location:
- file_player_mulran/tests/step_test.py
- file_player_mulran/tests/start_percent_test.py

Prerequisites
- Build and source your ROS workspace so these are available on PATH:
  - roslaunch lio_sam run_mulran.launch
  - rosrun file_player file_player_headless
  - rosrun rviz rviz
- MulRan sequence available under /data/mulran/<SEQ> (or pass your actual path via --dir)
- Optional: an RViz config file if you want a preset layout

Player capabilities referenced
- Stepper mode (play N data stamps and stop): headless binary accepts --step N
- Seek to percentage before starting: headless binary accepts --start-percent P (0..100)

Examples
1) Functional stepper test (no visualization)
- Verifies that at least N messages are published across key topics when stepping:
  python3 file_player_mulran/tests/step_test.py --dir /data/mulran/KAIST01 --step 5 --timeout 30

2) Visual stepper test (launch SC-LIO-SAM + RViz)
- Launches SLAM and RViz and keeps them running for 20s while stepping:
```
  python3 file_player_mulran/tests/step_test.py \
    --dir /data/mulran/KAIST01 \
    --step 50 \
    --with-slam \
    --params-file SC-LIO-SAM/SC-LIO-SAM/config/params_mulran.yaml \
    --with-rviz \
    --rviz-config SC-LIO-SAM/SC-LIO-SAM/doc/rviz/rviz.rviz \
    --visualize-seconds 20
```
3) Functional seek-to-percent test (no visualization)
- Seeks to 25% and publishes one stamp, then checks stamp against data_stamp.csv:
  python3 file_player_mulran/tests/start_percent_test.py \
    --dir /data/mulran/KAIST01 \
    --pct 25 \
    --timeout 30

4) Visual seek-to-percent test (continuous playback)
- Seeks to 25%, keeps playing for 30s while SLAM + RViz run:
  python3 file_player_mulran/tests/start_percent_test.py \
    --dir /data/mulran/KAIST01 \
    --pct 25 \
    --with-slam \
    --with-rviz \
    --visualize-seconds 30 \
    --keep-playing

Integrated visual test launcher
- A single script that launches SC-LIO-SAM (roslaunch), waits for the ROS master, starts RViz, and launches the headless file player; then validates either steps or start-percent. This helps avoid "master not running yet" issues.

Examples:
- Step 50 entries with visualization for 20s:
  python3 file_player_mulran/tests/visual_integration_test.py \
    --dir /data/mulran/KAIST01 \
    --step 50 \
    --params-file SC-LIO-SAM/SC-LIO-SAM/config/params_mulran.yaml \
    --rviz-config SC-LIO-SAM/SC-LIO-SAM/doc/rviz/rviz.rviz \
    --visualize-seconds 20

- If you still see "master not running", start a private roscore first:
  python3 file_player_mulran/tests/visual_integration_test.py \
    --dir /data/mulran/KAIST01 \
    --step 50 \
    --params-file SC-LIO-SAM/SC-LIO-SAM/config/params_mulran.yaml \
    --rviz-config SC-LIO-SAM/SC-LIO-SAM/doc/rviz/rviz.rviz \
    --visualize-seconds 20 \
    --roscore-first

- Seek to 25% and keep playing for 30s:
  python3 file_player_mulran/tests/visual_integration_test.py \
    --dir /data/mulran/KAIST01 \
    --pct 25 \
    --keep-playing \
    --params-file SC-LIO-SAM/SC-LIO-SAM/config/params_mulran.yaml \
    --rviz-config SC-LIO-SAM/SC-LIO-SAM/doc/rviz/rviz.rviz \
    --visualize-seconds 30

Manual headless examples
- Start at 25% and play continuously:
  rosrun file_player file_player_headless --dir /data/mulran/KAIST01 --rate 1.0 --start-percent 25

- Step 10 entries (data_stamp entries) and exit:
  rosrun file_player file_player_headless --dir /data/mulran/KAIST01 --rate 1.0 --step 10

Notes
- When using --with-slam, roslaunch starts roscore; otherwise scripts start/stop a private roscore.
- --params-file injects YAML into run_mulran.launch (e.g., SC-LIO-SAM/SC-LIO-SAM/config/params_mulran.yaml).
- You can omit --rviz-config to use the default RViz layout.

## Dependencies

Runtime (inside container):
- ROS Noetic CLI tools: `roslaunch`, `rosrun`, `rosbag`
- evo: `evo_ape`, `evo_rpe`
- Python 3

Python packages:
- Required: `PyYAML` (for parameter injection)
- Optional: `pandas` (for aggregation)
```bash
pip install pyyaml pandas
```

Data:
- MulRan sequences under `/data/mulran/<SEQ>`
- GT TUM file at `/output/gts/<SEQ>_gt.tum` (see conversion example above)


## Outputs Summary

- Per run:
  - Run directory: `/output/logs/<SEQ>_<label>_<param_hash>_<timestamp>/`
  - APE plot/results: `ape.png`, `ape.zip`
  - RPE plots/results: `rpe_trans_1m.{png,zip}`, `rpe_trans_1s.{png,zip}`, `rpe_rot_1s.{png,zip}`
  - `metrics.json`, `odom_to_tum.log`, `record.log`, `player.log`, `sc_lio.log`
- Global logs:
  - `/output/logs/results_v2.csv` (per-run rows)
  - `/output/logs/results.jsonl` (per-run JSON lines)
  - Aggregation (sweep only): `results_v2_<SWEEP_ID>_avg.csv`, `results_v2_avg.csv`


## Backward Compatibility

The original entrypoint `scripts/eval_sweep.py` remains as a thin wrapper forwarding to the package CLI. You can use:
- `python3 scripts/eval_sweep.py eval ...`
- `python3 -m scripts.eval_sweep eval ...`


## Appendix: Sample Parameter Dump (ROS)
Below is an example parameter dump for reference:
```
PARAMETERS
 * /ekf_gps/base_link_frame: base_link
 * /ekf_gps/frequency: 50
 * /ekf_gps/imu0: imu_correct
 * /ekf_gps/imu0_config: [False, False, Fa...
 * /ekf_gps/imu0_differential: False
 * /ekf_gps/imu0_queue_size: 50
 * /ekf_gps/imu0_remove_gravitational_acceleration: True
 * /ekf_gps/map_frame: map
 * /ekf_gps/odom0: odometry/gps
 * /ekf_gps/odom0_config: [True, True, True...
 * /ekf_gps/odom0_differential: False
 * /ekf_gps/odom0_queue_size: 10
 * /ekf_gps/odom_frame: odom
 * /ekf_gps/process_noise_covariance: [1.0, 0, 0, 0, 0,...
 * /ekf_gps/publish_tf: False
 * /ekf_gps/sensor_timeout: 0.01
 * /ekf_gps/two_d_mode: False
 * /ekf_gps/world_frame: odom
 * /lio_sam/Horizon_SCAN: 1024
 * /lio_sam/N_SCAN: 64
 * /lio_sam/baselinkFrame: base_link
 * /lio_sam/downsampleRate: 1
 * /lio_sam/edgeFeatureMinValidNum: 20
 * /lio_sam/edgeThreshold: 1.0
 * /lio_sam/extrinsicRPY: [-1, 0, 0, 0, -1,...
 * /lio_sam/extrinsicRot: [-1, 0, 0, 0, -1,...
 * /lio_sam/extrinsicTrans: [1.77, -0.0, -0.05]
 * /lio_sam/globalMapVisualizationLeafSize: 0.2
 * /lio_sam/globalMapVisualizationPoseDensity: 10.0
 * /lio_sam/globalMapVisualizationSearchRadius: 1000.0
 * /lio_sam/gpsCovThreshold: 2.0
 * /lio_sam/gpsTopic: odometry/gpsz
 * /lio_sam/historyKeyframeFitnessScore: 0.3
 * /lio_sam/historyKeyframeSearchNum: 25
 * /lio_sam/historyKeyframeSearchRadius: 15.0
 * /lio_sam/historyKeyframeSearchTimeDiff: 30.0
 * /lio_sam/imuAccBiasN: 0.000643566593535...
 * /lio_sam/imuAccNoise: 9.939570888238808...
 * /lio_sam/imuGravity: 9.80511
 * /lio_sam/imuGyrBiasN: 0.000356403186963...
 * /lio_sam/imuGyrNoise: 5.636343949698187...
 * /lio_sam/imuRPYWeight: 0.01
 * /lio_sam/imuTopic: /imu/data_raw
 * /lio_sam/lidarFrame: base_link
 * /lio_sam/lidarMaxRange: 1000.0
 * /lio_sam/lidarMinRange: 1.0
 * /lio_sam/loopClosureEnableFlag: False
 * /lio_sam/loopClosureFrequency: 1.0
 * /lio_sam/mapFrame: map
 * /lio_sam/mappingCornerLeafSize: 0.35
 * /lio_sam/mappingProcessInterval: 0.15
 * /lio_sam/mappingSurfLeafSize: 0.6
 * /lio_sam/numberOfCores: 4
 * /lio_sam/odomTopic: odometry/imu
 * /lio_sam/odometryFrame: odom
 * /lio_sam/odometrySurfLeafSize: 0.6
 * /lio_sam/pointCloudTopic: /os1_points
 * /lio_sam/poseCovThreshold: 25.0
 * /lio_sam/rotation_tollerance: 1000
 * /lio_sam/savePCD: False
 * /lio_sam/savePCDDirectory: /home/gil/sparoLa...
 * /lio_sam/sensor: mulran
 * /lio_sam/surfFeatureMinValidNum: 100
 * /lio_sam/surfThreshold: 0.1
 * /lio_sam/surroundingKeyframeDensity: 2.0
 * /lio_sam/surroundingKeyframeSearchRadius: 50.0
 * /lio_sam/surroundingKeyframeSize: 50
 * /lio_sam/surroundingkeyframeAddingAngleThreshold: 0.2
 * /lio_sam/surroundingkeyframeAddingDistThreshold: 1.0
 * /lio_sam/useGpsElevation: False
 * /lio_sam/useImuHeadingInitialization: True
 * /lio_sam/z_tollerance: 1000
 * /navsat/broadcast_utm_transform: False
 * /navsat/broadcast_utm_transform_as_parent_frame: False
 * /navsat/delay: 0.0
 * /navsat/frequency: 50
 * /navsat/magnetic_declination_radians: 0
 * /navsat/publish_filtered_gps: False
 * /navsat/wait_for_datum: False
 * /navsat/yaw_offset: 0
 * /navsat/zero_altitude: True
 * /robot_description: <?xml version="1....
 * /rosdistro: noetic
 * /rosversion: 1.17.4
