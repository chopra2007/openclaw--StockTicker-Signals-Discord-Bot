# M8.4 `FIRST_PULLBACK_VWAP`

Date: 2026-09-12 Pacific. Status: **implementation complete, covered and run
under the protected launcher.** The focused selection, the whole
`tests/trade_alerts_contracts` acceptance selection and the two-process
repeatability selection each ran with no failures, no errors and no skips, with
clean isolation and cleanup. The separate `[!]` `FIRST_PULLBACK_VWAP` definition
gate and the `[!]` source and historical-data gate in ROADMAP section 31 stay
open. PLAYBOOKS sections 6 and 17 still own the unresolved impulse, reversal-bar,
pullback-counting, slope/cross, retracement-band, volume-ratio, VWAP-distance and
AVWAP questions, and M0.3B is PROPOSED.

`consensus_engine/first_pullback_vwap.py` is the strategy that consumes the M8.3
measurement. M8.3 measures one frozen impulse leg and the pullback that followed
it; this module carries that measured structure the rest of the PLAYBOOKS
section 6 chain, `PULLBACK_FORMING -> ARMED -> ALERT_TRIGGERED`, on supplied
inputs. It reuses the M8.3 `FeatureSnapshot` and `PullbackPolicy`, the M6.2
`Observation`, the M2.3 `QuoteEventDecision`, the M4.4 `ConfidenceResult`, the
M4.2 `TransitionRules` and the M1.3 canonical risk, target, session and
transition records exactly as those milestones produce them. It reads no clock,
fetches no data, opens no database, stores no record, assembles no candidate and
sends nothing.

ALERT_TRIGGERED means the supplied inputs passed every gate at one evaluation
instant. It is not an alert, an approved rule, evidence of bar, tape or quote
coverage, a backtest result, an edge claim or permission to act.

## 1. Why nothing is hardcoded

- The module adopts no impulse minimum, no VWAP distance, no slope, no cross
  limit, no relative-strength floor, no retracement band, no kill retracement, no
  volume-contraction ratio, no support pad, no trigger offset, no spread limit, no
  pullback ordinal, no reward minimum and no confidence floor. A test asserts
  that no module-level number exists and that the playbook's draft figures do not
  appear in its source.
- Every threshold arrives inside the caller's supplied `PullbackVwapPolicy`,
  which names its own version and definition reference.
- Every observation arrives as a canonical supplied record: the M8.3 measurement,
  the VWAP context, the relative-strength reading, the last trade, the quote
  decision, the stop and targets and the M4.4 confidence.
- The supplied VWAP slope and relative-strength reading are read in the trade's
  own direction, because which convention names a rising VWAP stays with the
  unresolved definition. `VWAP_SLOPE_CONVENTION_UNDEFINED` is reported, not
  answered.
- Which completed pullback is the *first* one is not decided here. The caller
  supplies its own ordinal and its own maximum, and
  `FIRST_PULLBACK_COUNTING_UNDEFINED` stays named in the result.
- No confidence cutoff is applied. The floor is reported in `unavailable`
  together with the stop pad, the reward minimum, the impulse definition, the
  AVWAP question and the tape-acceleration preference.

Every number in the tests is a synthetic fixture.

## 2. What the milestone adds

- **`PullbackVwapPolicy`.** The caller's own direction, observation arm,
  staleness, impulse minimum, impulse-from-VWAP minimum, slope minimum, cross
  maximum, relative-strength minimum, retracement band and kill value, volume
  ratio, VWAP support pad, trigger offset and ATR multiple, spread limit, maximum
  pullback ordinal and first-target reward minimum.
- **`VwapContext`, `RelativeStrength` and `PullbackStructural`.** Supplied
  readings that each keep their own record ID, definition reference, availability
  instant and coverage flag. Each part may be missing on its own with a named
  reason, and a supplied value can never also claim one.
- **`evaluate_first_pullback_vwap`.** One pure evaluation reporting fifteen named
  gates: the M8.3 measurement, the impulse size, the impulse distance from VWAP,
  the last trade against the VWAP, the VWAP slope, the VWAP crosses, relative
  strength, the retracement band, the pullback volume ratio, the pullback
  support, the reversal-bar trigger, the quote spread, which pullback of the
  session this is, the stop and targets and the confidence.
- **The measurement must be this evaluation's own.** A snapshot of another
  feature version, data mode, symbol, reading direction or instant is refused by
  name, and an incomplete impulse or pullback leg keeps the owner at a forming
  pullback while naming the leg's own M8.3 reason.
- **The trigger is the reversal bar plus the larger supplied offset.** The level
  is the measured reversal-bar high for a long and its low for a short, offset by
  the greater of the caller's own absolute minimum and its own multiple of the
  supplied minute ATR. A last trade exactly at that level passes; one short of it
  does not.
