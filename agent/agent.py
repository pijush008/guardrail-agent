"""Agent orchestration: the full pipeline wired as discrete stages.

    InputGuardrail -> Intent -> Decompose -> Tools -> PII Redact
        -> Synthesis -> Output+Citation validation -> Permission gate

Every stage is a separate module/class so it can be unit-tested and
evaluated in isolation. Timing and token usage are accumulated per stage
into the AgentResult so the metrics collector has real numbers.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from .config import get_settings
from .db import Store, default_store
from .decompose import Decomposer
from .guardrail import Guardrail
from .llm import LLMClient, LLMError
from .models import AgentResult, EvidenceDoc
from .notify import ConfirmationSender
from .permission import ApprovalManager, PermissionDenied, PermissionLayer
from .redact import PIIRedactor, build_redactor
from .synthesize import Synthesizer
from .tools import ToolRegistry, build_default_registry, is_high_stakes
from .validate import CitationValidator, NoOpSchema, SchemaValidator


@dataclass
class Intent:
    kind: str = "research"  # "research" | "action"
    tool: str = ""
    action: str = ""
    subject: str = ""


class IntentClassifier:
    """Tiny classifier: is this request a read/research question or a
    mutating action the agent is being asked to perform?"""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def classify(self, question: str) -> Intent:
        sys = (
            "Classify the user request. If it asks the agent to DO something "
            "that changes state (send email, delete/update a record, transition "
            "a ticket, spend money, deploy), return "
            '{"intent":"action","tool":"gmail|notion|jira","action":"<verb>","subject":"<object>"}. '
            'Otherwise return {"intent":"research"}. JSON only.'
        )
        try:
            data = self.llm.chat_json(sys, "REQUEST:\n" + question[:1500], max_tokens=120)
        except LLMError:
            return Intent()
        if data.get("intent") != "action":
            return Intent()
        return Intent(kind="action",
                      tool=data.get("tool", ""),
                      action=data.get("action", ""),
                      subject=data.get("subject", ""))


class GuardrailAgent:
    def __init__(
        self,
        registry: ToolRegistry | None = None,
        llm: LLMClient | None = None,
        guardrail: Guardrail | None = None,
        permission: PermissionLayer | None = None,
        store: Store | None = None,
        persist: bool = True,
        min_citations: int | None = None,
    ):
        self.settings = get_settings()
        self.llm = llm or LLMClient(self.settings)
        self.registry = registry or build_default_registry()
        self.guardrail = guardrail or Guardrail(llm=self.llm)
        self.decomposer = Decomposer(self.registry, self.llm)
        self.redactor = build_redactor(self.settings.placeholder)
        self.synthesizer = Synthesizer(self.llm)
        self.min_citations = min_citations or self.settings.min_citations
        self.citation_validator = CitationValidator(
            self.llm if self.settings.citation_judge else None, self.min_citations)
        self.schema_validator: SchemaValidator | NoOpSchema = NoOpSchema()
        self.intent = IntentClassifier(self.llm)
        self.permission = permission or PermissionLayer(
            approvals=ApprovalManager(), sender=ConfirmationSender())
        self.store = store or default_store()
        self.persist = persist
        self.run_id = ""

    def new_run(self) -> str:
        import uuid
        self.run_id = uuid.uuid4().hex
        return self.run_id

    # ------------------------------------------------------------------
    def run(self, question: str, require_json: bool = False,
            expected_keys: list[str] | None = None,
            skip_guardrail: bool = False,
            documents: list[dict] | None = None) -> AgentResult:
        """Run one question through the pipeline.

        documents: optional user-uploaded docs as [{"source", "content"}].
        They enter the evidence flow BEFORE the indirect-injection scan and
        PII redaction, so uploaded content is treated as untrusted data just
        like tool output (and can still be cited by the final answer).
        """
        started = time.perf_counter()
        res = AgentResult(question=question)
        self.new_run()
        self._usage_before = (self.llm.usage.prompt_tokens,
                              self.llm.usage.completion_tokens)

        # [1] INPUT GUARDRAIL
        t0 = time.perf_counter()
        if not skip_guardrail:
            verdict = self.guardrail.check(question)
            res.latencies_ms["guardrail"] = (time.perf_counter() - t0) * 1000.0
            if not verdict.safe and self.settings.auto_block:
                res.blocked = True
                res.risk_label = verdict.risk.value
                res.block_reason = f"blocked by input guardrail: {verdict.risk.value} " \
                                   f"({'|'.join(verdict.rules_flagged or verdict.details)})"
                res.latencies_ms["total"] = (time.perf_counter() - started) * 1000.0
                self._persist_blocked(question)
                return res
        else:
            res.latencies_ms["guardrail"] = 0.0

        # [2a] INTENT: action request?
        t0 = time.perf_counter()
        intent = self.intent.classify(question)
        res.latencies_ms["intent"] = (time.perf_counter() - t0) * 1000.0

        if intent.kind == "action":
            if is_high_stakes(intent.tool, intent.action):
                return self._handle_high_stakes(question, intent, res, started)
            # Low-risk action: no guard gate, but it still needs evidence.
            res.degraded.append(f"non-high-stakes action {intent.tool}.{intent.action} not executed in read-only mode")

        # [2b] DECOMPOSE -> TOOLS
        t0 = time.perf_counter()
        subs = self.decomposer.execute(question)
        res.latencies_ms["decompose_tools"] = (time.perf_counter() - t0) * 1000.0
        res.sub_questions = subs

        for sq in subs:
            if sq.evidence:
                res.evidence.append(sq.evidence)
            elif sq.error:
                res.degraded.append(f"{sq.tool}: {sq.error}")

        # Deduplicate docs with the same id (multiple sub-questions can hit
        # the same source document).
        seen: set[str] = set()
        unique: list[EvidenceDoc] = []
        for doc in res.evidence:
            if doc.id in seen:
                continue
            seen.add(doc.id)
            unique.append(doc)
        res.evidence = unique

        # User-uploaded documents enter here as untrusted data: they get the
        # same indirect-injection scan + redaction + citation treatment.
        if documents:
            for i, doc in enumerate(documents, start=1):
                content = (doc.get("content") or "").strip()
                if not content:
                    continue
                source = doc.get("source") or "document"
                res.evidence.append(EvidenceDoc(
                    id=f"doc:{i}", source=source, content=content))

        # [2c] INDIRECT-INJECTION SCAN on tool content (untrusted data).
        # Any doc containing instruction-like text is excluded from synthesis
        # and the attempt is logged to injection_attempts.
        clean: list[EvidenceDoc] = []
        for doc in res.evidence:
            v = self.guardrail.scan_content(doc.content)
            if not v.safe:
                self._log_injection(doc.content, blocked=True)
                res.degraded.append(f"{doc.source} doc {doc.id} excluded: "
                                    f"indirect injection ({v.risk.value})")
            else:
                clean.append(doc)
        res.evidence = clean

        # [3] PII REDACTION
        t0 = time.perf_counter()
        redacted: list[EvidenceDoc] = []
        for doc in res.evidence:
            redacted.append(self.redactor.redact_evidence(doc))
        res.evidence = redacted
        res.redacted = True
        res.latencies_ms["redact"] = (time.perf_counter() - t0) * 1000.0

        # [4] SYNTHESIS
        t0 = time.perf_counter()
        res.answer = self.synthesizer.synthesize(question, res.evidence)
        res.latencies_ms["synthesis"] = (time.perf_counter() - t0) * 1000.0

        # [5] OUTPUT VALIDATION
        t0 = time.perf_counter()
        if require_json or expected_keys:
            self.schema_validator = SchemaValidator(expected_keys=expected_keys)
            res.schema_valid, res.schema_error = self.schema_validator.validate(res.answer)
            if not res.schema_valid:
                res.answer = self._resynthesize_json(question, res.evidence, expected_keys)
                res.schema_valid, res.schema_error = self.schema_validator.validate(res.answer)
        else:
            res.schema_valid, _ = NoOpSchema().validate(res.answer)
        res.latencies_ms["validate"] = (time.perf_counter() - t0) * 1000.0

        ok, cite_errors = self.citation_validator.validate(res.answer, res.evidence)
        res.citation_valid = ok
        res.citation_errors = cite_errors

        # Token accounting (per-run delta)
        self._record_usage(res)

        res.latencies_ms["total"] = (time.perf_counter() - started) * 1000.0
        if self.persist:
            self._persist_results(res)
        return res

    # ------------------------------------------------------------------
    def _handle_high_stakes(self, question: str, intent: Intent, res: AgentResult,
                            started: float) -> AgentResult:
        res.risk_label = "high_stakes"
        result = self.permission.evaluate(intent.tool, intent.action, intent.subject,
                                          reason=question)
        res.planned = result.planned
        res.approval = result.approval
        res.blocked = False
        if result.approval and result.approval.approved:
            try:
                outcome = self.permission.execute(intent.tool, intent.action,
                                                  intent.subject, result.approval)
                res.executed = True
                res.answer = outcome
            except PermissionDenied as exc:
                res.answer = f"Permission denied: {exc}"
        else:
            if self.persist and result.approval is not None:
                row_id = self._persist_pending_action(intent, result.approval)
                res.pending_action_id = row_id
            res.answer = (
                f"HIGH-STAKES ACTION REQUESTED but NOT executed. Plan: "
                f"{'; '.join(s.action + ' -> ' + s.subject for s in result.planned)}. "
                f"Approval token {result.approval.id if result.approval else 'n/a'}."
            )
        res.latencies_ms["total"] = (time.perf_counter() - started) * 1000.0
        self._record_usage(res)
        return res

    def _resynthesize_json(self, question: str, evidence: list[EvidenceDoc],
                           expected_keys: list[str] | None) -> str:
        blocks = "\n".join(
            f"<evidence id=\"{d.id}\" source=\"{d.source}\" number={i}>\n{d.content}\n</evidence>"
            for i, d in enumerate(evidence, start=1))
        sys = (
            "Return ONLY valid JSON with keys: " + ", ".join(expected_keys or ["answer"]) +
            " based strictly on the evidence. Cite with [n] inside the answer field."
        )
        try:
            text, _ = self.llm.chat(sys, "QUESTION:\n" + question + "\n\nEVIDENCE:\n" + blocks,
                                    max_tokens=600, json_mode=True)
            return text.strip()
        except LLMError:
            return '{"answer": "synthesis failed"}'

    def _llm_calls_hint(self) -> list[str]:
        return []

    def _record_usage(self, res: AgentResult) -> None:
        """Per-run token delta, not the client's cumulative counters."""
        p0, c0 = getattr(self, "_usage_before", (0, 0))
        res.tokens_prompt = max(0, self.llm.usage.prompt_tokens - p0)
        res.tokens_completion = max(0, self.llm.usage.completion_tokens - c0)
        res.tokens_total = res.tokens_prompt + res.tokens_completion
        res.n_llm_calls = len(self._llm_calls_hint())

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def _persist_blocked(self, question: str) -> None:
        if not self.persist:
            return
        try:
            self.store.log_injection_attempt(question, blocked=True)
        except Exception:  # noqa: BLE001
            pass

    def _log_injection(self, content: str, blocked: bool) -> None:
        if not self.persist:
            return
        try:
            self.store.log_injection_attempt(content, blocked=blocked)
        except Exception:  # noqa: BLE001
            pass

    def _persist_results(self, res: AgentResult) -> None:
        try:
            evidence_rows = [{
                "id": d.id, "source": d.source, "content": d.content,
                "retrieved_at": d.retrieved_at,
            } for d in res.evidence]
            self.store.save_evidence(evidence_rows, self.run_id)
            citations = self._build_citations(res.answer, res.evidence)
            self.store.save_final_answer(res.question, res.answer, citations,
                                         self.run_id)
        except Exception as exc:  # noqa: BLE001
            res.degraded.append(f"persist failed: {exc}")

    def _build_citations(self, answer: str, evidence: list[EvidenceDoc]) -> list[dict]:
        from .validate import parse_citations
        by_num = {i + 1: d for i, d in enumerate(evidence)}
        return [{"id": by_num[n].id, "source": by_num[n].source}
                for n in sorted(set(parse_citations(answer))) if n in by_num]

    def _persist_pending_action(self, intent: Intent, approval) -> str:
        import json
        plan = [{"action": s.action, "tool": s.tool, "subject": s.subject,
                 "rationale": s.rationale} for s in approval.plan]
        payload = {
            "plan": json.dumps({
                "plan": plan,
                "tool": intent.tool, "action": intent.action,
                "subject": intent.subject, "token": approval.id,
            }),
            "status": "pending",
        }
        return self.store.create_pending_action(payload)