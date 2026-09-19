# M6.2 `CRVOL_ORB5` actionable trigger over supplied observations

Date: 2026-09-10 Pacific. Status: **completed for independent review** for the
bounded offline supplied-input slice. The separate `[!]` approved-rule gate in
ROADMAP section 31 stays open, and the tape/projection source gate stays blocked
under M3.2.

`consensus_engine/orb5_trigger.py` reports the frozen candidate boundary, the
consecutive-observation crossing test, the ten-sample acceptance window, the two
participation arms, the fresh last trade, the current eligibility and trigger
geometry, the inside-range reset and the attempt quota. It reads no clock,
fetches no data, opens no database, stores nothing and sends nothing. The caller
supplies every threshold, every observation and every mandatory result.

`ALERT_TRIGGERED` here means the supplied gates passed at one evaluation instant
in a test process. It is not an alert, an approved rule, evidence of tape or
quote coverage, or permission to act.

## 1. Why nothing is hardcoded

The M6.1 gate row says the exact `CRVOL_ORB5` thresholds come from
`M03B_ORB5_V1`, which is still PROPOSED, and that no threshold may be adopted by
inference. M6.2 keeps that rule:

- `TriggerPolicy` has no defaults. The arm, buffer floor and ATR multiple, the
  window open/close seconds, the sample count, the accepting minimum, the grid
  interval, the maximum observation age, the participation minimum, the minimum
  projection elapsed seconds, the attempts per direction and the post-action
  cooldown must all be supplied, and the policy must name its own
  `definition_reference`. Supplying a value neither adopts a proposed rule nor
  claims the referenced definition was approved.
- Participation, eligibility and geometry are supplied results
  (`TapeIntensity` / `ProjectedVolume`, the M6.1 `EligibilityAssessment` and the
  M4.3 `RiskTargetResult`). M6.2 adds no intensity producer, no projection
  producer, no stop, no target and no score.

Every number in the tests is a synthetic fixture, including the D-090 section 8
hand-worked values.

## 2. What the milestone adds

- **The pre-crossing candidate boundary.** `candidate_boundary` returns
  `buffer = max(floor, multiple * latest ATR)` and the opening-range edge moved
  outward by it, recomputed before every crossing test.
  `freeze_candidate` freezes the opening range, buffer, boundary, ATR, arm,
  anchor bar identity and attempt number at t0. `FrozenCandidate` refuses a
  boundary that is not exactly the buffered edge, so nothing can move inside an
  attempt.
- **The consecutive-observation crossing test.** `evaluate_crossing` compares the
  preceding and current price with the *same* candidate boundary. Both must come
  from the configured arm, be covered, fresh and exactly one grid interval apart.
  The first observation after a gap cannot cross, and a boundary that fell under a
  shrinking ATR onto already-beyond prices is not a fresh crossing (D-090 FX-18).
- **The ten-sample acceptance window.** At each evaluation `t`, the samples stand
  at `t-9 … t` on the supplied grid. A sample uses only an observation already
  available at its own instant, so a later arrival cannot repair it. All ten must
  be known; at least the supplied minimum must lie at or beyond the frozen
  boundary. A missing, ambiguous, stale, uncovered, wrong-arm or null sample makes
  the window `UNKNOWN`, never a shorter passing window. A burst of messages at one
  grid instant is ambiguous, not two observations.
- **The window, deadline and reset.** Before the supplied open seconds the attempt
  gate fails; from the open through the close seconds inclusive it passes; past
  the close it fails and the state becomes `ARMED/WAITING_FOR_RESET`. An
  off-grid evaluation is `UNKNOWN`, not rounded. A final one-minute close strictly
  inside the *unbuffered* opening range invalidates the attempt and satisfies the
  required reset; a close at or outside an edge does neither. A halt, lost
  coverage or an unknown mandatory input invalidates the attempt. The single
  D-090 exception is kept: while a just-ended bar still awaits its final version
  the attempt holds without moving its deadline.
- **Two separate participation arms.** `TAPE` consumes only a supplied
  `INTENSITY_15S_MEAN20_V1` ratio; `QUOTE_PROJECTED` consumes only supplied
  current-minute inputs and computes `(60/elapsed) * volume / reference` for the
  minute containing the evaluation instant, with its own reference. A previous
  minute's numerator is never carried forward, and below the supplied minimum
  elapsed seconds the arm fails while the deadline stays unchanged (FX-11,
  FX-12). Each arm carries its own D-090 variant, so one arm's evidence can never
  complete the other's, in either direction.
