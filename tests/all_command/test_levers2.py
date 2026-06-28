"""Unit tests for the two #6 levers2 (all-quality-cheap-levers, batch 2):
  * Lever A — put/call OPEN-INTEREST: compute_max_pain exposes pc_oi_ratio +
    call_oi_sum/put_oi_sum (additively, weekly/monthly/spot shape intact) + the
    embed "📊 Options OI" call/put % split field (#53).
  * Lever B — earnings-move history: fetch_earnings_move reaction-day math
    (AMC -> next trading day, BMO -> report day, missing data -> None) + embed
    "Earnings" field.
"""
from __future__ import annotations

import asyncio

import pandas as pd
import pytest

from consensus_engine.scanners import options, earnings_move
from consensus_engine.alerts.all_command import embed


# ---------------------------------------------------------------------------
# Shared embed-render scaffolding (mirrors tests/all_command/test_cheap_levers.py)
# ---------------------------------------------------------------------------

class _FakeStructured:
    direction = "BULLISH"
    confidence_label = "HIGH"
    current_price = 180.00
    buy_zone_low = 178.00
    buy_zone_high = 180.00
    sl = 175.00
    tp1 = 190.00
    tp2 = 200.00
    tp3 = 210.00
    earnings_date = None
    breakout_timeframe = "TBD"
    magnitude_label = "TBD"
    next_catalyst_days = 3
    swing_horizon_days = 14
    swing_horizon_band = (10, 18)
    expected_move_typical = 5.0
    expected_move_high_vol = 8.0
    magnitude_band_label = "±$5–$8 / 2w"
    relative_volume = None
    max_pain = None
    earnings_move = None


class _FakeBreakdown:
    total = 82
    news_catalyst = 20
    social_apewisdom = 0
    social_stocktwits = 0
    social_reddit = 0
    google_trends = 0
    technical = 30
    llm_boost = 20
    options_flow = 0
    consensus_boost = 12


def _build(structured):
    return embed.build_embed(
        ticker="NVDA",
        structured=structured,
        score_breakdown=_FakeBreakdown(),
        narrative="**TL;DR:** thesis.\nBody.",
        sources_used=["news"],
        cache_age_seconds=None,
    )


def _field(payload, name):
    return next((f for f in payload["fields"] if f["name"] == name), None)


# ---------------------------------------------------------------------------
# Lever A — compute_max_pain pc_oi_ratio
# ---------------------------------------------------------------------------

class _Chain:
    def __init__(self, calls: pd.DataFrame, puts: pd.DataFrame):
        self.calls = calls
        self.puts = puts


def _chain(call_oi: dict, put_oi: dict) -> _Chain:
    calls = pd.DataFrame([{"strike": k, "openInterest": v} for k, v in call_oi.items()])
    puts = pd.DataFrame([{"strike": k, "openInterest": v} for k, v in put_oi.items()])
    return _Chain(calls, puts)


def _patch_chain(monkeypatch, call_oi, put_oi):
    """Make compute_max_pain's blocking fetch return a single nearest expiry whose
    chain is built from the given OI dicts. Two strikes min so max-pain is computable."""
    exp = "2026-06-19"
    chain = _chain(call_oi, put_oi)

    class _FakeTicker:
        def __init__(self, *_a, **_k):
            self.options = (exp,)
            self.fast_info = {"lastPrice": 100.0}

        def option_chain(self, e):
            return chain

    import types
    fake_yf = types.SimpleNamespace(Ticker=_FakeTicker)
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake_yf)
    return exp


@pytest.mark.asyncio
async def test_compute_max_pain_returns_pc_oi_ratio(monkeypatch):
    # put OI 1390 / call OI 1000 = 1.39 (AMD-like). Two strikes so max-pain computes.
    _patch_chain(monkeypatch,
                 call_oi={95.0: 1000.0, 105.0: 0.0},
                 put_oi={95.0: 0.0, 105.0: 1390.0})
    out = await options.compute_max_pain("AMD")
    assert out is not None
    assert out["pc_oi_ratio"] == 1.39
    # Existing shape unchanged: spot/weekly/monthly keys still present.
    assert set(out) >= {"spot", "weekly", "monthly", "pc_oi_ratio"}
    assert out["spot"] == 100.0
    # #53: raw OI sums now travel in the dict for the call/put % split.
    assert out["call_oi_sum"] == 1000.0
    assert out["put_oi_sum"] == 1390.0


