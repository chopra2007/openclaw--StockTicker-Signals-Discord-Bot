# M9.1EH retained stage-2 input binding — 2026-09-23 Pacific

## Scope

M9.1EH adds the closed offline boundary that binds each accepted M9.1EG
stage-1 winner to its matching complete-cost training events. It does not rank
the five stage-2 candidates, open held-out names, release a result shard, send
an alert or act live.

## Changed files

- `consensus_engine/retained_stage2_input.py`
- `tests/trade_alerts_contracts/test_retained_stage2_input.py`
- `trade_alerts_build_docs/M9_1EH_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

## Contract

`bind_retained_stage2_inputs` accepts the complete closed M9.1EG ranking and
one ordered event stream for each first-four playbook. It reconstructs the
complete 18/4/2/4 measurement catalog and reruns the frozen stage-1 ranking,
so a changed winner, measurement, exclusion count, source-gap OFF label,
training plan or candidate entry is rejected.

Each supplied event must name the retained winner, stay within the frozen
nine-name training plan, preserve a unique ticker-day-side event, carry every
candidate axis, cite source record identities and have complete accepted
costs. The exact events must reproduce the winner's frozen training
measurement. The output uses the existing `AcceptedStage1Winner` shape needed
by the stage-2 comparison boundary while also preserving the full source
ranking.

The output explicitly leaves stage-2 ranking, held-out access, result-shard
release, alerts and live action off.

## Focused checks

The new focused file covers successful first-four binding, preservation of all
18/4/2/4 candidate measurements, changed or opened ranking rejection, missing
playbooks, wrong candidates, held-out names, incomplete costs, wrong axes,
measurement mismatch and repeated events. Its recording check writes
`m91eh-retained-stage2-input.json` and is designed for both fresh controller
repeatability processes.

The controller's actual discovery rule selects:

- `tests/trade_alerts_contracts/test_retained_stage2_input.py::test_recorded_retained_stage2_input_is_deterministic_and_keeps_stage2_closed`

The initial protected launcher attempt stopped before collection at its
temporary-folder ownership step with `OSError: [Errno 22] Invalid argument`.
That sandbox failure was not retried and no application test ran outside the
protected launcher. The subsequent controller failure and repair are below.

## Escalated repair and pending verification

The controller's prior failure is preserved at
`/root/trade-alerts-builder/runs/20260923-184615-600770-build/verification.log`.
The failing case was
`tests/trade_alerts_contracts/test_retained_stage2_input.py::test_rejects_changed_ranking_or_nonmatching_winner_events[held_out]`,
with `E   Failed: DID NOT RAISE <class 'consensus_engine.trade_alerts_models.RecordError'>`.
The controller log reports `1 failed, 11 passed in 58.35s` for that file;
this is failed historical proof, not acceptance of the repaired test.

Cause: the test called AAPL a held-out name, but D-107 and
`M9_1T_PARAMETER_GRID_PREREGISTRATION.md` section 1 place AAPL in training.
The event still matched an allowed training session and reproduced the same
measurement, so the existing binding correctly accepted it. The repair uses
`HELD_OUT_TICKERS[0]` (GOOGL) and explicitly asserts that it is outside
`TRAINING_TICKERS` before testing rejection. This changes the erroneous test
input rather than changing the frozen split or the production acceptance rule.
The original failing test ID remains. No held-out market data was read.

The supplied controller selection remains:

- `tests/trade_alerts_contracts/test_retained_stage1_ranking.py`
- `tests/trade_alerts_contracts/test_retained_stage2_input.py`
- `tests/trade_alerts_contracts/test_retained_stage2_input.py::test_recorded_retained_stage2_input_is_deterministic_and_keeps_stage2_closed`
- `tests/trade_alerts_contracts/test_stage2_training_comparison.py`

Its supplied selection reason is `builder named directly affected checks`.
The repaired failing case was attempted first through the unchanged protected
launcher. It stopped before collection at `os.chown` with
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-w38v8uqi'`.
No retry or unprotected application test followed. Fresh controller focused,
broad acceptance and separate two-process recording proof remain required,
including discovery, collection and hash comparison of
`m91eh-retained-stage2-input.json` in both repeatability runs.
The controller stages will supply their phase names, runs, test counts, wall
seconds, selection reasons, exact selectors, focused details, JUnit times,
pytest lines, artifact locations and tested-source manifest. No repaired pass
is claimed. Prior attempts and counters remain intact.

