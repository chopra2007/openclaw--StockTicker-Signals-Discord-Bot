"""Real threads, cancellation and process termination; no remote providers."""
import asyncio
import importlib.util
import threading

import pytest


def test_runtime_contract_is_available():
    assert importlib.util.find_spec('member_dashboard.provider_runtime') is not None


async def wait_until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(.005)


@pytest.mark.asyncio
async def test_timeout_keeps_actual_capacity_and_zero_executor_queue(dashboard):
    from member_dashboard.provider_runtime import ProviderRuntime
    runtime = ProviderRuntime(dashboard.store, 'worker', clock=dashboard.clock)
    release = [threading.Event(), threading.Event()]
    started = [threading.Event(), threading.Event()]
    def block(index):
        started[index].set()
        assert release[index].wait(5)
        return index
    try:
        a, b = await asyncio.gather(*(runtime.run_blocking(str(i), lambda i=i: block(i), .02) for i in range(2)))
        assert a.status == b.status == 'timeout'
        assert not a.actual_completed and runtime.running_count == 2
        third = await runtime.run_blocking('third', lambda: 3, .02)
        retry = await runtime.run_blocking('0', lambda: 10, .02)
        assert third.status == 'busy' and retry.status == 'timeout'
        assert runtime.executor_queue_size == 0
        release[0].set()
        await wait_until(lambda: runtime.running_count == 1)
        assert (await runtime.run_blocking('third', lambda: 3, 1)).value == 3
        assert runtime.max_running_count == 2
    finally:
        for event in release: event.set()
        await wait_until(lambda: runtime.running_count == 0)
        runtime.shutdown()


@pytest.mark.asyncio
async def test_async_and_blocking_calls_share_the_same_two_slots(dashboard):
    from member_dashboard.provider_runtime import ProviderRuntime
    runtime = ProviderRuntime(dashboard.store, 'worker', clock=dashboard.clock)
    release = threading.Event()
    async_release = asyncio.Event()
    async def async_work():
        await async_release.wait()
        return 'async'
    try:
        await runtime.run_blocking('thread', lambda: release.wait(5), .01)
        await runtime.run_async('model', async_work, .01)
        assert (await runtime.run_async('other-model', async_work, .01)).status == 'busy'
        assert runtime.running_count == 2
    finally:
        release.set()
        async_release.set()
        await wait_until(lambda: runtime.running_count == 0)
        runtime.shutdown()


@pytest.mark.asyncio
async def test_cancel_before_submit_and_shutdown_do_not_claim_completion(dashboard):
    from member_dashboard.provider_runtime import ProviderRuntime
    runtime = ProviderRuntime(dashboard.store, 'worker', clock=dashboard.clock)
    ran = threading.Event()
    task = asyncio.create_task(runtime.run_blocking('cancelled', ran.set, 1))
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert not ran.is_set() and runtime.running_count == 0
    release = threading.Event()
    try:
        await runtime.run_blocking('active', lambda: release.wait(5), .01)
        runtime.shutdown()
        assert runtime.running_count == 1
        assert (await runtime.run_blocking('late', ran.set, 1)).status == 'closed'
    finally:
        release.set()
        await wait_until(lambda: runtime.running_count == 0)


@pytest.mark.asyncio
async def test_stuck_call_opens_persistent_circuit_after_fake_grace(dashboard):
    from member_dashboard.provider_runtime import ProviderRuntime
    runtime = ProviderRuntime(dashboard.store, 'worker', clock=dashboard.clock)
    release = threading.Event()
    try:
        await runtime.run_blocking('stuck', lambda: release.wait(5), .01, provider='fixture')
        dashboard.clock.advance(121)
        assert runtime.check_drains() is True
        assert (await runtime.run_blocking('other', lambda: 1, 1, provider='fixture')).status == 'circuit_open'
    finally:
        release.set()
        await wait_until(lambda: runtime.running_count == 0)
        runtime.shutdown()
    replacement = ProviderRuntime(dashboard.store, 'replacement', clock=dashboard.clock)
    assert (await replacement.run_blocking('restart', lambda: 1, 1, provider='fixture')).status == 'circuit_open'
    replacement.shutdown()


