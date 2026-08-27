"""Salesforce MCP adapter.

This is the only process meant to ever hold Salesforce credentials. It
exposes narrow, field-allowlisted tools over MCP so no agent talks to
Salesforce directly. Run standalone for local dev (stdio transport):

    cd mcp-services/salesforce
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

from client import (
    create_content_version,
    create_quote_draft,
    get_client,
    get_quote,
    update_opportunity,
)
from mcp.server.fastmcp import Context, FastMCP
from observability import correlation_id_from, log_tool_call

mcp = FastMCP("salesforce", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))


@mcp.tool()
def get_opportunity(opportunity_id: str, *, ctx: Context) -> dict:
    """Return a whitelisted snapshot of a Salesforce Opportunity and its Account.

    Read-only. Fields outside the allowlist in client.py are never returned,
    per the Controlled CRM tool contract in the architecture doc.
    """
    log_tool_call(correlation_id_from(ctx), "salesforce", "get_opportunity", opportunity_id=opportunity_id)
    return get_client().get_opportunity(opportunity_id)


@mcp.tool()
def update_opportunity_field(
    opportunity_id: str, fields: dict, expected_version, idempotency_key: str, *, ctx: Context
) -> dict:
    """Apply a confirmed field update with optimistic locking.

    Only ALLOWED_WRITE_FIELDS may be set. expected_version must match the
    opportunity's current version or this raises VersionConflict.
    """
    log_tool_call(correlation_id_from(ctx), "salesforce", "update_opportunity_field", opportunity_id=opportunity_id)
    return update_opportunity(opportunity_id, fields, expected_version, idempotency_key)


@mcp.tool()
def create_quote(
    opportunity_id: str, quote_line: dict, expiry: str, idempotency_key: str, *, ctx: Context
) -> dict:
    """Create (or idempotently replay) a Quote draft from a signed pricing quote.

    Rejects quote_line if its signature doesn't verify.
    """
    correlation_id = correlation_id_from(ctx)
    log_tool_call(correlation_id, "salesforce", "create_quote", opportunity_id=opportunity_id)
    return create_quote_draft(opportunity_id, quote_line, expiry, idempotency_key, correlation_id=correlation_id)


@mcp.tool()
def attach_content_version(opportunity_id: str, title: str, document_text: str, *, ctx: Context) -> dict:
    """Attach a document to an Opportunity as a Salesforce ContentVersion."""
    log_tool_call(correlation_id_from(ctx), "salesforce", "attach_content_version", opportunity_id=opportunity_id)
    return create_content_version(opportunity_id, title, document_text)


@mcp.tool()
def get_quote_by_id(quote_id: str, *, ctx: Context) -> dict:
    """Fetch a previously created quote by id — lets a caller (like the
    documents service) get the authoritative quote_line without having to
    reconstruct it from another agent's prose. Raises LookupError if unknown.
    """
    log_tool_call(correlation_id_from(ctx), "salesforce", "get_quote_by_id", quote_id=quote_id)
    return get_quote(quote_id)


if __name__ == "__main__":
    mcp.run(transport="streamable-http" if os.environ.get("PORT") else "stdio")
