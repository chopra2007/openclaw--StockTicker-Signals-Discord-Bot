"""Bounded denial-only current authority, independent of historical web backups.

This journal cannot grant access. The trusted updater renews a <=300 second
anchor only after validating the complete monotonic hash chain. Interrupted
append/anchor updates fail closed. The Linux updater is denial-only; deployment
identities and positive external permission authority remain unconfigured.
"""
from contextlib import closing,contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import time
from uuid import uuid4
from .launch import protected,private_output,read_private_json

KINDS={'member_suspended','sessions_revoked','feature_disabled','report_deleted',
       'conversation_deleted','source_denied','retraction'}
ZERO='0'*64
LIMIT=1000


class CheckpointStore:
    """Independent non-restored high-water authority. Never auto-created on open.

    Production composition must give only its trusted updater write access;
    consumers use the narrow checkpoint client, not this local writer object.
    """
    def __init__(self,path):
        self.path=protected(Path(path))
        protected(self.path.parent,directory=True)

    @classmethod
    def create(cls,path):
        path=Path(path);protected(path.parent,directory=True)
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        with closing(sqlite3.connect(path)) as con:
            con.execute('CREATE TABLE checkpoint(singleton INTEGER PRIMARY KEY CHECK(singleton=1),revision INTEGER NOT NULL,digest TEXT NOT NULL) STRICT')
            con.execute('INSERT INTO checkpoint VALUES (1,0,?)',(ZERO,));con.commit()
        return cls(path)

    def current(self):
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=2)) as con:
            row=con.execute('SELECT revision,digest FROM checkpoint WHERE singleton=1').fetchone()
        if row is None: raise ValueError('checkpoint_missing')
        return row

    def advance(self,previous,digest):
        with closing(sqlite3.connect(self.path,timeout=2)) as con:
            con.execute('BEGIN IMMEDIATE')
            if con.execute('SELECT revision,digest FROM checkpoint WHERE singleton=1').fetchone()!=previous:
                raise ValueError('checkpoint_conflict')
            con.execute('UPDATE checkpoint SET revision=?,digest=? WHERE singleton=1',(previous[0]+1,digest))
            con.commit()


