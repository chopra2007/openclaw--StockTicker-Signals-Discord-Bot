"""Launch gates are evidence gates, never self-attested production approval."""
import json
import os
from pathlib import Path
import sqlite3
import pytest

from member_dashboard.launch import evaluate, validate_staging, private_output, backup_web, restore_closed


@pytest.fixture(autouse=True)
def private_test_directory(tmp_path):
    from member_dashboard.launch import secure_directory
    secure_directory(tmp_path)


def test_launch_rejects_stale_feed_and_low_disk():
    report = evaluate(feed_p95_seconds=31, disk_free_gib=2.5, bot_latency_regression_pct=0)
    assert not report['ready']
    assert set(report['failures']) >= {'feed_latency', 'disk_headroom'}


def test_launch_missing_measurements_are_not_success():
    report = evaluate()
    assert not report['ready']
    assert set(report['failures']) >= {'feed_latency', 'cached_read_latency', 'capacity', 'source_rights', 'owner_approval'}


@pytest.mark.parametrize('origin', ['http://localhost:3443','https://example.com','https://127.0.0.1:3443','https://localhost:3443/a','https://user@localhost:3443'])
def test_load_rejects_unsupported_origin(origin):
    with pytest.raises(ValueError): validate_staging(origin, {})


def test_load_rejects_production_marker_and_missing_tls():
    with pytest.raises(ValueError): validate_staging('https://localhost:3443', {'mode':'production'})
    with pytest.raises(ValueError): validate_staging('https://localhost:3443', {'mode':'synthetic-staging','origin':'https://localhost:3443'})


def test_private_output_refuses_existing_symlink_and_escape(tmp_path):
    root=tmp_path/'private';root.mkdir(mode=0o700)
    with pytest.raises(ValueError): private_output(root, tmp_path/'outside.json', {})
    target=root/'report.json';private_output(root,target,{'ready':False})
    with pytest.raises((ValueError,FileExistsError)): private_output(root,target,{})
    assert json.loads(target.read_text()) == {'ready':False}


def test_backup_live_wal_and_restore_never_authorizes_old_state(tmp_path):
    from member_dashboard.store import WebStore
    root=tmp_path/'private';root.mkdir(mode=0o700)
    live=root/'web.sqlite3';store=WebStore(live);store.migrate()
    # Keep a WAL connection open so a naive main-file copy would miss this.
    writer=sqlite3.connect(live)
    writer.execute("UPDATE features SET enabled=0 WHERE name='options'");writer.commit()
    snapshot=root/'snapshot.sqlite3';backup_web(live,snapshot,root,quota_path=root/'quota.sqlite3')
    restored=root/'restored.sqlite3';restore_closed(snapshot,restored,root,quota_path=root/'quota.sqlite3')
    with sqlite3.connect(restored) as con:
        assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert con.execute('SELECT sum(enabled) FROM features').fetchone()[0]==0
        assert con.execute('SELECT retraction_authority_required FROM feed_state').fetchone()[0]==1
    writer.close()
    if os.name=='posix': assert restored.stat().st_mode & 0o077 == 0


def test_backup_rejects_quota_or_shared_destination(tmp_path):
    root=tmp_path.resolve()
    with pytest.raises(ValueError): backup_web(root/'quota.sqlite3',root/'copy',root,quota_path=root/'quota.sqlite3')
    with pytest.raises(ValueError): backup_web(root/'web.sqlite3',root/'web.sqlite3',root,quota_path=root/'quota.sqlite3')


def test_supervisor_reconciles_empty_web_ledger_and_retries_bounded(dashboard):
    from member_dashboard.worker import WorkerSupervisor
    class Dead:
        worker_id='dead-child'
        def is_dead(self): return True
        def close(self): pass
    calls=[];feeds=[];spawned=[]
    def reconcile(worker):
        calls.append(worker)
        return len(calls)>=3
    supervisor=WorkerSupervisor(dashboard.store,lambda:spawned.append(True),feeds.append,
        jobs=dashboard.app.state.research,clock=dashboard.clock,reconcile=reconcile)
    supervisor.child=Dead()
    supervisor.tick()
    assert calls==['dead-child'] and not spawned and supervisor.blocked
    dashboard.clock.advance(5);supervisor.tick()
    assert len(calls)==2 and len(feeds)==2 and not spawned
    dashboard.clock.advance(5);supervisor.tick()
    assert len(calls)==3 and len(spawned)==1 and not supervisor.blocked


