"""Tests for earnings calendar pre-alert scanner."""
from datetime import date

import pytest
from consensus_engine.scanners import earnings_calendar
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


@pytest.mark.asyncio
async def test_next_earnings_rejects_past_and_uses_earliest_future(monkeypatch):
    seen = {}

    async def _calendar(from_date, to_date, *, symbol=None):
        seen["range"] = (from_date, to_date)
        seen["symbol"] = symbol
        return [
            {"symbol": "NVDA", "date": "2026-08-15"},
            {"symbol": "NVDA", "date": "2026-08-27"},
            {"symbol": "AMD", "date": "2026-08-20"},
            {"symbol": "NVDA", "date": "2026-08-20"},
        ]

    monkeypatch.setattr(earnings_calendar, "fetch_earnings_calendar", _calendar)

    result = await earnings_calendar.fetch_next_earnings_for_ticker(
        "nvda", days_ahead=90, as_of=date(2026, 8, 16),
    )

    assert result == "2026-08-20"
    assert seen["range"] == ("2026-08-16", "2026-11-14")
    assert seen["symbol"] == "nvda"


@pytest.mark.asyncio
async def test_next_earnings_returns_none_without_upcoming_match(monkeypatch):
    async def _calendar(_from_date, _to_date, *, symbol=None):
        assert symbol == "SPY"
        return [
            {"symbol": "SPY", "date": "2026-08-15"},
            {"symbol": "NVDA", "date": "not-a-date"},
        ]

    monkeypatch.setattr(earnings_calendar, "fetch_earnings_calendar", _calendar)

    result = await earnings_calendar.fetch_next_earnings_for_ticker(
        "SPY", days_ahead=90, as_of=date(2026, 8, 16),
    )
    assert result is None
