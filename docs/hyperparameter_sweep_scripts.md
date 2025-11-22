# Hyperparameter Sweep Scripts

This note documents how the Bash entry points (`run_sweep.sh` and `run_eval_ros1.sh`) work, which helper utilities they rely on, and where each stage writes data during a sweep.

## `run_sweep.sh`

### Configuration and dependencies
- Located at the repo root. It assumes `yq` v4, `python3`, `rospack`, and `run_eval_ros1.sh` are on `PATH`.
- Key environment variables (with defaults):
  - `RUNNER=./run_eval_ros1.sh`
  - `OUT_ROOT=/output/results_v8`
  - `SEQ="KAIST01"`, `RATE=1.0`, `DUR=300`, `FULL_SEQ=0`
  - `REPS=${REPS:-10}` replicates per configuration
  - `SWEEP_ID=${SWEEP_ID:-$(date +%Y%m%d-%H%M%S)_${SEQ}_ofat}`
  - `BASE_YAML=$(rospack find lio_sam)/config/params_mulran.yaml`
- Parameter arrays (`ODOM_SURF`, `MAP_CORNER`, `MAP_SURF`, `EDGE_MIN`, `SURF_MIN`, `EDGE_THR`, `SURF_THR`) capture the candidates listed in [hyperparameter_sweep_overview.md](hyperparameter_sweep_overview.md).
- `default_from_array()` picks the middle entry from each array so baseline runs always use a realistic value, and optional overrides (e.g., `OD_BASE=0.4`) are respected.

### Control flow
1. **Baseline replicates**: Builds a `BASE_LABEL` that records every knob (`BASE_od0.5_mc0.325_…`) and calls `do_run` once, which in turn launches `run_eval_ros1.sh` `REPS` times for the baseline tuple.
2. **OFAT loops**: Each succeeding `for` loop injects a single parameter value and calls `do_run` again. The helper:
   - Copies the baseline YAML into `mktemp` output.
   - Uses `yq` to edit `.lio_sam.*` keys according to the args.
   - Calls `RUNNER` with `-s`, `-r`, either `-t` or `-F`, `-o`, and `-P` pointing to the temp file plus a structured `-L`abel (sanitised via `sanitize_label`).
   - Deletes the temp file once `run_eval_ros1.sh` exits.
3. **Error handling**: Each `RUNNER` invocation is guarded with `|| true` so a failed ROS run does not halt the remainder of the sweep. The failure is captured downstream through missing APE values.
4. **Aggregation**: After all loops complete, the embedded Python block:
   - Reads `${OUT_ROOT}/logs/results_v2.csv`.
   - Filters by `sweep_id`.
   - Groups by `[seq, rate, duration_s, full_seq, odom_surf_leaf, …, surf_threshold]`.
   - Computes `mean/std` columns for `ape_rmse_m`, `ape_sse`, `rpe_trans_1m_rmse_m`, `rpe_trans_1s_rmse_m`, `rpe_rot_1s_rmse_deg`.
   - Writes `${OUT_ROOT}/logs/results_v2_${SWEEP_ID}_avg.csv` (per-sweep) and updates `${OUT_ROOT}/logs/results_v2_avg.csv` (rolling) before printing the paths for convenience.

## `run_eval_ros1.sh`

### CLI surface
- `-s` sequence, `-r` playback rate, `-t` duration, `-F` for full-sequence mode, `-o` output root, `-d` odom topic, `-G` GT TUM root, `-p` `odom_to_tum.py`, `-P` params YAML, `-L` label.
- Expects MulRan data under `/data/mulran/<SEQ>` and GT TUM under `/output/gts/<SEQ>_gt.tum`. These defaults match the Docker volume layout.
- Validates toolchain availability (`roslaunch`, `rosrun`, `rosbag`, `evo_ape`, `python3`, `yq`).

