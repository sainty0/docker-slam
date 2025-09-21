"""
Utility helpers for eval_sweep package.
"""
from __future__ import annotations
import logging
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional, Sequence

LOG = logging.getLogger("eval_sweep.utils")


def which_or_raise(name: str) -> str:
    """Return path to executable or raise RuntimeError."""
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Required executable not found in PATH: {name}")
    return path


def safe_label(label: str) -> str:
    """Produce a filesystem-safe label from an arbitrary string."""
    s = re.sub(r"[^A-Za-z0-9._+%-]+", "_", label)
    s = re.sub(r"^_+|_+$", "", s)
    return s.replace(".", "p")


def now_timestamp() -> str:
    """Human readable timestamp used for run ids."""
    return time.strftime("%Y%m%d-%H%M%S")


def run_subprocess_background(cmd: Sequence[str], stdout_path: Path, env: Optional[Dict] = None) -> subprocess.Popen:
    """
    Launch a subprocess in the background, streaming stdout+stderr to a log file.
    Returns the Popen instance.
    """
    LOG.debug("Launching: %s", " ".join(map(str, cmd)))
    f = stdout_path.open("wb")
    proc = subprocess.Popen(list(map(str, cmd)), stdout=f, stderr=subprocess.STDOUT, env=env)
    return proc


def run_subprocess_capture(cmd: Sequence[str], cwd: Optional[Path] = None, check: bool = False) -> subprocess.CompletedProcess:
    """Run a subprocess and capture stdout/stderr (blocking)."""
    LOG.debug("Running (capture): %s", " ".join(map(str, cmd)))
    return subprocess.run(list(map(str, cmd)), cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=check, text=True)


def parse_evo_log_for_metric(log_path: Path, key: str = "rmse") -> Optional[float]:
    """
    Extract the last numeric value from evo logs where a line contains `key`.
    Example lines from evo output are searched and last numeric token is picked.
    """
    if not log_path.exists():
        return None
    last_val = None
    pattern = re.compile(rf"(?i)\b{re.escape(key)}\b[^\d\-+]*([0-9]*\.?[0-9]+(?:[eE][+\-]?\d+)?)")
    try:
        with log_path.open("r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                m = pattern.search(line)
                if m:
                    try:
                        last_val = float(m.group(1))
                    except Exception:
                        pass
    except Exception:
        return None
    return last_val
