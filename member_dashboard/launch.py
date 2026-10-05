"""Bounded offline launch evidence and fail-closed web snapshot operations.

Production authority is deliberately absent. A staging result never activates
services or grants licensed access. Reports contain fixed reason codes only.
"""
from contextlib import closing
import json
import math
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import stat
import subprocess
import time

ORIGIN = 'https://localhost:3443'
MAX_JSON = 65536
MAX_BACKUP = 64 * 1024 * 1024
PRODUCTION_BLOCKERS = ('source_rights', 'quota_coverage', 'current_authority',
    'restricted_assistant', 'runtime_isolation', 'production_tls', 'owner_approval')


def windows_private(path,mode='check'):
    script=Path(__file__).resolve().parents[1]/'scripts/member_dashboard_private.ps1'
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(script),
        '-Path',str(path),'-Mode',mode],capture_output=True,timeout=10)
    if result.returncode: raise ValueError('private_permissions_required')


def secure_directory(path):
    """Initialize only a new empty task-owned directory, never change live ACLs."""
    path=Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir() or any(path.iterdir()):
        raise ValueError('empty_private_directory_required')
    if os.name=='nt': windows_private(path,'initialize')
    else: path.chmod(0o700)


def evaluate(**measurements):
    gates = {
        'feed_latency': ('feed_p95_seconds', lambda x: x <= 30),
        'cached_read_latency': ('cached_read_p95_seconds', lambda x: x <= 1),
        'disk_headroom': ('disk_free_gib', lambda x: x >= 10),
        'disk_percentage': ('disk_free_pct', lambda x: x >= 15),
        'capacity': ('memory_available_gib', lambda x: x >= 3),
        'resident_cap': ('web_resident_gib', lambda x: x <= 2),
        'remaining_memory': ('loaded_memory_available_gib', lambda x: x >= 1),
        'bot_latency': ('bot_latency_regression_pct', lambda x: x <= 10),
    }
    failures = []
    measured = {}
    for gate, (key, check) in gates.items():
        value = measurements.get(key)
        valid = type(value) in (float,int) and math.isfinite(value) and value >= 0
        measured[key] = value if valid else None
        if not valid or not check(value): failures.append(gate)
    # No evidence verifier/updater for these production gates is implemented.
    # Caller booleans, synthetic grants and old reports cannot satisfy them.
    failures.extend(PRODUCTION_BLOCKERS)
    return {'ready': False, 'scope': 'offline-preflight', 'measurements': measured,
            'failures': failures}


def protected(path, *, directory=False):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink(): raise ValueError('unsafe_path')
    info = path.stat()
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError('unsafe_path')
    if os.name == 'posix' and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise ValueError('private_permissions_required')
    if os.name=='nt': windows_private(path)
    return path


def private_target(root, target):
    root = protected(Path(root), directory=True).resolve()
    target = Path(target)
    if not target.is_absolute() or target.parent.resolve() != root or target.is_symlink():
        raise ValueError('unsafe_output_location')
    if target.exists(): raise FileExistsError('output_exists')
    return target


