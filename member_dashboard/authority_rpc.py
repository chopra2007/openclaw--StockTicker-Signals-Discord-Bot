"""Denial-only local updater; authenticated readers cannot mint positive rights."""
import os
from pathlib import Path
import socket
import sqlite3
import struct
import time
from .authority import DenialJournal,LIMIT
from .quota_broker import BrokerServer
from consensus_engine.utils.provider_budget import receive_frame,send_frame


class AuthorityService:
    def __init__(self,journal,*,read_uids,write_uids):
        self.journal=journal
        self.read_uids=set(read_uids);self.write_uids=set(write_uids)
        if not self.write_uids<=self.read_uids: raise ValueError('invalid_authority_roles')

    def dispatch(self,request,*,peer_uid):
        if peer_uid not in self.read_uids or not isinstance(request,dict): raise ValueError('unauthorized_authority_peer')
        if request.get('method')=='append' and set(request)=={'method','kind','key'}:
            if peer_uid not in self.write_uids: raise ValueError('unauthorized_denial_writer')
            return {'revision':self.journal.append(request['kind'],request['key'])}
        if request.get('method')=='current' and set(request)=={'method','offset'}:
            offset=request['offset']
            if type(offset) is not int or not 0<=offset<=LIMIT: raise ValueError('invalid_authority_offset')
            rows=self.journal.current()
            return {'revision':len(rows),'digest':rows[-1][4] if rows else '0'*64,'rows':rows[offset:offset+16]}
        raise ValueError('invalid_authority_request')


class AuthorityServer(BrokerServer):
    def __init__(self,service,path):
        self.service=service
        super().__init__(None,path,uid_roles={})

    def _serve(self):
        while not self.stopping.is_set():
            try: connection,_=self.socket.accept()
            except socket.timeout: continue
            except OSError: break
            with connection:
                connection.settimeout(2)
                try:
                    _,uid,_=struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                    result=self.service.dispatch(receive_frame(connection),peer_uid=uid)
                except (OSError,ValueError,TypeError,KeyError,sqlite3.Error): result={'error':'authority_unavailable'}
                try: send_frame(connection,result)
                except (OSError,ValueError): pass


class AuthorityClient:
    # Reuse precisely the same projection operation; current() is authenticated RPC.
    reconcile=DenialJournal.reconcile
    def __init__(self,path,uid): self.path,self.uid=str(path),uid

    def _rpc(self,request):
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
            connection.settimeout(2);connection.connect(self.path)
            _,uid,_=struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            if uid!=self.uid: raise ValueError('wrong_authority_server')
            send_frame(connection,request);result=receive_frame(connection)
        if 'error' in result: raise ValueError('authority_unavailable')
        return result

    def current(self):
        rows=[];head=None;deadline=time.monotonic()+5
        while True:
            if time.monotonic()>deadline: raise ValueError('authority_read_deadline')
            result=self._rpc({'method':'current','offset':len(rows)})
            current=(result['revision'],result['digest'])
            if not 0<=current[0]<=LIMIT or (head is not None and current!=head): raise ValueError('authority_changed')
            head=current;page=result['rows']
            if len(page)>16: raise ValueError('authority_page_limit')
            rows.extend(tuple(row) for row in page)
            if len(rows)==head[0]: return rows
            if not page or len(rows)>head[0]: raise ValueError('authority_page_missing')

    def append(self,kind,key): return self._rpc({'method':'append','kind':kind,'key':key})['revision']
