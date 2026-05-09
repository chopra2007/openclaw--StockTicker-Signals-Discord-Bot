"""Earnings calendar pre-alert scanner.

Alerts 24 hours before tracked stocks report earnings.
Uses Finnhub /calendar/earnings endpoint (free tier).
"""

import logging
import time
from datetime import datetime, timedelta

import aiohttp

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.utils.rate_limiter import rate_limiter

log = logging.getLogger("consensus_engine.scanner.earnings")


def _filter_upcoming_earnings(earnings: list[dict], tracked_tickers: set[str]) -> list[dict]:
    """Filter earnings to only those for tracked tickers."""
    return [e for e in earnings if e.get("symbol") in tracked_tickers]


async def _fetch_finnhub_company_earnings(ticker: str) -> list[dict]:
    """Hit Finnhub /stock/earnings (symbol-specific, free tier) for EPS history.

    The /calendar/earnings endpoint caps responses at 1500 rows globally,
    which truncates wide windows down to a few days and drops major-cap
    tickers entirely. The symbol-specific endpoint always returns the
    most recent quarters for the requested ticker.
    """
    api_key = cfg.get_api_key("finnhub")
    if not api_key:
        return []
    if not await rate_limiter.acquire("finnhub"):
        return []
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://finnhub.io/api/v1/stock/earnings?symbol={ticker.upper()}&token={api_key}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    rate_limiter.report_failure("finnhub")
                    return []
                data = await resp.json()
                rate_limiter.report_success("finnhub")
                return data if isinstance(data, list) else []
    except Exception as e:
        log.debug("Finnhub /stock/earnings error for %s: %s", ticker, e)
        rate_limiter.report_failure("finnhub")
        return []


async def _fetch_yfinance_revenue_history(ticker: str) -> list[tuple[str, float]]:
    """Quarterly revenue history via yfinance, oldest→newest order swapped.

    Returns up to 5 quarters as (period_iso, revenue_float) so the recap
    builder can compute YoY = (latest − same_quarter_prior_year) / prior.
    Runs in the default executor since yfinance is blocking.
    """
    import asyncio
    loop = asyncio.get_running_loop()

    def _sync_fetch() -> list[tuple[str, float]]:
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            qf = t.quarterly_financials
            if qf is None or qf.empty:
                return []
            row_label = "Total Revenue" if "Total Revenue" in qf.index else (
                "TotalRevenue" if "TotalRevenue" in qf.index else None
            )
            if row_label is None:
                return []
            series = qf.loc[row_label]
            out: list[tuple[str, float]] = []
            for ts, val in series.items():
                try:
                    out.append((ts.strftime("%Y-%m-%d"), float(val)))
                except (TypeError, ValueError, AttributeError):
                    continue
            return out
        except Exception as e:
            log.debug("yfinance revenue fetch error for %s: %s", ticker, e)
            return []

    try:
        return await loop.run_in_executor(None, _sync_fetch)
    except Exception as e:
        log.debug("run_in_executor error for %s: %s", ticker, e)
        return []


async def fetch_recent_earnings_for_ticker(ticker: str) -> dict | None:
    """Return a recap dict for the most recent past earnings print, else None.

    Combines Finnhub `/stock/earnings` (EPS actual + estimate + surprise %)
    with yfinance quarterly_financials (revenue + YoY %). Either source
    alone is insufficient: Finnhub free tier omits revenue, and yfinance
    doesn't carry consensus estimates.
    """
    if not ticker:
        return None
    eps_quarters = await _fetch_finnhub_company_earnings(ticker)
    revenue_history = await _fetch_yfinance_revenue_history(ticker)
    if not eps_quarters:
        return None

    eps_quarters_sorted = sorted(
        eps_quarters, key=lambda r: str(r.get("period", "")), reverse=True,
    )
    latest = eps_quarters_sorted[0]
    period = str(latest.get("period", "")) or None

    revenue_actual: float | None = None
    revenue_yoy_pct: float | None = None
    if revenue_history:
        rev_sorted = sorted(revenue_history, key=lambda r: r[0], reverse=True)
        rev_latest_period, rev_latest_val = rev_sorted[0]
        revenue_actual = float(rev_latest_val)
        if len(rev_sorted) >= 5:
            _, rev_yoy_val = rev_sorted[4]
            try:
                if float(rev_yoy_val) > 0:
                    revenue_yoy_pct = (
                        (float(rev_latest_val) - float(rev_yoy_val))
                        / float(rev_yoy_val) * 100.0
                    )
            except (TypeError, ValueError, ZeroDivisionError):
                pass

    return {
        "period": period,
        "eps_actual": latest.get("actual"),
        "eps_estimate": latest.get("estimate"),
        "eps_surprise_pct": latest.get("surprisePercent"),
        "revenue_actual": revenue_actual,
        "revenue_yoy_pct": revenue_yoy_pct,
    }


