# M6.1 `CRVOL_ORB5` eligibility and state machine through ARMED

Date: 2026-09-10 Pacific. Status: **completed for independent review** for the
bounded offline supplied-input slice. The separate `[!]` approved-rule gate in
ROADMAP section 31 stays open.

`consensus_engine/orb5_eligibility.py` evaluates the universe, stock-in-play,
opening-range, VWAP and RVOL eligibility path and reports the state those
supplied inputs support, up to and including ARMED. It reads no clock, fetches
no data, opens no database, scores nothing, stores nothing and sends nothing.
The caller owns every threshold, every feature binding, the mandatory status
facts and the preliminary geometry result.

## 1. Why nothing is hardcoded

The M6.1 gate row says the exact ARMED thresholds and eligibility rules come
from `M03B_ORB5_V1`, which is still PROPOSED, and that no threshold may be
adopted by inference. So this module holds no number of its own:

- `EligibilityPolicy` has no defaults. Every window minute, threshold, age limit
  and confirmed-catalyst classification must be supplied, and the policy must
  name its own `definition_reference`. Supplying a value neither adopts a
  proposed rule nor claims the referenced definition was approved.
- `FeatureBinding` binds each required role to an exact feature name, producing
  version, data mode and unit, so a value can never be selected by name alone or
  served by a different definition, instrument or producer.
- `MandatoryStatus` carries the caller's supplied halt, macro-blackout and
  catalyst-coverage answers with their evidence reference. The macro blackout
  interval and the news classifier remain M0.3B work; this record defines neither.
- Preliminary risk and target geometry is the supplied M4.3 `RiskTargetResult`.
  M6.1 adds no stop, target, catalog or scoring rule.

The synthetic numbers in the tests are fixture inputs, not adopted rules.

## 2. What the milestone adds

- **A half-open evaluation window** measured from the scheduled regular open
  using the supplied start and end minutes. Before the start the state is
  `NOT_ELIGIBLE`; from the end onward it is `EXPIRED`. A day with no regular
  session stays `NOT_ELIGIBLE` with `NO_REGULAR_SESSION`.
- **Twelve reported gates.** `EVALUATION_WINDOW`, `OPENING_RANGE_READY`,
  `MIN_PRICE`, `MEDIAN_DOLLAR_VOLUME`, `OPEN5_RVOL`, `OR_WIDTH_ATR_RATIO`,
  `STOCK_IN_PLAY`, `VWAP_SIDE`, `QUOTE_ACTIONABLE`, `SPREAD_BPS`,
  `MANDATORY_STATUS` and `PRELIMINARY_RISK_TARGETS`. Each result keeps its
  status, observed value, threshold, reason code and input record IDs.
- **The state those gates support.** In-window: `SETUP_FORMING` when the opening
  range is ready and the non-live gates pass, `ARMED` when the live quote,
  status and preliminary-geometry gates also pass, otherwise `WATCHING`.
- **Three-valued logic.** `PASS`/`FAIL`/`UNKNOWN` per gate, and `TRUE`/`FALSE`/
  `UNKNOWN` for `stock_in_play`: a known true branch makes it true, no true
  branch plus an unknown branch leaves it unknown. A missing catalyst record is
  not evidence of no catalyst; the caller must supply `catalyst_coverage`
  `COMPLETE` before the catalyst branch can be false.
- **Exact boundary arithmetic.** Every comparison uses `Fraction(str(value))`, so
  the inclusive minimums, the OR width band and the basis-point spread do not
  move on binary floating-point representation.
- **Missingness that cannot pass.** An absent, ambiguous, stale, mislabeled,
  wrong-unit, not-yet-available, non-`VALID` or null feature is `UNKNOWN`, and an
  unknown mandatory gate keeps the state below the level it would otherwise
  reach. Two snapshots of one definition at the same instant are ambiguous, not
  silently preferred; a genuinely newer snapshot replaces an older one.
- **`Orb5EligibilityMachine`.** One serially owned `(session, symbol, direction)`
  owner. It proposes a canonical `StrategyStateTransition` for the M4.2 engine
  and never advances itself: local state moves only when the caller calls
  `confirm` after storage acknowledged the transition. It refuses a foreign
  scope, a changed policy, backward time, a non-pending confirmation and a
  restore on a used owner. `eligibility_rules()` supplies exactly the M6.1
  states; `ALERT_TRIGGERED` and attempt reset remain M6.2 work.

Changed files: `consensus_engine/orb5_eligibility.py` (new),
`tests/trade_alerts_contracts/test_orb5_eligibility.py` (new).
No existing module, configuration, migration or protected launcher file changed.

## 3. Protected proof — 2026-09-10 Pacific

All runs used the unchanged protected launcher
`scripts/testing/run_trade_alerts_contracts.py`
(`a4ffdd55…`, child `85285dee…`), with zero failures, errors and skips, no
unexpected isolation denials and passing cleanup in every run.

Two timing measures are quoted below: the pytest "passed in" figure from each
published `run-N/output.txt` (the JUnit `results.xml` time agrees with it to the
millisecond), and the controller's own phase wall clock, which also counts
launcher setup and artifact publication.

- **Focused stage (published 05:18:49 Pacific,
  `published-artifacts-1d47d8eb3802`):** the selection was the whole
  `tests/trade_alerts_contracts` directory — **1,397 tests passed in 321.49
  seconds** (JUnit 321.435 s; controller wall 324.632 s), one fresh process,
  inside the 420-second limit. Inside that run's `results.xml`, the 143 cases in
  `tests/trade_alerts_contracts/test_orb5_eligibility.py` all passed and take
  15.27 seconds of case time. A standalone single-file run of that test file was
  builder-local only; it has no published artifact set and is not part of this
  proof.
