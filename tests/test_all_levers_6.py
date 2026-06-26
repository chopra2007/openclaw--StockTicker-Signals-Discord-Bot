"""Tests for the #6 !all levers: EPS-revision trend (Lever 1) and Stocktwits retail
sentiment (Lever 2). The eps_revisions column casing is pinned with a real-shape fixture
(yfinance ships inconsistent casing: upLast30days / downLast30days lowercase but
downLast7Days capital-D — a guard that assumes uniform casing silently breaks)."""
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consensus_engine.scanners import snapshot, stocktwits_sentiment as st
from consensus_engine.alerts.all_command import embed


# real-shape eps_revisions frame (captured live from NVDA 2026-06-15)
def _rev_frame(up30=34, down30=3):
    return pd.DataFrame(
        {"upLast7days": [up30, 1, 5, 2], "upLast30days": [up30, 2, 8, 4],
         "downLast30days": [down30, 0, 1, 1], "downLast7Days": [down30, 0, 0, 0]},
        index=["0q", "+1q", "0y", "+1y"])


def _patch_yf(monkeypatch, frame):
    fake_t = types.SimpleNamespace(eps_revisions=frame)
    fake_yf = types.SimpleNamespace(Ticker=lambda _t: fake_t)
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)


# ----------------------------------------------------- Lever 1: eps_revisions
def test_eps_revisions_parses_real_casing(monkeypatch):
    _patch_yf(monkeypatch, _rev_frame(34, 3))
    assert snapshot._fetch_eps_revisions("NVDA") == {"up": 34, "down": 3}


def test_eps_revisions_empty_table_returns_none(monkeypatch):
    _patch_yf(monkeypatch, pd.DataFrame())
    assert snapshot._fetch_eps_revisions("XYZ") is None


def test_eps_revisions_zero_counts_returns_none(monkeypatch):
    _patch_yf(monkeypatch, _rev_frame(0, 0))
    assert snapshot._fetch_eps_revisions("XYZ") is None


def test_eps_revisions_missing_column_does_not_throw(monkeypatch):
    df = _rev_frame(34, 3).drop(columns=["upLast30days"])  # schema drift
    _patch_yf(monkeypatch, df)
    # up column gone -> up=0, down=3 -> still returns (down>0), never raises
    assert snapshot._fetch_eps_revisions("NVDA") == {"up": 0, "down": 3}


def test_format_snapshot_renders_eps_rev_segment():
    out = embed._format_snapshot({"eps_rev": {"up": 34, "down": 3}})
    assert "EPS rev 34↑ 3↓ (30d)" in out


def test_format_snapshot_no_eps_rev_when_absent():
    out = embed._format_snapshot({"fwd_pe": 24.0})
    assert "EPS rev" not in out


# ----------------------------------------------------- Lever 2: Stocktwits
@pytest.fixture(autouse=True)
def _clear_st_cache():
    st._cache.clear()
    st._inflight.clear()
    yield
    st._cache.clear()
    st._inflight.clear()


async def test_stocktwits_positive_cache_and_coalesce(monkeypatch):
    calls = {"n": 0}

    async def fake_raw(ticker):
        calls["n"] += 1
        return {"bull_pct": 73.0, "delta_5d": -2.0, "watchers": 650000}

    monkeypatch.setattr(st, "_fetch_raw", fake_raw)
    import asyncio
    # concurrent calls for the same ticker share ONE underlying fetch (coalesced)
    a, b, c = await asyncio.gather(*[st.fetch_stocktwits_sentiment("NVDA") for _ in range(3)])
    assert a == b == c and a["bull_pct"] == 73.0
    # a later call hits the 15-min positive cache, still one fetch total
    await st.fetch_stocktwits_sentiment("NVDA")
    assert calls["n"] == 1


async def test_stocktwits_negative_cache(monkeypatch):
    calls = {"n": 0}

    async def fake_raw(ticker):
        calls["n"] += 1
        return None  # API down / no data

    monkeypatch.setattr(st, "_fetch_raw", fake_raw)
    assert await st.fetch_stocktwits_sentiment("NVDA") is None
    assert await st.fetch_stocktwits_sentiment("NVDA") is None
    assert calls["n"] == 1  # negative-cached, not re-hit


