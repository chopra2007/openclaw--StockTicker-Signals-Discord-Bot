# M0.2E provider-limit and source-contract reconciliation

Date: 2026-09-14 Pacific. Status: **PROTECTED VERIFICATION COMPLETE;
INDEPENDENT ACCEPTANCE PENDING.** All switches remain off.

## Result

This milestone reconciles the disabled M0.2D queue and retained source inventory
with dated access proof and public official provider documents. It made no
provider request, login, credential read, download, purchase or runtime change.

Schwab's public Market Data page did not establish a numeric account request
ceiling, stream subscription or symbol ceiling, current entitlement, quote or
option time units, NBBO meaning, finality, corrections or history depth. The
saved September 13 proof remains exactly two successful free reads: one SPY quote
and one restricted SPY option chain with 20 contracts over five September 14-18
expirations. Friday option times were stale on Sunday despite `isDelayed=false`.
Those observations prove bounded access only.

The queue's 110-dispatch rolling ceiling is therefore recorded as a local safety
limit, not a Schwab allowance. The intended shared order is interactive,
actionable, background and research. No consumer is wired and combined load is
still unknown. Future Schwab records must keep the original time field/value,
raw source time, received time and delay flag; an assumed time unit must stay
labeled as an interpretation until official evidence supplies the unit.

Official Databento documentation supports keeping the retained feeds separate:

- [XNYS.PILLAR](https://databento.com/docs/venues-and-datasets/xnys-pillar) is
  direct NYSE Integrated data. Its documented times describe the feed message,
  not original availability or finality of the retained history.
- [EQUS.MINI](https://databento.com/docs/venues-and-datasets/equs-mini) is a
  derived component-venue aggregate. Trade venue identity is anonymized.
- [OHLCV](https://databento.com/docs/schemas-and-data-formats/ohlcv) rows occur
  only in intervals containing a trade. A missing minute is not automatically a
  zero-volume minute.
- [Historical and Live](https://databento.com/docs/quickstart) are separate
  services. [Release notes](https://databento.com/docs/release-notes) show
  repairs and degraded periods, not a universal per-record finality or revision
  contract.

The 4,257,208-row XNYS and 4,483,742-row EQUS 13-ETF inventories, their four and
fifteen provider-degraded dates and all recorded opening gaps remain unchanged.
They are inventory, not full-market, point-in-time, final, correction-complete or
executable evidence. The selected60 selection bias and exposed historical final
dates remain separate limits.

## Complete milestone delta

- `trade_alerts_build_docs/CODING_STANDARDS.md`
- `trade_alerts_build_docs/DATA_REQUIREMENTS.md`
- `trade_alerts_build_docs/M0_2E_CONTROLLER_EVIDENCE.json`
- `trade_alerts_build_docs/M0_2E_SOURCE_RECONCILIATION.md`
- `trade_alerts_build_docs/M0_2E_TESTED_SOURCE_MANIFEST.json`
- `trade_alerts_build_docs/M0_2E_VERIFICATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

## Published protected proof

The controller verified source hash
`847836ef6c213ab445d46bd0b8faea0c344b53923c67bea45af75307bf2f69e1`.
Full figures, selectors, file hashes and fresh-process comparisons are in
`M0_2E_VERIFICATION.md`, `M0_2E_CONTROLLER_EVIDENCE.json` and
`M0_2E_TESTED_SOURCE_MANIFEST.json`.

The focused phase used these directly affected checks:

- `tests/trade_alerts_contracts/test_request_queue.py`
- `tests/trade_alerts_contracts/test_schwab_normalization.py`
- `tests/trade_alerts_contracts/test_historical_bars.py`
- `tests/trade_alerts_contracts/test_reference_inputs.py`

The focused phase passed 179 tests. The broad acceptance phase passed 3,037
tests. The controller also ran its 39 discovered recording selectors in two
fresh processes; 63 tests passed in each process and all compared recording
files matched byte for byte. Every phase had zero failures, errors and skips,
expected isolation and clean cleanup.

## Remaining gates and next milestone

Schwab account limits, subscriptions, entitlement, official time units, NBBO
fidelity and combined load remain open. Databento original availability,
finality, revisions, corrections, adjustments, full coverage, point-in-time
membership and historical execution also remain open. M0.2C remains blocked by
the local disk-reserve admission rule, and M4.7 remains blocked by its separate
behavior and proof gaps. No source, continuity, capacity, history, early-
validation, profit or live gate closes here.

The proposed next milestone is **M0.2F — retained Databento minute-source manifest
and offline adapter**. It can use the existing immutable files under the owner's
bounded read-only source authority, preserve both feeds and every unknown fact,
and make no provider request or purchase. Independent review must confirm its
dependency order before work starts.
