#!/usr/bin/env python3
"""Publish the latest eval summary as a shield the README can reference.

Writes `results/badge.json` (shields.io endpoint format) and regenerates
`results/README.md` with a badge URL pointing at the raw JSON on GitHub so
the pass rate badge updates after every CI run:

    https://img.shields.io/endpoint?url=<raw badge.json URL>

Usage:
    python scripts/publish_badge.py reports/eval_summary.json results/README.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _color(rate: float) -> str:
    if rate >= 90:
        return "brightgreen"
    if rate >= 80:
        return "yellow"
    if rate >= 60:
        return "orange"
    return "red"


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    summary_path = Path(sys.argv[1])
    readme_path = Path(sys.argv[2])
    out_dir = readme_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = json.loads(summary_path.read_text())
    rate = float(summary.get("pass_rate", 0.0))
    refusal = summary.get("refusal_rate", {}) or {}
    n = int(summary.get("n", 0))
    badge = {
        "schemaVersion": 1,
        "label": "eval pass rate",
        "message": f"{rate:.1f}%",
        "color": _color(rate),
    }
    badge_path = out_dir / "badge.json"
    badge_path.write_text(json.dumps(badge))

    raw_url = "https://raw.githubusercontent.com/<ORG>/<REPO>/results/badge.json"
    readme_path.write_text(
        f"# Latest eval results\n\n"
        f"Pass rate: **{rate:.1f}%** ({summary.get('passed', 0)}/{n} cases)\n\n"
        f"Refusal rate: **{refusal.get('rate')}%** "
        f"({refusal.get('blocked', 0)}/{refusal.get('attacks', 0)} attacks blocked)\n\n"
        f"![eval pass rate]({raw_url})\n"
        f"![shield](https://img.shields.io/endpoint?url={raw_url})\n\n"
        f"Full JSON: `eval_summary.json`\n"
    )
    print(f"wrote {badge_path}")
    print(f"wrote {readme_path}")
    print(f"Badge: https://img.shields.io/endpoint?url={raw_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
