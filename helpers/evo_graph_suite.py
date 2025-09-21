#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import itertools
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


def parse_args():
    p = argparse.ArgumentParser(description="Evo Graphing Suite for SC-LIO-SAM sweeps")
    p.add_argument("--csv", required=True, help="Path to tidy CSV (e.g., results_v2.csv)")
    p.add_argument("--out", default="evo_graphs", help="Output directory for graphs and tables")
    p.add_argument("--metric", default="ape_rmse_m", help="Metric column to plot (default: ape_rmse_m)")
    p.add_argument("--sweep-id", default=None, help="Optional SWEEP_ID to filter")
    p.add_argument("--where", default=None, help="Optional pandas query filter, e.g. 'full_seq==0 and rate==1.0'")
    p.add_argument("--param-cols", default=None,
                   help="Comma-separated parameter columns. If omitted, auto-detect known LIO-SAM params.")
    p.add_argument("--per-param-groups", type=int, default=12,
                   help="Max control-groups per parameter to plot (largest groups by sample size).")
    p.add_argument("--min-p-values", type=int, default=2, help="Minimum distinct values for the parameter in a group.")
    p.add_argument("--max-heatmaps", type=int, default=6, help="Max number of pairwise heatmaps to generate.")
    p.add_argument("--top-n", type=int, default=30, help="How many top runs (lowest metric) to save to CSV.")
    return p.parse_args()


def slugify(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-._" else "_" for c in str(s))[:200]


def ensure_numeric(series: pd.Series):
    try:
        return pd.to_numeric(series, errors="coerce")
    except Exception:
        return series


def auto_param_cols(df: pd.DataFrame) -> list:
    # Known LIO-SAM knobs you swept
    candidates = [
        "odometrySurfLeafSize",
        "mappingCornerLeafSize",
        "mappingSurfLeafSize",
        "edgeFeatureMinValidNum",
        "surfFeatureMinValidNum",
        "edgeThreshold",
        "surfThreshold",
    ]
    return [c for c in candidates if c in df.columns]


def describe_dataset(df, metric, param_cols):
    lines = []
    lines.append(f"Rows: {len(df)}")
    lines.append(f"Metric: {metric}")
    if "sweep_id" in df.columns:
        lines.append(f"Sweep IDs: {sorted(df['sweep_id'].dropna().unique().tolist())}")
    lines.append(f"Params: {param_cols}")
    for c in param_cols:
        u = df[c].dropna().unique()
        lines.append(f"  - {c}: {len(u)} unique values → {sorted(u.tolist())[:10]}{'...' if len(u)>10 else ''}")
    return "".join(lines)


def save_table(df: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)

def plot_raw_error_scatter(x_vals, y_vals, title, xlabel, ylabel, out_path: Path, jitter=True, seed=0):
    """Scatter of raw metric values vs a parameter, with slight x-jitter to reduce overlap."""
    x_vals = np.asarray(x_vals, dtype=float)
    y_vals = np.asarray(y_vals, dtype=float)

    # Drop NaNs so matplotlib doesn't choke
    m = np.isfinite(x_vals) & np.isfinite(y_vals)
    x_vals = x_vals[m]
    y_vals = y_vals[m]

    if len(x_vals) == 0:
        return

    if jitter:
        rng = np.random.default_rng(seed)
        span = np.nanmax(x_vals) - np.nanmin(x_vals)
        width = (span if span > 0 else 1.0) * 0.01  # ~1% of span
        x_plot = x_vals + rng.uniform(-width, width, size=x_vals.shape)
    else:
        x_plot = x_vals

    plt.figure()
    plt.scatter(x_plot, y_vals, alpha=0.45, s=18)
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=160)
    plt.close()


