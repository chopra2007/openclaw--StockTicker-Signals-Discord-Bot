"""Fixed role assembly. Synthetic staging is runnable; production stays closed.

No credential discovery, plugins, shell commands or provider imports from config.
"""
import argparse
import asyncio
from contextlib import asynccontextmanager
import http.client
import json
import os
from pathlib import Path
import sys
import time
import threading
from uuid import uuid4

from .launch import read_private_json, private_output, validate_staging


def load_config(path):
    config=read_private_json(path)
    if set(config)!={'mode','origin','nonce','certificate_sha256','expires_at','run_directory'}:
        raise ValueError('invalid_runtime_config')
    validate_staging(config['origin'],config)
    run=Path(config['run_directory'])
    if not run.is_absolute() or run.is_symlink() or run.resolve()!=Path(path).parent.resolve():
        raise ValueError('unsafe_runtime_directory')
    return config


class FrontendObservation:
    """One fixed local Next endpoint. Admin reads cached observation only."""
    def __init__(self): self.observed_at=None

    def probe(self):
        connection=http.client.HTTPConnection('127.0.0.1',3444,timeout=.5)
        try:
            connection.request('GET','/healthz')
            response=connection.getresponse()
            if response.status==200 and response.read(128)==b'{"component":"member-dashboard-frontend"}':
                self.observed_at=time.time()
        except (OSError,http.client.HTTPException): pass
        finally: connection.close()

    def snapshot(self,now):
        from .admin_contracts import Observation
        when=self.observed_at
        if when is None or when>now: return Observation(status='unavailable')
        return Observation(status='responsive' if now-when<15 else 'stale',observed_at=when)


def staging_app(config_path):
    config=load_config(config_path)
    run=Path(config['run_directory'])
    from .synthetic import create_synthetic
    from .worker import ProcessTree,WorkerSupervisor
    app=create_synthetic(run)
    journal=staging_journal(app,run,initialize=True)
    observations=FrontendObservation()
    app.state.admin.frontend_observation=observations.snapshot
    children={}

    def factory():
        if len(children)>=3: raise ValueError('synthetic_restart_budget_exhausted')
        worker=str(uuid4())
        process=ProcessTree.start([sys.executable,'-m','member_dashboard.runtime','compute',
            '--config',str(config_path),'--worker-id',worker],worker_id=worker)
        children[worker]=process
        # Staging-only mapping + admission handshake. Child cannot run providers
        # until the trusted parent persists its exact owned ProcessTree mapping.
        deadline=time.monotonic()+5
        ready=run/(worker+'.ready.json')
        while not ready.exists():
            if process.is_dead() or time.monotonic()>deadline:
                process.kill_tree()
                raise ValueError('gated_child_unavailable')
            time.sleep(.05)
        pid=read_private_json(ready).get('pid')
        if not process.contains_pid(pid):
            process.kill_tree()
            raise ValueError('gated_child_outside_tree')
        private_output(run,run/(worker+'.owner.json'),{'worker':worker,'pid':pid,'mode':'synthetic-staging'})
        private_output(run,run/(worker+'.admit.json'),{'worker':worker,'mode':'synthetic-staging'})
        return process

    def reconcile(worker):
        child=children.get(worker)
        # Synthetic operations have no external requests/quota. Production is
        # denied by config validation and requires independent exit control.
        return child is not None and child.is_dead()

    supervisor=WorkerSupervisor(app.state.store,factory,lambda now:None,jobs=app.state.research,reconcile=reconcile)
    app.state.synthetic_supervisor=supervisor
    def metrics():
        if supervisor.child is None: return None
        path=run/(supervisor.child.worker_id+'.metrics.json')
        if not path.is_file() or path.stat().st_size>2048: return None
        value=json.loads(path.read_text())
        return value if time.time()-value['observed_at']<15 else None
    app.state.synthetic_metrics=metrics

    @asynccontextmanager
    async def lifespan(_):
        import anyio.to_thread
        anyio.to_thread.current_default_thread_limiter().total_tokens=4
        async def supervise():
            renewed=time.monotonic()
            while True:
                supervisor.tick()
                if time.monotonic()-renewed>=60:
                    journal.renew();renewed=time.monotonic()
                await asyncio.sleep(.1)
        async def frontend():
            while True:
                await asyncio.to_thread(observations.probe)
                await asyncio.sleep(5)
        tasks=[asyncio.create_task(supervise()),asyncio.create_task(frontend())]
        try: yield
        finally:
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            for child in children.values():
                child.kill_tree()
            deadline=time.monotonic()+5
            while any(not child.is_dead() for child in children.values()) and time.monotonic()<deadline:
                await asyncio.sleep(.05)
            for child in children.values(): child.close()
    app.router.lifespan_context=lifespan
    @app.get('/__fixture/identity')
    def identity():
        return {key:config[key] for key in ('mode','origin','nonce','certificate_sha256','expires_at')}
    return app


