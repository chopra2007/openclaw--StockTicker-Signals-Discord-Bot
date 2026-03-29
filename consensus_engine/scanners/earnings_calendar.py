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

    watchlist = cfg.get("premarket.watchlist", [])
    tracked.update(watchlist)

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
