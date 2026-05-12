"""Tests for the @-mention retry path in consensus_engine.main._handle_mention.

The handler runs 3 attempts of `openclaw agent` subprocess with exponential
backoff (2s, 4s between). Three failure branches: empty stdout, asyncio
TimeoutError, generic Exception. Test the 3 attempt-tree shapes:

1. retry-then-success — empties on attempts 1+2, real reply on attempt 3.
2. all-fail — every attempt returns empty stdout; reply contains
   "Agent unavailable after 3 retries" + last error.
3. timeout — every attempt raises TimeoutError; reply contains the
   "subprocess timed out (>125s)" last-error substring.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from consensus_engine import main as main_mod


def _make_proc(stdout: bytes, stderr: bytes) -> MagicMock:
    """Build a fake subprocess whose communicate() returns (stdout, stderr)."""
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


async def test_handle_mention_retry_then_success_on_third_attempt(monkeypatch):
    """Empty stdout on attempts 1+2, real reply on attempt 3. Asserts:
      - subprocess factory invoked exactly 3 times
      - send_command_reply called once with the reply text
      - asyncio.sleep called with backoff sequence (2, 4) — no sleep after 3
    """
    procs = [
        _make_proc(b"", b"FailoverError attempt 1"),
        _make_proc(b"", b"FailoverError attempt 2"),
        _make_proc(b"4", b""),
    ]
    factory = AsyncMock(side_effect=procs)
    monkeypatch.setattr(main_mod.asyncio, "create_subprocess_exec", factory)

    sleep_mock = AsyncMock()
    monkeypatch.setattr(main_mod.asyncio, "sleep", sleep_mock)

    reply_mock = AsyncMock()
    from consensus_engine.alerts import discord as discord_mod
    monkeypatch.setattr(discord_mod, "send_command_reply", reply_mock)

    await main_mod._handle_mention("hello", "chan_123", "msg_456")

    assert factory.await_count == 3, "expected 3 subprocess invocations"
    assert reply_mock.await_count == 1, "expected one reply"
    args, _ = reply_mock.call_args
    assert args[0] == "chan_123"
    assert args[1] == "msg_456"
    assert args[2] == "4"

    sleep_calls = [c.args[0] for c in sleep_mock.await_args_list]
    assert sleep_calls == [2, 4], f"expected backoff [2, 4]; got {sleep_calls!r}"


async def test_handle_mention_all_attempts_fail_returns_unavailable(monkeypatch):
    """Every attempt yields empty stdout. Reply text reports the failure."""
    factory = AsyncMock(
        side_effect=[_make_proc(b"", b"upstream 503") for _ in range(3)]
    )
    monkeypatch.setattr(main_mod.asyncio, "create_subprocess_exec", factory)
    monkeypatch.setattr(main_mod.asyncio, "sleep", AsyncMock())

    reply_mock = AsyncMock()
    from consensus_engine.alerts import discord as discord_mod
    monkeypatch.setattr(discord_mod, "send_command_reply", reply_mock)

    await main_mod._handle_mention("hello", "chan_xyz", "msg_abc")

    assert factory.await_count == 3
    assert reply_mock.await_count == 1
    reply_text = reply_mock.call_args.args[2]
    assert "Agent unavailable after 3 retries" in reply_text
    assert "Last error:" in reply_text
    assert "upstream 503" in reply_text


async def test_handle_mention_timeout_branch_reports_timeout(monkeypatch):
    """All 3 attempts raise asyncio.TimeoutError inside wait_for. Reply
    contains the "subprocess timed out (>180s)" branch's last_err."""
    factory = AsyncMock(return_value=_make_proc(b"x", b""))
    monkeypatch.setattr(main_mod.asyncio, "create_subprocess_exec", factory)
    monkeypatch.setattr(main_mod.asyncio, "sleep", AsyncMock())

    async def _always_timeout(*_args, **_kwargs):
        raise asyncio.TimeoutError()
    monkeypatch.setattr(main_mod.asyncio, "wait_for", _always_timeout)

    reply_mock = AsyncMock()
    from consensus_engine.alerts import discord as discord_mod
    monkeypatch.setattr(discord_mod, "send_command_reply", reply_mock)

    await main_mod._handle_mention("ping", "chan_t", "msg_t")

    assert factory.await_count == 3
    assert reply_mock.await_count == 1
    reply_text = reply_mock.call_args.args[2]
    assert "Agent unavailable after 3 retries" in reply_text
    assert "subprocess timed out (>180s)" in reply_text


async def test_handle_mention_empty_content_short_circuits(monkeypatch):
    """Empty content takes the early-return greeting path: no subprocess."""
    factory = AsyncMock()
    monkeypatch.setattr(main_mod.asyncio, "create_subprocess_exec", factory)

    reply_mock = AsyncMock()
    from consensus_engine.alerts import discord as discord_mod
    monkeypatch.setattr(discord_mod, "send_command_reply", reply_mock)

    await main_mod._handle_mention("", "chan_g", "msg_g")

    assert factory.await_count == 0, "no subprocess on empty content"
    assert reply_mock.await_count == 1
    assert "use `!help`" in reply_mock.call_args.args[2]
