# M0.3G deterministic research definition proof

Date: 2026-09-13 Pacific. Status: **definition and protected proof complete for
independent review.** All switches remain off.

Version `M03G_GAP_FADE_FAILED_OPEN_V1` freezes the opening-extension window,
loss of open, failed reclaim, from-open SPY comparison, catalyst treatment,
mirrored gap-down behavior, trigger, staleness, stop, targets, score and outcome
rules for `GAP_FADE_FAILED_OPEN`. The packet is incorporated into PLAYBOOKS,
DATA_REQUIREMENTS, TESTING_AND_VALIDATION, DECISIONS_AND_OPEN_QUESTIONS and
ROADMAP. It reports no replay result, edge or profit and does not approve live
use.

## Published protected proof

The controller verified source hash
`8f9edeed2ea2375132462e76b639f9b2d7b87f8d13cc98188405c1c2d5f36f95`.
The complete tested-source manifest is
`/root/trade-alerts-builder/runs/20260913-154608-556078-build/verified-manifest.json`
with SHA-256
`d5b0394d4667412ee40f9910efef5b0a28d63c3c36e0987682106bb83659dddc`.

### focused

Selector: `tests/trade_alerts_contracts`. Selection reason: `builder named directly affected checks`.
Runs: 1. Test count: 2922. Controller wall seconds: 519.725.
Artifact directory: `/root/trade-alerts-builder/runs/20260913-154608-556078-build/published-artifacts-8a5a557c67c0`.
pytest line: `2922 passed in 515.94s (0:08:35)`. JUnit time: `515.822` seconds.
Publication record SHA-256: `9072eb6c0bdc8a98cb8abd77b2bd90e1b45bf4606589a779f3dfa8e7392f64e3`.

### acceptance

Selector: `tests/trade_alerts_contracts`. Selection reason: `unknown dependency impact; safe broad fallback`.
Runs: 1. Test count: 2922. Controller wall seconds: 510.387.
Artifact directory: `/root/trade-alerts-builder/runs/20260913-154608-556078-build/published-artifacts-0d7462c275f2`.
pytest line: `2922 passed in 506.78s (0:08:26)`. JUnit time: `506.669` seconds.
Publication record SHA-256: `d210924d46fc104bd5f5f41cf40ecf6e12fdaf2e27cc129a3dfeef25e03c5c25`.

### repeatability

Runs: 2. Test count: 59. Controller wall seconds: 300.066. Selection reason: `recording output requires fresh-process comparison`.
Artifact directory: `/root/trade-alerts-builder/runs/20260913-154608-556078-build/published-artifacts-083a450f901b`.
The exact 35 selectors are recorded in that directory's `summary.json` in
controller order.

Run 1 pytest line: `59 passed in 146.73s (0:02:26)`. Run 1 JUnit time: `146.733` seconds.
Run 2 pytest line: `59 passed in 149.64s (0:02:29)`. Run 2 JUnit time: `149.640` seconds.
Publication record SHA-256: `b743ab5637af1e02110b54bc9882ae6cff9be392afad867a898b0af1acbe8217`.

Every run has zero failures, errors and skips, no unexpected isolation denials,
and clean cleanup. Repeatability test IDs match in order. All 48 JSON recording
files match byte for byte between the acceptance run and both repeatability
runs.

## Records-only finalization

The 2026-09-13 16:17:26 Pacific verification handoff confirms the tested source
hash and complete tested-source manifest above. This finalization changes only
permitted research records. Code, tests, configuration, dependencies and
protected inputs did not change, so the published proof remains valid.

## Limits and next milestone

Faithful replay still requires a qualifying immutable source manifest and exact
chronological development, calibration and untouched final-validation dates.
Bars, trades, quotes, SPY, VWAP, catalyst history, halts, borrow and option facts
retain their separate source gates. No external connection, spending, alert,
order, activation or profit claim occurred.

The next open milestone is **M0.3H — CAT_FIRST_CONSOL deterministic research
definitions**, after independent acceptance of M0.3G.
