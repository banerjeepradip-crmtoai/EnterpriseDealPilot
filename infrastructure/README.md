# Infrastructure — Cloud Run deployment (live)

## Public web demo

**Live URL: https://dealpilot-web-444613256262.us-central1.run.app** — the
actual clickable product, not the backend MCP services below. Open it,
pick "orchestrator", and try `opp_ready_example` or
`opp_nordic_telecom_renewal`. Public (`--allow-unauthenticated`),
`SALESFORCE_MODE=fixture` (no real Salesforce writes possible from this
URL, by design — see "Not yet built" for the live-org tradeoff this
avoided).

This is a separate deployment from the 6 `mcp-services/*` below: it hosts
`agents/` (the orchestrator + its 3 specialists) directly, wrapping
`google.adk.cli.fast_api.get_fast_api_app(agents_dir="agents", web=True)`
in `web_app.py`, served by `Dockerfile.web` — **not** `adk deploy
cloud_run`, which only copies the target agent's own folder into the
build (see `google/adk/cli/cli_deploy.py`'s `to_cloud_run`). Every agent
here resolves its sibling agents and `mcp-services/*` relative to the
repo root (`agents/orchestrator/agent.py`'s `_REPO_ROOT`), so the build
needs the whole repo as context — the same reasoning as the shared
`Dockerfile` below, just for a different entrypoint. Everything currently
runs in-process inside this one container (fixture Salesforce data, local
tool logic) — it does **not** call the 6 deployed MCP services over the
network; see "Not yet built."

Service account `dealpilot-web@enterprisedealpilot.iam.gserviceaccount.com`
holds `roles/aiplatform.user` only — enough to call Gemini via Vertex AI,
nothing else. Rebuild + redeploy:

```bash
gcloud builds submit --config=cloudbuild.web.yaml --project enterprisedealpilot .
gcloud run deploy dealpilot-web --image gcr.io/enterprisedealpilot/dealpilot-web \
  --region us-central1 --project enterprisedealpilot
```


All 6 `mcp-services/*` adapters are deployed to Cloud Run, region
`us-central1`, project `enterprisedealpilot`. This is real, billed,
`--no-allow-unauthenticated` infrastructure — not a local stand-in. No
Terraform yet; everything below is a direct `gcloud` sequence, run and
verified manually. `docs/ROADMAP.md`'s Phase 5 section has the narrative
account (why each design choice, what broke, how it was fixed); this file
is the reference for reproducing or extending the deployment itself.

## Image

One root-level `Dockerfile`, shared by every service — not six
near-duplicates. Which service actually runs is selected at container
start via the `MCP_SERVICE_DIR` env var:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "cd \"$MCP_SERVICE_DIR\" && python server.py"]
```

The full repo is the build context on purpose: fixture-mode
`salesforce`/`documents` read `samples/` from outside their own service
directory, and this avoids duplicating those fixtures into every
service's folder. `.dockerignore` excludes `__pycache__/`, `.venv/`,
`.env`, `*.docx`, `salesforce-metadata/node_modules/`, `.git/`, etc.

Every `server.py` picks its transport from whether `$PORT` is set (Cloud
Run always sets it; local dev doesn't):

```python
mcp.run(transport="streamable-http" if os.environ.get("PORT") else "stdio")
```

**Version pin that matters:** `mcp>=1.24,<2` in `requirements.txt`, not
the newer `mcp>=2.0.0`. `google-adk` 2.7.1's `MCPToolset` — the client
side any ADK agent uses to call these services — only supports that
range; `mcp` 2.x renamed `FastMCP` to `MCPServer` and restructured
internals enough that `MCPToolset` fails to import
(`No module named 'mcp.shared.session'`) against it. Every `server.py`
here uses `mcp.server.fastmcp.FastMCP`, the v1 API — not the v2
`MCPServer` rename.

## The 6 services

| Service | URL | Cross-service calls out |
|---|---|---|
| `dealpilot-pricing` | `https://dealpilot-pricing-444613256262.us-central1.run.app` | none |
| `dealpilot-salesforce` | `https://dealpilot-salesforce-444613256262.us-central1.run.app` | → pricing (`verify_quote_signature`) |
| `dealpilot-approval` | `https://dealpilot-approval-444613256262.us-central1.run.app` | none |
| `dealpilot-communication` | `https://dealpilot-communication-444613256262.us-central1.run.app` | none |
| `dealpilot-security` | `https://dealpilot-security-444613256262.us-central1.run.app` | none (calls real Model Armor, not another `mcp-services/*`) |
| `dealpilot-documents` | `https://dealpilot-documents-444613256262.us-central1.run.app` | → salesforce (`get_quote_by_id`, `attach_content_version`) |

Deploy command shape (adjust `MCP_SERVICE_DIR` and service-specific env vars):

```bash
gcloud run deploy dealpilot-pricing \
  --source . --region us-central1 --project enterprisedealpilot \
  --set-env-vars "MCP_SERVICE_DIR=mcp-services/pricing" \
  --service-account="dealpilot-pricing@enterprisedealpilot.iam.gserviceaccount.com" \
  --no-allow-unauthenticated --port 8080
```

`dealpilot-salesforce` additionally sets `SALESFORCE_MODE=fixture` and
`PRICING_SERVICE_URL=<pricing-url>/mcp`. `dealpilot-documents` sets
`SALESFORCE_SERVICE_URL=<salesforce-url>/mcp`. `dealpilot-security` sets
`MODEL_ARMOR_MODE=live`, `GOOGLE_CLOUD_PROJECT=enterprisedealpilot`,
`MODEL_ARMOR_LOCATION=us-central1`, `MODEL_ARMOR_TEMPLATE=dealpilot-security-template`.

## Cross-service calls: real MCP-over-HTTP, not a shared import

Once each `mcp-services/*` directory is its own Cloud Run container, the
direct Python import a sibling service's client used locally (e.g.
Salesforce importing Pricing's `verify_signature` by file path) has
nothing to import anymore — the code isn't in that container. Both
`salesforce/client.py` and `documents/client.py` have a duplicated
`_call_remote_mcp_tool(url, tool_name, arguments, correlation_id=None)`
helper that calls the other deployed service over real
`mcp.client.streamable_http.streamablehttp_client`, falling back to the
original local file-path import when the relevant `*_SERVICE_URL` env
var isn't set (so local dev and the test suite are unaffected).

Two bugs only showed up once this was actually deployed and called
service-to-service, not in local testing:

- **`asyncio.run() cannot be called from a running event loop`** — a
  service's own `@mcp.tool()` handler is already running inside
  FastMCP's event loop when it calls `_call_remote_mcp_tool`; nesting
  another `asyncio.run()` raises. Fixed by detecting the running loop
  (`asyncio.get_running_loop()`) and, when one exists, running the call
  in a fresh thread via `concurrent.futures.ThreadPoolExecutor` instead.
- Registering an MCP server in Agent Registry needs `protocolBinding:
  JSONRPC` on its `--interfaces` flag, not `HTTP_JSON` — the latter is
  for A2A agent cards and the API rejects it for an MCP server spec with
  "instance not found in required enum." Found by trial, not documented
  anywhere obvious.

## Agent Identity + IAM

6 dedicated service accounts, one per service, least privilege:
`dealpilot-{pricing,salesforce,approval,documents,security,communication}@enterprisedealpilot.iam.gserviceaccount.com`.
Every service deploys `--no-allow-unauthenticated`. `roles/run.invoker`
is granted only to the specific caller identities each service actually
needs:

```bash
gcloud run services add-iam-policy-binding dealpilot-pricing \
  --region us-central1 --project enterprisedealpilot \
  --member="serviceAccount:dealpilot-salesforce@enterprisedealpilot.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

- `dealpilot-pricing` trusts `dealpilot-salesforce`'s SA (+ the operator's
  own account, for ops/testing).
- `dealpilot-salesforce` trusts `dealpilot-documents`'s SA (+ operator).
- The other 4 services trust only the operator's own account — nothing
  currently calls them service-to-service.
- `dealpilot-security`'s SA additionally holds `roles/modelarmor.user`.
- **No service grants `allUsers`.** IAM binding checks with `gcloud run
  services get-iam-policy <service>` confirm this on all 6.

A service-to-service caller authenticates by minting a Google-signed ID
token for its own identity (via the Cloud Run metadata server,
`google.oauth2.id_token.fetch_id_token`, audienced to the target's base
URL) and attaching it as `Authorization: Bearer`. This is what
`--no-allow-unauthenticated` actually buys: an unauthenticated or
wrongly-identified caller gets a plain 403 before the target's tool logic
ever runs.

To call a locked-down service directly as a human operator (testing,
debugging — not how agents call it), use `gcloud run services proxy
<service> --region us-central1 --project enterprisedealpilot --port
<local-port>`, which authenticates as your own `gcloud auth` identity and
opens a local unauthenticated tunnel to the real, authenticated Cloud Run
endpoint.

## Agent Registry

All 6 services are registered and discoverable:

```bash
gcloud alpha agent-registry services list --location=us-central1 --project=enterprisedealpilot
```

Registered via `services create --mcp-server-spec-type=no-spec
--interfaces="url=<service>/mcp,protocolBinding=jsonrpc"`. Registration
requires a live `interfaces` URL — there is no way to register a
discovery-only placeholder, which is why the 4 ADK agents
(`agents/orchestrator` and its 3 specialists) aren't registered here: they
run in-process via ADK's `InMemoryRunner`, not as independently callable
services, so they have no URL to register honestly.

**Agent Gateway:** no distinct first-party GCP product exists under this
name as of writing. Agent Registry's `bindings` resource (a declarative
agent↔service authorization graph) is the closest analog, but it too
requires both endpoints to have a registered, live `interfaces` URL —
same blocker as above. What's real today is Cloud Run's own
IAM-enforced authenticated ingress (above) plus this registry's service
discovery.

## Observability

Every `@mcp.tool()` handler accepts an injected `ctx: Context`
(`mcp.server.fastmcp.Context`) and logs a structured JSON line via
`mcp-services/*/observability.py` (duplicated per service, like every
other cross-file pattern in this codebase). Cloud Run captures stdout as
Cloud Logging entries and auto-parses a JSON line into `jsonPayload`, so
one query finds every hop of one request chain across all 6 services:

```bash
gcloud logging read 'jsonPayload.correlation_id="<id>"' \
  --project=enterprisedealpilot --order=asc \
  --format="value(resource.labels.service_name, jsonPayload.service, jsonPayload.tool)"
```

The correlation id is read from an `X-Correlation-Id` header
(`ctx.request_context.request.headers` — FastMCP's injected `Context`
exposes the underlying Starlette request under streamable-http
transport; confirmed empirically, since FastMCP's docs don't spell this
out) if the caller set one, otherwise a new id is minted — so a call is
either the root of a new chain or a continuation of one. `salesforce` and
`documents`' `_call_remote_mcp_tool` forward the id on every
service-to-service call they make, so both hops of e.g.
`create_quote → verify_quote_signature` or
`create_proposal_draft → get_quote_by_id` land under the same id.

This is deliberately Cloud Logging + a correlation id, not full
OpenTelemetry/Cloud Trace span propagation — enough to answer "show me
everything that happened for this one request" without standing up a
second tracing backend. Cloud Trace API (`cloudtrace.googleapis.com`) is
enabled on the project if trace-level instrumentation is wanted later.

## Verifying the deployment end to end

```bash
gcloud run services proxy dealpilot-pricing --region us-central1 --project enterprisedealpilot --port 18091
gcloud run services proxy dealpilot-salesforce --region us-central1 --project enterprisedealpilot --port 18092
# ...one per service, each on its own port
```

Then drive the same MCP client any ADK agent would use
(`mcp.client.streamable_http.streamablehttp_client` +
`mcp.ClientSession`) against `http://127.0.0.1:<port>/mcp`. Live-verified
this way: reachability + `list_tools()` on all 6; the full
pricing → salesforce → documents chain (quote creation, signature
verification, proposal generation and attachment); live Model Armor
correctly flagging the architecture doc's exact prompt-injection attack
text; approval and communication request/status round-trips; one
correlation id spanning all of the above in Cloud Logging.

## Not yet built

- Agent Gateway and Agent-to-Agent `bindings` — blocked on the 4 ADK
  agents not being deployed as independently callable services (see
  above). A materially larger, separate task if wanted.
- Memory Bank for confirmed, scoped user/account preferences.
- Terraform — this is still a manual `gcloud` sequence, documented here
  for reproducibility, not yet codified as IaC.
- Pub/Sub approval topic + Eventarc-driven resume (see
  `mcp-services/approval/README.md` — the pause/resume mechanism itself
  is real, the trigger transport is still a direct call standing in for
  a real approver's action).
