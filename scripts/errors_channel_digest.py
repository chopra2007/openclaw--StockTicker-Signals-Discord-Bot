#!/usr/bin/env python3
"""TODO #88 check 5 — print the last 24 hours of the Discord #errors channel.

The Schwab outage alerts were correct and sat unread for two days. This runs from
the session-start digest hook so the alerts arrive without anyone remembering to
look. Silent when the channel is quiet, and silent on any failure — a broken
digest must never block a session start.

  python3 scripts/errors_channel_digest.py            # last 24h
  python3 scripts/errors_channel_digest.py --hours 72
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.request
from zoneinfo import ZoneInfo

ENV_FILES = ["/home/openclaw/.openclaw/.env", "/home/openclaw/.openclaw/.env.service"]
FALLBACK_CHANNEL = "1521022584072831057"  # #errors
PACIFIC = ZoneInfo("America/Los_Angeles")
MAX_MESSAGES = 15
TIMEOUT = 8


def env_value(key: str) -> str | None:
    """Read a key from the bot's env files (they use `export KEY=value` lines)."""
    if os.environ.get(key):
        return os.environ[key]
    pattern = re.compile(r"^\s*(?:export\s+)?%s\s*=\s*(.*)$" % re.escape(key))
    for path in ENV_FILES:
        try:
            with open(path) as f:
                for line in f:
                    m = pattern.match(line)
                    if m:
                        return m.group(1).strip().strip('"').strip("'")
        except OSError:
            continue
    return None


def fetch(channel: str, token: str) -> list[dict]:
    url = "https://discord.com/api/v10/channels/%s/messages?limit=50" % channel
    # Discord rejects the default urllib user-agent with a 403, so name ourselves.
    req = urllib.request.Request(url, headers={
        "Authorization": "Bot " + token,
        "User-Agent": "DiscordBot (https://github.com/chopra2007/openclaw, 1.0)",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.load(resp)


def summarize(msg: dict) -> str:
    """One line: the message text, or the embed's title and description."""
    parts = []
    content = (msg.get("content") or "").strip()
    if content:
        parts.append(content)
    for embed in msg.get("embeds") or []:
        title = (embed.get("title") or "").strip()
        desc = (embed.get("description") or "").strip()
        if title:
            parts.append(title)
        if desc:
            parts.append(desc)
    text = " | ".join(parts) or "(no text)"
    text = " ".join(text.split())
    return text[:400]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=24, help="how far back to look")
    args = parser.parse_args()

    token = env_value("DISCORD_BOT_TOKEN")
    channel = env_value("DISCORD_ERRORS_CHANNEL_ID") or FALLBACK_CHANNEL
    if not token:
        return 0  # silent: no token, nothing to say

    try:
        messages = fetch(channel, token)
    except Exception:
        return 0  # silent: never block a session start on a network hiccup

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=args.hours)
    recent = []
    for msg in messages:
        try:
            when = dt.datetime.fromisoformat(msg["timestamp"])
        except (KeyError, ValueError):
            continue
        if when >= cutoff:
            recent.append((when, msg))
    if not recent:
        return 0  # quiet channel -> print nothing

    recent.sort(key=lambda pair: pair[0])
    print("\n🔴 #errors — %d message(s) in the last %dh (nobody read these for two days once):"
          % (len(recent), args.hours))
    for when, msg in recent[-MAX_MESSAGES:]:
        stamp = when.astimezone(PACIFIC).strftime("%a %H:%M PDT")
        print("  [%s] %s" % (stamp, summarize(msg)))
    if len(recent) > MAX_MESSAGES:
        print("  ...%d older message(s) not shown" % (len(recent) - MAX_MESSAGES))
    print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
