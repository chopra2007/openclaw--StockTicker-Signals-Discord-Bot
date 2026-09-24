# M9.1DZ retained evaluator-result binding — 2026-09-23 Pacific

M9.1DZ adds one offline boundary after the accepted M9.1DY sample restart. It
binds each restarted first-four evaluator result to exactly one retained
candidate, no-event or unavailable record for the same playbook, ticker and
session.

Candidate and no-event records are accepted only when the evaluator ran at
least one exact step, received unchanged acknowledgment for every proposed
transition, retained its final state and reported no missing input. Candidate
records also require at least one proposed transition. Evaluated no-event
records may have zero proposed transitions; every proposed transition must
still be acknowledged unchanged. Unavailable records are accepted only when their
evaluator stayed untouched, retained genuine missing inputs and produced no
state or transition. Source identities and all D-104 disabled rules must match
exactly. Missing, duplicate, cross-session, forged-status and opened-release
records are rejected.

The real retained fixture still lacks confidence, halt, macro, catalyst,
daily-history, quote-policy, continuity and parent facts. Its four rows remain
unavailable, and every rule that needs those facts remains OFF and untested.
Synthetic complete records cover candidate and no-event binding for all four
owner types. They prove only this offline contract. Candidate release, fill,
return, result-shard, held-out, alert and live boundaries remain off.

The recording test writes
`m91dz-retained-first-four-evaluator-binding.json`. It includes the genuine
unavailable fixture and the synthetic candidate/no-event bindings, commits to
the complete output, confirms every evaluated transition was acknowledged and
records every later release boundary as false. The controller must collect it
in both fresh repeatability processes.

## Protected test status

The protected focused launch was attempted once and stopped before collection
at the launcher's temporary-folder ownership step with:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-pqa2lzab'
```

It was not retried. No application tests ran outside protection. The controller
must provide fresh focused, broad acceptance and two-process recording proof.

## Complete milestone delta

- `consensus_engine/retained_first_four_evaluator_binding.py`
- `tests/trade_alerts_contracts/test_retained_first_four_evaluator_binding.py`
- `trade_alerts_build_docs/M9_1DZ_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

The focused selector is
`tests/trade_alerts_contracts/test_retained_first_four_evaluator_binding.py`.
The controller broad stage and discovered repeatability selectors remain
required.

## Historical protected-proof finalization

The earlier temporary-folder ownership stop is historical. The controller's
protected focused phase ran
`tests/trade_alerts_contracts/test_retained_first_four_evaluator_binding.py`
once: 5 checks, pytest time 13.17 seconds, JUnit time 13.173 seconds, and
controller wall time 14.967 seconds. Broad acceptance ran
`tests/trade_alerts_contracts` once because of unknown dependency impact: 4,207
checks, pytest time 984.67 seconds, JUnit time 984.456 seconds, and controller
wall time 990.421 seconds.

Two fresh repeatability processes ran the controller's published selector list:
95 checks per run, pytest times 206.95 and 206.49 seconds, JUnit times 206.945
and 206.488 seconds, and controller wall time 419.465 seconds. The list is in
`published-artifacts-17e423a30e4b/summary.json` under the controller build run.
The `m91dz-retained-first-four-evaluator-binding.json` hashes matched in both
processes at
`e729c713275cea75cf6be5ed840ed1aaeec4cfab94161893b19140e9ddd6febf`.
All published runs had zero failures, errors, and skips, preserved isolation,
and completed cleanup. The focused artifact is
`published-artifacts-070ebf981ad2/run-1`, broad acceptance is
`published-artifacts-140c44220e51/run-1`, and repeatability is
`published-artifacts-17e423a30e4b/run-1` and
`published-artifacts-17e423a30e4b/run-2` under the controller build run.

The complete tested-source manifest is
`/root/trade-alerts-builder/runs/20260923-093151-379810-build/verified-manifest.json`;
its source hash is
`5a156f7d9a2c4895f26f705b33dc0a09635bc41297632c9a0e9828adcbf156ea`.
This records-only finalization changes no code, test, configuration, dependency,
or protected input. The real retained rows still lack confidence, halt, macro,
catalyst, daily-history, quote-policy, continuity, and parent facts. Their
dependent rules remain OFF and untested; candidate, fill, return, result-shard,
held-out, alert, and live release remain off.

## Historical escalated assessment before storage diagnosis — 2026-09-23 Pacific

Status: **blocked; not independently accepted**. The historical passing proof
above remains preserved, but does not resolve the later controller failure
`acceptance verification failed`. No verification handoff was supplied for this
assessment. The latest controller `verification.log` stops amid failure/error
progress markers without test IDs, a traceback, or a final test summary.
The controller reports no published artifacts for that acceptance phase.

The diagnostic evidence gate is concrete: direct reads of the latest run's
`run-1/pytest.log`, `run-1/output.txt`, `run-1/results.xml`,
`run-1/isolation.json` and `summary.json` under
`/tmp/trade-alerts-m04-4t4x9qsc` all fail with permission denied. For example:

```text
[Errno 13] Permission denied: '/tmp/trade-alerts-m04-4t4x9qsc/run-1/pytest.log'
```

The underlying test-failure cause and failing test IDs remain unknown. No disk,
product-code or provider cause is inferred from the incomplete output. Unlike
the prior attempt, this assessment inspects the latest failure and its evidence
access before attempting any repair or repeated run. It changes records only;
the binding source and test contents still match the original tested manifest.
No tests were rerun, no protection was changed, and no attempts were reset.

