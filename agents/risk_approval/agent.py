"""Risk & Approval agent.

Given a priced, drafted quote, decides whether it needs a discount
approval (using requires_discount_approval — a flag the pricing service
already computed and signed, never re-derived here) and, if so, requests
one and reports that the workflow is now waiting. It never approves or
rejects anything itself — write authority is "Approval request only" (see
the agent fleet table in the architecture doc). Deciding the request is a
separate, explicit action (see mcp-services/approval/README.md for why
that's the local stand-in for a real approver's action arriving via
Pub/Sub).

Runs standalone via `adk web agents` (pick "risk_approval"), or as a
sub-tool the Deal Orchestrator calls after Solution & Pricing returns a
quote (see agents/orchestrator/agent.py).
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


_approval_client_module = _load_module(
    Path(__file__).resolve().parents[2] / "mcp-services" / "approval" / "client.py",
    "dealpilot_approval_client",
)
request_discount_approval = _approval_client_module.request_discount_approval
get_approval_status = _approval_client_module.get_approval_status


root_agent = Agent(
    # See agents/orchestrator/agent.py for why this is pinned to the
    # Gemini 3 family rather than a "-latest" alias or gemini-2.5-*.
    model="gemini-3.6-flash",
    name="risk_approval_agent",
    description=(
        "Decides whether a priced quote needs a discount approval, and "
        "if so requests one and reports that the workflow is waiting. "
        "Never decides an approval itself."
    ),
    instruction="""
You are the Risk & Approval agent for EnterpriseDealPilot.

You will be given a priced quote's details, including quote_id,
discount_pct, grand_total, and requires_discount_approval.

1. If requires_discount_approval is false, say plainly that no approval
   is needed and this quote is ready for the next step (proposal
   generation — a later phase of this build).
2. If requires_discount_approval is true, call request_discount_approval
   with the quote_id, the discount percentage, and a one-sentence
   rationale drawn from whatever context you were given (if none was
   given, say "seller-requested discount"). Report the returned
   approval_id and say clearly that the workflow is now waiting for that
   approval — do not imply it is approved, and do not guess how long that
   might take.

You never decide an approval yourself, and you never fabricate an
approval_id or a status — only report what request_discount_approval or
get_approval_status actually returned.
""".strip(),
    tools=[request_discount_approval, get_approval_status],
)
