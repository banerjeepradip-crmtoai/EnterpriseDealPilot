"""Local idempotent quote store.

A stand-in for Firestore/Cloud SQL (Phase 5 wires the real thing — see
docs/ROADMAP.md). Every create_quote_draft call is keyed by an
idempotency_key so a retried call returns the exact same quote_id instead
of creating a duplicate — this is what the "Duplicate callback" test case
in the architecture doc's test matrix checks.

The file this writes (`_quote_store.local.json`) is gitignored; delete it
any time to reset local demo state.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from threading import Lock

_STORE_PATH = Path(__file__).resolve().parent / "_quote_store.local.json"
_lock = Lock()


def _read_store() -> dict:
    if not _STORE_PATH.exists():
        return {}
    return json.loads(_STORE_PATH.read_text(encoding="utf-8"))


def _write_store(store: dict) -> None:
    _STORE_PATH.write_text(json.dumps(store, indent=2), encoding="utf-8")


def create_quote_draft(
    opportunity_id: str, quote_line: dict, expiry: str, idempotency_key: str
) -> dict:
    """Store a quote draft, replaying the existing one for a repeated key.

    `quote_line` must be a signed quote dict as returned by the pricing
    service's price_bundle — callers are expected to have already checked
    its signature via require_valid_quote_signature before reaching here.
    """
    with _lock:
        store = _read_store()
        existing = store.get(idempotency_key)
        if existing is not None:
            return {**existing, "idempotent_replay": True}

        quote = {
            "quote_id": f"quote_{uuid.uuid4().hex[:12]}",
            "opportunity_id": opportunity_id,
            "quote_line": quote_line,
            "grand_total": quote_line["grand_total"],
            "expiry": expiry,
            "idempotency_key": idempotency_key,
            "idempotent_replay": False,
        }
        store[idempotency_key] = quote
        _write_store(store)
        return quote


def get_quote_by_id(quote_id: str) -> dict | None:
    """Look up a previously created quote by its quote_id (not its
    idempotency_key — callers downstream of create_quote_draft only ever
    see the quote_id, never the key that created it).
    """
    store = _read_store()
    for record in store.values():
        if record.get("quote_id") == quote_id:
            return record
    return None


def _reset_for_tests() -> None:
    """Test-only: wipe the local store so idempotency tests start clean."""
    if _STORE_PATH.exists():
        _STORE_PATH.unlink()
