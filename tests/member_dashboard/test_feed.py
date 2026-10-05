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
    fixture = SimpleNamespace(dashboard=dashboard, policy=permitted,
        publisher=Publisher(dashboard.store, permitted), principal=Principal(member,'member',session,1))
    service(fixture)
    return fixture


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
        assert con.execute('SELECT count(*) FROM web_jobs').fetchone()[0]==0


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


@pytest.mark.parametrize('withdrawal',['source','dependency'])
def test_same_version_withdraw_restore_emits_ordered_changes(feed,withdrawal):
    original=publish(feed,extra_features=('analysis',))
    first=page(feed).json()
    if withdrawal=='source':
        feed.policy.authority_current=lambda:False
    else:
        with feed.dashboard.store.transaction() as con:
            con.execute("UPDATE features SET enabled=0 WHERE name='analysis'")
    sync=service(feed)
    assert sync.sync_publications(feed.dashboard.clock()).status=='ok'
    removed=page(feed,first['cursor']).json()
    assert removed['records']==[{'operation':'delete','id':original.card_id}]
    if withdrawal=='source': feed.policy.authority_current=lambda:True
    else:
        with feed.dashboard.store.transaction() as con:
            con.execute("UPDATE features SET enabled=1 WHERE name='analysis'")
    assert sync.sync_publications(feed.dashboard.clock()).status=='ok'
    restored=page(feed,removed['cursor']).json()
    assert restored['records'][0]['content_version']==original.content_version
    assert restored['records'][0]['operation']=='upsert'
    sync.sync_publications(feed.dashboard.clock())
    assert page(feed,restored['cursor']).json()['records']==[]
    with feed.dashboard.store.transaction() as con:
        assert [r[0] for r in con.execute('SELECT operation FROM publication_changes ORDER BY sequence')]==['upsert','delete','upsert']
        assert con.execute('SELECT count(*) FROM publications').fetchone()[0]==1


def test_current_permission_blocks_pinned_old_version_and_sends_content_free_delete(feed):
    for i in range(3): publish(feed,key=str(i))
    first=page(feed,limit=1).json()
    grant(feed.dashboard,policy_version='v2',display_raw=False)
    remaining=page(feed,first['cursor'],limit=100).json()
    assert len(remaining['records'])==2
    assert all(set(r)=={'operation','id'} and r['operation']=='delete' for r in remaining['records'])


def test_cursor_binds_feature_version_signature_and_expiry(feed):
    original=page(feed).json()['cursor']
    assert page(feed,original,feature='setups').status_code==409
    assert page(feed,original[:-1]+('0' if original[-1]!='0' else '1')).status_code==409
    with feed.dashboard.store.transaction() as con:
        con.execute("UPDATE features SET version=version+1 WHERE name='feed'")
    assert page(feed,original).status_code==409
    original=page(feed).json()['cursor']
    feed.dashboard.clock.advance(901)
    assert page(feed,original).status_code==409


def test_exact_retraction_annotation_retains_original_and_never_matches_proximity(feed):
    from member_dashboard.publication import evidence_retraction
    original=publish(feed)
    publish(feed,key='post-b')
    evidence=original.evidence[0]
    with feed.dashboard.store.transaction() as con:
        before=con.execute('SELECT content_json FROM publications WHERE source_post_key=?',('post-a',)).fetchone()[0]
    feed.publisher.retract('post-a','TEST',feed.dashboard.clock())
    with feed.dashboard.store.transaction() as con:
        annotation=evidence_retraction(con,evidence,feed.policy)
        assert annotation.status=='retracted' and annotation.recorded_at==feed.dashboard.clock()
        assert evidence_retraction(con,evidence.model_copy(update={'source_version':'different'}),feed.policy) is None
        assert evidence_retraction(con,evidence.model_copy(update={'id':'different'}),feed.policy) is None
        assert con.execute('SELECT content_json FROM publications WHERE source_post_key=?',('post-a',)).fetchone()[0]==before
    assert len(page(feed).json()['records'])==1


def test_denied_retraction_marker_survives_purge_restart_without_resurrection(feed):
    original=publish(feed)
    other=publish(feed,key='post-b')
    grant(feed.dashboard,policy_version='v2',tombstone_allowed=False)
    feed.publisher.retract('post-a','TEST',feed.dashboard.clock())
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM publication_retractions').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM evidence_retractions').fetchone()[0]==0
    grant(feed.dashboard,policy_version='v3',retain=False,tombstone_allowed=False)
    feed.policy.purge(feed.dashboard.clock())
    grant(feed.dashboard,policy_version='v4',tombstone_allowed=False)
    original=replace(original,lineage=lineage(version='v4'),content_version='reapproved-v4')
    other=replace(other,lineage=lineage(version='v4'),content_version='reapproved-v4')
    restarted=service(feed)
    assert not restarted.publisher.save(original,feed.dashboard.clock())
    assert not restarted.publisher.save(other,feed.dashboard.clock())
    assert page(feed).json()['records']==[]
    cleared=service(feed,retraction_clearance=lambda key,ticker:key=='post-b' and ticker=='TEST')
    assert not cleared.publisher.save(original,feed.dashboard.clock())
    assert cleared.publisher.save(other,feed.dashboard.clock())
    assert len(page(feed).json()['records'])==1


