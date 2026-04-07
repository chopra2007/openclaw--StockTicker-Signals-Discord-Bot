"""Discord Gateway listener for TweetShift tweets.

TweetShift bot posts analyst tweets to a designated Discord channel.
This scanner connects to the Discord Gateway (WebSocket) and listens for
MESSAGE_CREATE events in that channel, then feeds tweets into the pipeline.

Requires: MESSAGE_CONTENT privileged intent enabled on the bot in
Discord Developer Portal.
"""

import asyncio
import json
import logging
import re
import time
from typing import Callable, Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine import db

log = logging.getLogger("consensus_engine.scanner.discord_tweetshift")

# Discord Gateway constants
GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"
GATEWAY_REST = "https://discord.com/api/v10"

# Intents: GUILDS(1) + GUILD_MESSAGES(512) + MESSAGE_CONTENT(32768)
INTENTS = 1 | 512 | 32768

# Opcodes
OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11


def _normalize_handle(raw: str) -> str:
    """Strip @ prefix and lowercase for comparison."""
    return raw.lstrip("@").lower()


def _known_handles(sources: list[str]) -> set[str]:
    """Build a set of normalized handles from sources.json accounts."""
    return {_normalize_handle(h) for h in sources}


def _parse_tweetshift_message(message: dict) -> Optional[dict]:
    """Extract tweet data from a TweetShift Discord message.

    TweetShift sends embeds with the tweet author and content.
    Returns {"url": str, "text": str, "analyst": str, "timestamp": float}
    or None if the message doesn't look like a TweetShift tweet.
    """
    embeds = message.get("embeds", [])
    content = message.get("content", "")

    # Try embed-based format (most common for TweetShift)
    for embed in embeds:
        author = embed.get("author", {})
        author_name = author.get("name", "")
        author_url = author.get("url", "")
        author_icon = author.get("icon_url", "")
        description = embed.get("description", "")
        title = embed.get("title", "")
        fields = embed.get("fields", []) or []
        embed_url = embed.get("url", "")
        field_text = ""
        if fields and isinstance(fields, list):
            first = fields[0] if isinstance(fields[0], dict) else {}
            field_text = str(first.get("value", "") or "").strip()

        # Extract handle from author.url (most reliable)
        # e.g. https://twitter.com/NickTimiraos or https://x.com/NickTimiraos
        handle = None
        if author_url:
            m = re.search(r"(?:twitter\.com|x\.com)/([A-Za-z0-9_]+)", author_url)
            if m:
                handle = m.group(1)

        # Fallback: extract from author.name like "@handle" or "Name (@handle)"
        if not handle and author_name:
            m = re.search(r"@([A-Za-z0-9_]+)", author_name)
            if m:
                handle = m.group(1)
            elif re.match(r"^[A-Za-z0-9_]+$", author_name):
                handle = author_name

        if not handle:
            continue

        # Use embed URL as tweet URL, fallback to constructed URL
        tweet_url = embed_url or f"https://twitter.com/{handle}/status/unknown"

        timestamp = time.time()
        ts_str = embed.get("timestamp", "")
        if ts_str:
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                timestamp = dt.timestamp()
            except (ValueError, TypeError):
                pass

        # Tweet text can appear in description, title, or embed fields depending on TweetShift format.
        text = (description or title or field_text).replace("**", "").strip()
        if not text:
            continue

        return {
            "url": tweet_url,
            "text": text,
            "analyst": handle,
            "timestamp": timestamp,
            "avatar_url": author_icon or None,
            "display_name": author_name or None,
        }

    # Fallback: plain-text format "@handle: text"
    if content:
        m = re.match(r"@([A-Za-z0-9_]+)[:\s]+(.+)", content, re.DOTALL)
        if m:
            handle = m.group(1)
            text = m.group(2).strip()
            return {
                "url": f"https://twitter.com/{handle}/status/discord_{message.get('id', 'unknown')}",
                "text": text,
                "analyst": handle,
                "timestamp": time.time(),
            }

    return None


