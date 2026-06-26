"""!ask command — routes through the OpenClaw agent (same path as @-mention).

Since the !ask/@-mention unification, `!ask` no longer calls the Python
`call_with_fallback` chain directly. `_handle_ask` prepends the last 10
channel messages as context and forwards to `_handle_mention`, which runs
`openclaw agent --local` (workspace + tools + the openclaw model roulette).
"""
from __future__ import annotations

import pytest

from consensus_engine.alerts import commands


@pytest.mark.asyncio
async def test_ask_with_no_args_shows_usage(monkeypatch):
    sends: list[tuple[str, str, str]] = []

    async def _fake_send(channel_id, msg_id, content):
        sends.append((channel_id, msg_id, content))
        return "id"

    monkeypatch.setattr("consensus_engine.alerts.commands.send_command_reply", _fake_send)
    await commands.route_command("ask", [], "ch", "msg")
    assert len(sends) == 1
    assert "Usage" in sends[0][2] and "!ask" in sends[0][2]


@pytest.mark.asyncio
async def test_ask_routes_question_through_handle_mention(monkeypatch):
    """!ask forwards the question to _handle_mention (the openclaw agent path)."""
    captured: dict = {}

    async def _fake_mention(content, channel_id, message_id, *, allow_intercept=True):
        captured["content"] = content
        captured["channel_id"] = channel_id
        captured["message_id"] = message_id

    async def _fake_history(*_a, **_kw):
        return ""  # no channel history

    monkeypatch.setattr("consensus_engine.main._handle_mention", _fake_mention)
    monkeypatch.setattr(
        "consensus_engine.alerts.commands._fetch_channel_history", _fake_history,
    )

    await commands.route_command("ask", ["why", "is", "NVDA", "bullish?"], "ch", "msg")

    assert captured["content"] == "why is NVDA bullish?"
    assert captured["channel_id"] == "ch"
    assert captured["message_id"] == "msg"


@pytest.mark.asyncio
async def test_ask_prepends_channel_history_as_context(monkeypatch):
    """When channel history exists, !ask prefixes it to the question so the
    agent can answer with awareness of the recent conversation."""
    captured: dict = {}

    async def _fake_mention(content, channel_id, message_id, *, allow_intercept=True):
        captured["content"] = content

    async def _fake_history(*_a, **_kw):
        return "user1: previous chatter\nuser2: more chatter"

    monkeypatch.setattr("consensus_engine.main._handle_mention", _fake_mention)
    monkeypatch.setattr(
        "consensus_engine.alerts.commands._fetch_channel_history", _fake_history,
    )

    await commands.route_command("ask", ["what", "do", "you", "see"], "ch", "msg")

    content = captured["content"]
    assert "previous chatter" in content            # history is included
    assert "Question: what do you see" in content   # question is preserved


@pytest.mark.asyncio
async def test_ask_empty_question_guard(monkeypatch):
    """_handle_ask's defensive guard: an empty question replies with a hint
    and never reaches the agent."""
    sends: list[str] = []
    mention_calls: list = []

    async def _fake_send(channel_id, msg_id, content):
        sends.append(content)
        return "id"

    async def _fake_mention(*_a):
        mention_calls.append(_a)

    monkeypatch.setattr("consensus_engine.alerts.commands.send_command_reply", _fake_send)
    monkeypatch.setattr("consensus_engine.main._handle_mention", _fake_mention)

    await commands._handle_ask("", "ch", "msg")

    assert mention_calls == []
    assert len(sends) == 1
    assert "include a question" in sends[0].lower()
