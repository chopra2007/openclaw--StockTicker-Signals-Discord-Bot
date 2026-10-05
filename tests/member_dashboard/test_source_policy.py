"""Real web SQLite policy checks; each test catches an authorization/purge break."""
from dataclasses import replace
import json
from uuid import uuid4

import pytest


def policy(dashboard, **kwargs):
    from member_dashboard.source_policy import SourcePolicy
    return SourcePolicy(dashboard.store, authority_current=lambda: True,
                        backup_compliant=lambda source, product: True, **kwargs)


def grant(dashboard, source='permitted', **changes):
    from member_dashboard.source_policy import SourcePermission
    values = dict(source_id=source, product_id='fixture-product', provider='synthetic',
                  private_grant_ref='private-fixture-grant', private_account_ref='private-fixture-account',
                  policy_version='v1', audience='invited_members', status='allowed',
                  display_raw=True, display_derived=True, retain=True, model_input=False,
                  effective_at=dashboard.clock.now-100, expires_at=dashboard.clock.now+100,
                  review_at=dashboard.clock.now+90, retention_deadline=dashboard.clock.now+100,
                  terms_url='https://www.sec.gov/fixture-policy', evidence_ref='private-fixture-proof',
                  attribution='Synthetic public attribution', delay_seconds=0,
                  delete_on_expiry=True, tombstone_allowed=True)
    values.update(changes)
    item = SourcePermission(**values)
    policy(dashboard).record(item)
    return item


def lineage(source='permitted', version='v1'):
    from member_dashboard.contracts import ContentLineage, SourceContribution
    return ContentLineage(sources=[SourceContribution(source_id=source,product_id='fixture-product',
                                                     source_version='content-v1',policy_version=version)],
                          required_features=['feed'],field_dependencies=[],retention_deadline=None)


@pytest.mark.parametrize('use,want', [('display_raw','allowed'),('display_derived','allowed'),
                                     ('retain','allowed'),('model_input','denied')])
def test_each_use_requires_its_own_grant(dashboard,use,want):
    grant(dashboard)
    assert policy(dashboard).authorize(lineage().sources,use,dashboard.clock.now).status == want


@pytest.mark.parametrize('changes,want', [({'status':'denied'},'denied'),
    ({'status':'unverified'},'unverified'),({'expires_at':1.0},'denied'),
    ({'review_at':1.0},'unverified'),({'private_grant_ref':None},'unverified'),
    ({'evidence_ref':None},'unverified'),({'audience':'personal'},'denied')])
def test_invalid_or_expired_grant_fails_closed(dashboard,changes,want):
    grant(dashboard,**changes)
    assert policy(dashboard).authorize(lineage().sources,'display_derived',dashboard.clock.now).status == want


def test_mixed_result_cannot_hide_unverified_contributor(dashboard):
    grant(dashboard)
    mixed=lineage()
    mixed.sources.extend(lineage('unknown').sources)
    for use in ['display_raw','display_derived','retain','model_input']:
        assert not policy(dashboard).authorize(mixed.sources,use,dashboard.clock.now).allowed
    assert not policy(dashboard).authorize([], 'display_raw',dashboard.clock.now).allowed
    assert not policy(dashboard).authorize(['permitted'], 'display_raw',dashboard.clock.now).allowed


def test_current_policy_rechecked_for_saved_content_and_cache_identity(dashboard):
    grant(dashboard)
    first=policy(dashboard).authorize(lineage().sources,'display_derived',dashboard.clock.now)
    assert first.allowed
    grant(dashboard,policy_version='v2')
    second=policy(dashboard).authorize(lineage().sources,'display_derived',dashboard.clock.now)
    assert not second.allowed and first.cache_key != second.cache_key
    dashboard.clock.advance(200)
    assert not policy(dashboard).authorize(lineage(version='v2').sources,'retain',dashboard.clock.now).allowed


