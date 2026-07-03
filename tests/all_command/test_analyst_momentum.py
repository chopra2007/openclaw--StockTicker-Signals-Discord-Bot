"""Unit tests for the #6 analyst-consensus-momentum lever:
  * snapshot._reco_score / _fetch_analyst_momentum — .recommendations scoring +
    the rolling-window fallback (a '-3m' baseline is NOT guaranteed).
  * embed._format_snapshot — the 'Rating trend' segment (up / down / flat / absent).
"""
from __future__ import annotations

import pandas as pd
import pytest

from consensus_engine.alerts.all_command import embed
from consensus_engine.scanners import snapshot


def _reco_df(rows):
    """rows: list of (period, strongBuy, buy, hold, sell, strongSell) tuples."""
    cols = ["period", "strongBuy", "buy", "hold", "sell", "strongSell"]
    return pd.DataFrame([dict(zip(cols, r)) for r in rows])


class _FakeTicker:
    def __init__(self, df):
        self.recommendations = df


@pytest.fixture
def patch_yf(monkeypatch):
    def _install(df):
        import yfinance as yf
        monkeypatch.setattr(yf, "Ticker", lambda _t: _FakeTicker(df))
    return _install


# --- scoring ---------------------------------------------------------------

def test_reco_score_amd_now_matches_preflight():
    # AMD 0m: 5 SB / 37 B / 9 H → (25+148+27)/51 = 3.92 (pre-flight reference value).
    row = pd.Series({"strongBuy": 5, "buy": 37, "hold": 9, "sell": 0, "strongSell": 0})
    score, n = snapshot._reco_score(row)
    assert n == 51
    assert score == pytest.approx(3.9216, abs=1e-3)


def test_reco_score_no_analysts_returns_none():
    row = pd.Series({"strongBuy": 0, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0})
    assert snapshot._reco_score(row) == (None, 0)


# --- momentum fetch (rolling window) ---------------------------------------

def test_momentum_uses_3m_when_present(patch_yf):
    # TSLA-shaped 4-row table (has -3m).
    patch_yf(_reco_df([
        ("0m", 5, 18, 18, 4, 2),
        ("-1m", 5, 18, 18, 4, 2),
        ("-2m", 5, 18, 17, 4, 3),
        ("-3m", 5, 18, 17, 4, 3),
    ]))
    mom = snapshot._fetch_analyst_momentum("TSLA")
    assert mom["window"] == "3mo"
    assert mom["now"] == pytest.approx(3.43, abs=0.01)
    assert mom["shift"] == pytest.approx(0.04, abs=0.01)
    assert mom["n_now"] == 47


def test_momentum_falls_back_to_oldest_present(patch_yf):
    # AMD-shaped 3-row table (NO -3m) → baseline is -2m, window '2mo'.
    patch_yf(_reco_df([
        ("0m", 5, 37, 9, 0, 0),
        ("-1m", 5, 36, 10, 0, 0),
        ("-2m", 4, 33, 13, 0, 0),
    ]))
    mom = snapshot._fetch_analyst_momentum("AMD")
    assert mom["window"] == "2mo"
    assert mom["now"] == pytest.approx(3.92, abs=0.01)
    assert mom["prior"] == pytest.approx(3.82, abs=0.01)   # -2m: (20+132+39)/50
    assert mom["shift"] == pytest.approx(0.10, abs=0.01)


def test_momentum_only_current_month_returns_none(patch_yf):
    patch_yf(_reco_df([("0m", 5, 37, 9, 0, 0)]))
    assert snapshot._fetch_analyst_momentum("AMD") is None


def test_momentum_empty_returns_none(patch_yf):
    patch_yf(pd.DataFrame())
    assert snapshot._fetch_analyst_momentum("XYZ") is None


# --- render ----------------------------------------------------------------

def test_format_snapshot_renders_rating_trend_up():
    snap = {"target_mean": 200.0, "n_analysts": 30,
            "analyst_momentum": {"now": 3.92, "prior": 3.82, "shift": 0.10, "n_now": 51, "window": "2mo"}}
    assert "Rating trend ▲ 3.82→3.92 (2mo)" in embed._format_snapshot(snap)


def test_format_snapshot_renders_rating_trend_down():
    snap = {"target_mean": 200.0, "n_analysts": 30,
            "analyst_momentum": {"now": 3.40, "prior": 3.60, "shift": -0.20, "n_now": 40, "window": "3mo"}}
    assert "Rating trend ▼ 3.60→3.40 (3mo)" in embed._format_snapshot(snap)


def test_format_snapshot_rating_trend_flat():
    snap = {"target_mean": 200.0, "n_analysts": 30,
            "analyst_momentum": {"now": 3.50, "prior": 3.50, "shift": 0.0, "n_now": 40, "window": "3mo"}}
    assert "Rating trend → 3.50 (3mo flat)" in embed._format_snapshot(snap)


def test_format_snapshot_omits_rating_trend_when_absent():
    # No analyst_momentum key → no trend segment, but the snapshot still renders.
    out = embed._format_snapshot({"target_mean": 200.0, "n_analysts": 30})
    assert "Rating trend" not in out
    assert out != "—"
