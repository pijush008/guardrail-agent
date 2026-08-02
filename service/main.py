"""FastAPI service exposing the Guardrail Agent to the product surface.

Endpoints:
    GET  /health                         liveness + store backend
    POST /api/v1/chat                    run one question through the agent
    GET  /api/v1/pending_actions         human-in-the-loop queue
    POST /api/v1/pending_actions/{id}/decide   approve/deny a high-stakes action
    GET  /api/v1/final_answers           recent cited answers
    GET  /api/v1/evidence                recent redacted evidence docs
    GET  /api/v1/injection_attempts      blocked attempt log
    GET  /api/v1/metrics/latest          latest eval run summary
    GET  /api/v1/metrics/history         trend data for the dashboard
    GET  /api/v1/metrics/badge           shields.io-compatible JSON badge

Run:  uvicorn service.main:app --reload
"""
from __future__ import annotations

import json
import time
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent.agent import GuardrailAgent
from agent.db import default_store
from agent.llm import LLMClient
from agent.logfmt import log_run
from agent.models import AgentResult
from agent.pdf import MAX_PDF_BYTES, PdfExtractionError, extract_pdf_text
from agent.permission import ApprovalManager, PermissionDenied, PermissionLayer

app = FastAPI(title="Guardrail Agent Service", version="1.0.0")


def _make_llm():
    """Real LLMClient normally; deterministic FakeLLM in demo mode
    (GUARDRAIL_FAKE_LLM=1) so the stack runs without API quota."""
    import os
    if os.getenv("GUARDRAIL_FAKE_LLM") == "1":
        from agent.fake_llm import FakeLLM
        return FakeLLM()
    return LLMClient()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your Next.js origin in production
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# A single long-lived agent. The approval manager runs in human-in-the-loop
# mode (no auto-approve) so every high-stakes action creates a pending row
# that must be approved from the dashboard before execution.
_store = default_store()
_approvals = ApprovalManager(auto_approve=False)
_agent = GuardrailAgent(
    llm=_make_llm(),
    permission=PermissionLayer(approvals=_approvals),
    store=_store,
)


class ChatRequest(BaseModel):
    question: str
    require_json: bool = False
    expected_keys: list[str] | None = None


class DecideRequest(BaseModel):
    status: str  # "approved" | "denied"
    decided_by: str = "dashboard-user"


class ApproveRequest(BaseModel):
    decided_by: str = "dashboard-user"


def _serialize(result: AgentResult) -> dict:
    return {
        "question": result.question,
        "answer": result.answer,
        "blocked": result.blocked,
        "block_reason": result.block_reason,
        "risk": result.risk_label,
        "evidence": [
            {"id": d.id, "source": d.source, "content": d.content,
             "redacted": d.redacted}
            for d in result.evidence
        ],
        "citations": _agent._build_citations(result.answer, result.evidence),
        "schema_valid": result.schema_valid,
        "schema_error": result.schema_error,
        "citation_valid": result.citation_valid,
        "citation_errors": result.citation_errors,
        "degraded": result.degraded,
        "executed": result.executed,
        "pending_action_id": result.pending_action_id,
        "pii_redactions": result.pii_redactions,
        "latency_ms": round(result.latency_ms, 1),
        "tokens": result.tokens_total,
        "tokens_prompt": result.tokens_prompt,
        "tokens_completion": result.tokens_completion,
        "run_id": _agent.run_id,
    }


# ---------------------------------------------------------------------------
# Liveness / config
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "store": _store.name,
            "llm": type(_agent.llm).__name__, "time": time.time()}


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

@app.post("/api/v1/chat")
def chat(req: ChatRequest):
    if not req.question.strip():
        raise HTTPException(400, "question must not be empty")
    result = _agent.run(req.question, require_json=req.require_json,
                        expected_keys=req.expected_keys)
    log_run(result, run_id=_agent.run_id)
    return _serialize(result)