class DenialJournal:
    def __init__(self,path,anchor,*,checkpoint=None,clock=time.time):
        self.path,self.anchor,self.clock=Path(path),Path(anchor),clock
        self._protected_identities={}
        if checkpoint is None: raise ValueError('independent_checkpoint_required')
        self.checkpoint=checkpoint
        if isinstance(checkpoint,CheckpointStore) and any(root in checkpoint.path.resolve().parents
                for root in (self.path.parent.resolve(),self.anchor.parent.resolve())):
            raise ValueError('checkpoint_must_live_outside_journal_directory')
        if self.path.resolve()==self.anchor.resolve(): raise ValueError('independent_anchor_required')

    @classmethod
    def create(cls,path,anchor,*,checkpoint=None,clock=time.time):
        self=cls(path,anchor,checkpoint=checkpoint,clock=clock)
        if checkpoint.current()!=(0,ZERO): raise ValueError('checkpoint_already_advanced')
        protected(self.path.parent,directory=True);protected(self.anchor.parent,directory=True)
        if self.path.exists() or self.anchor.exists(): raise ValueError('authority_already_exists')
        fd=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        with closing(sqlite3.connect(self.path)) as con:
            con.execute('CREATE TABLE denials(revision INTEGER PRIMARY KEY,kind TEXT NOT NULL,object_key TEXT NOT NULL,observed_at REAL NOT NULL,digest TEXT NOT NULL) STRICT')
            con.commit()
        now=clock()
        private_output(self.anchor.parent,self.anchor,{'revision':0,'digest':ZERO,'issued_at':now,'expires_at':now+300})
        return self

    def _read(self,con):
        self._protected(self.anchor)
        if self.anchor.stat().st_size>4096: raise ValueError('authority_anchor_limit')
        anchor=json.loads(self.anchor.read_bytes())
        now=self.clock()
        if (set(anchor)!={'revision','digest','issued_at','expires_at'}
                or type(anchor['revision']) is not int or not 0<=anchor['revision']<=LIMIT
                or not all(type(anchor[k]) in (int,float) and math.isfinite(anchor[k]) for k in ('issued_at','expires_at'))
                or not anchor['issued_at']<=now<anchor['expires_at']<=anchor['issued_at']+300):
            raise ValueError('current_authority_expired_or_invalid')
        rows=con.execute('SELECT * FROM denials ORDER BY revision LIMIT ?',(LIMIT+1,)).fetchall()
        if len(rows)!=anchor['revision']: raise ValueError('authority_revision_mismatch')
        digest=ZERO
        for expected,(revision,kind,key,when,stored) in enumerate(rows,1):
            if revision!=expected or kind not in KINDS: raise ValueError('invalid_denial')
            digest=self._digest(digest,revision,kind,key,when)
            if stored!=digest: raise ValueError('authority_chain_mismatch')
        if digest!=anchor['digest']: raise ValueError('authority_anchor_mismatch')
        if self.checkpoint.current()!=(anchor['revision'],digest): raise ValueError('authority_checkpoint_mismatch')
        return rows,anchor

    @staticmethod
    def _digest(previous,revision,kind,key,when):
        return hashlib.sha256(json.dumps([previous,revision,kind,key,float(when)],separators=(',',':'),allow_nan=False).encode()).hexdigest()

    def _protected(self,path):
        # The trusted private directory owns replacements. Recheck ownership and
        # mode on every call; cache expensive Windows ACL checks per file identity.
        if path.is_symlink(): raise ValueError('unsafe_authority_path')
        info=path.stat();identity=(info.st_dev,info.st_ino,info.st_mode,info.st_uid)
        if os.name!='nt' or self._protected_identities.get(path)!=identity:
            protected(path);self._protected_identities[path]=identity

    def current(self):
        with self._publication_lock(): return self._current()

    @contextmanager
    def _publication_lock(self):
        """Bounded process/thread lock covers journal, checkpoint and anchor.

        Only lock contention is waited on. An acquired lock never makes a stale
        or interrupted state retryable or acceptable.
        """
        path=self.path.parent/'.authority.lock'
        if path.is_symlink(): raise ValueError('unsafe_authority_lock')
        fd=os.open(path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
        acquired=False
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or (os.name=='posix' and (info.st_uid!=os.getuid() or info.st_mode&0o077)):
                raise ValueError('unsafe_authority_lock')
            if info.st_size==0: os.write(fd,b'0')
            deadline=time.monotonic()+2
            while True:
                try:
                    if os.name=='nt':
                        import msvcrt
                        os.lseek(fd,0,os.SEEK_SET);msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    acquired=True;break
                except OSError:
                    if time.monotonic()>=deadline: raise ValueError('authority_busy') from None
                    time.sleep(.01)
            yield
        finally:
            if acquired:
                if os.name=='nt': os.lseek(fd,0,os.SEEK_SET);msvcrt.locking(fd,msvcrt.LK_UNLCK,1)
                else: fcntl.flock(fd,fcntl.LOCK_UN)
            os.close(fd)

    def _current(self):
        self._protected(self.path)
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=2)) as con:
            return self._read(con)[0]

    def append(self,kind,key):
        with self._publication_lock(): return self._append(kind,key)

    def _append(self,kind,key):
        if kind not in KINDS or not isinstance(key,str) or not 1<=len(key.encode('utf-8'))<=512 or any(ord(c)<32 for c in key):
            raise ValueError('invalid_denial')
        self._protected(self.path)
        with closing(sqlite3.connect(self.path,timeout=2)) as con:
            con.execute('BEGIN IMMEDIATE')
            rows,anchor=self._read(con)
            if len(rows)>=LIMIT: raise ValueError('authority_capacity')
            now=float(self.clock());revision=anchor['revision']+1
            digest=self._digest(anchor['digest'],revision,kind,key,now)
            con.execute('INSERT INTO denials VALUES (?,?,?,?,?)',(revision,kind,key,now,digest))
            con.commit()
            self.checkpoint.advance((anchor['revision'],anchor['digest']),digest)
            # Journal is durable BEFORE the independent anchor. Any interruption
            # produces a mismatch and blocks mutation/restore, never a rollback.
            temporary=self.anchor.parent/(str(uuid4())+'.anchor')
            private_output(self.anchor.parent,temporary,{'revision':revision,'digest':digest,'issued_at':now,'expires_at':now+300})
            os.replace(temporary,self.anchor)
            if os.name=='posix':
                fd=os.open(self.anchor.parent,os.O_RDONLY)
                try: os.fsync(fd)
                finally: os.close(fd)
        return revision

    def renew(self):
        """Trusted updater heartbeat; stale/mismatched state cannot be renewed."""
        with self._publication_lock(): return self._renew()

    def _renew(self):
        self._protected(self.path)
        with closing(sqlite3.connect(self.path,timeout=2)) as con:
            con.execute('BEGIN IMMEDIATE')
            _,anchor=self._read(con)
            now=float(self.clock())
            temporary=self.anchor.parent/(str(uuid4())+'.anchor')
            private_output(self.anchor.parent,temporary,{**anchor,'issued_at':now,'expires_at':now+300})
            os.replace(temporary,self.anchor)
            con.commit()

    def reconcile(self,con):
        rows=self.current()
        projection=con.execute('SELECT revision,digest FROM authority_projection WHERE singleton=1').fetchone()
        if projection is None: raise ValueError('authority_projection_missing')
        revision,digest=projection
        if revision>len(rows) or digest!=(rows[revision-1][4] if revision else ZERO):
            raise ValueError('authority_projection_mismatch')
        for _,kind,key,when,_ in rows[revision:]:
            if kind=='member_suspended':
                con.execute("UPDATE members SET status='suspended',authorization_version=authorization_version+1 WHERE id=? AND status!='suspended'",(key,))
            if kind in ('member_suspended','sessions_revoked'):
                con.execute('DELETE FROM sessions WHERE member_id=?',(key,))
            elif kind=='feature_disabled': con.execute('UPDATE features SET enabled=0,version=version+1 WHERE name=? AND enabled!=0',(key,))
            elif kind=='report_deleted':
                con.execute('UPDATE report_owners SET deleted_at=?,subscriber_version=subscriber_version+1 WHERE id=?',(when,key))
                con.execute('UPDATE research_requests SET deleted_at=?,subscriber_version=subscriber_version+1 WHERE report_owner_id=?',(when,key))
                con.execute('UPDATE job_subscribers SET deleted_at=?,subscriber_version=subscriber_version+1 WHERE request_id IN (SELECT id FROM research_requests WHERE report_owner_id=?)',(when,key))
            elif kind=='conversation_deleted':
                con.execute('UPDATE conversations SET deleted_at=?,version=version+1 WHERE id=?',(when,key))
                con.execute('DELETE FROM messages WHERE conversation_id=?',(key,))
            elif kind in ('source_denied','retraction'):
                # No source-specific positive clearance exists. Quarantine
                # globally closes source delivery instead of guessing lineage.
                con.execute('UPDATE feed_state SET retraction_authority_required=1')
                con.execute('UPDATE authority_projection SET source_withheld=1 WHERE singleton=1')
        if self.current()!=rows: raise ValueError('authority_changed_during_reconciliation')
        con.execute('UPDATE authority_projection SET revision=?,digest=? WHERE singleton=1',
                    (len(rows),rows[-1][4] if rows else ZERO))
