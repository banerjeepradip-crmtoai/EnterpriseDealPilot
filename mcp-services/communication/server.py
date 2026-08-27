"""Communication MCP adapter.

Run standalone for local dev (stdio transport):

    cd mcp-services/communication
    python server.py

Deployed to Cloud Run, this same file serves streamable-http instead —
see infrastructure/README.md. `authorize_send` is deliberately NOT
exposed as a tool here — same reasoning as approval's `resolve_approval`,
see that server's docstring.

Pinned to `mcp>=1.24,<2` (FastMCP) — see docs/ROADMAP.md's ADK/mcp
version-compatibility note.
"""
from __future__ import annotations

import os

from client import get_send_token_status, request_send_token, send_email
from mcp.server.fastmcp import Context, FastMCP
from observability import correlation_id_from, log_tool_call

mcp = FastMCP("communication", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))


@mcp.tool()
def create_send_token(
    quote_id: str, recipient_email: str, requested_by: str = "seller", *, ctx: Context
) -> dict:
    """Request authorization to email one exact recipient about one quote.

    Returns a PENDING token — the workflow now waits for human
    authorization (a separate action, not something you can trigger)
    before send_approved_email will accept it.
    """
    log_tool_call(correlation_id_from(ctx), "communication", "create_send_token", quote_id=quote_id)
    return request_send_token(quote_id, recipient_email, requested_by)


@mcp.tool()
def check_send_token_status(token_id: str, *, ctx: Context) -> dict:
    """Check whether a send token is PENDING or AUTHORIZED."""
    log_tool_call(correlation_id_from(ctx), "communication", "check_send_token_status", token_id=token_id)
    return get_send_token_status(token_id)


@mcp.tool()
def send_approved_email(quote_id: str, to: str, subject: str, body: str, token_id: str, *, ctx: Context) -> dict:
    """Send an email, only if token_id is an AUTHORIZED, unused token bound to
    this exact quote and recipient. Raises otherwise — never sends partially."""
    log_tool_call(correlation_id_from(ctx), "communication", "send_approved_email", quote_id=quote_id, token_id=token_id)
    return send_email(quote_id, to, subject, body, token_id)


if __name__ == "__main__":
    mcp.run(transport="streamable-http" if os.environ.get("PORT") else "stdio")