class DiscordTweetShiftListener:
    """Listens to a Discord channel for TweetShift posts via Gateway WebSocket."""

    def __init__(self, on_tweet: Callable, on_command: Optional[Callable] = None):
        """
        Args:
            on_tweet: async callback(tweet_data: dict) called for each new tweet.
            on_command: optional async callback(command, args, channel_id, message_id)
                        called for !-prefixed messages on the commands channel.
        """
        self._on_tweet = on_tweet
        self._on_command = on_command
        self._token: str = ""
        self._feed_channel_id: str = ""
        self._commands_channel_id: str = ""
        self._known: set[str] = set()

        self._session_id: Optional[str] = None
        self._sequence: Optional[int] = None
        self._heartbeat_interval: float = 41.25
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._stop = False

    def _load_config(self):
        self._token = cfg.get_api_key("discord_bot_token") or ""
        self._feed_channel_id = str(
            cfg.get("api_keys.discord_feed_channel_id", "") or ""
        ).strip()
        self._commands_channel_id = str(
            cfg.get("api_keys.discord_channel_id", "") or ""
        ).strip()
        if not self._commands_channel_id:
            log.warning("discord_channel_id not configured — command routing disabled")
        accounts = cfg.get_twitter_accounts()
        self._known = _known_handles(accounts)

    async def _send(self, payload: dict):
        if self._ws and not self._ws.closed:
            await self._ws.send_str(json.dumps(payload))

    async def _heartbeat_loop(self):
        while not self._stop:
            await asyncio.sleep(self._heartbeat_interval)
            if self._stop:
                break
            log.debug("Sending Gateway heartbeat (seq=%s)", self._sequence)
            await self._send({"op": OP_HEARTBEAT, "d": self._sequence})

    async def _identify(self):
        await self._send({
            "op": OP_IDENTIFY,
            "d": {
                "token": self._token,
                "intents": INTENTS,
                "properties": {
                    "os": "linux",
                    "browser": "openclaw",
                    "device": "openclaw",
                },
            },
        })

    async def _resume(self):
        await self._send({
            "op": OP_RESUME,
            "d": {
                "token": self._token,
                "session_id": self._session_id,
                "seq": self._sequence,
            },
        })

    async def _handle_dispatch(self, event: str, data: dict):
        if event == "READY":
            self._session_id = data.get("session_id")
            log.info("Discord Gateway READY (session=%s)", self._session_id)

        elif event == "MESSAGE_CREATE":
            channel_id = str(data.get("channel_id", ""))
            message_id = str(data.get("id", ""))
            content = data.get("content", "")

            # TweetShift feed channel: process as tweet
            if channel_id == self._feed_channel_id:
                tweet_data = _parse_tweetshift_message(data)
                if not tweet_data:
                    return
                analyst_norm = _normalize_handle(tweet_data.get("analyst", ""))
                if self._known and analyst_norm not in self._known:
                    log.debug(
                        "Ignoring non-tracked handle in feed channel: @%s",
                        tweet_data.get("analyst", ""),
                    )
                    return
                image_url = None
                for att in data.get("attachments", []):
                    ct = att.get("content_type", "")
                    fn = att.get("filename", "")
                    if ct.startswith("image/") or fn.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                        image_url = att["url"]
                        break
                if not image_url:
                    for embed in data.get("embeds", []):
                        image_url = embed.get("image", {}).get("url")
                        if image_url:
                            break
                if not image_url:
                    for embed in data.get("embeds", []):
                        image_url = embed.get("thumbnail", {}).get("url")
                        if image_url:
                            break
                tweet_data["image_url"] = image_url
                log.info(
                    "TweetShift tweet: @%s — %.80s",
                    tweet_data["analyst"],
                    tweet_data["text"],
                )
                try:
                    await self._on_tweet(tweet_data)
                except Exception as e:
                    log.error("Tweet callback error: %s", e, exc_info=True)

            # Commands channel: route !-prefixed messages
            elif channel_id == self._commands_channel_id and self._on_command:
                from consensus_engine.alerts.commands import parse_command
                parsed = parse_command(content)
                if parsed:
                    cmd, args = parsed
                    log.info("Discord command: !%s %s", cmd, args)
                    try:
                        await self._on_command(cmd, args, channel_id, message_id)
                    except Exception as e:
                        log.error("Command callback error: %s", e, exc_info=True)

    async def _connect_once(self):
        """Open one WebSocket session, run until disconnected."""
        headers = {"Authorization": f"Bot {self._token}"}
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                GATEWAY_URL,
                heartbeat=None,  # We manage heartbeats manually
                timeout=aiohttp.ClientTimeout(total=None, sock_read=60),
            ) as ws:
                self._ws = ws
                hb_task = None

                async for msg in ws:
                    if self._stop:
                        await ws.close()
                        break
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        payload = json.loads(msg.data)
                        op = payload.get("op")
                        data = payload.get("d", {})
                        seq = payload.get("s")
                        event = payload.get("t")

                        if seq is not None:
                            self._sequence = seq

                        if op == OP_HELLO:
                            self._heartbeat_interval = data["heartbeat_interval"] / 1000.0
                            if hb_task:
                                hb_task.cancel()
                            hb_task = asyncio.create_task(
                                self._heartbeat_loop(), name="discord-heartbeat"
                            )
                            if self._session_id and self._sequence:
                                await self._resume()
                            else:
                                await self._identify()

                        elif op == OP_DISPATCH:
                            await self._handle_dispatch(event, data or {})

                        elif op == OP_HEARTBEAT:
                            await self._send({"op": OP_HEARTBEAT, "d": self._sequence})

                        elif op == OP_HEARTBEAT_ACK:
                            log.debug("Gateway heartbeat ACK")

                    elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                        log.warning("Discord Gateway WS closed: %s", msg)
                        break

                if hb_task:
                    hb_task.cancel()

    async def run(self, stop_event: asyncio.Event):
        """Main loop: connect, reconnect on drop. Stops when stop_event is set."""
        self._load_config()

        if not self._token:
            log.error("No discord_bot_token configured — TweetShift listener disabled")
            return
        if not self._feed_channel_id or not self._feed_channel_id.isdigit():
            log.error("No discord_feed_channel_id configured — TweetShift listener disabled")
            return

        log.info(
            "TweetShift listener starting (channel=%s, watching %d accounts)",
            self._feed_channel_id,
            len(self._known),
        )

        backoff = 5
        while not stop_event.is_set() and not self._stop:
            try:
                await self._connect_once()
            except Exception as e:
                log.error("Discord Gateway error: %s", e)

            if stop_event.is_set():
                self._stop = True
                break
            if self._stop:
                break

            log.info("Reconnecting to Discord Gateway in %ds...", backoff)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 120)

        log.info("TweetShift listener stopped.")

    def stop(self):
        self._stop = True
