"""Static product catalogue.

A real catalogue would live in Salesforce Product2/PricebookEntry records
or a dedicated database; Phase 2 only needs enough bundles to prove
eligible-bundle selection and deterministic pricing work end to end.
`eligible_regions=None` means no data-residency restriction.
"""
from __future__ import annotations

BUNDLES = {
    "bundle_eu_secure": {
        "name": "Network Monitoring — EU Secure",
        "unit_price": 3200.00,
        "eligible_regions": {"EU"},
        "description": "EU-hosted network monitoring; customer data never leaves the EU region.",
    },
    "bundle_global_standard": {
        "name": "Network Monitoring — Global Standard",
        "unit_price": 2400.00,
        "eligible_regions": None,
        "description": "Standard multi-region network monitoring bundle.",
    },
    "bundle_fleet_telematics": {
        "name": "Fleet Telematics — Standard",
        "unit_price": 240.00,
        "eligible_regions": None,
        "description": "Per-vehicle fleet telematics and tracking, priced per vehicle.",
    },
}


def eligible_bundles(data_residency: str | None) -> dict:
    """Bundles whose region restriction, if any, accepts this residency value."""
    if not data_residency:
        return dict(BUNDLES)
    return {
        bundle_id: bundle
        for bundle_id, bundle in BUNDLES.items()
        if bundle["eligible_regions"] is None or data_residency in bundle["eligible_regions"]
    }