def test_frontend_observation_never_infers_success_from_api():
    from member_dashboard.runtime import FrontendObservation
    observation=FrontendObservation()
    assert observation.snapshot(100).status=='unavailable'
    observation.observed_at=100
    assert observation.snapshot(101).status=='responsive'
    assert observation.snapshot(115).status=='stale'


def test_runtime_rejects_plugins_and_production(tmp_path):
    from member_dashboard.runtime import load_config
    config=tmp_path/'config.json'
    config.write_text(json.dumps({'mode':'production','factory':'os.system'}));config.chmod(0o600)
    with pytest.raises(ValueError): load_config(config)


def test_exit_control_requires_kernel_proof_and_all_batches(dashboard,tmp_path):
    from member_dashboard.exit_control import ExitRegistry
    from member_dashboard.quota_broker import QuotaBroker,Identity
    from member_dashboard.store import WebStore
    quota=WebStore(tmp_path/'quota.sqlite3');quota.migrate()
    broker=QuotaBroker(quota,clock=dashboard.clock)
    registry=ExitRegistry(broker,supervisor_uid=123,compute_uid=456,cgroup_root=Path('/sys/fs/cgroup/dashboard-compute'))
    broker.configure_scope('synthetic',window_seconds=600,verified_limit=500,bot_reserved=0,dashboard_allocated=500,safety_margin=0,verified=True,expires_at=dashboard.clock()+1000)
    broker.configure_endpoint('synthetic',['synthetic'],participation_verified=True)
    assert not broker.reserve(['synthetic'],Identity('dashboard','unknown'),'synthetic',1,'before-map').allowed
    # Unit fixture records kernel evidence directly, never a wire-supplied claim.
    with quota.transaction() as con:
        con.execute('INSERT INTO trusted_workers VALUES (?,?,?,?,?,?)',('worker','owner','/sys/fs/cgroup/dashboard-compute/one',42,0,'registered'))
    for index in range(101):
        assert broker.reserve(['synthetic'],Identity('dashboard','owner'),'synthetic',1,'attempt-'+str(index)).allowed
    assert registry.reconcile('worker') is False  # absent kernel cgroup proof
    registry._tree_dead=lambda row:True
    assert registry.reconcile('worker') is False
    assert registry.reconcile('worker') is True
    with quota.transaction() as con:
        assert con.execute('SELECT sum(units),sum(uncertain),count(finished_at) FROM provider_admissions').fetchone()==(101,101,101)
    assert not broker.reserve(['synthetic'],Identity('dashboard','owner'),'synthetic',1,'after-exit').allowed


def test_exit_control_cannot_register_from_untrusted_peer(dashboard,tmp_path):
    from member_dashboard.exit_control import ExitRegistry
    from member_dashboard.quota_broker import QuotaBroker
    registry=ExitRegistry(QuotaBroker(dashboard.store),supervisor_uid=123,compute_uid=456,cgroup_root=Path('/sys/fs/cgroup/dashboard-compute'))
    with pytest.raises(ValueError): registry.dispatch({'method':'register','worker':'fake','pid':os.getpid()},peer_uid=456)
    with pytest.raises(ValueError): registry.dispatch({'method':'reconcile','worker':'fake','dead':True},peer_uid=123)


