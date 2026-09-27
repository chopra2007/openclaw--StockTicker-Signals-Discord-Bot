#!/usr/bin/env python3
"""Run the bounded contracts in one or two fresh processes, inside a fail-closed Linux sandbox.

No application imports occur in the parent. Only code and installed libraries
are mounted in the child; the live configuration, data and credentials are absent.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET


MINIMUM_AVAILABLE_MEMORY = 2 * 1024**3
MEMORY_PER_WORKER = 512 * 1024**2
VERIFICATION_TIMEOUT_SECONDS = 3600
INFRASTRUCTURE_FILES = {
    "fixture.yaml", "isolation.json", "output.txt", "pipeline-obs.jsonl",
    "pytest.log", "results.xml", "synthetic_sources.json",
}
TEST_WEIGHTS = {
    "test_orb5_stage1_result.py": 182,
    "test_retained_first_four_owner_inputs.py": 84,
    "test_retained_count_run.py": 72,
    "test_participation_features.py": 60,
    "test_stage1_result_package.py": 60,
    "test_retained_first_four_stage1_result.py": 50,
    "test_retained_training_candidate_parts.py": 49,
    "test_stage1_supervised_package_run.py": 47,
    "test_retained_training_candidate_record.py": 38,
    "test_retained_first_four_candidate_run.py": 36,
    "test_outcome_evaluator.py": 33,
    "test_orb5_replay.py": 31,
    "test_hod_comp_rs_replay.py": 25,
    "test_research_event_store.py": 20,
    "test_session_recovery.py": 17,
}


def available_memory():
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    return 0


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def selects_test(selectors, target):
    return any(
        path == target or target.startswith(path.rstrip("/") + "/")
        for path in (selector.split("::", 1)[0] for selector in selectors)
    )


def expand_test_groups(repo, selectors, workers):
    by_file = {}
    for selector in selectors:
        path_text = selector.split("::", 1)[0].rstrip("/")
        path = repo / path_text
        if path.is_dir():
            for test_path in sorted(path.glob("test_*.py")):
                relative = str(test_path.relative_to(repo))
                by_file.setdefault(relative, []).append(relative)
        else:
            by_file.setdefault(path_text, []).append(selector)
    if workers == 1 or len(by_file) < 2:
        return [selectors]
    groups = [[] for _ in range(workers)]
    totals = [0] * workers
    weighted = sorted(
        by_file.items(),
        key=lambda item: (-TEST_WEIGHTS.get(Path(item[0]).name, 1), item[0]),
    )
    for path, selected in weighted:
        index = min(range(workers), key=lambda candidate: (totals[candidate], candidate))
        groups[index].extend(selected)
        totals[index] += TEST_WEIGHTS.get(Path(path).name, 1)
    return [group for group in groups if group]


def sandbox_command(repo, run_root, tests, account):
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
           for selector in tests):
        command += [
            "--ro-bind", str(repo / "scripts/full_chain_collector.py"),
            "/workspace/scripts/full_chain_collector.py",
            "--ro-bind", str(repo / "tests/trade_alerts_contracts/fixtures/full_chain_collector.yaml"),
            "/workspace/config/full_chain_collector.yaml",
        ]
    if selects_test(
            tests, "tests/trade_alerts_contracts/test_saved_market_data_readiness.py"):
        data_root = repo / ".omc/research/professional-day-trader-methods"
        command += [
            "--ro-bind", str(repo / "scripts/research/run_saved_market_data_readiness.py"),
            "/workspace/scripts/research/run_saved_market_data_readiness.py",
            "--ro-bind", str(repo / "trade_alerts_build_docs/M9_1EQ_AUDITED_INPUT_BINDING.json"),
            "/workspace/trade_alerts_build_docs/M9_1EQ_AUDITED_INPUT_BINDING.json",
            "--ro-bind", str(repo / "trade_alerts_build_docs/M9_1EP_SAVED_DATA_QUALIFICATION.json"),
            "/workspace/trade_alerts_build_docs/M9_1EP_SAVED_DATA_QUALIFICATION.json",
            "--ro-bind", str(repo / "trade_alerts_build_docs/M9_1ER_DEVELOPMENT_READINESS_COUNTS.json"),
            "/workspace/trade_alerts_build_docs/M9_1ER_DEVELOPMENT_READINESS_COUNTS.json",
            "--ro-bind", str(data_root / "bars-equs-allmin.parquet"),
            "/workspace/.omc/research/professional-day-trader-methods/bars-equs-allmin.parquet",
            "--ro-bind", str(data_root / "bars-pillar-allmin.parquet"),
            "/workspace/.omc/research/professional-day-trader-methods/bars-pillar-allmin.parquet",
        ]
    command += [
        "--bind", str(run_root), "/tmp", "--remount-ro", "/",
        "--chdir", "/workspace", "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "TMPDIR", "/tmp", "--setenv", "TZ", "America/Los_Angeles",
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--setenv", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1",
        "--", sys.executable, "-I", "-B",
        "/workspace/scripts/testing/trade_alerts_contract_child.py", *tests,
    ]
    if account:
        command = ["/usr/bin/setpriv", "--reuid", str(account.pw_uid),
                   "--regid", str(account.pw_gid), "--init-groups", *command]
    return command


def valid_isolation(path):
    report = json.loads(path.read_text())
    sentinels = {"network": 2, "credential_read": 1, "database_path": 1,
                 "outside_write": 1, "child_process": 1}
    cleanup = report.get("cleanup", {})
    return (report.get("pytest_exit_code") == 0
            and report.get("unexpected_denials") == {}
            and report.get("sentinel_denials") == sentinels
            and report.get("all_denials") == sentinels
            and set(cleanup) == {"db_closed", "http_closed", "http_lock_cleared", "config_cleared"}
            and all(value is True for value in cleanup.values()))


def merge_shards(run_root, shard_roots):
    suites = ET.Element("testsuites")
    output_parts = []
    log_parts = []
    for shard_root in shard_roots:
        if not valid_isolation(shard_root / "isolation.json"):
            raise RuntimeError("parallel shard isolation proof failed")
        for suite in ET.parse(shard_root / "results.xml").getroot().iter("testsuite"):
            suites.append(suite)
        output_parts.append((shard_root / "output.txt").read_text(errors="replace"))
        log_parts.append((shard_root / "pytest.log").read_text(errors="replace"))
        for source in shard_root.iterdir():
            if not source.is_file() or source.name in INFRASTRUCTURE_FILES:
                continue
            target = run_root / source.name
            if target.exists():
                if digest(target) != digest(source):
                    raise RuntimeError(f"parallel shards produced conflicting proof: {source.name}")
            else:
                shutil.copyfile(source, target)
    ET.ElementTree(suites).write(run_root / "results.xml", encoding="utf-8", xml_declaration=True)
    (run_root / "output.txt").write_text("".join(output_parts))
    (run_root / "pytest.log").write_text("".join(log_parts))
    shutil.copyfile(shard_roots[0] / "fixture.yaml", run_root / "fixture.yaml")
    shutil.copyfile(shard_roots[0] / "synthetic_sources.json", run_root / "synthetic_sources.json")
    isolation = json.loads((shard_roots[0] / "isolation.json").read_text())
    isolation["parallel_shards"] = len(shard_roots)
    (run_root / "isolation.json").write_text(json.dumps(isolation, indent=2) + "\n")


def run_groups(repo, run_root, groups, account):
    if len(groups) == 1:
        with (run_root / "output.txt").open("w") as output:
            return subprocess.run(
                sandbox_command(repo, run_root, groups[0], account),
                env={"PATH": "/usr/bin:/bin"}, stdout=output,
                stderr=subprocess.STDOUT, timeout=VERIFICATION_TIMEOUT_SECONDS,
            ).returncode
    shard_parent = run_root / ".parallel-shards"
    shard_parent.mkdir()
    shard_roots = []
    processes = []
    started = time.monotonic()
    for index, tests in enumerate(groups, 1):
        shard_root = shard_parent / f"shard-{index}"
        shard_root.mkdir()
        shard_roots.append(shard_root)
        if account:
            os.chown(shard_root, account.pw_uid, account.pw_gid)
        output = (shard_root / "output.txt").open("w")
        command = ["/usr/bin/nice", "-n", "10", *sandbox_command(repo, shard_root, tests, account)]
        process = subprocess.Popen(command, env={"PATH": "/usr/bin:/bin"}, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        processes.append((process, output))
    while any(process.poll() is None for process, _ in processes):
        if available_memory() < MINIMUM_AVAILABLE_MEMORY:
            for process, _ in processes:
                if process.poll() is None:
                    os.killpg(process.pid, 15)
            raise RuntimeError("parallel verification memory reserve fell below 2 GiB")
        if time.monotonic() - started > VERIFICATION_TIMEOUT_SECONDS:
            for process, _ in processes:
                if process.poll() is None:
                    os.killpg(process.pid, 9)
            raise subprocess.TimeoutExpired(
                "parallel protected verification", VERIFICATION_TIMEOUT_SECONDS)
        time.sleep(1)
    for _, output in processes:
        output.close()
    statuses = [process.returncode for process, _ in processes]
    if statuses == [0] * len(processes):
        merge_shards(run_root, shard_roots)
    else:
        (run_root / "output.txt").write_text("".join(
            (root / "output.txt").read_text(errors="replace") for root in shard_roots
        ))
    return 0 if statuses == [0] * len(processes) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tests", nargs="*", default=["tests/trade_alerts_contracts"])
    parser.add_argument("--runs", type=int, choices=(1, 2), default=2)
    parser.add_argument("--workers", type=int, choices=(1, 3), default=1)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    artifact_root = Path(tempfile.mkdtemp(prefix="trade-alerts-m04-"))
    account = pwd.getpwnam("openclaw") if os.geteuid() == 0 else None
    if account:
        os.chown(artifact_root, account.pw_uid, account.pw_gid)
    print(f"Artifacts: {artifact_root}", flush=True)
    statuses = []
    workers = args.workers
    if workers == 3 and (os.cpu_count() or 1) < 4:
        workers = 1
    if workers == 3 and available_memory() < MINIMUM_AVAILABLE_MEMORY + workers * MEMORY_PER_WORKER:
        workers = 1
    groups = expand_test_groups(repo, args.tests, workers)
    for number in range(1, args.runs + 1):
        run_root = artifact_root / f"run-{number}"
        run_root.mkdir()
        if account:
            os.chown(run_root, account.pw_uid, account.pw_gid)
        result = run_groups(repo, run_root, groups, account)
        print((run_root / "output.txt").read_text(), end="", flush=True)
        statuses.append(result)
    (artifact_root / "summary.json").write_text(json.dumps({
        "commands": args.tests, "exit_codes": statuses, "runs": args.runs,
        "databento_credit_used": 0, "workers": len(groups),
    }, indent=2) + "\n")
    return 0 if statuses == [0] * args.runs else 1


if __name__ == "__main__":
    raise SystemExit(main())
