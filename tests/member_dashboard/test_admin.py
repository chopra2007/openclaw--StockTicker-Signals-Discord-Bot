"""Task11 real web-store administration, current access, and safe monitoring."""
import json
from typing import get_args
from uuid import uuid4
import pytest
from member_dashboard.auth import AuthError
from member_dashboard.authorization import SESSION_COOKIE
from member_dashboard.contracts import Feature
from tests.member_dashboard.test_auth import admin, PASSWORD


def identity(d, role='admin', username=None):
    auth=d.app.state.auth
    username=username or ('person_'+uuid4().hex[:12])
    mid=admin(auth,d,username)
    if role=='member':
        with d.store.transaction() as con: con.execute("UPDATE members SET role='member' WHERE id=?",(mid,))
    session=auth.login(username,PASSWORD,d.clock())
    return mid,session,auth.principal(session.token,d.clock())


def login(d, session):
    d.client.cookies.set(SESSION_COOKIE,session.token)


def write(d,path,session,body=None):
    method='PUT' if path.startswith('features/') else 'DELETE' if path.startswith('invites/') else 'POST'
    return d.client.request(method,'/api/v1/admin/'+path,json=body or {},headers={'Origin':d.settings.origin,'X-CSRF-Token':session.csrf_token})


def test_admin_routes_roles_csrf_unknown_and_safe_lists(dashboard):
    d=dashboard
    mid,session,_=identity(d,'member');login(d,session)
    assert d.client.get('/api/v1/admin/members').status_code==403
    aid,owner,_=identity(d);login(d,owner)
    assert d.client.put('/api/v1/admin/features/sec',json={'enabled':False}).status_code==403
    assert write(d,'features/unknown',owner,{'enabled':False}).status_code==422
    assert write(d,'features/sec',owner,{'enabled':False,'role':'admin'}).status_code==422
    response=d.client.get('/api/v1/admin/members')
    assert response.status_code==200
    assert {r['id'] for r in response.json()['items']}=={mid,aid}
    assert all(set(r)=={'id','username','role','status'} for r in response.json()['items'])


@pytest.mark.parametrize('feature',get_args(Feature))
def test_exact_feature_switches_version_and_me(dashboard,feature):
    d=dashboard
    _,s,p=identity(d);login(d,s)
    first=write(d,'features/'+feature,s,{'enabled':False})
    assert first.status_code==200
    assert first.json()=={'name':feature,'enabled':False,'version':2}
    assert write(d,'features/'+feature,s,{'enabled':False}).json()==first.json()
    assert d.client.get('/api/v1/me').json()['features'][feature]=={'enabled':False,'version':2}
    assert write(d,'features/'+feature,s,{'enabled':True}).json()['version']==3


def test_suspend_reactivate_and_session_revocation_need_new_login(dashboard):
    d=dashboard
    _,a,_=identity(d);mid,s,p=identity(d,'member');login(d,a)
    assert write(d,'members/'+mid+'/suspend',a).status_code==204
    with pytest.raises(AuthError): d.app.state.auth.revalidate(p,d.clock())
    assert write(d,'members/'+mid+'/reactivate',a).status_code==204
    with pytest.raises(AuthError): d.app.state.auth.principal(s.token,d.clock())
    fresh=d.app.state.auth.login(s.member.username,PASSWORD,d.clock())
    assert write(d,'members/'+mid+'/revoke-sessions',a).status_code==204
    with pytest.raises(AuthError): d.app.state.auth.principal(fresh.token,d.clock())


def test_self_lockout_denied_and_denials_audited(dashboard):
    d=dashboard
    mid,s,_=identity(d);login(d,s)
    for action in ('suspend','revoke-sessions','reset-link'):
        assert write(d,'members/'+mid+'/'+action,s).status_code==403
    assert d.client.get('/api/v1/me').status_code==200
    audit=d.client.get('/api/v1/admin/audit').json()['items']
    assert sum(row['result']=='denied' for row in audit)==3


