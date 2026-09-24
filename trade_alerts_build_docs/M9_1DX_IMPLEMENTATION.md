# M9.1DX retained first-four evaluator drive — 2026-09-23 Pacific

M9.1DX adds one offline drive boundary after the M9.1DW owner-construction
boundary. Each evaluation context comes from the confidence request already
admitted for that exact plan step. The boundary does not accept a second caller
supplied context list.

Every proposed transition goes to the supplied recording boundary first. The
owner advances only when that boundary returns the exact unchanged transition
tuple. A failed or changed acknowledgment raises before `confirm_recorded()`.
Incomplete retained plans return `UNAVAILABLE` with zero evaluated steps and
zero transitions, so the real confidence, halt, macro, catalyst, daily-history,
quote-policy, continuity and parent gaps remain genuine. Their dependent rules
stay OFF and untested.

Synthetic complete records cover all four first-four owner types in both
directions. They prove only the offline exact-context and record-before-advance
contract. No exact sample, candidate, fill, return, result shard, held-out name,
alert or live action is released.

The recording test writes
`m91dx-retained-first-four-evaluator-drive.json`. It records the synthetic
results and transitions, confirms that every proposed transition was
acknowledged, and naturally qualifies for the controller's two-fresh-process
recording comparison.

The first builder's protected focused launch stopped before collection with
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-ty2gs7c7'` at
temporary-folder ownership. It was not retried. Fresh controller focused,
broad acceptance and two-process recording proof remain required.

## Complete milestone delta

- `consensus_engine/retained_first_four_evaluator_drive.py`
- `tests/trade_alerts_contracts/test_retained_first_four_evaluator_drive.py`
- `trade_alerts_build_docs/M9_1DX_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

The focused selector is
`tests/trade_alerts_contracts/test_retained_first_four_evaluator_drive.py`.
The controller broad stage and discovered repeatability selectors remain
required.

## Escalated repair diagnosis — 2026-09-23 Pacific

The controller subsequently collected the focused file and reported:
`3 failed, 9 passed in 15.68s` (pytest summary, not controller wall time).
Original log: `/root/trade-alerts-builder/runs/20260923-081119-873860-build/verification.log`.
Its exact error was
`consensus_engine.trade_alerts_models.RecordError: the pullback cannot be evaluated before the impulse froze`.
The failing selectors were:

- `tests/trade_alerts_contracts/test_retained_first_four_evaluator_drive.py::test_complete_admitted_owner_uses_exact_context_and_acknowledges_before_advance[LONG-FIRST_PULLBACK_VWAP]`
- `tests/trade_alerts_contracts/test_retained_first_four_evaluator_drive.py::test_complete_admitted_owner_uses_exact_context_and_acknowledges_before_advance[SHORT-FIRST_PULLBACK_VWAP]`
- `tests/trade_alerts_contracts/test_retained_first_four_evaluator_drive.py::test_recorded_exact_context_drive_is_deterministic_and_keeps_release_off`

The drive tests reused the construction-only `_config` helper, whose pullback
window comes from the July 6 replay fixture. Their admitted measurement instead
comes from the January 5 parent-scan fixture. Construction does not evaluate a
pullback; driving it exposes the incompatible dates. The canonical time check
correctly refused this pairing.

The repair keeps production behavior and the original shared fixtures unchanged.
A drive-local helper now takes the impulse window from the same synthetic parent
scan that produced the admitted measurement. It asserts measurement equality
and that the window ends no later than evaluation. Both directions and the
recording test use that helper. Separate rejection cases retain the original
future-window pairing and require the same error, no recording, and unchanged
confirmed state. No missing retained fact is supplied or inferred.

The failed controller stage supplied `tests.runs: 1`,
`tests.selection_reason: "builder named directly affected checks"`,
`tests.selectors: ["tests/trade_alerts_contracts/test_retained_first_four_evaluator_drive.py"]`,
and `tests.test_count: null`. No controller wall time or JUnit time was supplied
for that stage. Prior failed proof and attempt history remain unchanged.

After this repair, the protected focused launcher stopped before collection at
`scripts/testing/run_trade_alerts_contracts.py:27` with
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-b3iesqp0'`.
It was not retried and no application tests ran outside protection. This is a
launcher limitation, not a passing test result. The controller must supply fresh
focused, broad acceptance and repeatability figures, source manifest and hashes.
The recording selector remains
`tests/trade_alerts_contracts/test_retained_first_four_evaluator_drive.py::test_recorded_exact_context_drive_is_deterministic_and_keeps_release_off`;
its named JSON file must be collected and hash-compared in both fresh
repeatability runs before recording proof is claimed. Acceptance remains pending.

## Protected-proof finalization — 2026-09-23 Pacific

The earlier focused failure and temporary-folder stop are historical. The
controller's protected focused phase ran once with `tests.phase=focused`,
`tests.runs=1`, `tests.test_count=3`, `tests.wall_seconds=13.279`, and
`tests.selection_reason="builder named directly affected checks"`. Its exact
selectors were:

- `tests/trade_alerts_contracts/test_retained_first_four_evaluator_drive.py::test_complete_admitted_owner_uses_exact_context_and_acknowledges_before_advance[LONG-FIRST_PULLBACK_VWAP]`
- `tests/trade_alerts_contracts/test_retained_first_four_evaluator_drive.py::test_complete_admitted_owner_uses_exact_context_and_acknowledges_before_advance[SHORT-FIRST_PULLBACK_VWAP]`
- `tests/trade_alerts_contracts/test_retained_first_four_evaluator_drive.py::test_recorded_exact_context_drive_is_deterministic_and_keeps_release_off`

Pytest reported `3 passed in 11.32s`; JUnit time was `11.327` seconds. Broad
acceptance ran once with `tests.phase=acceptance`, `tests.runs=1`,
`tests.test_count=4196`, `tests.wall_seconds=964.42`, and
`tests.selection_reason="unknown dependency impact; safe broad fallback"` on
the selector `tests/trade_alerts_contracts`. Pytest reported `4196 passed in
958.69s`; JUnit time was `958.470` seconds.

Repeatability ran the controller's published selector list in two fresh
processes with `tests.phase=repeatability`, `tests.runs=2`,
`tests.test_count=93`, `tests.wall_seconds=400.285`, and
`tests.selection_reason="recording output requires fresh-process comparison"`.
The selector list is recorded without alteration in
`published-artifacts-2087431c3f5f/summary.json`; it includes
`tests/trade_alerts_contracts/test_retained_first_four_evaluator_drive.py::test_recorded_exact_context_drive_is_deterministic_and_keeps_release_off`.
Pytest times were `197.67` and `197.09` seconds; JUnit times were `197.672`
and `197.091` seconds. The recorded
`m91dx-retained-first-four-evaluator-drive.json` hash was
`7131a9d7c1841b362bde33b3707192c6138be96080fa700c41f6fcc5f7ba5fc6` in
both runs. All published runs had zero failures, errors, and skips, preserved
isolation, and completed cleanup.

The protected artifacts are `published-artifacts-f15521885477`,
`published-artifacts-50812e10bbf3`, and `published-artifacts-2087431c3f5f`
under controller run
`/root/trade-alerts-builder/runs/20260923-081119-873860-build`. The complete
tested-source manifest is `verified-manifest.json`; its tested-source hash is
`4b57e520a44f913a0e2a621c40f75f1ff0cb2de0fd693f78da958bcd79dd15b9`.
Only this finalization record and the ROADMAP changed after that tested source.
