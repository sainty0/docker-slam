#!/usr/bin/env bash
#
# Evaluate SC-LIO-SAM on a MulRan sequence using the headless file player,
# export odometry to TUM via /odom_to_tum.py, then compute APE with evo.
#
# ROS1 version.
#

set -euo pipefail

### ──────────────────────────────── configurable defaults ─────────────────────
SEQ="KAIST01"                         # MulRan sequence folder name
SEQ_ROOT="/data/mulran"               # Where MulRan sequences live
RATE=1.0                              # Playback rate (1× realtime)
DURATION=60                           # Seconds to run player/SLAM
OUT_ROOT="/output"                    # Top-level folder for logs & bags

# Topics / files
ODOM_TOPIC="/lio_sam/mapping/odometry"
GT_TUM_ROOT="/output/gts"             # Folder containing <SEQ>_gt.tum
ODOM_TO_TUM="/odom_to_tum.py"         # Path to your converter script

# Extra seconds to let rosbag finish cleanly
RECORD_SLACK=10
### ────────────────────────────────────────────────────────────────────────────

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Options:
  -s  SEQ         MulRan sequence name         (default: $SEQ)
  -r  RATE        Player rate                  (default: $RATE)
  -t  SECONDS     Evaluation duration          (default: $DURATION)
  -o  DIR         Output root directory        (default: $OUT_ROOT)
  -d  TOPIC       Odometry topic               (default: $ODOM_TOPIC)
  -G  DIR         GT TUM dir (expects <SEQ>_gt.tum inside) (default: $GT_TUM_ROOT)
  -p  PATH        Path to /odom_to_tum.py      (default: $ODOM_TO_TUM)
  -h              Show this help
EOF
}

while getopts ":s:r:t:o:d:G:p:h" opt; do
  case ${opt} in
    s) SEQ=${OPTARG}        ;;
    r) RATE=${OPTARG}       ;;
    t) DURATION=${OPTARG}   ;;
    o) OUT_ROOT=${OPTARG}   ;;
    d) ODOM_TOPIC=${OPTARG} ;;
    G) GT_TUM_ROOT=${OPTARG};;
    p) ODOM_TO_TUM=${OPTARG};;
    h) usage; exit 0        ;;
    \?) echo "Invalid option: -$OPTARG" >&2; usage; exit 1 ;;
  esac
done

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
RUN_DIR="${OUT_ROOT}/logs/${SEQ}_${TIMESTAMP}"
BAG_DIR="${OUT_ROOT}/bags"
EST_BAG="${BAG_DIR}/${SEQ}_est_${TIMESTAMP}.bag"
EST_TUM="${RUN_DIR}/${SEQ}_est_${TIMESTAMP}.tum"
GT_TUM="${GT_TUM_ROOT}/${SEQ}_gt.tum"

mkdir -p "$RUN_DIR" "$BAG_DIR"

echo "[INFO  $(date +%F' '%T)] Starting evaluation on ${SEQ} for ${DURATION}s"
echo "[INFO] Output directory: $RUN_DIR"

###############################################################################
# Clean-up helper – gets invoked on EXIT, INT or TERM
###############################################################################
PIDS=()
cleanup() {
  echo
  echo "[INFO] Cleaning up…"
  for pid in "${PIDS[@]}"; do
    if ps -p "$pid" > /dev/null 2>&1; then
      kill "$pid" 2>/dev/null || true
      sleep 1
      if ps -p "$pid" > /dev/null 2>&1; then
        kill -9 "$pid" 2>/dev/null || true
      fi
    fi
  done
}
trap cleanup EXIT INT TERM

###############################################################################
# 0) Basic checks
###############################################################################
SEQ_DIR="${SEQ_ROOT}/${SEQ}"
if [ ! -d "$SEQ_DIR" ]; then
  echo "[ERROR] Sequence directory not found: ${SEQ_DIR}"
  exit 1
