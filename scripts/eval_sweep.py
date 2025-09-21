#!/usr/bin/env python3
"""
Thin wrapper kept for backward compatibility.

This forwards to the modular eval_sweep package CLI located at scripts/eval_sweep/.
You can now run either:
  - python3 scripts/eval_sweep.py eval ...
  - python3 -m scripts.eval_sweep eval ...
"""
from scripts.eval_sweep.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
