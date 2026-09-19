# M8.5 cross-strategy interaction tests

Date: 2026-09-13 Pacific. Status: **offline implementation and protected proof complete; independent acceptance pending.** All switches remain off.

The repaired report now requires every supporting handoff or reversal record to match the candidate stock, saved session, original setup, boundary and time order. It refuses missing or unrelated identity. A reversal declaration also requires the real `FAILURE_HANDOFF` check to pass. The report keeps the complete supporting records. Tests cover both directions, both assessment types, unrelated stocks, sessions and setups, refused states and invalid time order.

The original failure was that the report checked only the two candidate stocks. Unrelated supporting evidence could therefore declare a transition. The different approach links every frozen, gate and structural record to supplied canonical records and a saved session, then records those links for review. This also preserves the earlier repair for the zero-risk test example.

## Published protected proof

Source hash: `8df9ca40b864200e786255d5d435189e176a0d4818520f8d2608c4531cf63d56`.
Complete tested-source manifest: `/root/trade-alerts-builder/runs/20260912-094421-180831-build/verified-manifest.json`.
The full manifest contents, publication hashes, isolation records, cleanup results and artifact comparisons are published in `M8_5_LOCAL_CHECKS.json`.

### focused

Selector: `tests/trade_alerts_contracts`. Selection reason: `builder named directly affected checks`.
Runs: 1. Test count: 2922. Controller wall seconds: 517.863.
Artifact directory: `/root/trade-alerts-builder/runs/20260912-094421-180831-build/published-artifacts-969dc5bc86c8`.
pytest line: `2922 passed in 514.06s (0:08:34)`. JUnit time: `513.943` seconds.

### acceptance

Selector: `tests/trade_alerts_contracts`. Selection reason: `unknown dependency impact; safe broad fallback`.
Runs: 1. Test count: 2922. Controller wall seconds: 517.954.
Artifact directory: `/root/trade-alerts-builder/runs/20260912-094421-180831-build/published-artifacts-5434875fd10d`.
pytest line: `2922 passed in 514.22s (0:08:34)`. JUnit time: `514.103` seconds.

### repeatability

Runs: 2. Test count: 59. Controller wall seconds: 301.441. Selection reason: `recording output requires fresh-process comparison`.
Artifact directory: `/root/trade-alerts-builder/runs/20260912-094421-180831-build/published-artifacts-c467d2ce537d`.
The exact 35 selectors are recorded in `M8_5_LOCAL_CHECKS.json` in controller order.

Run 1 pytest line: `59 passed in 149.53s (0:02:29)`. Run 1 JUnit time: `149.527` seconds.
Run 2 pytest line: `59 passed in 148.11s (0:02:28)`. Run 2 JUnit time: `148.111` seconds.

Every run has zero failures, errors and skips, no unexpected isolation denials, and all cleanup checks are true. Repeatability test IDs match in order. Every required recording matches byte for byte across acceptance run 1 and both repeatability runs. The four M8.5 hashes are:

- `m8_5_cross_strategy_interaction_proof.json`: `743228377cf79f33c9f231051b5f5cdc53321ce733ee900fce0d45b9a1565b4a`
- `m8_5_cross_strategy_interaction_handoff_short_proof.json`: `0565a672b4c93fa9d32aa0e2517dc4d4e59fa52aa47538431db7ee29d2e40133`
- `m8_5_cross_strategy_interaction_reversal_long_proof.json`: `7a3ad97e9619ea6347f6ca9bc153636c145abc714197d49c77c326d4d2d8b264`
- `m8_5_cross_strategy_interaction_reversal_short_proof.json`: `d3dd0b24ffc0da9636d346b8dfa4ae5484601c40a7f518b539258ae1971fc2c4`

## Limits and next milestone

The definition gate stays open for primary ownership, equal-score ties, merging, opposite-direction suppression and reversal ownership. The source and historical-data gate also stays open because the candidates, ATR and handoff evidence are synthetic supplied records. This proof does not establish profit or edge.

The next open milestone is **M9.1 — Historical replay #1–#4**, after independent acceptance of M8.5. It must record `INSUFFICIENT_DATA` or `BLOCKED` when required history is unavailable.
