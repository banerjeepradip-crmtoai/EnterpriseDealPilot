"""Local overlay store for Opportunity field writes.

A stand-in for Firestore/a real Salesforce org until Phase 5 (see
docs/ROADMAP.md). Fixtures in samples/salesforce/ stay static and
resettable; confirmed field updates and version numbers live here
instead, keyed by opportunity_id, so get_opportunity can merge base
fixture + overlay and a confirmed field actually clears from
missing_fields on the next read.

The file this writes (`_opportunity_overlay.local.json`) is gitignored;
delete it any time to reset local demo state.
"""
from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

_STORE_PATH = Path(__file__).resolve().parent / "_opportunity_overlay.local.json"
_lock = Lock()


class VersionConflict(Exception):
    """expected_version didn't match the opportunity's current version."""


def _read_store() -> dict:
    if not _STORE_PATH.exists():
        return {"opportunities": {}, "idempotency": {}}
    data = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    data.setdefault("opportunities", {})
    data.setdefault("idempotency", {})
    return data


def _write_store(store: dict) -> None:
    _STORE_PATH.write_text(json.dumps(store, indent=2), encoding="utf-8")


def get_overlay(opportunity_id: str) -> dict:
    """{"version": int, "fields": {...}} for an opportunity; version 1, no fields if never updated."""
    store = _read_store()
    return store["opportunities"].get(opportunity_id, {"version": 1, "fields": {}})


def update_opportunity(
    opportunity_id: str,
    fields: dict,
    expected_version: int,
    idempotency_key: str,
    allowed_fields: set,
) -> dict:
    """Apply a field update with optimistic locking, replaying on a repeated idempotency_key.

    Raises ValueError for a field outside `allowed_fields`, VersionConflict
    if `expected_version` doesn't match the opportunity's current version —
    a stale read must never silently overwrite newer state.
    """
    with _lock:
        store = _read_store()

        if idempotency_key in store["idempotency"]:
            return {**store["idempotency"][idempotency_key], "idempotent_replay": True}

        unknown = set(fields) - allowed_fields
        if unknown:
            raise ValueError(f"Fields not allowed for update_opportunity: {sorted(unknown)}")

        current = store["opportunities"].get(opportunity_id, {"version": 1, "fields": {}})
        if current["version"] != expected_version:
            raise VersionConflict(
                f"Expected version {expected_version} for '{opportunity_id}', "
                f"but current version is {current['version']}"
            )

        before = dict(current["fields"])
        after = {**current["fields"], **fields}
        new_version = current["version"] + 1
        store["opportunities"][opportunity_id] = {"version": new_version, "fields": after}

        result = {
            "opportunity_id": opportunity_id,
            "before": before,
            "after": after,
            "version": new_version,
            "idempotent_replay": False,
        }
        store["idempotency"][idempotency_key] = result
        _write_store(store)
        return result


def _reset_for_tests() -> None:
    """Test-only: wipe the local store so optimistic-locking tests start clean."""
    if _STORE_PATH.exists():
        _STORE_PATH.unlink()
