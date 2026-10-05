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
            assert launcher.recover()==[]
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
            assert replacement.recover()==[child.worker_id]
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


def test_authority_nested_json_cannot_kill_rpc_thread(tmp_path,monkeypatch):
    import struct
    from member_dashboard.authority import DenialJournal,CheckpointStore
    from member_dashboard.authority_rpc import AuthorityService,AuthorityServer,AuthorityClient
    root=tmp_path/'authority';root.mkdir(mode=0o700)
    journal=DenialJournal.create(root/'journal',root/'anchor',checkpoint=CheckpointStore.create(tmp_path/'checkpoint'))
    service=AuthorityService(journal,read_uids=[os.getuid()],write_uids=[os.getuid()])
    with AuthorityServer(service,str(root/'rpc')) as server:
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as bad:
            bad.settimeout(2);bad.connect(str(root/'rpc'))
            payload=b'['*4000+b'0'+b']'*4000
            bad.sendall(struct.pack('!I',len(payload))+payload)
            bad.recv(1024)
        client=AuthorityClient(root/'rpc',os.getuid())
        assert client.current()==[]
        assert client.append('feature_disabled','options')==1
        assert server.thread.is_alive()
        # Some supported Python builds accept all nesting that fits 16KiB.
        # Exercise the decoder exception boundary deterministically as well.
        from member_dashboard import authority_rpc
        original=authority_rpc.receive_frame
        def decoder_limit(connection):
            value=original(connection)
            if isinstance(value,list): raise RecursionError('synthetic decoder recursion limit')
            return value
        monkeypatch.setattr(authority_rpc,'receive_frame',decoder_limit)
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as bad:
            bad.settimeout(2);bad.connect(str(root/'rpc'))
            bad.sendall(struct.pack('!I',len(payload))+payload);bad.recv(1024)
        assert client.current()[0][1]=='feature_disabled'
        assert server.thread.is_alive()


def test_nonroot_ambient_capabilities_are_removed_before_compute(tmp_path):
    if os.getuid()!=0: pytest.skip('Isolated root runner required for ambient capability fixture')
    # Only this disposable child gains synthetic capabilities; parent and host
    # permissions are unchanged. Mirror the documented nonroot supervisor unit.
    script=r'''
import ctypes,json,os,socket,sys
from pathlib import Path
from member_dashboard.compute_launcher import drop_compute_privileges
libc=ctypes.CDLL(None,use_errno=True)
class Header(ctypes.Structure): _fields_=[('version',ctypes.c_uint32),('pid',ctypes.c_int)]
class Data(ctypes.Structure): _fields_=[('effective',ctypes.c_uint32),('permitted',ctypes.c_uint32),('inheritable',ctypes.c_uint32)]
header=Header(0x20080522,0);data=(Data*2)();mask=(1<<6)|(1<<7)|(1<<21)
assert libc.prctl(8,1,0,0,0)==0
os.setgroups([]);os.setgid(65533);os.setuid(65533)
data[0]=Data(mask,mask,mask)
assert libc.capset(ctypes.byref(header),ctypes.byref(data))==0
for capability in (6,7,21): assert libc.prctl(47,2,capability,0,0)==0
before=Path('/proc/self/status').read_text()
assert int(next(v.split()[1] for v in before.splitlines() if v.startswith('CapAmb:')),16)==mask
drop_compute_privileges(65534,65534)
for change in (lambda:os.setuid(65533),lambda:os.setgid(65533),lambda:os.setgroups([65533])):
    try: change()
    except PermissionError: pass
    else: raise AssertionError('privileged identity operation survived')
status=Path('/proc/self/status').read_text()
for label in ('CapEff:','CapPrm:','CapInh:','CapAmb:'):
    assert int(next(v.split()[1] for v in status.splitlines() if v.startswith(label)),16)==0
assert next(v.split()[1] for v in status.splitlines() if v.startswith('NoNewPrivs:'))=='1'
from consensus_engine.utils.provider_budget import send_frame,receive_frame
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as con:
    con.connect(sys.argv[1]);send_frame(con,{'method':'recovery'})
    assert receive_frame(con)=={'ok':False}
print(json.dumps({'ambient_before':mask,'held_after':0,'identity_change_denied':True,'control_denied':True}))
'''
    from member_dashboard.store import WebStore
    from member_dashboard.quota_broker import QuotaBroker
    from member_dashboard.exit_control import ExitRegistry,ExitControlServer
    with tempfile.TemporaryDirectory(prefix='ambient-',dir='/run') as directory:
        root=Path(directory);root.chmod(0o755)
        socketdir=root/'control';socketdir.mkdir(mode=0o750);os.chown(socketdir,0,65534)
        store=WebStore(root/'quota');store.migrate()
        registry=ExitRegistry(QuotaBroker(store),supervisor_uid=65533,compute_uid=65534,cgroup_root=Path('/sys/fs/cgroup/synthetic'))
        server=ExitControlServer(registry,str(socketdir/'rpc'));os.chown(socketdir/'rpc',0,65534)
        with server:
            result=subprocess.run([sys.executable,'-c',script,str(socketdir/'rpc')],capture_output=True,text=True,timeout=10)
        assert result.returncode==0,result.stderr
        assert json.loads(result.stdout)['held_after']==0
