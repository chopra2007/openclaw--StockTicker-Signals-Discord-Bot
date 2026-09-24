# M9.1EI retained stage-2 training comparison — 2026-09-23 Pacific

## Scope

M9.1EI connects the accepted closed M9.1EH input to the existing frozen
five-candidate stage-2 training comparison. It preserves the full 18/4/2/4
stage-1 catalog, every source-gap OFF label and the training-nine boundary.
It does not open held-out names, release a result shard, send an alert or act
live.

## Changed files

- `consensus_engine/retained_stage2_training_run.py`
- `tests/trade_alerts_contracts/test_retained_stage2_training_run.py`
- `trade_alerts_build_docs/M9_1EI_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

## Contract

`run_retained_stage2_training` accepts only the exact closed M9.1EH record. It
rebuilds that record from the complete retained stage-1 catalog and winner
events before calling the accepted M9.1CT comparison. Changed catalogs,
events, OFF labels, versions or open later-boundary switches fail closed.

The result preserves the source input, all five measured candidates, their
frozen ranking, the selected training winner and the per-playbook OFF labels.
Held-out access, result-shard release, alerts and live action remain false.

## Focused checks

The focused file checks the full five-candidate comparison, the preserved
18/4/2/4 catalog, exact OFF labels, the frozen training winner, closed later
boundaries and rejection of changed or opened inputs. Its recording check
writes `m91ei-retained-stage2-training.json` for both fresh controller
repeatability processes.

The protected focused launch stopped before collection at the unchanged
launcher's temporary-folder ownership step with
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-8bis660k'`.
It was not retried, and no application test ran outside the protected launcher.
Fresh controller focused, broad acceptance and two-process recording proof
remain required. The controller stages will supply their phase names, counts,
timings, exact selectors, artifact paths, hashes and tested-source manifest.

## Open gates

Accepted exit-side costs, confidence, halt, macro, catalyst, daily-history,
quote-policy, continuity and parent facts remain missing in the real strict
input. Their dependent rules remain OFF and untested. Source, final, held-out,
result-shard, alert and live gates remain closed.

## Final protected verification record — 2026-09-23 Pacific

The controller's focused protected run selected
`tests/trade_alerts_contracts/test_retained_stage2_input.py`,
`tests/trade_alerts_contracts/test_retained_stage2_training_run.py`,
`tests/trade_alerts_contracts/test_retained_stage2_training_run.py::test_recorded_retained_stage2_training_is_deterministic_and_keeps_held_out_closed`,
and `tests/trade_alerts_contracts/test_stage2_training_comparison.py` for
`builder named directly affected checks`. It ran once, passed 39 tests with
zero failures, errors, and skips, and had controller wall time 62.761 seconds.
The published focused artifact directory is
`/root/trade-alerts-builder/runs/20260923-191238-704366-build/published-artifacts-71f978d7c7bf`.

The controller's broad protected acceptance run selected
`tests/trade_alerts_contracts` for `unknown dependency impact; safe broad
fallback`. It ran once, passed 4,482 tests with zero failures, errors, and
skips, and had controller wall time 426.844 seconds. The published broad
artifact directory is
`/root/trade-alerts-builder/runs/20260923-191238-704366-build/published-artifacts-b3a300c02635`.

The separate repeatability phase used the controller-recorded selector list in
`published-artifacts-afd2d642cb83/summary.json` in two fresh protected
processes, including
`tests/trade_alerts_contracts/test_retained_stage2_training_run.py::test_recorded_retained_stage2_training_is_deterministic_and_keeps_held_out_closed`.
It records 104 tests with zero failures, errors, and skips and two-run
controller wall time 171.167 seconds. The two
`m91ei-retained-stage2-training.json` artifacts matched byte-for-byte with
SHA-256 `50a92667ea49692b7830e47f95eeea8a7606557bd01d146c8c727feb8eb658b4`.
The published repeatability artifact directory is
`/root/trade-alerts-builder/runs/20260923-191238-704366-build/published-artifacts-afd2d642cb83`.

The tested-source manifest is
`/root/trade-alerts-builder/runs/20260923-191238-704366-build/verified-manifest.json`;
its source hash is
`76614c180486becbad1e3edfe10e19cd9d20051e6b826754e7d93f718675b993`.
This final record changes documentation only. Accepted exit-side costs,
confidence, halt, macro, catalyst, daily-history, quote-policy, continuity and
parent facts remain missing. Their dependent rules remain OFF and untested;
held-out data, result-shard release, alerts and live action remain closed.
