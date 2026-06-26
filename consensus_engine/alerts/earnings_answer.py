"""Deterministic answer for "when are earnings for X?" questions.

Why this exists: the @-mention / !ask path hands natural-language questions
to a free-roaming LLM agent. Asked "when are earnings for URI?" the agent
called the Finnhub-backed ``fetch_next_earnings_for_ticker()`` — which returns
None on the free tier — then *fabricated* a date ("2026-06-16 ... tomorrow")
and leaked the tool name (Discord msg 1519867430443159555), even though the
current date was injected into its prompt.

This module intercepts the common earnings-date question and answers it
directly from yfinance's analyst-estimate calendar: short, correct, and
hedged when the date isn't officially confirmed — before the agent ever runs.
Once we know it's an earnings-date question about a real ticker, we own the
reply so the agent can never fabricate one.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timezone

log = logging.getLogger("consensus_engine.earnings_answer")

# A standalone single uppercase letter — the shared chat resolver only matches
# plain tokens of 2+ letters, so it misses one-letter tickers (F=Ford, T=AT&T,
# V=Visa). We accept them here, gated by the Finnhub real-company name check.
_SINGLE_LETTER = re.compile(r"(?<![\w$])\$?([A-Z])(?![\w])")

# The question is about WHEN earnings happen.
_TIMING_CUES = (
    "when", "next", "date", "report", "reporting", "reports", "upcoming",
    "schedule", "scheduled", "due", "come out", "coming", "announce", "release",
)
# Result / history / move questions are NOT date questions — let the agent or
# !em handle those, so we don't hijack "how did X's last earnings go?".
_NEGATIVE_CUES = (
    "last", "previous", "recent", "results", "result", "beat", "missed",
    "how much", "how did", "revenue", "history", "past", "recap",
    "expected move", "move", "react",
)


def is_earnings_date_query(text: str) -> bool:
    """True if `text` is asking when a stock's earnings are."""
    if not text:
        return False
    t = text.lower()
    if "earnings" not in t:
        return False
    if any(neg in t for neg in _NEGATIVE_CUES):
        return False
    return any(cue in t for cue in _TIMING_CUES)


async def _company_name(sym: str) -> str | None:
    """Real listed-company name for `sym` via the shared Finnhub/cache name gate."""
    from consensus_engine import db
    from consensus_engine.utils.tickers import validate_ticker_market_cap
    meta = await db.get_ticker_metadata(sym, max_age_days=7)
    if meta is None:
        try:
            await validate_ticker_market_cap(sym)  # warms the cache (name+exchange)
        except Exception:
            pass
        meta = await db.get_ticker_metadata(sym, max_age_days=7)
    return (meta or {}).get("name") or None


async def _resolve_ticker(text: str) -> tuple[str | None, str | None]:
    """Return (symbol, company_name) for the first real ticker named in `text`."""
    try:
        from consensus_engine.utils.tickers import resolve_chat_ticker_anchors
        anchors = await resolve_chat_ticker_anchors(text, cap=3)
    except Exception as e:  # pragma: no cover - defensive
        log.debug("ticker resolution failed: %s", e)
        anchors = []
    if anchors:
        a = anchors[0]
        return a.get("symbol"), (a.get("name") or None)

    # Fallback: a one-letter ticker the shared resolver's regex can't see.
    # Only runs once we already know this is an earnings-date question, so a lone
    # capital letter is almost certainly the stock the user means.
    from consensus_engine.utils.tickers import _CHAT_GRAMMAR_WORDS
    for m in _SINGLE_LETTER.finditer(text):
        sym = m.group(1)
        if sym in _CHAT_GRAMMAR_WORDS:  # "A", "I"
            continue
        try:
            name = await _company_name(sym)
        except Exception as e:  # pragma: no cover - defensive
            log.debug("single-letter name lookup failed for %s: %s", sym, e)
            name = None
        if name:
            return sym, name
    return None, None


