"""
Evaluator module: contains EvalConfig and Evaluator which run a single evaluation.

This is a refactor of the `eval` functionality from the original monolithic script.
"""
from __future__ import annotations
import atexit
import json
import logging
import os
import shutil
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

try:
    import yaml
except Exception:
    yaml = None

from .utils import (
    LOG as _LOG,
    now_timestamp,
    run_subprocess_background,
    run_subprocess_capture,
    parse_evo_log_for_metric,
    safe_label,
)

LOG = logging.getLogger("eval_sweep.eval_runner")
LOG.propagate = True


@dataclass
class EvalConfig:
    seq: str = "KAIST01"
    seq_root: str = "/data/mulran"
    rate: float = 1.0
    duration: int = 160
    full_seq: bool = False
    out_root: str = "/output"
    odom_topic: str = "/lio_sam/mapping/odometry"
    gt_tum_root: str = "/output/gts"
    odom_to_tum: str = "odom_to_tum.py"
    record_slack: int = 10
    params_file: Optional[str] = None
    label: str = "base"
    sweep_id: Optional[str] = None
    roslaunch: str = "roslaunch"
    rosrun: str = "rosrun"
    rosbag: str = "rosbag"
    evo_ape: str = "evo_ape"
    python3: str = os.environ.get("PYTHON", os.sys.executable)


