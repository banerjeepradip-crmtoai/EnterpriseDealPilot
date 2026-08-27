# Pricing MCP adapter

Owns the deterministic quote calculation (bundle price, discount math) that
the Solution & Pricing agent calls. Gemini recommends a bundle; this
service is the only thing allowed to produce an authoritative total — see
"Findings and learnings to report" in the architecture doc.

## Contract

- `get_eligible_bundles(data_residency)` — filters `catalogue.py`'s static
  bundle list by region restriction. `data_residency=None` returns every
  unrestricted bundle.
- `get_bundle_price(bundle_id, quantity, discount_pct, data_residency)` —
  computes subtotal, discount, and grand total, flags whether the discount
  needs approval (`> 10%`, mirroring the architecture doc's ">10% requires
  CFO" rule), and signs the result with HMAC-SHA256.

The signature is the point: `mcp-services/salesforce/client.py`'s future
`create_quote_draft` must reject a quote whose totals don't match what this
service actually signed, so an agent (or a bug) can never write a price to
Salesforce that this service didn't compute. `verify_signature()` in
`client.py` does that check.

`PRICING_SIGNING_SECRET` is a placeholder dev secret in code — replace it
via Secret Manager before this ever runs anywhere but a laptop.

## Run standalone

```
cd mcp-services/pricing
python server.py
```

## Test

```
pytest tests/test_pricing_client.py
```