def private_output(root, target, value):
    target = private_target(root, target)
    data = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    if len(data) > MAX_JSON: raise ValueError('report_too_large')
    temporary=target.parent/(secrets.token_hex(16)+'.pending')
    fd = os.open(temporary, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        # Atomic publication with no replace/overwrite of an existing report.
        os.link(temporary,target)
    finally: temporary.unlink(missing_ok=True)


def read_private_json(path):
    path = protected(path)
    if path.stat().st_size > MAX_JSON: raise ValueError('config_too_large')
    with path.open('rb') as stream: raw=stream.read(MAX_JSON+1)
    if len(raw)>MAX_JSON: raise ValueError('config_too_large')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result: raise ValueError('duplicate_key')
            result[key]=value
        return result
    value=json.loads(raw,object_pairs_hook=unique)
    if not isinstance(value,dict): raise ValueError('invalid_config')
    return value


def validate_staging(origin, manifest, *, now=None):
    now = time.time() if now is None else now
    if origin != ORIGIN or manifest.get('mode') != 'synthetic-staging' or manifest.get('origin') != origin:
        raise ValueError('unsupported_staging_origin')
    if (not isinstance(manifest.get('nonce'),str) or len(manifest['nonce'])!=64
            or any(c not in '0123456789abcdef' for c in manifest['nonce'])
            or not isinstance(manifest.get('certificate_sha256'),str)
            or len(manifest['certificate_sha256'])!=64
            or type(manifest.get('expires_at')) not in (int,float)
            or not now < manifest['expires_at'] <= now+3600):
        raise ValueError('missing_staging_tls_or_identity')
    if any(item[4][0] not in ('127.0.0.1','::1') for item in socket.getaddrinfo('localhost',3443,type=socket.SOCK_STREAM)):
        raise ValueError('unsupported_staging_host')
    return manifest


def _snapshot(source, destination, root, quota_path):
    source, quota_path = Path(source), Path(quota_path)
    destination = private_target(root, destination)
    if (source.resolve() in (destination.resolve(),quota_path.resolve())
            or destination.resolve()==quota_path.resolve()): raise ValueError('shared_database_path')
    if source.exists() and quota_path.exists() and source.samefile(quota_path): raise ValueError('shared_database_path')
    if not source.is_file() or source.is_symlink(): raise ValueError('missing_web_database')
    if source.stat().st_size > MAX_BACKUP: raise ValueError('backup_capacity')
    fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    started=time.monotonic()
    def bounded(status, remaining, total):
        if total*4096>MAX_BACKUP or time.monotonic()-started>10: raise ValueError('backup_capacity')
    try:
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=2)) as src, closing(sqlite3.connect(destination)) as dst:
            src.backup(dst,pages=128,progress=bounded,sleep=.01)
            if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('invalid_backup')
            if {row[0] for row in dst.execute('SELECT version FROM schema_migrations')} != set(range(1,10)):
                raise ValueError('unsupported_backup_schema')
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination


def backup_web(source, destination, root, *, quota_path):
    """Private SQLite snapshot; production archival also requires encryption.

    Does not certify source-specific media/WAL erasure. Such sources stay off.
    """
    return _snapshot(source,destination,root,quota_path)


def restore_closed(source, destination, root, *, quota_path, denial_journal=None):
    """Quarantine restore. Never restores authorization, quota or runnable work.

    All members are suspended and all content delivery remains closed. A trusted
    current-authority integration is required before any selective reactivation.
    """
    if denial_journal is not None: denial_journal.current()
    path=_snapshot(source,destination,root,quota_path)
    with closing(sqlite3.connect(path)) as con:
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('DELETE FROM sessions');con.execute('DELETE FROM invites');con.execute('DELETE FROM password_resets')
        con.execute("UPDATE members SET status='suspended',authorization_version=authorization_version+1")
        con.execute('UPDATE features SET enabled=0,version=version+1')
        con.execute('UPDATE feed_state SET retraction_authority_required=1')
        con.execute("UPDATE web_jobs SET status='cancelled' WHERE status IN ('queued','running','draining')")
        con.execute("UPDATE assistant_runs SET status='unavailable',error_code='unavailable' WHERE status IN ('queued','running','draining')")
        con.execute("UPDATE provider_calls SET status='uncertain',reconciled=0 WHERE status IN ('running','draining')")
        # Historical quota tables in the web schema are never an admission source.
        con.execute('UPDATE provider_quota_policy SET verified=0')
        con.execute('UPDATE quota_endpoints SET participation_verified=0')
        if denial_journal is not None: denial_journal.reconcile(con)
        con.commit()
    # Positive retention authority is unavailable. Use the existing bounded
    # purge path; old licensed payloads must not survive as restorable access.
    from .source_policy import SourcePolicy
    from .store import WebStore
    policy=SourcePolicy(WebStore(path))
    cursors={}
    for _ in range(1000):
        outcome=policy.purge(time.time(),limit=100,cursors=cursors)
        if not outcome.more: break
        cursors=outcome.cursors
    else: raise ValueError('restore_purge_capacity')
    if denial_journal is not None: denial_journal.current()
    return path
