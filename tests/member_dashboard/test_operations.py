"""Focused fixed-role composition and maintenance regressions."""
import os
from pathlib import Path
import pytest


def test_fixed_role_config_cannot_smuggle_api_compute_privileges(tmp_path):
    from member_dashboard.operations import validate_config
    base={'role':'api','uid':123,'web_path':str(tmp_path/'web'),'origin':'https://dashboard.test',
          'signing_key':str(tmp_path/'signing'),'authority_socket':str(tmp_path/'authority.sock'),'authority_uid':124,
          'assistant_key_sha256':'a'*64,'assistant_verified_until':2e9}
    assert validate_config(base)['role']=='api'
    for extra in ({'market_path':'/private/source'},{'command':['sh']},{'verified':True},{'assistant_key':'/etc/key'},
                  {'assistant_key_sha256':'sk-or-plain-key'},{'assistant_verified_until':True}):
        with pytest.raises(ValueError): validate_config({**base,**extra})


def test_denial_authority_rpc_has_no_grant_or_untrusted_mutation(tmp_path):
    from member_dashboard.authority_rpc import AuthorityService
    from member_dashboard.authority import DenialJournal,CheckpointStore
    root=tmp_path/'journal';root.mkdir(mode=0o700)
    journal=DenialJournal.create(root/'journal',root/'anchor',checkpoint=CheckpointStore.create(tmp_path/'checkpoint'))
    service=AuthorityService(journal,read_uids=[123,124],write_uids=[123])
    for uid,request in ((124,{'method':'append','kind':'feature_disabled','key':'options'}),
                        (123,{'method':'grant','verified':True}),
                        (999,{'method':'current','offset':0})):
        with pytest.raises(ValueError): service.dispatch(request,peer_uid=uid)
    assert service.dispatch({'method':'append','kind':'feature_disabled','key':'options'},peer_uid=123)=={'revision':1}
    assert service.dispatch({'method':'current','offset':0},peer_uid=124)['rows'][0][1]=='feature_disabled'


def test_archive_maintenance_authenticates_expiry_before_deletion(tmp_path,monkeypatch):
    from member_dashboard.backup import maintain_archives,_crypt
    node=Path(__file__).resolve().parents[2]/'.superpowers/sdd/2026-10-05-member-dashboard/node-v24.21.0-win-x64/node.exe'
    if not node.exists(): pytest.skip('Node archive proof runs on Windows control host')
    import time
    key=tmp_path/'key';key.write_bytes(os.urandom(32));key.chmod(0o600)
    archive=tmp_path/'one.mdb';deadline=int(time.time())+10
    archive.write_bytes(_crypt('seal',deadline.to_bytes(8,'big')+b'synthetic',key,node));archive.chmod(0o600)
    assert maintain_archives(tmp_path,key_path=key,node=node,now=deadline-1)==0
    bad=bytearray(archive.read_bytes());bad[-1]^=1;archive.write_bytes(bad)
    with pytest.raises(ValueError): maintain_archives(tmp_path,key_path=key,node=node,now=deadline+1)
    assert archive.exists()
    archive.write_bytes(_crypt('seal',deadline.to_bytes(8,'big')+b'synthetic',key,node))
    assert maintain_archives(tmp_path,key_path=key,node=node,now=deadline+1)==1
    assert not archive.exists()


def test_feed_transaction_applies_committed_feature_denial(dashboard,tmp_path):
    from member_dashboard.authority import DenialJournal,CheckpointStore
    import time
    root=tmp_path/'journal';root.mkdir(mode=0o700)
    journal=DenialJournal.create(root/'journal',root/'anchor',checkpoint=CheckpointStore.create(tmp_path/'checkpoint'))
    dashboard.store.bind_authority(journal)
    journal.append('feature_disabled','feed')
    from member_dashboard.publication import FeedService
    feed=FeedService(dashboard.store,dashboard.app.state.auth,dashboard.app.state.source_policy,signing_key=b'x'*32)
    with feed._transaction(time.monotonic()+30) as con:
        assert con.execute("SELECT enabled FROM features WHERE name='feed'").fetchone()[0]==0


