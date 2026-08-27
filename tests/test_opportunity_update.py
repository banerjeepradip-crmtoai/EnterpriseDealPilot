"""Contract tests for idempotent Opportunity updates with optimistic locking.

Covers the "Duplicate callback" and general write-safety rows of the
architecture doc's test matrix for update_opportunity, plus the
None-vs-False regression: a seller-confirmed "no" must not still read as
missing on the next get_opportunity call.
"""
from pathlib import Path

import pytest

from _loader import load_module

_client = load_module(
    Path(__file__).resolve().parents[1] / "mcp-services" / "salesforce" / "client.py",
    "dealpilot_test_salesforce_client_for_updates",
)

# Reached through _client.opportunity_store (the module object client.py's
# own `import opportunity_store` bound), not loaded separately — a second,
# independent load would create a *different* VersionConflict class object
# than the one client.py actually raises, and `pytest.raises` matches by
# class identity, not by name. This is the same collision family the
# _load_module docstring warns about, just biting in the opposite
# direction: two loads of the same file, not one load of two files.
_opportunity_store = _client.opportunity_store

get_client = _client.get_client
update_opportunity = _client.update_opportunity
VersionConflict = _opportunity_store.VersionConflict

OPP_ID = "opp_nordic_telecom_renewal"  # starts with both fields unconfirmed


@pytest.fixture(autouse=True)
def _clean_overlay_store():
    _opportunity_store._reset_for_tests()
    yield
    _opportunity_store._reset_for_tests()


def test_confirming_a_field_clears_it_from_missing_fields():
    client = get_client()
    opp = client.get_opportunity(OPP_ID)
    assert "Budget_Confirmed__c" in opp["missing_fields"]

    update_opportunity(
        OPP_ID, {"Budget_Confirmed__c": True}, opp["version"], "test-key-1"
    )

    refreshed = client.get_opportunity(OPP_ID)
    assert "Budget_Confirmed__c" not in refreshed["missing_fields"]
    assert refreshed["Budget_Confirmed__c"] is True
    assert refreshed["version"] == 2


def test_confirming_budget_as_false_is_not_treated_as_missing():
    client = get_client()
    opp = client.get_opportunity(OPP_ID)

    update_opportunity(
        OPP_ID, {"Budget_Confirmed__c": False}, opp["version"], "test-key-false"
    )

    refreshed = client.get_opportunity(OPP_ID)
    assert refreshed["Budget_Confirmed__c"] is False
    assert "Budget_Confirmed__c" not in refreshed["missing_fields"]


def test_confirming_both_fields_makes_the_opportunity_ready():
    client = get_client()
    opp = client.get_opportunity(OPP_ID)

    step1 = update_opportunity(
        OPP_ID, {"Budget_Confirmed__c": True}, opp["version"], "test-key-both-1"
    )
    update_opportunity(
        OPP_ID,
        {"Account.Data_Residency__c": "EU"},
        step1["version"],
        "test-key-both-2",
    )

    refreshed = client.get_opportunity(OPP_ID)
    assert refreshed["missing_fields"] == []
    assert refreshed["Account"]["Data_Residency__c"] == "EU"


def test_stale_expected_version_raises_version_conflict():
    client = get_client()
    opp = client.get_opportunity(OPP_ID)

    update_opportunity(
        OPP_ID, {"Budget_Confirmed__c": True}, opp["version"], "test-key-stale-1"
    )

    with pytest.raises(VersionConflict):
        update_opportunity(
            OPP_ID,
            {"Account.Data_Residency__c": "EU"},
            opp["version"],  # stale: version 1, but it's now 2
            "test-key-stale-2",
        )


def test_disallowed_field_is_rejected():
    client = get_client()
    opp = client.get_opportunity(OPP_ID)

    with pytest.raises(ValueError):
        update_opportunity(
            OPP_ID, {"Amount": 999999}, opp["version"], "test-key-disallowed"
        )


def test_repeated_call_with_same_idempotency_key_applies_once():
    client = get_client()
    opp = client.get_opportunity(OPP_ID)

    first = update_opportunity(
        OPP_ID, {"Budget_Confirmed__c": True}, opp["version"], "test-key-repeat"
    )
    second = update_opportunity(
        OPP_ID, {"Budget_Confirmed__c": True}, opp["version"], "test-key-repeat"
    )

    assert first["version"] == second["version"] == 2
    assert second["idempotent_replay"] is True

    refreshed = client.get_opportunity(OPP_ID)
    assert refreshed["version"] == 2  # not 3 — the repeat did not apply again