def test_invite_reset_redaction_and_prior_reset_revoked(dashboard):
    d=dashboard
    _,a,_=identity(d);mid,s,_=identity(d,'member');login(d,a)
    invite=write(d,'invites',a)
    assert invite.status_code==200
    issued=invite.json()
    assert write(d,'invites/'+issued['id'],a).status_code==204
    with pytest.raises(AuthError): d.app.state.auth.redeem_invite(issued['token'],'new_member',PASSWORD,d.clock())
    first=write(d,'members/'+mid+'/reset-link',a).json()
    second=write(d,'members/'+mid+'/reset-link',a).json()
    with pytest.raises(AuthError): d.app.state.auth.reset_password(first['token'],PASSWORD+' new',d.clock())
    d.app.state.auth.reset_password(second['token'],PASSWORD+' new',d.clock())
    with d.store.transaction() as con:
        d.app.state.auth._audit(con,'local_admin_recovery',mid,d.clock(),detail={'operator_identity':'PRIVATE OPERATOR'})
    audit=d.client.get('/api/v1/admin/audit')
    listed=d.client.get('/api/v1/admin/invites')
    assert audit.status_code==listed.status_code==200
    combined=audit.text+listed.text
    for secret in (issued['token'],first['token'],second['token'],s.token,'PRIVATE OPERATOR','token_digest','password_hash'):
        assert secret not in combined


def test_health_unknown_is_not_empty_queue_success(dashboard):
    d=dashboard
    _,s,_=identity(d);login(d,s)
    result=d.client.get('/api/v1/admin/health')
    assert result.status_code==200
    health=result.json()
    assert health['api']['status']=='responsive'
    assert health['frontend']['status']==health['supervisor']['status']==health['compute']['status']=='unavailable'
    assert health['queue']['queued']==0
    assert health['usage']['input_tokens'] is None and health['usage']['cost'] is None


def test_field_only_dependencies_are_union_not_silently_ignored():
    from member_dashboard.contracts import ContentLineage
    lineage=ContentLineage(sources=[dict(source_id='synthetic',product_id='p',source_version='v',policy_version='v')],
        required_features=['analysis'],field_dependencies=[dict(field_path='payload.summary',required_features=['options'])],retention_deadline=None)
    assert set(lineage.required_features)=={'analysis','options'}

@pytest.mark.parametrize('feature',['sec','options','em_daily','em_weekly'])
@pytest.mark.asyncio
async def test_new_mixed_analysis_disabled_before_model_and_storage(dashboard,feature):
    from dataclasses import replace
    from test_research_parity import prepared_case
    from test_sec_outcomes import member_context
    from consensus_engine.analysis.research_contracts import ResearchServices,GapFillResult
    from member_dashboard.research import MemberResearchProvider
    from member_dashboard.providers import ProviderRegistry
    _,record,settings,clock=prepared_case('sparse_levels')
    record=replace(record,evidence=tuple(replace(row,source_id='synthetic',source_version='s1') for row in record.evidence))
    calls=[]
    async def synthesis(request): calls.append('model');return ''
    async def gap(request): calls.append('gap');return GapFillResult()
    context=member_context(dashboard,{},analysis_records={'NVDA':record},analysis_services=ResearchServices(settings,clock,synthesis,gap,lambda event:None),
        input_dependencies={'analysis_records':['analysis',feature],'analysis_services':['analysis',feature]})
    registry=ProviderRegistry();provider=MemberResearchProvider(context);provider.register(registry)
    assert feature in registry.providers['analysis'].lineage.required_features
    _,_,actor=identity(dashboard)
    dashboard.app.state.admin.set_feature(actor,feature,False)
    result=await provider.compute('NVDA','analysis',{'enabled_features':['analysis']})
    assert result.status=='unavailable' and result.payload is None and calls==[]


@pytest.mark.parametrize('kwargs',[{'analysis_records':{}},{'input_dependencies':{'invented':['options']}}])
def test_missing_or_unknown_mixed_input_declarations_fail_closed(dashboard,kwargs):
    from test_sec_outcomes import member_context
    with pytest.raises(ValueError,match='dependencies'):
        member_context(dashboard,{},**kwargs)