def test_api_role_constructs_no_market_reader_or_compute(tmp_path,monkeypatch):
    from member_dashboard.operations import api_app
    def forbidden(*args,**kwargs): pytest.fail('API constructed a market reader or child launcher')
    monkeypatch.setattr('member_dashboard.market_reader.MarketReader',forbidden)
    monkeypatch.setattr('member_dashboard.compute_launcher.CgroupLauncher',forbidden)
    key=tmp_path/'key';key.write_bytes(b'x'*32);key.chmod(0o600)
    app=api_app({'web_path':str(tmp_path/'web'),'signing_key':str(key),
        'origin':'https://dashboard.test','authority_socket':str(tmp_path/'rpc'),'authority_uid':124,
        'assistant_key_sha256':'a'*64,'assistant_verified_until':2e9})
    assert app.state.source_policy.authority_current() is False
    transport=app.state.assistant.transport
    assert transport.available(1e9) and not hasattr(transport,'credential') and not hasattr(transport,'client')
    assert set(app.state.providers.providers)=={'sec','options','em_daily','em_weekly','analysis'}
    assert not hasattr(app.state,'synthetic_supervisor')


def test_checkpoint_cannot_hide_inside_journal_snapshot(tmp_path):
    from member_dashboard.authority import DenialJournal,CheckpointStore
    root=tmp_path/'journal';root.mkdir(mode=0o700)
    nested=root/'nested';nested.mkdir(mode=0o700)
    checkpoint=CheckpointStore.create(nested/'checkpoint')
    with pytest.raises(ValueError,match='outside_journal'):
        DenialJournal.create(root/'journal',root/'anchor',checkpoint=checkpoint)


