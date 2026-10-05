"""Durable local request admission, separate from the actual-operation runtime.

No service starts on import. Only trusted bootstrap configures verified policy.
All real policies are absent/closed by default. Rolling windows are deliberately
conservative across provider fixed resets; requests and tokens are never refunded.
"""
from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import socket
import sqlite3
import struct
import threading
import time
from uuid import uuid4

from consensus_engine.utils.provider_budget import Admission, receive_frame, send_frame


@dataclass(frozen=True)
class Identity:
    caller: str
    owner: str


def process_identity(pid):
    """Linux PID, boot ID and start ticks, resistant to PID reuse."""
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    return f'{boot}:{pid}:{fields[19]}'


def confirmed_process_exit(owner):
    try:
        _, pid, _ = owner.split(':')
        return process_identity(int(pid)) != owner
    except FileNotFoundError:
        return True
    except (OSError, ValueError, IndexError):
        return False


def _number(value, *, positive=False):
    try:
        return (not isinstance(value, bool) and isinstance(value, (int, float))
                and math.isfinite(value) and (value > 0 if positive else value >= 0))
    except OverflowError:
        return False


def _label(value):
    return isinstance(value, str) and 0 < len(value) <= 128 and all(
        c.isascii() and (c.isalnum() or c in '._:-') for c in value)