def test_encrypted_backup_roundtrip_and_tamper(tmp_path):
    from member_dashboard.backup import encrypted_backup,encrypted_restore
    from member_dashboard.store import WebStore
    node=Path(__file__).resolve().parents[2]/'.superpowers/sdd/2026-10-05-member-dashboard/node-v24.21.0-win-x64/node.exe'
    if not node.exists(): pytest.skip('Node archive proof runs on the Windows control host')
    root=tmp_path/'archive';root.mkdir(mode=0o700)
    live=root/'web.sqlite3';WebStore(live).migrate()
    key=root/'key';key.write_bytes(os.urandom(32));key.chmod(0o600)
    kwargs=dict(quota_path=root/'quota.sqlite3',key_path=key,node=node)
    archive=encrypted_backup(live,root/'backup.mdb',root,**kwargs)
    assert b'SQLite format' not in archive.read_bytes()
    restored=encrypted_restore(archive,root/'restore.sqlite3',root,**kwargs)
    with sqlite3.connect(restored) as con: assert con.execute('SELECT sum(enabled) FROM features').fetchone()[0]==0
    bad=bytearray(archive.read_bytes());bad[-1]^=1;archive.write_bytes(bad)
    with pytest.raises(ValueError): encrypted_restore(archive,root/'bad.sqlite3',root,**kwargs)
    assert not (root/'bad.sqlite3').exists()


def test_current_denial_journal_survives_old_web_restore_and_rejects_rollback(tmp_path):
    from member_dashboard.authority import DenialJournal,CheckpointStore
    from member_dashboard.store import WebStore
    root=tmp_path/'authority';root.mkdir(mode=0o700)
    journal=DenialJournal.create(root/'journal.sqlite3',root/'anchor.json',checkpoint=CheckpointStore.create(tmp_path/'checkpoint.sqlite3'),clock=lambda:100)
    live=tmp_path/'web.sqlite3';WebStore(live).migrate()
    snapshot=tmp_path/'old.sqlite3';backup_web(live,snapshot,tmp_path,quota_path=tmp_path/'quota.sqlite3')
    old_anchor=(root/'anchor.json').read_bytes()
    journal.append('feature_disabled','options')
    restored=restore_closed(snapshot,tmp_path/'restore.sqlite3',tmp_path,quota_path=tmp_path/'quota.sqlite3',denial_journal=journal)
    with sqlite3.connect(restored) as con:
        assert con.execute("SELECT enabled FROM features WHERE name='options'").fetchone()[0]==0
    (root/'anchor.json').write_bytes(old_anchor)
    with pytest.raises(ValueError): journal.current()
    with pytest.raises(ValueError): restore_closed(snapshot,tmp_path/'rejected.sqlite3',tmp_path,quota_path=tmp_path/'quota.sqlite3',denial_journal=journal)
    assert not (tmp_path/'rejected.sqlite3').exists()


def test_denial_append_failure_blocks_web_mutation_and_expiry_blocks_restore(dashboard,tmp_path):
    from member_dashboard.authority import DenialJournal,CheckpointStore
    from member_dashboard.admin import AdminService
    from tests.member_dashboard.test_admin import identity
    root=tmp_path/'authority';root.mkdir(mode=0o700)
    journal=DenialJournal.create(root/'journal.sqlite3',root/'anchor.json',checkpoint=CheckpointStore.create(tmp_path/'checkpoint.sqlite3'),clock=dashboard.clock)
    service=dashboard.app.state.admin;service.denial_journal=journal
    _,_,actor=identity(dashboard)
    # Failure occurs before the feature mutation commits.
    journal.append=lambda *_: (_ for _ in ()).throw(ValueError('journal unavailable'))
    with pytest.raises(ValueError): service.set_feature(actor,'options',False)
    with dashboard.store.transaction() as con:
        assert con.execute("SELECT enabled FROM features WHERE name='options'").fetchone()[0]==1
    dashboard.clock.advance(301)
    with pytest.raises(ValueError): journal.current()