@pytest.mark.asyncio
async def test_actual_worker_observation_separates_responsiveness_and_progress(dashboard):
    from member_dashboard.worker import ComputeWorker
    from member_dashboard.provider_runtime import ProviderRuntime
    d=dashboard
    _,_,actor=identity(d)
    worker=ComputeWorker(d.app.state.research,d.app.state.research.registry,ProviderRuntime(d.store,'synthetic-worker',clock=d.clock),clock=d.clock)
    await worker.run_once()
    health=d.app.state.admin.health_snapshot(actor)
    assert health.compute.status=='responsive' and health.compute.state=='idle'
    assert health.compute.progress_at is None
    d.clock.advance(15)
    assert d.app.state.admin.health_snapshot(actor).compute.status=='stale'
    worker.runtime.shutdown()

from test_jobs import research, fixture_result, finish_all


def test_disabled_owned_asset_403_other_owner_404_and_stale_session_401(research,dashboard):
    from io import BytesIO
    from PIL import Image
    from member_dashboard.assets import AssetService
    jobs,users,_,_=research
    d=dashboard;d.app.state.research=jobs
    request=jobs.request_research(users[0],'SPY',False,d.clock())
    png=BytesIO();Image.new('RGB',(4,4)).save(png,format='PNG')
    while job:=jobs.claim_job('fixture',d.clock()):
        jobs.complete_job(job.id,job.lease_token,fixture_result(job.kind,d.clock()),d.clock(),png=png.getvalue() if job.kind=='em_daily' else None)
    asset=jobs.get_request(users[0],request.id,d.clock()).sections['em_daily'].payload.chart_asset_id
    _,_,actor=identity(d)
    d.app.state.admin.set_feature(actor,'em_daily',False)
    # HTTP identity comes from current auth; avoid possessing a fixture raw token.
    from member_dashboard.authorization import require_member
    d.app.dependency_overrides[require_member]=lambda:users[0]
    assert d.client.get('/api/v1/assets/'+asset).status_code==403
    jobs.policy.authority_current=lambda:False
    assert d.client.get('/api/v1/assets/'+asset).status_code==404
    jobs.policy.authority_current=lambda:True
    d.app.dependency_overrides[require_member]=lambda:users[1]
    assert d.client.get('/api/v1/assets/'+asset).status_code==404
    d.app.state.admin.suspend_member(actor,users[0].member_id)
    d.app.dependency_overrides[require_member]=lambda:users[0]
    assert d.client.get('/api/v1/assets/'+asset).status_code==401


def test_suspend_completion_race_does_not_attach_or_release_actual_work(research,dashboard):
    jobs,users,_,_=research
    d=dashboard
    request=jobs.request_research(users[0],'SPY',False,d.clock())
    job=jobs.claim_job('worker',d.clock())
    _,_,actor=identity(d)
    d.app.state.admin.suspend_member(actor,users[0].member_id)
    with d.store.transaction() as con:
        assert con.execute("SELECT status FROM web_jobs WHERE id=?",(job.id,)).fetchone()[0]=='running'
    jobs.complete_job(job.id,job.lease_token,fixture_result(job.kind,d.clock()),d.clock())
    with pytest.raises(AuthError): jobs.get_request(users[0],request.id,d.clock())
    with d.store.transaction() as con:
        assert con.execute('SELECT current_version_id FROM report_owners WHERE report_id=?',(request.report_id,)).fetchone()[0] is None

