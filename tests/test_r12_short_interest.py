"""r12 (standalone-scanners) — FINRA settlement short-interest + days-to-cover.

Tests:
  1. PARSER — good CSV, malformed rows skipped, ticker filter, dtype-pin.
  2. Domain / URL validation (api.finra.org only).
  3. days-to-cover score-leg math — elevated+rising -> cap; below-min -> 0;
     not-rising -> 0; short direction -> 0; stale row -> 0.
  4. DB round-trip — upsert / get_latest / history.
  5. score_ticker integration: flag OFF -> no DB read + days_to_cover=0 +
     byte-identical breakdown (no new key); flag ON -> days_to_cover=cap.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine import config as cfg
from consensus_engine.scanners import finra_short_interest as fsi
from consensus_engine.scanners.finra_short_interest import (
    _parse_short_interest_csv,
    _validate_url,
    FINRA_SHORT_INTEREST_PROVENANCE,
)
from consensus_engine.cross_reference import (
    _compute_days_to_cover_pts,
    _compute_squeeze_risk_pts,
    score_ticker,
)
from consensus_engine.utils.xref_cache import clear_xref_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_xref_cache()
    yield
    clear_xref_cache()


_HEADER = ('"accountingYearMonthNumber","symbolCode","issueName",'
           '"issuerServicesGroupExchangeCode","marketClassCode",'
           '"currentShortPositionQuantity","previousShortPositionQuantity",'
           '"stockSplitFlag","averageDailyVolumeQuantity","daysToCoverQuantity",'
           '"revisionFlag","changePercent","changePreviousNumber","settlementDate"')

_SAMPLE = _HEADER + "\n" + "\n".join([
    '"20260615","NVDA","NVIDIA","R","NNM","299666309","284722716",,"167960279","1.78",,"5.25","14943593","2026-06-15"',
    '"20260615","AMD","AMD","R","NNM","40000000","38000000",,"20000000","2.00",,"5.26","2000000","2026-06-15"',
])

_MALFORMED = _HEADER + "\n" + "\n".join([
    '"20260615","NVDA","NVIDIA","R","NNM","299666309","284722716",,"167960279","1.78",,"5.25","14943593","2026-06-15"',
    '"20260615","BAD","Bad Co","R","NNM","not_a_number","1",,"1","1.0",,"0","0","2026-06-15"',
])


# --------------------------------------------------------------------------- #
# 1. PARSER
# --------------------------------------------------------------------------- #

def test_parser_good_csv():
    rows = _parse_short_interest_csv(_SAMPLE)
    assert len(rows) == 2
    nvda = next(r for r in rows if r["symbol"] == "NVDA")
    assert nvda["short_interest"] == 299_666_309
    assert nvda["avg_daily_volume"] == 167_960_279
    assert nvda["days_to_cover"] == 1.78
    assert nvda["prev_short_interest"] == 284_722_716
    assert nvda["pct_change"] == 5.25
    assert nvda["settlement_date"] == "2026-06-15"


def test_parser_malformed_short_interest_skipped():
    rows = _parse_short_interest_csv(_MALFORMED)
    syms = {r["symbol"] for r in rows}
    assert "NVDA" in syms
    assert "BAD" not in syms  # non-numeric required column skipped


def test_parser_ticker_filter():
    rows = _parse_short_interest_csv(_SAMPLE, tickers={"NVDA"})
    assert [r["symbol"] for r in rows] == ["NVDA"]


def test_parser_empty():
    assert _parse_short_interest_csv("") == []


def test_provenance_label_constant():
    assert FINRA_SHORT_INTEREST_PROVENANCE == "settlement short interest (FINRA, twice-monthly)"


# --------------------------------------------------------------------------- #
# 2. Domain validation
# --------------------------------------------------------------------------- #

def test_validate_url_good():
    assert _validate_url("https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest") is True


def test_validate_url_wrong_domain():
    assert _validate_url("https://evil.com/x") is False
    assert _validate_url("https://cdn.finra.org/x") is False  # different host than the API


# --------------------------------------------------------------------------- #
# 3. days-to-cover score-leg math
# --------------------------------------------------------------------------- #

def _row(**kw):
    base = {"days_to_cover": 4.0, "pct_change": 5.0, "published_at": time.time()}
    base.update(kw)
    return base


def test_dtc_elevated_and_rising_gives_cap():
    pts = _compute_days_to_cover_pts(_row(), direction="long")
    assert pts == 3  # default term_cap


def test_dtc_below_min_gives_zero():
    pts = _compute_days_to_cover_pts(_row(days_to_cover=1.0), direction="long")
    assert pts == 0


def test_dtc_not_rising_gives_zero():
    pts = _compute_days_to_cover_pts(_row(pct_change=-1.0), direction="long")
    assert pts == 0


def test_dtc_short_direction_gives_zero():
    pts = _compute_days_to_cover_pts(_row(), direction="short")
    assert pts == 0


def test_dtc_stale_row_gives_zero():
    stale = _row(published_at=time.time() - 40 * 86400)  # 40d > 30d cap
    assert _compute_days_to_cover_pts(stale, direction="long") == 0


def test_dtc_missing_dtc_gives_zero():
    assert _compute_days_to_cover_pts(_row(days_to_cover=None), direction="long") == 0


# --------------------------------------------------------------------------- #
# 4. DB round-trip
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_db_roundtrip():
    import consensus_engine.db as db_mod
    db_mod.DB_PATH = ":memory:"
    db_mod._db = None
    await db_mod.init_db()

    await db_mod.upsert_finra_short_interest("NVDA", "2026-06-15", 299_666_309, 167_960_279, 1.78, 284_722_716, 5.25)
    await db_mod.upsert_finra_short_interest("NVDA", "2026-05-29", 284_722_716, 180_147_142, 1.58, 296_966_425, -4.12)

    latest = await db_mod.get_latest_finra_short_interest("NVDA")
    assert latest["settlement_date"] == "2026-06-15"
    assert latest["days_to_cover"] == 1.78

    hist = await db_mod.get_finra_short_interest_history("NVDA")
    assert len(hist) == 2
    assert hist[0]["settlement_date"] == "2026-06-15"  # newest first

    assert await db_mod.get_latest_finra_short_interest("ZZZZ") is None
    db_mod._db = None
    db_mod.DB_PATH = None


# --------------------------------------------------------------------------- #
# 5. score_ticker integration
# --------------------------------------------------------------------------- #

from consensus_engine.analysis.consolidation import ConsolidationResult as _CR
from consensus_engine.models import CatalystResult

_FAKE_CONS = _CR(fired=False, consolidated_id=None, effective_n_clusters=0,
                 combined_log_odds=0.0, consensus_boost=0, sources_seen=[], reason="disabled")


def _patch_fetchers():
    cat = CatalystResult(ticker="NVDA", catalyst_summary="", catalyst_type="", news_sources=[], catalyst_body="")
    return (
        patch("consensus_engine.cross_reference._run_news_cascade", new=AsyncMock(return_value=cat)),
        patch("consensus_engine.cross_reference._run_sec_check", new=AsyncMock(return_value=(False, ""))),
        patch("consensus_engine.cross_reference._run_social_check", new=AsyncMock(return_value={"apewisdom": 0, "stocktwits": 0, "reddit": 0, "google_trends": 0})),
        patch("consensus_engine.cross_reference._run_technical", new=AsyncMock(return_value=None)),
        patch("consensus_engine.cross_reference._run_other_analysts", new=AsyncMock(return_value=[])),
        patch("consensus_engine.cross_reference._run_options_check", new=AsyncMock(return_value=None)),
        patch("consensus_engine.cross_reference._get_youtube_context", new=AsyncMock(return_value=None)),
    )


def _flag(monkeypatch, overrides):
    real = cfg.get
    monkeypatch.setattr(cfg, "get", lambda k, d=None: overrides[k] if k in overrides else real(k, d))


@pytest.mark.asyncio
async def test_score_ticker_flag_off_no_db_read(monkeypatch):
    _flag(monkeypatch, {"features.short_interest.enabled": False})
    calls: list[str] = []
    with contextlib.ExitStack() as stack:
        for p in _patch_fetchers():
            stack.enter_context(p)
        mdb = stack.enter_context(patch("consensus_engine.cross_reference.db"))
        stack.enter_context(patch("consensus_engine.analysis.consolidation.consolidate_for_ticker", new=AsyncMock(return_value=_FAKE_CONS)))
        stack.enter_context(patch("consensus_engine.cross_reference._run_llm_score", new_callable=AsyncMock, return_value=(0, "")))
        mdb.get_signal_counts_by_source = AsyncMock(return_value={})
        mdb.get_analyst_precision_lb = AsyncMock(return_value=None)
        mdb.get_latest_finra_short_interest = AsyncMock(side_effect=lambda t: calls.append("si") or None)
        result = await score_ticker("NVDA", base_score=30, direction="long")
    assert result.breakdown.days_to_cover == 0
    assert not calls, "Flag OFF -> no short-interest DB read on the hot path"


@pytest.mark.asyncio
async def test_score_ticker_flag_on_elevated(monkeypatch):
    _flag(monkeypatch, {"features.short_interest.enabled": True})
    with contextlib.ExitStack() as stack:
        for p in _patch_fetchers():
            stack.enter_context(p)
        mdb = stack.enter_context(patch("consensus_engine.cross_reference.db"))
        stack.enter_context(patch("consensus_engine.analysis.consolidation.consolidate_for_ticker", new=AsyncMock(return_value=_FAKE_CONS)))
        stack.enter_context(patch("consensus_engine.cross_reference._run_llm_score", new_callable=AsyncMock, return_value=(0, "")))
        mdb.get_signal_counts_by_source = AsyncMock(return_value={})
        mdb.get_analyst_precision_lb = AsyncMock(return_value=None)
        mdb.get_latest_finra_short_interest = AsyncMock(return_value={
            "ticker": "NVDA", "settlement_date": "2026-06-15", "short_interest": 3, "avg_daily_volume": 1,
            "days_to_cover": 4.5, "prev_short_interest": 2, "pct_change": 5.0, "published_at": time.time(),
        })
        result = await score_ticker("NVDA", base_score=30, direction="long")
    assert result.breakdown.days_to_cover == 3


# --------------------------------------------------------------------------- #
# 7. F7 (c102) — short-alert squeeze-risk guard
# --------------------------------------------------------------------------- #

def test_squeeze_short_elevated_rising_gives_negative_cap():
    # SHORT signal + crowded, rising short -> DEMOTE (negative penalty_cap)
    assert _compute_squeeze_risk_pts(_row(), direction="short") == -4


def test_squeeze_long_direction_gives_zero():
    # A crowded short is confluence FOR a long (r12), never the guard
    assert _compute_squeeze_risk_pts(_row(), direction="long") == 0


def test_squeeze_below_min_gives_zero():
    assert _compute_squeeze_risk_pts(_row(days_to_cover=1.0), direction="short") == 0


def test_squeeze_not_rising_gives_zero():
    assert _compute_squeeze_risk_pts(_row(pct_change=-1.0), direction="short") == 0


def test_squeeze_stale_row_gives_zero():
    stale = _row(published_at=time.time() - 40 * 86400)
    assert _compute_squeeze_risk_pts(stale, direction="short") == 0


def test_squeeze_missing_dtc_gives_zero():
    assert _compute_squeeze_risk_pts(_row(days_to_cover=None), direction="short") == 0


async def _score_with_flags(overrides, direction, si_row):
    """Run score_ticker with the short-interest DB read mocked; return
    (breakdown, list-of-DB-read-calls)."""
    calls: list[str] = []
    with contextlib.ExitStack() as stack:
        for p in _patch_fetchers():
            stack.enter_context(p)
        real = cfg.get
        stack.enter_context(patch.object(
            cfg, "get",
            lambda k, d=None: overrides[k] if k in overrides else real(k, d)))
        mdb = stack.enter_context(patch("consensus_engine.cross_reference.db"))
        stack.enter_context(patch(
            "consensus_engine.analysis.consolidation.consolidate_for_ticker",
            new=AsyncMock(return_value=_FAKE_CONS)))
        stack.enter_context(patch(
            "consensus_engine.cross_reference._run_llm_score",
            new_callable=AsyncMock, return_value=(0, "")))
        mdb.get_signal_counts_by_source = AsyncMock(return_value={})
        mdb.get_analyst_precision_lb = AsyncMock(return_value=None)

        def _read(t):
            calls.append("si")
            return si_row

        mdb.get_latest_finra_short_interest = AsyncMock(side_effect=_read)
        result = await score_ticker("NVDA", base_score=30, direction=direction)
    return result.breakdown, calls


_CROWDED_RISING = {
    "ticker": "NVDA", "settlement_date": "2026-06-15", "short_interest": 3, "avg_daily_volume": 1,
    "days_to_cover": 4.5, "prev_short_interest": 2, "pct_change": 5.0,
}


@pytest.mark.asyncio
async def test_guard_on_short_demotes(monkeypatch):
    bd, calls = await _score_with_flags(
        {"features.short_interest.enabled": False, "features.short_squeeze_guard.enabled": True},
        direction="short", si_row=dict(_CROWDED_RISING, published_at=time.time()))
    assert bd.squeeze_risk == -4
    assert bd.days_to_cover == 0, "bullish r12 leg stays 0 when only the guard flag is on"
    assert calls == ["si"], "exactly ONE short-interest DB read is shared between both legs"


@pytest.mark.asyncio
async def test_guard_on_long_is_zero(monkeypatch):
    bd, _ = await _score_with_flags(
        {"features.short_interest.enabled": False, "features.short_squeeze_guard.enabled": True},
        direction="long", si_row=dict(_CROWDED_RISING, published_at=time.time()))
    assert bd.squeeze_risk == 0, "guard never fires on a long signal"


@pytest.mark.asyncio
async def test_guard_off_no_extra_read_and_byte_identical(monkeypatch):
    # Both flags OFF -> zero DB reads, squeeze_risk 0 (byte-identical to today).
    bd, calls = await _score_with_flags(
        {"features.short_interest.enabled": False, "features.short_squeeze_guard.enabled": False},
        direction="short", si_row=dict(_CROWDED_RISING, published_at=time.time()))
    assert bd.squeeze_risk == 0
    assert bd.days_to_cover == 0
    assert not calls, "both flags off -> no short-interest read on the hot path"


@pytest.mark.asyncio
async def test_guard_and_r12_both_on_share_one_read(monkeypatch):
    # LONG signal, both flags on: r12 adds +3, guard stays 0 (long), ONE read.
    bd, calls = await _score_with_flags(
        {"features.short_interest.enabled": True, "features.short_squeeze_guard.enabled": True},
        direction="long", si_row=dict(_CROWDED_RISING, published_at=time.time()))
    assert bd.days_to_cover == 3
    assert bd.squeeze_risk == 0
    assert calls == ["si"], "both legs read the SAME row via one DB call"


# --------------------------------------------------------------------------- #
# 6. SHADOW-SOAK split: collect (loop ingests) vs enabled (score leg)
# --------------------------------------------------------------------------- #

class _OneShotStop:
    """Stop-event stub that lets finra_short_interest_loop run EXACTLY one iteration:
    the while-guard is False on the first check, then True. wait() returns at once so
    the loop never blocks on the real interval."""
    def __init__(self):
        self._checks = 0

    def is_set(self) -> bool:
        self._checks += 1
        return self._checks > 1

    async def wait(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_loop_ingests_when_collect_true_enabled_off(monkeypatch):
    """collect:true, enabled:false -> the loop condition is TRUE, so ingest runs
    (shadow-fills the table) even though the score leg stays OFF."""
    _flag(monkeypatch, {"features.short_interest.enabled": False,
                        "features.short_interest.collect": True})
    calls = {"n": 0}

    async def _fake_ingest(*a, **k):
        calls["n"] += 1
        return 0

    monkeypatch.setattr(fsi, "ingest_short_interest", _fake_ingest)
    await fsi.finra_short_interest_loop(_OneShotStop())
    assert calls["n"] == 1, "collect:true must make the loop ingest"


@pytest.mark.asyncio
async def test_loop_skips_when_collect_and_enabled_both_off(monkeypatch):
    """collect:false, enabled:false -> the loop condition is FALSE, so ingest is
    never called (dormant, no table writes)."""
    _flag(monkeypatch, {"features.short_interest.enabled": False,
                        "features.short_interest.collect": False})
    calls = {"n": 0}

    async def _fake_ingest(*a, **k):
        calls["n"] += 1
        return 0

    monkeypatch.setattr(fsi, "ingest_short_interest", _fake_ingest)
    await fsi.finra_short_interest_loop(_OneShotStop())
    assert calls["n"] == 0, "both flags off must keep the loop dormant"


@pytest.mark.asyncio
async def test_collect_on_enabled_off_breakdown_byte_identical(monkeypatch):
    """SCORE leg stays gated on .enabled ONLY: with enabled:false, flipping collect on
    must NOT read the short-interest table on the hot path and must leave the FULL
    ScoreBreakdown byte-identical vs collect:false. Proves the soak changes no live score."""
    async def _run(overrides):
        calls: list[str] = []
        with contextlib.ExitStack() as stack:
            for p in _patch_fetchers():
                stack.enter_context(p)
            real = cfg.get
            stack.enter_context(patch.object(
                cfg, "get",
                lambda k, d=None: overrides[k] if k in overrides else real(k, d)))
            mdb = stack.enter_context(patch("consensus_engine.cross_reference.db"))
            stack.enter_context(patch(
                "consensus_engine.analysis.consolidation.consolidate_for_ticker",
                new=AsyncMock(return_value=_FAKE_CONS)))
            stack.enter_context(patch(
                "consensus_engine.cross_reference._run_llm_score",
                new_callable=AsyncMock, return_value=(0, "")))
            mdb.get_signal_counts_by_source = AsyncMock(return_value={})
            mdb.get_analyst_precision_lb = AsyncMock(return_value=None)
            mdb.get_latest_finra_short_interest = AsyncMock(
                side_effect=lambda t: calls.append("si") or None)
            result = await score_ticker("NVDA", base_score=30, direction="long")
        return result.breakdown, calls

    bd_off, calls_off = await _run({"features.short_interest.enabled": False,
                                    "features.short_interest.collect": False})
    bd_collect, calls_collect = await _run({"features.short_interest.enabled": False,
                                            "features.short_interest.collect": True})

    assert bd_collect.days_to_cover == 0
    assert not calls_collect, "collect-on/enabled-off must still skip the score-path DB read"
    assert not calls_off
    assert bd_off == bd_collect, "collect flag must leave the breakdown byte-identical"
