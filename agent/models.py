"""Core data models shared across the pipeline."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class PermissionStateError(RuntimeError):
    """Raised when an approval record is moved through a disallowed state."""


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"


_ALLOWED_TRANSITIONS = {
    ApprovalStatus.PENDING: {
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
        ApprovalStatus.EXPIRED,
    },
    ApprovalStatus.APPROVED: {
        ApprovalStatus.EXECUTING,
        ApprovalStatus.EXPIRED,
    },
    ApprovalStatus.EXECUTING: {
        ApprovalStatus.EXECUTED,
        ApprovalStatus.FAILED,
    },
    ApprovalStatus.REJECTED: set(),
    ApprovalStatus.EXPIRED: set(),
    ApprovalStatus.EXECUTED: set(),
    ApprovalStatus.FAILED: set(),
}


class InjectionRisk(str, Enum):
    NONE = "none"
    DIRECT = "direct"
    INDIRECT = "indirect"
    EXFILTRATION = "exfiltration"
    ENCODING = "encoding"
    JAILBREAK = "jailbreak"
    SUSPICIOUS = "suspicious"


@dataclass
class GuardrailVerdict:
    """Result of the input guardrail pre-filter."""

    safe: bool
    risk: InjectionRisk = InjectionRisk.NONE
    details: list[str] = field(default_factory=list)
    rules_flagged: list[str] = field(default_factory=list)
    classifier_label: Optional[str] = None


@dataclass
class EvidenceDoc:
    """A single, self-contained piece of retrieved evidence."""

    id: str
    source: str
    content: str
    retrieved_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    metadata: dict[str, Any] = field(default_factory=dict)
    redacted: bool = False

    def display_ref(self) -> str:
        return f"[{self.id}]"


@dataclass
class SubQuestion:
    """A decomposed sub-question and its target tool."""

    text: str
    tool: str
    evidence: Optional[EvidenceDoc] = None
    error: Optional[str] = None
    started: float = field(default_factory=time.perf_counter)
    duration_ms: float = 0.0


@dataclass
class PlanStep:
    """One step of a high-stakes plan (generated instead of executing)."""

    action: str
    tool: str
    subject: str
    rationale: str


@dataclass
class ApprovalRecord:
    """Record of a human-in-the-loop approval gate.

    Lifecycle (ApprovalStatus):
        PENDING -> APPROVED -> EXECUTING -> EXECUTED
        PENDING -> REJECTED / EXPIRED
        APPROVED -> EXPIRED (not executed in time)
        EXECUTING -> FAILED
    Disallowed transitions raise PermissionStateError. Execution is gated by
    idempotency_key so an approval can never execute twice, and expires_at
    enforces a time-to-live on pending approvals.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    plan: list[PlanStep] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    decided_at: Optional[float] = None
    approved: Optional[bool] = None
    approver: str = ""
    status: str = ApprovalStatus.PENDING.value
    idempotency_key: str = field(default_factory=lambda: uuid.uuid4().hex)
    expires_at: float = 0.0
    executed_at: Optional[float] = None
    failure_reason: str = ""
    events: list[dict] = field(default_factory=list)

    def transition(self, status: str, actor: str = "system") -> None:
        nxt = ApprovalStatus(status)
        if nxt not in _ALLOWED_TRANSITIONS[ApprovalStatus(self.status)]:
            raise PermissionStateError(
                f"invalid approval transition {self.status!r} -> {status!r}")
        self.status = status
        if nxt is ApprovalStatus.EXECUTED:
            self.executed_at = time.time()
        self.events.append({
            "at": time.time(), "actor": actor, "to": status,
            "idempotency_key": self.idempotency_key,
        })

    def finalize(self, approved: bool, approver: str = "automated") -> None:
        """PENDING -> APPROVED or PENDING -> REJECTED."""
        if self.status != ApprovalStatus.PENDING.value:
            raise PermissionStateError(
                f"cannot finalize approval in state {self.status!r}")
        if self.is_expired():
            self.expire("expiry_check")
            raise PermissionStateError("approval expired before decision")
        self.approved = approved
        self.approver = approver
        self.decided_at = time.time()
        self.transition(
            ApprovalStatus.APPROVED.value if approved else ApprovalStatus.REJECTED.value,
            actor=approver,
        )

    def is_expired(self, now: Optional[float] = None) -> bool:
        if not self.expires_at:
            return False
        now = now if now is not None else time.time()
        return now >= self.expires_at and self.status in (
            ApprovalStatus.PENDING.value, ApprovalStatus.APPROVED.value)

    def expire(self, actor: str = "system") -> None:
        if self.status in (ApprovalStatus.PENDING.value, ApprovalStatus.APPROVED.value):
            self.transition(ApprovalStatus.EXPIRED.value, actor=actor)


@dataclass
class AgentResult:
    """Everything produced by one agent run."""

    question: str
    blocked: bool = False
    block_reason: str = ""
    risk_label: str = ""
    sub_questions: list[SubQuestion] = field(default_factory=list)
    evidence: list[EvidenceDoc] = field(default_factory=list)
    redacted: bool = False
    answer: str = ""
    schema_valid: bool = False
    schema_error: Optional[str] = None
    citation_valid: bool = False
    citation_errors: list[str] = field(default_factory=list)
    planned: list[PlanStep] = field(default_factory=list)
    approval: Optional[ApprovalRecord] = None
    executed: bool = False
    pending_action_id: Optional[str] = None
    latencies_ms: dict[str, float] = field(default_factory=dict)
    tokens_total: int = 0
    tokens_prompt: int = 0
    tokens_completion: int = 0
    n_llm_calls: int = 0
    degraded: list[str] = field(default_factory=list)

    @property
    def latency_ms(self) -> float:
        return float(self.latencies_ms.get("total", 0.0))

    @property
    def ok(self) -> bool:
        return not self.blocked and self.answer != ""

    def to_metrics(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "risk": self.risk_label or ("blocked" if self.blocked else "none"),
            "answered": bool(self.answer),
            "latency_ms": round(self.latency_ms, 1),
            "tokens": self.tokens_total,
            "tokens_prompt": self.tokens_prompt,
            "tokens_completion": self.tokens_completion,
            "llm_calls": self.n_llm_calls,
            "schema_valid": self.schema_valid,
            "citation_valid": self.citation_valid,
            "degraded": self.degraded,
            "executed": self.executed,
        }