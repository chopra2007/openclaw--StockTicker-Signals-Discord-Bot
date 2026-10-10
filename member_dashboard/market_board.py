"""Market strip and watchlist quotes (design round 2026-10-06).

One Schwab /quotes call at most once a minute, made by the compute worker (the only process with Schwab
access) while anyone is signed in or the market is open, and saved in `market_quotes`. The API only reads that
table, so a page view never reaches Schwab. The call covers the five index symbols, every watched ticker and
the tickers of the newest alerts (cap 100 symbols).
"""
import asyncio
from datetime import datetime
import re
import sqlite3
import time
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo('America/Los_Angeles')
INDEXES = (('$SPX', 'S&P 500'), ('$COMPX', 'Nasdaq'), ('$DJI', 'Dow'), ('$RUT', 'Russell 2000'), ('$VIX', 'VIX'))
TICKER = re.compile(r'[A-Z][A-Z0-9.\-]{0,15}\Z')
WATCH_LIMIT = 50      # Tickers one member may watch.
WATCHED_SYMBOLS = 95  # Watched tickers come first (most-watched first); alert tickers fill what is left of the 100.
MAX_SYMBOLS = 100     # One /quotes call.
ALERT_SYMBOLS = 60    # Tickers of the newest alerts and setups, so Overview cards show day change.
INTERVAL = 60
STALE = 1800          # A quote older than this is not served.
ACTIVE = 600          # "Signed in" = a session seen in the last 10 minutes.
# NYSE calendar from nyse.com (checked 2026-10-09); add the next year's dates before 2028.
HOLIDAYS = frozenset((
    '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03', '2026-05-25', '2026-06-19', '2026-07-03', '2026-09-07',
    '2026-11-26', '2026-12-25', '2027-01-01', '2027-01-18', '2027-02-15', '2027-03-26', '2027-05-31', '2027-06-18',
    '2027-07-05', '2027-09-06', '2027-11-25', '2027-12-24'))
EARLY_CLOSE = frozenset(('2026-11-27', '2026-12-24', '2027-11-26'))  # Regular session ends 10:00 AM Pacific.


def open_day(t):
    """`t`: a Pacific datetime. Weekday and not an NYSE holiday."""
    return t.weekday() < 5 and t.date().isoformat() not in HOLIDAYS


def close_minute(t):
    """Minute of the Pacific day the regular session ends: 1:00 PM, or 10:00 AM on an early close."""
    return 10 * 60 if t.date().isoformat() in EARLY_CLOSE else 13 * 60


def market_hours(now):
    """Trading days 6:00 AM - 15 minutes after the close, Pacific (the regular session plus a little padding)."""
    t = datetime.fromtimestamp(now, PACIFIC)
    return open_day(t) and 6 * 60 <= t.hour * 60 + t.minute <= close_minute(t) + 15


def recent_tickers(con, now, limit=ALERT_SYMBOLS):
    """Tickers of the newest bot alerts and setups, the cards that show a price (analyst calls show none)."""
    return [r[0] for r in con.execute(
        "SELECT p.ticker FROM publication_heads h JOIN publications p ON p.id=h.publication_id WHERE h.source_id IN ('swarm_alerts','alert_history') "
        "AND h.active=1 AND h.authority_blocked=0 AND p.observed_at>? GROUP BY p.ticker ORDER BY max(p.observed_at) DESC LIMIT ?",
        (now - 3 * 86400, limit))]


def wanted(con, now):
    symbols = [s for s, _ in INDEXES]
    for ticker in [r[0] for r in con.execute('SELECT ticker FROM watchlist GROUP BY ticker ORDER BY count(*) DESC,ticker LIMIT ?', (WATCHED_SYMBOLS,))] + recent_tickers(con, now):
        if TICKER.match(ticker) and ticker not in symbols: symbols.append(ticker)
    return symbols[:MAX_SYMBOLS]


def due(con, now):
    last = con.execute('SELECT max(fetched_at) FROM market_quotes').fetchone()[0]
    if last and now - last < INTERVAL: return False
    return market_hours(now) or con.execute('SELECT 1 FROM sessions WHERE revoked_at IS NULL AND last_seen_at>? LIMIT 1', (now - ACTIVE,)).fetchone() is not None


