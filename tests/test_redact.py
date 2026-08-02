"""Unit tests for the PII redactor."""
import pytest

from agent.models import EvidenceDoc
from agent.redact import PIIRedactor, contains_pii


@pytest.fixture
def red():
    return PIIRedactor()


def test_redacts_email(red):
    out, found = red.redact("contact maria.garcia@acmecorp.example for details")
    assert "[EMAIL_REDACTED]" in out
    assert "maria.garcia@acmecorp.example" not in out
    assert any(f.kind == "EMAIL" for f in found)


def test_redacts_phone(red):
    out, _ = red.redact("call +1 415 555 0132 today")
    assert "[PHONE_REDACTED]" in out
    assert "415 555" not in out


def test_redacts_ssn(red):
    out, _ = red.redact("SSN 111-22-3333 on file")
    assert "[SSN_REDACTED]" in out


def test_redacts_credit_card(red):
    out, _ = red.redact("card 4532 1234 5678 9012 exp 09/27")
    assert "[CARD_REDACTED]" in out


def test_redacts_dob(red):
    out, _ = red.redact("DOB 1989-05-14")
    assert "[DOB_REDACTED]" in out


def test_redacts_address(red):
    out, _ = red.redact("Address: 4100 Willow Avenue, Apt 3B, Chicago, IL 60618")
    assert "[ADDRESS_REDACTED]" in out


def test_redacts_name_hint(red):
    out, _ = red.redact("From: Maria Garcia, +1 415 555 0132")
    assert "Maria Garcia" not in out
    assert "[NAME_REDACTED]" in out


def test_plain_text_untouched(red):
    out, found = red.redact("What are the goals for Project Phoenix in Q3?")
    assert out == "What are the goals for Project Phoenix in Q3?"
    assert found == []


def test_evidence_redaction(red):
    doc = EvidenceDoc(id="g1", source="gmail",
                      content="From: maria.garcia@acmecorp.example — call +1 415 555 0132")
    new = red.redact_evidence(doc)
    assert new.redacted
    assert "maria.garcia@acmecorp.example" not in new.content
    assert "EMAIL" in new.metadata["pii_masked"]


def test_contains_pii():
    assert contains_pii("email me at a@b.com")
    assert not contains_pii("what is the roadmap?")


# ---------------------------------------------------------------------------
# Presidio-backed path (active when presidio is installed)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def presidio_red():
    from agent.redact import build_redactor
    r = build_redactor()
    if type(r).__name__ != "PresidioPIIRedactor":
        pytest.skip("presidio not installed")
    return r


def test_build_prefers_presidio():
    from agent.redact import build_redactor
    if not pytest.importorskip("presidio_analyzer"):
        return
    assert type(build_redactor()).__name__ == "PresidioPIIRedactor"


def test_presidio_catches_unlisted_name(presidio_red):
    # "Tomás Herrera" is NOT in the deterministic name-hint list; only the
    # Presidio NER pass can catch it.
    out, found = presidio_red.redact("Email Tomás Herrera the invoice details.")
    assert "[NAME_REDACTED]" in out
    assert "Tomás Herrera" not in out
    assert any(f.kind == "NAME" for f in found)


def test_presidio_keeps_product_terms(presidio_red):
    out, _found = presidio_red.redact(
        "Project Phoenix — Q3 kickoff. Our goal is to ship the mobile beta "
        "by November 15. Date: 2026-08-02T16:35:12Z"
    )
    assert "Project Phoenix" in out
    assert "November 15" in out
    assert "2026-08-02T16:35:12Z" in out
    assert "Q3" in out


def test_presidio_consistent_placeholders(presidio_red):
    out, _found = presidio_red.redact(
        "From: Sofia Reyes <sofia.reyes@acmecorp.example>, call +1 415 555 0132"
    )
    assert "sofia.reyes@acmecorp.example" not in out
    assert "[EMAIL_REDACTED]" in out
    assert "[NAME_REDACTED]" in out
    import re as _re
    assert _re.search(r"<[A-Z_]+>", out) is None  # no raw <ENTITY> placeholders