@pytest.fixture
def source_feed(feed):
    from member_dashboard.market_reader import MarketReader
    with sqlite3.connect(feed.dashboard.settings.market_path) as con:
        con.execute('CREATE TABLE ticker_signals(id INTEGER PRIMARY KEY,ticker TEXT,source_type TEXT,sentiment TEXT,'
                    'detected_at REAL,expires_at REAL)')
        con.executemany('INSERT INTO ticker_signals VALUES (?,?,?,?,?,?)',[
            (n,'TEST','synthetic','bullish',feed.dashboard.clock()-100,feed.dashboard.clock()+100) for n in range(1,151)])
    sync=service(feed,reader=MarketReader(feed.dashboard.settings.market_path,clock=feed.dashboard.clock),
                 lineage_resolver=lambda row:lineage())
    return feed,sync


def test_projection_budget_fair_progress_pruning_and_stale_schema(source_feed):
    feed,sync=source_feed
    for _ in range(12):
        stats=sync.sync_publications(feed.dashboard.clock())
        assert stats.status=='ok' and stats.scanned<=100 and stats.reconciled<=100
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM publication_heads WHERE active=1').fetchone()[0]==150
        checkpoint=con.execute("SELECT last_id FROM source_checkpoints WHERE source_id='ticker_signals'").fetchone()[0]
    with sqlite3.connect(feed.dashboard.settings.market_path) as con:
        con.execute('DELETE FROM ticker_signals')
    sync.sync_publications(feed.dashboard.clock())
    assert len(page(feed,limit=100).json()['records'])==100
    with sqlite3.connect(feed.dashboard.settings.market_path) as con:
        con.execute('DROP TABLE ticker_signals')
    sync.sync_publications(feed.dashboard.clock())
    response=page(feed,limit=1).json()
    assert response['records'][0]['source']=='ticker_signals'
    assert response['records'][0]['stale']
    assert next(s for s in response['sources'] if s['source']=='ticker_signals')['status']=='unavailable'
    cursor=response['cursor']
    while response['has_more']:
        response=page(feed,cursor,limit=100).json()
        cursor=response['cursor']
    response=page(feed,cursor).json()
    assert response['records']==[]
    assert next(s for s in response['sources'] if s['source']=='ticker_signals')['status']=='unavailable'
    with feed.dashboard.store.transaction() as con:
        assert con.execute("SELECT last_id FROM source_checkpoints WHERE source_id='ticker_signals'").fetchone()[0]==checkpoint


def test_default_lineage_stays_closed_and_polls_do_not_read_sources(source_feed):
    feed,sync=source_feed
    closed=service(feed,reader=sync.reader)
    closed.sync_publications(feed.dashboard.clock())
    assert page(feed).json()['records']==[]
    sync.sync_publications(feed.dashboard.clock())
    def forbidden(*args,**kwargs): raise AssertionError('source/provider work from poll')
    sync.reader.read_batch=forbidden
    feed.dashboard.app.state.feed=sync
    assert page(feed).status_code==200


def test_projection_unknown_new_lineage_withdraws_old_card(source_feed):
    feed,sync=source_feed
    sync.sync_publications(feed.dashboard.clock())
    with sqlite3.connect(feed.dashboard.settings.market_path) as con:
        con.execute("UPDATE ticker_signals SET sentiment='bearish'")
    sync.lineage_resolver=lambda row:None
    for _ in range(12): sync.sync_publications(feed.dashboard.clock())
    assert all(r['operation']=='delete' for r in page(feed,limit=100).json()['records'])


def test_same_version_policy_restore_survives_pruning_during_withdrawal(source_feed):
    feed,sync=source_feed
    with sqlite3.connect(feed.dashboard.settings.market_path) as con:
        con.execute('DELETE FROM ticker_signals WHERE id>1')
    sync.sync_publications(feed.dashboard.clock())
    before=page(feed).json()['records'][0]
    feed.policy.authority_current=lambda:False
    sync.sync_publications(feed.dashboard.clock())
    sync.sync_publications(feed.dashboard.clock())
    assert page(feed).json()['records']==[]
    with sqlite3.connect(feed.dashboard.settings.market_path) as con:
        con.execute('DELETE FROM ticker_signals')
    feed.policy.authority_current=lambda:True
    sync.sync_publications(feed.dashboard.clock())
    after=page(feed).json()['records']
    assert len(after)==1 and after[0]['content_version']==before['content_version']


def test_lock_contention_returns_quickly_and_callback_contains_ordinary_failure(feed):
    import time
    sync=service(feed)
    with feed.dashboard.store.transaction():
        started=time.monotonic()
        result=sync.sync_publications(feed.dashboard.clock())
        elapsed=time.monotonic()-started
    assert result.status=='unavailable' and elapsed<1.1
    def fail(_): raise RuntimeError('synthetic unexpected failure')
    sync.sync_publications=fail
    assert sync.feed_tick(feed.dashboard.clock()).status=='failed'
    def stop(_): raise KeyboardInterrupt()
    sync.sync_publications=stop
    with pytest.raises(KeyboardInterrupt): sync.feed_tick(feed.dashboard.clock())


