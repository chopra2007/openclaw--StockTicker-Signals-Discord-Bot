"""Bounded historical one-hour observations; never substitute a current quote."""
from datetime import datetime
import logging
import math
import time
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)
PACIFIC = ZoneInfo('America/Los_Angeles')
LOOKBACK = 30 * 86400


def get_history(*args, **kwargs):
    from consensus_engine.scanners.schwab_client import get_price_history_payload
    return get_price_history_payload(*args, **kwargs)


def in_session(stamp):
    t = datetime.fromtimestamp(stamp, PACIFIC)
    return t.weekday() < 5 and 390 <= t.hour * 60 + t.minute < 780


def fetch_hour_price(ticker, alerted_at, now=None):
    """Close of the minute containing alert+1h, once that minute completes.

    A historical minute is a bounded observation, not an exact-tick execution.
    Missing minute coverage, holidays and closed-session horizons stay missing.
    """
    now = time.time() if now is None else now
    target = alerted_at + 3600
    minute = int(target // 60) * 60
    if (not in_session(alerted_at) or not in_session(target) or
            now < minute + 60 or now - alerted_at > LOOKBACK):
        return 0.0
    try:
        history = get_history(ticker, interval='1m', start=minute * 1000,
                              end=(minute + 120) * 1000, extended_hours=False)
        for candle in history.get('candles', []) or []:
            # Schwab candles are stamped at the start of each minute.
            if candle.get('datetime') != minute * 1000: continue
            value = candle.get('close')
            if isinstance(value, (int,float)) and not isinstance(value,bool) and math.isfinite(value) and value > 0:
                return float(value)
    except Exception as error:
        log.debug('Historical hour observation unavailable for %s: %s', ticker, error)
    return 0.0