def test_stocktwits_partial_success_renders(monkeypatch):
    # sentiment ok, watchers fail -> dict still built from what succeeded
    monkeypatch.setattr(st, "_fetch_sentiment_sync", lambda t: (73.0, -2.7))
    monkeypatch.setattr(st, "_fetch_watchers_sync", lambda t: None)
    assert st._blocking_fetch("NVDA") == {"bull_pct": 73.0, "delta_5d": -2.7, "watchers": None}


def test_stocktwits_all_fail_returns_none(monkeypatch):
    monkeypatch.setattr(st, "_fetch_sentiment_sync", lambda t: (None, None))
    monkeypatch.setattr(st, "_fetch_watchers_sync", lambda t: None)
    assert st._blocking_fetch("NVDA") is None


# ----------------------------------------------------- #6: fundamentals one-liner (C2)
def test_format_snapshot_fundamentals_full():
    out = embed._format_snapshot({"fundamentals": {
        "peg": 0.6, "rev_growth_pct": 85.2, "profit_margin_pct": 63.0,
        "beta": 2.2, "inst_pct": 70.9}})
    assert "PEG 0.6 · Growth 85% · Margin 63% · Beta 2.2 · Inst 71%" in out


def test_format_snapshot_fundamentals_negative_margin_renders():
    # an unprofitable margin is honest signal — it must still render
    out = embed._format_snapshot({"fundamentals": {
        "peg": None, "rev_growth_pct": 47.0, "profit_margin_pct": -19.4,
        "beta": 0.99, "inst_pct": 37.2}})
    assert "Margin -19%" in out
    assert "PEG" not in out          # PEG None -> silently omitted, no '—'
    assert "Growth 47%" in out


def test_format_snapshot_no_fundamentals_when_absent():
    out = embed._format_snapshot({"fwd_pe": 24.0})
    assert "PEG" not in out and "Beta" not in out and "Inst" not in out


def test_format_snapshot_fundamentals_all_none_renders_nothing():
    out = embed._format_snapshot({"fundamentals": {
        "peg": None, "rev_growth_pct": None, "profit_margin_pct": None,
        "beta": None, "inst_pct": None}})
    assert out == "—"  # nothing else in snap, fundamentals all empty


_FUND_INFO = {"recommendationKey": "buy", "targetMeanPrice": 200.0,
              "numberOfAnalystOpinions": 50, "trailingPegRatio": 0.6,
              "revenueGrowth": 0.85, "profitMargins": 0.63, "beta": 2.2,
              "heldPercentInstitutions": 0.71, "currentPrice": 180.0}


@pytest.mark.asyncio
async def test_fetch_snapshot_fundamentals_gated_off_by_default(monkeypatch):
    # flag OFF (conftest default) -> scanner does NOT populate snap["fundamentals"]
    monkeypatch.setattr(snapshot, "_fetch_info", lambda t: dict(_FUND_INFO))
    snap = await snapshot.fetch_ticker_snapshot("NVDA")
    assert snap is not None
    assert "fundamentals" not in snap  # gated OFF


@pytest.mark.asyncio
async def test_fetch_snapshot_fundamentals_populated_when_on(monkeypatch):
    from consensus_engine import config as cfg
    real_get = cfg.get
    overrides = {
        "features.fundamentals_oneliner.enabled": True,
        "features.snapshot.enabled": True,
        "features.snapshot.eps_revisions": False,
    }
    monkeypatch.setattr(cfg, "get", lambda k, d=None: overrides.get(k, real_get(k, d)))
    monkeypatch.setattr(snapshot, "_fetch_info", lambda t: dict(_FUND_INFO))
    snap = await snapshot.fetch_ticker_snapshot("NVDA")
    assert snap["fundamentals"]["peg"] == 0.6
    assert round(snap["fundamentals"]["rev_growth_pct"], 0) == 85.0
    assert round(snap["fundamentals"]["profit_margin_pct"], 0) == 63.0
