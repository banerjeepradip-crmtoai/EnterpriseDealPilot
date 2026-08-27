"""Contract tests for the gated email send.

These are the tests that actually prove the security test case's stopping
point: an unauthorized, wrong-recipient, reused, or off-domain send must
be refused, with no partial send in any case.
"""
from pathlib import Path

import pytest

from _loader import load_module

_client = load_module(
    Path(__file__).resolve().parents[1] / "mcp-services" / "communication" / "client.py",
    "dealpilot_test_communication_client",
)

request_send_token = _client.request_send_token
authorize_send = _client.authorize_send
send_email = _client.send_email
get_send_token_status = _client.get_send_token_status
SendNotAuthorized = _client.SendNotAuthorized
SendTokenNotFound = _client.SendTokenNotFound


def setup_function():
    _client._reset_for_tests()


def teardown_function():
    _client._reset_for_tests()


def test_request_creates_a_pending_token():
    token = request_send_token("quote_abc", "buyer@baltic-freight.example")
    assert token["status"] == "PENDING"


def test_send_is_refused_before_authorization():
    token = request_send_token("quote_abc", "buyer@baltic-freight.example")

    with pytest.raises(SendNotAuthorized):
        send_email("quote_abc", "buyer@baltic-freight.example", "Subject", "Body", token["token_id"])


def test_send_succeeds_after_authorization():
    token = request_send_token("quote_abc", "buyer@baltic-freight.example")
    authorize_send(token["token_id"], authorized_by="sales_manager@example.com")

    result = send_email(
        "quote_abc", "buyer@baltic-freight.example", "Subject", "Body", token["token_id"]
    )

    assert result["to"] == "buyer@baltic-freight.example"
    assert get_send_token_status(token["token_id"])["used"] is True


def test_token_cannot_be_reused():
    token = request_send_token("quote_abc", "buyer@baltic-freight.example")
    authorize_send(token["token_id"], authorized_by="sales_manager@example.com")
    send_email("quote_abc", "buyer@baltic-freight.example", "Subject", "Body", token["token_id"])

    with pytest.raises(SendNotAuthorized):
        send_email(
            "quote_abc", "buyer@baltic-freight.example", "Subject 2", "Body 2", token["token_id"]
        )


def test_token_does_not_authorize_a_different_recipient():
    """The actual stopping point for the security test case: a token bound
    to the real customer contact must not authorize sending to an
    attacker's address, even with a valid, authorized token in hand.
    """
    token = request_send_token("quote_abc", "buyer@baltic-freight.example")
    authorize_send(token["token_id"], authorized_by="sales_manager@example.com")

    with pytest.raises(SendNotAuthorized):
        send_email("quote_abc", "attacker@example.com", "Subject", "Body", token["token_id"])


def test_token_does_not_authorize_a_different_quote():
    token = request_send_token("quote_abc", "buyer@baltic-freight.example")
    authorize_send(token["token_id"], authorized_by="sales_manager@example.com")

    with pytest.raises(SendNotAuthorized):
        send_email(
            "quote_other", "buyer@baltic-freight.example", "Subject", "Body", token["token_id"]
        )


def test_unknown_token_raises_not_found():
    with pytest.raises(SendTokenNotFound):
        send_email("quote_abc", "buyer@baltic-freight.example", "Subject", "Body", "tok_does_not_exist")
