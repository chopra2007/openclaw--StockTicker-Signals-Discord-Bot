#!/usr/bin/env python3
"""Ask the bot a question in the REAL #chat channel and read its real reply.

Posts as the bot, @-mentioning itself. The gateway listener lets a self-post
through (it only drops a self *reply*), so this lands in the same
`_handle_mention` path the owner's @-mention uses — the whole point being that
nothing here is simulated: the engine answers, and the answer is read back off
Discord.

Usage: python3 scripts/qa_live_chat_probe.py "your question" [--wait 240]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from consensus_engine import config as cfg  # noqa: E402

BOT_USER_ID = "1468886193054814352"
API = "https://discord.com/api/v10"
UA = "DiscordBot (https://github.com/chopra2007, 1.0)"


def _req(method: str, url: str, body: dict | None = None):
    token = cfg.get_api_key("discord_bot_token")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bot {token}",
        "User-Agent": UA,
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--wait", type=int, default=240, help="seconds to wait for the reply")
    ap.add_argument("--channel", default="chat")
    args = ap.parse_args()

    channel_id = str(cfg.get_api_key({"chat": "discord_channel_id"}[args.channel]) or "").strip()
    if not channel_id:
        print("no channel id configured", file=sys.stderr)
        return 1

    posted = _req("POST", f"{API}/channels/{channel_id}/messages",
                  {"content": f"<@{BOT_USER_ID}> {args.question}"})
    asked_id = posted["id"]
    print(f"asked (msg {asked_id}): {args.question}", flush=True)

    deadline = time.monotonic() + args.wait
    while time.monotonic() < deadline:
        time.sleep(10)
        msgs = _req("GET", f"{API}/channels/{channel_id}/messages?after={asked_id}&limit=50")
        # A reply to our question, or any bot message posted after it that is
        # not another alert card.
        for m in reversed(msgs):
            ref = (m.get("message_reference") or {}).get("message_id")
            if ref == asked_id:
                print("\n=== REPLY ===")
                print(m.get("content", ""))
                print(f"\n(reply msg id {m['id']}, {int(time.monotonic() - (deadline - args.wait))}s)")
                return 0
    print("\nNO REPLY within the wait window", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
