"""Approval routing and pause/resume.

Local stand-in for Pub/Sub + Eventarc (see docs/ROADMAP.md for the live
wiring that remains). request_discount_approval creates a PENDING record;
decide_approval is what an Eventarc-triggered Cloud Run handler would call
after consuming a real EnterpriseDealPilot_Approval_Event__e — see
architecture doc section 5. Calling it directly here simulates that event
arriving, which is exactly the mechanism the doc's WAITING_APPROVAL state
and "asynchronous operation" judging criterion are about: the workflow
must be able to stop, let real time pass, and resume from exactly where
it left off — not hold anything in memory across that gap.

The file this writes (`_approval_store.local.json`) is gitignored; delete
it any time to reset local demo state.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from threading import Lock

_STORE_PATH = Path(__file__).resolve().parent / "_approval_store.local.json"
_lock = Lock()

VALID_DECISIONS = {"APPROVED", "REJECTED"}


class ApprovalNotFound(LookupError):
    pass


class InvalidDecision(ValueError):
    pass


def _read_store() -> dict:
    if not _STORE_PATH.exists():
        return {}
    return json.loads(_STORE_PATH.read_text(encoding="utf-8"))


def _write_store(store: dict) -> None:
    _STORE_PATH.write_text(json.dumps(store, indent=2), encoding="utf-8")


def request_discount_approval(
    quote_id: str, percentage: float, rationale: str, requested_by: str = "seller"
) -> dict:
    """Create a PENDING approval request. This is the pause: nothing else
    happens until decide_approval is called for the returned approval_id.
    """
    with _lock:
        store = _read_store()
        approval_id = f"appr_{uuid.uuid4().hex[:12]}"
        record = {
            "approval_id": approval_id,
            "quote_id": quote_id,
            "percentage": percentage,
            "rationale": rationale,
            "requested_by": requested_by,
            "status": "PENDING",
            "decided_by": None,
            "decision_note": None,
        }
        store[approval_id] = record
        _write_store(store)
        return record


def get_approval_status(approval_id: str) -> dict:
    store = _read_store()
    if approval_id not in store:
        raise ApprovalNotFound(f"No approval request '{approval_id}'")
    return store[approval_id]


def decide_approval(
    approval_id: str, decision: str, decided_by: str, decision_note: str = ""
) -> dict:
    """Resolve a pending approval — the resume.

    In production this is invoked by an Eventarc trigger consuming the
    real approval event, not called directly by an agent. Locally, call
    it to simulate that event so the pause/resume mechanism is testable
    without a live Pub/Sub topic.
    """
    if decision not in VALID_DECISIONS:
        raise InvalidDecision(
            f"decision must be one of {sorted(VALID_DECISIONS)}, got '{decision}'"
        )
    with _lock:
        store = _read_store()
        if approval_id not in store:
            raise ApprovalNotFound(f"No approval request '{approval_id}'")
        record = store[approval_id]
        if record["status"] != "PENDING":
            return {**record, "already_decided": True}
        record.update(
            status=decision, decided_by=decided_by, decision_note=decision_note
        )
        store[approval_id] = record
        _write_store(store)
        return {**record, "already_decided": False}


def _reset_for_tests() -> None:
    """Test-only: wipe the local store so approval tests start clean."""
    if _STORE_PATH.exists():
        _STORE_PATH.unlink()
