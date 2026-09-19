# M7.3 heads-up and actionable path for `HOD_COMP_RS`

Date: 2026-09-11 Pacific. Status: **completed for independent review** for the
bounded offline supplied-input slice. The separate `[!]` definition gate and the
`[!]` source gate in ROADMAP section 31 stay open. PLAYBOOKS section 13 still
owns the unresolved `HOD_COMP_RS` questions, M0.3B is PROPOSED, and M3.3-M3.5
keep the compression and structure definitions.

`consensus_engine/hod_comp_rs_trigger.py` adds two reported paths over supplied
inputs. The heads-up notice reports one approaching structure while the supplied
M7.2 eligibility is ARMED, the supplied M7.1 distance is inside the caller's own
cutoff and the last trade still stands inside the frozen boundary. The actionable
path freezes one structure, watches the caller's own acceptance grid after the
crossing, and reports ALERT_TRIGGERED only while every supplied gate passes.
`tests/trade_alerts_contracts/test_hod_comp_rs_trigger.py` covers both paths.

A reported heads-up is a notice and ALERT_TRIGGERED is a reported state over
supplied inputs at one instant. Neither is an alert, a sent message, an approved
rule, evidence of provider coverage or permission to act.

## 1. Why nothing is hardcoded

PLAYBOOKS section 13 lists the open `HOD_COMP_RS` questions by name: the trigger
buffer, the acceptance duration and share, the trade-intensity minimum, the
heads-up distance and the compression numbers. M7.3 answers none of them.

- Every number arrives on `TriggerPolicy` with the caller's own version and
  definition reference: the buffer floor and its volatility multiple, the
  acceptance window's open and close seconds, the sample count, interval and
  share, the observation age limit, the trade-intensity minimum, the projection
  elapsed floor, the extension limit in R, the heads-up distance limit, the
  structures a session allows per direction and the cooldown between actions.
  The module compares supplied numbers; it carries none.
- `M03B_HOD_COMP_RS_V1` is not an approved definition, so a policy must name its
  own definition reference and every assessment repeats it.
- The frozen boundary is derived from the caller's own buffer floor and
  volatility multiple against the supplied M7.1 reference; nothing here decides
  how far beyond the reference a structure sits.
- A test asserts the module source carries none of the playbook's numbers.

Every number in the tests is a synthetic fixture.

## 2. What the milestone adds

- **One frozen structure.** `structure_boundary` and `freeze_structure` freeze
  the supplied reference extreme, the compression range, the supplied ATR, the
  caller's buffer and the resulting boundary into an immutable `FrozenStructure`
  that carries its own structure number and its inspected record IDs. A short
  mirrors the long; a coil on the wrong side of its own reference is refused.
- **The supplied crossing test.** `evaluate_crossing` reports CROSSED only for
  two consecutive, fresh, covered, available supplied observations on the
  caller's own grid that both stand at or beyond the boundary, and names its
  refusal otherwise. A boundary that fell onto prices already beyond it is not a
  crossing.
- **The heads-up notice.** `evaluate_hod_comp_rs_heads_up` reports three gates:
  the M7.2 ARMED eligibility, the supplied M7.1 distance against the caller's
  own cutoff, and the last trade still inside the boundary. All three must pass
  for `ARMED/HEADS_UP`; a distance that already stands beyond its own frozen
  reference is UNKNOWN, not a passing approach.
- **The actionable path.** `evaluate_hod_comp_rs_trigger` reports six gates: the
  structure still active inside its acceptance window, the acceptance share over
  the fixed sample grid, the participation arm, the last trade beyond the
  boundary, the M7.2 eligibility, and the move not already stale in R.
- **Two separate participation arms.** The tape arm consumes only its own
  supplied `TapeIntensity`; the quote-projection arm consumes only its own
  supplied `ProjectedVolume` and its own elapsed floor. An arm that is enabled
  can never repair or complete the other, and an arm that reports the wrong mode
  is a missing arm rather than a substitute one.
- **Three-valued inputs.** A missing, stale, ambiguous, late, uncovered or
  wrongly identified supplied record leaves its gate UNKNOWN, which keeps the
  structure below the state it would otherwise reach. UNKNOWN never passes. One
  unknown sample keeps the whole acceptance count unknown rather than counting
  the rest.
- **Named ends, not silent ones.** Only a compression-close invalidation, a
  broken-coil close, lost coverage at the arm's own instant, a mandatory halt or
  an unknown mandatory input ends a structure outright. A merely failing known
  gate leaves it running until its own supplied deadline, and a just-ended bar
  still awaiting its final version holds action without moving that deadline.
- **`HodCompRsTriggerMachine`** owns one `(session, symbol, direction, arm)`
  structure serially. It reserves a structure number before any crossing,
  refuses a foreign heads-up, crossing, evaluation or policy, enforces the
  supplied session quota and cooldown, and advances only after the caller
  confirms a recorded transition. An alert that already fired never re-arms
  silently: the inside-compression close is recorded first as
  `ARMED/WAITING_FOR_RESET`, and a second recorded step re-arms the owner. A
  restored owner regains every quota fact explicitly and infers nothing from its
  state alone.
