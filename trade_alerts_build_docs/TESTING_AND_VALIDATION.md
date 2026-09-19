# TESTING_AND_VALIDATION.md

## 1. Purpose

This document is the canonical specification for testing, historical replay, backtesting, forward validation, statistical evaluation, strategy promotion, regression protection, and ongoing evidence standards for the intraday human-in-the-loop trading alert system.

It defines:
- unit tests;
- integration tests;
- synthetic strategy scenarios;
- deterministic historical replay;
- look-ahead-bias protections;
- execution modeling;
- data-quality validation;
- alert validation;
- MFE/MAE and R-based metrics;
- false-positive analysis;
- reaction-delay analysis;
- walk-forward testing;
- parameter robustness;
- ablation;
- confidence calibration;
- human-discretion analysis;
- options-layer validation;
- shadow validation;
- portfolio-level evaluation;
- promotion/rejection standards;
- continuous health validation.

Implementation success is not evidence of trading edge.

## 2. Validation Philosophy

Primary question:

```text
Does this strategy appear to have
repeatable,
forward-usable,
human-executable
positive expected value
after realistic delays,
spreads,
slippage,
regime variation,
and parameter uncertainty?
```

No strategy is presumed profitable.

Possible final states include:
- ACTIVE
- PROVISIONAL
- SHADOW
- MODIFY
- DEGRADED
- DISABLED
- REJECTED
- INSUFFICIENT_DATA

## 3. Evidence Stages

Use precise stage labels:
- IMPLEMENTED
- UNIT_TESTED
- REPLAYABLE
- HISTORICALLY_TESTED
- WALK_FORWARD_TESTED
- SHADOW_TESTED
- PROVISIONAL
- ACTIVE
- MODIFY
- REJECTED
- INSUFFICIENT_DATA

Do not use `VALIDATED` as an undefined catch-all.

## 4. Testing Layers

```text
UNIT TESTS
    ↓
SYNTHETIC STRATEGY TESTS
    ↓
INTEGRATION TESTS
    ↓
REPLAY REGRESSION TESTS
    ↓
HISTORICAL STRATEGY EVALUATION
    ↓
WALK-FORWARD
    ↓
LIVE SHADOW
    ↓
PROVISIONAL / ACTIVE
    ↓
CONTINUOUS HEALTH MONITORING
```

No later stage eliminates the need for earlier stages.

### 4.1 Protected test frequency for future build work

Use staged testing for future milestones and repairs:

1. Run the exact failing cases and directly affected protected checks first.
2. If a focused check fails, stop. Save the exact error and test IDs for repair.
3. After focused checks pass, run a broader protected acceptance selection based
   on changed files, callers, stored data, interfaces, and dependencies.
4. Record why that broader selection covers the risk. If impact is unknown, use
   the broad safe selection.
5. A builder's selector list may add coverage but cannot remove controller- or
   reviewer-required checks.

Run the broader acceptance selection once unless repeatability is part of the
claim. Use two fresh processes and compare required artifacts for deterministic
recordings, reopen/retry behavior, recovery, ordering, idempotence, or another
recorded repeatability reason. Keep isolation, source identity, zero
failures/errors/skips, cleanup, and independent-review rules unchanged.

Code, test, configuration, dependency, and protected-input changes invalidate
affected proof. Records-only finalization may reuse matching published proof when
the tested hashes and complete milestone delta still agree. Do not rerun product
tests only to correct prose, copied counts, or structured record formatting.

This section governs future test planning. Later sections preserve exact dated
milestone evidence and required reruns after specific historical repairs. Their
recorded two-run results remain valid proof; they do not create an automatic
two-broad-run rule for every future change.

## 5. Unit Testing

Every deterministic shared calculation should have focused tests.

At minimum:
- session/calendar logic
- VWAP
- ATR
- RVOL
- premarket RVOL
- gap % / gap ATR
- HOD/LOD
- opening range
- relative strength
- VWAP slope / cross count
- compression ratio
- retracement
- drive efficiency
- spread calculations
- R calculations
- target calculations
- confidence aggregation
- OptionScore
- profile calculations

Tests should cover normal, boundary, zero/empty, missing, invalid, warm-up, and long/short symmetry where relevant.

Use hand-calculated fixtures where practical rather than comparing two implementations of the same logic.

## 6. Market Session Tests

Test:
- normal trading day
- premarket
- regular open
- regular close
- after-hours
- weekend
- holiday
- early close
- DST transition
- conversion between stored absolute instants and Pacific display

No strategy may depend on local-machine timezone assumptions.

## 7. Point-in-Time Feature Tests

Every historical feature must prove it uses only information available at that moment.

Examples:
- HOD at 06:45 = max high from session open through 06:45, never final HOD.
- RVOL cannot use final current-day volume.
- VWAP at T uses only price/volume through T.
- current-session profile uses only current-session data through T.
- prior-session profile may be fully frozen before the next session.

## 8. Synthetic Strategy Tests

Every strategy should test:
- clean qualifying setup
- near miss
- mandatory filter failure
- stale setup
- insufficient R:R
- wide spread
- missing mandatory data
- optional data missing
- long
- short
- expiry
- invalidation
- cooldown
- duplicate suppression

### `CRVOL_ORB5`
- clean high-RVOL ORB
- low-RVOL breakout
- wick/no acceptance
- accepted breakout
- breakout into resistance
- extremely wide OR
- aligned/opposed market
- short ORB
- stale breakout

### `HOD_COMP_RS`
- clean HOD compression
- generic HOD break without compression
- weak/strong RS
- dead-volume drift
- exhaustion
- valid retest
- failed break
- short LOD compression

### `OR_FAILURE_REV`
- meaningful breakout then failure
- one-tick excursion
- successful breakout retest
- rapid/late failure
- failure then rebreak
- major catalyst continuation
- two-sided OR chop

### `FIRST_PULLBACK_VWAP`
- strong impulse + clean first pullback
- deep retracement
- high-volume opposing pullback
- VWAP hold
- VWAP loss/reclaim
- multiple VWAP crosses
- second pullback
- short setup

### `INDEX_OPEN_DRIVE_BREADTH`
- broad QQQ/SPY drive
- narrow leadership
- breadth deterioration
- price strong + breadth weak
- sector proxy mode
- full-breadth fixture
- VWAP failure
- macro suppression

### `GAP_FADE_FAILED_OPEN`
- technical gap-up failure
- major catalyst continuation
- gap-down equivalent
- failed extension
- loss of open
- failed reclaim
- temporary dip
- gap already mostly filled
- sector-supported gap
- UNKNOWN catalyst

### `CAT_FIRST_CONSOL`
- clean hard catalyst
- clean first consolidation
- deep consolidation
- mixed earnings/guidance
- catalyst arrives late
- catalyst unknown
- gap immediately fades
- second consolidation
- climactic pre-consolidation move

### `VP_ACCEPT_LVN`
- clean prior VAH acceptance
- false VAH breakout
- stable/unstable LVN
- LVN traversal
- LVN rejection
- current-session refill
- approximate profile
- true-profile fixture

## 9. State-Machine Tests

For each state:
- valid entry transition
- valid exit transition
- invalid transition
- reset
- expiry
- invalidation

Impossible shortcuts should be rejected where appropriate.

## 10. Integration Tests

Verify boundaries among:
- data adapter
- canonical market model
- feature engine
- context
- strategy
- risk/target engine
- confidence
- options
- portfolio orchestrator
- storage
- Discord renderer

Minimum flows:

```text
market data → features → state transition → heads-up
```

and:

```text
market data → actionable → stop/targets → confidence → options → dedup → persistence → rendering
```

Failure integration cases:
- stale quote
- missing option chain
- database write failure
- Discord failure
- feed reconnect
- missing breadth
- missing catalyst

## 11. Historical Replay

Live and historical logic should use the same or substantially identical runtime.

Replay consumes events chronologically.

Given identical input dataset, strategy version, config version, and feature-engine version, output state transitions, alerts, and suppressions should be identical.

Every replay records:
- dataset ID
- date range
- symbols
- strategy versions
- config hashes
- code/git revision where available
- execution model
- timestamp

## 12. Replay Regression Testing

Maintain deterministic fixtures that assert:
- event counts
- ordered state transitions
- alert IDs/fingerprints
- trigger levels
- stop levels
- target levels

Non-semantic refactors should not change expected outputs.

Intentional semantic changes require new strategy/config version and updated expected fixture.

## 13. Look-Ahead Bias Protection

Forbidden future information:
- final daily volume
- future HOD/LOD
- future VWAP
- future profile
- later revised news
- future earnings metadata
- future option quote/spread
- future index membership
- future market-regime label

News must distinguish event timestamp from received timestamp.

For Strategy #5, current-membership backtests must be labeled biased/provisional if point-in-time membership is unavailable.

For Strategy #8, prior-session profile is allowed; current-day final profile is not.

## 14. Survivorship / Selection / Data-Snooping Bias

Where possible broad-universe research should include delisted, renamed, merged, and failed companies.

If unavailable, disclose survivorship limitations.

Persist all mechanically qualifying alerts needed for analysis. Do not evaluate only traded, delivered, winning, or high-confidence alerts unless explicitly analyzing that subset.

Where feasible persist meaningful candidates suppressed by filters so ablation can test whether suppression helped.

## 15. Outcome Model

For each actionable alert calculate:
- MFE
- MAE
- maximum R
- T1 hit
- T2 hit
- stop hit
- time to T1/T2/stop

Long:

```text
MFE_R = (max_future_price - entry_price) / R
MAE_R = (entry_price - min_future_price) / R
```

Short symmetric.

Outcome horizon must be strategy-specific and explicit. Do not let winners run indefinitely while cutting losers at expiry.

## 16. Same-Bar Ambiguity

With 1m bars, if high >= target and low <= stop, ordering is unknown.

Allowed handling:
- UNKNOWN
- STOP_FIRST_CONSERVATIVE
- higher-resolution data

Default should be conservative. Never assume target-first.

## 17. Execution Models

### Idealized trigger
Measures theoretical signal quality only. Label `IDEALIZED`.

### Human reaction delay
Required where possible:
- 0s
- 5s
- 15s
- 30s
- 60s

Conceptual manual-fit labels:
- EXCELLENT: 30–60s survives
- GOOD: 15–30s survives
- MARGINAL: 5–15s
- POOR: requires <5s
- UNSUITABLE: ultra-low-latency

These labels are provisional and should be derived from results.

### Spread / slippage
Use historical bid/ask where available. Without it, run low/base/high conservative sensitivity models and disclose the limitation.

A credible edge should not depend entirely on zero spread, zero delay, zero slippage, and perfect fills.

## 18. Primary Strategy Metrics

Report:
- actionable alerts
- trading sessions
- symbols
- long/short counts
- win/loss/scratch
- average/median winner R
- average/median loser R
- expectancy R
- profit factor
- average/median MFE R
- average/median MAE R
- T1/T2/stop rates
- median time to target/stop
- max losing streak
- drawdown R

Expectancy in R is primary.

## 19. Expectancy / Profit Factor

Basic expectancy:

```text
expectancy_R = win_probability * average_win_R - loss_probability * average_loss_R
```

Or directly use mean modelled/realized R when partial/scratch outcomes require it.

Profit factor:

```text
PF = gross_positive_R / abs(gross_negative_R)
```

No metric should be used alone.

## 20. Precision / False Positives

True recall is usually undefined because the full universe of true opportunities is not independently labeled.

Possible favorable threshold:

```text
MFE >= 1R before structural stop
```

Then:

```text
precision_proxy = favorable_alerts / actionable_alerts
```

Do not claim true recall until an independently labeled opportunity set exists.

## 21. Heads-Up Validation

Track:
- heads-up count
- heads-up→actionable conversion
- median lead time
- false/expired heads-ups
- notification burden

Heads-up alerts should provide useful preparation time without excessive noise.

## 22. Statistical Uncertainty

Where sample permits calculate:
- win-rate confidence intervals
- bootstrap expectancy interval
- bootstrap average-R interval
- probability expectancy > 0 where appropriate

Consider session/block bootstrap to preserve within-day dependence.

## 23. Sample-Size Discipline

Initial evidence labels:
- <30 alerts: VERY LOW
- 30–99: LOW
- 100–299: MODERATE
- 300+: STRONGER BASIS

Also evaluate independent days, symbols, regimes, directions, and correlation.

## 24. Time-Split / OOS

Evaluate chronologically. Separate `IN_SAMPLE` from `OUT_OF_SAMPLE`.

Primary strategy decisions emphasize OOS and live shadow evidence.

## 25. Walk-Forward Validation

```text
TRAIN WINDOW
→ choose reasonable parameter region
→ LOCK PARAMETERS
→ FUTURE TEST WINDOW
→ ROLL FORWARD
```

Record train/test periods, chosen config, train/test expectancy, sample, and drawdown for each fold.

## 26. Parameter Robustness

Test structurally justified neighboring values, not huge grids.

Example RVOL around 2.0:
- 1.50
- 1.75
- 2.00
- 2.25
- 2.50

Flag `PARAMETER FRAGILITY` if small changes flip performance without structural explanation.

Prefer stable plateaus over a single historical optimum.

## 27. Multiple Testing

Each additional search increases overfitting risk.

Keep parameter grids small, document variants, separate exploratory vs confirmatory analysis, and validate proposed improvements on held-out/future data.

## 28. Ablation Testing

Ablation is mandatory for important filters.

Compare base strategy with base + filter.

Report:
- alerts before/after
- removed alerts
- Δ expectancy
- Δ profit factor
- Δ win rate
- Δ MFE/MAE
- Δ drawdown

Labels:
- KEEP
- OPTIONAL
- REMOVE
- HARMFUL
- INSUFFICIENT_DATA

