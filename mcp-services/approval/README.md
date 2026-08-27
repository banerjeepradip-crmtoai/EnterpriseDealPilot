# Approval MCP adapter

Owns approval-matrix routing and the pause/resume mechanism for the
Risk & Approval agent.

## Contract

- `request_discount_approval(quote_id, percentage, rationale, requested_by)`
  — creates a `PENDING` record. This is the pause: the workflow state
  machine enters `WAITING_APPROVAL` and nothing else happens until someone
  decides it.
- `get_approval_status(approval_id)` — read the current status.
- `decide_approval(approval_id, decision, decided_by, decision_note)` —
  resolves a pending request to `APPROVED` or `REJECTED`. This is the
  resume. Calling it twice on an already-decided request returns the
  original decision with `already_decided: true` instead of re-applying.

## Why this is the Pub/Sub stand-in, not the real thing yet

In production, `decide_approval` is called by an Eventarc trigger
consuming a real Salesforce `EnterpriseDealPilot_Approval_Event__e`
platform event — an approver acts in Salesforce, that fires the event,
Eventarc invokes a Cloud Run handler, the handler calls `decide_approval`.
Locally there's no event bus, so calling `decide_approval` directly *is*
the simulation of that event arriving. The pause/resume mechanism itself
(a durable `PENDING` record an agent can check back on days later) is
real and tested; only the transport that flips it is stubbed. Wiring the
actual Pub/Sub topic + Eventarc trigger is a remaining Phase 3 live-infra
step — see docs/ROADMAP.md.

## Run standalone

```
cd mcp-services/approval
python server.py
```

## Test

```
pytest tests/test_approval_client.py
```
