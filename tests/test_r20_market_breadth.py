"""r20 (standalone-scanners) — market-breadth participation proxy (RSP/SPY).

Tests:
  1. _ratio_trend math (latest ratio + % trend over window).
  2. compute_market_breadth classification (broadening / narrowing / flat) with
     mocked price history.
  3. DESCRIPTIVE-ONLY guard: market_breadth is NOT wired into cross_reference /
     ScoreBreakdown.
  4. !market panel render: field present with a row, absent without (byte-identical).
  5. forward_log round-trip into market_breadth_daily.
"""
from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from consensus_engine.analysis import market_breadth as mb
from consensus_engine.analysis.market_breadth import _ratio_trend, compute_market_breadth


def _df(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2026-05-01", periods=len(closes), freq="D")
    return pd.DataFrame({"Close": closes}, index=idx)


# --------------------------------------------------------------------------- #
# 1. _ratio_trend
# --------------------------------------------------------------------------- #

def test_ratio_trend_rising():
    num = _df([1.0] * 21)
    # den falls over the window -> ratio (num/den) rises
    den = _df([2.2 - 0.01 * i for i in range(21)])
    latest, trend = _ratio_trend(num, den, window_days=20)
    assert trend > 0
    assert latest == pytest.approx(1.0 / den["Close"].iloc[-1], rel=1e-6)


def test_ratio_trend_insufficient_data():
    assert _ratio_trend(_df([1.0]), _df([1.0]), window_days=20) is None
    assert _ratio_trend(None, _df([1.0, 1.0]), window_days=20) is None


# --------------------------------------------------------------------------- #
# 2. compute_market_breadth classification
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_compute_broadening(monkeypatch):
    # RSP flat, SPY falling -> RSP/SPY rises -> broadening
    fake = {"RSP": _df([100.0] * 21), "SPY": _df([100.0 - 0.5 * i for i in range(21)]),
            "IWM": _df([50.0] * 21)}
    monkeypatch.setattr(mb, "__name__", mb.__name__)  # no-op keep import
    import consensus_engine.utils.prices as prices
    monkeypatch.setattr(prices, "fetch_history", lambda sym, **kw: fake[sym])
    read = await compute_market_breadth(window_days=20, trend_threshold_pct=0.5)
    assert read["breadth_state"] == "broadening"
    assert read["rsp_spy_trend"] > 0.5


@pytest.mark.asyncio
async def test_compute_narrowing(monkeypatch):
    fake = {"RSP": _df([100.0 - 0.5 * i for i in range(21)]), "SPY": _df([100.0] * 21),
            "IWM": _df([50.0] * 21)}
    import consensus_engine.utils.prices as prices
    monkeypatch.setattr(prices, "fetch_history", lambda sym, **kw: fake[sym])
    read = await compute_market_breadth(window_days=20, trend_threshold_pct=0.5)
    assert read["breadth_state"] == "narrowing"


@pytest.mark.asyncio
async def test_compute_flat(monkeypatch):
    fake = {"RSP": _df([100.0] * 21), "SPY": _df([100.0] * 21), "IWM": _df([50.0] * 21)}
    import consensus_engine.utils.prices as prices
    monkeypatch.setattr(prices, "fetch_history", lambda sym, **kw: fake[sym])
    read = await compute_market_breadth(window_days=20, trend_threshold_pct=0.5)
    assert read["breadth_state"] == "flat"


@pytest.mark.asyncio
async def test_compute_none_when_rsp_missing(monkeypatch):
    fake = {"RSP": None, "SPY": _df([100.0] * 21), "IWM": _df([50.0] * 21)}
    import consensus_engine.utils.prices as prices
    monkeypatch.setattr(prices, "fetch_history", lambda sym, **kw: fake[sym])
    assert await compute_market_breadth(window_days=20) is None


# --------------------------------------------------------------------------- #
# 3. DESCRIPTIVE-ONLY guard — never wired into the scorer
# --------------------------------------------------------------------------- #

def test_not_in_score_breakdown():
    from consensus_engine.models import ScoreBreakdown
    names = {f.name for f in dataclasses.fields(ScoreBreakdown)}
    assert "market_breadth" not in names


def test_cross_reference_never_imports_market_breadth():
    import inspect
    import consensus_engine.cross_reference as xr
    src = inspect.getsource(xr)
    assert "market_breadth" not in src, "r20 must stay descriptive-only (never in score_ticker)"


# --------------------------------------------------------------------------- #
# 4. !market panel render
# --------------------------------------------------------------------------- #

def test_market_embed_renders_breadth_panel():
    from consensus_engine.alerts.commands import _build_market_embed
    row = {"breadth_state": "broadening", "rsp_spy_trend": 1.9, "iwm_spy_trend": 3.7, "window_days": 20}
    embed = _build_market_embed([], [], None, None, "note", market_breadth_row=row)
    names = [f["name"] for f in embed["fields"]]
    assert any("Market breadth" in n for n in names)


def test_market_embed_absent_without_row():
    from consensus_engine.alerts.commands import _build_market_embed
    embed = _build_market_embed([], [], None, None, "note")  # no market_breadth_row
    names = [f["name"] for f in embed["fields"]]
    assert not any("Market breadth (participation)" in n for n in names)


# --------------------------------------------------------------------------- #
# 5. forward_log round-trip
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_forward_log_roundtrip(monkeypatch):
    import consensus_engine.db as db_mod
    db_mod.DB_PATH = ":memory:"
    db_mod._db = None
    await db_mod.init_db()
    fake = {"RSP": _df([100.0] * 21), "SPY": _df([100.0 - 0.5 * i for i in range(21)]),
            "IWM": _df([50.0] * 21)}
    import consensus_engine.utils.prices as prices
    monkeypatch.setattr(prices, "fetch_history", lambda sym, **kw: fake[sym])

    read = await mb.forward_log_market_breadth(window_days=20)
    assert read is not None and read["breadth_state"] == "broadening"
    latest = await db_mod.get_db()
    cur = await latest.execute("SELECT breadth_state, window_days FROM market_breadth_daily")
    r = await cur.fetchone()
    assert r["breadth_state"] == "broadening"
    assert r["window_days"] == 20
    db_mod._db = None
    db_mod.DB_PATH = None
