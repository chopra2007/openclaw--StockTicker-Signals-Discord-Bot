# M9.1EF complete retained stage-1 measurement catalog — 2026-09-23 Pacific

M9.1EF adds one offline boundary after M9.1EE. It accepts one complete M9.1EE
measurement record for every frozen first-four candidate, requires the exact
18/4/2/4 catalog in preregistered order, and requires the same exact ordered
training-session coverage across all nine training names before the catalog is
complete.

Every measurement keeps its source run's unresolved, incomplete-cost,
unfilled, no-event and unavailable exclusions. Required source-gap rules stay
OFF and untested. Missing, duplicate, reordered, changed-coverage, changed-rule
or already-released inputs are refused. Ranking, result-shard release,
held-out access, alerts and live action remain off.

The real strict input remains empty because accepted exit-side costs are
missing. Confidence, halt, macro, catalyst, daily-history, quote-policy,
continuity and parent facts also remain missing. Their dependent rules remain
OFF and untested.

The deterministic synthetic recording proves only this offline catalog
boundary. It does not establish real candidate measurements, ranking, source
qualification, profit, held-out results or live readiness.

## Complete milestone delta

- `consensus_engine/retained_stage1_measurement_catalog.py`
- `tests/trade_alerts_contracts/test_retained_stage1_measurement_catalog.py`
- `trade_alerts_build_docs/M9_1EF_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

Required focused selectors:

- `tests/trade_alerts_contracts/test_retained_stage1_measurement_catalog.py`
- `tests/trade_alerts_contracts/test_retained_stage1_candidate_measurements.py`
- `tests/trade_alerts_contracts/test_search_run_config.py`

The controller's current discovery rule finds this recording selector for both
fresh repeatability processes:

- `tests/trade_alerts_contracts/test_retained_stage1_measurement_catalog.py::test_recorded_full_candidate_catalog_is_deterministic_and_keeps_ranking_closed`

Fresh protected focused, broad acceptance and two-process recording proof and
independent review remain required.

Static Python syntax checks passed. The protected focused launch selected the
three files above and stopped before collection at the launcher's temporary
folder ownership step:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-7v1azojq'
```

The reproduced sandbox failure was not retried, and no application test ran
outside protection. The controller must supply the protected proof.

## Historical pre-repair protected verification — review rejected, 2026-09-23 Pacific

These runs covered the initial implementation. Independent review found the
unchecked nested measurement shape and numeric values described below. This
proof is preserved, but does not cover the repair or establish acceptance.

The controller's protected focused phase ran once with `builder named directly
affected checks`. It selected
`tests/trade_alerts_contracts/test_retained_stage1_candidate_measurements.py`,
`tests/trade_alerts_contracts/test_retained_stage1_measurement_catalog.py`, and
`tests/trade_alerts_contracts/test_search_run_config.py`. It passed 47 tests
with zero failures, errors, and skips. Pytest reported `47 passed in 3.64s`;
JUnit time was 3.645 seconds and controller wall time was 5.376 seconds.
Published artifacts are at
`/root/trade-alerts-builder/runs/20260923-164411-396403-build/published-artifacts-1d4e3389788e`.

The controller's protected broad acceptance phase ran once with `unknown
dependency impact; safe broad fallback`. It selected
`tests/trade_alerts_contracts`, passed 4,290 tests with zero failures, errors,
and skips. Pytest reported `4290 passed in 1059.93s (0:17:39)`; JUnit time was
1059.722 seconds and controller wall time was 1065.097 seconds. Published
artifacts are at
`/root/trade-alerts-builder/runs/20260923-164411-396403-build/published-artifacts-61835d71547f`.

The separate protected repeatability phase used the 75 selectors recorded in
`published-artifacts-ef9513094ecf/summary.json` twice in fresh processes,
including
`tests/trade_alerts_contracts/test_retained_stage1_measurement_catalog.py::test_recorded_full_candidate_catalog_is_deterministic_and_keeps_ranking_closed`.
Each run passed 101 tests with zero failures, errors, and skips. Pytest reported
`101 passed in 208.78s (0:03:28)` for run 1 and `101 passed in 210.94s
(0:03:30)` for run 2; JUnit time was 208.779 seconds for run 1 and 210.934
seconds for run 2. The two-run controller wall time was 424.875 seconds. The
two `m91ef-retained-stage1-measurement-catalog.json` artifacts matched
byte-for-byte with SHA-256
`c947186240dce4ad07f33a557dcf01e89d59922cd28a3c56382ba5140d27e8ba`.
Published artifacts are at
`/root/trade-alerts-builder/runs/20260923-164411-396403-build/published-artifacts-ef9513094ecf`.

The complete tested-source manifest is
`/root/trade-alerts-builder/runs/20260923-164411-396403-build/verified-manifest.json`;
its controller source hash is
`431896e49bb1ebd443175102b321ee71e8a1147df891c06b539714e32861abcf`.
That earlier finalization changed documentation only. The repair below changes
code and tests, so fresh controller proof is required.

## Review repair — 2026-09-23 Pacific

The reported failure was that `_validate_source` accepted exact-version records
with a forged `TrainingMeasurement` containing NaN values and could mark the
catalog complete. A missing nested measurement instead raised `AttributeError`
rather than `RecordError`. Review required
`tests/trade_alerts_contracts/test_retained_stage1_measurement_catalog.py`.

Cause: version labels and outer row fields were checked without checking the
measurement container or nested record type. Row fields were read and trade
counts summed before every row had been validated. Neither dataclass validates
its own numeric values.

The repair validates the tuple container, each outer measurement, its nested
`TrainingMeasurement`, and the frozen `Candidate` before reading nested values.
Counts are summed only after validating every row. Mean profit and bootstrap
lower bound must be finite numbers. Weekly win rate must be finite and between
zero and one. Recovery must be nonnegative; positive infinity remains valid
because the existing producer emits it when recovery is unavailable. Booleans,
strings, missing values, NaN and negative infinity are refused. Week count must
be positive and cannot exceed trade count.

New refusal cases cover malformed containers, rows and nested measurements,
invalid candidates, invalid counts and numeric values in every first-four row,
including rows other than the one selected by the catalog key. A producer-path
test preserves actual losing, flat and winning synthetic measurements, including
the valid unavailable-recovery value. The existing deterministic recording
selector remains required in both fresh controller repeatability runs.

The protected focused launch used the three required focused selectors listed
above and stopped before collection at `os.chown` in the unchanged launcher:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-b0ozcjs8'
```

