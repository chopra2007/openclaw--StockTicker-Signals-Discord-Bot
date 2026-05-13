"""F6: SIGKILL-resistant workspace hygiene for the video fallback chain.

Runs at engine startup AND in every chain invocation's finally: block.
Never blocks ingest — all failures are logged, not raised.
"""
from __future__ import annotations

import fcntl
import logging
import os
import shutil
import time

log = logging.getLogger("consensus_engine.hygiene.disk_inode_sweep")

_DEFAULT_WORKSPACE = "/var/tmp/video-fallback"
_MIN_FREE_MB = 500
_MAX_INODE_PCT = 85
_MAX_AGE_HOURS = 6


def _workspace_root() -> str:
    try:
        from consensus_engine.config import get as _cfg_get
        return _cfg_get("youtube.hygiene.workspace_root", _DEFAULT_WORKSPACE)
    except Exception:
        return _DEFAULT_WORKSPACE


def _thresholds() -> tuple[int, int, int]:
    try:
        from consensus_engine.config import get as _cfg_get
        return (
            int(_cfg_get("youtube.hygiene.min_free_disk_mb", _MIN_FREE_MB)),
            int(_cfg_get("youtube.hygiene.max_inode_pct", _MAX_INODE_PCT)),
            int(_cfg_get("youtube.hygiene.file_max_age_hours", _MAX_AGE_HOURS)),
        )
    except Exception:
        return _MIN_FREE_MB, _MAX_INODE_PCT, _MAX_AGE_HOURS


def _ensure_workspace(root: str) -> None:
    if not os.path.exists(root):
        os.makedirs(root, mode=0o700, exist_ok=True)


def pre_flight_check() -> bool:
    """Return True if disk/inode conditions allow ingest, False otherwise."""
    root = _workspace_root()
    min_free_mb, max_inode_pct, _ = _thresholds()
    _ensure_workspace(root)
    try:
        stat = shutil.disk_usage(root)
        free_mb = stat.free // (1024 * 1024)
        if free_mb < min_free_mb:
            log.warning("F6 pre-flight: free disk %dMB < threshold %dMB", free_mb, min_free_mb)
            return False
    except OSError as exc:
        log.warning("F6 pre-flight: disk_usage failed: %s", exc)

    try:
        vfs = os.statvfs(root)
        total_inodes = vfs.f_files
        free_inodes = vfs.f_favail
        if total_inodes > 0:
            used_pct = 100 * (total_inodes - free_inodes) / total_inodes
            if used_pct > max_inode_pct:
                log.warning("F6 pre-flight: inode usage %.1f%% > threshold %d%%", used_pct, max_inode_pct)
                return False
    except OSError as exc:
        log.warning("F6 pre-flight: statvfs failed: %s", exc)

    return True


def startup_sweep() -> None:
    """Delete stale files and dead-PID lockfiles. Called once at engine boot."""
    root = _workspace_root()
    _ensure_workspace(root)
    lock_path = root.rstrip("/") + "/.sweep.lock"
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        log.warning("F6 startup_sweep: cannot open lock: %s", exc)
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.info("F6 startup_sweep: sweep lock held by another process — skipping")
        os.close(fd)
        return

    try:
        _, _, max_age_hours = _thresholds()
        cutoff = time.time() - max_age_hours * 3600
        try:
            with os.scandir(root) as it:
                for entry in it:
                    if entry.is_symlink():
                        continue
                    try:
                        stat = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if entry.name.endswith(".lock"):
                        _purge_dead_lockfile(entry.path, stat)
                    elif stat.st_mtime < cutoff:
                        _safe_remove(entry.path)
        except OSError as exc:
            log.warning("F6 startup_sweep: scandir error: %s", exc)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def cleanup_run_workspace(run_id: str) -> None:
    """Delete the per-run scratch dir. Called in finally: after every chain invocation."""
    root = _workspace_root()
    run_dir = os.path.join(root, str(run_id))
    if os.path.isdir(run_dir):
        _safe_remove(run_dir)


def _purge_dead_lockfile(path: str, stat: os.stat_result) -> None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Lock acquired → previous owner is dead; safe to remove
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.unlink(path)
            log.info("F6 startup_sweep: removed dead lockfile %s", path)
        except OSError:
            pass  # live process holds it — leave alone
    finally:
        os.close(fd)


def _safe_remove(path: str) -> None:
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.unlink(path)
        log.debug("F6 cleanup: removed %s", path)
    except OSError as exc:
        log.warning("F6 cleanup: could not remove %s: %s", path, exc)