@pytest.mark.asyncio
async def test_compute_max_pain_pc_oi_ratio_none_when_no_call_oi(monkeypatch):
    # Zero call OI -> ratio None (guarded division), but put OI keeps max-pain valid.
    _patch_chain(monkeypatch,
                 call_oi={95.0: 0.0, 105.0: 0.0},
                 put_oi={95.0: 500.0, 105.0: 500.0})
    out = await options.compute_max_pain("XYZ")
    assert out is not None
    assert out["pc_oi_ratio"] is None


# ---------------------------------------------------------------------------
# Lever A + #53 — embed "📊 Options OI" call/put % split field (OI basis)
# ---------------------------------------------------------------------------

def test_build_embed_shows_oi_split_when_present():
    s = _FakeStructured()
    # 600 call OI / 400 put OI = 60% / 40%; total 1000 >= the 50-contract floor.
    s.max_pain = {"spot": 100.0, "weekly": None, "monthly": None,
                  "pc_oi_ratio": 0.67, "call_oi_sum": 600.0, "put_oi_sum": 400.0}
    payload = _build(s)
    f = _field(payload, "📊 Options OI")
    assert f is not None
    assert f["value"] == "🟢 Calls 60% / 🔴 Puts 40% (open interest)"
    assert f["inline"] is True


def test_build_embed_omits_oi_split_when_sums_missing():
    # Legacy dict with only pc_oi_ratio (no raw sums) -> field omitted.
    s = _FakeStructured()
    s.max_pain = {"spot": 100.0, "weekly": None, "monthly": None, "pc_oi_ratio": 0.42}
    payload = _build(s)
    assert _field(payload, "📊 Options OI") is None


def test_build_embed_omits_oi_split_when_no_max_pain():
    s = _FakeStructured()
    s.max_pain = None
    payload = _build(s)
    assert _field(payload, "📊 Options OI") is None


def test_build_embed_omits_oi_split_when_thin_oi():
    # Total OI below the 50-contract floor -> suppressed (a split would be noise,
    # and !all shows no contract count to calibrate it).
    s = _FakeStructured()
    s.max_pain = {"spot": 100.0, "weekly": None, "monthly": None,
                  "pc_oi_ratio": 0.82, "call_oi_sum": 11.0, "put_oi_sum": 9.0}
    payload = _build(s)
    assert _field(payload, "📊 Options OI") is None


# ---------------------------------------------------------------------------
# Lever B — earnings_move reaction-day math
# ---------------------------------------------------------------------------

def _patch_earnings(monkeypatch, earnings_index, closes_series):
    """Stub yfinance so _compute_earnings_move sees the given earnings-date index
    (tz-aware) and Close series (tz-aware DatetimeIndex)."""
    # Real get_earnings_dates returns a frame WITH columns; a column-less frame
    # reports .empty == True even with an index, so carry a dummy column.
    idx = pd.DatetimeIndex(earnings_index)
    ed = pd.DataFrame({"EPS Estimate": [None] * len(idx)}, index=idx)
    hist = pd.DataFrame({"Close": closes_series.values}, index=closes_series.index)

    class _FakeTicker:
        def __init__(self, *_a, **_k):
            pass

        def get_earnings_dates(self, limit=24):
            return ed

        def history(self, period="2y"):
            return hist

    import types
    fake_yf = types.SimpleNamespace(Ticker=_FakeTicker)
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake_yf)


def _closes(dates, prices, tz="America/New_York"):
    idx = pd.DatetimeIndex(pd.to_datetime(dates)).tz_localize(tz)
    return pd.Series(prices, index=idx)


def test_earnings_move_amc_picks_next_trading_day(monkeypatch):
    # Trading days Mon-Fri. Report Wed AMC (18:00) -> reaction is Thu's close.
    # Wed close 100 -> Thu close 110 = +10% reaction.
    dates = ["2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07", "2026-05-08"]
    prices = [90.0, 95.0, 100.0, 110.0, 112.0]
    closes = _closes(dates, prices)
    # Report Wed 2026-05-06 18:00 ET (AMC).
    ed_idx = [pd.Timestamp("2026-05-06 18:00", tz="America/New_York")]
    _patch_earnings(monkeypatch, ed_idx, closes)
    out = earnings_move._compute_earnings_move("NVDA", n=8)
    assert out is not None
    assert out["n"] == 1
    assert out["avg_pct"] == 10.0  # |110/100 - 1| * 100


