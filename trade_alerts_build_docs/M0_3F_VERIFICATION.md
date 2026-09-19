# M0.3F deterministic research definition proof

Date: 2026-09-13 Pacific. Status: **V2 definition and protected proof complete
for independent review.** All switches remain off.

Version `M03F_INDEX_OPEN_DRIVE_BREADTH_V2` freezes the full, sector-proxy and
hybrid breadth modes, component formulas and coverage, mirrored short rules,
drive efficiency, retracement, acceptance, warning, reduced-priority,
suppression, stop, target, score and outcome rules for
`INDEX_OPEN_DRIVE_BREADTH`. The packet is incorporated into the four governing
records. It does not report a replay result, edge or profit and does not approve
live use.

## Review diagnosis and repair

The review found definition gaps, not failing application tests. V1 delegated
the VWAP choice to M0.3A, which defines two modes, and used "prior eligible
price" without a volume interval or observation sequence. V2 names exactly
`SESSION_VWAP_BAR_HLC3_V1` for every VWAP use and freezes
`SESSION_DIRECTIONAL_TRADE_VOLUME_V1`: session-open through evaluation, ordered
eligible trades, each trade's own shares against its immediate predecessor,
neutral opening/tied prices, as-of corrections and strict coverage. Packet §10
adds worked cases for these distinctions. The comparison family and separate
source gates stay intact.

## V2 published protected proof

The controller verified source hash
`cd53ff6cbe814c28cc3dc32cd8b8b8c52abc1afd23f38416fc80a89c0234292d`.
The complete tested-source manifest is
`trade_alerts_build_docs/M0_3F_TESTED_SOURCE_MANIFEST.json`, and the controller
summary is `M0_3F_CONTROLLER_EVIDENCE.json`.

### focused

Selector: `tests/trade_alerts_contracts`. Selection reason: `builder named directly affected checks`.
Runs: 1. Test count: 2922. Controller wall seconds: 502.358.
Artifact directory: `/root/trade-alerts-builder/runs/20260913-142357-771316-build/published-artifacts-f698672b0778`.
pytest line: `2922 passed in 498.71s (0:08:18)`. JUnit time: `498.603` seconds.

### acceptance

Selector: `tests/trade_alerts_contracts`. Selection reason: `unknown dependency impact; safe broad fallback`.
Runs: 1. Test count: 2922. Controller wall seconds: 511.713.
Artifact directory: `/root/trade-alerts-builder/runs/20260913-142357-771316-build/published-artifacts-5c5759dac7f4`.
pytest line: `2922 passed in 507.99s (0:08:27)`. JUnit time: `507.884` seconds.

### repeatability

Runs: 2. Test count: 59. Controller wall seconds: 299.572. Selection reason: `recording output requires fresh-process comparison`.
Artifact directory: `/root/trade-alerts-builder/runs/20260913-142357-771316-build/published-artifacts-ec481d9167f8`.
The exact 35 selectors are recorded in `M0_3F_LOCAL_CHECKS.json` in controller
order.

Run 1 pytest line: `59 passed in 147.76s (0:02:27)`. Run 1 JUnit time: `147.757` seconds.
Run 2 pytest line: `59 passed in 148.00s (0:02:27)`. Run 2 JUnit time: `148.000` seconds.

Every run has zero failures, errors and skips, no unexpected isolation denials,
and clean cleanup. Repeatability test IDs match in order. All 48 JSON recording
files match byte for byte between the acceptance run and both repeatability
runs.

## Limits and next milestone

Full and hybrid breadth remain blocked until M0.2 supplies verified point-in-time
constituent membership, weights, minute history and coverage. Sector proxy still
requires all 11 named ETFs. Replay also requires an immutable source manifest
and exact chronological development, calibration and untouched final-validation
dates. No external connection, spending, alert, order, activation or profit
claim occurred.

The next open milestone is **M0.3G — GAP_FADE_FAILED_OPEN deterministic research
definitions**, after independent acceptance of M0.3F.

## Records-only finalization

