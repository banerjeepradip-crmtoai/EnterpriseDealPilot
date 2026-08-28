"""Solution & Pricing agent.

Recommends an eligible product bundle and quantity from the opportunity's
use case and data residency, then calls the pricing service for the
authoritative total. Never presents a number it didn't get back from
get_bundle_price — that tool's signature is what lets a later step reject
a tampered or hallucinated total (see mcp-services/pricing/README.md).

Runs standalone via `adk web agents` (pick "solution_pricing"), or as a
sub-tool the Deal Orchestrator calls once an opportunity has no missing
fields (see agents/orchestrator/agent.py).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from google.adk.agents import Agent


def _load_module(path: Path, unique_name: str):
    """Load a module by file path, under a unique sys.modules name.

    See agents/orchestrator/agent.py's copy of this helper for why: every
    mcp-services/* adapter has its own client.py, and a bare `import
    client` would silently collide with a sibling service's client.py the
    moment both get loaded into the same process.
    """
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(unique_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_pricing_client_module = _load_module(
    Path(__file__).resolve().parents[2] / "mcp-services" / "pricing" / "client.py",
    "dealpilot_pricing_client",
)
list_eligible_bundles = _pricing_client_module.list_eligible_bundles
price_bundle = _pricing_client_module.price_bundle

# Solution & Pricing's write authority is "Quote draft only" (see the
# agent fleet table in the architecture doc) — it may create a Quote
# draft from its own signed price, nothing else in Salesforce.
_salesforce_client_module = _load_module(
    Path(__file__).resolve().parents[2] / "mcp-services" / "salesforce" / "client.py",
    "dealpilot_salesforce_client_for_pricing",
)
_sf_create_quote_draft = _salesforce_client_module.create_quote_draft


def get_eligible_bundles(data_residency: str | None = None) -> dict:
    """List product bundles eligible for a customer's data-residency requirement.

    Args:
        data_residency: The confirmed Account.Data_Residency__c value (for
            example "EU"), or omit/None if there is no confirmed
            restriction — every bundle without a region restriction comes
            back either way.
    """
    return list_eligible_bundles(data_residency)


def get_bundle_price(
    bundle_id: str,
    quantity: int,
    discount_pct: float = 0.0,
    data_residency: str | None = None,
) -> dict:
    """Return the authoritative, signed price for a bundle and quantity.

    This is the only source of truth for a total. Raises if the bundle is
    unknown or not eligible for the given data_residency.

    Args:
        bundle_id: A bundle id returned by get_eligible_bundles.
        quantity: Units of the bundle (for example, vehicle count for a
            per-vehicle bundle).
        discount_pct: Requested discount percentage, 0-100. Defaults to 0.
        data_residency: The same value passed to get_eligible_bundles, so
            eligibility is re-checked at price time.
    """
    return price_bundle(bundle_id, quantity, discount_pct, data_residency)


def create_quote_draft(opportunity_id: str, quote_line: dict, expiry: str) -> dict:
    """Create (or idempotently replay) a Quote draft from a signed price.

    Args:
        opportunity_id: The opportunity this quote is for.
        quote_line: Pass exactly the dict get_bundle_price returned — never
            an edited copy. Its signature is re-verified here; a mismatch
            raises instead of writing anything.
        expiry: An ISO date roughly 30 days out unless told otherwise.

    Returns:
        The created (or replayed) quote, including quote_id and
        grand_total. requires_discount_approval on quote_line tells you
        whether this quote still needs an approval before it can proceed.
    """
    idempotency_key = (
        f"{opportunity_id}:{quote_line['bundle_id']}:"
        f"{quote_line['quantity']}:{quote_line['discount_pct']}"
    )
    return _sf_create_quote_draft(opportunity_id, quote_line, expiry, idempotency_key)


root_agent = Agent(
    # See agents/orchestrator/agent.py for why this is pinned to the
    # Gemini 3 family rather than a "-latest" alias or gemini-2.5-*.
    model="gemini-3.6-flash",
    name="solution_pricing_agent",
    description=(
        "Recommends an eligible product bundle and quantity for a "
        "ready opportunity, then obtains the authoritative signed price."
    ),
    instruction="""
You are the Solution & Pricing agent for EnterpriseDealPilot.

You will be given an opportunity id, its use case description, amount,
and its account's confirmed data residency requirement (which may be
empty/none). You will also be told explicitly whether the seller has
already confirmed an exact bundle, quantity, and discount for this
opportunity, or whether this is a fresh request for a recommendation —
always follow whichever of the two sections below matches what you were
told, never assume.

## Fresh request — no confirmed bundle/quantity/discount given to you

1. Call get_eligible_bundles with the data residency to see which bundles
   this customer may buy.
2. From the use case description, pick the single bundle that best matches
   what the customer actually needs, and infer a reasonable quantity from
   the text (for example "40 vehicles" means quantity 40; if nothing in
   the text implies a quantity, use 1).
3. Call get_bundle_price with that bundle, quantity, and data residency,
   with discount_pct 0 unless you were told the seller already asked for
   a specific discount.
4. Report this back as a PROPOSED quote — bundle name, bundle_id,
   quantity, unit price, subtotal, discount, grand total. State plainly
   that nothing has been written to Salesforce yet and this needs the
   seller's explicit confirmation before any Quote record is created. Do
   NOT call create_quote_draft in this case, under any circumstances.

If no eligible bundle plausibly matches the use case, say so instead of
forcing a recommendation, and do not call get_bundle_price or
create_quote_draft.

## Confirmed request — you were told the seller already confirmed an
exact bundle_id, quantity, and discount_pct for this opportunity

5. Call get_bundle_price again with exactly those confirmed values — do
   not re-derive the bundle from the use case text this time, and do not
   change the quantity or discount from what you were told was confirmed.
6. Call create_quote_draft with the opportunity id, exactly the dict
   get_bundle_price returned, and an expiry about 30 days out.
7. Report back: bundle name, quantity, unit price, subtotal, discount,
   grand total, and the quote_id — all exactly as returned by the tools,
   never a number you computed yourself. State plainly whether
   requires_discount_approval is true or false, since that decides what
   happens next.

Never call create_quote_draft unless you were explicitly told the seller
already confirmed the bundle, quantity, and discount — a proposed quote
from the fresh-request path is not itself confirmation.
""".strip(),
    tools=[get_eligible_bundles, get_bundle_price, create_quote_draft],
)
