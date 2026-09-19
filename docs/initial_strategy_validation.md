# Initial strategy validation

Date: 2026-09-13 Pacific. Evidence stage: `INSUFFICIENT_DATA`.

This report publishes the M9.1 result for the first four playbooks. It does not
upgrade any playbook to `HISTORICALLY_TESTED`. It does not report returns, edge,
shadow results, promotion, activation or permission to trade. All switches stay
off.

## Results

| Playbook | Result | Strategy source owner | Reopening test |
|---|---|---|---|
| `CRVOL_ORB5` | `INSUFFICIENT_DATA` | M6.4 | Supply the common source and rule evidence below, then replay the frozen `CRVOL_ORB5` version twice from the same manifest and compare ordered results and recording bytes. |
| `HOD_COMP_RS` | `INSUFFICIENT_DATA` | M7.5 | Supply the common source and rule evidence below, then replay the frozen `HOD_COMP_RS` version twice from the same manifest and compare ordered results and recording bytes. |
| `OR_FAILURE_REV` | `INSUFFICIENT_DATA` | M8.2 | Supply the common source and rule evidence below, then replay the frozen `OR_FAILURE_REV` version twice from the same manifest and compare ordered results and recording bytes. |
| `FIRST_PULLBACK_VWAP` | `INSUFFICIENT_DATA` | M8.4 | Supply the common source and rule evidence below, then replay the frozen `FIRST_PULLBACK_VWAP` version twice from the same manifest and compare ordered results and recording bytes. |

The software can replay supplied records in a repeatable way. Its existing
examples are synthetic. They are not historical market observations and cannot
be used to calculate or claim profit.

## Missing evidence and owners

The historical study needs a dated source manifest for the requested symbols and
sessions. M0.2, M2.2, M2.3 and M2.4 own the shared source proof. M6.4, M7.5,
M8.2 and M8.4 own the playbook-specific historical coverage. The manifest must
show:

- point-in-time minute bars, quotes, benchmark and reference inputs, and each
  required participation input;
- original source and availability times, finality, revisions, corrections, and
  compatible price and volume adjustments;
- the prior-session history required by each playbook; and
- corporate-action and historical-universe handling for the selected sample.

M0.3 owns approved frozen definitions for each playbook. The definitions must
settle the required thresholds, timing, participation, risk and confidence rules
before results are viewed. M5.2 owns the approved execution and outcome policy.
That policy must settle entry and delay rules, fills, fees, slippage, stops,
targets, ambiguous bars, halts, borrow, censoring and the study horizon before a
return is calculated.

## Reopening test

Reopen historical validation only after every owner above supplies its missing
evidence. Before calculation, freeze the dataset ID, date range, symbols,
strategy versions, configuration hashes, feature version, code revision and
execution model. Replay events in their original availability order through the
isolated recording path. Confirm that no future or revised fact affects an
earlier decision, and keep full and proxy data modes separate.

Run the same frozen manifest again in a fresh process. The ordered state changes,
candidates, suppressions and required recording bytes must match. A passing
software check leaves the evidence stage at `INSUFFICIENT_DATA` until the missing
historical source, approved definitions and approved execution policy all exist.

Source record: [M9_1_VERIFICATION.md](../trade_alerts_build_docs/M9_1_VERIFICATION.md).

## Offline verification record

The protected focused phase selected `tests/trade_alerts_contracts` because the
builder named the directly affected checks. It passed 2,922 tests in one run;
the controller wall time was 522.087 seconds. Its artifacts are in
`/root/trade-alerts-builder/runs/20260913-025651-839166-build/published-artifacts-14caf6a8f279`.

The protected broad acceptance phase selected `tests/trade_alerts_contracts`
because the dependency impact was unknown and the controller used its safe broad
fallback. It passed 2,922 tests in one run; the controller wall time was 521.483
seconds. Its artifacts are in
`/root/trade-alerts-builder/runs/20260913-025651-839166-build/published-artifacts-9a31bdf9eae9`.

The separate protected repeatability phase selected the 35 recording checks
listed in its published `summary.json` because recording output requires a
fresh-process comparison. It passed 59 tests in each of two runs; the controller
wall time was 294.463 seconds. The required recordings and ordered results
matched between runs. Its artifacts and file hashes are in
`/root/trade-alerts-builder/runs/20260913-025651-839166-build/published-artifacts-d59086e8d45b`.

The complete tested-source manifest is
`/root/trade-alerts-builder/runs/20260913-025651-839166-build/verified-manifest.json`.
The tested source hash is
`64fa5fb9bde362b9db5a26f35ceee47fa65fed8a664041176d89b292bb8898c0`.
All three phases exited successfully. This software proof does not change the
four `INSUFFICIENT_DATA` results or close the separate M9.1 historical replay
gate.