def test_backup_and_restore_authority_default_closed(dashboard):
    from member_dashboard.source_policy import SourcePolicy
    grant(dashboard)
    assert not SourcePolicy(dashboard.store).authorize(lineage().sources,'display_raw',dashboard.clock.now).allowed
    assert not SourcePolicy(dashboard.store,authority_current=lambda:True).authorize(
        lineage().sources,'display_raw',dashboard.clock.now).allowed


def test_delay_and_earliest_retention_are_enforced(dashboard):
    grant(dashboard,delay_seconds=60)
    result=policy(dashboard).authorize_lineage(lineage(),'display_raw',dashboard.clock.now,
                                            observed_at=dashboard.clock.now-10)
    assert result.status=='denied'
    assert policy(dashboard).authorize_lineage(lineage(),'display_raw',dashboard.clock.now,
        observed_at=dashboard.clock.now-70).retention_deadline==dashboard.clock.now+100


def test_expiry_purges_web_copies_and_keeps_noncontent_tombstone(dashboard):
    from member_dashboard.publication import Publisher
    grant(dashboard)
    content_lineage=lineage()
    card_id=str(uuid4())
    payload='{"ticker":"TEST","direction":"bullish","excerpt":"fixture licensed content"}'
    with dashboard.store.transaction() as conn:
        conn.execute('INSERT INTO publications(id,source_post_key,ticker,content_version,feature,content_json,'
            'source_lineage_json,required_features_json,observed_at,published_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
            (card_id,'fixture-post','TEST','content-v1','feed',payload,
             json.dumps([s.model_dump() for s in content_lineage.sources]), '["feed"]',1.0,1.0))
    assert Publisher(dashboard.store,policy(dashboard)).load(card_id,dashboard.clock.now) is not None
    dashboard.clock.advance(200)
    assert Publisher(dashboard.store,policy(dashboard)).load(card_id,dashboard.clock.now) is None
    outcome=policy(dashboard).purge(dashboard.clock.now)
    assert outcome.deleted==1
    with dashboard.store.transaction() as conn:
        assert conn.execute('SELECT count(*) FROM publications').fetchone()[0]==0
        tomb=conn.execute('SELECT reason FROM content_tombstones WHERE object_id=?',(card_id,)).fetchone()
        assert tomb==('source_permission_unavailable',)
        assert conn.execute('SELECT operation,content_json FROM publication_changes').fetchone()==('delete',None)


def test_purge_does_not_preserve_unlicensed_tombstone(dashboard):
    grant(dashboard,tombstone_allowed=False)
    with dashboard.store.transaction() as conn:
        conn.execute('INSERT INTO publications(id,source_post_key,ticker,content_version,feature,content_json,'
            'source_lineage_json,published_at) VALUES (?,?,?,?,?,?,?,?)',
            (str(uuid4()),'fixture','TEST','v1','feed','{}',
             json.dumps([s.model_dump() for s in lineage().sources]),1.0))
    dashboard.clock.advance(200)
    policy(dashboard).purge(dashboard.clock.now)
    with dashboard.store.transaction() as conn:
        assert conn.execute('SELECT count(*) FROM content_tombstones').fetchone()[0]==0


def test_publication_save_rechecks_permissions_and_removal_is_explicit(dashboard,tmp_path):
    from member_dashboard.market_reader import SourceRecord,SourceName,MarketPayload
    from member_dashboard.publication import Publisher,publishable
    grant(dashboard)
    record=SourceRecord(SourceName.ANALYST,'fixture-post','TEST','source-v1',dashboard.clock.now-10,
        dashboard.clock.now-5,'https://x.com/fixture/status/123','bullish','A safe excerpt',
        MarketPayload(ticker='TEST',direction='bullish',excerpt='A safe excerpt'),lineage=lineage())
    publication=publishable(record)
    publisher=Publisher(dashboard.store,policy(dashboard))
    assert publication.published_at is None and publication.research_only
    assert publisher.save(publication,dashboard.clock.now)
    assert publisher.save(publication,dashboard.clock.now)
    with dashboard.store.transaction() as conn:
        id=conn.execute('SELECT id FROM publications').fetchone()[0]
        assert conn.execute('SELECT count(*) FROM publication_changes').fetchone()[0]==1
    assert publisher.load(id,dashboard.clock.now).excerpt=='A safe excerpt'
    assert publisher.load(id,dashboard.clock.now).attributions==['Synthetic public attribution']
    publisher.retract('fixture-post','TEST',dashboard.clock.now)
    assert publisher.load(id,dashboard.clock.now) is None
    grant(dashboard,policy_version='v2',display_raw=False)
    assert not publisher.save(publication,dashboard.clock.now)


