"""Shared idempotency ledger for live-mode writes.

Fixture mode's opportunity_store.py and quote_store.py each carry their
own idempotency tracking alongside the fixture data they simulate —
there's nowhere else for that data to live, so their ledger doubles as a
full result cache. Live mode's actual data lives in Salesforce; this
module only needs to remember "have we already processed this
idempotency_key," so a retried call replays the prior result instead of
writing the same field or Quote twice. A local stand-in for Firestore,
same as the other stores here — see docs/ROADMAP.md.
"""
from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

_STORE_PATH = Path(__file__).resolve().parent / "_live_idempotency.local.json"
_lock = Lock()


def get(idempotency_key: str) -> dict | None:
    return _read_store().get(idempotency_key)


def put(idempotency_key: str, result: dict) -> None:
    with _lock:
        store = _read_store()
        store[idempotency_key] = result
        _write_store(store)


def get_quote_by_id(quote_id: str) -> dict | None:
    """Look up a previously created quote by its quote_id.

    Live mode's Quote record in Salesforce only carries Signed_Total__c /
    Discount_Pct__c — not bundle_name/quantity/unit_price/subtotal, which
    exist only here, in the result create_quote_draft cached at write
    time. A documented limitation, not an oversight: adding those as
    Quote fields too is a reasonable future increment, not required for
    this ledger to do its one job (replay-safety + this lookup).
    """
    store = _read_store()
    for record in store.values():
        if record.get("quote_id") == quote_id and "quote_line" in record:
            return record
    return None


def _read_store() -> dict:
    if not _STORE_PATH.exists():
        return {}
    return json.loads(_STORE_PATH.read_text(encoding="utf-8"))


def _write_store(store: dict) -> None:
    _STORE_PATH.write_text(json.dumps(store, indent=2), encoding="utf-8")


def _reset_for_tests() -> None:
    """Test-only: wipe the local ledger so idempotency tests start clean."""
    if _STORE_PATH.exists():
        _STORE_PATH.unlink()
