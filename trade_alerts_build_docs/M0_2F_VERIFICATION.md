# M0.2F retained Databento minute-source manifest and offline adapter proof

Date: 2026-09-14 Pacific. Status: **PROTECTED VERIFICATION COMPLETE; INDEPENDENT ACCEPTANCE PENDING.** All switches remain off.

`M0_2F_SOURCE_MANIFEST.json` records the two retained immutable 13-ETF files as separate sources. `consensus_engine/databento_minute_bars.py` converts already-decoded `ohlcv-1m` rows offline while preserving source identity, raw nanosecond message time and unknown availability, finality and correction facts. It does not read a source file, join feeds, fill gaps, contact a provider or label a row final.

## Complete milestone delta

- `consensus_engine/databento_minute_bars.py`
- `tests/trade_alerts_contracts/test_databento_minute_bars.py`
- `trade_alerts_build_docs/CODING_STANDARDS.md`
- `trade_alerts_build_docs/DATA_REQUIREMENTS.md`
- `trade_alerts_build_docs/M0_2F_CONTROLLER_EVIDENCE.json`
- `trade_alerts_build_docs/M0_2F_SOURCE_MANIFEST.json`
- `trade_alerts_build_docs/M0_2F_TESTED_SOURCE_MANIFEST.json`
- `trade_alerts_build_docs/M0_2F_VERIFICATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

## Published protected proof

Verified source hash: `603325b34100b63b1b566d45de2a2c43c60081afcb8183db9ff5602dede4416b`.

Complete tested-source manifest: `/root/trade-alerts-builder/runs/20260914-032056-806227-build/verified-manifest.json` (SHA-256 `6e38f63df209d8ec922533fd3918d84910dfa02a4f3a67d1e93f2a79edfa7ea1`). A project copy is `M0_2F_TESTED_SOURCE_MANIFEST.json`.

Controller evidence: `/root/trade-alerts-builder/runs/20260914-032056-806227-build/controller-evidence.json` (SHA-256 `c166ff4ac866fc9cb997f387eb5300d29ab8264ac87f437f2eb39964b83a2640`). A project copy is `M0_2F_CONTROLLER_EVIDENCE.json`.

### focused

Selectors: `tests/trade_alerts_contracts/test_databento_minute_bars.py`, `tests/trade_alerts_contracts/test_databento_minute_bars.py::test_recorded_source_identity_proof_is_deterministic`. Selection reason: `builder named directly affected checks`.

Runs: 1. Test count: 11. Controller wall seconds: 3.848.

Artifact directory: `/root/trade-alerts-builder/runs/20260914-032056-806227-build/published-artifacts-18149d83e7c6`.

pytest line: `11 passed in 1.98s`. JUnit time: `1.984` seconds. Publication record SHA-256: `d4683ccda24029b99fb1830ee4b618782207e805e946f549a3e92defdd052b05`.

### acceptance

Selector: `tests/trade_alerts_contracts`. Selection reason: `unknown dependency impact; safe broad fallback`.

Runs: 1. Test count: 3048. Controller wall seconds: 554.204.

Artifact directory: `/root/trade-alerts-builder/runs/20260914-032056-806227-build/published-artifacts-a30c76845df4`.

pytest line: `3048 passed in 550.30s (0:09:10)`. JUnit time: `550.175` seconds. Publication record SHA-256: `97d3c9e25a97e57be47c1ee8521ab0d40da69e0501ecf8b900b13fbd0cac3464`.

### repeatability

The controller used the 40 exact selectors in the repeatability publication because `recording output requires fresh-process comparison`. They are recorded in controller order in the `commands` array of `/root/trade-alerts-builder/runs/20260914-032056-806227-build/published-artifacts-9e0cf82e41ac/summary.json`. The list includes `tests/trade_alerts_contracts/test_databento_minute_bars.py::test_recorded_source_identity_proof_is_deterministic`.

Runs: 2. Test count: 64. Controller wall seconds: 306.907.

Artifact directory: `/root/trade-alerts-builder/runs/20260914-032056-806227-build/published-artifacts-9e0cf82e41ac`.

Run 1 pytest line: `64 passed in 150.16s (0:02:30)`. Run 1 JUnit time: `150.160` seconds.

Run 2 pytest line: `64 passed in 152.80s (0:02:32)`. Run 2 JUnit time: `152.804` seconds.

Publication record SHA-256: `fca2ea81e23fbe85ccc22c8e0d2f8e42d53912c41e145226e5d4198abb8cfcd4`.

Every phase has zero failures, errors and skips, no unexpected isolation denials and clean cleanup. The controller marked repeatability stable. Both fresh processes contain matching names and hashes for the compared recording files, including `m02f-databento-minute-source-proof.json` with SHA-256 `998824281d92111987132df1849982ba95e8cdff96d0fcb845ddd1f6bbc596fe`.

## Limits and next milestone

This proof establishes the offline inventory and conversion contract only. It does not prove complete coverage, no-trade minutes, original availability, finality, revisions, corrections, adjustments, point-in-time membership, borrow, trade or option execution, historical results, profit, promotion or live readiness. M0.2C and M4.7 remain blocked by their separate recorded issues.

The next open milestone is **M0.2G — coverage-only session manifest and split-admission report**, subject to independent review of dependency order.
