"""Track record of the bot's own alerts (design round 2026-10-06).

Supervisor (reads the bot database): `sync` copies alerts that were really posted to #alerts, with the prices the bot
recorded 1 hour, 1 day and 5 days later, into `track_alerts`. Compute worker (Schwab): `refresh_spy` saves SPY daily
closes once a day. API: `summary` counts and compares, so a page view reads only the dashboard database.
"""
import asyncio
from bisect import bisect_right
from datetime import datetime
import math
import sqlite3
from statistics import median
import time

from .market_board import PACIFIC, TICKER, market_hours

WINDOW = 90 * 86400     # Alerts older than this are not counted.
RECENT = 9 * 86400      # Recent alerts are re-read so their later prices fill in (5 trading days is up to 9 calendar days).
CHUNK = 1000
MIN_RATE = 20           # No win rate on fewer alerts than this.
FLAT = 0.0001           # A move smaller than 0.01% is "flat" (the market was closed, so the price could not move).
HORIZONS = (('1h', '1 hour', None), ('1d', '1 day', 1), ('5d', '5 days', 5))
# An alert only counts when the bot's Discord post is on record: alert_messages is written after the post is confirmed.
POSTED = ("SELECT a.id,a.ticker,a.alerted_at,a.price_at_alert,a.price_1h_later,a.price_24h_later,a.price_5d_later FROM alert_history a "
          "WHERE a.alerted_at>? AND (a.id>? OR a.alerted_at>?) AND a.price_at_alert>0 AND EXISTS (SELECT 1 FROM alert_messages m "
          "WHERE m.ticker=a.ticker AND m.instant_msg_id IS NOT NULL AND m.created_at BETWEEN a.alerted_at-120 AND a.alerted_at+600) "
          "ORDER BY a.id LIMIT ?")