@pytest.mark.asyncio
async def test_waiter_cancellation_preserves_running_thread_and_retrieves_exception(dashboard):
    from member_dashboard.provider_runtime import ProviderRuntime
    runtime = ProviderRuntime(dashboard.store, 'worker', clock=dashboard.clock)
    started, release = threading.Event(), threading.Event()
    def fails_late():
        started.set()
        assert release.wait(5)
        raise RuntimeError('synthetic private failure')
    task = asyncio.create_task(runtime.run_blocking('call', fails_late, 3))
    try:
        await wait_until(started.is_set)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert runtime.running_count == 1
        release.set()
        await wait_until(lambda: runtime.outcome('call') is not None)
        assert runtime.outcome('call').status == 'failed'
        assert 'synthetic' not in repr(runtime.outcome('call'))
    finally:
        release.set()
        runtime.shutdown()


@pytest.mark.asyncio
async def test_circuit_requires_bounded_probe_not_worker_boot(dashboard):
    from member_dashboard.provider_runtime import ProviderRuntime
    runtime = ProviderRuntime(dashboard.store, 'worker', clock=dashboard.clock)
    with dashboard.store.transaction() as con:
        con.execute("INSERT INTO provider_circuits VALUES ('fixture',?,?,'open')", (dashboard.clock(),dashboard.clock()+60))
    try:
        assert (await runtime.health_probe('fixture','early',lambda: True)).status == 'circuit_open'
        dashboard.clock.advance(61)
        assert (await runtime.health_probe('fixture','probe',lambda: True)).actual_completed
        assert (await runtime.run_blocking('normal',lambda: 7,1,provider='fixture')).value == 7
    finally:
        runtime.shutdown()


@pytest.mark.asyncio
async def test_supervisor_keeps_feed_running_and_kills_descendants_before_replacement(dashboard, tmp_path):
    import json
    import os
    import sys
    from member_dashboard.worker import ProcessTree, WorkerSupervisor
    marker = tmp_path/'child.json'
    child = (
        "import os,signal,subprocess,sys,time,json; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        "p=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)']); "
        "open(sys.argv[1],'w').write(json.dumps([os.getpid(),p.pid])); time.sleep(30)"
    )
    launched, ticks = [], []
    def factory():
        if launched:
            assert launched[-1].is_dead(), 'replacement launched before old process tree death'
        process = ProcessTree.start([sys.executable,'-c',child,str(marker)])
        launched.append(process)
        return process
    supervisor = WorkerSupervisor(dashboard.store, factory, lambda now: ticks.append(now),
                                  jobs=dashboard.app.state.research,clock=dashboard.clock, stop_timeout=2, reconcile=lambda _: True)
    try:
        supervisor.tick()
        await wait_until(marker.exists)
        old = json.loads(marker.read_text())
        assert old[0] != os.getpid()
        supervisor.request_restart()
        supervisor.tick()
        dashboard.clock.advance(5)
        supervisor.tick()
        await wait_until(launched[0].is_dead)
        supervisor.tick()
        assert len(launched) == 2
        assert len(ticks) >= 2
        assert supervisor.last_exit_confirmed is True
    finally:
        for process in launched:
            process.kill_tree()
        for process in launched:
            await wait_until(process.is_dead)
            process.close()


@pytest.mark.asyncio
async def test_supervisor_restart_blocks_when_quota_uncertainty_is_unreconciled(dashboard):
    import sys
    from member_dashboard.worker import ProcessTree, WorkerSupervisor
    launched = []
    def factory():
        process = ProcessTree.start([sys.executable,'-c','import time; time.sleep(30)'])
        launched.append(process)
        return process
    supervisor = WorkerSupervisor(dashboard.store, factory, lambda now: None, jobs=dashboard.app.state.research,clock=dashboard.clock)
    supervisor.tick()
    process = launched[0]
    with dashboard.store.transaction() as con:
        con.execute("INSERT INTO provider_calls(call_id,worker_id,provider,status,started_at) VALUES ('unknown',?,'fixture','running',?)", (process.worker_id,dashboard.clock()))
    try:
        process.kill_tree()
        await wait_until(process.is_dead)
        supervisor.tick()
        assert len(launched) == 1 and supervisor.blocked
        with dashboard.store.transaction() as con:
            assert con.execute("SELECT status FROM provider_calls WHERE call_id='unknown'").fetchone()[0] == 'uncertain'
    finally:
        process.kill_tree()
        await wait_until(process.is_dead)
        process.close()


