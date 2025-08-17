#!/usr/bin/env bash
#
# Evaluate SC-LIO-SAM on a MulRan sequence using the headless file player,
# then compute APE metrics with evo. Designed for reproducible, unattended runs.
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

# Topics to record/evaluate
GT_TOPIC="/gt"
ODOM_TOPIC="/lio_sam/mapping/odometry"

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
  -g  TOPIC       Ground-truth topic           (default: $GT_TOPIC)
  -d  TOPIC       Odometry topic               (default: $ODOM_TOPIC)
  -h              Show this help
EOF
}

while getopts ":s:r:t:o:g:d:h" opt; do
  case ${opt} in
    s) SEQ=${OPTARG}        ;;
    r) RATE=${OPTARG}       ;;
    t) DURATION=${OPTARG}   ;;
    o) OUT_ROOT=${OPTARG}   ;;
    g) GT_TOPIC=${OPTARG}   ;;
    d) ODOM_TOPIC=${OPTARG} ;;
    h) usage; exit 0        ;;
    \?) echo "Invalid option: -$OPTARG" >&2; usage; exit 1 ;;
  esac
done

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
RUN_DIR="${OUT_ROOT}/logs/${SEQ}_${TIMESTAMP}"
BAG_DIR="${OUT_ROOT}/bags"
EST_BAG="${BAG_DIR}/${SEQ}_est_${TIMESTAMP}.bag"

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
      # Try graceful first
      kill "$pid" 2>/dev/null || true
      sleep 1
      # Then force if still around (avoid if already reaped)
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
command -v rosrun >/dev/null 2>&1 || { echo "[ERROR] rosrun not found"; exit 1; }
command -v rosbag >/dev/null 2>&1 || { echo "[ERROR] rosbag not found"; exit 1; }
command -v evo_ape >/dev/null 2>&1 || { echo "[ERROR] evo_ape not found"; exit 1; }

###############################################################################
# 1) Launch SC-LIO-SAM (this starts roscore implicitly)
###############################################################################
echo "🧠  [1/5] Launching SC-LIO-SAM…"
roslaunch lio_sam run_mulran.launch use_sim_time:=true \
  > >(tee "${RUN_DIR}/sc_lio.log") 2>&1 &
PIDS+=($!)
SLAM_PID=$!
sleep 5   # ensure ROS core + SLAM node are alive
echo "[DEBUG] SLAM PID: $SLAM_PID"

###############################################################################
# 2) Start headless MulRan player (bounded runtime via timeout)
###############################################################################
echo "🚀  [2/5] Playing MulRan sequence from ${SEQ_DIR} at ${RATE}× for ${DURATION}s…"
timeout --preserve-status ${DURATION} \
  rosrun file_player file_player_headless --dir "$SEQ_DIR" --rate "$RATE" \
  > >(tee "${RUN_DIR}/player.log") 2>&1 &
PIDS+=($!)
PLAYER_PID=$!
echo "[DEBUG] Player PID: $PLAYER_PID"

###############################################################################
# 3) Record ground-truth & odometry for the whole duration (+ slack)
###############################################################################
RECORD_SECS=$((DURATION + RECORD_SLACK))
echo "📦  [3/5] Recording ${GT_TOPIC} and ${ODOM_TOPIC} → ${EST_BAG} (${RECORD_SECS}s)…"
rosbag record "${GT_TOPIC}" "${ODOM_TOPIC}" \
  --duration=${RECORD_SECS} \
  -O "$EST_BAG" \
  > "${RUN_DIR}/record.log" 2>&1 &
PIDS+=($!)
RECORD_PID=$!
echo "[DEBUG] Record PID: $RECORD_PID"

###############################################################################
# 4) Block until player exits, then stop SLAM and wait for recorder to finalize
###############################################################################
wait "$PLAYER_PID" || true
echo "[INFO] Player finished – stopping SLAM & waiting for recorder…"

# Politely stop SLAM; recorder will stop on its own via --duration
kill "$SLAM_PID" 2>/dev/null || true

echo "[INFO] Waiting for recorder to finalize the bag…"
if ! wait "$RECORD_PID"; then
  echo "[WARN] Recorder did not exit cleanly (see ${RUN_DIR}/record.log)."
fi

# If rosbag was interrupted or slow to close, the file may be *.bag.active
if [ -f "${EST_BAG}.active" ] && [ ! -f "${EST_BAG}" ]; then
  echo "[INFO] Found active bag; attempting to finalize…"
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
  echo "[ERROR] Expected bag not found: ${EST_BAG}"
  echo "        Check ${RUN_DIR}/record.log and ${RUN_DIR}/record_reindex.log (if present)."
  exit 2
fi

###############################################################################
# 5) Evaluate with evo_ape
###############################################################################
echo "📊  [5/5] Computing APE with evo…"
evo_ape bag "${EST_BAG}" "${GT_TOPIC}" "${ODOM_TOPIC}" \
  -va --save_results "${RUN_DIR}/ape.zip" --save_plot "${RUN_DIR}/ape.png" \
  > "${RUN_DIR}/evo.log" 2>&1 || {
    echo "[ERROR] evo_ape failed – see ${RUN_DIR}/evo.log"
    exit 3
  }

echo ""
echo "✅  Evaluation completed"
echo "📝  Logs    → ${RUN_DIR}"
echo "📦  Bag     → ${EST_BAG}"
echo "📊  APE     → ${RUN_DIR}/ape.{zip,png}"
