"""Core data models shared across the pipeline."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


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
    """Record of a human-in-the-loop approval gate."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    plan: list[PlanStep] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    decided_at: Optional[float] = None
    approved: Optional[bool] = None
    approver: str = ""

    def finalize(self, approved: bool, approver: str = "automated") -> None:
        self.approved = approved
        self.approver = approver
        self.decided_at = time.time()


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