def schwab_sources():
    from .contracts import SourceContribution
    from .operations import SCHWAB_SOURCE, SCHWAB_PRODUCT, OWNER_POLICY_VERSION
    return [SourceContribution(source_id=SCHWAB_SOURCE, product_id=SCHWAB_PRODUCT, source_version='v1', policy_version=OWNER_POLICY_VERSION)]


def schwab_allowed(policy, use, now=None):
    """The owner's Schwab permission, checked the same way research results are (a denial hides the numbers)."""
    try: return policy.authorize(schwab_sources(), use, now or time.time()).allowed
    except Exception: return False


def fetch(client, symbols):
    """One /quotes call. Returns {symbol: (price, Schwab's previous close, quote time)}."""
    from consensus_engine.scanners.schwab_client import to_schwab_symbol, _map_quote
    wire = {to_schwab_symbol(s): s for s in symbols}
    data = client._get('/quotes', {'symbols': ','.join(wire)})
    out = {}
    for key, symbol in wire.items():
        entry = data.get(key)
        if not isinstance(entry, dict): continue
        q = _map_quote(entry)
        price, prev = q.get('c'), q.get('pc')
        if not price or price <= 0: continue
        out[symbol] = (price, prev if prev and prev > 0 else None, float(q.get('quote_time') or q.get('t') or 0) or None)
    return out


def trading_day(stamp, now):
    return datetime.fromtimestamp(stamp or now, PACIFIC).date().isoformat()


def settle(quotes, known, now):
    """Pick each symbol's previous close. Schwab resets an index's previous close to today's close once the market
    shuts (the day change reads zero), so a previous close seen while the price differed from it is kept for that
    trading day. Returns ({symbol: (price, prev, prev_day, stamp)}, index symbols that still need a daily-candle look-up)."""
    out, need = {}, []
    for symbol, (price, prev, stamp) in quotes.items():
        day = trading_day(stamp, now)
        old_prev, old_day = known.get(symbol, (None, None))
        if prev is not None and prev != price: pass  # A live previous close.
        elif old_prev is not None and old_day == day: prev = old_prev  # Remembered from earlier in the session.
        elif symbol.startswith('$'): prev = None; need.append(symbol)
        else: prev = None  # Unchanged price and nothing remembered: show no change rather than a false zero.
        out[symbol] = (price, prev, day, stamp)
    return out, need


def history_prev(client, symbol, day):
    """The last daily close before `day` (one daily-candle call; needed at most once per index per trading day)."""
    from consensus_engine.scanners.schwab_client import to_schwab_symbol
    history = client.get_price_history(to_schwab_symbol(symbol), period='1mo', interval='1d')
    closes = {stamp.date().isoformat(): row['Close'] for stamp, row in history.iterrows()} if history is not None else {}
    before = [d for d in closes if d < day]
    return float(closes[max(before)]) if before else None


async def refresh(store, client, allowed, clock=time.time):
    """Save a new snapshot when one is due. Returns the number of quotes saved (0 when nothing was due)."""
    now = clock()
    with store.transaction() as con:
        if not due(con, now): return 0
        symbols = wanted(con, now)
        known = {r[0]: (r[1], r[2]) for r in con.execute('SELECT symbol,prev_close,prev_day FROM market_quotes')}
    if not allowed(): return 0
    quotes = await asyncio.to_thread(fetch, client, symbols)
    if not quotes: return 0
    settled, need = settle(quotes, known, now)
    for symbol in need:
        try: prev = await asyncio.to_thread(history_prev, client, symbol, settled[symbol][2])
        except Exception: continue  # No change shown for this index until the next try.
        settled[symbol] = (settled[symbol][0], prev, *settled[symbol][2:])
    with store.transaction() as con:
        for symbol, (price, prev, day, stamp) in settled.items():
            con.execute('INSERT INTO market_quotes(symbol,price,prev_close,prev_day,quote_time,fetched_at) VALUES (?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET '
                        'price=excluded.price,prev_close=excluded.prev_close,prev_day=excluded.prev_day,quote_time=excluded.quote_time,fetched_at=excluded.fetched_at',
                        (symbol, price, prev, day, stamp, now))
        con.execute('DELETE FROM market_quotes WHERE symbol NOT IN (' + ','.join('?' * len(symbols)) + ')', symbols)  # Nobody asks for them any more.
    return len(settled)


