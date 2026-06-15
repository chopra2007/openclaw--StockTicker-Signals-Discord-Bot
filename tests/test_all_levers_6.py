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


async def test_stocktwits_partial_success_renders(monkeypatch):
    # sentiment ok, watchers fail -> dict still built from what succeeded
    async def fake_sent(ticker):
        return 73.0, -2.7
    async def fake_watch(ticker):
        return None
    monkeypatch.setattr(st, "_fetch_sentiment", fake_sent)
    monkeypatch.setattr(st, "_fetch_watchers", fake_watch)
    out = await st._fetch_raw("NVDA")
    assert out == {"bull_pct": 73.0, "delta_5d": -2.7, "watchers": None}


async def test_stocktwits_all_fail_returns_none(monkeypatch):
    async def none_sent(t):
        return None, None
    async def none_watch(t):
        return None
    monkeypatch.setattr(st, "_fetch_sentiment", none_sent)
    monkeypatch.setattr(st, "_fetch_watchers", none_watch)
    assert await st._fetch_raw("NVDA") is None
