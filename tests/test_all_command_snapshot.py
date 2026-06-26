"""Tests for #6 A2 — the Snapshot embed field (analyst target + fwd P/E + short).

Covers the embed formatter (full / partial / empty / short%-fraction) and the
scanner's guards (NaN/None drop, empty-.info -> None, feature flag gate).
"""
import math
import pytest
from unittest.mock import patch

from consensus_engine.alerts.all_command import embed
from consensus_engine.scanners import snapshot as snap_mod


# --- formatter ---------------------------------------------------------------

def test_format_snapshot_full():
    snap = {"target_mean": 215.0, "target_high": 260.0, "target_low": 180.0,
            "n_analysts": 58, "rating": "Buy", "fwd_pe": 31.0,
            "short_pct": 0.0092, "short_days": 3.11}
    out = embed._format_snapshot(snap)
    assert "🎯 $215 avg ($180–$260)" in out
    assert "58 analysts" in out
    assert "Buy" in out
    assert "Fwd P/E 31" in out
    # short_pct is a FRACTION (0.0092) -> 0.9%
    assert "Short 0.9% (3.1d cover)" in out


def test_format_snapshot_none_and_empty():
    assert embed._format_snapshot(None) == "—"
    assert embed._format_snapshot("nope") == "—"
    assert embed._format_snapshot({}) == "—"


def test_format_snapshot_analyst_only():
    out = embed._format_snapshot({"target_mean": 50.0, "n_analysts": 12, "rating": "Hold"})
    assert "🎯 $50 avg" in out
    assert "12 analysts" in out and "Hold" in out
    assert "Fwd P/E" not in out and "Short" not in out


def test_format_snapshot_fundamentals_only():
    out = embed._format_snapshot({"fwd_pe": 8.4, "short_pct": 0.135})
    assert "Fwd P/E 8.4" in out          # <10 -> one decimal
    assert "Short 13.5%" in out
    assert "🎯" not in out


def test_format_snapshot_low_price_target_two_decimals():
    out = embed._format_snapshot({"target_mean": 7.5, "target_low": 6.0, "target_high": 9.0})
    assert "$7.50 avg ($6.00–$9.00)" in out


# --- scanner guards ----------------------------------------------------------

def test_num_drops_nan_none_and_garbage():
    assert snap_mod._num(None) is None
    assert snap_mod._num(float("nan")) is None
    assert snap_mod._num(float("inf")) is None
    assert snap_mod._num("x") is None
    assert snap_mod._num(3) == 3.0


@pytest.mark.asyncio
async def test_fetch_snapshot_empty_info_returns_none():
    with patch.object(snap_mod, "_fetch_info", return_value={}):
        assert await snap_mod.fetch_ticker_snapshot("NVDA") is None


@pytest.mark.asyncio
async def test_fetch_snapshot_no_usable_fields_returns_none():
    # .info present but none of the fields we surface -> None (field omitted).
    with patch.object(snap_mod, "_fetch_info", return_value={"longName": "X", "marketCap": 1}):
        assert await snap_mod.fetch_ticker_snapshot("NVDA") is None


@pytest.mark.asyncio
async def test_fetch_snapshot_happy_path():
    # fwd_pe is now price ÷ current-FY EPS (synthetic key _eps_cfy set by
    # _fetch_info), NOT yfinance's forwardPE field. forwardPE is left in the
    # input to assert it is now ignored. 200 / 8.0 = 25.0.
    info = {"recommendationKey": "strong_buy", "numberOfAnalystOpinions": 58,
            "targetMeanPrice": 215.3, "targetHighPrice": 260, "targetLowPrice": 180,
            "forwardPE": 31.2, "_eps_cfy": 8.0, "currentPrice": 200.0,
            "shortPercentOfFloat": 0.0092, "shortRatio": 3.11}
    with patch.object(snap_mod, "_fetch_info", return_value=info):
        snap = await snap_mod.fetch_ticker_snapshot("NVDA")
    assert snap["rating"] == "Strong Buy"
    assert snap["n_analysts"] == 58
    assert snap["target_mean"] == 215.3
    assert snap["fwd_pe"] == 25.0  # 200 / 8.0 current-FY EPS, not forwardPE 31.2
    assert snap["short_pct"] == 0.0092


@pytest.mark.asyncio
async def test_fetch_snapshot_flag_off_returns_none_without_fetch():
    called = {"hit": False}

    def _spy(_t):
        called["hit"] = True
        return {"targetMeanPrice": 1}

    with patch.object(snap_mod, "_fetch_info", side_effect=_spy), \
         patch("consensus_engine.config.get",
               side_effect=lambda k, d=None: False if k == "features.snapshot.enabled" else d):
        assert await snap_mod.fetch_ticker_snapshot("NVDA") is None
    assert called["hit"] is False, "flag off must skip the .info fetch entirely"
