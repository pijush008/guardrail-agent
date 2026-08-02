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
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent.agent import GuardrailAgent
from agent.db import default_store
from agent.permission import ApprovalManager, PermissionLayer
from agent.llm import LLMClient
from agent.models import AgentResult
from agent.pdf import MAX_PDF_BYTES, PdfExtractionError, extract_pdf_text

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
    expected_keys: Optional[list[str]] = None


class DecideRequest(BaseModel):
    status: str  # "approved" | "denied"
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
    return _serialize(result)


@app.post("/api/v1/chat/upload")
def chat_upload(question: str = Form(...),
                file: UploadFile | None = File(None)):
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
    return _serialize(result)


# ---------------------------------------------------------------------------
# Approvals (human-in-the-loop)
# ---------------------------------------------------------------------------

@app.get("/api/v1/pending_actions")
def pending_actions(status: Optional[str] = None):
    return _store.list_pending_actions(status=status)


@app.post("/api/v1/pending_actions/{row_id}/decide")
def decide(row_id: str, req: DecideRequest):
    if req.status not in ("approved", "denied"):
        raise HTTPException(400, "status must be 'approved' or 'denied'")
    row = _store.get_pending_action(row_id)
    if not row:
        raise HTTPException(404, "pending action not found")
    if row.get("status") != "pending":
        raise HTTPException(409, f"action already decided ({row.get('status')})")

    payload = _parse_plan(row["plan"])
    token = payload.get("token")
    if not token:
        raise HTTPException(500, "pending action is missing its approval token")

    approved = req.status == "approved"
    rec = None
    if approved:
        try:
            rec = _approvals.approve(token, req.decided_by)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(409, f"approval token already used or unknown: {exc}")
    else:
        try:
            rec = _approvals.deny(token, req.decided_by)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(409, f"approval token already used or unknown: {exc}")

    _store.decide_pending_action(row_id, req.status, req.decided_by)

    outcome = None
    if approved:
        try:
            outcome = _agent.permission.execute(
                payload["tool"], payload["action"], payload["subject"], rec)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"action failed after approval: {exc}")

    return {
        "id": row_id,
        "status": req.status,
        "decided_by": req.decided_by,
        "outcome": outcome,
    }


def _parse_plan(plan: str) -> dict:
    try:
        data = json.loads(plan)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    raise HTTPException(500, "pending action plan is not valid JSON")


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
