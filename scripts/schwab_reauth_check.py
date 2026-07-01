#!/usr/bin/env python3
"""Weekly Schwab OAuth re-auth reminder (TODO #57).

Schwab's refresh token expires ~7 days after the last browser login and the
auto-refresh CANNOT extend it (proven live: refresh returns the same
refresh_token). When it lapses, the real-time options feed silently falls
back to the free ~15-min-delayed yfinance/Finnhub feed.

This script runs daily via schwab-reauth-check.timer and:
- warns a couple of days BEFORE the 7-day wall (config: schwab.reauth_warn_days), and
- keeps warning once a day AFTER the wall breaches (reactive: schwab_client.REAUTH_MARKER),
until the user re-logs in via browser, which resets the token and clears the marker.

Silent (no alert, no log line) when healthy and not near expiry — no spam.
"""
import argparse
import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

_WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _WORKSPACE)

import requests

from consensus_engine import config
from consensus_engine.scanners import schwab_client

NOTIF_LOG = "/root/task_system/notifications.log"

REAUTH_STEPS = (
    "To renew:\n"
    "1. Ask Claude Code to open the Schwab login URL and log in in your browser.\n"
    "2. Approve, then copy the redirect URL Schwab sends you to (starts with "
    "https://127.0.0.1/?code=...).\n"
    "3. Paste it back right away (the code expires in ~30 seconds) so it can be "
    "traded in for a fresh token."
)


def _build_message(days_left: float, marker_present: bool) -> str:
    expired = marker_present or days_left < 0
    if expired:
        status = (
            "⚠️ Schwab login has EXPIRED — the real-time options feed is on "
            "the free ~15-min Yahoo fallback right now until you re-login."
        )
    else:
        deadline_utc = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days_left)
        deadline_pt = deadline_utc.astimezone(ZoneInfo("America/Los_Angeles"))
        deadline_str = deadline_pt.strftime("%Y-%m-%d ~%-I:%M%p PT")
        status = (
            f"⚠️ Schwab login expires in {days_left:.1f} days (by {deadline_str}). "
            "When it lapses, the real-time options feed drops back to the free ~15-min "
            "Yahoo data until you re-run the Schwab login."
        )
    return f"{status}\n\n{REAUTH_STEPS}"


def _append_notification(message: str) -> None:
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    headline = message.splitlines()[0]
    try:
        with open(NOTIF_LOG, "a") as f:
            f.write(f"[{ts}] {headline}\n")
    except OSError:
        pass  # best-effort; file may be root-owned


def _post_to_discord(message: str) -> None:
    webhook = os.environ.get("CLAUDECODE_WEBHOOK")
    if not webhook:
        print("no CLAUDECODE_WEBHOOK in env — cannot post to Discord", file=sys.stderr)
        return
    try:
        requests.post(
            webhook,
            json={"content": message, "username": "ClaudeCode"},
            timeout=10,
        )
    except requests.RequestException as e:
        print(f"Discord post failed: {e}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Schwab weekly re-auth reminder (TODO #57)")
    parser.add_argument("--dry-run", action="store_true",
                         help="print what would be sent, don't post to Discord or notifications.log")
    parser.add_argument("--force", action="store_true",
                         help="send the alert even if not near expiry (for testing)")
    args = parser.parse_args()

    days_left = schwab_client.reauth_days_left()
    marker_present = os.path.exists(schwab_client.REAUTH_MARKER)
    warn_days = config.get("schwab.reauth_warn_days", 2)

    should_alert = args.force or marker_present or days_left <= warn_days

    if not should_alert:
        print(f"Schwab re-auth OK ({days_left:.1f} days left)")
        return

    message = _build_message(days_left, marker_present)

    if args.dry_run:
        print("[DRY RUN] would send:\n" + message)
        return

    _append_notification(message)
    _post_to_discord(message)
    print(message)


if __name__ == "__main__":
    main()