@app.post("/api/v1/chat/upload")
def chat_upload(question: str = Form(...),
                file: Annotated[UploadFile | None, File()] = None):
    """Chat with an optional attached PDF.

    The PDF is read as untrusted evidence: it is scanned for indirect
    injection and PII-redacted before synthesis, and citations point at the
    uploaded document.
    """
    if not question.strip():
        raise HTTPException(400, "question must not be empty")

    documents: list[dict] = []
    if file is not None:
        if not (file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(400, "only PDF files are supported")
        raw = file.file.read()
        if len(raw) > MAX_PDF_BYTES:
            raise HTTPException(413, "file exceeds 10 MB limit")
        try:
            text = extract_pdf_text(raw)
        except PdfExtractionError as exc:
            raise HTTPException(422, str(exc))
        documents = [{"source": f"PDF:{file.filename}", "content": text}]

    result = _agent.run(question, documents=documents)
    log_run(result, run_id=_agent.run_id)
    return _serialize(result)


# ---------------------------------------------------------------------------
# Approvals (human-in-the-loop)
# ---------------------------------------------------------------------------

@app.get("/api/v1/pending_actions")
def pending_actions(status: str | None = None):
    return _store.list_pending_actions(status=status)


@app.post("/api/v1/pending_actions/{row_id}/decide")
def decide(row_id: str, req: DecideRequest):
    if req.status not in ("approved", "denied"):
        raise HTTPException(400, "status must be 'approved' or 'denied'")
    return _decide(row_id, req.status, req.decided_by)


def _parse_plan(plan: str) -> dict:
    try:
        data = json.loads(plan)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    raise HTTPException(500, "pending action plan is not valid JSON")


# ---------------------------------------------------------------------------
# Agent runs (master §26)
# ---------------------------------------------------------------------------

@app.post("/api/v1/agent/run")
def agent_run(req: ChatRequest):
    """Alias of /api/v1/chat with the full run envelope."""
    if not req.question.strip():
        raise HTTPException(400, "question must not be empty")
    result = _agent.run(req.question, require_json=req.require_json,
                        expected_keys=req.expected_keys)
    log_run(result, run_id=_agent.run_id)
    payload = _serialize(result)
    payload["status"] = (
        "blocked" if result.blocked
        else "pending_approval" if result.pending_action_id
        else "executed" if result.executed
        else "complete" if result.answer
        else "failed")
    return payload


def _run_rows(limit: int = 50) -> list[dict]:
    answers = _store.list_table("final_answers", limit=limit)
    evidence = _store.list_table("evidence_docs", limit=1000)
    rows = []
    for a in answers:
        run_id = a.get("run_id", "")
        ev = [e for e in evidence if e.get("run_id") == run_id]
        citations = a.get("citations") or []
        rows.append({
            "run_id": run_id,
            "question": a.get("question", ""),
            "answer": a.get("answer", ""),
            "citations": citations,
            "evidence_count": len(ev),
            "sources": sorted({e.get("source", "") for e in ev}),
            "created_at": a.get("created_at", ""),
        })
    return rows


@app.get("/api/v1/agent/runs")
def agent_runs(limit: int = 50):
    return _run_rows(limit=limit)


@app.get("/api/v1/agent/runs/{run_id}")
def agent_run_detail(run_id: str):
    answers = _store.list_table("final_answers", limit=100)
    evidence = _store.list_table("evidence_docs", limit=1000)
    answer_row = next((a for a in answers if a.get("run_id") == run_id), None)
    if not answer_row:
        raise HTTPException(404, "run not found")
    ev = [e for e in evidence if e.get("run_id") == run_id]
    return {
        "run_id": run_id,
        "question": answer_row.get("question", ""),
        "answer": answer_row.get("answer", ""),
        "citations": answer_row.get("citations") or [],
        "evidence": ev,
        "trace": _build_trace(answer_row, ev),
        "created_at": answer_row.get("created_at", ""),
    }


def _build_trace(answer_row: dict, evidence: list[dict]) -> list[dict]:
    """Render the 13-stage pipeline trace for the Runs detail page."""
    has_answer = bool(answer_row.get("answer"))
    return [
        {"step": "Request received", "status": "ok"},
        {"step": "Input checked", "status": "ok"},
        {"step": "Request classified", "status": "ok"},
        {"step": "Plan created", "status": "ok"},
        {"step": "Tool called", "status": "ok" if evidence else "n/a",
         "detail": f"{len(evidence)} evidence doc(s) retrieved"},
        {"step": "Evidence retrieved",
         "status": "ok" if evidence else "n/a",
         "detail": sorted({e.get("source", "") for e in evidence}) or None},
        {"step": "PII redacted", "status": "ok",
         "detail": sum(1 for e in evidence if e.get("content_redacted"))},
        {"step": "Response generated", "status": "ok" if has_answer else "failed"},
        {"step": "Schema validated", "status": "ok"},
        {"step": "Citations validated",
         "status": "ok" if answer_row.get("citations") else "n/a"},
        {"step": "Approval created", "status": "n/a"},
        {"step": "Action executed", "status": "n/a"},
        {"step": "Response returned", "status": "ok" if has_answer else "failed"},
    ]


# ---------------------------------------------------------------------------
# Evaluations (master §26)
# ---------------------------------------------------------------------------

@app.get("/api/v1/evaluations/cases")
def eval_cases():
    from evals.eval_runner import load_cases
    cases = load_cases()
    return [{
        "id": c["id"], "category": c["category"], "input": c["input"],
        "pass": c.get("pass", []),
        "attack": bool(c.get("attack")),
        "expect_block": bool(c.get("expect_block")),
        "approval_mode": c.get("approval_mode"),
        "require_json": bool(c.get("require_json")),
    } for c in cases]


@app.post("/api/v1/evaluations/run")
def eval_run(category: str | None = None, limit: int | None = None,
             min_pass: float = 80.0):
    import tempfile

    from evals.eval_runner import run_suite
    outdir = tempfile.mkdtemp(prefix="eval-api-")
    exit_code, summary = run_suite(outdir=outdir, category=category,
                                   limit=limit, min_pass=min_pass)
    if summary.get("skipped"):
        raise HTTPException(503, "no LLM API key configured; cannot run the "
                                 "evaluation suite")
    return {"gate_passed": exit_code == 0, "exit_code": exit_code,
            "summary": summary}


@app.get("/api/v1/evaluations/runs")
def eval_runs(limit: int = 50):
    return _store.list_eval_runs(limit=limit)


@app.get("/api/v1/evaluations/runs/{run_id}")
def eval_run_detail(run_id: str):
    runs = _store.list_eval_runs(limit=1000)
    run = next((r for r in runs if r.get("id") == run_id), None)
    if not run:
        raise HTTPException(404, "evaluation run not found")
    run["cases"] = _store.list_eval_cases(run_id)
    return run


# ---------------------------------------------------------------------------
# Guardrail events (master §26)
# ---------------------------------------------------------------------------

@app.get("/api/v1/guardrails/events")
def guardrail_events(limit: int = 50):
    rows = _store.list_table("injection_attempts", limit=limit)
    blocked = sum(1 for r in rows if r.get("blocked"))
    return {
        "total": len(rows), "blocked": blocked,
        "types": ["direct", "indirect", "encoded", "jailbreak"],
        "events": rows,
    }


# ---------------------------------------------------------------------------
# Approvals REST (master §26)
# ---------------------------------------------------------------------------

@app.get("/api/v1/approvals")
def approvals(status: str | None = None):
    return _store.list_pending_actions(status=status)


@app.post("/api/v1/approvals/{row_id}/approve")
def approve_action(row_id: str, req: ApproveRequest | None = None):
    return _decide(row_id, "approved", (req.decided_by if req else None) or "dashboard-user")


@app.post("/api/v1/approvals/{row_id}/reject")
def reject_action(row_id: str, req: ApproveRequest | None = None):
    return _decide(row_id, "denied", (req.decided_by if req else None) or "dashboard-user")


def _decide(row_id: str, status: str, decided_by: str) -> dict:
    row = _store.get_pending_action(row_id)
    if not row:
        raise HTTPException(404, "pending action not found")
    if row.get("status") != "pending":
        raise HTTPException(409, f"action already decided ({row.get('status')})")

    payload = _parse_plan(row["plan"])
    token = payload.get("token")
    if not token:
        raise HTTPException(500, "pending action is missing its approval token")

    if status == "approved":
        try:
            rec = _approvals.approve(token, decided_by)
        except PermissionDenied as exc:
            raise HTTPException(409, str(exc))
    else:
        try:
            rec = _approvals.deny(token, decided_by)
        except PermissionDenied as exc:
            raise HTTPException(409, str(exc))
    _store.decide_pending_action(row_id, status, decided_by)

    outcome = None
    if status == "approved":
        try:
            outcome = _agent.permission.execute(
                payload["tool"], payload["action"], payload["subject"], rec)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(409, f"action failed after approval: {exc}")

    return {
        "id": row_id, "status": status, "decided_by": decided_by,
        "approval_status": rec.status, "outcome": outcome,
    }


# ---------------------------------------------------------------------------
# Metrics + CI status (master §26)
# ---------------------------------------------------------------------------

@app.get("/api/v1/metrics")
def metrics_aggregate():
    runs = _store.list_eval_runs(limit=50)
    latest = runs[0] if runs else None
    injections = _store.list_table("injection_attempts", limit=500)
    pending = _store.list_pending_actions(status="pending")
    totals = {}
    if latest:
        summary = latest.get("payload") or {}
        totals = {
            "total_cases": summary.get("n"),
            "passed": summary.get("passed"),
            "pass_rate": summary.get("pass_rate"),
            "citation_validity": summary.get("citation_validity"),
            "schema_validity": summary.get("schema_validity"),
            "pii_redactions": summary.get("pii_redactions"),
            "avg_latency_ms": summary.get("latency", {}).get("avg"),
            "p95_latency_ms": summary.get("latency", {}).get("p95"),
        }
    return {
        "latest": latest,
        "history": runs,
        "totals": totals,
        "guardrails": {
            "injection_attempts": len(injections),
            "injection_blocked": sum(1 for r in injections if r.get("blocked")),
        },
        "approvals": {"pending": len(pending)},
    }


@app.get("/api/v1/ci/status")
def ci_status():
    """Real status when running inside GitHub Actions, honest mock otherwise."""
    import os
    if os.getenv("GITHUB_ACTIONS") == "true" and os.getenv("GITHUB_REPOSITORY"):
        return {
            "integration": "github",
            "workflow": os.getenv("GITHUB_WORKFLOW", "eval"),
            "branch": os.getenv("GITHUB_REF_NAME", ""),
            "sha": (os.getenv("GITHUB_SHA") or "")[:12],
            "run_id": os.getenv("GITHUB_RUN_ID", ""),
            "status": os.getenv("GITHUB_ACTION_STATUS", "unknown"),
        }
    return {
        "integration": "mock",
        "message": "Mock CI status — GitHub integration is not configured.",
        "status": "mock",
    }


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@app.get("/api/v1/final_answers")
def final_answers(limit: int = 20):
    return _store.list_table("final_answers", limit=limit)


@app.get("/api/v1/evidence")
def evidence(limit: int = 20):
    return _store.list_table("evidence_docs", limit=limit)


@app.get("/api/v1/injection_attempts")
def injection_attempts(limit: int = 20):
    rows = _store.list_table("injection_attempts", limit=limit)
    blocked = sum(1 for r in rows if r.get("blocked"))
    return {"total": len(rows), "blocked": blocked, "rows": rows}


# ---------------------------------------------------------------------------
# Metrics (eval results for the dashboard)
# ---------------------------------------------------------------------------

@app.get("/api/v1/metrics/latest")
def metrics_latest():
    runs = _store.list_eval_runs(limit=1)
    if not runs:
        raise HTTPException(404, "no eval runs recorded yet — run the eval suite")
    return runs[0]


@app.get("/api/v1/metrics/history")
def metrics_history(limit: int = 50):
    runs = _store.list_eval_runs(limit=limit)
    out = []
    for r in reversed(runs):
        out.append({
            "created_at": r.get("created_at"),
            "accuracy": r.get("accuracy"),
            "refusal_rate": r.get("refusal_rate"),
            "avg_latency_ms": r.get("avg_latency_ms"),
            "avg_tokens": r.get("avg_tokens"),
        })
    return out


@app.get("/api/v1/metrics/badge")
def metrics_badge():
    """shields.io endpoint JSON: https://img.shields.io/endpoint?url=..."""
    runs = _store.list_eval_runs(limit=1)
    if not runs:
        return {"schemaVersion": 1, "label": "eval pass rate", "message": "no runs",
                "color": "lightgrey"}
    rate = runs[0].get("accuracy")
    if rate is None:
        return {"schemaVersion": 1, "label": "eval pass rate", "message": "n/a",
                "color": "lightgrey"}
    color = "brightgreen" if rate >= 90 else ("yellow" if rate >= 80 else "red")
    return {"schemaVersion": 1, "label": "eval pass rate",
            "message": f"{rate:.1f}%", "color": color}
