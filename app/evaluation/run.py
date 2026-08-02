"""Canonical entry point for the eval suite (master §35-36).

Usage:
    python -m app.evaluation.run --min-pass 80 --outdir reports

Delegates to the canonical runner so both spellings behave identically:
    python -m evals.eval_runner
"""
from __future__ import annotations

import sys


def main() -> int:
    from evals.eval_runner import main as _runner_main

    return _runner_main()


if __name__ == "__main__":
    sys.exit(main())
