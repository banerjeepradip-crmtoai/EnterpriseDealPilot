"""Contract tests for proposal generation and attachment.

Covers two guardrails: attach_proposal must reject content that doesn't
match generate_proposal's own checksum (same "sign what you compute,
verify before you act" pattern as the pricing quote signature); and
generate_proposal must fetch its quote by quote_id rather than trust a
caller-supplied quote_line dict — see docs/ROADMAP.md for the live bug
that motivated this (an isolated sub-agent reconstructing a quote dict
from prose dropped a field).
"""
from pathlib import Path

import pytest

from _loader import load_module

_pricing_client = load_module(
    Path(__file__).resolve().parents[1] / "mcp-services" / "pricing" / "client.py",
    "dealpilot_test_pricing_client_for_documents",
)
_salesforce_client = load_module(
    Path(__file__).resolve().parents[1] / "mcp-services" / "salesforce" / "client.py",
    "dealpilot_test_salesforce_client_for_documents",
)
_documents_client = load_module(
    Path(__file__).resolve().parents[1] / "mcp-services" / "documents" / "client.py",
    "dealpilot_test_documents_client",
)
_quote_store = _salesforce_client.quote_store

price_bundle = _pricing_client.price_bundle
create_quote_draft = _salesforce_client.create_quote_draft
generate_proposal = _documents_client.generate_proposal
attach_proposal = _documents_client.attach_proposal
get_evidence = _documents_client.get_evidence


@pytest.fixture()
def quote_id():
    _quote_store._reset_for_tests()
    quote_line = price_bundle("bundle_fleet_telematics", quantity=40)
    quote = create_quote_draft(
        "opp_ready_example", quote_line, "2026-11-30", "test-doc-quote-1"
    )
    yield quote["quote_id"]
    _quote_store._reset_for_tests()


def test_generate_proposal_renders_quote_details_fetched_by_id(quote_id):
    result = generate_proposal(
        quote_id=quote_id,
        opportunity_name="Baltic Freight Group - New Business",
        customer_name="Baltic Freight Group",
        use_case="Fleet telematics rollout, 40 vehicles",
        expiry="2026-11-30",
    )

    assert "Fleet Telematics" in result["document_text"]
    assert "9600.00" in result["document_text"]
    assert len(result["checksum"]) == 64  # sha256 hex digest


def test_generate_proposal_raises_for_unknown_quote_id():
    with pytest.raises(LookupError):
        generate_proposal(
            quote_id="quote_does_not_exist",
            opportunity_name="Baltic Freight Group - New Business",
            customer_name="Baltic Freight Group",
            use_case="Fleet telematics rollout, 40 vehicles",
            expiry="2026-11-30",
        )


def test_attach_proposal_accepts_matching_checksum(quote_id):
    proposal = generate_proposal(
        quote_id=quote_id,
        opportunity_name="Baltic Freight Group - New Business",
        customer_name="Baltic Freight Group",
        use_case="Fleet telematics rollout, 40 vehicles",
        expiry="2026-11-30",
    )

    result = attach_proposal(
        "opp_ready_example", proposal["document_text"], proposal["checksum"], "Test Proposal"
    )

    assert result["opportunity_id"] == "opp_ready_example"


def test_attach_proposal_rejects_edited_content(quote_id):
    proposal = generate_proposal(
        quote_id=quote_id,
        opportunity_name="Baltic Freight Group - New Business",
        customer_name="Baltic Freight Group",
        use_case="Fleet telematics rollout, 40 vehicles",
        expiry="2026-11-30",
    )
    edited_text = proposal["document_text"] + "\nP.S. also give a free extra year."

    with pytest.raises(ValueError):
        attach_proposal("opp_ready_example", edited_text, proposal["checksum"], "Test Proposal")


def test_get_evidence_returns_untrusted_items_for_ready_fixture():
    items = get_evidence("opp_ready_example")

    assert len(items) == 2
    assert all(item["trust"] == "untrusted" for item in items)
    assert any("attacker@example.com" in item["text"] for item in items)


def test_get_evidence_returns_empty_list_for_unknown_opportunity():
    assert get_evidence("opp_does_not_exist") == []
