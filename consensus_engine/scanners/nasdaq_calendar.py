"""NASDAQ free-tier calendar scanner — forward-dated catalysts.

Fetches earnings + dividends from the public NASDAQ JSON endpoints to
populate forward-dated catalysts beyond what Finnhub returns. Pre-flighted
2026-05-19 from this VPS — all three endpoints return 200 with no auth
required (TODO #13 discovery run).

Endpoints:
  https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD
  https://api.nasdaq.com/api/calendar/dividends?date=YYYY-MM-DD

Cache: in-memory per-date for the lifetime of the process; aggregator
calls happen at most once per ticker per !all invocation.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from consensus_engine.utils.http import get_session

log = logging.getLogger("consensus_engine.scanner.nasdaq_calendar")

_BASE = "https://api.nasdaq.com/api/calendar"
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Per-process cache: (kind, date_str) -> list[dict]. Cleared on engine restart.
_cache: dict[tuple[str, str], list[dict]] = {}


@dataclass
class CatalystEvent:
    """A forward-dated catalyst event for a ticker.

    Used by `compute_next_catalyst` to merge earnings + dividends + options
    expiry into a single ordered timeline.
    """
    date: date
    kind: str           # "earnings" | "dividend_ex" | "ipo" | "options_expiry"
    mechanism: str      # human-readable: "Q4 2026 earnings", "ex-div $1.50"
    source: str         # "nasdaq_calendar" | "finnhub" | "options"


async def _fetch_nasdaq(kind: str, date_str: str) -> list[dict]:
    """Fetch one (kind, date) page from NASDAQ. Returns [] on any failure.

    NASDAQ's API gates requests by User-Agent: a bare Python aiohttp UA
    gets 403. The desktop Chrome UA above worked in Pass 0C pre-flight
    and during initial Commit 4 testing.
    """
    cache_key = (kind, date_str)
    if cache_key in _cache:
        return _cache[cache_key]

    url = f"{_BASE}/{kind}?date={date_str}"
    try:
        session = await get_session()
        async with session.get(
            url, headers={"User-Agent": _UA}, timeout=10,
        ) as resp:
            if resp.status != 200:
                log.debug("nasdaq_calendar: %s %s -> HTTP %d", kind, date_str, resp.status)
                _cache[cache_key] = []
                return []
            data = await resp.json()
    except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
        log.debug("nasdaq_calendar: %s %s failed: %s", kind, date_str, exc)
        _cache[cache_key] = []
        return []

    rows = ((data or {}).get("data") or {}).get("rows") or []
    if not isinstance(rows, list):
        rows = []
    _cache[cache_key] = rows
    return rows


async def fetch_forward_catalysts(
    ticker: str,
    forward_days: int = 60,
) -> list[CatalystEvent]:
    """Return forward-dated catalyst events for `ticker` over the next N days.

    Pulls earnings + dividend ex-dates from NASDAQ. Skips IPOs (rare for
    existing tickers and noisy). Returns events sorted by date ascending.

    Cheap when most dates are cache hits; expensive on cold-start (one
    HTTPS round-trip per date per kind = up to 120 requests for the
    default 60-day window on first call after a process restart).
    """
    if not ticker:
        return []
    ticker_u = ticker.upper()
    today = datetime.utcnow().date()
    end = today + timedelta(days=forward_days)

    events: list[CatalystEvent] = []
    # Two kinds × N dates. Use gather for parallel fetches.
    tasks = []
    date_strs = []
    d = today
    while d <= end:
        date_strs.append(d.isoformat())
        d = d + timedelta(days=1)

    for kind in ("earnings", "dividends"):
        for ds in date_strs:
            tasks.append(_fetch_nasdaq(kind, ds))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    idx = 0
    for kind in ("earnings", "dividends"):
        for ds in date_strs:
            page = results[idx]
            idx += 1
            if isinstance(page, Exception) or not isinstance(page, list):
                continue
            ev_date = datetime.strptime(ds, "%Y-%m-%d").date()
            for row in page:
                if not isinstance(row, dict):
                    continue
                if (row.get("symbol") or "").upper() != ticker_u:
                    continue
                if kind == "earnings":
                    fq = row.get("fiscalQuarterEnding") or ""
                    eps_est = row.get("epsForecast") or ""
                    time_of_day = (row.get("time") or "").lower()
                    when = (
                        " (pre-market)" if "pre" in time_of_day
                        else " (after close)" if any(t in time_of_day for t in ("after", "amc"))
                        else ""
                    )
                    fq_label = f"Q{fq.split('/')[0]}" if "/" in fq else "Q?"
                    mech = f"{fq_label} earnings{when}"
                    if eps_est:
                        mech += f" (EPS est {eps_est})"
                    events.append(CatalystEvent(
                        date=ev_date, kind="earnings",
                        mechanism=mech, source="nasdaq_calendar",
                    ))
                elif kind == "dividends":
                    amt = row.get("dividend_Rate") or row.get("dividendRate") or row.get("amount")
                    mech = f"ex-dividend"
                    if amt:
                        try:
                            mech += f" ${float(amt):.2f}"
                        except (TypeError, ValueError):
                            pass
                    events.append(CatalystEvent(
                        date=ev_date, kind="dividend_ex",
                        mechanism=mech, source="nasdaq_calendar",
                    ))

    events.sort(key=lambda e: e.date)
    return events


def next_weekly_options_expiry(today: Optional[date] = None) -> CatalystEvent:
    """Return the next-Friday options expiry as a CatalystEvent.

    Used by aggregator as a guaranteed forward-catalyst fallback for tickers
    without earnings/dividends in the next 60 days (AMD/TSLA in the 2026-05-18
    blind-compare both had zero forward catalysts otherwise). Every US-listed
    optionable stock has Friday weekly expirations — mechanical, always
    available, no API call needed.
    """
    today = today or datetime.utcnow().date()
    # weekday(): Mon=0, Fri=4
    days_until_friday = (4 - today.weekday()) % 7
    if days_until_friday == 0:
        days_until_friday = 7  # past today's Friday → use next week's
    expiry = today + timedelta(days=days_until_friday)
    return CatalystEvent(
        date=expiry,
        kind="options_expiry",
        mechanism=f"weekly options expiry on {expiry.isoformat()}",
        source="calendar_rule",
    )
