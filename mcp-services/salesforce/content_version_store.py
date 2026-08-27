"""Local ContentVersion store for fixture mode.

A stand-in for a real Salesforce ContentVersion until Firestore/a real
org — live mode creates an actual ContentVersion record instead (see
LiveSalesforceClient.create_content_version in client.py).

The file this writes (`_content_versions.local.json`) is gitignored;
delete it any time to reset local demo state.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from threading import Lock

_STORE_PATH = Path(__file__).resolve().parent / "_content_versions.local.json"
_lock = Lock()


def create_content_version(opportunity_id: str, title: str, document_text: str) -> dict:
    with _lock:
        store = _read_store()
        content_version_id = f"cv_{uuid.uuid4().hex[:12]}"
        record = {
            "content_version_id": content_version_id,
            "opportunity_id": opportunity_id,
            "title": title,
            "document_text": document_text,
        }
        store[content_version_id] = record
        _write_store(store)
        return record


def _read_store() -> dict:
    if not _STORE_PATH.exists():
        return {}
    return json.loads(_STORE_PATH.read_text(encoding="utf-8"))


def _write_store(store: dict) -> None:
    _STORE_PATH.write_text(json.dumps(store, indent=2), encoding="utf-8")


def _reset_for_tests() -> None:
    """Test-only: wipe the local store so tests start clean."""
    if _STORE_PATH.exists():
        _STORE_PATH.unlink()
