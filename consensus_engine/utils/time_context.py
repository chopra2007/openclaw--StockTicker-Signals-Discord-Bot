"""Time-context helpers for LLM system prompts.

Provides a multi-line block (system-prompt friendly) and a single-line
oneliner (user-message-prefix friendly) describing the current UTC time,
the current PDT time + weekday, and the NYSE session state (open/closed/
holiday/early-close). All user-facing times are Pacific (the user's timezone).

Used by !ask, !all narrator, and @-mention steering prefix so the LLM
answers time/market-hours questions correctly instead of hallucinating
from stale training data.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pandas_market_calendars as mcal

_NYSE = mcal.get_calendar("NYSE")


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
