"""
eval_sweep package

This package splits the original large script into tidy modules:
  - utils.py       : helper utilities
  - eval_runner.py : EvalConfig + Evaluator implementation
  - sweep.py       : sweep orchestration and aggregation
  - cli.py         : CLI wiring and entrypoint

Importing `main` from this package provides the CLI entrypoint.
"""
from .cli import main  # re-export the CLI entrypoint

__all__ = ["main"]