async def fetch_next_earnings_for_ticker(ticker: str, days_ahead: int = 60) -> str | None:
    """Return the next earnings ISO date for `ticker` within `days_ahead`, else None.

    Used by the !all command to populate `compute_breakout_timeframe` when the
    DB's `decision_snapshots` table doesn't carry earnings metadata. Calls
    Finnhub `/calendar/earnings` over the lookahead window and picks the
    earliest entry whose symbol matches.
    """
    if not ticker:
        return None
    today = datetime.utcnow().date()
    horizon = today + timedelta(days=days_ahead)
    rows = await fetch_earnings_calendar(today.isoformat(), horizon.isoformat())
    target = ticker.upper()
    matches = [r for r in rows if str(r.get("symbol", "")).upper() == target]
    if not matches:
        return None
    matches.sort(key=lambda r: r.get("date", ""))
    return str(matches[0].get("date") or "") or None


async def fetch_earnings_calendar(from_date: str, to_date: str) -> list[dict]:
    """Fetch earnings calendar from Finnhub."""
    api_key = cfg.get_api_key("finnhub")
    if not api_key:
        return []
    if not await rate_limiter.acquire("finnhub"):
        return []

    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://finnhub.io/api/v1/calendar/earnings?from={from_date}&to={to_date}&token={api_key}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    log.warning("Finnhub earnings calendar returned %d", resp.status)
                    rate_limiter.report_failure("finnhub")
                    return []
                data = await resp.json()
                rate_limiter.report_success("finnhub")
                return data.get("earningsCalendar", [])
    except Exception as e:
        log.warning("Finnhub earnings calendar error: %s", e)
        rate_limiter.report_failure("finnhub")
        return []


async def scan_upcoming_earnings() -> list[dict]:
    """Scan for earnings reports happening tomorrow for tracked tickers."""
    tracked = set()
    try:
        conn = await db.get_db()
        cutoff = time.time() - 7 * 86400
        cursor = await conn.execute(
            "SELECT DISTINCT ticker FROM alert_messages WHERE created_at >= ?",
            (cutoff,),
        )
        rows = await cursor.fetchall()
        tracked = {r["ticker"] for r in rows}
    except Exception as e:
        log.debug("Error fetching tracked tickers: %s", e)

    if not tracked:
        return []

    tomorrow = datetime.utcnow() + timedelta(days=1)
    from_date = tomorrow.strftime("%Y-%m-%d")
    to_date = from_date

    earnings = await fetch_earnings_calendar(from_date, to_date)
    filtered = _filter_upcoming_earnings(earnings, tracked)

    if filtered:
        log.info("Earnings pre-alert: %d tracked tickers reporting tomorrow", len(filtered))
    return filtered


def format_earnings_alert(earnings: list[dict]) -> str:
    """Format earnings pre-alert as a Discord message."""
    if not earnings:
        return "No tracked tickers reporting earnings tomorrow."
    lines = ["**Earnings Pre-Alert -- Tomorrow**"]
    for e in earnings[:15]:
        symbol = e.get("symbol", "?")
        hour = e.get("hour", "?")
        timing = "before open" if hour == "bmo" else "after close" if hour == "amc" else hour
        eps_est = e.get("epsEstimate")
        eps_str = f" (EPS est: ${eps_est:.2f})" if eps_est else ""
        lines.append(f"`${symbol}` reports **{timing}**{eps_str}")
    return "\n".join(lines)
