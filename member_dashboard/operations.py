"""Fixed Linux role composition. Missing external evidence is unavailable.

No provider credentials, imports, shell commands, grant flags or arbitrary URLs
are accepted from configuration. A live denial authority never implies a grant.
"""
import argparse
import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import time
from .launch import read_private_json,protected

COMMON={'role','uid'}
WEB={'web_path','authority_socket','authority_uid'}
FIELDS={
 'api':COMMON|WEB|{'origin','signing_key'},
 'supervisor':COMMON|WEB|{'market_path','cgroup_root','compute_uid','compute_gid','compute_config','control_socket','quota_uid'},
 'compute':COMMON|WEB,
 'quota':COMMON|{'quota_path','budget_socket','control_socket','supervisor_uid','compute_uid','bot_uid','cgroup_root'},
 'authority':COMMON|{'journal_path','anchor_path','checkpoint_path','socket_path','read_uids','write_uids'},
 'archive':COMMON|{'archive_root','key_path','node_path'},
}


def validate_config(config):
    role=config.get('role')
    if role not in FIELDS or set(config)!=FIELDS[role]: raise ValueError('invalid_fixed_role_config')
    for key,value in config.items():
        if key=='uid' or key.endswith('_uid') or key.endswith('_gid'):
            if type(value) is not int or value<0: raise ValueError('invalid_role_identity')
        if key.endswith(('_path','_root','_socket','_config')) or key=='signing_key':
            if not isinstance(value,str) or not Path(value).is_absolute() or '..' in Path(value).parts:
                raise ValueError('explicit_absolute_path_required')
        if key.endswith('_uids'):
            if not isinstance(value,list) or not 1<=len(value)<=8 or any(type(v) is not int or v<0 for v in value):
                raise ValueError('invalid_authority_identities')
    if role=='supervisor' and len({config['uid'],config['compute_uid'],config['quota_uid'],config['authority_uid']})!=4:
        raise ValueError('distinct_runtime_identities_required')
    if role=='quota' and len({config['uid'],config['supervisor_uid'],config['compute_uid'],config['bot_uid']})!=4:
        raise ValueError('distinct_quota_identities_required')
    if role in ('api','compute') and config['uid']==config['authority_uid']: raise ValueError('distinct_authority_identity_required')
    if role=='authority' and config['uid'] in config['read_uids']: raise ValueError('separate_authority_writer_required')
    return config


def load_config(path,role):
    config=validate_config(read_private_json(Path(path)))
    if os.name!='posix' or not hasattr(os,'getuid'): raise ValueError('linux_role_required')
    if config['role']!=role or os.getuid()!=config['uid']: raise ValueError('wrong_role_identity')
    return config


def web_store(config):
    from .store import WebStore
    from .authority_rpc import AuthorityClient
    store=WebStore(Path(config['web_path']));store.migrate()
    store.bind_authority(AuthorityClient(config['authority_socket'],config['authority_uid']))
    return store


def api_app(config):
    from .app import create_app
    from .settings import Settings
    from .runtime import FrontendObservation
    from .authority_rpc import AuthorityClient
    # API config has no source mount or compute configuration. This sentinel is
    # only the Settings path inequality guard; no MarketReader is constructed.
    web=Path(config['web_path'])
    key_path=protected(Path(config['signing_key']))
    if key_path.stat().st_size!=32: raise ValueError('signing_key_requires_32_bytes')
    key=key_path.read_bytes()
    if len(key)!=32: raise ValueError('signing_key_requires_32_bytes')
    app=create_app(Settings(web_path=web,market_path=web.parent/'no-market-access',origin=config['origin'],feed_signing_key=key))
    authority=AuthorityClient(config['authority_socket'],config['authority_uid'])
    observation=FrontendObservation();app.state.admin.frontend_observation=observation.snapshot
    app.state.source_policy.authority_current=lambda:False
    for service in (app.state.admin,app.state.history,app.state.source_policy): service.denial_journal=authority
    @asynccontextmanager
    async def lifespan(_):
        import anyio.to_thread
        anyio.to_thread.current_default_thread_limiter().total_tokens=4
        app.state.store.migrate();app.state.store.bind_authority(authority)
        async def monitor():
            while True:
                await asyncio.to_thread(observation.probe);await asyncio.sleep(5)
        task=asyncio.create_task(monitor())
        try: yield
        finally: task.cancel();await asyncio.gather(task,return_exceptions=True)
    app.router.lifespan_context=lifespan
    return app


