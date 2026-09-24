# M9.1EG retained per-playbook stage-1 ranking — 2026-09-23 Pacific

M9.1EG adds one offline boundary after M9.1EF. It accepts only the complete,
closed 18/4/2/4 retained measurement catalog and applies the frozen stage-1
rule independently to each first-four playbook. Highest mean profit after
costs wins. Ties use highest weekly win rate, then lowest drawdown recovery,
then the earliest preregistered table row.

The result preserves every candidate measurement and its unresolved,
incomplete-cost, unfilled, no-event and unavailable exclusions. Exact shared
nine-name training coverage and all required source-gap OFF labels are checked
again before ranking. Changed, incomplete, malformed, reordered or
already-open inputs are refused. Held-out names remain sealed. No result shard,
alert or live action is released.

The real strict input remains empty because accepted exit-side costs are
missing. Confidence, halt, macro, catalyst, daily-history, quote-policy,
continuity and parent facts also remain missing. Their dependent rules remain
OFF and untested. The deterministic synthetic recording proves only this
offline ranking contract. It proves no real winner, profit, source
qualification, held-out result or live readiness.

## Complete milestone delta

- `consensus_engine/retained_stage1_ranking.py`
- `tests/trade_alerts_contracts/test_retained_stage1_ranking.py`
- `trade_alerts_build_docs/M9_1EG_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

Required focused selectors:

- `tests/trade_alerts_contracts/test_retained_stage1_ranking.py`
- `tests/trade_alerts_contracts/test_retained_stage1_measurement_catalog.py`
- `tests/trade_alerts_contracts/test_search_run_config.py`

The controller's discovery rule finds this recording selector for both fresh
repeatability processes:

- `tests/trade_alerts_contracts/test_retained_stage1_ranking.py::test_recorded_stage1_ranking_is_deterministic_and_keeps_later_release_closed`

Historical initial attempt: static Python syntax checks passed. The protected focused launch selected the
three files above and stopped before collection at the unchanged launcher's
temporary-folder ownership step:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-3o5oplcq'
```

The reproduced sandbox failure was not retried, and no application test ran
outside protection. The controller must supply fresh focused, broad acceptance
and two-process recording proof. M9.1EH remains open for fresh review after
M9.1EG acceptance.

## Escalated repair — source-run totals versus one playbook

The controller's prior focused run failed with
`consensus_engine.trade_alerts_models.RecordError: ranking catalog exclusion counts do not match`.
Its log is `/root/trade-alerts-builder/runs/20260923-175615-710589-build/verification.log`.
The published pytest line was `3 failed, 195 passed in 5.06s`; this is historical
failure evidence, not repaired acceptance. The supplied controller summary records
phase `focused`, runs `1`, test_count `null`, selection_reason
`builder named directly affected checks`; controller wall_seconds was not supplied.
JUnit time was not supplied. Its selectors, in supplied order, were:

- `tests/trade_alerts_contracts/test_retained_stage1_measurement_catalog.py`
- `tests/trade_alerts_contracts/test_retained_stage1_ranking.py`
- `tests/trade_alerts_contracts/test_retained_stage1_ranking.py::test_recorded_stage1_ranking_is_deterministic_and_keeps_later_release_closed`
- `tests/trade_alerts_contracts/test_search_run_config.py`

The failed IDs were:

- `tests/trade_alerts_contracts/test_retained_stage1_ranking.py::test_each_playbook_uses_frozen_rank_and_preserves_every_catalog_entry`
- `tests/trade_alerts_contracts/test_retained_stage1_ranking.py::test_frozen_ties_use_win_rate_recovery_then_table_order`
- `tests/trade_alerts_contracts/test_retained_stage1_ranking.py::test_recorded_stage1_ranking_is_deterministic_and_keeps_later_release_closed`

Cause: M9.1EE sums fully costed trades across all four nonempty playbook
measurements. M9.1EF copies that source-run total and its exclusions into each
catalog entry, alongside only the selected playbook measurement. M9.1EG wrongly
required that total to equal the selected playbook's trade count. The supplied
valid fixture had four source-run trades and one selected-playbook trade.

