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

from datetime import date

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

    async def _stub_calendar(_from_date, _to_date, *, symbol=None):
        assert symbol == "NVDA"
        return [{"symbol": "NVDA", "date": "2026-08-15"}]

    monkeypatch.setattr(
        earnings_calendar, "_fetch_finnhub_company_earnings", _stub_finnhub,
    )
    monkeypatch.setattr(
        earnings_calendar, "_fetch_yfinance_revenue_history", _stub_yfinance,
    )
    monkeypatch.setattr(earnings_calendar, "_pacific_today", lambda: date(2026, 8, 16))
    monkeypatch.setattr(earnings_calendar, "fetch_earnings_calendar", _stub_calendar)

    out = await earnings_calendar.fetch_recent_earnings_for_ticker("NVDA")
    assert out is not None, "should return a recap dict"
    assert out["period"] == "2026-01-31"
    assert out["report_date"] == "2026-08-15"
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
async def test_fetch_recent_earnings_suppresses_when_pending_quarter(monkeypatch):
    """Quarter ended but actual=None → pre-earnings mode → return None.

    Mirrors the NVDA May-20-2026 incident: Q4 FY26 (period 2026-01-26) was
    already reported, but Q1 FY27 (period 2026-04-27) had ended without an
    actual EPS yet.  The function must return None rather than surfacing the
    stale Q4 recap.
    """
    from datetime import date, timedelta
    import consensus_engine.scanners.earnings_calendar as ec

    # Simulate "today" as May 20 2026 by patching datetime inside the module
    past_period = (date.today() - timedelta(days=89)).isoformat()   # reported quarter
    pending_period = (date.today() - timedelta(days=23)).isoformat()  # ended, not reported

    finnhub_quarters = [
        {"period": past_period, "actual": 5.16, "estimate": 4.60,
         "surprise": 0.56, "surprisePercent": 12.17},
        {"period": pending_period, "actual": None, "estimate": 4.90,
         "surprise": None, "surprisePercent": None},
    ]

    async def _stub_finnhub(_t):
        return finnhub_quarters

    async def _stub_yfinance(_t):
        return []

    monkeypatch.setattr(ec, "_fetch_finnhub_company_earnings", _stub_finnhub)
    monkeypatch.setattr(ec, "_fetch_yfinance_revenue_history", _stub_yfinance)

    out = await ec.fetch_recent_earnings_for_ticker("NVDA")
    assert out is None, (
        "should return None when a quarter has ended but actual EPS is missing "
        "(ticker is in pre-earnings mode)"
    )


@pytest.mark.asyncio
async def test_fetch_recent_earnings_ignores_future_period_quarters(monkeypatch):
    """Quarters whose period date is in the future are ignored entirely."""
    from datetime import date, timedelta
    import consensus_engine.scanners.earnings_calendar as ec

    past_period = (date.today() - timedelta(days=89)).isoformat()
    future_period = (date.today() + timedelta(days=30)).isoformat()

    finnhub_quarters = [
        {"period": past_period, "actual": 5.16, "estimate": 4.60,
         "surprise": 0.56, "surprisePercent": 12.17},
        {"period": future_period, "actual": None, "estimate": 5.50,
         "surprise": None, "surprisePercent": None},
    ]

    async def _stub_finnhub(_t):
        return finnhub_quarters

    async def _stub_yfinance(_t):
        return []

    async def _stub_calendar(_from_date, _to_date, *, symbol=None):
        assert symbol == "NVDA"
        return [{"symbol": "NVDA", "date": date.today().isoformat()}]

    monkeypatch.setattr(ec, "_fetch_finnhub_company_earnings", _stub_finnhub)
    monkeypatch.setattr(ec, "_fetch_yfinance_revenue_history", _stub_yfinance)
    monkeypatch.setattr(ec, "fetch_earnings_calendar", _stub_calendar)

    out = await ec.fetch_recent_earnings_for_ticker("NVDA")
    # future-period quarter is dropped; past reported quarter has no pending
    # siblings → should return the past quarter's recap
    assert out is not None, "past reported quarter should still be returned"
    assert out["period"] == past_period
    assert out["eps_actual"] == 5.16


