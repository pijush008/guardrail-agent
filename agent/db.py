"""Persistence layer: Supabase/Postgres in production, local JSON fallback.

Both halves of the system (Python agent + Next.js surface) read and write
the same tables:
    evidence_docs, final_answers, pending_actions,
    eval_runs, eval_cases, injection_attempts

The store is chosen at import time via env vars. When SUPABASE_URL +
SUPABASE_SERVICE_KEY are present we use SupabaseStore (REST over httpx,
no extra SDK). Otherwise we use LocalStore, which persists to JSON files so
the whole system works offline for tests and local dev.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx

from .config import get_settings


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class StoreError(RuntimeError):
    pass


class Store:
    """Interface implemented by SupabaseStore and LocalStore."""

    name: str = "base"

    def save_evidence(self, docs: list[dict], run_id: str) -> list[str]:
        raise NotImplementedError

    def save_final_answer(self, question: str, answer: str, citations: list[dict],
                          run_id: str) -> str:
        raise NotImplementedError

    def create_pending_action(self, payload: dict) -> str:
        raise NotImplementedError

    def get_pending_action(self, row_id: str) -> Optional[dict]:
        raise NotImplementedError

    def decide_pending_action(self, row_id: str, status: str, decided_by: str) -> bool:
        raise NotImplementedError

    def list_pending_actions(self, status: Optional[str] = None) -> list[dict]:
        raise NotImplementedError

    def log_injection_attempt(self, input_text: str, blocked: bool) -> None:
        raise NotImplementedError

    def save_eval_run(self, summary: dict) -> str:
        raise NotImplementedError

    def save_eval_cases(self, run_id: str, rows: list[dict]) -> None:
        raise NotImplementedError

    def list_eval_runs(self, limit: int = 50) -> list[dict]:
        raise NotImplementedError

    def list_eval_cases(self, run_id: str, limit: int = 200) -> list[dict]:
        raise NotImplementedError

    def list_table(self, table: str, limit: int = 50) -> list[dict]:
        raise NotImplementedError

    def ping(self) -> dict:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Supabase (Postgres) store via REST
# ---------------------------------------------------------------------------

@dataclass
class SupabaseStore(Store):
    url: str = ""
    key: str = ""
    name: str = "supabase"

    def __post_init__(self):
        self.url = self.url or __import__("os").getenv("SUPABASE_URL", "")
        self.key = self.key or (__import__("os").getenv("SUPABASE_SERVICE_KEY")
                                or __import__("os").getenv("SUPABASE_ANON_KEY", ""))
        if not self.url or not self.key:
            raise StoreError("SUPABASE_URL and SUPABASE_SERVICE_KEY required")
        self.url = self.url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.url + "/rest/v1",
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            timeout=15.0,
        )

    def _post(self, table: str, payload: list[dict] | dict) -> list[dict]:
        try:
            resp = self._client.post(f"/{table}", json=payload)
        except httpx.HTTPError as exc:
            raise StoreError(f"supabase {table} write failed: {exc}") from exc
        if resp.status_code >= 400:
            raise StoreError(f"supabase {table} write failed: {resp.status_code} {resp.text[:300]}")
        return resp.json()

    def _get(self, table: str, params: dict | None = None) -> list[dict]:
        try:
            resp = self._client.get(f"/{table}", params=params or {})
        except httpx.HTTPError as exc:
            raise StoreError(f"supabase {table} read failed: {exc}") from exc
        if resp.status_code >= 400:
            raise StoreError(f"supabase {table} read failed: {resp.status_code} {resp.text[:300]}")
        return resp.json()

    def _patch(self, table: str, row_id: str, payload: dict) -> list[dict]:
        try:
            resp = self._client.patch(f"/{table}", params={"id": f"eq.{row_id}"}, json=payload)
        except httpx.HTTPError as exc:
            raise StoreError(f"supabase {table} update failed: {exc}") from exc
        if resp.status_code >= 400:
            raise StoreError(f"supabase {table} update failed: {resp.status_code} {resp.text[:300]}")
        return resp.json()

    def save_evidence(self, docs: list[dict], run_id: str) -> list[str]:
        rows = [{**d, "run_id": run_id, "content_redacted": d.pop("content", "")}
                for d in docs]
        if not rows:
            return []
        out = self._post("evidence_docs", rows)
        return [str(r["id"]) for r in out]

    def save_final_answer(self, question: str, answer: str, citations: list[dict],
                          run_id: str) -> str:
        out = self._post("final_answers", {
            "question": question, "answer": answer, "citations": citations,
            "run_id": run_id,
        })
        return str(out[0]["id"])

    def create_pending_action(self, payload: dict) -> str:
        out = self._post("pending_actions", payload)
        return str(out[0]["id"])

    def get_pending_action(self, row_id: str) -> Optional[dict]:
        rows = self._get("pending_actions", {"id": f"eq.{row_id}", "select": "*"})
        return rows[0] if rows else None

    def decide_pending_action(self, row_id: str, status: str, decided_by: str) -> bool:
        out = self._patch("pending_actions", row_id, {
            "status": status, "decided_at": _now(), "decided_by": decided_by,
        })
        return bool(out)

    def list_pending_actions(self, status: Optional[str] = None) -> list[dict]:
        params: dict[str, Any] = {"select": "*", "order": "created_at.desc"}
        if status:
            params["status"] = f"eq.{status}"
        return self._get("pending_actions", params)

    def log_injection_attempt(self, input_text: str, blocked: bool) -> None:
        self._post("injection_attempts", {
            "input": input_text[:2000], "blocked": blocked,
        })

    def save_eval_run(self, summary: dict) -> str:
        refusal = summary.get("refusal_rate", {})
        out = self._post("eval_runs", {
            "accuracy": summary.get("accuracy"),
            "refusal_rate": refusal.get("rate"),
            "avg_latency_ms": summary.get("latency", {}).get("avg"),
            "avg_tokens": summary.get("tokens", {}).get("avg"),
        })
        return str(out[0]["id"])

    def save_eval_cases(self, run_id: str, rows: list[dict]) -> None:
        payload = [{
            "run_id": run_id,
            "category": r.get("category"),
            "input": r.get("input", ""),
            "passed": bool(r.get("passed")),
            "latency_ms": r.get("latency_ms"),
            "tokens": r.get("tokens"),
        } for r in rows]
        if payload:
            self._post("eval_cases", payload)

    def list_eval_runs(self, limit: int = 50) -> list[dict]:
        return self._get("eval_runs", {"select": "*", "order": "created_at.desc",
                                       "limit": str(limit)})

    def list_eval_cases(self, run_id: str, limit: int = 200) -> list[dict]:
        return self._get("eval_cases", {
            "select": "*", "run_id": f"eq.{run_id}", "limit": str(limit)})

    def list_table(self, table: str, limit: int = 50) -> list[dict]:
        return self._get(table, {"select": "*", "order": "created_at.desc",
                                 "limit": str(limit)})

    def ping(self) -> dict:
        return {"backend": "supabase", "url": self.url}


# ---------------------------------------------------------------------------
# Local JSON fallback (offline dev + tests)
# ---------------------------------------------------------------------------

@dataclass
class LocalStore(Store):
    data_dir: str = ""
    name: str = "local"
    _rows: dict[str, list[dict]] = field(default_factory=dict)

    def __post_init__(self):
        if not self.data_dir:
            self.data_dir = str(Path(getattr(get_settings(), "data_dir", "data")))
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        for table in ("evidence_docs", "final_answers", "pending_actions",
                      "eval_runs", "eval_cases", "injection_attempts"):
            p = Path(self.data_dir) / f"{table}.json"
            if p.exists():
                try:
                    self._rows[table] = json.loads(p.read_text())
                except json.JSONDecodeError:
                    self._rows[table] = []
            else:
                self._rows[table] = []

    def _persist(self, table: str) -> None:
        (Path(self.data_dir) / f"{table}.json").write_text(
            json.dumps(self._rows[table], indent=2, default=str))

    def _new_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def save_evidence(self, docs: list[dict], run_id: str) -> list[str]:
        ids = []
        for d in docs:
            row = {k: v for k, v in d.items() if k != "content"}
            row.update({"id": self._new_id(), "run_id": run_id,
                        "content_redacted": d.get("content", ""),
                        "retrieved_at": _now()})
            self._rows["evidence_docs"].append(row)
            ids.append(row["id"])
        self._persist("evidence_docs")
        return ids

    def save_final_answer(self, question: str, answer: str, citations: list[dict],
                          run_id: str) -> str:
        row = {"id": self._new_id(), "question": question, "answer": answer,
               "citations": citations, "run_id": run_id, "created_at": _now()}
        self._rows["final_answers"].append(row)
        self._persist("final_answers")
        return row["id"]

    def create_pending_action(self, payload: dict) -> str:
        row = {"id": self._new_id(), "created_at": _now(),
               "decided_at": None, "decided_by": None, **payload}
        self._rows["pending_actions"].append(row)
        self._persist("pending_actions")
        return row["id"]

    def get_pending_action(self, row_id: str) -> Optional[dict]:
        for r in self._rows["pending_actions"]:
            if r["id"] == row_id:
                return r
        return None

    def decide_pending_action(self, row_id: str, status: str, decided_by: str) -> bool:
        for r in self._rows["pending_actions"]:
            if r["id"] == row_id:
                r["status"] = status
                r["decided_at"] = _now()
                r["decided_by"] = decided_by
                self._persist("pending_actions")
                return True
        return False

    def list_pending_actions(self, status: Optional[str] = None) -> list[dict]:
        rows = sorted(self._rows["pending_actions"],
                      key=lambda r: r.get("created_at", ""), reverse=True)
        if status:
            rows = [r for r in rows if r.get("status") == status]
        return rows

    def log_injection_attempt(self, input_text: str, blocked: bool) -> None:
        self._rows["injection_attempts"].append({
            "id": self._new_id(), "input": input_text[:2000], "blocked": blocked,
            "created_at": _now(),
        })
        self._persist("injection_attempts")

    def save_eval_run(self, summary: dict) -> str:
        refusal = summary.get("refusal_rate", {})
        row = {"id": self._new_id(), "created_at": _now(),
               "accuracy": summary.get("accuracy"),
               "refusal_rate": refusal.get("rate"),
               "avg_latency_ms": summary.get("latency", {}).get("avg"),
               "avg_tokens": summary.get("tokens", {}).get("avg"),
               "payload": summary}
        self._rows["eval_runs"].append(row)
        self._persist("eval_runs")
        return row["id"]

    def save_eval_cases(self, run_id: str, rows: list[dict]) -> None:
        for r in rows:
            self._rows["eval_cases"].append({
                "id": self._new_id(), "run_id": run_id,
                "category": r.get("category"), "input": r.get("input", ""),
                "passed": bool(r.get("passed")),
                "latency_ms": r.get("latency_ms"), "tokens": r.get("tokens"),
            })
        self._persist("eval_cases")

    def list_eval_runs(self, limit: int = 50) -> list[dict]:
        rows = sorted(self._rows["eval_runs"],
                      key=lambda r: r.get("created_at", ""), reverse=True)
        return rows[:limit]

    def list_eval_cases(self, run_id: str, limit: int = 200) -> list[dict]:
        rows = [r for r in self._rows["eval_cases"] if r.get("run_id") == run_id]
        return rows[:limit]

    def list_table(self, table: str, limit: int = 50) -> list[dict]:
        if table not in self._rows:
            return []
        rows = sorted(self._rows[table],
                      key=lambda r: r.get("created_at", r.get("id", "")),
                      reverse=True)
        return rows[:limit]

    def ping(self) -> dict:
        return {"backend": "local", "data_dir": self.data_dir,
                "tables": {k: len(v) for k, v in self._rows.items()}}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_store() -> Store:
    import os
    if os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_KEY"):
        return SupabaseStore()
    return LocalStore(data_dir=os.getenv("GUARDRAIL_DATA_DIR", "data"))


_default_store = get_store()


def default_store() -> Store:
    return _default_store
