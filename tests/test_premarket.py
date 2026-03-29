"""Tests for pre-market gap scanner."""
import pytest
from consensus_engine.scanners.premarket import _detect_gaps, GapResult


def test_detect_gaps_finds_large_gap():
    quotes = {
        "NVDA": {"c": 100.0, "pc": 90.0},
        "AAPL": {"c": 150.0, "pc": 149.0},
        "TSLA": {"c": 200.0, "pc": 210.0},
    }
    results = _detect_gaps(quotes, threshold_pct=3.0)
    tickers = [r.ticker for r in results]
    assert "NVDA" in tickers
    assert "TSLA" in tickers
    assert "AAPL" not in tickers


def test_detect_gaps_sorted_by_magnitude():
    quotes = {
        "A": {"c": 110.0, "pc": 100.0},
        "B": {"c": 120.0, "pc": 100.0},
    }
    results = _detect_gaps(quotes, threshold_pct=3.0)
    assert results[0].ticker == "B"
    assert results[1].ticker == "A"


def test_detect_gaps_handles_zero_prev_close():
    quotes = {"X": {"c": 50.0, "pc": 0.0}}
    results = _detect_gaps(quotes, threshold_pct=3.0)
    assert results == []


def test_detect_gaps_empty():
    results = _detect_gaps({}, threshold_pct=3.0)
    assert results == []
