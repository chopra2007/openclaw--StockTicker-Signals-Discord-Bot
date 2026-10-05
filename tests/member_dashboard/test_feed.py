"""Synthetic durable feed behavior, using real web transactions and HTTP reads."""
from dataclasses import replace
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import pytest

from test_source_policy import grant, lineage, policy
from member_dashboard.auth import Principal, digest
from member_dashboard.market_reader import MarketPayload, SourceName, SourceRecord
from member_dashboard.publication import Publisher, publishable


@pytest.fixture
def feed(dashboard):
    grant(dashboard, expires_at=None, review_at=None, retention_deadline=None, delete_on_expiry=False)
    permitted = policy(dashboard)
    dashboard.app.state.source_policy = permitted
    now = dashboard.clock()
    member, session = str(uuid4()), str(uuid4())
    with dashboard.store.transaction() as con:
        con.execute('INSERT INTO members(id,username,password_hash,role,created_at) VALUES (?,?,?,?,?)',
                    (member, 'feed_member', 'unused', 'member', now))
        con.execute('INSERT INTO sessions(id,member_id,token_digest,csrf_digest,created_at,last_seen_at,'
                    'absolute_expires_at,idle_expires_at) VALUES (?,?,?,?,?,?,?,?)',
                    (session, member, digest('feed-session'), digest('csrf'), now, now, now+43200, now+7200))
    dashboard.client.cookies.set('__Host-member_session', 'feed-session')
    return SimpleNamespace(dashboard=dashboard, policy=permitted,
        publisher=Publisher(dashboard.store, permitted), principal=Principal(member,'member',session,1))


def record(feed, key='post-a', version='v1', excerpt='First', feature='feed', extra_features=()):
    sources = lineage()
    sources.required_features = [feature, *extra_features]
    return SourceRecord(SourceName.ANALYST if feature=='feed' else SourceName.ALERT,
        key,'TEST',version,feed.dashboard.clock()-10,None,None,'bullish',excerpt,
        MarketPayload(ticker='TEST',direction='bullish',excerpt=excerpt),lineage=sources)


def publish(feed, **kwargs):
    value = publishable(record(feed, **kwargs))
    assert feed.publisher.save(value, feed.dashboard.clock())
    return value


def page(feed, cursor=None, feature='feed', limit=50):
    params={'limit':limit}
    if cursor is not None: params['cursor']=cursor
    return feed.dashboard.client.get('/api/v1/'+feature,params=params)


def service(feed, **kwargs):
    from member_dashboard.publication import FeedService
    result = FeedService(feed.dashboard.store,feed.dashboard.app.state.auth,feed.policy,
                        signing_key=b'synthetic-feed-test-signing-key-32',clock=feed.dashboard.clock,**kwargs)
    feed.dashboard.app.state.feed = result
    return result


def test_snapshot_then_revision_replaces_same_card_without_generation(feed):
    first_publication=publish(feed)
    first=page(feed)
    assert first.status_code==200
    first=first.json()
    assert first['snapshot'] and not first['has_more']
    assert first['records'][0]['id']==first_publication.card_id
    assert first['records'][0]['payload']['excerpt']=='First'
    publish(feed,version='v2',excerpt='Corrected')
    delta=page(feed,first['cursor']).json()
    assert not delta['snapshot']
    assert [(r['id'],r['payload']['excerpt']) for r in delta['records']]==[(first_publication.card_id,'Corrected')]
    assert page(feed,delta['cursor']).json()['records']==[]
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM publications').fetchone()[0]==2
        assert con.execute('SELECT count(*) FROM jobs').fetchone()[0]==0


def test_same_time_pagination_pins_snapshot_and_drains_delta(feed):
    originals=[publish(feed,key='post-'+str(n)) for n in range(4)]
    first=page(feed,limit=2)
    assert first.status_code==200
    first=first.json()
    assert first['has_more']
    publish(feed,key='post-3',version='v2',excerpt='Later')
    publish(feed,key='post-4')
    second=page(feed,first['cursor'],limit=2).json()
    assert second['snapshot'] and not second['has_more']
    records=first['records']+second['records']
    assert {r['id'] for r in records}=={p.card_id for p in originals}
    assert all(r['payload']['excerpt']=='First' for r in records)
    delta=page(feed,second['cursor'],limit=1).json()
    assert not delta['snapshot'] and delta['has_more']
    last=page(feed,delta['cursor'],limit=1).json()
    assert not last['has_more'] and len(last['records'])==1


def test_explicit_retraction_cannot_be_undone_by_polling_same_or_new_version(feed):
    publication=publish(feed)
    feed.publisher.retract('post-a','TEST',feed.dashboard.clock())
    assert not feed.publisher.save(publication,feed.dashboard.clock())
    assert not feed.publisher.save(publishable(record(feed,version='v2')),feed.dashboard.clock())


@pytest.mark.parametrize('feature',['feed','setups'])
def test_route_features_guard_each_feed_and_current_session(feed,feature):
    publish(feed,feature=feature)
    response=page(feed,feature=feature)
    assert response.status_code==200
    assert response.headers['cache-control']=='private, no-store'
    with feed.dashboard.store.transaction() as con:
        con.execute('UPDATE features SET enabled=0 WHERE name=?',(feature,))
    assert page(feed,feature=feature).status_code==403
    with feed.dashboard.store.transaction() as con:
        con.execute("UPDATE members SET status='suspended' WHERE id=?",(feed.principal.member_id,))
    assert page(feed).status_code==401


@pytest.mark.parametrize('cursor',['corrupt','x'*4097])
def test_corrupt_cursor_requests_explicit_snapshot_reset(feed,cursor):
    response=page(feed,cursor)
    assert response.status_code==409
    assert response.json()['error']=='snapshot_reset'


def test_snapshot_on_empty_store_is_usable_for_later_insertions(feed):
    first=page(feed)
    assert first.status_code==200
    assert first.json()['records']==[]
    publish(feed)
    assert len(page(feed,first.json()['cursor']).json()['records'])==1
