#!/usr/bin/env python3
"""#71: one command to do the weekly Schwab browser re-login.

Schwab's refresh token dies 7 days after the last BROWSER login, and the automatic
refresh cannot extend it. When it lapses the real-time options feed silently drops
back to free ~15-minute-delayed data. Renewing it by hand meant racing a 30-second
timer with a pile of curl commands; it failed twice on 2026-07-08 before working.

This does the whole thing:

    python3 scripts/schwab_login.py

It prints a Schwab login URL. Open it in a browser, log in, approve. Schwab then
redirects you to an address starting `https://127.0.0.1/?code=...` — that page will
NOT load, which is expected. Copy the whole address out of the URL bar and paste it
back here. The script trades the code for a fresh 7-day token, fixes the file's
owner and permissions, clears the "re-login needed" marker, and proves it worked by
pulling a live quote.

You can also skip the prompt:

    python3 scripts/schwab_login.py --redirect-url 'https://127.0.0.1/?code=...'
    echo 'https://127.0.0.1/?code=...' | python3 scripts/schwab_login.py

IMPORTANT — the code Schwab gives you expires in about 30 seconds.
If you are running this from a Claude Code session, COMMIT FIRST so the git tree is
clean. On a dirty tree the verify-on-done Stop hook can stall ~80 seconds at the end
of a turn, which is what ate the code twice on 2026-07-08. A clean tree exits the
hook instantly.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

_WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _WORKSPACE)

import requests  # noqa: E402

from consensus_engine.scanners import schwab_client  # noqa: E402

AUTHORIZE_URL = "https://api.schwabapi.com/v1/oauth/authorize"
TOKEN_OWNER = "openclaw"


class LoginError(Exception):
    """Anything that stops the re-login, phrased for a non-coder."""


# --------------------------------------------------------------------------
# pure helpers (unit-tested)
# --------------------------------------------------------------------------

def build_authorize_url(app_key: str, callback_url: str) -> str:
    """The URL the user opens in a browser to log in to Schwab."""
    if not app_key:
        raise LoginError("SCHWAB_APP_KEY is not set in ~/.openclaw/.env")
    if not callback_url:
        raise LoginError("SCHWAB_CALLBACK_URL is not set in ~/.openclaw/.env")
    return (f"{AUTHORIZE_URL}?client_id={quote(app_key, safe='')}"
            f"&redirect_uri={quote(callback_url, safe='')}")


def extract_code(redirect_url: str) -> str:
    """Pull the one-time `code` out of the address Schwab redirected the user to.

    Schwab appends a `@` and a session marker to the code and does NOT url-encode it,
    so `parse_qs` on the raw query is the only thing that reliably recovers it.
    """
    redirect_url = (redirect_url or "").strip().strip('"').strip("'")
    if not redirect_url:
        raise LoginError("No redirect URL given.")
    if "code=" not in redirect_url:
        raise LoginError(
            "That address has no `code=` in it. Copy the FULL address Schwab sent you "
            "to — it starts with https://127.0.0.1/?code= — even though the page did "
            "not load."
        )
    qs = parse_qs(urlparse(redirect_url).query)
    codes = qs.get("code") or []
    if not codes or not codes[0]:
        raise LoginError("Found `code=` but it was empty. Copy the whole address again.")
    return codes[0]


def build_token_doc(token_response: dict, now: float | None = None) -> dict:
    """The exact on-disk shape `schwab_client.get_access_token()` expects.

    `_refresh_created` freezes the 7-day wall at THIS browser login; refreshes carry
    it forward untouched, which is how `reauth_days_left()` stays honest.
    """
    if "access_token" not in token_response or "refresh_token" not in token_response:
        raise LoginError(
            f"Schwab's reply is missing a token. It said: {str(token_response)[:200]}"
        )
    stamp = int(time.time() if now is None else now)
    return {
        "token": token_response,
        "creation_timestamp": stamp,
        "_refresh_created": stamp,
    }


def explain_exchange_failure(status: int, body: str) -> str:
    """Turn Schwab's terse OAuth errors into something actionable."""
    if "invalid_grant" in body:
        return (
            "Schwab rejected the code (invalid_grant). Almost always this means the code "
            "expired — it only lives ~30 seconds. Run the script again and paste faster. "
            "If you are in a Claude Code session, commit your changes first so the "
            "end-of-turn hook cannot stall."
        )
    if "invalid_client" in body:
        return (
            "Schwab rejected the app credentials (invalid_client). SCHWAB_APP_KEY or "
            "SCHWAB_APP_SECRET in ~/.openclaw/.env is wrong, or the app is not approved."
        )
    if status >= 500:
        return f"Schwab's own servers returned HTTP {status}. Wait a few minutes and retry."
    return f"Schwab returned HTTP {status}: {body[:200]}"


