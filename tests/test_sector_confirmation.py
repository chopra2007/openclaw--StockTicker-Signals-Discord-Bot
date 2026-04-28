"""Tests for A4: sector ETF peer-confirmation gate (spec §8.2)."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine.analysis.sector_confirmation import (
    SectorVerdict,
    check_sector_alignment,
)


# ---------------------------------------------------------------------------
# Helper: market-hours datetime (Wednesday 10:00 ET = 14:00 UTC)
# ---------------------------------------------------------------------------

_MARKET_HOURS_UTC = datetime(2026, 4, 29, 14, 0, tzinfo=timezone.utc)  # Wed 10:00 ET


# ---------------------------------------------------------------------------
# (a) aligned passes: ETF moved in same direction -> verdict.aligned=True
# ---------------------------------------------------------------------------

async def test_aligned_long_passes():
    """ETF moved up for a long signal -> aligned=True."""
    with patch(
        "consensus_engine.analysis.sector_confirmation.cfg.get",
        side_effect=lambda k, d=None: True if k == "features.sector_confirmation.enabled" else d,
    ), patch(
        "consensus_engine.analysis.sector_confirmation._fetch_etf_change_pct",
        new=AsyncMock(return_value=1.5),
    ), patch(
        "consensus_engine.analysis.sector_confirmation._load_sector_map",
        return_value={"AAPL": "XLK"},
    ):
        verdict = await check_sector_alignment("AAPL", "long", "Technical Breakout", _MARKET_HOURS_UTC)

    assert verdict.aligned is True
    assert verdict.reason == "aligned"
    assert verdict.sector_etf == "XLK"
    assert verdict.sector_change_pct == 1.5
    assert verdict.bypass_due_to_catalyst is False
    assert verdict.bypass_due_to_unknown is False
    assert verdict.bypass_due_to_premarket is False
    assert verdict.bypass_due_to_unmapped is False


# ---------------------------------------------------------------------------
# (b) catalyst bypass list: catalyst_type="M&A" -> bypass_due_to_catalyst=True
# ---------------------------------------------------------------------------

async def test_bypass_catalyst_ma():
    """catalyst_type='M&A' -> bypass_due_to_catalyst=True regardless of ETF."""
    with patch(
        "consensus_engine.analysis.sector_confirmation.cfg.get",
        side_effect=lambda k, d=None: True if k == "features.sector_confirmation.enabled" else d,
    ):
        verdict = await check_sector_alignment("AAPL", "long", "M&A", _MARKET_HOURS_UTC)

    assert verdict.bypass_due_to_catalyst is True
    assert verdict.reason == "bypass_catalyst"
    assert verdict.aligned is False


# ---------------------------------------------------------------------------
# (c) unknown catalyst bypass: empty catalyst_type or "Market Movement"
# ---------------------------------------------------------------------------

async def test_bypass_unknown_empty_catalyst():
    """Empty catalyst_type -> bypass_due_to_unknown=True."""
    with patch(
        "consensus_engine.analysis.sector_confirmation.cfg.get",
        side_effect=lambda k, d=None: True if k == "features.sector_confirmation.enabled" else d,
    ):
        verdict = await check_sector_alignment("AAPL", "long", "", _MARKET_HOURS_UTC)

    assert verdict.bypass_due_to_unknown is True
    assert verdict.reason == "bypass_unknown"


async def test_bypass_unknown_market_movement():
    """catalyst_type='Market Movement' -> bypass_due_to_unknown=True."""
    with patch(
        "consensus_engine.analysis.sector_confirmation.cfg.get",
        side_effect=lambda k, d=None: True if k == "features.sector_confirmation.enabled" else d,
    ):
        verdict = await check_sector_alignment("NVDA", "short", "Market Movement", _MARKET_HOURS_UTC)

    assert verdict.bypass_due_to_unknown is True
    assert verdict.reason == "bypass_unknown"


# ---------------------------------------------------------------------------
# (d) premarket bypass: now_utc before 09:35 ET -> bypass_due_to_premarket=True
# ---------------------------------------------------------------------------

async def test_bypass_premarket():
    """Before 09:35 ET -> bypass_due_to_premarket=True."""
    # 08:00 ET = 12:00 UTC
    premarket_utc = datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc)
    with patch(
        "consensus_engine.analysis.sector_confirmation.cfg.get",
        side_effect=lambda k, d=None: True if k == "features.sector_confirmation.enabled" else d,
    ):
        verdict = await check_sector_alignment("AAPL", "long", "Technical Breakout", premarket_utc)

    assert verdict.bypass_due_to_premarket is True
    assert verdict.reason == "bypass_premarket"


# ---------------------------------------------------------------------------
# (e) unmapped bypass: ticker not in sector_map -> bypass_due_to_unmapped=True
# ---------------------------------------------------------------------------

async def test_bypass_unmapped_ticker():
    """Ticker not in sector_map -> bypass_due_to_unmapped=True."""
    with patch(
        "consensus_engine.analysis.sector_confirmation.cfg.get",
        side_effect=lambda k, d=None: True if k == "features.sector_confirmation.enabled" else d,
    ), patch(
        "consensus_engine.analysis.sector_confirmation._load_sector_map",
        return_value={},
    ):
        verdict = await check_sector_alignment("UNKN", "long", "Technical Breakout", _MARKET_HOURS_UTC)

    assert verdict.bypass_due_to_unmapped is True
    assert verdict.reason == "bypass_unmapped"
    assert verdict.sector_etf is None


# ---------------------------------------------------------------------------
# (f) blocked path: ETF moved opposite direction, no bypass -> reason="blocked"
# ---------------------------------------------------------------------------

async def test_blocked_opposite_direction():
    """ETF moved down for a long signal, no bypass -> reason='blocked', aligned=False."""
    with patch(
        "consensus_engine.analysis.sector_confirmation.cfg.get",
        side_effect=lambda k, d=None: True if k == "features.sector_confirmation.enabled" else (0.3 if k == "features.sector_confirmation.sector_change_threshold_pct" else d),
    ), patch(
        "consensus_engine.analysis.sector_confirmation._fetch_etf_change_pct",
        new=AsyncMock(return_value=-1.2),
    ), patch(
        "consensus_engine.analysis.sector_confirmation._load_sector_map",
        return_value={"AAPL": "XLK"},
    ):
        verdict = await check_sector_alignment("AAPL", "long", "Technical Breakout", _MARKET_HOURS_UTC)

    assert verdict.aligned is False
    assert verdict.reason == "blocked"
    assert verdict.bypass_due_to_catalyst is False
    assert verdict.bypass_due_to_unknown is False
    assert verdict.bypass_due_to_premarket is False
    assert verdict.bypass_due_to_unmapped is False
    assert verdict.sector_etf == "XLK"
    assert verdict.sector_change_pct == -1.2
