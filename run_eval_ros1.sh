#!/usr/bin/env bash
#
# Evaluate SC-LIO-SAM on a MulRan sequence using the headless file player,
# export odometry to TUM via /odom_to_tum.py, then compute APE/RPE with evo.
# Now supports dynamic parameter files and nicer run naming.
#
# ROS1 version.
#

set -euo pipefail
export LC_ALL=C

### ──────────────────────────────── configurable defaults ─────────────────────
SEQ="KAIST01"                         # MulRan sequence folder name
SEQ_ROOT="/data/mulran"               # Where MulRan sequences live
RATE=1.0                              # Playback rate (1× realtime)
DURATION=60                           # Seconds to run player/SLAM (ignored with -F)
OUT_ROOT="/output"                    # Top-level folder for logs & bags

# Topics / files
ODOM_TOPIC="/lio_sam/mapping/odometry"
GT_TUM_ROOT="/output/gts"             # Folder containing <SEQ>_gt.tum
ODOM_TO_TUM="/odom_to_tum.py"         # Path to your converter script

# Extra seconds to let rosbag finish cleanly (only used when not full-seq)
RECORD_SLACK=10

# Optional dynamic params
PARAMS_FILE=""                        # Provided via -P
LABEL="base"                          # Human-friendly label via -L
FULL_SEQ=0                            # -F -> run full sequence
### ────────────────────────────────────────────────────────────────────────────

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Options:
  -s  SEQ         MulRan sequence name                       (default: $SEQ)
  -r  RATE        Player rate                                (default: $RATE)
  -t  SECONDS     Evaluation duration (ignored with -F)      (default: $DURATION)
  -F              Full sequence (no timeout)
  -o  DIR         Output root directory                      (default: $OUT_ROOT)
  -d  TOPIC       Odometry topic                             (default: $ODOM_TOPIC)
  -G  DIR         GT TUM dir (expects <SEQ>_gt.tum)          (default: $GT_TUM_ROOT)
  -p  PATH        Path to /odom_to_tum.py                    (default: $ODOM_TO_TUM)
  -P  FILE        Params YAML to inject (launch arg: params_file:=FILE)
  -L  LABEL       Short label added to names for comparison  (default: $LABEL)
  -h              Show this help
EOF
}

while getopts ":s:r:t:Fo:d:G:p:P:L:h" opt; do
  case ${opt} in
    s) SEQ=${OPTARG}        ;;
    r) RATE=${OPTARG}       ;;
    t) DURATION=${OPTARG}   ;;
    F) FULL_SEQ=1           ;;
    o) OUT_ROOT=${OPTARG}   ;;
    d) ODOM_TOPIC=${OPTARG} ;;
    G) GT_TUM_ROOT=${OPTARG};;
    p) ODOM_TO_TUM=${OPTARG};;
    P) PARAMS_FILE=${OPTARG};;
    L) LABEL=${OPTARG}      ;;
    h) usage; exit 0        ;;
    \?) echo "Invalid option: -$OPTARG" >&2; usage; exit 1 ;;
  esac
done

seq_dir="${SEQ_ROOT}/${SEQ}"
if [ ! -d "$seq_dir" ]; then
  echo "[ERROR] Sequence directory not found: ${seq_dir}"
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

GT_TUM="${GT_TUM_ROOT}/${SEQ}_gt.tum"
if [ ! -f "$GT_TUM" ]; then
  echo "[ERROR] GT TUM not found at: $GT_TUM"
  echo "        Provide ${SEQ}_gt.tum in ${GT_TUM_ROOT} or use -G to point to the dir."
  exit 1
fi

# Short content hash of params file (or 'default' if none)
if [[ -n "$PARAMS_FILE" ]]; then
  if [ ! -f "$PARAMS_FILE" ]; then
    echo "[ERROR] Params file not found: $PARAMS_FILE"; exit 1
  fi
  PARAM_HASH=$(sha1sum "$PARAMS_FILE" | awk '{print $1}' | cut -c1-8)
else
  PARAM_HASH="default"
fi

# Sanitize label: keep A–Z a–z 0–9 . _ + % -
safe_label=$(printf '%s' "$LABEL" | sed -E 's/[^A-Za-z0-9._+%-]+/_/g; s/^_+|_+$//g')

timestamp=$(date +%Y%m%d-%H%M%S)
run_base="${SEQ}_${safe_label}_${PARAM_HASH}_${timestamp}"

RUN_DIR="${OUT_ROOT}/logs/${run_base}"
BAG_DIR="${OUT_ROOT}/bags"

EST_BAG="${BAG_DIR}/${run_base}.bag"
EST_TUM="${RUN_DIR}/${run_base}.tum"

mkdir -p "$RUN_DIR" "$BAG_DIR"

# Global results CSV
RESULTS_CSV="${OUT_ROOT}/logs/results.csv"
if [ ! -f "$RESULTS_CSV" ]; then
  echo "timestamp,seq,label,param_hash,rate,duration_s,full_seq,ape_rmse_m,ape_sse,rpe_trans_1m_rmse_m,rpe_trans_1s_rmse_m,rpe_rot_1s_rmse_deg,run_dir,est_bag,est_tum" > "$RESULTS_CSV"
