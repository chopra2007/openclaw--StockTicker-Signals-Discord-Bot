#!/usr/bin/env python3
"""Discord 24h verification loop runner.

Runs iterations 2..24 of the verification loop on hourly cadence (started
externally; iteration 1 was logged by the parent autopilot session right
after the T+30min smoke test passed).

Per spec §3.3:
  Each iteration:
    1. Sleep until next hour mark.
    2. Run scripts/discord_24h_verify.py --once.
    3. On success: append log line, update state, continue.
    4. On failure: classify, apply remediation, re-run once, continue.

Per spec §3.4 (Architect-revised) self-heal table:
  dispatch_silent (exit 1/2/3): attempt 1 = restart_with_session_clear,
    attempt 2 = HALT_with_state_machine_diagnostic.
  unknown / transport_error (exit 4): attempt 1 = restart, attempt 2 = HALT.

Per spec §3.4 hard stops (all enforced as runtime checks here):
  - Same <class>:<remediation> twice → escalate (handled by attempt indexing).
  - Same class 3 iterations in a row → HALT.
  - Total fixes_applied > 8 → HALT.
  - Any "halt" remediation → HALT immediately (no ScheduleWakeup).

Usage:
  nohup python3 scripts/discord_24h_loop.py > .omc/logs/discord-24h-loop.stderr 2>&1 &
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/openclaw/.openclaw/workspace")
STATE_FILE = ROOT / ".omc/state/discord-24h-verify.json"
LOG_FILE = ROOT / ".omc/logs/discord-verification-24h.log"
DIAG_DIR = ROOT / ".omc/logs"
VERIFY = ROOT / "scripts/discord_24h_verify.py"
ITER_INTERVAL_S = 3600
SERVICE = "consensus-engine.service"
TOTAL_ITERATIONS = 24
FIX_BUDGET = 8
CLASS_3X_LIMIT = 3

EXIT_TO_CLASS = {
    0: "success",
    1: "dispatch_silent_help",
    2: "dispatch_silent_mention",
    3: "dispatch_silent_both",
    4: "transport_error",
}

# Class -> ordered remediation attempts. After the last, HALT.
REMEDIATION_TABLE = {
    "dispatch_silent_help": ["restart_with_session_clear", "HALT_with_diagnostic"],
    "dispatch_silent_mention": ["restart_with_session_clear", "HALT_with_diagnostic"],
    "dispatch_silent_both": ["restart_with_session_clear", "HALT_with_diagnostic"],
    "transport_error": ["restart_with_session_clear", "HALT_with_diagnostic"],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_ts() -> int:
    return int(time.time())


def load_state() -> dict:
    return json.loads(STATE_FILE.read_text())


def save_state(s: dict) -> None:
    STATE_FILE.write_text(json.dumps(s, indent=2))


def append_log(line: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a") as fh:
        fh.write(line + "\n")


def run_verify() -> tuple[int, str]:
    proc = subprocess.run(
        ["python3", str(VERIFY), "--once"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    return proc.returncode, proc.stdout.strip()


def restart_service() -> int:
    p = subprocess.run(
        ["sudo", "systemctl", "restart", SERVICE],
        capture_output=True,
        text=True,
        timeout=60,
    )
    time.sleep(30)  # let READY land
    return p.returncode


def service_uptime_s() -> int:
    try:
        out = subprocess.run(
            ["systemctl", "show", "-p", "ActiveEnterTimestamp", "--value", SERVICE],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        ts = subprocess.run(
            ["date", "-d", out, "+%s"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        return now_ts() - int(ts)
    except Exception:
        return -1


def restarts_count() -> int:
    try:
        out = subprocess.run(
            ["systemctl", "show", "-p", "NRestarts", "--value", SERVICE],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        return int(out)
    except Exception:
        return -1


def write_diagnostic_dump(iter_n: int, klass: str, state: dict) -> Path:
    p = DIAG_DIR / f"discord-fail-iter-{iter_n}.log"
    journal = subprocess.run(
        ["journalctl", "-u", SERVICE, "--since", "10 minutes ago", "--no-pager"],
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout
    p.write_text(
        f"=== Iter {iter_n} diagnostic dump @ {now_iso()} ===\n"
        f"Class: {klass}\n"
        f"State: {json.dumps(state, indent=2)}\n\n"
        f"=== journalctl -u {SERVICE} --since '10 minutes ago' ===\n{journal}"
    )
    return p


def class_consecutive_failures(state: dict) -> int:
    failures = state.get("failures", [])
    if not failures:
        return 0
    last_iters = sorted({f["iter"] for f in failures})[-CLASS_3X_LIMIT:]
    if len(last_iters) < CLASS_3X_LIMIT:
        return 0
    if last_iters != list(range(last_iters[0], last_iters[0] + CLASS_3X_LIMIT)):
        return 0
    classes = [f["class"] for f in failures if f["iter"] in last_iters]
    return CLASS_3X_LIMIT if len(set(classes)) == 1 else 0


def halt(state: dict, iter_n: int, reason: str) -> None:
    state["halted"] = True
    state["halt_reason"] = reason
    save_state(state)
    append_log(f"{now_iso()} iter={iter_n}/{TOTAL_ITERATIONS} HALTED reason={reason}")


def attempt_index_for_class(state: dict, klass: str) -> int:
    """How many fixes have already been tried for this class (used to pick the
    next remediation in the per-class registry)."""
    return sum(1 for sig in state.get("fixes_applied", []) if sig.startswith(f"{klass}:"))


def pick_remediation(state: dict, klass: str) -> str | None:
    table = REMEDIATION_TABLE.get(klass, ["restart_with_session_clear", "HALT_with_diagnostic"])
    idx = attempt_index_for_class(state, klass)
    if idx >= len(table):
        return None  # exhausted — caller halts
    return table[idx]


def apply_remediation(state: dict, iter_n: int, klass: str, remediation: str) -> bool:
    """Returns True if loop should continue, False to halt."""
    sig = f"{klass}:{remediation}"
    state["fixes_applied"].append(sig)
    state["last_fix_signature"] = sig

    if remediation == "restart_with_session_clear":
        rc = restart_service()
        append_log(f"{now_iso()} iter={iter_n}/{TOTAL_ITERATIONS} APPLIED fix={sig} rc={rc}")
        return True

    if remediation == "HALT_with_diagnostic":
        path = write_diagnostic_dump(iter_n, klass, state)
        append_log(f"{now_iso()} iter={iter_n}/{TOTAL_ITERATIONS} APPLIED fix={sig} dump={path.name}")
        halt(state, iter_n, f"halt_remediation:{klass}:{remediation}")
        return False

    halt(state, iter_n, f"unknown_remediation:{remediation}")
    return False


def run_iteration(iter_n: int) -> bool:
    """Run one iteration. Returns True to continue, False to halt."""
    state = load_state()
    if state.get("halted"):
        return False

    rc, stdout = run_verify()
    ts = now_iso()
    uptime = service_uptime_s()
    restarts = restarts_count()
    klass = EXIT_TO_CLASS.get(rc, f"unknown_exit_{rc}")

    if rc == 0:
        state["successes"] += 1
        state["iteration"] = iter_n
        save_state(state)
        append_log(
            f"{ts} iter={iter_n}/{TOTAL_ITERATIONS} SUCCESS {stdout} "
            f"uptime={uptime}s restarts={restarts}"
        )
        return True

    # Failure path
    failure_record = {
        "iter": iter_n,
        "ts": ts,
        "class": klass,
        "exit_code": rc,
        "stdout": stdout[:300],
    }
    state["failures"].append(failure_record)
    state["iteration"] = iter_n
    save_state(state)
    append_log(
        f"{ts} iter={iter_n}/{TOTAL_ITERATIONS} FAILURE class={klass} exit={rc} {stdout} "
        f"uptime={uptime}s restarts={restarts}"
    )

    # Hard stops (evaluate BEFORE picking remediation, per Critic §3.D)
    if len(state["fixes_applied"]) >= FIX_BUDGET:
        halt(state, iter_n, f"fix_budget>={FIX_BUDGET}")
        return False
    if class_consecutive_failures(state) >= CLASS_3X_LIMIT:
        halt(state, iter_n, f"class_3x:{klass}")
        return False

    # Pick and apply remediation
    remediation = pick_remediation(state, klass)
    if remediation is None:
        halt(state, iter_n, f"remediation_exhausted:{klass}")
        return False

    if not apply_remediation(state, iter_n, klass, remediation):
        return False

    # After applying a fix, wait 30s and re-run once (counts as same iter result)
    time.sleep(30)
    rc2, stdout2 = run_verify()
    ts2 = now_iso()
    save_state(state)
    if rc2 == 0:
        state["successes"] += 1
        save_state(state)
        append_log(
            f"{ts2} iter={iter_n}/{TOTAL_ITERATIONS} RECOVERED {stdout2} "
            f"fix={state['last_fix_signature']}"
        )
        return True
    append_log(
        f"{ts2} iter={iter_n}/{TOTAL_ITERATIONS} RECOVERY_FAILED exit={rc2} {stdout2}"
    )
    # Re-evaluate hard stops after the failed re-run
    if len(state["fixes_applied"]) >= FIX_BUDGET:
        halt(state, iter_n, f"fix_budget>={FIX_BUDGET}")
        return False
    return True  # try next iteration


def main() -> int:
    state = load_state()
    if state.get("halted"):
        print("Already halted, exiting", file=sys.stderr)
        return 1

    start_iter = max(2, state.get("iteration", 0) + 1)
    append_log(
        f"{now_iso()} LOOP_RESUME starting at iter={start_iter}/{TOTAL_ITERATIONS} "
        f"commit={state.get('fix_commit_sha', '?')[:7]}"
    )

    for iter_n in range(start_iter, TOTAL_ITERATIONS + 1):
        time.sleep(ITER_INTERVAL_S)
        cont = run_iteration(iter_n)
        if not cont:
            return 1

    final_state = load_state()
    append_log(
        f"{now_iso()} LOOP_COMPLETE iters={final_state['iteration']}/{TOTAL_ITERATIONS} "
        f"successes={final_state['successes']} "
        f"failures={len(final_state['failures'])} "
        f"fixes={len(final_state['fixes_applied'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
