"""Agents configuration (read-only settings)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """All tunable knobs, overridable via environment variables."""

    model: str = field(
        default_factory=lambda: os.getenv(
            "GUARDRAIL_MODEL", os.getenv("OPENAI_MODEL", "llama-3.3-70b-versatile")
        )
    )
    base_url: str = field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")
    )
    api_key: str = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", "")
        or os.getenv("GROQ_API_KEY", "")
    )
    temperature: float = float(os.getenv("GUARDRAIL_TEMPERATURE", "0.0"))

    # ---- Input guardrail ----
    auto_block: bool = _env_bool("GUARDRAIL_AUTO_BLOCK", True)
    log_blocks: bool = _env_bool("GUARDRAIL_LOG_BLOCKS", True)

    # ---- Redaction ----
    redact_enabled: bool = _env_bool("GUARDRAIL_REDACT", True)
    placeholder: str = os.getenv("GUARDRAIL_PLACEHOLDER", "")

    # ---- Built-in tool failure simulation ----
    sim_timeout: bool = _env_bool("GUARDRAIL_SIM_TIMEOUT", True)
    sim_auth: bool = _env_bool("GUARDRAIL_SIM_AUTH", True)
    sim_rate_limit: bool = _env_bool("GUARDRAIL_SIM_RATE", True)
    sim_malformed: bool = _env_bool("GUARDRAIL_SIM_MALFORMED", True)

    # ---- Permission layer ----
    require_approval: bool = _env_bool("GUARDRAIL_REQUIRE_APPROVAL", True)
    auto_approve: bool = _env_bool("GUARDRAIL_AUTO_APPROVE", True)
    approval_timeout_s: float = float(os.getenv("GUARDRAIL_APPROVAL_TIMEOUT", "10"))

    # ---- Output / citation ----
    min_citations: int = int(os.getenv("GUARDRAIL_MIN_CITATIONS", "1"))
    citation_judge: bool = _env_bool("GUARDRAIL_CITATION_JUDGE", False)

    # ---- Misc ----
    no_tools: bool = _env_bool("GUARDRAIL_NO_TOOLS", False)

    # ---- Deterministic offline mode (no API key needed) ----
    fake_llm: bool = _env_bool("GUARDRAIL_FAKE_LLM", False)


_settings = Settings()


def get_settings() -> Settings:
    return _settings