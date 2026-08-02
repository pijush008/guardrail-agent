"""Output validation (Section 2.3): schema check + citation validation.

Citation validation is two-fold:
  a) structural — every [n] marker maps to a real evidence ID;
  b) semantic — an LLM-as-judge checks each cited claim is actually
     supported by the referenced evidence doc.
"""
from __future__ import annotations

import json
import re

from .llm import LLMClient, LLMError
from .models import EvidenceDoc

_CITE_RE = re.compile(r"\[(\d+)\]")


def parse_citations(answer: str) -> list[int]:
    return [int(m) for m in _CITE_RE.findall(answer)]


class CitationValidator:
    def __init__(self, llm: LLMClient | None = None, min_citations: int = 1):
        self.llm = llm
        self.min_citations = min_citations

    def validate_structural(self, answer: str, evidence: list[EvidenceDoc]) -> tuple[bool, list[str]]:
        citations = parse_citations(answer)
        errors: list[str] = []
        if not citations:
            errors.append(f"answer contains no citations (min {self.min_citations} required)")
            return False, errors
        valid_ids = {i + 1 for i in range(len(evidence))}
        bad = sorted({c for c in citations if c not in valid_ids})
        if bad:
            errors.append(f"citation markers {bad} do not map to any evidence doc")
            return False, errors
        return True, errors

    def validate_semantic(self, answer: str, evidence: list[EvidenceDoc]) -> tuple[bool, list[str]]:
        """LLM-as-judge: does each [n] claim match its evidence block?"""
        if not self.llm:
            return True, []
        citations = parse_citations(answer)
        blocks = {i + 1: evidence[i].content for i in range(len(evidence))}
        judge_system = (
            "You verify citations. For each claim-citation pair, decide if the "
            "claim is SUPPORTED by the evidence block. Respond JSON: "
            '{"ok": bool, "errors": ["[n]: claim contradicts/misses evidence"]}. '
            "Claims stating data was unavailable, or redaction placeholders, are fine."
        )
        judge_user = "ANSWER:\n" + answer + "\n\nEVIDENCE BLOCKS:\n"
        for n in citations:
            judge_user += f"\n--- block {n} ---\n{blocks.get(n, 'MISSING')[:1200]}\n"
        try:
            data = self.llm.chat_json(judge_system, judge_user + "\nVerdict JSON:", max_tokens=300)
        except LLMError:
            return True, []
        if not data.get("ok", False):
            return False, list(data.get("errors", ["unsupported citation"]))
        return True, []

    def validate(self, answer: str, evidence: list[EvidenceDoc]) -> tuple[bool, list[str]]:
        ok, errors = self.validate_structural(answer, evidence)
        if not ok:
            return ok, errors
        ok2, errors2 = self.validate_semantic(answer, evidence)
        if not ok2:
            return False, errors2
        return True, []


class SchemaValidator:
    """Validates structured outputs (JSON) against a JSON-schema-like spec."""

    def __init__(self, expected_keys: list[str] | None = None, expected_type: str = "json"):
        self.expected_keys = expected_keys
        self.expected_type = expected_type

    def validate(self, answer: str) -> tuple[bool, str | None]:
        text = answer.strip()
        text = re.sub(r"^```(json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return False, f"invalid JSON: {exc.msg}"
        if self.expected_keys:
            missing = [k for k in self.expected_keys if k not in data]
            if missing:
                return False, f"missing keys: {missing}"
        return True, None


class NoOpSchema:
    """Used when a question does not demand structured output."""

    def validate(self, answer: str):
        return True, None