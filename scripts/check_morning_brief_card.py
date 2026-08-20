#!/usr/bin/env python3
"""Inspect the morning brief Discord actually posted and report what landed.

Run after the scheduled post window. Reads the newest brief message back off the
Discord API and checks the four things TODO #87 promised: a real card, all five
sections present, the SPY expected-move image(s) attached, and no Eastern-time
label anywhere on it. Appends a one-line verdict to the task-system notification
log so the next session sees it.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)  # config/ paths are read relative to the repo root
from consensus_engine import config as cfg               # noqa: E402
from consensus_engine.briefing import alfred             # noqa: E402

NOTIFY = "/root/task_system/notifications.log"
API = "https://discord.com/api/v10"


def verdict_for(msgs: list) -> str:
    """Build the one-line verdict from the messages Discord returned.

    Split out from main() so it can be tested without the network. TODO #88
    check 4: this is the code that once reported "0 charts" on a card carrying
    two, because it counted attachments — and Discord empties the attachment
    list once an embed points at the image. Charts are counted on the EMBEDS.
    """
    brief = next((m for m in msgs
                  if any("Morning Brief" in (e.get("title") or "") for e in m.get("embeds", []))),
                 None)
    if brief is None:
        return "MORNING BRIEF CHECK: no brief card found in the last 25 messages"
    embeds = brief["embeds"]
    fields = embeds[0].get("fields", [])
    blob = json.dumps(embeds, ensure_ascii=False)
    return (
        f"MORNING BRIEF CHECK (msg {brief['id']}): embeds={len(embeds)} "
        f"sections={len(fields)}/5 charts={sum(1 for e in embeds if e.get('image'))} "
        f"chars={sum(alfred._embed_len(e) for e in embeds)}/6000 "
        f"eastern_label={'YES — BUG' if alfred._has_forbidden_timezone_label(blob) else 'no'}")


def main() -> int:
    token = cfg.get_api_key("discord_bot_token")
    channel = str(cfg.get("alfred.channel_id", "") or
                  cfg.get("api_keys.discord_briefing_channel_id", "") or "")
    req = urllib.request.Request(
        f"{API}/channels/{channel}/messages?limit=25",
        headers={"Authorization": f"Bot {token}",
                 "User-Agent": "DiscordBot (https://github.com/chopra2007, 1.0)"})
    msgs = json.load(urllib.request.urlopen(req, timeout=20))

    verdict = verdict_for(msgs)
    print(verdict)
    with open(NOTIFY, "a") as fh:
        fh.write(verdict + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