@pytest.mark.asyncio
async def test_supervisor_detects_persisted_drain_and_preserves_feed_on_reconcile_error(dashboard):
    import sys
    from member_dashboard.worker import ProcessTree, WorkerSupervisor
    process = ProcessTree.start([sys.executable,'-c','import time; time.sleep(30)'])
    feeds = []
    supervisor = WorkerSupervisor(dashboard.store,lambda:process,feeds.append,jobs=dashboard.app.state.research,clock=dashboard.clock,
                                  reconcile=lambda _: (_ for _ in ()).throw(RuntimeError('broker offline')))
    supervisor.tick()
    with dashboard.store.transaction() as con:
        con.execute("INSERT INTO provider_calls(call_id,worker_id,provider,status,started_at,draining_at) VALUES ('stuck',?,'fixture','draining',?,?)", (process.worker_id,dashboard.clock()-200,dashboard.clock()-121))
    try:
        supervisor.tick()
        # PID-namespace launchers may inherit SIGTERM ignored. Exercise the
        # promised bounded hard-stop path, without assuming graceful termination.
        dashboard.clock.advance(6)
        supervisor.tick()
        await wait_until(process.is_dead)
        supervisor.tick()
        assert supervisor.blocked
        dashboard.clock.advance(5)
        supervisor.tick()
        assert len(feeds) >= 2
    finally:
        process.kill_tree()
        await wait_until(process.is_dead)
        process.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('healthy',[False,True])
async def test_cancelled_probe_settles_after_actual_completion_and_reopens_after_restart(dashboard,healthy):
    from member_dashboard.provider_runtime import ProviderRuntime
    runtime=ProviderRuntime(dashboard.store,'worker',clock=dashboard.clock)
    with dashboard.store.transaction() as con:
        con.execute("INSERT INTO provider_circuits VALUES ('fixture',?,?,'open')",(dashboard.clock()-70,dashboard.clock()-1))
    started,release=threading.Event(),threading.Event()
    def probe():
        started.set()
        assert release.wait(5)
        return healthy
    task=asyncio.create_task(runtime.health_probe('fixture','cancelled-probe',probe))
    try:
        await wait_until(started.is_set)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert runtime.running_count==1
        assert (await runtime.health_probe('fixture','overlap',lambda:True)).status=='circuit_open'
        release.set()
        await wait_until(lambda:runtime.running_count==0)
        with dashboard.store.transaction() as con:
            assert con.execute("SELECT status FROM provider_circuits WHERE provider='fixture'").fetchone()[0] == ('closed' if healthy else 'open')
    finally:
        release.set()
        runtime.shutdown()
    replacement=ProviderRuntime(dashboard.store,'new-worker',clock=dashboard.clock)
    try:
        if not healthy:
            dashboard.clock.advance(61)
            assert (await replacement.health_probe('fixture','next-probe',lambda:True)).status=='completed'
        assert (await replacement.run_blocking('normal',lambda:7,1,provider='fixture')).value==7
    finally:
        replacement.shutdown()


@pytest.mark.asyncio
async def test_probe_cancellation_before_submission_restores_cooldown(dashboard):
    from member_dashboard.provider_runtime import ProviderRuntime
    runtime=ProviderRuntime(dashboard.store,'worker',clock=dashboard.clock)
    with dashboard.store.transaction() as con:
        con.execute("INSERT INTO provider_circuits VALUES ('fixture',?,?,'open')",(dashboard.clock()-70,dashboard.clock()-1))
    executed=threading.Event()
    task=asyncio.create_task(runtime.health_probe('fixture','never-submitted',executed.set))
    try:
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert not executed.is_set() and runtime.running_count==0
        with dashboard.store.transaction() as con:
            assert con.execute('SELECT count(*) FROM provider_probes').fetchone()[0]==0
            assert con.execute("SELECT status,probe_after FROM provider_circuits WHERE provider='fixture'").fetchone()==('open',dashboard.clock()+60)
    finally:
        runtime.shutdown()


