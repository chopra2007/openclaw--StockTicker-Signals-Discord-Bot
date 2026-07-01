"""Multi-ticker command support.

`!all nvda amd mu` (or `!all nvda, amd, mu`) runs the command for each ticker.
These tests cover the parser (`_parse_ticker_args`), the batch runner
(`_run_ticker_command`), the LONG/SHORT direction-word rules, and the blacklist
additions — plus a few end-to-end routes through `route_command`.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine.alerts import commands
from consensus_engine.utils.tickers import BLACKLIST, extract_tickers


# ---------------------------------------------------------------------------
# _parse_ticker_args
# ---------------------------------------------------------------------------

def test_parse_space_and_comma_equivalent():
    a, _, _, _ = commands._parse_ticker_args(["nvda,", "amd", "mu"], cap=5)
    b, _, _, _ = commands._parse_ticker_args(["nvda", "amd", "mu"], cap=5)
    c, _, _, _ = commands._parse_ticker_args(["nvda,amd,mu"], cap=5)
    assert a == b == c == ["NVDA", "AMD", "MU"]


def test_parse_strips_dollar_and_uppercases():
    tickers, _, _, _ = commands._parse_ticker_args(["$nvda", "AMD"], cap=5)
    assert tickers == ["NVDA", "AMD"]


def test_parse_dedupes_preserving_order():
    tickers, _, _, _ = commands._parse_ticker_args(
        ["nvda", "NVDA", "amd", "nvda"], cap=5)
    assert tickers == ["NVDA", "AMD"]


def test_parse_cap_moves_extras_to_dropped():
    tickers, _, invalid, dropped = commands._parse_ticker_args(
        ["a", "b", "c", "d", "e"], cap=3)
    assert tickers == ["A", "B", "C"]
    assert dropped == ["D", "E"]
    assert invalid == []


def test_parse_bad_format_is_invalid():
    tickers, _, invalid, _ = commands._parse_ticker_args(
        ["nvda", "toolongsym", "a!b"], cap=5)
    assert tickers == ["NVDA"]
    assert "TOOLONGSYM" in invalid
    assert "A!B" in invalid


def test_parse_direction_extracted_when_takes_direction():
    tickers, direction, invalid, _ = commands._parse_ticker_args(
        ["nvda", "amd", "short"], cap=5, takes_direction=True)
    assert tickers == ["NVDA", "AMD"]
    assert direction == "short"
    assert invalid == []  # 'short' is a direction word, not an invalid ticker


def test_parse_direction_default_long():
    _, direction, _, _ = commands._parse_ticker_args(
        ["nvda"], cap=5, takes_direction=True)
    assert direction == "long"


def test_parse_last_direction_word_wins():
    _, direction, _, _ = commands._parse_ticker_args(
        ["nvda", "long", "amd", "short"], cap=5, takes_direction=True)
    assert direction == "short"


def test_parse_direction_words_dropped_for_non_direction_commands():
    tickers, direction, invalid, _ = commands._parse_ticker_args(
        ["nvda", "short", "amd", "long"], cap=5, takes_direction=False)
    assert tickers == ["NVDA", "AMD"]
    assert "SHORT" not in tickers and "LONG" not in tickers
    assert "SHORT" not in invalid and "LONG" not in invalid
    assert direction == "long"  # unused, stays default


def test_parse_only_direction_word_yields_no_ticker():
    tickers, _, invalid, _ = commands._parse_ticker_args(
        ["short"], cap=5, takes_direction=True)
    assert tickers == []
    assert invalid == []


def test_parse_spy_still_valid():
    # The full blacklist would reject SPY; the command path must not.
    tickers, _, _, _ = commands._parse_ticker_args(["spy", "qqq"], cap=5)
    assert tickers == ["SPY", "QQQ"]


# ---------------------------------------------------------------------------
# blacklist (free-text extraction only)
# ---------------------------------------------------------------------------

def test_short_long_in_blacklist():
    assert "SHORT" in BLACKLIST
    assert "LONG" in BLACKLIST


def test_extract_ignores_short_and_long():
    assert extract_tickers("SHORT SQUEEZE ON GME") == {"GME"}
    assert extract_tickers("I am LONG NVDA here") == {"NVDA"}


# ---------------------------------------------------------------------------
# _batch_note
# ---------------------------------------------------------------------------

def test_batch_note_none_for_clean_single():
    assert commands._batch_note(["NVDA"], [], [], 5) is None


def test_batch_note_running_for_multi():
    note = commands._batch_note(["NVDA", "AMD"], [], [], 5)
    assert note is not None
    assert "NVDA" in note and "AMD" in note


def test_batch_note_reports_skips_and_drops():
    note = commands._batch_note(["A", "B", "C"], ["BADSYM"], ["D", "E"], 3)
    assert "Skipped" in note and "BADSYM" in note
    assert "Dropped" in note and "max 3" in note


# ---------------------------------------------------------------------------
# _run_ticker_command — semantics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_no_args_sends_usage():
    with patch.object(commands, "send_command_reply", new_callable=AsyncMock) as m:
        await commands._run_ticker_command(
            [], "ch", "mid", work=AsyncMock(), mode="parallel", cap=5,
            usage="USAGE-HERE")
    m.assert_called_once()
    assert m.call_args[0][2] == "USAGE-HERE"


@pytest.mark.asyncio
async def test_run_all_invalid_sends_invalid_message():
    work = AsyncMock()
    with patch.object(commands, "send_command_reply", new_callable=AsyncMock) as m:
        await commands._run_ticker_command(
            ["bad!sym"], "ch", "mid", work=work, mode="parallel", cap=5, usage="u")
    work.assert_not_called()
    assert "Invalid ticker" in m.call_args[0][2]


@pytest.mark.asyncio
async def test_run_parallel_fires_all_in_order():
    called = []

    async def work(t):
        called.append(t)

    with patch.object(commands, "send_command_reply", new_callable=AsyncMock):
        await commands._run_ticker_command(
            ["a", "b", "c"], "ch", "mid", work=work, mode="parallel", cap=5,
            usage="u")
    assert called == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_run_sequential_serializes_and_orders(monkeypatch):
    order = []

    async def _inner(t):
        order.append(f"start:{t}")
        await asyncio.sleep(0.005)
        order.append(f"end:{t}")

    async def work(t):
        # mimic a medium/heavy handler: dispatch the work, return its task
        return asyncio.create_task(_inner(t))

    async def _inline_dispatch(coro):
        await coro  # run the chain to completion, deterministically

    monkeypatch.setattr(commands, "_dispatch_inner", _inline_dispatch)
    with patch.object(commands, "send_command_reply", new_callable=AsyncMock):
        await commands._run_ticker_command(
            ["a", "b", "c"], "ch", "mid", work=work, mode="sequential", cap=5,
            usage="u")
    assert order == ["start:A", "end:A", "start:B", "end:B", "start:C", "end:C"]


@pytest.mark.asyncio
async def test_run_skips_bad_runs_rest():
    called = []

    async def work(t):
        called.append(t)

    with patch.object(commands, "send_command_reply", new_callable=AsyncMock) as m:
        await commands._run_ticker_command(
            ["nvda", "bad!sym", "amd"], "ch", "mid", work=work, mode="parallel",
            cap=5, usage="u")
    assert called == ["NVDA", "AMD"]
    notes = [c.args[2] for c in m.call_args_list]
    assert any("Skipped" in n and "BAD!SYM" in n for n in notes)


@pytest.mark.asyncio
async def test_run_cap_drops_extras():
    called = []

    async def work(t):
        called.append(t)

    with patch.object(commands, "send_command_reply", new_callable=AsyncMock) as m:
        await commands._run_ticker_command(
            ["a", "b", "c", "d"], "ch", "mid", work=work, mode="parallel", cap=3,
            usage="u")
    assert called == ["A", "B", "C"]
    notes = [c.args[2] for c in m.call_args_list]
    assert any("Dropped" in n and "max 3" in n for n in notes)


# ---------------------------------------------------------------------------
# End-to-end through route_command
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_route_signals_multi_parallel(monkeypatch):
    calls = []

    async def fake(t, ch, mid):
        calls.append(t)

    monkeypatch.setattr(commands, "_handle_signals", fake)
    monkeypatch.setattr(commands, "send_command_reply", AsyncMock())
    await commands.route_command("signals", ["nvda", "amd"], "ch", "mid")
    assert calls == ["NVDA", "AMD"]


@pytest.mark.asyncio
async def test_route_technical_multi_with_direction(monkeypatch):
    calls = []

    async def fake(t, d, ch, mid):
        calls.append((t, d))

    monkeypatch.setattr(commands, "_handle_technical", fake)
    monkeypatch.setattr(commands, "send_command_reply", AsyncMock())
    await commands.route_command("technical", ["nvda", "amd", "short"], "ch", "mid")
    assert calls == [("NVDA", "short"), ("AMD", "short")]


@pytest.mark.asyncio
async def test_route_sec_multi_sequential_in_order(monkeypatch):
    calls = []

    async def fake(t, ch, mid):
        calls.append(t)
        return None

    async def _inline_dispatch(coro):
        await coro

    monkeypatch.setattr(commands, "_dispatch_inner", _inline_dispatch)
    monkeypatch.setattr(commands, "_handle_sec", fake)
    monkeypatch.setattr(commands, "send_command_reply", AsyncMock())
    await commands.route_command("sec", ["nvda", "amd", "mu"], "ch", "mid")
    assert calls == ["NVDA", "AMD", "MU"]


@pytest.mark.asyncio
async def test_route_all_caps_at_3(monkeypatch):
    calls = []
    sent = []

    async def fake(t, ch, mid):
        calls.append(t)
        return None

    async def _inline_dispatch(coro):
        await coro

    async def fake_send(ch, mid, content):
        sent.append(content)

    monkeypatch.setattr(commands, "_dispatch_inner", _inline_dispatch)
    monkeypatch.setattr(commands, "_handle_all", fake)
    monkeypatch.setattr(commands, "send_command_reply", fake_send)
    await commands.route_command("all", ["a", "b", "c", "d", "e"], "ch", "mid")
    assert calls == ["A", "B", "C"]
    assert any("Dropped" in s and "max 3" in s for s in sent)
