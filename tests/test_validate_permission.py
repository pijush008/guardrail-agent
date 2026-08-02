"""Unit tests for output/citation validation and the permission layer."""
import pytest

from agent.models import (
    ApprovalRecord,
    ApprovalStatus,
    EvidenceDoc,
    PermissionStateError,
    PlanStep,
)
from agent.permission import (
    ApprovalManager,
    ConfirmationSender,
    PermissionDenied,
    PermissionLayer,
    classify_action,
)
from agent.validate import CitationValidator, SchemaValidator, parse_citations

EVIDENCE = [
    EvidenceDoc(id="g1", source="gmail", content="Launch mobile beta by November 15."),
    EvidenceDoc(id="j1", source="jira", content="Payments sandbox rate limits us."),
]


# ---- Citation validation (structural; no LLM) ----

def test_parse_citations():
    assert parse_citations("Goals are A[1] and B[2]") == [1, 2]
    assert parse_citations("A [1] B [2]") == [1, 2]


def test_citations_valid():
    v = CitationValidator(llm=None, min_citations=1)
    ok, errs = v.validate_structural("The beta launches in November [1].", EVIDENCE)
    assert ok and not errs


def test_citations_invalid_ref():
    v = CitationValidator(llm=None, min_citations=1)
    ok, errs = v.validate_structural("The beta launches in November [7].", EVIDENCE)
    assert not ok
    assert any("7" in e for e in errs)


def test_citations_none():
    v = CitationValidator(llm=None, min_citations=1)
    ok, errs = v.validate_structural("The beta launches in November.", EVIDENCE)
    assert not ok
    assert any("no citations" in e for e in errs)


# ---- Schema validation ----

def test_schema_valid_json():
    v = SchemaValidator(expected_keys=["summary", "citations"])
    ok, err = v.validate('{"summary": "hi", "citations": 2}')
    assert ok and err is None


def test_schema_missing_key():
    v = SchemaValidator(expected_keys=["summary", "citations"])
    ok, err = v.validate('{"summary": "hi"}')
    assert not ok and "summary" not in err.replace("summary", "")


def test_schema_invalid_json():
    v = SchemaValidator(expected_keys=["summary"])
    ok, err = v.validate("not json at all")
    assert not ok and err is not None


# ---- Permission layer ----

def test_classify_action():
    assert classify_action("gmail", "send_email") == "high"
    assert classify_action("gmail", "search") == "read"


def test_permission_gate_approves():
    layer = PermissionLayer()
    res = layer.evaluate("gmail", "send_email", "boss@corp.example", reason="user asked")
    assert res.risk == "high"
    assert res.approval is not None
    assert res.approval.approved is True  # auto-approve in test env
    out = layer.execute("gmail", "send_email", "boss@corp.example", res.approval)
    assert "EXECUTED" in out


def test_execution_blocked_without_approval():
    layer = PermissionLayer()
    with pytest.raises(PermissionDenied):
        layer.execute("jira", "delete_issue", "PHX-101", None)


def test_execution_blocked_after_denial():
    mgr = ApprovalManager(auto_approve=False)
    layer = PermissionLayer(approvals=mgr)
    res = layer.evaluate("jira", "delete_issue", "PHX-101", "cleanup")
    with pytest.raises(PermissionDenied):
        layer.execute("jira", "delete_issue", "PHX-101", res.approval)


def test_approval_manager_records():
    mgr = ApprovalManager(auto_approve=False)
    rec = mgr.request([PlanStep(action="gmail.send_email", tool="gmail", subject="x", rationale="y")])
    assert rec.approved is None  # undecided until an approver acts
    assert len(mgr.records) == 1
    rec2 = mgr.approve(rec.id, "human")
    assert rec2.approved is True
    assert rec2.approver == "human"


def test_auto_approve_path():
    mgr = ApprovalManager(auto_approve=True)
    rec = mgr.request([PlanStep(action="gmail.send_email", tool="gmail", subject="x", rationale="y")])
    assert rec.approved is True
    assert rec.approver == "automated"


