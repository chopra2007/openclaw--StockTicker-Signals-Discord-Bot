"""Focused fixed-role composition and maintenance regressions."""
import os
from pathlib import Path
import pytest


def test_fixed_role_config_cannot_smuggle_api_compute_privileges(tmp_path):
    from member_dashboard.operations import validate_config
    base={'role':'api','uid':123,'web_path':str(tmp_path/'web'),'origin':'https://dashboard.test',
          'signing_key':str(tmp_path/'signing'),'authority_socket':str(tmp_path/'authority.sock'),'authority_uid':124}
    assert validate_config(base)['role']=='api'
    for extra in ({'market_path':'/private/source'},{'command':['sh']},{'verified':True}):
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
        'origin':'https://dashboard.test','authority_socket':str(tmp_path/'rpc'),'authority_uid':124})
    assert app.state.source_policy.authority_current() is False
    assert app.state.providers is None
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


@pytest.mark.parametrize('with_call',[False,True])
def test_restart_carries_broker_tombstone_into_web_after_crash(research,dashboard,tmp_path,with_call):
    from member_dashboard.operations import recover_worker_state
    from member_dashboard.exit_control import ExitRegistry
    from member_dashboard.quota_broker import QuotaBroker
    from member_dashboard.store import WebStore
    from member_dashboard.compute_launcher import CgroupLauncher
    from member_dashboard.worker import WorkerSupervisor
    from uuid import uuid4
    service,users,_,_=research;worker=str(uuid4());now=dashboard.clock()
    service.request_research(users[0],'SPY',False,now)
    job=service.claim_job(worker,now)
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
    launcher=CgroupLauncher.__new__(CgroupLauncher);launcher.root=root;launcher.control=Control()
    # Abrupt crash: no worker_exits row. Then crash again after independent broker
    # settlement but before any web commit. Fresh launcher must rediscover tombstone.
    assert launcher.recover()==[worker]
    with dashboard.store.transaction() as con:
        assert con.execute('SELECT count(*) FROM worker_exits').fetchone()[0]==0
    restarted=CgroupLauncher.__new__(CgroupLauncher);restarted.root=root;restarted.control=Control()
    assert recover_worker_state(restarted,dashboard.store,now)
    with dashboard.store.transaction() as con:
        assert con.execute('SELECT reconciled FROM worker_exits WHERE worker_id=?',(worker,)).fetchone()[0]==1
        assert con.execute('SELECT status FROM web_jobs WHERE id=?',(job.id,)).fetchone()[0]=='queued'
        if with_call: assert con.execute('SELECT status FROM provider_calls').fetchone()[0]=='failed'
    spawned=[]
    supervisor=WorkerSupervisor(dashboard.store,lambda:spawned.append(True),lambda _:None,clock=dashboard.clock)
    supervisor.tick()
    assert spawned==[True]