- **The remaining trigger gates.** The arm's fresh last trade must still stand at
  or beyond the frozen boundary, including in quote mode; the supplied M6.1
  assessment must be `ARMED` at this exact instant; and the supplied M4.3 result
  must be `READY` for this arm, direction, crossing, instant and boundary.
- **Exact arithmetic.** Every comparison uses `Fraction(str(value))`, so the
  boundary, the acceptance minimum, the participation minimum and the cooldown do
  not move on binary floating-point representation (FX-02, FX-07, FX-08, FX-09).
- **`Orb5TriggerMachine`.** One serially owned `(session, symbol, direction, arm)`
  attempt owner. It proposes canonical `StrategyStateTransition` records for the
  M4.2 engine and never advances itself: local state moves only when the caller
  calls `confirm` after storage acknowledged the transition. It holds the
  reserved attempt number, the started count, the required reset, the attempts
  per direction and the post-action cooldown, and `restore` positions an unused
  owner at explicitly recovered facts (M5.5) without inferring any of them.
  `trigger_rules()` supplies exactly the M6.2 attempt states.

Changed files: `consensus_engine/orb5_trigger.py` (new),
`tests/trade_alerts_contracts/test_orb5_trigger.py` (new).
No existing module, configuration, migration or protected launcher file changed.

## 3. Protected proof — 2026-09-10 Pacific

All runs used the unchanged protected launcher
`scripts/testing/run_trade_alerts_contracts.py` (`a4ffdd55…`, child
`85285dee…`), with zero failures, errors and skips, no unexpected isolation
denials, `pytest_exit_code` 0 and passing cleanup in every run.

The controller published three separate phases, each its own artifact set with
its own source directory. Three figures are quoted per run: pytest's own "passed
in" line from that run's `output.txt`, the JUnit `results.xml` suite `time`
attribute, and the controller's wall figure for that phase.

**The two full-selection runs.** Both ran the whole
`tests/trade_alerts_contracts` selection, each as a single run in its own fresh
process and its own published set:

- **Focused phase** (set `405af72dbbb7`, source `/tmp/trade-alerts-m04-bnmqnbgf`,
  1 run): **1,616 tests passed in 335.08 seconds** by pytest's own figure (JUnit
  335.003 s, controller wall 338.513 s), exit code 0, inside the 420-second
  limit.
- **Acceptance phase** (set `9bbf972c6493`, source
  `/tmp/trade-alerts-m04-um9nsjx9`, 1 run): the same selection — **1,616 tests
  passed in 336.01 seconds** (JUnit 335.943 s, controller wall 339.425 s), exit
  code 0, inside the same limit.

The 1,616 tests are the previously accepted 1,397 plus the **219 new M6.2 cases**
in `tests/trade_alerts_contracts/test_orb5_trigger.py`. Each run's `results.xml`
shows all 219 passing, taking 6.25 and 6.28 seconds of case time. The ordered
test IDs of the two runs are identical. Each of these two runs wrote 38 artifact
files, including `pipeline-obs.jsonl`; comparing the two sets, 35 of the 38 are
byte-identical and only `output.txt`, `results.xml` and `pipeline-obs.jsonl`
differ, in timing text and observation timestamps.

**Repeatability phase** (set `d7f67e560ce8`, source
`/tmp/trade-alerts-m04-n2vgvetx`). This is a separate, narrower selection: the
**21 recording node IDs**, **32 tests per run**, run **twice in fresh
processes**, because recording output needs a fresh-process comparison. Run 1
passed 32 tests in 107.67 seconds (JUnit 107.674 s) and run 2 in 106.05 seconds
(JUnit 106.053 s); both exit code 0, controller wall 217.462 seconds for the
phase. The two M6.2 cases in this selection took 1.71 and 1.79 seconds. Ordered
test IDs match. Each of these runs wrote **37 artifact files** and no
`pipeline-obs.jsonl`; **35 are byte-identical** and only `output.txt` and
`results.xml` differ, and only in timing text. The M6.2 recordings match exactly
across both repeatability runs and across both full-selection runs:

| Artifact | Bytes | SHA-256 |
|---|---|---|
| `m62-orb5-trigger-long-proof.json` | 5,065 | `cd9817b46006ddc1b917f3a1173a94b6c03fef548e605deba230d6fd26242e04` |
| `m62-orb5-trigger-short-proof.json` | 5,051 | `e8a8485562a97ff582c0778a46e5a52a9cbdd1723e3a377bcedc17cea3590f8b` |

Every earlier milestone recording in the same runs is unchanged, including the
M6.1 eligibility recording (`f7e25fc2…`, 3,832 bytes) and the M5.3 replay
fingerprint (`2356f8e1…`), so this addition altered no accepted output.

