# M7.4 risk, confidence and suppression for `HOD_COMP_RS`

Date: 2026-09-11 Pacific. Status: **completed for independent review** for the
bounded offline supplied-input slice. The separate `[!]` definition gate and the
`[!]` source gate in ROADMAP section 31 stay open. PLAYBOOKS section 13 still
owns the unresolved `HOD_COMP_RS` questions, M0.3B is PROPOSED, and M3.2-M3.5
keep the structural stop, target and compression definitions.

`consensus_engine/hod_comp_rs_risk_confidence.py` composes four supplied things
at one evaluation instant: the M7.3 `TriggerAssessment`, the caller's own
structural stop and targets, the M4.4 `ConfidenceResult` and the caller's own
suppression policy and prior-action history. It re-checks that every supplied
part describes this frozen structure at this exact instant, then reports the
stop, the targets, the confidence and the suppression decision those inputs
already carry. It calculates no stop, no target, no R multiple, no score and no
weight of its own. It reads no clock, fetches no data, opens no database, stores
nothing, assembles no alert candidate and sends nothing.

`READY` here means the supplied composition held together at one instant in a
test process. `SUPPRESSED` reports the caller's own history decision. Neither is
an alert, an approved rule, evidence of provider coverage, a quality cutoff or
permission to act.

## 1. Why nothing is hardcoded

PLAYBOOKS section 13 leaves the `HOD_COMP_RS` stop, target and suppression
numbers open, and `M03B_HOD_COMP_RS_V1` is not an approved definition. M7.4
answers none of them.

- The module calculates no stop, no target, no R multiple, no factor, no score
  and no weight. Every one of those numbers arrives inside the supplied
  `StructuralReading` and `ConfidenceResult`, each carrying its own definition
  reference.
- The playbook's `compression_low - 0.05 * ATR_1m` stop is **not** adopted. The
  module checks only that the supplied stop stands behind the entry and outside
  the frozen coil; how far outside stays the caller's own undefined number,
  reported as `STOP_PAD_UNDEFINED`.
- The playbook's `T1 >= 1.5R` and `T2 >= 2.5R` preferences are **not** adopted.
  No reward minimum of any size is applied; a target may only not claim more
  reward than its own supplied prices show. `TARGET_REWARD_MINIMUM_UNDEFINED` is
  reported instead.
- **No quality cutoff is applied.** A minimum confidence is a rule-bearing number
  no approved definition supplies, so `CONFIDENCE_FLOOR_UNDEFINED` is reported
  instead of filtering. A final score of 0 and a final score of 100 both compose
  to `READY`.
- Every suppression number arrives on `SuppressionPolicy` with the caller's own
  version and definition reference: the cooldown, the actionable count a single
  structure allows, the structures a session allows per direction, whether an
  opposite-direction conflict suppresses at all, and that conflict's window. The
  playbook's "one actionable, ~10-minute cooldown, max ~2 structures" prior is
  adopted nowhere in the module.
