# M9.1ED strict retained stage-1 candidate grouping — 2026-09-23 Pacific

M9.1ED adds one offline boundary after the accepted M9.1EC result connection.
It groups fully costed strict result rows by the exact frozen candidate for each
of the first four playbooks. Every group must carry the same ordered retained
training-session list, and that list must cover all nine frozen training names.
Missing, extra, duplicate, reordered, held-out or candidate-specific partial
coverage is refused.

The boundary rechecks the M9.1EC count relationships, source-gap OFF labels,
candidate identity, complete costs, tested axes and each row's membership in
the supplied training-session list. It carries unresolved, incomplete-cost,
unfilled, no-event and unavailable counts forward unchanged. It does not call
the existing measurement code. Measurement, ranking, result-shard, held-out,
alert and live release remain off.

Current retained outcomes still have no accepted exit-side cost evidence, so
the real strict input has zero fully costed rows. The grouping boundary does
not fill that gap or call an empty group a measured candidate. Real retained
rows also still lack confidence, halt, macro, catalyst, daily-history,
quote-policy, continuity and parent facts. Every dependent rule remains OFF
and untested.

The deterministic synthetic recording covers only this offline contract. It
does not establish real coverage, source qualification, a candidate result,
profit or live readiness.

## Complete milestone delta

- `consensus_engine/retained_stage1_candidate_groups.py`
- `tests/trade_alerts_contracts/test_retained_stage1_candidate_groups.py`
- `trade_alerts_build_docs/M9_1ED_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

Required focused selectors:

- `tests/trade_alerts_contracts/test_retained_stage1_candidate_groups.py`
- `tests/trade_alerts_contracts/test_retained_first_four_stage1_result.py`
- `tests/trade_alerts_contracts/test_stage1_training_measurement.py`

Fresh protected focused, broad acceptance and two-process recording proof are
required. The recording selector is
`tests/trade_alerts_contracts/test_retained_stage1_candidate_groups.py::test_recorded_candidate_groups_are_deterministic_and_keep_measurement_closed`.
No test count, time, recording hash or protected pass is claimed before the
controller publishes those artifacts.

Static Python syntax checks passed. The protected focused launch selected the
three files above and stopped before collection at the launcher's temporary
folder ownership step:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-6ktgi6c5'
```

The reproduced sandbox failure was not retried, and no application test ran
outside protection. The controller must supply the fresh protected stages.

## Final protected verification record — 2026-09-23 Pacific

The supplied controller proof supersedes the earlier sandbox-only launch. The
focused phase ran once with these selectors, selected for `builder named
directly affected checks`:

- `tests/trade_alerts_contracts/test_retained_first_four_stage1_result.py`
- `tests/trade_alerts_contracts/test_retained_stage1_candidate_groups.py`
- `tests/trade_alerts_contracts/test_retained_stage1_candidate_groups.py::test_recorded_candidate_groups_are_deterministic_and_keep_measurement_closed`
- `tests/trade_alerts_contracts/test_stage1_training_measurement.py`

It passed 58 tests with zero failures, errors, and skips. The pytest line was
58.55 seconds, the JUnit time was 58.555 seconds, and controller wall time was
60.484 seconds. The broad acceptance phase ran once with
`tests/trade_alerts_contracts`, selected for `unknown dependency impact; safe
broad fallback`. It passed 4,259 tests with zero failures, errors, and skips.
The pytest line was 1039.31 seconds, the JUnit time was 1039.097 seconds, and
controller wall time was 1044.506 seconds.

The separate repeatability phase ran the 73 selectors recorded in
`published-artifacts-519833aca6af/summary.json` in two fresh protected
processes, including the M9.1ED recording selector above. Each process passed
99 tests with zero failures, errors, and skips. The pytest lines were 221.08
and 209.48 seconds; the JUnit times were 221.074 and 209.474 seconds.
Controller wall time for the two-run phase was 435.801 seconds. The two
`m91ed-retained-stage1-candidate-groups.json` artifacts matched byte-for-byte
with SHA-256
`99a72138f1145c3363406a8c6d3b7b134dd6ab93232fa14702158541220b23d8`.

Published artifact directories are `published-artifacts-9ec1fe7f85f0`,
`published-artifacts-7b965ecc418d`, and `published-artifacts-519833aca6af`
under `/root/trade-alerts-builder/runs/20260923-152540-423198-build/`. The
complete tested-source manifest is `verified-manifest.json` in that run
directory with source hash
`3d9166a610d3a1a07f01619de1c5caa4fe558c317696213a2b8d4ff1556b7e0c`.
This records-only finalization changes only this evidence record and the
roadmap, not the tested code, tests, configuration, dependencies, or protected
inputs.

The real strict input remains empty because accepted exit-side costs are still
missing. Confidence, halt, macro, catalyst, daily-history, quote-policy,
continuity, and parent facts also remain missing. Their dependent rules remain
OFF and untested. Measurement, ranking, result-shard, held-out, alert, profit,
and live release remain off.