fi

echo "[INFO  $(date +%F' '%T)] Starting evaluation on ${SEQ} (${safe_label})"
if [[ $FULL_SEQ -eq 1 ]]; then
  echo "[INFO] Mode: full-sequence (no timeout)"
else
  echo "[INFO] Mode: fixed duration = ${DURATION}s"
fi
echo "[INFO] Output directory: $RUN_DIR"
[[ -n "$PARAMS_FILE" ]] && echo "[INFO] Params: $PARAMS_FILE (hash=${PARAM_HASH})"

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
# 1) Launch SC-LIO-SAM (this starts roscore implicitly), loading params if given
###############################################################################
echo "🧠  [1/6] Launching SC-LIO-SAM…"

LAUNCH_ARGS=()
if [[ -n "$PARAMS_FILE" ]]; then
  LAUNCH_ARGS+=( "params_file:=${PARAMS_FILE}" )
fi
LAUNCH_ARGS+=( "use_sim_time:=true" )

roslaunch lio_sam run_mulran.launch "${LAUNCH_ARGS[@]}" \
  > >(tee "${RUN_DIR}/sc_lio.log") 2>&1 &
PIDS+=($!)
SLAM_PID=$!
sleep 5
echo "[DEBUG] SLAM PID: $SLAM_PID"

# Save effective params
rosparam get /lio_sam > "${RUN_DIR}/lio_sam_params.yaml" 2>/dev/null || true
[[ -n "$PARAMS_FILE" ]] && cp -f "$PARAMS_FILE" "${RUN_DIR}/params_injected.yaml"

###############################################################################
# 2) Start headless MulRan player
###############################################################################
echo "🚀  [2/6] Playing MulRan sequence from ${seq_dir} at ${RATE}×…"
PLAYER_LOG="${RUN_DIR}/player.log"

if [[ $FULL_SEQ -eq 1 ]]; then
  rosrun file_player file_player_headless --dir "$seq_dir" --rate "$RATE" \
    > >(tee "$PLAYER_LOG") 2>&1 &
else
  timeout --preserve-status ${DURATION} \
    rosrun file_player file_player_headless --dir "$seq_dir" --rate "$RATE" \
    > >(tee "$PLAYER_LOG") 2>&1 &
fi
PIDS+=($!)
PLAYER_PID=$!
echo "[DEBUG] Player PID: $PLAYER_PID"

###############################################################################
# 3) Record odometry bag
###############################################################################
if [[ $FULL_SEQ -eq 1 ]]; then
  echo "📦  [3/6] Recording ${ODOM_TOPIC} → ${EST_BAG} (until player ends)…"
  rosbag record "${ODOM_TOPIC}" -O "$EST_BAG" \
    > "${RUN_DIR}/record.log" 2>&1 &
else
  RECORD_SECS=$((DURATION + RECORD_SLACK))
  echo "📦  [3/6] Recording ${ODOM_TOPIC} → ${EST_BAG} (${RECORD_SECS}s)…"
  rosbag record "${ODOM_TOPIC}" --duration=${RECORD_SECS} -O "$EST_BAG" \
    > "${RUN_DIR}/record.log" 2>&1 &
fi
PIDS+=($!)
RECORD_PID=$!
echo "[DEBUG] Record PID: $RECORD_PID"

###############################################################################
# 4) Start odom_to_tum.py
###############################################################################
echo "📝  [4/6] Writing TUM from ${ODOM_TOPIC} → ${EST_TUM}"
python3 -u "${ODOM_TO_TUM}" --topic "${ODOM_TOPIC}" --out "${EST_TUM}" \
  > "${RUN_DIR}/odom_to_tum.log" 2>&1 &
PIDS+=($!)
ODOM2TUM_PID=$!
echo "[DEBUG] odom_to_tum.py PID: $ODOM2TUM_PID"

start_wall=$(date +%s)

###############################################################################
# 5) Wait for player; stop SLAM; finalize recorder & odom_to_tum
###############################################################################
wait "$PLAYER_PID" || true
echo "[INFO] Player finished – stopping SLAM & waiting for tools…"

kill "$SLAM_PID" 2>/dev/null || true

if [[ $FULL_SEQ -eq 1 ]]; then
  echo "[INFO] Stopping rosbag recorder (full-seq mode)…"
  kill "$RECORD_PID" 2>/dev/null || true
fi

echo "[INFO] Waiting for rosbag recorder to finalize…"
if ! wait "$RECORD_PID"; then
  echo "[WARN] Recorder did not exit cleanly (see ${RUN_DIR}/record.log)."
fi

echo "[INFO] Stopping odom_to_tum.py…"
kill "$ODOM2TUM_PID" 2>/dev/null || true
for _ in {1..5}; do
  if ! ps -p "$ODOM2TUM_PID" > /dev/null; then break; fi
  sleep 1