def _price(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0 else None


def sync(store, reader, now, limit=CHUNK):
    """Copy one chunk of posted alerts. Returns the number of rows copied (== limit means more are waiting)."""
    with store.transaction() as con:
        last = con.execute('SELECT coalesce(max(alert_id),0) FROM track_alerts').fetchone()[0]
    try:
        with reader.connection() as bot:
            rows = bot.execute(POSTED, (now - WINDOW, last, now - RECENT, limit)).fetchall()
    except sqlite3.Error:
        return 0
    keep = [(r[0], r[1], r[2], _price(r[3]), _price(r[4]), _price(r[5]), _price(r[6])) for r in rows
            if isinstance(r[1], str) and TICKER.match(r[1]) and isinstance(r[2], (int, float)) and 0 < r[2] <= now + 86400 and _price(r[3])]
    with store.transaction() as con:
        for row in keep:
            con.execute('INSERT INTO track_alerts(alert_id,ticker,alerted_at,price,price_1h,price_24h,price_5d) VALUES (?,?,?,?,?,?,?) '
                        'ON CONFLICT(alert_id) DO UPDATE SET price_1h=excluded.price_1h,price_24h=excluded.price_24h,price_5d=excluded.price_5d', row)
        con.execute('DELETE FROM track_alerts WHERE alerted_at<?', (now - WINDOW - 7 * 86400,))
    return len(rows)


def _closes(history, now):
    """Daily candles -> {Pacific date: close}, leaving out today's unfinished candle while the market is open."""
    out = {}
    today = datetime.fromtimestamp(now, PACIFIC).date().isoformat()
    for stamp, row in history.iterrows():
        close = _price(row.get('Close'))
        day = stamp.date().isoformat()  # Candles are stamped in New York time; their date is the trading day.
        if close and not (day >= today and market_hours(now)): out[day] = close
    return out


async def refresh_spy(store, client, allowed, clock=time.time):
    """One Schwab call a day (a call is skipped when closes were saved in the last 20 hours)."""
    now = clock()
    with store.transaction() as con:
        last = con.execute("SELECT max(fetched_at) FROM index_daily WHERE symbol='SPY'").fetchone()[0]
    if last and now - last < 20 * 3600: return 0
    if not allowed(): return 0
    history = await asyncio.to_thread(client.get_price_history, 'SPY', period='6mo', interval='1d')
    closes = _closes(history, now) if history is not None else {}
    if not closes: return 0
    with store.transaction() as con:
        for day, close in closes.items():
            con.execute("INSERT INTO index_daily(symbol,day,close,fetched_at) VALUES ('SPY',?,?,?) ON CONFLICT(symbol,day) DO UPDATE SET "
                        "close=excluded.close,fetched_at=excluded.fetched_at", (day, close, now))
    return len(closes)


def _spy_move(days, closes, alerted_at, steps):
    """S&P 500 move from the alert's day to `steps` trading days later (from the day before when the alert came mid-session)."""
    t = datetime.fromtimestamp(alerted_at, PACIFIC)
    day = t.date().isoformat()
    mid = t.weekday() < 5 and 6 * 60 + 30 <= t.hour * 60 + t.minute < 13 * 60
    i = bisect_right(days, day) - 1 - (1 if mid and day in closes else 0)
    if i < 0 or i + steps >= len(days): return None
    return closes[days[i + steps]] / closes[days[i]] - 1


def in_session(stamp):
    """Regular session: weekdays 6:30 AM - 1:00 PM Pacific."""
    t = datetime.fromtimestamp(stamp, PACIFIC)
    return t.weekday() < 5 and 6 * 60 + 30 <= t.hour * 60 + t.minute < 13 * 60


def open_for_1h(alerted_at):
    """A 1-hour move only means something when the alert and its 1-hour price both fall inside the session."""
    return in_session(alerted_at) and in_session(alerted_at + 3600)


def _horizon(rows, key, label, steps, closes, days):
    moves = [(r['alerted_at'], r[key] / r['price'] - 1) for r in rows if r[key] and (key != 'price_1h' or open_for_1h(r['alerted_at']))]
    spy = [m for m in (_spy_move(days, closes, t, steps) for t, _ in moves) if m is not None] if steps and closes else []
    pct = lambda values: (round(median(values) * 100, 1) or 0.0) if values else None  # `or 0.0`: never "-0.0"
    return dict(key={'price_1h': '1h', 'price_24h': '1d', 'price_5d': '5d'}[key], label=label, count=len(moves),
                up=sum(m >= FLAT for _, m in moves), flat=sum(abs(m) < FLAT for _, m in moves), median_pct=pct([m for _, m in moves]),
                spy_count=len(spy), spy_up=sum(m > 0 for m in spy), spy_median_pct=pct(spy))


def summary(con, now, rows=50, with_spy=True):
    con.row_factory = sqlite3.Row
    alerts = con.execute('SELECT * FROM track_alerts WHERE alerted_at>? ORDER BY alerted_at DESC', (now - WINDOW,)).fetchall()
    closes = {r[0]: r[1] for r in con.execute("SELECT day,close FROM index_daily WHERE symbol='SPY' ORDER BY day")} if with_spy else {}
    days = sorted(closes)
    horizons = [_horizon(alerts, key, label, steps, closes, days)
                for key, (_, label, steps) in zip(('price_1h', 'price_24h', 'price_5d'), HORIZONS)]
    move = lambda r, key: round((r[key] / r['price'] - 1) * 100, 2) if r[key] else None
    recent = [dict(ticker=r['ticker'], alerted_at=r['alerted_at'], price=r['price'], closed_1h=not open_for_1h(r['alerted_at']),
                   move_1h=move(r, 'price_1h') if open_for_1h(r['alerted_at']) else None, move_1d=move(r, 'price_24h'), move_5d=move(r, 'price_5d')) for r in alerts[:rows]]
    return dict(total=len(alerts), days=WINDOW // 86400, horizons=horizons, recent=recent)