fi
command -v roslaunch >/dev/null 2>&1 || { echo "[ERROR] roslaunch not found"; exit 1; }
command -v rosrun   >/dev/null 2>&1 || { echo "[ERROR] rosrun not found"; exit 1; }
command -v rosbag   >/dev/null 2>&1 || { echo "[ERROR] rosbag not found"; exit 1; }
command -v evo_ape  >/dev/null 2>&1 || { echo "[ERROR] evo_ape not found"; exit 1; }
command -v python3  >/dev/null 2>&1 || { echo "[ERROR] python3 not found"; exit 1; }

if [ ! -f "$ODOM_TO_TUM" ]; then
  echo "[ERROR] odom_to_tum.py not found at: $ODOM_TO_TUM"
  exit 1
fi
if [ ! -f "$GT_TUM" ]; then
  echo "[ERROR] GT TUM not found at: $GT_TUM"
  echo "        Provide ${SEQ}_gt.tum in ${GT_TUM_ROOT} or use -G to point to the dir."
  exit 1
fi

###############################################################################
# 1) Launch SC-LIO-SAM (this starts roscore implicitly)
###############################################################################
echo "🧠  [1/6] Launching SC-LIO-SAM…"
roslaunch lio_sam run_mulran.launch use_sim_time:=true \
  > >(tee "${RUN_DIR}/sc_lio.log") 2>&1 &
PIDS+=($!)
SLAM_PID=$!
sleep 5
echo "[DEBUG] SLAM PID: $SLAM_PID"

###############################################################################
# 2) Start headless MulRan player (bounded runtime via timeout)
###############################################################################
echo "🚀  [2/6] Playing MulRan sequence from ${SEQ_DIR} at ${RATE}× for ${DURATION}s…"
timeout --preserve-status ${DURATION} \
  rosrun file_player file_player_headless --dir "$SEQ_DIR" --rate "$RATE" \
  > >(tee "${RUN_DIR}/player.log") 2>&1 &
PIDS+=($!)
PLAYER_PID=$!
echo "[DEBUG] Player PID: $PLAYER_PID"

###############################################################################
# 3) Record odometry bag for the whole duration (+ slack)
###############################################################################
RECORD_SECS=$((DURATION + RECORD_SLACK))
echo "📦  [3/6] Recording ${ODOM_TOPIC} → ${EST_BAG} (${RECORD_SECS}s)…"
rosbag record "${ODOM_TOPIC}" \
  --duration=${RECORD_SECS} \
  -O "$EST_BAG" \
  > "${RUN_DIR}/record.log" 2>&1 &
PIDS+=($!)
RECORD_PID=$!
echo "[DEBUG] Record PID: $RECORD_PID"

###############################################################################
# 4) Start odom_to_tum.py to write the estimate TUM concurrently
###############################################################################
echo "📝  [4/6] Writing TUM from ${ODOM_TOPIC} → ${EST_TUM}"
python3 -u "${ODOM_TO_TUM}" --topic "${ODOM_TOPIC}" --out "${EST_TUM}" \
  > "${RUN_DIR}/odom_to_tum.log" 2>&1 &
PIDS+=($!)
ODOM2TUM_PID=$!
echo "[DEBUG] odom_to_tum.py PID: $ODOM2TUM_PID"

###############################################################################
# 5) Wait for player; stop SLAM; allow recorder and odom_to_tum to finalize
###############################################################################
wait "$PLAYER_PID" || true
echo "[INFO] Player finished – stopping SLAM & waiting for tools…"

# Politely stop SLAM
kill "$SLAM_PID" 2>/dev/null || true

echo "[INFO] Waiting for rosbag recorder to finalize…"
if ! wait "$RECORD_PID"; then
  echo "[WARN] Recorder did not exit cleanly (see ${RUN_DIR}/record.log)."
fi

echo "[INFO] Stopping odom_to_tum.py…"
# Try graceful stop; the script traps SIGINT/SIGTERM and closes the file
kill "$ODOM2TUM_PID" 2>/dev/null || true
for i in {1..5}; do
  if ! ps -p "$ODOM2TUM_PID" > /dev/null; then break; fi
  sleep 1