def test_renew_waits_for_complete_denial_publication(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from member_dashboard.authority import DenialJournal,CheckpointStore
    root=tmp_path/'journal';root.mkdir(mode=0o700)
    journal=DenialJournal.create(root/'journal',root/'anchor',checkpoint=CheckpointStore.create(tmp_path/'checkpoint'))
    # Separate object matches the updater/RPC concurrency and shares no Python lock.
    updater=DenialJournal(root/'journal',root/'anchor',checkpoint=CheckpointStore(tmp_path/'checkpoint'))
    entered=threading.Event();release=threading.Event();renew_entered=threading.Event()
    original=journal.checkpoint.advance
    def paused(*args):
        entered.set();assert release.wait(5);return original(*args)
    monkeypatch.setattr(journal.checkpoint,'advance',paused)
    def renew(): renew_entered.set();return updater.renew()
    with ThreadPoolExecutor(max_workers=2) as pool:
        append=pool.submit(journal.append,'feature_disabled','options')
        if not entered.wait(5): append.result(timeout=1);pytest.fail('append did not reach checkpoint')
        renewal=pool.submit(renew);assert renew_entered.wait(5)
        try:
            import time
            time.sleep(.2)
            assert not renewal.done(), 'renew observed the intentional multi-file update gap'
        finally: release.set()
        assert append.result(timeout=5)==1
        renewal.result(timeout=5)
    assert updater.current()[0][1]=='feature_disabled'


from test_jobs import research


def test_synthetic_auth_boundary_preserves_per_test_address_limit(tmp_path):
    from member_dashboard.synthetic import create_synthetic
    from member_dashboard.auth import AuthError
    from fastapi.testclient import TestClient
    import time
    app=create_synthetic(tmp_path)
    with TestClient(app) as client:
        for _ in range(2):
            for index in range(50): app.state.auth._reserve_login(str(index),'synthetic-address',time.time())
            with pytest.raises(AuthError): app.state.auth.reserve_public_write('synthetic-address',time.time())
            assert client.post('/__fixture/control',json={'action':'auth_test_boundary'}).status_code==200
        with app.state.store.transaction() as con:
            assert con.execute('SELECT count(*) FROM auth_attempts').fetchone()[0]==0


@pytest.mark.parametrize('attempts,current_rights',[(1,True),(3,True),(3,False)])
def test_live_supervisor_terminal_recovery_uses_current_authorization(research,dashboard,attempts,current_rights):
    from member_dashboard.worker import WorkerSupervisor
    from test_jobs import fixture_result
    import json
    service,users,_,_=research;now=dashboard.clock()
    request=service.request_research(users[0],'SPY',False,now)
    prior=service.claim_job('completed-worker',now)
    service.complete_job(prior.id,prior.lease_token,fixture_result(prior.kind,now),now)
    job=service.claim_job('dead-worker',now)
    with dashboard.store.transaction() as con:
        con.execute('UPDATE web_jobs SET attempts=? WHERE id=?',(attempts,job.id))
        before=con.execute('SELECT current_version_id FROM report_owners WHERE report_id=?',(request.report_id,)).fetchone()[0]
    service.policy.authority_current=lambda:current_rights
    class Dead:
        worker_id='dead-worker'
        def is_dead(self): return True
        def close(self): pass
    spawned=[]
    supervisor=WorkerSupervisor(dashboard.store,lambda:spawned.append(True),lambda _:None,
        jobs=service,clock=dashboard.clock,reconcile=lambda _:True)
    supervisor.child=Dead();supervisor.tick()
    assert spawned==[True]
    with dashboard.store.transaction() as con:
        assert con.execute('SELECT status FROM web_jobs WHERE id=?',(job.id,)).fetchone()[0]==('queued' if attempts==1 else 'failed')
        row=con.execute('SELECT v.id,v.content_json FROM report_versions v JOIN report_owners o ON o.current_version_id=v.id WHERE o.report_id=?',(request.report_id,)).fetchone()
        if attempts==3 and current_rights:
            snapshot=json.loads(row[1]);assert snapshot[job.kind]['status']=='failed'
            assert snapshot[prior.kind]['status']=='completed'
        if not current_rights: assert row[0]==before


def test_exit_control_decoder_failure_does_not_stop_later_connections(monkeypatch):
    from member_dashboard import exit_control
    from types import SimpleNamespace
    import struct,threading
    stopping=threading.Event();responses=[]
    monkeypatch.setattr(exit_control.socket,'SO_PEERCRED',17,raising=False)
    class Connection:
        def __enter__(self): return self
        def __exit__(self,*_): pass
        def settimeout(self,_): pass
        def getsockopt(self,*_): return struct.pack('3i',10,123,456)
    connections=iter([Connection(),Connection()])
    def accept():
        connection=next(connections)
        if responses: stopping.set()
        return connection,None
    calls=iter([RecursionError('synthetic decoder recursion limit'),{'method':'recovery'}])
    def receive(_):
        value=next(calls)
        if isinstance(value,Exception): raise value
        return value
    monkeypatch.setattr(exit_control,'receive_frame',receive)
    monkeypatch.setattr(exit_control,'send_frame',lambda _,value:responses.append(value))
    server=exit_control.ExitControlServer.__new__(exit_control.ExitControlServer)
    server.stopping=stopping;server.socket=SimpleNamespace(accept=accept)
    server.registry=SimpleNamespace(dispatch=lambda request,peer_uid:{'workers':[]})
    server._serve()
    assert responses==[{'ok':False},{'workers':[]}]


@pytest.mark.parametrize('with_call,attempts,current_rights',[
    (False,1,True),(True,1,True),(False,3,True),(True,3,True),(False,3,False)])
def test_restart_carries_broker_tombstone_into_web_after_crash(research,dashboard,tmp_path,with_call,attempts,current_rights):
    from member_dashboard.operations import recover_worker_state
    from member_dashboard.exit_control import ExitRegistry
    from member_dashboard.quota_broker import QuotaBroker
    from member_dashboard.store import WebStore
    from member_dashboard.compute_launcher import CgroupLauncher
    from member_dashboard.worker import WorkerSupervisor
    from uuid import uuid4
    service,users,_,_=research;worker=str(uuid4());now=dashboard.clock()
    request=service.request_research(users[0],'SPY',False,now)
    completed_kind=None
    if attempts==3:
        from test_jobs import fixture_result
        prior=service.claim_job('completed-worker',now)
        service.complete_job(prior.id,prior.lease_token,fixture_result(prior.kind,now),now)
        completed_kind=prior.kind
    job=service.claim_job(worker,now)
    with dashboard.store.transaction() as con:
        con.execute('UPDATE web_jobs SET attempts=? WHERE id=?',(attempts,job.id))
        version_before=con.execute('SELECT current_version_id FROM report_owners WHERE report_id=?',(request.report_id,)).fetchone()[0]
    service.policy.authority_current=lambda:current_rights
    if with_call:
        with dashboard.store.transaction() as con:
            con.execute("INSERT INTO provider_calls(call_id,worker_id,provider,status,started_at) VALUES (?,?,?,'running',?)",(job.call_id,worker,'synthetic',now))
    quota=WebStore(tmp_path/'quota.sqlite3');quota.migrate()
    registry=ExitRegistry(QuotaBroker(quota),supervisor_uid=123,compute_uid=456,cgroup_root=Path('/sys/fs/cgroup/synthetic'))
    with quota.transaction() as con:
        con.execute('INSERT INTO trusted_workers VALUES (?,?,?,?,?,?)',(worker,'synthetic-owner','/sys/fs/cgroup/synthetic/'+worker,1,now,'registered'))
    registry._tree_dead=lambda _:True  # Kernel proof is exercised separately on Linux.
    root=tmp_path/'groups';root.mkdir();(root/worker).mkdir();(root/worker/'cgroup.kill').touch()
    class Control:
        def call(self,method): return registry.dispatch({'method':method},peer_uid=123)
        def reconcile(self,key): return registry.reconcile(key)
        def forget(self,key): return registry.dispatch({'method':'forget','worker':key},peer_uid=123)['ok']
    launcher=CgroupLauncher.__new__(CgroupLauncher);launcher.root=root;launcher.control=Control()
    # Abrupt crash: no worker_exits row. Then crash again after independent broker
    # settlement but before any web commit. Fresh launcher must rediscover tombstone.
    assert launcher.recover()==[worker]
    with dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM worker_exits').fetchone()[0]==0
    restarted=CgroupLauncher.__new__(CgroupLauncher);restarted.root=root;restarted.control=Control()
    assert recover_worker_state(restarted,service,now)
    with dashboard.store.transaction() as con:
        assert con.execute('SELECT reconciled FROM worker_exits WHERE worker_id=?',(worker,)).fetchone()[0]==1
        assert con.execute('SELECT status FROM web_jobs WHERE id=?',(job.id,)).fetchone()[0]==('queued' if attempts==1 else 'failed')
        if with_call: assert con.execute('SELECT status FROM provider_calls').fetchone()[0]=='failed'
        if attempts==3 and current_rights:
            import json
            row=con.execute('SELECT v.content_json FROM report_versions v JOIN report_owners o ON o.current_version_id=v.id WHERE o.report_id=?',(request.report_id,)).fetchone()
            snapshot=json.loads(row[0])
            assert snapshot[job.kind]['status']=='failed'
            assert snapshot[completed_kind]['status']=='completed'
        if not current_rights:
            assert con.execute('SELECT current_version_id FROM report_owners WHERE report_id=?',(request.report_id,)).fetchone()[0]==version_before
    if not current_rights:
        assert service.get_request(users[0],request.id,now).sections[completed_kind].status=='unavailable'
    assert recover_worker_state(restarted,service,now)  # Repeat after the web commit too.
    spawned=[]
    supervisor=WorkerSupervisor(dashboard.store,lambda:spawned.append(True),lambda _:None,jobs=dashboard.app.state.research,clock=dashboard.clock)
    supervisor.tick()
    assert spawned==[True]


def test_quota_role_assistant_cap_survives_restart_and_limit_change(tmp_path):
    from member_dashboard.store import WebStore
    from member_dashboard.quota_broker import QuotaBroker,Identity
    from member_dashboard.operations import ensure_assistant_policy,ASSISTANT_REQUEST_SCOPE,ASSISTANT_COST_SCOPE
    from member_dashboard.assistant_transport import QUOTA_ENDPOINT
    now=[1000.0]
    store=WebStore(tmp_path/'quota.sqlite3');store.migrate()
    broker=QuotaBroker(store,clock=lambda:now[0])
    ensure_assistant_policy(broker,3,now[0])
    who=Identity('dashboard','worker')
    def spend(attempt,usd):
        return broker.reserve([ASSISTANT_REQUEST_SCOPE,ASSISTANT_COST_SCOPE],who,QUOTA_ENDPOINT,
                              {ASSISTANT_REQUEST_SCOPE:1,ASSISTANT_COST_SCOPE:usd},attempt).allowed
    assert spend('a',2.0) and not spend('b',1.5) and spend('c',0.9)
    # Restart inside the window (startup forces verified=0 first) keeps the spend history.
    with store.transaction() as con: con.execute('UPDATE provider_quota_policy SET verified=0')
    now[0]+=60;ensure_assistant_policy(broker,3,now[0])
    assert not spend('d',0.2)
    now[0]+=60;ensure_assistant_policy(broker,5,now[0])
    assert spend('e',1.9) and not spend('f',0.3)
    now[0]+=86400;assert spend('g',4.0)


def test_bot_feed_rows_publish_only_with_owner_permission_and_live_authority(dashboard):
    import time
    from member_dashboard.operations import bot_feed_lineage,owner_permissions,BOT_PRODUCT
    from member_dashboard.market_reader import SourceName,SourceRecord,MarketPayload
    from member_dashboard.publication import publishable
    policy=dashboard.app.state.source_policy
    now=time.time()
    row=SourceRecord(SourceName.ANALYST,'post-1','NVDA','v1',now-60,None,None,'bullish','Analyst says up.',
        MarketPayload(ticker='NVDA',direction='bullish',excerpt='Analyst says up.'))
    lineage=bot_feed_lineage(row)
    assert lineage.required_features==['feed'] and lineage.sources[0].product_id==BOT_PRODUCT
    assert bot_feed_lineage(SourceRecord(SourceName.ALERT,'1','NVDA','v1',now,None,None,'bullish','x',
        MarketPayload(ticker='NVDA',direction='bullish',excerpt='x'))).required_features==['setups']
    assert bot_feed_lineage(SourceRecord(SourceName.TICKER,'7','NVDA','v1',now,None,None,'bullish','x',
        MarketPayload(ticker='NVDA',direction='bullish',excerpt='x'))) is None  # Raw mentions never publish.
    policy.authority_current=lambda:True
    assert not policy.authorize_lineage(lineage,'display_raw',now).allowed
    for permission in owner_permissions([lineage.sources[0].source_id],BOT_PRODUCT,'openclaw-bot','https://docs.x.com/developer-terms',now-1):
        policy.record(permission)
    assert all(policy.authorize_lineage(lineage,use,now).allowed for use in ('display_raw','display_derived','retain','model_input'))
    policy.authority_current=lambda:False
    assert not policy.authorize_lineage(lineage,'display_raw',now).allowed
    from dataclasses import replace
    publication=publishable(replace(row,lineage=lineage))
    assert publication.required_feature=='feed'
    # The assistant only uses evidence whose (source, version) the lineage tracks.
    tracked={(s.source_id,s.source_version) for s in lineage.sources}
    assert all((e.source_id,e.source_version) in tracked for e in publication.evidence)


def test_service_restart_removed_cgroup_settles_and_prunes_tombstones(tmp_path):
    """systemd deletes the service cgroup on stop; recovery must not block forever."""
    import os
    from uuid import uuid4
    from member_dashboard.exit_control import ExitRegistry
    from member_dashboard.quota_broker import QuotaBroker,process_identity
    from member_dashboard.store import WebStore
    from member_dashboard.compute_launcher import CgroupLauncher
    quota=WebStore(tmp_path/'quota.sqlite3');quota.migrate()
    registry=ExitRegistry(QuotaBroker(quota),supervisor_uid=123,compute_uid=456,cgroup_root=Path('/sys/fs/cgroup/synthetic'))
    gone,alive=str(uuid4()),str(uuid4())
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    with quota.transaction() as con:
        con.execute('INSERT INTO trusted_workers VALUES (?,?,?,?,?,?)',(gone,boot+':999999999:1',str(tmp_path/'groups'/gone),1,1.0,'registered'))
        con.execute('INSERT INTO trusted_workers VALUES (?,?,?,?,?,?)',(alive,process_identity(os.getpid()),str(tmp_path/'groups'/alive),1,2.0,'registered'))
    assert registry.reconcile(gone) and not registry.reconcile(alive)
    root=tmp_path/'groups';root.mkdir()
    class Control:
        def call(self,method): return registry.dispatch({'method':method},peer_uid=123)
        def reconcile(self,key): return registry.reconcile(key)
        def forget(self,key): return registry.dispatch({'method':'forget','worker':key},peer_uid=123)['ok']
    launcher=CgroupLauncher.__new__(CgroupLauncher);launcher.root=root;launcher.control=Control()
    assert launcher.recover() is None  # A live owner still blocks replacement.
    assert not Control().forget(alive) and Control().forget(gone)
    with quota.transaction() as con:
        assert [r[0] for r in con.execute('SELECT worker FROM trusted_workers')]==[alive]
    with pytest.raises(ValueError): registry.dispatch({'method':'forget','worker':alive},peer_uid=456)


def test_authority_restart_after_downtime_resumes_only_an_intact_chain(tmp_path):
    from member_dashboard.authority import DenialJournal,CheckpointStore
    clock=[1000.0]
    root=tmp_path/'journal';root.mkdir(mode=0o700)
    checkpoint=CheckpointStore.create(tmp_path/'checkpoint')
    journal=DenialJournal.create(root/'journal',root/'anchor',checkpoint=checkpoint,clock=lambda:clock[0])
    journal.append('feature_disabled','options')
    clock[0]+=3600  # Server was down for an hour.
    with pytest.raises(ValueError): journal.current()
    with pytest.raises(ValueError): journal.renew()
    journal.restart_renew()
    assert journal.current()[0][1]=='feature_disabled'
    # A rolled-back journal (older copy) still cannot resume.
    head=(1,journal.current()[0][4])
    clock[0]+=3600
    checkpoint.advance(head,'f'*64)
    with pytest.raises(ValueError): journal.restart_renew()


def test_symbol_catalog_reads_provisioned_list_and_fails_closed(tmp_path):
    from member_dashboard.operations import symbol_catalog
    from member_dashboard.providers import SymbolError
    path=tmp_path/'symbols.json';path.write_text('{"NVDA":"equity","BRK.B":"equity","QQQ":"fund"}')
    catalog=symbol_catalog(path)
    assert catalog.lookup('nvda')=='NVDA' and catalog.lookup('BRK-B')=='BRK.B'
    with pytest.raises(SymbolError): catalog.lookup('ZZZZ')
    with pytest.raises(SymbolError): symbol_catalog(tmp_path/'missing.json').lookup('NVDA')


async def test_api_and_compute_research_specs_match_exactly(dashboard,tmp_path):
    from member_dashboard.operations import register_research_specs,research_registry
    from member_dashboard.providers import ProviderRegistry
    api=register_research_specs(ProviderRegistry())
    config={'budget_socket':str(tmp_path/'none.sock'),'schwab_credentials':str(tmp_path/'none.json'),'schwab_state':str(tmp_path),
            'analysis_settings':str(tmp_path/'none-settings.json'),'assistant_key':str(tmp_path/'none.key')}
    compute=await research_registry(ProviderRegistry(),dashboard.store,dashboard.app.state.source_policy,object(),config)
    try:
        assert set(api.providers)==set(compute.providers)=={'sec','options','em_daily','em_weekly','analysis'}
        for section in api.providers:
            assert api.providers[section].descriptor()==compute.providers[section].descriptor()
    finally:
        await next(iter(compute.providers.values())).operation.__self__.context.sec_context.client.close()
