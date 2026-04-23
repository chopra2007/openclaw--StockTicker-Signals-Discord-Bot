"""Unit tests for the Stage C catalyst resolver.

Covers:
- Publish-ts parsing (ISO with Z suffix)
- Relative weekday resolution
- Month/day without year (same year vs next year)
- Absolute ISO pass-through
- Unparseable inputs → None
- Earnings verification via mocked fetch_earnings_calendar
- Batch resolve+verify orchestration
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine.analysis.catalyst_resolver import (
    _parse_publish_ts,
    _resolve_relative_date,
    _verify_earnings,
    resolve_and_verify_catalysts,
)
from consensus_engine.models import CandidateCatalyst


# 2026-04-17 is a Friday.
PUB_FRI = datetime(2026, 4, 17, 14, 30, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Publish ts parsing
# ---------------------------------------------------------------------------

def test_parse_publish_ts_iso_z():
    dt = _parse_publish_ts("2026-04-17T14:30:45Z")
    assert dt.tzinfo is not None
    assert dt.year == 2026 and dt.month == 4 and dt.day == 17


def test_parse_publish_ts_empty_falls_back_to_now():
    dt = _parse_publish_ts("")
    assert dt.tzinfo is not None  # still aware


def test_parse_publish_ts_naive_assumed_utc():
    dt = _parse_publish_ts("2026-04-17T14:30:00")
    assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# Relative weekday resolution
# ---------------------------------------------------------------------------

def test_resolve_next_wednesday_from_friday():
    # Friday 2026-04-17 → "next Wednesday" should resolve to 2026-04-22
    # (the upcoming Wednesday, 5 days later).
    out = _resolve_relative_date("next Wednesday", PUB_FRI)
    assert out == "2026-04-22"


def test_resolve_this_tuesday_from_friday():
    # Friday 2026-04-17 → "this Tuesday" — past this week, so goes to 2026-04-21
    out = _resolve_relative_date("this Tuesday", PUB_FRI)
    assert out == "2026-04-21"


def test_resolve_bare_weekday_forward():
    # Bare "Monday" on Friday → next Monday 2026-04-20
    out = _resolve_relative_date("Monday", PUB_FRI)
    assert out == "2026-04-20"


def test_resolve_next_week_anchor_monday():
    out = _resolve_relative_date("next week", PUB_FRI)
    # Monday 2026-04-20 — the Monday after the publish Friday
    assert out == "2026-04-20"


# ---------------------------------------------------------------------------
# Month/day resolution
# ---------------------------------------------------------------------------

def test_resolve_month_day_no_year_same_year():
    out = _resolve_relative_date("April 29", PUB_FRI)
    assert out == "2026-04-29"


def test_resolve_month_day_no_year_next_year():
    # January 15 when publish date is 2026-04-17 is in the past → 2027.
    out = _resolve_relative_date("January 15", PUB_FRI)
    assert out == "2027-01-15"


def test_resolve_absolute_iso_passthrough():
    out = _resolve_relative_date("2026-04-29", PUB_FRI)
    assert out == "2026-04-29"


def test_resolve_with_year_respects_year():
    out = _resolve_relative_date("April 29, 2027", PUB_FRI)
    assert out == "2027-04-29"


def test_resolve_unparseable_returns_none():
    out = _resolve_relative_date("bananaland", PUB_FRI)
    assert out is None


def test_resolve_empty_returns_none():
    assert _resolve_relative_date("", PUB_FRI) is None
    assert _resolve_relative_date(None, PUB_FRI) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Earnings verification (Finnhub mocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_earnings_exact_match_confirms():
    rows = [{"symbol": "MSFT", "date": "2026-04-29", "epsEstimate": 3.21}]
    with patch(
        "consensus_engine.analysis.catalyst_resolver.fetch_earnings_calendar",
        new=AsyncMock(return_value=rows),
    ):
        result = await _verify_earnings("MSFT", "2026-04-29")
    assert result == 1


@pytest.mark.asyncio
async def test_verify_earnings_within_three_days_confirms():
    rows = [{"symbol": "MSFT", "date": "2026-04-30"}]
    with patch(
        "consensus_engine.analysis.catalyst_resolver.fetch_earnings_calendar",
        new=AsyncMock(return_value=rows),
    ):
        result = await _verify_earnings("MSFT", "2026-04-29")
    assert result == 1


@pytest.mark.asyncio
async def test_verify_earnings_other_ticker_contradicts():
    rows = [{"symbol": "AAPL", "date": "2026-04-29"}]
    with patch(
        "consensus_engine.analysis.catalyst_resolver.fetch_earnings_calendar",
        new=AsyncMock(return_value=rows),
    ):
        result = await _verify_earnings("MSFT", "2026-04-29")
    assert result == -1


@pytest.mark.asyncio
async def test_verify_earnings_empty_is_unverified():
    with patch(
        "consensus_engine.analysis.catalyst_resolver.fetch_earnings_calendar",
        new=AsyncMock(return_value=[]),
    ):
        result = await _verify_earnings("MSFT", "2026-04-29")
    assert result == 0


@pytest.mark.asyncio
async def test_verify_earnings_fetch_error_is_unverified():
    with patch(
        "consensus_engine.analysis.catalyst_resolver.fetch_earnings_calendar",
        new=AsyncMock(side_effect=RuntimeError("network")),
    ):
        result = await _verify_earnings("MSFT", "2026-04-29")
    assert result == 0


@pytest.mark.asyncio
async def test_verify_earnings_invalid_date_is_unverified():
    result = await _verify_earnings("MSFT", "not-a-date")
    assert result == 0


# ---------------------------------------------------------------------------
# resolve_and_verify_catalysts — orchestration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_and_verify_batch_mixed():
    """Verify 3 candidates: one earnings (verified), one macro (not checked),
    one unparseable (no resolved_date, no verify attempted)."""
    candidates = [
        CandidateCatalyst(
            ticker="MSFT", catalyst_type="earnings",
            mentioned_date="April 29",
        ),
        CandidateCatalyst(
            ticker="SPY", catalyst_type="fed",
            mentioned_date="next Wednesday",
        ),
        CandidateCatalyst(
            ticker="AAPL", catalyst_type="earnings",
            mentioned_date="bananaland",
        ),
    ]
    rows = [{"symbol": "MSFT", "date": "2026-04-29"}]
    with patch(
        "consensus_engine.analysis.catalyst_resolver.fetch_earnings_calendar",
        new=AsyncMock(return_value=rows),
    ) as mock_fetch:
        out = await resolve_and_verify_catalysts(candidates, "2026-04-17T14:30:00Z")

    by_ticker = {c.ticker: c for c in out}

    msft = by_ticker["MSFT"]
    assert msft.resolved_date == "2026-04-29"
    assert msft.verified == 1

    spy = by_ticker["SPY"]
    assert spy.resolved_date == "2026-04-22"
    assert spy.verified == 0  # macro catalyst — not Finnhub-verified

    aapl = by_ticker["AAPL"]
    assert aapl.resolved_date is None
    assert aapl.verified == 0

    # Finnhub should only have been consulted once (for MSFT earnings).
    assert mock_fetch.await_count == 1


@pytest.mark.asyncio
async def test_resolve_and_verify_skips_fetch_for_non_earnings():
    candidates = [
        CandidateCatalyst(
            ticker="SPY", catalyst_type="cpi",
            mentioned_date="next Tuesday",
        ),
    ]
    with patch(
        "consensus_engine.analysis.catalyst_resolver.fetch_earnings_calendar",
        new=AsyncMock(return_value=[]),
    ) as mock_fetch:
        out = await resolve_and_verify_catalysts(candidates, "2026-04-17T00:00:00Z")
    assert mock_fetch.await_count == 0
    assert out[0].resolved_date == "2026-04-21"
    assert out[0].verified == 0


@pytest.mark.asyncio
async def test_resolve_and_verify_empty_list():
    out = await resolve_and_verify_catalysts([], "2026-04-17T00:00:00Z")
    assert out == []
