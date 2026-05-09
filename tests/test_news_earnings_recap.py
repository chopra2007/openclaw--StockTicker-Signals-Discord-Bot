"""Gap 2 — News scanner must surface the most recent earnings print.

The pre-fix bot narrative for NVDA cited $213M options flow and YouTube
analyst takes instead of the Q4 FY26 earnings ($68.1B revenue, +73 % YoY).
Finnhub's `company-news` endpoint returns headlines but its summaries are
~one-sentence and rarely include the revenue / EPS numbers.

Fix: a new highest-priority tier in `news_cascade` that calls Finnhub
`/calendar/earnings` for a backwards 90-day window. When a print is found
we synthesize a CatalystResult whose `catalyst_body` includes EPS actual /
estimate and revenue actual / estimate. The downstream synth prompt then
gets the real numbers instead of having to guess from headline keywords.

Acceptance per `RESUME-after-compact.md`:
> for NVDA, assert data["news_catalyst"].catalyst_body contains either
> "$68" or "73%" somewhere.
"""
from __future__ import annotations

import pytest

from consensus_engine.scanners import earnings_calendar, news


@pytest.mark.asyncio
async def test_fetch_recent_earnings_returns_latest_print(monkeypatch):
    """`/calendar/earnings` over backwards window → latest past print dict."""
    fake_calendar = [
        {"symbol": "NVDA", "date": "2025-11-19",
         "epsActual": 0.81, "epsEstimate": 0.74,
         "revenueActual": 35080000000, "revenueEstimate": 33270000000, "hour": "amc"},
        {"symbol": "NVDA", "date": "2026-02-25",
         "epsActual": 5.16, "epsEstimate": 4.60,
         "revenueActual": 68132000000, "revenueEstimate": 64850000000, "hour": "amc"},
        {"symbol": "AAPL", "date": "2026-01-30",
         "epsActual": 2.40, "epsEstimate": 2.35},
    ]

    async def _stub(*_a, **_kw):
        return fake_calendar

    monkeypatch.setattr(earnings_calendar, "fetch_earnings_calendar", _stub)

    out = await earnings_calendar.fetch_recent_earnings_for_ticker("NVDA", days_back=120)
    assert out is not None, "should find NVDA's most recent past print"
    assert out["date"] == "2026-02-25", "should pick the most-recent past date"
    assert out["eps_actual"] == 5.16
    assert out["revenue_actual"] == 68132000000
    assert out["revenue_estimate"] == 64850000000


@pytest.mark.asyncio
async def test_fetch_recent_earnings_skips_future_prints(monkeypatch):
    """Only past prints qualify as 'recent'; future prints belong to next-earnings."""
    from datetime import datetime, timedelta
    future_date = (datetime.utcnow() + timedelta(days=20)).date().isoformat()

    async def _stub(*_a, **_kw):
        return [{"symbol": "NVDA", "date": future_date, "epsActual": None, "revenueActual": None}]

    monkeypatch.setattr(earnings_calendar, "fetch_earnings_calendar", _stub)
    out = await earnings_calendar.fetch_recent_earnings_for_ticker("NVDA")
    assert out is None, "future prints must not be returned as recent earnings"


@pytest.mark.asyncio
async def test_search_recent_earnings_builds_catalyst_with_revenue(monkeypatch):
    """News tier wraps the recap into CatalystResult.catalyst_body."""
    async def _stub(*_a, **_kw):
        return {
            "date": "2026-02-25",
            "eps_actual": 5.16, "eps_estimate": 4.60,
            "revenue_actual": 68132000000, "revenue_estimate": 64850000000,
            "hour": "amc",
        }
    monkeypatch.setattr(
        earnings_calendar, "fetch_recent_earnings_for_ticker", _stub,
    )

    result = await news._search_recent_earnings("NVDA")
    assert result is not None, "recent earnings present → CatalystResult expected"
    assert result.catalyst_type == "Earnings Report"
    body = result.catalyst_body or ""
    assert "$68" in body, f"revenue actual must appear; got {body!r}"
    # Beat-magnitude commentary is computed: (68.13 - 64.85) / 64.85 ≈ 5%
    # but %YoY isn't in /calendar/earnings — we just need the absolute number
    # in there. The prompt will let the LLM cite it.
    assert "EPS" in body or "eps" in body.lower()
    assert "5.16" in body


@pytest.mark.asyncio
async def test_news_cascade_runs_recent_earnings_first(monkeypatch):
    """`news_cascade` must call _search_recent_earnings before legacy tiers."""
    seen: list[str] = []

    async def _earnings_tier(ticker):
        seen.append("recent_earnings")
        return news._build_catalyst(
            ticker, "NVDA Q4 FY26 reported 2026-02-25",
            "https://finnhub.io/", "Earnings Report",
            body="Q4 reported 2026-02-25 — Revenue $68.13B vs est $64.85B; EPS 5.16 vs est 4.60.",
        )

    async def _other_tier(_ticker):
        seen.append("other")
        return None

    monkeypatch.setattr(news, "_search_recent_earnings", _earnings_tier)
    monkeypatch.setattr(news, "_search_finnhub_news", _other_tier)
    monkeypatch.setattr(news, "_search_google_news_rss", _other_tier)
    monkeypatch.setattr(news, "_search_brave", _other_tier)
    monkeypatch.setattr(news, "_search_searxng", _other_tier)

    result = await news.news_cascade("NVDA")
    assert seen[0] == "recent_earnings", (
        f"recent_earnings tier must run FIRST; got order {seen}"
    )
    assert result is not None
    assert "$68" in (result.catalyst_body or "")
