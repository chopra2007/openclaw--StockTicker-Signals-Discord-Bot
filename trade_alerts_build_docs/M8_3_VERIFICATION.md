# M8.3 impulse/pullback primitives

Date: 2026-09-12 Pacific. Status: **implementation complete, covered and run
under the protected launcher.** The focused selection, the whole
`tests/trade_alerts_contracts` acceptance selection and the two-process
repeatability selection each ran with no failures, no errors and no skips, with
clean isolation and cleanup. The separate `[!]` `FIRST_PULLBACK_VWAP` definition
gate and the `[!]` source and historical-data gate in ROADMAP section 31 stay
open. PLAYBOOKS sections 6 and 17 still own the unresolved impulse, reversal-bar
and pullback-counting questions and M0.3B is PROPOSED.

`consensus_engine/impulse_pullback.py` is the shared offline support the
`FIRST_PULLBACK_VWAP` playbook needs. It measures one frozen impulse leg over the
caller's own supplied window and the pullback that followed it, on supplied
minute bars. It reuses the M2.2 canonical `Bar`, `FeatureValue` and
`FeatureSnapshot` records, the M3.1 `HistoryBatch` coverage view and the M1.2
session clock exactly as those milestones produce them. It reads no clock,
fetches no data, opens no database, stores no record, assembles no candidate and
sends nothing.

Measuring an impulse and a pullback describes the supplied bars at one evaluation
instant. It is not an alert, an approved rule, evidence of provider coverage, a
backtest result, an edge claim or permission to act.

## 1. Why nothing is hardcoded

- The module adopts no impulse minimum, no retracement band, no volume
  contraction ratio, no VWAP distance and no arming rule. A test asserts that the
  playbook's draft figures do not appear in its source.
- Every definition arrives inside the caller's supplied `PullbackPolicy`, which
  names its own version and definition reference: the direction it reads, how
  many completed minutes its own definition needs before there is a pullback to
  measure, and whether the legs are read from the bar extremes or from the
  closes.
- The impulse window itself is supplied. The caller passes its own frozen start
  and freeze instants; this module never decides where an impulse began.
- The unresolved PLAYBOOKS section 17 questions stay unresolved here. Impulse and
  reversal-bar definitions, swing confirmation, pullback counting and the
  slope/cross convention are all the definition gate's to answer; nothing here
  counts a "first" pullback or judges a leg valid.
- The minute ATR and the VWAP are supplied levels, re-expressed in the caller's
  own units and never recomputed.

Every number in the tests is a synthetic fixture.

## 2. What the milestone adds

- **`PullbackPolicy`.** The caller's own direction, minimum pullback length and
  reading convention, with its own version and definition reference.
- **`build_impulse_pullback_snapshot`.** One pure measurement returning a
  canonical `FeatureSnapshot` of nineteen named values: the impulse origin,
  extreme, distance, bar count and volume; whether the extreme printed after its
  origin; the pullback extreme, bar count, reversal-bar high and low and volume;
  the pullback depth, retracement and volume ratio; each leg's own completeness
  flag; and the impulse distance and both extremes expressed against the supplied
  VWAP in supplied minute-ATR units.
- **The impulse is frozen.** The leg is measured only over the supplied window's
  completed minutes, so a later high or low in the same session never leaks
  backwards: a 104.50 print after the freeze leaves the frozen 104.00 extreme
  where it was.
- **The pullback walks forward one whole minute at a time** from the freeze to
  the evaluation instant, and its last completed minute is the reversal bar whose
  own traded high and low are reported under either reading convention.
- **Each leg refuses on its own.** A window that is not covered, not contiguous,
  provisional, missing, untraded, contradicted by an overlapping record or of
  another instrument type keeps its own values unavailable with a named reason,
  and a refused impulse does not block the pullback measurement or the other way
  round. The supplied window must be minute-aligned, non-empty, inside the
  regular session and not reach past the evaluation instant.
- **Geometry is reported, not judged.** An extreme that printed before its own
  origin, a pullback deeper than its impulse and a pullback that never gave
  anything back are each reported as measured, including a negative retracement,
  because which of them is a valid first pullback belongs to the unresolved
  definition.
- **Nothing is divided into zero.** A flat impulse reports no retracement with
  `ZERO_IMPULSE_DISTANCE` and a volumeless impulse reports no ratio with
  `ZERO_IMPULSE_VOLUME`, instead of filling in a number.
- **A missing supplied level stays missing.** Without the minute ATR the ATR
  distances are unavailable by name; without the VWAP only the two VWAP distances
  are, and the impulse distance in ATR units still reports.

## 3. Tests

`tests/trade_alerts_contracts/test_impulse_pullback.py` covers the supplied
policy contract, both directions on one mirrored session, both reading
conventions, the frozen impulse against a later high, the pullback window and its
minimum length, every named window refusal on each leg, the reported
out-of-order, deep and negative geometries, both zero-division reasons, the ATR
and VWAP distances with their missing and non-positive reasons, incompatible or
absent history, a closed day, the public scope checks, deep immutability and JSON
round trip, the absence of any rule number of the module's own, and one
deterministic recording that writes `m8_3_impulse_pullback_proof.json`.

The controller's published run supplies the test count, the timings and the
hashes. No builder-run figure is written here.

## 4. Required protected selection

- Focused: `tests/trade_alerts_contracts/test_impulse_pullback.py`.
- Acceptance coverage: the whole `tests/trade_alerts_contracts` directory,
  because the new module reuses the M2.2 canonical records, the M3.1 history
  coverage view and the M1.2 session clock that the rest of the directory also
  exercises, and the launcher installs its isolation for the whole collection.
- Repeatability: required, because `m8_3_impulse_pullback_proof.json` is a
  recorded artifact that must be compared between two fresh processes.

All three selections ran in this session under the protected launcher with no
failures, no errors and no skips and with clean isolation and cleanup. The
acceptance selection was the whole `tests/trade_alerts_contracts` directory in
one child process. The two repeatability processes wrote a byte-identical
`m8_3_impulse_pullback_proof.json`. The launcher and its child script were not
edited, bypassed or retried.

The counts, timings and hashes belong to the controller's published stages, so
none is written here.

## 5. Required gates that stay open

- **Definition gate.** The `FIRST_PULLBACK_VWAP` impulse minimum, retracement
  band, volume-contraction ratio, VWAP distance, reversal-bar definition and
  pullback counting remain unresolved under PLAYBOOKS sections 6 and 17 and M0.3,
  and M0.3B is PROPOSED. Every value used here is supplied by the caller and a
  complete measurement adopts nothing.
- **Source and historical-data gate.** The minute bars, the ATR and the VWAP are
  synthetic supplied records. Actual point-in-time minute coverage, finality,
  corrections and adjustment history remain blocked under M0.2, M2.3, M2.4, M3.1
  and M3.2, and the AVWAP question keeps its own open owner.
- The strategy itself keeps its M8.4 owner; candidate assembly, suppression, the
  options path and delivery keep their M4.5, M4.6, M4.7 and M15 owners;
  walk-forward, ablation, shadow validation and promotion keep their M9, M16 and
  M17 owners. Nothing here measures profit or edge.

## 6. Next milestone

**M8.4 — `FIRST_PULLBACK_VWAP`**, the strategy that consumes these primitives,
after independent acceptance of M8.3. All switches remain off and D-091 stays $0
used and $0 reserved.