- **Broad acceptance stage (`published-artifacts-98dae56ac548`, run between the
  focused and repeatability stages):** the same
  `tests/trade_alerts_contracts` selection — **1,397 tests passed in 319.15
  seconds** (JUnit 319.089 s; controller wall 322.335 s), a second fresh process,
  inside the 420-second limit. Its `results.xml` again shows the same 143 M6.1
  cases passing.
- **Repeatability stage (published 05:27:42 Pacific,
  `published-artifacts-fa444cd142e2`):** a different, narrower selection — the
  **20 recording node IDs** across the contract suites, **30 tests per run**, run
  **twice in fresh processes**, passing in **102.80 and 102.88 seconds** (JUnit
  102.802 s and 102.878 s; controller wall 209.332 s for the phase), exit code 0
  both times. Each of those two runs wrote 35 artifacts, 33 of them
  byte-identical, with only `output.txt` and `results.xml` differing in timing
  text.

The two full-directory runs above wrote 36 artifacts each. **33 are
byte-identical**; only `output.txt`, `results.xml` and `pipeline-obs.jsonl`
differ, and only in timing text and observation timestamps. The M6.1 recordings
match exactly across all four published runs:

| Artifact | Bytes | SHA-256 |
|---|---|---|
| `m61-orb5-eligibility-long-proof.json` | 3,832 | `f7e25fc26612925f918eb1c2ebd1f499c09e6d190121a8758f4aeeeb0f19ceab` |
| `m61-orb5-eligibility-short-proof.json` | 3,826 | `d0e4cd03bf088d497110393cac1aca087a5134a8becf06bda154cdebde1141d6` |

Every earlier milestone recording in the same runs is also unchanged, including
the M5.3 replay fingerprint, so this addition altered no accepted output.

The tested milestone files are `consensus_engine/orb5_eligibility.py`
`2ca34145…` and `tests/trade_alerts_contracts/test_orb5_eligibility.py`
`907a3a46…`. `M6_1_LOCAL_CHECKS.json` records the full hashes, per-run figures
and checks.

## 4. What the 143 cases cover

- The supplied path to `ARMED` for long and short, with every gate passing.
- Both edges of the half-open window at second resolution, and a window that
  moves only because the supplied minutes changed.
- Every three-valued `stock_in_play` combination: catalyst, premarket plus gap,
  opening participation, a known-false result under complete catalyst coverage,
  and each unknown branch, including an unclassified or `UNKNOWN`-classified
  catalyst.
- Each of the eight bound roles missing, absent, mislabeled by version, mode,
  instrument, quality, source time or unit, plus ambiguity and staleness.
- Inclusive numeric boundaries: minimum price, median dollar volume, the OR
  width band at both ends, and the spread in basis points.
- The quote path: stale trade, stale quote, delayed or unknown feed, one-sided,
  non-positive, crossed and entirely absent quote decisions.
- Halted, unknown halt, macro blackout, unknown blackout and a status that is not
  yet available.
- Preliminary geometry `READY`, `REJECTED` and `UNAVAILABLE`, plus a mismatched
  direction and a stale instant.
- Machine behavior: propose without advancing, confirm only the pending
  transition, no transition when the state is unchanged, foreign scope, changed
  policy, backward time, restore rules and construction validation.
- Shared features end to end for long and short: supplied Bars through the real
  M3.1 core price, M3.6 opening range and M3.2 participation producers, then the
  M4.3 selector, the M4.2 transition engine with the M4.2 SQLite store and an
  idempotent append into the M5.1 research event store, with the compact
  recording written per direction.
- A refused recording leaves both the engine and the machine below `ARMED`.

## 5. Boundaries kept open

- [x] **M6.1 offline eligibility and state machine:** implemented and proved
  offline for independent review.
- [!] **M6.1 approved-rule gate:** the exact ARMED thresholds and eligibility
  rules still need `M03B_ORB5_V1`, which remains PROPOSED, and section 10 keeps
  the shared prior-session bar-profile and swing/AVWAP producer with M3.5/M4.3.
  A passing supplied policy does not adopt any number.
- [!] Actual source coverage, trade eligibility, finality, corrections, halt and
  macro classification feeds remain blocked under M0.2/M2.3/M3.x. Supplied
  synthetic records establish none of them.
- [ ] The crossing, buffer, acceptance window, tape and projected-quote
  participation, stale-extension logic and attempt quota belong to M6.2; risk,
  targets and confidence for this strategy belong to M6.3; replay and synthetic
  scenario coverage to M6.4.

`ARMED` here means the supplied gates passed at one instant. It is not a trigger,
an alert, evidence of provider coverage or permission to act.

## 6. Exact next milestone

**M6.2 — actionable trigger for `CRVOL_ORB5`**, now an open row in ROADMAP
section 31, bounded to the offline supplied-input slice of D-090 sections 4–5:
the frozen candidate boundary and buffer, the consecutive-observation crossing
test, the ten-sample acceptance window from t0+10 through t0+30, the tape and
projected-quote arms kept separate, the inside-OR reset and the attempt quota.
Its own rule-bearing branch stays gated by the same PROPOSED `M03B_ORB5_V1`
definition, and the tape/projection source coverage stays blocked under M3.2.

No proposed rule was approved and no strategy rule was added. All switches remain
off. No provider, broker, Discord, application, deployment, restart, order,
purchase, paid fallback or Git write occurred. D-091 remains $25 authorized,
$0 used and $0 reserved.