@pytest.mark.parametrize('feature',['analysis','sec','options','em_daily','em_weekly'])
def test_admin_disable_research_current_cached_history_and_tool(research,dashboard,feature):
    import sqlite3
    from member_dashboard.history import HistoryService
    from member_dashboard.assistant_tools import get_research,parse_tool
    from test_assistant import allow_model
    jobs,users,registry,policy=research;d=dashboard
    allow_model(research)
    saved=jobs.request_research(users[0],'SPY',False,d.clock());finish_all(jobs,d.clock())
    _,_,actor=identity(d)
    before=d.settings.market_path.read_bytes()
    d.app.state.admin.set_feature(actor,feature,False)
    assert feature not in jobs.get_request(users[0],saved.id,d.clock()).sections
    history=HistoryService(jobs,signing_key=b'synthetic-history-key-at-least32',clock=d.clock)
    assert history.get_report(users[0],saved.report_id).sections[feature].payload is None
    with jobs.store.transaction() as con:
        con.row_factory=sqlite3.Row
        result=get_research(jobs,con,users[0],parse_tool({'name':'get_research','arguments':{'request_id':saved.id}}),d.clock())
        assert all(item['section']!=feature for item in result.content['sections'])
        count=con.execute('SELECT count(*) FROM web_jobs').fetchone()[0]
    # Current/cache reads never submit work.
    with jobs.store.transaction() as con: assert con.execute('SELECT count(*) FROM web_jobs').fetchone()[0]==count
    assert d.settings.market_path.read_bytes()==before
    newer=jobs.request_research(users[1],'SPY',False,d.clock())
    assert feature not in newer.sections


def test_legacy_field_only_job_dependency_blocks_completion(research,dashboard):
    jobs,users,_,_=research;d=dashboard
    saved=jobs.request_research(users[0],'SPY',False,d.clock())
    job=jobs.claim_job('worker',d.clock())
    with d.store.transaction() as con:
        data=json.loads(con.execute('SELECT lineage_json FROM web_jobs WHERE id=?',(job.id,)).fetchone()[0])
        data['field_dependencies']=[{'field_path':'payload.summary','required_features':['feed']}]
        con.execute('UPDATE web_jobs SET lineage_json=? WHERE id=?',(json.dumps(data),job.id))
    _,_,actor=identity(d);d.app.state.admin.set_feature(actor,'feed',False)
    jobs.complete_job(job.id,job.lease_token,fixture_result(job.kind,d.clock()),d.clock())
    with d.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM market_results WHERE section=?',(job.kind,)).fetchone()[0]==0


def test_legacy_field_only_stored_lineage_is_withheld_by_tools(research,dashboard):
    import sqlite3
    from member_dashboard.assistant_tools import permitted
    jobs,users,registry,policy=research
    old=dict(source_lineage_json=json.dumps([s.model_dump() for s in registry.providers['options'].lineage.sources]),
        required_features_json='["analysis"]',field_dependencies_json='[{"field_path":"payload.summary","required_features":["options"]}]',retention_deadline=None)
    lineage=policy.stored_lineage(old)
    assert set(lineage.required_features)=={'analysis','options'}
    _,_,actor=identity(dashboard);dashboard.app.state.admin.set_feature(actor,'options',False)
    with jobs.store.transaction() as con: assert not permitted(jobs,con,lineage,[],dashboard.clock(),dashboard.clock()-100)


def test_parallel_admin_suspension_keeps_one_active_admin(dashboard):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from member_dashboard.admin import AdminError
    d=dashboard
    first=identity(d);second=identity(d);gate=Barrier(2)
    def suspend(pair):
        actor,target=pair;gate.wait(timeout=5)
        try: d.app.state.admin.suspend_member(actor[2],target[0]);return True
        except (AuthError,AdminError):return False
    with ThreadPoolExecutor(2) as pool: outcomes=list(pool.map(suspend,[(first,second),(second,first)]))
    assert sorted(outcomes)==[False,True]
    with d.store.transaction() as con: assert con.execute("SELECT count(*) FROM members WHERE role='admin' AND status='active'").fetchone()[0]==1


def test_reactivating_active_admin_cannot_revoke_own_session(dashboard):
    d=dashboard
    mid,s,p=identity(d);login(d,s)
    assert write(d,'members/'+mid+'/reactivate',s).status_code==204
    assert d.client.get('/api/v1/me').status_code==200


