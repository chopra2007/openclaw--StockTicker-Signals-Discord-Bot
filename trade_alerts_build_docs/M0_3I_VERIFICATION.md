# M0.3I deterministic research definition proof

Date: 2026-09-13 Pacific. Status: **complete; protected proof recorded for the
crossing-rule repair.** All switches remain off.

Version `M03I_VP_ACCEPT_LVN_V1` freezes true-trade and one-minute-bar volume
allocation, bin construction, VPOC and value-area ties, LVN/HVN shelves,
adjacency, stability, acceptance, refill, risk, targets, score, matched control
and outcome rules for `VP_ACCEPT_LVN`. The packet is incorporated into
PLAYBOOKS, DATA_REQUIREMENTS, TESTING_AND_VALIDATION,
DECISIONS_AND_OPEN_QUESTIONS and ROADMAP.

It reports no replay result, edge or profit and does not approve live use.

## Published protected proof — corrected definition

The controller verified the corrected source at 2026-09-13 18:04:14 Pacific.
The verified source hash is
`95d5be7eeb73d7ec3dfbd65de85ed419db5139f82b7b8a1ad2a8f2a2211c2cbb`.
The complete tested-source manifest is
`/root/trade-alerts-builder/runs/20260913-170006-015535-build/verified-manifest.json`
with SHA-256
`f4ac33e1b483f9204fa1a34081fcdfdba949238eebad0a5ff869a303c6d649e3`.

### focused

Selector: `tests/trade_alerts_contracts`. Selection reason: `builder named directly affected checks`.
Runs: 1. Test count: 2922. Controller wall seconds: 511.197.
Artifact directory: `/root/trade-alerts-builder/runs/20260913-170006-015535-build/published-artifacts-b43b42e687c8`.
pytest line: `2922 passed in 507.55s (0:08:27)`. JUnit time: `507.434` seconds.
Publication record SHA-256: `5634a7df5bb4b1b19a7e5b04376c524eefc29d99f21dfa243cf97394f2b92cb8`.

### acceptance

Selector: `tests/trade_alerts_contracts`. Selection reason: `unknown dependency impact; safe broad fallback`.
Runs: 1. Test count: 2922. Controller wall seconds: 517.499.
Artifact directory: `/root/trade-alerts-builder/runs/20260913-170006-015535-build/published-artifacts-5a761c870393`.
pytest line: `2922 passed in 513.69s (0:08:33)`. JUnit time: `513.584` seconds.
Publication record SHA-256: `18ab3297bf1319515ab55f6a3b71d8ddb88e764fe3fb8dd96023399a76375472`.

### repeatability

Runs: 2. Test count: 59. Controller wall seconds: 295.139. Selection reason: `recording output requires fresh-process comparison`.
Artifact directory: `/root/trade-alerts-builder/runs/20260913-170006-015535-build/published-artifacts-2fdc754554f7`.
The exact 35 selectors are recorded in that directory's `summary.json` in
controller order.

Run 1 pytest line: `59 passed in 144.11s (0:02:24)`. Run 1 JUnit time: `144.111` seconds.
Run 2 pytest line: `59 passed in 147.35s (0:02:27)`. Run 2 JUnit time: `147.348` seconds.
Publication record SHA-256: `7e0e8a212eb8eea91516de32c706b1e092769bed8dc16e4d202be9c4f4d339a3`.

Every run has zero failures, errors and skips, no unexpected isolation denials,
and clean cleanup. Repeatability test IDs match in order. All 47 JSON recording
files match byte for byte between the acceptance run and both repeatability
runs.

## Review repair and final protected stage

The review found that §5 said the fourth crossing "after the first break,"
which could mean the fifth total crossing. The state rule, example 10 and the
governing strategy and evidence records instead required the fourth total
crossing. No failing test IDs were supplied; this was a definition conflict.

The repair replaces relative wording with one explicit count: the first
buffered break is crossing 1. Each later strict-side change of the frozen
unbuffered VAH/VAL adds one. Equality, same-side trades and duplicate
observations add nothing. Crossing 4 ends the untriggered candidate before
any LVN trigger at that event. The worked example now traces counts 1 through
4 for both directions. PLAYBOOKS, TESTING_AND_VALIDATION and D-099 carry the
same rule. No threshold, D-090 rule, source gate or live switch changed.

The complete milestone delta remains:

- `trade_alerts_build_docs/DATA_REQUIREMENTS.md`
- `trade_alerts_build_docs/DECISIONS_AND_OPEN_QUESTIONS.md`
- `trade_alerts_build_docs/M0_3I_DEFINITION_PACKET.md`
- `trade_alerts_build_docs/M0_3I_VERIFICATION.md`
- `trade_alerts_build_docs/PLAYBOOKS.md`
- `trade_alerts_build_docs/ROADMAP.md`
- `trade_alerts_build_docs/TESTING_AND_VALIDATION.md`

This repair edits the definition packet, decision, playbook, evidence policy,
proof record and ROADMAP; the earlier DATA_REQUIREMENTS change is preserved.
The original tested manifest and all published run artifacts above remain
unchanged. No code, test, configuration, dependency or launcher file was edited.

Document checks confirmed the linked local files exist, the corrected count
agrees across the affected records, and the last M0.3I/M3.3 progress rows are
complete/open. A full ROADMAP and PLAYBOOKS status scan retained the resolved
research definitions and separate source gates. The milestone documents were
also checked for private-data-shaped text. These are document checks, not
protected application-test results.

The controller's corrected-source focused, acceptance and repeatability stages
all passed. The records-only finalization changed only this proof and ROADMAP;
the tested source and controller proof remain the evidence for the
definition repair.

## Limits and next milestone

Faithful replay still requires a qualifying immutable source manifest and exact
chronological development, calibration and untouched final-validation dates.
Approximate and true profile history, bars, trades, quotes, adjustments, halts,
borrow and option facts retain their separate source gates. No external
connection, spending, alert, order, activation or profit claim occurred.

The next open milestone is **M3.3 — Relative-strength engine**, after
independent acceptance of M0.3I.