def test_journal_anchor_interruption_blocks_renewal(tmp_path,monkeypatch):
    from member_dashboard.authority import DenialJournal,CheckpointStore
    root=tmp_path/'authority';root.mkdir(mode=0o700)
    journal=DenialJournal.create(root/'journal.sqlite3',root/'anchor.json',checkpoint=CheckpointStore.create(tmp_path/'checkpoint.sqlite3'),clock=lambda:100)
    monkeypatch.setattr('member_dashboard.authority.os.replace',lambda *_: (_ for _ in ()).throw(OSError('synthetic anchor failure')))
    with pytest.raises(OSError): journal.append('retraction','post/SPY')
    with pytest.raises(ValueError): journal.current()
    with pytest.raises(ValueError): journal.renew()


from test_jobs import research
from test_history import history,completed


def test_current_history_deletion_applies_to_old_backup(history,research,dashboard,tmp_path):
    from member_dashboard.authority import DenialJournal,CheckpointStore
    root=tmp_path/'authority';root.mkdir(mode=0o700)
    journal=DenialJournal.create(root/'journal.sqlite3',root/'anchor.json',checkpoint=CheckpointStore.create(tmp_path/'checkpoint.sqlite3'),clock=dashboard.clock)
    history.denial_journal=journal
    request=completed(research,dashboard)[0]
    history.get_report(research[1][0],request.report_id)
    assert journal.current()==[]
    snapshot=tmp_path/'old.sqlite3'
    backup_web(dashboard.settings.web_path,snapshot,tmp_path,quota_path=tmp_path/'quota.sqlite3')
    history.delete_report(research[1][0],request.report_id)
    restored=restore_closed(snapshot,tmp_path/'restore.sqlite3',tmp_path,quota_path=tmp_path/'quota.sqlite3',denial_journal=journal)
    with sqlite3.connect(restored) as con:
        assert con.execute('SELECT deleted_at FROM report_owners WHERE report_id=?',(request.report_id,)).fetchone()[0] is not None
        assert con.execute('SELECT count(*) FROM job_subscribers WHERE deleted_at IS NULL').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM report_versions').fetchone()[0]==0


def test_staging_source_authority_closes_when_updater_expires(tmp_path):
    import time
    from types import SimpleNamespace
    from member_dashboard.runtime import staging_journal
    from member_dashboard.store import WebStore
    store=WebStore(tmp_path/'web.sqlite3');store.migrate()
    state=SimpleNamespace(store=store,admin=SimpleNamespace(),history=SimpleNamespace(),source_policy=SimpleNamespace())
    journal=staging_journal(SimpleNamespace(state=state),tmp_path,initialize=True)
    assert state.source_policy.authority_current() is True
    journal.clock=lambda:time.time()+301
    os.utime(journal.anchor,None)
    assert state.source_policy.authority_current() is False


def test_pending_broker_exit_survives_supervisor_restart(dashboard):
    from member_dashboard.worker import WorkerSupervisor
    class Dead:
        worker_id='persisted-dead'
        def is_dead(self): return True
        def close(self): pass
    spawned=[];calls=[]
    first=WorkerSupervisor(dashboard.store,lambda:spawned.append(True),lambda _:None,
        jobs=dashboard.app.state.research,clock=dashboard.clock,reconcile=lambda _:False)
    first.child=Dead();first.tick()
    second=WorkerSupervisor(dashboard.store,lambda:spawned.append(True),lambda _:None,
        jobs=dashboard.app.state.research,clock=dashboard.clock,reconcile=lambda worker:calls.append(worker) or False)
    second.tick()
    assert not spawned and calls==['persisted-dead']
    second.reconcile=lambda worker:worker=='persisted-dead'
    second.tick()
    assert spawned==[True]


def test_archive_rejects_noncanonical_suffix_and_serializes_writers(tmp_path,monkeypatch):
    from member_dashboard.backup import encrypted_backup,archive_lock
    root=tmp_path/'archive';root.mkdir(mode=0o700)
    with pytest.raises(ValueError,match='archive_name'):
        encrypted_backup(root/'web',root/'backup.bin',root,quota_path=root/'quota',key_path=root/'key',node=root/'node')
    with archive_lock(root):
        with pytest.raises(ValueError,match='archive_busy'):
            with archive_lock(root): pytest.fail('competing writer acquired the archive')
        import subprocess,sys
        child=subprocess.run([sys.executable,'-c',
            'from member_dashboard.backup import archive_lock; import sys;\nwith archive_lock(sys.argv[1]): pass',str(root)],
            capture_output=True,text=True,timeout=10)
        assert child.returncode!=0 and 'archive_busy' in child.stderr


