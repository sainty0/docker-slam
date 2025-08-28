#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

RUNNER=./run_eval_ros1.sh
OUT_ROOT=/output/results
SEQ="KAIST01"
RATE=1.0
DUR=60         # quick smoke test
FULL_SEQ=0

BASE_YAML="$(rospack find lio_sam)/config/params_mulran.yaml"
command -v yq >/dev/null 2>&1 || { echo "[ERROR] yq v4 is required."; exit 1; }

ODOM_SURF=(0.2 0.3 0.4 0.5 0.6)
MAP_CORNER=(0.1 0.15 0.2 0.25 0.3)
MAP_SURF=(0.2 0.3 0.4 0.5 0.6)
EDGE_MIN=(10 20 30)
SURF_MIN=(50 100 150)
EDGE_THR=(0.8 1.0 1.2)
SURF_THR=(0.08 0.10 0.12)

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

echo "✅ Sweep complete. Aggregate results at ${OUT_ROOT}/logs/results.csv"