# def plot_line_with_errorbars(x_vals, y_mean, y_std, title, xlabel, ylabel, out_path: Path):
def plot_line_with_errorbars(x_vals, y_mean, y_std, title, xlabel, ylabel, out_path: Path):
    plt.figure()
    y_std = np.nan_to_num(y_std, nan=0.0)

    plt.plot(x_vals, y_mean, marker="o", label="median")
    plt.fill_between(x_vals, y_mean - y_std, y_mean + y_std, alpha=0.3, label="±1 std dev")

    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.legend()
    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=160)
    plt.close()

    # plt.figure()
    # # Avoid NaNs (matplotlib errorbar doesn't like all-NaN std)
    # y_std = np.nan_to_num(y_std, nan=0.0)
    # plt.errorbar(x_vals, y_mean, yerr=y_std, marker="o")
    # plt.title(title)
    # plt.xlabel(xlabel)
    # plt.ylabel(ylabel)
    # plt.tight_layout()
    # out_path.parent.mkdir(parents=True, exist_ok=True)
    # plt.savefig(out_path, dpi=160)
    # plt.close()


def plot_heatmap(x_labels, y_labels, grid, title, xlabel, ylabel, out_path: Path):
    plt.figure()
    ax = plt.gca()
    im = ax.imshow(grid, aspect="auto", origin="lower")
    ax.set_xticks(np.arange(len(x_labels)))
    ax.set_yticks(np.arange(len(y_labels)))
    ax.set_xticklabels([str(x) for x in x_labels], rotation=45, ha="right")
    ax.set_yticklabels([str(y) for y in y_labels])
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    plt.colorbar(im, ax=ax)
    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=160)
    plt.close()


