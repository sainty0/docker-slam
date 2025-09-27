from __future__ import annotations
from pathlib import Path
import json
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from datetime import datetime
from typing import Optional
from .schemas import RunRecord, Metrics

DEFAULT_ROOT = Path("/output")


def _ensure_parents(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)


def _append_parquet(df: pd.DataFrame, path: Path):
    _ensure_parents(path)
    if path.exists():
        prev = pq.read_table(path).to_pandas()
        df = pd.concat([prev, df], ignore_index=True)
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), path)


def write_run(rec: RunRecord, root: Path = DEFAULT_ROOT):
    runs_path = root / "logs" / "runs.parquet"
    metrics_path = root / "logs" / "metrics.parquet"

    # Human-readable artifact co-located with plots/logs
    metrics_json = Path(rec.run_dir) / "metrics.json"
    metrics_json.write_text(
        json.dumps((rec.metrics or Metrics()).model_dump(), indent=2),
        encoding="utf-8",
    )

    # Flatten config and params
    run_row = {
        "run_id": rec.run_id,
        "timestamp": rec.timestamp.isoformat().replace("+00:00", "Z"),
        "status": rec.status,
        "wall_time_s": rec.wall_time_s,
        "run_dir": rec.run_dir,
        "est_bag": rec.est_bag,
        "est_tum": rec.est_tum,
        "gt_tum": rec.gt_tum,
        "sweep_id": rec.cfg.sweep_id,
        "seq": rec.cfg.seq,
        "rate": rec.cfg.rate,
        "duration_s": rec.cfg.duration_s,
        "full_seq": rec.cfg.full_seq,
        "label": rec.cfg.label,
        "params_sha1": rec.params_sha1,
        "odom_topic": rec.cfg.odom_topic,
    }

    # Optional param fields (remain None if absent)
    if rec.params:
        pr = rec.params.model_dump()
        for k, v in pr.items():
            run_row[k] = v

    _append_parquet(pd.DataFrame([run_row]), runs_path)

    if rec.metrics:
        m = rec.metrics.model_dump()
        m["run_id"] = rec.run_id
        _append_parquet(pd.DataFrame([m]), metrics_path)


def read_tables(root: Path = DEFAULT_ROOT) -> tuple[pd.DataFrame, pd.DataFrame]:
    runs_path = root / "logs" / "runs.parquet"
    metrics_path = root / "logs" / "metrics.parquet"
    runs = pq.read_table(runs_path).to_pandas() if runs_path.exists() else pd.DataFrame()
    metrics = pq.read_table(metrics_path).to_pandas() if metrics_path.exists() else pd.DataFrame()
    return runs, metrics
