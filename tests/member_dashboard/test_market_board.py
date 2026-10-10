"""Market strip, watchlist and track record: real web transactions and HTTP reads, fake Schwab and bot database."""
import asyncio
from datetime import datetime
import sqlite3
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from test_feed import feed, publish  # noqa: F401  (fixture + helper)
from test_source_policy import grant
from member_dashboard import market_board, track_record

PACIFIC = ZoneInfo('America/Los_Angeles')
# FakeClock's default is Monday Oct 5 2026 11:30 AM Pacific, inside market hours.
HEADERS = lambda feed: {'Origin': feed.dashboard.settings.origin, 'X-CSRF-Token': 'csrf'}


def allow_schwab(feed):
    grant(feed.dashboard, source='schwab-marketdata', product_id='schwab-market-data', policy_version='owner-2026-10-05',
          expires_at=None, review_at=None, retention_deadline=None, delete_on_expiry=False)


def save_quotes(feed, rows):
    now = feed.dashboard.clock()
    with feed.dashboard.store.transaction() as con:
        for symbol, price, prev, stamp in rows:
            con.execute('INSERT INTO market_quotes(symbol,price,prev_close,quote_time,fetched_at) VALUES (?,?,?,?,?)', (symbol, price, prev, stamp, now))


class FakeSchwab:
    def __init__(self, entries=None): self.calls = []; self.entries = entries
    def _get(self, path, params=None):
        self.calls.append((path, params))
        entry = lambda last, close: {'quote': {'lastPrice': last, 'closePrice': close, 'quoteTime': 1_791_000_000_000}}
        symbols = params['symbols'].split(',')
        return self.entries if self.entries is not None else {s: entry(100.0 + i, 99.0 + i) for i, s in enumerate(symbols)}


def test_strip_serves_index_quotes_with_change_and_one_time(feed):
    allow_schwab(feed)
    save_quotes(feed, [('$SPX', 5000.0, 4950.0, 1_791_000_000.0), ('$VIX', 15.0, 16.0, 1_790_999_000.0), ('NVDA', 1.0, 1.0, None)])
    body = feed.dashboard.client.get('/api/v1/market/strip').json()
    assert [q['symbol'] for q in body['quotes']] == ['$SPX', '$VIX']  # Index order, tickers never in the strip.
    assert body['quotes'][0]['change'] == 50.0 and body['quotes'][0]['change_pct'] == 1.01
    assert body['quotes'][1]['change_pct'] == -6.25
    assert body['quote_time'] == 1_791_000_000.0


def test_strip_hides_when_schwab_permission_missing_or_quotes_stale(feed):
    save_quotes(feed, [('$SPX', 5000.0, 4950.0, 1.0)])
    assert feed.dashboard.client.get('/api/v1/market/strip').status_code == 503  # No owner permission recorded.
    allow_schwab(feed)
    feed.dashboard.clock.advance(market_board.STALE + 1)
    assert feed.dashboard.client.get('/api/v1/market/strip').json()['quotes'] == []


def test_watchlist_add_remove_cap_and_csrf(feed):
    client, headers = feed.dashboard.client, HEADERS(feed)
    assert client.put('/api/v1/watchlist/nvda').status_code == 403  # No CSRF token.
    assert client.put('/api/v1/watchlist/nvda', headers=headers).json()['items'][0]['symbol'] == 'NVDA'
    assert client.put('/api/v1/watchlist/NVDA', headers=headers).status_code == 200  # Adding twice is harmless.
    assert client.put('/api/v1/watchlist/not a ticker', headers=headers).status_code == 422
    for i in range(market_board.WATCH_LIMIT - 1): assert client.put(f'/api/v1/watchlist/T{i}', headers=headers).status_code == 200
    assert client.put('/api/v1/watchlist/OVER', headers=headers).status_code == 409
    assert len(client.get('/api/v1/watchlist').json()['items']) == market_board.WATCH_LIMIT
    assert client.delete('/api/v1/watchlist/NVDA', headers=headers).status_code == 204
    assert 'NVDA' not in [i['symbol'] for i in client.get('/api/v1/watchlist').json()['items']]


