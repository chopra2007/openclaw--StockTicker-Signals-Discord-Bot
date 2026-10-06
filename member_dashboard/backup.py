"""Encrypted private web backups; quota and current authority are not restored."""
from contextlib import closing,contextmanager
import os
import json
from pathlib import Path
import sqlite3
import subprocess
import time
from uuid import uuid4
from .launch import MAX_BACKUP,backup_web,restore_closed,protected,private_target


@contextmanager
def archive_lock(root):
    """OS-released cross-process exclusion; crash cannot leave a stale lock."""
    root=protected(Path(root),directory=True)
    path=root/'.archive.lock'
    if path.is_symlink(): raise ValueError('unsafe_archive_lock')
    fd=os.open(path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
    acquired=False
    try:
        if os.fstat(fd).st_size==0: os.write(fd,b'0')
        os.lseek(fd,0,os.SEEK_SET)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            acquired=True
        except OSError: raise ValueError('archive_busy') from None
        yield
    finally:
        if acquired:
            if os.name=='nt':
                os.lseek(fd,0,os.SEEK_SET);msvcrt.locking(fd,msvcrt.LK_UNLCK,1)
            else: fcntl.flock(fd,fcntl.LOCK_UN)
        os.close(fd)


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
    if Path(destination).suffix!='.mdb': raise ValueError('archive_name_requires_mdb')
    with archive_lock(root):
        return _encrypted_backup(source,destination,root,quota_path=quota_path,key_path=key_path,node=node,retention_seconds=retention_seconds)


def _encrypted_backup(source,destination,root,*,quota_path,key_path,node,retention_seconds):
    destination=private_target(root,destination)
    archives=list(Path(root).glob('*.mdb'))
    if any(p.is_symlink() or not p.is_file() for p in archives): raise ValueError('unsafe_archive_entry')
    if len(archives)>=30 or sum(p.stat().st_size for p in archives)>128*1024*1024-MAX_BACKUP-4096:
        raise ValueError('backup_growth_limit')
    source=Path(source)
    temporary=Path(root)/(str(uuid4())+'.snapshot.sqlite3')
    try:
        backup_web(source,temporary,root,quota_path=quota_path)
        # Validate the exact consistent snapshot that will be encrypted. An
        # earlier live permission read can race with a concurrent policy update.
        with closing(sqlite3.connect(temporary.as_uri()+'?mode=ro',uri=True)) as con:
            if con.execute('SELECT 1 FROM source_permissions WHERE delete_on_expiry=1 OR retention_deadline IS NOT NULL LIMIT 1').fetchone():
                raise ValueError('source_backup_deletion_unverified')
            for table in ('publications','publication_changes','assets','messages','report_versions','market_results'):
                if con.execute(f'SELECT 1 FROM {table} WHERE retention_deadline IS NOT NULL LIMIT 1').fetchone():
                    raise ValueError('source_backup_deletion_unverified')
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


def maintain_archives(root,*,key_path,node,now=None):
    """At most two authenticated expired files per call, under the creation lock.

    Header time only selects candidates. Authentication precedes unlink. This is
    logical retention maintenance, not proof of media or filesystem erasure.
    """
    now=time.time() if now is None else now
    removed=0
    with archive_lock(root):
        archives=sorted(Path(root).glob('*.mdb'))
        if len(archives)>30 or sum(p.lstat().st_size for p in archives)>128*1024*1024:
            raise ValueError('backup_growth_limit')
        for path in archives:
            protected(path)
            if path.stat().st_size>MAX_BACKUP+4096: raise ValueError('backup_capacity')
            with path.open('rb') as stream: header=stream.read(12)
            if len(header)!=12 or header[:4]!=b'MDB1': raise ValueError('invalid_archive')
            if int.from_bytes(header[4:12],'big')>now: continue
            evidence=json.loads(_crypt('inspect',path.read_bytes(),key_path,node))
            if evidence['expires_at']>now: raise ValueError('expiry_changed')
            path.unlink();removed+=1
            if removed==2: break
    return removed


# Feed cards are copies of bot data and the feed re-imports them once its checkpoints are gone.
FEED_TABLES=('publication_intervals','publication_heads','publication_evidence_refs','publication_retractions',
             'publication_changes','publications','source_checkpoints','feed_source_status')


def accounts_backup(staging,root,*,key_path,node,now=None,retention_seconds=14*86400):
    """Encrypted backup of a private web snapshot without feed cards (owner decision 2026-10-06).

    The snapshot is consumed: feed rows are deleted from it, then it is encrypted and removed.
    """
    staging=protected(Path(staging))
    try:
        with closing(sqlite3.connect(staging)) as con:
            for table in FEED_TABLES: con.execute(f'DELETE FROM {table}')
            con.commit();con.execute('VACUUM')
        name=time.strftime('%Y%m%d-%H%M%S',time.gmtime(time.time() if now is None else now))+'.mdb'
        return encrypted_backup(staging,Path(root)/name,root,quota_path=Path(root)/'no-quota.sqlite3',
                                key_path=key_path,node=node,retention_seconds=retention_seconds)
    finally:
        for suffix in ('','-wal','-shm'): Path(str(staging)+suffix).unlink(missing_ok=True)
