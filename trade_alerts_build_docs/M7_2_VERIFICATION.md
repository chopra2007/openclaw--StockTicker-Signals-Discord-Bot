# M7.2 RS and trend eligibility for `HOD_COMP_RS`

Date: 2026-09-11 Pacific. Status: **completed for independent review** for the
bounded offline supplied-input slice. The separate `[!]` definition gate and the
`[!]` source gate in ROADMAP section 31 stay open. PLAYBOOKS section 13 still
owns the unresolved `HOD_COMP_RS` questions, M0.3B is PROPOSED, and M3.3-M3.5
keep the compression and structure definitions.

`consensus_engine/rs_trend_eligibility.py` adds two things. It measures one
relative-strength value from two supplied canonical minute batches, and it
evaluates the `HOD_COMP_RS` eligibility path through ARMED from that value, the
M7.1 frozen reference and compression window, and the caller's own thresholds.
`tests/trade_alerts_contracts/test_rs_trend_eligibility.py` covers both paths.

ARMED is a reported state over supplied inputs at one instant. It is not a
trigger, an arming decision, an approved rule, evidence of provider coverage or
permission to act.

## 1. Why nothing is hardcoded

PLAYBOOKS section 13 lists the open `HOD_COMP_RS` questions by name: the RS15
warm-up before 15 regular-session minutes, the compression and distance numbers,
acceptance duration and tape fallback. M7.2 answers none of them.

- Every threshold arrives on `RsTrendPolicy` with the caller's own version and
  definition reference: the minimum price, dollar volume, relative volume, the
  open-move floor and its volatility part, the RS floor and its volatility part,
  the spread limit and every age limit. The module compares supplied numbers; it
  carries none.
- The lookback is the caller's too. `RsWindowPolicy` carries the bar count, the
  benchmark symbol and which price starts the return, so the open basis question
  stays open. A test measures the same bars under both supplied bases and gets
  two different returns.
- The warm-up answer is not decided here. Before the supplied number of session
  minutes has elapsed, `RS_WARMUP_COMPLETE_V1` is 0 and both returns stay
  unavailable with a named reason. The lookback never shortens itself, because
  which shorter window would be acceptable is exactly the open question.
- A test asserts the module source carries none of the playbook's numbers.

Every number in the tests is a synthetic fixture.

## 2. What the milestone adds

- **One relative-strength measurement.** `build_rs_trend_snapshot` reports the
  stock return and the benchmark return over the last completed regular-session
  minutes the supplied lookback asks for, their difference, the supplied bar
  count and the warm-up flag. Returns are exact decimal ratios, never float
  arithmetic. The benchmark must be a different explicit symbol.
- **Separate fates.** The two returns are measured independently, so a broken
  benchmark still reports a complete stock return and names its own side with a
  `BENCHMARK_` reason. The difference names the first input it lacks.
- **Named refusals, never a substitute value.** A missing, provisional,
  conflicting, low-quality, untraded, non-contiguous, short or unexpectedly
  overlapping lookback keeps its own value `None` with a reason and its inspected
  record IDs. Nothing is defaulted, interpolated or carried over.
- **One immutable `FeatureSnapshot`** under `M72_RS_TREND_V1` and data mode
  `SUPPLIED_BAR_RS_TREND`, so a consumer must bind these values by full identity.
- **The eligibility path.** `evaluate_rs_trend_eligibility` reports thirteen
  gates: the evaluation window, the M7.1 reference and compression flags, the
  minimum price, dollar volume, relative volume, the open move, the RS warm-up,
  the RS trend, the VWAP side, the quote and spread, and the mandatory halt and
  macro facts. Six of them support SETUP_FORMING and all twelve support ARMED.
- **Three-valued inputs.** A missing, stale, ambiguous, wrongly united or
  wrongly identified feature leaves its gate UNKNOWN, which keeps the machine
  below the state it would otherwise reach. UNKNOWN never passes.
- **Both directions.** The trend gate mirrors for a short: the same supplied
  strength against the benchmark is required with the opposite sign, and the
  VWAP side flips with it.
- **`HodCompRsEligibilityMachine`** proposes canonical transitions for the M4.2
  engine and the M5.1 store and advances only after the caller confirms a
  recorded transition. It never writes, sends or advances itself.
- **Reuse.** The halt and macro-blackout record is the strategy-neutral M6.1
  `MandatoryStatus`; the transition rules, strategy context and canonical records
  are the existing M5.3/M4.1/M1.x ones. No existing file changed.

## 3. What the new cases cover

