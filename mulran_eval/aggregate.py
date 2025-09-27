from __future__ import annotations
from pathlib import Path
import pandas as pd
from typing import Iterable
from .storage import read_tables


AGG_COLS = [
    "ape_rmse_m",
    "rpe_trans_1m_rmse_m",
    "rpe_trans_1s_rmse_m",
    "rpe_rot_1s_rmse_deg",
]

KEY_COLS = [
    "sweep_id", "seq", "label",
    "rate", "duration_s", "full_seq",
    # Param knobs (may be NaN if not set)
    "odometrySurfLeafSize",
    "mappingCornerLeafSize",
    "mappingSurfLeafSize",
    "edgeFeatureMinValidNum",
    "surfFeatureMinValidNum",
    "edgeThreshold",
    "surfThreshold",
]


def aggregate_sweep(sweep_id: str, out_root: Path | None = None) -> pd.DataFrame:
    root = out_root or Path("/output")
    if not root.exists():
        # Try local fallback if absolute root isn't available
        try:
            local = Path.cwd() / "output" / root.name
            if local.exists():
                root = local
        except Exception:
            pass
    runs, metrics = read_tables(root)
    if runs.empty or metrics.empty:
        return pd.DataFrame()

    df = runs.merge(metrics, on="run_id", how="left")
    df = df[df["sweep_id"] == sweep_id]
    if df.empty:
        return pd.DataFrame()

    # success mask
    ok = df[df["status"] == "ok"]

    grp = ok.groupby(KEY_COLS, dropna=False)
    mean = grp[AGG_COLS].mean().add_suffix("_mean")
    std = grp[AGG_COLS].std(ddof=0).add_suffix("_std")
    cnt = grp.size().rename("success_reps")

    agg = pd.concat([mean, std, cnt], axis=1).reset_index()
    agg["reps"] = df.groupby(KEY_COLS, dropna=False).size().values

    # Write to Parquet
    out_path = root.joinpath("logs", f"aggregates_{sweep_id}.parquet")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    agg.to_parquet(out_path, index=False)
    return agg