Key ablations:
- RVOL
- VWAP
- relative strength
- market/sector
- breadth
- acceptance
- volume acceleration
- catalyst
- Level 2
- AVWAP
- profile context

## 29. Human Discretion Validation

Compare:
- ALL MECHANICAL ALERTS
- HUMAN ACCEPTED
- HUMAN REJECTED
- NO DECISION

Report count, expectancy, PF, win rate, MFE, MAE, max R.

Analyze rejection reasons such as poor tape, resistance too close, market/sector conflict, exhaustion, catalyst uncertainty, poor options, too late.

Human-selection analysis is observational; do not automatically claim causality.

## 30. Confidence Calibration

Initial buckets:
- 0–59
- 60–69
- 70–79
- 80–89
- 90–100

Or use quantiles if distribution is concentrated.

Report count, expectancy, win rate, MFE/MAE, PF by bucket.

Higher confidence should ideally rank better outcomes. If not, recalibrate rather than assume the score is meaningful.

## 31. Factor Importance

Use interpretable methods first:
- bucket comparisons
- correlations
- simple regression
- conditional expectancy tables

Avoid opaque ML until simpler analysis is exhausted.

## 32. Regime Analysis

Segment by:
- SPY/QQQ up/down/flat
- realized volatility
- VIX
- trend/rotational day
- gap day
- macro-event day
- high-RVOL environment
- time of day
- long/short
- liquidity/market cap/sector
- catalyst class

Classify:
- REGIME ROBUST
- REGIME SPECIFIC BUT IDENTIFIABLE
- UNSTABLE
- INSUFFICIENT_DATA

A regime-specific edge is acceptable if the regime is identifiable point-in-time.

## 33. Options-Layer Validation

First ask whether the underlying setup has edge. Then ask whether the options layer provides acceptable execution.

Where supported track:
- OptionScore
- spread
- delta
- DTE
- IV
- option MFE/MAE
- executable return
- slippage

Initial OptionScore buckets:
- <65
- 65–74
- 75–84
- 85+

Without historical options data, underlying validation is allowed; historical option-performance claims are not.

## 34. Strategy-Specific Critical Experiments

### `CRVOL_ORB5`
Generic 5m ORB vs ORB + stock-in-play/RVOL. Ablate RVOL, catalyst, VWAP, acceptance, RS, sector, market.

### `HOD_COMP_RS`
Generic HOD vs HOD + compression, then +RS, +volume contraction, +acceptance.

### `OR_FAILURE_REV`
Fade any OR excursion vs confirmed OR failure. Test failure speed, 1m close, inside acceptance, market divergence, catalyst filter.

### `FIRST_PULLBACK_VWAP`
Generic first pullback vs VWAP-aligned, then volume contraction, RS, AVWAP.

### `INDEX_OPEN_DRIVE_BREADTH`
Drive only vs sector proxy vs full breadth. Ablate advance ratio, above-VWAP ratio, volume breadth, sector breadth, VIX, SPY/QQQ mutual confirmation.

### `GAP_FADE_FAILED_OPEN`
Fade all gaps vs failed-extension only vs +VWAP loss vs +failed reclaim. Segment by catalyst, gap ATR, gap %, premarket volume.

### `CAT_FIRST_CONSOL`
Catalyst direction only vs +impulse vs +first consolidation. Ablate volume contraction, VWAP, acceptance, RS; segment by catalyst type.

### `VP_ACCEPT_LVN`
Highest falsification standard. Mandatory matched comparison:
- accepted VAH breakout + adjacent LVN
- accepted VAH breakout without adjacent LVN

Match RVOL, ATR, time, market, sector, liquidity, gap, and break strength. If LVN adds no value, reject/downgrade #8.

## 35. Failure-Cluster / New-Filter Protocol

Losing-alert patterns are observations, not automatic new filters.

```text
OBSERVATION
→ HYPOTHESIS
→ HELD-OUT / FUTURE TEST
→ CHALLENGER VERSION
```

Never discover a losing subgroup, delete it from the same history, and call the improved curve validated.

## 36. Strategy Modification Protocol

For proposed changes document:
- current rule
- observed problem
- evidence
- proposed change
- expected effect
- overfitting risk
- whether new version required
- whether forward test required

Material changes require new strategy/config version.

## 37. Promotion / Rejection

No single numeric gate guarantees promotion.

`ACTIVE` should require credible:
- data integrity
- positive OOS/forward expectancy
- realistic costs
- reaction-delay robustness
- parameter stability
- regime understanding
- acceptable drawdown
- shadow/live consistency

`PROVISIONAL` is appropriate when evidence is encouraging but incomplete.

Consider `REJECTED` when OOS expectancy is non-positive after realistic costs and no robust ex-ante subgroup demonstrates credible edge.

Other rejection reasons: manual reaction impossible, data cost unjustified, redundancy, parameter fragility, unsupported structural thesis.

## 38. Shadow Validation

Shadow must use the same live inputs/runtime as production.

Record:
- candidate
- trigger
- stop
- targets
- confidence
- data mode
- latency
- option snapshot
- outcome

Compare historical vs shadow frequency, expectancy, MFE/MAE, and reaction decay.

Poor data-quality shadow periods do not count as valid forward evidence.

## 39. Portfolio Overlap

Calculate pairwise same-symbol/same-direction overlap within 1m and 5m plus outcome correlation.

Possible decisions:
- KEEP INDEPENDENT
- MERGE
- CONFLUENCE ONLY
- SUBTYPE
- REVIEW REDUNDANCY

Identify correlated market-event clusters rather than treating them as independent observations.

## 40. Regression Testing

Every meaningful bug fix should add a regression test where possible, including:
- future HOD leak
- duplicate alerts
- wrong OR boundary
- gap-sign bug
- DST issue
- same-bar ordering
- incorrect option spread

Non-semantic refactors should not change strategy replay output unexpectedly.

## 41. Data-Quality Reports

Before major backtests report:
- date coverage
- symbols
- missing sessions/minutes
- duplicate/out-of-order bars
- invalid prices/volume
- premarket availability
- corporate-action anomalies
- quote gaps
- breadth/catalyst/profile quality where relevant

## 42. Reproducible Research

Every report should include:
- strategy version
- config hash
- dataset
- date range
- universe
- execution model
- reaction delay
- costs
- data limitations

Use precise evidence language. Do not claim “the strategy wins” without definitions and context.

## 43. Continuous Validation

After promotion monitor rolling:
- last 20/50/100 alerts
- last 5/20/60 trading days
- rolling 3m/6m/lifetime

Track expectancy, PF, MFE, MAE, alert frequency, reaction decay, confidence calibration, execution quality, data integrity, human decision drift, and option quality.

Distinguish signal degradation, execution degradation, data issues, and regime scarcity.

Use champion/challenger for material changes. No live auto-tuning.

## 44. Definition of Done — Shared Platform

```text
[ ] Unit tests exist for shared features.
[ ] Synthetic state tests exist.
[ ] Integration tests exist.
[ ] Replay is deterministic.
[ ] Look-ahead protections are tested.
[ ] Outcome evaluator is deterministic.
[ ] Same-bar ambiguity handled.
[ ] Reaction-delay analysis exists.
[ ] Cost model exists.
[ ] Walk-forward exists.
[ ] Parameter sensitivity exists.
[ ] Ablation exists.
[ ] Confidence calibration exists.
[ ] Human decision analysis exists.
[ ] Strategy overlap analysis exists.
[ ] Data-quality reports exist.
[ ] Shadow results can be analyzed.
```

## 45. Definition of Done — Individual Strategy

```text
[ ] Strategy implementation tests pass.
[ ] Replay works.
[ ] Historical data integrity is understood.
[ ] Sample statistics calculated.
[ ] MFE/MAE calculated.
[ ] Reaction-delay analysis completed.
[ ] Major filters ablated.
[ ] Long/short analyzed separately.
[ ] Regime analysis performed where sample permits.
[ ] Parameter robustness examined.
[ ] OOS/walk-forward evidence available.
[ ] Shadow evidence collected where feasible.
[ ] Options analysis separated from underlying.
[ ] Known data limitations documented.
[ ] Promotion/rejection decision recorded.
```

## 46. Final Validation Principle

The validation system exists to answer four independent questions:

```text
1. Does the mechanical setup itself contain edge?
2. Do context filters improve that edge?
3. Does human discretionary filtering add further value?
4. Can the edge actually be expressed through stock/options after realistic execution constraints?
```

The project succeeds if it can determine with evidence that a strategy should be promoted, modified, left in shadow, disabled, or rejected without changing rules merely to improve historical results.

## 47. Prebuild evidence limits and offline proof

PREBUILD_REVIEW distinguishes inspected code, inspected test sources, freshly executed offline tests, and unverified live behavior. The review did not test a broker account, send Discord messages, change application code or run deployment commands. Documentation checks do not validate the proposed strategies.

Before reusing an implementation, freeze adapter contracts in M0.4. Offline tests must use a temporary database, fake providers, a fixed clock, a recording sink, and explicit failures on network/credential access. Prove that the existing test configuration does not silently force the new enabled path off. The full suite and exact failing-test-ID comparison are implementation/release gates; documentation-only edits use the lighter checks in `docs/agents/WORKFLOWS.md`.

## 48. Required adversarial acceptance cases

| Test ID | Required proof | Owning milestone |
|---|---|---|
| AT-01 | Existing commands, scores, scans and measurement records behave identically with the new switches off; enabled-path tests actually exercise the new path. | M0.4 / M18.4 |
| AT-02 | At 06:34:59 Pacific the five-minute OR is incomplete. It becomes eligible only after all required bars are final and available. Revised bars, early closes, missing minutes and clock changes cannot leak future values. | M1.1 / M2.2 / M3.6 |
| AT-03 | Duplicate/out-of-order events and reconnect bursts do not inflate acceptance, VWAP/RVOL or trade counts; lost coverage suppresses the dependent trigger. | M2.3 / M3.1–M3.5 |
| AT-04 | Stale cached quotes, fresh bid/ask with stale last trade, delayed data, crossed quotes and stock/option time skew are rejected or explicitly degraded according to the frozen contract. | M2.1 / M2.3 / M14.2 |
| AT-05 | Each of the eight strategies passes hand-worked long/short, near-miss, missing-data, threshold, expiry and invalidation fixtures using approved definitions; unresolved branches stay blocked. | M0.3 / M6–M13 |
| AT-06 | Database failure before persistence sends nothing. Crash before/after send preserves one mechanical event; uncertain delivery stays UNKNOWN without blind replay. Expired intents never send on recovery. | M4.6 / M5.5 / M15.7 |
| AT-07 | A continuous run and a crash/resume run produce identical strategy facts, frozen references, structure counts, suppressions and outcomes from the same input manifest. | M5.3 / M5.5 |
| AT-08 | An options/AI outage preserves the valid stock setup with explicit missing-quality/enrichment status. Exact contracts, non-standard deliverables, zero/missing Greeks and 0DTE constraints are handled without changing underlying validity. | M4.7 / M14 |
| AT-09 | #1→#3, #3↔#6, #2↔#7, opposite directions and equal-score ties produce deterministic thesis ownership; component candidates survive dedup for research. | M4.7 / M8.5 / M15 |
| AT-10 | Replay cannot read credentials, write the live database, or contact the network. Live shadow records its sink and cannot be called delivery-tested without actual delivery evidence. | M5.3 / M9.3 |
| AT-11 | Sector/full/hybrid breadth and approximate/true profiles retain formulas, coverage and mode. Missing sectors, a membership change, a split, missing no-trade bars and zero prior LVN volume produce defined results. | M10 / M13 |
| AT-12 | Original news receive/classification availability is respected; a later correction or late catalyst cannot create an earlier #7 signal. | M12 |
| AT-13 | Saturation, provider throttling, authentication failure, disk-full and slow delivery remain bounded and observable while old commands continue to work. Rollback preserves records. | M0.2 / M18 |
| AT-14 | Research includes undelivered/suppressed candidates as appropriate, explicit unresolved outcomes, correct after-cost fills, and separate mechanical, delivery, human and option results. | M5.2 / M16 / M17 |

## 49. Frozen execution and statistical contract

Before calculating expectancy, M0.3/M5.2 records an exact outcome policy: entry reference, delay origin, quote side, maximum entry wait, trigger/stop/target ordering, target exit fractions, remaining-position exit, time horizon, fees, slippage, gaps/halts, borrow, same-bar ambiguity and censoring. Stop/target geometry alone does not define profit. Do not select these choices after seeing returns.

Mechanical delay starts from the recorded mechanical event. Executable alert delay starts after confirmed delivery; human reaction starts after the defined receipt/decision reference. Report these separately. With only one-minute OHLCV, do not invent 5/15/30-second quotes or a path inside the trigger bar. After M0.3 freezes which observations are permissible, use the first actually available permissible entry observation, mark unsupported delay horizons unavailable, and retain the full requested delay study as a data-dependent requirement.

The existing exact-quote measurement path uses ask for option entry, bid for exit, and $0.45 per contract per transaction ($0.90 round trip for one contract). Preserve that behavior when reusing it. Other existing research uses midpoint assumptions; preserve its separate attribution. These are inspected implementation facts, not approval of a primary fill model for the new playbooks. P-03 must record the approved primary and sensitivity models before their results are calculated. A modeled midpoint or quote-side assumption alone does not prove an actual fill. Executable option evidence requires the exact contract, multiplier, bid/ask, timestamps and expiry; executable short-stock evidence also requires point-in-time borrow eligibility and costs. Missing borrow permits a labeled directional study, not executable short-stock profit. Record the frozen fee rule, add only separately supported fees, and avoid double-charging a spread already included in the selected model.

