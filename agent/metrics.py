"""Metrics collector: aggregates per-run results into a JSON report."""
from __future__ import annotations

import json
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any


class MetricsCollector:
    def __init__(self, out_dir: str = "reports"):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.rows: list[dict[str, Any]] = []

    def add(self, case_id: str, category: str, metrics: dict[str, Any],
            passed: bool, fail_reason: str = "", extra: dict[str, Any] | None = None) -> None:
        self.rows.append({
            "case_id": case_id,
            "category": category,
            "passed": passed,
            "fail_reason": fail_reason,
            **metrics,
            **(extra or {}),
        })

    def summarize(self) -> dict[str, Any]:
        if not self.rows:
            return {"n": 0}
        total = len(self.rows)
        passed = sum(1 for r in self.rows if r["passed"])
        latencies = [r.get("latency_ms", 0.0) for r in self.rows]
        tokens = [r.get("tokens", 0) for r in self.rows]

        blocked = [r for r in self.rows if r.get("blocked")]
        adversarial = [r for r in self.rows if r.get("category") == "adversarial"]
        adv_attacks = sum(1 for r in adversarial if r.get("attack"))
        adv_blocked = sum(1 for r in adversarial if r.get("blocked"))
        by_cat: dict[str, dict[str, Any]] = {}
        for cat in {r["category"] for r in self.rows}:
            cat_rows = [r for r in self.rows if r["category"] == cat]
            cat_passed = sum(1 for r in cat_rows if r["passed"])
            by_cat[cat] = {"n": len(cat_rows), "passed": cat_passed,
                           "pass_rate": 100.0 * cat_passed / len(cat_rows)}

        def _rate(key: str) -> float | None:
            vals = [r.get(key) for r in self.rows if key in r and r.get(key) is not None]
            return round(100.0 * sum(1 for v in vals if v) / len(vals), 2) if vals else None

        citation_validity = _rate("citation_valid")
        schema_validity = _rate("schema_valid")
        tool_success = _rate("tool_success")
        executed = [r for r in self.rows if r.get("executed")]
        pending_created = [r for r in self.rows if r.get("pending_created")]
        approval_compliance = _rate("approval_compliant")
        total_redactions = sum(r.get("pii_redactions", 0) for r in self.rows)

        return {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "n": total,
            "passed": passed,
            "pass_rate": round(100.0 * passed / total, 2),
            "accuracy": round(100.0 * passed / total, 2),
            "blocked_count": len(blocked),
            "refusal_rate": {
                "n": len(adversarial),
                "attacks": adv_attacks,
                "blocked": adv_blocked,
                "rate": round(100.0 * adv_blocked / adv_attacks, 2) if adv_attacks else None,
            },
            "citation_validity": citation_validity,
            "schema_validity": schema_validity,
            "tool_success_rate": tool_success,
            "pii_redactions": total_redactions,
            "approval": {
                "executed": len(executed),
                "pending_created": len(pending_created),
                "compliance_rate": approval_compliance,
            },
            "latency": {
                "avg": round(statistics.mean(latencies), 1),
                "p50": round(_percentile(latencies, 50), 1),
                "p95": round(_percentile(latencies, 95), 1),
                "max": round(max(latencies), 1),
            },
            "tokens": {
                "avg": round(statistics.mean(tokens), 1),
                "total": sum(tokens),
            },
            "category_breakdown": by_cat,
        }

    def save_rows(self, name: str = "eval_rows.json") -> Path:
        p = self.out_dir / name
        p.write_text(json.dumps(self.rows, indent=2))
        return p

    def save_summary(self, name: str = "eval_summary.json") -> Path:
        p = self.out_dir / name
        p.write_text(json.dumps(self.summarize(), indent=2))
        return p


def _percentile(values, q) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * q / 100.0
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)