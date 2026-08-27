# Salesforce MCP adapter

Read-only in Phase 1. Owns the field allowlist and the "is this opportunity
ready" business check — both agents and tests depend on `client.py`, not on
Salesforce's raw schema, so a change to what counts as ready only happens
in one place.

Why this directory has no `__init__.py` and isn't imported as a Python
package: it deploys as its own Cloud Run service, independent of every
other agent and service in this repo. Hyphenated directory names (matching
the architecture doc's `mcp-services/` convention) aren't valid Python
package names on purpose — nothing outside this directory should import it
as a module. Callers either run it as an MCP server (`server.py`) or, in
Phase 1 only, add this directory to `sys.path` for fast local iteration
(see `agents/orchestrator/agent.py`).

## Modes

Set `SALESFORCE_MODE`:
- `fixture` (default) — reads `samples/salesforce/<opportunity_id>.json`.
  No network calls, no credentials required.
- `live` — queries a real org via `simple_salesforce`. Not exercised yet;
  needs `SALESFORCE_USERNAME`, `SALESFORCE_PASSWORD`,
  `SALESFORCE_SECURITY_TOKEN`, `SALESFORCE_DOMAIN` from Secret Manager at
  deploy time (see `.env.sample` at repo root for the full variable list).

## Run standalone

```
cd mcp-services/salesforce
python server.py
```

## Test

```
pytest tests/test_salesforce_client.py
```