def test_supervisor_actual_tick_and_usage_unknown_partial(dashboard):
    from types import SimpleNamespace
    from member_dashboard.worker import WorkerSupervisor
    d=dashboard;_,_,actor=identity(d)
    child=SimpleNamespace(worker_id='fake-tree',is_dead=lambda:False)
    supervisor=WorkerSupervisor(d.store,lambda:child,lambda now:None,clock=d.clock)
    supervisor.tick()
    value=d.app.state.admin.health_snapshot(actor)
    assert value.supervisor.status=='responsive'
    assert value.compute.status=='unavailable'
    d.clock.advance(15)
    assert d.app.state.admin.health_snapshot(actor).supervisor.status=='stale'
    supervisor.tick()
    assert d.app.state.admin.health_snapshot(actor).supervisor.status=='responsive'

from test_feed import feed

@pytest.mark.parametrize('feature',['feed','setups'])
def test_admin_disabled_feed_direct_cursor_and_tool(feed,feature):
    import sqlite3
    from test_feed import publish,page
    from member_dashboard.assistant_tools import lookup_market,parse_tool
    d=feed.dashboard
    publish(feed,feature=feature)
    cursor=page(feed,feature=feature).json()['cursor']
    _,_,actor=identity(d)
    d.app.state.admin.set_feature(actor,feature,False)
    assert page(feed,feature=feature).status_code==403
    assert page(feed,cursor,feature=feature).status_code==403
    d.app.state.research.policy=feed.policy
    with d.store.transaction() as con:
        con.row_factory=sqlite3.Row
        result=lookup_market(d.app.state.research,con,feed.principal,parse_tool({'name':'lookup_market','arguments':{'ticker':'TEST'}}),d.clock())
        assert result.content['records']==[]
    d.app.state.admin.set_feature(actor,feature,True)
    assert page(feed,cursor,feature=feature).status_code==409


from test_assistant import assistant

@pytest.mark.asyncio
async def test_admin_disabled_assistant_hides_current_and_saved_answer(assistant,research,dashboard):
    from test_assistant import allow_model,prepare_answer,compute
    from member_dashboard.history import HistoryError
    allow_model(research)
    user,conversation,run=prepare_answer(assistant,research,dashboard)
    _,runtime=await compute(assistant,research,dashboard)
    try:
        assert assistant.get_run(user,conversation.id,run.id).status=='completed'
        _,_,actor=identity(dashboard)
        dashboard.app.state.admin.set_feature(actor,'assistant',False)
        for call in (lambda:assistant.get_run(user,conversation.id,run.id),lambda:assistant.history.get_conversation(user,conversation.id),
                     lambda:assistant.submit(user,conversation.id,'Cannot send','SPY')):
            with pytest.raises(HistoryError) as caught: call()
            assert caught.value.status==403
    finally: runtime.shutdown()


def test_audit_is_bounded_and_sanitizes_unrecognized_metadata(dashboard):
    d=dashboard;_,_,actor=identity(d)
    with d.store.transaction() as con:
        for i in range(102): d.app.state.auth._audit(con,'PRIVATE provider error','SECRET PATH',d.clock(),actor.member_id,{'token':'SECRET TOKEN'})
    first=d.app.state.admin.page(actor,'audit');second=d.app.state.admin.page(actor,'audit',first.next_cursor)
    assert len(first.items)==100 and second.items and not second.next_cursor
    assert len({r.id for r in first.items+second.items})==len(first.items+second.items)
    assert 'SECRET' not in first.model_dump_json()+second.model_dump_json()
    assert 'PRIVATE' not in first.model_dump_json()+second.model_dump_json()

