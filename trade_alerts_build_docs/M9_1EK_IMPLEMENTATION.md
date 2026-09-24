# M9.1EK retained held-out input binding — 2026-09-23 Pacific

## Scope

M9.1EK binds already-resolved, complete-cost events from the frozen D-107
held-out eight to the accepted M9.1EJ stage-3 winner. It reproduces the full
stage-1 and stage-2 training evidence before accepting the held-out input. It
does not run D-108, release a result shard, send an alert or act live.

## Changed files

- `consensus_engine/retained_stage3_held_out_input.py`
- `tests/trade_alerts_contracts/test_retained_stage3_held_out_input.py`
- `trade_alerts_build_docs/M9_1EK_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

## Contract

`bind_retained_stage3_held_out_inputs` accepts only the exact closed M9.1EJ
record. The evaluated-name list must equal the frozen held-out tuple in frozen
order. Every event must use a selected playbook and its frozen stage-1 winner,
one of the held-out eight, every selected setting axis, complete costs and a
unique ticker-day-side cluster. Changed training evidence, training names,
unselected playbooks, changed candidates, missing costs, changed axes and
duplicate clusters fail closed.

The result preserves the complete M9.1EJ source record, the frozen stage-2
winner, the selected playbooks, every held-out event and every source-gap OFF
label. D-108 evaluation, result-shard release, alerts and live action remain
false.

## Focused checks and pending proof

The focused checks cover the complete binding, frozen split, selected winner,
source-gap OFF labels, closed later boundaries and rejection cases. The
recording check writes `m91ek-retained-stage3-held-out-input.json` for both
fresh controller repeatability processes.

The focused protected launch stopped before collection at the unchanged
launcher's temporary-folder ownership step with `OSError: [Errno 22] Invalid
argument`. It was not retried, and no application test ran outside the
protected launcher. Fresh controller focused, broad acceptance and separate
two-process recording proof and independent review remain required.

## Open gates

Accepted exit-side costs, confidence, halt, macro, catalyst, daily-history,
quote-policy, continuity and parent facts remain missing in the real strict
input. Their dependent rules remain OFF and untested. M9.1EK binds synthetic
supplied records only; it does not prove real held-out source coverage or a
D-108 result. Source, final, D-108 result, result-shard, alert and live gates
remain closed.

## Final protected verification record

The controller completed fresh protected proof on 2026-09-23 Pacific. The
focused phase ran once for `builder named directly affected checks`, using the
seven selectors recorded in
`/root/trade-alerts-builder/runs/20260923-195118-906663-build/published-artifacts-3aa556ccc4b5/summary.json`.
It recorded 74 tests and controller wall time 120.865 seconds. The broad
acceptance phase ran once for `unknown dependency impact; safe broad fallback`,
using `tests/trade_alerts_contracts`. It recorded 4,501 tests and controller
wall time 500.007 seconds.

The separate repeatability phase ran twice in fresh protected processes for
`recording output requires fresh-process comparison`. Its exact selector list,
including
`tests/trade_alerts_contracts/test_retained_stage3_held_out_input.py::test_recorded_held_out_binding_is_deterministic_and_does_not_run_d108`,
is recorded in
`/root/trade-alerts-builder/runs/20260923-195118-906663-build/published-artifacts-55c4a32c7703/summary.json`.
It recorded 106 tests and two-run controller wall time 186.213 seconds. The
two `m91ek-retained-stage3-held-out-input.json` artifacts matched with SHA-256
`59f3c6f1c1de369ce748a8ecd107e0496250eafa7b7588cd6814545992236f5c`.

The tested-source manifest is
`/root/trade-alerts-builder/runs/20260923-195118-906663-build/verified-manifest.json`;
its controller source hash is
`83f2c2c94699ab1f5abc915b5375adae9bd43cda6506835be553dc550beefee7`.
The later documentation-only proof record does not change the tested code or
tests. Accepted exit-side costs, confidence, halt, macro, catalyst,
daily-history, quote-policy, continuity and parent facts remain missing. Their
dependent rules remain OFF and untested. Held-out source coverage, D-108,
result-shard release, alerts and live action remain closed.
