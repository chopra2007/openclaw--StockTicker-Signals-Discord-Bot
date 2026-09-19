# M0.2E provider-limit and source-contract reconciliation proof

Date: 2026-09-14 Pacific. Status: **PROTECTED VERIFICATION COMPLETE; INDEPENDENT ACCEPTANCE PENDING.** All switches remain off.

The reconciliation is documented in `M0_2E_SOURCE_RECONCILIATION.md`, DATA_REQUIREMENTS section 60 and CODING_STANDARDS section 75. It makes no provider request, credential read, purchase, runtime change, source-qualification claim or live action.

## Complete milestone delta

- `trade_alerts_build_docs/CODING_STANDARDS.md`
- `trade_alerts_build_docs/DATA_REQUIREMENTS.md`
- `trade_alerts_build_docs/M0_2E_CONTROLLER_EVIDENCE.json`
- `trade_alerts_build_docs/M0_2E_SOURCE_RECONCILIATION.md`
- `trade_alerts_build_docs/M0_2E_TESTED_SOURCE_MANIFEST.json`
- `trade_alerts_build_docs/M0_2E_VERIFICATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

## Published protected proof

Verified source hash: `847836ef6c213ab445d46bd0b8faea0c344b53923c67bea45af75307bf2f69e1`.

Complete tested-source manifest: `/root/trade-alerts-builder/runs/20260914-024639-929081-build/verified-manifest.json` (SHA-256 `5436a9b2baa0383f64285235a1b51077c9a91429525092286f746e89acb0dcda`). A project copy is `M0_2E_TESTED_SOURCE_MANIFEST.json`.

Controller evidence: `/root/trade-alerts-builder/runs/20260914-024639-929081-build/controller-evidence.json` (SHA-256 `d55166b7795b3b3c155f9a5b51c0700622b54f53d1694c957674e4705c914466`). A project copy is `M0_2E_CONTROLLER_EVIDENCE.json`.

### focused

Selectors: `tests/trade_alerts_contracts/test_historical_bars.py`, `tests/trade_alerts_contracts/test_reference_inputs.py`, `tests/trade_alerts_contracts/test_request_queue.py`, `tests/trade_alerts_contracts/test_schwab_normalization.py`. Selection reason: `builder named directly affected checks`.

Runs: 1. Test count: 179. Controller wall seconds: 37.667.

Artifact directory: `/root/trade-alerts-builder/runs/20260914-024639-929081-build/published-artifacts-95ee29239167`.

pytest line: `179 passed in 36.11s`. JUnit time: `36.104` seconds. Publication record SHA-256: `5947941156c20c721906840b453a16130901a76d2660463bf5d7d5e510724f6c`.

### acceptance

Selector: `tests/trade_alerts_contracts`. Selection reason: `unknown dependency impact; safe broad fallback`.

Runs: 1. Test count: 3037. Controller wall seconds: 547.087.

Artifact directory: `/root/trade-alerts-builder/runs/20260914-024639-929081-build/published-artifacts-9cbd8e418a16`.

pytest line: `3037 passed in 543.06s (0:09:03)`. JUnit time: `542.934` seconds. Publication record SHA-256: `133d981cabc5028ddeee88a6d4f14f87fca2de97cc693fc46d758e44de684b44`.

### repeatability

The controller used the 39 exact selectors in the repeatability publication because `recording output requires fresh-process comparison`. They are recorded in controller order in the `commands` array of `/root/trade-alerts-builder/runs/20260914-024639-929081-build/published-artifacts-51185b1fb154/summary.json`. `M0_2E_CONTROLLER_EVIDENCE.json` records the broad acceptance selector only.

Runs: 2. Test count: 63. Controller wall seconds: 315.667.

Artifact directory: `/root/trade-alerts-builder/runs/20260914-024639-929081-build/published-artifacts-51185b1fb154`.

Run 1 pytest line: `63 passed in 157.70s (0:02:37)`. Run 1 JUnit time: `157.698` seconds.

Run 2 pytest line: `63 passed in 153.92s (0:02:33)`. Run 2 JUnit time: `153.929` seconds.

Publication record SHA-256: `eeda083f37305e9e1bb44a2a26875bc9782819dc6746e0c46a31082a8f259a8d`.

Every phase has zero failures, errors and skips, no unexpected isolation denials and clean cleanup. The controller marked repeatability stable. Both fresh processes contain matching names and hashes for the compared recording files.

## Limits and next milestone

This proof checks the offline records and existing contracts. It does not establish Schwab account limits, subscriptions, entitlement, time units, NBBO fidelity or combined load. It does not establish Databento original availability, finality, revisions, complete corrections, full coverage, point-in-time membership or historical execution. M0.2C capacity, source, history, early-validation and live gates remain open.

The next open milestone is **M0.2F — retained Databento minute-source manifest and offline adapter**, subject to independent review of dependency order.
