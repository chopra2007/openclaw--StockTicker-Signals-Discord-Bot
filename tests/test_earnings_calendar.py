"""Tests for earnings calendar pre-alert scanner."""
import pytest
from consensus_engine.scanners.earnings_calendar import _filter_upcoming_earnings


def test_filter_finds_tracked_tickers():
    earnings = [
        {"symbol": "NVDA", "date": "2026-03-30", "hour": "amc", "epsEstimate": 0.85},
        {"symbol": "RANDOM", "date": "2026-03-30", "hour": "bmo", "epsEstimate": 1.2},
        {"symbol": "TSLA", "date": "2026-03-30", "hour": "amc", "epsEstimate": 0.50},
    ]
    tracked = {"NVDA", "TSLA", "AMD"}
    result = _filter_upcoming_earnings(earnings, tracked)
    tickers = [e["symbol"] for e in result]
    assert "NVDA" in tickers
    assert "TSLA" in tickers
    assert "RANDOM" not in tickers


def test_filter_empty_earnings():
    result = _filter_upcoming_earnings([], {"NVDA"})
    assert result == []


def test_filter_no_tracked():
    earnings = [{"symbol": "NVDA", "date": "2026-03-30", "hour": "amc", "epsEstimate": 0.85}]
    result = _filter_upcoming_earnings(earnings, set())
    assert result == []
