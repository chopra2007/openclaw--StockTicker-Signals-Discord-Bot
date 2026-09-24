# M9.1EO M9.4 early-validation gate assessment — 2026-09-23 Pacific

## Result

The bounded reconciliation is written, but M9.1EO remains blocked on qualifying
real held-out source evidence and a promotable #1-#4 result. Completing this
assessment does not complete the required validation. M9.4 remains blocked.
Strategy #5 through #8 implementation stays closed.

## 2026-09-24 independent-work update

The historically blocked M0.2C work is reopened as M0.2CA for protected
verification and review. A supervisor measurement passed capacity admission and is
recorded in `M0_2C_CAPACITY_ASSESSMENT.md`. This does not change the M9.1EO or
M9.4 blocker and does not qualify a source, activate cleanup, or enable a live
switch. The proposed next milestone is M0.2CA, subject to independent review.

M9.1EN's protected recording preserves an offline D-108 pass, but the record is
explicitly `ENGINEERING_PILOT_ONLY`. It was built from synthetic supplied
records. It does not establish real held-out source coverage or a promotable
edge. The same record keeps promotion, alert and live release false.

The protected M9.1EN recording is in
`/root/trade-alerts-builder/runs/20260923-205906-558794-build/`
`published-artifacts-fc0e66851bce/`. Both fresh-process copies report
`exact_offline_d108_passed: true`, `gap_dependent_rules: OFF_UNTESTED`, and
`promotion_alert_or_live_released: false`. Their bytes match with SHA-256
`16d2b0aab56307fa187c403faf157dfbe17936beba3eef870d5d22a6029cc9ee`.

## Open evidence

Accepted exit-side costs, confidence, halt, macro, catalyst, daily-history,
quote-policy, continuity and parent facts remain missing. Their dependent rules
remain OFF and untested. Original availability, corrections/finality and
point-in-time membership remain recorded gaps under D-104. Real held-out
source coverage is not proven.

These gaps keep source and promotion gates open. No alert or live gate is
closed. No Strategy #5 through #8 implementation may start from the synthetic
offline pass.

## Boundary

This repair session changes records only. The complete milestone delta also
contains the preserved capacity changes to `config/full_chain_collector.yaml`,
`consensus_engine/full_chain_storage.py` and `scripts/full_chain_collector.py`,
plus `M0_2C_CAPACITY_ASSESSMENT.md`, this record and `ROADMAP.md`.
Those existing code and configuration changes were not modified in this repair. It does not rerun the
protected M9.1EN proof. No live activation, provider call, message, order,
deployment, restart or spending occurred. All switches remain off.

M0.2CA is the proposed independent shared-capacity handoff in the ROADMAP.
That capacity work does not reopen this gate. This gate can reopen only when
qualifying real source and held-out evidence exists and the required rules can
be tested, or when a later explicit owner decision changes the build order
without waiving the source, promotion, alert or live gates.

## Source-change diagnosis and verification handoff — 2026-09-24 Pacific

The reported failure was `source changed before review; rebuild required to
reconcile M9.1EO completion and M0.2CA handoff`. No failing test IDs were
reported. The saved `changes.diff` still names the old M0.2C handoff and a
blocked M9.1EO; the current records had changed the handoff to M0.2CA and marked
M9.1EO complete. The whole delta also includes the separate capacity repair.
This is a record/source-identity and missing-coverage issue, not evidence of a
failed strategy calculation. The repair preserves the code, prior attempts and
measurement, reconciles the records, and requests the directly affected tests
instead of repeating the contracts-only selection.

Fresh controller verification now covers the complete delta. Its root is
`/root/trade-alerts-builder/runs/20260923-212100-389817-build/`.
`controller-evidence.json` records source hash
`2a5127aa89bedbc0c0615636b1a0e83b274ca4a46d675bcc0ef92a0d9831604b`.
The earlier failed launch remains history and is not presented as the final
result.

- Focused: `tests.phase: focused`, `tests.runs: 1`,
  `tests.test_count: 394`, `tests.wall_seconds: 127.664`,
  `tests.selection_reason: builder named directly affected checks`,
  `tests.selectors: [tests/test_full_chain_collector.py,
  tests/test_full_chain_storage.py]`. Published artifacts:
  `published-artifacts-cd7e74baadf1/`.
- Broad acceptance: `tests.runs: 1`, `tests.test_count: 4949`,
  `tests.wall_seconds: 1197.449`, `tests.selection_reason: unknown dependency impact; safe broad fallback`,
  `tests.selectors: [tests/trade_alerts_contracts, tests/test_full_chain_collector.py,
  tests/test_full_chain_storage.py]`. Published artifacts:
  `published-artifacts-2a70f5f53376/`.
- Separate repeatability: `tests.phase: repeatability`, `tests.runs: 2`,
  `tests.test_count: 109`, `tests.wall_seconds: 460.061`,
  `tests.selection_reason: recording output requires fresh-process comparison`.
  Published artifacts: `published-artifacts-f86824e36acf/`. Both fresh
  protected runs passed with matching published outputs and `stable: true`.

The completed assessment keeps M9.4 **blocked**, since real validation evidence
is still absent; protected execution is not the sole remaining obligation. The
independent reviewer must confirm M0.2CA eligibility before advancement. All
gap-dependent rules stay OFF and untested, and all release switches stay off.
