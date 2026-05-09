"""!ask command — full-power LLM responses via the primary chain.

Bare @-mentions stay on role="text" with the lighter chain. The !ask
command escapes to role="primary" with max_tokens=8000 so users can get
multi-paragraph reasoning that the splitting layer in send_command_reply
will fan out across multiple Discord messages.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

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
async def test_ask_routes_to_primary_with_8000_max_tokens(monkeypatch):
    sends: list[tuple[str, str, str]] = []
    captured: dict = {}

    async def _fake_send(channel_id, msg_id, content):
        sends.append((channel_id, msg_id, content))
        return "id"

    async def _fake_call(*, role, messages, max_tokens, temperature=None, timeout=None):
        captured["role"] = role
        captured["max_tokens"] = max_tokens
        captured["messages"] = messages
        return "Long bullish analysis of NVDA goes here."

    async def _fake_history(*_a, **_kw):
        return "user1: previous chatter\nuser2: more chatter"

    monkeypatch.setattr("consensus_engine.alerts.commands.send_command_reply", _fake_send)
    monkeypatch.setattr("consensus_engine.llm_client.call_with_fallback", _fake_call)
    monkeypatch.setattr(
        "consensus_engine.alerts.commands._fetch_channel_history", _fake_history,
    )
    monkeypatch.setattr(
        "consensus_engine.config.get_api_key", lambda *_a, **_kw: "fake_key",
    )

    await commands.route_command("ask", ["why", "is", "NVDA", "bullish?"], "ch", "msg")

    assert captured.get("role") == "primary"
    assert captured.get("max_tokens") == 8000
    user_msg = captured["messages"][-1]["content"]
    assert "why is NVDA bullish?" in user_msg


@pytest.mark.asyncio
async def test_ask_sends_full_response_via_split_capable_send(monkeypatch):
    """Long LLM output is delegated whole to send_command_reply (which splits)."""
    sends: list[tuple[str, str, str]] = []

    async def _fake_send(channel_id, msg_id, content):
        sends.append((channel_id, msg_id, content))
        return "id"

    long_response = "X" * 5500

    async def _fake_call(**_kwargs):
        return long_response

    async def _fake_history(*_a, **_kw):
        return ""

    monkeypatch.setattr("consensus_engine.alerts.commands.send_command_reply", _fake_send)
    monkeypatch.setattr("consensus_engine.llm_client.call_with_fallback", _fake_call)
    monkeypatch.setattr(
        "consensus_engine.alerts.commands._fetch_channel_history", _fake_history,
    )
    monkeypatch.setattr(
        "consensus_engine.config.get_api_key", lambda *_a, **_kw: "fake_key",
    )

    await commands.route_command("ask", ["what", "do", "you", "see"], "ch", "msg")

    # Single delegated send — splitting happens inside send_command_reply (tested
    # separately in test_discord_message_splitting.py).
    assert len(sends) == 1
    assert sends[0][2] == long_response


@pytest.mark.asyncio
async def test_ask_handles_empty_llm_response(monkeypatch):
    sends: list[tuple[str, str, str]] = []

    async def _fake_send(channel_id, msg_id, content):
        sends.append((channel_id, msg_id, content))
        return "id"

    async def _fake_call(**_kwargs):
        return ""

    async def _fake_history(*_a, **_kw):
        return ""

    monkeypatch.setattr("consensus_engine.alerts.commands.send_command_reply", _fake_send)
    monkeypatch.setattr("consensus_engine.llm_client.call_with_fallback", _fake_call)
    monkeypatch.setattr(
        "consensus_engine.alerts.commands._fetch_channel_history", _fake_history,
    )
    monkeypatch.setattr(
        "consensus_engine.config.get_api_key", lambda *_a, **_kw: "fake_key",
    )

    await commands.route_command("ask", ["any", "q"], "ch", "msg")
    assert len(sends) == 1
    assert "unavailable" in sends[0][2].lower() or "warning" in sends[0][2].lower()
