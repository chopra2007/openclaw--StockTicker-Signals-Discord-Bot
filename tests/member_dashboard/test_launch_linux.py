"""Actual Linux peer and filesystem checks; synthetic files only."""
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import pytest

pytestmark=pytest.mark.skipif(sys.platform!='linux',reason='Linux kernel boundary proof')


def test_control_socket_rejects_actual_untrusted_peer(tmp_path):
    from member_dashboard.store import WebStore
    from member_dashboard.quota_broker import QuotaBroker
    from member_dashboard.exit_control import ExitRegistry,ExitControlServer
    from consensus_engine.utils.provider_budget import send_frame,receive_frame
    root=tmp_path/'private';root.mkdir(mode=0o700)
    store=WebStore(root/'quota.sqlite3');store.migrate()
    registry=ExitRegistry(QuotaBroker(store),supervisor_uid=os.getuid()+1,
        compute_uid=os.getuid()+2,cgroup_root=Path('/sys/fs/cgroup/member-dashboard-compute'))
    with ExitControlServer(registry,str(root/'control.sock')):
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
            client.connect(str(root/'control.sock'))
            send_frame(client,{'method':'reconcile','worker':'unknown','dead':True})
            assert receive_frame(client)=={'ok':False}
    assert not (root/'control.sock').exists()


def test_actual_readonly_wal_and_secret_denial():
    if os.getuid()!=0: pytest.skip('Isolated root runner required for numeric UID sandbox proof')
    with tempfile.TemporaryDirectory(prefix='member-launch-sandbox-') as directory:
        root=Path(directory);root.chmod(0o755)
        market=root/'market';market.mkdir(mode=0o750);os.chown(market,0,65534)
        secret=root/'denied';secret.mkdir(mode=0o700)
        (secret/'synthetic-secret').write_text('synthetic-only')
        db=market/'source.sqlite3'
        writer=sqlite3.connect(db)
        writer.execute('PRAGMA journal_mode=WAL');writer.execute('CREATE TABLE observations(value TEXT)')
        writer.execute("INSERT INTO observations VALUES ('wal-only synthetic record')");writer.commit()
        for file in market.iterdir(): os.chown(file,0,65534);file.chmod(0o640)
        script='''
import json,sqlite3,sys
from pathlib import Path
root=Path(sys.argv[1]);db=root/'market/source.sqlite3'
con=sqlite3.connect('file:market/source.sqlite3?mode=ro',uri=True)
assert con.execute('SELECT value FROM observations').fetchone()[0]=='wal-only synthetic record'
for path in (db,root/'denied/synthetic-secret'):
    try:
        with path.open('r+b'): pass
    except PermissionError: pass
    else: raise AssertionError('filesystem write/secret boundary open')
try: (root/'denied/synthetic-secret').read_text()
except PermissionError: pass
else: raise AssertionError('secret exposed')
try: con.execute("INSERT INTO observations VALUES ('forbidden')")
except sqlite3.OperationalError: pass
else: raise AssertionError('SQLite source write allowed')
print(json.dumps({'wal_read':True,'source_write_denied':True,'secret_read_denied':True}))
'''
        def demote(): os.setgroups([]);os.setgid(65534);os.setuid(65534)
        result=subprocess.run([sys.executable,'-c',script,'.'],cwd=root,preexec_fn=demote,
            capture_output=True,text=True,timeout=10)
        writer.close()
        assert result.returncode==0,result.stderr
        assert json.loads(result.stdout)=={'wal_read':True,'source_write_denied':True,'secret_read_denied':True}


