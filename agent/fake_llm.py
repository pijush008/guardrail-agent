"""A deterministic fake LLM so the pipeline can run offline.

Used by the test suite and by the service in "demo mode"
(GUARDRAIL_FAKE_LLM=1) so the full stack works without API quota.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .llm import LLMUsage


@dataclass
class FakeUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class FakeLLM:
    """Mimics LLMClient's chat/chat_json with canned, deterministic output."""

    usage = FakeUsage()

    def _bump(self, prompt: int, completion: int):
        self.usage.prompt_tokens += prompt
        self.usage.completion_tokens += completion

    def chat(self, system: str, user: str, max_tokens: int = 1024,
             temperature: float | None = None, json_mode: bool = False):
        self._bump(len(system) // 4 + len(user) // 4, 40)
        text = self._respond(system, user)
        return text, LLMUsage(prompt_tokens=10, completion_tokens=10)

    def chat_json(self, system: str, user: str, max_tokens: int = 1024) -> dict:
        text, _ = self.chat(system, user, max_tokens=max_tokens, json_mode=True)
        return json.loads(text)

    # ------------------------------------------------------------------
    def _respond(self, system: str, user: str) -> str:
        low_user = user.lower()
        if "security classifier" in system:
            if "ignore previous" in low_user or "system prompt" in low_user \
                    or "api key" in low_user or "jailbreak" in low_user:
                return json.dumps({"block": True, "category": "direct",
                                   "reason": "stub: manipulation detected"})
            return json.dumps({"block": False, "category": "normal",
                               "reason": "stub: benign"})
        if "decomposition step" in system:
            if "email" in low_user or "send" in low_user:
                return json.dumps([{"sub_question": "Project Phoenix kickoff email from David Okafor", "tool": "gmail"}])
            if "blocker" in low_user or "issue" in low_user:
                return json.dumps([{"sub_question": "blocked payments sandbox rate limits", "tool": "jira"}])
            if "goal" in low_user or "roadmap" in low_user or "pilot" in low_user:
                return json.dumps([{"sub_question": "Project Phoenix goals design partner pilots coverage", "tool": "notion"}])
            if "newsletter" in low_user or "happy teams" in low_user:
                return json.dumps([{"sub_question": "tips for happy teams newsletter", "tool": "content"}])
            return json.dumps([])
        if "Classify the user request" in system:
            if "send" in low_user or "delete" in low_user:
                tool = "gmail" if "email" in low_user else "notion"
                verb = "send_email" if "email" in low_user else "delete_page"
                return json.dumps({"intent": "action", "tool": tool,
                                   "action": verb, "subject": "test subject"})
            return json.dumps({"intent": "research"})
        if "You synthesize a final answer" in system:
            return ("The mobile beta launches by November 15 [1]. "
                    "Payments sandbox rate limits are a blocker [2].")
        if "verification" in system or "verify citations" in system.lower():
            return json.dumps({"ok": True, "errors": []})
        if "Return ONLY valid JSON" in system:
            return json.dumps({"answer": "synthesized from evidence [1]"})
        return "canned answer with [1] citation"
