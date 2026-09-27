# M9.1ER development-only saved-bar readiness counts — 2026-09-25 Pacific

## Current repair: ready for controller verification — 2026-09-25 Pacific

The review identified two causes: the published recording exercised only a
synthetic case, and an inclusive date-range filter materialized intervening
dates before discarding them. The prior blocked assessment below is historical.
The current protected launcher already mounts the exact research script,
binding, audit, expected count record and both saved Parquet files read-only for
the named readiness test. This session did not change any protection file.

The existing partial repair is preserved: `_load` filters exact date membership
and the frozen training tickers before table materialization, and the research
script retains its shared as-of coverage cache. The different approach here
strengthens the tests at the actual failure boundaries:

- `test_saved_file_loader_reads_exact_dates_not_intervening_dates` observes the
  rows returned by the real Parquet filter before later grouping can hide an
  out-of-scope read. Its fixture includes an intervening date and a held-out
  ticker. It checks materialized rows, histories and requested/used sessions.
- `test_recorded_real_24_date_readiness_is_deterministic_and_matches_published_proof`
  calls the actual research script's `main`, changing only its output path to
  `/tmp/M9_1ER_DEVELOPMENT_READINESS_COUNTS.json`. The script verifies the frozen
  source hashes and rebuilds the complete record. The test compares both the
  entire parsed record and its exact bytes against the unchanged published
  record, checks development scope, counts and OFF/CLOSED boundaries, and leaves
  the generated file for the controller to compare between fresh processes.
  No synthetic data or expected-file copy replaces that generated artifact.

Static compilation passed. Applying the unchanged controller discovery predicate
recognizes the new exact recording selector:
`tests/trade_alerts_contracts/test_saved_market_data_readiness.py::test_recorded_real_24_date_readiness_is_deterministic_and_matches_published_proof`.
This is static discovery evidence, not test collection or a protected pass.

The focused protected launcher was attempted normally on
`tests/trade_alerts_contracts/test_saved_market_data_readiness.py`. It stopped
before collection at `scripts/testing/run_trade_alerts_contracts.py:244`:

```text
    os.chown(artifact_root, account.pw_uid, account.pw_gid)
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-fkxcqjl0'
```

No retry or unprotected application test followed. The controller must supply
fresh focused proof, its required broad acceptance selection and two fresh
repeatability runs that each collect the new selector and publish/hash-compare
`M9_1ER_DEVELOPMENT_READINESS_COUNTS.json`. Those stages will supply their phase,
runs, test_count, wall_seconds, selection_reason, selectors, focused result,
run artifacts and complete tested-source manifest; no new stage figures exist
here. Earlier passing proof does not validate these test changes.

The latest pre-repair packet also retains synthetic-only proof at
`/root/trade-alerts-builder/runs/20260925-030854-140270-build/published-artifacts-daa48a545b47`
(focused), `published-artifacts-0eccfd419fc0` (acceptance), and
`published-artifacts-873df39316f7` (repeatability), under that same run root.
The older proof references and rejected claims below remain historical. All
prior failures and attempts remain intact.

The complete milestone delta remains `consensus_engine/saved_market_data_readiness.py`,
`scripts/research/run_saved_market_data_readiness.py`,
`tests/trade_alerts_contracts/test_saved_market_data_readiness.py`,
`trade_alerts_build_docs/M9_1ER_DEVELOPMENT_READINESS_COUNTS.json`,
`trade_alerts_build_docs/M9_1ER_IMPLEMENTATION.md` and
`trade_alerts_build_docs/ROADMAP.md`. This session changes only the test and
status records; the expected saved-data record remains unchanged.

All unsupported inputs and D-104-dependent rules remain OFF and untested;
held-out evaluation and every delivery/live switch remain closed. M9.1ES is the
existing next task, conditional on fresh M9.1ER proof and independent acceptance.

## Historical blocked assessment after independent review

The earlier completion claim below was rejected. The collected tests passed,
but their synthetic recording does not verify the saved-data readiness record.
The date filter also reads intervening dates outside the frozen development
list. Neither obligation is resolved by the historical passing test counts.

