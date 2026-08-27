# Salesforce metadata

The Salesforce side of EnterpriseDealPilot's golden path — six custom
fields, the permission set that makes them actually visible, and the two
synthetic records `mcp-services/salesforce`'s Python fixtures mirror
exactly. Both reads and writes are verified against the real org, not
just deployed.

## Org

`enterprisedealpilot` (alias) — a genuine Developer Edition
(`orgfarm-be66d5cfe1-dev-ed.develop.my.salesforce.com`), not production,
not a sandbox of a real business org. It's also used for an unrelated
prior project (an AI governance/risk-assessment app — `AI_Risk_Assessment__c`
and friends); none of that metadata was touched, and nothing here
collides with it. Re-authenticate any time with:

```
sf org login web --alias enterprisedealpilot --instance-url https://login.salesforce.com
```

## What's deployed

| Object | Field | Type | Why not the obvious type |
|---|---|---|---|
| Account | `Data_Residency__c` | Picklist (EU/US/APAC) | A controlled value, not free text — matches the doc's "regional/data-residency policy configuration" |
| Opportunity | `Budget_Confirmed__c` | Picklist (Yes/No) | **Not a Checkbox.** A Checkbox can't be blank — it's always true/false. `missing_fields` logic depends on being able to tell "not yet asked" (blank) apart from an explicit "No" (a real, recorded answer). `mcp-services/salesforce/client.py`'s `_coerce_live_record` maps Yes/No/blank to Python True/False/None at read time — that's the one place this translation happens. |
| Opportunity | `Use_Case__c` | Text(255) | Short free-text summary the Solution & Pricing agent reads to pick a bundle |
| Quote | `Signed_Total__c` | Currency(16,2) | Standard `GrandTotal` is a system rollup from QuoteLineItems — not settable without a full Product2/Pricebook2Entry setup, which the architecture doc explicitly scopes out ("do not begin with Salesforce CPQ... simultaneously"). This carries the actual HMAC-verified total from `mcp-services/pricing` instead. |
| Quote | `Discount_Pct__c` | Percent(5,2) | Mirrors the doc's `Discount__c` |
| Quote | `Approval_Status__c` | Picklist (Not Required/Pending/Approved/Rejected) | Set at Quote creation from `requires_discount_approval`; not yet synced from `mcp-services/approval`'s `decide_approval` — see `docs/ROADMAP.md` |

Plus `EnterpriseDealPilot_Access`, a permission set granting read/edit on
all six fields, and object-level Create/Read/Edit on Quote (plus Read/Edit
on Opportunity and Account — Salesforce won't grant Read on a child object
like Quote without Read on its parent, a dependency this permission set
exists to satisfy explicitly). **None of this is optional** — newer
Salesforce API versions don't auto-grant field-level security to any
profile (System Administrator included) when a field is deployed via
Metadata API. The very first deploy here reported `Succeeded` with all
three original fields created, but they were invisible to every query and
every profile until a permission set was deployed and assigned. Caught by
directly hitting the REST describe endpoint, not by trusting the deploy
report. Also learned the hard way: a metadata deploy is all-or-nothing —
when the Quote fields + permission set deployed together and the
permission set failed on that Read-Opportunity dependency, the fields
that had individually reported "OK" were rolled back too.

## Data

`data/plan.json` + `data/Account.json` + `data/Opportunity.json` —
loaded via `sf data import tree`, not clicked in by hand, so it's
reproducible. Mirrors `samples/salesforce/*.json` field-for-field:

- **Nordic Telecom AB** — `Budget_Confirmed__c` and `Data_Residency__c`
  both blank, drives the clarification path.
- **Baltic Freight Group** — `Budget_Confirmed__c = "Yes"`,
  `Data_Residency__c = "EU"`, ready for pricing.

Redeploy metadata: `sf project deploy start --source-dir force-app/main/default --target-org enterprisedealpilot`
Reload data: `sf data import tree --plan data/plan.json --target-org enterprisedealpilot`
(Re-running the data import creates duplicates, since these aren't
upserts — delete the existing two Accounts first if you need a clean
reset, or query by Name before assuming they don't exist yet.)

## Live-mode status

All four `SalesforceClient` operations are verified against this real
org — `get_opportunity`, `update_opportunity`, `create_quote_draft`, and
`create_content_version`, all through `mcp-services/salesforce/client.py`'s
actual `LiveSalesforceClient`, not a mock. Verified manually, not as an
automated test: the contract test suite stays fixture-only and offline on
purpose, so CI never depends on live credentials.

**`create_content_version`** creates a real `ContentVersion`, correctly
linked to the Opportunity via `FirstPublishLocationId` — confirmed by
querying it back. One quirk from cleaning up the test record: you can't
delete a `ContentVersion` directly (`INSUFFICIENT_ACCESS_OR_READONLY`) —
Salesforce wants you to delete its parent `ContentDocument` instead
(`ContentVersion.ContentDocumentId`).

**Optimistic locking in live mode** uses Salesforce's own `LastModifiedDate`
on both Opportunity and Account as a composite version token (the two
writable fields span two different objects), instead of a custom counter
field. Confirmed working: a stale `expected_version` correctly raises
`VersionConflict`. This is a client-side check-then-write, not a
server-enforced atomic guarantee — there's a narrow race window between
the version check and the write. A production fix would be a Salesforce
validation rule comparing an incoming version against `PRIORVALUE()`,
which Salesforce evaluates atomically in the same transaction; not built,
since this is a single-seller demo scenario, not a concurrent-write
system.

**`create_quote_draft`** creates a real `Quote` record linked to the
Opportunity, with our signed total in `Signed_Total__c`. Confirmed: a
repeated call with the same idempotency key replays the same `quote_id`
without creating a duplicate; a tampered/unsigned total is rejected with
`ValueError` before any Quote is created.

**A real trap, caught during this verification:** the live test run
temporarily wrote real values into Nordic Telecom AB's `Budget_Confirmed__c`
and `Data_Residency__c` to prove the write path — but that record's whole
demo purpose is staying *incomplete*, to trigger the clarification flow.
Verifying a write, by definition, changes state; anyone testing against
this org needs to reset Nordic Telecom's two fields back to blank
afterward (and delete any test Quote records) or the golden-path demo
breaks silently. There's no automated reset script for this yet — it was
done by hand this time via `sf data update record`.

**Not done yet:** the Risk & Approval agent's `decide_approval` doesn't
write back to `Quote.Approval_Status__c` — that field is only set once,
at Quote creation time.

## Auth for the Python client

Two paths, see `.env.sample`:
- `SALESFORCE_SESSION_ID` + `SALESFORCE_INSTANCE_URL` — an existing access
  token (get one with `sf org display --target-org enterprisedealpilot --json`,
  with `SF_TEMP_SHOW_SECRETS=true` set). Short-lived, nothing durable to
  store — what was used for the verification above.
- `SALESFORCE_USERNAME` + `SALESFORCE_PASSWORD` + `SALESFORCE_SECURITY_TOKEN`
  — durable, but a password sits in `.env`. A Connected App (OAuth,
  Phase 5 governance work) is the better long-term answer; not built yet.
