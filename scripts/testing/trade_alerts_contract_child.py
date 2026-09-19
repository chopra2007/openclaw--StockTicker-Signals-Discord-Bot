"""Pre-import guards for run_trade_alerts_contracts.py; not a general runner."""

import asyncio
import builtins
from collections import Counter
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys


class IsolationViolation(BaseException):
    """Do not let an application `except Exception` turn a violation into success."""


violations = Counter()
connections = []
dotenv_calls = []


def deny(kind):
    violations[kind] += 1
    raise IsolationViolation(f"M0.4 isolation denied: {kind}")


def within_temp(path):
    return Path(os.fsdecode(path)).resolve().is_relative_to(Path("/tmp"))


def check_open(path, writing=False):
    if isinstance(path, int):
        return
    resolved = Path(os.fsdecode(path)).resolve()
    if resolved.name == ".env" or resolved.name.startswith(".env."):
        deny("credential_read")
    if resolved.suffix in {".db", ".sqlite", ".sqlite3"} and not within_temp(resolved):
        deny("database_path")
    if writing and not within_temp(resolved):
        deny("outside_write")
    if not writing and not any(resolved.is_relative_to(Path(root)) for root in (
            "/tmp", "/usr", "/workspace", "/proc")) and str(resolved) not in {
            "/etc/passwd", "/etc/group", "/etc/ld.so.cache", "/dev/null", "/dev/urandom"}:
        deny("outside_read")


def audit(event, args):
    if event == "open":
        mode, flags = args[1:3]
        writing = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
        check_open(args[0], writing or bool(mode and any(c in mode for c in "wax+")))
    elif event == "sqlite3.connect":
        if not within_temp(args[0]) or str(args[0]).startswith("file:"):
            deny("database_path")
        connections.append(str(Path(os.fsdecode(args[0])).resolve()))
    elif event == "socket.__new__" and args[1] != socket.AF_UNIX:
        deny("network")
    elif event.startswith("socket.") and event not in {"socket.__new__"}:
        deny("network")
    elif event in {"subprocess.Popen", "os.system", "os.fork", "os.forkpty",
                   "os.posix_spawn", "os.exec", "pty.spawn"}:
        deny("child_process")
    elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.chown",
                   "os.truncate", "os.utime"}:
        if not isinstance(args[0], int) and not within_temp(args[0]):
            deny("outside_write")
    elif event in {"os.rename", "os.link", "os.symlink"}:
        if not within_temp(args[0]) or not within_temp(args[1]):
            deny("outside_write")


def self_test():
    attempts = [
        ("network", lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM)),
        ("network", lambda: socket.getaddrinfo("sentinel.invalid", 443)),
        ("credential_read", lambda: Path("/tmp/synthetic/.env").read_text()),
        ("database_path", lambda: sqlite3.connect("/outside/synthetic.db")),
        ("outside_write", lambda: Path("/outside/sentinel.txt").write_text("sentinel")),
        ("child_process", lambda: subprocess.run(["/usr/bin/true"], check=True)),
    ]
    for kind, attempt in attempts:
        before = violations[kind]
        try:
            attempt()
        except IsolationViolation:
            assert violations[kind] == before + 1
        else:
            raise AssertionError(f"Isolation sentinel unexpectedly allowed: {kind}")
    return dict(violations)


def main():
    # Refuse direct host use: /workspace exists only in this launcher's mount tree.
    if Path(__file__).resolve() != Path("/workspace/scripts/testing/trade_alerts_contract_child.py"):
        raise SystemExit("Use run_trade_alerts_contracts.py")
    assert not any(name.startswith("consensus_engine") for name in sys.modules)
    sys.addaudithook(audit)
    expected = self_test()
    # urllib3 otherwise probes IPv6 by opening/binding a socket during import.
    # Network capability is deliberately unavailable in this offline process.
    socket.has_ipv6 = False
    sys.path.insert(0, "/workspace")
    sys.modules["trade_alerts_isolation"] = sys.modules[__name__]

    # Intercept dotenv before config imports; real credential files are not mounted.
    import dotenv

    def skip_dotenv(*args, **kwargs):
        dotenv_calls.append("intercepted")
        return False

    dotenv.load_dotenv = skip_dotenv
    dotenv.main.load_dotenv = skip_dotenv
    import consensus_engine.config as config
    config._DEFAULT_CONFIG_PATH = Path("/tmp/fixture.yaml")
    config._DEFAULT_CONFIG_PATH.write_text("database:\n  path: /tmp/default.db\n")
    from consensus_engine import db
    from consensus_engine.utils import obs_log

    sources = Path("/tmp/synthetic_sources.json")
    sources.write_text('{"youtube_channels": []}\n')

    def fixture_source_open(path, *args, **kwargs):
        if path == "/root/.openclaw/sources.json":
            path = sources
        return builtins.open(path, *args, **kwargs)

    # Existing initialization reads a hardcoded source registry; supply an empty
    # synthetic registry at that file boundary, keeping all migration code real.
    db.open = fixture_source_open
    obs_log._LOG_PATH = Path("/tmp/pipeline-obs.jsonl")
    import pytest

    exit_code = 1
    try:
        exit_code = int(pytest.main([
            "-q", "--tb=short", "-p", "no:cacheprovider", "-p", "pytest_asyncio.plugin",
            "-p", "pytest_timeout", "--basetemp=/tmp/pytest",
            "--junitxml=/tmp/results.xml", "--log-file=/tmp/pytest.log", *sys.argv[1:],
        ]))
    finally:
        from consensus_engine import db
        from consensus_engine.utils import http
        asyncio.run(db.close_db())
        asyncio.run(http.close_session())
        http._lock = None
        config._config = None
        unexpected = dict(Counter(violations) - Counter(expected))
        cleanup = {"db_closed": db._db is None, "http_closed": http._session is None,
                   "config_cleared": config._config is None, "http_lock_cleared": http._lock is None}
        report = {
            "sentinel_denials": expected, "all_denials": dict(violations),
            "unexpected_denials": unexpected, "dotenv_calls_intercepted": len(dotenv_calls),
            "database_connections": connections, "pytest_exit_code": exit_code,
            "cleanup": cleanup, "ipv6_probe_suppressed": True,
        }
        Path("/tmp/isolation.json").write_text(json.dumps(report, indent=2) + "\n")
        print("M0.4 isolation:", json.dumps(report, sort_keys=True))
    if unexpected:
        return 86
    return exit_code if all(cleanup.values()) else 87


if __name__ == "__main__":
    raise SystemExit(main())
