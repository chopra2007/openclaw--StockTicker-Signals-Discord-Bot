# M0.3D deterministic research definition proof

Date: 2026-09-13 Pacific. Status: **offline definition work and protected proof
complete; independent acceptance pending.** All switches remain off.

Version `M03D_OR_FAILURE_REV_V1` freezes the meaningful excursion, failure
timer, inside acceptance, close and failure-bar confirmations, ORB reversal
ownership, mirrored stop and target, score and outcome rules for
`OR_FAILURE_REV`. The packet is incorporated into the four governing records.
The full milestone change is listed in `M0_3D_LOCAL_CHECKS.json`.
This work records rules for later research. It does not report a replay result,
edge or profit and does not approve live use.

## Published protected proof

Source hash: `e460d073f15646750117d8e6f150321c57c8bebb17fef079814459141070cc85`.
Complete tested-source manifest: `trade_alerts_build_docs/M0_3D_TESTED_SOURCE_MANIFEST.json`.
The complete controller records, publication hashes, isolation records and
cleanup results are in `M0_3D_CONTROLLER_EVIDENCE.json`. The compact milestone
record is in `M0_3D_LOCAL_CHECKS.json`.

### focused

Selector: `tests/trade_alerts_contracts`. Selection reason: `builder named directly affected checks`.
Runs: 1. Test count: 2922. Controller wall seconds: 529.09.
Artifact directory: `/root/trade-alerts-builder/runs/20260913-130239-204286-build/published-artifacts-a867536dc09e`.
pytest line: `2922 passed in 525.32s (0:08:45)`. JUnit time: `525.203` seconds.

### acceptance

Selector: `tests/trade_alerts_contracts`. Selection reason: `unknown dependency impact; safe broad fallback`.
Runs: 1. Test count: 2922. Controller wall seconds: 516.091.
Artifact directory: `/root/trade-alerts-builder/runs/20260913-130239-204286-build/published-artifacts-a321c0032b0c`.
pytest line: `2922 passed in 512.36s (0:08:32)`. JUnit time: `512.250` seconds.

### repeatability

Runs: 2. Test count: 59. Controller wall seconds: 306.228. Selection reason: `recording output requires fresh-process comparison`.
Artifact directory: `/root/trade-alerts-builder/runs/20260913-130239-204286-build/published-artifacts-67573f3af5e1`.
The exact 35 selectors are recorded in `M0_3D_LOCAL_CHECKS.json` in controller order.

Run 1 pytest line: `59 passed in 151.82s (0:02:31)`. Run 1 JUnit time: `151.818` seconds.
Run 2 pytest line: `59 passed in 150.32s (0:02:30)`. Run 2 JUnit time: `150.320` seconds.

Every run has zero failures, errors and skips, no unexpected isolation denials,
and clean cleanup. Repeatability test IDs match in order. All 47 recording files
match byte for byte between the acceptance run and both repeatability runs.

## Limits and next milestone

Historical replay still requires the missing M0.2 source manifest. Missing
sub-minute trades, quotes, point-in-time catalyst facts, borrow evidence and
option quotes block only their dependent evidence. No external connection,
spending, alert, order, activation or profit claim occurred.

The next open milestone is **M0.3E — FIRST_PULLBACK_VWAP deterministic research
definitions**, after independent acceptance of M0.3D.

## Records-only finalization

The 2026-09-13 13:35:00 Pacific verification handoff confirms the original
tested source hash `e460d073f15646750117d8e6f150321c57c8bebb17fef079814459141070cc85`.
The original complete tested-source manifest is preserved in
`M0_3D_TESTED_SOURCE_MANIFEST.json`. This finalization added only the proof
records and the ROADMAP proof note. Code, tests, configuration, dependencies and
protected inputs did not change, so the published focused, acceptance and
repeatability proof remains valid. Source and historical-data gates stay open.