- **Reuse.** The supplied observation, tape-intensity, projected-volume and
  minute-close records are the strategy-neutral M6.2 ones, reused unchanged. The
  eligibility assessment is the M7.2 one, the transition rules are the M5.3
  ones, and the canonical records are the M1.x ones. No existing module, test,
  configuration, migration or protected launcher file changed.

## 3. What the new cases cover

- Supplied contracts: the policy, the distance and extension readings, the
  frozen structure and both requests must be explicit, coherent and immutable; a
  null supplied value stays an explicit unknown with its own reason; a foreign
  arm or a backward instant is refused.
- The frozen boundary and its short mirror, the buffer moving the reference
  outward, and the boundary helper's refusals.
- The crossing test in both directions, every named crossing refusal, and a
  boundary that fell onto already-beyond prices.
- The heads-up notice in both directions and every named heads-up refusal.
- The actionable trigger in both directions and both participation modes.
- The acceptance share on both sides of its own boundary, including the same six
  samples passing a caller who supplies a smaller share.
- One missing, ambiguous, stale, uncovered, untraded, late or wrong-mode sample,
  each keeping the whole window unknown.
- Each participation arm consuming only its own evidence, the last trade falling
  back inside the boundary, a move already extended past its supplied limit in
  both directions, and every unknown extension input.
- The mandatory eligibility and halt facts, a failing eligibility gate that
  holds below the trigger, every supplied final close that ends or resets a
  structure, a pending close that holds the deadline unchanged, lost arm
  coverage at the evaluation instant, both acceptance-window edges and an
  off-grid evaluation.
- The owner: reservation, one opened structure, a heads-up before any crossing
  and a lapsed one, foreign heads-ups, crossings and evaluations, the supplied
  session quota, the supplied cooldown, an unrecorded or mismatched advance,
  backward time, a reset without a structure, expiry, restore, identity, and the
  rules covering exactly the M7.3 states.
- Immutability, stable JSON, the supported gate names, and the adopted-number
  check.
- The M4.2 engine and the M5.1 store over one supplied synthetic session, a
  refused recording that leaves the owner where it was, and one deterministic
  recording, `m7_3_hod_comp_rs_trigger_proof.json`, holding the heads-up notice,
  the trigger assessment, the transitions and the stored position.

## 4. Boundaries kept open

- [x] **M7.3 offline heads-up and actionable path:** implemented and proved
  offline for independent review.
- [!] **M7.3 definition gate:** the trigger buffer, the acceptance duration and
  share, the trade-intensity minimum, the heads-up distance, the stale-extension
  limit and the structures a session allows stay unresolved under PLAYBOOKS
  section 13 and M0.3, and M0.3B is still PROPOSED. A supplied policy adopts
  none of them.
- [!] **M7.3 source and historical-data gate:** every observation, intensity,
  projection and minute close measured here is a synthetic supplied record. No
  actual tape or quote coverage, point-in-time finality, correction or
  adjustment history is proved. Those remain blocked under M0.2, M2.3, M2.4,
  M3.1, M3.2 and M3.6. Nothing here measures profit or edge.
- [ ] Risk, confidence and suppression, and the replay and synthetic scenarios
  for this strategy, keep their M7.4-M7.5 owners. Candidate assembly and
  delivery keep their M4.5/M4.6/M4.7 owners.

## 5. Protected proof

The controller's published protected stage supplies every count, timing, hash and
byte figure for this milestone; those numbers are not written here from any
builder-local run. The required selection is the whole
`tests/trade_alerts_contracts` directory, because the new module imports the
shared M1.x records, the M4.1 strategy context, the M5.3 transition rules, the
M6.2 observation records and the M7.1/M7.2 producers that the rest of the
directory also exercises, and because the launcher installs its isolation for
the whole collection.

This milestone states a repeatability need:
`m7_3_hod_comp_rs_trigger_proof.json` is a recorded artifact, so the recording
selection must be compared between two fresh processes in addition to the
acceptance run. Every earlier milestone recording in the same runs must stay
unchanged, including the M3.6 opening-range recording, the M6.1 eligibility
recordings, the M6.4 scenario artifact, the M7.1 compression recording and the
M7.2 RS recording.

Tested milestone files: `consensus_engine/hod_comp_rs_trigger.py`
`fa9a534cfa2978b65792ccc4fd528718cecc1d4c7d245697f528451f72cb6a66` and
`tests/trade_alerts_contracts/test_hod_comp_rs_trigger.py`
`a916b60c9bdee50c3bc2e39168fd344590d86a0ee0f4455f44f893f2a08d537b`.
`M7_3_LOCAL_CHECKS.json` records the inspected hashes and the local checks that
are not proof.

## 6. Exact next milestone

**M7.4 — risk, confidence and suppression for `HOD_COMP_RS`**, now an open row
in ROADMAP section 31. M7.3's frozen structure, reported states and supplied
gates are its direct inputs, so it is the next dependency-ready work. Its
rule-bearing branch stays gated for the same reasons recorded above.

No proposed rule was approved and no strategy rule was added. All switches remain
off. No provider, broker, Discord, application, deployment, restart, order,
purchase, paid fallback or Git write occurred. D-091 remains $25 authorized,
$0 used and $0 reserved.