MFE/MAE and a favorable excursion are diagnostics, not realized or modeled net profit. Unresolved, unfilled, halted and ambiguous outcomes remain visible in denominators; report the declared conservative handling and unresolved counts. Record all attempted variants and use chronological held-out periods, session/market-event dependence, overlap-aware uncertainty and train-only calibration. Purge overlapping outcome windows across train/test boundaries. Alert-count labels in §23 describe sample size, not statistical strength or an automatic promotion gate.

Historical universe exclusions, missing delistings/corporate actions, revised fundamentals/news, or current membership must be disclosed and quantified. A biased/provisional study may inform research but cannot establish broad-universe edge or satisfy promotion by labeling alone. Full-data/proxy results stay separate. When uncertainty or selection bias cannot be bounded, use INSUFFICIENT_DATA for the affected claim.

Promotion requires a preregistered report and explicit recorded owner decision under D-083. No score, successful implementation, sample-count label, reviewer vote or automatic monitoring action grants approval. Refinement, rejection and challenger work preserve versioned history and all original mechanical facts.

## 50. Release and deployment proof

Before ACTIVE, verify a new flag cannot bypass release checks by being absent in the previous configuration. Require the existing exact failing-test-ID gate without absorbing newly broken tests into `.test-baseline`. Test the new behavior enabled as well as disabled.

Compare installed and checked-in deployment definitions before any approved deployment; preserve startup checks, failure reporting, process ownership and resource limits. Rehearse rollback, kill switch, restart continuity and delivery reconciliation before activation. A supported interpreter and dependency compatibility must be established by the chosen-runtime test run. Full Phase 18/19 work stays tracked after these minimum controls are satisfied.


## 51. Approved M0.3A research policy and worked-definition evidence

D-090, owner-approved on 2026-09-05 Pacific, incorporates [M0_3_DEFINITION_PACKET.md](./M0_3_DEFINITION_PACKET.md) version `M03A_ORB5_V1` §7 as research policy O-01 under this document's authority. It fixes the specified entry clocks/search, quote sides, risk references, two-unit 50/50 exits, fixed stop, same-session horizon, ambiguity/censoring and option timing. It does not supply the explicitly unfinished fees/slippage, borrow, primary/sensitivity assumptions, historical splits, uncertainty or promotion gates; those remain M0.3B requirements before expectancy claims.

The packet's FX-01–FX-18 are synthetic definition examples checked during drafting. Their inputs/results and all trading formulas are unchanged by the approval update. They are not executed strategy tests or profitability evidence. Later implementation must exercise equivalent cases in the actual enabled path under AT-02–AT-05/AT-14. The existing $0.45 per-contract transaction fee remains unchanged; two whole research contracts allow the specified half/half exits without splitting a contract.

D-091 separately authorizes no more than $25 cumulative Databento testing credit. Before any charged request, verify the relevant official cost mechanism, reserve a conservative request bound in DECISIONS §31, and ensure confirmed plus reserved usage cannot exceed the cap. Include retries and uncertain/in-flight charges; retain unresolved reservations after interruption. Approval does not make a request free or its data fit for a particular test. The documentation/approval update ran no provider request, application test, trade, Discord delivery or deployment.

## 52. M0.3B offline evidence policy — `M03B_OR_RESEARCH_V2`

The owner's 2026-09-13 Pacific delegation authorizes the offline research choices in [M0_3B_DEFINITION_PACKET.md](./M0_3B_DEFINITION_PACKET.md), section “Agent-selected preregistration.” Incorporate its evidence contract under this document's authority. It selects the historical packet's §4 cost, delay, uncertainty, score-calibration, conservative missing-outcome and release formulas for V2, except that no B arm is privileged and the confirmatory family is the 72 frozen V2 stop/exit arms.

Every arm reports after-cost expectancy, win rate, payoff ratio, maximum drawdown and frequency with counts and denominators. Keep 5-minute/15-minute, immediate/confirmed/retest, long/short, both stops and all three exits identifiable. Keep market regimes `DOWN` at or below -0.50%, `FLAT` strictly between -0.50% and +0.50%, and `UP` at or above +0.50%, using point-in-time SPY open versus prior close. Unknown regime does not erase the main result. D-090 is a separate historical arm. Losing, empty and unavailable arms remain in the report.

The 72-arm confirmatory allocation is one-sided `0.05/72 = 1/1440` per arm. Use the existing circular 10-session moving-block bootstrap with 10,000 draws, frozen seeds and nearest-rank `q=1/1440`. This comparison control does not establish exact family-error control and does not choose an operational winner. Stock exact-quote, one-minute bar estimate, executable short and executable option evidence stay separate. Missing borrow blocks executable short claims. Missing option bid/ask or contract evidence blocks only the option claim.

The chronological split stays 60% development, 20% calibration and the remainder final validation over an immutable ascending covered-session manifest. The exact manifest hash and date lists must be written before any candidate or return is generated. Final validation may be opened once. Any tuning or repeated access requires newly arriving final dates. The coverage-only audit found no qualifying manifest, so all exact date lists are currently unavailable and replay is blocked. `M0_3B_COVERAGE_AUDIT.json` records null rather than inventing dates or a hash. No strategy return was calculated in this revision.

[FIRST_BUILD_SESSION.md](./FIRST_BUILD_SESSION.md) supplies M0.4 cases C04-01–C04-07 and pre-import protection. Passing them proves only isolated compatibility of the tested existing interfaces. It does not prove new strategy logic, full provider fidelity, delivery receipt, profitability or release readiness. New records/recovery/replay work stays in M1/M4/M5. The fresh session must record actual test results and leave missing source or trading approvals open.

## 53. M1.1 clock evidence boundary

[M1_1_VERIFICATION.md](./M1_1_VERIFICATION.md) records 41 fixed-input clock cases
and the independent 125-case combined selection, passing twice under pre-import
protection. This closes the shared clock's §6 scenarios and only AT-02's clock
portion: 06:34:59 precedes the opening-five-minute boundary; 06:35 begins the
configured evaluation window; 07:15 ends it. Reaching those times does not prove
the required bars are final and available. Receipt delays, revisions, missing
minutes and resulting feature eligibility remain required under M2.2/M3.6.

## 54. M1.2 configuration evidence boundary

[M1_2_VERIFICATION.md](./M1_2_VERIFICATION.md) records 48 new configuration cases
within an independent 194-case combined selection, passing in each of two
protected processes. Tests cover the real loader with absent/disabled/enabled
settings, strict invalid inputs, prior cache/reload compatibility, detached fixed
snapshots, legacy secret exclusion, stable identity and configured clock inputs.
The two processes produce the same config hash and no unexpected isolation
denials. A configured true switch is tested as a requested setting only; no
strategy runtime or delivery is started by these tests.

This closes the M1.2 configuration portion of FR-030. Persisted old-session
attribution, restart/replay identity and full AT-07/AT-14 remain M5.1/M5.3/M5.5
and M16.1 proof. Actual approval/readiness and enabled runtime/sink/release gates
remain their M4/M9/M17/M18 owners. Neither these checks nor a version label proves
an approved policy, valid data, live output or trading edge. The full application
suite and live release were not run or claimed passing.


## 55. M1.3 canonical record evidence boundary

[M1_3_VERIFICATION.md](./M1_3_VERIFICATION.md) records 144 new record cases
and a final independent 363-case combined selection, passing twice under
pre-import protection. The tests cover all thirteen record types, invalid and
ambiguous serialized inputs, date/time/finality constraints, missing versus zero
data, exact option identity, immutable nested values and configuration/session
attribution through the existing loader. Separate option/delivery/outcome/human
records preserve the original candidate bytes. Both process outputs are identical.

This closes M1.3 record consistency only. It does not complete M2 provider
normalization/freshness/coverage, M4 runtime/delivery/options/suppression, M5
storage/link integrity/recovery/replay or AT-04/06/07/08/10/14 in their full scope.
The model records state labels and caller-supplied facts; it does not independently
prove their external truth or approval. The full application release suite and
live output were not run or claimed passing. Existing listener isolation and
interpreter/deployment gaps remain with M18.4/M18.6.


## 56. M2.1 normalization evidence boundary

[M2_1_VERIFICATION.md](./M2_1_VERIFICATION.md) records 41 new raw Schwab mapping
cases, each passing twice under pre-import isolation. The independent combined
selection passes 420 cases twice. Tests cover raw versus legacy last-price
semantics, exact milliseconds, both quote/trade age directions, original
availability, revisions, missing/zero/sentinel values, delay/quality/context
contradictions, positive valid quote sides, caller-defined bar boundaries/finality,
and exact option expiry/side/strike with adjusted roots preserved. Canonical Bar,
Quote and OptionQuote round trips produce byte-identical proof in both processes.

This covers M2.1's normalization slice of AT-04. A synthetic VALID label does not
prove current provider freshness, matching sessions or executable quotes. Numeric
age/skew budgets, dynamic stale/reconnect gates, full fallback and coverage,
OI timing/units, history finality and actual stock/option alignment remain with
M0.2/M0.3, M2.2/M2.3 and M14.2. No AT-04 live gate, strategy evidence or release
permission closes by implication. Replay, storage and delivery are not activated.

## 57. M2.2 offline acceptance evidence

[M2_2_VERIFICATION.md](./M2_2_VERIFICATION.md) §11 records the supervisor's two
fresh protected runs: **424 tests passed in each**, including 75 historical-interface
cases, with zero failures/errors/skips, identical test IDs, no unexpected
isolation denials and all cleanup checks true. Both `m22-history-proof.json`
records are byte-identical. [M2_2_LOCAL_CHECKS.json](./M2_2_LOCAL_CHECKS.json)
saves inspected publication hashes, counts, output summaries and source identity.
The verified repair in §10 adds four unknown-evidence-reference cases and includes
`tests/test_all_command_levers.py::test_pct_change_short_history_returns_none`
and `tests/test_all_command_levers.py::test_pct_change_happy` in the required
protected selection. Both cases and all four repair cases passed in each run.
All 771 saved file contents matched before records-only finalization. Code, tests
and protection stayed unchanged. Section 9's 418-test results and the earlier
launcher errors remain historical. Independent acceptance still belongs to the
supervisor's separate reviewer; M2.3 remains proposed until that review passes.

The actual synthetic path uses the raw historical request function with fake
transport, M2.1 normalization, canonical Bar records, scheduled requested coverage
and deterministic archive/available-time views. At 06:34:59 Pacific the fifth
minute has not ended. At 06:35 its late final is still missing; at 06:35:02 it is
available. The first two views contain 46 shares; the complete view contains 60.
Later revisions cannot alter an earlier view. Tests also cover daily and premarket
requests, holidays/early closes/clock changes, gaps, provisional and invalid
revisions, duplicate/conflicting/out-of-order observations, certified no-trade
intervals, source/adjustment/mode mismatch, legacy table/fallback callers and a
synthetic direct daily-history consumer.

With the repaired source's fresh protected proof, M2.2 closes only its offline
coverage/availability slice of AT-02. M3.6 retains
actual OR extrema and the at-least-one-traded-input requirement; M0.2 retains real
provider evidence. The full application/release suite, live streaming, strategy
replay, delivery and profitability are not established by these synthetic cases.
All existing approval/data/release gates remain open with their roadmap owners.


## 58. M2.3 offline event acceptance — review repair execution pending

[M2_3_VERIFICATION.md](./M2_3_VERIFICATION.md) §11 records the second source-time
repair, extensions of both named tests and the offline recording case. Sections
8/10's earlier 487/489-test runs predate this repair and do not verify it. No passing
repair result is claimed. The supervisor must run
`tests/trade_alerts_contracts`, `tests/test_models.py` and
`tests/test_schwab_client.py` twice through that protection. No launcher/guard
change or outside test execution is needed or permitted for this handoff.

The end-to-end case `test_normalized_events_failure_reconnect_recording_end_to_end`
uses M2.1 raw REST-shaped normalization, canonical Quote round trips, the actual
M2.3 state/age decisions, explicit fixed times and deterministic recording output.
It covers independent quote/trade advances, repeated and out-of-order inputs,
quote-age boundary, disconnect/reconnect, stale recovery proof, unknown evidence,
explicit and elapsed gaps, delayed/missing data and fresh recovery. It now includes
unchanged quote/trade timestamps with missing, wrong-session and same-session
pre-recovery source times, rejected confirmation and a cache repeat that cannot
heal missingness. A source time after availability stays on the unusable retained
record even after the clock catches up. The expected forwarded quote IDs are
q1/q2/q5/q10/q14/q18; expected last-trade snapshot IDs are q1/q3/q5/q10/q14/q18,
across 43 decisions. These are written repair assertions, not observed passing
output. Both named tests must also prove the bad input stays visible and unusable,
with no forwarding, until fresh recovery data and proof. Existing cache non-healing
assertions are preserved.

Each protected process must produce `m23-quote-events-proof.json`. Read both files,
require byte-identical decisions, then inspect both XML/isolation reports for zero
failures/errors/skips, matching test IDs, no unexpected denials and successful
cleanup. Source grammar/compilation and static inspection are not substitutes.
A fresh builder receiving successful supervisor artifacts must finalize records
without changing code or tests, then return completed for independent review.

This proves only M2.3's offline ordering/continuity and age slices of AT-03/AT-04.
Feature acceptance, VWAP/RVOL, trade counts and complete window coverage remain
M3/M6; stock/option timing remains M14.2. No synthetic count proves tape coverage,
provider access, live recovery, strategy returns or release readiness. All switches
remain off. Full live M2.3 remains explicitly blocked under M0.2/M2.3.


## 59. M2.4 offline reference acceptance — execution pending

[M2_4_VERIFICATION.md](./M2_4_VERIFICATION.md) specifies the M2.4 assertions and
exact protected selection: `tests/trade_alerts_contracts`, `tests/test_models.py`,
`tests/test_schwab_client.py` and
`tests/test_wolf_macro_brain.py::test_stock_sector_etf`. Both unchanged protected
children must pass. No passing M2.4 count is claimed; local launcher execution
stopped before tests. Source inspection/compilation cannot replace that evidence.
M2.3 §12's successful 490-test proof supersedes §58's pending status but predates
this milestone and is not M2.4 proof.