Escalated diagnosis found a required protection change outside this assignment:
`scripts/testing/run_trade_alerts_contracts.py::sandbox_command` mounts
`consensus_engine`, `models`, `tests`, `scripts/testing`, `pytest.ini` and the
named shortlist script (plus a conditional collector fixture). It does not mount
`scripts/research/run_saved_market_data_readiness.py`, the binding/audit/count
records under `trade_alerts_build_docs`, or either audited saved bar file.
`trade_alerts_contract_child.py` also blocks child processes, outside reads and
writes outside `/tmp`. Thus the current protected tests cannot execute the real
research script against those exact inputs. This is a source inspection finding;
no new launcher failure or test pass is claimed.

The prior proof is retained at
`/root/trade-alerts-builder/runs/20260925-030854-140270-build/published-artifacts-abc7e289a073`:
both `run-1/m91er-saved-readiness-proof.json` and
`run-2/m91er-saved-readiness-proof.json` contain the synthetic record. The
focused artifacts remain at
`/root/trade-alerts-builder/runs/20260925-030854-140270-build/published-artifacts-a2282a61963a`,
and broad artifacts at
`/root/trade-alerts-builder/runs/20260925-030854-140270-build/published-artifacts-ef0d6cc105f5`.
The original complete tested-source manifest and its hash remain recorded in
the historical proof section below. These record corrections do not convert
that proof into evidence for the absent real-data test.

The different approach in this attempt is to trace the required proof through
the protected mount boundary before repeating any command. A separately reviewed
protection assignment must provide narrowly scoped, immutable offline inputs and
the actual script, preserving source identity and every isolation check. There
is no authorization here to edit the launcher, expose the live tree, copy hidden
inputs through test fixtures, or run application tests outside protection.
No implementation, tests, protected inputs or controller files changed in this
attempt. All prior failures, collected proof and attempt history remain intact.

After that prerequisite, the same M9.1ER repair still needs:

- Replace the inclusive date-range predicate in the research script's `_load`
  with exact date membership before table materialization. Test a real Parquet
  fixture containing an intervening date and prove it never reaches `_batch`
  or the readiness counts; also retain ticker exclusion.
- Execute the actual research script in each protected fresh process, writing
  only under `/tmp`, and compare the entire generated record against
  `M9_1ER_DEVELOPMENT_READINESS_COUNTS.json`. Preserve the frozen source hashes,
  dates and ticker scope. Do not substitute a synthetic record for this check.
- Publish that exact recording in both controller repeatability runs, with
  collected selector IDs and file comparisons. Run the reviewer-required
  `tests/trade_alerts_contracts/test_saved_market_data_readiness.py` first, then
  the controller's broader selection. New stage figures must come from the
  controller; none exist for this unresolved repair.

M9.1ES remains conditional on M9.1ER acceptance and is not an eligible next
milestone now. No new milestone is invented for the protection prerequisite.
All unsupported inputs and D-104-dependent rules remain OFF and untested;
held-out evaluation and every delivery/live switch remain closed.

## Historical result claim — not accepted as protected real-data proof

`M9_1ER_DEVELOPMENT_READINESS_COUNTS.json` runs the existing first-four
adapter-count path through the accepted M9.1EQ binding. It uses only the first
24 dates of M9.1EP's frozen 40-date audit sample. The remaining 16 sample dates
were not read by this run. The run names only the nine frozen development
tickers and reads no held-out ticker.

Both audited files contain only `LLY` from those nine names. Each source has 24
usable `LLY` sessions and 7,392 adapter decision moments. `NVDA`, `MSFT`,
`AAPL`, `TSLA`, `SPY`, `QQQ`, `XLV` and `USO` are absent. Because `SPY` is
absent, relative-strength and warmup readiness are zero. RVOL readiness is also
zero because the existing runner has no requested 20-opening reference window.
The record preserves every not-ready reason rather than filling either gap.

The bar-only last-trade, close and VWAP-level readers are ready at all 1,848
moments per source. Other bar-only readers are partly ready where the required
minute windows exist; their exact counts and reasons are in the JSON record.
These are input-availability counts, not entries, trades, returns or evidence
of profit.

## Safety boundary

All 11 unsupported M9.1EQ inputs remain `OFF_UNTESTED`. All six D-104 gaps
remain explicit with their dependent rules off. The held-out evaluation stayed
closed. No return was calculated. No provider, broker or Discord connection was
made, nothing was bought, and no alert, order, promotion, deployment or live
action occurred.

M9.1EP's 40 dates were already used for a cross-file price agreement check, so
the 16 dates reserved from this readiness run are not claimed as untouched
final-validation evidence. The readiness record does not qualify either saved
file for fills, source finality, corrections, original availability,
point-in-time membership, adjustment history, borrow or options execution.