def test_archive_checks_retention_after_snapshot(tmp_path,monkeypatch):
    from member_dashboard import backup
    from member_dashboard.store import WebStore
    from member_dashboard.source_policy import SourcePolicy,SourcePermission
    root=tmp_path/'archive';root.mkdir(mode=0o700)
    source=root/'web.sqlite3';store=WebStore(source);store.migrate()
    original=backup.backup_web
    def snapshot(*args,**kwargs):
        SourcePolicy(store).record(SourcePermission(source_id='synthetic',product_id='fixture',provider='fixture',
            policy_version='v1',audience='invited_members',status='denied',delete_on_expiry=True))
        return original(*args,**kwargs)
    monkeypatch.setattr(backup,'backup_web',snapshot)
    with pytest.raises(ValueError,match='source_backup_deletion_unverified'):
        backup.encrypted_backup(source,root/'backup.mdb',root,quota_path=root/'quota',key_path=root/'key',node=root/'node')
    assert not (root/'backup.mdb').exists()


def test_matching_journal_anchor_rollback_is_rejected_by_external_checkpoint(tmp_path):
    from member_dashboard.authority import DenialJournal,CheckpointStore
    from contextlib import closing
    root=tmp_path/'authority';root.mkdir(mode=0o700)
    checkpoint=CheckpointStore.create(tmp_path/'checkpoint.sqlite3')
    journal=DenialJournal.create(root/'journal.sqlite3',root/'anchor.json',checkpoint=checkpoint,clock=lambda:100)
    old_db=(root/'journal.sqlite3').read_bytes();old_anchor=(root/'anchor.json').read_bytes()
    journal.append('feature_disabled','options')
    (root/'journal.sqlite3').write_bytes(old_db);(root/'anchor.json').write_bytes(old_anchor)
    restarted=DenialJournal(root/'journal.sqlite3',root/'anchor.json',checkpoint=CheckpointStore(tmp_path/'checkpoint.sqlite3'),clock=lambda:100)
    with pytest.raises(ValueError,match='checkpoint'): restarted.current()
    with pytest.raises(ValueError,match='checkpoint'): restarted.renew()


def test_denial_commit_web_rollback_blocks_auth_before_and_after_restart(dashboard,tmp_path):
    from member_dashboard.authority import DenialJournal,CheckpointStore
    from member_dashboard.auth import AuthService,AuthError
    from member_dashboard.store import WebStore
    from tests.member_dashboard.test_admin import identity
    root=tmp_path/'authority';root.mkdir(mode=0o700)
    checkpoint=CheckpointStore.create(tmp_path/'checkpoint.sqlite3')
    journal=DenialJournal.create(root/'journal.sqlite3',root/'anchor.json',checkpoint=checkpoint,clock=dashboard.clock)
    _,session,actor=identity(dashboard,'member')
    dashboard.store.bind_authority(journal)
    with pytest.raises(RuntimeError):
        with dashboard.store.transaction() as con:
            journal.append('member_suspended',actor.member_id)
            raise RuntimeError('synthetic web commit failure')
    with pytest.raises(AuthError): AuthService(dashboard.store).principal(session.token,dashboard.clock())
    for store in (dashboard.store,WebStore(dashboard.settings.web_path)):
        store.bind_authority(journal)
        with pytest.raises(AuthError): AuthService(store).principal(session.token,dashboard.clock())
        with store.transaction() as con:
            assert con.execute('SELECT revision FROM authority_projection').fetchone()[0]==1
            assert con.execute('SELECT status FROM members WHERE id=?',(actor.member_id,)).fetchone()[0]=='suspended'