This sandbox failure was not retried. No application tests ran outside protection.
The controller must supply fresh focused, broad acceptance and separate
two-process recording proof, including selectors, counts, times, source manifest,
recording hashes and comparisons. No repaired test pass is claimed. All prior
failures and collected proof remain historical; attempts were not reset.

The complete milestone delta remains the four paths listed above. M9.1EG stays
open, dependent on M9.1EF acceptance. Real missing inputs and their OFF/untested
rules, held-out restrictions and all later release gates remain unchanged.

## Final protected verification record — 2026-09-23 Pacific

The controller supplied fresh protected proof for the nested-measurement repair.
One focused run selected
`tests/trade_alerts_contracts/test_retained_stage1_candidate_measurements.py`,
`tests/trade_alerts_contracts/test_retained_stage1_measurement_catalog.py`,
`tests/trade_alerts_contracts/test_retained_stage1_measurement_catalog.py::test_recorded_full_candidate_catalog_is_deterministic_and_keeps_ranking_closed`,
and `tests/trade_alerts_contracts/test_search_run_config.py` for `builder named
directly affected checks`. It passed 198 tests with zero failures, errors, and
skips. Pytest reported `198 passed in 6.07s`; JUnit time was 6.066 seconds and
controller wall time was 7.959 seconds. Published artifacts are at
`/root/trade-alerts-builder/runs/20260923-164411-396403-build/published-artifacts-cc426808a749`.

One broad acceptance run selected `tests/trade_alerts_contracts` for `unknown
dependency impact; safe broad fallback`. It passed 4,441 tests with zero
failures, errors, and skips. Pytest reported `4441 passed in 1062.03s
(0:17:42)`; JUnit time was 1061.821 seconds and controller wall time was
1067.573 seconds. Published artifacts are at
`/root/trade-alerts-builder/runs/20260923-164411-396403-build/published-artifacts-a71772efb4e6`.

The separate repeatability phase ran the controller-recorded 73 selectors in
two fresh protected processes, including
`tests/trade_alerts_contracts/test_retained_stage1_measurement_catalog.py::test_recorded_full_candidate_catalog_is_deterministic_and_keeps_ranking_closed`.
Run 1 and run 2 each passed 101 tests with zero failures, errors, and skips.
Pytest reported `101 passed in 209.79s (0:03:29)` for run 1 and `101 passed in
210.65s (0:03:30)` for run 2; JUnit time was 209.787 seconds for run 1 and
210.648 seconds for run 2. The two-run controller wall time was 426.56 seconds.
The two `m91ef-retained-stage1-measurement-catalog.json` artifacts matched
byte-for-byte with SHA-256
`c947186240dce4ad07f33a557dcf01e89d59922cd28a3c56382ba5140d27e8ba`.
Published artifacts, including the complete selector list and both compared
recordings, are at
`/root/trade-alerts-builder/runs/20260923-164411-396403-build/published-artifacts-d4abb3d78abf`.

The complete tested-source manifest is
`/root/trade-alerts-builder/runs/20260923-164411-396403-build/verified-manifest.json`;
its controller source hash is
`d1654a0fd935e7096d0d5e864946107d496b1442e0b46922fbbf57d3824d9fe6`.
This final record changes documentation only.

The real strict input remains empty because accepted exit-side costs are
missing. Confidence, halt, macro, catalyst, daily-history, quote-policy,
continuity and parent facts remain missing. Their dependent rules remain OFF
and untested. Measurement, ranking, result-shard, held-out, alert, profit and
live release remain off.