@pytest.mark.asyncio
async def test_search_recent_earnings_builds_catalyst_with_revenue(monkeypatch):
    """News tier wraps the recap into CatalystResult.catalyst_body."""
    async def _stub(*_a, **_kw):
        return {
            "period": "2026-01-31",
            "report_date": "2026-08-15",
            "eps_actual": 5.16, "eps_estimate": 4.60, "eps_surprise_pct": 12.17,
            "revenue_actual": 68132000000, "revenue_yoy_pct": 73.2,
        }
    monkeypatch.setattr(
        earnings_calendar, "fetch_recent_earnings_for_ticker", _stub,
    )

    result = await news._search_recent_earnings("NVDA", as_of=date(2026, 8, 16))
    assert result is not None, "recent earnings present → CatalystResult expected"
    assert result.catalyst_type == "Earnings Report"
    body = result.catalyst_body or ""
    assert "$68" in body, f"revenue actual must appear; got {body!r}"
    assert "73" in body, f"YoY % must appear; got {body!r}"
    assert "5.16" in body or "EPS" in body


@pytest.mark.asyncio
async def test_search_recent_earnings_skips_stale_report(monkeypatch):
    async def _stub(*_a, **_kw):
        return {"period": "2026-06-30", "report_date": "2026-08-08"}

    monkeypatch.setattr(
        earnings_calendar, "fetch_recent_earnings_for_ticker", _stub,
    )

    result = await news._search_recent_earnings("NVDA", as_of=date(2026, 8, 16))
    assert result is None


@pytest.mark.asyncio
async def test_search_recent_earnings_keeps_seven_day_old_report(monkeypatch):
    async def _stub(*_a, **_kw):
        return {
            "period": "2026-06-30",
            "report_date": "2026-08-09",
            "eps_actual": 1.87,
        }

    monkeypatch.setattr(
        earnings_calendar, "fetch_recent_earnings_for_ticker", _stub,
    )

    result = await news._search_recent_earnings("NVDA", as_of=date(2026, 8, 16))
    assert result is not None


@pytest.mark.asyncio
async def test_search_recent_earnings_rejects_missing_report_date(monkeypatch):
    async def _stub(*_a, **_kw):
        return {"period": "2026-06-30", "eps_actual": 1.87}

    monkeypatch.setattr(
        earnings_calendar, "fetch_recent_earnings_for_ticker", _stub,
    )

    result = await news._search_recent_earnings("NVDA", as_of=date(2026, 8, 16))
    assert result is None


@pytest.mark.asyncio
async def test_old_quarter_reported_yesterday_is_fresh(monkeypatch):
    async def _stub(*_a, **_kw):
        return {
            "period": "2026-01-31",
            "report_date": "2026-08-15",
            "eps_actual": 5.16,
        }

    monkeypatch.setattr(
        earnings_calendar, "fetch_recent_earnings_for_ticker", _stub,
    )

    result = await news._search_recent_earnings("NVDA", as_of=date(2026, 8, 16))
    assert result is not None
    assert result.eps_period == "2026-01-31"


@pytest.mark.asyncio
async def test_news_cascade_uses_next_tier_after_stale_earnings(monkeypatch):
    async def _stale_recap(*_a, **_kw):
        return {"period": "2026-06-30", "report_date": "2026-07-01"}

    async def _fresh_news(ticker):
        return news._build_catalyst(
            ticker,
            "NVDA launches a new product",
            "https://www.reuters.com/example",
            "Product Launch",
        )

    async def _none(_ticker):
        return None

    monkeypatch.setattr(
        earnings_calendar, "fetch_recent_earnings_for_ticker", _stale_recap,
    )
    monkeypatch.setattr(news, "_search_finnhub_news", _fresh_news)
    monkeypatch.setattr(news, "_search_google_news_rss", _none)
    monkeypatch.setattr(news, "_search_brave", _none)
    monkeypatch.setattr(news, "_search_searxng", _none)
    monkeypatch.setattr(
        news.cfg,
        "get",
        lambda key, default=None: False if key == "news_cascade.parallel" else default,
    )

    result = await news.news_cascade("NVDA")
    assert result is not None
    assert result.catalyst_type == "Product Launch"


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
