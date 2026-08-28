"""Hosted ADK dev UI for EnterpriseDealPilot — a public, clickable demo.

Wraps google.adk.cli.fast_api.get_fast_api_app directly instead of using
`adk deploy cloud_run`: that command only copies the target agent's own
folder into the build (see google/adk/cli/cli_deploy.py's to_cloud_run),
but every agent here resolves its sibling agents and mcp-services/*
relative to the repo root (see agents/orchestrator/agent.py's
_REPO_ROOT) — the whole repo has to be the build context, which is
exactly the pattern already used for mcp-services/* (see Dockerfile).
This file plus Dockerfile.web reuse that same pattern for the agent UI.

use_local_storage=False: Cloud Run's filesystem is ephemeral per
instance anyway, and this is a public demo with no need for session
persistence across restarts — in-memory session/artifact services are
the right default here, not a workaround.

memory_service_uri points at a real Vertex AI Memory Bank scope — a
lightweight Agent Engine instance (see infrastructure/README.md) created
with no deployed agent code, used purely to scope confirmed opportunity
preferences (agents/orchestrator/agent.py's confirm_opportunity_field
writes to it; load_memory reads from it). Uses the FULL resource-name
form, not the short id, specifically to pin location=us-central1
independent of GOOGLE_CLOUD_LOCATION=global — that env var is set for
gemini-3.6-flash's sake (it 404s under regional endpoints), but the
Memory Bank resource itself lives in us-central1, and the short-id form
would incorrectly inherit "global" from that same env var. Uses the
numeric project number, matching what agent_engines.create() itself
returned as the resource's canonical name.

The os.environ.pop below is not optional. GOOGLE_GENAI_USE_VERTEXAI=True
(set for Gemini's sake) makes ADK's Vertex AI utils treat
"Enterprise mode" as enabled, and once that's true, the Memory Bank
client silently switches to an incompatible "Express Mode" — and fails
with a confusing RESOURCE_PROJECT_INVALID error — if GOOGLE_API_KEY is
present in the environment at all, regardless of project/location being
explicitly set. Found live, the hard way: identical code succeeded in
isolation and failed only once .env (with a leftover GOOGLE_API_KEY from
the pre-Vertex-AI free tier) was sourced into the same process.
"""
import importlib.util
import os
import sys
from pathlib import Path

from fastapi import HTTPException, Request
from google.adk.cli.fast_api import get_fast_api_app

os.environ.pop("GOOGLE_API_KEY", None)

_MEMORY_BANK_RESOURCE = (
    "projects/444613256262/locations/us-central1/"
    "reasoningEngines/6067128801567965184"
)

app = get_fast_api_app(
    agents_dir="agents",
    web=True,
    use_local_storage=False,
    memory_service_uri=f"agentengine://{_MEMORY_BANK_RESOURCE}",
    port=int(os.environ.get("PORT", 8080)),
)


def _load_communication_client():
    """Load mcp-services/communication/client.py by path — see
    agents/proposal_communication/agent.py's copy of this helper for why a
    bare `import client` would collide with a sibling service's client.py.
    """
    path = Path(__file__).resolve().parent / "mcp-services" / "communication" / "client.py"
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("dealpilot_web_communication_client", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@app.post("/admin/authorize-send-token")
async def authorize_send_token(request: Request):
    """Local stand-in for a human clicking "approve" on a pending send
    token — see mcp-services/communication/client.py's module docstring
    and scripts/approve_pending.py, which does the same thing for the
    local dev backend. Needed here specifically because this deployed
    instance's token store lives in ITS OWN container filesystem — a
    script running against a developer's local repo checkout has no way
    to reach it. Same public-unauthenticated posture as every other
    endpoint on this service (see salesforce-metadata/README.md's
    DealPilot Agent LWC section on why); not a production admin API.
    """
    body = await request.json()
    token_id = body.get("token_id")
    if not token_id:
        raise HTTPException(status_code=400, detail="token_id is required")
    authorized_by = body.get("authorized_by", "human approval via /admin endpoint")

    client_module = _load_communication_client()
    try:
        return client_module.authorize_send(token_id, authorized_by)
    except client_module.SendTokenNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