def _sync_fetch_earnings(ticker: str) -> tuple[list[date], bool | None, list[date]]:
    """Blocking yfinance lookup → (quoteSummary dates, is_estimate, get_earnings_dates dates).

    Yahoo's quoteSummary calendarEvents carries the next earnings date(s) AND
    ``isEarningsDateEstimate`` — the only free signal that tells a company-confirmed
    date (MRK) from an analyst estimate (URI). ``get_earnings_dates`` is a second
    date source: quoteSummary sometimes holds a stale *past* date (seen on TLRY)
    while the real upcoming row is only in get_earnings_dates.
    """
    import yfinance as yf

    t = yf.Ticker(ticker)
    qs_dates: list[date] = []
    is_estimate: bool | None = None
    gd_dates: list[date] = []

    try:
        url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker.upper()}"
        params = {"modules": "calendarEvents", "corsDomain": "finance.yahoo.com"}
        raw = t._data.get_raw_json(url, params=params)
        earn = raw["quoteSummary"]["result"][0]["calendarEvents"]["earnings"]
        for entry in earn.get("earningsDate", []):
            fmt = entry.get("fmt")
            if fmt:
                try:
                    qs_dates.append(date.fromisoformat(fmt))
                except ValueError:
                    pass
        flag = earn.get("isEarningsDateEstimate")
        if isinstance(flag, bool):
            is_estimate = flag
    except Exception as e:  # pragma: no cover - network/library/internal-api variance
        log.debug("yahoo quoteSummary failed for %s: %s", ticker, e)

    try:
        df = t.get_earnings_dates(limit=8)
        if df is not None and not df.empty:
            for idx, _row in df.iterrows():
                d = idx.date() if hasattr(idx, "date") else None
                if d:
                    gd_dates.append(d)
    except Exception as e:  # pragma: no cover - network/library variance
        log.debug("yfinance get_earnings_dates failed for %s: %s", ticker, e)

    return qs_dates, is_estimate, gd_dates


async def fetch_earnings_outlook(ticker: str) -> dict | None:
    """Return {ticker, dates, days_until, confirmed} for the next earnings, else None.

    `dates` is one date, or a [start, end] window when Yahoo gives a two-date
    range. `confirmed` is True only when Yahoo flags the upcoming date as
    company-confirmed (not an analyst estimate).
    """
    loop = asyncio.get_running_loop()
    try:
        qs_dates, is_estimate, gd_dates = await loop.run_in_executor(
            None, _sync_fetch_earnings, ticker)
    except Exception as e:  # pragma: no cover - defensive
        log.debug("earnings outlook fetch failed for %s: %s", ticker, e)
        return None

    today = datetime.now(timezone.utc).date()
    qs_future = sorted({d for d in qs_dates if d >= today})
    all_future = sorted({d for d in (qs_dates + gd_dates) if d >= today})
    if not all_future:
        return None

    if len(qs_future) >= 2 and qs_future[0] != qs_future[1]:
        dates = qs_future[:2]          # explicit estimate window → never "confirmed"
        confirmed = False
    elif qs_future:
        dates = [qs_future[0]]         # Yahoo's next date + its confirm flag
        confirmed = is_estimate is False
    else:
        dates = [all_future[0]]        # date only from get_earnings_dates → hedge
        confirmed = False
    return {
        "ticker": ticker.upper(),
        "dates": dates,
        "days_until": (dates[0] - today).days,
        "confirmed": confirmed,
    }


_FMT = "%A, %b %-d, %Y"  # "Wednesday, Jul 22, 2026"


def format_earnings_answer(outlook: dict, name: str | None = None) -> str:
    """One short sentence — confident when the date is company-confirmed, hedged
    when it's only an analyst estimate."""
    tkr = outlook["ticker"]
    label = f"{name} ({tkr})" if name else tkr
    dates = outlook["dates"]

    if len(dates) >= 2 and dates[0] != dates[1]:
        d0 = dates[0].strftime("%b %-d")
        d1 = dates[1].strftime("%b %-d, %Y")
        return (
            f"📅 **{label}** — its next earnings date isn't officially confirmed yet. "
            f"Analysts estimate the report between **{d0}** and **{d1}**."
        )

    d = dates[0].strftime(_FMT)
    if outlook.get("confirmed"):
        return f"📅 **{label}** is scheduled to report earnings on **{d}**."
    return (
        f"📅 **{label}** hasn't officially confirmed its next earnings date yet. "
        f"Analysts expect it around **{d}**."
    )


async def maybe_answer_earnings(text: str, channel_id: str, message_id: str) -> bool:
    """If `text` is an earnings-date question about a real ticker, answer it and
    return True. Otherwise return False so the caller falls through to the agent.

    Once a ticker resolves we always reply (even with "couldn't find a date")
    rather than handing back to the agent — that is the whole point: no fabrication.
    """
    if not is_earnings_date_query(text):
        return False
    symbol, name = await _resolve_ticker(text)
    if not symbol:
        return False

    from consensus_engine.alerts.discord import send_command_reply

    outlook = await fetch_earnings_outlook(symbol)
    if outlook:
        reply = format_earnings_answer(outlook, name)
        log.info("earnings_answer served ticker=%s dates=%s", symbol, outlook["dates"])
    else:
        label = f"{name} ({symbol})" if name else symbol
        reply = (
            f"📅 I couldn't find a scheduled or estimated earnings date for **{label}** "
            f"right now — it may not be on the analyst calendar yet."
        )
        log.info("earnings_answer no-date ticker=%s", symbol)
    await send_command_reply(channel_id, message_id, reply)
    return True
