"""Confirmation emails for the permission layer.

Uses a real SMTP server when SMTP_HOST/SMTP_USER/SMTP_PASSWORD are configured
(e.g. SendGrid, Mailgun, SES, or your own relay). Falls back to a simulated
sender that just records the message, so the permission gate still works in
tests and local dev.
"""
from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText

from .models import ApprovalRecord, PlanStep


def _render(approval: ApprovalRecord, plan: list[PlanStep]) -> tuple[str, str]:
    subject = "[GUARDRAIL AGENT] Action requires your approval"
    lines = [
        "A high-stakes action is awaiting your approval.",
        "",
        "Plan:",
    ]
    for s in plan:
        lines.append(f"  - {s.action} -> {s.subject} ({s.rationale})")
    lines += [
        "",
        f"Approval token: {approval.id}",
        "",
        "Approve or deny this action from the approvals dashboard.",
    ]
    return subject, "\n".join(lines)


class ConfirmationSender:
    """Sends the approval request to a human via email (or simulated)."""

    def __init__(self, smtp_host: str | None = None,
                 smtp_port: int | None = None,
                 smtp_user: str | None = None,
                 smtp_password: str | None = None,
                 from_addr: str | None = None,
                 to_addrs: list[str] | None = None):
        self.smtp_host = smtp_host or os.getenv("SMTP_HOST", "")
        self.smtp_port = smtp_port or int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = smtp_user or os.getenv("SMTP_USER", "")
        self.smtp_password = smtp_password or os.getenv("SMTP_PASSWORD", "")
        self.from_addr = from_addr or os.getenv("SMTP_FROM", "guardrail-agent@example.com")
        self.to_addrs = (to_addrs or os.getenv("SMTP_TO", "approver@example.com")
                         ).split(",")
        self.real = bool(self.smtp_host and self.smtp_user)
        self.sent: list[dict] = []

    def send(self, approval: ApprovalRecord, plan: list[PlanStep],
             channel: str = "email") -> str:
        subject, body = _render(approval, plan)
        if self.real:
            try:
                self._send_real(subject, body)
                channel = "smtp"
            except Exception as exc:  # noqa: BLE001
                self.sent.append({"channel": channel, "token": approval.id,
                                  "message": f"SMTP FAILED: {exc}", "delivered": False})
                return f"SMTP delivery failed ({exc}); falling back to simulated log"
        msg = (
            f"[CONFIRMATION REQUIRED] {subject} Plan: "
            + "; ".join(f"{s.action} -> {s.subject}" for s in plan)
            + f". Approve/deny with token {approval.id}."
        )
        self.sent.append({"channel": channel, "token": approval.id,
                          "message": msg, "delivered": True})
        return msg

    def _send_real(self, subject: str, body: str) -> None:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.to_addrs)
        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.login(self.smtp_user, self.smtp_password)
            server.sendmail(self.from_addr, self.to_addrs, msg.as_string())
