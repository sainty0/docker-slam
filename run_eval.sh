set -ex

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
SEQUENCE_NAME=KAIST01

# Dynamic paths for this run
LOG_DIR=/output/logs/${SEQUENCE_NAME}_${TIMESTAMP}
EST_BAG_PATH=/data/bags/${SEQUENCE_NAME}_estimation_${TIMESTAMP}
RESULTS_PATH=/data/results/${SEQUENCE_NAME}_${TIMESTAMP}
RAW_DATA_PATH=/data/mulran/$SEQUENCE_NAME
BAG_OUTPUT_PATH=/data/bags/$SEQUENCE_NAME

mkdir -p $LOG_DIR $RESULTS_PATH

echo "[INFO] run_eval.sh started at $(date)" > $LOG_DIR/script.log

echo "⏩ [1/5] Skipping conversion, using preconverted bag"

echo "🚀 [2/5] Playing bag file..."
ros2 bag play $BAG_OUTPUT_PATH --rate 1.0 --loop > $LOG_DIR/play.log 2>&1 &
PLAY_PID=$!
sleep 2

echo "🧠 [3/5] Launching LIO-SAM..."
ros2 launch lio_sam run.launch.py > $LOG_DIR/lio_sam.log 2>&1 &
LIO_PID=$!
sleep 5

echo "📦 [4/5] Recording LIO-SAM output to: $EST_BAG_PATH"
ros2 bag record \
  /gt \
  /lio_sam/mapping/odometry \
  -o "$EST_BAG_PATH" \
  > "$LOG_DIR/record.log" 2>&1 &


RECORD_PID=$!

echo "⏳ Collecting data for 60 seconds..."
sleep 60

echo "🛑 Stopping..."
kill $RECORD_PID || true
kill $PLAY_PID || true
kill $LIO_PID || true
wait || true

echo "📊 [5/5] Evaluating with evo_ape"
evo_ape bag2 $EST_BAG_PATH \
  /gt /lio_sam/mapping/odometry \
  -va \
  --save_results $RESULTS_PATH/ape.zip \
  --save_plot   $RESULTS_PATH/ape.png > $LOG_DIR/eval.log 2>&1


echo "✅ Done. Logs: $LOG_DIR | Estimation bag: $EST_BAG_PATH | Results: $RESULTS_PATH"
