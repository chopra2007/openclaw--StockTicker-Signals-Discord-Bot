# M6.4 `CRVOL_ORB5` replay and synthetic scenario coverage

Date: 2026-09-11 Pacific. Status: **completed for independent review** for the
bounded offline supplied-input slice. The separate `[!]` approved-rule gate and
the `[!]` tape, structure and source gates in ROADMAP section 31 stay open, and
the M4.3 catalog, M4.4 factor and M0.2/M2.3 source gates keep their owners.

`consensus_engine/orb5_replay.py` adds the M4.1 strategy adapter that lets the
M5.3 replay runner drive the already-proved M6.1 eligibility machine, M6.2
attempt owner and M6.3 composition through one chronological sequence of
supplied evaluation instants. `tests/trade_alerts_contracts/test_orb5_replay.py`
replays the six named scenarios: the clean catalyst breakout, the low-RVOL
fakeout, the resistance attempt that never accepts, the too-wide opening range,
the stale mandatory input and the mirrored short breakout.

A replayed scenario describes the supplied inputs at those instants only. It is
not an alert, an approved rule, evidence of source coverage, a backtest result,
an edge claim or permission to act.

## 1. Why nothing is hardcoded

The M6.1, M6.2 and M6.3 gate rows say the exact `CRVOL_ORB5` values come from
`M03B_ORB5_V1`, which is still PROPOSED. M6.4 keeps that rule:

- The adapter adds no threshold, window, buffer, acceptance minimum, quota,
  cooldown, score, weight, stop, target or cutoff. Every one of those numbers
  arrives inside the supplied M6.1 policy, M6.2 policy, M4.3 geometry result and
  M4.4 confidence result, which already carry their own definition references.
- The replay rules are exactly the union of the M6.1 and M6.2 pairs. No new
  transition is invented to join the two paths, and a test asserts the union.
- The caller names its own `strategy_version` and `definition_reference` and
  supplies every step. Naming them neither adopts a proposed rule nor claims the
  referenced definition was approved.
- A test asserts the module defines no numeric constant of its own.

Every number in the tests is a synthetic fixture.

## 2. What the milestone adds

- **`Orb5ReplayStep`.** Every supplied input for one exact evaluation instant:
  the mandatory status, the current preliminary M4.3 geometry, the optional
  crossing inputs, the arm observations, the participation record, the last
  trade, the trigger-time geometry, the M4.4 confidence, the minute close and an
  optional reset close. A field left null stays an explicit unknown for its own
  gate; nothing is carried over from an earlier instant and nothing is defaulted.
- **`CrossingInputs`.** The two consecutive same-arm observations and the
  pre-crossing structure. The buffer and boundary are recomputed from the
  supplied opening range and latest ATR before the crossing test and frozen only
  at the crossing itself, so a moving ATR cannot walk an open attempt's boundary.
- **`Orb5ReplayStrategy`.** One serially owned `(session, symbol, direction)`
  replay owner. It holds the M6.1 machine below ARMED, hands control to the M6.2
  attempt owner when a supplied fresh crossing passes the attempt quota, and
  takes control back after a supplied inside-range close resets that attempt. It
  proposes canonical transitions for the M4.2 engine and the M5.1 store; it never
  writes, sends or advances itself. State advances only after the caller records
  the proposed transition: `update` returns the transitions to store and confirms
  them at the start of the next evaluation, so a failed recording leaves the
  owner where it was. Transition record IDs are a fixed supplied prefix and an
  ordered counter, so one scenario replays the same IDs every time.
- **`orb5_replay_rules`.** The union of `eligibility_rules()` and
  `trigger_rules()`, because one replay hands the same M4.2 engine both paths.
- **Two deliberate refusals.** `heads_up` and `actionable` stay `None`: candidate
  assembly, suppression, deduplication, the options path and delivery keep their
  M4.5/M4.6 owners, and this owner reports the composed M6.3 outcome instead.
  `invalidate` and `expire` never let a caller assert an outcome the supplied
  evidence did not produce — M6.2 derives invalidation from its own gates during
  `update`, and M6.1 expiry follows the supplied evaluation window. `expire` is
  accepted only for an open attempt, where M6.2 already owns an expiry path.
