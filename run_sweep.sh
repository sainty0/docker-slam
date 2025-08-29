#!/usr/bin/env bash
# One-factor-at-a-time sweep:
# 1) Run a single BASELINE with defaults
# 2) For each parameter, vary it across its list while keeping all others at BASE
set -euo pipefail
export LC_ALL=C

# ─────────────────────────────────── config ───────────────────────────────────
RUNNER=./run_eval_ros1.sh
OUT_ROOT=/output/results_v3
SEQ="KAIST01"
RATE=1.0
DUR=160
FULL_SEQ=0

# Tag this sweep
export SWEEP_ID="${SWEEP_ID:-$(date +%Y%m%d-%H%M%S)_${SEQ}_ofat}"

BASE_YAML="$(rospack find lio_sam)/config/params_mulran.yaml"
command -v yq >/dev/null 2>&1 || { echo "[ERROR] yq v4 is required."; exit 1; }

# Candidate values for each knob
ODOM_SURF=(0.2 0.3 0.4 0.5 0.6)
MAP_CORNER=(0.1 0.15 0.2 0.25 0.3)
MAP_SURF=(0.2 0.3 0.4 0.5 0.6)
EDGE_MIN=(20)
SURF_MIN=(100)
EDGE_THR=(1.0)
SURF_THR=(0.10)