def test_watchlist_shows_prices_and_new_alert_badge(feed):
    allow_schwab(feed)
    client, headers = feed.dashboard.client, HEADERS(feed)
    client.put('/api/v1/watchlist/TEST', headers=headers)
    client.put('/api/v1/watchlist/QUIET', headers=headers)
    publish(feed, key='alert-1', excerpt='3 analysts in 5 min', feature='setups')  # An alert_history card on TEST.
    save_quotes(feed, [('TEST', 11.0, 10.0, 5.0)])
    items = {i['symbol']: i for i in client.get('/api/v1/watchlist').json()['items']}
    assert items['TEST']['price'] == 11.0 and items['TEST']['change_pct'] == 10.0 and items['TEST']['new_alert'] is True
    assert items['QUIET']['price'] is None and items['QUIET']['new_alert'] is False
    feed.dashboard.clock.advance(2 * 86400)  # Alerts older than 24 hours are not "new".
    with feed.dashboard.store.transaction() as con: con.execute('UPDATE sessions SET idle_expires_at=?,absolute_expires_at=?', (feed.dashboard.clock() + 7200, feed.dashboard.clock() + 7200))
    assert client.get('/api/v1/watchlist').json()['items'][0]['new_alert'] is False


def test_quotes_only_for_own_watchlist_and_recent_card_tickers(feed):
    allow_schwab(feed)
    client, headers = feed.dashboard.client, HEADERS(feed)
    client.put('/api/v1/watchlist/MINE', headers=headers)
    publish(feed, key='alert-1', excerpt='x', feature='setups')
    save_quotes(feed, [('MINE', 5.0, 4.0, 1.0), ('TEST', 11.0, 10.0, 1.0), ('SECRET', 9.0, 9.0, 1.0)])
    body = client.get('/api/v1/market/quotes', params={'symbols': 'mine,test,secret,bad ticker'}).json()
    assert sorted(q['symbol'] for q in body['quotes']) == ['MINE', 'TEST']


def test_refresh_makes_one_call_for_indices_watched_and_alert_tickers_then_waits_a_minute(feed, monkeypatch):
    allow_schwab(feed)
    monkeypatch.setattr(market_board, 'market_hours', lambda now: False)
    client, headers, store, clock = feed.dashboard.client, HEADERS(feed), feed.dashboard.store, feed.dashboard.clock
    client.put('/api/v1/watchlist/MINE', headers=headers)
    publish(feed, key='alert-1', excerpt='x', feature='setups')
    schwab = FakeSchwab()
    with store.transaction() as con: con.execute('UPDATE sessions SET last_seen_at=?', (clock() - 3600,))
    assert asyncio.run(market_board.refresh(store, schwab, lambda: True, clock)) == 0  # Market closed and nobody signed in.
    with store.transaction() as con: con.execute('UPDATE sessions SET last_seen_at=?', (clock(),))
    assert asyncio.run(market_board.refresh(store, schwab, lambda: True, clock)) == 7
    path, params = schwab.calls[0]
    assert path == '/quotes' and params['symbols'].split(',') == ['$SPX', '$COMPX', '$DJI', '$RUT', '$VIX', 'MINE', 'TEST']
    assert asyncio.run(market_board.refresh(store, schwab, lambda: True, clock)) == 0 and len(schwab.calls) == 1
    clock.advance(61)
    with store.transaction() as con: con.execute('UPDATE sessions SET last_seen_at=?', (clock(),))
    assert asyncio.run(market_board.refresh(store, schwab, lambda: True, clock)) == 7 and len(schwab.calls) == 2


def test_refresh_runs_all_day_during_market_hours_even_with_nobody_signed_in(feed, monkeypatch):
    allow_schwab(feed)
    monkeypatch.setattr(market_board, 'market_hours', lambda now: True)
    store, clock = feed.dashboard.store, feed.dashboard.clock
    with store.transaction() as con: con.execute('UPDATE sessions SET last_seen_at=?', (clock() - 3600,))
    assert asyncio.run(market_board.refresh(store, FakeSchwab(), lambda: True, clock)) == 5


