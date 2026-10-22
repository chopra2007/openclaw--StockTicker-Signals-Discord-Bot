"""Exercise updater/watchdog coordination without touching real services."""

import json
import hashlib
import sqlite3
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux service script")
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "openclawupdate"

STUB = r'''#!/usr/bin/python3
import json, os, pathlib, sys
p = pathlib.Path(os.environ["UPDATER_TEST_STATE"])
s = json.loads(p.read_text())
cmd, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
rc = 0
if cmd == "id": print("0")
elif cmd == "node": print("2026.10.3")
elif cmd == "npm":
    print(s.get("latest", "2026.10.3")); rc = s.get("registry_rc", 0)
elif cmd == "pgrep": rc = 1
elif cmd == "systemctl":
    action = args[0]
    units = [a for a in args[1:] if not a.startswith("-")]
    if action == "is-active": rc = 0 if s.get(units[0], False) else 3
    else:
        for unit in units:
            if action == "start" and unit == "gateway-watchdog.timer" and s["restore_fails"]:
                rc = 1
            else:
                s[unit] = action in ("start", "restart")
elif cmd == "sudo":
    if "repair" in args:
        # A live watchdog restarts an intentionally stopped gateway.
        if s["gateway-watchdog.timer"]:
            s["openclaw-gateway.service"] = True
        rc = 42 if s["openclaw-gateway.service"] else s["repair_rc"]
    elif "health" in args:
        s["health_checked_with_watchdog_paused"] = not s["gateway-watchdog.timer"]
        rc = 0 if s["openclaw-gateway.service"] else 1
    elif "memory" in args:
        if s["memory_identity"] == "invalid-json":
            print("not json")
        else:
            print(json.dumps([{"status": {"dirty": True, "custom": {"indexIdentity": {"status": s["memory_identity"]}}}}]))
        rc = s["memory_rc"]
s["calls"].append([cmd, *args])
p.write_text(json.dumps(s))
sys.exit(rc)
'''


@pytest.mark.parametrize("watchdog_active,repair_rc,restore_fails", [
    (True, 0, False), (True, 7, False), (False, 0, False),
    (True, 0, True), (True, 7, True),
])
def test_update_keeps_watchdog_paused_until_healthy_and_restores_it(
    tmp_path, watchdog_active, repair_rc, restore_fails
):
    run_update(tmp_path, watchdog_active, repair_rc, restore_fails)


def run_update(tmp_path, watchdog_active=True, repair_rc=0, restore_fails=False, successful=False, force=False, registry_rc=0, pending=False, memory_identity="valid", memory_rc=0):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "stub"
    stub.write_text(STUB)
    stub.chmod(0o755)
    for command in ("id", "node", "npm", "pgrep", "ss", "sudo", "systemctl"):
        (bin_dir / command).symlink_to(stub)

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "openclaw.json").write_text("{}")
    (state_dir / "state").mkdir()
    with sqlite3.connect(state_dir / "state/openclaw.sqlite") as db:
        db.execute("CREATE TABLE update_runs (run_id TEXT, updated_at_ms INTEGER, phase TEXT, status TEXT)")
    if successful:
        (state_dir / "openclawupdate-success").write_text("2026.10.3 " + hashlib.sha256(b"{}[]").hexdigest() + "\n")
    if pending:
        with sqlite3.connect(state_dir / "state/openclaw.sqlite") as db:
            db.execute("INSERT INTO update_runs VALUES ('later-attempt', 1, 'doctor', 'failed')")
    script = tmp_path / "openclawupdate"
    script.write_text(SCRIPT.read_text().replace("STATE=/home/openclaw/.openclaw", f"STATE={state_dir}"))
    state_file = tmp_path / "services.json"
    state_file.write_text(json.dumps({
        "gateway-watchdog.timer": watchdog_active,
        "gateway-watchdog.service": watchdog_active,
        "openclaw-gateway.service": True,
        "repair_rc": repair_rc,
        "restore_fails": restore_fails,
        "registry_rc": registry_rc,
        "memory_identity": memory_identity,
        "memory_rc": memory_rc,
        "calls": [],
    }))
    result = subprocess.run(
        [shutil.which("bash"), str(script), *(["--repair"] if force else [])],
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "UPDATER_TEST_STATE": str(state_file)},
        capture_output=True, text=True, timeout=20,
    )
    state = json.loads(state_file.read_text())
    if successful or registry_rc:
        return result, state
    assert result.returncode == (repair_rc or int(restore_fails)), result.stdout + result.stderr
    assert state["openclaw-gateway.service"] is True
    assert state["gateway-watchdog.timer"] is (watchdog_active and not restore_fails)
    assert state.get("health_checked_with_watchdog_paused") is True
    if restore_fails:
        assert "OK" not in result.stdout


def test_verified_current_version_does_not_stop_gateway_or_repeat_repair(tmp_path):
    result, state = run_update(tmp_path, successful=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not any(c[0] == "systemctl" and c[1] == "stop" for c in state["calls"])
    assert not any("repair" in c for c in state["calls"])
    assert any("health" in c for c in state["calls"])


def test_registry_failure_keeps_gateway_and_watchdog_running(tmp_path):
    result, state = run_update(tmp_path, registry_rc=1)
    assert result.returncode != 0
    assert not any(c[0] == "systemctl" and c[1] == "stop" for c in state["calls"])


def test_explicit_repair_bypasses_previous_success(tmp_path):
    result, state = run_update(tmp_path, successful=True, force=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert any("repair" in c for c in state["calls"])


def test_later_update_attempt_invalidates_success_receipt(tmp_path):
    result, state = run_update(tmp_path, successful=True, pending=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert any("repair" in c for c in state["calls"])


def test_failed_forced_repair_removes_previous_success_receipt(tmp_path):
    result, state = run_update(tmp_path, successful=True, force=True, repair_rc=7)
    assert result.returncode == 7, result.stdout + result.stderr
    assert not (tmp_path / "state/openclawupdate-success").exists()


@pytest.mark.parametrize("identity,rc", [("mismatched", 0), ("missing", 0), ("invalid-json", 0), ("valid", 124)])
@pytest.mark.parametrize("force", [False, True])
def test_memory_verification_failure_keeps_finalize_receipt(tmp_path, identity, rc, force):
    result, state = run_update(tmp_path, successful=True, force=force, memory_identity=identity, memory_rc=rc)
    assert result.returncode != 0
    assert "OK" not in result.stdout
    assert "memory" in result.stderr.lower()
    assert (tmp_path / "state/openclawupdate-success").exists()
    repairs_before = sum("repair" in c for c in state["calls"])
    again = subprocess.run(
        [shutil.which("bash"), str(tmp_path / "openclawupdate")],
        env={**os.environ, "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "UPDATER_TEST_STATE": str(tmp_path / "services.json")},
        capture_output=True, text=True, timeout=20,
    )
    state = json.loads((tmp_path / "services.json").read_text())
    assert again.returncode != 0
    assert sum("repair" in c for c in state["calls"]) == repairs_before