def test_confirmation_sender_emits_token():
    s = ConfirmationSender()
    rec = ApprovalRecord()
    msg = s.send(rec, [PlanStep(action="notion.delete_page", tool="notion", subject="n1", rationale="r")])
    assert rec.id in msg
    assert s.sent


# ---- Approval state machine ----

def _plan():
    return [PlanStep(action="jira.delete_issue", tool="jira", subject="PHX-101", rationale="r")]


def test_approval_lifecycle_transitions():
    rec = ApprovalRecord(plan=_plan())
    assert rec.status == ApprovalStatus.PENDING.value
    rec.finalize(True, "human")
    assert rec.status == ApprovalStatus.APPROVED.value
    rec.transition(ApprovalStatus.EXECUTING.value)
    rec.transition(ApprovalStatus.EXECUTED.value)
    assert rec.executed_at is not None
    # Terminal states can never transition again.
    for bad in (ApprovalStatus.EXECUTING, ApprovalStatus.EXECUTED, ApprovalStatus.APPROVED):
        with pytest.raises(PermissionStateError):
            rec.transition(bad.value)


def test_approval_disallowed_transitions():
    # PENDING -> EXECUTED is not allowed.
    rec = ApprovalRecord(plan=_plan())
    with pytest.raises(PermissionStateError):
        rec.transition(ApprovalStatus.EXECUTED.value)
    # REJECTED -> EXECUTED is not allowed.
    rec.finalize(False, "human")
    with pytest.raises(PermissionStateError):
        rec.transition(ApprovalStatus.EXECUTED.value)
    with pytest.raises(PermissionStateError):
        rec.transition(ApprovalStatus.EXECUTING.value)


def test_approval_expiry_blocks_execution():
    import time as _t
    # Approved while valid, then the approval window passes.
    rec = ApprovalRecord(plan=_plan(), expires_at=_t.time() + 60)
    rec.finalize(True, "human")
    assert rec.status == ApprovalStatus.APPROVED.value
    rec.expires_at = _t.time() - 1.0  # backdate the expiry window
    layer = PermissionLayer(approvals=ApprovalManager(auto_approve=False))
    with pytest.raises(PermissionDenied) as ei:
        layer.execute("jira", "delete_issue", "PHX-101", rec)
    assert "expired" in str(ei.value)
    assert rec.status == ApprovalStatus.EXPIRED.value


def test_expired_cannot_be_approved():
    import time as _t
    rec = ApprovalRecord(plan=_plan(), expires_at=_t.time() - 1.0)
    with pytest.raises(PermissionStateError):
        rec.finalize(True, "human")


def test_idempotency_prevents_double_execution():
    mgr = ApprovalManager(auto_approve=True)
    layer = PermissionLayer(approvals=mgr)
    res = layer.evaluate("jira", "delete_issue", "PHX-101", "cleanup")
    out = layer.execute("jira", "delete_issue", "PHX-101", res.approval)
    assert "EXECUTED" in out
    assert res.approval.status == ApprovalStatus.EXECUTED.value
    # Second execution with the same approval must be denied.
    with pytest.raises(PermissionDenied) as ei:
        layer.execute("jira", "delete_issue", "PHX-101", res.approval)
    assert "idempotency" in str(ei.value)


def test_rejected_approval_never_executes():
    mgr = ApprovalManager(auto_approve=False)
    layer = PermissionLayer(approvals=mgr)
    res = layer.evaluate("jira", "delete_issue", "PHX-101", "cleanup")
    mgr.deny(res.approval.id, "human")
    assert res.approval.status == ApprovalStatus.REJECTED.value
    with pytest.raises(PermissionDenied):
        layer.execute("jira", "delete_issue", "PHX-101", res.approval)


def test_audit_trail_records_idempotency_key():
    rec = ApprovalRecord(plan=_plan())
    rec.finalize(True, "human")
    rec.transition(ApprovalStatus.EXECUTING.value)
    rec.transition(ApprovalStatus.EXECUTED.value)
    assert len(rec.events) == 3
    assert all(e["idempotency_key"] == rec.idempotency_key for e in rec.events)
    assert rec.events[1]["to"] == ApprovalStatus.EXECUTING.value