def test_refresh_respects_permission_and_keeps_old_quotes_when_schwab_fails(feed, monkeypatch):
    monkeypatch.setattr(market_board, 'market_hours', lambda now: True)
    store, clock = feed.dashboard.store, feed.dashboard.clock
    with store.transaction() as con: con.execute('UPDATE sessions SET last_seen_at=?', (clock(),))
    schwab = FakeSchwab()
    assert asyncio.run(market_board.refresh(store, schwab, lambda: False, clock)) == 0 and schwab.calls == []
    save_quotes(feed, [('$SPX', 1.0, 1.0, 1.0)])
    clock.advance(120)
    with store.transaction() as con: con.execute('UPDATE sessions SET last_seen_at=?', (clock(),))
    with pytest.raises(ValueError):
        asyncio.run(market_board.refresh(store, type('Broken', (), {'_get': lambda self, *a, **k: (_ for _ in ()).throw(ValueError('down'))})(), lambda: True, clock))
    with store.transaction() as con: assert con.execute('SELECT count(*) FROM market_quotes').fetchone()[0] == 1


def test_settle_keeps_the_session_previous_close_after_schwab_resets_it():
    stamp = datetime(2026, 10, 6, 13, 0, tzinfo=PACIFIC).timestamp()
    now = stamp + 3 * 3600
    live = market_board.settle({'$SPX': (7818.93, 7773.95, stamp)}, {}, now)
    assert live == ({'$SPX': (7818.93, 7773.95, '2026-10-06', stamp)}, [])
    # After the close Schwab reports previous close == last: the remembered one for that trading day wins.
    after = market_board.settle({'$SPX': (7818.93, 7818.93, stamp)}, {'$SPX': (7773.95, '2026-10-06')}, now)
    assert after[0]['$SPX'][1] == 7773.95 and after[1] == []
    # Remembered for an older day: the index needs a daily-candle look-up; a ticker just shows no change.
    fresh, need = market_board.settle({'$SPX': (1.0, 1.0, stamp), 'NVDA': (2.0, 2.0, stamp)}, {'$SPX': (9.0, '2026-10-05')}, now)
    assert need == ['$SPX'] and fresh['$SPX'][1] is None and fresh['NVDA'][1] is None


def test_refresh_looks_up_an_index_previous_close_once_when_schwab_shows_no_change(feed, monkeypatch):
    allow_schwab(feed)
    monkeypatch.setattr(market_board, 'market_hours', lambda now: True)
    store, clock = feed.dashboard.store, feed.dashboard.clock
    stamp = clock() - 60
    flat = {'$SPX': {'quote': {'lastPrice': 7818.93, 'closePrice': 7818.93, 'quoteTime': 0, 'tradeTime': stamp * 1000}}}
    days = history([('2026-10-01', 7666.45), ('2026-10-02', 7722.72), (datetime.fromtimestamp(stamp, PACIFIC).date().isoformat(), 7818.93)])
    class Client(FakeSchwab):
        def get_price_history(self, symbol, **kwargs): self.calls.append(('history', symbol)); return days
    schwab = Client(flat)
    asyncio.run(market_board.refresh(store, schwab, lambda: True, clock))
    assert ('history', '$SPX') in schwab.calls
    with store.transaction() as con: assert con.execute("SELECT prev_close FROM market_quotes WHERE symbol='$SPX'").fetchone()[0] == 7722.72
    clock.advance(61); schwab.calls.clear()
    asyncio.run(market_board.refresh(store, schwab, lambda: True, clock))  # Remembered: no second look-up.
    assert [c[0] for c in schwab.calls] == ['/quotes']


def test_market_hours_are_pacific_weekdays():
    at = lambda *args: datetime(*args, tzinfo=PACIFIC).timestamp()
    assert market_board.market_hours(at(2026, 10, 6, 7, 0)) and market_board.market_hours(at(2026, 10, 6, 13, 10))
    assert not market_board.market_hours(at(2026, 10, 6, 5, 59)) and not market_board.market_hours(at(2026, 10, 6, 13, 30))
    assert not market_board.market_hours(at(2026, 10, 3, 9, 0))  # Saturday.


# ---------------------------------------------------------------- track record

