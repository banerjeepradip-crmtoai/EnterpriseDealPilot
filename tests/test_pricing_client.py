"""Contract tests for the deterministic pricing engine.

The thing that actually matters here: a total that didn't come from
price_bundle() must never verify, and a total that did must always verify
— that's what create_quote_draft will lean on later to reject a mismatched
quote (see mcp-services/pricing/README.md).
"""
from pathlib import Path

import pytest

from _loader import load_module

_client = load_module(
    Path(__file__).resolve().parents[1] / "mcp-services" / "pricing" / "client.py",
    "dealpilot_test_pricing_client",
)
BundleNotEligible = _client.BundleNotEligible
BundleNotFound = _client.BundleNotFound
price_bundle = _client.price_bundle
verify_signature = _client.verify_signature


def test_price_bundle_computes_subtotal_discount_and_total():
    quote = price_bundle("bundle_fleet_telematics", quantity=40, discount_pct=0)

    assert quote["subtotal"] == 9600.00
    assert quote["discount_amount"] == 0.00
    assert quote["grand_total"] == 9600.00
    assert quote["requires_discount_approval"] is False


def test_price_bundle_applies_discount_and_flags_approval_over_threshold():
    quote = price_bundle("bundle_global_standard", quantity=10, discount_pct=15)

    assert quote["subtotal"] == 24000.00
    assert quote["discount_amount"] == 3600.00
    assert quote["grand_total"] == 20400.00
    assert quote["requires_discount_approval"] is True


def test_eu_secure_bundle_rejects_non_eu_residency():
    with pytest.raises(BundleNotEligible):
        price_bundle("bundle_eu_secure", quantity=1, data_residency="US")


def test_eu_secure_bundle_accepts_eu_residency():
    quote = price_bundle("bundle_eu_secure", quantity=2, data_residency="EU")
    assert quote["grand_total"] == 6400.00


def test_unknown_bundle_raises():
    with pytest.raises(BundleNotFound):
        price_bundle("bundle_does_not_exist", quantity=1)


def test_signature_verifies_for_untouched_quote():
    quote = price_bundle("bundle_fleet_telematics", quantity=40)
    assert verify_signature(quote) is True


def test_signature_fails_for_tampered_total():
    quote = price_bundle("bundle_fleet_telematics", quantity=40)
    quote["grand_total"] = 1.00  # an agent (or bug) claiming a fake total

    assert verify_signature(quote) is False


def test_signature_survives_int_float_type_coercion():
    """Regression: found live via Vertex AI. A quote's numbers pass through
    an agent's tool-call JSON before reaching create_quote_draft — an LLM
    re-emitting 9600.0 as 9600 is a real, observed thing, not a hypothetical.
    Naive str(value) signing broke on exactly this: same value, different
    Python type once json.loads gets it back. Signing must be blind to
    which numeric type survived the round trip.
    """
    quote = price_bundle("bundle_fleet_telematics", quantity=40, discount_pct=0)

    coerced = dict(quote)
    coerced["grand_total"] = int(coerced["grand_total"])  # 9600.0 -> 9600
    coerced["unit_price"] = int(coerced["unit_price"])
    coerced["subtotal"] = int(coerced["subtotal"])
    coerced["discount_amount"] = int(coerced["discount_amount"])
    coerced["discount_pct"] = int(coerced["discount_pct"])
    coerced["quantity"] = float(coerced["quantity"])  # and the other direction

    assert verify_signature(coerced) is True


def test_signature_still_rejects_a_genuinely_different_total_of_a_different_type():
    quote = price_bundle("bundle_fleet_telematics", quantity=40)
    quote["grand_total"] = 1  # wrong value AND a type-coerced int

    assert verify_signature(quote) is False
