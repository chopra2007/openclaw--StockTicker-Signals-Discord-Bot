"""Synthetic stored records, real read-only/WAL connections and safe projections."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import pytest

NOW=1_791_225_000.0


@pytest.fixture
def market(tmp_path):
    path=tmp_path/'market.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('CREATE TABLE analyst_post_views(id INTEGER PRIMARY KEY,source_post_key TEXT,source_url TEXT,'
            'analyst TEXT,ticker TEXT,detected_at REAL,raw_text TEXT,raw_text_sha256 TEXT,parsed_summary TEXT,'
            'display_direction TEXT,reason_text TEXT,reason_start INTEGER,reason_end INTEGER,reason_kind TEXT,'
            'decision_code TEXT,parser_version TEXT,image_evidence_json TEXT,created_at REAL,private_extra TEXT)')
    return path


def insert(path,id=1,**changes):
    text='TEST has a bullish breakout'
    values=dict(id=id,source_post_key='fixture-post',source_url='https://x.com/fixture/status/123',
        analyst='PRIVATE_ANALYST',ticker='TEST',detected_at=NOW-10,raw_text=text,
        raw_text_sha256=hashlib.sha256(text.encode()).hexdigest(),parsed_summary='PRIVATE_SUMMARY',
        display_direction='long',reason_text='bullish breakout',reason_start=11,reason_end=27,
        reason_kind='setup',decision_code='explicit_clause',parser_version='fixture-v1',
        image_evidence_json=None,created_at=NOW-5,private_extra='SECRET')
    values.update(changes)
    if 'raw_text' in changes and 'raw_text_sha256' not in changes:
        values['raw_text_sha256']=hashlib.sha256(values['raw_text'].encode()).hexdigest()
    with sqlite3.connect(path) as conn:
        cols=','.join(values)
        conn.execute(f'INSERT INTO analyst_post_views({cols}) VALUES ({",".join("?" for _ in values)})',tuple(values.values()))


def read(path,checkpoint=None,limit=100):
    from member_dashboard.market_reader import MarketReader,SourceName,SourceCheckpoint
    return MarketReader(path,clock=lambda:NOW).read_batch(SourceName.ANALYST,checkpoint or SourceCheckpoint(),limit)


def test_market_connection_never_writes_or_imports_bot(market):
    from member_dashboard.market_reader import MarketReader
    before=set(sys.modules)
    with MarketReader(market).connection() as conn:
        with pytest.raises(sqlite3.OperationalError,match='readonly'):
            conn.execute('DELETE FROM analyst_post_views')
    assert not any(x.startswith('consensus_engine') for x in set(sys.modules)-before)


def test_strict_projection_excludes_private_fields_and_suppresses_html(market):
    insert(market,raw_text='<img src=x onerror=alert(1)> TEST bullish',reason_text='TEST bullish',
           reason_start=29,reason_end=41)
    batch=read(market)
    assert batch.available
    rendered=repr(batch.records)
    assert 'SECRET' not in rendered and 'PRIVATE_ANALYST' not in rendered and 'PRIVATE_SUMMARY' not in rendered
    assert '<img' not in rendered
    assert batch.records[0].research_only and not batch.records[0].lineage
    from member_dashboard.publication import publishable
    assert publishable(batch.records[0]) is None


@pytest.mark.parametrize('changes',[{'image_evidence_json':'{'},{'detected_at':-1},
    {'detected_at':float('inf')},{'reason_start':-1},{'reason_end':9999},{'ticker':'../../private'},
    {'image_evidence_json':'{"secret":"leak"}'}])
def test_invalid_record_is_blocked_without_source_content(market,changes):
    insert(market,**changes)
    batch=read(market)
    assert not batch.records and batch.blocked_keys==(('fixture-post','' if 'ticker' in changes else 'TEST'),)


def test_missing_schema_is_unavailable_without_initialization(tmp_path):
    missing=tmp_path/'never-created.sqlite3'
    assert not read(missing).available and not missing.exists()
    with sqlite3.connect(missing) as conn:
        conn.execute('CREATE TABLE analyst_post_views(id INTEGER)')
    assert not read(missing).available


def test_authority_selected_before_safety_filter_and_versions_not_lexicographic(market):
    insert(market,parser_version='z-old')
    insert(market,id=2,parser_version='a-new',created_at=NOW-1,display_direction='short')
    batch=read(market)
    assert len(batch.records)==1 and batch.records[0].direction=='bearish'
    with sqlite3.connect(market) as conn:
        conn.execute('UPDATE analyst_post_views SET detected_at=-1 WHERE id=2')
    assert not read(market).records


def test_old_mutation_reconciles_and_changes_content_version(market):
    insert(market,created_at=NOW-1000)
    first=read(market)
    with sqlite3.connect(market) as conn:
        conn.execute("UPDATE analyst_post_views SET display_direction='short' WHERE id=1")
    second=read(market,first.checkpoint)
    assert second.records[0].version!=first.records[0].version
    assert second.records[0].direction=='bearish'


def test_limit_is_bounded_and_source_is_fixed(market):
    from member_dashboard.market_reader import MarketReader,SourceCheckpoint
    for id in range(1,131): insert(market,id=id,source_post_key=f'fixture-{id}')
    assert len(read(market,limit=100).records)<=100
    with pytest.raises(ValueError): read(market,limit=101)
    with pytest.raises(ValueError): MarketReader(market).read_batch('analyst_post_views; DROP TABLE x',SourceCheckpoint())


def test_reads_committed_wal_during_writer_contention(market):
    insert(market)
    writer=sqlite3.connect(market)
    try:
        writer.execute('BEGIN IMMEDIATE')
        writer.execute("UPDATE analyst_post_views SET display_direction='short' WHERE id=1")
        assert read(market).records[0].direction=='bullish'
    finally:
        writer.rollback(); writer.close()


@pytest.mark.parametrize('url',[ 'javascript:alert(1)','file:///secret','data:text/html,x',
    'https://user:secret@x.com/a','https://127.0.0.1/a','https://x.com.evil.test/a',
    'https://x.com/redirect?url=https://127.0.0.1','https://x.com:8443/a','https://x.com/\\evil'])
def test_unsafe_source_links_are_unavailable(url):
    from member_dashboard.market_reader import safe_url
    assert safe_url(url) is None


def test_public_link_normalized_without_fetch():
    from member_dashboard.market_reader import safe_url
    assert safe_url('HTTPS://X.COM/fixture/status/123#tracking')=='https://x.com/fixture/status/123'


def test_query_deadline_interrupts_real_sqlite_work(market):
    from member_dashboard.market_reader import MarketReader
    with MarketReader(market,query_seconds=.001).connection() as conn:
        with pytest.raises(sqlite3.OperationalError,match='interrupted'):
            conn.execute('WITH RECURSIVE counts(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM counts WHERE n<10000000) '
                         'SELECT sum(n) FROM counts').fetchone()


@pytest.fixture
def delivery_market(market):
    with sqlite3.connect(market) as conn:
        conn.executescript('''
        CREATE TABLE measurement_alert_events_v1(event_id TEXT,alert_id TEXT,decision_id TEXT,legacy_alert_id INTEGER,created_at REAL);
        CREATE TABLE measurement_decision_events_v1(event_id TEXT,decision_id TEXT,candidate_id TEXT,created_at REAL);
        CREATE TABLE measurement_candidates_v1(candidate_id TEXT,ticker TEXT);
        CREATE TABLE measurement_delivery_events_v1(event_id TEXT,delivery_id TEXT,decision_id TEXT,attempt_id TEXT,
            status TEXT,external_message_id TEXT,confirmed_at REAL,created_at REAL);
        CREATE TABLE measurement_corrections_v1(correction_id TEXT,entity_id TEXT,prior_event_id TEXT);
        ''')
        conn.execute('INSERT INTO measurement_alert_events_v1 VALUES (?,?,?,?,?)',('a1','a','d',7,NOW-5))
        conn.execute('INSERT INTO measurement_decision_events_v1 VALUES (?,?,?,?)',('d1','d','c',NOW-6))
        conn.execute('INSERT INTO measurement_candidates_v1 VALUES (?,?)',('c','TEST'))
        conn.execute('INSERT INTO measurement_delivery_events_v1 VALUES (?,?,?,?,?,?,?,?)',
                     ('e1','delivery','d','attempt','confirmed_delivered','123456789',NOW-4,NOW-4))
    return market


def test_delivery_confirmation_requires_exact_linkage_and_is_not_rendered_setup(delivery_market):
    from member_dashboard.market_reader import MarketReader
    proof=MarketReader(delivery_market,clock=lambda:NOW).delivery_evidence(7,'TEST')
    assert proof.confirmed_at==NOW-4 and proof.rendered_content_verified is False
    assert MarketReader(delivery_market).delivery_evidence(8,'TEST') is None
    assert MarketReader(delivery_market).delivery_evidence(7,'OTHER') is None
    assert '123456789' not in repr(proof) # external delivery identifiers stay private


@pytest.mark.parametrize('message_id',['dry_run_msg_id','dry_run_merged_id','dry_run_followup_id','','0','abc'])
def test_dry_run_or_invalid_message_never_proves_publication(delivery_market,message_id):
    from member_dashboard.market_reader import MarketReader
    with sqlite3.connect(delivery_market) as conn:
        conn.execute('UPDATE measurement_delivery_events_v1 SET external_message_id=?',(message_id,))
    assert MarketReader(delivery_market,clock=lambda:NOW).delivery_evidence(7,'TEST') is None


def test_later_failed_attempt_does_not_erase_different_confirmed_attempt(delivery_market):
    from member_dashboard.market_reader import MarketReader
    with sqlite3.connect(delivery_market) as conn:
        conn.execute('INSERT INTO measurement_delivery_events_v1 VALUES (?,?,?,?,?,?,?,?)',
            ('e2','followup','d','second-attempt','failed',None,None,NOW-2))
    assert MarketReader(delivery_market,clock=lambda:NOW).delivery_evidence(7,'TEST').confirmed_at==NOW-4


def test_linked_unknown_correction_blocks_confirmation(delivery_market):
    from member_dashboard.market_reader import MarketReader
    with sqlite3.connect(delivery_market) as conn:
        conn.execute('INSERT INTO measurement_corrections_v1 VALUES (?,?,?)',('correction','delivery','e1'))
    assert MarketReader(delivery_market,clock=lambda:NOW).delivery_evidence(7,'TEST') is None


def test_authoritative_image_evidence_never_fabricates_text_quote(market):
    insert(market,reason_kind='image',decision_code='image_evidence',reason_text=None,reason_start=None,reason_end=None,
        image_evidence_json=json.dumps(dict(ticker='TEST',sentiment='bullish',setup_direction='long',
            overall_sentiment='bullish',confidence=.8,direction_basis='annotated_setup',
            direction_evidence='Annotated chart direction',image_url='https://x.com/fixture/status/123/photo/1')))
    record=read(market).records[0]
    assert record.excerpt=='' and record.direction=='bullish'


def test_existing_alert_is_research_only_and_json_mutation_versions_it(tmp_path):
    from member_dashboard.market_reader import MarketReader,SourceName,SourceCheckpoint
    path=tmp_path/'market.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE alert_history(id INTEGER,ticker TEXT,confidence_score REAL,catalyst_type TEXT,'
            'consensus_breakdown TEXT,technical_data TEXT,alerted_at REAL,price_at_alert REAL)')
        conn.execute('INSERT INTO alert_history VALUES (?,?,?,?,?,?,?,?)',
            (1,'TEST',75.0,'news','{"news_catalyst":5}','{"price":0}',NOW-1000,0))
    reader=MarketReader(path,clock=lambda:NOW)
    first=reader.read_batch(SourceName.ALERT,SourceCheckpoint())
    assert first.records[0].research_only and first.records[0].delivery_confirmed_at is None
    assert first.records[0].payload.price is None
    with sqlite3.connect(path) as conn:
        conn.execute('UPDATE alert_history SET consensus_breakdown=?',('{"news_catalyst":6}',))
    second=reader.read_batch(SourceName.ALERT,first.checkpoint)
    assert first.records[0].version!=second.records[0].version


def test_composite_research_reconciles_without_leaking_unproven_prose(tmp_path):
    from member_dashboard.market_reader import MarketReader,SourceName,SourceCheckpoint
    path=tmp_path/'market.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE research_sections(ticker TEXT,source TEXT,content TEXT,last_good_content TEXT,'
            'fetched_at REAL,last_good_at REAL,status TEXT)')
        conn.executemany('INSERT INTO research_sections VALUES (?,?,?,?,?,?,?)',[
            ('TEST','sec','PRIVATE_NEW','PRIVATE_OLD',NOW-5,NOW-100,'failed'),
            ('ZZZ','news','PRIVATE_NEWS',None,NOW-5,None,'ok')])
    reader=MarketReader(path,clock=lambda:NOW)
    first=reader.read_batch(SourceName.RESEARCH,SourceCheckpoint(),1)
    record=first.records[0]
    assert record.stale and record.observed_at is None and record.computed_at==NOW-100
    assert not record.excerpt and 'PRIVATE_' not in repr(record)
    second=reader.read_batch(SourceName.RESEARCH,first.checkpoint,1)
    assert second.records[0].ticker=='ZZZ'


def test_options_alerted_flag_and_unknown_fallback_do_not_make_live_setup(tmp_path):
    from member_dashboard.market_reader import MarketReader,SourceName,SourceCheckpoint
    from member_dashboard.publication import publishable
    path=tmp_path/'market.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE options_flow(id INTEGER,ticker TEXT,side TEXT,strike REAL,expiry TEXT,volume INTEGER,'
            'open_interest INTEGER,vol_oi_ratio REAL,premium_usd REAL,last_trade_ts REAL,spot REAL,contract_symbol TEXT,'
            'alerted INTEGER,detected_at REAL,flow_side TEXT,bid REAL,ask REAL)')
        conn.execute('INSERT INTO options_flow VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (1,'TEST','call',50.,'2026-10-09',100,10,10.,5000.,0.,0.,'TEST-fixture',1,NOW-5,'unknown',0.,0.))
    record=MarketReader(path,clock=lambda:NOW).read_batch(SourceName.OPTIONS,SourceCheckpoint()).records[0]
    assert record.observed_at is None and record.payload.price is None and record.lineage is None
    assert publishable(record) is None


@pytest.mark.parametrize('value',['{"news_catalyst":NaN}','{"news_catalyst":1,"news_catalyst":2}',
    '{"secret": {"nested":"payload"}}'])
def test_json_numeric_projection_rejects_nonfinite_duplicate_and_unexpected_keys(tmp_path,value):
    from member_dashboard.market_reader import MarketReader,SourceName,SourceCheckpoint
    path=tmp_path/'market.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE alert_history(id INTEGER,ticker TEXT,confidence_score REAL,catalyst_type TEXT,'
            'consensus_breakdown TEXT,technical_data TEXT,alerted_at REAL,price_at_alert REAL)')
        conn.execute('INSERT INTO alert_history VALUES (?,?,?,?,?,?,?,?)',
            (1,'TEST',75.,'news',value,'{}',NOW-10,None))
    batch=MarketReader(path,clock=lambda:NOW).read_batch(SourceName.ALERT,SourceCheckpoint())
    assert not batch.records and batch.blocked_keys
