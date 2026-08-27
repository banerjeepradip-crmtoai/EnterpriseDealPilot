"""Contract tests for idempotent quote-draft creation.

Covers two of the architecture doc's test matrix rows directly:
"Duplicate callback" (no duplicate Quote from a retried call) and
"Pricing mismatch" (quote creation rejected when totals don't match the
pricing service's signature).
"""
from pathlib import Path

import pytest

from _loader import load_module

_pricing_client = load_module(
    Path(__file__).resolve().parents[1] / "mcp-services" / "pricing" / "client.py",
    "dealpilot_test_pricing_client_for_quotes",
)
_salesforce_client = load_module(
    Path(__file__).resolve().parents[1] / "mcp-services" / "salesforce" / "client.py",
    "dealpilot_test_salesforce_client_for_quotes",
)
# Reached through _salesforce_client.quote_store, not loaded separately —
# see tests/test_opportunity_update.py for why a second independent load
# of the same file would be a distinct module object with its own class
# identities, which matters the moment anything here does an isinstance
# or except check against it.
_quote_store = _salesforce_client.quote_store

price_bundle = _pricing_client.price_bundle
create_quote_draft = _salesforce_client.create_quote_draft


@pytest.fixture(autouse=True)
def _clean_quote_store():
    _quote_store._reset_for_tests()
    yield
    _quote_store._reset_for_tests()


def test_create_quote_draft_accepts_a_validly_signed_quote():
    quote_line = price_bundle("bundle_fleet_telematics", quantity=40)

    quote = create_quote_draft(
        opportunity_id="opp_ready_example",
        quote_line=quote_line,
        expiry="2026-11-15",
        idempotency_key="opp_ready_example:v1",
    )

    assert quote["opportunity_id"] == "opp_ready_example"
    assert quote["grand_total"] == 9600.00
    assert quote["idempotent_replay"] is False


def test_repeated_call_with_same_idempotency_key_never_creates_a_duplicate():
    quote_line = price_bundle("bundle_fleet_telematics", quantity=40)

    first = create_quote_draft(
        "opp_ready_example", quote_line, "2026-11-15", "opp_ready_example:v1"
    )
    second = create_quote_draft(
        "opp_ready_example", quote_line, "2026-11-15", "opp_ready_example:v1"
    )

    assert first["quote_id"] == second["quote_id"]
    assert second["idempotent_replay"] is True


def test_create_quote_draft_rejects_a_tampered_total():
    quote_line = price_bundle("bundle_fleet_telematics", quantity=40)
    quote_line["grand_total"] = 1.00  # hallucinated/edited total

    with pytest.raises(ValueError):
        create_quote_draft(
            "opp_ready_example", quote_line, "2026-11-15", "opp_ready_example:v2"
        )
