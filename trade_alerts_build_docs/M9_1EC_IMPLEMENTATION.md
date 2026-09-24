# M9.1EC strict retained stage-1 result connection — 2026-09-23 Pacific

M9.1EC adds one offline boundary after the accepted M9.1EB outcome run.
Current repair: both accepted outcome types lack exit-side spread, slippage
and commission evidence. Every resolved outcome remains an incomplete-cost
exclusion. No `ResolvedTrainingTrade` row is emitted. Unknown outcomes remain
counted unresolved; unfilled, no-event and unavailable counts carry forward.
No missing cost is approximated or assumed zero.

The prior implementation mistook `fill.total_cost_per_share`, which covers
entry only, for complete round-trip costs. It also trusted `resolved_r`, and
the synthetic test supplied an arbitrary return. The repair removes that
admission path. Before classifying a resolved shared outcome as excluded, it
checks finite entry, actual risk and return; matching fill direction and
modeled entry; exit count and ordered unit identities; finite positive exit
prices; supported reasons and target names; chronological exit times between
fill and evaluation; and the average exit and direction-aware R calculation.
These are consistency checks, not historical price or exit-cost proof.

The boundary still rejects held-out names, catalog drift, changed fills,
foreign source identities, dropped source-gap off labels and opened later
releases. It creates no measurement or ranking. Result-shard, held-out, alert
and live release remain off.

Direct cases reject changed return, risk, direction, entry, average exit,
exit price, missing/duplicate/wrong units, invalid timing, reason and target,
and nonfinite numbers. Actual shared-evaluator outcomes in both directions
also remain excluded despite modeled entry costs. The synthetic split-unit
fixture now derives its return from exits and non-unit risk. Its recording
asserts an empty admitted result and preserved incomplete-cost counts, then
writes `m91ec-retained-first-four-stage1-result.json` for fresh-process
comparison. Synthetic cases prove only this offline boundary.

## Complete milestone delta

- `consensus_engine/retained_first_four_stage1_result.py`
- `tests/trade_alerts_contracts/test_retained_first_four_stage1_result.py`
- `trade_alerts_build_docs/M9_1EC_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

Historical initial attempt: static syntax checks passed. The protected focused launch selected
`tests/trade_alerts_contracts/test_retained_first_four_stage1_result.py` and
stopped before collection at the launcher's temporary-folder ownership step:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-s5moz6m_'
```

The reproduced sandbox failure was not retried, and no application test ran
outside protection. The controller must supply fresh focused, broad acceptance
and two-process recording proof. No test count, timing, recording hash or pass
is claimed here.

The real retained rows still lack confidence, halt, macro, catalyst,
daily-history, quote-policy, continuity and parent facts. Their dependent rules
remain OFF and untested. The exit-cost-dependent paths for all four playbooks remain OFF and untested.
No source, final-result, result-shard, held-out, alert, profit or live gate is
closed.

## Historical pre-repair protected verification record (review rejected) — 2026-09-23 Pacific

These runs cover the rejected pre-repair code only, not the current repair.
Their artifacts and original source identity remain preserved.
The supplied controller verification handoff superseded the earlier
temporary-folder ownership stop. The focused phase was one protected run of
`tests/trade_alerts_contracts/test_retained_first_four_stage1_result.py`,
selected because the builder named directly affected checks. It passed 5 tests;
the pytest line was 16.90 seconds, the JUnit time was 16.904 seconds, and the
controller wall time was 18.837 seconds. The broad acceptance phase was one
protected run of `tests/trade_alerts_contracts`, selected for `unknown
dependency impact; safe broad fallback`. It passed 4,224 tests; the pytest line
was 970.00 seconds, the JUnit time was 969.799 seconds, and the controller wall
time was 975.667 seconds. Both phases had zero failures, errors, and skips.

The repeatability phase used the controller-recorded 98 selectors in two fresh
protected processes, including
`tests/trade_alerts_contracts/test_retained_first_four_stage1_result.py::test_recorded_stage1_result_connection_is_deterministic_and_keeps_release_off`.
Each run passed 98 tests with zero failures, errors, and skips. Its pytest lines
were 206.99 and 210.50 seconds; its JUnit times were 206.991 and 210.496
seconds. The controller recorded 423.258 seconds for the two-run phase. The two
`m91ec-retained-first-four-stage1-result.json` artifacts matched byte-for-byte
with SHA-256
`e19159105be1062a51a0f2e1224ebbbbe84c5a99cb59f5f048a14d5e327beec9`.

