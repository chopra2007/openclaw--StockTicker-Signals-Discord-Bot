# M9.1EJ retained stage-3 input binding — 2026-09-23 Pacific

## Scope

M9.1EJ binds the accepted frozen M9.1EI stage-2 training winner to a closed
stage-3 input record. It preserves the complete stage-1 18/4/2/4 catalog, all
five stage-2 measurements, their frozen ranking, the selected winner, source
identities and every source-gap OFF label. It does not open held-out names,
run the held-out D-108 evaluation, release a result shard, send an alert or
act live.

## Changed files

- `consensus_engine/retained_stage3_input.py`
- `tests/trade_alerts_contracts/test_retained_stage3_input.py`
- `trade_alerts_build_docs/M9_1EJ_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

## Contract

`bind_retained_stage3_input` accepts only the exact closed M9.1EI training
record. It rebuilds the complete stage-2 comparison from the retained stage-2
input before binding the winner. A changed catalog, event, measurement,
ranking, winner, OFF label, version or open later-boundary switch fails closed.

The result carries the complete M9.1EI record plus an explicit selected-winner
record. Held-out access, D-108 evaluation, result-shard release, alerts and live
action remain false.

## Focused checks

The focused file checks the complete evidence chain, the frozen winner, exact
OFF labels, closed later boundaries and rejection of changed or opened input.
Its recording check writes `m91ej-retained-stage3-input.json` for both fresh
controller repeatability processes.

The initial local launcher limitation is superseded by the final controller
proof below. No test ran outside the protected launcher.

## Open gates

Accepted exit-side costs, confidence, halt, macro, catalyst, daily-history,
quote-policy, continuity and parent facts remain missing in the real strict
input. Their dependent rules remain OFF and untested. Source, final, held-out,
D-108 result, result-shard, alert and live gates remain closed.

## Final protected verification record — 2026-09-23 Pacific

The controller's focused protected run selected
`tests/trade_alerts_contracts/test_retained_stage2_input.py`,
`tests/trade_alerts_contracts/test_retained_stage2_training_run.py`,
`tests/trade_alerts_contracts/test_retained_stage3_input.py`,
`tests/trade_alerts_contracts/test_retained_stage3_input.py::test_recorded_retained_stage3_input_is_deterministic_and_keeps_held_out_sealed`,
and `tests/trade_alerts_contracts/test_stage2_training_comparison.py` for
`builder named directly affected checks`. It ran once, passed 47 tests with
zero failures, errors, and skips, and had controller wall time 66.703 seconds.
The published focused artifact directory is
`/root/trade-alerts-builder/runs/20260923-193238-725530-build/published-artifacts-c9353fc9b36e`.

The controller's broad protected acceptance run selected
`tests/trade_alerts_contracts` for `unknown dependency impact; safe broad
fallback`. It ran once, passed 4,490 tests with zero failures, errors, and
skips, and had controller wall time 425.871 seconds. The published broad
artifact directory is
`/root/trade-alerts-builder/runs/20260923-193238-725530-build/published-artifacts-741f9e8f3255`.

The separate repeatability phase used the exact controller-recorded selector
list in `published-artifacts-b10e1c4f5de4/summary.json` in two fresh protected
processes, including
`tests/trade_alerts_contracts/test_retained_stage3_input.py::test_recorded_retained_stage3_input_is_deterministic_and_keeps_held_out_sealed`.
It records 105 tests with zero failures, errors, and skips and two-run
controller wall time 183.253 seconds. The two
`m91ej-retained-stage3-input.json` artifacts matched byte-for-byte with SHA-256
`f96b158b4c1df7fe50c07a5b05112c57dc44036f8a5bcff98db3db28bcaaa7cd`.
The published repeatability artifact directory is
`/root/trade-alerts-builder/runs/20260923-193238-725530-build/published-artifacts-b10e1c4f5de4`.

The tested-source manifest is
`/root/trade-alerts-builder/runs/20260923-193238-725530-build/verified-manifest.json`;
its source hash is
`b16f192e4769217f248a60e4e043f34f841d906e8dd6dc7a3f764757be45ddd4`.
This final record changes documentation only. Accepted exit-side costs,
confidence, halt, macro, catalyst, daily-history, quote-policy, continuity and
parent facts remain missing. Their dependent rules remain OFF and untested;
held-out data, D-108 evaluation, result-shard release, alerts and live action
remain closed.