def test_earnings_move_bmo_picks_report_day(monkeypatch):
    # Report Wed BMO (08:00) -> reaction is Wed's close vs Tue's close.
    # Tue close 95 -> Wed close 100 = +5.3% reaction (rounded 1dp).
    dates = ["2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07", "2026-05-08"]
    prices = [90.0, 95.0, 100.0, 110.0, 112.0]
    closes = _closes(dates, prices)
    ed_idx = [pd.Timestamp("2026-05-06 08:00", tz="America/New_York")]
    _patch_earnings(monkeypatch, ed_idx, closes)
    out = earnings_move._compute_earnings_move("NVDA", n=8)
    assert out is not None
    assert out["n"] == 1
    assert out["avg_pct"] == 5.3  # |100/95 - 1| * 100 = 5.26 -> 5.3


def test_earnings_move_averages_multiple_prints(monkeypatch):
    dates = ["2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07", "2026-05-08"]
    prices = [100.0, 110.0, 100.0, 90.0, 90.0]
    closes = _closes(dates, prices)
    # Two AMC reports: Mon 18:00 -> Tue (100->110 = 10%); Wed 18:00 -> Thu (100->90 = 10%).
    ed_idx = [
        pd.Timestamp("2026-05-04 18:00", tz="America/New_York"),
        pd.Timestamp("2026-05-06 18:00", tz="America/New_York"),
    ]
    _patch_earnings(monkeypatch, ed_idx, closes)
    out = earnings_move._compute_earnings_move("NVDA", n=8)
    assert out is not None
    assert out["n"] == 2
    assert out["avg_pct"] == 10.0


def test_earnings_move_empty_earnings_returns_none(monkeypatch):
    closes = _closes(["2026-05-04", "2026-05-05"], [100.0, 101.0])
    _patch_earnings(monkeypatch, [], closes)
    assert earnings_move._compute_earnings_move("NVDA", n=8) is None


def test_earnings_move_empty_history_returns_none(monkeypatch):
    ed_idx = [pd.Timestamp("2026-05-06 18:00", tz="America/New_York")]
    empty_closes = pd.Series([], index=pd.DatetimeIndex([]).tz_localize("America/New_York"), dtype=float)
    _patch_earnings(monkeypatch, ed_idx, empty_closes)
    assert earnings_move._compute_earnings_move("NVDA", n=8) is None


def test_earnings_move_no_alignable_prints_returns_none(monkeypatch):
    # Report is AMC on the LAST trading day -> react index runs off the end -> skipped.
    dates = ["2026-05-04", "2026-05-05"]
    prices = [100.0, 105.0]
    closes = _closes(dates, prices)
    ed_idx = [pd.Timestamp("2026-05-05 18:00", tz="America/New_York")]  # AMC last day
    _patch_earnings(monkeypatch, ed_idx, closes)
    assert earnings_move._compute_earnings_move("NVDA", n=8) is None


@pytest.mark.asyncio
async def test_fetch_earnings_move_async_wrapper(monkeypatch):
    dates = ["2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07"]
    prices = [90.0, 95.0, 100.0, 110.0]
    closes = _closes(dates, prices)
    ed_idx = [pd.Timestamp("2026-05-06 18:00", tz="America/New_York")]
    _patch_earnings(monkeypatch, ed_idx, closes)
    out = await earnings_move.fetch_earnings_move("NVDA", n=8)
    assert out == {"avg_pct": 10.0, "n": 1}


# ---------------------------------------------------------------------------
# Lever B — embed "Earnings" field
# ---------------------------------------------------------------------------

def test_build_embed_shows_earnings_when_present():
    s = _FakeStructured()
    s.earnings_move = {"avg_pct": 3.7, "n": 8}
    payload = _build(s)
    f = _field(payload, "Earnings")
    assert f is not None
    assert f["value"] == "±3.7% (8)"
    assert f["inline"] is True


def test_build_embed_omits_earnings_when_none():
    s = _FakeStructured()
    s.earnings_move = None
    payload = _build(s)
    assert _field(payload, "Earnings") is None


def test_build_embed_omits_earnings_when_zero_n():
    s = _FakeStructured()
    s.earnings_move = {"avg_pct": 0.0, "n": 0}
    payload = _build(s)
    assert _field(payload, "Earnings") is None