@pytest.mark.asyncio
async def test_probe_process_death_requires_reconciliation_then_recovers(dashboard,tmp_path):
    import sys
    from member_dashboard.jobs import JobService
    from member_dashboard.provider_runtime import ProviderRuntime
    from member_dashboard.worker import ProcessTree
    with dashboard.store.transaction() as con:
        con.execute("INSERT INTO provider_circuits VALUES ('fixture',?,?,'open')",(dashboard.clock()-70,dashboard.clock()-1))
    marker=tmp_path/'probe-started'
    script='''
import asyncio,sys,time
from pathlib import Path
from member_dashboard.store import WebStore
from member_dashboard.provider_runtime import ProviderRuntime
store,marker,worker,now=sys.argv[1:]
runtime=ProviderRuntime(WebStore(Path(store)),worker,clock=lambda:float(now))
def probe():
    Path(marker).write_text('started')
    time.sleep(30)
    return True
asyncio.run(runtime.health_probe('fixture','dead-probe',probe))
'''
    process=ProcessTree.start([sys.executable,'-c',script,str(dashboard.settings.web_path),str(marker),'probe-worker',str(dashboard.clock())],worker_id='probe-worker')
    try:
        await wait_until(marker.exists)
        process.kill_tree()
        await wait_until(process.is_dead)
        jobs=JobService(dashboard.store,None,None,None)
        jobs.confirm_worker_exit(process.worker_id,dashboard.clock())
        with dashboard.store.transaction() as con:
            assert con.execute("SELECT status FROM provider_calls WHERE call_id='dead-probe'").fetchone()[0]=='uncertain'
            assert con.execute("SELECT status FROM provider_circuits WHERE provider='fixture'").fetchone()[0]=='probing'
        jobs.confirm_worker_exit(process.worker_id,dashboard.clock(),reconciled=True)
        with dashboard.store.transaction() as con:
            assert con.execute('SELECT count(*) FROM provider_probes').fetchone()[0]==0
            assert con.execute("SELECT status FROM provider_circuits WHERE provider='fixture'").fetchone()[0]=='open'
        dashboard.clock.advance(61)
        replacement=ProviderRuntime(dashboard.store,'replacement',clock=dashboard.clock)
        try:
            assert (await replacement.health_probe('fixture','healthy',lambda:True)).value is True
            assert (await replacement.run_blocking('normal',lambda:7,1,provider='fixture')).value==7
        finally:
            replacement.shutdown()
    finally:
        process.kill_tree()
        await wait_until(process.is_dead)
        process.close()


@pytest.mark.parametrize('actual_status',['completed','running',None])
def test_upgrade_repairs_orphaned_probe_only_after_confirmed_reconciled_exit(dashboard,actual_status):
    from member_dashboard.jobs import JobService
    from member_dashboard.provider_runtime import ProviderRuntime
    with dashboard.store.transaction() as con:
        con.execute("INSERT INTO provider_circuits VALUES ('fixture',?,?,'probing')",(dashboard.clock()-70,dashboard.clock()-1))
        if actual_status:
            con.execute('INSERT INTO provider_calls(call_id,worker_id,provider,status,started_at) VALUES (?,?,?,?,?)',('legacy-probe','old-worker','fixture',actual_status,dashboard.clock()-70))
    runtime=ProviderRuntime(dashboard.store,'new-worker',clock=dashboard.clock)
    try:
        with dashboard.store.transaction() as con:
            assert con.execute("SELECT status FROM provider_circuits WHERE provider='fixture'").fetchone()[0]=='probing'
        jobs=JobService(dashboard.store,None,None,None)
        jobs.confirm_worker_exit('old-worker',dashboard.clock())
        with dashboard.store.transaction() as con:
            assert con.execute("SELECT status FROM provider_circuits WHERE provider='fixture'").fetchone()[0]=='probing'
        jobs.confirm_worker_exit('old-worker',dashboard.clock(),reconciled=True)
        with dashboard.store.transaction() as con:
            assert con.execute("SELECT status,probe_after FROM provider_circuits WHERE provider='fixture'").fetchone()==('open',dashboard.clock()+60)
    finally:
        runtime.shutdown()