def bot_database(path, now):
    """A bot database with 4 real alerts, one that was never posted, one with a bad ticker."""
    with sqlite3.connect(path) as con:
        con.execute('CREATE TABLE alert_history(id INTEGER PRIMARY KEY,ticker TEXT,alerted_at REAL,price_at_alert REAL,price_1h_later REAL,price_24h_later REAL,price_5d_later REAL)')
        con.execute('CREATE TABLE alert_messages(id INTEGER PRIMARY KEY,ticker TEXT,instant_msg_id TEXT,created_at REAL)')
        rows = [(1, 'AAA', now - 10 * 86400, 100.0, 101.0, 102.0, 103.0), (2, 'BBB', now - 9 * 86400, 50.0, 49.0, None, None),
                (3, 'CCC', now - 5 * 86400, 10.0, 10.0, 9.0, None), (4, 'AAA', now - 3600 * 6, 100.0, None, None, None),
                (5, 'NOPOST', now - 4 * 86400, 10.0, 11.0, 12.0, 13.0), (6, 'bad ticker', now - 3 * 86400, 10.0, 11.0, 12.0, 13.0)]
        con.executemany('INSERT INTO alert_history VALUES (?,?,?,?,?,?,?)', rows)
        for i, (_, ticker, stamp, *_rest) in enumerate(rows):
            if ticker != 'NOPOST': con.execute('INSERT INTO alert_messages VALUES (?,?,?,?)', (i, ticker, '123', stamp + 5))
        con.execute('INSERT INTO alert_messages VALUES (99,?,NULL,?)', ('NOPOST', now - 4 * 86400 + 5))  # A row with no Discord message id.


def reader_for(tmp_path, now):
    from member_dashboard.market_reader import MarketReader
    path = tmp_path / 'bot.sqlite3'
    bot_database(path, now)
    return MarketReader(path, query_seconds=1.0)


def test_sync_copies_only_posted_alerts_and_refreshes_recent_prices(feed, tmp_path):
    store, now = feed.dashboard.store, feed.dashboard.clock()
    reader = reader_for(tmp_path, now)
    assert track_record.sync(store, reader, now) == 5  # The un-posted alert is never read.
    with store.transaction() as con:
        assert [r[0] for r in con.execute('SELECT alert_id FROM track_alerts ORDER BY alert_id')] == [1, 2, 3, 4]  # Bad ticker skipped.
        assert con.execute('SELECT price_1h FROM track_alerts WHERE alert_id=4').fetchone()[0] is None
    with sqlite3.connect(tmp_path / 'bot.sqlite3') as con: con.execute('UPDATE alert_history SET price_1h_later=101 WHERE id=4')
    track_record.sync(store, reader, now)  # The newest alert was inside the 9-day re-read window.
    with store.transaction() as con: assert con.execute('SELECT price_1h FROM track_alerts WHERE alert_id=4').fetchone()[0] == 101


def history(days_closes):
    return pd.DataFrame({'Close': [c for _, c in days_closes]}, index=pd.DatetimeIndex([pd.Timestamp(d, tz='America/New_York') for d, _ in days_closes]))


def test_spy_closes_are_fetched_once_a_day(feed):
    store, clock = feed.dashboard.store, feed.dashboard.clock
    calls = []
    class Client:
        def get_price_history(self, symbol, **kwargs): calls.append((symbol, kwargs)); return history([('2026-10-01', 500.0), ('2026-10-02', 505.0)])
    assert asyncio.run(track_record.refresh_spy(store, Client(), lambda: True, clock)) == 2
    assert asyncio.run(track_record.refresh_spy(store, Client(), lambda: True, clock)) == 0 and len(calls) == 1
    clock.advance(21 * 3600)
    assert asyncio.run(track_record.refresh_spy(store, Client(), lambda: False, clock)) == 0 and len(calls) == 1  # Permission off.


