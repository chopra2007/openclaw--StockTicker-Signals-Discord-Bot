"""Newest-cards reader for the website and trade-setup levels (owner report 2026-10-06)."""
import asyncio
from uuid import uuid4

from test_feed import feed, publish  # noqa: F401  (fixture + helper)


def latest(feed, feature):
    response = feed.dashboard.client.get('/api/v1/' + feature + '/latest')
    assert response.status_code == 200
    return response.json()['cards']


def levels(feed, ticker='TEST', **values):
    row = dict(direction='long', price=10.0, entry_low=9.5, entry_high=10.0, stop=9.0, target1=11.0, target2=12.0, target3=None)
    row.update(values)
    with feed.dashboard.store.transaction() as con:
        con.execute('INSERT INTO setup_levels(ticker,computed_at,direction,price,entry_low,entry_high,stop,target1,target2,target3) '
                    'VALUES (?,?,?,?,?,?,?,?,?,?)', (ticker, feed.dashboard.clock(), *row.values()))


def test_feed_latest_shows_only_cards_with_text(feed):
    publish(feed, key='with-text', excerpt='Breakout above 50 on volume')
    publish(feed, key='empty', excerpt='')
    cards = latest(feed, 'feed')
    assert [c['text'] for c in cards] == ['Breakout above 50 on volume']
    assert cards[0]['plan'] is None


def test_setups_need_a_trade_plan_and_show_one_card_per_ticker(feed):
    publish(feed, key='alert-1', excerpt='Analyst upgrade', feature='setups')
    assert latest(feed, 'setups') == []  # No levels yet: not a setup.
    levels(feed)
    publish(feed, key='alert-2', excerpt='Second alert', feature='setups')
    cards = latest(feed, 'setups')
    assert len(cards) == 1
    plan = cards[0]['plan']
    assert plan['direction'] == 'long' and plan['stop'] == 9.0 and plan['targets'] == [11.0, 12.0]
    assert cards[0]['price'] == 10.0


def test_setup_without_target_is_hidden(feed):
    publish(feed, key='alert-1', excerpt='x', feature='setups')
    levels(feed, target1=None, target2=None)
    assert latest(feed, 'setups') == []


def test_setup_levels_picks_due_ticker_and_waits_for_members(feed):
    from member_dashboard import setup_levels
    publish(feed, key='alert-1', excerpt='x', feature='setups')
    store, now = feed.dashboard.store, feed.dashboard.clock()
    with store.transaction() as con:
        assert setup_levels.next_ticker(con, now) == 'TEST'

    computed = []
    class Collector:
        async def __call__(self, ticker): computed.append(ticker); raise ValueError('no data')
        def services(self): raise AssertionError('not reached')
    assert asyncio.run(setup_levels.refresh_one(store, Collector(), clock=lambda: now)) == 'TEST'
    with store.transaction() as con:
        row = con.execute('SELECT price,computed_at FROM setup_levels WHERE ticker=?', ('TEST',)).fetchone()
        assert row == (None, now)  # Failed attempt: no price, retried after 10 minutes.
        assert setup_levels.next_ticker(con, now + 60) is None
        assert setup_levels.next_ticker(con, now + 601) == 'TEST'
        con.execute("INSERT INTO web_jobs(id,dedupe_key,ticker,section,status,created_at,policy_version,"
                    "required_features_json,lineage_json,input_json,feature_mask_json) VALUES "
                    "(?,'k','TEST','sec','queued',?,'p','[]','{}','{}','{}')", (str(uuid4()), now + 600))
    # A member researched in the last 2 minutes: the chore waits.
    assert asyncio.run(setup_levels.refresh_one(store, Collector(), clock=lambda: now + 601)) is None
    assert computed == ['TEST']