class Evaluator:
    def __init__(self, cfg: EvalConfig):
        self.cfg = cfg
        self.processes: List = []
        self._register_cleanup()
        self._resolve_tools()
        self._prepare_paths()

    def _register_cleanup(self):
        atexit.register(self.cleanup)
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: self._on_signal(sig))

    def _on_signal(self, sig):
        LOG.warning("Received signal %s, cleaning up...", sig)
        self.cleanup()
        raise SystemExit(1)

    def _resolve_tools(self):
        # best-effort checks; raise useful error early
        reqs = {
            "roslaunch": self.cfg.roslaunch,
            "rosrun": self.cfg.rosrun,
            "rosbag": self.cfg.rosbag,
            "evo_ape": self.cfg.evo_ape,
        }
        for name, exe in reqs.items():
            if shutil.which(exe) is None:
                raise RuntimeError(f"Required executable '{exe}' (for {name}) not found in PATH")

    def _prepare_paths(self):
        self.seq_dir = Path(self.cfg.seq_root) / self.cfg.seq
        if not self.seq_dir.is_dir():
            raise FileNotFoundError(f"Sequence directory not found: {self.seq_dir}")

        self.odom_to_tum_path = Path(self.cfg.odom_to_tum)
        if not self.odom_to_tum_path.exists():
            raise FileNotFoundError(f"odom_to_tum.py not found at: {self.odom_to_tum_path}")

        self.gt_tum = Path(self.cfg.gt_tum_root) / f"{self.cfg.seq}_gt.tum"
        if not self.gt_tum.exists():
            raise FileNotFoundError(f"GT TUM not found at: {self.gt_tum}")

        if self.cfg.params_file:
            if not Path(self.cfg.params_file).exists():
                raise FileNotFoundError(f"Params file not found: {self.cfg.params_file}")
            self.param_hash = self._short_hash(Path(self.cfg.params_file))
        else:
            self.param_hash = "default"

        self.safe_label = safe_label(self.cfg.label)
        self.timestamp = now_timestamp()
        self.run_base = f"{self.cfg.seq}_{self.safe_label}_{self.param_hash}_{self.timestamp}"
        self.run_dir = Path(self.cfg.out_root) / "logs" / self.run_base
        self.bag_dir = Path(self.cfg.out_root) / "bags"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.bag_dir.mkdir(parents=True, exist_ok=True)
        self.est_bag = self.bag_dir / f"{self.run_base}.bag"
        self.est_tum = self.run_dir / f"{self.run_base}.tum"
        self.results_csv = Path(self.cfg.out_root) / "logs" / "results_v2.csv"
        self.results_jsonl = Path(self.cfg.out_root) / "logs" / "results.jsonl"

        if not self.results_csv.exists():
            self.results_csv.parent.mkdir(parents=True, exist_ok=True)
            header = ",".join([
                "timestamp","seq","label","param_hash","rate","duration_s","full_seq","sweep_id",
                "ape_rmse_m","ape_sse","rpe_trans_1m_rmse_m","rpe_trans_1s_rmse_m","rpe_rot_1s_rmse_deg",
                "odom_surf_leaf","mapping_corner_leaf","mapping_surf_leaf",
                "edge_min_valid","surf_min_valid","edge_threshold","surf_threshold",
                "run_dir","est_bag","est_tum"
            ])
            self.results_csv.write_text(header + "\n")

    @staticmethod
    def _short_hash(p: Path) -> str:
        import hashlib
        h = hashlib.sha1(p.read_bytes()).hexdigest()
        return h[:8]

    def launch_slam(self):
        LOG.info("Launching SC-LIO-SAM (roslaunch)...")
        args = [self.cfg.roslaunch, "lio_sam", "run_mulran.launch"]
        if self.cfg.params_file:
            args.append(f"params_file:={self.cfg.params_file}")
        args.append("use_sim_time:=true")
        log_path = self.run_dir / "sc_lio.log"
        p = run_subprocess_background(args, log_path, env=os.environ.copy())
        self.processes.append(p)
        time.sleep(5)
        LOG.debug("SLAM PID: %s", p.pid)
        # best-effort save ros params
        try:
            run_subprocess_capture(["rosparam", "get", "/lio_sam"], check=False)
        except Exception:
            LOG.debug("rosparam get failed (non-fatal)")
        if self.cfg.params_file:
            try:
                shutil.copy(self.cfg.params_file, self.run_dir / "params_injected.yaml")
            except Exception:
                LOG.debug("Failed to copy params file into run dir", exc_info=True)
        return p

    def start_player(self):
        LOG.info("Starting headless MulRan player from %s at %sx", self.seq_dir, self.cfg.rate)
        player_log = self.run_dir / "player.log"
        cmd = [self.cfg.rosrun, "file_player", "file_player_headless", "--dir", str(self.seq_dir), "--rate", str(self.cfg.rate)]
        if self.cfg.full_seq:
            p = run_subprocess_background(cmd, player_log)
        else:
            if shutil.which("timeout"):
                p = run_subprocess_background(["timeout", "--preserve-status", str(self.cfg.duration)] + cmd, player_log)
            else:
                p = run_subprocess_background(cmd, player_log)
        self.processes.append(p)
        LOG.debug("Player PID: %s", p.pid)
        return p

    def start_recording(self):
        LOG.info("Recording odometry topic %s → %s", self.cfg.odom_topic, self.est_bag)
        rec_log = self.run_dir / "record.log"
        if self.cfg.full_seq:
            cmd = [self.cfg.rosbag, "record", self.cfg.odom_topic, "-O", str(self.est_bag)]
        else:
            rec_secs = self.cfg.duration + self.cfg.record_slack
            cmd = [self.cfg.rosbag, "record", self.cfg.odom_topic, f"--duration={rec_secs}", "-O", str(self.est_bag)]
        p = run_subprocess_background(cmd, rec_log)
        self.processes.append(p)
        LOG.debug("Record PID: %s", p.pid)
        return p

    def start_odom_to_tum(self):
        LOG.info("Starting odom_to_tum.py → %s", self.est_tum)
        odom_log = self.run_dir / "odom_to_tum.log"
        cmd = [self.cfg.python3, "-u", str(self.odom_to_tum_path), "--topic", self.cfg.odom_topic, "--out", str(self.est_tum)]
        p = run_subprocess_background(cmd, odom_log)
        self.processes.append(p)
        LOG.debug("odom_to_tum PID: %s", p.pid)
        return p

    def wait_for_player_and_teardown(self, player_proc, slam_proc, record_proc, odom_proc):
        LOG.info("Waiting for player to finish...")
        try:
            player_proc.wait()
        except Exception:
            LOG.debug("Player wait interrupted", exc_info=True)
        LOG.info("Player finished, stopping SLAM...")
        try:
            slam_proc.terminate()
        except Exception:
            pass
        if self.cfg.full_seq:
            try:
                record_proc.terminate()
            except Exception:
                pass

        LOG.info("Waiting for recorder to finalize...")
        try:
            record_proc.wait(timeout=60)
        except Exception:
            LOG.warning("Recorder did not exit cleanly; check logs.")

        LOG.info("Stopping odom_to_tum.py...")
        try:
            odom_proc.terminate()
            for _ in range(5):
                if odom_proc.poll() is not None:
                    break
                time.sleep(1)
            if odom_proc.poll() is None:
                LOG.warning("Forcing odom_to_tum to exit")
                odom_proc.kill()
        except Exception:
            pass

        active = Path(str(self.est_bag) + ".active")
        if active.exists() and not self.est_bag.exists():
            LOG.info("Finalizing active bag via rosbag reindex")
            if shutil.which("rosbag"):
                try:
                    run_subprocess_capture(["rosbag", "reindex", str(active)], check=False)
                except Exception:
                    LOG.warning("rosbag reindex failed; attempting rename")
                    try:
                        active.rename(self.est_bag)
                    except Exception:
                        LOG.exception("Failed to rename active bag")
            else:
                LOG.warning("rosbag not available to reindex; skipping")

    def _read_param_value(self, params_yaml: Optional[Path], key_path: str) -> Optional[object]:
        if not params_yaml or not params_yaml.exists() or yaml is None:
            return None
        key = key_path.lstrip(".")
        try:
            data = yaml.safe_load(params_yaml.read_text())
            parts = key.split(".")
            cur = data
            for p in parts:
                if cur is None:
                    return None
                cur = cur.get(p)
            return cur
        except Exception:
            return None

    def _maybe_run_evo(self):
        if not self.est_tum.exists() or self.est_tum.stat().st_size == 0:
            LOG.error("Expected EST TUM not found or empty: %s", self.est_tum)
            return False

        LOG.info("Running evo APE/RPE evaluations (GT=%s, EST=%s)", self.gt_tum, self.est_tum)
        try:
            run_subprocess_capture([self.cfg.evo_ape, "tum", str(self.gt_tum), str(self.est_tum),
                                    "-va", "--save_results", str(self.run_dir / "ape.zip"),
                                    "--save_plot", str(self.run_dir / "ape.png")],
                                   check=False)
        except Exception:
            LOG.exception("evo_ape failed")

        try:
            run_subprocess_capture(["evo_rpe", "tum", str(self.gt_tum), str(self.est_tum),
                                    "-va", "-r", "trans_part", "--delta", "1", "--delta_unit", "m",
                                    "--save_results", str(self.run_dir / "rpe_trans_1m.zip"),
                                    "--save_plot", str(self.run_dir / "rpe_trans_1m.png")],
                                   check=False)
        except Exception:
            LOG.debug("rpe trans/1m failed or not available")

        try:
            run_subprocess_capture(["evo_rpe", "tum", str(self.gt_tum), str(self.est_tum),
                                    "-va", "-r", "trans_part", "--delta", "1", "--delta_unit", "m",
                                    "--save_results", str(self.run_dir / "rpe_trans_1s.zip"),
                                    "--save_plot", str(self.run_dir / "rpe_trans_1s.png")],
                                   check=False)
        except Exception:
            LOG.debug("rpe trans/1s failed or not available")

        try:
            run_subprocess_capture(["evo_rpe", "tum", str(self.gt_tum), str(self.est_tum),
                                    "-va", "-r", "angle_deg", "--delta", "1", "--delta_unit", "m",
                                    "--save_results", str(self.run_dir / "rpe_rot_1s.zip"),
                                    "--save_plot", str(self.run_dir / "rpe_rot_1s.png")],
                                   check=False)
        except Exception:
            LOG.debug("rpe rot/1s failed or not available")

        return True

    def collect_and_write_metrics(self, start_wall: float, end_wall: float):
        ape_rmse = parse_evo_log_for_metric(self.run_dir / "evo_ape.log", "rmse")
        ape_sse = parse_evo_log_for_metric(self.run_dir / "evo_ape.log", "sse")
        rpe_1m = parse_evo_log_for_metric(self.run_dir / "evo_rpe_trans_1m.log", "rmse")
        rpe_1s = parse_evo_log_for_metric(self.run_dir / "evo_rpe_trans_1s.log", "rmse")
        rpe_rot = parse_evo_log_for_metric(self.run_dir / "evo_rpe_rot_1s.log", "rmse")

        params_yaml = None
        if self.cfg.params_file:
            params_yaml = Path(self.cfg.params_file)
        elif (self.run_dir / "params_injected.yaml").exists():
            params_yaml = self.run_dir / "params_injected.yaml"
        elif (self.run_dir / "lio_sam_params.yaml").exists():
            params_yaml = self.run_dir / "lio_sam_params.yaml"

        def read_param(k):
            return self._read_param_value(params_yaml, k)

        od_leaf = read_param(".lio_sam.odometrySurfLeafSize")
        mc_leaf = read_param(".lio_sam.mappingCornerLeafSize")
        ms_leaf = read_param(".lio_sam.mappingSurfLeafSize")
        edge_min = read_param(".lio_sam.edgeFeatureMinValidNum")
        surf_min = read_param(".lio_sam.surfFeatureMinValidNum")
        edge_thr = read_param(".lio_sam.edgeThreshold")
        surf_thr = read_param(".lio_sam.surfThreshold")

        wall_secs = int(end_wall - start_wall)
        status = "ok" if self.est_tum.exists() and self.est_tum.stat().st_size > 0 else "no_tum"

        metrics = {
            "timestamp": self.timestamp,
            "seq": self.cfg.seq,
            "label": self.safe_label,
            "param_hash": self.param_hash,
            "sweep_id": self.cfg.sweep_id or "",
            "rate": self.cfg.rate,
            "duration_s": self.cfg.duration,
            "full_seq": int(self.cfg.full_seq),
            "status": status,
            "ape_rmse_m": ape_rmse,
            "ape_sse": ape_sse,
            "rpe_trans_1m_rmse_m": rpe_1m,
            "rpe_trans_1s_rmse_m": rpe_1s,
            "rpe_rot_1s_rmse_deg": rpe_rot,
            "run_dir": str(self.run_dir),
            "est_bag": str(self.est_bag),
            "est_tum": str(self.est_tum),
            "wall_time_s": wall_secs,
            "params": {
                "odometrySurfLeafSize": od_leaf,
                "mappingCornerLeafSize": mc_leaf,
                "mappingSurfLeafSize": ms_leaf,
                "edgeFeatureMinValidNum": edge_min,
                "surfFeatureMinValidNum": surf_min,
                "edgeThreshold": edge_thr,
                "surfThreshold": surf_thr,
            },
        }

        with (self.run_dir / "metrics.json").open("w") as fh:
            json.dump(metrics, fh, indent=2)

        row = ",".join([
            metrics["timestamp"], metrics["seq"], metrics["label"], metrics["param_hash"],
            str(metrics["rate"]), str(metrics["duration_s"]), str(metrics["full_seq"]), metrics["sweep_id"],
            str(metrics.get("ape_rmse_m") or ""), str(metrics.get("ape_sse") or ""), str(metrics.get("rpe_trans_1m_rmse_m") or ""),
            str(metrics.get("rpe_trans_1s_rmse_m") or ""), str(metrics.get("rpe_rot_1s_rmse_deg") or ""),
            str(od_leaf or ""), str(mc_leaf or ""), str(ms_leaf or ""),
            str(edge_min or ""), str(surf_min or ""), str(edge_thr or ""), str(surf_thr or ""),
            metrics["run_dir"], metrics["est_bag"], metrics["est_tum"]
        ]) + "\n"
        with self.results_csv.open("a") as fh:
            fh.write(row)

        with self.results_jsonl.open("a") as fh:
            fh.write(json.dumps(metrics) + "\n")

        LOG.info("Metrics written to %s", self.run_dir / "metrics.json")
        return metrics

    def cleanup(self):
        LOG.info("Cleaning up %d processes...", len(self.processes))
        for p in list(self.processes):
            try:
                if p and p.poll() is None:
                    p.terminate()
                    time.sleep(1)
                    if p.poll() is None:
                        p.kill()
            except Exception:
                pass
        self.processes.clear()

    def run(self):
        LOG.info("Starting evaluation: seq=%s, label=%s", self.cfg.seq, self.cfg.label)
        start_wall = time.time()

        slam_proc = self.launch_slam()
        player_proc = self.start_player()
        record_proc = self.start_recording()
        odom_proc = self.start_odom_to_tum()

        self.wait_for_player_and_teardown(player_proc, slam_proc, record_proc, odom_proc)

        end_wall = time.time()
        est_tum_ok = self.est_tum.exists() and self.est_tum.stat().st_size > 0

        if est_tum_ok:
            try:
                self._maybe_run_evo()
            except Exception:
                LOG.exception("evo evaluation failed")

        metrics = self.collect_and_write_metrics(start_wall, end_wall)
        LOG.info("Evaluation completed. Logs → %s", self.run_dir)
        return metrics


def run_eval_from_args(args) -> int:
    """Helper: build EvalConfig from argparse args and run the evaluator."""
    cfg = EvalConfig(
        seq=args.seq,
        seq_root=getattr(args, "seq_root", "/data/mulran"),
        rate=args.rate,
        duration=args.duration,
        full_seq=args.full_seq,
        out_root=args.out_root,
        odom_topic=args.odom_topic,
        gt_tum_root=args.gt_tum_root,
        odom_to_tum=args.odom_to_tum,
        record_slack=getattr(args, "record_slack", 10),
        params_file=args.params_file,
        label=args.label,
        sweep_id=getattr(args, "sweep_id", None),
    )
    ev = Evaluator(cfg)
    ev.run()
    return 0
