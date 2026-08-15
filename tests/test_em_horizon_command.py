"""`!em <TICKER> [daily|weekly]` — horizon parsing and routing.

Covers the old default (`!em SPY` is still daily), the horizon word in either
position, multi-ticker plus one shared horizon, and the conflicting/incomplete
cases that must answer with the usage line instead of guessing a ticker.
"""

from unittest.mock import AsyncMock

import pytest

from consensus_engine.alerts import commands


# ---------------------------------------------------------------------------
# _extract_horizon
# ---------------------------------------------------------------------------

def test_no_horizon_word_means_daily():
    args, horizon = commands._extract_horizon(["spy"])
    assert args == ["spy"] and horizon == "daily"


def test_horizon_after_the_ticker():
    args, horizon = commands._extract_horizon(["spy", "weekly"])
    assert args == ["spy"] and horizon == "weekly"


def test_horizon_before_the_ticker():
    args, horizon = commands._extract_horizon(["weekly", "spy"])
    assert args == ["spy"] and horizon == "weekly"


def test_horizon_is_case_insensitive_and_dollar_tolerant():
    assert commands._extract_horizon(["SPY", "WeeKLY"])[1] == "weekly"
    assert commands._extract_horizon(["spy", "$daily"])[1] == "daily"


def test_explicit_daily_word():
    args, horizon = commands._extract_horizon(["spy", "daily"])
    assert args == ["spy"] and horizon == "daily"


def test_multi_ticker_with_one_shared_horizon():
    args, horizon = commands._extract_horizon(["nvda", "amd", "weekly"])
    assert args == ["nvda", "amd"] and horizon == "weekly"


def test_comma_separated_multi_ticker_with_horizon():
    args, horizon = commands._extract_horizon(["nvda,amd,mu", "weekly"])
    assert args == ["nvda", "amd", "mu"] and horizon == "weekly"


def test_repeating_the_same_horizon_is_fine():
    args, horizon = commands._extract_horizon(["spy", "weekly", "weekly"])
    assert args == ["spy"] and horizon == "weekly"


def test_two_different_horizons_is_a_conflict():
    args, horizon = commands._extract_horizon(["spy", "daily", "weekly"])
    assert horizon is None


# ---------------------------------------------------------------------------
# route_command("em", ...)
# ---------------------------------------------------------------------------

def _patch_em(monkeypatch):
    calls = []

    async def fake(t, ch, mid, horizon="daily"):
        calls.append((t, horizon))
        return None

    async def _inline_dispatch(coro):
        await coro

    reply = AsyncMock()
    monkeypatch.setattr(commands, "_dispatch_inner", _inline_dispatch)
    monkeypatch.setattr(commands, "_handle_em", fake)
    monkeypatch.setattr(commands, "send_command_reply", reply)
    return calls, reply


@pytest.mark.asyncio
async def test_route_em_plain_is_still_daily(monkeypatch):
    """Regression: `!em SPY` keeps working exactly as before."""
    calls, _ = _patch_em(monkeypatch)
    await commands.route_command("em", ["spy"], "ch", "mid")
    assert calls == [("SPY", "daily")]


@pytest.mark.asyncio
async def test_route_em_daily_word(monkeypatch):
    calls, _ = _patch_em(monkeypatch)
    await commands.route_command("em", ["spy", "daily"], "ch", "mid")
    assert calls == [("SPY", "daily")]


@pytest.mark.asyncio
async def test_route_em_weekly_word(monkeypatch):
    calls, _ = _patch_em(monkeypatch)
    await commands.route_command("em", ["spy", "weekly"], "ch", "mid")
    assert calls == [("SPY", "weekly")]


@pytest.mark.asyncio
async def test_route_em_horizon_first(monkeypatch):
    calls, _ = _patch_em(monkeypatch)
    await commands.route_command("em", ["weekly", "spy"], "ch", "mid")
    assert calls == [("SPY", "weekly")]


@pytest.mark.asyncio
async def test_route_em_multi_ticker_shares_the_horizon(monkeypatch):
    calls, _ = _patch_em(monkeypatch)
    await commands.route_command("em", ["nvda", "amd", "weekly"], "ch", "mid")
    assert calls == [("NVDA", "weekly"), ("AMD", "weekly")]


@pytest.mark.asyncio
async def test_route_em_conflicting_horizons_shows_usage(monkeypatch):
    calls, reply = _patch_em(monkeypatch)
    await commands.route_command("em", ["spy", "daily", "weekly"], "ch", "mid")
    assert calls == []
    sent = reply.call_args.args[2]
    assert "daily|weekly" in sent


@pytest.mark.asyncio
async def test_route_em_horizon_with_no_ticker_shows_usage(monkeypatch):
    calls, reply = _patch_em(monkeypatch)
    await commands.route_command("em", ["weekly"], "ch", "mid")
    assert calls == []
    assert "daily|weekly" in reply.call_args.args[2]


@pytest.mark.asyncio
async def test_route_em_no_args_shows_usage(monkeypatch):
    calls, reply = _patch_em(monkeypatch)
    await commands.route_command("em", [], "ch", "mid")
    assert calls == []
    assert "daily|weekly" in reply.call_args.args[2]


@pytest.mark.asyncio
async def test_help_text_shows_the_one_documented_format(monkeypatch):
    embed = commands._build_help_embed()
    blob = str(embed)
    assert "`!em <ticker> [daily|weekly]`" in blob
