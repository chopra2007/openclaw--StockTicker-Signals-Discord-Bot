"""Unit tests for Pass 5 Steps 6+7+8 (TweetShift hardening + semaphore pool + _safe_send).

Adds the test coverage that Agent B did not write before its dispatch budget
ran out. Each test exercises one behavior contract from the plan.

Step 6 — pre-READY buffer in scanners/discord_tweetshift.py
Step 7 — semaphore pool in alerts/commands.py
Step 8 — _safe_send retry/backoff in alerts/discord.py
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from consensus_engine.scanners.discord_tweetshift import DiscordTweetShiftListener
from consensus_engine.alerts.commands import _dispatch_inner, _OUTER_SEM
from consensus_engine.alerts.discord import _safe_send, _redact_secrets


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


def _bare_listener():
    """Listener with fresh state — no _bot_user_id set, _ready_received=False.

    Differs from the production-style helper in test_discord_command_dispatch_regression
    which sets _bot_user_id="999" to bypass the buffer. We want the buffer to engage."""
    listener = DiscordTweetShiftListener(
        on_tweet=AsyncMock(), on_command=AsyncMock(), on_mention=AsyncMock(),
    )
    listener._token = "fake-token"
    listener._feed_channel_id = "100"
    listener._commands_channel_id = "200"
    listener._briefing_channel_id = "300"
    # NOTE: deliberately do NOT set _bot_user_id — the buffer must engage
    return listener


# ---------------------------------------------------------------------------
# Step 6 — Pre-READY buffer behavior (scanners/discord_tweetshift.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step6_message_before_ready_is_buffered():
    """A MESSAGE_CREATE arriving while _ready_received=False must be appended
    to the pre-READY buffer (NOT dispatched), and the buffer count must grow."""
    listener = _bare_listener()
    payload = {
        "channel_id": "200", "id": "early-1",
        "author": {"id": "user-a"}, "content": "!help", "mentions": [],
    }
    assert len(listener._pre_ready_buffer) == 0

    await listener._handle_dispatch("MESSAGE_CREATE", payload)

    assert len(listener._pre_ready_buffer) == 1
    listener._on_command.assert_not_called()


@pytest.mark.asyncio
async def test_step6_buffer_drains_on_ready_in_arrival_order():
    """On READY, the buffered messages must replay through _handle_dispatch
    in arrival order before _ready_received flips to True."""
    listener = _bare_listener()
    listener._allowed_webhook_ids = set()  # match production default

    # Two pre-READY messages, both in the commands channel
    for i in (1, 2):
        await listener._handle_dispatch("MESSAGE_CREATE", {
            "channel_id": "200", "id": f"early-{i}",
            "author": {"id": "user-a"}, "content": f"!help arg{i}",
            "mentions": [],
        })
    assert len(listener._pre_ready_buffer) == 2

    # Mock db.claim_message so the dispatch path doesn't depend on real DB state
    with patch(
        "consensus_engine.scanners.discord_tweetshift.db.claim_message",
        new=AsyncMock(return_value=True),
    ):
        # READY event populates _bot_user_id + drains
        await listener._handle_dispatch("READY", {
            "session_id": "sess-abc",
            "user": {"id": "bot-id-1"},
        })

    # Drained — buffer empty, both commands routed in order
    assert len(listener._pre_ready_buffer) == 0
    assert listener._ready_received is True
    assert listener._on_command.call_count == 2
    # First call corresponds to early-1, second to early-2
    first = listener._on_command.call_args_list[0].args
    second = listener._on_command.call_args_list[1].args
    assert first[3] == "early-1"  # message_id is the 4th positional
    assert second[3] == "early-2"


@pytest.mark.asyncio
async def test_step6_buffer_drops_when_cap_exceeded():
    """When the buffer is at capacity, additional messages are dropped (with
    _pre_ready_drops incremented) — never silently overflow."""
    listener = _bare_listener()
    listener._pre_ready_buffer.clear()
    # Shrink the cap for the test (the production default is 100; here we want 2)
    from collections import deque
    listener._pre_ready_buffer = deque(maxlen=2)

    for i in range(5):
        await listener._handle_dispatch("MESSAGE_CREATE", {
            "channel_id": "200", "id": f"early-{i}",
            "author": {"id": "user-a"}, "content": "!help", "mentions": [],
        })

    # Only the first 2 fit; remaining 3 are dropped
    assert len(listener._pre_ready_buffer) == 2
    assert listener._pre_ready_drops == 3


@pytest.mark.asyncio
async def test_step6_bot_user_id_shortcut_bypasses_buffer():
    """If _bot_user_id is set externally (test-fixture path), the listener
    treats itself as post-READY and routes immediately without buffering."""
    listener = _bare_listener()
    listener._bot_user_id = "888"  # simulate post-READY for a test fixture
    listener._allowed_webhook_ids = set()

    payload = {
        "channel_id": "200", "id": "shortcut-1",
        "author": {"id": "user-a"}, "content": "!help", "mentions": [],
    }
    with patch(
        "consensus_engine.scanners.discord_tweetshift.db.claim_message",
        new=AsyncMock(return_value=True),
    ):
        await listener._handle_dispatch("MESSAGE_CREATE", payload)

    assert len(listener._pre_ready_buffer) == 0  # not buffered
    assert listener._ready_received is True       # shortcut flipped it
    listener._on_command.assert_called_once()


# ---------------------------------------------------------------------------
# Step 7 — Semaphore pool (alerts/commands.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step7_dispatch_inner_returns_task_and_resolves_value():
    """_dispatch_inner wraps a coroutine in _INNER_SEM and returns a Task
    that resolves to the coroutine's return value."""
    async def _sample():
        return "done"

    task = await _dispatch_inner(_sample())
    assert isinstance(task, asyncio.Task)
    assert (await task) == "done"


