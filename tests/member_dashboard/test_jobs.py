"""Durable research behavior on separate real SQLite connections."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import threading
from uuid import uuid4

import pytest


def test_jobs_contract_is_available():
    assert importlib.util.find_spec('member_dashboard.jobs') is not None


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
