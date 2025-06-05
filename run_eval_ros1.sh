#!/usr/bin/env bash
set -e

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
SEQ=KAIST01

# ────────────────────────────────────────────────────────────────────────────────
# Paths
# ────────────────────────────────────────────────────────────────────────────────
LOG=/output/logs/${SEQ}_${TIMESTAMP}
EST_BAG=/output/bags/${SEQ}_est_${TIMESTAMP}
INPUT_BAG=/output/KAIST01_input_20250605-093436.bag

mkdir -p "$LOG" /output/bags

echo "[INFO] $(date)  Starting eval for $SEQ" | tee "$LOG/script.log"

#
# 1) Launch SC-LIO-SAM (roslaunch starts roscore internally)
#
echo "🧠 [1/5] Launching SC-LIO-SAM (RViz enabled)…"
roslaunch lio_sam run_mulran.launch use_sim_time:=true \
  > "$LOG/sc_lio.log" 2>&1 &
SLAM_PID=$!
echo "[DEBUG] SC-LIO-SAM PID: $SLAM_PID"
sleep 5  # give SLAM a moment to come up

#
# 2) Play bag (simulated time), capturing real rosbag PID
#
echo "🚀 [2/5] Playing bag: $INPUT_BAG"
# Use process substitution so that $! is truly the rosbag-play PID, not tee
rosbag play "$INPUT_BAG" --clock --rate=1.0 --start=5 \
  > >(tee "$LOG/play.log") 2>&1 &
PLAY_PID=$!
echo "[DEBUG] rosbag play PID: $PLAY_PID"
sleep 2

#
# 3) Start recording the two topics, without --duration
#
echo "📦 [3/5] Recording /gt and /sc_lio_sam/mapping/odometry → ${EST_BAG}.bag"
rosbag record \
  /gt \
  /sc_lio_sam/mapping/odometry \
  -O "${EST_BAG}.bag" \
  > "$LOG/record.log" 2>&1 &
RECORD_PID=$!
echo "[DEBUG] rosbag record PID: $RECORD_PID"

#
# 4) Wait for rosbag play to finish (EOF)
#
wait $PLAY_PID
echo "[INFO] rosbag play has exited (EOF). Now stopping record…"

# Give record a short grace period to flush buffers, then kill it
sleep 1
if ps -p $RECORD_PID > /dev/null 2>&1; then
  echo "[INFO] Killing rosbag record (PID $RECORD_PID)…"
  kill $RECORD_PID
  sleep 2
  kill -9 $RECORD_PID 2>/dev/null || true
fi

#
# 5) Clean up SC-LIO-SAM
#
echo "🛑 [5/5] Stopping SC-LIO-SAM…"
if ps -p $SLAM_PID > /dev/null 2>&1; then
  kill $SLAM_PID
  sleep 2
  kill -9 $SLAM_PID 2>/dev/null || true
fi

echo "[INFO] All background processes stopped."

#
# 6) Evaluate with evo_ape
#
echo "📊 Evaluating with evo_ape…"
evo_ape bag "${EST_BAG}.bag" \
  /gt /sc_lio_sam/mapping/odometry \
  -va \
  --save_results "$LOG/ape.zip" \
  --save_plot "$LOG/ape.png" \
  > "$LOG/evo.log" 2>&1

echo "✅ Done."
echo "📝 Logs:     $LOG"
echo "📦 Bag:      ${EST_BAG}.bag"
echo "📊 Results:  $LOG/ape.zip and $LOG/ape.png"
