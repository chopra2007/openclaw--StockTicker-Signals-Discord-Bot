"""T1-c (#76 menu) — `!sweep`: score the whole watchlist on demand and rank it.

The autonomous poll only surfaces tickers that trip a threshold; `!sweep` is the
"show me everything, including the quiet names" view. It must NOT be named `!scan`
(a live command that takes explicit tickers, cap 5), and its number must be the SAME
0-100 precision score `!scan` reports — ranking on the raw additive breakdown total
would re-create the incoherence TODO #50 removed.

Asserts:
  * flag OFF (default) → a plain "not enabled" reply, no scoring work
  * `!scan` still dispatches to the scan handler (the sweep never clobbers it)
  * the universe = live-signal tickers + fixed core, deduped and capped
  * ranking is by the precision score, descending, and a failing ticker is skipped
    rather than sinking the whole sweep
  * the scorer path calls analyze_signal (the #50 one-score rule), not breakdown.total
"""
from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine import config as cfg
from consensus_engine.alerts import commands


def _flag(enabled: bool, **over):
    real_get = cfg.get

    def fake_get(key, default=None):
        if key == "features.sweep.enabled":
            return enabled
        if key.startswith("features.sweep."):
            return over.get(key.split(".")[-1], real_get(key, default))
        return real_get(key, default)

    return patch("consensus_engine.config.get", side_effect=fake_get)


async def test_flag_off_replies_disabled_and_scores_nothing():
    with _flag(False), \
         patch.object(commands, "send_command_reply", new=AsyncMock()) as reply, \
         patch.object(commands, "_sweep_score_one", new=AsyncMock()) as scorer:
        await commands._handle_sweep("chan", "msg")
    assert scorer.await_count == 0, "a disabled command must not do any work"
    assert "not enabled" in reply.await_args[0][2]


async def test_universe_is_active_plus_core_deduped_and_capped():
    with _flag(True, max_tickers=4), \
         patch.object(commands.db, "get_active_tickers",
                      new=AsyncMock(return_value=["NVDA", "AMD"])), \
         patch.object(commands.cfg, "get", side_effect=lambda k, d=None: (
             ["AMD", "SPY", "QQQ", "TSLA"] if k == "options_flow.fixed_core"
             else (4 if k == "features.sweep.max_tickers" else cfg.get(k, d)))):
        universe = await commands._sweep_universe()
    assert universe == ["NVDA", "AMD", "SPY", "QQQ"], "dedupe AMD, then cap at 4"


async def test_ranking_is_by_score_and_a_failure_is_skipped():
    async def fake_score(ticker):
        if ticker == "BAD":
            raise RuntimeError("source down")
        return {"ticker": ticker, "score": {"NVDA": 81, "AMD": 55}[ticker], "catalyst": ""}

    sent: list[dict] = []

    async def fake_embed(chan, msg, embed):
        sent.append(embed)

    with _flag(True), \
         patch.object(commands, "_sweep_universe", new=AsyncMock(return_value=["AMD", "NVDA", "BAD"])), \
         patch.object(commands, "_sweep_score_one", side_effect=fake_score), \
         patch.object(commands, "send_command_reply", new=AsyncMock()), \
         patch.object(commands, "send_command_embed_reply", side_effect=fake_embed):
        await commands._sweep_and_reply("chan", "msg")

    assert len(sent) == 1
    value = sent[0]["fields"][0]["value"]
    assert value.index("$NVDA") < value.index("$AMD"), "highest score must rank first"
    assert "81" in value and "55" in value
    assert "1 skipped" in sent[0]["description"], "the failed ticker is reported, not hidden"


def _code_of(fn) -> str:
    """Source with the docstring stripped — so a docstring MENTIONING a banned
    pattern can't be mistaken for the code USING it."""
    src = inspect.getsource(fn)
    doc = inspect.getdoc(fn) or ""
    for line in doc.splitlines():
        src = src.replace(line, "")
    return src


async def test_sweep_uses_the_precision_score_not_the_additive_total():
    """#50: one score. If this ever ranks on breakdown.total, `!sweep NVDA` and
    `!scan NVDA` would print different numbers for the same ticker."""
    code = _code_of(commands._sweep_score_one)
    assert "analyze_signal" in code
    assert 'precision.get("total_score"' in code
    assert "breakdown.total" not in code


def test_catalyst_is_cut_at_a_word_boundary():
    """A sweep row is one line; a mid-word cut ('...Thursday whe') reads as a bug."""
    long_text = "International Business Machines Corp. stock underperforms Thursday when compared to rivals"
    out = commands._short_catalyst(long_text)
    assert out.endswith("…")
    assert not out.rstrip("…").endswith("whe")
    assert len(out) <= 71
    assert commands._short_catalyst("short one") == "short one"  # no ellipsis when it fits


def test_scan_command_is_not_clobbered():
    """`!scan` is a live, documented command. The sweep must be a NEW word."""
    src = inspect.getsource(commands._route_command_inner)
    assert 'elif command == "scan":' in src
    assert 'elif command in ("sweep", "universe"):' in src
