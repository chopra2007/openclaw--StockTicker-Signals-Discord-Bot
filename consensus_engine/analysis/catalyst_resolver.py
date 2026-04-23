"""Catalyst resolver (Stage C of v2 two-stage pipeline).

Converts raw `mentioned_date` strings ("next Wednesday", "April 29") into
YYYY-MM-DD dates relative to the video's `publish_ts`, then verifies earnings-
type catalysts against the Finnhub calendar via the existing
`fetch_earnings_calendar()` helper.

Philosophy (plan principle 4): external calendars are truth, the LLM is a
witness. Every earnings catalyst that reaches an alert must be cross-verified
or marked unverified — it's never fabricated by the model.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from dateutil import parser as dateparser
from dateutil.relativedelta import relativedelta

from consensus_engine.models import CandidateCatalyst
from consensus_engine.scanners.earnings_calendar import fetch_earnings_calendar

log = logging.getLogger("consensus_engine.analysis.catalyst_resolver")


_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

_NEXT_WEEKDAY_RE = re.compile(
    r"\b(next|this|coming)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)
_BARE_WEEKDAY_RE = re.compile(
    r"^\s*(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Publish timestamp parsing
# ---------------------------------------------------------------------------

def _parse_publish_ts(publish_ts_str: str) -> datetime:
    """Parse YouTube publish timestamp (ISO with optional trailing Z) to UTC."""
    if not publish_ts_str:
        return datetime.now(timezone.utc)
    cleaned = publish_ts_str.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        dt = dateparser.parse(publish_ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Relative-date resolution
# ---------------------------------------------------------------------------

def _resolve_weekday(
    qualifier: str | None, weekday_name: str, publish_ts: datetime
) -> date:
    """Resolve "next Tuesday" / "this Friday" / "Monday" relative to publish_ts."""
    target = _WEEKDAYS[weekday_name.lower()]
    pub_day = publish_ts.date()
    current = pub_day.weekday()
    diff = (target - current) % 7
    if qualifier and qualifier.lower() == "next":
        # Always the following week's occurrence.
        diff = 7 if diff == 0 else diff
        # "next Tuesday" from Friday → 4 days out (same week); from Monday → 1 day.
        # Some speakers use "next" to mean the upcoming instance regardless of week.
        # Default to the nearest future occurrence at least one day away.
    elif qualifier and qualifier.lower() in ("this", "coming"):
        diff = diff if diff > 0 else 7
    else:
        # Bare weekday — nearest future occurrence (0→7 so it's always forward).
        diff = diff if diff > 0 else 7
    return pub_day + timedelta(days=diff)


def _resolve_relative_date(
    mentioned_date_str: str, publish_ts: datetime
) -> str | None:
    """Return YYYY-MM-DD or None if the string can't be parsed."""
    if not mentioned_date_str:
        return None
    raw = mentioned_date_str.strip()
    low = raw.lower()

    # "next Wednesday" / "this Friday" / "coming Monday"
    m = _NEXT_WEEKDAY_RE.search(low)
    if m:
        return _resolve_weekday(m.group(1), m.group(2), publish_ts).isoformat()

    # Bare weekday — "Monday"
    m = _BARE_WEEKDAY_RE.match(low)
    if m:
        return _resolve_weekday(None, m.group(1), publish_ts).isoformat()

    # "next week" / "this week" — give the following Monday as a reasonable anchor.
    if low in ("next week", "this week", "coming week"):
        return _resolve_weekday("next", "monday", publish_ts).isoformat()

    # Fall back to dateutil — handles "April 29", "2026-04-29", "April 29th 2026", etc.
    try:
        parsed = dateparser.parse(raw, default=publish_ts, fuzzy=False)
    except (ValueError, OverflowError, TypeError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    # If dateutil inferred a year, make sure a bare "April 29" that dateutil
    # defaulted to publish-year is bumped forward when it's already in the past.
    if re.search(r"\b\d{4}\b", raw) is None:
        if parsed.date() < publish_ts.date():
            parsed = parsed + relativedelta(years=1)
    return parsed.date().isoformat()


# ---------------------------------------------------------------------------
# Earnings verification
# ---------------------------------------------------------------------------

def _within_days(a: str, b: str, window: int) -> bool:
    try:
        da = date.fromisoformat(a)
        db_ = date.fromisoformat(b)
    except ValueError:
        return False
    return abs((da - db_).days) <= window


async def _verify_earnings(ticker: str, resolved_date: str) -> int:
    """Cross-check an earnings catalyst against Finnhub.

    Returns 1 when the ticker's earnings date lies within ±3 days of the
    resolved date, -1 when the window has *other* earnings but not this
    ticker (a clear contradiction), and 0 when the call fails or the
    window is empty (unverified — don't block the alert, just flag it).
    """
    try:
        start = (date.fromisoformat(resolved_date) - timedelta(days=3)).isoformat()
        end = (date.fromisoformat(resolved_date) + timedelta(days=3)).isoformat()
    except ValueError:
        return 0

    try:
        rows = await fetch_earnings_calendar(start, end)
    except Exception as e:
        log.debug("Finnhub lookup failed for %s: %s", ticker, e)
        return 0

    if not rows:
        return 0

    for row in rows:
        if str(row.get("symbol", "")).upper() == ticker.upper():
            row_date = row.get("date")
            if row_date and _within_days(row_date, resolved_date, 3):
                return 1

    # Had calendar data but no row for this ticker near the date → contradict.
    return -1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def resolve_and_verify_catalysts(
    candidates: Iterable[CandidateCatalyst], publish_ts: str
) -> list[CandidateCatalyst]:
    """Resolve relative dates and verify earnings candidates in place.

    The input list is mutated and returned for convenience.
    """
    pub_dt = _parse_publish_ts(publish_ts)
    out: list[CandidateCatalyst] = list(candidates)
    for cat in out:
        resolved = _resolve_relative_date(cat.mentioned_date, pub_dt)
        cat.resolved_date = resolved
        if resolved and cat.catalyst_type == "earnings" and cat.ticker:
            cat.verified = await _verify_earnings(cat.ticker, resolved)
        else:
            # Macro catalysts (cpi/fed/jobs) — no authoritative source wired yet.
            cat.verified = 0
    return out
