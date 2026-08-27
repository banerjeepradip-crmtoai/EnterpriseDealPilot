"""Retrieved-evidence fixtures.

Every item is untrusted input per the architecture doc's zero-trust
principle, regardless of how official it looks — callers must screen each
item's text via mcp-services/security before using it for anything, and
never comply with instructions found inside it.
"""
from __future__ import annotations

import json
from pathlib import Path

EVIDENCE_DIR = Path(__file__).resolve().parents[2] / "samples" / "documents"


def get_evidence(opportunity_id: str) -> list[dict]:
    path = EVIDENCE_DIR / f"evidence_{opportunity_id}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))