## Open gates

The real strict input remains empty because accepted exit-side costs are
missing. Confidence, halt, macro, catalyst, daily-history, quote-policy,
continuity and parent facts also remain missing. Their dependent rules remain
OFF and untested. Source, final, held-out, result-shard, alert and live gates
remain closed.

After M9.1EH acceptance, M9.1EI may pass this exact closed winner tuple into
the existing five-candidate stage-2 comparison and record the frozen training
winner without opening held-out names.

## Final protected verification record — 2026-09-23 Pacific

The controller's focused protected run selected
`tests/trade_alerts_contracts/test_retained_stage2_input.py::test_rejects_changed_ranking_or_nonmatching_winner_events[held_out]`
for `builder named directly affected checks`. It ran once, passed 1 test with
zero failures, errors, and skips, and had controller wall time 7.789 seconds.
Pytest reported `1 passed in 6.11s`; the JUnit report time was 6.114 seconds.
The published focused artifact directory is
`/root/trade-alerts-builder/runs/20260923-184615-600770-build/published-artifacts-a67a3e022cce`.

The controller's broad protected acceptance run selected
`tests/trade_alerts_contracts` for `unknown dependency impact; safe broad
fallback`. It ran once, passed 4,474 tests with zero failures, errors, and
skips, and had controller wall time 433.972 seconds. The three isolated pytest
shards reported `2177 passed in 345.42s (0:05:45)`, `1151 passed in 332.70s
(0:05:32)`, and `1146 passed in 429.76s (0:07:09)`; the merged JUnit report
records zero failures, errors, and skips. The published broad artifact directory is
`/root/trade-alerts-builder/runs/20260923-184615-600770-build/published-artifacts-62d1418ea1ee`.

The separate repeatability phase used the controller-recorded 77 selectors in
two fresh protected processes, including
`tests/trade_alerts_contracts/test_retained_stage2_input.py::test_recorded_retained_stage2_input_is_deterministic_and_keeps_stage2_closed`.
The controller records 103 tests and two-run wall time 163.247 seconds. Run 1's
three isolated pytest shards reported `31 passed in 79.28s (0:01:19)`, `45
passed in 74.61s (0:01:14)`, and `27 passed in 76.44s (0:01:16)`. Run 2's
three shards reported `31 passed in 78.99s (0:01:18)`, `45 passed in 74.21s
(0:01:14)`, and `27 passed in 75.96s (0:01:15)`. The merged JUnit reports each
contain all 103 tests with zero failures, errors, and skips. Both
`m91eh-retained-stage2-input.json` artifacts matched byte-for-byte with
SHA-256 `f147e16ac46f2544c1a82b73554d466b889a828e41faead1692e1b9148f436a2`.
The published repeatability artifact directory is
`/root/trade-alerts-builder/runs/20260923-184615-600770-build/published-artifacts-c455ed57a7ed`.

The tested-source manifest is
`/root/trade-alerts-builder/runs/20260923-184615-600770-build/verified-manifest.json`;
its source hash is
`21b5a78081cafdfda69805d2613f674df34c2bb1fa177eb846615b76bdbfb25e`.
This final record changes documentation only. The accepted exit-side-cost,
confidence, halt, macro, catalyst, daily-history, quote-policy, continuity and
parent-fact gaps remain. Their dependent rules remain OFF and untested;
held-out data, stage-2 ranking, result-shard release, alerts and live action
remain closed.
