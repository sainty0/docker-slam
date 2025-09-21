#!/usr/bin/env python3
"""
Module entrypoint to run the eval_sweep CLI as:
  python -m scripts.eval_sweep ...
"""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
