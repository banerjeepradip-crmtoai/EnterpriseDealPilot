"""Deal Orchestrator — the root ADK agent for EnterpriseDealPilot.

Retrieves a Salesforce Opportunity through the read-only adapter, decides
what business decisions are still missing, and either asks the seller
about them or delegates to the Solution & Pricing agent once the
opportunity is ready. Once a quote exists, delegates to the Risk &
Approval agent to decide whether it needs a discount approval, and — only
if no approval is pending — to the Proposal & Communication agent to
generate, attach, and (with an authorized send token) email the proposal.
Handover lands in a later phase — see docs/ROADMAP.md.

Run locally with the ADK dev UI from the repo root:

    adk web agents

and pick "orchestrator", or:

    adk run agents/orchestrator

Try opportunity id `opp_nordic_telecom_renewal` (missing two fields, should
trigger two clarification questions) and `opp_ready_example` (nothing
missing) against the fixture data in samples/salesforce/.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module(path: Path, unique_name: str):
    """Load a module by file path, under a unique sys.modules name.

    Every mcp-services/* adapter has its own client.py, and every agents/*
    package has its own agent.py — a bare `import client` or `import agent`
    would silently collide in sys.modules the moment two get loaded into
    the same process, which `adk web agents` does for every agent package
    it discovers. Loading by explicit path under a unique name sidesteps
    that; inserting the module's own directory into sys.path first keeps
    ITS internal bare imports (e.g. pricing's client.py importing
    catalogue.py) working exactly as if it had been run standalone.
    """
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(unique_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# mcp-services/salesforce is a standalone service directory (hyphenated on
# purpose — see mcp-services/salesforce/README.md), not a Python package.
# Phase 1 loads its client function directly for fast local iteration; a
# later phase replaces this with an MCPToolset call to the deployed Cloud
# Run service, routed through Agent Gateway, without changing this agent's
# instruction or the tool's signature.
_salesforce_client_module = _load_module(
    _REPO_ROOT / "mcp-services" / "salesforce" / "client.py",
    "dealpilot_salesforce_client",
)
get_client = _salesforce_client_module.get_client
_update_opportunity = _salesforce_client_module.update_opportunity

_solution_pricing_module = _load_module(
    _REPO_ROOT / "agents" / "solution_pricing" / "agent.py",
    "dealpilot_solution_pricing_agent",
)
solution_pricing_tool = AgentTool(agent=_solution_pricing_module.root_agent)

_risk_approval_module = _load_module(
    _REPO_ROOT / "agents" / "risk_approval" / "agent.py",
    "dealpilot_risk_approval_agent",
)
risk_approval_tool = AgentTool(agent=_risk_approval_module.root_agent)

_proposal_communication_module = _load_module(
    _REPO_ROOT / "agents" / "proposal_communication" / "agent.py",
    "dealpilot_proposal_communication_agent",
)
proposal_communication_tool = AgentTool(agent=_proposal_communication_module.root_agent)


def get_opportunity(opportunity_id: str) -> dict:
    """Fetch a whitelisted Salesforce Opportunity snapshot.

    Args:
        opportunity_id: The Salesforce Opportunity Id (or fixture key in
            fixture mode) the seller selected.

    Returns:
        A dict with the opportunity's allowlisted fields, its Account, and
        a `missing_fields` list of business decisions that are still
        unconfirmed and must be asked about before any configuration or
        pricing work begins.
    """
    return get_client().get_opportunity(opportunity_id)


def confirm_opportunity_field(opportunity_id: str, field: str, value: str) -> dict:
    """Persist the seller's answer to one previously-missing field.

    Args:
        opportunity_id: The same Id used with get_opportunity.
        field: One of the exact names get_opportunity's missing_fields
            listed — "Budget_Confirmed__c" or "Account.Data_Residency__c".
            Never call this with a field that wasn't in missing_fields.
        value: The seller's answer as text. For Budget_Confirmed__c, use
            a yes/no word ("yes", "no", "confirmed", "not confirmed"); for
            Account.Data_Residency__c, use the region as stated (for
            example "EU").

    Returns:
        The updated opportunity — call get_opportunity yourself afterward
        only if you need to double-check; this already reflects the write.
    """
    sf_client = get_client()
    current = sf_client.get_opportunity(opportunity_id)
    coerced_value = _coerce_field_value(field, value)
    idempotency_key = f"{opportunity_id}:{field}:{coerced_value}:{current['version']}"
    _update_opportunity(
        opportunity_id,
        {field: coerced_value},
        expected_version=current["version"],
        idempotency_key=idempotency_key,
    )
    return sf_client.get_opportunity(opportunity_id)


def _coerce_field_value(field: str, raw_value: str):
    if field != "Budget_Confirmed__c":
        return raw_value
    normalized = raw_value.strip().lower()
    if normalized in {"true", "yes", "y", "confirmed"}:
        return True
    if normalized in {"false", "no", "n", "not confirmed", "unconfirmed"}:
        return False
    raise ValueError(
        f"Could not interpret '{raw_value}' as yes/no for Budget_Confirmed__c"
    )


root_agent = Agent(
    # Pinned to the Gemini 3 family, not a "-latest" alias: this account's
    # key returned 404 on gemini-2.5-flash ("no longer available to new
    # users"), and gemini-flash-latest was intermittently 503-overloaded
    # during testing. Verified working end-to-end 2026-08-26.
    model="gemini-3.6-flash",
    name="deal_orchestrator",
    description=(
        "Leads a seller through an incomplete Salesforce opportunity: "
        "finds missing business decisions and asks focused questions "
        "before any configuration or pricing work begins."
    ),
    instruction="""
You are the Deal Orchestrator for EnterpriseDealPilot.

When a seller gives you an Opportunity Id:
1. Call get_opportunity to retrieve its whitelisted fields.
2. If `missing_fields` is non-empty, ask the seller ONE targeted question
   per missing field, and briefly explain why it matters (for example:
   "Data residency affects which product bundle is eligible"). Never
   invent or assume an answer on the seller's behalf.
3. When the seller answers a question, call confirm_opportunity_field with
   that exact field name and their answer as text. Its result already
   reflects the write — use its own missing_fields to decide what's still
   left; do not call get_opportunity again just to re-check. Repeat for
   each remaining missing field. If confirm_opportunity_field raises an
   error because you couldn't interpret an answer, ask the seller to
   rephrase rather than guessing a value.
4. Once missing_fields is empty (either from the start, or after the
   seller has answered everything), delegate to solution_pricing_agent:
   pass it the opportunity id, its Use_Case__c text, Amount, and the
   account's Data_Residency__c value. Relay its bundle recommendation,
   quote_id, and price back to the seller exactly as it reported them —
   never restate or recompute a total yourself.
5. Then delegate to risk_approval_agent: pass it the quote_id,
   discount_pct, grand_total, and requires_discount_approval exactly as
   solution_pricing_agent reported them. Relay its response — whether no
   approval is needed, or an approval_id was created and the workflow is
   waiting — exactly as it reported it.
6. If risk_approval_agent reported that no approval is needed, delegate to
   proposal_communication_agent: pass it the opportunity id, opportunity
   name, customer (account) name, use case, and the quote_id
   solution_pricing_agent produced — the quote_id alone, not the price or
   bundle details themselves; proposal_communication_agent fetches those
   directly rather than trusting a retyped copy. Relay whatever it reports — proposal
   attached, evidence blocked as suspected injection, waiting for send
   authorization, or a send outcome — exactly as it reported it, without
   softening or elaborating on a security block.
   If risk_approval_agent reported that an approval is still PENDING, stop
   here. Tell the seller the workflow is waiting for that approval and do
   not delegate to proposal_communication_agent — a proposal must never
   go out while a required discount approval is unresolved.

Only call get_opportunity or confirm_opportunity_field with an Id the
seller actually gave you for this opportunity. Never present an
unconfirmed field as if it were confirmed, never present a price that did
not come back from solution_pricing_agent, never state an approval
decision that did not come back from risk_approval_agent, and never
present a proposal or send outcome that did not come back from
proposal_communication_agent.
""".strip(),
    tools=[
        get_opportunity,
        confirm_opportunity_field,
        solution_pricing_tool,
        risk_approval_tool,
        proposal_communication_tool,
    ],
)
