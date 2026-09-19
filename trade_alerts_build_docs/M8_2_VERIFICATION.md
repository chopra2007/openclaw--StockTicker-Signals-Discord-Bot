# M8.2 `OR_FAILURE_REV`

Date: 2026-09-12 Pacific. Status: **implementation complete, covered and run
under the protected launcher.** The focused selection, the whole
`tests/trade_alerts_contracts` acceptance selection and the two-process
repeatability selection each ran with no failures, no errors and no skips, with
clean isolation and cleanup. The separate `[!]` `OR_FAILURE_REV` definition gate
and the `[!]` source and historical-data gate in ROADMAP section 31 stay open.
PLAYBOOKS section 13 still owns the unresolved `OR_FAILURE_REV` questions and
M0.3B is PROPOSED.

`consensus_engine/or_failure_rev.py` is the strategy that consumes the M8.1
handoff. M8.1 decides whether one ended supplied opening-range break hands its
structure over to a failure/reversal owner; this module carries that handed-over
structure the rest of the PLAYBOOKS section 5 chain,
`FAILURE_FORMING -> ARMED -> ALERT_TRIGGERED`, with the failure confirmation, the
supplied stop and targets and the supplied confidence. It reuses the M8.1
assessment, the M6.2 attempt records (`FrozenCandidate`, `MinuteClose`,
`Observation`), the M2.3 quote decision, the M4.3 risk and target records, the
M4.4 composition and the M4.2 transition engine exactly as those milestones
produce them. It reads no clock, fetches no data, opens no database, stores no
record, assembles no candidate and sends nothing.

Reporting ALERT_TRIGGERED describes the supplied inputs at one evaluation
instant. It is not an alert, an approved rule, evidence of provider coverage, a
backtest result, an edge claim or permission to act.

## 1. Why nothing is hardcoded

- The module defines no number of its own. A test asserts that its namespace
  holds no integer or float at all, and that the playbook's draft figures do not
  appear in its source.
- Every threshold arrives inside the caller's supplied `ReversalPolicy`, which
  names its own version and definition reference: which confirmation its own
  definition requires, the observation age limit, the minimum inside acceptance,
  the spread limit in basis points, the minimum displacement as an ATR multiple,
  the maximum extension in R and the minimum first-target R multiple.
- The unresolved PLAYBOOKS section 13 questions stay unresolved here. The
  meaningful excursion and the reacceptance window keep their M8.1 supplied
  owner; the failure timer origin, the inside-acceptance window, the mandatory
  close versus the stronger failure-bar trigger and reversal ownership after an
  ORB are all supplied, never adopted.
- No confidence cutoff is applied. The floor belongs to the unresolved
  definition, so a low supplied score still reports its own state and the
  missing floor is named in `unavailable` instead of being filled in.
- The stop, the targets, the R multiples, the inside-acceptance share, the
  spread and the score are all measured by the caller and only re-checked here
  against the handed-over break.

Every number in the tests is a synthetic fixture.

## 2. What the milestone adds

- **`ReversalPolicy`.** The caller's own confirmation choice, observation age
  limit, acceptance minimum, spread limit, displacement minimum, extension
  maximum and first-target minimum, with its own version and definition
  reference.
- **`InsideAcceptance` and `FailureBar`.** One supplied share of the failure
  window spent back inside the range, and one supplied minute bar whose extreme
  the stronger trigger must break. Both carry their own availability and
  coverage flags, and both may report an explicitly unknown value with its own
  reason instead of a number.
- **`ReversalStructural`.** One supplied M4.3 stop and target reading framed on
  its own direction, attempt, crossing and instant, so a reading taken from
  another structure cannot stand in for this one.
- **`ReversalRequest` and `evaluate_or_failure_rev`.** One pure evaluation of one
  handed-over failed break reporting nine gates: `FAILURE_HANDOFF`,
  `LAST_BACK_INSIDE_RANGE`, `FAILURE_CONFIRMATION`, `INSIDE_ACCEPTANCE`,
  `SPREAD_BPS`, `DISPLACEMENT_FROM_EDGE`, `STALE_EXTENSION`, `RISK_TARGETS` and
  `CONFIDENCE`.
- **Only a current M8.1 FAILURE_FORMING handoff opens the reversal.** A handoff
  evaluated at another instant is not this instant's fact however complete it
  looks; an unknown M8.1 gate stays explicitly unknown; a handoff that is not
  failure forming arms nothing; and a closed handoff closes the reversal with it.
- **The reversal direction is the mirror of the break**, taken from M8.1 rather
  than decided again here.
- **The supplied last trade must stand back inside the failed edge**, and far
  enough inside to clear `min_displacement_atr_multiple * frozen ATR`. A price
  that only just slipped back inside is refused, and the same slight move passes
  under a smaller supplied minimum.
- **Each confirmation arm is its own supplied definition.** The mandatory arm
  needs an available final close after the crossing and back inside the range;
  the stronger arm needs the supplied failure bar and a last trade beyond that
  bar's own extreme. Neither arm stands in for the other, and neither repairs a
  missing record of the other's kind.
- **A move that already ran past the caller's own maximum is stale.** The
  extension is measured in the caller's own supplied risk units and closes the
  reversal rather than reporting it late.
