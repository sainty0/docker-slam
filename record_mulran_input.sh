#!/usr/bin/env bash
set -e

# 🕒 Timestamped filename
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
SEQ_NAME=${1:-KAIST01}  # Allow passing sequence name as argument

# Output path
OUTPUT_BAG="/output/${SEQ_NAME}_input_${TIMESTAMP}.bag"

echo "🎯 Recording MulRan sequence: $SEQ_NAME"
echo "📦 Saving to: $OUTPUT_BAG"
echo ""

# Make sure use_sim_time is set
rosparam set use_sim_time true

# Record selected topics
rosbag record \
  /os1_points \
  /imu/data_raw \
  /odometry/imu \
  /odometry/imu_incremental \
  /odometry/gpsz \
  /gt \
  /Navtech/Polar \
  /tf \
  /tf_static \
  /clock \
  -O "$OUTPUT_BAG"
