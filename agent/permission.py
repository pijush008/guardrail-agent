"""Permission layer / risk mitigation (Section 2.6).

For high-stakes or irreversible actions (send external email, delete data,
spend money, push to prod) the agent MUST NOT execute directly. Instead it:

  1. produces a plan (what + why);
  2. sends a confirmation request to a human (simulated email/Slack with an
     approve/deny token);
  3. waits for explicit approval before execution.

The execution path is structurally gated: execute_action() is only reachable
through a finalized ApprovalRecord. In automated/CI contexts, an
ApprovalManager can be configured to auto-approve (GUARDRAIL_AUTO_APPROVE=1)
so the eval suite can exercise the full path deterministically.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .config import get_settings
from .models import ApprovalRecord, ApprovalStatus, PlanStep
from .tools import action_catalog, execute_action


@dataclass
class RiskResult:
    """Outcome of evaluating a proposed action."""

    tool: str
    action: str
    subject: str
    risk: str  # "read" | "high"
    planned: list[PlanStep] = field(default_factory=list)
    approval: ApprovalRecord | None = None
    message: str = ""


def classify_action(tool: str, action: str) -> str:
    if action in action_catalog().get(tool, []):
        return "high"
    return "read"


class PlanGenerator:
    """Generates a human-readable plan for a proposed high-stakes action."""

    def plan(self, tool: str, action: str, subject: str, reason: str = "") -> list[PlanStep]:
        return [
            PlanStep(
                action=f"{tool}.{action}",
                tool=tool,
                subject=subject,
                rationale=reason or f"user requested {tool}.{action} on {subject}",
            )
        ]


class ConfirmationSender:
    """Sends the approval request to a human. Simulated email/Slack now."""

    sent: list[dict] = field(default_factory=list)

    def __init__(self):
        self.sent = []

    def send(self, approval: ApprovalRecord, plan: list[PlanStep], channel: str = "email") -> str:
        summary = "; ".join(f"{s.action} -> {s.subject}" for s in plan)
        msg = (
            f"[CONFIRMATION REQUIRED] Agent proposes: {summary}. "
            f"Approve/deny with token {approval.id}."
        )
        self.sent.append({"channel": channel, "token": approval.id, "message": msg})
        return msg


class ApprovalManager:
    """Waits for (or simulates) human approval, then records the outcome."""

    def __init__(self, auto_approve: bool | None = None,
                 timeout_s: float | None = None,
                 poll_s: float = 0.05,
                 decider: Callable[[str, str], bool] | None = None):
        settings = get_settings()
        self.auto_approve = settings.auto_approve if auto_approve is None else auto_approve
        self.timeout = settings.approval_timeout_s if timeout_s is None else timeout_s
        self.poll = poll_s
        self.decider = decider  # (token, plan) -> bool override
        self.records: list[ApprovalRecord] = []

    def request(self, plan: list[PlanStep]) -> ApprovalRecord:
        rec = ApprovalRecord(plan=plan,
                             expires_at=time.time() + self.timeout)
        if self.decider:
            approved = self.decider(rec.id, "; ".join(s.action for s in plan))
            rec.finalize(approved, "test_decider")
        elif self.auto_approve:
            rec.finalize(True, "automated")
        else:
            # Human-in-the-loop: leave the record undecided so an approver
            # can approve/deny it later. Execution is blocked until then.
            pass
        self.records.append(rec)
        return rec

    def _get(self, token: str) -> ApprovalRecord:
        for r in self.records:
            if r.id == token:
                if r.is_expired():
                    r.expire(actor="expiry_sweep")
                return r
        raise PermissionDenied("unknown approval token")

    def approve(self, token: str, approver: str = "human") -> ApprovalRecord:
        rec = self._get(token)
        if rec.status != ApprovalStatus.PENDING.value:
            raise PermissionDenied(
                f"approval token already decided ({rec.status})")
        rec.finalize(True, approver)
        return rec

    def deny(self, token: str, approver: str = "human") -> ApprovalRecord:
        rec = self._get(token)
        if rec.status != ApprovalStatus.PENDING.value:
            raise PermissionDenied(
                f"approval token already decided ({rec.status})")
        rec.finalize(False, approver)
        return rec


class PermissionDenied(RuntimeError):
    pass


class PermissionLayer:
    """High-level API used by the agent."""

    def __init__(self, approvals: ApprovalManager | None = None,
                 sender: ConfirmationSender | None = None):
        self.approvals = approvals or ApprovalManager()
        self.sender = sender or ConfirmationSender()
        self.log: list[dict] = []
        # Idempotency: every executed approval has a unique key; re-executing
        # with a reused key is denied before any tool runs.
        self._executed_keys: set[str] = set()

    def evaluate(self, tool: str, action: str, subject: str,
                 reason: str = "") -> RiskResult:
        risk = classify_action(tool, action)
        if risk == "read":
            return RiskResult(tool=tool, action=action, subject=subject, risk="read",
                              message="read-only action, permitted")
        if not get_settings().require_approval:
            return RiskResult(tool=tool, action=action, subject=subject, risk="high",
                              message="approval disabled by config")
        plan = PlanGenerator().plan(tool, action, subject, reason)
        approval = self.approvals.request(plan)
        sent = self.sender.send(approval, plan)
        self.log.append({
            "ts": time.time(), "tool": tool, "action": action, "subject": subject,
            "token": approval.id, "approved": approval.approved,
        })
        return RiskResult(tool=tool, action=action, subject=subject, risk="high",
                          planned=plan, approval=approval, message=sent)

    def execute(self, tool: str, action: str, subject: str, approval: ApprovalRecord) -> str:
        """Structurally-gated execution: requires a finalized approval.

        Atomically verifies, before any tool runs:
          * approval status is APPROVED
          * approval has not expired
          * the idempotency key has not already been used

        The key is reserved BEFORE execution so a concurrent/duplicate call
        cannot double-execute the same approval.
        """
        if approval is None:
            raise PermissionDenied("no approval on file — action blocked")
        if approval.idempotency_key in self._executed_keys:
            raise PermissionDenied(
                "action already executed — idempotency key reused")
        if approval.status != ApprovalStatus.APPROVED.value:
            raise PermissionDenied("no approval on file — action blocked")
        if approval.is_expired():
            approval.expire(actor="execution_gate")
            raise PermissionDenied("approval expired before execution")
        approval.transition(ApprovalStatus.EXECUTING.value, actor="execution_gate")
        self._executed_keys.add(approval.idempotency_key)
        try:
            outcome = execute_action(tool, action, subject)
        except PermissionDenied:
            raise
        except Exception as exc:
            approval.transition(ApprovalStatus.FAILED.value, actor="execution_gate")
            approval.failure_reason = str(exc)
            raise PermissionDenied(f"execution failed: {exc}") from exc
        approval.transition(ApprovalStatus.EXECUTED.value, actor="execution_gate")
        self.log.append({
            "ts": time.time(), "tool": tool, "action": action, "subject": subject,
            "token": approval.id, "idempotency_key": approval.idempotency_key,
            "status": approval.status,
        })
        return outcome