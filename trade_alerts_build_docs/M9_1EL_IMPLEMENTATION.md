# M9.1EL retained held-out D-108 evaluation — 2026-09-23 Pacific

## Scope

M9.1EL runs the frozen D-108 success bar once over the already-bound M9.1EK
held-out events. It reproduces the complete training and held-out input before
the evaluation, publishes every frozen profit, consistency and survivability
measure, and preserves every source-gap OFF label. It does not release a result
shard, send an alert or act live.

## Changed files

- `consensus_engine/retained_stage3_d108_evaluation.py`
- `tests/trade_alerts_contracts/test_retained_stage3_d108_evaluation.py`
- `trade_alerts_build_docs/M9_1EL_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

## Contract

`run_retained_stage3_d108_evaluation` accepts only the exact closed M9.1EK
record and a required, separately retained `frozen_input_sha256`. The caller
must freeze this fingerprint from the accepted M9.1EK `as_dict()` before the
evaluation handoff, using sorted compact JSON, `ensure_ascii=True`,
`allow_nan=False` and UTF-8. The evaluator compares the handed-off record to
that fingerprint, then rebuilds it from its complete stage-3 source and events.
Changed nested evidence, changed held-out returns, incomplete or unbound input
and any already-open later boundary fail closed. The result retains the
fingerprint alongside the source. Missing or mismatched fingerprints fail;
there is no automatic fallback to a fingerprint of the submitted record.

The fingerprint is a supplied-record integrity check, not source authentication.
A caller that replaces both the input and its supposedly frozen fingerprint
violates this contract. M9.1EK has no separate original held-out outcome store
from which M9.1EL could infer an old return. Its accepted code and record shape
remain unchanged. A future caller must retain the accepted fingerprint
separately; it must not calculate the expected value from an untrusted handoff.

The run converts each already-resolved, complete-cost held-out event to the
existing `D108_SUCCESS_BAR_V1` input and calls the frozen evaluator once per
invocation after these checks. Deterministic offline re-evaluation is allowed;
this function is not a durable run-once store. The
result carries the complete M9.1EK source plus the exact mean profit, primary
and sensitivity bootstrap lower bounds, winning-week fraction, drawdown,
recovery time, losing streak and combined pass/fail decision. Result-shard,
alert and live release stay false.

## Focused checks and pending proof

The focused checks cover the one evaluator call, every published D-108 measure,
complete source preservation, closed later boundaries and rejection of changed
evidence. The recording check writes
`m91el-retained-stage3-d108-evaluation.json` for both fresh controller
repeatability processes.

The focused protected launch stopped before collection at the unchanged
launcher's temporary-folder ownership step with
`OSError: [Errno 22] Invalid argument`. It was not retried, and no application
test ran outside the protected launcher. Static syntax checks passed. Fresh
controller focused, broad acceptance and separate two-process recording proof
and independent review remain required.

## Open gates

Accepted exit-side costs, confidence, halt, macro, catalyst, daily-history,
quote-policy, continuity and parent facts remain missing in the real strict
input. Their dependent rules remain OFF and untested. M9.1EL proves only the
offline frozen evaluation contract over supplied synthetic records; it does
not prove real held-out source coverage or authorize result-shard, alert or live
release. Source, final, result-shard, alert and live gates remain closed.

## Escalated repair and preserved failure

The controller's prior focused run failed at
`tests/trade_alerts_contracts/test_retained_stage3_d108_evaluation.py::test_rejects_changed_evidence_or_an_open_later_boundary[forged_held_out_event]`:
`E   Failed: DID NOT RAISE <class 'consensus_engine.trade_alerts_models.RecordError'>`.
Its pytest line was `1 failed, 11 passed in 20.38s`. This is historical failed
proof, not repaired acceptance. Original evidence remains at
`/root/trade-alerts-builder/runs/20260923-201408-718219-build/verification.log`;
the complete original delta is `changes.diff` in that directory and the first
builder result remains in `attempt-history/build-1-build-result.json`.

Cause: M9.1EL rebuilt held-out input from the very events it was checking.
Replacing a valid finite return with another finite return produced an equal
rebuilt record. The structural rebuild alone could not detect that edit.
The different repair checks the independently frozen fingerprint first while
keeping full training reconstruction. It neither caps returns nor substitutes
training returns for held-out outcomes. The original failing test ID is retained
and supplies the fingerprint of the unchanged fixture before altering the input.
Additional direct cases cover changed close time, changed evidence ID, removed
and reordered events, unavailable/wrong fingerprints, forged training despite a
matching fingerprint, and a large return genuinely present in a frozen input.
Rejection cases also check that the D-108 evaluator is never reached.

The repaired recording separates `input_sha256` (the retained input fingerprint)
from `result_sha256` (the canonical evaluation result fingerprint). Its selector is
`tests/trade_alerts_contracts/test_retained_stage3_d108_evaluation.py::test_recorded_d108_evaluation_is_deterministic_and_keeps_release_closed`.
Both fresh controller repeatability runs must collect this selector, emit
`m91el-retained-stage3-d108-evaluation.json` and compare its bytes and hashes.
Static inspection shows its recording name, deterministic comparison and
`write_text` meet the controller's discovery rule; actual collection and
comparison remain pending.

## Historical repair verification handoff

The repair's focused protected attempt selected the original failing case first.
It stopped before collection in the unchanged launcher's `os.chown` call:
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-2vypn4pm'`.
This sandbox failure was not retried. No application test ran outside protection.
Syntax and scoped whitespace checks are local checks only, not acceptance proof.

