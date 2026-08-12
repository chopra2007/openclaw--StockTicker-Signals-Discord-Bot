"""I2 (signal-features-2026-06-09) — weight analysts by track record.

Two layers under test:
  1. The NEW db helper `get_analyst_precision_lb` returns the WILSON LOWER BOUND
     of an analyst's accuracy (not the raw ratio) and None below the n-floor.
  2. The scoring term at cross_reference.py:483 sums 20*clamp(2*lb, floor, cap)
     per analyst behind `features.analyst_accuracy_weight.enabled`.

Flag OFF -> analyst_pts stays the flat min(len,3)*20 (byte-identical); the
existing `test_analyst_multiplier_capped` (flag off via conftest) proves that.
"""
import pytest
from unittest.mock import AsyncMock, patch

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.models import (
    ParsedTweet, TweetType, Direction, Conviction,
)
from consensus_engine.cross_reference import cross_reference
from consensus_engine.utils.xref_cache import clear_xref_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_xref_cache()
    yield
    clear_xref_cache()


async def _insert_perf(analyst: str, accuracy: float, n: int, horizon: str = "1h"):
    """Insert a source_performance row for (analyst, horizon)."""
    conn = await db.get_db()
    await conn.execute(
        """INSERT OR REPLACE INTO source_performance
           (entity_id, horizon, rolling_accuracy, sample_count, updated_at)
           VALUES (?, ?, ?, ?, 0.0)""",
        (analyst, horizon, accuracy, n),
    )
    await conn.commit()


# ── Layer 1: the Wilson lower-bound helper ─────────────────────────────────

@pytest.mark.asyncio
async def test_lb_below_min_n_returns_none():
    """A 3/5 record (n=5) is below min_n=10 -> None (caller uses neutral 20)."""
    await _insert_perf("thin_analyst", accuracy=0.60, n=5)
    lb = await db.get_analyst_precision_lb("thin_analyst", horizon="1h", min_n=10)
    assert lb is None


@pytest.mark.asyncio
async def test_lb_is_lower_bound_not_raw_ratio():
    """A 30/40 record: LB must be BELOW the raw 0.75 ratio (pessimistic bound)."""
    await _insert_perf("good_analyst", accuracy=0.75, n=40)
    lb = await db.get_analyst_precision_lb("good_analyst", horizon="1h", min_n=10)
    assert lb is not None
    assert lb < 0.75            # strictly below the raw ratio
    assert 0.55 < lb < 0.65     # Wilson LB of 30/40 ~ 0.598


@pytest.mark.asyncio
async def test_lb_chronic_loser_low():
    """A 5/40 chronic loser: LB well below 0.25 -> drives the discount floor."""
    await _insert_perf("loser_analyst", accuracy=0.125, n=40)
    lb = await db.get_analyst_precision_lb("loser_analyst", horizon="1h", min_n=10)
    assert lb is not None
    assert lb < 0.25


@pytest.mark.asyncio
async def test_lb_absent_analyst_returns_none():
    lb = await db.get_analyst_precision_lb("never_seen", horizon="1h", min_n=10)
    assert lb is None


# ── Layer 2: the flag-gated scoring term ───────────────────────────────────

def _force_flag_on(monkeypatch):
    """Force ONLY features.analyst_accuracy_weight.enabled True (rest default)."""
    real_get = cfg.get

    def _get(key, default=None):
        if key == "features.analyst_accuracy_weight.enabled":
            return True
        return real_get(key, default)

    monkeypatch.setattr(cfg, "get", _get)


def _tweet():
    return ParsedTweet(
        tweet_url="https://x.com/user/123",
        analyst="reporter",
        raw_text="$NVDA breaking out",
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["NVDA"],
        direction=Direction.LONG,
        options=None,
        conviction=Conviction.HIGH,
        summary="NVDA",
    )