The required `test_supplied_reference_coverage_recording_end_to_end` exercises
synthetic raw input -> canonical Bar/Quote round trips -> actual per-symbol
M2.3 decisions and M2.2 coverage -> immutable reference snapshot -> recording.
Its two written expected snapshots have quote/history counts 9/11 then 0/12
for 13 expected ETFs. Missing QQQ/XLV, delayed XLE, disconnected XLP, missing XLF
history, late XLK history and unsupported VIX stay individually visible. These
are synthetic assertions until the resulting files have actually been inspected.

Additional cases cover all 13 ETFs independently, unknown current mapping and
its separate historical-unavailable label, wrong identity/source/session/mode,
future decisions/availability/components, stale sides versus stale last trade,
missing policy/history request, recovery and immutable prior views after revision.
Canonical validation rejects future component times before M2.3 accepts input;
an ignored future record cannot replace the retained current quote.

Each child must save `m24-reference-inputs-proof.json`. Require byte-identical
recordings and matching test IDs, zero failures/errors/skips, no unexpected
isolation denials and successful cleanup. The supervisor returns actual artifacts
to a fresh builder for records-only finalization and independent review. The
required M2.4 source gate stays [!] after offline proof; apply the blocked-gate
handoff in M2_4_VERIFICATION §6. Do not claim full source completion, sector/full
breadth formulas, live delivery, strategy validation or profitability.

## 60. M3.1 core price feature acceptance — fifth repair proof finalized

`tests/trade_alerts_contracts/test_core_price_features.py` checks D-090's hand-worked
minute ATR, daily ATR and HLC3 VWAP arithmetic; scheduled windows; missing, late,
revised-invalid and no-trade minutes; prior and premarket coverage; explicit
opening-trade/gap requirements; early close handling; future-revision isolation;
canonical FeatureSnapshot round trips; and deterministic recording. The review
repair also checks the first traded minute after certified no-trade opening minutes,
separates a valid prior session from an older incomplete ATR window, and rejects an
opening trade whose source time follows availability or evaluation. The deterministic
recording includes the repaired no-trade, daily-window and evaluation-time paths.

The second repair preserves a valid identified session open when the prior daily
bar or all daily history is absent, invalid or no-trade. Only gap needs that close.
Unexpected records outside the selected window cannot alter its results; records
overlapping required slots or the needed previous close still block them. A missing
previous close cannot be skipped to use an older one. Direct cases cover zero
session volume, complete all-no-trade windows, insufficient minute/daily warm-up,
and the unchanged legacy Wilder ATR and weighted-price helper contracts.

Shortened-session proof now sends actual synthetic Bars through coverage and
`build_core_price_snapshot`: the 2026-11-27 session has 210 scheduled minutes and
closes at 10:00 Pacific. Its last bar arrives at 10:00:02. The session results at
09:59:59, 10:00:00 and 10:00:02 must show usable, unavailable, then usable values.
A shortened daily Bar also supplies the next session's daily ATR and prior levels.
The deterministic recording saves these current-session views, both off-window
coverage/results, open-without-close, zero-volume and short-history results.

Run the unchanged protection twice with `tests/trade_alerts_contracts`,
`tests/test_models.py`, `tests/test_schwab_client.py`, and
`tests/test_wolf_macro_brain.py::test_stock_sector_etf`; include the assigned
`tests/trade_alerts_contracts/test_core_price_features.py` selector. Require matching test IDs,
zero failures/errors/skips, no unexpected isolation denial, clean cleanup and
byte-identical `m31-core-price-features-proof.json`. Local compilation is not passing
test evidence. Sections 7–8 of M3_1_VERIFICATION record historical 549- and 553-test
supervisor runs; both predate the second repair. The 553-test artifacts were read
again and contain 16 M3.1 cases in each run. They cannot verify the changed code or
the now **32 written M3.1 cases**. Their full-history M3.1 recording was also too
large for the review path. The repaired recording now publishes readable counts,
values and missing reasons plus SHA-256 hashes of the complete canonical objects;
the test still runs the full calculations, assertions and round trips, and rejects
a rendered proof file of 100,000 bytes or more. Fresh proof
must use this compact format. The local protected attempt stopped at the
launcher's initial ownership step before collection; see M3_1_LAUNCHER_LIMITATION.
Two protected runs passed 569 tests each, including all 32 then-current M3.1 cases, with
identical ordered test IDs and byte-identical 32,072-byte compact recordings.
There were no failures, errors, skips or unexpected isolation denials, and cleanup
passed in both runs. That proof is historical after the unit/instrument repair in
M3_1_VERIFICATION §11.

The third repair's **40 written M3.1 cases** added exact `USD_PER_SHARE` price and `SHARES`
volume checks, feature-specific missingness, source/venue-basis compatibility,
finite opening prices and EQUITY/ETF instrument matching. OPTION and mismatched
opening records cannot supply open or gap. The compact recording includes these
repair paths. Both changed Python files pass local compilation and Python 3.10
grammar parsing. Fresh supervisor proof at 15:37:54 Pacific used the unchanged
protection. Both runs passed 577 tests, including all 40 M3.1 cases, with zero
failures, errors or skips, identical ordered test IDs, no unexpected isolation
denials and clean cleanup. The two 41,712-byte compact recordings are byte-identical
with SHA-256 `5b3a9ebf39f9f81e989af9880b9914c699c19cceba5fdc2a8bab19220ade1ee1`.
That manifest matched the files before the fourth repair. These 577-test results
are now historical. Full trade VWAP and real source coverage stay [!] separately;
M3.2 remains proposed after independent review.

The fourth repair in M3_1_VERIFICATION §13 had **50 written M3.1 cases**. Six new
cases put a future ETF revision first and last in each minute/daily/premarket
history. Complete snapshots must stay identical before availability; dependent
features must reject mixed identity at exact availability. Further cases cover
future-only identity, a later compatible revision, a 329-minute request starting
at 01:01 Pacific and a complete 660-minute two-session request. The current
330-minute premarket window alone must supply PMH/PML=101.3/98.7; older 150/50
extrema cannot enter it. The compact recording includes these repaired paths and
readable snapshot instrument types. M3_1_VERIFICATION §14 records that repair's
historical 587-test proof. The fifth repair superseded it; neither protection file
changed.

Earlier pending M2.3/M2.4 status notes in §§58–59 are historical: their offline
proof was finalized in M2_3_VERIFICATION §12 and M2_4_VERIFICATION §9. ROADMAP §31
and PROJECT_INDEX §31 now carry this M3.1 repair. No synthetic check proves source
coverage, live access or profitability.

The 587-test/50-case proof is historical after the fifth review repair in
M3_1_VERIFICATION §15. The current **54 M3.1 cases** add two mixed-session
minute-ATR paths and both wrong-interval directions. A premarket close cannot
become the prior close for a regular-session true range. This remains true after
a certified no-trade opening minute. Minute history cannot supply daily ATR/prior
levels, and a daily bar cannot supply minute VWAP/current extrema. The compact
recording contains all four paths.

M3_1_VERIFICATION §16 records the completed proof. Both fresh protected runs passed
**591 tests**, including all **54 M3.1 cases**, with zero failures, errors or skips.
Ordered test IDs matched, isolation and cleanup were clean, and the two compact
recordings were byte-identical at **67,989 bytes** with SHA-256
`89ed9dcbfce5f458dd452ed0cae0bdb4cf730eb282e24e46e136da32238d2234`.
All required selectors above ran. The M3.1 offline row is `[x]`. The separate
full-data/source row stays `[!]`; this synthetic proof does not establish actual
source coverage, live access or profitability.

## 61. M3.2 participation acceptance — offline proof complete

`tests/trade_alerts_contracts/test_participation_features.py` contains 46 written
cases. They cover D-090 FX-05/FX-06 arithmetic, the tenth/eleventh daily median,
threshold neighbors without display rounding, zero/missing inputs, exact prior
sessions, truncated requests, late finals, provisional/invalid/conflicting
revisions, duplicate/order handling, future instrument identity, units/basis/mode
mismatch, holidays, clock changes and actual shortened-session daily Bars.
Legacy relative-volume arithmetic remains separately checked. All 46 cases passed
in both fresh protected supervisor runs.

The end-to-end case round-trips supplied canonical Bars, runs real M2.2 coverage
and M3.2 calculations, round-trips the immutable snapshots and writes
`m32-participation-features-proof.json`. At 06:29:59, 06:30:00, 06:34:59 and
06:35:00 Pacific, expected opening/premarket/dollar values are respectively
UNKNOWN/UNKNOWN/50,000,000; UNKNOWN/2.75/50,000,000;
UNKNOWN/2.75/50,000,000; and 2.0/2.75/50,000,000. Missing-reference, invalid-revision,
late-final, zero-numerator/denominator, clock-change and shortened-session cases
also appear in the compact recording. Full snapshots are checked and hashed;
readable values, reasons and input/coverage counts keep the file below 100,000 bytes.

The unchanged protected launcher ran twice with the selection in
M3_2_VERIFICATION §2. Both runs passed 637 tests, including all 46 M3.2 cases,
with zero failures/errors/skips, matching ordered test IDs, clean isolation and
cleanup, and identical 10,041-byte compact recordings. M3_2_VERIFICATION §8
records the inspected proof. The offline row is `[x]`, but full M3.2 remains
blocked by §5's required gates.
This proves only the supplied-Bar volume portion of AT-03 and point-in-time
feature behavior. No live coverage, acceptance window, strategy or profit is proved.

M3_2_VERIFICATION §7 records a timeout repair. The previous supervisor log reported
637 passing tests in its first child, then a second-child timeout at the existing
300-second limit. This incomplete run cannot close acceptance. The test fixtures
now reuse only the real immutable calendar intervals for an identical complete
HistoryRequest value. No coverage, feature or assertion result is cached. Every
end-to-end input uses the ordinary uncached request and real Bar round trips.
All 46 cases, parameter lists and assertion expressions are preserved. Production
code and both protection files are unchanged. The repaired local launcher stopped
before collection. The later supervisor proof in M3_2_VERIFICATION §8 completed
within the unchanged limit in both runs.

## 62. M3.6 opening-range acceptance — request-window repair proved

`tests/trade_alerts_contracts/test_opening_range_features.py` covers D-090's
five scheduled opening minutes, hand-computed high/low/mid/width, explicit
complete status, certified no-trade intervals, all-no-trade input, missing/late/
provisional/invalid/conflicting revisions, duplicates and ordering, wrong units,
identity, interval, source basis and mode, holidays, clock changes, a shortened
session and immutable earlier snapshots. The verified repair adds truncated and
disjoint original requests whose archives still contain all five opening Bars;
neither request may produce a completed range.

The end-to-end case round-trips canonical Bars, runs actual M2.2 available-time
coverage and the M3.6 calculation, round-trips immutable FeatureSnapshots and
writes `m36-opening-range-features-proof.json`. It requires no completed range at
06:34:59 Pacific, a complete range at 06:35 when all five bars are available,
unchanged earlier facts after a later bad revision, and no range from five
certified no-trade minutes. The recording is synthetic software proof only.

The required protected selection is `tests/trade_alerts_contracts`,
`tests/test_models.py`, `tests/test_schwab_client.py`,
`tests/test_wolf_macro_brain.py::test_stock_sector_etf` and
`tests/trade_alerts_contracts/test_opening_range_features.py`. Both runs must have
zero failures/errors/skips, matching ordered test IDs, clean isolation and cleanup,
and byte-identical compact M3.6 recordings. The finalized proof below meets these
requirements; compilation and source review alone are not passing test evidence.

### Historical attempts before the finalized proof

The local launcher stopped before collection at its initial ownership step; exact
evidence is in M3_6_LAUNCHER_LIMITATION.txt. It left the offline work ready for
supervisor verification at that time. The following attempts and pending states
are historical and are superseded by M3_6_VERIFICATION §12.

M3_6_VERIFICATION §8 records the 18:54 Pacific retry and then-unchanged hashes.
There were 26 written M3.6 cases after parameter expansion. That failed supervisor
status supplied no readable proof copy, so its failure cause and a passing result
were not established then.
No code, test or protection change was made for this records-only repair.

M3_6_VERIFICATION §9 records a later test-only speed repair. The broad-request
fixture selects the same five opening intervals before creating Bars rather than
creating a full regular session first. All 18 test functions, parameter lists and
assertion expressions were preserved, so the written count remained 26. Production
and both protection files were unchanged. That protected attempt stopped before
collection at the same ownership step. Fresh supervisor proof was required for
the changed test hash and all requirements above.

The §10 supervisor proof passed 663 tests in each of two protected runs, including
all 26 M3.6 cases. Ordered test IDs and the 7,237-byte compact M3.6 recordings
match; isolation and cleanup were clean. That proof is historical after the
request-window repair in M3_6_VERIFICATION §11.

After §11's request-window repair, the 28 written cases and expanded compact
recording required two fresh runs through the unchanged protection. The offline
row was then `[~]` and the milestone was `ready_for_verification`. Section 12's
finalized proof supersedes that pending state.
The local 19:37 Pacific attempt stopped before collection at the launcher's
initial ownership step; M3_6_VERIFICATION §11 saves the exact result.
Actual source coverage and data fitness remain a separate blocked gate. No
strategy readiness, live access, execution result or profitability follows.

### Current finalized offline proof

