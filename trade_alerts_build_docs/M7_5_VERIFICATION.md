# M7.5 replay and synthetic tests for `HOD_COMP_RS`

Date: 2026-09-11 Pacific. Status: **completed for independent review** for the
bounded offline supplied-input slice. The separate `[!]` definition gate and the
`[!]` source gate in ROADMAP section 31 stay open. PLAYBOOKS section 13 still
owns the unresolved `HOD_COMP_RS` questions, M0.3B is PROPOSED, and M3.2-M3.5
keep the compression, structural stop and target definitions.

`consensus_engine/hod_comp_rs_replay.py` adds the M4.1 strategy adapter that
lets the M5.3 replay runner drive the already-proved M7.2 eligibility machine,
M7.3 structure owner and M7.4 composition through one chronological sequence of
supplied evaluation instants. It reads no clock, fetches no data, opens no
database, measures no compression, scores no setup, assembles no alert candidate
and sends nothing.

A replayed scenario describes the supplied inputs at those instants only. It is
not a trigger, an alert, an approved rule, evidence of provider coverage, a
backtest result, an edge claim or permission to act.

## 1. Why nothing is hardcoded

- The module defines no number of its own. A test asserts that its namespace
  holds no integer or float at all.
- Every threshold arrives inside the caller's supplied `RsTrendPolicy`,
  `TriggerPolicy` and `SuppressionPolicy`, each naming its own definition
  reference. The compression ratio, the RS lookback and warm-up, the buffer, the
  acceptance share, the intensity minimum, the heads-up distance, the extension
  limit, the stop pad, the reward minimums, the confidence floor, the cooldown
  and the structure quota are adopted nowhere here.
- The replay rules are exactly the union of the M7.2 and M7.3 pairs. No
  transition either milestone did not already allow is added, and a test
  compares the union directly.
- Every compression, reference extreme, ATR, distance, observation,
  participation record, extension, stop, target, confidence result and prior
  action is a supplied record for one exact instant. Nothing is carried over
  from an earlier instant and nothing is defaulted.
- The caller names its own `strategy_version` and `definition_reference`. Naming
  them neither adopts a proposed rule nor claims the referenced definition was
  approved.

Every number in the tests is a synthetic fixture.

## 2. What the milestone adds

- **`StructureInputs`.** The caller's own frozen instant, reference extreme,
  compression range, ATR, anchor bar and record references. The same supplied
  values freeze the same structure for the heads-up notice and for the crossing
  that opens it, so a later evaluation cannot walk the boundary this owner
  already acted on.
- **`CrossingInputs`.** The two consecutive same-arm observations and the
  structure they cross. The boundary tested is the one that structure freezes
  on, so the crossing and the opened structure always describe the same prices.
- **The noticed structure is kept.** Once a heads-up transition is recorded,
  this owner keeps the exact `FrozenStructure` it described and compares every
  later supplied structure against it. A crossing or a second notice whose
  frozen instant, direction, arm, structure number, reference extreme,
  compression range, frozen ATR, buffer, boundary or anchor bar differs is
  refused with a `RecordError` naming the changed facts, so changed prices or a
  changed ATR can never walk the boundary the notice already described. The kept
  structure is dropped as soon as the crossing, a reset or an expiry closes the
  notice; from then on the M7.3 owner enforces its own open structure.
- **`HodCompRsReplayStep`.** Every supplied input for one exact evaluation
  instant: mandatory status, the compression and its distance, the crossing, the
  acceptance-grid observations, the participation record, the last trade, the
  extension risk, a minute close, a reset close, the structural reading, the
  confidence result and the action history. A field left null stays an explicit
  unknown for its own gate.
- **`HodCompRsReplayStrategy`.** One serially owned `(session, symbol,
  direction)` replay owner. It holds the M7.2 eligibility machine below ARMED
  and hands control to the M7.3 structure owner once a supplied compression
  reports a heads-up or a supplied crossing opens a structure; control returns
  after a supplied inside-compression close resets it. While a notice or a
  structure stands, the eligibility assessment is still evaluated at every
  instant, because it is the mandatory input the notice and the structure read.