- **Each supplied fact refuses on its own.** An unusable last trade, VWAP
  context, relative-strength reading, quote or geometry leaves only its own gates
  unknown, with the reason the supplied record gave. Lost coverage stays its own
  closing fact.
- **Only four supplied facts close the setup outright:** lost coverage, a cross
  count above the caller's own maximum, a retracement beyond the caller's own kill
  value and a pullback ordinal beyond the caller's own maximum. A merely failing
  known gate leaves the owner where it already stood, because the next completed
  minute may satisfy it.
- **The geometry is re-checked, never calculated.** The supplied entry must stand
  beyond the measured reversal bar, the stop beyond the measured pullback extreme
  and on the correct side of the entry, every target beyond the entry with a
  reward the supplied prices actually support, and the first target at or above
  the caller's own minimum.
- **`FirstPullbackVwapMachine`.** One serially owned `(session, symbol,
  direction)` owner that proposes canonical M4.2 transitions, advances only after
  the caller confirms the recording, records the formed pullback before the
  action, refuses a second impulse window, refuses to fall back or reopen, can
  expire, and can be restored from explicit saved facts for M5.5.

## 3. Tests

`tests/trade_alerts_contracts/test_first_pullback_vwap.py` covers the supplied
policy, VWAP context, relative-strength, structural and gate record contracts,
the canonical request checks, the rules chain, one actionable continuation in
both directions on the mirrored M8.3 session, every measurement refusal and both
incomplete legs, the impulse size and order, the impulse distance from VWAP, the
missing supplied ATR, the VWAP side, slope and cross gates with their invalidating
cross count, the directional relative-strength reading and its refusals, the
retracement band and its kill value, the volume ratio, both zero-division
reasons, the VWAP support pad, the trigger level and its exact boundary, every
unusable last trade, the quote spread, the pullback ordinal and its suppression,
every geometry refusal, every confidence mismatch, the reported result, JSON
determinism, immutability, the absence of any rule number of the module's own,
the owner's full lifecycle and restore checks, a refused recording, and one
deterministic end-to-end recording through the real M4.2 engine and M5.1 store
that writes `m8_4_first_pullback_vwap_proof.json`.

The controller's published stages supply the test count, the timings and the
hashes. No builder-run figure is written here.

## 4. Required protected selection

- Focused: `tests/trade_alerts_contracts/test_first_pullback_vwap.py`.
- Acceptance coverage: the whole `tests/trade_alerts_contracts` directory,
  because the new module reuses the M8.3 measurement, the M6.2 observation, the
  M2.3 quote decision, the M4.4 confidence, the M4.2 engine and the M5.1 store
  that the rest of the directory also exercises, and the launcher installs its
  isolation for the whole collection.
- Repeatability: required, because `m8_4_first_pullback_vwap_proof.json` is a
  recorded artifact that must be compared between two fresh processes.

All three selections ran in this session under the protected launcher with no
failures, no errors and no skips and with clean isolation and cleanup. The
acceptance selection was the whole `tests/trade_alerts_contracts` directory in
one child process. The two repeatability processes wrote a byte-identical
`m8_4_first_pullback_vwap_proof.json`, and every earlier milestone recording in
the same runs was unchanged. The launcher and its child script were not edited,
bypassed or retried.

The counts, timings and hashes belong to the controller's published stages, so
none is written here.

## 5. Required gates that stay open

- **Definition gate.** The `FIRST_PULLBACK_VWAP` impulse and reversal-bar
  definitions, swing confirmation, pullback counting, the slope and cross
  convention, the retracement band and its kill value, the volume-contraction
  ratio, the VWAP distances and the AVWAP question remain unresolved under
  PLAYBOOKS sections 6 and 17 and M0.3, and M0.3B is PROPOSED. Every value used
  here is supplied by the caller and a passing gate adopts nothing.
- **Source and historical-data gate.** The minute bars behind the M8.3
  measurement, the minute ATR, the VWAP level, slope and cross count, the
  relative-strength reading, the last trade and the quote are synthetic supplied
  records. Actual point-in-time coverage, finality, corrections, adjustment
  history, tape and quote cadence remain blocked under M0.2, M2.3, M2.4, M3.1,
  M3.2 and M7.2.
- Candidate assembly, suppression, the options path and delivery keep their M4.5,
  M4.6, M4.7 and M15 owners; cross-strategy interaction keeps its M8.5 owner;
  replay, walk-forward, ablation, shadow validation and promotion keep their M9,
  M16 and M17 owners. Nothing here measures profit or edge.

## 6. Next milestone

**M8.5 — cross-strategy interaction tests**, after independent acceptance of
M8.4. All switches remain off and D-091 stays $0 used and $0 reserved.