## Historical controller proof finalization — synthetic coverage only

The earlier local launcher failure is historical. The controller's protected
focused phase ran once and passed 11 tests on
`tests/trade_alerts_contracts/test_saved_market_data_binding.py`,
`tests/trade_alerts_contracts/test_saved_market_data_readiness.py::test_counts_only_bound_inputs_and_keeps_every_unsupported_rule_off`,
`tests/trade_alerts_contracts/test_saved_market_data_readiness.py::test_recorded_readiness_is_deterministic_and_contains_no_result`,
and `tests/trade_alerts_contracts/test_saved_market_data_readiness.py::test_rejects_scope_or_binding_drift`.
Its controller wall time was 64.055 seconds.

The protected broad acceptance phase ran once on
`tests/trade_alerts_contracts` and passed 4,568 tests. Its controller wall time
was 1089.936 seconds. The protected repeatability phase ran its published
recording selection twice in fresh processes, passed 110 tests, and had a
controller wall time of 530.307 seconds. The synthetic readiness proof hash was
`b5d185dbd5efa1fe3ef8d63eeee8f8faa89905a439e0820e731fc072e3652e83` in both
repeatability runs. The controller recorded the complete tested-source manifest
at `/root/trade-alerts-builder/runs/20260925-030854-140270-build/verified-manifest.json`
with source hash `b6bedeace9321e40adb82cadc9b9a0312e07c016e67eb4988b4d877b80c84c3d`.

No code, tests, configuration or protected inputs changed in this records-only
finalization. The 11 unsupported inputs and all six D-104 gap-dependent rule
groups remain OFF and untested. Held-out evaluation, alerts, orders, promotion,
deployment and live action remain closed.

After that proof and independent review, M9.1ES should record the no-evaluation
decision forced by eight missing development tickers, zero relative-strength
readiness and the still-open D-104 source gaps. It must not open a held-out
result unless new qualifying evidence actually closes those requirements.

## Controller protected-proof finalization — 2026-09-25 Pacific

The preceding local ownership failure and the earlier synthetic-only proof are
historical. The controller's fresh protected focused phase ran once with
`tests/trade_alerts_contracts/test_saved_market_data_readiness.py` and
`tests/trade_alerts_contracts/test_saved_market_data_readiness.py::test_recorded_real_24_date_readiness_is_deterministic_and_matches_published_proof`.
It passed 8 tests; the controller wall time was 339.371 seconds and the JUnit
time was 336.746 seconds. Its artifact directory is
`/root/trade-alerts-builder/runs/20260925-030854-140270-build/published-artifacts-de95316b4341`.

The controller's broad acceptance phase ran once with
`tests/trade_alerts_contracts` because of unknown dependency impact; safe broad
fallback. It passed 4,570 tests with controller wall time 1329.914 seconds.
Its artifact directory is
`/root/trade-alerts-builder/runs/20260925-030854-140270-build/published-artifacts-fd0872544867`.

The separate repeatability phase ran the published recording selection twice in
fresh protected processes because recording output requires fresh-process
comparison. It passed 111 tests with controller wall time 1074.334 seconds.
Both runs collected
`tests/trade_alerts_contracts/test_saved_market_data_readiness.py::test_recorded_real_24_date_readiness_is_deterministic_and_matches_published_proof`.
Both emitted `M9_1ER_DEVELOPMENT_READINESS_COUNTS.json` with SHA-256
`e7a6041f9dfa329fe358aaaa8513ce54bc6b1a8ea02ecc0e7761a7d7f63e884f`, and both
emitted `m91er-saved-readiness-proof.json` with SHA-256
`b5d185dbd5efa1fe3ef8d63eeee8f8faa89905a439e0820e731fc072e3652e83`.
The repeatability artifacts are in
`/root/trade-alerts-builder/runs/20260925-030854-140270-build/published-artifacts-224e4401a2cb`.

The controller's complete tested-source manifest is
`/root/trade-alerts-builder/runs/20260925-030854-140270-build/verified-manifest.json`,
with source hash
`b1c051f66d5d4e524ef72c72871d4556958b56bf74f2ac73034b92228fbf5358`.
This finalization changes only this proof record and the roadmap; it does not
change code, tests, configuration or protected inputs. All 11 unsupported
inputs and the six D-104 gap-dependent rule groups remain OFF and untested.
Held-out evaluation, alerts, orders, promotion, deployment and live action stay
closed.
