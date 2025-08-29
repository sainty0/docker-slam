#!/usr/bin/env python3
import argparse, json, sys, pathlib
import pandas as pd

def load_jsonl(p):
    rows=[]
    with open(p, 'r') as f:
        for line in f:
            line=line.strip()
            if not line: continue
            rows.append(json.loads(line))
    return pd.DataFrame(rows)

def load_from_runs(root):
    root=pathlib.Path(root)
    rows=[]
    for m in root.glob("logs/*/metrics.json"):
        with open(m) as f:
            j=json.load(f)
        rows.append(j)
    return pd.DataFrame(rows)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root", default="/output/results", help="OUT_ROOT from your scripts")
    ap.add_argument("--out", default="results_tidy.csv")
    ap.add_argument("--prefer-jsonl", action="store_true", help="Load logs/results.jsonl if present")
    args=ap.parse_args()

    logs = pathlib.Path(args.root)/"logs"
    jsonl = logs/"results.jsonl"
    if args.prefer_jsonl and jsonl.exists():
        df = load_jsonl(jsonl)
    else:
        df = load_from_runs(args.root)

    # Flatten params dict to columns if needed
    if "params" in df.columns:
        params = pd.json_normalize(df["params"])
        df = pd.concat([df.drop(columns=["params"]), params], axis=1)

    # Keep key columns in front
    front = [
        "timestamp","sweep_id","seq","label","param_hash","rate","duration_s","full_seq",
        "ape_rmse_m","ape_sse","rpe_trans_1m_rmse_m","rpe_trans_1s_rmse_m","rpe_rot_1s_rmse_deg",
        "odometrySurfLeafSize","mappingCornerLeafSize","mappingSurfLeafSize",
        "edgeFeatureMinValidNum","surfFeatureMinValidNum","edgeThreshold","surfThreshold",
        "run_dir","est_bag","est_tum","wall_time_s"
    ]
    cols = [c for c in front if c in df.columns] + [c for c in df.columns if c not in front]
    df = df[cols]

    df.to_csv(args.out, index=False)
    print(f"Wrote {args.out} with {len(df)} rows")

    # Example quick analysis printed to console
    if "ape_rmse_m" in df.columns:
        g = df.groupby("odometrySurfLeafSize")["ape_rmse_m"].median().sort_index()
        print("\nMedian APE RMSE vs odometrySurfLeafSize:")
        print(g.to_string())

if __name__ == "__main__":
    main()