- `D-090` section 6's two undefined structures stay named: `SOFT_INVALIDATION_
  UNDEFINED` and `RUNNER_UNDEFINED`.
- The caller names its own `strategy_version` and `definition_reference`. Naming
  them neither adopts a proposed rule nor claims the referenced definition was
  approved.
- A test asserts the module source carries none of the playbook's numbers.

Every number in the tests is a synthetic fixture.

## 2. What the milestone adds

- **`StructuralReading`.** One supplied stop and target set measured for this
  frozen structure under the caller's own definition reference, with its own
  direction, arm, structure number, crossing instant, evaluation instant,
  availability instant and record references. A missing measurement stays an
  explicit unknown with its own reason and carries no targets beside it; a
  supplied stop may not also claim to be missing.
- **`SuppressionPolicy`, `PriorAction` and `ActionHistory`.** The caller's own
  suppression numbers, the earlier heads-up and actionable rows this session
  already reported, and whether that history is complete and current.
- **The trigger gate.** Only a trigger whose supplied gates all passed
  (`ALERT_TRIGGERED`) composes a `READY` outcome. An unknown trigger input keeps
  the outcome `UNAVAILABLE` and names the first unknown gate; a definite refusal,
  including an invalidated structure, keeps it `REJECTED` and names the failing
  gate. The frozen structure's references are retained either way.
- **The supplied stop and targets, re-checked here.** M7.3 never saw them; this
  boundary checks the reading it was actually handed, so a later, mirrored,
  differently framed or foreign-arm measurement cannot arrive as this structure's
  geometry. The reading must use this arm, this direction, this structure number,
  this crossing instant and this evaluation instant, and must already have been
  available. An entry inside the frozen boundary, a stop on the wrong side of the
  entry, a stop inside the frozen compression, a target that is not beyond the
  entry and a target claiming more reward than its own prices show never pass.
- **The M4.4 confidence for this instant.** The supplied composition must belong
  to `HOD_COMP_RS`, the caller's named strategy version, this direction and this
  evaluation instant, and must itself be `READY`. A missing score or a missing
  declared factor stays an explicit unknown; it never becomes a zero.
- **The suppression decision.** Over the caller's own complete, current history:
  a second actionable for the same structure, the session's structure quota in
  this direction, the cooldown since the latest action in this direction, and an
  outstanding opposite-direction action inside the caller's own conflict window.
  Every matching reason is reported in one fixed order, and the gate names the
  first. A heads-up row never suppresses the actionable, and the other direction
  never consumes this direction's quota or cooldown.
- **Unknown history never becomes an empty one.** A missing, incomplete, stale or
  ahead-of-evaluation history leaves the suppression gate `UNKNOWN`, so a
  duplicate action can never pass on silence alone.
- **Per-gate reporting and one ranked status.** Each field is populated only by
  the gate that passed for it, so a refused or unknown input leaves its own facts
  absent instead of half-stated. Any unknown keeps the whole outcome
  `UNAVAILABLE`; a definite refusal with nothing unknown is `REJECTED`; an
  otherwise complete action the caller's own history suppresses is `SUPPRESSED`.
- **Exact comparison.** Entry, stop, target, boundary, compression and elapsed
  comparisons use `Fraction(str(value))`, so the frozen boundary and the entry
  beside it do not move on binary floating-point representation.
- **A deterministic compact record.** `as_dict`/`to_json` render the gates, the
  frozen structure, the stop, the targets, the confidence with its factors, the
  suppression reasons and what stays undefined. The same supplied inputs render
  the same bytes.
- **Reuse.** The trigger assessment and frozen structure are the M7.3 ones, the
  confidence result is the M4.4 one, the stop and target rows are the M1.x
  canonical `RiskLevel` and `TargetLevel`, and the transition rules are the M5.3
  ones. The `SuppressionEvent` record itself keeps its M4.5 owner: this module
  reports the reasons that caller would record. No existing module, test,
  configuration, migration or protected launcher file changed.

Changed files: `consensus_engine/hod_comp_rs_risk_confidence.py` (new),
`tests/trade_alerts_contracts/test_hod_comp_rs_risk_confidence.py` (new), this
document, `M7_4_LOCAL_CHECKS.json` and `ROADMAP.md`.

## 3. What the new cases cover

- Supplied contracts: every part of the request must be canonical and explicitly
  labelled; the composition refuses anything but its own request type; the
  structural reading, the suppression policy, a prior action and the history each
  refuse their own malformed or unlabelled values; a missing measurement stays an
  explicit unknown.
- The composed `READY` path in both directions and both participation arms: the
  reported stop, targets, confidence, structural references, state, crossing and
  versions are exactly the supplied ones.
- The caller's own weights carried through, and no quality cutoff: final scores
  of 0, 1 and 100 all compose to `READY`.
- What stays undefined, named exactly.
- The trigger gate: a failing acceptance window and an unknown participation
  input each keep the outcome out of `READY` with the right status and reason,
  and the frozen structure references are retained.
- The structural gate: foreign arm, foreign direction, another structure number,
  another crossing, another instant, a reading not yet available, a missing stop,
  missing targets, an entry inside the frozen boundary, a stop on the wrong side,
  a stop inside the frozen compression in both directions, a target behind the
  entry in both directions, and an overstated R multiple beside the same prices
  passing with the reward they actually measure.
- The confidence gate: another strategy, another strategy version, another
  direction, another instant, and each of the six missing scores or declared
  factors.
- The suppression gate: unknown, incomplete, stale and ahead-of-evaluation
  history; a duplicate structure actionable and the same history passing a caller
  who allows two; the session quota and a structure already counted not consuming
  it twice; the cooldown on both sides of its own boundary and exactly at it; an
  opposite-direction conflict only while it stands, inside its own window and
  only when the caller enabled it; the other direction consuming neither quota
  nor cooldown; a heads-up never suppressing the actionable; every matching
  reason in one fixed order; and a suppressed action still reporting the facts it
  was built from.
- Ranking: a refusal or an unknown input outranks a suppression, and one refusal
  beside one unknown stays `UNAVAILABLE` with each reason keeping its own gate.
- Immutability, stable JSON, the supported gate names, and the adopted-number
  check.
- The M4.2 engine and the M5.1 store over one supplied synthetic session in both
  directions, then the composed outcome at that recorded trigger and the same
  composition suppressed once the caller records that action, with one
  deterministic recording, `m7_4_hod_comp_rs_risk_confidence_proof.json`.

## 4. Boundaries kept open

- [x] **M7.4 offline risk, confidence and suppression:** implemented and proved
  offline for independent review.
- [!] **M7.4 definition gate:** the stop pad below the compression, the reward
  minimums, the confidence floor and weights, the cooldown, the actionable count
  per structure and the structures a session allows stay unresolved under
  PLAYBOOKS section 13 and M0.3, and M0.3B is still PROPOSED. A supplied policy
  adopts none of them.
- [!] **M7.4 source and historical-data gate:** every observation, score, stop,
  target and prior action composed here is a synthetic supplied record. No actual
  tape or quote coverage, point-in-time finality, correction or adjustment
  history is proved. Those remain blocked under M0.2, M2.3, M2.4, M3.1, M3.2 and
  M3.6. Nothing here measures profit or edge.
- [ ] Replay and synthetic scenario coverage for this strategy belongs to M7.5.
  The `SuppressionEvent` record, candidate assembly, the options path and
  delivery keep their existing M4.5/M4.6/M4.7 owners.

## 5. Protected proof

The controller's published protected stage supplies every count, timing, hash and
byte figure for this milestone; those numbers are not written here from any
builder-local run. The required selection is the whole
`tests/trade_alerts_contracts` directory, because the new module imports the
shared M1.x canonical records, the M4.1 strategy context, the M4.4 confidence
composition, the M5.3 transition rules and the M7.3 trigger producer that the
rest of the directory also exercises, and because the launcher installs its
isolation for the whole collection.

This milestone states a repeatability need:
`m7_4_hod_comp_rs_risk_confidence_proof.json` is a recorded artifact, so the
recording selection must be compared between two fresh processes in addition to
the acceptance run. Every earlier milestone recording in the same runs must stay
unchanged, including the M3.6 opening-range recording, the M6.1 eligibility
recordings, the M6.3 risk recordings, the M6.4 scenario artifact, the M7.1
compression recording, the M7.2 RS recording and the M7.3 trigger recording.

Tested milestone files: `consensus_engine/hod_comp_rs_risk_confidence.py`
`8ef374f00ab4d0c029ad76b7adb4b197614fe992a39e5c6fdb1ed31b72aa8210` and
`tests/trade_alerts_contracts/test_hod_comp_rs_risk_confidence.py`
`5aa88b533ad85688cf240d13880ff2f3755cfd99f4dc6c00b2e244530b173403`.
`M7_4_LOCAL_CHECKS.json` records the inspected hashes and the local checks that
are not proof.

## 6. Exact next milestone

**M7.5 — replay and synthetic tests for `HOD_COMP_RS`**, now an open row in
ROADMAP section 31: the compression break, the failed break, the RS-weak case and
the stale extension over the M5.3 replay runner, still on supplied inputs. Its
rule-bearing branch stays gated for the same reasons recorded above.

No proposed rule was approved and no strategy rule was added. All switches remain
off. No provider, broker, Discord, application, deployment, restart, order,
purchase, paid fallback or Git write occurred. D-091 remains $25 authorized,
$0 used and $0 reserved.
