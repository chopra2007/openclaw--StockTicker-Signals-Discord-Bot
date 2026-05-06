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

    def __init__(self, on_tweet: Callable, on_command: Optional[Callable] = None,
                 on_mention: Optional[Callable] = None):
        """
        Args:
            on_tweet: async callback(tweet_data: dict) called for each new tweet.
            on_command: optional async callback(command, args, channel_id, message_id)
                        called for !-prefixed messages on the commands channel.
            on_mention: optional async callback(content, channel_id, message_id, author_id)
                        called when the bot is @-mentioned with a non-command message
                        in the commands channel or the briefing channel.
        """
        self._on_tweet = on_tweet
        self._on_command = on_command
        self._on_mention = on_mention
        self._token: str = ""
        self._feed_channel_id: str = ""
        self._commands_channel_id: str = ""
        self._briefing_channel_id: str = ""
        self._bot_user_id: str = ""  # populated from READY event

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
        self._briefing_channel_id = str(
            cfg.get("api_keys.discord_briefing_channel_id", "") or ""
        ).strip()
        if not self._commands_channel_id:
            log.warning("discord_channel_id not configured — command routing disabled")

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
            self._reconnect_count = 0  # Reset on successful connect
            self._tweet_count = 0  # Reset tweet counter on connect
            self._bot_user_id = str((data.get("user") or {}).get("id") or "")
            log.info("Discord Gateway READY (session=%s, bot_id=%s)", self._session_id, self._bot_user_id)

        elif event == "MESSAGE_CREATE":
            channel_id = str(data.get("channel_id", ""))
            message_id = str(data.get("id", ""))
            content = data.get("content", "")

            # TweetShift feed channel: process as tweet
            if channel_id == self._feed_channel_id:
                tweet_data = _parse_tweetshift_message(data)
                guild_id = str(data.get("guild_id", ""))

                # Extract images from attachments and embeds regardless of tweet parse
                image_urls = []
                for att in data.get("attachments", []):
                    ct = att.get("content_type", "")
                    fn = att.get("filename", "")
                    if ct.startswith("image/") or fn.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                        image_urls.append(att["url"])
                for embed in data.get("embeds", []):
                    image_url = embed.get("image", {}).get("url")
                    if image_url:
                        image_urls.append(image_url)
                for embed in data.get("embeds", []):
                    thumb_url = embed.get("thumbnail", {}).get("url")
                    if thumb_url:
                        image_urls.append(thumb_url)
                # Also extract bare URLs from markdown image links in content: [text](url)
                if content:
                    for m in re.finditer(r'\[.*?\]\((https?://\S+\.(?:png|jpe?g|gif|webp)[^)]*)\)', content, re.IGNORECASE):
                        image_urls.append(m.group(1))
                deduped = list(dict.fromkeys(image_urls))

                if not tweet_data:
                    # Image-only message: skip if no images to analyze
                    if not deduped:
                        return
                    tweet_data = {
                        "url": f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}",
                        "text": "",
                        "analyst": "image_post",
                        "timestamp": time.time(),
                    }
                    log.info("Image-only message in feed channel — running vision analysis (%d image(s))", len(deduped))

                if guild_id and channel_id and message_id:
                    tweet_data["discord_source_link"] = (
                        f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
                    )
                tweet_data["image_urls"] = deduped
                tweet_data["image_url"] = deduped[0] if deduped else None
                log.info(
                    "TweetShift tweet: @%s — %.80s",
                    tweet_data["analyst"],
                    tweet_data["text"],
                )
                try:
                    await self._on_tweet(tweet_data)
                except Exception as e:
                    log.error("Tweet callback error: %s", e, exc_info=True)

            # Commands channel or briefing channel: route messages
            elif channel_id in (self._commands_channel_id, self._briefing_channel_id) and channel_id:
                author_id = str((data.get("author") or {}).get("id") or "")
                # Ignore messages from bots/webhooks to avoid loops
                author_obj = data.get("author") or {}
                if author_obj.get("bot") or data.get("webhook_id"):
                    return

                from consensus_engine.alerts.commands import parse_command
                parsed = parse_command(content)
                if parsed and self._on_command and channel_id == self._commands_channel_id:
                    cmd, args = parsed
                    log.info("Discord command: !%s %s (user=%s)", cmd, args, author_id or "?")
                    try:
                        await self._on_command(cmd, args, channel_id, message_id, author_id)
                    except TypeError:
                        # Backward-compat for callbacks without author_id
                        await self._on_command(cmd, args, channel_id, message_id)
                    except Exception as e:
                        log.error("Command callback error: %s", e, exc_info=True)
                elif self._on_mention and self._bot_user_id:
                    # Check if the bot is @-mentioned
                    mentioned_ids = [str(u.get("id", "")) for u in data.get("mentions", [])]
                    if self._bot_user_id in mentioned_ids:
                        # Strip the bot mention from content for cleaner input
                        clean = re.sub(r'<@!?' + re.escape(self._bot_user_id) + r'>', '', content).strip()
                        log.info("Discord mention in channel=%s (user=%s): %.80s", channel_id, author_id, clean)
                        try:
                            await self._on_mention(clean, channel_id, message_id, author_id)
                        except Exception as e:
                            log.error("Mention callback error: %s", e, exc_info=True)

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

        log.info("TweetShift listener starting (channel=%s)", self._feed_channel_id)

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