- **State advances only after recording.** `update` returns the proposed
  transitions and confirms them at the start of the next evaluation, so a
  refused recording leaves this owner exactly where it was.
- **Two boundaries kept explicit.** `heads_up` and `actionable` stay `None`,
  because candidate assembly, the suppression record, deduplication, the options
  path and delivery keep their existing M4.5/M4.6 owners; `invalidate` is
  refused outright and `expire` applies only to a structure this owner already
  opened, so a caller can never assert an outcome the supplied evidence did not
  produce.
- **Reuse.** The eligibility machine, the structure owner and the composition
  are the real M7.2, M7.3 and M7.4 producers; the runner, the transition engine
  and the research store are the real M5.3, M4.2 and M5.1 ones. No existing
  module, test, configuration, migration or protected launcher file changed.

Changed files: `consensus_engine/hod_comp_rs_replay.py` (new),
`tests/trade_alerts_contracts/test_hod_comp_rs_replay.py` (new), this document,
`M7_5_LOCAL_CHECKS.json` and `ROADMAP.md`.

## 3. What the new cases cover

The five named scenarios, each replayed through the M5.3 runner:

- **`clean`** and its mirrored short twin **`short`**: the supplied structure
  reports one heads-up while it is still approaching, the supplied crossing
  opens it, and the supplied acceptance grid, participation, last trade,
  eligibility and extension report ALERT_TRIGGERED with a READY M7.4
  composition. The reported stop, targets and confidence are the supplied ones,
  the entry stands beyond the frozen boundary, and the confidence floor is still
  reported as undefined.
- **`failed_break`**: six of ten supplied samples accept, so the supplied share
  is never met; the structure runs out its own deadline to WAITING_FOR_RESET and
  returns to ARMED on a supplied inside-compression close. The failing
  evaluation records no transition at all.
- **`rs_weak`**: every supplied setup gate still passes, so the coil is
  SETUP_FORMING, but the supplied relative strength stays below the caller's own
  directional minimum. The same supplied structure and crossing are present and
  open nothing.
- **`stale_extension`**: the supplied move already ran past the caller's own
  extension limit, so the structure stays at CROSSING_OBSERVED and the M7.4
  composition is REJECTED while still reporting the stop and confidence it was
  built from.

Alongside them: the union of the two milestones' rules; the module adopting no
number of its own; canonical-record checks for the step, the structure inputs
and the crossing inputs; immutability; the owner's supplied scope, chronological
distinct steps and the shared M4.1 interface; a foreign context, a missing step
and a backward instant each refused; state advancing only after the transition
was recorded; the refused caller-asserted invalidation and expiry beside a real
expiry of an open structure; a reset owner starting the supplied session again;
a crossing that is not fresh and a crossing observed at another instant; an
armed instant with no supplied structure proposing nothing; the runner's fixed
provenance; and every replayed input and transition stored exactly once.

Added by this repair: for long and for short, a crossing supplied after a
recorded heads-up with a changed reference extreme, and one with a changed ATR,
are each refused, the owner stays at the heads-up state and still reports the
structure it noticed; and, for long and short, the noticed structure is present
only while the notice stands and is dropped once the crossing opens it.

Determinism: every scenario is replayed twice in separate fresh databases and
must render identical JSON and identical fingerprints, and the five scenarios
write one deterministic combined artifact, `m7_5_hod_comp_rs_scenarios.json`,
whose five fingerprints are distinct.

## 4. Boundaries kept open

- [x] **M7.5 offline replay and synthetic tests:** implemented and proved
  offline for independent review.
- [!] **M7.5 definition gate:** every `HOD_COMP_RS` threshold these scenarios
  supply stays unresolved under PLAYBOOKS section 13 and M0.3, and M0.3B is
  still PROPOSED. A passing scenario adopts no value by inference.
- [!] **M7.5 source and historical-data gate:** the five scenarios are synthetic
  supplied records. Actual point-in-time minute, tape, quote, benchmark,
  halt/macro and prior-session coverage, finality, corrections and adjustment
  history remain blocked under M0.2, M2.3, M2.4, M3.1, M3.2 and M3.6.