def test_gated_compute_actual_cgroup_registration_and_recovery(monkeypatch):
    """Only the isolated transient-unit runner supplies this delegated subtree."""
    import time
    from member_dashboard.compute_launcher import CgroupLauncher,ExitClient
    from member_dashboard.exit_control import ExitRegistry,ExitControlServer
    from member_dashboard.quota_broker import QuotaBroker,Identity
    from member_dashboard.store import WebStore
    from member_dashboard.authority import DenialJournal,CheckpointStore
    from member_dashboard.authority_rpc import AuthorityService,AuthorityServer
    if os.getuid()!=0 or 'MEMBER_TEST_CGROUP' not in os.environ:
        pytest.skip('Task-owned transient cgroup proof runner required')
    root=Path(os.environ['MEMBER_TEST_CGROUP'])
    from member_dashboard import compute_launcher
    original_popen=compute_launcher.subprocess.Popen
    def capture(*args,**kwargs):
        kwargs['stderr']=subprocess.PIPE
        return original_popen(*args,**kwargs)
    monkeypatch.setattr(compute_launcher.subprocess,'Popen',capture)
    # Numeric nobody belongs only to this synthetic proof; no production identity inference.
    with tempfile.TemporaryDirectory(prefix='cg-',dir='/run') as directory:
        run=Path(directory);run.chmod(0o755)
        socketdir=run/'broker';socketdir.mkdir(mode=0o700)
        store=WebStore(socketdir/'quota');store.migrate()
        broker=QuotaBroker(store)
        registry=ExitRegistry(broker,supervisor_uid=0,compute_uid=65534,cgroup_root=root)
        webdir=run/'web';webdir.mkdir(mode=0o700);os.chown(webdir,65534,65534)
        journal_dir=run/'journal';journal_dir.mkdir(mode=0o700)
        highwater=run/'highwater';highwater.mkdir(mode=0o700)
        journal=DenialJournal.create(journal_dir/'journal',journal_dir/'anchor',checkpoint=CheckpointStore.create(highwater/'checkpoint'))
        authority_dir=run/'authority';authority_dir.mkdir(mode=0o750);os.chown(authority_dir,0,65534)
        authority=AuthorityServer(AuthorityService(journal,read_uids=[65534],write_uids=[]),str(authority_dir/'rpc'))
        os.chown(authority_dir/'rpc',0,65534)
        config=run/'compute.json'
        config.write_text(json.dumps({'role':'compute','uid':65534,'web_path':str(webdir/'web.sqlite3'),
            'authority_socket':str(authority_dir/'rpc'),'authority_uid':0}))
        os.chown(config,65534,65534);config.chmod(0o600)
        with authority,ExitControlServer(registry,str(socketdir/'control')):
            control=ExitClient(socketdir/'control',0)
            launcher=CgroupLauncher(root,compute_uid=65534,compute_gid=65534,config=config,control=control)
            assert launcher.recover()
            child=launcher()
            with store.transaction() as con:
                row=con.execute('SELECT worker,owner,cgroup,state FROM trusted_workers').fetchone()
            assert row[0]==child.worker_id and row[2]==str(child.path) and row[3]=='registered'
            deadline=time.monotonic()+8;observed=False
            while not child.is_dead() and time.monotonic()<deadline:
                try:
                    with sqlite3.connect((webdir/'web.sqlite3').as_uri()+'?mode=ro',uri=True) as con:
                        observed=con.execute("SELECT 1 FROM health_observations WHERE component='compute'").fetchone() is not None
                except sqlite3.Error: pass
                if observed: break
                time.sleep(.05)
            assert observed,child.process.stderr.read(4096).decode() if child.is_dead() else 'heartbeat missing'
            assert not child.is_dead()
            child.kill_tree()
            deadline=time.monotonic()+3
            while not child.is_dead() and time.monotonic()<deadline: time.sleep(.05)
            assert child.is_dead()
            child.close()
            replacement=CgroupLauncher(root,compute_uid=65534,compute_gid=65534,config=config,control=control)
            assert replacement.recover()
            with store.transaction() as con:
                assert con.execute('SELECT state FROM trusted_workers').fetchone()[0]=='reconciled'
            assert child.path.is_dir()  # Evidence retained through recovery.


def test_authority_rpc_authenticates_actual_peers(tmp_path):
    from member_dashboard.authority import DenialJournal,CheckpointStore
    from member_dashboard.authority_rpc import AuthorityService,AuthorityServer,AuthorityClient
    root=tmp_path/'authority';root.mkdir(mode=0o700)
    journal=DenialJournal.create(root/'journal',root/'anchor',checkpoint=CheckpointStore.create(tmp_path/'checkpoint'))
    service=AuthorityService(journal,read_uids=[os.getuid()],write_uids=[os.getuid()])
    with AuthorityServer(service,str(root/'rpc')):
        client=AuthorityClient(root/'rpc',os.getuid())
        assert client.current()==[]
        assert client.append('feature_disabled','options')==1
        assert client.current()[0][1]=='feature_disabled'
        with pytest.raises(ValueError,match='wrong_authority_server'):
            AuthorityClient(root/'rpc',os.getuid()+1).current()