def test_feed_retention_does_not_delete_saved_history_and_log_floor_is_durable(feed):
    original=publish(feed)
    with feed.dashboard.store.transaction() as con:
        con.execute('INSERT INTO report_versions(id,report_id,version,content_json,created_at) VALUES (?,?,?,?,?)',
                    (str(uuid4()),str(uuid4()),1,'{}',feed.dashboard.clock()))
    feed.dashboard.clock.advance(8*86400)
    # Read service tests use a new long-lived synthetic session, not an expired one.
    with feed.dashboard.store.transaction() as con:
        con.execute('UPDATE sessions SET absolute_expires_at=?,idle_expires_at=?',
                    (feed.dashboard.clock()+43200,feed.dashboard.clock()+7200))
    old=page(feed).json()['cursor']
    sync=service(feed)
    sync.sync_publications(feed.dashboard.clock())
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM publication_changes').fetchone()[0]==0
        assert con.execute('SELECT retained_floor FROM feed_state').fetchone()[0]>0
    assert page(feed,old).status_code==200 # already consumed the purged transition
    assert page(feed).json()['records'][0]['id']==original.card_id # active interval survives log retention
    feed.dashboard.clock.advance(83*86400)
    sync.sync_publications(feed.dashboard.clock())
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM publications').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM report_versions').fetchone()[0]==1


@pytest.mark.parametrize('lifecycle',['withdrawn','restored','retracted','empty'])
def test_upgrade_preserves_lifecycle_sequences_deleted_highwater_and_immutability(tmp_path,lifecycle):
    from pathlib import Path
    from member_dashboard.store import WebStore
    from member_dashboard.publication import card_identity
    path=tmp_path/'upgrade.sqlite3'
    migration_dir=Path(__file__).parents[2]/'member_dashboard'/'migrations'
    card=card_identity('historical','TEST')
    with sqlite3.connect(path) as con:
        con.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at REAL NOT NULL) STRICT')
        for number in range(1,6):
            con.executescript(next(migration_dir.glob(f'{number:03}_*.sql')).read_text())
            con.execute('INSERT INTO schema_migrations VALUES (?,?)',(number,1.0))
        con.execute('INSERT INTO publications(id,source_post_key,ticker,content_version,feature,content_json,published_at,retracted_at) '
                    'VALUES (?,?,?,?,?,?,?,?)',(str(uuid4()),'historical','TEST','v1','feed','{}',1.0,2.0 if lifecycle=='retracted' else None))
        con.execute('INSERT INTO publication_changes(sequence,card_id,content_version,operation,feature,changed_at) '
                    'VALUES (100,?,?,?, ?,?)',(card,'v1','upsert','feed',1.0))
        if lifecycle in {'withdrawn','restored'}:
            con.execute('INSERT INTO publication_changes(sequence,card_id,content_version,operation,feature,changed_at) '
                        'VALUES (101,?,?,?, ?,?)',(card,'v1','delete','feed',2.0))
        if lifecycle=='restored':
            con.execute('INSERT INTO publications(id,source_post_key,ticker,content_version,feature,content_json,published_at) '
                        'VALUES (?,?,?,?,?,?,?)',(str(uuid4()),'historical','TEST','v2','feed','{}',3.0))
            con.execute('INSERT INTO publication_changes(sequence,card_id,content_version,operation,feature,changed_at) '
                        'VALUES (102,?,?,?, ?,?)',(card,'v2','upsert','feed',3.0))
        con.execute("UPDATE sqlite_sequence SET seq=500 WHERE name='publication_changes'")
        if lifecycle=='empty': con.execute('DELETE FROM publication_changes')
    store=WebStore(path)
    store.migrate()
    with store.transaction() as con:
        assert con.execute("SELECT seq FROM sqlite_sequence WHERE name='publication_changes'").fetchone()[0]==500
        rows=con.execute('SELECT sequence FROM publication_changes ORDER BY sequence').fetchall()
        assert rows==([] if lifecycle=='empty' else [(100,),(101,),(102,)] if lifecycle=='restored' else [(100,),(101,)] if lifecycle=='withdrawn' else [(100,)])
        active=con.execute('SELECT active FROM publication_heads').fetchall()
        assert active==([] if lifecycle=='empty' else [(1,)] if lifecycle=='restored' else [(0,)])
        assert con.execute('SELECT count(*) FROM publication_intervals WHERE end_sequence IS NULL').fetchone()[0]==(1 if lifecycle=='restored' else 0)
        new=con.execute('INSERT INTO publication_changes(card_id,content_version,operation,feature,changed_at) '
                        'VALUES (?,?,?,?,?)',(card,'v1','upsert','feed',4.0)).lastrowid
        assert new==501
        with pytest.raises(sqlite3.IntegrityError,match='immutable publication change'):
            con.execute('UPDATE publication_changes SET changed_at=9 WHERE sequence=501')
        with pytest.raises(sqlite3.IntegrityError,match='immutable publication'):
            con.execute("UPDATE publications SET content_json='{}'")