def test_summary_counts_medians_and_spy_comparison(feed):
    store, now = feed.dashboard.store, feed.dashboard.clock()
    at = lambda *args: datetime(*args, tzinfo=PACIFIC).timestamp()
    alerts = [  # After-hours alerts (3:00 PM Pacific): the S&P base is that day's close.
        (1, 'AAA', at(2026, 9, 28, 15, 0), 100.0, 101.0, 102.0, 110.0), (2, 'BBB', at(2026, 9, 29, 15, 0), 50.0, 50.0, 49.0, None),
        (3, 'CCC', at(2026, 9, 30, 15, 0), 10.0, 9.0, None, None),
        (4, 'DDD', at(2026, 9, 30, 8, 0), 20.0, 21.0, None, None),  # Posted in the session, 1-hour price in the session.
        (5, 'EEE', at(2026, 9, 30, 12, 30), 20.0, 19.0, None, None)]  # 1-hour price lands after 1:00 PM (filled by fill_hours).
    with store.transaction() as con:
        con.executemany('INSERT INTO track_alerts(alert_id,ticker,alerted_at,price,price_1h,price_24h,price_5d) VALUES (?,?,?,?,?,?,?)', alerts)
        con.executemany("INSERT INTO index_daily(symbol,day,close,fetched_at) VALUES ('SPY',?,?,0)",
                        [('2026-09-28', 500.0), ('2026-09-29', 505.0), ('2026-09-30', 495.0), ('2026-10-01', 500.0), ('2026-10-02', 510.0), ('2026-10-05', 515.0)])
        page = track_record.summary(con, now)
    by = {h['key']: h for h in page['horizons']}
    assert page['total'] == 5
    # 1 hour counts every alert with a 1-hour price, in or out of the session: +1, 0, -10, +5, -5.
    assert (by['1h']['count'], by['1h']['up'], by['1h']['flat'], by['1h']['median_pct']) == (5, 2, 1, 0.0)
    assert (by['1d']['count'], by['1d']['up'], by['1d']['median_pct']) == (2, 1, 0.0)
    assert (by['5d']['count'], by['5d']['median_pct']) == (1, 10.0)
    assert by['1h']['spy_count'] == 0  # Daily closes cannot say what happened in one hour.
    # 1 day: AAA 500 -> 505 (+1.0%), BBB 505 -> 495 (-1.98%): median -0.5%, one up.
    assert (by['1d']['spy_count'], by['1d']['spy_up'], by['1d']['spy_median_pct']) == (2, 1, -0.5)
    assert (by['5d']['spy_count'], by['5d']['spy_median_pct']) == (1, 3.0)  # AAA 500 -> 515 five trading days later.
    recent = {r['ticker']: r for r in page['recent']}
    assert [r['ticker'] for r in page['recent']] == ['CCC', 'EEE', 'DDD', 'BBB', 'AAA'] and recent['AAA']['move_5d'] == 10.0
    assert recent['DDD']['move_1h'] == 5.0 and not recent['DDD']['closed_1h']
    assert recent['CCC']['move_1h'] == -10.0 and recent['CCC']['closed_1h'] and recent['EEE']['closed_1h']
    assert recent['CCC']['status_1h'] == 'recorded'


def test_spy_base_is_the_day_before_for_alerts_made_during_the_session():
    closes = {'2026-09-28': 500.0, '2026-09-29': 505.0, '2026-09-30': 495.0}
    days = sorted(closes)
    midday = datetime(2026, 9, 29, 9, 0, tzinfo=PACIFIC).timestamp()
    assert track_record._spy_move(days, closes, midday, 1) == pytest.approx(505.0 / 500.0 - 1)  # 9/28 close -> 9/29 close
    assert track_record._spy_move(days, closes, midday, 2) == pytest.approx(495.0 / 500.0 - 1)  # 9/28 -> 9/30
    assert track_record._spy_move(days, closes, midday, 5) is None  # Not enough closes yet.


def test_record_route_needs_setups_feature_and_hides_spy_without_permission(feed):
    client, store = feed.dashboard.client, feed.dashboard.store
    now = feed.dashboard.clock()
    with store.transaction() as con:
        con.execute('INSERT INTO track_alerts(alert_id,ticker,alerted_at,price,price_1h) VALUES (1,?,?,10.0,11.0)', ('AAA', now - 3600))
        con.execute("INSERT INTO index_daily(symbol,day,close,fetched_at) VALUES ('SPY','2026-10-01',500,0)")
    body = client.get('/api/v1/record', params={'rows': 0}).json()
    assert body['total'] == 1 and body['recent'] == [] and body['horizons'][0]['up'] == 1 and body['horizons'][1]['spy_count'] == 0
    with store.transaction() as con: con.execute("UPDATE features SET enabled=0 WHERE name='setups'")
    assert client.get('/api/v1/record').status_code == 403