- **The supplied geometry is re-checked, never recomputed.** The identity checks
  come first; then the entry must lie inside the failed range, the stop must sit
  beyond the break's own furthest traded price and on the right side of the
  entry, each target must lie beyond the entry with a stated R multiple the
  supplied prices support, and the first target must clear the caller's own
  minimum. How far beyond the extreme the stop sits stays the caller's own
  undefined pad. A breakout extreme that disagrees with the M8.1 excursion is
  refused.
- **The supplied confidence must be this subject's.** A composition for another
  strategy, version, direction or instant stays unknown, and an incomplete one
  never passes.
- **`OrFailureRevMachine`.** One serially owned `(session, symbol, reversal
  direction)` owner that proposes canonical M4.2 transitions and advances only
  after the caller confirms the recording. A first evaluation that already passes
  everything proposes both steps, so the recorded history always shows ARMED
  before the actionable state, and the second step needs its own explicitly
  supplied record ID. It refuses a different break once one is taken over, a fall
  back from an actionable reversal, backward evaluation time and inputs that are
  not its own. An armed reversal that stops being supported is closed explicitly
  instead of being silently dropped, and `restore` positions an unused owner on
  explicitly supplied saved facts only.

## 3. Tests

`tests/trade_alerts_contracts/test_or_failure_rev.py` covers the supplied policy
and record contracts, the mirrored direction, the exact M4.2 rule pairs, one
supplied actionable reversal in both directions, both confirmation arms, all nine
gates with every named refusal, the state each gate combination supports, the
deterministic JSON, the absence of any number of the module's own, the owner's
staged and single-step proposals, its refusals, expiry and restore, a refused
recording that leaves the owner where it was, and one long/short end-to-end path
through the real M4.2 engine and M5.1 store that writes the deterministic
`m8_2_or_failure_rev_proof.json` recording.

The controller's published run supplies the test count, the timings and the
hashes. No builder-run figure is written here.

## 4. Required protected selection

- Focused: `tests/trade_alerts_contracts/test_or_failure_rev.py`.
- Acceptance coverage: the whole `tests/trade_alerts_contracts` directory,
  because the new module reuses the M8.1 handoff, the M6.2 trigger records, the
  M3.6 opening range, the M2.3 quote decision, the M4.3 risk records, the M4.4
  composition, the M4.2 engine and the M5.1 store that the rest of the directory
  also exercises, and the launcher installs its isolation for the whole
  collection.
- Repeatability: required, because `m8_2_or_failure_rev_proof.json` is a
  recorded artifact that must be compared between two fresh processes.

All three selections ran in this session under the protected launcher with no
failures, no errors and no skips and with clean isolation and cleanup. The
acceptance selection was the whole `tests/trade_alerts_contracts` directory in
one child process. The two repeatability processes wrote a byte-identical
`m8_2_or_failure_rev_proof.json`. The launcher and its child script were not
edited, bypassed or retried.

The counts, timings and hashes belong to the controller's published stages, so
none is written here.

## 5. The earlier attempt in this build run, and what this attempt repaired

An earlier session in the same build run wrote the module and its coverage and
then stopped at its own API session limit before any protected run. That partial
work was preserved, not restarted. Running the focused selection showed that the
fixtures, not the module, were wrong in five places, and all five repairs are in
the test file only:

- The mirrored short-break fixtures flipped their prices on the reversal
  direction instead of the break direction, so every short-break record was
  built in the wrong price space and the mirrored failure bar had its low above
  its high. They now mirror on the break direction, as the M8.1 fixtures do.
- The last-trade helper could not express a supplied price of `None`, because
  `price=None` already meant "the fixture's own price". It now uses an explicit
  sentinel, so the no-trade-observed case is the case it claims to be.
- The not-failure-forming handoff case supplied no reacceptance close at all,
  which is an unknown input rather than a failed gate. It now supplies a close
  outside the range, which is the failed gate the case asserts.
- The unusable-quote cases named reasons the real M2.3 quote decision never
  produces. They now name the decision's own reasons, and the case that tried to
  build a crossed quote is replaced by the missing-ask case, because the
  canonical `Quote` record refuses a bid above its ask outright.
- The geometry-mismatch case passed its direction into the helper's own
  parameter instead of the record, and the stop-short-of-the-extreme case
  supplied a narrow risk that also tripped the stale-extension gate. Both now
  isolate the gate they name.

## 6. Required gates that stay open

- **Definition gate.** The `OR_FAILURE_REV` thresholds remain unresolved under
  PLAYBOOKS section 13 and M0.3, and M0.3B is PROPOSED. Every value used here is
  supplied by the caller; a passing gate adopts nothing, and no confidence floor
  is applied.
- **Source and historical-data gate.** The opening range, the attempt records,
  the breakout extreme, the last trade, the confirmation close, the failure bar,
  the inside acceptance, the quote, the stop, the targets and the scores are
  synthetic supplied records. Actual point-in-time minute, tape and quote
  coverage, finality, corrections and adjustment history remain blocked under
  M0.2, M2.3, M2.4, M3.1, M3.2 and M3.6.
- Candidate assembly, suppression, the options path and delivery keep their M4.5,
  M4.6, M4.7 and M15 owners. Walk-forward, ablation, shadow validation and
  promotion keep their M9, M16 and M17 owners. Nothing here measures profit or
  edge.

## 7. Next milestone

**M8.3 — impulse/pullback primitives**, the shared offline support the
`FIRST_PULLBACK_VWAP` playbook needs, after independent acceptance of M8.2. All
switches remain off and D-091 stays $0 used and $0 reserved.