# --------------------------------------------------------------------------
# side-effecting steps
# --------------------------------------------------------------------------

def exchange_code(code: str, app_key: str, app_secret: str, callback_url: str) -> dict:
    resp = requests.post(
        schwab_client.TOKEN_URL,
        auth=(app_key, app_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "authorization_code", "code": code,
              "redirect_uri": callback_url},
        timeout=30,
    )
    body = schwab_client._decode_body(resp)
    if resp.status_code != 200:
        raise LoginError(explain_exchange_failure(resp.status_code, body))
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise LoginError(f"Schwab's reply was not readable: {body[:200]}")


def write_token(doc: dict, path: str = schwab_client.TOKEN_PATH) -> None:
    """Write atomically, then hand the file back to openclaw with 600 perms.

    Running this as root and leaving a root-owned token behind is the classic way to
    break the engine (it runs as openclaw and gets a permission error on refresh).
    """
    tmp = f"{path}.tmp"
    Path(tmp).write_text(json.dumps(doc))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    _chown_to_openclaw(path)


def _chown_to_openclaw(path: str) -> None:
    if os.geteuid() != 0:
        return   # not root: whoever wrote it already owns it
    try:
        entry = pwd.getpwnam(TOKEN_OWNER)
    except KeyError:
        print(f"  ! user {TOKEN_OWNER} not found; leaving owner as-is", file=sys.stderr)
        return
    try:
        shutil.chown(path, user=entry.pw_uid, group=entry.pw_gid)
    except OSError as exc:
        # Inside a user namespace (the isolated test runner) euid is 0 but only
        # one id is mapped, so chowning to openclaw's real uid is rejected.
        print(f"  ! could not hand {path} to {TOKEN_OWNER}: {exc}", file=sys.stderr)
    os.chmod(path, 0o600)


def verify_live() -> tuple[bool, str]:
    """Prove the new token actually works: pull one real quote.

    schwab_client.get_quote() already normalizes Schwab's response into the
    Finnhub-shaped {c, pc, dp, ...} dict used elsewhere in the codebase — it
    is not the raw Schwab payload, so the price lives at "c", not
    ["quote"]["lastPrice"] (that nested shape was never what this function
    returns; checking for it made every successful login report as failed).
    """
    try:
        quote_data = schwab_client.get_quote("SPY")
    except Exception as e:
        return False, f"live quote failed: {e}"
    if not quote_data:
        return False, "live quote returned nothing"
    price = quote_data.get("c")
    if price is None:
        return False, f"live quote had no price: {str(quote_data)[:120]}"
    return True, f"SPY = ${price}"


def read_redirect_url(supplied: str | None) -> str:
    if supplied:
        return supplied
    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            return piped
        raise LoginError("Nothing on stdin. Pass --redirect-url instead.")
    return input("\nPaste the full redirect URL here, then press Enter:\n> ")


# --------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Do the weekly Schwab browser re-login in one command (#71).")
    p.add_argument("--redirect-url", default=None,
                   help="the https://127.0.0.1/?code=... address Schwab sent you to")
    p.add_argument("--print-url-only", action="store_true",
                   help="print the login URL and exit (no token exchange)")
    args = p.parse_args()

    try:
        app_key, app_secret = schwab_client._creds()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    callback_url = os.environ.get("SCHWAB_CALLBACK_URL", "")

    try:
        auth_url = build_authorize_url(app_key, callback_url)
    except LoginError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print("\nStep 1 — open this in a browser and log in to Schwab:\n")
    print(f"  {auth_url}\n")
    if args.print_url_only:
        return 0
    print("Step 2 — approve. Schwab sends you to an address starting")
    print("  https://127.0.0.1/?code=...")
    print("The page will NOT load. That is fine. Copy the whole address.")
    print("\nHURRY: the code stops working after about 30 seconds.")

    try:
        redirect_url = read_redirect_url(args.redirect_url)
        code = extract_code(redirect_url)
        token_response = exchange_code(code, app_key, app_secret, callback_url)
        doc = build_token_doc(token_response)
        write_token(doc)
    except LoginError as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"\nFAILED: unexpected error: {e}", file=sys.stderr)
        return 1

    schwab_client.clear_reauth_marker()

    ok, detail = verify_live()
    days = schwab_client.reauth_days_left()
    print(f"\nToken written to {schwab_client.TOKEN_PATH} (owner {TOKEN_OWNER}, mode 600).")
    print(f"Next re-login needed in {days:.1f} days.")
    if ok:
        print(f"Verified against the live feed: {detail}")
        print("\nDone. Real-time Schwab data is back on.")
        return 0
    print(f"\nWARNING: token saved, but the live check failed — {detail}", file=sys.stderr)
    print("The token file looks right; try `python3 -m consensus_engine --status`.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