def test_source_permission_summary_does_not_leak_private_references(dashboard):
    grant(dashboard)
    decision=policy(dashboard).authorize(lineage().sources,'display_raw',dashboard.clock.now)
    assert decision.allowed
    assert 'private-fixture' not in repr(decision)


def test_policy_version_cannot_mutate_under_existing_cache_fingerprint(dashboard):
    import sqlite3
    grant(dashboard)
    with dashboard.store.transaction() as conn:
        with pytest.raises(sqlite3.IntegrityError,match='immutable policy'):
            conn.execute("UPDATE source_permissions SET model_input=1 WHERE source_id='permitted'")


def test_logical_purge_covers_result_snapshot_chart_and_derived_message(dashboard):
    grant(dashboard)
    contribution=json.dumps([s.model_dump() for s in lineage().sources])
    result_id,report_id,version_id,asset_id,member_id,conversation_id,message_id=[str(uuid4()) for _ in range(7)]
    with dashboard.store.transaction() as conn:
        conn.execute('INSERT INTO market_results(id,fingerprint,ticker,section,content_json,source_lineage_json,'
            'required_features_json,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (result_id,'fixture-fingerprint','TEST','analysis','{}',contribution,'["feed"]',1.0))
        conn.execute('INSERT INTO report_versions(id,report_id,version,content_json,source_lineage_json,'
            'required_features_json,created_at) VALUES (?,?,?,?,?,?,?)',
            (version_id,report_id,1,'{}',contribution,'["feed"]',1.0))
        conn.execute('INSERT INTO assets(id,result_id,content_type,content,source_lineage_json,'
            'required_features_json,created_at) VALUES (?,?,?,?,?,?,?)',
            (asset_id,result_id,'image/png',b'fixture-bytes',contribution,'["feed"]',1.0))
        conn.execute('INSERT INTO members(id,username,password_hash,role,created_at) VALUES (?,?,?,?,?)',
            (member_id,'synthetic_purge','unused','member',1.0))
        conn.execute('INSERT INTO conversations(id,member_id,created_at) VALUES (?,?,?)',
            (conversation_id,member_id,1.0))
        conn.execute('INSERT INTO messages(id,conversation_id,member_id,role,content_json,source_lineage_json,'
            'required_features_json,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (message_id,conversation_id,member_id,'assistant','{}',contribution,'["feed"]',1.0))
    dashboard.clock.advance(200)
    assert policy(dashboard).purge(dashboard.clock.now).deleted==4
    with dashboard.store.transaction() as conn:
        for table in ['market_results','report_versions','assets','messages']:
            assert conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0]==0


def test_retention_sweep_revisits_rows_beyond_first_page(dashboard):
    grant(dashboard)
    contribution=json.dumps([s.model_dump() for s in lineage().sources])
    with dashboard.store.transaction() as conn:
        for i in range(3):
            conn.execute('INSERT INTO publications(id,source_post_key,ticker,content_version,feature,content_json,'
                'source_lineage_json,required_features_json,published_at) VALUES (?,?,?,?,?,?,?,?,?)',
                (str(uuid4()),str(i),'TEST','v1','feed','{}',contribution,'["feed"]',1.0))
    first=policy(dashboard).purge(dashboard.clock.now,limit=1)
    assert first.deleted==0 and first.more
    dashboard.clock.advance(200)
    second=policy(dashboard).purge(dashboard.clock.now,limit=1,cursors=first.cursors)
    assert second.deleted==1 # Permitted older row did not starve later expired rows.
