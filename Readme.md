docker compose exec sc-lio bash

python3 mulran_global_pose_to_tum.py \
  --in ~/Downloads/mulran/Riverside01/global_pose.csv \
  --out ~/docker-slam/output/gts/Riverside01_gt.tum \
  --timestamp-unit ns \
  --offset-origin \
  --enforce-orthonormal


  python3 /helpers/evo_graph_suite.py \
  --csv /output/results_v7/logs/results_v2.csv \
  --out /output/results_v7/graphs \
  --metric ape_rmse_m \
  --where "full_seq==0 and rate==1.0" \
  --per-param-groups 12 \
  --max-heatmaps 8 \
  --param-cols "odom_surf_leaf,mapping_corner_leaf,mapping_surf_leaf,edge_min_valid,surf_min_valid,edge_threshold,surf_threshold"

  python3 /helpers/evo_graph_suite.py \
  --csv /output/results_v6/logs/results_v2_avg.csv \
  --out /output/results_v6/graphs \
  --metric ape_rmse_m_mean \
  --where "full_seq==0 and rate==1.0" \
  --per-param-groups 12 \
  --max-heatmaps 8 \
  --param-cols "odom_surf_leaf,mapping_corner_leaf,mapping_surf_leaf,edge_min_valid,surf_min_valid,edge_threshold,surf_threshold"