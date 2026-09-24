# M9.1EA retained first-four candidate fill connection — 2026-09-23 Pacific

M9.1EA adds one offline boundary after the accepted M9.1DZ evaluator binding.
Only exact bound candidate rows enter the accepted D-106/D-107 fill model.
No-event and unavailable rows are counted and excluded before that call.

The boundary rejects a changed binding version, mismatched binding counts,
duplicate decisions, cross-session market records, duplicate market-record
identities, records outside the candidate's retained source identities, and a
binding that already opened a later release. Missing trade or quote facts stay
unfilled and are never approximated.

The real retained rows are still unavailable because confidence, halt, macro,
catalyst, daily-history, quote-policy, continuity and parent facts are missing.
Their dependent rules remain OFF and untested, so they release no candidate and
reach no fill. Synthetic complete records prove only the offline connection.
Return, result-shard, held-out, alert and live release remain off.

The recording test writes `m91ea-retained-first-four-fill.json`. It commits to
the complete candidate-only output, records the excluded no-event rows, and
keeps every later release false. The controller must collect and compare it in
both fresh repeatability processes.

## Historical first-attempt launcher status

The protected focused launch was attempted once and stopped before collection
at the launcher's temporary-folder ownership step with:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-pndxofhr'
```

It was not retried. No application tests ran outside protection. Fresh
controller focused, broad acceptance and two-process recording proof are
required. The focused selector is
`tests/trade_alerts_contracts/test_retained_first_four_fill.py`.

## Complete milestone delta

- `consensus_engine/retained_first_four_fill.py`
- `tests/trade_alerts_contracts/test_retained_first_four_fill.py`
- `trade_alerts_build_docs/M9_1EA_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

## Escalated focused-failure diagnosis and repair — 2026-09-23 Pacific

The controller subsequently collected the focused checks and reported:

```text
FAILED tests/trade_alerts_contracts/test_retained_first_four_fill.py::test_only_bound_candidates_reach_the_fill_boundary
E   AssertionError: assert 1 == 2
1 failed, 4 passed in 14.88s
```

This is preserved controller failure evidence, not acceptance. The original
log is `/root/trade-alerts-builder/runs/20260923-120329-260546-build/verification.log`;
its reported artifact root is `/tmp/trade-alerts-m04-zsdz7h2h`. The controller
summary records `runs: 1`, `exit_code: 1`, `test_count: null`, and
`selection_reason: builder named directly affected checks`, with selector
`tests/trade_alerts_contracts/test_retained_first_four_fill.py`. The line above
is pytest's time; no JUnit or controller wall time was supplied for this failure.
The original attempt and full milestone delta remain preserved in the build
folder, including `attempt-history/build-1-build-result.json` and `changes.diff`.

The cause is in this milestone's synthetic test setup. `_evaluated_binding`
inherits candidate alert instants from different playbook examples: the first
uses July 6 and the other January 5. `_fill_ready_binding` supplied a trade and
quote only relative to the first alert, then incorrectly expected both to fill.
The accepted fill model correctly rejects that trade for the other alert's
fixed 0–30-second window. This is not a missing permission or source gate.

The different approach repairs the test setup instead of changing the fill
model or weakening the expected full-input result. Each synthetic candidate
now gets its own uniquely named trade and quote relative to its alert time,
with their identities retained in the matching synthetic session. The complete
case checks each selected trade and quote time. A separate case preserves the
original incomplete input and requires one filled result and one
`NO_TRADE_IN_WINDOW` result without a modeled price. Another case supplies
trades but no quotes and requires `NO_QUOTE_AT_FILL` without approximation.
The recording now explicitly requires the complete-input fills before writing.
No product source changed during this repair; the source file listed above
remains part of the complete milestone delta from the initial implementation.

## Current verification boundary

After the repair, the protected focused launcher stopped before collection:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-tjwtm2h9'
```

The failure occurred at `scripts/testing/run_trade_alerts_contracts.py`'s
temporary-folder ownership step. It was not retried, and no application tests
ran outside protection. Static syntax checks passed. Applying the controller's
actual `repeatability_test` predicate to the test source selects
`tests/trade_alerts_contracts/test_retained_first_four_fill.py::test_recorded_candidate_fill_is_deterministic_and_keeps_later_release_off`.
This is discovery eligibility only, not collected or compared recording proof.

Fresh controller focused proof, broad acceptance, and two fresh repeatability
runs must supply their phase fields, selectors, counts, times, artifacts,
complete tested-source manifest and comparisons. In both repeatability runs,
the named recording selector must be collected and
`m91ea-retained-first-four-fill.json` must be emitted and hash-compared.
No new passing protected proof is claimed. All real missing inputs and their
OFF/untested dependent rules remain unchanged. Return, result-shard, held-out,
alert and live release remain off. M9.1EB remains dependent on M9.1EA acceptance.

## Final protected-proof record — 2026-09-23 Pacific

The supplied controller verification handoff supersedes the earlier
temporary-folder ownership stops. It records the same complete milestone delta
and tested-source manifest, with source hash
`7d56db3ee9c90a387daa22ed601dfdac7e9271857914201f1b9df1751b6e1b09`.
This final record edit changes no code, tests, configuration, dependencies, or
protected inputs.

The controller's protected focused phase ran
`tests/trade_alerts_contracts/test_retained_first_four_fill.py::test_only_bound_candidates_reach_the_fill_boundary`
once: 1 check, JUnit time 8.918 seconds, and controller wall time 10.959
seconds. Broad acceptance ran `tests/trade_alerts_contracts` once because of
unknown dependency impact: 4,214 checks, JUnit time 975.649 seconds, and
controller wall time 981.11 seconds. Both phases had zero failures, errors,
and skips.

The repeatability phase ran the controller's published 69-selector list twice
in fresh protected processes because recording output requires fresh-process
comparison. Each run passed 96 checks with zero failures, errors, and skips;
JUnit times were 214.207 and 206.039 seconds, and controller wall time was
426.235 seconds. The list is in
`published-artifacts-2b38084152ca/summary.json` under the controller build run
and includes
`tests/trade_alerts_contracts/test_retained_first_four_fill.py::test_recorded_candidate_fill_is_deterministic_and_keeps_later_release_off`.
The `m91ea-retained-first-four-fill.json` hashes matched in both runs at
`64a3d4447c9befc36eb264a73584c4924eacdd98af7c9a70ac2c289fd6d58502`.
The focused, broad, and repeatability artifacts are respectively
`published-artifacts-8ea22c18653e`, `published-artifacts-d20105a84e49`, and
`published-artifacts-2b38084152ca` under the controller build run.

The real retained rows still lack confidence, halt, macro, catalyst,
daily-history, quote-policy, continuity, and parent facts. Their dependent
rules remain OFF and untested. Candidate, fill, return, result-shard, held-out,
alert, and live release remain off.
