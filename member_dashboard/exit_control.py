"""Separate Linux supervisor control boundary; never a member/budget-client RPC.

Registration captures kernel identity while the child is gated. Reconciliation
requires the dedicated registered cgroup still exist and be empty. Missing or
recreated cgroups block recovery; deleting a cgroup is not proof of exit.
"""
import os
from pathlib import Path
import socket
import sqlite3
import struct
from uuid import UUID

from .quota_broker import BrokerServer,process_identity,confirmed_process_exit
from consensus_engine.utils.provider_budget import receive_frame,send_frame


class ExitRegistry:
    def __init__(self,broker,*,supervisor_uid,compute_uid,cgroup_root):
        if (type(supervisor_uid) is not int or type(compute_uid) is not int
                or supervisor_uid<0 or compute_uid<0 or supervisor_uid==compute_uid):
            raise ValueError('distinct_trusted_identities_required')
        self.broker=broker
        self.supervisor_uid,self.compute_uid=supervisor_uid,compute_uid
        self.cgroup_root=Path(cgroup_root)
        if not self.cgroup_root.as_posix().startswith('/sys/fs/cgroup/') or '..' in self.cgroup_root.parts:
            raise ValueError('dedicated_cgroup_root_required')
        with broker.store.transaction() as con:
            con.execute('''CREATE TABLE IF NOT EXISTS trusted_workers (
                worker TEXT PRIMARY KEY, owner TEXT NOT NULL UNIQUE,
                cgroup TEXT NOT NULL, inode INTEGER NOT NULL,
                registered_at REAL NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('registered','reconciled'))) STRICT''')
        broker.dashboard_owner_allowed=self.admitted_owner

    def admitted_owner(self,owner):
        with self.broker.store.transaction() as con:
            return con.execute("SELECT 1 FROM trusted_workers WHERE owner=? AND state='registered'",(owner,)).fetchone() is not None

    def register(self,worker,pid):
        if str(UUID(worker))!=worker or type(pid) is not int or pid<=0: raise ValueError('invalid_worker')
        owner=process_identity(pid)
        status=Path(f'/proc/{pid}/status').read_text()
        uid_line=next(line for line in status.splitlines() if line.startswith('Uid:'))
        if any(int(uid)!=self.compute_uid for uid in uid_line.split()[1:]): raise ValueError('wrong_compute_identity')
        lines=Path(f'/proc/{pid}/cgroup').read_text().splitlines()
        if len(lines)!=1 or not lines[0].startswith('0::/'): raise ValueError('unified_cgroup_required')
        cgroup=Path('/sys/fs/cgroup')/lines[0][3:].lstrip('/')
        root=self.cgroup_root.resolve(strict=True)
        if cgroup.resolve(strict=True)!=cgroup or root not in cgroup.parents or cgroup==root:
            raise ValueError('dedicated_child_cgroup_required')
        # No shared supervisor/other process cgroup can become a worker proof.
        pids=(cgroup/'cgroup.procs').read_text().split()
        if pids!=[str(pid)]: raise ValueError('child_must_be_gated_alone')
        info=cgroup.stat()
        if process_identity(pid)!=owner: raise ValueError('worker_changed_during_registration')
        with self.broker.store.transaction() as con:
            con.execute('INSERT INTO trusted_workers VALUES (?,?,?,?,?,?)',
                (worker,owner,str(cgroup),info.st_ino,self.broker.clock(),'registered'))
        return True

    def _tree_dead(self,row):
        _,owner,cgroup,inode,_,_=row
        try:
            path=Path(cgroup)
            if path.resolve(strict=True)!=path or path.stat().st_ino!=inode: return False
            events=dict(line.split() for line in (path/'cgroup.events').read_text().splitlines())
            return events.get('populated')=='0' and confirmed_process_exit(owner)
        except (OSError,ValueError): return False

    def reconcile(self,worker):
        with self.broker.store.transaction() as con:
            row=con.execute('SELECT * FROM trusted_workers WHERE worker=?',(worker,)).fetchone()
        if row is None or not self._tree_dead(row): return False
        self.broker.reconcile_exited(row[1],confirmed_dead=lambda owner:owner==row[1] and self._tree_dead(row),limit=100)
        with self.broker.store.transaction() as con:
            pending=con.execute('SELECT 1 FROM provider_admissions a JOIN quota_attempts q ON q.id=a.group_id WHERE q.owner=? AND a.finished_at IS NULL LIMIT 1',(row[1],)).fetchone()
            if pending: return False
            con.execute("UPDATE trusted_workers SET state='reconciled' WHERE worker=?",(worker,))
        return True

    def dispatch(self,request,*,peer_uid):
        if peer_uid!=self.supervisor_uid or not isinstance(request,dict): raise ValueError('unauthorized_supervisor')
        if request=={'method':'recovery'}:
            with self.broker.store.transaction() as con:
                # Reconciled tombstones remain discoverable until the web ledger
                # can finish its own commit after an abrupt supervisor crash.
                rows=con.execute('SELECT worker FROM trusted_workers ORDER BY registered_at,worker LIMIT 33').fetchall()
            if len(rows)>32: raise ValueError('worker_registry_capacity')
            return {'workers':[row[0] for row in rows]}
        if request.get('method')=='register' and set(request)=={'method','worker','pid'}:
            return {'ok':self.register(request['worker'],request['pid'])}
        if request.get('method')=='reconcile' and set(request)=={'method','worker'}:
            if not isinstance(request['worker'],str) or len(request['worker'])>128: raise ValueError('invalid_worker')
            return {'ok':self.reconcile(request['worker'])}
        raise ValueError('invalid_control_request')


class ExitControlServer(BrokerServer):
    """Private socket directory must be broker-owned, not compute/API-writable.

    Supervisor gets only socket-connect permission via an explicitly scoped ACL.
    No booleans, owners, cgroups, shell or arbitrary paths are accepted on wire.
    """
    def __init__(self,registry,path):
        self.registry=registry
        super().__init__(registry.broker,path,uid_roles={})

    def _serve(self):
        while not self.stopping.is_set():
            try: connection,_=self.socket.accept()
            except socket.timeout: continue
            except OSError: break
            with connection:
                connection.settimeout(2)
                try:
                    _,uid,_=struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                    result=self.registry.dispatch(receive_frame(connection),peer_uid=uid)
                except (OSError,ValueError,TypeError,KeyError,StopIteration,RecursionError,sqlite3.Error): result={'ok':False}
                try: send_frame(connection,result)
                except OSError: pass