def test_policy_purge_log_gap_resets_cursor_and_does_not_withdraw_newer_revision(feed):
    original=publish(feed)
    first=page(feed).json()['cursor']
    publish(feed,version='v2')
    grant(feed.dashboard,policy_version='v2',retain=False)
    feed.policy.purge(feed.dashboard.clock())
    assert page(feed,first).status_code==409
    assert page(feed).json()['records']==[]
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT active FROM publication_heads WHERE card_id=?',(original.card_id,)).fetchone()[0]==0
        operations=[r[0] for r in con.execute('SELECT operation FROM publication_changes')]
        assert operations==['delete']


def test_purging_only_old_revision_keeps_current_card(feed):
    original=publish(feed)
    grant(feed.dashboard,policy_version='v2')
    current=replace(publishable(record(feed,version='v2')),lineage=lineage(version='v2'))
    assert feed.publisher.save(current,feed.dashboard.clock())
    feed.policy.purge(feed.dashboard.clock())
    assert page(feed).json()['records'][0]['content_version']==current.content_version
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT active FROM publication_heads WHERE card_id=?',(original.card_id,)).fetchone()[0]==1
        assert con.execute("SELECT count(*) FROM publication_changes WHERE operation='delete'").fetchone()[0]==0


def test_no_market_query_before_feature_and_session_revalidation(feed):
    from member_dashboard.publication import FeedError
    from member_dashboard.auth import AuthError
    sync=service(feed)
    with feed.dashboard.store.transaction() as con:
        con.execute('DROP TABLE publication_intervals')
        con.execute("UPDATE features SET enabled=0 WHERE name='feed'")
    with pytest.raises(FeedError,match='forbidden'): sync.read_feed(feed.principal,'feed')
    with feed.dashboard.store.transaction() as con:
        con.execute("UPDATE members SET status='suspended'")
    with pytest.raises(AuthError): sync.read_feed(feed.principal,'setups')


def test_callback_failure_still_allows_supervisor_to_kill_draining_child(feed):
    from member_dashboard.worker import WorkerSupervisor
    class Child:
        worker_id='synthetic'
        stopped=False
        killed=False
        def is_dead(self): return False
        def request_stop(self): self.stopped=True
        def kill_tree(self): self.killed=True
    child=Child()
    sync=service(feed)
    def failed(_): raise RuntimeError('synthetic projection failure')
    sync.sync_publications=failed
    supervisor=WorkerSupervisor(feed.dashboard.store,lambda:child,sync.feed_tick,jobs=feed.dashboard.app.state.research,clock=feed.dashboard.clock)
    supervisor.child=child
    supervisor.request_restart()
    supervisor.tick()
    assert child.stopped
    feed.dashboard.clock.advance(5)
    supervisor.tick()
    assert child.killed


def test_invalid_authority_exact_key_withdrawal_is_reversible(source_feed):
    feed,sync=source_feed
    sync.sync_publications(feed.dashboard.clock())
    original=page(feed,limit=1).json()['records'][0]
    with sqlite3.connect(feed.dashboard.settings.market_path) as con:
        con.execute("UPDATE ticker_signals SET detected_at='invalid'")
    for _ in range(12): sync.sync_publications(feed.dashboard.clock())
    assert page(feed).json()['records']==[]
    with sqlite3.connect(feed.dashboard.settings.market_path) as con:
        con.execute('UPDATE ticker_signals SET detected_at=?',(feed.dashboard.clock()-100,))
    for _ in range(12): sync.sync_publications(feed.dashboard.clock())
    records=page(feed,limit=100).json()['records']
    assert original['id'] in {r['id'] for r in records}


def test_permanent_marker_wins_over_external_clearance(feed):
    original=publish(feed)
    feed.publisher.retract('post-a','TEST',feed.dashboard.clock())
    sync=service(feed,retraction_clearance=lambda key,ticker:True)
    assert not sync.publisher.save(original,feed.dashboard.clock())


def test_annotation_requires_current_external_permission_authority(feed):
    publish(feed)
    feed.policy.authority_current=lambda:False
    feed.publisher.retract('post-a','TEST',feed.dashboard.clock())
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM publication_retractions').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM evidence_retractions').fetchone()[0]==0
        assert con.execute('SELECT retraction_authority_required FROM feed_state').fetchone()[0]==1


def test_cursor_floor_persists_when_all_upserts_are_purged(feed):
    first=page(feed).json()['cursor']
    publish(feed)
    grant(feed.dashboard,policy_version='v2',retain=False)
    feed.policy.purge(feed.dashboard.clock())
    service(feed)
    assert page(feed,first).status_code==409


