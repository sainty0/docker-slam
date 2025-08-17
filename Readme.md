docker compose exec sc-lio bash

python3 mulran_global_pose_to_tum.py \
  --in ~/Downloads/mulran/KAIST01/global_pose.csv \
  --out ~/docker-slam/output/gts/KAIST01_gt.tum \
  --timestamp-unit ns \
  --offset-origin \
  --enforce-orthonormal