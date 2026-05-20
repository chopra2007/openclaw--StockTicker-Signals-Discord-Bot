"""Tests for the @-mention retry path in consensus_engine.main._handle_mention.

The handler runs 2 attempts of the `openclaw agent` subprocess with a single
2s backoff between them — openclaw itself walks the model chain inside each
invocation, so this wrapper is only a subprocess-level safety net. Three
failure branches: empty stdout, asyncio TimeoutError, generic Exception.

1. retry-then-success — empty stdout on attempt 1, real reply on attempt 2.
2. all-fail — every attempt returns empty stdout; reply contains
   "Agent unavailable after 2 attempts" + last error.
3. timeout — every attempt raises TimeoutError; reply contains the
   "subprocess timed out (>270s)" last-error substring.
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


async def test_handle_mention_retry_then_success_on_second_attempt(monkeypatch):
    """Empty stdout on attempt 1, real reply on attempt 2. Asserts:
      - subprocess factory invoked exactly 2 times
      - send_command_reply called once with the reply text
      - asyncio.sleep called once with the 2s backoff — no sleep after 2
    """
    procs = [
        _make_proc(b"", b"FailoverError attempt 1"),
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

    assert factory.await_count == 2, "expected 2 subprocess invocations"
    assert reply_mock.await_count == 1, "expected one reply"
    args, _ = reply_mock.call_args
    assert args[0] == "chan_123"
    assert args[1] == "msg_456"
    assert args[2] == "4"

    sleep_calls = [c.args[0] for c in sleep_mock.await_args_list]
    assert sleep_calls == [2], f"expected backoff [2]; got {sleep_calls!r}"


async def test_handle_mention_all_attempts_fail_returns_unavailable(monkeypatch):
    """Every attempt yields empty stdout. Reply text reports the failure."""
    factory = AsyncMock(
        side_effect=[_make_proc(b"", b"upstream 503") for _ in range(2)]
    )
    monkeypatch.setattr(main_mod.asyncio, "create_subprocess_exec", factory)
    monkeypatch.setattr(main_mod.asyncio, "sleep", AsyncMock())

    reply_mock = AsyncMock()
    from consensus_engine.alerts import discord as discord_mod
    monkeypatch.setattr(discord_mod, "send_command_reply", reply_mock)

    await main_mod._handle_mention("hello", "chan_xyz", "msg_abc")

    assert factory.await_count == 2
    assert reply_mock.await_count == 1
    reply_text = reply_mock.call_args.args[2]
    assert "Agent unavailable after 2 attempts" in reply_text
    assert "Last error:" in reply_text
    assert "upstream 503" in reply_text


async def test_handle_mention_timeout_branch_reports_timeout(monkeypatch):
    """All attempts raise asyncio.TimeoutError inside wait_for. Reply
    contains the "subprocess timed out (>270s)" branch's last_err."""
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

    assert factory.await_count == 2
    assert reply_mock.await_count == 1
    reply_text = reply_mock.call_args.args[2]
    assert "Agent unavailable after 2 attempts" in reply_text
    assert "subprocess timed out (>270s)" in reply_text


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
