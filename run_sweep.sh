#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

RUNNER=./run_eval_ros1.sh
OUT_ROOT=/output/results_v2
SEQ="KAIST01"
RATE=1.0
DUR=160
FULL_SEQ=0

# NEW: tag all runs from this sweep
export SWEEP_ID="${SWEEP_ID:-$(date +%Y%m%d-%H%M%S)_${SEQ}_smoketest}"

BASE_YAML="$(rospack find lio_sam)/config/params_mulran.yaml"
command -v yq >/dev/null 2>&1 || { echo "[ERROR] yq v4 is required."; exit 1; }

ODOM_SURF=(0.2 0.3 0.4 0.5 0.6)
MAP_CORNER=(0.1 0.15 0.2 0.25 0.3)
MAP_SURF=(0.2 0.3 0.4 0.5 0.6)
EDGE_MIN=(20)
SURF_MIN=(100)
EDGE_THR=(1.0)
SURF_THR=(0.10)

for od in "${ODOM_SURF[@]}"; do
  for mc in "${MAP_CORNER[@]}"; do
    for ms in "${MAP_SURF[@]}"; do
      for emin in "${EDGE_MIN[@]}"; do
        for smin in "${SURF_MIN[@]}"; do
          for et in "${EDGE_THR[@]}"; do
            for st in "${SURF_THR[@]}"; do
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

              LABEL="od${od}_mc${mc}_ms${ms}_emin${emin}_smin${smin}_e${et}_s${st}"
              LABEL=${LABEL//./p}

              if [[ $FULL_SEQ -eq 1 ]]; then
                "$RUNNER" -s "$SEQ" -r "$RATE" -F -o "$OUT_ROOT" -P "$TMP_YAML" -L "$LABEL" || true
              else
                "$RUNNER" -s "$SEQ" -r "$RATE" -t "$DUR" -o "$OUT_ROOT" -P "$TMP_YAML" -L "$LABEL" || true
              fi

              rm -f "$TMP_YAML"
            done
          done
        done
      done
    done
  done
done

echo "✅ Sweep complete."
echo "📊 Aggregate CSV: ${OUT_ROOT}/logs/results_v2.csv"
echo "📜 JSONL:         ${OUT_ROOT}/logs/results.jsonl"

