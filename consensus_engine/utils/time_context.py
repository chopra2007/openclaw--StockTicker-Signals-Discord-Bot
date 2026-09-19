"""Time-context helpers for LLM system prompts.

Provides a multi-line block (system-prompt friendly) and a single-line
oneliner (user-message-prefix friendly) describing the current UTC time,
the current PDT time + weekday, and the NYSE session state (open/closed/
holiday/early-close). All user-facing times are Pacific (the user's timezone).

Used by !ask, !all narrator, and @-mention steering prefix so the LLM
answers time/market-hours questions correctly instead of hallucinating
from stale training data.
"""

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo
import pandas_market_calendars as mcal

_NYSE = mcal.get_calendar("NYSE")
_NY = ZoneInfo("America/New_York")
_PACIFIC = ZoneInfo("America/Los_Angeles")


def as_utc(moment: datetime) -> datetime:
    """Preserve an absolute instant; never guess a timezone for a naive event."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone")
    return moment.astimezone(timezone.utc)


def format_pacific(moment: datetime) -> str:
    """Display an absolute timestamp with the correct Pacific seasonal label."""
    return as_utc(moment).astimezone(_PACIFIC).strftime("%Y-%m-%d %I:%M:%S %p %Z")


def session_date_at(moment: datetime) -> date:
    """Exchange-calendar date for an instant, independent of its supplied zone.

    This is the schedule lookup key, including on holidays and outside hours.
    Use the bounds or phase helpers to establish whether a session exists/opens;
    this does not roll a closed day backward to the previous trading session.
    """
    return as_utc(moment).astimezone(_NY).date()


def _premarket_open(day: date, start: time, regular_open: datetime) -> datetime:
    if start.tzinfo is not None:
        raise ValueError("Premarket start must be a Pacific clock time without tzinfo")
    opened = as_utc(datetime.combine(day, start, tzinfo=_PACIFIC))
    if opened >= regular_open:
        raise ValueError("Premarket start must precede the regular open")
    return opened


def premarket_bounds(
    day: date, premarket_start: time,
) -> tuple[datetime, datetime] | None:
    """Caller-configured [Pacific start, scheduled open), as absolute instants.

    Non-session dates return None. These clock bounds say nothing about whether
    a provider supplies the required premarket data or its final observations.
    D-090 F-02 uses time(1, 0); that research choice is not a platform default.
    """
    bounds = session_bounds(day)
    if bounds is None:
        return None
    opened = as_utc(bounds[0])
    return _premarket_open(day, premarket_start, opened), opened


def regular_session_window(
    day: date, start_after_open: timedelta, end_after_open: timedelta,
) -> tuple[datetime, datetime] | None:
    """Absolute [start, end) clock window, capped at the actual regular close.

    Offsets come from the caller's strategy configuration. A holiday or a window
    starting at/after the close returns None. Reaching a boundary does not prove
    bar finality, coverage or feature readiness; consumers must check those.
    """
    if start_after_open < timedelta(0) or end_after_open <= start_after_open:
        raise ValueError("Window offsets must satisfy 0 <= start < end")
    bounds = session_bounds(day)
    if bounds is None:
        return None
    opened, closed = (as_utc(value) for value in bounds)
    start = opened + start_after_open
    end = min(opened + end_after_open, closed)
    return (start, end) if start < end else None


def session_phase(
    moment: datetime, premarket_start: time,
) -> Literal["CLOSED", "PREMARKET", "REGULAR"]:
    """Clock phase with inclusive starts and exclusive ends; not data health.

    Before the configured premarket, after the regular close and on non-session
    dates the result is CLOSED. Extended-hours provider availability is separate.
    """
    instant = as_utc(moment)
    day = session_date_at(instant)
    bounds = session_bounds(day)
    if bounds is None:
        return "CLOSED"
    opened, closed = (as_utc(value) for value in bounds)
    premarket = _premarket_open(day, premarket_start, opened)
    if opened <= instant < closed:
        return "REGULAR"
    if premarket <= instant < opened:
        return "PREMARKET"
    return "CLOSED"


def session_dates(start: date, end: date) -> list[date]:
    """NYSE trading-session dates from ``start`` to ``end``, inclusive.

    Holiday-aware (skips closures), so callers can count real market sessions
    instead of weekdays. Returns [] when the range is empty or has no sessions.
    """
    if end < start:
        return []
    sched = _NYSE.schedule(start, end)
    if sched.empty:
        return []
    return [ts.date() for ts in sched.index]


def session_bounds(day: date) -> tuple[datetime, datetime] | None:
    """(open, close) in New York time for ``day``, or None if it is not a
    trading session. Early-close aware — a half-day returns its real close."""
    sched = _NYSE.schedule(day, day)
    if sched.empty:
        return None
    return (sched.iloc[0]["market_open"].astimezone(_NY),
            sched.iloc[0]["market_close"].astimezone(_NY))


def nyse_open_now(now_et: datetime | None = None) -> bool:
    """True if the NYSE regular session is open at ``now_et`` (defaults to now).

    Holiday- and early-close-aware via the shared NYSE calendar, so callers get
    a correct open/closed answer on holidays and half-days — unlike a plain
    weekday + 09:30–16:00 check. ``now_et`` may be any tz-aware datetime.
    """
    if now_et is None:
        now_et = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York"))
    sched = _NYSE.schedule(now_et.date(), now_et.date())
    if sched.empty:
        return False
    open_t = sched.iloc[0]["market_open"].astimezone(ZoneInfo("America/New_York"))
    close_t = sched.iloc[0]["market_close"].astimezone(ZoneInfo("America/New_York"))
    return open_t <= now_et < close_t


def build_time_context() -> str:
    now_utc = datetime.now(timezone.utc)
    _NY = ZoneInfo("America/New_York")
    _PT = ZoneInfo("America/Los_Angeles")
    now_et = now_utc.astimezone(_NY)   # internal: NYSE session is anchored to the exchange's own clock
    now_pt = now_utc.astimezone(_PT)   # display: everything the user sees is Pacific
    sched = _NYSE.schedule(now_et.date(), now_et.date())
    if sched.empty:
        session = "closed (weekend or holiday)"
        today_status = "non-trading day"
    else:
        open_t = sched.iloc[0]["market_open"].astimezone(_NY)
        close_t = sched.iloc[0]["market_close"].astimezone(_NY)
        is_open = open_t <= now_et < close_t
        open_pt = open_t.astimezone(_PT)
        close_pt = close_t.astimezone(_PT)
        session = ("open" if is_open
                   else f"closed (regular hours {open_pt.strftime('%H:%M')}–{close_pt.strftime('%H:%M')} PDT)")
        today_status = ("regular trading day" if close_t.strftime("%H:%M") == "16:00"
                        else f"early-close day (closes {close_pt.strftime('%H:%M')} PDT)")
    return (
        f"Current UTC time: {now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
        f"Current PDT time: {now_pt.strftime('%Y-%m-%d %I:%M %p %Z')} ({now_pt.strftime('%A')})\n"
        f"NYSE session:     {session}; today is a {today_status}.\n"
        f"Today's date:     {now_pt.strftime('%Y-%m-%d')} ({now_pt.strftime('%A')})"
    )


def build_time_context_oneliner() -> str:
    now_utc = datetime.now(timezone.utc)
    _NY = ZoneInfo("America/New_York")
    _PT = ZoneInfo("America/Los_Angeles")
    now_et = now_utc.astimezone(_NY)   # internal: NYSE session compare
    now_pt = now_utc.astimezone(_PT)   # display: Pacific
    sched = _NYSE.schedule(now_et.date(), now_et.date())
    if sched.empty:
        session = "closed"
    else:
        open_t = sched.iloc[0]["market_open"].astimezone(_NY)
        close_t = sched.iloc[0]["market_close"].astimezone(_NY)
        session = "open" if open_t <= now_et < close_t else "closed"
    return f"{now_pt.strftime('%Y-%m-%d %I:%M %p %Z')} ({now_pt.strftime('%a')}, NYSE {session})"