- **Replayability.** Each scenario runs through
  `HistoricalReplayRunner` with the recording-only sink, the isolated M5.1 store
  and the isolated M4.2 SQLite transition store. One replay keeps one fixed
  feature-engine version, so every supplied snapshot in a scenario is produced by
  the same declared fixture version. Each scenario is replayed twice, in separate
  fresh databases, and the two `ReplayResult` renderings and fingerprints must
  match byte for byte.

Changed files: `consensus_engine/orb5_replay.py` (new),
`tests/trade_alerts_contracts/test_orb5_replay.py` (new). No existing module,
test, configuration, migration or protected launcher file changed.
`consensus_engine/orb5_eligibility.py` still hashes to `2ca34145…`,
`consensus_engine/orb5_trigger.py` to `eba26708…`,
`consensus_engine/orb5_risk_confidence.py` to `36a73ed9…`,
`consensus_engine/historical_replay.py` to `379a1861…`, and the launcher to
`a4ffdd55…` with child `85285dee…`, exactly as M6.3 recorded them.

## 3. The six supplied scenarios

Each row is one chronological sequence of supplied contexts and steps through
the M5.3 runner. Every value is a synthetic fixture.

| Scenario | Direction | What is supplied | Recorded states |
|---|---|---|---|
| Clean catalyst breakout | LONG | every eligibility gate passes with a confirmed catalyst, a fresh crossing, then ten accepting samples, the arm's own participation, a fresh last trade beyond the frozen boundary and current geometry | ARMED, ARMED/CROSSING_OBSERVED, ALERT_TRIGGERED |
| Low-RVOL fakeout | LONG | the same crossing observations, with the supplied opening RVOL below its minimum | WATCHING only; no attempt opens |
| Resistance | LONG | a fresh crossing, then six of ten accepting samples, then the deadline, then a final inside-range close | ARMED, ARMED/CROSSING_OBSERVED, ARMED/WAITING_FOR_RESET, ARMED |
| Wide opening range | LONG | the same crossing observations, with the supplied OR width over daily ATR above its band | WATCHING only; no attempt opens |
| Stale mandatory input | LONG | a fresh crossing, then a quote older than the supplied limit at the attempt evaluation | ARMED, ARMED/CROSSING_OBSERVED, INVALIDATED |
| Short breakout | SHORT | the mirrored clean path on the mirrored opening range | ARMED, ARMED/CROSSING_OBSERVED, ALERT_TRIGGERED |

The clean and short scenarios compose a `READY` M6.3 outcome whose stop, targets
and confidence are exactly the supplied ones. The stale scenario keeps the
composition `UNAVAILABLE`, naming the unknown trigger gate, while the supplied
geometry and confidence it was handed are still reported: an unknown input never
becomes a pass, and a complete confidence never repairs it. The two refused-gate
scenarios compose nothing, because no attempt is ever opened.

## 4. What the new cases cover

- The six scenarios, each asserted against its own recorded state sequence, its
  own observation count, its own composed outcome status and the recording sink's
  own copy of the observations.
- The clean and short paths: the composed outcome is `READY` with no reasons, the
  owner reports exactly that outcome's stop, targets and confidence, the stop
  sits behind the entry and both targets beyond it for each direction, and the
  confidence floor is still named as undefined.
- The two refused gates: the named failing gate, the `NOT_ARMED:WATCHING` note,
  the supplied crossing observations that still open no attempt, and no trigger
  assessment or composed outcome at all.
- The resistance path: the deadline moves the attempt to `WAITING_FOR_RESET`
  without a transition at the non-accepting evaluation, and the supplied final
  inside-range close returns it to ARMED.
- The stale path: the attempt gate names `UNKNOWN_MANDATORY_INPUT`, the
  eligibility assessment is `WATCHING`, and the composition stays `UNAVAILABLE`.
- Replay determinism: each scenario replayed twice in separate fresh databases
  renders identical JSON and identical fingerprints, and the six fingerprints are
  distinct from each other.
- One deterministic combined proof artifact, `m6_4_orb5_scenarios.json`, holding
  each scenario's direction, fingerprint, recorded states, final state, outcome
  status, outcome reasons and notes.
