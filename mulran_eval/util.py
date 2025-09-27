from __future__ import annotations
from pathlib import Path
import hashlib
import re

def sha1_file(p: Path | None) -> str:
    if not p or not p.exists():
        return "default"
    h = hashlib.sha1()
    with p.open("rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()[:8]

_slug_re = re.compile(r"[^a-zA-Z0-9_.-]+")

def slugify(s: str) -> str:
    s = s.strip().replace(" ", "-")
    s = _slug_re.sub("-", s)
    return s.strip("-_")