def test_feed_signing_key_is_explicit_and_not_serialized(dashboard):
    from member_dashboard.settings import Settings
    with pytest.raises(ValueError,match='signing key'):
        Settings(dashboard.settings.web_path,dashboard.settings.market_path,feed_signing_key=b'short')
    assert 'synthetic-feed-test-signing-key' not in repr(replace(dashboard.settings,feed_signing_key=b'synthetic-feed-test-signing-key-32'))


@pytest.mark.parametrize('limit',[0,101,-1,'junk','1.5'])
def test_route_limit_validation(feed,limit):
    assert page(feed,limit=limit).status_code==422


def test_sync_commits_checkpoint_and_publications_atomically_on_failure(source_feed):
    feed,sync=source_feed
    seen=0
    def resolver(row):
        nonlocal seen
        seen+=1
        if seen==2: raise RuntimeError('synthetic interrupted projection')
        return lineage()
    sync.lineage_resolver=resolver
    assert sync.feed_tick(feed.dashboard.clock()).status=='failed'
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM source_checkpoints').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM publications').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM publication_changes').fetchone()[0]==0
    sync.lineage_resolver=lambda row:lineage()
    assert sync.sync_publications(feed.dashboard.clock()).published>0


def test_deadline_stops_source_loop_and_rotates_next_turn(feed):
    import time
    from member_dashboard.market_reader import SourceBatch,SourceCheckpoint
    calls=[]
    class SlowReader:
        def read_batch(self,source,checkpoint,limit):
            calls.append(source)
            time.sleep(.17)
            return SourceBatch((),SourceCheckpoint('1'))
    sync=service(feed,reader=SlowReader())
    started=time.monotonic()
    assert sync.sync_publications(feed.dashboard.clock()).status=='ok'
    assert time.monotonic()-started<1.1
    assert 1<=len(calls)<6
    previous=calls[0]
    calls.clear()
    assert sync.sync_publications(feed.dashboard.clock()).status=='ok'
    assert calls[0]!=previous


def test_polls_never_create_publications_or_optional_summary_jobs(source_feed):
    feed,sync=source_feed
    sync.sync_publications(feed.dashboard.clock())
    with feed.dashboard.store.transaction() as con:
        counts=tuple(con.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in ('publications','publication_changes','web_jobs'))
    cursor=None
    for _ in range(5): cursor=page(feed,cursor).json()['cursor']
    with feed.dashboard.store.transaction() as con:
        assert tuple(con.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in ('publications','publication_changes','web_jobs'))==counts


def test_retained_revision_explicit_marker_remains_after_feed_retention(feed):
    original=publish(feed)
    feed.publisher.retract('post-a','TEST',feed.dashboard.clock())
    feed.dashboard.clock.advance(91*86400)
    sync=service(feed)
    sync.sync_publications(feed.dashboard.clock())
    assert not sync.publisher.save(original,feed.dashboard.clock())
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM publications').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM publication_retractions').fetchone()[0]==1


def test_retraction_covers_exact_saved_evidence_after_old_feed_revision_is_purged(feed):
    from member_dashboard.publication import evidence_retraction
    original=publish(feed)
    saved=original.evidence[0].model_dump_json()
    with feed.dashboard.store.transaction() as con:
        con.execute('INSERT INTO report_versions(id,report_id,version,content_json,created_at) VALUES (?,?,?,?,?)',
                    (str(uuid4()),str(uuid4()),1,saved,feed.dashboard.clock()))
    feed.dashboard.clock.advance(89*86400)
    publish(feed,version='v2',excerpt='Later')
    feed.dashboard.clock.advance(2*86400)
    assert service(feed).sync_publications(feed.dashboard.clock()).status=='ok'
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM publications').fetchone()[0]==1
        assert con.execute('SELECT retraction_authority_required FROM feed_state').fetchone()[0]==0
    feed.publisher.retract('post-a','TEST',feed.dashboard.clock())
    with feed.dashboard.store.transaction() as con:
        annotation=evidence_retraction(con,original.evidence[0],feed.policy)
        assert annotation is not None and annotation.status=='retracted'
        assert con.execute('SELECT content_json FROM report_versions').fetchone()[0]==saved
        assert con.execute('SELECT retraction_authority_required FROM feed_state').fetchone()[0]==0
        assert evidence_retraction(con,original.evidence[0].model_copy(update={'source_version':'not-the-saved-version'}),feed.policy) is None
    unrelated=publish(feed,key='unrelated')
    with feed.dashboard.store.transaction() as con:
        con.execute('UPDATE sessions SET absolute_expires_at=?,idle_expires_at=?',
                    (feed.dashboard.clock()+43200,feed.dashboard.clock()+7200))
    assert [row['id'] for row in page(feed).json()['records']]==[unrelated.card_id]


def test_unchanged_null_observation_uses_source_computation_age_after_purge(feed):
    original=replace(record(feed,feature='setups'),source=SourceName.RESEARCH,
                     observed_at=None,computed_at=feed.dashboard.clock()-10)
    publication=publishable(original)
    assert feed.publisher.save(publication,feed.dashboard.clock())
    response=page(feed,feature='setups').json()['records'][0]
    assert response['observed_at'] is None and response['projected_at']==feed.dashboard.clock()
    assert response['published_at'] is None
    feed.dashboard.clock.advance(91*86400)
    assert service(feed).sync_publications(feed.dashboard.clock()).status=='ok'
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM publications').fetchone()[0]==0
    assert not feed.publisher.save(publishable(original),feed.dashboard.clock())


