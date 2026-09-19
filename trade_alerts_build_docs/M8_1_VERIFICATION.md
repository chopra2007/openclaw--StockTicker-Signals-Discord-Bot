# M8.1 ORB-to-failure transition support

Date: 2026-09-12 Pacific. Status: **implementation complete, covered and run
under the protected launcher.** The focused selection, the whole
`tests/trade_alerts_contracts` acceptance selection and the two-process
repeatability selection each ran with no failures, no errors and no skips, with
clean isolation and cleanup. The earlier attempts' blocker is gone: before this
attempt the controller raised the launcher's own per-run cap under its own
separately reviewed protection repair, so the single directory selection now
completes in one child process instead of timing out. Section 4 and
[M8_1_LAUNCHER_LIMITATION.txt](./M8_1_LAUNCHER_LIMITATION.txt) record that
history and its resolution. The separate `[!]` `OR_FAILURE_REV` definition gate and the `[!]` source
and historical-data gate in ROADMAP section 31 stay open. PLAYBOOKS section 13
still owns the unresolved `OR_FAILURE_REV` questions and M0.3B is PROPOSED.

`consensus_engine/or_failure_handoff.py` adds the shared offline support that
lets a supplied opening-range break hand over to a failure/reversal owner. It
reuses the M3.6 opening-range snapshot, the M6.2 attempt records
(`FrozenCandidate`, `MinuteClose`, `TriggerAssessment`) and the M4.2 transition
engine exactly as those milestones produce them. It reads no clock, fetches no
data, opens no database, stores no record, scores nothing and sends nothing.

Reporting FAILURE_FORMING describes the supplied records at one evaluation
instant. It is not an alert, an approved rule, evidence of provider coverage, a
backtest result, an edge claim or permission to act.

## 1. Why nothing is hardcoded

- The module defines no number of its own. A test asserts that its namespace
  holds no integer or float at all, and that the playbook's draft figures do not
  appear in its source.
- Every threshold arrives inside the caller's supplied `HandoffPolicy`, which
  names its own version and definition reference: the minimum excursion as an
  ATR multiple, the reacceptance window in seconds, and whether the caller's own
  definition owns a reversal after the ORB attempt already reached an alert.
  PLAYBOOKS section 13 leaves the meaningful excursion, the failure timer, the
  inside-acceptance window and reversal ownership unresolved, so each one is
  supplied, never adopted.
- The opening range, the frozen boundary, the ATR, the breakout extreme and the
  reacceptance close are all supplied records for their own instants. Nothing is
  defaulted and nothing is carried over from an earlier instant.
- The supplied rules stop before `OR_FAILURE_REV` ARMED. The PLAYBOOKS section 5
  chain continues `FAILURE_FORMING -> ARMED -> ALERT_TRIGGERED`; those two states
  belong to M8.2 with the unresolved thresholds, and a test asserts that no rule
  here can reach them.

Every number in the tests is a synthetic fixture.

## 2. What the milestone adds

- **`HandoffPolicy`.** The caller's own excursion minimum, reacceptance window
  and ownership rule, with its own version and definition reference.
- **`BreakoutExtreme`.** One supplied furthest traded price of the break with
  its own observation time, availability and coverage flag. An absent price
  stays unknown; it is never read as a small excursion.
- **`HandoffRequest` and `evaluate_or_failure_handoff`.** One pure evaluation of
  one supplied ended M6.2 attempt, reporting five gates:
  `ORB_ATTEMPT_ENDED`, `REVERSAL_OWNERSHIP`, `OPENING_RANGE_AGREEMENT`,
  `REAL_BREAK_EXCURSION` and `REACCEPTANCE_INSIDE`.
- **The reversal direction is the mirror of the break.** A failed upside break
  hands over to a short owner and a failed downside break to a long one;
  `mirror_direction` decides nothing else about the reversal.
- **Only a failed break hands anything over.** The supplied M6.2
  `ATTEMPT_ACTIVE` gate must already report `INSIDE_OR_CLOSE_INVALIDATION` or
  `ACCEPTANCE_DEADLINE_PASSED`. A still-running attempt, a lost-coverage or halt
  ending, and an off-grid or pending evaluation each keep the reversal owner at
  WATCHING, the unknown ones as an explicit UNKNOWN.
- **The frozen range cannot be walked.** The supplied M3.6 snapshot must carry
  the M3.6 feature version, the same instrument, a complete range and extrema
  equal to the frozen attempt's own opening range. A missing, incomplete,
  not-yet-available, foreign or disagreeing snapshot never becomes a pass.
- **A real break, by the caller's own minimum.** The supplied extreme must lie
  beyond the frozen buffered boundary and must clear
  `minimum_excursion_atr_multiple * frozen ATR` measured from the opening-range
  edge. The two refusals stay distinct: `BREAK_NOT_BEYOND_BOUNDARY` and
  `EXCURSION_BELOW_SUPPLIED_MINIMUM`.