### Runtime stages
1. **Initialisation**:
   - Computes `PARAM_HASH` (first eight characters of the YAML’s SHA1) so runs using the same parameter file can be grouped.
   - Generates `run_base=<SEQ>_<label>_<hash>_<timestamp>` and points `RUN_DIR` to `${OUT_ROOT}/logs/${run_base}` (or `${OUT_ROOT}/runs/...` when using the Python wrapper). Bags land under `${OUT_ROOT}/bags/`.
   - Creates `results_v2.csv` with a header if it does not exist.
   - Installs a `cleanup` trap so rogue ROS processes are killed on exit.
2. **Launch SC-LIO-SAM** (`roslaunch lio_sam run_mulran.launch use_sim_time:=true [params_file]`) and tee logs into `${RUN_DIR}/sc_lio.log`. Dumps `/lio_sam` parameters to `${RUN_DIR}/lio_sam_params.yaml` and copies the injected YAML to `${RUN_DIR}/params_injected.yaml`.
3. **Start the MulRan player** (`rosrun file_player file_player_headless --dir ... --rate ...`). When `FULL_SEQ=0`, the command is wrapped in `timeout DURATION`.
4. **Record odometry** with `rosbag record ${ODOM_TOPIC} -O ${EST_BAG}`. Fixed-duration runs include a slack window (`DURATION + RECORD_SLACK`) to make sure the bag finishes writing.
5. **Write TUM trajectories** by running `python3 -u /odom_to_tum.py --topic ${ODOM_TOPIC} --out ${EST_TUM}` in the background. Logs go to `${RUN_DIR}/odom_to_tum.log`.
6. **Shutdown and finalise**:
   - Wait for the player to exit, terminate SC-LIO-SAM, stop `rosbag` (reindex `.bag.active` files if needed), and kill `odom_to_tum.py`.
   - Verify `${EST_TUM}` exists and is non-empty, otherwise mark the run as `no_tum`.
7. **Run evo metrics**:
   - `evo_ape tum GT EST -va --save_results ${RUN_DIR}/ape.zip --save_plot ${RUN_DIR}/ape.png`.
   - `evo_rpe` for translation (1 m and 1 s) and rotation (1 s), each writing ZIPs and PNGs plus stdout logs for simple parsing.
   - Extract RMSE/SSE by scanning the logs for `rmse`/`sse`.
8. **Record metadata**:
   - Read back the effective parameters from either the injected YAML, the rosparam dump, or the run-time parameter file.
   - Assemble `${RUN_DIR}/metrics.json` (status, timing, metric scalars, leaf sizes, and file paths) and append the same dictionary to `${OUT_ROOT}/logs/results.jsonl`.
   - Append the CSV row to `${OUT_ROOT}/logs/results_v2.csv` regardless of success to preserve bookkeeping.
   - Echo a short summary with pointers to the log folder, `.bag`, `.tum`, and evo artifacts.

### Helper utilities invoked
- **MulRan player**: `file_player_headless` inside `file_player_mulran` streams `/os1_points`, IMU, GPS, and `/clock`. The sweep scripts rely on the headless binary only; GUI tests live under `file_player_mulran/tests`.
- **`odom_to_tum.py`**: Converts `/lio_sam/mapping/odometry_incremental` messages into TUM format. It is bundled at the repo root so no external dependencies are required.
- **`helpers/aggregate_evo_results.py`**: Optional helper to flatten historical `metrics.json` files or JSONL logs back into CSV if a sweep ran before `results_v2.csv` existed.
- **`helpers/evo_graph_suite.py`**: Consumes `results_v2.csv` or the aggregated CSV to generate scatter plots, heatmaps, and Spearman correlation bar charts (see [hyperparameter_sweep_spearman_analysis.md](hyperparameter_sweep_spearman_analysis.md)).

Together, these scripts supply reproducible, per-run metrics that can be stacked into the correlation studies used to pick `mappingSurfLeafSize` as the RL control knob.