done
if ps -p "$ODOM2TUM_PID" > /dev/null; then
  echo "[WARN] Forcing odom_to_tum.py to exit."
  kill -9 "$ODOM2TUM_PID" 2>/dev/null || true
fi

# Finalize a possible *.bag.active
if [ -f "${EST_BAG}.active" ] && [ ! -f "${EST_BAG}" ]; then
  echo "[INFO] Finalizing active bag…"
  set +e
  rosbag reindex "${EST_BAG}.active" >> "${RUN_DIR}/record_reindex.log" 2>&1
  REINDEX_RC=$?
  set -e
  if [ $REINDEX_RC -ne 0 ]; then
    echo "[WARN] rosbag reindex failed, falling back to rename."
    mv "${EST_BAG}.active" "${EST_BAG}"
  fi
fi

if [ ! -f "${EST_BAG}" ]; then
  echo "[WARN] Bag not found: ${EST_BAG} (continuing; TUM path may still be valid)"
fi

if [ ! -s "${EST_TUM}" ]; then
  echo "[ERROR] Expected TUM not found or empty: ${EST_TUM}"
  echo "        Check ${RUN_DIR}/odom_to_tum.log."
  exit 2
fi

###############################################################################
# 6) Evaluate with evo (APE + RPE)
###############################################################################
echo "📊  [6/6] Evaluating with evo (GT=${GT_TUM}, EST=${EST_TUM})…"

# --- Absolute Pose Error (global drift / consistency) ---
evo_ape tum "${GT_TUM}" "${EST_TUM}" \
  -va --save_results "${RUN_DIR}/ape.zip" --save_plot "${RUN_DIR}/ape.png" \
  > "${RUN_DIR}/evo_ape.log" 2>&1 || {
    echo "[ERROR] evo_ape failed – see ${RUN_DIR}/evo_ape.log"
}

# --- Relative Pose Error: translational drift every 1m travelled ---
evo_rpe tum "${GT_TUM}" "${EST_TUM}" \
  -va -r trans_part --delta 1 --delta_unit m \
  --save_results "${RUN_DIR}/rpe_trans_1m.zip" \
  --save_plot "${RUN_DIR}/rpe_trans_1m.png" \
  > "${RUN_DIR}/evo_rpe_trans_1m.log" 2>&1 || {
    echo "[ERROR] evo_rpe (trans/1m) failed – see ${RUN_DIR}/evo_rpe_trans_1m.log"
}

# --- Relative Pose Error: translational drift every 1s ---
evo_rpe tum "${GT_TUM}" "${EST_TUM}" \
  -va -r trans_part --delta 1 --delta_unit s \
  --save_results "${RUN_DIR}/rpe_trans_1s.zip" \
  --save_plot "${RUN_DIR}/rpe_trans_1s.png" \
  > "${RUN_DIR}/evo_rpe_trans_1s.log" 2>&1 || {
    echo "[ERROR] evo_rpe (trans/1s) failed – see ${RUN_DIR}/evo_rpe_trans_1s.log"
}

# --- Relative Pose Error: rotational drift every 1s ---
evo_rpe tum "${GT_TUM}" "${EST_TUM}" \
  -va -r angle_deg --delta 1 --delta_unit s \
  --save_results "${RUN_DIR}/rpe_rot_1s.zip" \
  --save_plot "${RUN_DIR}/rpe_rot_1s.png" \
  > "${RUN_DIR}/evo_rpe_rot_1s.log" 2>&1 || {
    echo "[ERROR] evo_rpe (rot/1s) failed – see ${RUN_DIR}/evo_rpe_rot_1s.log"
}


echo ""
echo "✅  Evaluation completed"
echo "📝  Logs    → ${RUN_DIR}"
echo "📦  Bag     → ${EST_BAG}"
echo "🧾  EST TUM → ${EST_TUM}"
echo "🎯  GT  TUM → ${GT_TUM}"
echo "📊  APE     → ${RUN_DIR}/ape.{zip,png}"
