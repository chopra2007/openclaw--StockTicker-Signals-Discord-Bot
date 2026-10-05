"""Replaceable computation child and independent lightweight supervisor lane.

Deployment composition supplies the permitted provider registry and feed callback.
There is no implicit bot configuration, provider credential discovery or activation.
"""
import asyncio
import os
from pathlib import Path
import signal
import subprocess
import time
from uuid import uuid4

from .contracts import SectionResult
from .jobs import DEADLINES, empty_result
from .providers import ComputeInputs, ProviderWait, ResearchCompletion
from .provider_runtime import ProviderOutcome


class ComputeWorker:
    def __init__(self, jobs, registry, runtime, *, clock=time.time, deadlines=None, assistant=None):
        self.jobs, self.registry, self.runtime, self.clock = jobs, registry, runtime, clock
        self.deadlines = {**DEADLINES, **(deadlines or {})}
        self.current = None
        self.restart_requested = False
        self.assistant = assistant
        self.assistant_current = None
        self.prefer_assistant = True
        self._last_observation = None


    def _observe(self, *, progress=False):
        from .monitoring import observe,CADENCE
        now=self.clock()
        if progress or self._last_observation is None or now-self._last_observation>=CADENCE:
            state='draining' if self.restart_requested else 'busy' if self.current or self.assistant_current else 'idle'
            observe(self.jobs.store,'compute',self.runtime.worker_id,now,state=state,progress=progress)
            self._last_observation=now

    async def _assistant_heartbeat(self, run):
        while True:
            await asyncio.sleep(5)
            self.assistant.heartbeat(run)
            self._observe()

    async def _run_assistant(self):
        run = self.assistant.claim(self.runtime.worker_id) if self.assistant else None
        if run is None: return False
        self.assistant_current = run
        self.prefer_assistant = False
        heartbeat = asyncio.create_task(self._assistant_heartbeat(run))
        try:
            if await self.assistant.execute(run, self.runtime):
                self.assistant_current = None
                self._observe(progress=True)
        finally:
            heartbeat.cancel()
            try: await heartbeat
            except asyncio.CancelledError: pass
        return True

    async def _heartbeat(self, job):
        while True:
            await asyncio.sleep(5)
            self.jobs.heartbeat(job.id, job.lease_token, self.clock())
            self._observe()

    def _settle(self, job, outcome):
        if outcome.status == 'completed':
            try:
                completion = outcome.value
                result = completion.result if isinstance(completion,ResearchCompletion) else SectionResult.model_validate(completion)
                self.jobs.complete_job(job.id, job.lease_token, result, self.clock(),
                                       png=completion.png if isinstance(completion,ResearchCompletion) else None)
            except (ValueError, TypeError):
                self.jobs.fail_attempt(job.id, job.lease_token, self.clock(), retryable=False)
        elif outcome.status == 'failed':
            self.jobs.fail_attempt(job.id, job.lease_token, self.clock())
        elif outcome.status in ('circuit_open', 'closed'):
            self.jobs.complete_job(job.id, job.lease_token, empty_result(job.kind), self.clock())
        else:
            return False
        self.runtime.forget(job.call_id)
        self.current = None
        self._observe(progress=True)
        return True

    async def run_once(self):
        self._observe()
        self.restart_requested = self.runtime.check_drains()
        if self.assistant_current:
            if self.assistant.settle(self.assistant_current,self.runtime):
                self.assistant_current = None
                self._observe(progress=True)
            return
        if self.current:
            job = self.current
            self.jobs.heartbeat(job.id, job.lease_token, self.clock())
            outcome = self.runtime.outcome(job.call_id)
            if outcome is not None:
                self._settle(job, outcome)
            return
        if self.restart_requested:
            return
        if self.prefer_assistant and await self._run_assistant(): return
        job = self.jobs.claim_job(self.runtime.worker_id, self.clock())
        if job is None:
            await self._run_assistant()
            return
        self.prefer_assistant = True
        self.current = job
        heartbeat = asyncio.create_task(self._heartbeat(job))
        try:
            if job.kind not in self.registry.providers:
                self.jobs.complete_job(job.id, job.lease_token, empty_result(job.kind), self.clock())
                self.current = None
                return
            inputs = ComputeInputs(self.runtime, job.call_id, self.deadlines[job.kind], self.clock(), job.inputs)
            try:
                result = await self.registry.compute(job.ticker, job.kind, inputs)
                outcome = ProviderOutcome('completed', True, result)
            except ProviderWait as waiting:
                outcome = waiting.outcome
            except (ValueError, TypeError):
                self.jobs.fail_attempt(job.id,job.lease_token,self.clock(),retryable=False)
                self.runtime.forget(job.call_id)
                self.current = None
                return
            if outcome.status == 'timeout':
                self.jobs.mark_draining(job.id, job.lease_token, self.clock())
            elif outcome.status == 'busy':
                # No actual operation was admitted. Return to durable queue, not an executor queue.
                self.jobs.defer_unsubmitted(job.id, job.lease_token, self.clock())
                self.current = None
            else:
                self._settle(job, outcome)
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass

    async def serve(self, stop_requested=lambda: False):
        """Supervisor keeps ticking independently, even if this child has stuck threads."""
        try:
            while not stop_requested() and not self.restart_requested:
                await self.run_once()
                await asyncio.sleep(.05)
        finally:
            self.runtime.shutdown()


