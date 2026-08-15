"""One command per horizon: `!em` is daily, `!emw` is weekly.

Both take several tickers at once and share the horizon across them. Typing the
old horizon word ("!em spy weekly") points at the other command instead of
looking up a stock called WEEKLY.
"""

from unittest.mock import AsyncMock

import pytest

from consensus_engine.alerts import commands


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


# ---------------------------------------------------------------------------
# !em — daily
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_em_is_daily(monkeypatch):
    calls, _ = _patch_em(monkeypatch)
    await commands.route_command("em", ["spy"], "ch", "mid")
    assert calls == [("SPY", "daily")]


@pytest.mark.asyncio
async def test_em_several_tickers_all_daily(monkeypatch):
    calls, _ = _patch_em(monkeypatch)
    await commands.route_command("em", ["spy", "qqq"], "ch", "mid")
    assert calls == [("SPY", "daily"), ("QQQ", "daily")]


@pytest.mark.asyncio
async def test_em_comma_separated_tickers(monkeypatch):
    calls, _ = _patch_em(monkeypatch)
    await commands.route_command("em", ["nvda,amd,mu"], "ch", "mid")
    assert calls == [("NVDA", "daily"), ("AMD", "daily"), ("MU", "daily")]


# ---------------------------------------------------------------------------
# !emw — weekly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_emw_is_weekly(monkeypatch):
    calls, _ = _patch_em(monkeypatch)
    await commands.route_command("emw", ["spy"], "ch", "mid")
    assert calls == [("SPY", "weekly")]


@pytest.mark.asyncio
async def test_emw_several_tickers_share_the_weekly_horizon(monkeypatch):
    calls, _ = _patch_em(monkeypatch)
    await commands.route_command("emw", ["spy", "qqq"], "ch", "mid")
    assert calls == [("SPY", "weekly"), ("QQQ", "weekly")]


@pytest.mark.asyncio
async def test_emw_respects_the_five_ticker_cap(monkeypatch):
    calls, reply = _patch_em(monkeypatch)
    await commands.route_command(
        "emw", ["a", "b", "c", "d", "e", "f"], "ch", "mid")
    assert [t for t, _ in calls] == ["A", "B", "C", "D", "E"]
    assert all(h == "weekly" for _, h in calls)


# ---------------------------------------------------------------------------
# Usage and the old horizon-word syntax
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_em_with_no_ticker_shows_daily_usage(monkeypatch):
    calls, reply = _patch_em(monkeypatch)
    await commands.route_command("em", [], "ch", "mid")
    assert calls == []
    assert "`!em <TICKER>`" in reply.call_args.args[2]


@pytest.mark.asyncio
async def test_emw_with_no_ticker_shows_weekly_usage(monkeypatch):
    calls, reply = _patch_em(monkeypatch)
    await commands.route_command("emw", [], "ch", "mid")
    assert calls == []
    assert "`!emw <TICKER>`" in reply.call_args.args[2]


@pytest.mark.asyncio
async def test_weekly_as_a_word_points_at_emw(monkeypatch):
    """`!em spy weekly` must not look up a stock called WEEKLY."""
    calls, reply = _patch_em(monkeypatch)
    await commands.route_command("em", ["spy", "weekly"], "ch", "mid")
    assert calls == []
    assert "`!emw <TICKER>`" in reply.call_args.args[2]


@pytest.mark.asyncio
async def test_daily_as_a_word_points_at_em(monkeypatch):
    """DAILY is a valid ticker shape — it must never be treated as one."""
    calls, reply = _patch_em(monkeypatch)
    await commands.route_command("em", ["spy", "daily"], "ch", "mid")
    assert calls == []
    assert "`!em <TICKER>`" in reply.call_args.args[2]


@pytest.mark.asyncio
async def test_horizon_word_hint_is_case_and_dollar_tolerant(monkeypatch):
    calls, reply = _patch_em(monkeypatch)
    await commands.route_command("emw", ["$WeeKLY", "spy"], "ch", "mid")
    assert calls == []
    assert "`!emw <TICKER>`" in reply.call_args.args[2]


def test_help_lists_both_commands():
    blob = str(commands._build_help_embed())
    assert "`!em <ticker>`" in blob
    assert "`!emw <ticker>`" in blob
    # the help must say the two commands accept more than one ticker
    assert "several tickers" in blob and "`!em spy qqq`" in blob
