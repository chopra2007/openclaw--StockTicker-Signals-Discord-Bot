"""r17 (standalone-scanners) — post-earnings-announcement drift (PEAD).

Tests:
  1. classify_pead — drift-consistent / faded / reversed.
  2. Mutual exclusion with earnings_magnitude: SILENT inside the 5-day window;
     active on day 5; silent past max horizon; boundary checks.
  3. Missing / tiny surprise -> None.
  4. _compute_pead_pts score-leg — consistent+long -> cap; faded/reversed -> 0;
     direction mismatch -> 0; None -> 0.
  5. Descriptive render (_format_pead).
  6. score_ticker flag OFF -> no compute + pead=0.
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine import config as cfg
from consensus_engine.analysis.pead import classify_pead
from consensus_engine.cross_reference import _compute_pead_pts, score_ticker
from consensus_engine.alerts.all_command.embed import _format_pead
from consensus_engine.utils.xref_cache import clear_xref_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_xref_cache()
    yield
    clear_xref_cache()


_NOW = datetime(2026, 7, 8, tzinfo=timezone.utc)


def _closes(start_iso: str, days: int, jump_on: str | None, jump_pct: float):
    """Build a chronological (date, close) series; step price by jump_pct on jump_on."""
    out = []
    d0 = datetime.strptime(start_iso, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    px = 100.0
    jumped = False
    for i in range(days):
        d = (d0 + timedelta(days=i)).date().isoformat()
        if jump_on and d >= jump_on and not jumped:
            px = px * (1 + jump_pct / 100.0)
            jumped = True
        out.append((d, round(px, 2)))
    return out


# --------------------------------------------------------------------------- #
# 1 + 2. classification + mutual-exclusion boundary
# --------------------------------------------------------------------------- #

def test_drift_consistent_long():
    # flat at the print, then drifts UP a week later -> continuation
    closes = _closes("2026-05-20", 50, "2026-06-08", 6.0)
    r = classify_pead(8.0, "2026-06-01", closes, now=_NOW)
    assert r["classification"] == "drift-consistent"
    assert r["direction"] == "long"
    assert r["drift_pct"] > 0


def test_reversed_when_drift_opposes_surprise():
    # flat at the print, then falls a week later after a beat -> reversal
    closes = _closes("2026-05-20", 50, "2026-06-08", -6.0)
    r = classify_pead(8.0, "2026-06-01", closes, now=_NOW)
    assert r["classification"] == "reversed"


def test_faded_when_drift_small():
    closes = _closes("2026-05-20", 50, "2026-06-01", 0.5)  # barely moved
    r = classify_pead(8.0, "2026-06-01", closes, now=_NOW, faded_threshold_pct=2.0)
    assert r["classification"] == "faded"


def test_silent_inside_5day_window():
    closes = _closes("2026-06-20", 30, "2026-07-05", 6.0)
    # print 3 days old -> earnings_magnitude owns it
    assert classify_pead(8.0, "2026-07-05", closes, now=_NOW) is None


def test_active_on_day5_silent_on_day4():
    closes = _closes("2026-06-20", 40, None, 0.0)
    assert classify_pead(8.0, "2026-07-03", closes, now=_NOW) is not None   # 5 days
    assert classify_pead(8.0, "2026-07-04", closes, now=_NOW) is None       # 4 days


def test_silent_past_max_horizon():
    closes = _closes("2026-03-01", 130, "2026-03-10", 6.0)
    # print ~120 days old -> past 45-day horizon
    assert classify_pead(8.0, "2026-03-10", closes, now=_NOW) is None


def test_none_surprise_returns_none():
    closes = _closes("2026-05-20", 50, "2026-06-01", 6.0)
    assert classify_pead(None, "2026-06-01", closes, now=_NOW) is None


def test_tiny_surprise_returns_none():
    closes = _closes("2026-05-20", 50, "2026-06-01", 6.0)
    assert classify_pead(0.5, "2026-06-01", closes, now=_NOW, min_surprise_pct=2.0) is None


# --------------------------------------------------------------------------- #
# 4. score-leg
# --------------------------------------------------------------------------- #

def test_pead_pts_consistent_long_gives_cap():
    r = {"classification": "drift-consistent", "direction": "long", "drift_pct": 6.0, "days_since": 30}
    assert _compute_pead_pts(r, direction="long") == 3


def test_pead_pts_direction_mismatch_zero():
    r = {"classification": "drift-consistent", "direction": "long", "drift_pct": 6.0, "days_since": 30}
    assert _compute_pead_pts(r, direction="short") == 0


def test_pead_pts_faded_zero():
    r = {"classification": "faded", "direction": "long", "drift_pct": 0.5, "days_since": 30}
    assert _compute_pead_pts(r, direction="long") == 0


def test_pead_pts_reversed_zero():
    r = {"classification": "reversed", "direction": "long", "drift_pct": -6.0, "days_since": 30}
    assert _compute_pead_pts(r, direction="long") == 0


def test_pead_pts_none_zero():
    assert _compute_pead_pts(None, direction="long") == 0


# --------------------------------------------------------------------------- #
# 5. render
# --------------------------------------------------------------------------- #

def test_format_pead_none_is_dash():
    assert _format_pead(None) == "—"
    assert _format_pead({}) == "—"


def test_format_pead_consistent():
    out = _format_pead({"classification": "drift-consistent", "drift_pct": 5.8, "days_since": 30})
    assert "since print" in out and "30d" in out


# --------------------------------------------------------------------------- #
# 6. score_ticker flag OFF -> no compute, pead=0
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


@pytest.mark.asyncio
async def test_score_ticker_pead_flag_off_no_compute(monkeypatch):
    real = cfg.get
    monkeypatch.setattr(cfg, "get", lambda k, d=None: False if k == "features.pead.enabled" else real(k, d))
    calls: list[str] = []
    with contextlib.ExitStack() as stack:
        for p in _patch_fetchers():
            stack.enter_context(p)
        mdb = stack.enter_context(patch("consensus_engine.cross_reference.db"))
        stack.enter_context(patch("consensus_engine.analysis.consolidation.consolidate_for_ticker", new=AsyncMock(return_value=_FAKE_CONS)))
        stack.enter_context(patch("consensus_engine.cross_reference._run_llm_score", new_callable=AsyncMock, return_value=(0, "")))
        stack.enter_context(patch("consensus_engine.analysis.pead.compute_pead", new=AsyncMock(side_effect=lambda *a, **k: calls.append("pead") or None)))
        mdb.get_signal_counts_by_source = AsyncMock(return_value={})
        mdb.get_analyst_precision_lb = AsyncMock(return_value=None)
        result = await score_ticker("NVDA", base_score=30, direction="long")
    assert result.breakdown.pead == 0
    assert not calls, "Flag OFF -> PEAD is never computed on the hot path"
