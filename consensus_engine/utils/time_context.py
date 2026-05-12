"""Time-context helpers for LLM system prompts.

Provides a multi-line block (system-prompt friendly) and a single-line
oneliner (user-message-prefix friendly) describing the current UTC time,
the current ET time + weekday, and the NYSE session state (open/closed/
holiday/early-close).

Used by !ask, !all narrator, and @-mention steering prefix so the LLM
answers time/market-hours questions correctly instead of hallucinating
from stale training data.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pandas_market_calendars as mcal

_NYSE = mcal.get_calendar("NYSE")


def build_time_context() -> str:
    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ZoneInfo("America/New_York"))
    sched = _NYSE.schedule(now_et.date(), now_et.date())
    if sched.empty:
        session = "closed (weekend or holiday)"
        today_status = "non-trading day"
    else:
        open_t = sched.iloc[0]["market_open"].astimezone(ZoneInfo("America/New_York"))
        close_t = sched.iloc[0]["market_close"].astimezone(ZoneInfo("America/New_York"))
        is_open = open_t <= now_et < close_t
        session = ("open" if is_open
                   else f"closed (regular hours {open_t.strftime('%H:%M')}–{close_t.strftime('%H:%M')} ET)")
        today_status = ("regular trading day" if close_t.strftime("%H:%M") == "16:00"
                        else f"early-close day (closes {close_t.strftime('%H:%M')} ET)")
    return (
        f"Current UTC time: {now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
        f"Current ET time:  {now_et.strftime('%Y-%m-%d %I:%M %p %Z')} ({now_et.strftime('%A')})\n"
        f"NYSE session:     {session}; today is a {today_status}.\n"
        f"Today's date:     {now_et.strftime('%Y-%m-%d')} ({now_et.strftime('%A')})"
    )


def build_time_context_oneliner() -> str:
    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ZoneInfo("America/New_York"))
    sched = _NYSE.schedule(now_et.date(), now_et.date())
    if sched.empty:
        session = "closed"
    else:
        open_t = sched.iloc[0]["market_open"].astimezone(ZoneInfo("America/New_York"))
        close_t = sched.iloc[0]["market_close"].astimezone(ZoneInfo("America/New_York"))
        session = "open" if open_t <= now_et < close_t else "closed"
    return f"{now_et.strftime('%Y-%m-%d %I:%M %p ET')} ({now_et.strftime('%a')}, NYSE {session})"
