# Frontend — Phase 6

This directory is intentionally empty. The decision landed on a Salesforce
Lightning Web Component, not a standalone React app — see
`salesforce-metadata/force-app/main/default/lwc/dealPilotAgent`, embedded
directly on the Opportunity record page rather than hosted separately here.

**Status: built, not yet deployed or live-verified.** The LWC
(`dealPilotAgent`), its Apex controller (`DealPilotAgentController`), and
`DealPilot_Setting__mdt`/`DealPilot_Agent` (Custom Metadata + a Remote
Site Setting, standing in for a Named Credential — see
`salesforce-metadata/README.md` for why) exist as SFDX source. What's proven:
the Apex controller's own contract tests (mocked HTTP callouts) pass, and
its request/response shapes were checked directly against
`google.adk.cli.api_server`'s actual `RunAgentRequest`/`Event` schemas —
not just assumed. What's not yet proven: the LWC has not been deployed to
the org, dropped onto a record page via Lightning App Builder, or clicked
through against a real running backend. See
`salesforce-metadata/README.md`'s "DealPilot Agent LWC" section for the
architecture and exactly what's needed to close that gap.

This replaces relying on `adk web`'s bundled dev UI as the demo surface
(see `docs/ROADMAP.md` Phase 6) — the backend REST API underneath
(`web_app.py`, wrapping `google.adk.cli.fast_api.get_fast_api_app`) is
unchanged; the LWC is just a different, purpose-built caller of the same
`/run` endpoint the dev UI already used.
