# M3.3 supplied-input relative-strength implementation

Date: 2026-09-14 Pacific. Status: **OWNER-REOPENED REPAIR: PROTECTED VERIFICATION COMPLETE; INDEPENDENT ACCEPTANCE PENDING.** All switches remain off.

`consensus_engine/relative_strength_features.py` calculates stock strength against SPY, QQQ and a supplied sector ETF. It freezes the first 15 complete one-minute bars for `RS15_SPY_CLOSE_V1`, keeps each reference's missing reason separate, and handles the collected stale, future, provisional, revised, no-trade and incompatible supplied cases. The earlier revised-bar defect and rejected proof remain recorded below. It performs no fetch, clock read, storage, alert or order.

The original controller failure was `schema_version must be 1`. Positional Bar fixture fields assigned source metadata to the inherited version field. The producer had the same positional shift in its FeatureSnapshot output. Both records now use named fields, which preserves version 1 and makes every field assignment clear.

## Published protected proof

Source hash: `e4bc875e337302cf2917ec718111289c08724f60effc063d348db802058e76e7`.
Complete tested-source manifest: `/root/trade-alerts-builder/runs/20260913-180916-739029-build/verified-manifest.json`.
The full manifest, publication hashes, isolation records and cleanup results are published in `M3_3_LOCAL_CHECKS.json`.

### focused

The controller named this phase `focused`. It selected the eight exact repaired cases recorded in `M3_3_LOCAL_CHECKS.json` because the builder named directly affected checks. Runs: 1. Test count: 8. Controller wall seconds: 11.679. Artifact directory: `/root/trade-alerts-builder/runs/20260913-180916-739029-build/published-artifacts-9945c02b41e7`. pytest line: `8 passed in 9.80s`. JUnit time: `9.809` seconds.

### acceptance

Selector: `tests/trade_alerts_contracts`. Selection reason: `unknown dependency impact; safe broad fallback`. Runs: 1. Test count: 2937. Controller wall seconds: 531.681. Artifact directory: `/root/trade-alerts-builder/runs/20260913-180916-739029-build/published-artifacts-31a19a343ce8`. pytest line: `2937 passed in 527.06s (0:08:47)`. JUnit time: `526.945` seconds.

### repeatability

The controller named this phase `repeatability`. Selection reason: `recording output requires fresh-process comparison`. Runs: 2. Test count: 60. Controller wall seconds: 308.469. Artifact directory: `/root/trade-alerts-builder/runs/20260913-180916-739029-build/published-artifacts-076c5ed1a513`. The exact 36 selectors are recorded in `M3_3_LOCAL_CHECKS.json` in controller order.

Run 1 pytest line: `60 passed in 153.34s (0:02:33)`. Run 1 JUnit time: `153.344` seconds. Run 2 pytest line: `60 passed in 150.88s (0:02:30)`. Run 2 JUnit time: `150.884` seconds.

Every run has zero failures, errors and skips. There were no unexpected isolation denials, and every cleanup check is true. Repeatability test IDs match in order. `m33-relative-strength-proof.json` matches byte for byte between acceptance run 1 and both repeatability runs. Its SHA-256 is `91728e81d80454e10eb62191ad9cd4082f1472968b7847e37b4eb44f06d1cd8e`.

## Limits and next milestone

Actual point-in-time stock, SPY, QQQ and sector mapping, minute-bar and eligible-trade coverage, original availability, corrections and compatible adjustments remain a separate source and historical-data gate. Synthetic supplied records do not close it or prove profit, edge or live readiness.

At the time of this rejected proof, the next open milestone was **M3.4 — VWAP
context**. It was later completed as a separate supplied-input milestone while
its source gate remained blocked.

## Current independent review rejection — 2026-09-13 Pacific

M3.3 is not accepted. The collected targeted, full and repeated checks passed,
but direct checks for revised bars, wrong units, wrong instrument types, wrong
sessions and incompatible 15-minute adjustment bases were not added. The
engine also fails to reject selected final bars with revision above zero.
The Sol/Astra attempt limit leaves these code and testing obligations for human
review. No code or tests are changed by this blocked assessment. Original
proof, rejected reviews, source manifests and attempts remain intact.
Reopening requires the actual revision rejection, the missing cases, fresh
protected focused/broad/repeated proof and independent acceptance.
M3.4 supplied-input VWAP context uses accepted bars/core price/session timing,
not this relative-strength engine. A fresh blocked-assessment review must
confirm that independent route. Source and historical-data gates stay open.

## Owner-approved focused repair — 2026-09-14 Pacific

The reopened repair now rejects every selected first-15-minute bar whose
revision is above zero. Five direct checks cover revised bars, wrong units,
wrong instrument types, wrong sessions and incompatible 15-minute adjustment
bases. The earlier rejected proof and blocked review above remain historical.

The controller completed the repaired protected stages against source hash
`7ce413bb364e28a936ceb62683a96e1c354443c8bb139279e3c436781bb2d27d`.
The complete tested-source manifest is
`/root/trade-alerts-builder/runs/20260914-001422-309071-build/verified-manifest.json`
(SHA-256 `b3a9cfe665d9aeb8fdb633e549457923024e1bd6b29ed6cd5b11178f714a50be`).
Controller evidence is
`/root/trade-alerts-builder/runs/20260914-001422-309071-build/controller-evidence.json`
(SHA-256 `1816cab0bb8b30402b0d2b7c61421fc01217ad4208708c4a3eeccd398e7aefaf`).

### focused

Selector: `tests/trade_alerts_contracts`. Selection reason: `builder named directly affected checks`.

Runs: 1. Test count: 2999. Controller wall seconds: 543.695.

Artifact directory: `/root/trade-alerts-builder/runs/20260914-001422-309071-build/published-artifacts-81c39e33276c`.

pytest line: `2999 passed in 539.78s (0:08:59)`. JUnit time: `539.628` seconds.

### acceptance

Selector: `tests/trade_alerts_contracts`. Selection reason: `unknown dependency impact; safe broad fallback`.

Runs: 1. Test count: 2999. Controller wall seconds: 547.537.

Artifact directory: `/root/trade-alerts-builder/runs/20260914-001422-309071-build/published-artifacts-abfd43e26022`.

pytest line: `2999 passed in 543.58s (0:09:03)`. JUnit time: `543.461` seconds.

### repeatability

The controller used the 38 selectors recorded in its repeatability artifact
because `recording output requires fresh-process comparison`. Runs: 2. Test
count: 62. Controller wall seconds: 320.871.

Artifact directory: `/root/trade-alerts-builder/runs/20260914-001422-309071-build/published-artifacts-077d76b8a16b`.

Run 1 pytest line: `62 passed in 158.43s (0:02:38)`. Run 1 JUnit time: `158.427` seconds.

Run 2 pytest line: `62 passed in 158.45s (0:02:38)`. Run 2 JUnit time: `158.457` seconds.

Both fresh processes published `m33-relative-strength-proof.json` with SHA-256
`62dbbfb958c89a6ed89e8cc78b1e2a9a52ac4ebf488969c2a8682fc934f95ac1`.
The bytes match. All three phases have zero failures, errors and skips. There
were no unexpected isolation denials, all cleanup checks are true, and the
controller marked repeatability stable.

## Final result and next milestone

The owner-reopened offline repair is complete and ready for independent
acceptance. The separate source and historical-data gate remains blocked, and
all switches remain off.

The proposed next milestone is **M4.7 — minimum options and portfolio path**.
It is a shared prerequisite for the first four playbooks. Independent review
must confirm its place in the dependency order. Its source, historical,
early-validation and live gates remain separate.