The fresh supervisor proof supplied at 19:48:40 Pacific passed **665 tests** in
each protected run, including all **28 M3.6 cases**. Ordered test IDs match. The
two 9,379-byte compact records are byte-identical with SHA-256
`e51116fd2f4430d33e53014d4c02bde9ee36a11e90e922d2749ec2eb208912a3`.
Both isolation reports have no unexpected denials and show successful cleanup.
This completes the repaired offline acceptance only. ROADMAP §31 retains the
offline `[x]` row and the required actual-source `[!]` row. Overall status remains
`blocked`, with independent next milestone **M4.1** after review.

## 63. M4.1 interface acceptance — protected proof complete

`tests/trade_alerts_contracts/test_strategy_interface.py` contains 55 cases, all
passing in both protected supervisor runs.
They cover common member completeness, all eight existing identity labels,
explicit required-data roles, separate setup/substate labels, immutable context,
missing versus zero, reference identity, future/duplicate/misattributed inputs,
current Quote decisions, missing/stale inputs and unchanged all-off settings.
M4_1_VERIFICATION §7 and M4_1_SUPERVISOR_TESTS.json record the verified results.

The long and short end-to-end cases round-trip supplied Bars, run real M2.2/M3.6
opening-range calculations and M2.3 Quote checks, pass canonical snapshots through
the new interface to a test-only strategy, and record canonical transitions and
heads-up/actionable candidates. The expected sequence at 06:34:59, 06:35:00 and
06:35:01 Pacific is WATCHING/no candidate, SETUP_FORMING/HEADS_UP, and
ALERT_TRIGGERED/ACTIONABLE. The first/second-ready-input script, fixed score and
geometry exist only in this test; they are not CRVOL_ORB5 or another trading rule.
Missing/stale input, invalidation, expiry and reset remain in the recording.
Repeated execution after reset must give identical original records.

Use the unchanged protected launcher with `tests/trade_alerts_contracts`,
`tests/test_models.py`, `tests/test_schwab_client.py`,
`tests/test_wolf_macro_brain.py::test_stock_sector_etf`, and
`tests/trade_alerts_contracts/test_strategy_interface.py`. It runs both children.
Require all 55 M4.1 cases, matching ordered IDs, zero failures/errors/skips,
no unexpected isolation denials and successful cleanup. Each child must write
`m41-strategy-interface-long-proof.json` and
`m41-strategy-interface-short-proof.json`; the corresponding files must match
byte for byte across runs and each remain below 100,000 bytes.

The supervisor supplied the required proof at **20:50:15 Pacific** on 2026-09-06.
Both runs passed **720 tests**, including all **55 M4.1 cases**, with zero failures,
errors or skips and matching ordered test IDs. Both isolation reports show no
unexpected denials and successful cleanup. The long and short records are
byte-identical across runs at **16,032** and **16,044 bytes**, respectively.
A fresh builder checked the readable XML, isolation, output and recording files
and matched source/test/protection contents to the tested manifest. Records-only
finalization is complete; independent acceptance review remains. The failed local
attempt and ownership notes in M4_1_VERIFICATION §3 and
M4_1_LOCAL_CHECKS.json's historical section are superseded by this proof.
Compilation is not test proof. This closes only the M4.1
interface slice of FR-005/CAP-01. Full AT-05 strategy behavior, AT-07 recovery,
live data, delivery, approval and profitability remain with their original owners.

## 64. M4.2 transition/storage acceptance — expanded protected proof complete

Current status: implementation, expanded protected proof and records-only
finalization complete. Both fresh runs passed **826 tests**, including all 56
M4.2 cases and the four database checks added after review. All 18 selectors in
M4_2_VERIFICATION §2 ran through the unchanged launcher. Section 13 of that record
and M4_2_LOCAL_CHECKS.json save the inspected proof. Code, tests, configuration
and protection remain unchanged; independent acceptance review remains.

`tests/trade_alerts_contracts/test_state_transitions.py` contains 56 written cases.
They cover all seven canonical states with explicit entry/exit substate pairs,
immutable rules/scope/configuration, invalid shortcuts, identity/time/reference
errors, same-time serialized writes, backward time, exact retry, conflicting IDs,
recording failure, invalidation/expiry/reset and missing-input invalidation.
Actual temporary-database cases check complete round trips, identical replay,
scope/position/predecessor conflicts, append-only updates/deletes, transaction
rollback, lost acknowledgment retry and additive migration/reopen preservation.

The long/short end-to-end cases send round-tripped supplied Bars through actual
M2.2/M3.6 feature calculation, M2.3 Quote checks and M4.1's test-only strategy.
The resulting canonical transitions pass through the actual M4.2 engine and host
database transaction. At 06:34:59, 06:35:00, 06:35:01 and 06:35:02 Pacific, expected
states are WATCHING, SETUP_FORMING, ALERT_TRIGGERED and WATCHING. The final input
has a stale quote and no candidate. Explicit invalidation, same-session reset
and expiry produce nine saved changes per direction. Replay of the first four
adds zero rows; close/reopen preserves all nine byte for byte. No test script
or score/geometry/expiry fixture is an approved playbook or a live policy.

The complete required protected selection is in M4_2_VERIFICATION §2. It includes
the existing contract directory, the new explicit file and affected legacy
model/provider/reference/database/migration/measurement/schema checks supported
by the unchanged launcher. C04-05's exact expected version list now includes 35;
its rollback and schema/reopen assertions are preserved. Tests requiring an
unmounted gate script are recorded as full-suite limits, not falsely claimed
passing or used as a reason to weaken protection.

Both protected runs must have matching ordered IDs, zero failures/errors/skips,
no unexpected isolation denials and successful cleanup. Require all 56 M4.2 cases
and byte-identical `m42-state-transitions-long-proof.json` and
`m42-state-transitions-short-proof.json` across runs, each under 100,000 bytes.
Inspect the XML, isolation, logs and both recordings. Compilation is not test
evidence; M4_2_VERIFICATION records the actual execution status. No required
live/data/definition gate belongs to this shared mechanism. Full AT-05/06/07,
earlier source gates, automatic recovery and profitability remain unproved here.

### Historical attempts before the expanded-selection review

The following pending states belong to earlier attempts. The 822-test proof below
superseded their failures. M4_2_VERIFICATION §13 now also proves the four checks
added in §12. None of these historical states is a current verification gap.

M4_2_VERIFICATION §7 records the first repair inspection after the supervisor's
first child timed out at the unchanged 300-second limit. No completed proof copy
was published, and detailed output returned `Permission denied`. All 56 cases
and the entire required selection remain unchanged. The supervisor must return
two successful protected runs and their matching recordings, or publish readable
partial output and the pytest log if execution times out again. An incomplete
run cannot close acceptance; the local ownership limitation cannot establish the
cause of the supervisor's timeout. No protection change is authorized here.

M4_2_VERIFICATION §8 records a second first-child timeout, reported at
22:05:33 Pacific. Both detailed output and pytest.log returned `Permission denied`.
No complete proof, passing count or measured slow operation was supplied. The
fresh local attempt at 22:10:01 Pacific failed before collection at the unchanged
launcher's initial ownership step. The 19 test functions, 56 written cases,
complete selection and both protection files are preserved. Status at that attempt stayed
**ready_for_verification**. The supervisor must publish readable child progress
for diagnosis or return the complete two-run proof and host ownership check.

M4_2_VERIFICATION §9 records the historical third timeout at **22:20:53 Pacific**.
Detailed child output and pytest.log again returned `Permission denied`; no
completed proof or measured slow-test cause was supplied. The unchanged local
launcher stopped before collection at 22:31:38 Pacific. The earlier attempts above
are historical; no M4.2 passing result is claimed.

That attempt's delta also contained existing owner changes in
`test_core_price_features.py` and `test_reference_inputs.py`. They reuse bounded
immutable history inputs while keeping the actual coverage/feature calculations,
test bodies, parameters and all assertions unchanged. This session preserves
those files and adds both explicit selectors to M4_2_VERIFICATION §2. Fresh proof
must include all 54 M3.1 and 46 M2.4 cases, both matching affected recordings,
and the 56 M4.2 cases and long/short recordings required above. Prior passing
runs predate these input-helper changes and do not verify them. Two complete
protected runs, readable proof and host ownership verification remain required.
Status at that attempt stayed **ready_for_verification**; protection and its limit were unchanged.


M4_2_VERIFICATION §10 records the historical configuration-fixture repair. The
supervisor's 22:45:35 Pacific log shows two completed failed runs: 817 passed and
five failed in each, within the unchanged time limit. The failures all expected
market-layer settings absent from the protected fixture. The affected file now
loads a temporary, non-secret excerpt through the real configuration loader only
in protected execution. Its 11 values/types match the current repository settings
in the separate static check saved in M4_2_LOCAL_CHECKS.json. Ordinary suite runs
still load repository settings. All test bodies, parameters and assertions stay
unchanged; no setting getter, protection or case is weakened. Earlier timeouts
are historical. No passing result for the repaired fixture is claimed.

Retain the entire §64 selection and both required runs. Fresh evidence must cover
the full market-layer test file, all 56 M4.2 cases, all affected existing cases,
matching IDs and recordings, zero failures/errors/skips and clean isolation and
cleanup. Protected supplied-config tests do not prove live configuration; the
saved source comparison is separate, and full release proof remains M18 work.

### Earlier verified selection and its missing coverage

M4_2_VERIFICATION §11 supersedes the historical pending states above. Both protected
runs passed **822 tests**, including all **56 M4.2 cases**, with matching ordered
IDs, zero failures/errors/skips, zero unexpected isolation denials and successful
cleanup. Long and short M4.2 records match byte for byte across runs and stay
below 100,000 bytes. The affected M3.1 and M2.4 records also match. This verifies
the earlier selection only. Review found four omitted compatibility checks for
the shared database initialization. The expanded selection now also requires:

- `tests/test_db_youtube.py::test_init_db_survives_legacy_duplicates`
- `tests/test_db_youtube.py::test_tables_created`
- `tests/test_decision_outcomes_5d_20d.py::test_migration_adds_columns_idempotently_and_preserves_data`
- `tests/test_research_schema.py::test_research_tables_exist`

The repair in M4_2_VERIFICATION §12 required both fresh runs to include these
four cases, all earlier selectors and required recordings. Its local launcher
result and **ready_for_verification** status are historical. The expanded proof
below completes that requirement. Live data, full recovery and profitability
remain with their existing owners.

### Current expanded proof and finalization

The supervisor returned fresh proof at **23:38:41 Pacific** on 2026-09-06.
Both runs passed **826 tests**, in **280.13 and 255.66 seconds**, including all
56 M4.2, 55 M4.1, 54 M3.1 and 46 M2.4 cases and every added database check above.
Ordered IDs match, failures/errors/skips are zero, unexpected isolation denials
are empty and all cleanup checks pass. All 39 published artifact hashes match.

M4.2 long/short recordings are byte-identical across runs at **52,627** and
**52,658 bytes**. Each preserves nine ordered complete entries, fixed scope,
session/configuration/rules, zero extra rows from repeated inputs and identical
records after reopen. The observed states and stale-input candidate removal
match the end-to-end expectations above. The affected M3.1/M2.4 and M4.1
recordings also match across runs. M4_2_LOCAL_CHECKS.json saves their hashes.

All 808 tested file contents matched the supervisor manifest before records-only
finalization; the manifest confirms host ownership for all milestone paths.
Code, tests, configuration, both protection files and the failing-test list remain
unchanged. No test or application was rerun in this session. M4.2 is **completed**
for independent review; ROADMAP §31 saves **M4.3** as proposed next after acceptance.
This closes only the assigned shared transition/storage proof. Earlier source
and definition gates, full strategy/recovery acceptance and profitability remain
with their existing owners.

## 65. M4.3 supplied structural risk acceptance — protected proof complete

`tests/trade_alerts_contracts/test_structural_risk.py` contains the assigned
D-090 §6 contracts. They cover FX-08/09 in both modes, exact outward tick/0.35/
1/1.5/2.5 boundaries in both directions, nearer obstacles, equal-price labels,
missing T1/T2, all seven catalog families, each missing geometry input, unknown/
late/stale/mismatched coverage and features, path-mode mixing, future revisions,
zero ATR versus unknown/zero increment, bad geometry and immutable attribution.
All 105 expanded M4.3 cases passed in both fresh protected runs.

The long/short end-to-end cases use 20 round-tripped supplied Bars, actual M2.2
coverage, M3.1 ATR and M3.6 opening features, then the actual selector and a
round-tripped canonical candidate. Expected R is 0.25, extension is 0.04 and
T1/T2 are 1.88R/3.88R for both directions. Candidate construction, confidence,
complete catalog and path coverage are explicitly synthetic; this does not detect
a strategy trigger or prove actual source completeness. Missing path/catalog and
a later obstacle cannot mutate the earlier candidate.

Use only the unchanged protected launcher with the six selectors in
M4_3_VERIFICATION §3. Require both runs to pass with matching ordered test IDs,
zero failures/errors/skips, no unexpected isolation denials and clean cleanup.
Both must save matching m43-structural-risk-long-proof.json and
m43-structural-risk-short-proof.json, each below 100,000 bytes. Inspect their
actual values, XML, output, summary and isolation records. M4_3_VERIFICATION §8
and M4_3_LOCAL_CHECKS.json save the completed proof: both runs passed 892 tests
with matching IDs, clean isolation/cleanup and byte-identical long/short recordings.

This completes only the supplied-input geometry portion of FR-008/009/010 and
AT-05 after verification. Full structural producers/applicability, actual source
coverage, soft invalidation/runner and dependent strategy acceptance remain
blocked under M4_3_VERIFICATION §4. After offline proof, preserve separate [x]
and required [!] rows and return blocked with independent next_milestone M4.4.
No profit, live readiness or new trading approval follows.

## 66. M4.4 supplied confidence acceptance — protected proof complete

