"""Unit tests for the mock tool adapters and failure simulation."""
import pytest

from agent.models import EvidenceDoc
from agent.tools import (
    Tool,
    ToolAuthError,
    ToolError,
    ToolMalformed,
    ToolRateLimit,
    ToolRegistry,
    ToolTimeout,
    action_catalog,
    build_default_registry,
    execute_action,
    is_high_stakes,
)


@pytest.fixture
def reg():
    return build_default_registry()


def test_registry_has_tools(reg):
    assert set(reg.names()) == {"gmail", "notion", "jira", "content"}


def test_gmail_search_finds_email(reg):
    docs = reg.search("gmail", "Project Phoenix kickoff")
    assert docs
    assert docs[0].source == "Gmail"


def test_notion_search_finds_goals(reg):
    docs = reg.search("notion", "goals")
    assert docs
    assert any("beta" in d.content for d in docs)


def test_jira_search_finds_blocker(reg):
    docs = reg.search("jira", "blocker payments")
    assert docs
    assert any("PHX-101" in d.content for d in docs)


def test_timeout_fault(reg):
    reg.fault("gmail", "timeout")
    with pytest.raises(ToolTimeout):
        reg.search("gmail", "anything")


def test_auth_fault(reg):
    reg.fault("notion", "auth")
    with pytest.raises(ToolAuthError):
        reg.search("notion", "anything")


def test_rate_fault(reg):
    reg.fault("jira", "rate")
    with pytest.raises(ToolRateLimit):
        reg.search("jira", "anything")


def test_malformed_fault(reg):
    reg.fault("gmail", "malformed")
    with pytest.raises(ToolMalformed):
        reg.search("gmail", "anything")


def test_clear_faults(reg):
    reg.fault("gmail", "timeout")
    reg.clear_faults()
    docs = reg.search("gmail", "kickoff")
    assert docs


def test_unknown_tool_raises(reg):
    with pytest.raises(ToolError):
        reg.search("slack", "hi")


def test_high_stakes_catalog():
    assert is_high_stakes("gmail", "send_email")
    assert is_high_stakes("notion", "delete_page")
    assert is_high_stakes("jira", "delete_issue")
    assert not is_high_stakes("gmail", "search")


def test_execute_action_requires_high_stakes(reg):
    with pytest.raises(ToolError):
        execute_action("gmail", "search", "x")


def test_execute_action_simulated():
    out = execute_action("gmail", "send_email", "a@b.com")
    assert "EXECUTED" in out