done
if ps -p "$ODOM2TUM_PID" > /dev/null; then
  echo "[WARN] Forcing odom_to_tum.py to exit."
  kill -9 "$ODOM2TUM_PID" 2>/dev/null || true
fi

# Finalize possible *.bag.active
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
# 6) Evaluate with evo (APE + RPE), then write metrics.json + results.csv
###############################################################################
echo "📊  [6/6] Evaluating with evo (GT=${GT_TUM}, EST=${EST_TUM})…"

evo_ape tum "${GT_TUM}" "${EST_TUM}" \
  -va --save_results "${RUN_DIR}/ape.zip" --save_plot "${RUN_DIR}/ape.png" \
  > "${RUN_DIR}/evo_ape.log" 2>&1 || echo "[ERROR] evo_ape failed"

evo_rpe tum "${GT_TUM}" "${EST_TUM}" \
  -va -r trans_part --delta 1 --delta_unit m \
  --save_results "${RUN_DIR}/rpe_trans_1m.zip" \
  --save_plot "${RUN_DIR}/rpe_trans_1m.png" \
  > "${RUN_DIR}/evo_rpe_trans_1m.log" 2>&1 || echo "[ERROR] evo_rpe (trans/1m) failed"

evo_rpe tum "${GT_TUM}" "${EST_TUM}" \
  -va -r trans_part --delta 1 --delta_unit m \
  --save_results "${RUN_DIR}/rpe_trans_1s.zip" \
  --save_plot "${RUN_DIR}/rpe_trans_1s.png" \
  > "${RUN_DIR}/evo_rpe_trans_1s.log" 2>&1 || echo "[ERROR] evo_rpe (trans/1s) failed"

evo_rpe tum "${GT_TUM}" "${EST_TUM}" \
  -va -r angle_deg --delta 1 --delta_unit m \
  --save_results "${RUN_DIR}/rpe_rot_1s.zip" \
  --save_plot "${RUN_DIR}/rpe_rot_1s.png" \
  > "${RUN_DIR}/evo_rpe_rot_1s.log" 2>&1 || echo "[ERROR] evo_rpe (rot/1s) failed"

get_last_val () { local key="$1" file="$2"; awk -v k="$key" 'tolower($0) ~ k {print $2}' "$file" 2>/dev/null | tail -n1; }
APE_RMSE=$(get_last_val rmse "${RUN_DIR}/evo_ape.log")
APE_SSE=$(get_last_val sse  "${RUN_DIR}/evo_ape.log")
RPE1M_RMSE=$(get_last_val rmse "${RUN_DIR}/evo_rpe_trans_1m.log")
RPE1S_RMSE=$(get_last_val rmse "${RUN_DIR}/evo_rpe_trans_1s.log")
RPEROT_RMSE=$(get_last_val rmse "${RUN_DIR}/evo_rpe_rot_1s.log")

end_wall=$(date +%s)
wall_secs=$((end_wall - start_wall))

num_or_null () { v="$1"; [[ -z "${v:-}" ]] && echo null || echo "$v"; }
cat > "${RUN_DIR}/metrics.json" <<JSON
{
  "timestamp": "${timestamp}",
  "seq": "${SEQ}",
  "label": "${safe_label}",
  "param_hash": "${PARAM_HASH}",
  "rate": ${RATE},
  "duration_s": ${DURATION},
  "full_seq": ${FULL_SEQ},
  "ape_rmse_m": $(num_or_null "$APE_RMSE"),
  "ape_sse": $(num_or_null "$APE_SSE"),
  "rpe_trans_1m_rmse_m": $(num_or_null "$RPE1M_RMSE"),
  "rpe_trans_1s_rmse_m": $(num_or_null "$RPE1S_RMSE"),
  "rpe_rot_1s_rmse_deg": $(num_or_null "$RPEROT_RMSE"),
  "run_dir": "${RUN_DIR}",
  "est_bag": "${EST_BAG}",
  "est_tum": "${EST_TUM}",
  "wall_time_s": ${wall_secs}
}
JSON

echo "${timestamp},${SEQ},${safe_label},${PARAM_HASH},${RATE},${DURATION},${FULL_SEQ},${APE_RMSE:-},${APE_SSE:-},${RPE1M_RMSE:-},${RPE1S_RMSE:-},${RPEROT_RMSE:-},${RUN_DIR},${EST_BAG},${EST_TUM}" >> "$RESULTS_CSV"

echo ""
echo "✅  Evaluation completed"
echo "📝  Logs    → ${RUN_DIR}"
echo "📦  Bag     → ${EST_BAG}"
echo "🧾  EST TUM → ${EST_TUM}"
echo "🎯  GT  TUM → ${GT_TUM}"
echo "📊  APE     → ${RUN_DIR}/ape.{zip,png}"
echo "📈  Metrics → ${RUN_DIR}/metrics.json"
echo "🧮  Sweep   → ${RESULTS_CSV}"
