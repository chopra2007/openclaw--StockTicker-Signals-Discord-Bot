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