`tests/trade_alerts_contracts/test_confidence.py` checks exact supplied weighted
arithmetic, score bounds and unrounded decimal values, known zero versus missing
values, every required score/factor, zero weights, multiple signed factor versions,
identity/units/definition/mode, source/quality/time, immutable attribution and
canonical candidate/configuration compatibility. All eight strategy identities
use explicitly supplied existing weights and test-only factor policies. No factor
formula, missing-factor policy or scoring threshold is approved by these fixtures.

The long/short end-to-end cases round-trip supplied Bars through actual shared
opening-range calculation, then bind supplied score/contribution snapshots to
that original feature. Actual composition produces 66 from scores 80/60/40 with
weights 0.5/0.3/0.2. Both heads-up and actionable candidate records round-trip.
Missing Context factor means no confidence and prevents candidate construction;
a later score revision gives 100 only for a new result. Earlier candidate bytes
remain unchanged after revision and a separate options-unavailable record. The
score normalization, geometry and candidate assembly are synthetic facts only.

Use only the unchanged protected launcher with the five selectors in
M4_4_VERIFICATION §3. Require two successful runs, matching ordered test IDs,
zero failures/errors/skips, no unexpected isolation denials and clean cleanup.
Inspect actual XML, output, summary and isolation records. The
`m44-confidence-long-proof.json` and `m44-confidence-short-proof.json` recordings
must match across runs and each be below 100,000 bytes. Inspect actual weights,
scores, factor versions/component membership and original feature/config links.

The local ownership-step failure remains historical in
M4_4_LAUNCHER_LIMITATION.txt. Both fresh supervisor runs passed 949 tests,
including all 68 M4.4 cases, with matching ordered IDs, clean isolation/cleanup
and byte-identical long/short recordings. M4_4_VERIFICATION §8 saves the proof.
Retain the separate required full definition/source [!] row in §4 and return
blocked with proposed independent next_milestone M4.5 for review. This closes
only the supplied-composition slice of FR-011/012. Full scoring,
M5 retention, calibration, strategy/data/approval gates and profit remain unproved.

## 67. M4.5 supplied candidate acceptance — protected execution pending

`tests/trade_alerts_contracts/test_candidate_assembly.py` checks both directions
and alert types, all eight strategy identities, explicit supplied geometry and
zero scores, unknown mandatory facts, context/version/configuration/time conflicts,
primary and confidence references, separate suppression, component preservation,
confluence link consistency and before/at/after expiry boundaries. Altered full
confidence results cannot pass. These are consistency checks, not trading rules.

The two end-to-end cases round-trip supplied Bars through the actual shared
opening-range calculation, attach explicitly supplied score/factor snapshots,
run actual M4.4 composition, then actual M4.5 assembly for HEADS_UP and ACTIONABLE.
Expected supplied geometry is R=1 and T1=2R; actual composition is 66 from
80/60/40 and weights 0.5/0.3/0.2. Original components and complete confidence
attribution survive. Expiry checks one microsecond before, at and after the
explicit instant yield false/true/true. A later separate suppression keeps its
explicit reason. Missing confidence produces no candidate and a candidate-less
suppression. A later score revision yields 100 only for a new candidate; earlier
bytes remain unchanged after that revision and separate unavailable options.

The exact protected selection is in M4_5_VERIFICATION §3. Both children must pass
all assigned and compatibility tests with matching ordered IDs, zero failures/
errors/skips, no unexpected isolation denials and successful cleanup. Require
byte-identical `m45-candidate-assembly-long-proof.json` and
`m45-candidate-assembly-short-proof.json` across runs, each below 100,000 bytes.
Inspect actual XML, output, summary, isolation, candidate fields and full supplied
links. Compilation and written assertions are not passing evidence. A fresh
builder receiving supervisor proof must finish evidence/roadmap without code or
test changes before returning completed for independent review.

This closes only the M4.5 common candidate/expiry/suppression-link consistency
portion of FR-006/016/017. Full AT-05/06/07/09/14 strategy, portfolio, durability,
delivery and outcome acceptance remain with their original owners. All switches
stay off; synthetic examples establish neither provider coverage nor returns.

## 68. M4.6 offline renderer and delivery acceptance — primary repair proof complete

`tests/trade_alerts_contracts/test_alert_delivery.py` contains 130 cases, all passing
in both fresh protected runs recorded in M4_6_VERIFICATION §13. The prior
77-case supervisor proof predates the component-link repair. It covers complete frozen rendering in both
alert types/directions, missing/zero facts, oversized/malformed input, mention/
markup safety, Pacific dates, absent/poor options without loss of stock validity,
assembly/session attribution, recording defaults, unavailable live mode, expiry,
failed persistence, temporary-database rollback, full fallback, partial/unknown
receipts, provider-directed retry, response errors, cancellation and uncertain
acknowledgment storage. Existing sender/renderer tests protect old callers.

Both end-to-end cases round-trip supplied Bars through actual history coverage,
opening-range calculation, confidence composition and candidate assembly. The
new boundary then retains the full assembly before recording or fake transport.
Expected width is 10, supplied risk/share is 1, target is 2R and quality is 66.
For both heads-up and actionable candidates, fake rich rejection uses the exact
complete plain text; a successful fake receipt has two attempts. A partial
legacy ID stays UNKNOWN, exact expiry sends nothing, and absent options do not
change stock validity or original bytes. No fixture is source-coverage, live
notification, trading-rule or profitability evidence.

Use only the unchanged protected launcher with every selector in
M4_6_VERIFICATION §3. Require two successful runs, matching ordered IDs, zero
failures/errors/skips, no unexpected isolation denials and successful cleanup.
Read actual XML, output, summary and isolation files. Both runs must produce
byte-identical `m46-alert-delivery-long-proof.json` and
`m46-alert-delivery-short-proof.json`, each below 100,000 bytes. Inspect their
prices, quality, option status, sink, full fallback and receipt results.

The local launcher stopped before collection at its initial ownership step;
M4_6_LAUNCHER_LIMITATION.txt and M4_6_LOCAL_CHECKS.json save the exact result.
That ready_for_verification state is historical. Both supervisor runs passed
1,140 tests, including all 77 M4.6 cases, with matching ordered IDs, zero failures,
errors or skips, and clean isolation/cleanup. The long and short recordings match
across runs at 25,813 and 25,850 bytes. M4_6_VERIFICATION §§7–8 and
M4_6_LOCAL_CHECKS.json record the inspected proof and records-only finalization.
Code, tests and protection matched that earlier tested manifest before the repair.
The component-link repair is complete and has fresh protected proof. Both fresh
supervisor runs passed 1,145 tests, including all 82 M4.6 cases, with matching
ordered IDs, zero failures/errors/skips, clean isolation/cleanup and byte-identical
updated long/short recordings (26,915 and 26,966 bytes). Delivery now rechecks
missing/mismatched linked components before storage or send and preserves valid
linked and unlinked components; both kinds appear in the saved delivery intent in
both end-to-end recordings. See M4_6_VERIFICATION §10. The earlier 1,140-test,
77-case proof and the §9 ready state are historical. Full storage/recovery and
notification proof remain M5.1/M5.5/M9/M15/M17. The separate M4.7 definition gate
stays blocked; proposed independent next milestone is M5.1 within M4_6_VERIFICATION
§5.

### Current primary-attribution repair

M4_6_VERIFICATION §12 supersedes the previous completion status above. The 48
new cases cover strategy/version, symbol/type, absent primary feature, dropped
primary/confidence links, unknown input, reused input ID, creation time, delivery
status and altered full confidence result, in both directions and alert types.
Each requires RecordError with neither storage callback nor transport called.
The primary feature and confidence snapshot are distinct so each missing-link
case exercises its own dependency. Both long/short end-to-end recordings retain
all twelve rejected paths per alert type, with zero stored records and zero sends.

The previous 1,145-test/82-case proof predates this repair. Require the unchanged
full §3 selection twice, now including all 130 M4.6 cases, matching ordered IDs,
zero failures/errors/skips, clean isolation/cleanup and byte-identical expanded
recordings below 100,000 bytes. The local launcher stopped before collection;
no passing result is claimed. Status is ready_for_verification; M5.1 remains the
proposed next milestone after fresh proof, records-only finalization and review.

### Finalized primary-attribution proof

M4_6_VERIFICATION §13 supersedes the pending state above. Fresh proof returned at
22:03:30 Pacific on 2026-09-07 passed **1,193 tests in each run**, including all
**130 M4.6 cases** and **48 primary-attribution rejection cases**. The full §3
selection ran unchanged. Ordered IDs match, failures/errors/skips are zero,
isolation has no unexpected denials and all cleanup checks pass.

The expanded long/short recording pairs are byte-identical at **28,043/28,094
bytes**. Each direction contains both alert types and twelve rejected alterations
per alert type with zero stored records and zero sends. Frozen geometry, quality,
component links, complete fallback, unavailable options, unknown receipts and
expiry results remain intact. All 55 published hashes and all 828 tested file
contents matched before records-only finalization; code/tests/protection are
unchanged. M4_6_LOCAL_CHECKS.json saves the inspected checks and proof hashes.

The assigned offline M4.6 gate is complete for independent review. M5.1 remains
next under M4_6_VERIFICATION §5; M4.7 and all earlier required blocked branches
remain open. Full recovery, actual sources and notification evidence remain with
their existing owners. No live access or profitability is established.

## M5.1 storage acceptance

The M5.1 contract tests run the normal offline temporary-database pattern:
inject `consensus_engine.event_store.ResearchEventStore` over the real existing
migration and transaction machinery, store a fully assembled M4.5 candidate and
its complete supplied attribution, then verify typed kinds, append-only
idempotent replay, conflicting id/fingerprint and link-kind rejection, atomic
rollback (forced-trigger leaves no row), deterministic reopen preservation, and
the injected save_intent/save_result delivery boundary. Selectors include the
new event-store file plus the existing alert-delivery, candidate-assembly,
state-transition, confidence, domain and strategy-interface contracts, and the
migration-idempotency, market-layer-schema and specified schema/migration
compatibility cases. The two unrelated listener tests with unfaked reaction
requests remain the saved M18.4 isolation gap. A passing store is not a strategy,
delivery, recovery, data-realization or profitability claim.


The repair acceptance below was finalized in M5_1_VERIFICATION section 9.
Its pending states describe the historical pre-proof handoff.
M5.1 repair acceptance is M5_1_VERIFICATION section 7. The 21 written
cases must pass twice under unchanged protection, including forward/reverse and
same-bundle conflicts, complete attribution, identical history/assembly/result
retries, refused repeated intents and competing store owners. Require identical
m51-research-event-store-long-proof.json and
m51-research-event-store-short-proof.json across runs, each below 100,000 bytes.
Inspect original supplied geometry/quality, components, missing options, recording
receipt, stored fingerprints and link status. No earlier local simulation is
protected proof. All section 4 selectors, including added research-table and core
database checks, remain required. Current status is ready_for_verification.


M5_1_VERIFICATION section 8 records the 2026-09-08 Pacific schema-expectation
repair handoff. The foundation test now expects exact versions 7 through 36;
its explicit selector joins the unchanged full selection. The controller's
1,244-pass summary is not readable two-run proof. The fresh local launcher stops
before collection at os.chown; no passing result is claimed. Status remains
ready_for_verification, with M5.2 proposed only after proof and independent review.
All section 7 long/short recordings and prior blocked gates remain required.

### M5.1 finalized protected proof

M5_1_VERIFICATION §9 supersedes the pending states above. Both fresh protected
runs passed **1,245 tests**, including all **21 M5.1 cases** and the exact
versions-7-through-36 foundation assertion. The complete saved selection ran;
ordered IDs match, failures/errors/skips are zero, isolation has no unexpected
denials and cleanup passed. All 59 published hashes and 833 tested file contents
matched before records-only finalization. Code, tests and protection are unchanged.

Long/short recordings match at **11,304/11,325 bytes**. Each retains 20 rows,
full assembly attribution and exact reopen equality. Geometry is risk/share 1
and target 2R, quality is 66, options remain unavailable and the recording sink
makes zero send attempts. Complete supplied links resolve; the separate missing
link test retains unavailable status until the compatible input is supplied.
M5_1_LOCAL_CHECKS.json saves hashes and inspected results. This completes the
assigned common storage proof for independent review; M5.2 is proposed next.
Full recovery, actual-source, options/portfolio and profitability gates remain
with their existing owners. All switches remain off.


### Historical M5.1 primary-feature review repair — pre-proof handoff

M5_1_VERIFICATION section 10 supersedes the completion status above. The earlier
1,245-test proof predates the source repair and is historical. There are now 33
written storage cases: all 21 prior cases plus twelve tests of wrong stock, type
and session, in both insertion orders, through append and atomic bundle writes.
Both long/short pipelines record all six append rejection paths and exact reopen
preservation. No passing repair result is claimed.

Run the unchanged protected launcher twice with every M5_1_VERIFICATION section 4
selector, now also including
`tests/test_batch2_trade_tracking.py::test_storage_retries_keep_stable_entity_ids_without_duplicate_facts`
and `tests/test_batch2_trade_tracking.py::test_batch2_fact_tables_reject_update_and_delete`.
Require matching ordered test IDs, zero failures/errors/skips, clean isolation and
cleanup, all 33 storage cases and matching expanded long/short recordings below
100,000 bytes. Inspect the six rejection outcomes in each recording. Keep M5.1
unfinished until fresh proof, records-only finalization and independent acceptance.
Saved proposed next_milestone remains M5.2; all earlier required gates stay open.

M5_1_VERIFICATION section 11 preserves the supplied test-only import isolation
fix in tests/test_batch2_trade_tracking.py. The unrelated gate helper is imported
only within its three gate tests; both required storage selectors and all their
assertions are unchanged. Neither protection file changes. The complete saved
selection, all 33 storage cases and both expanded recordings still require two
fresh protected runs. The local launcher stopped before collection; no passing
repair result is claimed. Historical proof cannot close this current gate.

