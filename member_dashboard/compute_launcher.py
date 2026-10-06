"""Fixed Linux compute entrypoint, gated by kernel credentials and cgroup proof.

Only UUID child directories under this service's delegated cgroup are writable.
Groups are retained for independent broker reconciliation, never deleted here.
"""
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys
import time
from uuid import UUID,uuid4
from .quota_broker import process_identity
from consensus_engine.utils.provider_budget import send_frame,receive_frame


class ExitClient:
    def __init__(self,path,uid): self.path,self.uid=str(path),uid
    def call(self,method,worker=None,pid=None):
        request={'method':method}
        if worker is not None: request['worker']=worker
        if pid is not None: request['pid']=pid
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as con:
            con.settimeout(2);con.connect(self.path)
            _,uid,_=struct.unpack('3i',con.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            if uid!=self.uid: raise ValueError('wrong_exit_authority')
            send_frame(con,request);return receive_frame(con)
    def register(self,worker,pid): return self.call('register',worker,pid).get('ok') is True
    def reconcile(self,worker): return self.call('reconcile',worker).get('ok') is True


class CgroupChild:
    def __init__(self,worker,path,process,pid,owner):
        self.worker_id,self.path,self.process,self.pid,self.owner=worker,path,process,pid,owner
    def is_dead(self):
        from .quota_broker import confirmed_process_exit
        self.process.poll()  # reap the namespace launcher
        events=dict(line.split() for line in (self.path/'cgroup.events').read_text().splitlines())
        return events.get('populated')=='0' and confirmed_process_exit(self.owner)
    def request_stop(self):
        if not self.is_dead() and process_identity(self.pid)==self.owner: os.kill(self.pid,signal.SIGTERM)
    def kill_tree(self): (self.path/'cgroup.kill').write_text('1')
    def close(self):
        if not self.is_dead(): raise ValueError('live_compute_tree')
        self.process.wait(timeout=2)


class CgroupLauncher:
    def __init__(self,root,*,compute_uid,compute_gid,config,control):
        if sys.platform!='linux': raise ValueError('linux_launcher_required')
        if any(type(v) is not int or v<=0 for v in (compute_uid,compute_gid)) or compute_uid==os.getuid():
            raise ValueError('distinct_compute_identity_required')
        root=Path(root)
        own=Path('/sys/fs/cgroup')/Path('/proc/self/cgroup').read_text().strip().removeprefix('0::/').lstrip('/')
        if not root.is_absolute() or root.is_symlink() or root.resolve(strict=True)!=root or own not in root.parents:
            raise ValueError('cgroup_outside_delegated_service')
        self.root,self.uid,self.gid,self.config,self.control=root,compute_uid,compute_gid,Path(config),control

    def recover(self):
        """Before replacement, kill/reconcile every persisted registered owner.

        Unknown/missing/recreated tree evidence blocks; no web-only ledger reset.
        """
        response=self.control.call('recovery')
        if set(response)!={'workers'} or len(response['workers'])>32: raise ValueError('unknown_broker_ownership')
        children=[p for p in self.root.iterdir() if p.is_dir()]
        if len(children)>32: raise ValueError('retained_cgroup_capacity')
        for path in children:
            if path.is_symlink() or str(UUID(path.name))!=path.name: raise ValueError('unknown_child_cgroup')
            (path/'cgroup.kill').write_text('1')
        for worker in response['workers']:
            if str(UUID(worker))!=worker: raise ValueError('invalid_worker')
            path=self.root/worker
            if path.is_symlink() or not path.is_dir(): raise ValueError('missing_retained_cgroup')
            (path/'cgroup.kill').write_text('1')
            if not self.control.reconcile(worker): return None
        return response['workers']

    def __call__(self):
        # cgroup interface files are not children; cap retained worker directories.
        if sum(p.is_dir() for p in self.root.iterdir())>=32: raise ValueError('retained_cgroup_capacity')
        worker=str(uuid4());path=self.root/worker;path.mkdir()
        parent,child=socket.socketpair();parent.setsockopt(socket.SOL_SOCKET,socket.SO_PASSCRED,1);parent.settimeout(5)
        process=None
        try:
            process=subprocess.Popen(['/usr/bin/unshare','--pid','--fork','--mount-proc',sys.executable,
                '-m','member_dashboard.compute_launcher','--gate-fd',str(child.fileno()),'--uid',str(self.uid),
                '--gid',str(self.gid),'--config',str(self.config),'--worker',worker],
                pass_fds=(child.fileno(),),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                env={'PATH':'/usr/bin:/bin','PYTHONNOUSERSITE':'1'},start_new_session=True)
            child.close()
            message,ancillary,_,_=parent.recvmsg(1,socket.CMSG_SPACE(12))
            credentials=[struct.unpack('3i',data) for level,kind,data in ancillary
                if level==socket.SOL_SOCKET and kind==socket.SCM_CREDENTIALS]
            if message!=b'R' or len(credentials)!=1 or credentials[0][1:]!=(self.uid,self.gid):
                raise ValueError('invalid_compute_handshake')
            pid=credentials[0][0];owner=process_identity(pid)
            (path/'cgroup.procs').write_text(str(pid))
            if not self.control.register(worker,pid): raise ValueError('broker_registration_failed')
            if process_identity(pid)!=owner: raise ValueError('compute_changed')
            parent.sendall(b'A')
            return CgroupChild(worker,path,process,pid,owner)
        except BaseException:
            (path/'cgroup.kill').write_text('1')
            if process is not None:
                try: process.wait(timeout=6)
                except subprocess.TimeoutExpired: process.kill();process.wait(timeout=2)
            raise
        finally: parent.close();child.close()


def drop_compute_privileges(uid,gid):
    """Drop held capabilities explicitly, including nonroot ambient launchers.

    no_new_privs prevents regaining privilege at a later exec; bounding-set bits
    are ceilings, not held privileges, and need not be expanded with SETPCAP just
    to remove them. No privileged sibling thread may survive the transition.
    """
    import ctypes
    if sys.platform!='linux' or uid<=0 or gid<=0 or len(list(Path('/proc/self/task').iterdir()))!=1:
        raise ValueError('single_thread_linux_privilege_drop_required')
    libc=ctypes.CDLL(None,use_errno=True)
    libc.prctl.argtypes=[ctypes.c_int,*([ctypes.c_ulong]*4)]
    class Header(ctypes.Structure): _fields_=[('version',ctypes.c_uint32),('pid',ctypes.c_int)]
    class Data(ctypes.Structure): _fields_=[('effective',ctypes.c_uint32),('permitted',ctypes.c_uint32),('inheritable',ctypes.c_uint32)]
    libc.capset.argtypes=[ctypes.POINTER(Header),ctypes.POINTER(Data)]
    def checked(result):
        if result!=0: raise OSError(ctypes.get_errno(),'compute capability drop failed')
    checked(libc.prctl(38,1,0,0,0))  # PR_SET_NO_NEW_PRIVS
    os.setgroups([]);os.setresgid(gid,gid,gid);os.setresuid(uid,uid,uid)
    checked(libc.prctl(47,4,0,0,0))  # PR_CAP_AMBIENT_CLEAR_ALL
    header=Header(0x20080522,0);empty=(Data*2)()
    checked(libc.capset(ctypes.byref(header),empty))
    status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines())
    if (any(int(status[key].strip(),16)!=0 for key in ('CapEff','CapPrm','CapInh','CapAmb'))
            or status['NoNewPrivs'].strip()!='1'
            or any(int(value)!=uid for value in status['Uid'].split())
            or any(int(value)!=gid for value in status['Gid'].split()) or status['Groups'].strip()):
        raise ValueError('compute_privilege_drop_unverified')


def main():
    import argparse
    parser=argparse.ArgumentParser()
    for key in ('gate-fd','uid','gid'): parser.add_argument('--'+key,type=int,required=True)
    for key in ('config','worker'): parser.add_argument('--'+key,required=True)
    args=parser.parse_args()
    if os.getpid()!=1 or args.uid<=0 or args.gid<=0: raise ValueError('private_compute_namespace_required')
    drop_compute_privileges(args.uid,args.gid)
    # No provider/app/config import before the independent broker admission.
    with socket.socket(fileno=args.gate_fd) as gate:
        gate.settimeout(5);gate.sendall(b'R')
        if gate.recv(1)!=b'A': raise ValueError('compute_not_admitted')
    from .operations import load_config,run_compute
    import asyncio
    config=load_config(args.config,'compute')
    asyncio.run(run_compute(config,args.worker))


if __name__=='__main__': main()
