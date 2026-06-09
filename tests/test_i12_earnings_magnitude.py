"""I12 (signal-features-2026-06-09) — magnitude-scaled earnings beat/miss.

Today a +40% blowout beat and an in-line print score the SAME catalyst tier
(`news_pts = _get_catalyst_score(catalyst_type)`). Behind
`features.earnings_magnitude.enabled` the scorer adds, ON TOP of that base tier:

    +per_10pct (5) per 10% surprise, capped at cap (+15)

Mandatory safeguards asserted here:
  - absolute-$ surprise floor + sane-denominator guard: a $0.01 beat on a
    $0.001 estimate (near-zero surprise % AND trivial denominator) adds 0
  - cap: a +40% surprise adds +15 (3 * 5 = 15, capped), not +20
  - freshness gate: a stale recap (period older than recency_days) adds 0
  - missing surprise % -> base tier only
  - flag OFF -> base tier byte-identical (no bonus)

The wiring prerequisite is also covered: the recap's numeric surprise % +
estimate + period are threaded onto CatalystResult by news._search_recent_earnings
and reach the scorer at cross_reference.py.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine import config as cfg
from consensus_engine.models import CatalystResult
from consensus_engine.cross_reference import (
    _earnings_magnitude_bonus,
    _get_catalyst_score,
    score_ticker,
)
from consensus_engine.scanners import earnings_calendar, news
from consensus_engine.utils.xref_cache import clear_xref_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_xref_cache()
    yield
    clear_xref_cache()


_FRESH = datetime.now(timezone.utc).strftime("%Y-%m-%d")
_STALE = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")


def _flag_on(monkeypatch):
    """Force ONLY features.earnings_magnitude.enabled ON; all else default."""
    real_get = cfg.get
    monkeypatch.setattr(
        cfg, "get",
        lambda k, d=None: True if k == "features.earnings_magnitude.enabled"
        else real_get(k, d),
    )


def _earn_catalyst(*, surprise, estimate, period, catalyst_type="Earnings Report"):
    """A passing Earnings CatalystResult carrying the numeric I12 fields."""
    return CatalystResult(
        ticker="NVDA",
        catalyst_summary="NVDA reported earnings",
        catalyst_type=catalyst_type,
        news_sources=["finnhub.io"],
        source_urls=["https://finnhub.io/api/v1/stock/earnings"],
        confidence=0.8,
        catalyst_body="NVDA reported earnings.",
        eps_surprise_pct=surprise,
        eps_estimate=estimate,
        eps_period=period,
    )


# ── Layer 0: wiring prerequisite — fields reach the catalyst ───────────────

@pytest.mark.asyncio
async def test_recap_threads_numeric_fields_onto_catalyst(monkeypatch):
    """_search_recent_earnings must populate eps_surprise_pct/estimate/period."""
    async def _stub(*_a, **_kw):
        return {
            "period": "2026-01-31",
            "eps_actual": 5.16, "eps_estimate": 4.60, "eps_surprise_pct": 12.17,
            "revenue_actual": 68132000000, "revenue_yoy_pct": 73.2,
        }
    monkeypatch.setattr(earnings_calendar, "fetch_recent_earnings_for_ticker", _stub)
    result = await news._search_recent_earnings("NVDA")
    assert result is not None
    assert result.eps_surprise_pct == pytest.approx(12.17)
    assert result.eps_estimate == pytest.approx(4.60)
    assert result.eps_period == "2026-01-31"


def test_other_catalysts_leave_eps_fields_default():
    """A non-earnings catalyst built via _build_catalyst has no eps numbers."""
    c = news._build_catalyst("NVDA", "FDA approves drug", "https://x.com", "FDA Approval")
    assert c.eps_surprise_pct is None
    assert c.eps_estimate is None
    assert c.eps_period == ""


# ── Layer 1: pure helper ───────────────────────────────────────────────────

def test_bonus_plus40_surprise_caps_at_15():
    # +40% surprise -> 40/10 * 5 = 20 -> capped at +15.
    c = _earn_catalyst(surprise=40.0, estimate=4.60, period=_FRESH)
    assert _earnings_magnitude_bonus(c) == 15


def test_bonus_plus20_surprise_is_10():
    c = _earn_catalyst(surprise=20.0, estimate=4.60, period=_FRESH)
    assert _earnings_magnitude_bonus(c) == 10


def test_bonus_near_zero_beat_on_tiny_estimate_is_0():
    # $0.01 beat on a $0.001 estimate would be a +900% surprise; the
    # denominator + magnitude guards must block it -> 0.
    c = _earn_catalyst(surprise=900.0, estimate=0.001, period=_FRESH)
    assert _earnings_magnitude_bonus(c) == 0


def test_bonus_tiny_surprise_pct_is_0():
    # A 1% surprise is below the absolute floor (min_abs_eps 0.02 => 2%).
    c = _earn_catalyst(surprise=1.0, estimate=4.60, period=_FRESH)
    assert _earnings_magnitude_bonus(c) == 0


def test_bonus_stale_recap_is_0():
    c = _earn_catalyst(surprise=40.0, estimate=4.60, period=_STALE)
    assert _earnings_magnitude_bonus(c) == 0


def test_bonus_missing_surprise_is_0():
    c = _earn_catalyst(surprise=None, estimate=4.60, period=_FRESH)
    assert _earnings_magnitude_bonus(c) == 0


def test_bonus_missing_estimate_is_0():
    c = _earn_catalyst(surprise=40.0, estimate=None, period=_FRESH)
    assert _earnings_magnitude_bonus(c) == 0


# ── Layer 2: full score_ticker path ────────────────────────────────────────

async def _news_pts_via_score(catalyst) -> int:
    with patch("consensus_engine.cross_reference._run_news_cascade",
               new=AsyncMock(return_value=catalyst)), \
         patch("consensus_engine.cross_reference._run_sec_check",
               new=AsyncMock(return_value=(False, ""))), \
         patch("consensus_engine.cross_reference._run_social_check",
               new=AsyncMock(return_value={})), \
         patch("consensus_engine.cross_reference._run_technical",
               new=AsyncMock(return_value=None)), \
         patch("consensus_engine.cross_reference._run_other_analysts",
               new=AsyncMock(return_value=[])), \
         patch("consensus_engine.cross_reference._run_options_check",
               new=AsyncMock(return_value=None)), \
         patch("consensus_engine.cross_reference._get_youtube_context",
               new=AsyncMock(return_value=None)), \
         patch("consensus_engine.cross_reference._run_llm_score",
               new=AsyncMock(return_value=(0.0, ""))):
        result = await score_ticker("NVDA", base_score=0)
    return result.breakdown.news_catalyst


@pytest.mark.asyncio
async def test_score_plus40_surprise_adds_15(monkeypatch):
    _flag_on(monkeypatch)
    base = _get_catalyst_score("Earnings Report")
    c = _earn_catalyst(surprise=40.0, estimate=4.60, period=_FRESH)
    assert await _news_pts_via_score(c) == base + 15


@pytest.mark.asyncio
async def test_score_near_zero_beat_adds_0(monkeypatch):
    _flag_on(monkeypatch)
    base = _get_catalyst_score("Earnings Report")
    c = _earn_catalyst(surprise=900.0, estimate=0.001, period=_FRESH)
    assert await _news_pts_via_score(c) == base   # no bonus


@pytest.mark.asyncio
async def test_score_stale_recap_adds_0(monkeypatch):
    _flag_on(monkeypatch)
    base = _get_catalyst_score("Earnings Report")
    c = _earn_catalyst(surprise=40.0, estimate=4.60, period=_STALE)
    assert await _news_pts_via_score(c) == base   # freshness gate skips bonus


# ── Layer 3: flag OFF is byte-identical (base tier, no bonus) ──────────────

@pytest.mark.asyncio
async def test_score_flag_off_is_base_tier():
    # No _flag_on -> conftest force-off keeps the feature dark.
    base = _get_catalyst_score("Earnings Report")
    c = _earn_catalyst(surprise=40.0, estimate=4.60, period=_FRESH)
    assert await _news_pts_via_score(c) == base   # base tier, no magnitude add
