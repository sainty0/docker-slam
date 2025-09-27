#!/usr/bin/env bash
# One-factor-at-a-time (OFAT) sweep with REPLICATES:
# 1) Run a BASELINE config N times
# 2) For each parameter, vary it across its list while keeping others at BASE,
#    and run each variant N times
# 3) Aggregate (mean/std) across the N replicates into results_v2_<SWEEP_ID>_avg.csv
set -euo pipefail
export LC_ALL=C

# ─────────────────────────────────── config ───────────────────────────────────
RUNNER=./run_eval_ros1.sh
OUT_ROOT=/output/results_v8
SEQ="KAIST01"
RATE=1.0
DUR=300
FULL_SEQ=0
REPS=${REPS:-10}   # number of replicates per configuration

# Tag this sweep
export SWEEP_ID="${SWEEP_ID:-$(date +%Y%m%d-%H%M%S)_${SEQ}_ofat}"

BASE_YAML="$(rospack find lio_sam)/config/params_mulran.yaml"
command -v yq >/dev/null 2>&1 || { echo "[ERROR] yq v4 is required."; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "[ERROR] python3 is required."; exit 1; }

# Candidate values for each knob
ODOM_SURF=(0.4 0.5 0.6 0.65 0.7)
MAP_CORNER=( 0.25 0.3 0.325 0.35 0.0.375)
MAP_SURF=(0.4 0.5 0.55 0.6 0.65 0.7)
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
  local od="$1" mc="$2" ms="$3" emin="$4" smin="$5" et="$6" st="$7" label_base="$8"

  # replicate N times
  for ((rep=1; rep<=REPS; rep++)); do
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
    LBL=$(sanitize_label "${label_base}__rep${rep}")

    if [[ $FULL_SEQ -eq 1 ]]; then
      "$RUNNER" -s "$SEQ" -r "$RATE" -F -o "$OUT_ROOT" -P "$TMP_YAML" -L "$LBL" || true
    else
      "$RUNNER" -s "$SEQ" -r "$RATE" -t "$DUR" -o "$OUT_ROOT" -P "$TMP_YAML" -L "$LBL" || true
    fi

    rm -f "$TMP_YAML"
  done
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

# ─────────────────────────────── 3) Aggregate means ───────────────────────────
# Compute mean/std across the REPS for this SWEEP_ID and write:
#   - ${OUT_ROOT}/logs/results_v2_${SWEEP_ID}_avg.csv  (per-sweep file)
#   - ${OUT_ROOT}/logs/results_v2_avg.csv              (global rolling file)
python3 - "$OUT_ROOT" "$SWEEP_ID" <<'PY'
import sys, time, pandas as pd
out_root, sweep_id = sys.argv[1], sys.argv[2]
src = f"{out_root}/logs/results_v2.csv"
df = pd.read_csv(src)
if "sweep_id" in df.columns:
    df = df[df["sweep_id"] == sweep_id].copy()

# Ensure numeric
metrics = ["ape_rmse_m","ape_sse","rpe_trans_1m_rmse_m","rpe_trans_1s_rmse_m","rpe_rot_1s_rmse_deg"]
for m in metrics:
    if m in df.columns:
        df[m] = pd.to_numeric(df[m], errors="coerce")

params = ["odom_surf_leaf","mapping_corner_leaf","mapping_surf_leaf",
          "edge_min_valid","surf_min_valid","edge_threshold","surf_threshold"]
fixed  = ["seq","rate","duration_s","full_seq"]
group_cols = [c for c in fixed+params if c in df.columns]
if not group_cols:
    print("[WARN] No grouping columns found; skip aggregation.", file=sys.stderr); sys.exit(0)

g = df.groupby(group_cols, dropna=False)
rows=[]
ts=time.strftime("%Y%m%d-%H%M%S")
for key, sub in g:
    sub = sub.copy()
    rec = {"timestamp": ts, "sweep_id": sweep_id}
    # unpack key
    if isinstance(key, tuple):
        for i,col in enumerate(group_cols):
            rec[col]=key[i]
    else:
        rec[group_cols[0]] = key
    rec["reps"] = len(sub)
    rec["success_reps"] = int(sub["ape_rmse_m"].notna().sum()) if "ape_rmse_m" in sub.columns else len(sub)
    for m in metrics:
        if m in sub.columns:
            rec[m+"_mean"] = sub[m].mean(skipna=True)
            rec[m+"_std"]  = sub[m].std(skipna=True)
    # human label for the config
    def fmt(v): 
        try: return str(v).replace(".","p")
        except: return str(v)
    rec["label"] = ("AVG_od"+fmt(rec.get("odom_surf_leaf"))+
                    "_mc"+fmt(rec.get("mapping_corner_leaf"))+
                    "_ms"+fmt(rec.get("mapping_surf_leaf"))+
                    "_emin"+fmt(rec.get("edge_min_valid"))+
                    "_smin"+fmt(rec.get("surf_min_valid"))+
                    "_e"+fmt(rec.get("edge_threshold"))+
                    "_s"+fmt(rec.get("surf_threshold")))
    rows.append(rec)

agg = pd.DataFrame(rows)

cols = ['timestamp','seq','label','sweep_id','rate','duration_s','full_seq','reps','success_reps',
        'ape_rmse_m_mean','ape_rmse_m_std','ape_sse_mean','ape_sse_std',
        'rpe_trans_1m_rmse_m_mean','rpe_trans_1m_rmse_m_std',
        'rpe_trans_1s_rmse_m_mean','rpe_trans_1s_rmse_m_std',
        'rpe_rot_1s_rmse_deg_mean','rpe_rot_1s_rmse_deg_std'] + params
cols = [c for c in cols if c in agg.columns]

out_sweep = f"{out_root}/logs/results_v2_{sweep_id}_avg.csv"
agg[cols].to_csv(out_sweep, index=False)

# maintain a global rolling file (dedupe this sweep_id)
out_global = f"{out_root}/logs/results_v2_avg.csv"
try:
    prev = pd.read_csv(out_global)
    prev = prev[prev.get("sweep_id","") != sweep_id]
    final = pd.concat([prev, agg[cols]], ignore_index=True)
except Exception:
    final = agg[cols]
final.to_csv(out_global, index=False)
print(out_sweep)
PY

echo "✅ OFAT sweep complete (with ${REPS} reps per config)."
echo "📊 Per-run CSV:   ${OUT_ROOT}/logs/results_v2.csv"
echo "📈 Averaged CSV:  ${OUT_ROOT}/logs/results_v2_${SWEEP_ID}_avg.csv"
echo "🗂  Rolling AVG:   ${OUT_ROOT}/logs/results_v2_avg.csv"
