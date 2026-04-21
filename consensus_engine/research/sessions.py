"""ET trading session helpers shared by Atlas and Alfred."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from consensus_engine import config as cfg

ET = ZoneInfo("America/New_York")


def _holiday_list() -> list[str]:
    return list(cfg.get("alfred.market_holidays", []) or [])


def is_market_holiday(dt: datetime) -> bool:
    key = dt.astimezone(ET).strftime("%Y-%m-%d")
    return key in _holiday_list()


def _prev_trading_day(dt: datetime) -> datetime:
    d = dt
    while True:
        d = d - timedelta(days=1)
        if d.weekday() < 5 and not is_market_holiday(d):
            return d


def _is_trading_day(dt: datetime) -> bool:
    return dt.weekday() < 5 and not is_market_holiday(dt)


def current_et_session(now: datetime | None = None) -> tuple[float, float, str]:
    """Return (session_start_utc, session_end_utc, session_key).

    session_key is the most recent *trading* day in ET (rolling back over
    weekends and market holidays). session_start = prev trading day 16:00 ET.
    session_end = session_key day 16:00 ET (or now() if before 16:00).
    """
    now = now or datetime.now(tz=ET)
    now_et = now.astimezone(ET)

    # Find session date: today if trading day, else most recent trading day.
    cur = now_et.date()
    d = datetime(cur.year, cur.month, cur.day, tzinfo=ET)
    while not _is_trading_day(d):
        d = d - timedelta(days=1)
    session_key = d.strftime("%Y-%m-%d")

    end_et = datetime(d.year, d.month, d.day, 16, 0, tzinfo=ET)
    if now_et < end_et:
        end_et = now_et
    start_et = end_et - timedelta(hours=24)
    return start_et.timestamp(), end_et.timestamp(), session_key
