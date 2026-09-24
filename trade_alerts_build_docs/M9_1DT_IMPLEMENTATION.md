# M9.1DT retained first-four evaluator plan — 2026-09-23 Pacific

This bounded step connects each accepted retained session input to the canonical
replay-step type and evaluator name for all four first-four playbooks. It keeps
the exact retained source IDs, point-in-time offline inputs and any available
parent records together in one immutable plan.

The retained inputs do not prove complete confidence, halt, macro, catalyst,
daily-history, quote-policy or continuity facts. The current sample also lacks
the required parent records for the reversal and first-pullback paths. The plan
therefore remains not runnable and does not instantiate or advance a strategy
evaluator. It does not turn an unknown into a passing value, a candidate or a
no-event result. All D-104 gap-dependent rules remain OFF and untested.

Focused coverage is in
`tests/trade_alerts_contracts/test_retained_first_four_evaluator_plan.py`. It
checks all four evaluator bindings, exact replay-step types, source identity,
confidence and parent blockers, missing quote/trade handling and the
deterministic recording
`m91dt-retained-first-four-evaluator-plan.json`.

The initial implementation's protected launch stopped before collection at its
temporary-folder ownership step:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-zpx7oi_d'
```

That sandbox failure was not retried during the initial implementation.

## Focused failure diagnosis and repair

The controller subsequently ran the focused file. Its original failure remains
in `/root/trade-alerts-builder/runs/20260923-043118-766258-build/verification.log`:

```text
FAILED tests/trade_alerts_contracts/test_retained_first_four_evaluator_plan.py::test_binds_every_first_four_playbook_to_its_canonical_evaluator_inputs
E     Left contains 76 more items, first extra item: 'Orb5ReplayStep'
1 failed, 3 passed in 5.51s
```

The last line is the controller's pytest output, not a JUnit time or controller
wall time. The supplied controller summary records `runs: 1`,
`test_count: null`, selection reason `builder named directly affected checks`,
and selector `tests/trade_alerts_contracts/test_retained_first_four_evaluator_plan.py`.
It supplies no phase name, JUnit time or controller wall time. This failed run
is historical evidence, not acceptance of the repair.

The test incorrectly assumed that each first-two playbook has one replay step.
The shared input fixture contains the full frozen decision schedule, and
`build_retained_first_two_request` correctly emits a step for every moment.
The repair checks the complete type sequence, its length against the input
schedule, and exact ordered times in both replay steps and offline inputs.
It retains the source-identity and missing-parent checks. No product code,
fixture, strategy rule or missing-input behavior was changed by this repair.

The repaired focused launch stopped before collection at the same protected
ownership operation:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-0w_xyzux'
```

This reproduced sandbox failure was not retried. No application test ran outside
protection. The controller must supply fresh focused and broader acceptance
proof and separate two-process recording proof for
`tests/trade_alerts_contracts/test_retained_first_four_evaluator_plan.py::test_recorded_first_four_evaluator_plan_is_deterministic`,
including comparison of `m91dt-retained-first-four-evaluator-plan.json`.
The controller stages will supply all counts, hashes and timings; none are
claimed for the repaired tests here. Prior attempts and failures are preserved.

This is a blocked parent handoff, not M9.1DT acceptance. M9.1DU must consume the
plan through a fail-closed evaluator execution boundary, preserve the exact
missing-input result, and add complete parent evidence only when the retained
records actually prove it. No exact sample, fill, return, result shard, held-out
name, outside call or live action is released.

## Proof-publication repair

After the focused assertion repair, the controller's broader protected log
records this pytest result:

```text
4008 passed in 817.77s (0:13:37)
```

This is the pytest line, not a JUnit time or controller wall time. Publication
then failed with `verification error: artifact publication file is too large or unsafe`.
The carried-forward repair identified the full deterministic plan recording as
exceeding the unchanged 2 MiB per-file limit. It repeated the canonical plan
representation solely as recording evidence; the product plan was not rejected.

The recording now stores the SHA-256 fingerprint and exact byte count of the
same canonical plan representation, plus playbook names, step counts, runnable
flags and every missing-input reason. This allows comparison of the original
representation while avoiding repeated bulk data. The per-file controller limit and all
protected-test rules remain unchanged. Fresh protected proof is required.

## Escalated publication diagnosis

The current session read the prior failure, complete milestone delta, controller
publication check, source, callers and recording test before attempting a run.
The saved delta writes the whole indented plan representation. The current test
already contains the compact fingerprint repair described above; that partial
work was preserved. The different approach is to publish the fingerprint and
readable blockers, with a file-size assertion, instead of repeating the oversized
payload or raising the protected publication limit. Product behavior is unchanged.

Direct inspection of the old raw artifact directory was unavailable:

```text
PermissionError: [Errno 13] Permission denied: '/tmp/trade-alerts-m04-bv901_3l'
```

The earlier repair's byte-size figure is therefore not independently verified
here. No published acceptance or repeatability proof is claimed. The old broad
log remains historical evidence for the earlier recording, not the compact one.

The normal focused protected launch for the current compact recording stopped
before collection in `scripts/testing/run_trade_alerts_contracts.py` at
`os.chown(artifact_root, account.pw_uid, account.pw_gid)`:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-gfkqk417'
```

It was not retried or bypassed. Static syntax inspection passed, and the actual
controller repeatability predicate recognizes
`tests/trade_alerts_contracts/test_retained_first_four_evaluator_plan.py::test_recorded_first_four_evaluator_plan_is_deterministic`.
That inspection is not collection or execution proof. The controller must still
collect it in both fresh recording runs and publish the comparison of
`m91dt-retained-first-four-evaluator-plan.json`, alongside focused and broad
acceptance proof. The controller stages will supply their phase names, run
counts, test counts, selectors, timings, manifests and artifact fingerprints.

M9.1DT remains a blocked parent handoff because actual evaluator execution and
the required complete confidence and parent evidence remain unfinished.
M9.1DU stays open for independent review of that next bounded work. Missing-data
dependent rules remain OFF and untested; no source or live gate is closed.