def test_publication_without_provable_source_age_fails_closed(feed):
    original=replace(record(feed,feature='setups'),source=SourceName.RESEARCH,observed_at=None,computed_at=None)
    assert not feed.publisher.save(publishable(original),feed.dashboard.clock())


def test_null_observation_retention_ends_from_computation_age_not_projection(feed):
    original=replace(record(feed,feature='setups'),source=SourceName.RESEARCH,
                     observed_at=None,computed_at=feed.dashboard.clock()-89*86400)
    assert feed.publisher.save(publishable(original),feed.dashboard.clock())
    feed.dashboard.clock.advance(2*86400)
    service(feed).sync_publications(feed.dashboard.clock())
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM publications').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM publication_evidence_refs').fetchone()[0]==1


def test_source_policy_purge_archives_exact_evidence_before_deleting_content(feed):
    from member_dashboard.publication import evidence_retraction
    original=publish(feed)
    grant(feed.dashboard,policy_version='v2',retain=False,tombstone_allowed=True)
    feed.policy.purge(feed.dashboard.clock())
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM publications').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM publication_evidence_refs').fetchone()[0]==1
        assert con.execute('SELECT retraction_authority_required FROM feed_state').fetchone()[0]==0
    feed.publisher.retract('post-a','TEST',feed.dashboard.clock())
    with feed.dashboard.store.transaction() as con:
        assert evidence_retraction(con,original.evidence[0],feed.policy).status=='retracted'


@pytest.mark.parametrize('change',['rights','authority'])
def test_archived_evidence_refs_revoke_with_latch_before_identity_loss(feed,change):
    from member_dashboard.publication import evidence_retraction
    original=publish(feed)
    feed.dashboard.clock.advance(91*86400)
    service(feed).sync_publications(feed.dashboard.clock())
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM publication_evidence_refs').fetchone()[0]==1
    if change=='rights': grant(feed.dashboard,policy_version='v2',tombstone_allowed=False)
    else: feed.policy.authority_current=lambda:False
    result=feed.policy.purge(feed.dashboard.clock(),limit=1)
    assert 'publication_evidence_refs' in result.cursors
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM publication_evidence_refs').fetchone()[0]==0
        assert con.execute('SELECT retraction_authority_required FROM feed_state').fetchone()[0]==1
        assert evidence_retraction(con,original.evidence[0],feed.policy).status=='unavailable'


def test_lost_archive_union_across_cleanup_turns_cannot_reappear_as_partial_proof(feed):
    from member_dashboard.publication import evidence_retraction
    base=lineage().sources[0]
    for start in (0,1,2):
        contributors=lineage()
        contributors.sources=[base.model_copy(update={'source_version':f'version-{n}'}) for n in range(start,start+200)]
        candidate=publishable(replace(record(feed),lineage=contributors))
        assert feed.publisher.save(candidate,feed.dashboard.clock())
    grant(feed.dashboard,policy_version='v2',retain=False,tombstone_allowed=True)
    first=feed.policy.purge(feed.dashboard.clock(),limit=1)
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM publication_evidence_refs').fetchone()[0]==1
        assert con.execute('SELECT retraction_authority_required FROM feed_state').fetchone()[0]==0
    second=feed.policy.purge(feed.dashboard.clock(),limit=1,cursors=first.cursors)
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM publication_evidence_refs').fetchone()[0]==0
        assert con.execute('SELECT retraction_authority_required FROM feed_state').fetchone()[0]==1
    feed.policy.purge(feed.dashboard.clock(),limit=1,cursors=second.cursors)
    feed.publisher.retract('post-a','TEST',feed.dashboard.clock())
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM publication_evidence_refs').fetchone()[0]==0
        assert evidence_retraction(con,candidate.evidence[0],feed.policy).status=='unavailable'


def test_global_lost_coverage_overrides_later_partial_annotation(feed):
    from member_dashboard.publication import evidence_retraction
    original=publish(feed)
    feed.publisher.retract('post-a','TEST',feed.dashboard.clock())
    with feed.dashboard.store.transaction() as con:
        con.execute('UPDATE feed_state SET retraction_authority_required=1')
        assert evidence_retraction(con,original.evidence[0],feed.policy).status=='unavailable'
    assert not service(feed,retraction_clearance=lambda key,ticker:True).publisher.save(original,feed.dashboard.clock())


