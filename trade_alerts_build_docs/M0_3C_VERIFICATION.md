# M0.3C deterministic research definition proof

Date: 2026-09-13 Pacific. Status: **offline definition work and protected proof complete; independent acceptance pending.** All switches remain off.

Version `M03C_HOD_COMP_RS_V1` freezes the HOD/LOD ownership, relative-strength warm-up, compression seed, acceptance, tape fallback, stop, target, score and outcome rules for `HOD_COMP_RS`. The full milestone change is listed in `M0_3C_LOCAL_CHECKS.json`. This work records rules for later research. It does not report a replay result, edge or profit and does not approve live use.

## Published protected proof

Source hash: `0bac8754f5e0b8b46fe5806a62da1a80c3ea957d7e82e58712312ae88ed3bdf3`.
Complete tested-source manifest: `trade_alerts_build_docs/M0_3C_TESTED_SOURCE_MANIFEST.json`.
The complete controller records, publication hashes, isolation records and cleanup results are in `M0_3C_CONTROLLER_EVIDENCE.json`. The compact milestone record is in `M0_3C_LOCAL_CHECKS.json`.

### focused

Selector: `tests/trade_alerts_contracts`. Selection reason: `builder named directly affected checks`.
Runs: 1. Test count: 2922. Controller wall seconds: 519.198.
Artifact directory: `/root/trade-alerts-builder/runs/20260913-115650-632146-build/published-artifacts-ede8292a2704`.
pytest line: `2922 passed in 515.14s (0:08:35)`. JUnit time: `515.019` seconds.

### acceptance

Selector: `tests/trade_alerts_contracts`. Selection reason: `unknown dependency impact; safe broad fallback`.
Runs: 1. Test count: 2922. Controller wall seconds: 508.704.
Artifact directory: `/root/trade-alerts-builder/runs/20260913-115650-632146-build/published-artifacts-24e71d331877`.
pytest line: `2922 passed in 504.94s (0:08:24)`. JUnit time: `504.815` seconds.

### repeatability

Runs: 2. Test count: 59. Controller wall seconds: 295.554. Selection reason: `recording output requires fresh-process comparison`.
Artifact directory: `/root/trade-alerts-builder/runs/20260913-115650-632146-build/published-artifacts-58372fa53b67`.
The exact 35 selectors are recorded in `M0_3C_LOCAL_CHECKS.json` in controller order.

Run 1 pytest line: `59 passed in 145.88s (0:02:25)`. Run 1 JUnit time: `145.880` seconds.
Run 2 pytest line: `59 passed in 145.96s (0:02:25)`. Run 2 JUnit time: `145.958` seconds.

Every run has zero failures, errors and skips, no unexpected isolation denials, and clean cleanup. Repeatability test IDs match in order. All 47 recording files match byte for byte between the acceptance run and both repeatability runs.

## Limits and next milestone

The protected proof establishes the offline document contract only. Historical replay still requires the missing M0.2 source manifest and the M0.3B source gate remains open. No external connection, spending, alert, order, activation or profit claim occurred.

The next open milestone is **M0.3D — OR_FAILURE_REV deterministic research definitions**, after independent acceptance of M0.3C.
## Records-only finalization

The 2026-09-13 12:50:39 Pacific verification handoff confirms the original tested source hash `0bac8754f5e0b8b46fe5806a62da1a80c3ea957d7e82e58712312ae88ed3bdf3`. The complete path-by-path comparison is in `M0_3C_CONTROLLER_EVIDENCE.json` and `M0_3C_LOCAL_CHECKS.json`. Only permitted research records changed after testing. Code, tests, configuration, dependencies and protected inputs did not change, so the published focused, acceptance and repeatability proof remains valid. The final record edit corrects the current count to six unresolved PLAYBOOKS §13 rows and leaves every source and historical-data gate open.