async def run_compute(config,worker):
    from uuid import UUID
    if str(UUID(worker))!=worker or os.getpid()!=1: raise ValueError('gated_compute_required')
    from .providers import ProviderRegistry
    from .provider_runtime import ProviderRuntime
    from .jobs import JobService
    from .source_policy import SourcePolicy
    from .auth import AuthService
    from .worker import ComputeWorker
    store=web_store(config)
    registry=ProviderRegistry()  # No real provider/account/egress evidence supplied.
    policy=SourcePolicy(store);policy.authority_current=lambda:False
    policy.denial_journal=store.authority
    runtime=ProviderRuntime(store,worker)
    jobs=JobService(store,AuthService(store),policy,registry)
    await ComputeWorker(jobs,registry,runtime).serve()


def supervisor(config):
    from .compute_launcher import CgroupLauncher,ExitClient
    from .worker import WorkerSupervisor
    from .source_policy import SourcePolicy
    from .auth import AuthService
    from .market_reader import MarketReader
    from .publication import FeedService
    from .jobs import JobService
    store=web_store(config)
    control=ExitClient(config['control_socket'],config['quota_uid'])
    launcher=CgroupLauncher(config['cgroup_root'],compute_uid=config['compute_uid'],compute_gid=config['compute_gid'],
        config=config['compute_config'],control=control)
    policy=SourcePolicy(store);policy.authority_current=lambda:False
    policy.denial_journal=store.authority
    feed=FeedService(store,AuthService(store),policy,signing_key=b'not-used-for-member-cursors-000000',reader=MarketReader(Path(config['market_path'])))
    worker=WorkerSupervisor(store,launcher,feed.feed_tick,reconcile=control.reconcile)
    try:
        while True:
            if worker.child is None and not launcher.recover():
                feed.feed_tick(time.time());time.sleep(1);continue
            worker.tick();time.sleep(.1)
    finally:
        if worker.child is not None:
            worker.child.kill_tree()
            deadline=time.monotonic()+5
            while not worker.child.is_dead() and time.monotonic()<deadline: time.sleep(.05)
            if worker.child.is_dead():
                JobService(store,None,None,None).confirm_worker_exit(worker.child.worker_id,time.time(),reconciled=False)
                worker.child.close()


def quota(config):
    from .store import WebStore
    from .quota_broker import QuotaBroker,BrokerServer
    from .exit_control import ExitRegistry,ExitControlServer
    protected(Path(config['quota_path']))  # Never silently replace a lost ledger.
    store=WebStore(Path(config['quota_path']));store.migrate()
    # Historical local booleans are not current account evidence. Keep all
    # accounting, but no allocation can reopen without the missing trusted
    # external account-policy integration.
    with store.transaction() as con:
        con.execute('UPDATE provider_quota_policy SET verified=0')
        con.execute('UPDATE quota_endpoints SET participation_verified=0')
    broker=QuotaBroker(store)
    registry=ExitRegistry(broker,supervisor_uid=config['supervisor_uid'],compute_uid=config['compute_uid'],cgroup_root=Path(config['cgroup_root']))
    with BrokerServer(broker,config['budget_socket'],uid_roles={config['compute_uid']:'dashboard',config['bot_uid']:'bot'}), ExitControlServer(registry,config['control_socket']):
        while True: time.sleep(1)


def authority(config):
    from .authority import DenialJournal,CheckpointStore
    from .authority_rpc import AuthorityService,AuthorityServer
    journal=DenialJournal(config['journal_path'],config['anchor_path'],checkpoint=CheckpointStore(config['checkpoint_path']))
    journal.current()  # Never auto-initialize lost current authority.
    service=AuthorityService(journal,read_uids=config['read_uids'],write_uids=config['write_uids'])
    with AuthorityServer(service,config['socket_path']):
        while True:
            time.sleep(60);journal.renew()  # Denial continuity only, no positive rights.


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('role',choices=FIELDS);parser.add_argument('--config',required=True,type=Path)
    args=parser.parse_args();config=load_config(args.config,args.role)
    if args.role=='api':
        import uvicorn
        uvicorn.run(api_app(config),host='127.0.0.1',port=3445,workers=1,access_log=False,log_level='warning')
    elif args.role=='supervisor': supervisor(config)
    elif args.role=='quota': quota(config)
    elif args.role=='authority': authority(config)
    elif args.role=='archive':
        from .backup import maintain_archives
        maintain_archives(config['archive_root'],key_path=Path(config['key_path']),node=Path(config['node_path']))
    else: raise ValueError('compute_requires_kernel_gate')


if __name__=='__main__': main()
