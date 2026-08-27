"""Contract tests for approval routing and pause/resume.

Covers the "Approval rejected" test matrix row directly, and the
pause/resume mechanism the WAITING_APPROVAL state depends on: a request
must stay PENDING until explicitly decided, and a decided request must
never flip again.
"""
from pathlib import Path

import pytest

from _loader import load_module

_client = load_module(
    Path(__file__).resolve().parents[1] / "mcp-services" / "approval" / "client.py",
    "dealpilot_test_approval_client",
)

request_discount_approval = _client.request_discount_approval
get_approval_status = _client.get_approval_status
decide_approval = _client.decide_approval
ApprovalNotFound = _client.ApprovalNotFound
InvalidDecision = _client.InvalidDecision


@pytest.fixture(autouse=True)
def _clean_approval_store():
    _client._reset_for_tests()
    yield
    _client._reset_for_tests()


def test_request_creates_a_pending_record():
    record = request_discount_approval("quote_abc123", 15.0, "Strategic renewal")

    assert record["status"] == "PENDING"
    assert record["percentage"] == 15.0
    assert record["decided_by"] is None


def test_pending_request_stays_pending_until_decided():
    record = request_discount_approval("quote_abc123", 15.0, "Strategic renewal")

    status = get_approval_status(record["approval_id"])

    assert status["status"] == "PENDING"


def test_decide_approval_resolves_to_approved():
    record = request_discount_approval("quote_abc123", 15.0, "Strategic renewal")

    decided = decide_approval(
        record["approval_id"], "APPROVED", decided_by="cfo@example.com"
    )

    assert decided["status"] == "APPROVED"
    assert decided["decided_by"] == "cfo@example.com"
    assert decided["already_decided"] is False

    refreshed = get_approval_status(record["approval_id"])
    assert refreshed["status"] == "APPROVED"


def test_decide_approval_resolves_to_rejected_with_note():
    record = request_discount_approval("quote_abc123", 25.0, "Aggressive ask")

    decided = decide_approval(
        record["approval_id"],
        "REJECTED",
        decided_by="cfo@example.com",
        decision_note="Exceeds delegated authority",
    )

    assert decided["status"] == "REJECTED"
    assert decided["decision_note"] == "Exceeds delegated authority"


def test_deciding_an_already_decided_request_does_not_flip_it():
    record = request_discount_approval("quote_abc123", 15.0, "Strategic renewal")
    decide_approval(record["approval_id"], "APPROVED", decided_by="cfo@example.com")

    second = decide_approval(
        record["approval_id"], "REJECTED", decided_by="someone_else@example.com"
    )

    assert second["status"] == "APPROVED"  # unchanged
    assert second["already_decided"] is True


def test_invalid_decision_is_rejected():
    record = request_discount_approval("quote_abc123", 15.0, "Strategic renewal")

    with pytest.raises(InvalidDecision):
        decide_approval(record["approval_id"], "MAYBE", decided_by="cfo@example.com")


def test_unknown_approval_id_raises():
    with pytest.raises(ApprovalNotFound):
        get_approval_status("appr_does_not_exist")
