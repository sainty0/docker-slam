# Hyperparameter Sweep Spearman Analysis

This document explains how per-run metrics from `run_eval_ros1.sh` are transformed into scatter plots, parameter-conditioned summaries, and Spearman correlation graphs that guided the decision to let RL control `mappingSurfLeafSize`.

## Data Inputs
- **Primary CSV**: `/output/results_v8/logs/results_v2.csv` accumulates every run triggered by `run_sweep.sh`. Each row records raw APE/RPE values plus the exact parameter tuple used.
- **Aggregated CSVs**: `/output/results_v8/logs/results_v2_<SWEEP_ID>_avg.csv` (current sweep) and `/output/results_v8/logs/results_v2_avg.csv` (rolling) contain `mean/std` columns per configuration. These are ideal when the per-run replicates exhibit large variance.
- **Alternative sources**:
  - `helpers/aggregate_evo_results.py` can rebuild a tidy CSV directly from `${OUT_ROOT}/logs/*/metrics.json` or `results.jsonl`.
  - The Python runner in `mulran_eval/storage.py` writes Parquet tables (`/output/tables/{runs,metrics}.parquet`) that can be converted back to CSV with `pyarrow.parquet`.

## Processing Workflow (`helpers/evo_graph_suite.py`)
1. **Invocation**  
   ```bash
   python3 helpers/evo_graph_suite.py \
     --csv /output/results_v8/logs/results_v2.csv \
     --out /output/results_v8/graphs \
     --metric ape_rmse_m \
     --where "full_seq==0 and rate==1.0" \
     --param-cols "odom_surf_leaf,mapping_corner_leaf,mapping_surf_leaf,edge_min_valid,surf_min_valid,edge_threshold,surf_threshold"
   ```
   - `--where` filters out full-sequence runs or unusual rates so the comparisons stay apples-to-apples.
   - `--param-cols` is optional; omitted columns are auto-detected from known SC-LIO-SAM knobs.
2. **Overview tables**  
   - `tables/dataset_overview.txt` summarises row counts, sweep IDs, and the distinct values observed for each parameter.
   - `tables/top_runs.csv` lists the best-performing runs for the chosen metric.
3. **Per-parameter analysis**  
   - `per_param_global/<param>.png` shows medians ± std across the entire dataset.  
   - `per_param_global/<param>__raw_scatter.png` visualises every run as a jittered scatter plot.
   - `per_param/param=<p>/<group>/plot.png` focuses on “control groups” where all other parameters match, making the causal effect easier to see.
4. **Pairwise medians**  
   - `heatmaps/<a>__vs__<b>.png` charts the median metric for manageable grid sizes to reveal interactions (e.g., surf vs. corner leaf sizes).
5. **Spearman correlations**  
   - `tables/param_spearman_correlations.csv` contains a signed Spearman coefficient per parameter. Values closer to ±1 indicate strong monotonic relationships with the metric.  
   - `correlations/spearman_correlations.png` is a horizontal bar chart ranking each parameter by absolute correlation magnitude.  
   - These results mirror the plot reproduced in `santiago_thesis/Chapter3/spearman_correlations.png`, which compares the three most sensitive parameters.

## Interpreting the Results
- The OFAT sweeps highlighted that the voxel-leaf parameters (`mappingCornerLeafSize`, `mappingSurfLeafSize`, and to a lesser extent `odometrySurfLeafSize`) had the highest absolute Spearman correlations with APE. This matches the textual description in `santiago_thesis/Chapter3/Methodology.tex`, where these knobs were the focus of the hyper-parameter study.
- Even when `mappingCornerLeafSize` ranked slightly higher in correlation magnitude, only `mappingSurfLeafSize` exposes a runtime ROS topic (`/lio_sam/params/mapping_surf_leaf_size`) as documented in `docs/slam_and_dependencies.md`. Corner leaf size requires editing the YAML and relaunching SC-LIO-SAM, which is infeasible inside the RL control loop.
- Consequently, the Spearman workflow served two purposes:
  1. **Quantitative triage** – validating that voxel-density knobs dominate APE sensitivity while thresholds (`edgeThreshold`, `surfThreshold`) and minimum feature counts play secondary roles within the tested ranges.
  2. **Action selection** – justifying why the RL stack modulates `mappingSurfLeafSize` despite `mappingCornerLeafSize` also showing strong correlations.

## Example Outputs and Locations
- `output/results_v8/graphs/tables/param_spearman_correlations.csv` – CSV ready for spreadsheets or thesis plots.
- `output/results_v8/graphs/correlations/spearman_correlations.png` – bar chart embedded in presentations/thesis (`santiago_thesis/Chapter3/spearman_correlations.png` is one such instance).
- `output/results_v8/graphs/per_param_global/mappingSurfLeafSize.png` – median/std view that informed the safe operating range used in RL training (`action_to_leaf` clips to `[5e-4, 1.0]` m but rewards were tuned around the range that performed best in the sweeps).

## From Correlations to RL Control
1. Run `./run_sweep.sh` (or the Typer equivalent in `mulran_eval/cli.py`) to populate `results_v2.csv`.
2. Generate Spearman plots with `helpers/evo_graph_suite.py`.
3. Confirm that the candidate parameter not only correlates strongly with APE but also has a runtime hook. For this project, `mappingSurfLeafSize` satisfied both conditions.
4. Feed that decision back into the RL stack: `RLBatchedEnv` publishes Float32 values on `/lio_sam/params/mapping_surf_leaf_size`, `metric_pkg` echoes `action_last`, and the reward loop measures improvements through APE.

These steps close the loop from offline sweeps → evo metrics → Spearman correlations → RL action design.