class QuotaBroker:
    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock
        self.dashboard_owner_allowed = None

    def configure_scope(self, scope_id, *, window_seconds, verified_limit, bot_reserved,
                        dashboard_allocated, safety_margin, verified=False,
                        max_concurrency=None, expires_at=None, policy_version='1'):
        values = [verified_limit, bot_reserved, dashboard_allocated, safety_margin]
        if (not _label(scope_id) or not _number(window_seconds, positive=True)
                or not all(_number(v) for v in values)
                or bot_reserved + dashboard_allocated + safety_margin > verified_limit
                or (max_concurrency is not None and (type(max_concurrency) is not int or max_concurrency < 1))
                or (verified and (not _number(expires_at, positive=True) or expires_at <= self.clock()))):
            raise ValueError('invalid verified quota policy')
        with self.store.transaction() as con:
            old = con.execute('SELECT window_seconds FROM provider_quota_policy WHERE scope_id=?', (scope_id,)).fetchone()
            if old and old[0] != window_seconds:
                raise ValueError('window changes require a new scope and overlapping old scope')
            if old and con.execute('SELECT 1 FROM provider_admissions WHERE scope_id=? AND (admitted_at>? OR finished_at IS NULL) LIMIT 1', (scope_id, self.clock()-window_seconds)).fetchone():
                raise ValueError('active quota policy cannot be reallocated')
            con.execute('INSERT INTO provider_quota_policy VALUES (?,?,?,?,?,?,?,?,?,?,?) '
                        'ON CONFLICT(scope_id) DO UPDATE SET policy_version=excluded.policy_version,verified=excluded.verified,'
                        'verified_limit=excluded.verified_limit,bot_reserved=excluded.bot_reserved,'
                        'dashboard_allocated=excluded.dashboard_allocated,safety_margin=excluded.safety_margin,'
                        'max_concurrency=excluded.max_concurrency,expires_at=excluded.expires_at',
                        (scope_id, policy_version, int(verified), window_seconds, *values,
                         max_concurrency, self.clock(), expires_at))

    def configure_endpoint(self, endpoint, scope_ids, *, participation_verified=False, minimum_units=1):
        if (not _label(endpoint) or not scope_ids or len(scope_ids) > 16
                or not all(_label(s) for s in scope_ids) or len(set(scope_ids)) != len(scope_ids)
                or not _number(minimum_units, positive=True)):
            raise ValueError('invalid endpoint mapping')
        with self.store.transaction() as con:
            con.execute('INSERT INTO quota_endpoints VALUES (?,?,?,?) ON CONFLICT(endpoint) DO UPDATE SET '
                        'scopes_json=excluded.scopes_json,participation_verified=excluded.participation_verified,'
                        'minimum_units=excluded.minimum_units',
                        (endpoint, json.dumps(sorted(scope_ids)), int(participation_verified), minimum_units))

    def reserve(self, scope_ids, identity, endpoint, units, attempt_id):
        now = self.clock()
        def denied(reason, when=None):
            return Admission(False, not_before=when if when is not None else now+5, reason=reason)
        if identity.caller == 'dashboard' and self.dashboard_owner_allowed is not None:
            try: allowed=self.dashboard_owner_allowed(identity.owner) is True
            except Exception: allowed=False
            if not allowed: return denied('unregistered_worker')
        if (identity.caller not in ('bot', 'dashboard') or not _label(attempt_id)
                or not _label(endpoint)
                or not isinstance(scope_ids, (list, tuple)) or not 0 < len(scope_ids) <= 16
                or not all(_label(s) for s in scope_ids) or len(set(scope_ids)) != len(scope_ids)):
            return denied('invalid_request')
        scopes = sorted(scope_ids)
        charges = units if isinstance(units, dict) else {scope: units for scope in scopes}
        if set(charges) != set(scopes) or not all(_number(v, positive=True) for v in charges.values()):
            return denied('invalid_units')
        fingerprint = json.dumps([scopes, endpoint, {s: float(charges[s]) for s in scopes}], separators=(',', ':'))
        with self.store.transaction() as con:
            mapping = con.execute('SELECT scopes_json,participation_verified,minimum_units FROM quota_endpoints WHERE endpoint=?', (endpoint,)).fetchone()
            if not mapping or not mapping[1] or json.loads(mapping[0]) != scopes or any(v < mapping[2] for v in charges.values()):
                return denied('unverified_mapping')
            prior = con.execute('SELECT id,owner,caller,fingerprint FROM quota_attempts WHERE attempt_id=?', (attempt_id,)).fetchone()
            if prior:
                if prior[1:] != (identity.owner, identity.caller, fingerprint):
                    return denied('attempt_conflict')
                if con.execute('SELECT 1 FROM provider_admissions a JOIN provider_quota_policy p ON p.scope_id=a.scope_id WHERE a.group_id=? AND (a.outcome IS NOT NULL OR a.finished_at IS NOT NULL OR a.admitted_at<=?-p.window_seconds OR p.verified=0 OR p.expires_at IS NULL OR p.expires_at<=?) LIMIT 1', (prior[0], now, now)).fetchone():
                    return denied('stale_attempt')
                cooldown = con.execute('SELECT max(c.not_before) FROM provider_admissions a JOIN provider_cooldowns c ON c.scope_id=a.scope_id WHERE a.group_id=?', (prior[0],)).fetchone()[0]
                if cooldown is not None and cooldown > now:
                    return denied('capacity_or_cooldown', cooldown)
                return Admission(True, admission_id=prior[0])
            windows = []
            blocked_until = now
            for scope in scopes:
                policy = con.execute('SELECT verified,window_seconds,bot_reserved,dashboard_allocated,max_concurrency,effective_at,expires_at FROM provider_quota_policy WHERE scope_id=?', (scope,)).fetchone()
                if not policy or not policy[0] or now < policy[5] or policy[6] is None or now >= policy[6]:
                    return denied('unverified_scope')
                window, allocation = policy[1], policy[2 if identity.caller == 'bot' else 3]
                cooldown = con.execute('SELECT not_before FROM provider_cooldowns WHERE scope_id=?', (scope,)).fetchone()
                if cooldown:
                    blocked_until = max(blocked_until, cooldown[0])
                used, earliest = con.execute('SELECT coalesce(sum(units),0),min(admitted_at) FROM provider_admissions WHERE scope_id=? AND caller=? AND admitted_at>?', (scope, identity.caller, now-window)).fetchone()
                if used + charges[scope] > allocation:
                    blocked_until = max(blocked_until, (earliest+window) if earliest is not None else now+window)
                # Unfinished work remains active even beyond the request window.
                if policy[4] is not None:
                    active = con.execute('SELECT count(*) FROM provider_admissions WHERE scope_id=? AND finished_at IS NULL', (scope,)).fetchone()[0]
                    if active >= policy[4]:
                        blocked_until = max(blocked_until, now+1)
                windows.append(now-window)
            if blocked_until > now:
                return denied('capacity_or_cooldown', blocked_until)
            group = str(uuid4())
            con.execute('INSERT INTO quota_attempts VALUES (?,?,?,?,?,?)', (group, attempt_id, identity.owner, identity.caller, fingerprint, now))
            for scope, start in zip(scopes, windows):
                con.execute('INSERT INTO provider_admissions(id,attempt_id,scope_id,caller,endpoint,units,admitted_at,window_start,group_id) VALUES (?,?,?,?,?,?,?,?,?)',
                            (str(uuid4()), attempt_id, scope, identity.caller, endpoint, charges[scope], now, start, group))
            return Admission(True, admission_id=group)

    def finish(self, admission_id, identity, outcome, retry_after=None):
        if outcome not in ('completed', 'failed', '429', 'uncertain', '429_uncertain'):
            return
        now = self.clock()
        with self.store.transaction() as con:
            owner = con.execute('SELECT owner,caller FROM quota_attempts WHERE id=?', (admission_id,)).fetchone()
            if owner != (identity.owner, identity.caller):
                return
            rows = con.execute('SELECT scope_id,finished_at FROM provider_admissions WHERE group_id=?', (admission_id,)).fetchall()
            if not rows or all(row[1] is not None for row in rows):
                return
            if outcome in ('429', '429_uncertain'):
                delay = retry_after if _number(retry_after, positive=True) else 600
                for scope, _ in rows:
                    con.execute('INSERT INTO provider_cooldowns VALUES (?,?,?) ON CONFLICT(scope_id) DO UPDATE SET not_before=max(not_before,excluded.not_before),updated_at=excluded.updated_at', (scope, now+delay, now))
            uncertain = outcome in ('uncertain', '429_uncertain')
            con.execute('UPDATE provider_admissions SET finished_at=?,outcome=?,retry_after=?,uncertain=? WHERE group_id=? AND finished_at IS NULL',
                        (None if uncertain else now, outcome,
                         retry_after if _number(retry_after) else None, int(uncertain), admission_id))

    def reconcile_exited(self, owner, *, confirmed_dead=None, limit=100):
        """Supervisor-only; exact process tree must be dead. Never offered by RPC.

        Returns settled scope rows (at most limit). Repeat bounded batches before
        settling ProviderRuntime calls/probes. A callback is trusted supervisor
        evidence, never elapsed time, missing heartbeat or a member assertion.
        """
        if confirmed_dead is None or not 1 <= limit <= 100 or not confirmed_dead(owner):
            return 0
        with self.store.transaction() as con:
            return con.execute("UPDATE provider_admissions SET finished_at=?,outcome='process_exited',uncertain=1 WHERE id IN (SELECT a.id FROM provider_admissions a JOIN quota_attempts q ON q.id=a.group_id WHERE q.owner=? AND a.finished_at IS NULL LIMIT ?)", (self.clock(), owner, limit)).rowcount


