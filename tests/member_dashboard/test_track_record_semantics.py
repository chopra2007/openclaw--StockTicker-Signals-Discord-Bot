"""Direction and elapsed-horizon cases from the track-record audit."""
from datetime import datetime
import sqlite3
from zoneinfo import ZoneInfo

from test_feed import feed  # noqa: F401
from member_dashboard import track_record
from test_market_board import reader_for


def test_bearish_rise_is_adverse_and_unknown_direction_is_not_graded(feed):
    now = feed.dashboard.clock()
    stamp = datetime(2026, 9, 30, 9, tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()
    with feed.dashboard.store.transaction() as con:
        con.executemany('INSERT INTO track_alerts(alert_id,ticker,alerted_at,price,price_1h,price_24h,direction) VALUES (?,?,?,?,?,?,?)',
                        [(1, 'AAA', stamp, 100., 110., 110., 'bearish'),
                         (2, 'BBB', stamp, 100., 90., 90., 'bearish'),
                         (3, 'CCC', stamp, 100., 120., 120., 'unclear')])
        page = track_record.summary(con, now)
    h = page['horizons'][0]
    assert (h['count'], h['graded'], h['favorable'], h['adverse']) == (3, 2, 1, 1)
    rows = {r['ticker']: r for r in page['recent']}
    assert rows['AAA']['move_1h'] == 10 and rows['AAA']['favorable_1h'] is False
    assert rows['BBB']['favorable_1h'] is True and rows['CCC']['favorable_1h'] is None


def test_due_missing_price_is_unavailable_and_new_alert_is_pending(feed):
    now = feed.dashboard.clock()
    stamp = datetime(2026, 9, 30, 9, tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()
    with feed.dashboard.store.transaction() as con:
        con.executemany('INSERT INTO track_alerts(alert_id,ticker,alerted_at,price) VALUES (?,?,?,100)',
                        [(1, 'OLD', stamp), (2, 'NEW', now - 60)])
        page = track_record.summary(con, now)
    rows = {r['ticker']: r for r in page['recent']}
    assert rows['OLD']['status_1h'] == 'unavailable'
    assert rows['OLD']['status_1d'] == 'unavailable'
    assert rows['NEW']['status_1h'] == 'pending'
    assert rows['NEW']['status_1d'] == 'pending'
    assert page['horizons'][0]['pending'] == 1 and page['horizons'][0]['unavailable'] == 1


def test_sync_revisits_old_repairs_and_small_chunks_do_not_starve_new_alerts(feed, tmp_path):
    now = feed.dashboard.clock()
    reader = reader_for(tmp_path, now)
    with sqlite3.connect(tmp_path / 'bot.sqlite3') as bot:
        bot.execute("ALTER TABLE alert_history ADD COLUMN direction TEXT DEFAULT 'unclear'")
        bot.execute("UPDATE alert_history SET price_1h_later=NULL,direction='short' WHERE id=1")
    for _ in range(6): track_record.sync(feed.dashboard.store, reader, now, limit=1)
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT direction FROM track_alerts WHERE alert_id=1').fetchone()[0] == 'bearish'
        assert con.execute('SELECT count(*) FROM track_alerts').fetchone()[0] == 4
    with sqlite3.connect(tmp_path / 'bot.sqlite3') as bot:
        bot.execute('UPDATE alert_history SET price_1h_later=109 WHERE id=1')
    for _ in range(6): track_record.sync(feed.dashboard.store, reader, now, limit=1)
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT price_1h FROM track_alerts WHERE alert_id=1').fetchone()[0] == 109


def test_accounts_backup_resets_track_cursors_when_alert_copies_are_removed(feed, tmp_path, monkeypatch):
    from member_dashboard import backup
    from member_dashboard.store import WebStore
    staging = tmp_path / 'snapshot.sqlite3'
    WebStore(staging).migrate()
    con = sqlite3.connect(staging)
    con.execute('UPDATE track_sync_state SET last_id=100,new_id=500'); con.commit(); con.close()
    def encrypted(source, *args, **kwargs):
        con = sqlite3.connect(source)
        try: assert con.execute('SELECT last_id,new_id FROM track_sync_state').fetchone() == (0,0)
        finally: con.close()
        return tmp_path / 'result.mdb'
    monkeypatch.setattr(backup, 'encrypted_backup', encrypted)
    backup.accounts_backup(staging, tmp_path, key_path=tmp_path/'key', node=tmp_path/'node', now=1)


def test_live_record_counts_from_start_and_reports_real_span():
    from member_dashboard import track_record
    import sqlite3
    con = sqlite3.connect(':memory:')
    con.execute('CREATE TABLE track_alerts(alert_id,ticker,alerted_at,price,price_1h,price_24h,price_5d,direction)')
    con.execute('CREATE TABLE index_daily(symbol,day,close)')
    start = 1_000_000_000
    con.executemany('INSERT INTO track_alerts VALUES (?,?,?,?,?,?,?,?)',
                    [(1, 'OLD', start - 3600, 10, None, None, None, 'bullish'), (2, 'NEW', start + 3600, 10, None, None, None, 'bullish')])
    page = track_record.summary(con, start + 2 * 86400, with_spy=False, start=start)
    assert (page['total'], page['days']) == (1, track_record.MIN_DAYS)   # Older alert left out; never under 4 days.
    page = track_record.summary(con, start + 9.5 * 86400, with_spy=False, start=start)
    assert page['days'] == 10                                             # Grows a day at a time.
    assert track_record.summary(con, start + 200 * 86400, with_spy=False, start=start)['days'] == 90