async def compute(config_path,worker):
    config=load_config(config_path)
    from uuid import UUID
    if str(UUID(worker))!=worker: raise ValueError('invalid_worker')
    run=Path(config['run_directory'])
    private_output(run,run/(worker+'.ready.json'),{'pid':os.getpid()})
    deadline=time.monotonic()+10
    while not (run/(worker+'.admit.json')).exists():
        if time.monotonic()>deadline: raise ValueError('admission_handshake_missing')
        await asyncio.sleep(.05)
    owner=read_private_json(run/(worker+'.owner.json'))
    admission=read_private_json(run/(worker+'.admit.json'))
    if owner!={'worker':worker,'pid':os.getpid(),'mode':'synthetic-staging'} or admission!={'worker':worker,'mode':'synthetic-staging'}:
        raise ValueError('admission_identity_mismatch')
    from .synthetic import create_synthetic
    app=create_synthetic(run,initialize=False,worker_id=worker)
    staging_journal(app,run,initialize=False)
    runtime=app.state.synthetic_worker.runtime
    async def telemetry():
        while True:
            value={'observed_at':time.time(),'python_threads':threading.active_count(),
                'executor_queue':runtime.executor_queue_size,'max_actual_operations':runtime.max_running_count}
            temporary=run/(str(uuid4())+'.metrics.tmp')
            fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'w') as stream: json.dump(value,stream)
            os.replace(temporary,run/(worker+'.metrics.json'))
            await asyncio.sleep(5)
    task=asyncio.create_task(telemetry())
    try: await app.state.synthetic_worker.serve()
    finally:
        task.cancel();await asyncio.gather(task,return_exceptions=True)


def staging_journal(app,run,*,initialize):
    """Staging updater only; never confers a real source grant."""
    from .authority import DenialJournal,CheckpointStore
    from .launch import secure_directory
    directory=run/'authority'
    if initialize:
        directory.mkdir(mode=0o700)
        secure_directory(directory)
        checkpoint=CheckpointStore.create(run/'authority-high-water.sqlite3')
        journal=DenialJournal.create(directory/'denials.sqlite3',directory/'anchor.json',checkpoint=checkpoint)
    else: journal=DenialJournal(directory/'denials.sqlite3',directory/'anchor.json',checkpoint=CheckpointStore(run/'authority-high-water.sqlite3'))
    app.state.store.bind_authority(journal)
    app.state.admin.denial_journal=journal
    app.state.history.denial_journal=journal
    app.state.source_policy.denial_journal=journal
    cached_stamp=None;cached_until=0
    def staging_current():
        nonlocal cached_stamp,cached_until
        try:
            info=journal.anchor.stat();stamp=(info.st_ino,info.st_mtime_ns,info.st_size)
            now=time.time()
            if stamp!=cached_stamp or now>=cached_until:
                journal.current()
                anchor=json.loads(journal.anchor.read_text())
                cached_until=min(now+5,anchor['expires_at']);cached_stamp=stamp
            return now<cached_until
        except (OSError,ValueError): return False
    # Only synthetic permissions were installed by create_synthetic. This
    # freshness check never upgrades the default production SourcePolicy.
    app.state.source_policy.authority_current=staging_current
    return journal


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('role',choices=('api','supervisor','compute','quota'))
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--worker-id')
    args=parser.parse_args()
    load_config(args.config)
    if args.role=='api':
        import uvicorn
        uvicorn.run(staging_app(args.config),host='127.0.0.1',port=3445,workers=1,access_log=False,log_level='warning')
    elif args.role=='compute':
        try: asyncio.run(compute(args.config,args.worker_id))
        except BaseException as error:
            private_output(args.config.parent,args.config.parent/(str(uuid4())+'.error.json'),
                {'code':type(error).__name__,'detail':str(error)[:500]})
            raise
    else: raise ValueError('production_role_unconfigured')


if __name__=='__main__': main()