class ProcessTree:
    """OS-owned process tree. Windows uses a Job; Linux uses a private process group.

    The Linux service must additionally use KillMode=control-group and a private
    PID namespace. Providers may not launch descendants that escape the group.
    """
    def __init__(self):
        self.worker_id = str(uuid4())
        self._closed = False

    @classmethod
    def start(cls, command, *, worker_id=None):
        self = cls()
        # Composition passes the same fresh boot ID to the child command and
        # its ProviderRuntime. It is not a PID and must never be reused.
        if worker_id is not None:
            self.worker_id = worker_id
        if os.name == 'nt':
            self._start_windows(command)
        else:
            self.process = subprocess.Popen(command, start_new_session=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.pid = self.process.pid
        return self

    def _start_windows(self, command):
        import ctypes as c
        from ctypes import wintypes as w
        class Startup(c.Structure):
            _fields_ = [('cb',w.DWORD),('reserved',w.LPWSTR),('desktop',w.LPWSTR),('title',w.LPWSTR),
                ('x',w.DWORD),('y',w.DWORD),('xsize',w.DWORD),('ysize',w.DWORD),('xchars',w.DWORD),
                ('ychars',w.DWORD),('fill',w.DWORD),('flags',w.DWORD),('show',w.WORD),
                ('reserved2size',w.WORD),('reserved2',c.POINTER(c.c_byte)),
                ('stdin',w.HANDLE),('stdout',w.HANDLE),('stderr',w.HANDLE)]
        class ProcessInfo(c.Structure):
            _fields_ = [('process',w.HANDLE),('thread',w.HANDLE),('pid',w.DWORD),('tid',w.DWORD)]
        class BasicLimit(c.Structure):
            _fields_ = [('process_time',c.c_int64),('job_time',c.c_int64),('flags',w.DWORD),
                ('min_working',c.c_size_t),('max_working',c.c_size_t),('active_limit',w.DWORD),
                ('affinity',c.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
        class ExtendedLimit(c.Structure):
            _fields_ = [('basic',BasicLimit),('io',c.c_uint64*6),('process_memory',c.c_size_t),
                ('job_memory',c.c_size_t),('peak_process',c.c_size_t),('peak_job',c.c_size_t)]
        kernel = c.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [c.c_void_p,w.LPCWSTR]
        kernel.CreateJobObjectW.restype = w.HANDLE
        kernel.SetInformationJobObject.argtypes = [w.HANDLE,c.c_int,c.c_void_p,w.DWORD]
        kernel.QueryInformationJobObject.argtypes = [w.HANDLE,c.c_int,c.c_void_p,w.DWORD,c.c_void_p]
        kernel.CreateProcessW.argtypes = [w.LPCWSTR,w.LPWSTR,c.c_void_p,c.c_void_p,w.BOOL,w.DWORD,c.c_void_p,w.LPCWSTR,c.POINTER(Startup),c.POINTER(ProcessInfo)]
        kernel.AssignProcessToJobObject.argtypes = [w.HANDLE,w.HANDLE]
        kernel.ResumeThread.argtypes = [w.HANDLE]
        kernel.TerminateProcess.argtypes = [w.HANDLE,w.UINT]
        kernel.TerminateJobObject.argtypes = [w.HANDLE,w.UINT]
        kernel.WaitForSingleObject.argtypes = [w.HANDLE,w.DWORD]
        kernel.CloseHandle.argtypes = [w.HANDLE]
        self._kernel, self._ctypes = kernel, c
        self._job = kernel.CreateJobObjectW(None,None)
        if not self._job:
            raise c.WinError(c.get_last_error())
        limits = ExtendedLimit()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        info, startup = ProcessInfo(), Startup()
        startup.cb = c.sizeof(startup)
        try:
            if not kernel.SetInformationJobObject(self._job,9,c.byref(limits),c.sizeof(limits)):
                raise c.WinError(c.get_last_error())
            line = c.create_unicode_buffer(subprocess.list2cmdline(command))
            # Suspended creation closes the otherwise real descendant-escape race.
            if not kernel.CreateProcessW(None,line,None,None,False,0x4|0x200|0x08000000,None,None,c.byref(startup),c.byref(info)):
                raise c.WinError(c.get_last_error())
            self._handle, self.pid = info.process, info.pid
            if not kernel.AssignProcessToJobObject(self._job,self._handle):
                raise c.WinError(c.get_last_error())
            if kernel.ResumeThread(info.thread) == -1:
                raise c.WinError(c.get_last_error())
        except BaseException:
            if info.process:
                kernel.TerminateProcess(info.process,1)
                kernel.CloseHandle(info.process)
            kernel.CloseHandle(self._job)
            raise
        finally:
            if info.thread: kernel.CloseHandle(info.thread)

    def request_stop(self):
        if self._closed:
            return
        if os.name == 'nt':
            self._kernel.TerminateProcess(self._handle,1)
        else:
            try: os.killpg(self.pid, signal.SIGTERM)
            except ProcessLookupError: pass

    def contains_pid(self,pid):
        """Verify a gated runtime PID belongs to this OS-owned tree (venv launchers may fork)."""
        if self._closed or type(pid) is not int or pid<=0: return False
        if os.name=='nt':
            c=self._ctypes
            class ProcessIds(c.Structure):
                _fields_=[('assigned',c.c_uint32),('listed',c.c_uint32),('pids',c.c_size_t*128)]
            value=ProcessIds()
            if not self._kernel.QueryInformationJobObject(self._job,3,c.byref(value),c.sizeof(value),None): return False
            return value.assigned<=128 and pid in value.pids[:value.listed]
        try: return os.getpgid(pid)==self.pid
        except ProcessLookupError: return False

    def kill_tree(self):
        if self._closed:
            return
        if os.name == 'nt':
            if not self._kernel.TerminateJobObject(self._job,1):
                raise self._ctypes.WinError(self._ctypes.get_last_error())
        else:
            try: os.killpg(self.pid, signal.SIGKILL)
            except ProcessLookupError: pass

    def is_dead(self):
        if self._closed:
            return True
        if os.name == 'nt':
            c = self._ctypes
            class Accounting(c.Structure):
                _fields_ = [('times',c.c_int64*4),('page_faults',c.c_uint32),('total',c.c_uint32),('active',c.c_uint32),('terminated',c.c_uint32)]
            value = Accounting()
            if not self._kernel.QueryInformationJobObject(self._job,1,c.byref(value),c.sizeof(value),None):
                raise c.WinError(c.get_last_error())
            return value.active == 0 and self._kernel.WaitForSingleObject(self._handle,0) == 0
        if self.process.poll() is None:
            return False
        for path in Path('/proc').iterdir():
            if path.name.isdigit():
                try:
                    fields = (path/'stat').read_text().rsplit(')',1)[1].split()
                    if int(fields[2]) == self.pid and fields[0] != 'Z':
                        return False
                except (FileNotFoundError, ProcessLookupError, PermissionError):
                    continue
        return True

    def close(self):
        if self._closed:
            return
        if not self.is_dead():
            raise RuntimeError('cannot close a live process tree')
        if os.name == 'nt':
            self._kernel.CloseHandle(self._handle)
            self._kernel.CloseHandle(self._job)
        self._closed = True


class WorkerSupervisor:
    def __init__(self, store, child_factory, feed_tick, *, clock=time.time, stop_timeout=5,
                 reconcile=lambda worker_id: False):
        if not 0 < stop_timeout <= 30:
            raise ValueError('bounded stop timeout required')
        self.store, self.child_factory, self.feed_tick = store, child_factory, feed_tick
        self.clock, self.stop_timeout, self.reconcile = clock, stop_timeout, reconcile
        self.child = None
        self._last_feed = None
        self._stop_at = None
        self._restart = False
        self.last_exit_confirmed = False
        self.blocked = False
        self._observation_id = str(uuid4())
        self._last_observation = None
        self._pending_exit = None

    def request_restart(self):
        self._restart = True

    def _has_uncertainty(self, worker_id=None):
        with self.store.transaction() as con:
            return bool(con.execute("SELECT 1 FROM provider_calls WHERE status IN ('running','draining','uncertain')" +
                (' AND worker_id=?' if worker_id else '') + ' LIMIT 1', (worker_id,) if worker_id else ()).fetchone())

    def tick(self):
        now = self.clock()
        from .monitoring import observe,CADENCE
        if self._last_observation is None or now-self._last_observation>=CADENCE:
            observe(self.store,'supervisor',self._observation_id,now,state='blocked' if self.blocked else 'busy' if self._restart else 'idle')
            self._last_observation=now
        if self._last_feed is None or now-self._last_feed >= 5:
            self.feed_tick(now)
            self._last_feed = now
        child = self.child
        if child is not None:
            with self.store.transaction() as con:
                stuck = con.execute("SELECT DISTINCT provider FROM provider_calls WHERE worker_id=? AND status='draining' AND draining_at<=?", (child.worker_id,now-120)).fetchall()
                for (provider,) in stuck:
                    con.execute("INSERT INTO provider_circuits(provider,opened_at,probe_after,status) VALUES (?,?,?,'open') ON CONFLICT(provider) DO UPDATE SET status='open',probe_after=max(probe_after,excluded.probe_after)", (provider,now,now+60))
                if stuck:
                    self._restart = True
            if child.is_dead():
                self.last_exit_confirmed = True
                # The independent broker can own admissions absent from web state.
                # Persist/retain the exact exited identity until every bounded batch
                # is reconciled; feed/heartbeat continue while the broker is offline.
                self._pending_exit = child.worker_id
                child.close()
                self.child = None
                self._stop_at, self._restart = None, False
            elif self._restart:
                if self._stop_at is None:
                    child.request_stop()
                    self._stop_at = now+self.stop_timeout
                elif now >= self._stop_at:
                    child.kill_tree()
        if self._pending_exit is not None:
            try: reconciled = self.reconcile(self._pending_exit) is True
            except Exception: reconciled = False
            from .jobs import JobService
            jobs=JobService(self.store,None,None,None)
            jobs.confirm_worker_exit(self._pending_exit,now,reconciled=reconciled)
            self.blocked=not reconciled
            if reconciled:
                jobs.recover_expired_leases(now)
                self._pending_exit=None
        if self.child is None and not self.blocked:
            # Startup never restores stale permits from a historical snapshot.
            if self._has_uncertainty():
                self.blocked = True
            else:
                self.child = self.child_factory()