def test_fill_hours_uses_extended_trades_or_alert_price(feed):
    import pandas as pd
    store, now = feed.dashboard.store, feed.dashboard.clock()
    at = lambda *args: datetime(*args, tzinfo=PACIFIC).timestamp()
    pre = at(2026, 10, 6, 5, 0)        # Pre-market alert: a real extended-hours trade 40 minutes later.
    sat = at(2026, 10, 3, 10, 0)       # Saturday: nothing trades, so the price did not move.
    regular = at(2026, 10, 6, 8, 0)    # Regular session: left to the bot.
    with store.transaction() as con:
        con.executemany('INSERT INTO track_alerts(alert_id,ticker,alerted_at,price) VALUES (?,?,?,?)',
                        [(1, 'AAA', pre, 10.0), (2, 'BBB', sat, 20.0), (3, 'CCC', regular, 30.0)])
    frames = {'AAA': pd.DataFrame({'Close': [10.5, 11.0, 12.0]}, index=pd.to_datetime([pre + 600, pre + 2400, pre + 3600], unit='s', utc=True)),
              'BBB': pd.DataFrame({'Close': [19.0]}, index=pd.to_datetime([sat - 86400], unit='s', utc=True))}
    calls = []
    class Client:
        def get_price_history(self, symbol, **kwargs): calls.append((symbol, kwargs)); return frames[symbol]
    track_record._hours_last[0] = 0.0
    clock = lambda: at(2026, 10, 7, 12, 0)
    assert asyncio.run(track_record.fill_hours(store, Client(), lambda: True, clock)) == 2
    with store.transaction() as con:
        got = dict(con.execute('SELECT ticker,price_1h FROM track_alerts').fetchall())
    assert got == {'AAA': 11.0, 'BBB': 19.0, 'CCC': None}   # The 12.0 minute ends after alert+1h, so it is not used.
    # Saturday: nothing traded, so the 1-hour price is the alert's starting price, the last trade before it (Friday's 19.0).
    assert {c[0] for c in calls} == {'AAA', 'BBB'} and all(c[1]['extended_hours'] and c[1]['interval'] == '1m' for c in calls)
    assert asyncio.run(track_record.fill_hours(store, Client(), lambda: True, clock)) == 0 and len(calls) == 2  # Every 15 minutes only.


def test_fill_hours_waits_for_data_covering_the_hour_and_starts_from_the_last_trade(feed):
    # 2026-10-09: 6:01 AM alerts were saved flat because the minute data did not yet reach 7:01 AM.
    store = feed.dashboard.store
    at = lambda *args: datetime(*args, tzinfo=PACIFIC).timestamp()
    alert = at(2026, 10, 9, 6, 1)
    with store.transaction() as con:
        con.execute('INSERT INTO track_alerts(alert_id,ticker,alerted_at,price) VALUES (1,?,?,?)', ('TSLA', alert, 375.0))
    stale = pd.DataFrame({'Close': [375.0, 380.0]}, index=pd.to_datetime([at(2026, 10, 8, 13, 0), at(2026, 10, 8, 16, 59)], unit='s', utc=True))
    fresh = pd.DataFrame({'Close': [380.0, 388.0, 384.1, 390.0]}, index=pd.to_datetime(
        [at(2026, 10, 8, 16, 59), alert - 120, alert + 3000, alert + 3660], unit='s', utc=True))
    frames = [stale, fresh]
    class Client:
        def get_price_history(self, symbol, **kwargs): return frames.pop(0)
    clock = lambda: at(2026, 10, 9, 7, 15)
    track_record._hours_last[0] = 0.0
    assert asyncio.run(track_record.fill_hours(store, Client(), lambda: True, clock)) == 0   # Not saved flat.
    track_record._hours_last[0] = 0.0
    assert asyncio.run(track_record.fill_hours(store, Client(), lambda: True, clock)) == 1
    with store.transaction() as con:
        assert con.execute('SELECT price,price_1h FROM track_alerts').fetchone() == (388.0, 384.1)  # Pre-market price, not yesterday's close.


def test_holidays_and_early_closes_follow_the_nyse_calendar():
    at = lambda *args: datetime(*args, tzinfo=PACIFIC).timestamp()
    thanksgiving, early = at(2026, 11, 26, 9, 0), at(2026, 11, 27, 10, 30)
    assert not track_record.in_session(thanksgiving) and not track_record.can_trade(thanksgiving, thanksgiving + 3600)
    assert not market_board.market_hours(thanksgiving)
    assert track_record.in_session(at(2026, 11, 27, 9, 30)) and not track_record.in_session(early)
    assert track_record.can_trade(early, early + 3600) and not track_record.can_trade(at(2026, 11, 27, 14, 5), at(2026, 11, 27, 15, 5))
    assert track_record.in_session(at(2026, 10, 9, 12, 59)) and not track_record.in_session(at(2026, 10, 9, 13, 0))
