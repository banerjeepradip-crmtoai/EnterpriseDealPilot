"""Documents adapter.

Renders the one approved template from a signed quote, then attaches the
result to the opportunity. generate_proposal signs its own output with a
checksum; attach_proposal verifies that checksum before writing anything
— same "sign what you compute, verify before you act" pattern as
pricing's quote signature (see mcp-services/pricing/client.py), so an
agent can never attach edited or hallucinated content.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from pathlib import Path

from evidence import get_evidence  # noqa: F401 — re-exported for callers
from templates import PROPOSAL_TEMPLATE


def _get_id_token_for(url: str) -> str | None:
    """Mint a Google-signed ID token for calling `url`, audienced to its
    base URL (Cloud Run's own convention) — see
    mcp-services/salesforce/client.py's copy for the full rationale.
    Returns None if no credentials are available to mint one.
    """
    try:
        import google.auth.transport.requests
        import google.oauth2.id_token

        audience = url.split("/mcp")[0]
        return google.oauth2.id_token.fetch_id_token(
            google.auth.transport.requests.Request(), audience
        )
    except Exception:
        return None


def _call_remote_mcp_tool(url: str, tool_name: str, arguments: dict, correlation_id: str | None = None):
    """Call a tool on another deployed mcp-services/* server over real MCP
    (streamable-http), synchronously — see
    mcp-services/salesforce/client.py's copy of this same helper for why
    this exists (once each service is its own Cloud Run container, a
    direct Python import of a sibling service's client.py has nothing to
    import anymore), for why it has to handle both a plain script (no
    event loop yet) and a tool handler on an already-deployed MCP server
    (already running inside one) — `asyncio.run()` raises in the second
    case, found live on the first deployed cross-service call — and for
    why it attaches an ID token: the target is deployed with
    `--no-allow-unauthenticated`.
    """
    import asyncio
    import concurrent.futures
    import json

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = {}
    id_token = _get_id_token_for(url)
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"
    if correlation_id:
        headers["X-Correlation-Id"] = correlation_id

    async def _call():
        async with streamablehttp_client(url, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                if result.isError:
                    raise RuntimeError(f"Remote tool '{tool_name}' at {url} returned an error")
                return json.loads(result.content[0].text)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_call())
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _call()).result()


def _load_local_salesforce_client_module():
    """Load the Salesforce adapter by path, not by name — the local-dev
    fallback when SALESFORCE_SERVICE_URL isn't set. See
    agents/orchestrator/agent.py's _load_module for why a bare `import
    client` would collide with THIS module (also client.py).
    """
    path = Path(__file__).resolve().parents[1] / "salesforce" / "client.py"
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(
        "dealpilot_salesforce_client_for_documents", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _get_quote(quote_id: str, correlation_id: str | None = None) -> dict:
    """Fetch a quote by id, remotely if SALESFORCE_SERVICE_URL is set
    (deployed mode), locally otherwise (dev/test)."""
    salesforce_url = os.environ.get("SALESFORCE_SERVICE_URL")
    if salesforce_url:
        return _call_remote_mcp_tool(
            salesforce_url, "get_quote_by_id", {"quote_id": quote_id}, correlation_id
        )
    return _load_local_salesforce_client_module().get_quote(quote_id)


def _create_content_version(
    opportunity_id: str, title: str, document_text: str, correlation_id: str | None = None
) -> dict:
    """Create a ContentVersion, remotely if SALESFORCE_SERVICE_URL is set
    (deployed mode), locally otherwise (dev/test)."""
    salesforce_url = os.environ.get("SALESFORCE_SERVICE_URL")
    if salesforce_url:
        return _call_remote_mcp_tool(
            salesforce_url,
            "attach_content_version",
            {"opportunity_id": opportunity_id, "title": title, "document_text": document_text},
            correlation_id,
        )
    return _load_local_salesforce_client_module().create_content_version(
        opportunity_id, title, document_text
    )


def generate_proposal(
    quote_id: str,
    opportunity_name: str,
    customer_name: str,
    use_case: str,
    expiry: str,
    context: str = "",
    correlation_id: str | None = None,
) -> dict:
    """Render the approved template from a previously created quote.

    Takes quote_id, not a quote_line dict — deliberately. An agent calling
    this runs in its own isolated sub-conversation and only ever sees the
    quote's details as prose relayed by another agent; asking it to
    reconstruct a dict from that prose is exactly the kind of thing that
    silently drops or renames a field (this happened during Phase 4 build
    — see docs/ROADMAP.md). Fetching the authoritative quote_line by id
    instead removes that failure mode entirely.

    Returns {document_text, checksum} — pass both, unedited, to
    attach_proposal. `context` should only ever contain evidence text that
    has already been screened and cleared — see mcp-services/security.
    """
    quote = _get_quote(quote_id, correlation_id)
    quote_line = quote["quote_line"]
    document_text = PROPOSAL_TEMPLATE.format(
        customer_name=customer_name,
        opportunity_name=opportunity_name,
        use_case=use_case,
        bundle_name=quote_line["bundle_name"],
        quantity=quote_line["quantity"],
        unit_price=quote_line["unit_price"],
        subtotal=quote_line["subtotal"],
        discount_pct=quote_line["discount_pct"],
        discount_amount=quote_line["discount_amount"],
        grand_total=quote_line["grand_total"],
        context=context or "None.",
        expiry=expiry,
    )
    checksum = hashlib.sha256(document_text.encode("utf-8")).hexdigest()
    return {"document_text": document_text, "checksum": checksum}


def attach_proposal(
    opportunity_id: str,
    document_text: str,
    checksum: str,
    title: str,
    correlation_id: str | None = None,
) -> dict:
    """Attach a proposal to the opportunity, after verifying its checksum.

    Rejects document_text that doesn't match checksum — an agent (or bug)
    handing this a different document than generate_proposal actually
    produced gets a ValueError, never a written ContentVersion.
    """
    actual = hashlib.sha256(document_text.encode("utf-8")).hexdigest()
    if actual != checksum:
        raise ValueError(
            "document_text does not match checksum — refusing to attach "
            "content that generate_proposal did not actually produce"
        )
    return _create_content_version(opportunity_id, title, document_text, correlation_id)