M5_1_VERIFICATION section 13 records the supplied Batch 2 test setup repair:
one database setup retains all ten update/delete checks across five tables.
Only that test function differs from the prior saved hash; both protection files
and the other five source/test hashes match. The latest supervisor first child
again exceeded 300 seconds; detailed logs returned Permission denied. The local
launcher stopped before collection. No passing result or time saving is claimed.
Status remains ready_for_verification, with proposed next_milestone M5.2 after
fresh complete proof, records-only finalization and independent review.


M5_1_VERIFICATION section 14 records the latest supplied identity-test setup
repair. All twelve identity checks now share two database setups, yielding 23
reported storage cases; both expanded recordings retain six rejection paths.
The latest supervisor log reports 1,259 passes in its first run and a second-run
300-second timeout. That incomplete proof predates verification of the supplied
repair. The local launcher stopped before collection at os.chown. No passing
current repair result is claimed. Require two fresh complete protected runs and
matching recordings. Status remains ready_for_verification; proposed
next_milestone remains M5.2 after proof, records-only finalization and review.


### Current M5.1 repaired protected proof — finalized

M5_1_VERIFICATION section 15 supersedes the pending repair states above.
Both fresh protected runs passed **1,249 tests**, including all **23 storage
cases**, the two tests containing twelve identity checks, both required Batch 2
storage checks and the exact schema-version assertion. All section 4 selectors
are covered by the directory and explicit selections. Ordered IDs match; failures,
errors and skips are zero; isolation and cleanup passed.

Expanded long/short recordings match at **12,092/12,113 bytes**. Each retains
all six primary-feature rejection paths, unchanged original facts, absent
rejected rows and exact reopen equality before and after rejection. The original
20-row pipeline preserves full assembly, resolved supplied links, risk/share 1,
target 2R, quality 66 and unavailable options. Recording makes zero send attempts.
All 59 published hashes and all 833 tested contents matched before records-only
finalization. M5_1_LOCAL_CHECKS.json saves the inspected results and hashes.
Code, tests and protection remain unchanged; independent acceptance review remains.

No required gate remains for the assigned common storage mechanism. M5.5 retains
full recovery, M5.2 is proposed next under section 7's adopted O-01 scope, and
all earlier required source/definition gates stay open. No live access, source
coverage, new trading rule or profitability is established by this proof.

## 70. M5.2 supplied-bar outcome acceptance — protected proof finalized

M5_2_VERIFICATION section 16 is current. Earlier protected results below are
historical after the exact-boundary repair. The fresh 420-second protected proof
is finalized; the separate required source/definition gate remains blocked.

### Historical first proof

M5.2 implements only D-090 O-01's `BAR_ONLY_ORB5_O1_PROXY` against supplied,
complete regular-session one-minute Bars. M5_2_VERIFICATION records 15 written
cases for mirrored outcomes, two equal units, T1/T2 or close handling, gaps,
stop-after-T1, conservative same-bar ambiguity plus unresolved sensitivity,
MFE/MAE/max R and hit times, missing coverage, invalid entry geometry, canonical
append-only storage and compact end-to-end recordings.

Both fresh protected runs passed **1,216 tests**, including all **15 M5.2
outcome-evaluator cases**, in 273.10 and 266.97 seconds. Ordered test IDs match;
failures, errors and skips are zero; isolation and cleanup passed. Long/short
recordings match byte for byte across runs at **10,890/10,891 bytes**. All
section 4 selectors are covered. The local ownership error in
M5_2_LAUNCHER_LIMITATION.txt remains historical. M5_2_VERIFICATION section 7 and
M5_2_LOCAL_CHECKS.json save the inspected proof. This completes the assigned
offline supplied-bar outcome scope for independent review.

Actual source coverage and unfinished costs, borrow and statistical terms remain
separate required gates; synthetic cases do not establish executable profit.
Proposed next milestone remains M5.3, after independent acceptance.

M5_2_VERIFICATION section 8 corrects the overall handoff to **blocked**. Keep
the finished offline [x] row and the required source/definition [!] row. The
1,216-test proof is unchanged; all source/tests/protection match the tested
manifest. Proposed independent next_milestone is **M5.3**, within section 8,
after the reviewer validates this blocked handoff.


### Historical M5.2 review repair handoff

M5_2_VERIFICATION section 9 records all-target open/range handling, the strict
07:15 Pacific entry/availability boundary, and no later exits across missing
coverage. Full entry/unit-exit/ambiguity/status details now persist atomically
beside canonical outcomes. Mirrored recording tests compare every stored row
after actual database close/reopen for resolved, ambiguous and partial cases.
Require section 4's selection twice through the unchanged protection, matching
ordered IDs, clean isolation/cleanup and matching compact recordings. The local
launcher stopped before collection with `OSError: [Errno 22] Invalid argument`.
Status is ready_for_verification for the offline repair. The separate required
source/definition gate remains [!]; after successful offline proof return
blocked for that gate with proposed independent M5.3, subject to acceptance.
The controller must not advance before repaired M5.2 acceptance.


### Historical M5.2 repaired proof

M5_2_VERIFICATION section 10 records the proof supplied at **13:55:36 Pacific**
on 2026-09-08. Both protected runs passed **1,242 tests**, including all **41
M5.2 cases** and both required Batch 2 storage checks, with matching ordered IDs,
zero failures/errors/skips and clean isolation/cleanup. All section 4 selectors
are covered. All 63 published hashes and 838 tested contents matched before
records-only finalization. Code, tests, configuration and protection are unchanged.

Expanded long/short recordings match at **52,342/52,348 bytes**. They prove actual
assembly, evaluation, atomic storage and full row equality after database reopen
for resolved, ambiguous and partial outcomes. Both open/range targets resolve to
2.5R; competing stop/target keeps conservative -1R and unresolved sensitivity;
missing coverage retains earlier exits without inventing a resolved total.
Entry at 07:15 Pacific stays unavailable. These are synthetic checks only.
M5_2_LOCAL_CHECKS.json records hashes and inspected results.

Retain M5.2's finished offline [x] row and required source/definition [!] row.
Overall status is **blocked**, with independent next_milestone **M5.3** limited
to the supplied-record runner in M5_2_VERIFICATION section 8, subject to reviewer
validation. Actual compatible history and remaining adopted cost/borrow/statistical
terms still require that section's supervised reopening proof. No source coverage,
after-cost profit, new rule or live authority is established. All switches stay off.

### Current original-risk proof repair

The prior example used equal actual and original entry prices. The new mirrored
long/short test moves the modeled entry, proves different actual-entry and
original-entry R figures, stores both, closes and reopens the database, and
checks the saved values. Existing trailing certified-no-trade tests require an
observed final closing bar before a session-close exit can resolve remaining
units. Require the full section 4 selection twice under unchanged protection.
Current offline status is **ready_for_verification**. Proposed next milestone
remains M5.3 only after fresh proof and review; the required source/definition
row remains `[!]`.

The supervisor's next protected runs found that the new moved-entry test supplied
open 100.20 with high 100.10. Both directions therefore failed the record's OHLC
geometry check; 1,244 other cases passed. The fixture now sets high to 100.20 and
preserves the intended different actual-entry and original-entry R figures. Static
Python compilation passed. A 22:18 Pacific full-selection attempt then stopped
before collection at the unchanged launcher's initial ownership operation with
exit code 1 and no artifact path. Exact output is in
M5_2_LAUNCHER_LIMITATION.txt and M5_2_VERIFICATION section 13. Fresh supervisor
execution remains the sole offline verification step.

The next fresh protected runs exposed a second issue: the valid 1.50R remaining-
room boundary rounded slightly below 1.50 and returned UNFILLED. The evaluator
now uses exact decimal comparisons for the approved inclusive 1.50R room and
0.35 extension limits. The original-risk expectations remain unchanged. Static
compilation passed. The unchanged launcher stopped before collection at 22:34
Pacific during its initial ownership operation; M5_2_VERIFICATION section 14
and M5_2_LAUNCHER_LIMITATION.txt save the exact result. Fresh protected proof is
still the sole remaining offline step.

### Finalized 420-second protected proof

Both fresh protected runs with the verified 420-second limit passed **1,246
tests** in **306.46 and 305.01 seconds**, including all **45 M5.2 cases** and
both required Batch 2 storage checks. Ordered test IDs match; failures, errors
and skips are zero; isolation and cleanup pass. D-091 remains $0 used. Expanded
long/short recordings are byte-identical at **52,588/52,594 bytes**. The
evaluator uses exact decimal values for the approved inclusive 0.35 extension
and 1.50 remaining-room boundaries. All 63 published hashes matched before this
records-only finalization. M5_2_VERIFICATION section 16 and
M5_2_LOCAL_CHECKS.json save the proof. The required actual-source and
executable-profit gate remains open; proposed next_milestone stays **M5.3**,
subject to independent review.

### Current M5.2 exact-extension repair

The reviewer found that the exact extension value was compared with the binary
float `0.35`, which rejected the approved inclusive boundary. The comparison now
uses `Fraction("0.35")`. Four protected cases cover exact and just-over values in
both directions. Fresh protected proof is the sole remaining offline step.
Status is **ready_for_verification**. The required actual-source and executable-
profit gate remains open; proposed next_milestone stays **M5.3** after proof and
review.

### Current M5.2 exact-boundary fixture repair

The four exact-extension cases previously changed a frozen target price without
changing its matching R multiple. The canonical candidate rejected that invalid
geometry before the evaluator ran. The helper now updates both values together,
leaving a valid candidate that isolates exact 0.35 and just-over-0.35 entries in
both directions. Production code is unchanged by this fixture repair.

Python compilation, JSON syntax and scoped whitespace checks passed. The
unchanged protected launcher stopped before collection at its initial `os.chown`
with `OSError: [Errno 22] Invalid argument`. Fresh protected proof remains the
sole offline step. Status is **ready_for_verification**. The required source and
definition gate remains open, and proposed next_milestone remains **M5.3** after
proof and independent review.

### Current M5.2 decimal target fixture repair

The supervisor's two fresh runs collected 1,250 tests and reported 1,248 passes.
The exact 0.35 long and short cases still failed because binary decimal math made
their intended 1.50R target slightly too close. The fixture now builds entry,
risk and target with exact decimal values before supplying ordinary numeric
prices. It also keeps the target price and R multiple consistent.

Python compilation, JSON syntax and scoped whitespace checks passed. The
unchanged protected launcher stopped before collection at its initial `os.chown`
with `OSError: [Errno 22] Invalid argument`. Fresh protected proof remains the
sole offline step. Status is **ready_for_verification**. The required source and
definition gate remains open, and proposed next_milestone remains **M5.3** after
proof and independent review.

### Final M5.2 decimal fixture proof

The fresh supervisor record supplied at **00:32:11 Pacific** on 2026-09-09
supersedes the pending proof state above. Both protected runs passed **1,250
tests** in **304.67 and 306.15 seconds**, including all **49 M5.2 cases** and
both required Batch 2 storage checks. Ordered test IDs match. Failures, errors
and skips are zero. Isolation and cleanup passed with no unexpected denials.

Long and short outcome recordings are byte-identical across runs at **52,588
and 52,594 bytes**. The tested evaluator, fixture, protected launcher and child
hashes match the supplied manifest. M5_2_VERIFICATION section 20 and
M5_2_SUPERVISOR_TESTS.json save the checked result.

The offline supplied-bar evaluator row is complete. The separate required
actual-source and executable-profit row stays blocked. Synthetic bars do not
establish actual coverage or profitability. Proposed next milestone remains
**M5.3**, limited to the independent supplied-record runner after review. All
switches remain off.

## 71. M0.3C offline evidence policy — `M03C_HOD_COMP_RS_V1`

The owner's 2026-09-13 delegation authorizes the finite offline evidence rules
in [M0_3C_DEFINITION_PACKET.md](./M0_3C_DEFINITION_PACKET.md). Incorporate §8
under this document's evidence authority. Before replay, tests must cover the
non-overlapping three/seven boundary, three-to-eight-bar seed and extension,
point-in-time HOD/LOD freeze, 15-bar warm-up, exact long/short mirrors, crossing,
seven-of-ten acceptance, separate tape/projected modes, stop rounding, 1.5R and
2.5R targets, inclusive 0.40R staleness, score missingness and adverse event
ordering.

Each direction and data mode reports after-cost expectancy, win rate, payoff
ratio, maximum drawdown and candidate frequency with counts and denominators.
Keep the score-threshold arm separate from all mechanical candidates. Preserve
losing, unknown, unfilled, unresolved and short-borrow-blocked rows. A bar-only
arm stays labeled `BAR_PROXY / MODELED_COST_ONLY`; it cannot prove the sub-minute
trigger. Stock and option evidence remain separate.

Exact development, calibration and untouched final dates require a qualifying
coverage-only source manifest recorded before results are opened. Written
definitions and synthetic boundary checks do not satisfy that gate, validate an
edge or authorize live use.

## 72. M0.3D offline evidence policy — `M03D_OR_FAILURE_REV_V1`

The owner's 2026-09-13 delegation authorizes the finite offline evidence rules
in [M0_3D_DEFINITION_PACKET.md](./M0_3D_DEFINITION_PACKET.md). Incorporate §9
under this document's evidence authority. Before replay, tests must cover the
buffered crossing, exact 0.10 ATR excursion, crossing-based 180-second deadline,
strict inside close, frozen failure bar, exact long/short mirrors, seven-of-ten
inside acceptance, separate tape/quote modes, separate close/bar-break arms,
ORB ownership transfer, catalyst-continuation missingness, stop rounding,
structural target priority, inclusive 0.40R staleness, score missingness and
adverse event ordering.

