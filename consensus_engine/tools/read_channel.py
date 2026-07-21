"""Read recent messages from one of this bot's Discord channels.

The mention/@-ask agent calls this when the user asks about something that was
posted in another room — "in #errors I got a Schwab-down message but never a
recovery one, why?".

Why this exists: without it that question is a dead end. On 2026-07-21 the
agent was asked exactly that, had no way to read #errors, fell back to a
chat-summary query that could not contain the answer, and re-ran that same
query 39 times until its run budget expired. The user waited 4.5 minutes for
"Agent unavailable". The channel is readable — the bot posted those messages
itself — so the fix is to hand the agent the reader.

Usage:
    python3 -m consensus_engine.tools.read_channel --channel errors
    python3 -m consensus_engine.tools.read_channel --channel errors --limit 50
    python3 -m consensus_engine.tools.read_channel --channel errors --contains schwab
    python3 -m consensus_engine.tools.read_channel --list
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from consensus_engine import config as cfg

PACIFIC = ZoneInfo("America/Los_Angeles")

# Room name -> the config key holding its channel id. Keep in sync with
# consensus_engine.main._KNOWN_CHANNEL_NAMES, which rewrites <#id> mentions
# into these same names so the agent can pass one straight through.
CHANNELS = {
    "chat": "discord_channel_id",
    "errors": "discord_errors_channel_id",
    "twitter": "discord_feed_channel_id",
    "news": "discord_news_channel_id",
    "briefing": "discord_briefing_channel_id",
    "options-flow": "options_flow_channel_id",
    "alerts": "swarm_alert_channel_id",
}


def _resolve(channel: str) -> str:
    """Channel name (or a raw id) -> channel id. Empty string if unknown."""
    name = channel.strip().lstrip("#")
    if name.isdigit():
        return name
    return str(cfg.get_api_key(CHANNELS.get(name, "")) or "").strip()


def _fetch(channel_id: str, limit: int) -> list:
    """Most-recent `limit` messages, oldest-first. Raises on HTTP failure."""
    token = cfg.get_api_key("discord_bot_token")
    if not token:
        raise RuntimeError("no discord_bot_token configured")
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages"
        f"?limit={max(1, min(limit, 100))}",
        headers={
            "Authorization": f"Bot {token}",
            # Discord's edge rejects the default urllib agent with a 403.
            "User-Agent": "DiscordBot (https://github.com/chopra2007, 1.0)",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return list(reversed(json.load(resp)))


def _format(msg: dict) -> str:
    """One message as `HH:MM PDT author: text`, embeds folded in."""
    stamp = msg.get("timestamp", "")
    try:
        when = (datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                .astimezone(PACIFIC).strftime("%Y-%m-%d %I:%M %p PDT"))
    except ValueError:
        when = stamp
    author = (msg.get("author") or {}).get("username", "unknown")

    parts = []
    if (msg.get("content") or "").strip():
        parts.append(msg["content"].strip())
    for embed in msg.get("embeds") or []:
        if embed.get("title"):
            parts.append(f"[{embed['title']}]")
        if embed.get("description"):
            parts.append(embed["description"][:400])
        for field in embed.get("fields") or []:
            parts.append(f"{field.get('name', '')}: {field.get('value', '')[:200]}")
    return f"{when}  {author}: " + " | ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--channel", help=f"room name ({', '.join(CHANNELS)}) or a raw id")
    ap.add_argument("--limit", type=int, default=25, help="messages to read (max 100)")
    ap.add_argument("--contains", default="",
                    help="only show messages containing this text (case-insensitive)")
    ap.add_argument("--list", action="store_true", help="list readable rooms and exit")
    args = ap.parse_args()

    if args.list or not args.channel:
        for name in CHANNELS:
            marker = "" if _resolve(name) else "  (not configured)"
            print(f"{name}{marker}")
        return 0

    channel_id = _resolve(args.channel)
    if not channel_id:
        print(f"Unknown channel {args.channel!r}. Readable rooms: "
              f"{', '.join(CHANNELS)}", file=sys.stderr)
        return 2

    try:
        messages = _fetch(channel_id, args.limit)
    except (urllib.error.URLError, OSError, RuntimeError, ValueError) as exc:
        print(f"Could not read that channel: {exc}", file=sys.stderr)
        return 1

    needle = args.contains.lower()
    shown = 0
    for msg in messages:
        line = _format(msg)
        if needle and needle not in line.lower():
            continue
        print(line)
        shown += 1

    if not shown:
        # Say so explicitly — an empty result must read as a real answer, not as
        # a reason to try the same lookup again.
        where = f"the last {len(messages)} message(s) of #{args.channel.lstrip('#')}"
        print(f"(nothing matching {args.contains!r} in {where})" if needle
              else f"(no messages in {where})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
