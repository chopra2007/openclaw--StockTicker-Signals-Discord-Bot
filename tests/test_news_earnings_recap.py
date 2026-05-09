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
    """Finnhub /stock/earnings + yfinance quarterly_financials → recap dict."""
    finnhub_eps_quarters = [
        {"period": "2026-01-31", "actual": 5.16, "estimate": 4.60,
         "surprise": 0.56, "surprisePercent": 12.17, "year": 2026, "quarter": 4},
        {"period": "2025-10-31", "actual": 0.81, "estimate": 0.74,
         "surprise": 0.07, "surprisePercent": 9.46, "year": 2026, "quarter": 3},
    ]
    yfinance_revenue_history = [
        ("2026-01-31", 68132000000),
        ("2025-10-31", 57006000000),
        ("2025-07-31", 46743000000),
        ("2025-04-30", 44062000000),
        ("2025-01-31", 39330000000),
    ]

    async def _stub_finnhub(_t):
        return finnhub_eps_quarters

    async def _stub_yfinance(_t):
        return yfinance_revenue_history

    monkeypatch.setattr(
        earnings_calendar, "_fetch_finnhub_company_earnings", _stub_finnhub,
    )
    monkeypatch.setattr(
        earnings_calendar, "_fetch_yfinance_revenue_history", _stub_yfinance,
    )

    out = await earnings_calendar.fetch_recent_earnings_for_ticker("NVDA")
    assert out is not None, "should return a recap dict"
    assert out["period"] == "2026-01-31"
    assert out["eps_actual"] == 5.16
    assert out["eps_estimate"] == 4.60
    assert out["revenue_actual"] == 68132000000
    # YoY = (68.13 - 39.33) / 39.33 ≈ 73.2%
    assert 70 <= out["revenue_yoy_pct"] <= 76, (
        f"YoY should be ~73%; got {out['revenue_yoy_pct']!r}"
    )


@pytest.mark.asyncio
async def test_fetch_recent_earnings_returns_none_when_no_eps(monkeypatch):
    """No Finnhub EPS data → no recap (we don't fabricate)."""
    async def _empty(_t):
        return []
    async def _empty_rev(_t):
        return []
    monkeypatch.setattr(earnings_calendar, "_fetch_finnhub_company_earnings", _empty)
    monkeypatch.setattr(earnings_calendar, "_fetch_yfinance_revenue_history", _empty_rev)
    out = await earnings_calendar.fetch_recent_earnings_for_ticker("NVDA")
    assert out is None


@pytest.mark.asyncio
async def test_search_recent_earnings_builds_catalyst_with_revenue(monkeypatch):
    """News tier wraps the recap into CatalystResult.catalyst_body."""
    async def _stub(*_a, **_kw):
        return {
            "period": "2026-01-31",
            "eps_actual": 5.16, "eps_estimate": 4.60, "eps_surprise_pct": 12.17,
            "revenue_actual": 68132000000, "revenue_yoy_pct": 73.2,
        }
    monkeypatch.setattr(
        earnings_calendar, "fetch_recent_earnings_for_ticker", _stub,
    )

    result = await news._search_recent_earnings("NVDA")
    assert result is not None, "recent earnings present → CatalystResult expected"
    assert result.catalyst_type == "Earnings Report"
    body = result.catalyst_body or ""
    assert "$68" in body, f"revenue actual must appear; got {body!r}"
    assert "73" in body, f"YoY % must appear; got {body!r}"
    assert "5.16" in body or "EPS" in body


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