A single-file run of `tests/trade_alerts_contracts/test_orb5_trigger.py` alone
was made locally for convenience. It was never published, so no figure from it
is quoted here and it is no part of the proof above.

Tested milestone files: `consensus_engine/orb5_trigger.py` `eba26708…` and
`tests/trade_alerts_contracts/test_orb5_trigger.py` `d3014413…`.
`M6_2_LOCAL_CHECKS.json` records the full hashes, per-run figures and checks.

## 4. What the 219 cases cover

- The whole supplied trigger reaching `ALERT_TRIGGERED` for long and short in
  both arms, with every gate passing and no reason recorded.
- Policy validation: unsupported arm, non-numeric, negative, non-finite, boolean
  and non-integer values, a window that closes before it opens, more accepting
  samples than samples, and a first sample window that would start at or before
  the crossing.
- Record validation for observations, tape intensity, projected volume, minute
  closes, the frozen candidate, gate results and the request itself, including
  duplicate observation IDs, a foreign arm and an evaluation before the crossing.
- D-090 fixtures FX-02, FX-07, FX-08, FX-09, FX-10, FX-11, FX-12 and FX-18, with
  mirrored long and short cases.
- Crossing: a fresh crossing, an exact boundary at both sides, a repeated
  boundary value, no preceding observation, a one-second gap, a wrong arm,
  unknown coverage, an unknown or excessive age, a null price and an observation
  that was not yet available.
- Acceptance: seven of ten passing, six of ten failing, ten exactly at the
  boundary, one unusable sample of each kind, a missing grid slot, a late
  arrival, an ambiguous burst, and the other arm's grid being ignored.
- The attempt window at 5, 9, 10, 30 and 31 seconds, an off-grid instant, the
  deadline handoff to `WAITING_FOR_RESET`, the inside-range invalidation and
  reset, closes at and outside both range edges, an unavailable close, a pending
  bar holding action without moving the deadline, three lost-coverage paths, an
  unknown mandatory input and a supplied halt.
- Participation: the tape ratio at and just below the supplied minimum,
  incomplete coverage, a missing ratio, a missing result, both arm-substitution
  directions, the projected ratio at and below the minimum, the new-minute
  elapsed floor, a zero reference, a missing baseline and three minute-alignment
  errors.
- The last trade at, beyond and inside the frozen boundary, stale, and absent.
- Eligibility armed, failing, and from another instant; trigger geometry `READY`,
  `REJECTED`, `UNAVAILABLE`, absent, and mismatched by arm, direction, crossing,
  instant or boundary.
- The machine: the reserved attempt number surviving until the crossing, a
  crossing that must use it, propose without advancing, confirm only the pending
  transition, no transition when the state is unchanged, a foreign attempt,
  changed policy, backward time, the required reset, the cooldown at and below
  its supplied value, the exhausted quota, reset validation, expiry and restore
  validation.
- End to end for long and short: the M4.2 transition engine with the M4.2 SQLite
  store and an idempotent append into the M5.1 research event store, with the
  compact recording written per direction; and a refused recording leaving both
  the engine and the owner where they were.

## 5. Boundaries kept open

- [x] **M6.2 offline actionable trigger:** implemented and proved offline for
  independent review.
- [!] **M6.2 approved-rule gate:** the exact buffer, acceptance, participation,
  stale-extension, quota and cooldown values still need `M03B_ORB5_V1`, which
  remains PROPOSED. A passing supplied policy adopts no number.
- [!] **M6.2 tape and projection source gate:** `INTENSITY_15S_MEAN20_V1`,
  minute-start volume baselines, trade eligibility, corrections, sub-minute
  coverage and their 20-session references remain blocked under M3.2 and
  M0.2/M2.3. Final one-minute bars cannot supply them, and the supplied fixtures
  here establish none of them.
- [ ] Risk, targets and confidence for this strategy belong to M6.3; replay and
  synthetic scenario coverage to M6.4. Heads-up delivery, deduplication and the
  options path retain their existing owners.

## 6. Exact next milestone

**M6.3 — risk, targets and confidence for `CRVOL_ORB5`**, now an open row in
ROADMAP section 31. It composes the existing M4.3 selector and M4.4 confidence
boundary for this strategy at its frozen trigger, still on supplied inputs, and
its own rule-bearing branch stays gated by the same PROPOSED `M03B_ORB5_V1`
definition and by the M4.3/M4.4 catalog and factor gates.

No proposed rule was approved and no strategy rule was added. All switches remain
off. No provider, broker, Discord, application, deployment, restart, order,
purchase, paid fallback or Git write occurred. D-091 remains $25 authorized,
$0 used and $0 reserved.
