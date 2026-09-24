# M0.2CC off-by-default cleanup implementation

## Scope

The cleanup action now consumes the existing `plan_retention` result. It is a
separate `cleanup` command. Checked-in `cleanup_enabled` remains `false`, so the
command prints the dry-run plan and removes nothing by default.

An explicitly enabled run can remove only the three already approved classes:
verified minute option parts, verified duplicate temporary set members and
expired zero-byte notification markers. Primary and supporting research records
are not candidates.

## Safety checks

Immediately before each removal the action rechecks the configured root, legal
holds, target identity and the class-specific age rule. For minute parts and
temporary duplicates it also rechecks the immutable publication pointer, proof,
chain, open-interest file and every source identity that has not already been
removed by the same cleanup run. A new, missing, changed, linked or escaped path
stops the run.

Each target gets its own durable result file. The action records removal
authorization before unlinking the target, flushes the target folder after the
unlink, then records `removed`. A mismatch, result-write failure or removal
error stops the run at that file. The result write also respects the storage
reserve and a 16,384-byte bound.

## Verification boundary

The focused checks use only temporary synthetic files. No owner file is a test
target. The protected launcher stopped before collection in the Codex sandbox
with `OSError: [Errno 22] Invalid argument` while changing ownership of its
temporary folder. The controller must run the focused storage and collector
files, broad acceptance and required fresh-process comparison. Cleanup,
compaction, collection and every live switch remain off.

This implementation does not qualify a market source, close a D-104 gap, open
Strategies #5 through #8, prove a result or authorize live use.

## Escalated diagnosis — 2026-09-24 Pacific

Current status: **blocked on a separately reviewed protected-input repair**.
The earlier sandbox ownership error above describes the first local attempt.
The controller subsequently reached collection and reported
`KeyError: 'storage'` in
`tests/test_full_chain_collector.py::test_storage_cleanup_is_checked_in_off_and_dry_run_is_default`.
The original controller log is
`/root/trade-alerts-builder/runs/20260924-080950-896105-build/verification.log`;
its artifacts path is `/tmp/trade-alerts-m04-43ku_89e`.

The cause is the protected settings substitution. In
`scripts/testing/run_trade_alerts_contracts.py`, `sandbox_command` mounts
`tests/trade_alerts_contracts/fixtures/full_chain_collector.yaml` at
`/workspace/config/full_chain_collector.yaml`. That substitute file has no
`storage` section. The actual checked-in `config/full_chain_collector.yaml`
does have `storage.cleanup_enabled: false`. The failing assertion therefore
reads the substitute rather than the checked-in storage switch. The action
itself uses an absent-switch default of false; this does not establish the
checked-in-switch assertion or replace its required proof.

The different approach in this attempt was to trace the loaded settings back
through the protected mount, rather than rerun the same failing command or
weaken the assertion. No product code, tests, configuration, protected inputs
or launcher files were changed in this diagnosis. No test command was rerun.
The supplied escalation rule requires a blocked result when the cause lies
outside the milestone code. A separately reviewed protection repair must
resolve how the protected test verifies the checked-in switch while keeping
the sanitized temporary output root and isolation intact.

The supplied controller focused summary records `runs: 1`, `exit_code: 1`,
`test_count: null`, and selection reason
`builder named directly affected checks`. Its selectors, in published order:

- `tests/test_full_chain_collector.py::test_storage_cleanup_is_checked_in_off_and_dry_run_is_default`
- `tests/test_full_chain_storage.py::test_cleanup_defaults_to_dry_run_and_removes_nothing`
- `tests/test_full_chain_storage.py::test_cleanup_removes_only_revalidated_planned_classes_and_records_each_result`
- `tests/test_full_chain_storage.py::test_cleanup_stops_before_removal_when_eligibility_changes`
- `tests/test_full_chain_storage.py::test_m02cc_cleanup_recording_is_deterministic`

The controller log preserves `1 failed in 2.34s` for the collector group and
`4 passed in 2.66s` for the storage group. These are pytest lines, not controller
wall times or JUnit times. The supplied summary has no wall time. No successful
broad acceptance or two-run M0.2CC comparison is supplied; the controller must
supply those figures and artifacts after the focused failure is resolved.
The storage group's passing cases do not establish milestone acceptance.

The complete milestone delta remains:
`config/full_chain_collector.yaml`, `consensus_engine/full_chain_storage.py`,
`scripts/full_chain_collector.py`, `tests/test_full_chain_collector.py`,
`tests/test_full_chain_storage.py`, `trade_alerts_build_docs/M0_2CC_IMPLEMENTATION.md`,
and `trade_alerts_build_docs/ROADMAP.md`. Prior work, failures and attempt history
are preserved. Only these implementation and roadmap records changed in this
diagnosis. Cleanup and all live switches remain off. M0.2CD remains conditional
on M0.2CC acceptance and is not an independent next step while this gate is open.