- The measurement: the two returns and their difference, the supplied bar count
  and record IDs, both supplied return bases, the warm-up refusal and the first
  instant that clears it, a history shorter than the lookback, a missing,
  provisional, untraded, foreign-instrument or unexpectedly overlapping minute,
  a broken benchmark beside a complete stock return, absent, foreign-symbol,
  daily-interval, wrong-unit and unknown-basis history, and a closed day.
- Supplied contracts: the lookback and the policy must be explicit and coherent
  and are immutable, every role must be bound exactly once by full identity, and
  public scope is checked before any measurement.
- The path through ARMED in both directions, the half-open evaluation window at
  all four edges, and a window that moves with the supplied minutes.
- The M7.1 flags and the warm-up flag: unset fails its own gate by name, a
  non-boolean value is UNKNOWN rather than read as true, and an unmeasured RS
  keeps the trend gate UNKNOWN.
- Missing, absent, stale, ambiguous, wrongly united and wrongly identified
  inputs, one per bound role, and a newer snapshot replacing an older one.
- Numeric boundaries: dollar volume, relative volume, minimum price, the spread
  in basis points, and both floor-and-volatility minimums on each side of their
  own boundary, including the short mirror and an unavailable daily ATR that
  leaves both composite gates UNKNOWN.
- Quote and status gates, the machine's propose/confirm/restore contract, a
  foreign evaluation, a changed policy, backward time, and a refused recording
  that leaves both the engine and the machine below ARMED.
- The real M7.1 and M7.2 producers over one supplied synthetic session, carried
  through the M4.2 engine and the M5.1 store in both directions, with one
  deterministic recording, `m7_2_rs_trend_proof.json`, holding the bar hash, the
  measured feature values, the assessment, the transition and the stored
  position and fingerprint for each direction.

## 4. Boundaries kept open

- [x] **M7.2 offline RS and trend eligibility:** implemented and proved offline
  for independent review.
- [!] **M7.2 definition gate:** the RS15 lookback, its warm-up answer, the return
  basis, the trend thresholds and every eligibility cutoff stay unresolved under
  PLAYBOOKS section 13 and M0.3, and M0.3B is still PROPOSED. A supplied policy
  adopts none of them.
- [!] **M7.2 source and historical-data gate:** every bar and benchmark minute
  here is a synthetic supplied record, and no actual benchmark instrument,
  reference-market coverage or point-in-time minute coverage, finality,
  correction or adjustment history is proved. Those remain blocked under M0.2,
  M2.3, M2.4, M3.1, M3.2 and M3.6. Nothing here measures profit or edge.
- [ ] The heads-up and actionable path, risk, confidence and suppression, and the
  replay and synthetic scenarios for this strategy keep their M7.3-M7.5 owners.
  Candidate assembly and delivery keep their M4.5/M4.6/M4.7 owners.

## 5. Protected proof

The controller's published protected stage supplies every count, timing, hash and
byte figure for this milestone; those numbers are not written here from any
builder-local run. The required selection is the whole
`tests/trade_alerts_contracts` directory, because the new module imports the
shared M1.x records, the M2.2 history, the M4.1 strategy context, the M5.3
transition rules and the M6.1 status record that the rest of the directory also
exercises, and because the launcher installs its isolation for the whole
collection.

This milestone states a repeatability need: `m7_2_rs_trend_proof.json` is a
recorded artifact, so the recording selection must be compared between two fresh
processes in addition to the acceptance run. Every earlier milestone recording in
the same runs must stay unchanged, including the M3.6 opening-range recording,
the M6.1 eligibility recordings, the M6.4 scenario artifact and the M7.1
compression recording.

Tested milestone files: `consensus_engine/rs_trend_eligibility.py`
`6a53d814ab1df107dc95bb389e7d2b4a9472f29328f8e531afbd7a4003e55f29` and
`tests/trade_alerts_contracts/test_rs_trend_eligibility.py`
`5eb17db2de870a4c936bf586e65196fb6a3bfe9c099f98ea1dc18de66d506f1b`.
`M7_2_LOCAL_CHECKS.json` records the inspected hashes and the local checks that
are not proof.

## 6. Exact next milestone

**M7.3 — heads-up and actionable path for `HOD_COMP_RS`**, now an open row in
ROADMAP section 31. M7.2's ARMED state and measured inputs are its direct
inputs, so it is the next dependency-ready work. Its rule-bearing branch stays
gated for the same reasons recorded above.

No proposed rule was approved and no strategy rule was added. All switches remain
off. No provider, broker, Discord, application, deployment, restart, order,
purchase, paid fallback or Git write occurred. D-091 remains $25 authorized,
$0 used and $0 reserved.
