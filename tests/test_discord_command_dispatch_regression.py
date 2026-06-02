"""Regression tests for the Discord gateway silent-reconnect fix.

Pre-fix behavior these tests catch:
1. op:9 INVALID_SESSION arrived but the gateway loop had no handler — the
   loop kept resuming on stale `_session_id`/`_sequence`, dispatch silently
   stopped while heartbeats continued.
2. `async for msg in ws` exited silently when `aiohttp` `sock_read=60`
   timeout fired — no CLOSE/ERROR frame, no log, no state clearing — and
   the next reconnect RESUMEd on stale state.
3. The bot's own messages were filtered before dispatch by an unconditional
   `author.bot` check, so verification probes via the bot's own token were
   silently dropped and could not detect either the silent-reconnect bug
   or its fix.

These tests directly exercise `_handle_dispatch` and `_connect_once` so they
cannot pass on pre-fix HEAD.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from consensus_engine.scanners.discord_tweetshift import (
    DiscordTweetShiftListener,
    OP_DISPATCH,
    OP_INVALID_SESSION,
)


def _fake_ws_msg(op, data=None, event=None, seq=None):
    payload = {"op": op}
    if data is not None:
        payload["d"] = data
    if event is not None:
        payload["t"] = event
    if seq is not None:
        payload["s"] = seq
    msg = MagicMock()
    msg.type = aiohttp.WSMsgType.TEXT
    msg.data = json.dumps(payload)
    return msg


def _make_listener():
    listener = DiscordTweetShiftListener(
        on_tweet=AsyncMock(),
        on_command=AsyncMock(),
        on_mention=AsyncMock(),
    )
    listener._token = "fake-token"
    listener._feed_channel_id = "100"
    listener._commands_channel_id = "200"
    listener._briefing_channel_id = "300"
    listener._news_channel_id = "400"
    listener._bot_user_id = "999"
    # Reactions hit the Discord REST API; stub them so routing tests stay
    # hermetic. Real reaction behaviour is covered separately via _react.
    listener._add_ack_reaction = AsyncMock(return_value=True)
    listener._remove_ack_reaction = AsyncMock()
    return listener


class _FakeWS:
    """Minimal aiohttp.ClientWebSocketResponse stand-in."""

    def __init__(self, messages, close_code=None):
        self._messages = list(messages)
        self.closed = False
        self.close_code = close_code

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            self.closed = True
            raise StopAsyncIteration
        return self._messages.pop(0)

    async def close(self, code=1000):
        self.closed = True
        self.close_code = code

    async def send_str(self, data):
        return None


class _FakeWSContext:
    def __init__(self, ws):
        self._ws = ws

    async def __aenter__(self):
        return self._ws

    async def __aexit__(self, *args):
        return False


class _FakeSession:
    def __init__(self, ws):
        self._ws = ws

    def ws_connect(self, *args, **kwargs):
        return _FakeWSContext(self._ws)


class _FakeSessionContext:
    def __init__(self, ws):
        self._ws = ws

    async def __aenter__(self):
        return _FakeSession(self._ws)

    async def __aexit__(self, *args):
        return False


async def _run_connect(listener, messages, close_code=None):
    fake_ws = _FakeWS(messages, close_code=close_code)
    fake_session = _FakeSession(fake_ws)
    with patch(
        "consensus_engine.scanners.discord_tweetshift.get_session",
        new=AsyncMock(return_value=fake_session),
    ):
        await listener._connect_once()
    return fake_ws


@pytest.mark.asyncio
async def test_op9_invalid_session_clears_state():
    """op:9 INVALID_SESSION must clear `_session_id` and `_sequence` so the
    next reconnect re-IDENTIFYs instead of RESUMEing on stale state."""
    listener = _make_listener()
    listener._session_id = "stale-session-abc"
    listener._sequence = 42

    await _run_connect(listener, [_fake_ws_msg(OP_INVALID_SESSION, data=False)])

    assert listener._session_id is None, "op:9 must clear stale _session_id"
    assert listener._sequence is None, "op:9 must clear stale _sequence"


@pytest.mark.asyncio
async def test_silent_exit_clears_state():
    """When the WS recv loop exits without CLOSE/ERROR (sock_read=60 zombie),
    the cleanup path must clear `_session_id` and `_sequence` to force
    IDENTIFY on the next reconnect."""
    listener = _make_listener()
    listener._session_id = "stale-session-xyz"
    listener._sequence = 99

    # Empty message stream → loop exits via StopAsyncIteration with
    # close_code=None — the silent-zombie signature.
    await _run_connect(listener, [], close_code=None)

    assert listener._session_id is None, "silent exit must clear _session_id"
    assert listener._sequence is None, "silent exit must clear _sequence"


@pytest.mark.asyncio
async def test_self_bot_probe_reaches_dispatch():
    """A `MESSAGE_CREATE` from the bot itself (verification probe via bot
    token) must reach `_on_command`. The bot-self filter relaxation lets
    self-author messages through while still filtering other bots and
    webhooks."""
    listener = _make_listener()

    payload = {
        "channel_id": "200",  # commands channel
        "id": "msg-id-1",
        "author": {"id": "999", "bot": True},  # self-bot probe
        "content": "!help",
        "mentions": [],
    }

    with patch("consensus_engine.scanners.discord_tweetshift.db.claim_message",
               new=AsyncMock(return_value=True)), \
         patch("consensus_engine.scanners.discord_tweetshift.db.mark_message_done",
               new=AsyncMock()):
        await listener._handle_dispatch("MESSAGE_CREATE", payload)

    listener._on_command.assert_called_once()
    cmd, args, channel_id, message_id, author_id = listener._on_command.call_args[0]
    assert cmd == "help"
    assert args == []
    assert channel_id == "200"
    assert message_id == "msg-id-1"
    assert author_id == "999"


@pytest.mark.asyncio
async def test_other_bot_still_filtered():
    """Loop-safety check: messages from a *different* bot are still filtered.
    Only `author.id == self._bot_user_id` is exempt from the bot filter."""
    listener = _make_listener()

    payload = {
        "channel_id": "200",
        "id": "msg-id-2",
        "author": {"id": "12345", "bot": True},  # some other bot
        "content": "!help",
        "mentions": [],
    }

    await listener._handle_dispatch("MESSAGE_CREATE", payload)

    listener._on_command.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_still_filtered():
    """Loop-safety check: webhook posts are filtered when their webhook_id is
    NOT in the allow-list. Whitelisted webhooks are covered separately below."""
    listener = _make_listener()
    listener._allowed_webhook_ids = set()  # empty allow-list

    payload = {
        "channel_id": "200",
        "id": "msg-id-3",
        "author": {"id": "999", "bot": True},
        "webhook_id": "abc-webhook",
        "content": "!help",
        "mentions": [],
    }

    await listener._handle_dispatch("MESSAGE_CREATE", payload)

    listener._on_command.assert_not_called()


@pytest.mark.asyncio
async def test_allowed_webhook_id_routes_command():
    """A webhook whose ID is in `_allowed_webhook_ids` should bypass the
    webhook filter and route the command. Used by external test harnesses
    (e.g. ClaudeCode) to trigger !all programmatically."""
    listener = _make_listener()
    listener._allowed_webhook_ids = {"WEBHOOK_ID_REDACTED"}

    payload = {
        "channel_id": "200",
        "id": "msg-id-allowed",
        # Real Discord webhook payloads carry author.bot=true; the filter must
        # exempt whitelisted webhook IDs from the bot-author drop or the
        # message never reaches dispatch.
        "author": {"id": "wh-author", "username": "ClaudeCode", "bot": True},
        "webhook_id": "WEBHOOK_ID_REDACTED",
        "content": "!all NVDA",
        "mentions": [],
    }

    with patch("consensus_engine.scanners.discord_tweetshift.db.claim_message",
               new=AsyncMock(return_value=True)), \
         patch("consensus_engine.scanners.discord_tweetshift.db.mark_message_done",
               new=AsyncMock()):
        await listener._handle_dispatch("MESSAGE_CREATE", payload)

    listener._on_command.assert_called_once()
    cmd, args, channel_id, message_id, author_id = listener._on_command.call_args.args
    assert cmd == "all"
    assert args == ["NVDA"]


@pytest.mark.asyncio
async def test_non_whitelisted_webhook_id_is_filtered():
    """Webhook with a different ID than the allow-list still gets filtered."""
    listener = _make_listener()
    listener._allowed_webhook_ids = {"WEBHOOK_ID_REDACTED"}

    payload = {
        "channel_id": "200",
        "id": "msg-id-other-wh",
        "author": {"id": "wh-author", "username": "Other"},
        "webhook_id": "9999999999999999999",
        "content": "!help",
        "mentions": [],
    }

    await listener._handle_dispatch("MESSAGE_CREATE", payload)

    listener._on_command.assert_not_called()


@pytest.mark.asyncio
async def test_self_bot_reply_is_filtered():
    """Loop-safety check: a self-bot message with `message_reference` is the
    bot's own reply (Discord auto-pings the replied-to user, which is the
    bot itself, creating a mention loop). The filter must drop these while
    still allowing self-probes (no message_reference) through."""
    listener = _make_listener()

    payload = {
        "channel_id": "200",
        "id": "msg-id-reply",
        "author": {"id": "999", "bot": True},  # self-bot
        "content": "OpenClaw Signal Engine — Commands\n!help — show this message",
        "message_reference": {"message_id": "earlier-probe-id"},
        "mentions": [{"id": "999"}],  # auto-included by Discord on a reply
    }

    await listener._handle_dispatch("MESSAGE_CREATE", payload)

    listener._on_command.assert_not_called()
    listener._on_mention.assert_not_called()


@pytest.mark.asyncio
async def test_news_channel_mention_routes():
    """An @-mention in the #news channel must reach `_on_mention` (questions
    in #news were previously ignored — only feed/commands/briefing listened)."""
    listener = _make_listener()
    payload = {
        "channel_id": "400",  # news channel
        "id": "news-mention-1",
        "author": {"id": "user-42"},
        "content": "<@999> What does Wolf say about Google?",
        "mentions": [{"id": "999"}],
    }
    with patch("consensus_engine.scanners.discord_tweetshift.db.claim_message",
               new=AsyncMock(return_value=True)), \
         patch("consensus_engine.scanners.discord_tweetshift.db.mark_message_done",
               new=AsyncMock()):
        await listener._handle_dispatch("MESSAGE_CREATE", payload)

    listener._on_mention.assert_called_once()
    clean, channel_id, message_id, author_id = listener._on_mention.call_args.args
    assert clean == "What does Wolf say about Google?"
    assert channel_id == "400"
    listener._on_command.assert_not_called()