@pytest.mark.asyncio
async def test_step7_dispatch_inner_exception_propagates_not_swallowed():
    """If the inner coroutine raises, the exception must be raisable from the
    task (not silently swallowed) — proves async-with release is exception-safe."""
    class _Boom(Exception):
        pass

    async def _explode():
        raise _Boom("expected")

    task = await _dispatch_inner(_explode())
    with pytest.raises(_Boom):
        await task


@pytest.mark.asyncio
async def test_step7_outer_sem_is_async_with_compatible():
    """_OUTER_SEM must support async-with — protects callers from leaking
    permits on exception. We verify by acquiring + releasing twice with
    an exception sandwiched between."""
    # First entry — acquires + releases cleanly
    async with _OUTER_SEM:
        pass
    # Second entry — must still have permits available
    try:
        async with _OUTER_SEM:
            raise RuntimeError("simulated handler failure")
    except RuntimeError:
        pass
    # Third entry — would deadlock if the prior exception leaked a permit
    async with _OUTER_SEM:
        pass


# ---------------------------------------------------------------------------
# Step 8 — _safe_send retry/backoff (alerts/discord.py)
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal aiohttp.ClientResponse stand-in for _safe_send tests."""

    def __init__(self, status: int, *, json_body=None, text_body="", headers=None):
        self.status = status
        self._json_body = json_body if json_body is not None else {}
        self._text_body = text_body
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return self._json_body

    async def text(self):
        return self._text_body


class _FakeSession:
    """Records each post() call and returns the next queued response."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls = []  # (url, payload) per call

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append((url, json))
        if not self._responses:
            raise RuntimeError("test exhausted queued responses")
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_step8_safe_send_returns_json_on_200():
    """200 OK → return the parsed JSON body."""
    session = _FakeSession([_FakeResponse(200, json_body={"id": "msg-1"})])
    with patch(
        "consensus_engine.alerts.discord.get_session",
        new=AsyncMock(return_value=session),
    ):
        result = await _safe_send("https://discord", {}, {"content": "hi"})

    assert result == {"id": "msg-1"}
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_step8_safe_send_400_falls_back_to_plaintext():
    """400 Bad Request on embed payload → falls back to plain content post.
    The fallback succeeds → final result is the fallback's parsed JSON."""
    session = _FakeSession([
        _FakeResponse(400, text_body="Invalid embed shape"),
        _FakeResponse(200, json_body={"id": "fallback-1"}),
    ])
    payload = {"embeds": [{"description": "rich body here", "title": "T"}]}

    with patch(
        "consensus_engine.alerts.discord.get_session",
        new=AsyncMock(return_value=session),
    ):
        result = await _safe_send("https://discord", {}, payload)

    assert result == {"id": "fallback-1"}
    # Second call must be the plaintext fallback (content, no embeds)
    assert "content" in session.calls[1][1]
    assert "embeds" not in session.calls[1][1]
    assert session.calls[1][1]["content"].startswith("rich body here")


