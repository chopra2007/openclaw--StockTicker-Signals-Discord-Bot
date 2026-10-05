"""Durable research behavior on separate real SQLite connections."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import threading
from uuid import uuid4

import pytest


def test_jobs_contract_is_available():
    assert importlib.util.find_spec('member_dashboard.jobs') is not None


@pytest.mark.parametrize('age',[0,1200])
def test_review_quote_delay_survives_completion_and_delivery(research,dashboard,age):
    from dataclasses import replace
    from datetime import datetime,timedelta,timezone
    from types import SimpleNamespace
    from test_sec_outcomes import synthetic_chain
    from consensus_engine.scanners.expected_move import ExpectedMoveSettings
    from member_dashboard.providers import ProviderContext
    from member_dashboard.research import MemberResearchProvider
    from member_dashboard.source_policy import SourcePermission
    service,users,registry,policy=research
    now=dashboard.clock()
    instant=datetime.fromtimestamp(now,timezone.utc)
    chain=synthetic_chain()
    expiry=(instant+timedelta(days=1)).date().isoformat()
    chain.calls=chain.calls[chain.calls.expiry==chain.expirations[0]].copy()
    chain.puts=chain.puts[chain.puts.expiry==chain.expirations[0]].copy()
    for frame in (chain.calls,chain.puts):
        frame['expiry']=expiry
        frame['providerQuoteTime']=(now-age)*1000
        frame['lastTradeDate']=instant-timedelta(days=1)
    chain.expirations=[expiry]
    chain.underlying_quote_time=now-age
    policy.record(SourcePermission(source_id='synthetic',product_id='fixture',provider='fixture',policy_version='p2',
        audience='invited_members',status='allowed',display_raw=True,display_derived=True,retain=True,
        private_grant_ref='fixture',evidence_ref='fixture',terms_url='https://www.sec.gov/fixture',effective_at=0.0,
        delay_seconds=900))
    spec=registry.providers['em_daily']
    lineage=spec.lineage.model_copy(update={'sources':[s.model_copy(update={'policy_version':'p2'}) for s in spec.lineage.sources]})
    client=SimpleNamespace(get_option_chain=lambda *a,**k:chain,get_price_history=lambda *a,**k:None)
    provider=MemberResearchProvider(ProviderContext(policy,{'em_daily':lineage},{'synthetic':client},ExpectedMoveSettings(),
        lambda:instant,object(),object(),object(),lambda event:None,'synthetic'))
    provider.register(registry)
    request=service.request_research(users[0],'SPY',False,now)
    while job:=service.claim_job('fixture-worker',now):
        if job.kind=='em_daily': break
        service.complete_job(job.id,job.lease_token,fixture_result(job.kind,now),now)
    completion=provider.compute_blocking('SPY','em_daily',{})
    result=getattr(completion,'result',completion)
    service.complete_job(job.id,job.lease_token,result,now)
    public=service.get_request(users[0],request.id,now).sections['em_daily']
    with service.store.transaction() as con:
        count=con.execute("SELECT count(*) FROM market_results WHERE section='em_daily'").fetchone()[0]
    if age==0:
        assert public.status=='unavailable' and count==0
    else:
        assert public.status=='completed' and count==1
        assert public.observed_at==now-age and public.delay_seconds==900
        assert {row.input_kind:row.observed_at for row in public.payload.quote_times}==dict.fromkeys(
            ('call','put','underlying','selection'),now-age)


def test_chart_completion_is_atomic_owned_and_current(research,dashboard):
    from io import BytesIO
    from PIL import Image
    service,users,_,policy=research
    request=service.request_research(users[0],'SPY',False,dashboard.clock())
    png=BytesIO(); Image.new('RGB',(8,8),'navy').save(png,format='PNG')
    while job:=service.claim_job('fixture-worker',dashboard.clock()):
        if job.kind=='em_daily': break
        service.complete_job(job.id,job.lease_token,fixture_result(job.kind,dashboard.clock()),dashboard.clock())
    service.complete_job(job.id,job.lease_token,fixture_result(job.kind,dashboard.clock()),dashboard.clock(),png=png.getvalue())
    result=service.get_request(users[0],request.id,dashboard.clock()).sections['em_daily']
    assert result.payload.chart_asset_id
    from member_dashboard.assets import AssetService
    assets=AssetService(service)
    assert assets.read(users[0],result.payload.chart_asset_id,dashboard.clock()) == png.getvalue()
    assert assets.read(users[1],result.payload.chart_asset_id,dashboard.clock()) is None
    with service.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM assets WHERE result_id=?',(result.result_id,)).fetchone()[0]==1
        content=con.execute('SELECT content_json FROM report_versions ORDER BY rowid DESC LIMIT 1').fetchone()[0]
        assert result.payload.chart_asset_id in content
        # Valid JSON with unrelated malformed section shape cannot break ownership.
        con.execute('INSERT INTO report_versions(id,report_id,version,content_json,created_at) VALUES (?,?,?,?,?)',
                    (str(uuid4()),request.report_id,999,'{"unrelated":"not an object"}',dashboard.clock()))
        # Password reset fences pending work, but retained owned history remains
        # readable from a newly authenticated session after the version changes.
        con.execute('UPDATE members SET authorization_version=2 WHERE id=?',(users[0].member_id,))
        con.execute('UPDATE sessions SET authorization_version=2 WHERE id=?',(users[0].session_id,))
    from dataclasses import replace
    new_principal=replace(users[0],authorization_version=2)
    assert assets.read(new_principal,result.payload.chart_asset_id,dashboard.clock())==png.getvalue()
    with service.store.transaction() as con:
        con.execute('UPDATE research_requests SET deleted_at=? WHERE id=?',(dashboard.clock(),request.id))
    assert assets.read(new_principal,result.payload.chart_asset_id,dashboard.clock())==png.getvalue()
    with service.store.transaction() as con:
        con.execute("UPDATE features SET enabled=0 WHERE name='em_daily'")
    from member_dashboard.assets import AssetDenial
    assert assets.read(new_principal,result.payload.chart_asset_id,dashboard.clock()) is AssetDenial.FEATURE_DISABLED


@pytest.mark.parametrize('withdraw',['source','retention','session','owner'])
def test_chart_reads_recheck_every_permission(research,dashboard,withdraw):
    from io import BytesIO
    from PIL import Image
    from dataclasses import replace
    from member_dashboard.assets import AssetService
    from member_dashboard.source_policy import SourcePermission
    service,users,registry,policy=research
    if withdraw=='retention':
        spec=registry.providers['em_daily']
        registry.providers['em_daily']=replace(spec,lineage=spec.lineage.model_copy(update={'retention_deadline':dashboard.clock()+5}))
    service.request_research(users[0],'SPY',False,dashboard.clock())
    while job:=service.claim_job('fixture-worker',dashboard.clock()):
        if job.kind=='em_daily': break
        service.complete_job(job.id,job.lease_token,fixture_result(job.kind,dashboard.clock()),dashboard.clock())
    png=BytesIO(); Image.new('RGB',(8,8)).save(png,format='PNG')
    service.complete_job(job.id,job.lease_token,fixture_result(job.kind,dashboard.clock()),dashboard.clock(),png=png.getvalue())
    with service.store.transaction() as con:
        asset_id=con.execute('SELECT id FROM assets').fetchone()[0]
    assert AssetService(service).read(users[0],asset_id,dashboard.clock())==png.getvalue()
    if withdraw=='source':
        policy.record(SourcePermission(source_id='synthetic',product_id='fixture',provider='fixture',policy_version='p2',audience='invited_members',status='denied'))
    elif withdraw=='retention': dashboard.clock.advance(6)
    else:
        with service.store.transaction() as con:
            if withdraw=='session': con.execute('UPDATE sessions SET revoked_at=? WHERE id=?',(dashboard.clock(),users[0].session_id))
            else: con.execute('UPDATE report_owners SET deleted_at=? WHERE member_id=?',(dashboard.clock(),users[0].member_id))
    if withdraw=='session':
        from member_dashboard.auth import AuthError
        with pytest.raises(AuthError): AssetService(service).read(users[0],asset_id,dashboard.clock())
    else: assert AssetService(service).read(users[0],asset_id,dashboard.clock()) is None


def test_late_chart_with_deleted_owner_persists_nothing(research,dashboard):
    from io import BytesIO
    from PIL import Image
    service,users,_,_=research
    request=service.request_research(users[0],'SPY',False,dashboard.clock())
    while job:=service.claim_job('fixture-worker',dashboard.clock()):
        if job.kind=='em_daily': break
        service.complete_job(job.id,job.lease_token,fixture_result(job.kind,dashboard.clock()),dashboard.clock())
    with service.store.transaction() as con:
        con.execute('UPDATE report_owners SET deleted_at=? WHERE member_id=?',(dashboard.clock(),users[0].member_id))
    png=BytesIO(); Image.new('RGB',(8,8)).save(png,format='PNG')
    service.complete_job(job.id,job.lease_token,fixture_result(job.kind,dashboard.clock()),dashboard.clock(),png=png.getvalue())
    with service.store.transaction() as con:
        assert con.execute("SELECT count(*) FROM market_results WHERE section='em_daily'").fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM assets').fetchone()[0]==0


def test_disclosures_rechecked_from_current_policy_on_cache_read(research,dashboard):
    from member_dashboard.source_policy import SourcePermission
    service,users,registry,policy=research
    def grant(version,attribution,delay,allowed=True):
        policy.record(SourcePermission(source_id='synthetic',product_id='fixture',provider='fixture',policy_version=version,
            audience='invited_members',status='allowed',display_raw=True,display_derived=allowed,retain=True,
            private_grant_ref='fixture',evidence_ref='fixture',terms_url='https://www.sec.gov/fixture-terms',effective_at=0.0,
            attribution=attribution,delay_seconds=float(delay)))
    grant('p2','Synthetic provider attribution',20)
    from dataclasses import replace
    for section,spec in list(registry.providers.items()):
        sources=[source.model_copy(update={'policy_version':'p2'}) for source in spec.lineage.sources]
        registry.providers[section]=replace(spec,lineage=spec.lineage.model_copy(update={'sources':sources}))
    request=service.request_research(users[0],'SPY',False,dashboard.clock())
    finish_all(service,dashboard.clock())
    result=service.get_request(users[0],request.id,dashboard.clock()).sections['options']
    assert result.attributions==['Synthetic provider attribution'] and result.delay_seconds==20
    cached=service.get_request(users[0],request.id,dashboard.clock()+1).sections['options']
    assert cached.attributions==result.attributions and cached.delay_seconds==20
    grant('p3','Revised attribution',30,False)
    assert service.get_request(users[0],request.id,dashboard.clock()).sections['options'].status=='unavailable'


@pytest.mark.asyncio
async def test_chart_handoff_keeps_same_actual_work_until_render_finishes(research,dashboard):
    import asyncio
    from dataclasses import replace
    from io import BytesIO
    from PIL import Image
    from member_dashboard.providers import ResearchCompletion
    from member_dashboard.provider_runtime import ProviderRuntime
    from member_dashboard.worker import ComputeWorker
    service,users,registry,_=research
    with service.store.transaction() as con:
        con.execute("UPDATE features SET enabled=0 WHERE name IN ('analysis','sec','options','em_weekly')")
    entered,release=threading.Event(),threading.Event()
    png=BytesIO(); Image.new('RGB',(8,8)).save(png,format='PNG')
    def compute(*args):
        entered.set()
        release.wait(5)
        return ResearchCompletion(fixture_result('em_daily',dashboard.clock()),png.getvalue())
    registry.providers['em_daily']=replace(registry.providers['em_daily'],operation=compute)
    request=service.request_research(users[0],'SPY',False,dashboard.clock())
    runtime=ProviderRuntime(dashboard.store,'chart-worker',clock=dashboard.clock)
    worker=ComputeWorker(service,registry,runtime,clock=dashboard.clock,deadlines={'em_daily':.01})
    try:
        await worker.run_once()
        assert entered.is_set() and runtime.running_count==1
        with service.store.transaction() as con:
            assert con.execute('SELECT count(*) FROM assets').fetchone()[0]==0
            assert con.execute('SELECT count(*) FROM provider_calls').fetchone()[0]==1
        release.set()
        for _ in range(100):
            if runtime.running_count==0: break
            await asyncio.sleep(.01)
        await worker.run_once()
        result=service.get_request(users[0],request.id,dashboard.clock()).sections['em_daily']
        assert result.status=='completed' and result.payload.chart_asset_id
    finally:
        release.set()
        runtime.shutdown()


def test_chart_insert_failure_rolls_back_parent(research,dashboard):
    import sqlite3
    from io import BytesIO
    from PIL import Image
    service,users,_,_=research
    service.request_research(users[0],'SPY',False,dashboard.clock())
    while job:=service.claim_job('fixture-worker',dashboard.clock()):
        if job.kind=='em_daily': break
        service.complete_job(job.id,job.lease_token,fixture_result(job.kind,dashboard.clock()),dashboard.clock())
    png=BytesIO(); Image.new('RGB',(8,8)).save(png,format='PNG')
    with service.store.transaction() as con:
        con.execute("CREATE TRIGGER reject_chart BEFORE INSERT ON assets BEGIN SELECT RAISE(ABORT,'synthetic chart failure'); END")
    with pytest.raises(sqlite3.IntegrityError,match='synthetic chart failure'):
        service.complete_job(job.id,job.lease_token,fixture_result(job.kind,dashboard.clock()),dashboard.clock(),png=png.getvalue())
    with service.store.transaction() as con:
        assert con.execute("SELECT count(*) FROM market_results WHERE section='em_daily'").fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM assets').fetchone()[0]==0
        assert con.execute('SELECT status FROM web_jobs WHERE id=?',(job.id,)).fetchone()[0]=='running'


@pytest.fixture
def research(dashboard):
    from member_dashboard.auth import Principal
    from member_dashboard.contracts import ContentLineage, SourceContribution
    from member_dashboard.jobs import JobService
    from member_dashboard.providers import ProviderRegistry, ProviderSpec, SymbolCatalog
    from member_dashboard.source_policy import SourcePermission, SourcePolicy
    policy = SourcePolicy(dashboard.store, authority_current=lambda: True,
                          backup_compliant=lambda *_: True)
    policy.record(SourcePermission(source_id='synthetic', product_id='fixture', provider='fixture',
        policy_version='p1', audience='invited_members', status='allowed', display_raw=True,
        display_derived=True, retain=True, private_grant_ref='fixture', evidence_ref='fixture',
        terms_url='https://www.sec.gov/fixture-terms', effective_at=0.0))
    sources = [SourceContribution(source_id='synthetic', product_id='fixture',
                                 source_version='s1', policy_version='p1')]
    registry = ProviderRegistry(SymbolCatalog({'SPY': 'ETF', 'QQQ': 'ETF', 'AAPL': 'equity', 'BRK.B': 'equity'}))
    for section in ['analysis', 'sec', 'options', 'em_daily', 'em_weekly']:
        registry.register(section, ProviderSpec(ContentLineage(sources=sources, required_features=[section],
                                  field_dependencies=[], retention_deadline=None),
                                  lambda ticker, section, inputs: fixture_result(section, dashboard.clock()), 'fixture'))
    service = JobService(dashboard.store, dashboard.app.state.auth, policy, registry)
    principals = []
    for index in range(3):
        member, session = str(uuid4()), str(uuid4())
        with dashboard.store.transaction() as con:
            con.execute('INSERT INTO members(id,username,password_hash,created_at) VALUES (?,?,?,?)',
                        (member, f'research_{index}', 'unused-fixture', dashboard.clock()))
            con.execute('INSERT INTO sessions(id,member_id,token_digest,csrf_digest,created_at,last_seen_at,absolute_expires_at,idle_expires_at) VALUES (?,?,?,?,?,?,?,?)',
                        (session, member, bytes([index])*32, bytes([index+3])*32,
                         dashboard.clock(), dashboard.clock(), dashboard.clock()+43200, dashboard.clock()+7200))
        principals.append(Principal(member, 'member', session, 1))
    dashboard.app.state.research = service
    return service, principals, registry, policy


def finish_all(service, now):
    while job := service.claim_job('fixture-worker', now):
        service.complete_job(job.id, job.lease_token, fixture_result(job.kind, now), now)


def fixture_result(section, now):
    from member_dashboard.contracts import SectionResult
    payloads = {
        'analysis': dict(kind='analysis', summary='Synthetic research only', direction='neutral', score=None),
        'sec': dict(kind='sec', coverage='complete'),
        'options': dict(kind='options', call_volume=None, put_volume=None, put_call_ratio=None, call_premium=None, put_premium=None),
        'em_daily': dict(kind='move', horizon='daily', spot=None, expiry=None, chart_asset_id=None),
        'em_weekly': dict(kind='move', horizon='weekly', spot=None, expiry=None, chart_asset_id=None),
    }
    return SectionResult(section=section, status='completed', job_id=None, result_id=None,
        observed_at=now-100, computed_at=now, valid_until=now+1000, stale=False,
        analysis_version='v1', payload=payloads[section], message=None)


def test_parallel_members_share_work_but_never_ownership(research, dashboard):
    service, users, _, _ = research
    barrier = threading.Barrier(2)
    def request(user):
        barrier.wait(timeout=5)
        return service.request_research(user, 'spy', False, dashboard.clock())
    with ThreadPoolExecutor(2) as pool:
        requests = list(pool.map(request, users[:2]))
    assert requests[0].id != requests[1].id
    assert requests[0].ticker == 'SPY'
    assert len(requests[0].sections) == 5
    with dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM web_jobs').fetchone()[0] == 5
        assert con.execute('SELECT count(*) FROM report_owners').fetchone()[0] == 2
    assert service.get_request(users[1], requests[0].id, dashboard.clock()) is None
    finish_all(service, dashboard.clock())
    assert all(r.status == 'completed' for r in service.get_request(users[0], requests[0].id, dashboard.clock()).sections.values())
    third = service.request_research(users[2], 'SPY', False, dashboard.clock())
    assert all(r.status == 'completed' for r in third.sections.values())
    with dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM web_jobs').fetchone()[0] == 5


@pytest.mark.parametrize('symbol', ['*', '../SPY', 'SPY;DROP', 'SPY\n', '$SPY', 'A'*17, 'S PY'])
def test_invalid_ticker_never_creates_work(research, dashboard, symbol):
    from member_dashboard.jobs import ResearchError
    service, users, _, _ = research
    with pytest.raises(ResearchError) as caught:
        service.request_research(users[0], symbol, False, dashboard.clock())
    assert caught.value.code == 'invalid_ticker'


def test_symbol_lookup_is_bounded_local_and_distinguishes_outage(research, dashboard):
    from member_dashboard.jobs import ResearchError
    service, users, registry, _ = research
    assert service.request_research(users[0], 'brk-b', False, dashboard.clock()).ticker == 'BRK.B'
    with pytest.raises(ResearchError) as caught:
        service.request_research(users[1], 'UNKNOWN', False, dashboard.clock())
    assert caught.value.code == 'unknown_ticker'
    registry.catalog.available = False
    with pytest.raises(ResearchError) as caught:
        service.request_research(users[1], 'SPY', False, dashboard.clock())
    assert caught.value.code == 'symbol_lookup_unavailable'


def test_refresh_cooldown_and_stale_cache_create_new_immutable_result(research, dashboard):
    from member_dashboard.jobs import ResearchError
    service, users, _, _ = research
    first = service.request_research(users[0], 'SPY', False, dashboard.clock())
    finish_all(service, dashboard.clock())
    original = service.get_request(users[0], first.id, dashboard.clock()).sections['options'].result_id
    with pytest.raises(ResearchError) as caught:
        service.request_research(users[0], 'SPY', True, dashboard.clock()+10)
    assert caught.value.code == 'refresh_cooldown'
    dashboard.clock.advance(901)
    second = service.request_research(users[0], 'SPY', False, dashboard.clock())
    assert second.sections['options'].status == 'queued'
    assert service.get_request(users[0], first.id, dashboard.clock()).sections['options'].stale
    finish_all(service, dashboard.clock())
    assert service.get_request(users[0], second.id, dashboard.clock()).sections['options'].result_id != original
    with dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM market_results').fetchone()[0] == 10


@pytest.mark.parametrize('withdraw', ['feature', 'suspend', 'session', 'delete', 'policy'])
def test_late_completion_never_reattaches_withdrawn_subscriber(research, dashboard, withdraw):
    service, users, _, _ = research
    request = service.request_research(users[0], 'SPY', False, dashboard.clock())
    job = service.claim_job('worker', dashboard.clock())
    with dashboard.store.transaction() as con:
        if withdraw == 'feature':
            con.execute("UPDATE features SET enabled=0,version=version+1 WHERE name='sec'")
        elif withdraw == 'suspend':
            con.execute("UPDATE members SET status='suspended' WHERE id=?", (users[0].member_id,))
        elif withdraw == 'session':
            con.execute('UPDATE sessions SET revoked_at=? WHERE id=?', (dashboard.clock(), users[0].session_id))
        elif withdraw == 'delete':
            con.execute('UPDATE report_owners SET deleted_at=? WHERE id=(SELECT report_owner_id FROM research_requests WHERE id=?)', (dashboard.clock(), request.id))
    if withdraw == 'policy':
        from member_dashboard.source_policy import SourcePermission
        research[3].record(SourcePermission(source_id='synthetic', product_id='fixture', provider='fixture',
            policy_version='p2', audience='invited_members', status='denied'))
    service.complete_job(job.id, job.lease_token, fixture_result(job.kind, dashboard.clock()), dashboard.clock())
    with dashboard.store.transaction() as con:
        assert con.execute('SELECT result_id FROM request_sections WHERE request_id=? AND section=?',
                           (request.id, job.kind)).fetchone()[0] is None


def test_fencing_recovery_retry_limits_and_draining(research, dashboard):
    service, users, _, _ = research
    request = service.request_research(users[0], 'SPY', False, dashboard.clock())
    old = service.claim_job('old', dashboard.clock())
    service.mark_draining(old.id, old.lease_token, dashboard.clock())
    assert service.recover_expired_leases(dashboard.clock()+500) == 0
    assert service.claim_job('new', dashboard.clock()+500) is None
    service.confirm_worker_exit('old', dashboard.clock()+501, reconciled=True)
    assert service.recover_expired_leases(dashboard.clock()+502) == 1
    new = service.claim_job('new', dashboard.clock()+550)
    assert new.id == old.id and new.lease_token != old.lease_token
    service.complete_job(old.id, old.lease_token, fixture_result(old.kind, dashboard.clock()), dashboard.clock()+551)
    with dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM market_results').fetchone()[0] == 0
    service.complete_job(new.id, new.lease_token, fixture_result(new.kind, dashboard.clock()+552), dashboard.clock()+552)
    assert service.get_request(users[0], request.id, dashboard.clock()+552).sections[new.kind].status == 'completed'


def test_member_active_cap_and_dedupe_before_compute_charge(research, dashboard):
    from member_dashboard.jobs import ResearchError
    service, users, _, _ = research
    service.request_research(users[0], 'SPY', False, dashboard.clock())
    service.request_research(users[0], 'QQQ', False, dashboard.clock())
    # Joining existing ticker does not consume another active ticker slot.
    service.request_research(users[0], 'SPY', False, dashboard.clock())
    with pytest.raises(ResearchError) as caught:
        service.request_research(users[0], 'AAPL', False, dashboard.clock())
    assert caught.value.code == 'member_capacity'


def test_feature_mask_changes_analysis_fingerprint_and_read_guard(research, dashboard):
    service, users, _, _ = research
    first = service.request_research(users[0], 'SPY', False, dashboard.clock())
    finish_all(service, dashboard.clock())
    with dashboard.store.transaction() as con:
        con.execute("UPDATE features SET enabled=0,version=version+1 WHERE name='sec'")
    second = service.request_research(users[1], 'SPY', False, dashboard.clock())
    assert 'sec' not in second.sections
    assert second.sections['analysis'].status == 'queued'
    assert second.sections['options'].status == 'completed'
    assert service.get_request(users[0], first.id, dashboard.clock()).sections['analysis'].payload is None


def test_research_routes_require_auth_and_never_execute_provider(dashboard):
    assert dashboard.client.get('/api/v1/research/missing').status_code == 401
    assert dashboard.client.post('/api/v1/research', json={'ticker': 'SPY', 'refresh': False}).status_code in (401,403)


def test_retry_limit_and_section_failure_independence(research, dashboard):
    service, users, _, _ = research
    request = service.request_research(users[0], 'SPY', False, dashboard.clock())
    ids = []
    for attempt in range(3):
        job = service.claim_job('worker', dashboard.clock())
        ids.append(job.id)
        service.fail_attempt(job.id, job.lease_token, dashboard.clock())
        dashboard.clock.advance(40)
    assert len(set(ids)) == 1
    finish_all(service, dashboard.clock())
    result = service.get_request(users[0], request.id, dashboard.clock())
    assert result.sections['analysis'].status == 'failed'
    assert all(result.sections[name].status == 'completed' for name in ['sec','options','em_daily','em_weekly'])
    with dashboard.store.transaction() as con:
        assert con.execute('SELECT attempts FROM web_jobs WHERE id=?', (ids[0],)).fetchone()[0] == 3


def test_hourly_cap_and_global_pending_cap(research, dashboard):
    from member_dashboard.jobs import ResearchError
    service, users, registry, _ = research
    for _ in range(10):
        service.request_research(users[0], 'SPY', True, dashboard.clock())
        finish_all(service, dashboard.clock())
        dashboard.clock.advance(61)
    with pytest.raises(ResearchError) as error:
        service.request_research(users[0], 'SPY', True, dashboard.clock())
    assert error.value.code == 'member_hourly_limit'
    # Real pending rows from independent requests fill the shared global bound.
    from member_dashboard.providers import SymbolCatalog
    registry.catalog = SymbolCatalog({f'TEST{chr(65+i)}': 'equity' for i in range(11)})
    for index in range(10):
        # Each fixture owner starts with no active requests; all auth checks remain real.
        with dashboard.store.transaction() as con:
            con.execute("UPDATE request_sections SET status='unavailable' WHERE request_id IN (SELECT id FROM research_requests WHERE member_id=?)", (users[1].member_id,))
        service.request_research(users[1], f'TEST{chr(65+index)}', False, dashboard.clock())
        dashboard.clock.advance(1)
    with pytest.raises(ResearchError) as error:
        service.request_research(users[2], 'TESTK', False, dashboard.clock())
    assert error.value.code == 'global_capacity'


def test_policy_version_and_metadata_change_dedupe(research, dashboard):
    from dataclasses import replace
    from member_dashboard.source_policy import SourcePermission
    service, users, registry, policy = research
    first = service.request_research(users[0], 'SPY', False, dashboard.clock())
    finish_all(service, dashboard.clock())
    policy.record(SourcePermission(source_id='synthetic', product_id='fixture', provider='fixture',
        policy_version='p2', audience='invited_members', status='allowed', display_raw=True,
        display_derived=True, retain=True, private_grant_ref='fixture', evidence_ref='fixture',
        terms_url='https://www.sec.gov/fixture-terms', effective_at=0.0, delay_seconds=60.0))
    for section, spec in registry.providers.items():
        lineage = spec.lineage.model_copy(update={'sources': [s.model_copy(update={'policy_version': 'p2'}) for s in spec.lineage.sources]})
        registry.providers[section] = replace(spec, lineage=lineage)
    second = service.request_research(users[1], 'SPY', False, dashboard.clock())
    assert second.sections['options'].status == 'queued'
    assert second.sections['options'].job_id != first.sections['options'].job_id


@pytest.mark.asyncio
async def test_worker_persists_once_and_restart_reuses_result(research, dashboard):
    from member_dashboard.provider_runtime import ProviderRuntime
    from member_dashboard.worker import ComputeWorker
    service, users, registry, _ = research
    request = service.request_research(users[0], 'SPY', False, dashboard.clock())
    runtime = ProviderRuntime(dashboard.store, 'worker', clock=dashboard.clock)
    worker = ComputeWorker(service, registry, runtime, clock=dashboard.clock)
    try:
        for _ in range(5):
            await worker.run_once()
    finally:
        runtime.shutdown()
    assert all(x.status == 'completed' for x in service.get_request(users[0], request.id, dashboard.clock()).sections.values())
    restarted = type(service)(dashboard.store, service.auth, service.policy, registry)
    assert restarted.claim_job('new-worker', dashboard.clock()+35) is None
    cached = restarted.request_research(users[1], 'SPY', False, dashboard.clock())
    assert cached.sections['analysis'].result_id == service.get_request(users[0], request.id, dashboard.clock()).sections['analysis'].result_id


@pytest.mark.asyncio
async def test_worker_deadline_keeps_heartbeats_and_accepts_late_result(research, dashboard):
    import asyncio
    from dataclasses import replace
    from member_dashboard.provider_runtime import ProviderRuntime
    from member_dashboard.worker import ComputeWorker
    service, users, registry, _ = research
    release = threading.Event()
    def blocked(*_):
        assert release.wait(5)
        return fixture_result('analysis', dashboard.clock())
    registry.providers['analysis'] = replace(registry.providers['analysis'], operation=blocked)
    request = service.request_research(users[0], 'SPY', False, dashboard.clock())
    runtime = ProviderRuntime(dashboard.store, 'worker', clock=dashboard.clock)
    worker = ComputeWorker(service, registry, runtime, clock=dashboard.clock, deadlines={'analysis': .01})
    try:
        await worker.run_once()
        assert service.get_request(users[0], request.id, dashboard.clock()).sections['analysis'].status == 'unavailable'
        dashboard.clock.advance(35)
        await worker.run_once()
        assert service.recover_expired_leases(dashboard.clock()) == 0
        assert service.claim_job('rival', dashboard.clock()) is None
        release.set()
        async with asyncio.timeout(3):
            while runtime.running_count: await asyncio.sleep(.005)
        await worker.run_once()
        assert service.get_request(users[0], request.id, dashboard.clock()).sections['analysis'].status == 'completed'
    finally:
        release.set()
        runtime.shutdown()


def test_expected_move_cache_expires_at_session_and_option_expiry(research, dashboard):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    service, users, _, _ = research
    now = datetime(2026,10,5,12,59,59,tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()
    # Renew synthetic sessions for this separate deterministic exchange boundary.
    with dashboard.store.transaction() as con:
        con.execute('UPDATE sessions SET absolute_expires_at=?,idle_expires_at=?', (now+43200,now+7200))
    first = service.request_research(users[0], 'SPY', False, now)
    finish_all(service, now)
    second = service.request_research(users[1], 'SPY', False, now+2)
    assert second.sections['em_daily'].status == 'queued'
    assert second.sections['em_weekly'].status == 'queued'
    assert second.sections['options'].status == 'completed'
    daily = None
    while job := service.claim_job('worker', now+2):
        result = fixture_result(job.kind, now+2)
        if job.kind == 'em_daily':
            result = result.model_copy(update={'payload': result.payload.model_copy(update={'expiry':'2026-10-05'})})
            daily = job
        service.complete_job(job.id, job.lease_token, result, now+2)
    third = service.request_research(users[2], 'SPY', False, now+3)
    assert daily is not None and third.sections['em_daily'].status == 'queued'


def test_authenticated_routes_cache_private_and_get_does_not_schedule(research, dashboard):
    from member_dashboard.auth import digest
    service, users, _, _ = research
    with dashboard.store.transaction() as con:
        con.execute('UPDATE sessions SET token_digest=?,csrf_digest=? WHERE id=?',
                    (digest('fixture-session'),digest('fixture-csrf'),users[0].session_id))
    dashboard.client.cookies.set('__Host-member_session','fixture-session')
    response = dashboard.client.post('/api/v1/research', json={'ticker':'SPY','refresh':False},
        headers={'Origin':dashboard.settings.origin,'X-CSRF-Token':'fixture-csrf'})
    assert response.status_code == 200, response.text
    request_id = response.json()['id']
    assert response.headers['Cache-Control'] == 'private, no-store'
    for _ in range(3):
        assert dashboard.client.get('/api/v1/research/'+request_id).status_code == 200
    with dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM web_jobs').fetchone()[0] == 5
        assert con.execute('SELECT count(*) FROM provider_calls').fetchone()[0] == 0
        assert con.execute('SELECT count(*) FROM research_requests').fetchone()[0] == 1


def test_persistence_failure_rolls_back_result_job_and_attachments(research, dashboard):
    import sqlite3
    service, users, _, _ = research
    request = service.request_research(users[0], 'SPY', False, dashboard.clock())
    job = service.claim_job('worker', dashboard.clock())
    with dashboard.store.transaction() as con:
        con.execute("CREATE TRIGGER fail_snapshot BEFORE INSERT ON report_versions BEGIN SELECT RAISE(ABORT,'synthetic disk failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match='synthetic disk failure'):
        service.complete_job(job.id, job.lease_token, fixture_result(job.kind,dashboard.clock()), dashboard.clock())
    with dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM market_results').fetchone()[0] == 0
        assert con.execute('SELECT status FROM web_jobs WHERE id=?',(job.id,)).fetchone()[0] == 'running'
        assert con.execute('SELECT result_id FROM request_sections WHERE request_id=? AND section=?',(request.id,job.kind)).fetchone()[0] is None
        con.execute('DROP TRIGGER fail_snapshot')
    service.complete_job(job.id,job.lease_token,fixture_result(job.kind,dashboard.clock()),dashboard.clock())
    assert service.get_request(users[0],request.id,dashboard.clock()).sections['analysis'].status == 'completed'


@pytest.mark.asyncio
async def test_capacity_denial_does_not_exhaust_job_attempts(research, dashboard):
    from member_dashboard.provider_runtime import ProviderRuntime
    from member_dashboard.worker import ComputeWorker
    service, users, registry, _ = research
    service.request_research(users[0], 'SPY', False, dashboard.clock())
    runtime = ProviderRuntime(dashboard.store,'worker',clock=dashboard.clock)
    worker = ComputeWorker(service,registry,runtime,clock=dashboard.clock)
    release = threading.Event()
    try:
        await runtime.run_blocking('one',lambda:release.wait(5),.01)
        await runtime.run_blocking('two',lambda:release.wait(5),.01)
        for _ in range(4):
            await worker.run_once()
            dashboard.clock.advance(10)
        with dashboard.store.transaction() as con:
            assert con.execute('SELECT sum(attempts) FROM web_jobs').fetchone()[0] == 0
    finally:
        release.set()
        from tests.member_dashboard.test_provider_runtime import wait_until
        await wait_until(lambda: runtime.running_count == 0)
        runtime.shutdown()


@pytest.mark.parametrize('persist', [False,True])
def test_real_process_crash_response_boundary_is_bounded_and_persisted_result_survives(research, dashboard, tmp_path, persist):
    import subprocess
    import sys
    service, users, _, _ = research
    request = service.request_research(users[0],'SPY',False,dashboard.clock())
    marker = tmp_path/'responses.txt'
    script = '''
import asyncio,json,os,sys
from pathlib import Path
from member_dashboard.auth import AuthService
from member_dashboard.jobs import JobService
from member_dashboard.store import WebStore
from member_dashboard.source_policy import SourcePolicy
from member_dashboard.providers import ProviderRegistry,ProviderSpec
from member_dashboard.provider_runtime import ProviderRuntime
from member_dashboard.contracts import ContentLineage,SectionResult
path,marker,worker,now,persist=sys.argv[1:]
now=float(now)
store=WebStore(Path(path))
registry=ProviderRegistry()
with store.transaction() as con:
    for section,metadata in con.execute('SELECT section,input_json FROM web_jobs'):
        spec=json.loads(metadata)['provider_spec']
        registry.register(section,ProviderSpec(ContentLineage.model_validate(spec['lineage']),lambda *_:None,spec['provider'],spec['asynchronous'],spec['analysis_version'],spec['safe_input_version'],spec['settings_hash']))
service=JobService(store,AuthService(store),SourcePolicy(store,authority_current=lambda:True,backup_compliant=lambda *_:True),registry)
job=service.claim_job(worker,now)
runtime=ProviderRuntime(store,worker,clock=lambda:now)
def response():
    with open(marker,'a') as stream: stream.write(job.kind+'\\n')
    return SectionResult(section=job.kind,status='completed',job_id=None,result_id=None,observed_at=now,computed_at=now,valid_until=now+900,stale=False,analysis_version='v1',payload=dict(kind='analysis',summary='Synthetic',direction='neutral',score=None),message=None)
outcome=asyncio.run(runtime.run_blocking(job.call_id,response,1))
if persist=='yes': service.complete_job(job.id,job.lease_token,outcome.value,now)
os._exit(17)
'''
    for attempt in range(1 if persist else 3):
        worker = 'crash-worker-'+str(attempt)
        child = subprocess.run([sys.executable,'-c',script,str(dashboard.settings.web_path),str(marker),worker,str(dashboard.clock()),'yes' if persist else 'no'],timeout=8,capture_output=True,text=True)
        assert child.returncode == 17, child.stderr
        service.confirm_worker_exit(worker,dashboard.clock(),reconciled=True)
        dashboard.clock.advance(31)
        service.recover_expired_leases(dashboard.clock())
        dashboard.clock.advance(40)
    values = service.get_request(users[0],request.id,dashboard.clock()).sections
    assert values['analysis'].status == ('completed' if persist else 'failed')
    assert marker.read_text().splitlines() == ['analysis']*(1 if persist else 3)
    next_job = service.claim_job('survivor',dashboard.clock())
    assert next_job.kind == 'sec'


def test_revoked_queued_work_never_calls_provider_and_cannot_resurrect(research,dashboard):
    service,users,_,_=research
    original=service.request_research(users[0],'SPY',False,dashboard.clock())
    with dashboard.store.transaction() as con:
        con.execute('UPDATE sessions SET revoked_at=? WHERE id=?',(dashboard.clock(),users[0].session_id))
    assert service.claim_job('worker',dashboard.clock()) is None
    with dashboard.store.transaction() as con:
        assert con.execute("SELECT count(*) FROM web_jobs WHERE status IN ('queued','running')").fetchone()[0] == 0
    fresh=service.request_research(users[1],'SPY',False,dashboard.clock())
    assert fresh.id != original.id and fresh.sections['analysis'].status == 'queued'


def test_worker_inputs_preserve_current_features_and_reject_untracked_evidence(research,dashboard):
    from member_dashboard.contracts import Evidence
    service,users,_,_=research
    service.request_research(users[0],'SPY',False,dashboard.clock())
    job=service.claim_job('worker',dashboard.clock())
    assert job.inputs['enabled_features'] == ['analysis','sec','options','em_daily','em_weekly']
    result=fixture_result(job.kind,dashboard.clock()).model_copy(update={'evidence':[
        Evidence(id='other',source_id='untracked-source',source_version='v1',observed_at=dashboard.clock(),url=None,excerpt='unverified',research_only=True)]})
    with pytest.raises(ValueError,match='lineage'):
        service.complete_job(job.id,job.lease_token,result,dashboard.clock())


@pytest.mark.asyncio
async def test_registry_compute_returns_the_typed_section_contract(research,dashboard):
    from member_dashboard.contracts import SectionResult
    from member_dashboard.provider_runtime import ProviderRuntime
    from member_dashboard.providers import ComputeInputs
    service,users,registry,_=research
    service.request_research(users[0],'SPY',False,dashboard.clock())
    job=service.claim_job('worker',dashboard.clock())
    runtime=ProviderRuntime(dashboard.store,'worker',clock=dashboard.clock)
    try:
        result=await registry.compute(job.ticker,job.kind,ComputeInputs(runtime,job.call_id,1,dashboard.clock(),job.inputs))
        assert isinstance(result,SectionResult)
    finally:
        runtime.shutdown()


@pytest.mark.parametrize('recovery',[False,True])
def test_last_failure_finalizes_immutable_mixed_outcome_snapshot(research,dashboard,recovery):
    import json
    service,users,_,_=research
    initial_now=dashboard.clock()
    request=service.request_research(users[0],'SPY',False,dashboard.clock())
    for _ in range(4):
        job=service.claim_job('worker',dashboard.clock())
        service.complete_job(job.id,job.lease_token,fixture_result(job.kind,dashboard.clock()),dashboard.clock())
        dashboard.clock.advance(1)
    last=service.claim_job('worker',dashboard.clock())
    if recovery:
        for _ in range(2):
            service.fail_attempt(last.id,last.lease_token,dashboard.clock())
            dashboard.clock.advance(40)
            last=service.claim_job('worker',dashboard.clock())
        service.confirm_worker_exit('worker',dashboard.clock(),reconciled=True)
        dashboard.clock.advance(31)
        service.recover_expired_leases(dashboard.clock())
    else:
        service.fail_attempt(last.id,last.lease_token,dashboard.clock(),retryable=False)
    with dashboard.store.transaction() as con:
        row=con.execute('SELECT v.finalized,v.content_json FROM report_versions v JOIN report_owners o ON o.current_version_id=v.id WHERE o.report_id=?',(request.report_id,)).fetchone()
        assert row[0] == 1
        content=json.loads(row[1])
        assert content['em_weekly']['status'] == 'failed'
        assert content['analysis']['observed_at'] == initial_now-100
        assert con.execute('SELECT count(*) FROM report_versions WHERE report_id=?',(request.report_id,)).fetchone()[0] == 5


@pytest.mark.asyncio
@pytest.mark.parametrize('changed', ['analysis_version','safe_input_version','settings_hash','sources','dependencies'])
@pytest.mark.parametrize('after_claim',[False,True])
async def test_saved_provider_spec_is_fenced_before_execution(research,dashboard,changed,after_claim):
    from dataclasses import replace
    from member_dashboard.contracts import FieldDependency
    from member_dashboard.provider_runtime import ProviderRuntime
    from member_dashboard.worker import ComputeWorker
    service,users,registry,_=research
    request=service.request_research(users[0],'SPY',False,dashboard.clock())
    job=service.claim_job('worker',dashboard.clock()) if after_claim else None
    executed=[]
    spec=registry.providers['analysis']
    update={'operation':lambda *_: executed.append('changed') or fixture_result('analysis',dashboard.clock())}
    if changed == 'sources':
        update['lineage']=spec.lineage.model_copy(update={'sources':[s.model_copy(update={'source_version':'new-input'}) for s in spec.lineage.sources]})
    elif changed == 'dependencies':
        update['lineage']=spec.lineage.model_copy(update={'field_dependencies':[FieldDependency(field_path='summary',required_features=['sec'])]})
    else:
        update[changed]='new-version'
    registry.providers['analysis']=replace(spec,**update)
    runtime=ProviderRuntime(dashboard.store,'worker',clock=dashboard.clock)
    worker=ComputeWorker(service,registry,runtime,clock=dashboard.clock)
    try:
        if job:
            # Existing claim models a rolling registry change between claim and compute.
            from member_dashboard.providers import ComputeInputs
            with pytest.raises(ValueError,match='specification'):
                await registry.compute(job.ticker,job.kind,ComputeInputs(runtime,job.call_id,1,dashboard.clock(),job.inputs))
        else:
            await worker.run_once()
            assert service.get_request(users[0],request.id,dashboard.clock()).sections['analysis'].status == 'unavailable'
        assert executed == []
        with dashboard.store.transaction() as con:
            assert con.execute("SELECT count(*) FROM market_results WHERE section='analysis'").fetchone()[0] == 0
    finally:
        runtime.shutdown()


def test_completion_rejects_wrong_version_instead_of_relabeling(research,dashboard):
    service,users,_,_=research
    service.request_research(users[0],'SPY',False,dashboard.clock())
    job=service.claim_job('worker',dashboard.clock())
    wrong=fixture_result(job.kind,dashboard.clock()).model_copy(update={'analysis_version':'v2'})
    with pytest.raises(ValueError,match='version'):
        service.complete_job(job.id,job.lease_token,wrong,dashboard.clock())


@pytest.mark.parametrize('started',[False,True])
@pytest.mark.parametrize('withdraw',['feature','deleted','session'])
def test_withdrawal_snapshot_settles_without_resurrecting_owner(research,dashboard,started,withdraw):
    import json
    service,users,_,_=research
    request=service.request_research(users[0],'SPY',False,dashboard.clock())
    initial=dashboard.clock()
    for _ in range(4):
        job=service.claim_job('worker',dashboard.clock())
        service.complete_job(job.id,job.lease_token,fixture_result(job.kind,dashboard.clock()),dashboard.clock())
        dashboard.clock.advance(1)
    last=service.claim_job('worker',dashboard.clock()) if started else None
    with dashboard.store.transaction() as con:
        old=con.execute('SELECT current_version_id FROM report_owners WHERE report_id=?',(request.report_id,)).fetchone()[0]
        if withdraw=='feature':
            con.execute("UPDATE features SET enabled=0,version=version+1 WHERE name='em_weekly'")
        elif withdraw=='deleted':
            con.execute('UPDATE report_owners SET deleted_at=? WHERE report_id=?',(dashboard.clock(),request.report_id))
        else:
            con.execute('UPDATE sessions SET revoked_at=? WHERE id=?',(dashboard.clock(),users[0].session_id))
    if last:
        service.complete_job(last.id,last.lease_token,fixture_result(last.kind,dashboard.clock()),dashboard.clock())
    else:
        assert service.claim_job('worker',dashboard.clock()) is None
    with dashboard.store.transaction() as con:
        row=con.execute('SELECT v.id,v.finalized,v.content_json FROM report_versions v JOIN report_owners o ON o.current_version_id=v.id WHERE o.report_id=?',(request.report_id,)).fetchone()
        if withdraw=='feature':
            assert row[0] != old and row[1] == 1
            content=json.loads(row[2])
            assert content['em_weekly']['status']=='unavailable'
            assert content['analysis']['payload'] is None
            assert content['sec']['observed_at']==initial-99
            assert con.execute('SELECT finalized FROM report_versions WHERE id=?',(old,)).fetchone()[0] == 0
        else:
            assert row[0] == old


@pytest.mark.parametrize('started',[False,True])
@pytest.mark.parametrize('withdraw',['features','policy'])
@pytest.mark.parametrize('owner_state',['active','deleted','revoked','suspended'])
def test_all_withdrawn_terminal_snapshot_is_content_free_and_owner_guarded(research,dashboard,started,withdraw,owner_state):
    import json
    from member_dashboard.source_policy import SourcePermission
    service,users,_,policy=research
    request=service.request_research(users[0],'SPY',False,dashboard.clock())
    for _ in range(4):
        job=service.claim_job('worker',dashboard.clock())
        service.complete_job(job.id,job.lease_token,fixture_result(job.kind,dashboard.clock()),dashboard.clock())
        dashboard.clock.advance(1)
    last=service.claim_job('worker',dashboard.clock()) if started else None
    with dashboard.store.transaction() as con:
        original=con.execute('SELECT v.id,v.content_json,v.finalized,v.source_lineage_json FROM report_versions v JOIN report_owners o ON o.current_version_id=v.id WHERE o.report_id=?',(request.report_id,)).fetchone()
        if withdraw=='features':
            con.execute("UPDATE features SET enabled=0,version=version+1 WHERE name IN ('analysis','sec','options','em_daily','em_weekly')")
        if owner_state=='deleted':
            con.execute('UPDATE report_owners SET deleted_at=? WHERE report_id=?',(dashboard.clock(),request.report_id))
        elif owner_state=='revoked':
            con.execute('UPDATE sessions SET revoked_at=? WHERE id=?',(dashboard.clock(),users[0].session_id))
        elif owner_state=='suspended':
            con.execute("UPDATE members SET status='suspended' WHERE id=?",(users[0].member_id,))
    if withdraw=='policy':
        policy.record(SourcePermission(source_id='synthetic',product_id='fixture',provider='fixture',policy_version='p2',audience='invited_members',status='denied'))
    if last:
        service.complete_job(last.id,last.lease_token,fixture_result(last.kind,dashboard.clock()),dashboard.clock())
    else:
        assert service.claim_job('worker',dashboard.clock()) is None
    with dashboard.store.transaction() as con:
        latest=con.execute('SELECT v.id,v.finalized,v.content_json,v.source_lineage_json,v.field_dependencies_json,v.required_features_json,v.retention_deadline FROM report_versions v JOIN report_owners o ON o.current_version_id=v.id WHERE o.report_id=?',(request.report_id,)).fetchone()
        assert con.execute('SELECT id,content_json,finalized,source_lineage_json FROM report_versions WHERE id=?',(original[0],)).fetchone()==original
        if owner_state!='active':
            assert latest[0]==original[0]
            assert con.execute('SELECT count(*) FROM report_versions WHERE report_id=?',(request.report_id,)).fetchone()[0]==4
            return
        assert latest[0]!=original[0] and latest[1]==1
        sections=json.loads(latest[2])
        assert set(sections)=={'analysis','sec','options','em_daily','em_weekly'}
        for value in sections.values():
            assert value['status']=='unavailable'
            assert value['payload'] is None and value['evidence']==[]
            assert all(value[name] is None for name in ['observed_at','computed_at','valid_until','job_id','result_id','message'])
        assert latest[3:]==('[]','[]','[]',None)
        assert con.execute('SELECT count(*) FROM report_versions WHERE report_id=?',(request.report_id,)).fetchone()[0]==5
