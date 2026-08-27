"""Deterministic pricing engine.

Gemini recommends a bundle; this module is the only thing allowed to
produce the authoritative price. Every quote carries an HMAC signature so
a downstream consumer (create_quote_draft) can reject a total that doesn't
match what this service actually computed — see the Controlled CRM tool
contract in the architecture doc, and "Findings and learnings to report":
a model should recommend, but a deterministic service must calculate.
"""
from __future__ import annotations

import hashlib
import hmac
import os

from catalogue import BUNDLES, eligible_bundles

# Phase 2 stand-in for a real secret in Secret Manager — replace before any
# deployment past local dev/testing.
_SIGNING_SECRET = os.environ.get(
    "PRICING_SIGNING_SECRET", "phase2-dev-signing-secret-not-for-prod"
).encode()

# Mirrors the ">10% discount requires CFO" enterprise rule in the
# architecture doc's memory model table — Phase 3 reads this flag to decide
# whether to route an approval, it does not re-derive the threshold.
DISCOUNT_APPROVAL_THRESHOLD_PCT = 10


class BundleNotFound(LookupError):
    pass


class BundleNotEligible(ValueError):
    pass


def list_eligible_bundles(data_residency: str | None = None) -> dict:
    """Bundles a customer with this data-residency constraint may buy."""
    return {
        bundle_id: {k: v for k, v in bundle.items() if k != "eligible_regions"}
        for bundle_id, bundle in eligible_bundles(data_residency).items()
    }


def price_bundle(
    bundle_id: str,
    quantity: int,
    discount_pct: float = 0.0,
    data_residency: str | None = None,
) -> dict:
    """Compute the authoritative total for a bundle and sign the result.

    Raises BundleNotFound for an unknown id, BundleNotEligible if the
    bundle's region restriction rejects this customer's data residency.
    """
    if bundle_id not in BUNDLES:
        raise BundleNotFound(f"Unknown bundle '{bundle_id}'")
    bundle = BUNDLES[bundle_id]
    allowed_regions = bundle["eligible_regions"]
    if allowed_regions is not None and data_residency not in allowed_regions:
        raise BundleNotEligible(
            f"Bundle '{bundle_id}' is not eligible for data residency '{data_residency}'"
        )
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if not (0 <= discount_pct <= 100):
        raise ValueError("discount_pct must be between 0 and 100")

    subtotal = round(bundle["unit_price"] * quantity, 2)
    discount_amount = round(subtotal * (discount_pct / 100), 2)
    grand_total = round(subtotal - discount_amount, 2)

    quote = {
        "bundle_id": bundle_id,
        "bundle_name": bundle["name"],
        "quantity": quantity,
        "unit_price": bundle["unit_price"],
        "subtotal": subtotal,
        "discount_pct": discount_pct,
        "discount_amount": discount_amount,
        "grand_total": grand_total,
        "requires_discount_approval": discount_pct > DISCOUNT_APPROVAL_THRESHOLD_PCT,
    }
    quote["signature"] = _sign(quote)
    return quote


def verify_signature(quote: dict) -> bool:
    """True if `quote`'s signature matches what this service computes for its own fields."""
    claimed = quote.get("signature")
    if not claimed:
        return False
    unsigned = {k: v for k, v in quote.items() if k != "signature"}
    return hmac.compare_digest(claimed, _sign(unsigned))


# Every field's canonical representation, applied before signing AND before
# verifying. Necessary because a quote signed here doesn't stay in Python's
# hands: it passes through an agent's tool-call JSON, where an LLM can (and
# does) re-emit 9600.0 as 9600 — same value, different Python type once
# json.loads gets it back, which would silently break naive str(value)
# signing. Casting every field to one fixed type/precision on both sides
# means the signature only depends on the value, never on which numeric
# type happened to survive that round trip.
_FIELD_CANONICALIZERS = {
    "bundle_id": str,
    "bundle_name": str,
    "quantity": lambda v: str(int(v)),
    "unit_price": lambda v: f"{float(v):.2f}",
    "subtotal": lambda v: f"{float(v):.2f}",
    "discount_pct": lambda v: f"{float(v):.2f}",
    "discount_amount": lambda v: f"{float(v):.2f}",
    "grand_total": lambda v: f"{float(v):.2f}",
    "requires_discount_approval": lambda v: str(bool(v)),
}


def _sign(quote_without_signature: dict) -> str:
    payload = "|".join(
        f"{k}={_FIELD_CANONICALIZERS[k](quote_without_signature[k])}"
        for k in sorted(quote_without_signature)
        if k in _FIELD_CANONICALIZERS
    )
    return hmac.new(_SIGNING_SECRET, payload.encode(), hashlib.sha256).hexdigest()