The repair keeps source-run totals intact and checks that the total can contain
the selected playbook plus at least one trade for each other playbook. Both
existing exclusion arithmetic checks remain. Exact reconciliation of the whole
source-run sum remains at M9.1EF, where all four measurements are available;
unrelated catalog entries must not be summed as if they came from one source run.
The new checks cover unequal valid playbook counts, the exact minimum total,
and selected counts that leave too few trades for the other playbooks or exceed
the total. The recording now uses unequal counts and compares repeated ranking
outputs before writing its artifact. Prior failed tests and attempts are retained.

The repaired focused launch selected the three file-level selectors above and
stopped before collection at the unchanged protected launcher:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-4s8_9qyd'
```

No retry or unprotected application test followed. Static syntax checks are
separate from product acceptance. The controller must supply fresh focused and
broad acceptance figures, source manifest and isolation/cleanup evidence, plus
both fresh repeatability runs and the hash comparison of
`m91eg-retained-stage1-ranking.json`. No repaired pass or recording comparison
is claimed. M9.1EH remains proposed only after M9.1EG acceptance. All source-gap
OFF/untested labels and held-out, result, alert and live boundaries stay closed.

## Final protected verification record — 2026-09-23 Pacific

The controller supplied the final protected proof for the repaired ranking
boundary. The focused phase ran once, for `builder named directly affected
checks`, with these three selectors:

- `tests/trade_alerts_contracts/test_retained_stage1_ranking.py::test_each_playbook_uses_frozen_rank_and_preserves_every_catalog_entry`
- `tests/trade_alerts_contracts/test_retained_stage1_ranking.py::test_frozen_ties_use_win_rate_recovery_then_table_order`
- `tests/trade_alerts_contracts/test_retained_stage1_ranking.py::test_recorded_stage1_ranking_is_deterministic_and_keeps_later_release_closed`

It passed 3 tests with zero failures, errors, and skips. Pytest reported `3
passed in 1.91s`; JUnit time was 1.916 seconds and controller wall time was
3.705 seconds. Its published artifact directory is
`/root/trade-alerts-builder/runs/20260923-175615-710589-build/published-artifacts-61f0f80c7fa2`.

The broad acceptance phase ran once, selecting
`tests/trade_alerts_contracts` for `unknown dependency impact; safe broad
fallback`. It passed 4,462 tests with zero failures, errors, and skips. Pytest
reported `4462 passed in 1032.65s (0:17:12)`; JUnit time was 1032.466 seconds
and controller wall time was 1037.662 seconds. Its published artifact directory
is `/root/trade-alerts-builder/runs/20260923-175615-710589-build/published-artifacts-958fb871ea4f`.

The separate repeatability phase ran the controller-recorded 76 selectors in
two fresh protected processes for `recording output requires fresh-process
comparison`, including
`tests/trade_alerts_contracts/test_retained_stage1_ranking.py::test_recorded_stage1_ranking_is_deterministic_and_keeps_later_release_closed`.
Each run passed 102 tests with zero failures, errors, and skips. JUnit time was
208.864 seconds for run 1 and 210.813 seconds for run 2. Pytest reported `102
passed in 208.86s (0:03:28)` for run 1 and `102 passed in 210.82s (0:03:30)`
for run 2; the two-run controller wall time was 424.874 seconds. The two
`m91eg-retained-stage1-ranking.json` artifacts matched byte-for-byte with
SHA-256 `6e66a624741f124764fee8d2d160a81ecc6b902963463ff647dfa419f4cd08fd`.
The repeatability artifact directory is
`/root/trade-alerts-builder/runs/20260923-175615-710589-build/published-artifacts-b98f696c5131`;
its `summary.json` holds the complete selector list and its `publication.json`
holds both artifact hashes.

The tested-source manifest is
`/root/trade-alerts-builder/runs/20260923-175615-710589-build/verified-manifest.json`;
its source hash is
`126eb58b21fb434036fa0c774b036c93e408f352ff7ac20ef19a71f1772518dd`.
This final record changes documentation only. The accepted exit-side costs,
confidence, halt, macro, catalyst, daily-history, quote-policy, continuity and
parent facts remain missing. Their dependent rules remain OFF and untested;
held-out names, result-shard release, alerts and live action remain closed.