def test_archived_identity_unions_contributors_across_separate_policy_purges(feed):
    import json
    from member_dashboard.publication import evidence_retraction
    original=publish(feed)
    grant(feed.dashboard,source='other')
    combined=lineage()
    combined.sources.extend(lineage('other').sources)
    second=publishable(replace(record(feed),lineage=combined))
    assert feed.publisher.save(second,feed.dashboard.clock())
    grant(feed.dashboard,policy_version='v2',retain=False,tombstone_allowed=True)
    first=feed.policy.purge(feed.dashboard.clock(),limit=1)
    feed.policy.purge(feed.dashboard.clock(),limit=1,cursors=first.cursors)
    with feed.dashboard.store.transaction() as con:
        refs=con.execute('SELECT source_lineage_json FROM publication_evidence_refs').fetchall()
        assert len(refs)==1 and {s['source_id'] for s in json.loads(refs[0][0])}=={'permitted','other'}
    feed.publisher.retract('post-a','TEST',feed.dashboard.clock())
    with feed.dashboard.store.transaction() as con:
        assert evidence_retraction(con,original.evidence[0],feed.policy).status=='retracted'
    grant(feed.dashboard,source='other',policy_version='v2',tombstone_allowed=False)
    with feed.dashboard.store.transaction() as con:
        assert evidence_retraction(con,original.evidence[0],feed.policy).status=='unavailable'


def test_feed_cleanup_commits_bounded_archive_progress_before_deadline(feed):
    import time
    for n in range(80): publish(feed,key=f'old-{n}')
    feed.dashboard.clock.advance(91*86400)
    def slow_authority():
        time.sleep(.015)
        return True
    feed.policy.authority_current=slow_authority
    sync=service(feed)
    started=time.monotonic()
    sync.sync_publications(feed.dashboard.clock())
    assert time.monotonic()-started<1.1
    with feed.dashboard.store.transaction() as con:
        remaining=con.execute('SELECT count(*) FROM publications').fetchone()[0]
        assert 0<remaining<80
        assert con.execute('SELECT count(*) FROM publication_evidence_refs').fetchone()[0]==80-remaining
    sync.sync_publications(feed.dashboard.clock())
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM publications').fetchone()[0]==0


def test_stale_source_record_cannot_restart_ninety_day_feed_retention(source_feed):
    feed,sync=source_feed
    sync.sync_publications(feed.dashboard.clock())
    feed.dashboard.clock.advance(91*86400)
    sync.sync_publications(feed.dashboard.clock())
    sync.sync_publications(feed.dashboard.clock())
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM publications').fetchone()[0]==0


def test_current_delay_and_attribution_are_public_but_private_lineage_is_not(feed):
    grant(feed.dashboard,policy_version='v2',delay_seconds=60)
    candidate=replace(publishable(record(feed)),lineage=lineage(version='v2'))
    assert not feed.publisher.save(candidate,feed.dashboard.clock())
    candidate=replace(candidate,observed_at=feed.dashboard.clock()-70)
    assert feed.publisher.save(candidate,feed.dashboard.clock())
    response=page(feed).json()
    assert response['records'][0]['delay_seconds']==60
    assert response['records'][0]['payload']['attributions']==['Synthetic public attribution']
    assert 'private-fixture' not in str(response) and 'policy_version' not in str(response)


def test_query_deadline_bounds_snapshot_read_on_large_backlog(feed,monkeypatch):
    import member_dashboard.publication as publication
    sync=service(feed)
    deadline_clock=SimpleNamespace(now=0.0)
    monkeypatch.setattr(publication,'time',SimpleNamespace(monotonic=lambda:deadline_clock.now))
    with pytest.raises(sqlite3.OperationalError,match='interrupted'):
        with sync._transaction(1.0) as con:
            deadline_clock.now=2.0
            con.execute('WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<10000000) SELECT sum(x) FROM n').fetchone()


def test_twenty_member_local_projection_and_poll_latency(source_feed):
    from concurrent.futures import ThreadPoolExecutor
    import time
    feed,sync=source_feed
    started=time.monotonic()
    feed.dashboard.clock.advance(5)
    stats=sync.sync_publications(feed.dashboard.clock())
    assert stats.status=='ok' and stats.published>0
    principals=[]
    now=feed.dashboard.clock()
    with feed.dashboard.store.transaction() as con:
        for n in range(20):
            member,session=str(uuid4()),str(uuid4())
            con.execute('INSERT INTO members(id,username,password_hash,role,created_at) VALUES (?,?,?,?,?)',
                        (member,f'load_{n}','unused','member',now))
            con.execute('INSERT INTO sessions(id,member_id,token_digest,csrf_digest,created_at,last_seen_at,'
                        'absolute_expires_at,idle_expires_at) VALUES (?,?,?,?,?,?,?,?)',
                        (session,member,digest(f'load_{n}'),digest('csrf'),now,now,now+43200,now+7200))
            principals.append(Principal(member,'member',session,1))
    feed.dashboard.clock.advance(15)
    with ThreadPoolExecutor(max_workers=20) as pool:
        pages=list(pool.map(lambda principal:sync.read_feed(principal,'feed'),principals))
    elapsed=time.monotonic()-started
    assert all(value.records and value.records[0].operation=='upsert' for value in pages)
    assert elapsed<5 # local budget leaves ample room within the 15-30 second cadence
    assert all(value.records[0].projected_at==now for value in pages)
    print(f'20-member synthetic projection/poll: {elapsed:.3f}s wall; visible after 20s synthetic cadence')


