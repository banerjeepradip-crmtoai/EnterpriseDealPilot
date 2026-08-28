"""Self-service stand-in for the human approval step in request_send_token's
gate — see client.py's module docstring for why this is a manual call and
not an agent tool. Run this yourself during a demo instead of asking
Claude to authorize a token, so a live "first run" of Deal Orchestration
never leaves you stuck waiting on someone else to unblock the send.

Usage (from mcp-services/communication/):
    python approve_pending.py                # list every PENDING token
    python approve_pending.py --latest        # authorize the most recent PENDING one
    python approve_pending.py --all           # authorize every PENDING one
    python approve_pending.py tok_abc123      # authorize one specific token
"""
from __future__ import annotations

import sys

import client

APPROVER = "Pradip Banerjee (human approval)"


def _pending() -> list[dict]:
    tokens = client._read_tokens()
    return [t for t in tokens.values() if t["status"] == "PENDING"]


def _print(token: dict) -> None:
    print(
        f"{token['token_id']}  {token['status']:<10} "
        f"quote={token['quote_id']} to={token['recipient_email']}"
    )


def main() -> None:
    args = sys.argv[1:]
    pending = _pending()

    if not args:
        if not pending:
            print("No PENDING send tokens.")
            return
        print("PENDING send tokens:")
        for t in pending:
            _print(t)
        print(
            "\nRun with --latest, --all, or a specific token id to authorize."
        )
        return

    if args[0] == "--all":
        if not pending:
            print("No PENDING send tokens.")
            return
        for t in pending:
            result = client.authorize_send(t["token_id"], APPROVER)
            _print(result)
        return

    if args[0] == "--latest":
        if not pending:
            print("No PENDING send tokens.")
            return
        result = client.authorize_send(pending[-1]["token_id"], APPROVER)
        _print(result)
        return

    token_id = args[0]
    try:
        result = client.authorize_send(token_id, APPROVER)
    except client.SendTokenNotFound as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    _print(result)


if __name__ == "__main__":
    main()
