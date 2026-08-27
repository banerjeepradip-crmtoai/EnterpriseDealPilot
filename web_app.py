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
persistence across restarts — in-memory session/artifact/memory
services are the right default here, not a workaround.
"""
import os

from google.adk.cli.fast_api import get_fast_api_app

app = get_fast_api_app(
    agents_dir="agents",
    web=True,
    use_local_storage=False,
    port=int(os.environ.get("PORT", 8080)),
)
