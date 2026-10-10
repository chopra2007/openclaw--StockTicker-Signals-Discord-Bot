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

from .market_board import PACIFIC, TICKER, close_minute, market_hours, open_day

WINDOW = 90 * 86400     # Alerts older than this are not counted.
# Owner decision 2026-10-07: the live record starts fresh on 2026-10-04 00:00 Pacific and grows a day at a time up to WINDOW.
START = 1791097200
MIN_DAYS = 4
CHUNK = 1000
MIN_RATE = 20           # No win rate on fewer alerts than this.
FLAT = 0.0001           # A move smaller than 0.01% is "flat".
HORIZONS = (('1h', '1 hour', None), ('1d', '1 day', 1), ('5d', '5 days', 5))
# An alert only counts when the bot's Discord post is on record: alert_messages is written after the post is confirmed.
POSTED = ("SELECT a.id,a.ticker,a.alerted_at,a.price_at_alert,a.price_1h_later,a.price_24h_later,a.price_5d_later,{direction} FROM alert_history a "
          "WHERE a.alerted_at>? AND a.id>? AND a.price_at_alert>0 AND EXISTS (SELECT 1 FROM alert_messages m "
          "WHERE m.ticker=a.ticker AND m.instant_msg_id IS NOT NULL AND m.created_at BETWEEN a.alerted_at-120 AND a.alerted_at+600) "
          "ORDER BY a.id LIMIT ?")


