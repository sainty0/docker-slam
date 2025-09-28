from __future__ import annotations
import time
import uuid
import shutil
import subprocess
from pathlib import Path
from contextlib import ExitStack
from datetime import datetime, timezone
from .schemas import RunConfig, RunRecord, Params
from .evo_tools import compute_metrics
from .storage import write_run
from .util import sha1_file, slugify


def _read_params_yaml(p: Path | None) -> Params:
    if not p or not p.exists():
        return Params()
    try:
        from ruamel.yaml import YAML as _YAML
        yaml = _YAML(typ="safe")
    except Exception:
        return Params()
    data = yaml.load(p.read_text(encoding="utf-8")) or {}
    # Best-effort extraction; ignores missing keys gracefully
    return Params(
        odometrySurfLeafSize=data.get("odometrySurfLeafSize"),
        mappingCornerLeafSize=data.get("mappingCornerLeafSize"),
        mappingSurfLeafSize=data.get("mappingSurfLeafSize"),
        edgeFeatureMinValidNum=data.get("edgeFeatureMinValidNum"),
        surfFeatureMinValidNum=data.get("surfFeatureMinValidNum"),
        edgeThreshold=data.get("edgeThreshold"),
        surfThreshold=data.get("surfThreshold"),
    )


def run_once(cfg: RunConfig) -> RunRecord:
    ts = datetime.now(timezone.utc)
    param_hash = sha1_file(Path(cfg.params_file) if cfg.params_file else None)

    base = f"{cfg.seq}_{slugify(cfg.label)}_{param_hash}_{ts.strftime('%Y%m%d-%H%M%S')}"
    out_root = Path(cfg.out_root)
    # Ensure out_root exists; if creating an absolute like /output fails (e.g., permissions),
    # fall back to a local ./output[/<suffix>] under the current working directory.
    try:
        out_root.mkdir(parents=True, exist_ok=True)
    except Exception:
        local_base = Path.cwd() / "output"
        try:
            local_base.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        # Preserve the last component (e.g., "results_v8") if provided
        suffix = Path(cfg.out_root).name or "logs"
        out_root = local_base / suffix
        out_root.mkdir(parents=True, exist_ok=True)

    run_dir = out_root / "runs" / base
    logs_dir = run_dir / "logs"
    artifacts_dir = run_dir / "artifacts"
    bags_dir = out_root / "data" / "bags"
    logs_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    bags_dir.mkdir(parents=True, exist_ok=True)

    est_bag = bags_dir / f"{base}.bag"
    est_tum = artifacts_dir / f"{base}.tum"
    gt_tum = Path(cfg.gt_tum_root) / f"{cfg.seq}_gt.tum"

    # Snapshot provided params file for reproducibility
    if cfg.params_file:
        try:
            shutil.copy2(cfg.params_file, run_dir / "params_injected.yaml")
        except Exception:
            pass

    start = time.time()
    status = "ok"

    with ExitStack() as stack:
        # 1) Launch SLAM
        launch_args = [
            "roslaunch", "lio_sam", "run_mulran.launch",
            "use_sim_time:=true",
        ]
        if cfg.params_file:
            launch_args.append(f"params_file:={cfg.params_file}")
        slam_log = (logs_dir / "sc_lio.log").open("w", encoding="utf-8")
        slam = subprocess.Popen(launch_args, stdout=slam_log, stderr=subprocess.STDOUT, text=True)
        stack.callback(lambda: slam.kill())
        time.sleep(5)

        # 2) rosparam dump (best-effort)
        try:
            with (run_dir / "lio_sam_params.yaml").open("w", encoding="utf-8") as f:
                subprocess.run(["rosparam", "get", "/lio_sam"], stdout=f, text=True, check=False)
        except Exception:
            pass

        # 3) Play MulRan
        seq_dir = Path("/data/mulran") / cfg.seq
        player_cmd = ["rosrun", "file_player", "file_player_headless", "--dir", str(seq_dir), "--rate", str(cfg.rate)]
        player_log = (logs_dir / "player.log").open("w", encoding="utf-8")
        if cfg.full_seq:
            player = subprocess.Popen(player_cmd, stdout=player_log, stderr=subprocess.STDOUT, text=True)
        else:
            player = subprocess.Popen(["timeout", "--preserve-status", str(cfg.duration_s), *player_cmd],
                                      stdout=player_log, stderr=subprocess.STDOUT, text=True)
        stack.callback(lambda: player.kill())

        # 4) rosbag record
        record_log = (logs_dir / "record.log").open("w", encoding="utf-8")
        if cfg.full_seq:
            recorder = subprocess.Popen(["rosbag", "record", cfg.odom_topic, "-O", str(est_bag)],
                                        stdout=record_log, stderr=subprocess.STDOUT, text=True)
        else:
            record_secs = cfg.duration_s + 10
            recorder = subprocess.Popen(["rosbag", "record", cfg.odom_topic, f"--duration={record_secs}", "-O", str(est_bag)],
                                        stdout=record_log, stderr=subprocess.STDOUT, text=True)
        stack.callback(lambda: recorder.kill())

        # 5) odom_to_tum converter
        od2_log = (logs_dir / "odom_to_tum.log").open("w", encoding="utf-8")
        od2 = subprocess.Popen(["python3", "-u", cfg.odom_to_tum, "--topic", cfg.odom_topic, "--out", str(est_tum)],
                               stdout=od2_log, stderr=subprocess.STDOUT, text=True)
        stack.callback(lambda: od2.kill())

        # 6) Wait for player to finish and tear down
        player.wait()
        try:
            slam.terminate(); slam.wait(timeout=5)
        except Exception:
            slam.kill()
        if cfg.full_seq:
            try:
                recorder.terminate(); recorder.wait(timeout=5)
            except Exception:
                recorder.kill()
        try:
            od2.terminate(); od2.wait(timeout=5)
        except Exception:
            od2.kill()

    # Metrics
    metrics = None
    if not est_tum.exists() or est_tum.stat().st_size == 0:
        status = "no_tum"
    else:
        metrics = compute_metrics(gt_tum, est_tum, artifacts_dir, logs_dir)
        if metrics is None:
            status = "evo_failed"

    wall = int(time.time() - start)

    # Effective params (prefer the injected snapshot)
    params = _read_params_yaml(run_dir / "params_injected.yaml") if (run_dir / "params_injected.yaml").exists() else _read_params_yaml(Path(cfg.params_file) if cfg.params_file else None)

    rec = RunRecord(
        run_id=str(uuid.uuid4()),
        timestamp=ts,
        status=status,
        wall_time_s=wall,
        run_dir=str(run_dir),
        est_bag=str(est_bag),
        est_tum=str(est_tum),
        gt_tum=str(gt_tum),
        params_sha1=param_hash,
        cfg=cfg,
        params=params,
        metrics=metrics,
    )
    write_run(rec, out_root)
    return rec
