"""Test-only helper for loading service modules that share a filename.

Every mcp-services/* adapter has its own client.py. A bare `sys.path.insert`
+ `import client` works fine for a single test module in isolation, but
pytest collects every test file into one process — the second test module
to import "client" silently gets whichever service's client.py happened to
load first, straight from sys.modules. Loading by explicit path under a
unique name sidesteps that; see agents/orchestrator/agent.py's copy of
this same pattern for where it matters in production code too.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module(path: Path, unique_name: str):
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(unique_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
