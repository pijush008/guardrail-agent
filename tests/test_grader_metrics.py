"""Unit tests for the grader and metrics collector (pure logic)."""
import pytest

from agent.llm import LLMUsage
from agent.models import AgentResult
from agent.metrics import MetricsCollector
from evals.grader import RuleJudge


def _result(**kw) -> AgentResult:
    r = AgentResult(question="q")
    for k, v in kw.items():
        setattr(r, k, v)
    return r


def test_grader_blocked_criterion():
    j = RuleJudge()
    ok, _ = j.check("blocked", _result(blocked=True), "irrelevant", {})
    assert ok
    ok, _ = j.check("blocked", _result(blocked=False, answer="hello"), "irrelevant", {})
    assert not ok


def test_grader_cites():
    j = RuleJudge()
    r = _result(citation_valid=True, citation_errors=[])
    ok, _ = j.check("cites_at_least_1", r, "The beta is Nov 15 [1].", {})
    assert ok
    r2 = _result(citation_valid=False, citation_errors=["no citations"])
    ok, _ = j.check("cites_at_least_1", r2, "The beta is Nov 15.", {})
    assert not ok


def test_grader_mentions_keyword():
    j = RuleJudge()
    ok, _ = j.check("mentions_beta", _result(), "The mobile beta ships soon.", {})
    assert ok
    ok, _ = j.check("mentions_rate_limit", _result(), "The sandbox rate-limits us.", {})
    assert ok


def test_grader_redacted():
    j = RuleJudge()
    ok, _ = j.check("redacted", _result(), "Contact [EMAIL_REDACTED] for info.", {})
    assert ok
    ok, _ = j.check("redacted", _result(), "Contact maria.garcia@acmecorp.example.", {})
    assert not ok


def test_grader_graceful_degrade():
    j = RuleJudge()
    ok, _ = j.check("mentions_unavailable", _result(), "Jira data unavailable.", {})
    assert ok


def test_metrics_collector_summary():
    c = MetricsCollector(out_dir="/tmp/opencode/metrics_test")
    c.add("a", "normal", {"blocked": False, "latency_ms": 10, "tokens": 5}, True)
    c.add("b", "adversarial", {"blocked": True, "latency_ms": 20, "tokens": 5, "attack": True}, True)
    c.add("c", "adversarial", {"blocked": False, "latency_ms": 30, "tokens": 5, "attack": True}, False)
    s = c.summarize()
    assert s["n"] == 3
    assert s["pass_rate"] == pytest.approx(66.67, abs=0.1)
    assert s["refusal_rate"]["blocked"] == 1
    assert s["refusal_rate"]["attacks"] == 2
    assert s["latency"]["avg"] == 20.0
    assert s["tokens"]["total"] == 15