At this point the controller stage had not yet supplied fresh proof. The final
protected record below supersedes this pending note. The supplied historical
failed selection was, in its recorded order:

- `tests/trade_alerts_contracts/test_d108_evaluator.py::test_strong_winning_pattern_passes_all_three`
- `tests/trade_alerts_contracts/test_retained_stage3_d108_evaluation.py`
- `tests/trade_alerts_contracts/test_retained_stage3_held_out_input.py::test_binds_complete_cost_events_for_the_frozen_winner_only`
- `tests/trade_alerts_contracts/test_retained_stage3_input.py::test_binds_frozen_stage2_winner_and_keeps_stage3_closed`

The focused coverage and recording selector stayed required. Broader selection
remained the controller's decision. This pending state is historical; the final
record below shows acceptance. All source-gap OFF labels and result-shard, alert
and live restrictions remain in force.

## Final protected verification record

Fresh controller proof passed after the retained fingerprint repair. The focused
phase ran once for `builder named directly affected checks` with
`tests/trade_alerts_contracts/test_retained_stage3_d108_evaluation.py::test_rejects_changed_evidence_or_an_open_later_boundary[forged_held_out_event]`.
It recorded 1 test and controller wall time 12.302 seconds. The broad acceptance
phase ran once for `unknown dependency impact; safe broad fallback` with
`tests/trade_alerts_contracts`. It recorded 4523 tests and controller wall time
531.088 seconds. Both phases had zero failures, errors, and skips.

The separate repeatability phase ran twice in fresh protected processes for
`recording output requires fresh-process comparison`. It used the controller's
published 107-selector list, including
`tests/trade_alerts_contracts/test_retained_stage3_d108_evaluation.py::test_recorded_d108_evaluation_is_deterministic_and_keeps_release_closed`,
recorded 107 tests, and had two-run controller wall time 194.27 seconds. Both
`m91el-retained-stage3-d108-evaluation.json` artifacts matched byte-for-byte
with SHA-256
`4ab8c3118255c55a3bf610f255454975c089b20f6e56d400036bcd50df3bff4c`.
The controller artifacts are
`/root/trade-alerts-builder/runs/20260923-201408-718219-build/published-artifacts-03d03fca726c`,
`/root/trade-alerts-builder/runs/20260923-201408-718219-build/published-artifacts-028fd568e038`,
and
`/root/trade-alerts-builder/runs/20260923-201408-718219-build/published-artifacts-cf82121b5a80`.
The tested-source manifest is
`/root/trade-alerts-builder/runs/20260923-201408-718219-build/verified-manifest.json`
with source hash
`843e1affdae2f5a3852788792db4fd367a8f5eb170c9d4e9b7d2b727b5f5617f`.

Accepted exit-side costs, confidence, halt, macro, catalyst, daily-history,
quote-policy, continuity and parent facts remain missing. Their dependent rules
remain OFF and untested. Held-out source coverage, result-shard release, alerts
and live action remain closed.
