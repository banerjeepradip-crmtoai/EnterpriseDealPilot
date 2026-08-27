"""Approval MCP adapter.

Run standalone for local dev (stdio transport):

    cd mcp-services/approval
    python server.py

Deployed to Cloud Run, this same file serves streamable-http instead —
see infrastructure/README.md. `resolve_approval` is exposed here because
MCP has no per-tool ACL of its own; risk_approval_agent's AgentTool/
MCPToolset wiring must filter it out (see agents/risk_approval/agent.py)
— it stays a human/Eventarc-only action even though the transport can't
enforce that by itself.

Pinned to `mcp>=1.24,<2` (FastMCP) — see docs/ROADMAP.md's ADK/mcp
version-compatibility note.
"""
from __future__ import annotations

import os

from client import decide_approval, get_approval_status, request_discount_approval
from mcp.server.fastmcp import Context, FastMCP
from observability import correlation_id_from, log_tool_call

mcp = FastMCP("approval", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))


@mcp.tool()
def create_discount_approval_request(
    quote_id: str, percentage: float, rationale: str, requested_by: str = "seller", *, ctx: Context
) -> dict:
    """Request approval for a discount. Returns a PENDING record — the workflow pauses here."""
    log_tool_call(correlation_id_from(ctx), "approval", "create_discount_approval_request", quote_id=quote_id)
    return request_discount_approval(quote_id, percentage, rationale, requested_by)


@mcp.tool()
def check_approval_status(approval_id: str, *, ctx: Context) -> dict:
    """Check whether a discount approval is still PENDING, APPROVED, or REJECTED."""
    log_tool_call(correlation_id_from(ctx), "approval", "check_approval_status", approval_id=approval_id)
    return get_approval_status(approval_id)


@mcp.tool()
def resolve_approval(
    approval_id: str, decision: str, decided_by: str, decision_note: str = "", *, ctx: Context
) -> dict:
    """Approve or reject a pending request. decision must be APPROVED or REJECTED.

    Stands in for the Eventarc handler that would call this after a real
    approval event — see client.py's module docstring.
    """
    log_tool_call(correlation_id_from(ctx), "approval", "resolve_approval", approval_id=approval_id, decision=decision)
    return decide_approval(approval_id, decision, decided_by, decision_note)


if __name__ == "__main__":
    mcp.run(transport="streamable-http" if os.environ.get("PORT") else "stdio")