# ───────────────────────────── helper: defaults ──────────────────────────────
# Pick a baseline from an array (middle element); allow env override like OD_BASE=0.4
default_from_array() {
  local -n arr=$1
  local n=${#arr[@]}
  if (( n == 0 )); then echo ""; return; fi
  echo "${arr[$(( n/2 ))]}"   # upper-middle for even n; middle for odd n
}

OD_BASE=${OD_BASE:-$(default_from_array ODOM_SURF)}
MC_BASE=${MC_BASE:-$(default_from_array MAP_CORNER)}
MS_BASE=${MS_BASE:-$(default_from_array MAP_SURF)}
EMIN_BASE=${EMIN_BASE:-$(default_from_array EDGE_MIN)}
SMIN_BASE=${SMIN_BASE:-$(default_from_array SURF_MIN)}
ET_BASE=${ET_BASE:-$(default_from_array EDGE_THR)}
ST_BASE=${ST_BASE:-$(default_from_array SURF_THR)}

# ───────────────────────────── helper: run once ──────────────────────────────
sanitize_label() {
  # keep A–Z a–z 0–9 . _ + % - then swap '.'→'p' for filesystem-friendliness
  local s="$1"
  s="$(printf '%s' "$s" | sed -E 's/[^A-Za-z0-9._+%-]+/_/g; s/^_+|_+$//g')"
  s="${s//./p}"
  echo "$s"
}

do_run() {
  local od="$1" mc="$2" ms="$3" emin="$4" smin="$5" et="$6" st="$7" label="$8"

  local TMP_YAML
  TMP_YAML=$(mktemp /tmp/params_mulran.XXXX.yaml)
  cp "$BASE_YAML" "$TMP_YAML"

  OD="$od" MC="$mc" MS="$ms" EMIN="$emin" SMIN="$smin" ET="$et" ST="$st" \
  yq e -i '
    .lio_sam.odometrySurfLeafSize   = (env(OD)   | tonumber) |
    .lio_sam.mappingCornerLeafSize  = (env(MC)   | tonumber) |
    .lio_sam.mappingSurfLeafSize    = (env(MS)   | tonumber) |
    .lio_sam.edgeFeatureMinValidNum = (env(EMIN) | tonumber) |
    .lio_sam.surfFeatureMinValidNum = (env(SMIN) | tonumber) |
    .lio_sam.edgeThreshold          = (env(ET)   | tonumber) |
    .lio_sam.surfThreshold          = (env(ST)   | tonumber)
  ' "$TMP_YAML"

  local LBL
  LBL=$(sanitize_label "$label")

  if [[ $FULL_SEQ -eq 1 ]]; then
    "$RUNNER" -s "$SEQ" -r "$RATE" -F -o "$OUT_ROOT" -P "$TMP_YAML" -L "$LBL" || true
  else
    "$RUNNER" -s "$SEQ" -r "$RATE" -t "$DUR" -o "$OUT_ROOT" -P "$TMP_YAML" -L "$LBL" || true
  fi

  rm -f "$TMP_YAML"
}

# ──────────────────────────────── 1) BASELINE ────────────────────────────────
BASE_LABEL="BASE_od${OD_BASE}_mc${MC_BASE}_ms${MS_BASE}_emin${EMIN_BASE}_smin${SMIN_BASE}_e${ET_BASE}_s${ST_BASE}"
do_run "$OD_BASE" "$MC_BASE" "$MS_BASE" "$EMIN_BASE" "$SMIN_BASE" "$ET_BASE" "$ST_BASE" "$BASE_LABEL"

# ──────────────────────── 2) Vary ONE knob at a time ────────────────────────
# Each loop skips the baseline value to avoid duplicate runs.

# Vary ODOM_SURF
for od in "${ODOM_SURF[@]}"; do
  [[ "$od" == "$OD_BASE" ]] && continue
  do_run "$od" "$MC_BASE" "$MS_BASE" "$EMIN_BASE" "$SMIN_BASE" "$ET_BASE" "$ST_BASE" \
         "VARY_od${od}__mc${MC_BASE}__ms${MS_BASE}__emin${EMIN_BASE}__smin${SMIN_BASE}__e${ET_BASE}__s${ST_BASE}"
done

# Vary MAP_CORNER
for mc in "${MAP_CORNER[@]}"; do
  [[ "$mc" == "$MC_BASE" ]] && continue
  do_run "$OD_BASE" "$mc" "$MS_BASE" "$EMIN_BASE" "$SMIN_BASE" "$ET_BASE" "$ST_BASE" \
         "VARY_mc${mc}__od${OD_BASE}__ms${MS_BASE}__emin${EMIN_BASE}__smin${SMIN_BASE}__e${ET_BASE}__s${ST_BASE}"
done

# Vary MAP_SURF
for ms in "${MAP_SURF[@]}"; do
  [[ "$ms" == "$MS_BASE" ]] && continue
  do_run "$OD_BASE" "$MC_BASE" "$ms" "$EMIN_BASE" "$SMIN_BASE" "$ET_BASE" "$ST_BASE" \
         "VARY_ms${ms}__od${OD_BASE}__mc${MC_BASE}__emin${EMIN_BASE}__smin${SMIN_BASE}__e${ET_BASE}__s${ST_BASE}"
done

# If you later provide multiple values for these, they will vary against BASE too.

# Vary EDGE_MIN
for emin in "${EDGE_MIN[@]}"; do
  [[ "$emin" == "$EMIN_BASE" ]] && continue
  do_run "$OD_BASE" "$MC_BASE" "$MS_BASE" "$emin" "$SMIN_BASE" "$ET_BASE" "$ST_BASE" \
         "VARY_emin${emin}__od${OD_BASE}__mc${MC_BASE}__ms${MS_BASE}__smin${SMIN_BASE}__e${ET_BASE}__s${ST_BASE}"
done

# Vary SURF_MIN
for smin in "${SURF_MIN[@]}"; do
  [[ "$smin" == "$SMIN_BASE" ]] && continue
  do_run "$OD_BASE" "$MC_BASE" "$MS_BASE" "$EMIN_BASE" "$smin" "$ET_BASE" "$ST_BASE" \
         "VARY_smin${smin}__od${OD_BASE}__mc${MC_BASE}__ms${MS_BASE}__emin${EMIN_BASE}__e${ET_BASE}__s${ST_BASE}"
done

# Vary EDGE_THR
for et in "${EDGE_THR[@]}"; do
  [[ "$et" == "$ET_BASE" ]] && continue
  do_run "$OD_BASE" "$MC_BASE" "$MS_BASE" "$EMIN_BASE" "$SMIN_BASE" "$et" "$ST_BASE" \
         "VARY_e${et}__od${OD_BASE}__mc${MC_BASE}__ms${MS_BASE}__emin${EMIN_BASE}__smin${SMIN_BASE}__s${ST_BASE}"
done

# Vary SURF_THR
for st in "${SURF_THR[@]}"; do
  [[ "$st" == "$ST_BASE" ]] && continue
  do_run "$OD_BASE" "$MC_BASE" "$MS_BASE" "$EMIN_BASE" "$SMIN_BASE" "$ET_BASE" "$st" \
         "VARY_s${st}__od${OD_BASE}__mc${MC_BASE}__ms${MS_BASE}__emin${EMIN_BASE}__smin${SMIN_BASE}__e${ET_BASE}"
done

echo "✅ OFAT sweep complete."
echo "📊 Aggregate CSV: ${OUT_ROOT}/logs/results_v2.csv"
echo "📜 JSONL:         ${OUT_ROOT}/logs/results.jsonl"