@pytest.mark.asyncio
async def test_mixed_analysis_withdrawal_after_model_await_withholds_all_prose(dashboard):
    from dataclasses import replace
    from test_research_parity import prepared_case
    from test_sec_outcomes import member_context
    from consensus_engine.analysis.research_contracts import ResearchServices,GapFillResult
    from member_dashboard.research import MemberResearchProvider
    from member_dashboard.source_policy import SourcePermission
    _,record,settings,clock=prepared_case('bullish')
    record=replace(record,evidence=tuple(replace(row,source_id='synthetic',source_version='s1') for row in record.evidence))
    _,_,actor=identity(dashboard);calls=[]
    async def synthesis(request):
        calls.append('sent');dashboard.app.state.admin.set_feature(actor,'options',False);return 'dependent model narrative'
    async def gap(request): return GapFillResult()
    context=member_context(dashboard,{},analysis_records={'NVDA':record},analysis_services=ResearchServices(settings,clock,synthesis,gap,lambda event:None),
        input_dependencies={'analysis_records':['analysis'],'analysis_services':['analysis','options']})
    context.policy.record(SourcePermission(source_id='synthetic',product_id='fixture',provider='fixture',policy_version='p2',
        audience='invited_members',status='allowed',display_raw=True,display_derived=True,retain=True,model_input=True,
        private_grant_ref='fixture',evidence_ref='fixture',terms_url='https://www.sec.gov/fixture',effective_at=0.0))
    with_lineage={key:line.model_copy(update={'sources':[s.model_copy(update={'policy_version':'p2'}) for s in line.sources]}) for key,line in context.lineage.items()}
    provider=MemberResearchProvider(replace(context,lineage=with_lineage))
    result=await provider.compute('NVDA','analysis',{'enabled_features':['analysis','options']})
    assert calls==['sent']
    assert result.status=='unavailable' and result.payload is None and result.evidence==[]


def test_supplied_metric_features_union_and_withhold_section(dashboard):
    from types import SimpleNamespace
    from test_sec_outcomes import member_context,synthetic_chain
    from consensus_engine.analysis.research_contracts import DerivedContextMetric
    from member_dashboard.research import MemberResearchProvider
    row=DerivedContextMetric('iv_skew',0.2,'IV fraction','synthetic method',None,'synthetic','s1')
    client=SimpleNamespace(get_option_chain=lambda *a,**k:pytest.fail('Disabled input touched provider'))
    provider=MemberResearchProvider(member_context(dashboard,{'synthetic':client},supplied_metrics={'em_daily':(row,)},
        input_dependencies={'supplied_metrics.em_daily.0':['options']}))
    assert set(provider.context.lineage['em_daily'].required_features)=={'em_daily','options'}
    _,_,actor=identity(dashboard);dashboard.app.state.admin.set_feature(actor,'options',False)
    assert provider.compute_blocking('SPY','em_daily',{}).status=='unavailable'

@pytest.mark.asyncio
async def test_disable_after_claim_never_invokes_registered_provider(research,dashboard):
    from dataclasses import replace
    from member_dashboard.providers import ComputeInputs,ProviderWait
    from member_dashboard.provider_runtime import ProviderRuntime
    jobs,users,registry,_=research;calls=[]
    registry.providers['analysis']=replace(registry.providers['analysis'],operation=lambda *a:calls.append('wire') or fixture_result('analysis',dashboard.clock()))
    jobs.request_research(users[0],'SPY',False,dashboard.clock());job=jobs.claim_job('worker',dashboard.clock())
    _,_,actor=identity(dashboard);dashboard.app.state.admin.set_feature(actor,'analysis',False)
    runtime=ProviderRuntime(dashboard.store,'worker',clock=dashboard.clock)
    try:
        try: await registry.compute(job.ticker,job.kind,ComputeInputs(runtime,job.call_id,1,dashboard.clock(),job.inputs))
        except (ValueError,ProviderWait): pass
        assert calls==[]
    finally: runtime.shutdown()


def test_usage_counts_only_runs_with_both_actual_token_values(assistant,research,dashboard):
    runs=[]
    for user in research[1][:2]:
        conversation=assistant.create_conversation(user,'Synthetic')
        runs.append(assistant.submit(user,conversation.id,'No model access',None))
    with dashboard.store.transaction() as con:
        con.execute('UPDATE assistant_runs SET actual_input_tokens=5 WHERE id=?',(runs[0].id,))
        con.execute('UPDATE assistant_runs SET actual_output_tokens=7 WHERE id=?',(runs[1].id,))
    _,_,actor=identity(dashboard)
    usage=dashboard.app.state.admin.health_snapshot(actor).usage
    assert usage.known_usage_runs==0 and usage.input_tokens is None and usage.output_tokens is None and usage.cost is None


