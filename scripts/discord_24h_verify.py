#!/usr/bin/env python3
"""Discord bot 24h verification probe.

Posts a `!help` command and an `@bot ping-PROBE-<nonce>` mention to the
commands channel using the bot's own token, then polls for replies.

Per spec line 99: match `!help` reply by `message_reference.message_id ==
probe_id`; match mention reply by `referenced_message.id == probe_id` OR by
content containing the unique nonce. The bot's relaxed self-filter at
`discord_tweetshift.py:284-285` lets self-token probes reach dispatch.

Exit codes:
  0 = both probes received replies (success)
  1 = !help reply timed out
  2 = mention reply timed out
  3 = both timed out
  4 = transport error (HTTP 5xx, network failure, missing env, etc.)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import uuid
from typing import Optional

import aiohttp


API_BASE = "https://discord.com/api/v10"
ENV_FILE = "/home/openclaw/.openclaw/.env.service"
POLL_EVERY_S = 3
POLL_TIMEOUT_S = 60
HTTP_TIMEOUT_S = 15


def _load_env(path: str) -> None:
    if os.environ.get("DISCORD_BOT_TOKEN") and os.environ.get("DISCORD_CHANNEL_ID"):
        return
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


async def _post(session: aiohttp.ClientSession, channel_id: str, content: str) -> str:
    url = f"{API_BASE}/channels/{channel_id}/messages"
    async with session.post(url, json={"content": content}) as resp:
        if resp.status not in (200, 201):
            body = await resp.text()
            raise RuntimeError(f"POST failed {resp.status}: {body[:200]}")
        data = await resp.json()
        return str(data["id"])


async def _wait_for_reply(
    session: aiohttp.ClientSession,
    channel_id: str,
    probe_id: str,
    nonce: Optional[str] = None,
) -> tuple[bool, float]:
    """Poll GET /messages?after={probe_id} until a matching reply appears.

    A "matching reply" is any message whose `message_reference.message_id`
    equals the probe id, OR whose content contains the optional nonce.
    """
    url = f"{API_BASE}/channels/{channel_id}/messages"
    deadline = time.time() + POLL_TIMEOUT_S
    while time.time() < deadline:
        async with session.get(url, params={"after": probe_id, "limit": 20}) as resp:
            if resp.status != 200:
                await asyncio.sleep(POLL_EVERY_S)
                continue
            messages = await resp.json()
            for m in messages:
                ref = m.get("message_reference") or {}
                if str(ref.get("message_id") or "") == probe_id:
                    return True, time.time() - (deadline - POLL_TIMEOUT_S)
                if nonce and nonce in (m.get("content") or ""):
                    return True, time.time() - (deadline - POLL_TIMEOUT_S)
        await asyncio.sleep(POLL_EVERY_S)
    return False, POLL_TIMEOUT_S


async def _verify_once() -> int:
    _load_env(ENV_FILE)
    token = os.environ.get("DISCORD_BOT_TOKEN")
    channel_id = os.environ.get("DISCORD_CHANNEL_ID")
    if not token or not channel_id:
        print("ERROR: DISCORD_BOT_TOKEN or DISCORD_CHANNEL_ID missing from env", file=sys.stderr)
        return 4

    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)

    nonce = uuid.uuid4().hex[:8]
    help_ok = mention_ok = False
    help_elapsed = mention_elapsed = -1.0

    try:
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            help_id = await _post(session, channel_id, "!help")
            help_ok, help_elapsed = await _wait_for_reply(session, channel_id, help_id)

            bot_id = os.environ.get("DISCORD_BOT_USER_ID", "1468886193054814352")
            mention_content = f"<@{bot_id}> ping-PROBE-{nonce}"
            mention_id = await _post(session, channel_id, mention_content)
            mention_ok, mention_elapsed = await _wait_for_reply(
                session, channel_id, mention_id, nonce=f"PROBE-{nonce}"
            )
    except (aiohttp.ClientError, RuntimeError, asyncio.TimeoutError) as exc:
        print(f"TRANSPORT_ERROR: {exc}", file=sys.stderr)
        return 4

    print(
        f"help={'OK' if help_ok else 'TIMEOUT'} ({help_elapsed:.1f}s) | "
        f"mention={'OK' if mention_ok else 'TIMEOUT'} ({mention_elapsed:.1f}s)"
    )
    if help_ok and mention_ok:
        return 0
    if not help_ok and mention_ok:
        return 1
    if help_ok and not mention_ok:
        return 2
    return 3


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run one probe pair and exit.")
    args = parser.parse_args()
    if not args.once:
        print("ERROR: only --once is supported (orchestration is in the Claude session loop)", file=sys.stderr)
        return 4
    return asyncio.run(_verify_once())


if __name__ == "__main__":
    sys.exit(main())
