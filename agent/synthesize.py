"""Synthesis (Section 2.4): draft a cited final answer from redacted evidence.

The evidence docs are passed in a numbered block; the model must cite them
with [n] markers that map to evidence IDs. The citation validator (validate.py)
enforces that every [n] refers to a real evidence doc.
"""
from __future__ import annotations

from .llm import LLMClient, LLMError
from .models import EvidenceDoc

_SYSTEM = (
    "You synthesize a final answer from evidence. Rules:\n"
    "1. Only use information present in the provided <evidence> blocks.\n"
    "2. Attach a citation marker [n] after every factual claim, where n is "
    "the evidence block number.\n"
    "3. If evidence is missing or a source failed, say so explicitly "
    "(e.g. 'Jira data unavailable') instead of guessing.\n"
    "4. Never invent numbers, dates, names, or sources.\n"
    "5. Placeholder tokens like [EMAIL_REDACTED] are deliberate PII "
    "redactions — keep them as-is; do not try to fill them in.\n"
    "6. If nothing was retrieved, answer that no information was found.\n"
    "7. Keep the answer under ~220 words, in prose with [n] citations."
)


class Synthesizer:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def synthesize(self, question: str, evidence: list[EvidenceDoc]) -> str:
        if not evidence:
            return ("No information could be retrieved from the connected "
                    "tools for this question.")
        blocks = []
        for i, doc in enumerate(evidence, start=1):
            blocks.append(f"<evidence id=\"{doc.id}\" source=\"{doc.source}\" number={i}>\n{doc.content}\n</evidence>")
        user = (
            "QUESTION:\n" + question[:2000] + "\n\n"
            "EVIDENCE:\n" + "\n".join(blocks) + "\n\n"
            "Draft the cited answer:"
        )
        try:
            answer, _ = self.llm.chat(_SYSTEM, user, max_tokens=700)
        except LLMError as exc:
            return f"Synthesis failed: {exc}"
        return answer.strip()