Latest controller phase fields, copied from its saved `state.json` at
`2026-09-23T10:35:36-07:00` (Pacific), are:

```json
{
  "tests": {
    "phase": "acceptance",
    "runs": 1,
    "test_count": null,
    "wall_seconds": 522.193,
    "selection_reason": "unknown dependency impact; safe broad fallback",
    "selectors": ["tests/trade_alerts_contracts"],
    "exit_code": 1,
    "artifacts_path": "",
    "focused": {
      "phase": "focused",
      "runs": 1,
      "test_count": 4207,
      "wall_seconds": 992.036,
      "selection_reason": "builder named directly affected checks",
      "selectors": ["tests/trade_alerts_contracts"],
      "exit_code": 0,
      "artifacts_path": "/root/trade-alerts-builder/runs/20260923-093151-379810-build/published-artifacts-85b1eb22640a"
    }
  }
}
```

These wall times are controller wall times, not pytest or JUnit times. The
failed stage has no published final pytest/JUnit figures; the controller must
supply its readable failure evidence. Earlier acceptance and repeatability
artifacts and the original tested-source manifest remain as referenced above.
The complete milestone delta remains unchanged. This final record edit is
separate from the original tested-source evidence.

The supervisor must publish the existing failure details and failing test IDs
for diagnosis before another repair. M9.1EA remains open but depends on M9.1DZ
acceptance; it is not an independent next task. No independent successor is
established by this packet. All genuine missing inputs, OFF/untested dependent
rules and closed release boundaries described above remain unchanged.

## Current supervisor storage diagnosis — 2026-09-23 Pacific

Status: **blocked; not independently accepted**. The supervisor has resolved
the unknown cause in the preceding assessment. The durable report is
`/root/trade-alerts-builder/runs/20260923-093151-379810-build/SUPERVISOR_STORAGE_DIAGNOSIS.md`.
It identifies a host storage failure, not a product-test assertion failure:
the root filesystem reached 0 bytes available during the later verification.
Controller cleanup removed that temporary pytest folder. No durable failing
test IDs exist; obtaining them is no longer the requested repair prerequisite.

The immediately preceding controller log,
`attempt-history/acceptance-2-verification.log` under that same build run,
records `4207 passed in 985.52s` and exit code 0. That is the pytest time;
it does not replace the controller wall time or JUnit time. The controller
labels the corresponding published phase **focused**, with the exact selector
`tests/trade_alerts_contracts`, as recorded in the phase fields above. The
log filename does not relabel that phase. The earlier acceptance and separate
two-run recording proof, artifacts, hashes and tested-source manifest remain
preserved above. None is newly declared independent acceptance here.

The supervisor reports 5.6 GB available after verified archive offload.
Recovered free space does not itself prove that verification finished.
Unlike the prior attempt, this assessment uses the durable host diagnosis
and compares the binding source and test contents with the original tested
manifest; both still match. No code repair or repeated failing command is
appropriate for this external cause. Only these records and ROADMAP changed
in this attempt. No tests ran, no launcher or input changed, and no attempts
were reset.

The remaining gate is controller disposition of the storage-interrupted
verification: authorize reuse of matching published proof or supply fresh
protected proof in the recovered environment, followed by independent review.
No verification handoff was supplied in this packet. Any new stage figures
must come from the controller; no new counts or timings are claimed here.
This blocked return follows the escalated-task rule for a cause outside the
milestone code. M9.1EA remains open but depends on M9.1DZ acceptance, so it is
not an eligible independent successor. All missing facts and OFF/untested
dependent rules remain as listed above; every later release stays off.

## Final protected-proof record — 2026-09-23 Pacific

The supplied verification handoff supersedes the storage-interrupted assessment.
It records the same complete milestone delta and tested-source manifest, with
source hash
`3fe0afd5489d93ff01226f6b6c06e231ff991dbc30d209e578b872c7af71680f`.
This final record edit changes no code, tests, configuration, dependencies, or
protected inputs.

The controller's protected focused phase ran
`tests/trade_alerts_contracts/test_retained_first_four_evaluator_binding.py`
once: 5 checks, JUnit time 14.252 seconds, and controller wall time 16.201
seconds. Broad acceptance ran `tests/trade_alerts_contracts` once because of
unknown dependency impact: 4,207 checks, JUnit time 963.589 seconds, and
controller wall time 969.047 seconds. Both phases had zero failures, errors,
and skips.

The repeatability phase ran the controller's published 69-selector list twice
in fresh protected processes because recording output requires fresh-process
comparison. Each run passed 95 checks with zero failures, errors, and skips;
JUnit times were 204.315 and 205.413 seconds, and controller wall time was
415.139 seconds. The `m91dz-retained-first-four-evaluator-binding.json` hashes
matched in both runs at
`e729c713275cea75cf6be5ed840ed1aaeec4cfab94161893b19140e9ddd6febf`.
The focused, broad, and repeatability artifacts are respectively
`published-artifacts-19b4d0601ffd`, `published-artifacts-a3e024360065`, and
`published-artifacts-9287090c5a70` under the controller build run.

The real retained rows still lack confidence, halt, macro, catalyst,
daily-history, quote-policy, continuity, and parent facts. Their dependent
rules remain OFF and untested. Candidate, fill, return, result-shard, held-out,
alert, and live release remain off.
