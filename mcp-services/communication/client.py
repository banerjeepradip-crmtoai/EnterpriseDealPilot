"""Gated email send.

The architecture doc's requirement — "a human approval gate before any
external email or binding commercial action" — is enforced here at the
code level, not left to an agent's judgment. request_send_token creates a
PENDING authorization bound to one exact recipient; authorize_send is the
local stand-in for a human clicking approve (mirrors
mcp-services/approval's decide_approval — not exposed to any agent);
send_email refuses unless the token is AUTHORIZED, unused, and its bound
recipient matches exactly.

This is also the actual stopping point for the security test case: even
if a prompt-injection attempt in retrieved evidence tricked an agent into
calling send_email with an attacker's address, there is no authorized
token for that address, so the call fails — the block does not depend on
the model "choosing" not to comply.

No real email is dispatched. "Sent" mail is recorded locally
(`_sent_emails.local.json`, gitignored) — see README for why simulating
delivery, not the authorization gate itself, is the right thing to keep
out of scope for this MVP.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from threading import Lock

_TOKENS_PATH = Path(__file__).resolve().parent / "_send_tokens.local.json"
_SENT_PATH = Path(__file__).resolve().parent / "_sent_emails.local.json"
_lock = Lock()


class SendTokenNotFound(LookupError):
    pass


class SendNotAuthorized(PermissionError):
    """Covers every reason a send is refused: no token, wrong recipient,
    not yet authorized, already used, or domain not allowed. Deliberately
    one exception type — callers should treat all of these identically:
    the send does not happen.
    """


def request_send_token(quote_id: str, recipient_email: str, requested_by: str = "seller") -> dict:
    """Create a PENDING send authorization bound to exactly one recipient."""
    with _lock:
        tokens = _read_tokens()
        token_id = f"tok_{uuid.uuid4().hex[:12]}"
        record = {
            "token_id": token_id,
            "quote_id": quote_id,
            "recipient_email": recipient_email,
            "requested_by": requested_by,
            "status": "PENDING",
            "authorized_by": None,
            "used": False,
        }
        tokens[token_id] = record
        _write_tokens(tokens)
        return record


def get_send_token_status(token_id: str) -> dict:
    tokens = _read_tokens()
    if token_id not in tokens:
        raise SendTokenNotFound(f"No send token '{token_id}'")
    return tokens[token_id]


def authorize_send(token_id: str, authorized_by: str) -> dict:
    """Mark a token AUTHORIZED — the local stand-in for a human's approval
    action. Not exposed to any agent tool; call it directly to simulate
    that approval arriving, same pattern as mcp-services/approval's
    decide_approval.
    """
    with _lock:
        tokens = _read_tokens()
        if token_id not in tokens:
            raise SendTokenNotFound(f"No send token '{token_id}'")
        record = tokens[token_id]
        if record["status"] == "PENDING":
            record["status"] = "AUTHORIZED"
            record["authorized_by"] = authorized_by
        tokens[token_id] = record
        _write_tokens(tokens)
        return record


def send_email(quote_id: str, to: str, subject: str, body: str, token_id: str) -> dict:
    """Send only if `token_id` is AUTHORIZED, unused, bound to this exact
    quote and recipient, and `to`'s domain is allowed. Raises
    SendNotAuthorized otherwise — never sends, never partially sends.
    """
    with _lock:
        tokens = _read_tokens()
        if token_id not in tokens:
            raise SendTokenNotFound(f"No send token '{token_id}'")
        token = tokens[token_id]

        if token["status"] != "AUTHORIZED":
            raise SendNotAuthorized(
                f"Token '{token_id}' is {token['status']}, not AUTHORIZED"
            )
        if token["used"]:
            raise SendNotAuthorized(f"Token '{token_id}' has already been used")
        if token["quote_id"] != quote_id:
            raise SendNotAuthorized(
                f"Token '{token_id}' was issued for quote '{token['quote_id']}', not '{quote_id}'"
            )
        if token["recipient_email"].lower() != to.lower():
            raise SendNotAuthorized(
                f"Token '{token_id}' authorizes sending to '{token['recipient_email']}', "
                f"not '{to}'"
            )
        allowed_domain = os.environ.get("ALLOWED_EMAIL_DOMAIN")
        if allowed_domain and not to.lower().endswith("@" + allowed_domain.lower()):
            raise SendNotAuthorized(
                f"'{to}' is outside the allowed send domain '{allowed_domain}'"
            )

        token["used"] = True
        tokens[token_id] = token
        _write_tokens(tokens)

        sent = _read_sent()
        record = {
            "email_id": f"email_{uuid.uuid4().hex[:12]}",
            "quote_id": quote_id,
            "to": to,
            "subject": subject,
            "body": body,
            "token_id": token_id,
        }
        sent.append(record)
        _write_sent(sent)
        return record


def _read_tokens() -> dict:
    if not _TOKENS_PATH.exists():
        return {}
    return json.loads(_TOKENS_PATH.read_text(encoding="utf-8"))


def _write_tokens(tokens: dict) -> None:
    _TOKENS_PATH.write_text(json.dumps(tokens, indent=2), encoding="utf-8")


def _read_sent() -> list:
    if not _SENT_PATH.exists():
        return []
    return json.loads(_SENT_PATH.read_text(encoding="utf-8"))


def _write_sent(sent: list) -> None:
    _SENT_PATH.write_text(json.dumps(sent, indent=2), encoding="utf-8")


def _reset_for_tests() -> None:
    if _TOKENS_PATH.exists():
        _TOKENS_PATH.unlink()
    if _SENT_PATH.exists():
        _SENT_PATH.unlink()