@pytest.mark.asyncio
async def test_ack_reaction_added_and_removed_for_command():
    """A real command gets the "thinking" reaction added while working and
    removed after the reply."""
    listener = _make_listener()
    payload = {
        "channel_id": "200",  # commands channel
        "id": "ack-cmd-1",
        "author": {"id": "user-7"},
        "content": "!help",
        "mentions": [],
    }
    with patch("consensus_engine.scanners.discord_tweetshift.db.claim_message",
               new=AsyncMock(return_value=True)), \
         patch("consensus_engine.scanners.discord_tweetshift.db.mark_message_done",
               new=AsyncMock()):
        await listener._handle_dispatch("MESSAGE_CREATE", payload)

    listener._on_command.assert_called_once()
    listener._add_ack_reaction.assert_called_once_with("200", "ack-cmd-1")
    listener._remove_ack_reaction.assert_called_once_with("200", "ack-cmd-1")


@pytest.mark.asyncio
async def test_no_ack_reaction_for_plain_channel_message():
    """A plain message (no command, no mention) in a listened channel must NOT
    get a reaction — so the bot never reacts to its own #news posts."""
    listener = _make_listener()
    payload = {
        "channel_id": "400",  # news channel
        "id": "plain-1",
        "author": {"id": "user-9"},
        "content": "just chatting, no mention here",
        "mentions": [],
    }
    with patch("consensus_engine.scanners.discord_tweetshift.db.claim_message",
               new=AsyncMock(return_value=True)), \
         patch("consensus_engine.scanners.discord_tweetshift.db.mark_message_done",
               new=AsyncMock()):
        await listener._handle_dispatch("MESSAGE_CREATE", payload)

    listener._on_command.assert_not_called()
    listener._on_mention.assert_not_called()
    listener._add_ack_reaction.assert_not_called()
