"""Structured request logging + correlation-id propagation.

Cloud Run captures stdout as Cloud Logging entries, and a JSON line is
auto-parsed into `jsonPayload` — so `jsonPayload.correlation_id="..."` in
Cloud Logging finds every hop of one request chain across all 6 services
in a single query, without standing up a separate tracing backend.

correlation_id_from() reads the id back out of the X-Correlation-Id
header a caller attached (see mcp-services/salesforce/client.py and
mcp-services/documents/client.py's _call_remote_mcp_tool, which set it on
every service-to-service call) — a call with no such header is the root
of its own new chain, so one is minted.

Duplicated per service on purpose, not shared from a common module: each
mcp-services/* directory is its own Cloud Run build context (see this
repo's Dockerfile — `cd "$MCP_SERVICE_DIR" && python server.py`, which
puts only that directory on sys.path[0]) and every other cross-file
pattern in this codebase (see _call_remote_mcp_tool itself) already
duplicates rather than imports a sibling for the same reason.
"""
from __future__ import annotations

import json
import logging
import sys
import uuid

_logger = logging.getLogger("dealpilot")
if not _logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False


def correlation_id_from(ctx) -> str:
    """ctx is an mcp.server.fastmcp.Context, injected by FastMCP into any
    tool function with a `ctx: Context` parameter. request is None under
    stdio transport (local dev) or when no incoming header was set —
    both cases just start a new chain.
    """
    request = ctx.request_context.request if ctx.request_context else None
    incoming = request.headers.get("x-correlation-id") if request is not None else None
    return incoming or f"corr_{uuid.uuid4().hex[:16]}"


def log_tool_call(correlation_id: str, service: str, tool: str, **fields) -> None:
    _logger.info(json.dumps({"correlation_id": correlation_id, "service": service, "tool": tool, **fields}))
