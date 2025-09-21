"""
Sweep orchestration and aggregation.

Implements: 
  - sweep_main(args): OFAT sweep with replicates and optional parallel workers
  - aggregate_results(): per-sweep and rolling CSV aggregation

This module runs individual evals by invoking the package CLI as a Python module:
  python -m scripts.eval_sweep.cli eval ...
"""
from __future__ import annotations
import concurrent.futures
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

try:
    import pandas as pd  # optional, for aggregation
except Exception:
    pd = None

try:
    import yaml  # required to inject parameters into YAML
except Exception:
    yaml = None

from .utils import now_timestamp, safe_label

LOG = logging.getLogger("eval_sweep.sweep")
LOG.propagate = True

# Module path used to invoke the eval subcommand
MODULE_RUNNER = "scripts.eval_sweep.cli"


def default_from_array(arr: List[str]) -> Optional[str]:
    if not arr:
        return None
    n = len(arr)
    return arr[n // 2]


def sanitize_label_for_fs(s: str) -> str:
    return safe_label(s)


def run_eval_subprocess(args: List[str]) -> int:
    """
    Invoke the eval subcommand via module execution in a subprocess:
      python -m scripts.eval_sweep.cli eval ...
    """
    cmd = [sys.executable, "-m", MODULE_RUNNER] + args
    LOG.debug("Invoking eval subprocess: %s", " ".join(cmd))
    return subprocess.call(cmd)


def aggregate_results(out_root: Path, sweep_id: str):
    """Aggregate results for a given sweep_id into per-sweep and global CSVs."""
    src = out_root / "logs" / "results_v2.csv"
    if not src.exists():
        LOG.warning("No per-run CSV found at %s; skipping aggregation", src)
        return None

    if pd is None:
        LOG.warning("pandas not available; skip aggregation. Install pandas to enable aggregation.")
        return None

    df = pd.read_csv(src)
    if "sweep_id" in df.columns:
        df = df[df["sweep_id"] == sweep_id].copy()

    # ensure metrics numeric
    metrics = ["ape_rmse_m","ape_sse","rpe_trans_1m_rmse_m","rpe_trans_1s_rmse_m","rpe_rot_1s_rmse_deg"]
    for m in metrics:
        if m in df.columns:
            df[m] = pd.to_numeric(df[m], errors="coerce")

    params = ["odom_surf_leaf","mapping_corner_leaf","mapping_surf_leaf",
              "edge_min_valid","surf_min_valid","edge_threshold","surf_threshold"]
    fixed  = ["seq","rate","duration_s","full_seq"]
    group_cols = [c for c in (fixed + params) if c in df.columns]
    if not group_cols:
        LOG.warning("No grouping columns found; skip aggregation.")
        return None

    g = df.groupby(group_cols, dropna=False)
    rows = []
    ts = now_timestamp()
    for key, sub in g:
        sub = sub.copy()
        rec = {"timestamp": ts, "sweep_id": sweep_id}
        # unpack key
        if isinstance(key, tuple):
            for i, col in enumerate(group_cols):
                rec[col] = key[i]
        else:
            rec[group_cols[0]] = key
        rec["reps"] = len(sub)
        rec["success_reps"] = int(sub["ape_rmse_m"].notna().sum()) if "ape_rmse_m" in sub.columns else len(sub)
        for m in metrics:
            if m in sub.columns:
                rec[m + "_mean"] = sub[m].mean(skipna=True)
                rec[m + "_std"] = sub[m].std(skipna=True)
        def fmt(v):
            try:
                return str(v).replace(".", "p")
            except Exception:
                return str(v)
        rec["label"] = ("AVG_od" + fmt(rec.get("odom_surf_leaf")) +
                        "_mc" + fmt(rec.get("mapping_corner_leaf")) +
                        "_ms" + fmt(rec.get("mapping_surf_leaf")) +
                        "_emin" + fmt(rec.get("edge_min_valid")) +
                        "_smin" + fmt(rec.get("surf_min_valid")) +
                        "_e" + fmt(rec.get("edge_threshold")) +
                        "_s" + fmt(rec.get("surf_threshold")))
        rows.append(rec)

    agg = pd.DataFrame(rows)
    cols = ['timestamp','seq','label','sweep_id','rate','duration_s','full_seq','reps','success_reps',
            'ape_rmse_m_mean','ape_rmse_m_std','ape_sse_mean','ape_sse_std',
            'rpe_trans_1m_rmse_m_mean','rpe_trans_1m_rmse_m_std',
            'rpe_trans_1s_rmse_m_mean','rpe_trans_1s_rmse_m_std',
            'rpe_rot_1s_rmse_deg_mean','rpe_rot_1s_rmse_deg_std'] + params
    cols = [c for c in cols if c in agg.columns]

    out_sweep = out_root / "logs" / f"results_v2_{sweep_id}_avg.csv"
    agg[cols].to_csv(out_sweep, index=False)

    # maintain a global rolling file (dedupe this sweep_id)
    out_global = out_root / "logs" / "results_v2_avg.csv"
    try:
        prev = pd.read_csv(out_global)
        prev = prev[prev.get("sweep_id", "") != sweep_id]
        final = pd.concat([prev, agg[cols]], ignore_index=True)
    except Exception:
        final = agg[cols]
    final.to_csv(out_global, index=False)
    LOG.info("Aggregation written to %s and %s", out_sweep, out_global)
    return out_sweep


def sweep_main(args) -> int:
    """
    OFAT sweep with replicates and optional parallelism.
    """
    out_root = Path(args.out_root)
    seq = args.seq
    rate = args.rate
    dur = args.duration
    full_seq = args.full_seq
    reps = args.reps
    workers = getattr(args, "workers", 1)

    sweep_id = args.sweep_id or f"{now_timestamp()}_{seq}_ofat"
    LOG.info("Sweep ID: %s", sweep_id)

    # locate base YAML
    base_yaml = args.base_yaml
    if base_yaml is None:
        LOG.error("BASE YAML must be provided via --base-yaml")
        return 1
    base_yaml = Path(base_yaml)
    if not base_yaml.exists():
        LOG.error("Base YAML not found: %s", base_yaml)
        return 1

    if yaml is None:
        LOG.error("PyYAML is required for sweep parameter injection. Install pyyaml.")
        return 1

    # candidate arrays (strings)
    ODOM_SURF = args.odometry_surf or ["0.4","0.5","0.6","0.65","0.7"]
    MAP_CORNER = args.mapping_corner or ["0.25","0.3","0.325","0.35","0.375"]
    MAP_SURF = args.mapping_surf or ["0.4","0.5","0.55","0.6","0.65","0.7"]
    EDGE_MIN = args.edge_min or ["20"]
    SURF_MIN = args.surf_min or ["100"]
    EDGE_THR = args.edge_thr or ["1.0"]
    SURF_THR = args.surf_thr or ["0.10"]

    OD_BASE = args.od_base or default_from_array(ODOM_SURF)
    MC_BASE = args.mc_base or default_from_array(MAP_CORNER)
    MS_BASE = args.ms_base or default_from_array(MAP_SURF)
    EMIN_BASE = args.emin_base or default_from_array(EDGE_MIN)
    SMIN_BASE = args.smin_base or default_from_array(SURF_MIN)
    ET_BASE = args.et_base or default_from_array(EDGE_THR)
    ST_BASE = args.st_base or default_from_array(SURF_THR)

    # Build a list of tasks (each task describes a single eval run)
    tasks = []

    def add_tasks_for_config(od, mc, ms, emin, smin, et, st, label_base):
        for rep in range(1, reps + 1):
            LBL = sanitize_label_for_fs(f"{label_base}__rep{rep}")
            cmd_args = [
                "eval",
                "-s", seq,
                "-r", str(rate),
                "-o", str(out_root),
                "-P", "<TMP_YAML>",   # placeholder; worker will create the real tmp yaml
                "-L", LBL,
                "--sweep-id", sweep_id,
            ]
            if full_seq:
                cmd_args.append("-F")
            else:
                cmd_args += ["-t", str(dur)]

            tasks.append({
                "od": od, "mc": mc, "ms": ms, "emin": emin, "smin": smin,
                "et": et, "st": st, "label": LBL, "cmd_args": cmd_args
            })

    # 1) baseline
    BASE_LABEL = f"BASE_od{OD_BASE}_mc{MC_BASE}_ms{MS_BASE}_emin{EMIN_BASE}_smin{SMIN_BASE}_e{ET_BASE}_s{ST_BASE}"
    add_tasks_for_config(OD_BASE, MC_BASE, MS_BASE, EMIN_BASE, SMIN_BASE, ET_BASE, ST_BASE, BASE_LABEL)

    # 2) vary each parameter skipping baseline values
    for od in ODOM_SURF:
        if od == str(OD_BASE): 
            continue
        label = f"VARY_od{od}__mc{MC_BASE}__ms{MS_BASE}__emin{EMIN_BASE}__smin{SMIN_BASE}__e{ET_BASE}__s{ST_BASE}"
        add_tasks_for_config(od, MC_BASE, MS_BASE, EMIN_BASE, SMIN_BASE, ET_BASE, ST_BASE, label)

    for mc in MAP_CORNER:
        if mc == str(MC_BASE):
            continue
        label = f"VARY_mc{mc}__od{OD_BASE}__ms{MS_BASE}__emin{EMIN_BASE}__smin{SMIN_BASE}__e{ET_BASE}__s{ST_BASE}"
        add_tasks_for_config(OD_BASE, mc, MS_BASE, EMIN_BASE, SMIN_BASE, ET_BASE, ST_BASE, label)

    for ms in MAP_SURF:
        if ms == str(MS_BASE):
            continue
        label = f"VARY_ms{ms}__od{OD_BASE}__mc{MC_BASE}__emin{EMIN_BASE}__smin{SMIN_BASE}__e{ET_BASE}__s{ST_BASE}"
        add_tasks_for_config(OD_BASE, MC_BASE, ms, EMIN_BASE, SMIN_BASE, ET_BASE, ST_BASE, label)

    for emin in EDGE_MIN:
        if emin == str(EMIN_BASE):
            continue
        label = f"VARY_emin{emin}__od{OD_BASE}__mc{MC_BASE}__ms{MS_BASE}__smin{SMIN_BASE}__e{ET_BASE}__s{ST_BASE}"
        add_tasks_for_config(OD_BASE, MC_BASE, MS_BASE, emin, SMIN_BASE, ET_BASE, ST_BASE, label)

    for smin in SURF_MIN:
        if smin == str(SMIN_BASE):
            continue
        label = f"VARY_smin{smin}__od{OD_BASE}__mc{MC_BASE}__ms{MS_BASE}__emin{EMIN_BASE}__e{ET_BASE}__s{ST_BASE}"
        add_tasks_for_config(OD_BASE, MC_BASE, MS_BASE, EMIN_BASE, smin, ET_BASE, ST_BASE, label)

    for et in EDGE_THR:
        if et == str(ET_BASE):
            continue
        label = f"VARY_e{et}__od{OD_BASE}__mc{MC_BASE}__ms{MS_BASE}__emin{EMIN_BASE}__smin{SMIN_BASE}__s{ST_BASE}"
        add_tasks_for_config(OD_BASE, MC_BASE, MS_BASE, EMIN_BASE, SMIN_BASE, et, ST_BASE, label)

    for st in SURF_THR:
        if st == str(ST_BASE):
            continue
        label = f"VARY_s{st}__od{OD_BASE}__mc{MC_BASE}__ms{MS_BASE}__emin{EMIN_BASE}__smin{SMIN_BASE}__e{ET_BASE}"
        add_tasks_for_config(OD_BASE, MC_BASE, MS_BASE, EMIN_BASE, SMIN_BASE, ET_BASE, st, label)

    if not tasks:
        LOG.warning("No tasks generated for sweep; exiting.")
        return 1

    LOG.info("Prepared %d eval tasks; executing with %d workers", len(tasks), workers)

    # worker that creates a tmp YAML, invokes eval subcommand, and cleans up
    def worker(task):
        tmp_yaml_fd, tmp_yaml_path = tempfile.mkstemp(suffix=".yaml", prefix="params_mulran.")
        os.close(tmp_yaml_fd)
        tmp_yaml = Path(tmp_yaml_path)
        try:
            shutil.copy(base_yaml, tmp_yaml)
            doc = yaml.safe_load(tmp_yaml.read_text() or "{}")
            if "lio_sam" not in doc or doc["lio_sam"] is None:
                doc["lio_sam"] = {}
            doc["lio_sam"]["odometrySurfLeafSize"] = float(task["od"])
            doc["lio_sam"]["mappingCornerLeafSize"] = float(task["mc"])
            doc["lio_sam"]["mappingSurfLeafSize"] = float(task["ms"])
            doc["lio_sam"]["edgeFeatureMinValidNum"] = int(float(task["emin"]))
            doc["lio_sam"]["surfFeatureMinValidNum"] = int(float(task["smin"]))
            doc["lio_sam"]["edgeThreshold"] = float(task["et"])
            doc["lio_sam"]["surfThreshold"] = float(task["st"])
            tmp_yaml.write_text(yaml.safe_dump(doc))
        except Exception:
            LOG.exception("Failed to construct tmp yaml for task %s", task.get("label"))
            tmp_yaml.unlink(missing_ok=True)
            return 1

        # substitute placeholder with actual tmp yaml
        cmd_args = [str(a) if a != "<TMP_YAML>" else str(tmp_yaml) for a in task["cmd_args"]]

        try:
            LOG.info("Worker starting eval: %s", " ".join(cmd_args))
            rc = run_eval_subprocess(cmd_args)
            if rc != 0:
                LOG.warning("Eval returned non-zero rc=%s for label=%s", rc, task.get("label"))
            return rc
        except Exception:
            LOG.exception("Eval subprocess failed for label=%s", task.get("label"))
            return 1
        finally:
            tmp_yaml.unlink(missing_ok=True)

    # execute tasks with a ThreadPool (safe for subprocess invocation)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        future_to_task = {ex.submit(worker, t): t for t in tasks}
        for fut in concurrent.futures.as_completed(future_to_task):
            t = future_to_task[fut]
            try:
                rc = fut.result()
                results.append(rc)
                LOG.info("Task finished label=%s rc=%s", t.get("label"), rc)
            except Exception:
                LOG.exception("Task raised an exception for label=%s", t.get("label"))
                results.append(1)

    # aggregate
    agg_file = aggregate_results(out_root, sweep_id)
    LOG.info("OFAT sweep complete (with %s reps per config).", reps)
    LOG.info("Per-run CSV: %s", out_root / "logs" / "results_v2.csv")
    if agg_file:
        LOG.info("Averaged CSV: %s", agg_file)
    LOG.info("Rolling AVG: %s", out_root / "logs" / "results_v2_avg.csv")
    return 0
