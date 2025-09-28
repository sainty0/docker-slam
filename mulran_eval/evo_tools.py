from __future__ import annotations
import json
import subprocess
import zipfile
from pathlib import Path
from typing import Optional
from .schemas import Metrics


def _run(cmd: list[str], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    log_path.write_text(p.stdout, encoding="utf-8")
    return p.returncode


def _parse_result_zip(zip_path: Path) -> dict:
    if not zip_path.exists():
        return {}
    with zipfile.ZipFile(zip_path, "r") as zf:
        # First JSON entry wins
        for name in zf.namelist():
            if name.endswith(".json"):
                try:
                    return json.loads(zf.read(name).decode("utf-8"))
                except Exception:
                    return {}
    return {}


def _rmse(d: dict, key: str = "rmse") -> Optional[float]:
    try:
        return float(d.get("statistics", {}).get(key))
    except Exception:
        return None


def compute_metrics(gt_tum: Path, est_tum: Path, out_dir: Path, log_dir: Optional[Path] = None) -> Optional[Metrics]:
    """Run evo_* tools and parse structured results from the saved ZIPs."""
    out_dir.mkdir(parents=True, exist_ok=True)
    L = log_dir or out_dir

    ape_zip = out_dir / "ape.zip"
    rpe_1m_zip = out_dir / "rpe_trans_1m.zip"
    rpe_1s_zip = out_dir / "rpe_trans_1s.zip"
    rpe_rot_zip = out_dir / "rpe_rot_1s.zip"

    # APE
    _run([
        "evo_ape", "tum", str(gt_tum), str(est_tum), "-va",
        "--save_results", str(ape_zip),
        "--save_plot", str(out_dir/"ape.png"),
    ], L/"evo_ape.log")

    # RPE 1m
    _run([
        "evo_rpe", "tum", str(gt_tum), str(est_tum), "-va",
        "-r", "trans_part", "--delta", "1", "--delta_unit", "m",
        "--save_results", str(rpe_1m_zip),
        "--save_plot", str(out_dir/"rpe_trans_1m.png"),
    ], L/"evo_rpe_trans_1m.log")

    # RPE 1s
    _run([
        "evo_rpe", "tum", str(gt_tum), str(est_tum), "-va",
        "-r", "trans_part", "--delta", "1", "--delta_unit", "s",
        "--save_results", str(rpe_1s_zip),
        "--save_plot", str(out_dir/"rpe_trans_1s.png"),
    ], L/"evo_rpe_trans_1s.log")

    # RPE rot 1s
    _run([
        "evo_rpe", "tum", str(gt_tum), str(est_tum), "-va",
        "-r", "angle_deg", "--delta", "1", "--delta_unit", "s",
        "--save_results", str(rpe_rot_zip),
        "--save_plot", str(out_dir/"rpe_rot_1s.png"),
    ], L/"evo_rpe_rot_1s.log")

    A = _parse_result_zip(ape_zip)
    T1M = _parse_result_zip(rpe_1m_zip)
    T1S = _parse_result_zip(rpe_1s_zip)
    ROT = _parse_result_zip(rpe_rot_zip)

    if not A and not T1M and not T1S and not ROT:
        return None

    return Metrics(
        ape_rmse_m=_rmse(A),
        ape_sse=_rmse(A, "sse"),
        rpe_trans_1m_rmse_m=_rmse(T1M),
        rpe_trans_1s_rmse_m=_rmse(T1S),
        rpe_rot_1s_rmse_deg=_rmse(ROT),
    )