- Supplied record contracts: steps and crossing inputs require canonical records
  and explicit labels, both are immutable, the owner requires complete supplied
  scope, and steps must be chronological and distinct.
- The shared interface: the owner is a `Strategy`, declares its required data for
  every bound role, starts at `NOT_ELIGIBLE`, and reports no stop, target or
  confidence before any evaluation.
- Owner boundaries: a foreign context, a missing step for the instant, backward
  time, a crossing observed at another instant and a crossing that is not fresh
  are each refused or recorded as a note; state advances only after
  `confirm_recorded`; a caller cannot assert an invalidation or an expiry; an
  open attempt can be expired and then proposes nothing further; a reset owner
  starts the supplied session again from the first record ID.
- Storage and provenance: every replayed input and transition is stored once with
  distinct record IDs, and a replay specification naming another strategy version
  fails closed.

## 5. Boundaries kept open

- [x] **M6.4 offline replay and synthetic scenarios:** implemented and proved
  offline for independent review.
- [!] **M6.4 approved-rule gate:** the thresholds, buffers, acceptance minimums,
  participation minimums, quotas, cooldowns, weights, factor roster and reward
  minimums these scenarios supply still come from `M03B_ORB5_V1`, which is
  PROPOSED, and from the M4.3 catalog and M4.4 factor gates, which stay open. A
  passing scenario adopts no number.
- [!] **M6.4 source and historical-data gate:** these scenarios are synthetic
  supplied records. Actual point-in-time minute, tape, quote, catalyst,
  halt/macro and 20-prior-session coverage, finality, corrections and adjustment
  history remain blocked under M0.2, M2.3, M3.1, M3.2 and M3.6. No walk-forward,
  ablation, shadow validation or promotion evidence is produced here; M16 and M17
  keep those. Nothing here measures profit or edge.
- [ ] Candidate assembly, suppression, deduplication, the options path and
  delivery keep their existing M4.5/M4.6/M4.7 owners. M5.4's reaction-delay
  horizons stay data-blocked.

## 6. Protected proof

The controller's published protected stage supplies every count, timing, hash and
byte figure for this milestone; those numbers are not written here from any
builder-local run. The required selection is the whole
`tests/trade_alerts_contracts` directory, because the new test module imports
fixtures from `test_orb5_eligibility`, `test_orb5_trigger`,
`test_orb5_risk_confidence` and `test_strategy_interface`, and because the new
adapter reuses the M5.3 runner, the M4.2 engine and the M5.1 store.

This milestone states a repeatability need: `m6_4_orb5_scenarios.json` is a
recorded artifact, so the recording selection must be compared between two fresh
processes in addition to the acceptance run. Every earlier milestone recording in
the same runs must stay unchanged, including the M6.3, M6.2 and M6.1 recordings
and the M5.3 replay fingerprint.

Tested milestone files: `consensus_engine/orb5_replay.py`
`e6feddc9d7ba1bf1aea9cb7d9935508c22a3f6becbd72f385e988de3ff356a7c` and
`tests/trade_alerts_contracts/test_orb5_replay.py`
`75159e100731bf00c1de5ca37cab7039195d68c48153dd1077d681e12583bd5e`.
`M6_4_LOCAL_CHECKS.json` records the inspected hashes and the local checks that
are not proof.

## 7. Exact next milestone

**M7.1 — point-in-time HOD/LOD and compression for `HOD_COMP_RS`**, now an open
row in ROADMAP section 31. Phase 6's offline rows are complete, so Phase 7's
first offline supplied-input slice is the next dependency-ready work. Its
rule-bearing branch stays gated: the `HOD_COMP_RS` definitions remain unresolved
under PLAYBOOKS section 13 and M0.3, M0.3B is still PROPOSED, and the compression
and structure definitions retained by M3.3–M3.5 are not adopted by this handoff.

No proposed rule was approved and no strategy rule was added. All switches remain
off. No provider, broker, Discord, application, deployment, restart, order,
purchase, paid fallback or Git write occurred. D-091 remains $25 authorized,
$0 used and $0 reserved.
