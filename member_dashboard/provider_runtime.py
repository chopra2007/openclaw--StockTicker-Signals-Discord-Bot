"""Actual-work authority shared by blocking and asynchronous provider calls.

Waiters do not own capacity. Only the original future's completion callback or
a supervisor-confirmed process exit may release it. No executor backlog exists.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import threading
import time


@dataclass(frozen=True)
class ProviderOutcome:
    status: str
    actual_completed: bool
    value: object = None


class ProviderRuntime:
    def __init__(self, store, worker_id, *, clock=time.time):
        self.store, self.worker_id, self.clock = store, worker_id, clock
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='web-provider')
        self._lock = threading.RLock()
        self._futures = {}
        self._outcomes = {}
        self._closed = False
        self.max_running_count = 0

    @property
    def running_count(self):
        with self.store.transaction() as con:
            return con.execute("SELECT count(*) FROM provider_calls WHERE status IN ('running','draining','uncertain')").fetchone()[0]

    @property
    def executor_queue_size(self):
        return self.executor._work_queue.qsize()

    def _reserve(self, call_id, provider, *, probe=False):
        with self.store.transaction() as con:
            if con.execute('SELECT 1 FROM provider_calls WHERE call_id=?', (call_id,)).fetchone():
                return 'uncertain'
            circuit = con.execute('SELECT status FROM provider_circuits WHERE provider=?', (provider,)).fetchone()
            if circuit and circuit[0] != 'closed' and not probe:
                return 'circuit_open'
            active = con.execute("SELECT count(*) FROM provider_calls WHERE status IN ('running','draining','uncertain')").fetchone()[0]
            if active >= 2:
                return 'busy'
            con.execute("INSERT INTO provider_calls(call_id,worker_id,provider,status,started_at) VALUES (?,?,?,'running',?)",
                        (call_id, self.worker_id, provider, self.clock()))
            self.max_running_count = max(self.max_running_count, active+1)
        return None

    def _completed(self, call_id, future):
        # Retrieve exceptions even when every coroutine waiting for this call left.
        try:
            value = future.result()
            outcome = ProviderOutcome('completed', True, value)
        except BaseException:
            outcome = ProviderOutcome('failed', True)
        with self._lock:
            with self.store.transaction() as con:
                con.execute('UPDATE provider_calls SET status=?,completed_at=? WHERE call_id=? AND worker_id=?',
                            (outcome.status, self.clock(), call_id, self.worker_id))
            self._outcomes[call_id] = outcome

    def outcome(self, call_id):
        with self._lock:
            return self._outcomes.get(call_id)

    def forget(self, call_id):
        """Worker calls only after durable result/failure persistence."""
        with self._lock:
            if call_id in self._outcomes:
                self._outcomes.pop(call_id)
                self._futures.pop(call_id, None)

    def _draining(self, call_id):
        with self.store.transaction() as con:
            con.execute("UPDATE provider_calls SET status='draining',draining_at=coalesce(draining_at,?) WHERE call_id=? AND status='running'",
                        (self.clock(), call_id))

    async def _run(self, call_id, operation, wait_timeout, provider, asynchronous, probe=False):
        if not 0 < wait_timeout <= 180:
            raise ValueError('finite wait timeout required')
        # A pending cancellation must be observed before reserving/submitting.
        await asyncio.sleep(0)
        with self._lock:
            existing = self._outcomes.get(call_id)
            if existing:
                return existing
            future = self._futures.get(call_id)
            if future is None:
                if self._closed:
                    return ProviderOutcome('closed', False)
                denied = self._reserve(call_id, provider, probe=probe)
                if denied:
                    return ProviderOutcome(denied, False)
                try:
                    future = asyncio.create_task(operation()) if asynchronous else self.executor.submit(operation)
                except BaseException:
                    with self.store.transaction() as con:
                        con.execute("UPDATE provider_calls SET status='failed',completed_at=? WHERE call_id=?", (self.clock(), call_id))
                    raise
                self._futures[call_id] = future
                future.add_done_callback(lambda done: self._completed(call_id, done))
        wrapper = future if isinstance(future, asyncio.Future) else asyncio.wrap_future(future)
        # The wrapper also observes exceptions independently of the waiter.
        wrapper.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            await asyncio.wait_for(asyncio.shield(wrapper), timeout=wait_timeout)
        except TimeoutError:
            self._draining(call_id)
            return ProviderOutcome('timeout', False)
        except asyncio.CancelledError:
            self._draining(call_id)
            raise
        except Exception:
            pass
        # For asyncio tasks our completion callback was registered first.
        return self.outcome(call_id) or ProviderOutcome('failed', True)

    async def run_blocking(self, call_id, operation, wait_timeout, *, provider='default'):
        return await self._run(call_id, operation, wait_timeout, provider, False)

    async def run_async(self, call_id, operation, wait_timeout, *, provider='default'):
        return await self._run(call_id, operation, wait_timeout, provider, True)

    def check_drains(self):
        """Persist the circuit before asking the supervisor to replace this child."""
        now = self.clock()
        with self.store.transaction() as con:
            rows = con.execute("SELECT DISTINCT provider FROM provider_calls WHERE worker_id=? AND status='draining' AND draining_at<=?",
                               (self.worker_id, now-120)).fetchall()
            for row in rows:
                con.execute("INSERT INTO provider_circuits(provider,opened_at,probe_after,status) VALUES (?,?,?,'open') ON CONFLICT(provider) DO UPDATE SET status='open',probe_after=max(probe_after,excluded.probe_after)",
                            (row[0], now, now+60))
        return bool(rows)

    async def health_probe(self, provider, call_id, operation):
        """One bounded probe after cooldown; failed probes keep the circuit closed to traffic."""
        with self.store.transaction() as con:
            changed = con.execute("UPDATE provider_circuits SET status='probing' WHERE provider=? AND status='open' AND probe_after<=?",
                                  (provider, self.clock())).rowcount
        if not changed:
            return ProviderOutcome('circuit_open', False)
        outcome = await self._run(call_id, operation, 5, provider, False, probe=True)
        with self.store.transaction() as con:
            con.execute('UPDATE provider_circuits SET status=?,probe_after=? WHERE provider=?',
                        ('closed' if outcome.status == 'completed' and outcome.value is True else 'open', self.clock()+60, provider))
        return outcome

    def shutdown(self):
        self._closed = True
        # This returns promptly but does not kill active threads or release permits.
        self.executor.shutdown(wait=False, cancel_futures=False)
