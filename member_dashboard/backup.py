"""Encrypted private web backups; quota and current authority are not restored."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import time
from uuid import uuid4
from .launch import MAX_BACKUP,backup_web,restore_closed,protected,private_target


def _crypt(mode,data,key_path,node):
    key_path=protected(key_path)
    if key_path.stat().st_size!=32: raise ValueError('backup_key_requires_32_bytes')
    node=Path(node)
    if not node.is_absolute() or not node.is_file(): raise ValueError('explicit_node_required')
    script=Path(__file__).resolve().parents[1]/'scripts/member_dashboard_crypto.mjs'
    result=subprocess.run([str(node),str(script),mode],input=key_path.read_bytes()+data,
        capture_output=True,timeout=15)
    if result.returncode: raise ValueError('encrypted_backup_unavailable')
    if len(result.stdout)>MAX_BACKUP+4096: raise ValueError('backup_capacity')
    return result.stdout


def encrypted_backup(source,destination,root,*,quota_path,key_path,node,retention_seconds=30*86400):
    if type(retention_seconds) is not int or not 0<retention_seconds<=30*86400: raise ValueError('invalid_backup_retention')
    destination=private_target(root,destination)
    archives=list(Path(root).glob('*.mdb'))
    if len(archives)>=30 or sum(p.stat().st_size for p in archives)>128*1024*1024-MAX_BACKUP:
        raise ValueError('backup_growth_limit')
    source=Path(source)
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as con:
        # Until independently verified media/WAL/backup deletion exists, no
        # archive containing source-specific deletion obligations is allowed.
        if con.execute('SELECT 1 FROM source_permissions WHERE delete_on_expiry=1 OR retention_deadline IS NOT NULL LIMIT 1').fetchone():
            raise ValueError('source_backup_deletion_unverified')
    temporary=Path(root)/(str(uuid4())+'.snapshot.sqlite3')
    try:
        backup_web(source,temporary,root,quota_path=quota_path)
        expires=int(time.time())+retention_seconds
        data=_crypt('seal',expires.to_bytes(8,'big')+temporary.read_bytes(),key_path,node)
        fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
    finally: temporary.unlink(missing_ok=True)
    return destination


def encrypted_restore(source,destination,root,*,quota_path,key_path,node,denial_journal=None):
    source=protected(source)
    private_target(root,destination)
    if source.stat().st_size>MAX_BACKUP+4096: raise ValueError('backup_capacity')
    data=_crypt('open',source.read_bytes(),key_path,node)
    temporary=Path(root)/(str(uuid4())+'.restore.sqlite3')
    fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,'wb') as stream: stream.write(data)
        return restore_closed(temporary,destination,root,quota_path=quota_path,denial_journal=denial_journal)
    finally: temporary.unlink(missing_ok=True)
