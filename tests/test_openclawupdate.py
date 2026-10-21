"""Exercise updater/watchdog coordination without touching real services."""

import json
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
elif cmd == "npm": print("2026.10.3")
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
    script = tmp_path / "openclawupdate"
    script.write_text(SCRIPT.read_text().replace("STATE=/home/openclaw/.openclaw", f"STATE={state_dir}"))
    state_file = tmp_path / "services.json"
    state_file.write_text(json.dumps({
        "gateway-watchdog.timer": watchdog_active,
        "gateway-watchdog.service": watchdog_active,
        "openclaw-gateway.service": True,
        "repair_rc": repair_rc,
        "restore_fails": restore_fails,
        "calls": [],
    }))
    result = subprocess.run(
        [shutil.which("bash"), str(script)],
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "UPDATER_TEST_STATE": str(state_file)},
        capture_output=True, text=True, timeout=20,
    )
    state = json.loads(state_file.read_text())
    assert result.returncode == (repair_rc or int(restore_fails)), result.stdout + result.stderr
    assert state["openclaw-gateway.service"] is True
    assert state["gateway-watchdog.timer"] is (watchdog_active and not restore_fails)
    assert state.get("health_checked_with_watchdog_paused") is True
    if restore_fails:
        assert "OK" not in result.stdout
