#!/usr/bin/env bash
#
# Evaluate SC-LIO-SAM on a MulRan sequence using the headless file player,
# then compute APE metrics with evo.  Designed for reproducible, unattended runs.
#
# Author: <you>
#

set -euo pipefail

### ──────────────────────────────── configurable defaults ─────────────────────
SEQ="KAIST01"                         # MulRan sequence folder name
SEQ_ROOT="/data/mulran"               # Where MulRan sequences live
RATE=1.0                              # Playback rate (1× realtime)
DURATION=60                           # Seconds to run player/SLAM
OUT_ROOT="/output"                    # Top-level folder for logs & bags
### ────────────────────────────────────────────────────────────────────────────

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Options:
  -s  SEQ         MulRan sequence name   (default: $SEQ)
  -r  RATE        Player rate            (default: $RATE)
  -t  SECONDS     Evaluation duration    (default: $DURATION)
  -o  DIR         Output root directory  (default: $OUT_ROOT)
  -h              Show this help
EOF
}

while getopts ":s:r:t:o:h" opt; do
  case ${opt} in
    s) SEQ=${OPTARG}        ;;
    r) RATE=${OPTARG}       ;;
    t) DURATION=${OPTARG}   ;;
    o) OUT_ROOT=${OPTARG}   ;;
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
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

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
SEQ_DIR="${SEQ_ROOT}/${SEQ}"
echo "🚀  [2/5] Playing MulRan sequence from ${SEQ_DIR} at ${RATE}× for ${DURATION}s…"
timeout --preserve-status ${DURATION} \
  rosrun file_player file_player_headless --dir "$SEQ_DIR" --rate "$RATE" \
  > >(tee "${RUN_DIR}/player.log") 2>&1 &
PIDS+=($!)
PLAYER_PID=$!
echo "[DEBUG] Player PID: $PLAYER_PID"

###############################################################################
# 3) Record ground-truth & odometry for the whole duration (+5 s slack)
###############################################################################
echo "📦  [3/5] Recording /gt and /sc_lio_sam/mapping/odometry → ${EST_BAG}"
rosbag record /lio_sam/mapping/odometry \
  --duration=$((${DURATION}+5)) \
  -O "$EST_BAG" \
  > "${RUN_DIR}/record.log" 2>&1 &
PIDS+=($!)
RECORD_PID=$!
echo "[DEBUG] Record PID: $RECORD_PID"

###############################################################################
# 4) Block until player exits (i.e. timeout reached)
###############################################################################
wait "$PLAYER_PID" || true
echo "[INFO] Player finished – stopping SLAM & recorder"

# Explicitly kill SLAM now; recorder will exit after its --duration
kill "$SLAM_PID" 2>/dev/null || true

# Wait for rosbag record’s natural exit; safety kill after 3 s
for i in {1..3}; do
  if ! ps -p "$RECORD_PID" > /dev/null; then break; fi
  sleep 1
done
kill -9 "$RECORD_PID" 2>/dev/null || true

###############################################################################
# 5) Evaluate with evo_ape
###############################################################################
echo "📊  [5/5] Computing APE with evo…"
evo_ape bag "${EST_BAG}" /gt /sc_lio_sam/mapping/odometry \
  -va --save_results "${RUN_DIR}/ape.zip" --save_plot "${RUN_DIR}/ape.png" \
  > "${RUN_DIR}/evo.log" 2>&1

echo ""
echo "✅  Evaluation completed"
echo "📝  Logs    → ${RUN_DIR}"
echo "📦  Bag     → ${EST_BAG}"
echo "📊  APE     → ${RUN_DIR}/ape.{zip,png}"