- **The reacceptance stays a supplied fact.** Only an available final
  `MinuteClose` after the crossing and strictly inside the unbuffered range
  satisfies it. A close past the caller's own window and a lost coverage flag
  close a taken-over handoff outright; a pending or unavailable bar stays
  UNKNOWN and keeps the owner at the breakout attempt.
- **`OrFailureHandoffMachine`.** One serially owned `(session, symbol, reversal
  direction)` owner that proposes canonical M4.2 transitions and advances only
  after the caller confirms the recording. It refuses a break that does not
  reverse into its direction, a changed policy, a foreign symbol, a different
  attempt once one is taken over, a second handoff of the same ended attempt, a
  fall back from the recorded failure to the breakout attempt, and backward
  evaluation time. A first evaluation that already reports the reacceptance
  proposes both steps, so the recorded history always shows the break before its
  failure, and the second step needs its own explicitly supplied record ID.
- **Ownership is never silently dropped.** When a later supplied input stops
  supporting a recorded handoff, the owner proposes the explicit INVALIDATED
  transition instead of quietly returning to WATCHING. `release` reopens the
  owner for a different attempt and keeps the finished attempt key, and `restore`
  positions an unused owner on explicitly supplied saved facts only.

## 3. Tests

`tests/trade_alerts_contracts/test_or_failure_handoff.py` covers the supplied
policy and record contracts, the mirrored direction, the exact rule pairs, both
accepted endings and every refused one, all five gates with every named refusal
in both directions, the state each gate combination supports, the deterministic
JSON, the owner's staged and single-step proposals, its refusals, release,
expiry and restore, a refused recording that leaves the owner where it was, and
one long/short end-to-end path through the real M4.2 engine and M5.1 store that
writes the deterministic `m8_1_or_failure_handoff_proof.json` recording.

The controller's published run supplies the test count, the timings and the
hashes. No builder-run figure is written here.

## 4. Required protected selection

- Focused: `tests/trade_alerts_contracts/test_or_failure_handoff.py`.
- Acceptance coverage: the whole `tests/trade_alerts_contracts` directory,
  because the new module reuses the M6.2 trigger, the M3.6 opening range, the
  M4.2 engine and the M5.1 store that the rest of the directory also exercises,
  and the launcher installs its isolation for the whole collection.
- Repeatability: required, because `m8_1_or_failure_handoff_proof.json` is a
  recorded artifact that must be compared between two fresh processes. Every
  earlier milestone recording in the same runs must stay unchanged.

All three selections ran in this session under the protected launcher with no
failures, no errors and no skips and with clean isolation and cleanup. The
acceptance selection was the whole `tests/trade_alerts_contracts` directory in
one child process, not the split groups the earlier attempt had to use. The two
repeatability processes wrote a byte-identical `m8_1_or_failure_handoff_proof.json`,
and every earlier milestone recording listed in `M8_1_LOCAL_CHECKS.json` matched
between those same two processes as well.

**How the earlier blocker was cleared.** The two previous attempts could not
finish the single directory selection: the launcher capped each child process at
420 seconds and the directory had grown past that, so the controller's own
verification raised `subprocess.TimeoutExpired` before pytest reported. That was
a capacity limit rather than a failing test, and the M8.1 file was never the
cause. Before this attempt the controller raised that per-run cap itself, under
its own separately reviewed protection repair; the launcher hash accordingly
differs from the build-run start manifest, while the child script is unchanged.
Both hashes are recorded in `M8_1_LOCAL_CHECKS.json` and in
`M8_1_LAUNCHER_LIMITATION.txt`, and the file on disk matches this attempt's
protected baseline exactly. No build session edited, bypassed or retried either
protection script. Nothing in the M8.1 module or its coverage was changed to
make the directory fit.

The counts, timings and hashes belong to the controller's published stages, so
none is written here.

## 5. Required gates that stay open

- **Definition gate.** The `OR_FAILURE_REV` thresholds remain unresolved under
  PLAYBOOKS section 13 and M0.3, and M0.3B is PROPOSED. Every value used here is
  supplied by the caller; a passing gate adopts nothing.
- **Source and historical-data gate.** The opening range, the attempt records,
  the breakout extreme and the reacceptance close are synthetic supplied
  records. Actual point-in-time minute, tape and quote coverage, finality,
  corrections and adjustment history remain blocked under M0.2, M2.3, M2.4,
  M3.1, M3.2 and M3.6.
- ARMED, the actionable trigger, the stop, the targets, the score, candidate
  assembly, suppression, the options path and delivery keep their M8.2 and
  M4.x owners. Walk-forward, ablation, shadow validation and promotion keep
  their M9, M16 and M17 owners. Nothing here measures profit or edge.

## 6. Next milestone

**M8.2 — `OR_FAILURE_REV`**, the strategy that consumes this support, after
independent acceptance of M8.1. Its rule-bearing branch stays gated by the same
unresolved definitions. All switches remain off and D-091 stays $0 used and $0
reserved.
