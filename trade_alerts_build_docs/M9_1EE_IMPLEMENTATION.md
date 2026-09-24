# M9.1EE strict retained candidate-group measurement — 2026-09-23 Pacific

M9.1EE adds one offline boundary after the accepted M9.1ED grouping step. It
connects each non-empty, fully costed candidate group to the existing strict
stage-1 training measurement. It accepts only the four frozen first-playbook
candidates in order, the exact shared training-session plan across all nine
training names, complete costs, every tested candidate axis and the required
source-gap OFF labels.

The result stores one training measurement per complete candidate group and
carries all unresolved, incomplete-cost, unfilled, no-event and unavailable
counts forward unchanged. Empty groups are refused. Missing costs or rows are
not filled, treated as zero or measured. Ranking, result-shard release,
held-out access, alerts and live action remain off.

The current real M9.1ED input is empty because accepted exit-side cost evidence
is missing. It therefore cannot cross this measurement boundary. Confidence,
halt, macro, catalyst, daily-history, quote-policy, continuity and parent facts
also remain missing. Their dependent rules remain OFF and untested.

The deterministic synthetic recording proves only this offline connection. It
does not establish real candidate measurements, source qualification, profit,
held-out results or live readiness.

## Complete milestone delta

- `consensus_engine/retained_stage1_candidate_measurements.py`
- `tests/trade_alerts_contracts/test_retained_stage1_candidate_measurements.py`
- `trade_alerts_build_docs/M9_1EE_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

Required focused selectors:

- `tests/trade_alerts_contracts/test_retained_stage1_candidate_measurements.py`
- `tests/trade_alerts_contracts/test_retained_stage1_candidate_groups.py`
- `tests/trade_alerts_contracts/test_stage1_training_measurement.py`

The controller's current discovery rule finds this new recording selector for
both fresh repeatability processes:

- `tests/trade_alerts_contracts/test_retained_stage1_candidate_measurements.py::test_recorded_candidate_measurements_are_deterministic_and_keep_release_closed`

Static Python syntax checks passed. The protected focused launch selected the
three files above and stopped before collection at the launcher's temporary
folder ownership step:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-vqh7q2t4'
```

The reproduced sandbox failure was not retried, and no application test ran
outside protection. The controller later supplied the protected proof below.

## Final protected verification record — 2026-09-23 Pacific

The controller's protected focused phase ran once with
`builder named directly affected checks`. It selected
`tests/trade_alerts_contracts/test_retained_stage1_candidate_groups.py`,
`tests/trade_alerts_contracts/test_retained_stage1_candidate_measurements.py`,
`tests/trade_alerts_contracts/test_retained_stage1_candidate_measurements.py::test_recorded_candidate_measurements_are_deterministic_and_keep_release_closed`,
and `tests/trade_alerts_contracts/test_stage1_training_measurement.py`. It
passed 50 tests with zero failures, errors, and skips. JUnit time was 4.764
seconds; controller wall time was 6.453 seconds. Published artifacts are at
`/root/trade-alerts-builder/runs/20260923-160704-954542-build/published-artifacts-1ee11f8dc1aa`.

The controller's protected broad acceptance phase ran once with `unknown
dependency impact; safe broad fallback`. It selected
`tests/trade_alerts_contracts`, passed 4,275 tests with zero failures, errors,
and skips. JUnit time was 1026.773 seconds; controller wall time was 1032.033
seconds. Published artifacts are at
`/root/trade-alerts-builder/runs/20260923-160704-954542-build/published-artifacts-41fe1daa0262`.

The separate protected repeatability phase ran the 73 selectors recorded in
`published-artifacts-677321f9ef2a/summary.json` twice in fresh processes,
including
`tests/trade_alerts_contracts/test_retained_stage1_candidate_measurements.py::test_recorded_candidate_measurements_are_deterministic_and_keep_release_closed`.
Each run passed 100 tests with zero failures, errors, and skips. JUnit time was
210.388 seconds for run 1 and 210.089 seconds for run 2; the two-run controller
wall time was 425.604 seconds. The two
`m91ee-retained-stage1-candidate-measurements.json` artifacts matched
byte-for-byte with SHA-256
`a784fa8e06d88b38a318b3051ebbac903b736f43cd03ac33e92c735baaff8b2e`.
Published artifacts are at
`/root/trade-alerts-builder/runs/20260923-160704-954542-build/published-artifacts-677321f9ef2a`.

The complete tested-source manifest is
`/root/trade-alerts-builder/runs/20260923-160704-954542-build/verified-manifest.json`;
its controller source hash is
`643e3c7b40616dadfc8336a5c898fe7148dcb1242657db2a898841d235064e25`.
This final record changes documentation only; it does not change tested code,
tests, configuration, dependencies, or protected inputs.
