#!/usr/bin/env python3
"""Run the bounded contracts in one or two fresh processes, inside a fail-closed Linux sandbox.

No application imports occur in the parent. Only code and installed libraries
are mounted in the child; the live configuration, data and credentials are absent.
"""

import argparse
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tests", nargs="*", default=["tests/trade_alerts_contracts"])
    parser.add_argument("--runs", type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    artifact_root = Path(tempfile.mkdtemp(prefix="trade-alerts-m04-"))
    account = pwd.getpwnam("openclaw") if os.geteuid() == 0 else None
    if account:
        os.chown(artifact_root, account.pw_uid, account.pw_gid)
    print(f"Artifacts: {artifact_root}", flush=True)
    statuses = []
    for number in range(1, args.runs + 1):
        run_root = artifact_root / f"run-{number}"
        run_root.mkdir()
        if account:
            os.chown(run_root, account.pw_uid, account.pw_gid)
        command = [
            "/usr/bin/bwrap", "--unshare-all", "--die-with-parent",
            "--new-session", "--cap-drop", "ALL", "--clearenv",
            "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin",
            "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
            "--proc", "/proc", "--dev", "/dev",
            "--ro-bind", "/etc/passwd", "/etc/passwd",
            "--ro-bind", "/etc/group", "/etc/group",
            "--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache",
        ]
        for relative in ("consensus_engine", "models", "tests", "scripts/testing", "pytest.ini",
                         "scripts/put_flow_shortlist_job.py"):
            command += ["--ro-bind", str(repo / relative), f"/workspace/{relative}"]
        if any(selector.split("::", 1)[0] == "tests/test_full_chain_collector.py"
               for selector in args.tests):
            command += [
                "--ro-bind", str(repo / "scripts/full_chain_collector.py"),
                "/workspace/scripts/full_chain_collector.py",
                "--ro-bind", str(repo / "tests/trade_alerts_contracts/fixtures/full_chain_collector.yaml"),
                "/workspace/config/full_chain_collector.yaml",
            ]
        command += [
            "--bind", str(run_root), "/tmp", "--remount-ro", "/",
            "--chdir", "/workspace", "--setenv", "PATH", "/usr/bin:/bin",
            "--setenv", "TMPDIR", "/tmp", "--setenv", "TZ", "America/Los_Angeles",
            "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
            "--setenv", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1",
            "--", sys.executable, "-I", "-B",
            "/workspace/scripts/testing/trade_alerts_contract_child.py", *args.tests,
        ]
        if account:
            command = ["/usr/bin/setpriv", "--reuid", str(account.pw_uid),
                       "--regid", str(account.pw_gid), "--init-groups", *command]
        with (run_root / "output.txt").open("w") as output:
            result = subprocess.run(command, env={"PATH": "/usr/bin:/bin"},
                                    stdout=output, stderr=subprocess.STDOUT, timeout=1200)
        print((run_root / "output.txt").read_text(), end="", flush=True)
        statuses.append(result.returncode)
    (artifact_root / "summary.json").write_text(json.dumps({
        "commands": args.tests, "exit_codes": statuses, "runs": args.runs,
        "databento_credit_used": 0,
    }, indent=2) + "\n")
    return 0 if statuses == [0] * args.runs else 1


if __name__ == "__main__":
    raise SystemExit(main())
