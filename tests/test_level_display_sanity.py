"""Tests for the shared display-time level sanity gate (item C, deep-dive-2026-06-08)."""
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine.analysis.level_display_sanity import (
    LevelVerdict,
    classify_level,
    filter_levels_for_display,
    _INDEX_RANGE,
)


def _patch_quote(price):
    return patch(
        "consensus_engine.analysis.level_display_sanity.get_live_quote_price",
        new=AsyncMock(return_value=price),
    )


@pytest.mark.asyncio
async def test_drops_nvda_850_on_208_stock():
    # 850 / 208 = 4.09x >= 2.0 -> DROP
    assert await classify_level("NVDA", 850.0, live_price=208.0) is LevelVerdict.DROP


@pytest.mark.asyncio
async def test_keeps_30pct_above_real_level():
    # 270 / 208 = 1.30x, inside [0.5, 2.0) -> KEEP (proves we didn't over-tighten)
    assert await classify_level("NVDA", 270.0, live_price=208.0) is LevelVerdict.KEEP


@pytest.mark.asyncio
async def test_drops_half_or_below():
    # 100 / 208 = 0.48x <= 0.5 -> DROP
    assert await classify_level("NVDA", 100.0, live_price=208.0) is LevelVerdict.DROP
    # 120 / 208 = 0.577 -> KEEP
    assert await classify_level("NVDA", 120.0, live_price=208.0) is LevelVerdict.KEEP


@pytest.mark.asyncio
async def test_penny_exemption():
    # live $0.50, target $2 (4x) — penny names keep their multi-bagger targets
    assert await classify_level("ABCD", 2.0, live_price=0.50) is LevelVerdict.KEEP


@pytest.mark.asyncio
async def test_index_range_drops_smh_12616():
    # SMH has no resolvable quote here (None) -> _INDEX_RANGE (150-400) -> 12,616 DROP
    with _patch_quote(None):
        assert await classify_level("SMH", 12616.0) is LevelVerdict.DROP


@pytest.mark.asyncio
async def test_index_range_keeps_real_smh_level():
    with _patch_quote(None):
        assert await classify_level("SMH", 280.0) is LevelVerdict.KEEP


@pytest.mark.asyncio
async def test_index_range_drops_gold_21000():
    with _patch_quote(None):
        assert await classify_level("GOLD", 21000.0) is LevelVerdict.DROP


@pytest.mark.asyncio
async def test_equity_no_quote_fails_open_suspect():
    with _patch_quote(None):
        assert await classify_level("ZZZZ", 999.0) is LevelVerdict.SUSPECT


@pytest.mark.asyncio
async def test_btc_fails_open_above_band():
    # BTC is unbounded-upside: a value above the band ceiling but < 10x is KEPT
    with _patch_quote(None):
        assert await classify_level("BTC", 260000.0) is LevelVerdict.KEEP
        # absurd (>10x ceiling) still drops
        assert await classify_level("BTC", 9_000_000.0) is LevelVerdict.DROP


@pytest.mark.asyncio
async def test_filter_returns_kept_and_dropped_count():
    levels = [{"price": 850.0}, {"price": 270.0}, {"price": 100.0}]
    with _patch_quote(208.0):
        kept, dropped = await filter_levels_for_display("NVDA", levels)
    assert dropped == 2  # 850 and 100 dropped
    assert [l["price"] for l in kept] == [270.0]


def test_index_range_covers_all_scope_display_keys():
    """Coverage guard (BLOCKER-C-B1): every index/commodity scope wolf_news can display
    MUST have an _INDEX_RANGE band, else 'GOLD 21,000' prints like SMH 12,616 did. A future
    scope addition fails this test until a range is added."""
    from consensus_engine.alerts.wolf_news import _SCOPE_DISPLAY
    missing = set(_SCOPE_DISPLAY) - set(_INDEX_RANGE)
    assert not missing, f"_SCOPE_DISPLAY scopes missing an _INDEX_RANGE band: {missing}"
