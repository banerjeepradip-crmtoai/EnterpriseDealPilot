"""Pricing MCP adapter.

Exposes the catalogue and the deterministic pricing calculation as MCP
tools. Run standalone for local dev (stdio transport):

    cd mcp-services/pricing
    python server.py

Deployed to Cloud Run, this same file serves streamable-http instead —
Cloud Run always sets $PORT, which is what selects the transport below.
See infrastructure/README.md for the deploy command.

Pinned to `mcp>=1.24,<2` (FastMCP, not the v2 MCPServer rename) because
google-adk 2.7.1's MCPToolset — the client side any agent uses to call
this service once deployed — only supports that range; see
docs/ROADMAP.md's "ADK's MCP client vs this server's mcp version" note.
"""
from __future__ import annotations

import os

from client import list_eligible_bundles, price_bundle, verify_signature
from mcp.server.fastmcp import Context, FastMCP
from observability import correlation_id_from, log_tool_call

mcp = FastMCP("pricing", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))


@mcp.tool()
def get_eligible_bundles(data_residency: str | None = None, *, ctx: Context) -> dict:
    """List product bundles eligible for a customer's data-residency requirement.

    Pass data_residency=None (or omit it) when the requirement is not yet
    confirmed — every bundle without a region restriction comes back.
    """
    log_tool_call(correlation_id_from(ctx), "pricing", "get_eligible_bundles", data_residency=data_residency)
    return list_eligible_bundles(data_residency)


@mcp.tool()
def get_bundle_price(
    bundle_id: str,
    quantity: int,
    discount_pct: float = 0.0,
    data_residency: str | None = None,
    *,
    ctx: Context,
) -> dict:
    """Return the authoritative, signed price for a bundle.

    This is the only source of truth for a total — never present a number
    that did not come back from this tool.
    """
    log_tool_call(correlation_id_from(ctx), "pricing", "get_bundle_price", bundle_id=bundle_id, quantity=quantity)
    return price_bundle(bundle_id, quantity, discount_pct, data_residency)


@mcp.tool()
def verify_quote_signature(quote: dict, *, ctx: Context) -> dict:
    """True/false whether `quote`'s signature matches what this service
    would compute for its own fields — the remote-call counterpart to
    calling verify_signature() in-process, for once the Salesforce
    service is a separate deployed Cloud Run instance and can no longer
    import this one directly. See mcp-services/salesforce/client.py.
    """
    log_tool_call(correlation_id_from(ctx), "pricing", "verify_quote_signature", quote_id=quote.get("bundle_id"))
    return {"verified": verify_signature(quote)}


if __name__ == "__main__":
    mcp.run(transport="streamable-http" if os.environ.get("PORT") else "stdio")