The controller artifacts are under
`/root/trade-alerts-builder/runs/20260923-141055-496631-build/`; the tested
source manifest is `verified-manifest.json` with source hash
`7e2d9ef43ad9f246ac4732e87fad66d8ab1965a4ed41190d033a0641c3cb1ead`.
That earlier records-only finalization changed no tested inputs. The current
code and test repair invalidates that proof for current acceptance. The real retained rows still lack
confidence, halt, macro, catalyst, daily-history, quote-policy, continuity and
parent facts. Their dependent rules, plus all four exit-cost paths, remain OFF
and untested. Result-shard, held-out, alert, profit and live release remain off.

## Repair verification pending — 2026-09-23 Pacific

The reviewer rejected the entry-only cost claim and unchecked return. Prior
failures and collected proof above remain historical. M9.1EC is open pending
fresh protected verification and independent review. M9.1ED remains open but
must not advance before M9.1EC acceptance.

Required focused selectors:

- `tests/trade_alerts_contracts/test_retained_first_four_stage1_result.py`
- `tests/trade_alerts_contracts/test_playbook_outcome_evaluator.py`
- `tests/trade_alerts_contracts/test_fill_cost_model.py`

The controller must supply current focused and broad acceptance figures,
complete tested-source manifest, and both fresh repeatability artifacts with
the exact recording selector and compared hashes. No historical pass proves
the repair. No source, final, profit or live gate is closed.

The repaired focused launch stopped before collection at the protected
launcher's temporary-folder ownership change:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-jbryrw4m'
```

This sandbox failure was not retried. No application tests ran outside the
protected launcher. Static Python syntax checks passed; they are not test
proof. The controller stages must supply all current pass counts, timings,
source hashes and compared recording artifacts.

## Final protected verification record — 2026-09-23 Pacific

The repaired boundary received the supplied protected controller proof. The
focused phase ran once with the four recorded selectors:

- `tests/trade_alerts_contracts/test_fill_cost_model.py`
- `tests/trade_alerts_contracts/test_playbook_outcome_evaluator.py`
- `tests/trade_alerts_contracts/test_retained_first_four_stage1_result.py`
- `tests/trade_alerts_contracts/test_retained_first_four_stage1_result.py::test_recorded_stage1_result_connection_is_deterministic_and_keeps_release_off`

It was selected for `builder named directly affected checks`, passed 50 tests,
and had zero failures, errors, and skips. The pytest line was 58.87 seconds,
the JUnit time was 58.866 seconds, and controller wall time was 60.728
seconds. The broad acceptance phase ran once with
`tests/trade_alerts_contracts`, selected for `unknown dependency impact; safe
broad fallback`. It passed 4,243 tests with zero failures, errors, and skips.
The pytest line was 1033.31 seconds, the JUnit time was 1033.083 seconds, and
controller wall time was 1038.748 seconds.

The separate repeatability phase ran the controller-recorded 98 selectors in
two fresh protected processes, including
`tests/trade_alerts_contracts/test_retained_first_four_stage1_result.py::test_recorded_stage1_result_connection_is_deterministic_and_keeps_release_off`.
Each process passed 98 tests with zero failures, errors, and skips. The pytest
lines were 210.24 and 209.41 seconds; the JUnit times were 210.241 and 209.407
seconds. Controller wall time for the two-run phase was 425.416 seconds. The
two `m91ec-retained-first-four-stage1-result.json` artifacts matched
byte-for-byte with SHA-256
`4d0db6e25b7af310336faa29482ff677a0a1109a81a61ec6abdaea930bc4e5ad`.

Published artifact directories are
`published-artifacts-1534e44015d4`, `published-artifacts-d4388dd93e15`, and
`published-artifacts-96bbf514fc98` under
`/root/trade-alerts-builder/runs/20260923-141055-496631-build/`. The complete
tested-source manifest is `verified-manifest.json` in that run directory with
source hash `e442db06b0ac1f5fd2204fb92a74324e9a5f4fcf1464c8dc19a41b9f4dd94cfe`.
This records-only finalization changes only these evidence records and the
roadmap, not the tested code, tests, configuration, dependencies, or protected
inputs.

The shared and ORB5 outcomes remain incomplete-cost exclusions because
exit-side costs are absent. The real retained rows still lack confidence, halt,
macro, catalyst, daily-history, quote-policy, continuity and parent facts.
Every dependent rule remains OFF and untested. Result-shard, held-out, alert,
profit and live release remain off.