async def _score_with_analysts(analysts, lb_map):
    """Run cross_reference with mocked sources + a mocked precision-LB lookup.

    lb_map maps analyst name -> Wilson LB (or None). All other sources empty.
    """
    async def _fake_lb(analyst, horizon="1h", min_n=10):
        return lb_map.get(analyst)

    with patch("consensus_engine.cross_reference.get_cached_xref",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.cross_reference.cache_xref",
               new_callable=AsyncMock), \
         patch("consensus_engine.cross_reference._run_news_cascade",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.cross_reference._run_sec_check",
               new_callable=AsyncMock, return_value=(False, "")), \
         patch("consensus_engine.cross_reference._run_social_check",
               new_callable=AsyncMock, return_value={}), \
         patch("consensus_engine.cross_reference._run_technical",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.cross_reference._run_other_analysts",
               new_callable=AsyncMock, return_value=analysts), \
         patch("consensus_engine.cross_reference._run_llm_score",
               new_callable=AsyncMock, return_value=(0.0, "")), \
         patch("consensus_engine.cross_reference._run_options_check",
               new_callable=AsyncMock, return_value=None), \
         patch.object(db, "get_analyst_precision_lb", new=_fake_lb):
        return await cross_reference("NVDA", _tweet())


@pytest.mark.asyncio
async def test_flag_on_thin_record_stays_neutral_20(monkeypatch):
    """A 3/5 record is below min_n -> helper returns None -> neutral weight 1.0 -> 20."""
    _force_flag_on(monkeypatch)
    result = await _score_with_analysts(
        {"aligned": ["thin"], "opposing": []}, {"thin": None}
    )
    assert result.breakdown.additional_analysts == 20


@pytest.mark.asyncio
async def test_flag_on_high_record_lifted(monkeypatch):
    """A 30/40 high record (Wilson LB ~0.598) lifts above the flat 20."""
    _force_flag_on(monkeypatch)
    result = await _score_with_analysts(
        {"aligned": ["good"], "opposing": []}, {"good": 0.598}
    )
    # 20 * clamp(2*0.598, 0.5, 1.5) = 20 * 1.196 = 23.9 -> round 24
    assert result.breakdown.additional_analysts == 24
    assert result.breakdown.additional_analysts > 20


@pytest.mark.asyncio
async def test_flag_on_chronic_loser_floored(monkeypatch):
    """A 5/40 chronic loser (Wilson LB ~0.055) floors the weight at 0.5x -> 10."""
    _force_flag_on(monkeypatch)
    result = await _score_with_analysts(
        {"aligned": ["loser"], "opposing": []}, {"loser": 0.055}
    )
    # 20 * clamp(2*0.055, 0.5, 1.5) = 20 * 0.5 = 10
    assert result.breakdown.additional_analysts == 10


@pytest.mark.asyncio
async def test_flag_on_uplift_notional_cap(monkeypatch):
    """3 max-weight analysts can't run away: capped at flat(60) + uplift_cap(20) = 80."""
    _force_flag_on(monkeypatch)
    # 3 analysts each weight 1.5 -> 90 raw, but capped to 60 + 20 = 80
    result = await _score_with_analysts(
        {"aligned": ["a", "b", "c"], "opposing": []},
        {"a": 0.9, "b": 0.9, "c": 0.9},
    )
    assert result.breakdown.additional_analysts == 80


@pytest.mark.asyncio
async def test_flag_off_flat_60_for_three(monkeypatch):
    """Flag OFF (conftest force-off) -> 3 analysts score the flat 3*20 = 60."""
    # No _force_flag_on: conftest keeps features.analyst_accuracy_weight.enabled False.
    result = await _score_with_analysts(
        {"aligned": ["a", "b", "c"], "opposing": []},
        {"a": 0.9, "b": 0.9, "c": 0.9},
    )
    assert result.breakdown.additional_analysts == 60


@pytest.mark.asyncio
async def test_unsigned_legacy_analyst_list_adds_zero_agreement(monkeypatch):
    _force_flag_on(monkeypatch)

    result = await _score_with_analysts(["unsigned"], {"unsigned": 0.9})

    assert result.breakdown.additional_analysts == 0
    assert result.other_analysts == []


@pytest.mark.asyncio
async def test_same_analyst_conflicting_directions_has_no_net_agreement_when_weighted(monkeypatch):
    _force_flag_on(monkeypatch)

    result = await _score_with_analysts(
        {"aligned": [], "opposing": ["conflicted"]},
        {"conflicted": 0.9},
    )

    assert result.breakdown.additional_analysts <= 0
    assert result.n_opposing >= 1
