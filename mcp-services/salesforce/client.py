"""Salesforce Opportunity read/write adapter.

Field-allowlisted access to Opportunity and Account. Two client
implementations share one interface so the rest of the system never has
to know whether it is talking to a fixture or a real org — see the
Controlled CRM tool contract in the architecture doc. Both reads and
writes are mode-aware: FixtureSalesforceClient simulates state locally,
LiveSalesforceClient writes to a real org (verified against the
enterprisedealpilot dev org — see salesforce-metadata/README.md).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Protocol

import content_version_store
import idempotency_log
import opportunity_store
import quote_store

# The write-side half of the same allowlist get_opportunity reads from —
# only these may be set via update_opportunity, per the Controlled CRM
# tool contract's "Allowed-field list" guardrail.
ALLOWED_WRITE_FIELDS = {"Budget_Confirmed__c", "Account.Data_Residency__c"}

ALLOWED_OPPORTUNITY_FIELDS = [
    "Id",
    "Name",
    "StageName",
    "Amount",
    "CloseDate",
    "Budget_Confirmed__c",
    "Use_Case__c",
    "AccountId",
]

ALLOWED_ACCOUNT_FIELDS = [
    "Id",
    "Name",
    "Industry",
    "BillingCountry",
    "Data_Residency__c",
]

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "samples" / "salesforce"

# Re-exported so callers only need to catch one exception type regardless
# of SALESFORCE_MODE — both clients raise this same class.
VersionConflict = opportunity_store.VersionConflict


class SalesforceClient(Protocol):
    def get_opportunity(self, opportunity_id: str) -> dict: ...
    def update_opportunity(
        self, opportunity_id: str, fields: dict, expected_version, idempotency_key: str
    ) -> dict: ...
    def create_quote_draft(
        self, opportunity_id: str, quote_line: dict, expiry: str, idempotency_key: str
    ) -> dict: ...
    def create_content_version(
        self, opportunity_id: str, title: str, document_text: str
    ) -> dict: ...
    def get_quote(self, quote_id: str) -> dict: ...


class FixtureSalesforceClient:
    """Reads/writes synthetic records from samples/salesforce/*.json plus a
    local overlay for writes.

    Used for local development, tests, and the hackathon demo so the golden
    path never depends on a live org being reachable.
    """

    def __init__(self, fixtures_dir: Path = FIXTURES_DIR) -> None:
        self._fixtures_dir = fixtures_dir

    def get_opportunity(self, opportunity_id: str) -> dict:
        path = self._fixtures_dir / f"{opportunity_id}.json"
        if not path.exists():
            raise LookupError(
                f"No fixture opportunity '{opportunity_id}' in {self._fixtures_dir}"
            )
        raw = json.loads(path.read_text(encoding="utf-8"))
        overlay = opportunity_store.get_overlay(opportunity_id)
        merged = _apply_overlay(raw, overlay["fields"])
        result = _apply_field_allowlist(merged)
        result["version"] = overlay["version"]
        return result

    def update_opportunity(
        self, opportunity_id: str, fields: dict, expected_version, idempotency_key: str
    ) -> dict:
        return opportunity_store.update_opportunity(
            opportunity_id, fields, expected_version, idempotency_key, ALLOWED_WRITE_FIELDS
        )

    def create_quote_draft(
        self, opportunity_id: str, quote_line: dict, expiry: str, idempotency_key: str
    ) -> dict:
        return quote_store.create_quote_draft(
            opportunity_id, quote_line, expiry, idempotency_key
        )

    def create_content_version(
        self, opportunity_id: str, title: str, document_text: str
    ) -> dict:
        return content_version_store.create_content_version(
            opportunity_id, title, document_text
        )

    def get_quote(self, quote_id: str) -> dict:
        record = quote_store.get_quote_by_id(quote_id)
        if record is None:
            raise LookupError(f"No quote '{quote_id}'")
        return record


class LiveSalesforceClient:
    """Talks to a real Salesforce org via simple_salesforce.

    Verified against the enterprisedealpilot dev org — reads, and now
    writes too (update_opportunity, create_quote_draft). Credentials must
    come from Secret Manager at deploy time; never commit them, and never
    widen this client past the field allowlist below without updating the
    architecture doc's tool contract.

    Two auth paths, either satisfies simple_salesforce:
    - SALESFORCE_SESSION_ID + SALESFORCE_INSTANCE_URL: an existing access
      token (for example from `sf org display --json`) — short-lived,
      good for a one-off check, nothing durable to store.
    - SALESFORCE_USERNAME + SALESFORCE_PASSWORD + SALESFORCE_SECURITY_TOKEN:
      durable, but a password sits in .env; prefer the session path for
      quick verification and a Connected App (Phase 5 governance) for
      anything longer-lived.

    Optimistic locking here uses Salesforce's own LastModifiedDate on both
    Opportunity and Account (the "version" is a composite of both, since
    the two writable fields span two different objects) rather than a
    custom counter field. This is a client-side check-then-write, not a
    server-enforced atomic guarantee — there's a real, if narrow, race
    window between the version check and the write. A production-grade
    fix would be a Salesforce validation rule comparing an incoming
    version field against PRIORVALUE(), which Salesforce evaluates
    atomically within the same transaction; not built, since this is a
    single-seller demo scenario, not a concurrent-write system.
    """

    def __init__(self) -> None:
        try:
            from simple_salesforce import Salesforce  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "simple_salesforce is required for LiveSalesforceClient; "
                "install it or set SALESFORCE_MODE=fixture for local dev."
            ) from exc
        session_id = os.environ.get("SALESFORCE_SESSION_ID")
        if session_id:
            self._sf = Salesforce(
                instance_url=os.environ["SALESFORCE_INSTANCE_URL"],
                session_id=session_id,
            )
        else:
            self._sf = Salesforce(
                username=os.environ["SALESFORCE_USERNAME"],
                password=os.environ.get("SALESFORCE_PASSWORD", ""),
                security_token=os.environ.get("SALESFORCE_SECURITY_TOKEN", ""),
                domain=os.environ.get("SALESFORCE_DOMAIN", "test"),
            )

    def get_opportunity(self, opportunity_id: str) -> dict:
        soql = (
            f"SELECT {_soql_fields()}, LastModifiedDate, "
            f"Account.LastModifiedDate FROM Opportunity WHERE Id = '{opportunity_id}'"
        )
        result = self._sf.query(soql)
        if result["totalSize"] == 0:
            raise LookupError(f"Opportunity '{opportunity_id}' not found")
        record = result["records"][0]
        opportunity = _apply_field_allowlist(_coerce_live_record(record))
        account_lmd = (record.get("Account") or {}).get("LastModifiedDate")
        opportunity["version"] = f"{record['LastModifiedDate']}|{account_lmd}"
        return opportunity

    def update_opportunity(
        self, opportunity_id: str, fields: dict, expected_version, idempotency_key: str
    ) -> dict:
        cached = idempotency_log.get(idempotency_key)
        if cached is not None:
            return {**cached, "idempotent_replay": True}

        unknown = set(fields) - ALLOWED_WRITE_FIELDS
        if unknown:
            raise ValueError(f"Fields not allowed for update_opportunity: {sorted(unknown)}")

        current = self.get_opportunity(opportunity_id)
        if current["version"] != expected_version:
            raise VersionConflict(
                f"Expected version {expected_version} for '{opportunity_id}', "
                f"but current version is {current['version']}"
            )

        opp_updates: dict = {}
        acct_updates: dict = {}
        before: dict = {}
        for dotted_key, value in fields.items():
            if dotted_key == "Budget_Confirmed__c":
                before[dotted_key] = current["Budget_Confirmed__c"]
                opp_updates["Budget_Confirmed__c"] = {True: "Yes", False: "No"}[value]
            elif dotted_key == "Account.Data_Residency__c":
                before[dotted_key] = current["Account"]["Data_Residency__c"]
                acct_updates["Data_Residency__c"] = value

        if opp_updates:
            self._sf.Opportunity.update(opportunity_id, opp_updates)
        if acct_updates:
            self._sf.Account.update(current["AccountId"], acct_updates)

        refreshed = self.get_opportunity(opportunity_id)
        result = {
            "opportunity_id": opportunity_id,
            "before": before,
            "after": dict(fields),
            "version": refreshed["version"],
            "idempotent_replay": False,
        }
        idempotency_log.put(idempotency_key, result)
        return result

    def create_quote_draft(
        self, opportunity_id: str, quote_line: dict, expiry: str, idempotency_key: str
    ) -> dict:
        cached = idempotency_log.get(idempotency_key)
        if cached is not None:
            return {**cached, "idempotent_replay": True}

        # GrandTotal on Quote is a system rollup from QuoteLineItems — it
        # can't be set directly without a full Product2/Pricebook2Entry
        # setup, which the architecture doc explicitly scopes out ("Do not
        # begin with Salesforce CPQ, Revenue Cloud... simultaneously").
        # Signed_Total__c carries our actual authoritative, HMAC-verified
        # total instead — see salesforce-metadata/ for the field.
        quote_fields = {
            "Name": f"{quote_line['bundle_name']} — {quote_line['quantity']} units",
            "OpportunityId": opportunity_id,
            "ExpirationDate": expiry,
            "Status": "Draft",
            "Signed_Total__c": quote_line["grand_total"],
            "Discount_Pct__c": quote_line["discount_pct"],
            "Approval_Status__c": (
                "Pending" if quote_line.get("requires_discount_approval") else "Not Required"
            ),
        }
        created = self._sf.Quote.create(quote_fields)
        result = {
            "quote_id": created["id"],
            "opportunity_id": opportunity_id,
            "quote_line": quote_line,
            "grand_total": quote_line["grand_total"],
            "expiry": expiry,
            "idempotency_key": idempotency_key,
            "idempotent_replay": False,
        }
        idempotency_log.put(idempotency_key, result)
        return result

    def create_content_version(
        self, opportunity_id: str, title: str, document_text: str
    ) -> dict:
        """Create a real ContentVersion attached to the Opportunity.

        No idempotency key here — the doc's tool contract for
        attach_proposal doesn't call for one (checksum guards content
        integrity, not duplicate-call detection). A retried call can
        create a duplicate File; low business risk for a demo proposal
        attachment, unlike a duplicate Quote or a double-applied field
        write, so left as a known limitation rather than built out.

        `.html`, not `.txt` — mcp-services/documents/templates.py renders
        a self-contained HTML document (inline CSS, inline SVG logo), and
        the extension is what makes Salesforce's file preview and a
        downloaded copy actually render it as a styled page instead of
        showing raw markup as plain text.
        """
        import base64

        encoded = base64.b64encode(document_text.encode("utf-8")).decode("ascii")
        created = self._sf.ContentVersion.create(
            {
                "Title": title,
                "PathOnClient": f"{title}.html",
                "VersionData": encoded,
                "FirstPublishLocationId": opportunity_id,
            }
        )
        return {
            "content_version_id": created["id"],
            "opportunity_id": opportunity_id,
            "title": title,
            "document_text": document_text,
        }

    def get_quote(self, quote_id: str) -> dict:
        record = idempotency_log.get_quote_by_id(quote_id)
        if record is None:
            raise LookupError(f"No quote '{quote_id}'")
        return record


def _coerce_live_record(raw: dict) -> dict:
    """Adapt live schema representations to the fixture-mode shape.

    Budget_Confirmed__c is a Salesforce Picklist ("Yes"/"No"/blank), not a
    Checkbox — deliberately, so blank can mean "not yet confirmed"
    distinctly from an explicit "No" (see the field's own description in
    salesforce-metadata/). Fixture mode and the rest of this codebase work
    in Python True/False/None; this is the one place that translates.
    """
    coerced = dict(raw)
    budget = coerced.get("Budget_Confirmed__c")
    coerced["Budget_Confirmed__c"] = {"Yes": True, "No": False}.get(budget)
    return coerced


def _soql_fields() -> str:
    account_fields = ", ".join(
        f"Account.{f}" for f in ALLOWED_ACCOUNT_FIELDS if f != "Id"
    )
    return ", ".join(ALLOWED_OPPORTUNITY_FIELDS) + ", Account.Id, " + account_fields


def _apply_overlay(raw: dict, overlay_fields: dict) -> dict:
    """Layer confirmed field updates on top of a raw fixture record.

    Supports both plain Opportunity fields ("Budget_Confirmed__c") and
    dotted Account fields ("Account.Data_Residency__c"), matching
    missing_fields' own naming so a seller-confirmed answer round-trips:
    update_opportunity writes it here, the next get_opportunity call sees
    it and drops it from missing_fields.
    """
    merged = dict(raw)
    account = dict(merged.get("Account") or {})
    for dotted_key, value in overlay_fields.items():
        if dotted_key.startswith("Account."):
            account[dotted_key.split(".", 1)[1]] = value
        else:
            merged[dotted_key] = value
    merged["Account"] = account
    return merged


def _apply_field_allowlist(raw: dict) -> dict:
    opportunity = {k: raw.get(k) for k in ALLOWED_OPPORTUNITY_FIELDS if k in raw}
    account = raw.get("Account") or {}
    opportunity["Account"] = {
        k: account.get(k) for k in ALLOWED_ACCOUNT_FIELDS if k in account
    }
    opportunity["missing_fields"] = _find_missing_fields(opportunity)
    return opportunity


def _find_missing_fields(opportunity: dict) -> list[str]:
    """Business-readiness check, not a schema check.

    Mirrors the doc's NEEDS_INPUT gate: a field can be present in Salesforce
    but still unconfirmed (None/blank) — that is what should trigger a
    clarification question, not a missing key.
    """
    missing = []
    # `is None` on purpose: Budget_Confirmed__c is a yes/no field, and a
    # seller-confirmed "no" (False) is a real, non-missing answer — treating
    # it as falsy-therefore-missing would make an explicit "not confirmed"
    # answer un-recordable, looping the clarification question forever.
    if opportunity.get("Budget_Confirmed__c") is None:
        missing.append("Budget_Confirmed__c")
    if not opportunity.get("Account", {}).get("Data_Residency__c"):
        missing.append("Account.Data_Residency__c")
    return missing


def get_client() -> SalesforceClient:
    mode = os.environ.get("SALESFORCE_MODE", "fixture")
    if mode == "live":
        return LiveSalesforceClient()
    return FixtureSalesforceClient()


def _get_id_token_for(url: str) -> str | None:
    """Mint a Google-signed ID token for calling `url`, audienced to its
    base URL (Cloud Run's own convention). Returns None if no credentials
    are available to mint one — the caller sends the request unauthenticated
    in that case, which is only survivable in fixture/local-dev deploys
    that still allow unauthenticated access; a locked-down target rejects
    it, on purpose.
    """
    try:
        import google.auth.transport.requests
        import google.oauth2.id_token

        audience = url.split("/mcp")[0]
        return google.oauth2.id_token.fetch_id_token(
            google.auth.transport.requests.Request(), audience
        )
    except Exception:
        return None


def _call_remote_mcp_tool(url: str, tool_name: str, arguments: dict, correlation_id: str | None = None):
    """Call a tool on another deployed mcp-services/* server over real MCP
    (streamable-http), synchronously.

    Once each service is its own Cloud Run container, a direct Python
    import of a sibling service's client.py (the local-dev shortcut used
    everywhere else in this codebase) no longer has anything to import —
    the code isn't in this container. This is the deployed equivalent:
    the same protocol an ADK agent uses to call any of these services,
    just invoked from inside another service instead of from an agent.

    Deliberately handles both call contexts: a plain script (no event loop
    running yet) and a tool handler on an already-deployed MCP server
    (which IS running inside FastMCP's own event loop when it calls this).
    `asyncio.run()` raises if a loop is already running in the current
    thread — found live, the first time `create_quote` on the deployed
    salesforce service tried to remote-verify against pricing. Running the
    whole async call in a fresh thread with its own loop works in both
    cases.

    Attaches a Google-signed ID token identifying THIS service's own
    identity (its dedicated Cloud Run service account, via the metadata
    server) — the target service is deployed with
    `--no-allow-unauthenticated`, so an unauthenticated call gets a plain
    403 before it ever reaches this service's tool logic. This is what
    "least-privilege Agent Identity" actually enforces here: the target
    only grants roles/run.invoker to the specific caller identities it
    named, not to the public internet.
    """
    import asyncio
    import concurrent.futures
    import json

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = {}
    id_token = _get_id_token_for(url)
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"
    if correlation_id:
        headers["X-Correlation-Id"] = correlation_id

    async def _call():
        async with streamablehttp_client(url, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                if result.isError:
                    raise RuntimeError(f"Remote tool '{tool_name}' at {url} returned an error")
                return json.loads(result.content[0].text)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_call())
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _call()).result()


def _load_local_pricing_verify_signature():
    """Load the pricing service's verify_signature by path, not by name —
    the local-dev fallback when PRICING_SERVICE_URL isn't set.

    A bare `from client import verify_signature` would collide with THIS
    module (also named client.py) the moment both get imported into one
    process — see agents/orchestrator/agent.py's _load_module for the full
    story.
    """
    pricing_client_path = (
        Path(__file__).resolve().parents[1] / "pricing" / "client.py"
    )
    if str(pricing_client_path.parent) not in sys.path:
        sys.path.insert(0, str(pricing_client_path.parent))
    spec = importlib.util.spec_from_file_location(
        "dealpilot_pricing_client_for_salesforce", pricing_client_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify_signature


def _quote_signature_is_valid(quote_line: dict, correlation_id: str | None = None) -> bool:
    """Verify a quote's signature, remotely if PRICING_SERVICE_URL is set
    (deployed mode), locally otherwise (dev/test) — quote_creation must not
    trust a total it can't independently verify, so this check is not
    optional in either mode.
    """
    pricing_url = os.environ.get("PRICING_SERVICE_URL")
    if pricing_url:
        result = _call_remote_mcp_tool(
            pricing_url, "verify_quote_signature", {"quote": quote_line}, correlation_id
        )
        return result["verified"]
    return _load_local_pricing_verify_signature()(quote_line)


def create_quote_draft(
    opportunity_id: str,
    quote_line: dict,
    expiry: str,
    idempotency_key: str,
    correlation_id: str | None = None,
) -> dict:
    """Create (or idempotently replay) a Quote draft from a signed pricing quote.

    Rejects `quote_line` if its signature doesn't verify — this is the
    guardrail from the Controlled CRM tool contract: "totals must match
    pricing-service signature". An agent (or a bug) that hands this
    function a hallucinated or edited total gets a ValueError, never a
    written Quote. Dispatches to whichever client SALESFORCE_MODE selects.

    correlation_id, if given, rides along on the pricing verification call
    so both hops of this request show up under the same id in Cloud
    Logging — see mcp-services/*/observability.py.
    """
    if not _quote_signature_is_valid(quote_line, correlation_id):
        raise ValueError(
            "quote_line signature does not verify — refusing to create a "
            "Quote draft from an unverified or tampered total"
        )
    return get_client().create_quote_draft(opportunity_id, quote_line, expiry, idempotency_key)


def update_opportunity(
    opportunity_id: str, fields: dict, expected_version, idempotency_key: str
) -> dict:
    """Apply a confirmed field update with optimistic locking.

    Only ALLOWED_WRITE_FIELDS may be set. expected_version must match the
    opportunity's current version (from a prior get_opportunity call) or
    this raises VersionConflict — a stale read must never silently
    overwrite a newer state. A repeated call with the same idempotency_key
    replays the original result instead of double-applying. Dispatches to
    whichever client SALESFORCE_MODE selects.
    """
    return get_client().update_opportunity(
        opportunity_id, fields, expected_version, idempotency_key
    )


def create_content_version(opportunity_id: str, title: str, document_text: str) -> dict:
    """Attach a document to an Opportunity. Dispatches by SALESFORCE_MODE.

    Callers should verify their own content checksum before reaching this
    (see mcp-services/documents/client.py's attach_proposal) — this
    function trusts document_text as given.
    """
    return get_client().create_content_version(opportunity_id, title, document_text)


def get_quote(quote_id: str) -> dict:
    """Fetch a previously created quote by id. Dispatches by SALESFORCE_MODE.

    Exists so a consumer of a quote_id (like documents' generate_proposal)
    never has to reconstruct quote details itself — see
    docs/ROADMAP.md's "an LLM reconstructing a dict from prose" entry for
    why that's a real, not hypothetical, failure mode in a multi-agent
    system.
    """
    return get_client().get_quote(quote_id)