The 2026-09-13 15:27:00 Pacific verification handoff confirms the V2 tested
source hash and complete tested-source manifest above. This finalization changes
only permitted research records. Code, tests, configuration, dependencies and
protected inputs did not change, so the published V2 proof remains valid.

The controller's 2026-09-13 15:37:51 Pacific comparison covered the first nine
record corrections and confirmed that protected inputs were unchanged. The
current records-only controller stage will publish a new complete comparison
that also covers the later status wording and separately preserved V1 records.

## Historical V1 published protected proof

All figures and artifacts in this section describe the earlier V1 source only.

Source hash: `87c18c4c7c1f70b396ec9482ad661f53caf483dc0ed1c050638f423cd6bda9a9`.
Complete tested-source manifest: `trade_alerts_build_docs/M0_3F_V1_HISTORICAL_TESTED_SOURCE_MANIFEST.json`.
The controller's original summary is preserved in
`M0_3F_V1_HISTORICAL_CONTROLLER_EVIDENCE.json`. Each phase's publication, run summaries,
isolation and cleanup records remain in its artifact directory below.

### focused

Selector: `tests/trade_alerts_contracts`. Selection reason: `builder named directly affected checks`.
Runs: 1. Test count: 2922. Controller wall seconds: 513.199.
Artifact directory: `/root/trade-alerts-builder/runs/20260913-142357-771316-build/published-artifacts-3edf48818ae0`.
pytest line: `2922 passed in 509.40s (0:08:29)`. JUnit time: `509.290` seconds.

### acceptance

Selector: `tests/trade_alerts_contracts`. Selection reason: `unknown dependency impact; safe broad fallback`.
Runs: 1. Test count: 2922. Controller wall seconds: 517.53.
Artifact directory: `/root/trade-alerts-builder/runs/20260913-142357-771316-build/published-artifacts-9ad2d0ae4e3b`.
pytest line: `2922 passed in 513.81s (0:08:33)`. JUnit time: `513.701` seconds.

### repeatability

Runs: 2. Test count: 59. Controller wall seconds: 297.072. Selection reason: `recording output requires fresh-process comparison`.
Artifact directory: `/root/trade-alerts-builder/runs/20260913-142357-771316-build/published-artifacts-c11d470c01dc`.
The exact 35 selectors are recorded in `M0_3F_V1_HISTORICAL_LOCAL_CHECKS.json` under
`tests.repeatability.selectors` in controller order.

Run 1 pytest line: `59 passed in 146.57s (0:02:26)`. Run 1 JUnit time: `146.569` seconds.
Run 2 pytest line: `59 passed in 146.75s (0:02:26)`. Run 2 JUnit time: `146.751` seconds.

Every run has zero failures, errors and skips, no unexpected isolation denials,
and clean cleanup. Repeatability test IDs match in order. All 47 recording files
match byte for byte between the acceptance run and both repeatability runs.

## Limits and next milestone

Full and hybrid breadth remain blocked until M0.2 supplies verified point-in-time
constituent membership, weights, minute history and coverage. Sector proxy still
requires all 11 named ETFs. Replay also requires an immutable source manifest
and exact chronological development, calibration and untouched final-validation
dates. No external connection, spending, alert, order, activation or profit
claim occurred.

The next open milestone is **M0.3G — GAP_FADE_FAILED_OPEN deterministic research
definitions**, after independent acceptance of M0.3F.

## Historical V1 records-only finalization

The 2026-09-13 14:54:10 Pacific verification handoff confirms the original
tested source hash above. The original complete tested-source manifest is
preserved in `M0_3F_V1_HISTORICAL_TESTED_SOURCE_MANIFEST.json`. This finalization added only
proof records and ROADMAP text. Code, tests, configuration, dependencies and
protected inputs did not change during that finalization, so its published
focused, acceptance and repeatability proof was retained for V1. The later V2
definition repair above requires fresh controller proof. The original source
hash and complete tested manifest remain unchanged as historical evidence.
Separate source and historical-data gates stay open.
