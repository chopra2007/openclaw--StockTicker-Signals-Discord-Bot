"""Tests for volume breakout scanner."""
import pytest
from consensus_engine.scanners.volume_scanner import _detect_breakouts, BreakoutResult


def test_detect_breakouts_finds_high_rvol():
    quote_data = {
        "NVDA": {"c": 110.0, "pc": 100.0, "v": 500000},
        "AAPL": {"c": 150.0, "pc": 149.0, "v": 10000},
    }
    avg_volumes = {"NVDA": 50000, "AAPL": 100000}
    results = _detect_breakouts(quote_data, avg_volumes, rvol_threshold=5.0, min_price_change_pct=1.0)
    tickers = [r.ticker for r in results]
    assert "NVDA" in tickers
    assert "AAPL" not in tickers


def test_detect_breakouts_filters_low_price_change():
    quote_data = {"X": {"c": 100.5, "pc": 100.0, "v": 500000}}
    avg_volumes = {"X": 10000}
    results = _detect_breakouts(quote_data, avg_volumes, rvol_threshold=5.0, min_price_change_pct=1.0)
    assert results == []


def test_detect_breakouts_empty():
    results = _detect_breakouts({}, {}, rvol_threshold=5.0, min_price_change_pct=1.0)
    assert results == []


def test_detect_breakouts_sorted_by_rvol():
    quote_data = {
        "A": {"c": 110.0, "pc": 100.0, "v": 500000},
        "B": {"c": 110.0, "pc": 100.0, "v": 1000000},
    }
    avg_volumes = {"A": 50000, "B": 50000}
    results = _detect_breakouts(quote_data, avg_volumes, rvol_threshold=5.0, min_price_change_pct=1.0)
    assert results[0].ticker == "B"
    assert results[1].ticker == "A"
