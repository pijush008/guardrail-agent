"""Decomposition (Section 2.5): break a question into sub-questions and
route each to the right tool. Extensible — new tools register in the
ToolRegistry and are announced to the decomposer automatically.
"""
from __future__ import annotations

import json
import re
import time

from .llm import LLMClient, LLMError
from .models import SubQuestion
from .tools import ToolError, ToolRegistry


def _normalize(raw: object) -> list[dict]:
    """Accept any shape the model might produce:
    a top-level list, a {"sub_questions": [...]} wrapper, a single
    {"sub_question": ..., "tool": ...} object, or a mix thereof.
    """
    out: list[dict] = []

    def _push(item: dict) -> None:
        text = str(item.get("sub_question", item.get("question", item.get("text", "")))).strip()
        tool = str(item.get("tool", "")).strip()
        if text or tool:
            out.append({"sub_question": text, "tool": tool})

    def _walk(node) -> None:
        if isinstance(node, list):
            for child in node:
                _walk(child)
        elif isinstance(node, dict):
            if "sub_questions" in node:
                _walk(node["sub_questions"])
            elif "sub_question" in node or "tool" in node:
                _push(node)
            else:
                for child in node.values():
                    _walk(child)

    _walk(raw)
    return out


def _try_extract_json(text: str) -> list[dict]:
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return _normalize(data)
        return _normalize(data)
    except json.JSONDecodeError:
        pass
    # Find the first [...] block if the model wrapped it in prose.
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    return _normalize(data)


_SYSTEM = (
    "You are the decomposition step of a multi-tool research agent. "
    "Break the user's question into concrete sub-questions, and for each "
    "choose the single best tool from the available list. If a question is "
    "about email, choose gmail; about project docs/roadmap/goals/pilots/"
    "contacts/coverage, choose notion; about tasks/issues/tickets/deadlines/"
    "blockers, choose jira; about fetched external content, choose content. "
    "If a question asks about a person, a role, a sender, or who did/sent "
    "something, choose gmail (people are named in email threads). "
    'Reply with ONLY a JSON array: [{"sub_question": str, "tool": str}]. '
    "Use at most 4 sub-questions. Empty/unknown → []."
)


class Decomposer:
    def __init__(self, registry: ToolRegistry, llm: LLMClient):
        self.registry = registry
        self.llm = llm

    def decompose(self, question: str) -> list[SubQuestion]:
        tools = self.registry.names()
        user = (
            f"AVAILABLE TOOLS: {', '.join(tools)}\n\n"
            f"USER QUESTION:\n{question[:3000]}\n\n"
            "JSON decomposition:"
        )
        try:
            text, _ = self.llm.chat(_SYSTEM, user, max_tokens=600, json_mode=True)
        except LLMError as exc:
            return [SubQuestion(text=question, tool="", error=str(exc))]

        plans = _try_extract_json(text)
        out: list[SubQuestion] = []
        for p in plans[:4]:
            sq_text = str(p.get("sub_question", "")).strip()
            tool = str(p.get("tool", "")).strip()
            if not sq_text:
                continue
            if tool not in self.registry.names():
                tool = self._fallback_tool(sq_text)
            out.append(SubQuestion(text=sq_text, tool=tool))
        return out or [SubQuestion(text=question, tool="gmail")]

    @staticmethod
    def _fallback_tool(text: str) -> str:
        t = text.lower()
        if any(w in t for w in ("email", "mail", "inbox", "message")):
            return "gmail"
        if any(w in t for w in ("roadmap", "goal", "doc", "page", "notion",
                                "pilot", "contact", "coverage", "partner")):
            return "notion"
        if any(w in t for w in ("ticket", "issue", "task", "deadline", "blocker",
                                "jira", "status", "in progress")):
            return "jira"
        return "gmail"

    def execute(self, question: str) -> list[SubQuestion]:
        """Decompose then query each tool, building evidence per sub-question."""
        subs = self.decompose(question)
        for sq in subs:
            if not sq.tool:
                sq.error = "no tool routed"
                continue
            t0 = time.perf_counter()
            try:
                docs = self.registry.search(sq.tool, sq.text)
            except ToolError as exc:
                sq.error = str(exc)
                sq.duration_ms = (time.perf_counter() - t0) * 1000.0
                continue
            sq.duration_ms = (time.perf_counter() - t0) * 1000.0
            if docs:
                sq.evidence = docs[0]
            else:
                sq.error = f"no data for '{sq.text}'"
        return subs