def change(price, prev):
    """(dollar change, percent change) from the previous close, or (None, None)."""
    if price is None or not prev: return None, None
    return round(price - prev, 4), round((price / prev - 1) * 100, 3)


def quote_row(row):
    d, p = change(row['price'], row['prev_close'])
    return dict(symbol=row['symbol'], price=row['price'], change=d, change_pct=p, quote_time=row['quote_time'])


def strip(con, now):
    con.row_factory = sqlite3.Row
    rows = {r['symbol']: r for r in con.execute('SELECT * FROM market_quotes WHERE symbol LIKE ? AND fetched_at>?', ('$%', now - STALE))}
    quotes, stamps = [], []
    for symbol, label in INDEXES:
        r = rows.get(symbol)
        if r is None: continue
        d, p = change(r['price'], r['prev_close'])
        quotes.append(dict(symbol=symbol, label=label, price=r['price'], change=d, change_pct=p))
        if r['quote_time']: stamps.append(r['quote_time'])
    return dict(quotes=quotes, quote_time=stamps[0] if stamps else None)  # The first index with a time (the S&P 500).


def visible_symbols(con, member_id, now):
    """Tickers a member may read quotes for: their own watchlist and the tickers of the newest cards."""
    return {r[0] for r in con.execute('SELECT ticker FROM watchlist WHERE member_id=?', (member_id,))} | set(recent_tickers(con, now, 60))


def quotes(con, member_id, symbols, now):
    con.row_factory = sqlite3.Row
    allowed = visible_symbols(con, member_id, now)
    names = sorted({s for s in symbols if TICKER.match(s) and s in allowed})[:100]
    if not names: return dict(quotes=[])
    rows = con.execute('SELECT * FROM market_quotes WHERE fetched_at>? AND symbol IN (' + ','.join('?' * len(names)) + ')', (now - STALE, *names))
    return dict(quotes=[quote_row(r) for r in rows])


def alerted_recently(con, member_id, tickers, now):
    """Tickers the bot alerted on in the last 24 hours, for the features this member can read."""
    if not tickers: return set()
    rows = con.execute(
        "SELECT DISTINCT p.ticker FROM publication_heads h JOIN publications p ON p.id=h.publication_id JOIN features f ON f.name=h.feature AND f.enabled=1 "
        "WHERE h.active=1 AND h.authority_blocked=0 AND h.source_id IN ('swarm_alerts','alert_history') AND p.observed_at>? AND p.ticker IN ("
        + ','.join('?' * len(tickers)) + ')', (now - 86400, *tickers))
    return {r[0] for r in rows}


def watchlist(con, member_id, now):
    con.row_factory = sqlite3.Row
    rows = con.execute('SELECT ticker,added_at FROM watchlist WHERE member_id=? ORDER BY added_at DESC,ticker', (member_id,)).fetchall()
    prices = {r['symbol']: r for r in con.execute('SELECT * FROM market_quotes WHERE fetched_at>?', (now - STALE,))}
    hot = alerted_recently(con, member_id, [r[0] for r in rows], now)
    items = []
    for ticker, added in rows:
        q = quote_row(prices[ticker]) if ticker in prices else dict(symbol=ticker)
        items.append(dict(q, symbol=ticker, added_at=added, new_alert=ticker in hot))
    return dict(items=items, limit=WATCH_LIMIT)


class WatchlistFull(Exception): pass


def watch(con, member_id, ticker, now):
    if con.execute('SELECT 1 FROM watchlist WHERE member_id=? AND ticker=?', (member_id, ticker)).fetchone(): return
    if con.execute('SELECT count(*) FROM watchlist WHERE member_id=?', (member_id,)).fetchone()[0] >= WATCH_LIMIT: raise WatchlistFull()
    con.execute('INSERT INTO watchlist(member_id,ticker,added_at) VALUES (?,?,?)', (member_id, ticker, now))


def unwatch(con, member_id, ticker):
    con.execute('DELETE FROM watchlist WHERE member_id=? AND ticker=?', (member_id, ticker))
