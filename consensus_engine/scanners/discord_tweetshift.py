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
import urllib.parse
from collections import deque
from json import JSONDecodeError
from typing import Callable, Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.utils.http import get_session
from consensus_engine.utils.obs_log import obs_log

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
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

# #8 — reconnect replay tuning.
_DISCORD_EPOCH_MS = 1420070400000   # Discord snowflake epoch (2015-01-01)
_REPLAY_PAGE_LIMIT = 100            # Discord REST /messages max per page
_REPLAY_MAX_MESSAGES = 50           # most-recent N replayed per channel
_REPLAY_STALENESS_SECONDS = 900.0   # skip messages older than 15 minutes


def _normalize_handle(raw: str) -> str:
    """Strip @ prefix and lowercase for comparison."""
    return raw.lstrip("@").lower()


def _snowflake_age_seconds(message_id: str, now: float) -> float:
    """Age in seconds of a Discord snowflake id relative to `now` (epoch secs).

    An unparseable id returns 0.0 (treated as fresh) — routing/claim decides.
    """
    try:
        created_ms = (int(message_id) >> 22) + _DISCORD_EPOCH_MS
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, now - created_ms / 1000.0)


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
        self._news_channel_id: str = ""
        self._bot_user_id: str = ""  # populated from READY event
        self._allowed_webhook_ids: set[str] = set()  # populated by _load_config

        self._session_id: Optional[str] = None
        self._sequence: Optional[int] = None
        self._heartbeat_interval: float = 41.25
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._stop = False
        self._replay_lock = asyncio.Lock()  # #8 — serialize reconnect replays

        # Safe defaults — set properly on READY; pre-READY messages reference these
        self._reconnect_count: int = 0
        self._tweet_count: int = 0

        # Pre-READY buffer: messages arriving before READY are queued (cap 100),
        # then replayed in arrival order once READY fires.
        _pre_ready_cap = cfg.get("tweetshift.pre_ready_buffer_cap", 100)
        self._pre_ready_buffer: deque = deque(maxlen=_pre_ready_cap)
        self._pre_ready_drops: int = 0
        self._ready_received: bool = False

        # Malformed-frame rate-limiting: log at most once per minute
        self._malformed_frame_count: int = 0
        self._malformed_last_log: float = 0.0

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
        self._news_channel_id = str(
            cfg.get("api_keys.discord_news_channel_id", "") or ""
        ).strip()
        # Whitelist of webhook IDs allowed to post commands (default empty).
        # Used so external test harnesses can trigger !all and other commands
        # without going through a real Discord user account. Whitelisting by
        # webhook_id (not username) prevents trivial spoofing.
        raw_allowed = cfg.get("api_keys.discord_allowed_webhook_ids", []) or []
        self._allowed_webhook_ids: set[str] = {
            str(w).strip() for w in raw_allowed if str(w).strip()
        }
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
            # Drain pre-READY buffer in arrival order before marking ready.
            if self._pre_ready_buffer:
                log.info(
                    "Draining %d pre-READY buffered message(s)",
                    len(self._pre_ready_buffer),
                )
                while self._pre_ready_buffer:
                    buffered = self._pre_ready_buffer.popleft()
                    try:
                        await self._handle_dispatch("MESSAGE_CREATE", buffered)
                    except Exception as e:
                        log.error("Pre-READY replay error: %s", e, exc_info=True)
            self._ready_received = True
            # #8: READY (not RESUMED) means a fresh session with no Discord-side
            # event replay — re-drive commands/mentions missed during the gap.
            asyncio.create_task(self._replay_missed(), name="discord-replay")

        elif event == "MESSAGE_CREATE":
            # Buffer messages that arrive before READY — replay once READY fires.
            # If _bot_user_id is already set (e.g. externally configured for tests),
            # treat the listener as past-READY so messages are not buffered.
            if self._bot_user_id and not self._ready_received:
                self._ready_received = True
            if not self._ready_received:
                cap = self._pre_ready_buffer.maxlen or 100
                if len(self._pre_ready_buffer) >= cap:
                    self._pre_ready_drops += 1
                    obs_log({"ts": time.time(), "event": "pre_ready_drop", "total_drops": self._pre_ready_drops, "cap": cap})
                    log.warning(
                        "Pre-READY buffer full (cap=%d) — dropping message id=%s reason=pre_ready_buffer_full",
                        cap, data.get("id", "?"),
                    )
                else:
                    self._pre_ready_buffer.append(data)
                return
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

            # Commands / briefing channel: route messages. #8 — the filter +
            # dispatch logic moved into _filtered_out / _route_message so the
            # reconnect-replay path reuses exactly the same routing.
            elif channel_id in (self._commands_channel_id, self._briefing_channel_id,
                                self._news_channel_id) and channel_id:
                if self._filtered_out(data):
                    return
                await self._route_message(data)

    def _filtered_out(self, data: dict) -> bool:
        """True if a commands/briefing-channel message should be ignored —
        other bots, non-whitelisted webhooks, or the bot's own replies."""
        author_obj = data.get("author") or {}
        author_id = str(author_obj.get("id") or "")
        is_self = bool(self._bot_user_id) and author_id == self._bot_user_id
        # Self-bot replies carry message_reference (Discord auto-pings the
        # replied-to user — the bot itself — causing a mention loop). Drop
        # them. Self-bot fresh posts (no reference) are verification probes.
        is_self_reply = is_self and bool(
            (data.get("message_reference") or {}).get("message_id")
        )
        # Webhooks are dropped EXCEPT ones whitelisted in
        # api_keys.discord_allowed_webhook_ids (external test harnesses).
        webhook_id = str(data.get("webhook_id") or "")
        is_allowed_webhook = bool(webhook_id) and webhook_id in self._allowed_webhook_ids
        if ((author_obj.get("bot") and not is_self and not is_allowed_webhook)
                or (webhook_id and not is_allowed_webhook)
                or is_self_reply):
            return True
        if is_allowed_webhook:
            log.info(
                "Discord command via allowed webhook id=%s username=%s",
                webhook_id, author_obj.get("username", ""),
            )
        return False

    async def _route_message(self, data: dict) -> None:
        """Route one commands/briefing-channel message to the command or
        mention handler. The caller must have applied the channel check and
        _filtered_out first.

        #8: an atomic db.claim_message gate runs before dispatch so a live
        delivery and a reconnect replay never both handle the same message;
        db.mark_message_done after dispatch keeps replay from re-driving it.
        """
        channel_id = str(data.get("channel_id", ""))
        message_id = str(data.get("id", ""))
        content = data.get("content", "")
        author_id = str((data.get("author") or {}).get("id") or "")
        if not message_id:
            return
        if not await db.claim_message(message_id, channel_id):
            return  # already handled (live or a prior replay), or in flight

        from consensus_engine.alerts.commands import parse_command
        parsed = parse_command(content)

        # Commands run only on the commands channel; @-mentions are answered on
        # any listened channel (commands, briefing, news).
        is_command = bool(
            parsed and self._on_command and channel_id == self._commands_channel_id
        )
        mentioned_ids = [str(u.get("id", "")) for u in data.get("mentions", [])]
        is_mention = bool(
            not is_command and self._on_mention and self._bot_user_id
            and self._bot_user_id in mentioned_ids
        )

        # Restore the "thinking" indicator: react to the triggering message while
        # we work, remove it once the reply is sent. Only for real commands /
        # mentions — never the bot's own posts or unrelated channel chatter.
        acked = False
        if is_command or is_mention:
            acked = await self._add_ack_reaction(channel_id, message_id)

        callback_succeeded = False
        try:
            if is_command:
                cmd, args = parsed
                log.info("Discord command: !%s %s (user=%s)", cmd, args, author_id or "?")
                try:
                    await self._on_command(cmd, args, channel_id, message_id, author_id)
                except TypeError:
                    # Backward-compat for callbacks without author_id
                    await self._on_command(cmd, args, channel_id, message_id)
                callback_succeeded = True
            elif is_mention:
                clean = re.sub(r'<@!?' + re.escape(self._bot_user_id) + r'>',
                               '', content).strip()
                log.info("Discord mention in channel=%s (user=%s): %.80s",
                         channel_id, author_id, clean)
                log.info("mention_received", extra={
                    "channel_id": channel_id, "user_id": author_id,
                })
                await self._on_mention(clean, channel_id, message_id, author_id)
                callback_succeeded = True
            else:
                # Message in channel but not a command and not a mention — mark done anyway
                callback_succeeded = True
        except Exception as e:
            log.error("%s callback error: %s",
                      "Command" if is_command else "Mention", e, exc_info=True)
        finally:
            if acked:
                await self._remove_ack_reaction(channel_id, message_id)

        # mark_message_done only on callback success — leaves message claimable on error
        if callback_succeeded:
            await db.mark_message_done(message_id)

    async def _add_ack_reaction(self, channel_id: str, message_id: str) -> bool:
        """React to the triggering message with the ack emoji (the "thinking"
        indicator). Returns True if the reaction was added, so the caller knows
        whether to remove it later. Never raises — a failed reaction must not
        block the actual reply."""
        return await self._react(channel_id, message_id, "PUT")

    async def _remove_ack_reaction(self, channel_id: str, message_id: str) -> None:
        """Remove the bot's own ack emoji once the reply has been sent."""
        await self._react(channel_id, message_id, "DELETE")

    async def _react(self, channel_id: str, message_id: str, method: str) -> bool:
        emoji = str(cfg.get("tweetshift.ack_reaction", "👀") or "").strip()
        if not emoji or not channel_id or not message_id or not self._token:
            return False
        enc = urllib.parse.quote(emoji)
        url = (f"{GATEWAY_REST}/channels/{channel_id}/messages/{message_id}"
               f"/reactions/{enc}/@me")
        headers = {"Authorization": f"Bot {self._token}"}
        try:
            session = await get_session()
            async with session.request(
                method, url, headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status not in (200, 204):
                    log.debug("ack reaction %s -> HTTP %d (channel=%s)",
                              method, resp.status, channel_id)
                    return False
            return True
        except Exception as e:  # noqa: BLE001 — reactions are best-effort
            log.debug("ack reaction %s failed (channel=%s): %s",
                      method, channel_id, e)
            return False

    async def _replay_missed(self) -> None:
        """Replay commands/mentions missed during a gateway outage.

        Fires on READY only. The lock serializes two quick READYs — the
        second runs after the first and finds everything already claimed.
        """
        async with self._replay_lock:
            for channel_id in (self._commands_channel_id, self._briefing_channel_id,
                               self._news_channel_id):
                if not channel_id:
                    continue
                try:
                    await self._replay_channel(channel_id)
                except Exception as e:  # noqa: BLE001 — replay must not crash the listener
                    log.error("Replay error for channel %s: %s", channel_id, e)

    async def _replay_channel(self, channel_id: str) -> None:
        """Replay missed messages for one channel since its watermark."""
        after_id = await db.channel_watermark(channel_id)
        messages = await self._fetch_messages_since(channel_id, after_id)
        if messages is None:
            return  # REST error already logged
        if len(messages) >= _REPLAY_PAGE_LIMIT:
            log.warning(
                "Replay channel %s hit the %d-message page cap — an older "
                "backlog was likely dropped", channel_id, _REPLAY_PAGE_LIMIT,
            )
        # REST returns newest-first; replay oldest-first, capped at most-recent N.
        ordered = list(reversed(messages))[-_REPLAY_MAX_MESSAGES:]
        now = time.time()
        replayed = 0
        for msg in ordered:
            msg_id = str(msg.get("id", ""))
            if not msg_id:
                continue
            if _snowflake_age_seconds(msg_id, now) > _REPLAY_STALENESS_SECONDS:
                continue  # staleness cutoff — too old to be worth answering
            if self._filtered_out(msg):
                continue
            await self._route_message(msg)
            replayed += 1
        if replayed:
            log.info("Replay: routed %d missed message(s) for channel %s",
                     replayed, channel_id)

    async def _fetch_messages_since(
        self, channel_id: str, after_id: Optional[str],
    ) -> Optional[list]:
        """REST-fetch up to 100 messages for a channel, newest-first.

        With a watermark, fetches messages strictly after it; without one,
        the most recent page. Returns None on a non-200 (replay for the
        channel is then skipped). Modelled on discord_history._fetch_page.
        """
        url = f"{GATEWAY_REST}/channels/{channel_id}/messages"
        params: dict[str, object] = {"limit": _REPLAY_PAGE_LIMIT}
        if after_id:
            params["after"] = after_id
        headers = {"Authorization": f"Bot {self._token}"}
        try:
            session = await get_session()
            async with session.get(
                url, headers=headers, params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    log.warning("Replay fetch channel=%s HTTP %d",
                                channel_id, resp.status)
                    return None
                payload = await resp.json()
            return payload if isinstance(payload, list) else []
        except Exception as e:  # noqa: BLE001 — replay must degrade gracefully
            log.warning("Replay fetch channel=%s error: %s", channel_id, e)
            return None

    async def _connect_once(self):
        """Open one WebSocket session, run until disconnected."""
        headers = {"Authorization": f"Bot {self._token}"}
        session = await get_session()
        async with session.ws_connect(
            GATEWAY_URL,
            headers=headers,
            heartbeat=None,  # We manage heartbeats manually
            timeout=aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=60),
        ) as ws:
                self._ws = ws
                hb_task = None

                async for msg in ws:
                    if self._stop:
                        await ws.close()
                        break
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            payload = json.loads(msg.data)
                        except (JSONDecodeError, UnicodeDecodeError):
                            self._malformed_frame_count += 1
                            now = time.time()
                            if now - self._malformed_last_log >= 60.0:
                                log.warning(
                                    "Malformed Gateway frame (count=%d since last log) — skipping",
                                    self._malformed_frame_count,
                                )
                                self._malformed_last_log = now
                                self._malformed_frame_count = 0
                            continue
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

                        elif op == OP_INVALID_SESSION:
                            log.warning(
                                "Discord Gateway op:9 INVALID_SESSION (resumable=%s) — clearing session, will IDENTIFY on next connect",
                                bool(data),
                            )
                            self._session_id = None
                            self._sequence = None
                            await ws.close(code=4000)
                            break

                    elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                        log.warning("Discord Gateway WS closed: %s", msg)
                        break

                # Detect silent exit (sock_read=60 zombie): WS read loop
                # ended without an explicit CLOSE/ERROR frame.
                # Force IDENTIFY on next reconnect by clearing session state.
                ws_close_code = ws.close_code if ws else None
                log.info(
                    "Gateway loop exited (last_op=%s, last_event=%s, ws_closed=%s, close_code=%s)",
                    op if 'op' in dir() else None,
                    event if 'event' in dir() else None,
                    ws.closed if ws else None,
                    ws_close_code,
                )
                if ws_close_code is None:
                    log.warning("Silent gateway exit detected — clearing session to force IDENTIFY")
                    self._session_id = None
                    self._sequence = None
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