@pytest.mark.asyncio
async def test_step8_safe_send_429_retries_then_succeeds():
    """429 with Retry-After 0 → sleeps 0s, retries → 200 → success."""
    session = _FakeSession([
        _FakeResponse(429, json_body={"retry_after": 0.0}, headers={"Retry-After": "0"}),
        _FakeResponse(200, json_body={"id": "after-retry"}),
    ])
    with patch(
        "consensus_engine.alerts.discord.get_session",
        new=AsyncMock(return_value=session),
    ), patch(
        "consensus_engine.alerts.discord.asyncio.sleep",
        new=AsyncMock(),
    ) as fake_sleep:
        result = await _safe_send("https://discord", {}, {"content": "hi"}, max_retries=2)

    assert result == {"id": "after-retry"}
    assert len(session.calls) == 2
    fake_sleep.assert_called_once_with(0.0)


@pytest.mark.asyncio
async def test_step8_safe_send_429_exhaustion_posts_truncation_notice():
    """All max_retries+1 attempts return 429 → post truncation embed → return None."""
    # max_retries=1 → 2 attempts total before exhaustion + truncation post
    session = _FakeSession([
        _FakeResponse(429, json_body={"retry_after": 0.0}),
        _FakeResponse(429, json_body={"retry_after": 0.0}),
        _FakeResponse(200, json_body={"id": "truncation-notice"}),  # truncation post
    ])
    with patch(
        "consensus_engine.alerts.discord.get_session",
        new=AsyncMock(return_value=session),
    ), patch(
        "consensus_engine.alerts.discord.asyncio.sleep",
        new=AsyncMock(),
    ):
        result = await _safe_send("https://discord", {}, {"content": "hi"}, max_retries=1)

    assert result is None
    # Last call must be the truncation embed
    last_call_payload = session.calls[-1][1]
    assert "embeds" in last_call_payload
    desc = last_call_payload["embeds"][0]["description"]
    assert "truncated" in desc.lower()


@pytest.mark.asyncio
async def test_step8_safe_send_500_returns_none_no_retry():
    """Non-429 non-400 errors (e.g. 500) → log + return None, no retry loop."""
    session = _FakeSession([_FakeResponse(500, text_body="Internal Server Error")])
    with patch(
        "consensus_engine.alerts.discord.get_session",
        new=AsyncMock(return_value=session),
    ):
        result = await _safe_send("https://discord", {}, {"content": "hi"})

    assert result is None
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_step8_safe_send_network_exception_returns_none():
    """If the session.post() raises (network failure, etc.), _safe_send must
    swallow + return None (callers must not crash on transient network errors)."""
    class _BoomSession:
        def post(self, *a, **kw):
            raise RuntimeError("connection reset")

    with patch(
        "consensus_engine.alerts.discord.get_session",
        new=AsyncMock(return_value=_BoomSession()),
    ):
        result = await _safe_send("https://discord", {}, {"content": "hi"})

    assert result is None


# ---------------------------------------------------------------------------
# Step 8 — _redact_secrets helper
# ---------------------------------------------------------------------------


def test_step8_redact_secrets_strips_token_keyword():
    """The literal word 'token' (case-insensitive) gets replaced with [REDACTED]."""
    assert "[REDACTED]" in _redact_secrets("Authorization: Bearer your_token_here")
    assert "[REDACTED]" in _redact_secrets("auth Token expired")


def test_step8_redact_secrets_strips_mtq_token_pattern():
    """Discord bot tokens start with MTQ — pattern MTQ + 20+ chars must redact."""
    payload = "Bot MTQabcdefghijklmnopqrstuvwxyz0123456789 failed"
    redacted = _redact_secrets(payload)
    assert "MTQabc" not in redacted
    assert "[REDACTED]" in redacted


def test_step8_redact_secrets_passes_through_clean_text():
    """Non-secret text is unchanged."""
    clean = "Discord error: 400 Bad Request — embed too long"
    assert _redact_secrets(clean) == clean