- [ ] Walk-forward, ablation, shadow validation, promotion and any profit or
  edge claim keep their M9, M16 and M17 owners. Candidate assembly, the
  `SuppressionEvent` record, the options path and delivery keep their existing
  M4.5/M4.6/M4.7 owners.

## 5. Protected proof

This repair changed the module and its test file, so every figure and hash the
earlier published proof carried is invalidated and is not reused here. The
controller's rerun of the protected stages for this attempt supplies the fresh
figures — test counts, pytest lines, JUnit seconds, controller wall times,
recording hashes and the tested-source manifest — and no builder-run number is
written in their place.

The protected phases stay the same three. The focused phase selects
`tests/trade_alerts_contracts/test_hod_comp_rs_replay.py`; the acceptance phase
selects `tests/trade_alerts_contracts`; the repeatability phase selects the
controller's recording selectors, run twice in fresh processes.

The required selection is the whole
`tests/trade_alerts_contracts` directory, because the new module drives the M7.2
eligibility machine, the M7.3 structure owner, the M7.4 composition, the M5.3
replay runner, the M4.2 transition engine and the M5.1 research store that the
rest of the directory also exercises, and because the launcher installs its
isolation for the whole collection. The focused selector is
`tests/trade_alerts_contracts/test_hod_comp_rs_replay.py`.

This milestone states a repeatability need:
`m7_5_hod_comp_rs_scenarios.json` is a recorded artifact, so the recording
selection must be compared between two fresh processes in addition to the
acceptance run. That comparison, its run count, its selectors, its artifact
directory and its recording hashes come from the controller's fresh publication
for this attempt. Every earlier milestone recording in the same runs must stay
unchanged, including the M3.6 opening-range recording, the M6.1 eligibility
recordings, the M6.3 risk recordings, the M6.4 scenario artifact, the M7.1
compression recording, the M7.2 RS recording, the M7.3 trigger recording and the
M7.4 composition proof. Acceptance and repeatability stay separate proof.

The tested milestone files are `consensus_engine/hod_comp_rs_replay.py` and
`tests/trade_alerts_contracts/test_hod_comp_rs_replay.py`. Their fresh hashes and
the complete tested-source manifest come from the controller's published
manifest for this attempt. `M7_5_LOCAL_CHECKS.json` records the locally
inspected hashes, which are not proof, and the local checks that are not proof.

## 6. Exact next milestone

**M8.1 — ORB→failure transition support**, now an open row in ROADMAP section
31: the shared offline support that lets a supplied opening-range break hand
over to a failure/reversal owner, reusing the M3.6 opening range, the M6.2
attempt records and the M4.2 engine, still on supplied inputs. Its rule-bearing
branch stays gated, because the `OR_FAILURE_REV` thresholds remain unresolved
under PLAYBOOKS section 13 and M0.3 and M0.3B is still PROPOSED.

No proposed rule was approved and no strategy rule was added. All switches remain
off. No provider, broker, Discord, application, deployment, restart, order,
purchase, paid fallback or Git write occurred. D-091 remains $25 authorized,
$0 used and $0 reserved.

## 7. Repair of the reported structure-identity failure

The reported failure: after HEADS_UP, the replay owner accepted a different
`CrossingInputs.structure` with changed prices or ATR, which could move the
frozen boundary and contradicted the structure-identity claim above. No failing
test IDs were supplied.

Cause: the owner froze each supplied `StructureInputs` on its own and kept no
record of the structure a recorded heads-up stood on, so nothing compared a
later crossing structure against it.

Fix: the owner now keeps that `FrozenStructure` while the notice stands, exposes
it through `noticed_structure()`, and refuses any later supplied structure that
differs in any frozen fact, naming the changed facts in the error. The kept
structure is dropped once the crossing, a reset or an expiry closes the notice.
Four new cases cover a changed reference extreme and a changed ATR for long and
for short, and two more check that the noticed structure is present only while
the notice stands. The five named scenarios and every earlier case are unchanged.

Because product code and tests changed, the earlier published proof no longer
applies; section 5 names the phases and selectors, and the controller's rerun
supplies the fresh figures and hashes. Usage is unknown.
