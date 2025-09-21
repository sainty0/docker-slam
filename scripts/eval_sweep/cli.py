"""
CLI entrypoint for eval_sweep package.

Subcommands:
  - eval  : run a single evaluation (replacement for run_eval_ros1.sh)
  - sweep : OFAT sweep with replicates and optional parallel workers (replacement for run_sweep.sh)
"""
from __future__ import annotations
import argparse
import logging
import os
import sys
from typing import Optional

from .eval_runner import run_eval_from_args
from .sweep import sweep_main


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="eval_sweep", description="Evaluation and OFAT sweep utilities (Python port)")
    sub = p.add_subparsers(dest="cmd", required=True)

    # eval subcommand
    e = sub.add_parser("eval", help="Run a single evaluation (replacement for run_eval_ros1.sh)")
    e.add_argument("-s", "--seq", default="KAIST01")
    e.add_argument("--seq-root", default="/data/mulran")
    e.add_argument("-r", "--rate", type=float, default=1.0)
    e.add_argument("-t", "--duration", type=int, default=160)
    e.add_argument("-F", "--full-seq", action="store_true")
    e.add_argument("-o", "--out-root", default="/output")
    e.add_argument("-d", "--odom-topic", default="/lio_sam/mapping/odometry")
    e.add_argument("-G", "--gt-tum-root", default="/output/gts")
    e.add_argument("-p", "--odom-to-tum", default="odom_to_tum.py")
    e.add_argument("--record-slack", type=int, default=10)
    e.add_argument("-P", "--params-file", default=None)
    e.add_argument("-L", "--label", default="base")
    e.add_argument("--sweep-id", default=None)
    e.set_defaults(func=lambda args: run_eval_from_args(args))

    # sweep subcommand
    sw = sub.add_parser("sweep", help="Run an OFAT sweep (replacement for run_sweep.sh)")
    sw.add_argument("--runner", default=None, help="(unused) path to runner")
    sw.add_argument("--out-root", default="/output/results_v8")
    sw.add_argument("-s", "--seq", default="Riverside01")
    sw.add_argument("-r", "--rate", type=float, default=1.0)
    sw.add_argument("-t", "--duration", type=int, default=300)
    sw.add_argument("-F", "--full-seq", action="store_true")
    sw.add_argument("--reps", type=int, default=int(os.environ.get("REPS", "10")))
    sw.add_argument("--workers", type=int, default=1, help="Concurrency for eval runs (default 1)")
    sw.add_argument("--sweep-id", default=None)
    sw.add_argument("--base-yaml", default=None, help="Path to base params YAML (required)")
    sw.add_argument("--odometry-surf", nargs="+", default=None)
    sw.add_argument("--mapping-corner", nargs="+", default=None)
    sw.add_argument("--mapping-surf", nargs="+", default=None)
    sw.add_argument("--edge-min", nargs="+", default=None)
    sw.add_argument("--surf-min", nargs="+", default=None)
    sw.add_argument("--edge-thr", nargs="+", default=None)
    sw.add_argument("--surf-thr", nargs="+", default=None)
    # optional overrides for baselines
    sw.add_argument("--od-base", default=None)
    sw.add_argument("--mc-base", default=None)
    sw.add_argument("--ms-base", default=None)
    sw.add_argument("--emin-base", default=None)
    sw.add_argument("--smin-base", default=None)
    sw.add_argument("--et-base", default=None)
    sw.add_argument("--st-base", default=None)
    sw.set_defaults(func=lambda args: sweep_main(args))

    return p


def main(argv: Optional[list[str]] = None) -> int:
    # Configure logging once here (modules will use package loggers)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        rc = args.func(args)
        # Ensure integer exit code
        return int(rc or 0)
    except Exception as exc:
        logging.getLogger("eval_sweep.cli").exception("Fatal error: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