def test_slow_permission_reconciliation_commits_bounded_fair_progress(source_feed):
    import time
    feed,sync=source_feed
    for _ in range(12): sync.sync_publications(feed.dashboard.clock())
    sync.reader=None
    original=feed.policy._authorize_lineage
    def slow(*args,**kwargs):
        time.sleep(.007)
        return original(*args,**kwargs)
    feed.policy._authorize_lineage=slow
    feed.policy.authority_current=lambda:False
    started=time.monotonic()
    result=sync.sync_publications(feed.dashboard.clock())
    assert time.monotonic()-started<1.1
    assert result.reconciled>0
    with feed.dashboard.store.transaction() as con:
        removed=con.execute('SELECT count(*) FROM publication_heads WHERE active=0').fetchone()[0]
        assert 0<removed<150
    for _ in range(3): sync.sync_publications(feed.dashboard.clock())
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM publication_heads WHERE active=1').fetchone()[0]==0


@pytest.mark.parametrize('change',['rights','authority'])
def test_retraction_metadata_revocation_latches_before_bounded_purge(feed,change):
    from member_dashboard.publication import evidence_retraction
    original=publish(feed)
    feed.publisher.retract('post-a','TEST',feed.dashboard.clock())
    if change=='rights':
        grant(feed.dashboard,policy_version='v2',tombstone_allowed=False)
    else: feed.policy.authority_current=lambda:False
    with feed.dashboard.store.transaction() as con:
        annotation=evidence_retraction(con,original.evidence[0],feed.policy)
        assert annotation.status=='unavailable' and annotation.recorded_at is None
    feed.policy.purge(feed.dashboard.clock(),limit=1)
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT retraction_authority_required FROM feed_state').fetchone()[0]==1
        assert con.execute('SELECT count(*) FROM publication_retractions').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM evidence_retractions').fetchone()[0]==0
        annotation=evidence_retraction(con,original.evidence[0],feed.policy)
        assert annotation.status=='unavailable'
        mapping=con.execute('SELECT source_key,ticker FROM publication_heads').fetchone()
        assert mapping==(None,None) or change=='rights'
    # Current permission can return, but erased retraction authority cannot be
    # guessed from the now-empty marker table.
    feed.policy.authority_current=lambda:True
    restored=replace(original,lineage=lineage(version='v2') if change=='rights' else original.lineage)
    assert not service(feed).publisher.save(restored,feed.dashboard.clock())


def test_marker_reconciliation_is_bounded_and_scans_past_still_allowed_rows(feed):
    for n in range(3):
        publish(feed,key=f'post-{n}')
        feed.publisher.retract(f'post-{n}','TEST',feed.dashboard.clock())
    first=feed.policy.purge(feed.dashboard.clock(),limit=1)
    assert first.more
    grant(feed.dashboard,policy_version='v2',tombstone_allowed=False)
    second=feed.policy.purge(feed.dashboard.clock(),limit=1,cursors=first.cursors)
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM publication_retractions').fetchone()[0]==2
    assert second.more


def test_repeated_exact_evidence_retraction_unions_all_contributors(feed):
    import json
    from member_dashboard.publication import evidence_retraction
    first=publish(feed)
    grant(feed.dashboard,source='other')
    combined=lineage()
    combined.sources.extend(lineage('other').sources)
    second=publishable(replace(record(feed),lineage=combined))
    assert feed.publisher.save(second,feed.dashboard.clock())
    assert first.evidence[0]==second.evidence[0]
    feed.publisher.retract('post-a','TEST',feed.dashboard.clock())
    with feed.dashboard.store.transaction() as con:
        rows=con.execute('SELECT source_lineage_json FROM evidence_retractions').fetchall()
        assert len(rows)==1
        assert {s['source_id'] for s in json.loads(rows[0][0])}=={'permitted','other'}
    grant(feed.dashboard,source='other',policy_version='v2',tombstone_allowed=False)
    with feed.dashboard.store.transaction() as con:
        assert evidence_retraction(con,first.evidence[0],feed.policy).status=='unavailable'


def test_marker_union_over_cap_keeps_no_incomplete_identity_mapping(feed):
    from member_dashboard.publication import evidence_retraction
    original=record(feed)
    base=lineage().sources[0]
    for start in (0,1,2):
        contributors=lineage()
        contributors.sources=[base.model_copy(update={'source_version':f'version-{n}'}) for n in range(start,start+200)]
        candidate=publishable(replace(original,lineage=contributors))
        assert feed.publisher.save(candidate,feed.dashboard.clock())
    feed.publisher.retract('post-a','TEST',feed.dashboard.clock())
    with feed.dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM publication_retractions').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM evidence_retractions').fetchone()[0]==0
        assert con.execute('SELECT retraction_authority_required FROM feed_state').fetchone()[0]==1
        assert evidence_retraction(con,candidate.evidence[0],feed.policy).status=='unavailable'
