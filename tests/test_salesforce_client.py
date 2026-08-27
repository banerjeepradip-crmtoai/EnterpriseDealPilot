"""Contract tests for the Salesforce read adapter.

Only exercises FixtureSalesforceClient — no network, no credentials. These
are the tests referenced as the Day 3-4 "definition of done" in
docs/ROADMAP.md: a whitelisted opportunity JSON must come back for a known
id, and the field allowlist must never leak an unlisted field.
"""
from pathlib import Path

import pytest

from _loader import load_module

_client = load_module(
    Path(__file__).resolve().parents[1] / "mcp-services" / "salesforce" / "client.py",
    "dealpilot_test_salesforce_client",
)
ALLOWED_ACCOUNT_FIELDS = _client.ALLOWED_ACCOUNT_FIELDS
ALLOWED_OPPORTUNITY_FIELDS = _client.ALLOWED_OPPORTUNITY_FIELDS
FixtureSalesforceClient = _client.FixtureSalesforceClient

ALLOWED_TOP_LEVEL_KEYS = set(ALLOWED_OPPORTUNITY_FIELDS) | {"Account", "missing_fields", "version"}


def test_incomplete_opportunity_returns_only_allowlisted_fields():
    client = FixtureSalesforceClient()
    opp = client.get_opportunity("opp_nordic_telecom_renewal")

    assert set(opp) <= ALLOWED_TOP_LEVEL_KEYS
    assert set(opp["Account"]) <= set(ALLOWED_ACCOUNT_FIELDS)


def test_incomplete_opportunity_flags_missing_budget_and_residency():
    client = FixtureSalesforceClient()
    opp = client.get_opportunity("opp_nordic_telecom_renewal")

    assert opp["missing_fields"] == ["Budget_Confirmed__c", "Account.Data_Residency__c"]


def test_ready_opportunity_has_no_missing_fields():
    client = FixtureSalesforceClient()
    opp = client.get_opportunity("opp_ready_example")

    assert opp["missing_fields"] == []
    assert opp["Budget_Confirmed__c"] is True
    assert opp["Account"]["Data_Residency__c"] == "EU"


def test_unknown_opportunity_raises_lookup_error():
    client = FixtureSalesforceClient()

    with pytest.raises(LookupError):
        client.get_opportunity("does-not-exist")