def test_review_fixed_admin_route_contract(dashboard):
    d=dashboard
    _,member_session,_=identity(d,'member');login(d,member_session)
    assert d.client.get('/api/v1/admin/features').status_code==403
    _,session,_=identity(d);login(d,session)
    response=d.client.get('/api/v1/admin/features')
    assert response.status_code==200
    assert {r['name'] for r in response.json()}==set(get_args(Feature))
    assert all(set(r)=={'name','enabled','version'} for r in response.json())
    assert write(d,'features/feed',session,{'enabled':False}).status_code==200
    assert next(r for r in d.client.get('/api/v1/admin/features').json() if r['name']=='feed')=={'name':'feed','enabled':False,'version':2}
    invite=write(d,'invites',session).json()
    assert d.client.delete('/api/v1/admin/invites/'+invite['id']).status_code==403
    assert write(d,'invites/'+invite['id'],session).status_code==204
    assert d.client.post('/api/v1/admin/features/feed',json={'enabled':True}).status_code==405
    assert d.client.post('/api/v1/admin/invites/'+invite['id']+'/revoke').status_code==404


@pytest.mark.asyncio
@pytest.mark.parametrize('feature',['feed','setups','assistant'])
async def test_review_analysis_carries_enabled_nonsection_dependency(dashboard,feature):
    from dataclasses import replace
    from test_research_parity import prepared_case
    from test_sec_outcomes import member_context
    from consensus_engine.analysis.research_contracts import ResearchServices,GapFillResult
    from member_dashboard.research import MemberResearchProvider
    from member_dashboard.providers import ProviderRegistry,SymbolCatalog,ComputeInputs,ProviderWait
    from member_dashboard.jobs import JobService
    from member_dashboard.provider_runtime import ProviderRuntime
    _,record,settings,clock=prepared_case('sparse_levels')
    record=replace(record,evidence=tuple(replace(row,source_id='synthetic',source_version='s1') for row in record.evidence))
    async def synthesis(request):return ''
    async def gap(request):return GapFillResult()
    context=member_context(dashboard,{},analysis_records={'NVDA':record},analysis_services=ResearchServices(settings,clock,synthesis,gap,lambda event:None),
        input_dependencies={'analysis_records':['analysis',feature],'analysis_services':['analysis']})
    provider=MemberResearchProvider(context);registry=ProviderRegistry(SymbolCatalog({'NVDA':'equity'}));provider.register(registry)
    jobs=JobService(dashboard.store,dashboard.app.state.auth,context.policy,registry)
    _,_,actor=identity(dashboard)
    request=jobs.request_research(actor,'NVDA',False,dashboard.clock())
    job=jobs.claim_job('worker',dashboard.clock())
    assert job.kind=='analysis' and feature in job.inputs['enabled_features']
    runtime=ProviderRuntime(dashboard.store,'worker',clock=dashboard.clock)
    try:
        result=await registry.compute(job.ticker,job.kind,ComputeInputs(runtime,job.call_id,2,dashboard.clock(),job.inputs))
        assert result.status=='completed' and result.payload is not None
        dashboard.app.state.admin.set_feature(actor,feature,False)
        assert (await provider.compute('NVDA','analysis',job.inputs)).status=='unavailable'
        with dashboard.store.transaction() as con: assert jobs._prepare(con,'NVDA','analysis',dashboard.clock()) is None
        dashboard.app.state.admin.set_feature(actor,feature,True)
        jobs.complete_job(job.id,job.lease_token,result,dashboard.clock())
        assert jobs.get_request(actor,request.id,dashboard.clock()).sections['analysis'].payload is None
    finally: runtime.shutdown()
