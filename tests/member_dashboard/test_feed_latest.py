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
        async def study(self, ticker): computed.append(ticker); raise ValueError('no data')
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


def test_setup_keeps_chart_already_collected_without_ai(feed):
    from types import SimpleNamespace
    from member_dashboard import setup_levels
    from test_market_board import allow_schwab
    allow_schwab(feed)
    publish(feed, key='chart-alert', excerpt='Analyst upgrade', feature='setups')
    now=feed.dashboard.clock()
    display=dict(company='Test Company',quote={},chart=dict(daily=[[now-86400,9.0],[now,10.0]],intraday=[]))
    class Collector:
        async def study(self, ticker):
            return SimpleNamespace(result=SimpleNamespace(structured=SimpleNamespace(direction='BULLISH',current_price=10)),
                facts=dict(price=10,trade_plan=dict(entry_low=9,entry_high=10,stop=8,targets=[dict(price=12)])),display=display)
    asyncio.run(setup_levels.refresh_one(feed.dashboard.store, Collector(), clock=lambda:now,retain_context=lambda:True))
    card=latest(feed,'setups')[0]
    assert card['chart']['daily']==display['chart']['daily']
    assert card['company'] is None  # Company metadata may have a separate source permission.
    assert card['chart_at']==now


def test_setup_chart_is_not_retained_without_permission(feed):
    from member_dashboard import setup_levels
    levels(feed)
    with feed.dashboard.store.transaction() as con:
        con.execute("UPDATE setup_levels SET context_json='{}'")
    class Collector:
        async def study(self,ticker): raise AssertionError('No research needed')
    asyncio.run(setup_levels.refresh_one(feed.dashboard.store,Collector(),clock=feed.dashboard.clock,retain_context=lambda:False))
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT context_json FROM setup_levels').fetchone()[0] is None


def test_policy_purge_removes_disallowed_setup_chart(feed):
    levels(feed)
    with feed.dashboard.store.transaction() as con:
        con.execute("UPDATE setup_levels SET context_json='{}'")
    feed.policy.purge(feed.dashboard.clock())
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT context_json FROM setup_levels').fetchone()[0] is None


def swarm_rows(path, now, rows):
    import json, sqlite3
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE swarm_alerts (id INTEGER PRIMARY KEY, ticker TEXT, posted_at REAL, analyst_count INTEGER, '
                'span_text TEXT, price REAL, members_json TEXT, message_id TEXT)')
    for ticker, age, members in rows:
        con.execute('INSERT INTO swarm_alerts(ticker,posted_at,analyst_count,span_text,price,members_json) VALUES (?,?,?,?,?,?)',
                    (ticker, now - age, len(members), '52 min', 242.44, json.dumps(members)))
    con.commit(); con.close()


def test_group_alerts_from_the_alerts_channel(feed, tmp_path):
    """Owner 2026-10-06: the #alerts posts (several analysts on one ticker) belong on the home page."""
    from dataclasses import replace
    from member_dashboard.market_reader import MarketReader, SourceCheckpoint, SourceName
    from member_dashboard.publication import publishable
    from test_source_policy import lineage
    now = feed.dashboard.clock()
    a = {'analyst': 'MarketRebels', 'direction': 'long', 'reason': 'Clears $6 trillion', 'reason_kind': 'event_claim'}
    b = {'analyst': 'ThetaWarrior', 'direction': 'unclear', 'reason': '', 'reason_kind': 'none'}
    swarm_rows(tmp_path / 'bot.db', now, [('NVDA', 300, [a, b]), ('NVDA', 60, [a, b, dict(b, analyst='kpak82')]),
                                          ('AVGO', 120, [a, dict(a, analyst='preetkailon')]),
                                          ('BAD', 30, [{'analyst': 'x y', 'direction': 'long'}])])
    batch = MarketReader(tmp_path / 'bot.db', clock=feed.dashboard.clock).read_batch(SourceName.SWARM, SourceCheckpoint())
    assert [r.ticker for r in batch.records] == ['NVDA', 'NVDA', 'AVGO'] and [t for _, t in batch.blocked_keys] == ['BAD']
    sources = lineage(); sources.required_features = ['feed']
    for row in batch.records:
        assert feed.publisher.save(publishable(replace(row, lineage=sources)), now)
    cards = latest(feed, 'alerts')
    assert [(c['ticker'], c['direction'], c['group']['analysts']) for c in cards] == [('NVDA', 'unclear', 3), ('AVGO', 'bullish', 2)]
    calls = cards[0]['group']['calls']
    assert {k:calls[0][k] for k in ('analyst','view','reason')} == {'analyst': 'MarketRebels', 'view': 'bullish', 'reason': 'Analyst says: Clears $6 trillion'}
    assert calls[1]['reason'] == 'reason not stated' and cards[0]['group']['span'] == '52 min' and cards[0]['price'] == 242.44
    assert latest(feed, 'feed') == []  # Analyst calls leave group alerts to their own panel.


def test_group_alert_preserves_each_post_time_source_and_chart(feed, tmp_path):
    from dataclasses import replace
    from member_dashboard.market_reader import MarketReader, SourceCheckpoint, SourceName
    from member_dashboard.publication import publishable
    from test_source_policy import lineage
    now = feed.dashboard.clock()
    member = dict(analyst='chart_author', direction='unclear', reason='', reason_kind='none',
                  observed_at=now-120, link='https://x.com/chart_author/status/123',
                  image_urls=['https://pbs.twimg.com/media/chart.png'])
    swarm_rows(tmp_path/'bot.db', now, [('MU', 60, [member, dict(member, analyst='another_author')])])
    batch = MarketReader(tmp_path/'bot.db', clock=feed.dashboard.clock).read_batch(SourceName.SWARM, SourceCheckpoint())
    sources = lineage(); sources.required_features = ['feed']
    assert feed.publisher.save(publishable(replace(batch.records[0], lineage=sources)), now)
    call = latest(feed, 'alerts')[0]['group']['calls'][0]
    assert call['observed_at'] == now-120
    assert call['url'] == member['link']
    assert call['image_urls'] == member['image_urls']
    assert 'Chart attached' in call['reason']