class BrokerServer:
    """Serial bounded local RPC; no pickle, DB queries or admin methods on wire."""
    def __init__(self, broker, path, *, uid_roles):
        if os.name != 'posix' or not hasattr(socket, 'SO_PEERCRED'):
            raise ValueError('production broker requires Linux peer credentials')
        directory = Path(path).parent
        info = directory.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o027:
            raise ValueError('quota socket directory must be owned and restricted (0750 or tighter)')
        if any(role not in ('bot', 'dashboard') for role in uid_roles.values()):
            raise ValueError('invalid role mapping')
        self.broker, self.uid_roles, self.credentials = broker, dict(uid_roles), None
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(path)
        os.chmod(path, 0o660)
        self.address = path
        self._setup()

    @classmethod
    def for_loopback_tests(cls, broker, credentials):
        """Isolated Windows proof only; not a production identity mechanism."""
        instance = cls.__new__(cls)
        instance.broker, instance.uid_roles = broker, None
        instance.credentials = dict(credentials)
        instance.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        instance.socket.bind(('127.0.0.1', 0))
        instance.address = instance.socket.getsockname()
        instance._setup()
        return instance

    def _setup(self):
        self.socket.listen(16)
        self.socket.settimeout(.2)
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def _identity(self, connection, request):
        if self.credentials is not None:
            credential = request.get('credential')
            if not isinstance(credential, str):
                raise ValueError('unauthenticated')
            role = next((role for token, role in self.credentials.items() if hmac.compare_digest(token, credential)), None)
            if role is None:
                raise ValueError('unauthenticated')
            return Identity(role, 'test-' + hashlib.sha256(credential.encode()).hexdigest())
        pid, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        role = self.uid_roles.get(uid)
        if role is None:
            raise ValueError('unauthenticated')
        return Identity(role, process_identity(pid))

    def _serve(self):
        while not self.stopping.is_set():
            try:
                connection, _ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                connection.settimeout(2)
                try:
                    request = receive_frame(connection)
                    if not isinstance(request, dict):
                        raise ValueError('invalid request')
                    identity = self._identity(connection, request)
                    if request.get('method') == 'reserve':
                        if request.get('caller') != identity.caller:
                            raise ValueError('caller mismatch')
                        response = asdict(self.broker.reserve(request.get('scope_ids'), identity,
                            request.get('endpoint'), request.get('units'), request.get('attempt_id')))
                    elif request.get('method') == 'finish':
                        self.broker.finish(request.get('admission_id'), identity,
                                           request.get('outcome'), request.get('retry_after'))
                        response = {'ok': True}
                    else:
                        raise ValueError('unknown method')
                    send_frame(connection, response)
                except (OSError, ValueError, TypeError, RecursionError, sqlite3.Error):
                    try:
                        send_frame(connection, asdict(Admission(False, not_before=self.broker.clock()+5, reason='rejected')))
                    except OSError:
                        pass

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stopping.set()
        self.socket.close()
        self.thread.join(3)
        if isinstance(self.address, str):
            Path(self.address).unlink(missing_ok=True)
