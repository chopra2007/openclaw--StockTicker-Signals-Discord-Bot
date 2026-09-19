# M0.3E deterministic research definition proof

Date: 2026-09-13 Pacific. Status: **offline definition work and protected proof
complete; independent acceptance pending.** All switches remain off.

Version `M03E_FIRST_PULLBACK_VWAP_V1` freezes the impulse, swing confirmation,
pullback counting, volume normalization, VWAP slope and crosses, retracement
boundaries, reversal bar, priority arms, mirrored stop and targets, score and
outcome rules for `FIRST_PULLBACK_VWAP`. The packet is incorporated into the
four governing records. This work records rules for later research. It does not
report a replay result, edge or profit and does not approve live use.

## Published protected proof

Source hash: `a58c3e84add41c2c34693b4c8d0dbb723a521bcd20ea91c1a0cf26848f0cdc42`.
Complete tested-source manifest: `trade_alerts_build_docs/M0_3E_TESTED_SOURCE_MANIFEST.json`.
The complete controller records, publication hashes, isolation records and
cleanup results are in `M0_3E_CONTROLLER_EVIDENCE.json`.

### focused

Selector: `tests/trade_alerts_contracts`. Selection reason: `builder named directly affected checks`.
Runs: 1. Test count: 2922. Controller wall seconds: 528.502.
Artifact directory: `/root/trade-alerts-builder/runs/20260913-134119-903468-build/published-artifacts-3e616d90e139`.
pytest line: `2922 passed in 524.51s (0:08:44)`. JUnit time: `524.406` seconds.

### acceptance

Selector: `tests/trade_alerts_contracts`. Selection reason: `unknown dependency impact; safe broad fallback`.
Runs: 1. Test count: 2922. Controller wall seconds: 530.675.
Artifact directory: `/root/trade-alerts-builder/runs/20260913-134119-903468-build/published-artifacts-bed6ae133541`.
pytest line: `2922 passed in 526.93s (0:08:46)`. JUnit time: `526.814` seconds.

### repeatability

Runs: 2. Test count: 59. Controller wall seconds: 305.484. Selection reason: `recording output requires fresh-process comparison`.
Artifact directory: `/root/trade-alerts-builder/runs/20260913-134119-903468-build/published-artifacts-5526792f8125`.
The exact 35 selectors are recorded in `M0_3E_LOCAL_CHECKS.json` in controller order.

Run 1 pytest line: `59 passed in 151.31s (0:02:31)`. Run 1 JUnit time: `151.311` seconds.
Run 2 pytest line: `59 passed in 150.35s (0:02:30)`. Run 2 JUnit time: `150.354` seconds.

Every run has zero failures, errors and skips, no unexpected isolation denials,
and clean cleanup. Repeatability test IDs match in order. All 47 recording files
match byte for byte between the acceptance run and both repeatability runs.

## Limits and next milestone

Historical replay still requires the missing M0.2 source manifest. Missing
minute bars, sub-minute trades and quotes, point-in-time news, borrow evidence
and option quotes block only their dependent evidence. No external connection,
spending, alert, order, activation or profit claim occurred.

The next open milestone is **M0.3F — INDEX_OPEN_DRIVE_BREADTH deterministic
research definitions**, after independent acceptance of M0.3E.

## Records-only finalization

The 2026-09-13 14:10:43 Pacific verification handoff confirms the original
tested source hash above. The original complete tested-source manifest is
preserved in `M0_3E_TESTED_SOURCE_MANIFEST.json`. This finalization added only
proof records and ROADMAP text. A later records-only review correction marked
the M8.3 and M8.4 definition gates resolved by M0.3E, updated their summaries,
and corrected the current unresolved PLAYBOOKS section 13 count to four. Code,
tests, configuration, dependencies and protected inputs did not change, so the
published focused, acceptance and repeatability proof remains valid. The M8.3
and M8.4 source and historical-data gates stay open.
