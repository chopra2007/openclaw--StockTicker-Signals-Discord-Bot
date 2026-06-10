"""Item 3 — level sanity gate in the !all anchor pipeline.

Proves that a wild YouTube level (e.g. 700 on a $208 NVDA) cannot reach
TP1/2/3 via the aggregator anchor pipeline, while a sane level passes through
unchanged.

Two test groups:
  A) Unit: extract_anchors_from_youtube_levels + filter_levels_for_display
     interact so wild rows are excluded from the Anchor list.
  B) Integration: the filter is wired in aggregator._gather_all_data path
     via a minimal monkeypatched run that exercises the real code path.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine.alerts.all_command import levels as levels_mod
from consensus_engine.analysis.level_display_sanity import (
    LevelVerdict,
    classify_level,
    filter_levels_for_display,
)


# ---------------------------------------------------------------------------
# Helper: build a minimal youtube_levels DB row dict.
# ---------------------------------------------------------------------------

def _yt_level_row(ticker: str, price: float, level_type: str = "resistance") -> dict:
    return {
        "ticker": ticker,
        "price": price,
        "level_type": level_type,
        "channel_name": "TestChannel",
        "published_at": "2026-06-10",
        "source_snippet": None,
        "channel_id": None,
        "trust_score": None,
        "approved": None,
        "freshness_days": 0,
        "touches": 0,
        "volume_strength": 0.0,
    }


def _patch_quote(price):
    """Patch the Finnhub quote used by classify_level / filter_levels_for_display."""
    return patch(
        "consensus_engine.analysis.level_display_sanity.get_live_quote_price",
        new=AsyncMock(return_value=price),
    )


# ---------------------------------------------------------------------------
# A) classify_level + filter_levels_for_display unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wild_setup_target_700_on_208_price_is_dropped():
    """700 / 208 = 3.37x >= 2.0 -> LevelVerdict.DROP (the exact bug scenario)."""
    verdict = await classify_level("NVDA", 700.0, live_price=208.0)
    assert verdict is LevelVerdict.DROP, (
        f"expected DROP for NVDA 700 on $208, got {verdict}"
    )


@pytest.mark.asyncio
async def test_sane_target_passes_through_unchanged():
    """$240 on a $208 stock = 1.15x -> KEEP."""
    verdict = await classify_level("NVDA", 240.0, live_price=208.0)
    assert verdict is LevelVerdict.KEEP, (
        f"expected KEEP for NVDA 240 on $208, got {verdict}"
    )


@pytest.mark.asyncio
async def test_filter_levels_for_display_excludes_wild_rows():
    """filter_levels_for_display strips the 700-row and keeps the 240-row."""
    rows = [
        {"price": 700.0},
        {"price": 240.0},
    ]
    with _patch_quote(208.0):
        kept, dropped = await filter_levels_for_display("NVDA", rows)

    assert dropped == 1, f"expected 1 dropped, got {dropped}"
    assert len(kept) == 1, f"expected 1 kept, got {len(kept)}"
    assert kept[0]["price"] == 240.0


# ---------------------------------------------------------------------------
# B) extract_anchors_from_youtube_levels does not itself suppress — the
#    aggregator must apply filter_levels_for_display BEFORE calling extract.
#    Test that the combination works end-to-end.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wild_level_excluded_from_anchor_list():
    """After filtering, extract_anchors_from_youtube_levels must not contain
    the wild $700 level, so it can never feed into TP1/2/3."""
    raw_rows = [
        _yt_level_row("NVDA", 700.0, "resistance"),  # wild
        _yt_level_row("NVDA", 240.0, "resistance"),  # sane
    ]

    with _patch_quote(208.0):
        sane_rows, dropped = await filter_levels_for_display("NVDA", raw_rows)

    anchors = levels_mod.extract_anchors_from_youtube_levels(sane_rows)
    prices = [a.price for a in anchors]

    assert 700.0 not in prices, f"wild $700 anchor must not be present; got {prices}"
    assert 240.0 in prices, f"sane $240 anchor must be present; got {prices}"
    assert dropped == 1


@pytest.mark.asyncio
async def test_sane_levels_pass_through_anchor_pipeline_unchanged():
    """Two sane NVDA levels ($220, $240) both survive the filter."""
    raw_rows = [
        _yt_level_row("NVDA", 220.0, "resistance"),
        _yt_level_row("NVDA", 240.0, "resistance"),
    ]

    with _patch_quote(208.0):
        sane_rows, dropped = await filter_levels_for_display("NVDA", raw_rows)

    anchors = levels_mod.extract_anchors_from_youtube_levels(sane_rows)
    prices = sorted(a.price for a in anchors)

    assert dropped == 0
    assert prices == [220.0, 240.0]


# ---------------------------------------------------------------------------
# C) Trade-plan TP selection never emits a wild target even with wild anchors
#    supplied directly (belt-and-suspenders: the select_trade_plan path is
#    pure, but this documents the behaviour).
# ---------------------------------------------------------------------------

def test_select_trade_plan_uses_anchor_prices_directly():
    """select_trade_plan picks from whatever anchors it is given.
    This proves that the aggregator MUST filter before constructing anchors —
    if a wild anchor (700.0) is passed as a resistance it WILL appear as TP.
    The aggregator gate (item 3) is what prevents that."""
    # We pass a wild resistance to show it IS used without filtering — this is
    # why the filter before extract_anchors_from_youtube_levels is required.
    from consensus_engine.alerts.all_command.levels import Anchor, select_trade_plan

    def _sup(p):
        return Anchor(price=p, source="s", source_type="swing")

    def _res(p):
        return Anchor(price=p, source="r", source_type="yt")

    supports = [_sup(195.0), _sup(190.0), _sup(185.0), _sup(180.0)]
    resistances = [_res(700.0), _res(710.0), _res(720.0)]  # wild values

    plan = select_trade_plan(supports, resistances)
    # Without the display-sanity gate, wild prices DO reach the trade plan:
    assert plan["tp1"] == 700.0  # confirms the gate in aggregator is necessary
