"""Bounded denial-only current authority, independent of historical web backups.

This journal cannot grant access. The trusted updater renews a <=300 second
anchor only after validating the complete monotonic hash chain. Interrupted
append/anchor updates fail closed. Production updater identity/wiring is absent.
"""
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time
from uuid import uuid4
from .launch import protected,private_output,read_private_json

KINDS={'member_suspended','sessions_revoked','feature_disabled','report_deleted',
       'conversation_deleted','source_denied','retraction'}
ZERO='0'*64
LIMIT=1000


class DenialJournal:
    def __init__(self,path,anchor,*,clock=time.time):
        self.path,self.anchor,self.clock=Path(path),Path(anchor),clock
        if self.path.resolve()==self.anchor.resolve(): raise ValueError('independent_anchor_required')

    @classmethod
    def create(cls,path,anchor,*,clock=time.time):
        self=cls(path,anchor,clock=clock)
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
        anchor=read_private_json(self.anchor)
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
        return rows,anchor

    @staticmethod
    def _digest(previous,revision,kind,key,when):
        return hashlib.sha256(json.dumps([previous,revision,kind,key,float(when)],separators=(',',':'),allow_nan=False).encode()).hexdigest()

    def current(self):
        protected(self.path)
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=2)) as con:
            return self._read(con)[0]

    def append(self,kind,key):
        if kind not in KINDS or not isinstance(key,str) or not 1<=len(key)<=512 or any(ord(c)<32 for c in key):
            raise ValueError('invalid_denial')
        protected(self.path)
        with closing(sqlite3.connect(self.path,timeout=2)) as con:
            con.execute('BEGIN IMMEDIATE')
            rows,anchor=self._read(con)
            if len(rows)>=LIMIT: raise ValueError('authority_capacity')
            now=float(self.clock());revision=anchor['revision']+1
            digest=self._digest(anchor['digest'],revision,kind,key,now)
            con.execute('INSERT INTO denials VALUES (?,?,?,?,?)',(revision,kind,key,now,digest))
            con.commit()
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
        protected(self.path)
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
        for _,kind,key,when,_ in rows:
            if kind=='member_suspended':
                con.execute("UPDATE members SET status='suspended',authorization_version=authorization_version+1 WHERE id=?",(key,))
            if kind in ('member_suspended','sessions_revoked'):
                con.execute('DELETE FROM sessions WHERE member_id=?',(key,))
            elif kind=='feature_disabled': con.execute('UPDATE features SET enabled=0,version=version+1 WHERE name=?',(key,))
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
        self.current()  # Expiry or competing rollback during restore aborts it.