def _price(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0 else None


def sync(store, reader, now, limit=CHUNK):
    """Copy one chunk of posted alerts. Returns the number of rows copied (== limit means more are waiting)."""
    with store.transaction() as con:
        cursor, last = con.execute('SELECT last_id,new_id FROM track_sync_state WHERE id=1').fetchone()
    try:
        with reader.connection() as bot:
            # Old databases remain readable until the bot migration is applied.
            columns = {r[1] for r in bot.execute('PRAGMA table_info(alert_history)')}
            query = POSTED.format(direction='a.direction' if 'direction' in columns else "'unclear'")
            rows = bot.execute(query, (now - WINDOW, last, limit)).fetchall()
            refresh = bot.execute(query, (now - WINDOW, cursor, limit)).fetchall()
    except sqlite3.Error:
        return 0
    keep = [(r[0], r[1], r[2], _price(r[3]), _price(r[4]), _price(r[5]), _price(r[6]),
             {'long':'bullish','short':'bearish','bullish':'bullish','bearish':'bearish'}.get(r[7], 'unclear')) for r in {r[0]:r for r in [*refresh,*rows]}.values()
            if isinstance(r[1], str) and TICKER.match(r[1]) and isinstance(r[2], (int, float)) and 0 < r[2] <= now + 86400 and _price(r[3])]
    with store.transaction() as con:
        for row in keep:
            con.execute('INSERT INTO track_alerts(alert_id,ticker,alerted_at,price,price_1h,price_24h,price_5d,direction) VALUES (?,?,?,?,?,?,?,?) '
                        'ON CONFLICT(alert_id) DO UPDATE SET price_1h=coalesce(excluded.price_1h,track_alerts.price_1h),price_24h=excluded.price_24h,price_5d=excluded.price_5d,direction=excluded.direction', row)
        con.execute('UPDATE track_sync_state SET last_id=? WHERE id=1', (refresh[-1][0] if len(refresh) == limit else 0,))
        if rows: con.execute('UPDATE track_sync_state SET new_id=? WHERE id=1', (rows[-1][0],))
        con.execute('DELETE FROM track_alerts WHERE alerted_at<?', (now - WINDOW - 7 * 86400,))
    return max(len(rows), len(refresh))


def _closes(history, now):
    """Daily candles -> {Pacific date: close}, leaving out today's unfinished candle while the market is open."""
    out = {}
    today = datetime.fromtimestamp(now, PACIFIC).date().isoformat()
    for stamp, row in history.iterrows():
        close = _price(row.get('Close'))
        day = stamp.date().isoformat()  # Candles are stamped in New York time; their date is the trading day.
        if close and not (day >= today and market_hours(now)): out[day] = close
    return out


HOURS_EVERY = 15 * 60    # Owner 2026-10-07: 1-hour prices outside regular hours are filled every 15 minutes...
HOURS_GRACE = 30 * 60    # ...so a missing 1-hour price stays "pending" this long before it reads "unavailable".
HOURS_TICKERS = 10       # Schwab calls per run (the dashboard shares the bot's Schwab login).
LOOKBACK = 4 * 86400     # Owner 2026-10-09: an alert outside regular hours starts from the last trade before it (covers 3-day weekends).
_hours_last = [0.0]


def _price_at(frame, start, end):
    """Close of the last minute that ended by `end` and started at or after `start`; None when nothing traded."""
    last = None
    for stamp, close in zip(frame.index, frame['Close']) if frame is not None else ():
        t = stamp.timestamp()
        if start <= t and t + 60 <= end and close and close > 0: last = float(close)
    return last


async def fill_hours(store, client, allowed, clock=time.time):
    """1-hour price for alerts the bot leaves blank (posted or ending outside the regular session).

    The bot fills regular-session hours itself. Here: the last trade at or before alert+1h, pre-market and after-hours
    included; when nothing traded in that hour (overnight, weekend) the price did not move, so it is the alert price.
    "Nothing traded" needs minute data reaching past the hour: data that stops earlier (2026-10-09: the 6:01 AM
    alerts were saved flat) is tried again next run. An alert posted outside the regular session also takes the last
    trade before it as its price, instead of the bot's quote (yesterday's close before the pre-market).
    """
    now = clock()
    if now - _hours_last[0] < HOURS_EVERY or not allowed(): return 0
    _hours_last[0] = now
    with store.transaction() as con:
        rows = con.execute('SELECT alert_id,ticker,alerted_at,price FROM track_alerts WHERE price_1h IS NULL AND alerted_at>? AND alerted_at<? '
                           'ORDER BY alerted_at DESC', (now - 9 * 86400, now - 3660)).fetchall()
    todo = {}
    for alert_id, ticker, alerted_at, price in rows:
        if not open_for_1h(alerted_at) and (ticker in todo or len(todo) < HOURS_TICKERS):
            todo.setdefault(ticker, []).append((alert_id, alerted_at, price))
    filled = 0
    for ticker, alerts in todo.items():
        span = math.ceil((now - min(a[1] for a in alerts) + LOOKBACK) / 86400) + 1
        period = '1d' if span <= 1 else '2d' if span <= 2 else '5d' if span <= 5 else '10d'
        try: frame = await asyncio.to_thread(client.get_price_history, ticker, period=period, interval='1m', extended_hours=True)
        except Exception: continue  # Tried again next run.
        if frame is None or not len(frame): continue  # No minute data at all: not a quiet hour; tried again next run.
        last = frame.index[-1].timestamp() + 60
        with store.transaction() as con:
            for alert_id, alerted_at, price in alerts:
                end = alerted_at + 3600
                value = _price_at(frame, alerted_at, end)
                if value is None and last < end and can_trade(alerted_at, end): continue  # Data does not cover the hour yet.
                start = price if in_session(alerted_at) else _price_at(frame, alerted_at - LOOKBACK, alerted_at) or price
                filled += con.execute('UPDATE track_alerts SET price_1h=?,price=? WHERE alert_id=? AND price_1h IS NULL',
                                      (value or start, start, alert_id)).rowcount
    return filled


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
    """Regular session: trading days 6:30 AM - 1:00 PM Pacific (10:00 AM on an early close)."""
    t = datetime.fromtimestamp(stamp, PACIFIC)
    return open_day(t) and 6 * 60 + 30 <= t.hour * 60 + t.minute < close_minute(t)


def can_trade(start, end):
    """Any of [start, end] inside extended hours: trading days 4:00 AM until 4 hours after the close, Pacific."""
    for stamp in range(int(start), int(end) + 1, 300):
        t = datetime.fromtimestamp(stamp, PACIFIC)
        if open_day(t) and 4 * 60 <= t.hour * 60 + t.minute < close_minute(t) + 4 * 60: return True
    return False


def open_for_1h(alerted_at):
    """Alert and its 1-hour price both inside the regular session: the bot fills these; `fill_hours` does the rest."""
    return in_session(alerted_at) and in_session(alerted_at + 3600)


def _status(row, key, now):
    if row[key]: return 'recorded'
    due = {'price_1h': 3600 + HOURS_GRACE, 'price_24h': 86400, 'price_5d': 7 * 86400}[key]
    return 'pending' if now < row['alerted_at'] + due else 'unavailable'


def _favorable(row, key):
    if not row[key] or row['direction'] not in ('bullish', 'bearish'): return None
    move = (row[key] / row['price'] - 1) * (1 if row['direction'] == 'bullish' else -1)
    return move >= FLAT


def _horizon(rows, key, label, steps, closes, days, now):
    moves = [(r['alerted_at'], r[key] / r['price'] - 1) for r in rows if r[key]]
    spy = [m for m in (_spy_move(days, closes, t, steps) for t, _ in moves) if m is not None] if steps and closes else []
    pct = lambda values: (round(median(values) * 100, 1) or 0.0) if values else None  # `or 0.0`: never "-0.0"
    return dict(key={'price_1h': '1h', 'price_24h': '1d', 'price_5d': '5d'}[key], label=label, count=len(moves),
                graded=sum(_status(r,key,now)=='recorded' and r['direction'] in ('bullish','bearish') for r in rows),
                favorable=sum(_status(r,key,now)=='recorded' and _favorable(r,key) is True for r in rows),
                adverse=sum(_status(r,key,now)=='recorded' and r['direction'] in ('bullish','bearish') and
                            (r[key]/r['price']-1)*(1 if r['direction']=='bullish' else -1) <= -FLAT for r in rows),
                pending=sum(_status(r,key,now)=='pending' for r in rows), unavailable=sum(_status(r,key,now)=='unavailable' for r in rows),
                up=sum(m >= FLAT for _, m in moves), flat=sum(abs(m) < FLAT for _, m in moves), median_pct=pct([m for _, m in moves]),
                spy_count=len(spy), spy_up=sum(m > 0 for m in spy), spy_median_pct=pct(spy))


def summary(con, now, rows=50, with_spy=True, start=None):
    """`start`: count only alerts after it (the live API passes START); `days` is then the real span, MIN_DAYS to 90."""
    con.row_factory = sqlite3.Row
    since = now - WINDOW if start is None else max(now - WINDOW, start)
    span = WINDOW // 86400 if start is None else min(WINDOW // 86400, max(MIN_DAYS, math.ceil((now - since) / 86400)))
    alerts = con.execute('SELECT * FROM track_alerts WHERE alerted_at>? ORDER BY alerted_at DESC', (since,)).fetchall()
    closes = {r[0]: r[1] for r in con.execute("SELECT day,close FROM index_daily WHERE symbol='SPY' ORDER BY day")} if with_spy else {}
    days = sorted(closes)
    horizons = [_horizon(alerts, key, label, steps, closes, days, now)
                for key, (_, label, steps) in zip(('price_1h', 'price_24h', 'price_5d'), HORIZONS)]
    move = lambda r, key: round((r[key] / r['price'] - 1) * 100, 2) if r[key] else None
    recent = [dict(ticker=r['ticker'], alerted_at=r['alerted_at'], price=r['price'], closed_1h=not open_for_1h(r['alerted_at']),
                   direction=r['direction'], **{'status_'+h:_status(r,key,now) for h,key in [('1h','price_1h'),('1d','price_24h'),('5d','price_5d')]},
                   **{'favorable_'+h:_favorable(r,key) if _status(r,key,now)=='recorded' else None for h,key in [('1h','price_1h'),('1d','price_24h'),('5d','price_5d')]},
                   move_1h=move(r, 'price_1h'), move_1d=move(r, 'price_24h'), move_5d=move(r, 'price_5d')) for r in alerts[:rows]]
    return dict(total=len(alerts), days=span, horizons=horizons, recent=recent)