def main():
    args = parse_args()
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(args.csv)
    # Optional filtering
    if args.sweep_id and "sweep_id" in df.columns:
        df = df[df["sweep_id"] == args.sweep_id].copy()
    if args.where:
        df = df.query(args.where).copy()

    # Make metric numeric
    if args.metric not in df.columns:
        print(f"[ERROR] Metric column '{args.metric}' not found.", file=sys.stderr)
        sys.exit(2)
    df[args.metric] = ensure_numeric(df[args.metric])

    # Parameter columns
    if args.param_cols:
        param_cols = [c.strip() for c in args.param_cols.split(",") if c.strip()]
    else:
        param_cols = auto_param_cols(df)
    for c in param_cols:
        df[c] = ensure_numeric(df[c])

    # Overview
    overview_txt = describe_dataset(df, args.metric, param_cols)
    (out_root / "tables").mkdir(parents=True, exist_ok=True)
    with open(out_root / "tables" / "dataset_overview.txt", "w") as f:
        f.write(overview_txt + "")
    print(overview_txt)

    # Save top runs
    if args.metric in df.columns:
        top_runs = df.sort_values(args.metric, ascending=True).head(args.top_n)
        save_table(top_runs, out_root / "tables" / "top_runs.csv")

    # Per-parameter: global aggregation (median ± std)
    per_param_global_dir = out_root / "per_param_global"
    for p in param_cols:
        agg = (df
               .groupby(p, dropna=True)[args.metric]
               .agg(["count", "median", "mean", "std"])
               .reset_index()
               .sort_values(p))
        save_table(agg, out_root / "tables" / f"{p}_global_stats.csv")
        plot_line_with_errorbars(
            x_vals=agg[p].values,
            y_mean=agg["median"].values,
            y_std=agg["std"].values,
            title=f"{args.metric} vs {p} (median ± std)",
            xlabel=p, ylabel=args.metric,
            out_path=per_param_global_dir / f"{p}.png",
        )
        plot_raw_error_scatter(
            x_vals=df[p].values,
            y_vals=df[args.metric].values,
            title=f"Raw {args.metric} vs {p} (all runs)",
            xlabel=p, ylabel=args.metric,
            out_path=per_param_global_dir / f"{p}__raw_scatter.png",
        )


    # Per-parameter: control groups where all other params are fixed
    per_param_dir = out_root / "per_param"
    for p in param_cols:
        others = [c for c in param_cols if c != p]
        if not others:
            continue

        # Group by the other params to find stable control groups
        g = df.groupby(others, dropna=False)
        groups = []
        for key, sub in g:
            # Require at least two distinct values of p in this control group
            if sub[p].nunique(dropna=True) >= args.min_p_values:
                groups.append((key, len(sub), sub.copy()))
        # Sort groups by size, keep top N
        groups.sort(key=lambda t: t[1], reverse=True)
        groups = groups[:args.per_param_groups]

        for key, size, sub in groups:
            # Aggregate within group by p
            agg = (sub
                   .groupby(p, dropna=True)[args.metric]
                   .agg(["count", "median", "mean", "std"])
                   .reset_index()
                   .sort_values(p))
            # Store table
            key_items = list(key) if isinstance(key, tuple) else [key]
            group_kv = dict(zip(others, key_items))
            group_id = "__".join(f"{k}={group_kv[k]}" for k in others)
            group_slug = slugify(group_id)
            group_dir = per_param_dir / f"param={p}" / group_slug
            save_table(agg, group_dir / "stats.csv")

            # Plot
            plot_line_with_errorbars(
                x_vals=agg[p].values,
                y_mean=agg["median"].values,
                y_std=agg["std"].values,
                title=f"{args.metric} vs {p} (fixed: {group_id})",
                xlabel=p, ylabel=args.metric,
                out_path=group_dir / "plot.png",
            )
            plot_raw_error_scatter(
                x_vals=sub[p].values,
                y_vals=sub[args.metric].values,
                title=f"Raw {args.metric} vs {p}\n(fixed: {group_id})",
                xlabel=p, ylabel=args.metric,
                out_path=group_dir / "raw_scatter.png",
            )


    # Pairwise heatmaps (median metric)
    # Choose pairs with reasonable grid sizes to keep images readable
    heatmap_dir = out_root / "heatmaps"
    pairs = list(itertools.combinations(param_cols, 2))[: args.max_heatmaps * 2]  # candidate pool
    made = 0
    for (a, b) in pairs:
        a_vals = np.sort(df[a].dropna().unique())
        b_vals = np.sort(df[b].dropna().unique())
        if len(a_vals) * len(b_vals) > 100:  # skip giant grids
            continue
        pivot = (df.pivot_table(index=b, columns=a, values=args.metric, aggfunc="median"))
        # Drop all-NaN rows/cols to avoid empty heatmaps
        pivot = pivot.dropna(how="all").dropna(axis=1, how="all")
        if pivot.empty:
            continue
        plot_heatmap(
            x_labels=list(pivot.columns.values),
            y_labels=list(pivot.index.values),
            grid=pivot.values,
            title=f"Median {args.metric} – heatmap of {a} vs {b}",
            xlabel=a, ylabel=b,
            out_path=heatmap_dir / f"{a}__vs__{b}.png",
        )
        made += 1
        if made >= args.max_heatmaps:
            break

    # Simple Spearman correlations between params and metric
    corr_dir = out_root / "correlations"
    corrs = []
    for p in param_cols:
        s = df[p]
        if s.dropna().empty:
            continue
        try:
            c = s.corr(df[args.metric], method="spearman")
        except Exception:
            c = np.nan
        corrs.append((p, c))
    corr_df = pd.DataFrame(corrs, columns=["parameter", "spearman_corr"]).sort_values("spearman_corr")
    save_table(corr_df, out_root / "tables" / "param_spearman_correlations.csv")

    # Plot correlations as bar chart
    plt.figure()
    plt.barh(corr_df["parameter"], corr_df["spearman_corr"])
    plt.title(f"Spearman correlation with {args.metric}")
    plt.xlabel("Correlation")
    plt.ylabel("Parameter")
    plt.tight_layout()
    (corr_dir).mkdir(parents=True, exist_ok=True)
    plt.savefig(corr_dir / "spearman_correlations.png", dpi=160)
    plt.close()

    print(f"Done. Artifacts in: {out_root}")

if __name__ == "__main__":
    main()

# USAGE
# python3 /helpers/evo_graph_suite.py \
#   --csv /output/results/logs/results_v2.csv \
#   --out /output/results/graphs \
#   --metric ape_rmse_m \
#   --where "full_seq==0 and rate==1.0" \
#   --per-param-groups 12 \
#   --max-heatmaps 8
