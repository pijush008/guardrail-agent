"""Structured logfmt logging for agent runs (master §35-36).

Emits one `key=value` line per completed run so operators can grep/parse
guardrail outcomes (blocked, risk, PII redactions, citations, approvals)
without dumping request bodies.
"""
from __future__ import annotations

import sys
import time
from typing import Any

from .models import AgentResult


def _fmt(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    s = str(v)
    if any(ch in s for ch in " \t\"'="):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def log_run(result: AgentResult, *, run_id: str, event: str = "agent.run") -> None:
    """Write one structured line describing an agent run."""
    fields: dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": event,
        "run_id": run_id,
        "blocked": result.blocked,
        "risk": result.risk_label or ("blocked" if result.blocked else "none"),
        "latency_ms": round(result.latency_ms, 1),
        "tokens": result.tokens_total,
        "pii_redactions": result.pii_redactions,
        "citation_valid": result.citation_valid,
        "schema_valid": result.schema_valid,
        "approval": result.pending_action_id or "",
        "executed": result.executed,
    }
    print(" ".join(f"{k}={_fmt(v)}" for k, v in fields.items()), file=sys.stderr)