Report the 24 direction/confirmation/data-mode/exit-policy arms separately by
after-cost expectancy, win rate, payoff ratio, maximum drawdown and candidate
frequency, with counts and denominators. Keep the score-threshold arm separate
from all mechanical candidates. Preserve losing, late, unknown, unfilled,
unresolved and short-borrow-blocked rows. A bar-only arm stays labeled
`BAR_PROXY / MODELED_COST_ONLY`; it cannot prove the sub-minute trigger. Stock
and option evidence remain separate.

Exact development, calibration and untouched final dates require a qualifying
coverage-only source manifest recorded before results are opened. Written
definitions and synthetic boundary checks do not satisfy that gate, validate an
edge or authorize live use.

## 73. M0.3E offline evidence policy — `M03E_FIRST_PULLBACK_VWAP_V1`

The owner's 2026-09-13 delegation authorizes the finite offline evidence rules
in [M0_3E_DEFINITION_PACKET.md](./M0_3E_DEFINITION_PACKET.md). Incorporate §§9–10
under this document's evidence authority. Before replay, tests must cover the
ordered impulse, exact two-bar swing confirmation, independent structure count,
first/second/third priority treatment, exact long/short mirrors, 0.20/0.65/0.70
retracement boundaries, duration-normalized volume, three-minute VWAP slope,
strict close-cross counting, support boundaries, reversal-bar crossing, stop
rounding, structural target priority, fixed 2R and fixed 3R exits, inclusive
0.40R staleness, score missingness and adverse event ordering.

Report all 18 direction/priority/ordinal/exit cells separately, crossed with the
five delays, two score populations and two stock-slippage assumptions for the
frozen family of 360 primary comparisons. Use the 10-session circular moving-
block bootstrap and the preregistered `1 / 7200` family threshold. Each cell
reports after-cost expectancy, win rate, payoff ratio, maximum drawdown and
candidate frequency with counts and denominators. Keep the score-threshold arm
separate from all mechanical candidates. Preserve losing, deep-refused,
suppressed, unknown, unfilled, unresolved and short-borrow-blocked rows. A
bar-only arm stays labeled
`BAR_PROXY / MODELED_COST_ONLY`; it cannot prove the sub-minute trigger. Stock
and option evidence remain separate.

Exact development, calibration and untouched final dates require a qualifying
coverage-only source manifest recorded before results are opened. Written
definitions and synthetic boundary checks do not satisfy that gate, validate an
edge or authorize live use.

## 74. M0.3F offline evidence policy — `M03F_INDEX_OPEN_DRIVE_BREADTH_V2`

The owner's 2026-09-13 delegation authorizes the finite offline evidence rules
in [M0_3F_DEFINITION_PACKET.md](./M0_3F_DEFINITION_PACKET.md). Incorporate
§§9–10 under this document's evidence authority. Before replay, tests must cover
all four BreadthScore components, score values below and at 60, exact mirrored
short treatment, full/proxy/hybrid mode identity, every coverage boundary,
missing-component refusal, the drive path denominator and its zero case, the
120-second minimum, 0.55 efficiency, three-minute VWAP slope, 0.35/0.40
retracement roles, ten-second acceptance, warning, reduced-priority and both
suppression rules, stop rounding, targets, fixed 2R and 3R exits, staleness,
score missingness and adverse event ordering.

V2 also requires packet §10 examples 11–13: completed-bar HLC3 weighting and
missing-bar refusal with no trade-VWAP fallback; session-to-evaluation Up Volume
using each trade's own shares against its immediate predecessor; neutral
opening/tied prices; long/short numerators with one shared denominator; as-of
cancels/corrections, duplicate removal, equal-time ordering, certified empty
intervals, unexplained gaps and evaluation-time boundaries. A cumulative member
volume classified by its last price cannot satisfy this contract. The previous V1 controller runs are historical proof only. The repaired version
passed its protected focused stage, required broader selection and two fresh
repeatability runs. M0_3F_VERIFICATION.md records the published figures and
artifacts; independent review decides acceptance.

Report the 36 direction/breadth-mode/priority/exit cells separately, crossed
with five delays, two score populations and two stock-slippage assumptions for
the frozen family of 720 primary comparisons. Use the 10-session circular
moving-block bootstrap and preregistered `1 / 14400` family threshold. Each cell
reports after-cost expectancy, win rate, payoff ratio, maximum drawdown and
candidate frequency with counts and denominators. Keep SPY, QQQ, IWM and DIA
rows separate, and preserve losing, warning, reduced, suppressed, unknown,
unfilled, unresolved and short-borrow-blocked rows.

Full and hybrid cells remain unavailable until their point-in-time membership
and coverage gates pass. A sector-proxy result cannot be relabeled full breadth.
A bar-only arm stays labeled `BAR_PROXY / MODELED_COST_ONLY`; it cannot prove
the sub-minute trigger. Stock and option evidence remain separate. Exact
development, calibration and untouched final dates require a qualifying
coverage-only source manifest recorded before results are opened. Written
definitions and synthetic checks do not validate an edge or authorize live use.

## 75. M0.3G offline evidence policy — `M03G_GAP_FADE_FAILED_OPEN_V1`

The owner's 2026-09-13 delegation authorizes the finite offline evidence rules
in [M0_3G_DEFINITION_PACKET.md](./M0_3G_DEFINITION_PACKET.md). Incorporate
§§9–10 under this document's evidence authority. Before replay, tests must cover
the 1% and 0.25 ATR gap boundaries, all three scheduled opening minutes,
certified no-trade and unexplained gaps, exact extension equality, point-in-time
extreme freeze, strict loss of open, VWAP equality, temporary bounce versus
reclaim, the inclusive 180-second reclaim deadline, and exact long/short mirrors.

Tests must also cover same-instant stock-minus-SPY returns and zero, the frozen
first-three-minute crossing, nonpositive/nonnegative VWAP-slope mirrors, catalyst
classes A/B/C/D, the 15- and 30-point penalties, missing catalyst coverage,
0.35 gap-fill staleness, opening/reclaim stop precedence, outward rounding,
structural targets, fixed 2R and fixed 3R exits, score missingness, ownership
with `OR_FAILURE_REV` and adverse event ordering.

Report the 24 direction/catalyst-class/exit cells separately, crossed with five
delays, two score populations and two stock-slippage assumptions for the frozen
family of 480 primary comparisons. Use the 10-session circular moving-block
bootstrap and preregistered `1 / 9600` family threshold. Each cell reports
after-cost expectancy, win rate, payoff ratio, maximum drawdown and candidate
frequency with counts and denominators. Preserve losing, suppressed, stale,
unknown, unfilled, unresolved and short-borrow-blocked rows.

Keep the score-threshold arm separate from all mechanical candidates. A bar-only
arm stays labeled `BAR_PROXY / MODELED_COST_ONLY`; it cannot prove the trade
crossing, reclaim order, point-in-time catalyst or quote-side fills. Stock and
option evidence remain separate. Exact development, calibration and untouched
final dates require a qualifying coverage-only source manifest before results
are opened. Written definitions and synthetic checks do not validate an edge or
authorize live use.

## 76. M0.3H offline evidence policy — `M03H_CAT_FIRST_CONSOL_V1`

The owner's 2026-09-13 delegation authorizes the finite offline evidence rules
in [M0_3H_DEFINITION_PACKET.md](./M0_3H_DEFINITION_PACKET.md). Incorporate
§§9–10 under this document's evidence authority. Before replay, tests must cover
point-in-time catalyst receipt and correction, exact A/B/C/D classes and
direction, material and contradictory news, proven no-event versus unknown
coverage, the 30-minute freshness boundary and the class-C abnormality diagnostic.

Tests must also cover the post-receipt reaction start, regular-session impulse
threshold, two-bar extreme confirmation, first-versus-later consolidation,
two-through-eight-bar duration, exact 0.50/0.65 depth roles, range and volume
ratios, ten fixed one-second samples, seven-of-ten acceptance, mirrored crossing,
VWAP side, stop rounding, targets, fixed 2R and fixed 3R exits, 0.35R staleness,
score missingness, `HOD_COMP_RS` ownership and adverse event ordering.

Report the 36 direction/catalyst-population/depth/exit cells separately, crossed
with five delays, two score populations and two stock-slippage assumptions for
the frozen family of 720 primary comparisons. Use the 10-session circular moving-
block bootstrap and preregistered `1 / 14400` family threshold. Each cell reports
after-cost expectancy, win rate, payoff ratio, maximum drawdown and candidate
frequency with counts and denominators. Keep A, B and C-diagnostic rows and
primary/deep rows separate. Preserve losing, suppressed, stale, later-
consolidation, unknown, unfilled, unresolved and short-borrow-blocked rows.

Keep the score-threshold arm separate from all mechanical candidates. A bar-only
arm stays labeled `BAR_PROXY / MODELED_COST_ONLY`; it cannot prove catalyst
timing, the trade crossing, ten-second acceptance or quote-side fills. Stock and
option evidence remain separate. Exact development, calibration and untouched
final dates require a qualifying coverage-only source manifest before results
are opened. Written definitions and synthetic checks do not validate an edge or
authorize live use.

## 77. M0.3I offline evidence policy — `M03I_VP_ACCEPT_LVN_V1`

The owner's 2026-09-13 delegation authorizes the finite offline evidence rules
in [M0_3I_DEFINITION_PACKET.md](./M0_3I_DEFINITION_PACKET.md). Incorporate
§§8–10 under this document's evidence authority. Before replay, tests must cover
true-trade and bar allocation, conservation of volume, zero-origin bin
boundaries, tick rounding for all three widths, edge smoothing, VPOC and
value-area ties, percentile ranks, shelf boundaries, LVN width, adjacency and
next-HVN selection.

Tests must also cover the two sensitivity IoUs and 0.60 boundary, zero prior LVN
volume, every refill boundary, 90 fixed samples and the 0.70 boundary, final-bar
close, mirrored value and LVN crossings, fourth-total-cross kill, VWAP side, RVOL,
0.35 traversal staleness, stop precedence and rounding, structural/fixed exits,
score missingness, matched-control tie order and adverse event ordering.

For the crossing kill, packet §5 and boundary example 10 count the first
buffered break as crossing 1, then each later strict-side change of the frozen
unbuffered VAH/VAL once. Cover counts 1, 2 and 3 without this kill, immediate
termination at count 4 before any same-event LVN trigger, and no increment for
equality, same-side trades or duplicate observations. Cover both directions;
do not restart the count after the first break.

Report the 72 direction/profile-mode/width/cohort/exit cells separately, crossed
with five delays, two score populations and two stock-slippage assumptions for
the frozen family of 1,440 primary comparisons. Use the 10-session circular
moving-block bootstrap and preregistered `1 / 28800` family threshold. Each cell
reports after-cost expectancy, win rate, payoff ratio, maximum drawdown and
candidate frequency with counts and denominators. Report stability, refill and
volume-acceleration strata separately. Preserve losing, suppressed, stale,
unstable, zero-prior-volume, unknown, unmatched, unfilled, unresolved and
short-borrow-blocked rows.

Keep the score-threshold arm separate from all mechanical candidates. A bar-only
arm stays labeled `BAR_PROXY / MODELED_COST_ONLY`; it cannot prove sub-minute
acceptance, LVN crossing or quote-side fills. True and approximate profiles and
stock and option evidence remain separate. Exact development, calibration and
untouched final dates require a qualifying coverage-only source manifest before
results are opened. Written definitions and synthetic checks do not validate an
edge or authorize live use.

## 78. M3.3 supplied-input relative-strength checks

Protected checks must cover the hand-calculated first-15-minute stock-minus-SPY
value, the exact 15-minute warm-up boundary and the fact that the value stays
fixed afterward. Missing, provisional, revised, no-trade, wrong-unit, wrong-type,
wrong-session and incompatible-adjustment inputs must stay unavailable.

From-open checks must cover stock versus SPY, QQQ and sector independently, exact
zero, missing mapping, missing references, original opening-trade delay, current
trade freshness at and beyond three seconds, future availability and immutable
serialization. The recording must pass through canonical Bar coverage and the
real feature builder. These supplied synthetic records prove only the offline
calculation; they do not prove source coverage, an edge or live readiness.

## 79. M4.7 AT-08/AT-09 supplied-record checks

`M47_FIRST4_RESEARCH_V1` in M4_7_DEFINITION_PACKET section 6 is the frozen
evidence contract. AT-08 must cover ordinary and strict-0DTE equality,
stale/future times, wrong or unknown units/identity/standardness, the pre-filter
IV median, every score factor, full ties, incomplete chains, missing possibly
eligible delta, known poor rows and unchanged stock validity.

AT-09 must cover literal UTF-8 fingerprints, reordered input IDs, semantic
identity collision, research-arm and source isolation, reordered complete
batches, incomplete-batch refusal, original-anchor rather than chained grouping,
simultaneous priority, uncalibrated opposite-side conflict, exact checked
ORB-to-failure release, wrong symbol/session/parent rejection, producer quotas,
600-second equality, intent expiry before/at/after and restart without deadline
extension. Run deterministic recording in two fresh protected processes.

Passing supplied records proves the software contract only. It does not prove
complete source chains, units, executable fills, calibration, profit, shadow or
live readiness.

## 80. M0.2G chronological split admission

The fixed split remains 60% development, 20% calibration and the remainder
untouched final validation over an ascending immutable covered-session list.
Before any strategy result is read, the source record must publish every
qualifying symbol/date row and one fingerprint for the complete qualifying
manifest.

`M0_2G_COVERAGE_ONLY_MANIFEST.json` records 22,958 observed ETF
dataset/symbol/date inventory rows but zero qualifying rows. Its exact
qualifying-row list is empty, its qualifying-manifest fingerprint is null and
all three date lists are null. Opening-window presence cannot replace missing
stock, tape, correction, point-in-time or untouched-final facts. No replay,
calibration or final-validation access is admitted by M0.2G.
