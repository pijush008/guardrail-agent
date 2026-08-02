"""Thin LLM client wrapper that tracks tokens + latency per call.

All calls in the pipeline go through this module so the metrics collector
can see real usage numbers (prompt/completion/total tokens, duration).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI

from .config import get_settings


@dataclass
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_ms: float = 0.0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self._client = OpenAI(
            api_key=self.settings.api_key or "unused",
            base_url=self.settings.base_url,
        )
        self.usage = LLMUsage()

    def chat(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: Optional[float] = None,
        json_mode: bool = False,
    ) -> tuple[str, LLMUsage]:
        """Return (text, usage). Raises LLMError on transport failure."""
        t0 = time.perf_counter()
        kwargs = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = self._client.chat.completions.create(
                model=self.settings.model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                max_tokens=max_tokens,
                temperature=self.settings.temperature if temperature is None else temperature,
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"LLM call failed: {exc}") from exc

        dm = resp.usage
        self.usage.prompt_tokens += dm.prompt_tokens
        self.usage.completion_tokens += dm.completion_tokens
        self.usage.duration_ms += (time.perf_counter() - t0) * 1000.0

        return (
            resp.choices[0].message.content or "",
            LLMUsage(prompt_tokens=dm.prompt_tokens,
                     completion_tokens=dm.completion_tokens,
                     duration_ms=(time.perf_counter() - t0) * 1000.0),
        )

    def chat_json(self, system: str, user: str, max_tokens: int = 1024) -> dict:
        import json
        text, _ = self.chat(system, user, max_tokens=max_tokens, json_mode=True)
        return json.loads(text)


class _Noop:  # pragma: no cover - placeholder
    def __getattr__(self, _):
        return lambda *a, **k: None