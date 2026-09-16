# ROADMAP.md

## 1. Purpose

This document defines the dependency-ordered implementation roadmap for the intraday human-in-the-loop trading alert system.

It converts `MASTER_SPEC.md` and supporting canonical documents into discrete implementation milestones suitable for many fresh Codex sessions.

It governs build order, milestone boundaries, dependencies, acceptance criteria, testing, and progress tracking. It does not redefine strategy logic, data availability, validation standards, or coding conventions.

## 2. Roadmap Principles

- Build infrastructure before strategy proliferation.
- One coherent milestone per Codex session.
- Shared infrastructure must remain shared.
- Replay capability is an early dependency.
- Implementation does not imply validation.

```text
REPOSITORY AUDIT
→ SHARED DATA / DOMAIN MODEL
→ SHARED FEATURE ENGINE
→ STATE-MACHINE RUNTIME
→ RESEARCH / REPLAY FOUNDATION
→ STRATEGIES #1–#4
→ EARLY HISTORICAL + SHADOW VALIDATION
→ STRATEGIES #5–#8
→ PORTFOLIO / OPTIONS / RESEARCH MATURITY
→ PRODUCTION HARDENING
→ CONTINUOUS MONITORING
```

## 3. Progress Status

```text
[ ] NOT STARTED
[~] IN PROGRESS
[x] COMPLETE
[!] BLOCKED
[-] DEFERRED / NOT REQUIRED
```

## 4. Phase Summary

| Phase | Area | Objective |
|---:|---|---|
| 0 | Repository Audit | Understand/reuse existing system |
| 1 | Core Foundation | Clock, config, canonical models |
| 2 | Data Layer | Normalize live/historical inputs |
| 3 | Shared Analytics | VWAP, ATR, RVOL, RS, structure |
| 4 | Strategy Runtime | State machines, alerts, suppression |
| 5 | Research Foundation | Persistence, outcomes, replay |
| 6 | Strategy 1 | `CRVOL_ORB5` |
| 7 | Strategy 2 | `HOD_COMP_RS` |
| 8 | Strategies 3–4 | `OR_FAILURE_REV`, `FIRST_PULLBACK_VWAP` |
| 9 | Early Validation | Replay/shadow #1–#4 |
| 10 | Strategy 5 | Index drive + breadth |
| 11 | Strategy 6 | Failed gap fade |
| 12 | Strategy 7 | Catalyst first consolidation |
| 13 | Strategy 8 | Experimental profile/LVN |
| 14 | Options Layer | Contract ranking |
| 15 | Portfolio Orchestration | Dedup/confluence |
| 16 | Research Analytics | Ablation/calibration/human analysis |
| 17 | Live Validation | Shadow → provisional → active |
| 18 | Production Hardening | Reliability/observability |
| 19 | Continuous Monitoring | Health/challenger framework |

# 5. Phase 0 — Repository and Capability Audit

## M0.1 — Repository map

Tasks:
- identify entry points/runtime/services
- locate Schwab integration
- locate live/historical market data
- locate Discord
- locate options/unusual-options
- locate storage/schedulers/config/logging/tests/deployment
- identify reusable analytics/backtesting

Deliverable: [PREBUILD_REVIEW.md](./PREBUILD_REVIEW.md), the repository map and review record for this audit. Do not create a duplicate audit merely to satisfy the former placeholder path.

Acceptance: major reusable components identified before new equivalents are built.

## M0.2 — Current data capability audit

Verify actual support for:
- 1m OHLCV
- premarket
- L1 bid/ask
- time-and-sales
- L2
- options chains/quotes/volume/OI/IV/Greeks
- SPY/QQQ/sector
- VIX
- news/earnings
- halts
- historical bars/options

Update `DATA_REQUIREMENTS.md`. Distinguish code support, offline tests, observed provider output, current entitlement and coverage. Include existing collector/command load, cross-process request coordination, streaming limits, data-retention and latency budgets. A blocked faithful mode retains its alternative, cost/fidelity difference and reopening test.

## M0.3 — Freeze deterministic definitions and evidence contracts

Close PLAYBOOKS §13 and proposals P-01–P-03 for the next dependent strategy; track all eight. Define shared feature units/lookbacks/warm-up, sampling/proxy formulas, missingness, state timing, stop/target selection, score factors and outcome policy. Preserve existing numerical rules. Apply uniquely determined engineering clarifications directly; record owner decisions for behavior-changing alternatives. Acceptance: a second implementer can derive the same boundary-case output without guessing. Unresolved choices block only their dependent branch.

M0.3 is divided into reviewable documentation steps without changing its acceptance gate:

- **M0.3A — complete:** shared calculations and the first ORB B-entry/risk/outcome rules in [M0_3_DEFINITION_PACKET.md](./M0_3_DEFINITION_PACKET.md), approved by the owner for written research under D-090. The six specified rows and their boundary examples are frozen; unfinished dependencies remain M0.3B.
- **M0.3B — reopened for agent-owned research revision, 2026-09-13 Pacific:** the owner delegated research-rule choices in [RESEARCH_AUTHORIZATION_20260913.md](./RESEARCH_AUTHORIZATION_20260913.md). Revise [M0_3B_DEFINITION_PACKET.md](./M0_3B_DEFINITION_PACKET.md) into versioned 5-minute/15-minute × immediate/confirmed/retest × long/short research arms, freeze exact rules and final held-out dates in governing files, and supply deterministic boundary examples. Preserve D-090 as a historical arm. This is research authority, not approval of the unseen old packet or live operation.
- M0.3C through M0.3I freeze the seven later strategy research definitions; M0.3I crossing-rule wording is corrected and has protected proof. All PLAYBOOKS §13 strategy rows now have a frozen research version. Source, historical replay and implementation gates remain separate. No B-only result completes the first strategy; no proxy completes its full-fidelity counterpart.


## M0.4 — Offline reuse and compatibility contracts

Freeze existing provider/config/database/Discord interfaces, supported runtime/deployment versions, enabled/disabled test paths and temporary-database/network isolation. Build the smallest safe contract fixtures before application changes. Acceptance: C04-01–C04-07 prove the M0.4 compatibility/isolation slices of AT-01/AT-04/AT-10; full new-adapter, replay, shadow and release acceptance remains with the later owners in TESTING_AND_VALIDATION §48. Read [FIRST_BUILD_SESSION.md](./FIRST_BUILD_SESSION.md) for actual source anchors, pre-import guards, the read-only runtime/deployment comparison and exact end condition. It can begin independently of the unapproved M0.3B trading choices. This implementation milestone was not started by the documentation review.

# 6. Phase 1 — Core Foundation

## M1.1 — Canonical time/session service
Support absolute internal timestamps, Pacific display, premarket, regular session, holidays, early closes, DST.

Complete for the shared clock; see [M1_1_VERIFICATION.md](./M1_1_VERIFICATION.md).
Premarket start and open-relative windows are caller supplied. Clock boundaries do
not establish bar finality or feature readiness; M2.2/M3.6 retain that AT-02 proof.

## M1.2 — Canonical configuration
Centralize strategy, data, options, alert, and research configuration. Add validation and config hash/version.

Complete for the configuration foundation; see [M1_2_VERIFICATION.md](./M1_2_VERIFICATION.md) and CODING_STANDARDS §56. All new switches default off; unfinished policy, version and window values remain null. Actual runtime enforcement, approved strategy parameters and persistent session records retain their later milestone owners.

## M1.3 — Canonical domain/event models
At minimum: Bar, Quote, OptionQuote, CatalystEvent, StrategyStateTransition, FeatureSnapshot, AlertCandidate, OptionRecommendation, OutcomeRecord.

Complete for the record contract, including suppression and separately linked session/delivery/human records; see [M1_3_VERIFICATION.md](./M1_3_VERIFICATION.md) and CODING_STANDARDS §57. Actual adapters, state logic, storage/link enforcement and evaluation remain with M2/M4/M5 and later owners.

# 7. Phase 2 — Data Layer

## M2.1 — Schwab normalization
Reuse existing auth/client. Normalize historical bars, streaming quotes, options fields where available.

Complete for the bounded offline mapping contract; see [M2_1_VERIFICATION.md](./M2_1_VERIFICATION.md) and CODING_STANDARDS §58. Three pure mappings reuse canonical records and preserve legacy outputs. Provider access/history/finality remain M0.2/M2.2 evidence; streaming transport, reconnect and dynamic freshness remain M2.3. No live call is implied by mapping synthetic payloads.

## M2.2 — Historical bar interface
Daily, 1m, premarket, regular session. Complete for the repaired bounded offline
interface and evidence handoff; independent acceptance review remains. See
[M2_2_VERIFICATION.md §11](./M2_2_VERIFICATION.md#11-repaired-source-proof-finalized--2026-09-06-pacific).
The existing request path, clock and M2.1 mappings preserve requested/observed
coverage, original availability, revisions, missing intervals and source conventions.
Fresh supervisor runs passed 424 tests each after this repair. Actual provider capability
remains subject to M0.2 evidence; opening-range features remain M3.6.

## M2.3 — Streaming quote/event interface
Normalized event-driven L1 with stale detection/reconnect. The bounded offline
canonical-Quote event/continuity prerequisite and its second repair have completed
offline implementation and evidence. Same-session source time before recovery and
source time after original availability remain visibly unusable. Fresh supervisor
runs passed 490 tests each with identical 43-decision recordings. See
[M2_3_VERIFICATION.md §12](./M2_3_VERIFICATION.md#12-second-repair-proof-finalized--2026-09-06-pacific).
Independent acceptance review remains. The earlier 487/489-test proofs and
launcher errors remain historical.
It uses explicit supplied policy, fixed times and fake inputs, with no streaming
fields or live defaults.
Full provider transport, authentication refresh/resubscription and verified
continuity/capacity remain blocked under M0.2/M2.3 after that offline slice.

## M2.4 — Reference-market inputs
SPY, QQQ, sector ETFs, VIX if available. The supplied-record reference-input/coverage
prerequisite and evidence are finished: two protected supervisor runs passed
537 tests each with identical reference recordings; see M2_4_VERIFICATION §9.
Full M2.4 remains blocked. Current provider coverage, supported VIX input and historical sector membership
remain required blocked M0.2/M2.4 gates. No reference-return or breadth formula
is selected by this work.

# 8. Phase 3 — Shared Analytics

## M3.1 — Core rolling price features
VWAP, 1m ATR, daily ATR, current HOD/LOD, session open, prior high/low, premarket levels, gap.

## M3.2 — RVOL engine
Same-time/cumulative, 5m, premarket as explicitly defined. No future volume leakage.
The D-090 supplied-Bar slice has completed protected proof in
[M3_2_VERIFICATION.md](./M3_2_VERIFICATION.md) §8. Other required definition/source
branches remain blocked there; this is not full M3.2 completion.

## M3.3 — Relative-strength engine
Stock vs SPY/QQQ/sector.

## M3.4 — VWAP context
Slope, distance, cross count, above/below.

## M3.5 — Structural geometry
Retracement, compression, drive efficiency, distance to level, swing detection, R:R, ATR buffers. If M03B_ORB5_V1 is adopted, M3.5/M4.3 own its minimum shared prior-session bar-profile and swing/AVWAP producer before M6. This dependency must not wait for Strategy #8/M13; full trade profile and #8-specific HVN/LVN/refill behavior remain M13.

## M3.6 — Opening range
5m OR high/low/mid/width/complete status. Completed OR cannot exist before 06:35 Pacific.

# 9. Phase 4 — Shared Strategy Runtime

## M4.1 — Strategy interface
Common required-data, update/state, heads-up/actionable, invalidate/expire/reset, confidence, stop/targets.

The common offline contract in `strategy_interface.py` has completed protected
proof: both supervisor runs passed 720 tests, including all 55 M4.1 cases.
See [M4_1_VERIFICATION.md](./M4_1_VERIFICATION.md) §7 and M4_1_SUPERVISOR_TESTS.json.
It reuses existing canonical records and adds no strategy or live registration.

## M4.2 — State transition engine
Persist timestamp/symbol/strategy/old/new/reason/feature snapshot.

The assigned offline engine, additive transition storage and expanded protected
proof are complete. Both runs passed 826 tests, including all 56 M4.2 cases and
the four added database checks. See
[M4_2_VERIFICATION.md](./M4_2_VERIFICATION.md) §13.
Rules are explicitly supplied. No playbook graph, live consumer or full M5
recovery is added.

## M4.3 — Structural risk/target service
Entry reference, hard/soft invalidation, T1/T2, runner, R, R:R.

## M4.4 — Confidence framework
Setup/Context/Execution + factor persistence.

The assigned supplied-score composition and complete attribution boundary has
completed protected proof: both runs passed 949 tests. See
[M4_4_VERIFICATION.md](./M4_4_VERIFICATION.md) §8. Canonical records are reused;
M5 retains durable storage. Full factor definitions/missingness and actual source
readiness remain a separate required blocked gate.

## M4.5 — Candidate alert model
HEADS_UP/ACTIONABLE, expiry, suppression, confluence.

The assigned pure supplied-candidate assembly and consistency prerequisite has
completed protected proof: both runs passed 1,045 tests. See
[M4_5_VERIFICATION.md](./M4_5_VERIFICATION.md) §8.
Existing canonical records are unchanged. Supplied geometry, full confidence,
session/configuration and component links are checked before construction.
Expiry inspection and caller-reason suppression preserve original candidates.
Automatic rules, portfolio decisions and storage retain their later owners.

## M4.6 — Existing delivery adapter and non-network sinks
Extend the existing Discord sender behind a recording/test/Discord sink boundary; build deterministic heads-up/actionable rendering, receipt status and failure handling. Default replay/shadow output to recording only. AT-06/AT-10 are prerequisites for notification validation. M15.5–M15.7 retain full renderer/delivery refinement.

The primary-attribution review repair and fresh protected proof are complete.
Both runs passed 1,193 tests, including all 130 M4.6 cases, with matching expanded
recordings. Delivery reuses the complete M4.5 assembly checks before storage/send.
See [M4_6_VERIFICATION.md](./M4_6_VERIFICATION.md) §13. All switches remain off.
Full storage/recovery and actual notification proof remain M5.1/M5.5/M9/M15/M17.

## M4.7 — Minimum options and portfolio path before first shadow
Connect the existing options utilities without altering stock validity. Bring forward the minimum parts of M14.1–M14.5 needed for the first four playbooks: canonical contract candidates, mandatory quote/contract filters, frozen OptionScore factors and deterministic ties, the configured strategy option policies, and poor/unavailable results. No contract recommendation may be emitted until those rules and AT-08 fixtures are complete. Persist independent candidates, stable fingerprints, basic cooldown/expiry and deterministic confluence/reversal ownership. Complete the applicable P-01/P-02 contracts first. AT-08/AT-09 must pass before M9.3. M14 and M15 retain the remaining strategies, full refinement and final acceptance of the same shared components.

# 10. Phase 5 — Research Foundation

## M5.1 — Research event store
Persist state, snapshots, alerts, suppressions, option snapshots, versions.

## M5.2 — Outcome evaluator
MFE/MAE/max R/T1/T2/stop/timing. Same-bar ambiguity conservative.

## M5.3 — Historical replay
Chronological deterministic same-runtime replay.

## M5.4 — Reaction-delay framework
0/5/15/30/60 seconds as data permits. Unsupported sub-minute horizons remain data-blocked, not synthesized from one-minute bars.

## M5.5 — Durable session and delivery recovery
Use the existing database framework for atomic mechanical facts plus delivery intent, separate acknowledgment/outcome records, versioned state recovery and expiry-aware retry. Prove AT-06/AT-07/AT-10 before first shadow. M18 still owns full load/failure hardening and runbooks.

# 11. Phase 6 — Strategy #1 `CRVOL_ORB5`

## M6.1 — Eligibility/state machine
Universe, stock-in-play, OR, VWAP, RVOL, state through ARMED.

## M6.2 — Actionable trigger
Break buffer, acceptance, tape/bar proxy, stale logic.

## M6.3 — Risk/targets/confidence

## M6.4 — Replay/synthetic tests
Clean catalyst ORB, low-RVOL fakeout, resistance, wide OR, stale, short.

Completion: IMPLEMENTED + TESTED + REPLAYABLE.

The offline slice is implemented and covered: `consensus_engine/orb5_replay.py`
drives the M6.1, M6.2 and M6.3 owners through the M5.3 replay runner over
supplied evaluation instants, and
`tests/trade_alerts_contracts/test_orb5_replay.py` replays all six named
scenarios, each twice, with matching fingerprints and one deterministic combined
proof artifact. See [M6_4_VERIFICATION.md](./M6_4_VERIFICATION.md) and ROADMAP
section 31. The scenarios are synthetic supplied records: the approved-rule gate
and the actual source/historical-data gate stay open, and no walk-forward,
ablation, shadow validation, promotion or profit evidence is produced here.

# 12. Phase 7 — Strategy #2 `HOD_COMP_RS`

## M7.1 — Point-in-time HOD/LOD + compression

The offline slice is implemented and covered:
`consensus_engine/hod_compression.py` measures the HOD/LOD frozen at a supplied
instant and one compression window described by the caller's own definition, and
`tests/trade_alerts_contracts/test_hod_compression.py` covers the freeze, the
window, the distances, every named refusal and one deterministic recording. See
[M7_1_VERIFICATION.md](./M7_1_VERIFICATION.md) and ROADMAP section 31. The bars
are synthetic supplied records: the `HOD_COMP_RS` definition gate and the
source/historical-data gate stay open, and no threshold, ratio, bar count,
distance cutoff or arming rule is adopted here.

## M7.2 — RS/trend eligibility

The offline slice is implemented and covered:
`consensus_engine/rs_trend_eligibility.py` measures one relative-strength value
from two supplied minute batches over the caller's own lookback and evaluates the
`HOD_COMP_RS` eligibility path through ARMED from that value, the M7.1 reference
and compression flags and the caller's supplied thresholds, and
`tests/trade_alerts_contracts/test_rs_trend_eligibility.py` covers the
measurement, every named refusal, the warm-up answer, all thirteen gates in both
directions and one deterministic recording. See
[M7_2_VERIFICATION.md](./M7_2_VERIFICATION.md) and ROADMAP section 31. The bars
are synthetic supplied records: the `HOD_COMP_RS` definition gate and the
source/historical-data gate stay open, and no threshold, warm-up rule, return
basis or arming rule is adopted here.

## M7.3 — Heads-up/actionable

The offline slice is implemented and covered:
`consensus_engine/hod_comp_rs_trigger.py` freezes one structure from the supplied
M7.1 reference and compression window and the caller's own buffer, reports the
heads-up notice while the supplied M7.2 eligibility is ARMED and the structure is
still approaching, tests the crossing on the caller's own grid, and reports
ALERT_TRIGGERED only while every supplied gate passes after that crossing, and
`tests/trade_alerts_contracts/test_hod_comp_rs_trigger.py` covers both paths,
every named refusal, both participation arms, the structure owner and one
deterministic recording. See
[M7_3_VERIFICATION.md](./M7_3_VERIFICATION.md) and ROADMAP section 31. The
observations are synthetic supplied records: the `HOD_COMP_RS` definition gate
and the source/historical-data gate stay open, and no buffer, acceptance share,
intensity minimum, distance cutoff, extension limit or quota rule is adopted
here.

## M7.4 — Risk/confidence/suppression

The offline slice is implemented and covered:
`consensus_engine/hod_comp_rs_risk_confidence.py` composes one M7.3 trigger
assessment with the caller's own supplied stop and targets, the M4.4 confidence
result and the caller's own suppression policy and prior-action history, and
reports the stop, targets, confidence and suppression decision they already
carry, and
`tests/trade_alerts_contracts/test_hod_comp_rs_risk_confidence.py` covers the
composed path, every named refusal, every suppression reason and one
deterministic recording. See
[M7_4_VERIFICATION.md](./M7_4_VERIFICATION.md) and ROADMAP section 31. The inputs
are synthetic supplied records: the `HOD_COMP_RS` definition gate and the
source/historical-data gate stay open, and no stop pad, reward minimum,
confidence floor, cooldown or structure quota is adopted here.

## M7.5 — Replay/synthetic tests
Clean compression break, failed break, RS-weak, stale extension, short.

Completion: IMPLEMENTED + TESTED + REPLAYABLE.

The offline slice is implemented and covered: `consensus_engine/hod_comp_rs_replay.py`
drives the M7.2, M7.3 and M7.4 owners through the M5.3 replay runner over
supplied evaluation instants, and
`tests/trade_alerts_contracts/test_hod_comp_rs_replay.py` replays all five named
scenarios, each twice, with matching fingerprints and one deterministic combined
proof artifact. See [M7_5_VERIFICATION.md](./M7_5_VERIFICATION.md) and ROADMAP
section 31. The scenarios are synthetic supplied records: M0.3C resolves the
`HOD_COMP_RS` research-definition gate, while the actual source/historical-data
gate stays open, and no
walk-forward, ablation, shadow validation, promotion or profit evidence is
produced here.

# 13. Phase 8 — Strategies #3/#4

## M8.1 — ORB→failure transition support

The offline slice is implemented and covered:
`consensus_engine/or_failure_handoff.py` decides from supplied records whether
one ended M6.2 opening-range attempt hands over to a failure/reversal owner and
in which direction, reusing the M3.6 opening range, the M6.2 attempt records and
the M4.2 engine, and
`tests/trade_alerts_contracts/test_or_failure_handoff.py` covers the five gates,
every named refusal, both directions, the handoff owner and one deterministic
recording. See [M8_1_VERIFICATION.md](./M8_1_VERIFICATION.md) and ROADMAP
section 31. The records are synthetic supplied ones: M0.3D resolves the
`OR_FAILURE_REV` research-definition gate, while the source/historical-data
gate stays open, and no excursion
minimum, reacceptance window, ownership rule or trigger is adopted here.

## M8.2 — `OR_FAILURE_REV`

The offline slice is implemented and covered: `consensus_engine/or_failure_rev.py`
carries one supplied M8.1 handoff the rest of the PLAYBOOKS section 5 chain,
`FAILURE_FORMING -> ARMED -> ALERT_TRIGGERED`, reporting nine supplied gates, the
supplied stop and targets and the supplied M4.4 confidence, and
`tests/trade_alerts_contracts/test_or_failure_rev.py` covers every gate, both
confirmation arms, both directions, the reversal owner and one deterministic
recording. See [M8_2_VERIFICATION.md](./M8_2_VERIFICATION.md) and ROADMAP
section 31. The records are synthetic supplied ones: M0.3D resolves the
`OR_FAILURE_REV` research-definition gate, while the source/historical-data
gate stays open. No threshold or
confidence floor is adopted here, and nothing is alerted or acted on.

## M8.3 — impulse/pullback primitives

The offline slice is implemented and covered:
`consensus_engine/impulse_pullback.py` measures one frozen impulse leg over the
caller's own supplied window and the pullback that followed it from supplied
minute bars, reusing the M2.2 canonical records, the M3.1 history coverage view
and the M1.2 session clock, and
`tests/trade_alerts_contracts/test_impulse_pullback.py` covers both directions,
both reading conventions, every named window refusal on each leg, the reported
geometries and one deterministic recording. See
[M8_3_VERIFICATION.md](./M8_3_VERIFICATION.md) and ROADMAP section 31. The bars,
the ATR and the VWAP are synthetic supplied records: M0.3E resolves the
`FIRST_PULLBACK_VWAP` research-definition gate, while the source/historical-data
gate stays open, and no impulse
minimum, retracement band, volume ratio, reversal-bar definition or pullback
count is adopted here.

## M8.4 — `FIRST_PULLBACK_VWAP`

The offline slice is implemented and covered:
`consensus_engine/first_pullback_vwap.py` carries one supplied M8.3 impulse and
pullback measurement the rest of the PLAYBOOKS section 6 chain,
`PULLBACK_FORMING -> ARMED -> ALERT_TRIGGERED`, reporting fifteen supplied gates,
the supplied stop and targets and the supplied M4.4 confidence, and
`tests/trade_alerts_contracts/test_first_pullback_vwap.py` covers every gate,
both directions, the exact trigger boundary, the continuation owner and one
deterministic recording. See [M8_4_VERIFICATION.md](./M8_4_VERIFICATION.md) and
ROADMAP section 31. The records are synthetic supplied ones: the
`FIRST_PULLBACK_VWAP` research-definition gate is resolved by M0.3E, while the
source/historical-data gate stays open. No impulse minimum, retracement band, volume ratio, trigger offset,
pullback count or confidence floor is adopted here, and nothing is alerted or
acted on.

## M8.5 — cross-strategy interaction tests

# 14. Phase 9 — Early Validation / Shadow

## M9.1 — Historical replay #1–#4
## M9.2 — initial validation report
Create/update `docs/initial_strategy_validation.md`.
## M9.3 — shadow mode
Prove safe recording, input continuity and the initial pipeline with the first four playbooks; this is the engineering pilot, not the M17 evidence-bearing promotion gate. Depends on M4.6, M4.7, M5.5, the selected mode's M0.2 provider/queue/storage/disk/memory budgets, validated input continuity and AT-13 bounded-load proof. Record data modes and use the recording sink by default; actual delivery and human-reaction validation require separately authorized delivery evidence.
## M9.4 — human decision tags

Complete the required early #1–#4 validation before implementing the remaining four strategies, as MASTER_SPEC §19 and D-041 require. If historical or future data is unavailable, record the exact INSUFFICIENT_DATA/BLOCKED assessment and leave the validation gate open. Independent shared/data prerequisite work may continue; #5–#8 strategy implementation stays behind this gate unless an explicitly approved decision changes the order. Every blocked prerequisite keeps an owner and reopening test.

# 15. Phase 10 — Strategy #5

Research definition version `M03F_INDEX_OPEN_DRIVE_BREADTH_V2` resolves the
PLAYBOOKS section 13 formula choices for M10.1–M10.6 in writing; protected
verification of the M0.3F repair passed; independent acceptance remains pending. M10.7's full-breadth
source, point-in-time membership and historical-coverage gate stays blocked
until M0.2 supplies its separate evidence. Sector proxy remains a separately
labeled fallback and cannot close that gate.

## M10.1 — opening drive
## M10.2 — breadth proxy v1
## M10.3 — BreadthScore
## M10.4 — state/alerts
## M10.5 — SPY/QQQ dedup
## M10.6 — tests
## M10.7 — full-breadth mode and point-in-time membership
Retain full-mode completion with live/history/membership/coverage gates. A passing sector-proxy test does not complete full breadth.

# 16. Phase 11 — Strategy #6

Research definition version `M03G_GAP_FADE_FAILED_OPEN_V1` resolves the
PLAYBOOKS section 13 deterministic choices for M11.1–M11.6 in writing. Actual
bars, trades, quotes, SPY, catalyst history, borrow and option coverage remain
separate required source gates. The written freeze does not authorize replay or
live use.

## M11.1 — gap classification features
## M11.2 — catalyst-state field
## M11.3 — failed-open state machine
## M11.4 — risk/targets
## M11.5 — OR failure interaction
## M11.6 — tests

# 17. Phase 12 — Strategy #7

Conditional on catalyst data.

Research definition version `M03H_CAT_FIRST_CONSOL_V1` resolves the PLAYBOOKS
section 13 deterministic choices for M12.1–M12.4 in writing. Actual point-in-time
catalyst history, bars, trades, quotes, borrow and option coverage remain
separate required source gates. The written freeze does not authorize replay or
live use.

## M12.1 — catalyst source assessment
## M12.2 — CatalystEvent normalization
## M12.3 — deterministic catalyst classification v1
## M12.4 — first-consolidation state machine
## M12.5 — interaction with `HOD_COMP_RS`
## M12.6 — tests

If data inadequate: SHADOW_DEGRADED or BLOCKED. Keep faithful catalyst completion and source/receive-time acceptance tracked; a price-only substitute does not complete #7.

# 18. Phase 13 — Strategy #8

Experimental and last.

## M13.1 — deterministic 1m approximate profile
## M13.2 — LVN/HVN detection
## M13.3 — profile stability
## M13.4 — state machine
## M13.5 — dynamic LVN fill
## M13.6 — matched-sample experiment support
## M13.7 — true-profile data-mode reopening and parity
Retain the full-data mode with its data blocker; require frozen volume-at-price coverage and matched mode comparison before declaring it complete.

# 19. Phase 14 — Options Layer

Complete and refine the shared engine first connected under M4.7; retain all eight strategy policies and all M14 acceptance criteria. Do not build a duplicate ranker.

## M14.1 — canonical candidate engine
## M14.2 — contract quality features
## M14.3 — OptionScore
## M14.4 — poor-quality rejection
## M14.5 — strategy-specific option policies
## M14.6 — historical-option limitations

# 20. Phase 15 — Portfolio Orchestration

## M15.1 — duplicate fingerprinting
## M15.2 — primary vs confluence
## M15.3 — cross-strategy conflicts
## M15.4 — suppression/cooldown
## M15.5 — Discord actionable renderer
## M15.6 — heads-up renderer
## M15.7 — delivery reliability

# 21. Phase 16 — Research Analytics

## M16.1 — strategy report
Metrics: sample, win/loss, avg/median R, expectancy, PF, MFE/MAE, T1/T2, drawdown.

## M16.2 — reaction delay
## M16.3 — ablation
## M16.4 — confidence calibration
## M16.5 — human discretion analysis
## M16.6 — regime segmentation
## M16.7 — strategy overlap report

# 22. Phase 17 — Live Validation

## M17.1 — evidence-bearing forward validation #1–#4
Use the same pipeline proven by M9.3, with the frozen validation duration/sample/independent-session and stability criteria from M0.3/P-03. Collect and assess actual forward evidence; M9.3 pilot completion does not complete this milestone or authorize promotion.
## M17.2 — shadow #5–#8 as feasible
## M17.3 — forward-data retention audit
## M17.4 — preliminary promotion review
Before any ACTIVE decision, the promotion record must link passing minimum controls to exact owners: M18.1 provider/data health; M18.2 classified operational faults; M18.3 latency/backlog budgets; M18.4 kill switch, absent-to-enabled gate and AT-13 load/failure proof; M18.5 secret/access isolation; M18.6 the deployed-version/runbook check; M19.1 version-specific health baseline; M19.7 rehearsed rollback. M4.6/M5.5 must already pass AT-06/AT-07 delivery/restart recovery. These subacceptances are required before ACTIVE; parent hardening/monitoring milestones remain open until their full scope is complete. Record explicit promotion approval under D-083.
## M17.5 — walk-forward
## M17.6 — parameter robustness

# 23. Phase 18 — Production Hardening

## M18.1 — data-health monitoring
## M18.2 — structured observability
## M18.3 — runtime latency measurement
## M18.4 — failure-mode tests
## M18.5 — secrets/security audit
## M18.6 — deployment documentation

# 24. Phase 19 — Continuous Monitoring

## M19.1 — version-specific baselines
## M19.2 — rolling health metrics
## M19.3 — GREEN/YELLOW/ORANGE/RED states
## M19.4 — degradation diagnostics
## M19.5 — research proposal queue
## M19.6 — champion/challenger
## M19.7 — rollback support

# 25. Data Dependency Gates

- #5: proceed with explicit breadth proxy if full breadth unavailable.
- #7: do not claim faithful implementation without reliable catalyst data.
- #8: proceed with `BAR_APPROX_PROFILE`; keep true profile separate.
- L2/tape are optional; do not block core.
- historical OPRA absence does not block underlying validation.

# 26. Milestone Acceptance Template

```text
[ ] Required code exists.
[ ] Existing functionality reused where appropriate.
[ ] Unit tests added/updated.
[ ] Integration tests added where applicable.
[ ] Tests pass.
[ ] Lint/type checks pass where configured.
[ ] No known regression introduced.
[ ] Documentation updated.
[ ] ROADMAP checkbox updated.
[ ] Open issues recorded.
```

# 27. Strategy Completion Template

```text
[ ] Config
[ ] Required data mapped
[ ] Eligibility
[ ] State machine
[ ] Heads-up
[ ] Actionable trigger
[ ] Invalidation
[ ] Expiry
[ ] Suppression
[ ] Stop
[ ] Targets
[ ] Confidence
[ ] Human checklist
[ ] Options hook
[ ] Event persistence
[ ] Synthetic tests
[ ] Replay
[ ] Shadow-ready
[ ] Historical results documented
[ ] Research questions recorded
```

# 28. Documentation Progress

- [x] `PROJECT_INDEX.md`
- [x] `MASTER_SPEC.md`
- [x] `PLAYBOOKS.md`
- [x] `ROADMAP.md`
- [x] `SESSION_PROTOCOL.md`
- [x] `DATA_REQUIREMENTS.md`
- [x] `TESTING_AND_VALIDATION.md`
- [x] `CODING_STANDARDS.md`
- [x] `DECISIONS_AND_OPEN_QUESTIONS.md`

# 29. Global Implementation Checklist

## Foundation
- [ ] Repository audit
- [ ] Data capability audit
- [x] Session clock
- [x] Configuration framework
- [x] Canonical models

## Data
- [x] Schwab normalization
- [x] Historical bar interface (offline): repaired source and evidence complete for independent acceptance review; actual source coverage remains M0.2
- [ ] Live quotes
- [ ] Options data
- [ ] Reference markets
- [ ] Stale-data handling

## Shared analytics
- [ ] VWAP
- [ ] ATR
- [ ] RVOL
- [ ] Relative strength
- [ ] HOD/LOD
- [ ] Premarket levels
- [ ] Gap
- [x] Opening range (M3.6 offline) — implementation and protected proof complete; see M3_6_VERIFICATION §12
- [!] Opening range (M3.6 source completion) — actual opening-minute source evidence remains required under M0.2/M2.2
- [ ] VWAP slope/crosses
- [ ] Compression
- [ ] Retracement
- [ ] Structural R:R

## Runtime / research / strategies
- [x] Strategy interface (M4.1) — implementation and protected proof complete
- [x] State transitions (M4.2) — implementation and expanded 826-test protected proof complete in M4_2_VERIFICATION §13
- [x] Candidates (M4.5 supplied assembly) — implementation and protected proof complete
- [ ] Risk/target engine
- [ ] Confidence
- [x] Suppression (M4.5 separate supplied record) — implementation and protected proof complete
- [x] Event store (M5.1) — repaired protected proof complete in M5_1_VERIFICATION §15; M5.5 retains full recovery
- [ ] Outcomes
- [ ] Replay
- [ ] Reaction delay
- [ ] `CRVOL_ORB5`
- [ ] `HOD_COMP_RS`
- [ ] `OR_FAILURE_REV`
- [ ] `FIRST_PULLBACK_VWAP`
- [ ] `INDEX_OPEN_DRIVE_BREADTH`
- [ ] `GAP_FADE_FAILED_OPEN`
- [ ] `CAT_FIRST_CONSOL`
- [ ] `VP_ACCEPT_LVN`
- [ ] Contract engine / OptionScore
- [ ] Dedup/confluence
- [ ] Discord delivery
- [ ] Historical reports / walk-forward / ablation
- [ ] Confidence/human analysis
- [ ] Shadow mode
- [ ] Health monitoring
- [ ] Production hardening

# 30. Roadmap Update Rules

At the end of every Codex session:
1. update completed checkboxes;
2. leave partial milestones `[~]`;
3. mark true external blockers `[!]`;
4. record new dependencies;
5. do not reorder major phases without documenting why;
6. identify exact next milestone;
7. synchronize changed assumptions with canonical docs;
8. end the session report with the mandatory one-line next-session kickoff from SESSION_PROTOCOL §32, after saving this roadmap's actual state.

Do not mark `[x]` unless acceptance criteria and verification are satisfied.

# 31. Build progress and exact next milestone

Status as of **2026-09-06 Pacific**: M0.4, M1.1–M1.3 and M2.1–M2.3 have completed
bounded offline evidence. M2.3 §12 records its fresh supervisor proof: two runs
of 490 tests with identical 43-decision recordings. Its required live-provider
branch remains blocked. **M2.4's offline implementation and evidence are finished**:
two protected supervisor runs passed 537 tests each, including 46 M2.4 cases,
with identical reference recordings and clean isolation/cleanup. All 781 saved
file contents matched before records-only finalization; source/tests are unchanged.
Read [M2_4_VERIFICATION.md](./M2_4_VERIFICATION.md) §9. **Required M2.4 source
completion remains blocked**, with exact reopening proof in §7. That blocked-gate handoff selected **M3.1**, bounded in §6; its current repair status is below. M0.3A remains approved, M0.3B remains
PROPOSED and no strategy/live activation has started. D-091 remains $25 total
authorized, $0 used and $0 reserved.

**M3.1's fifth repair has fresh protected proof.** Minute ATR now
ignores premarket closes when finding the prior regular-session close, including
after a certified no-trade opening minute. Minute and daily feature paths reject
history with the wrong interval. Both fresh protected runs passed **591 tests**,
including all **54 M3.1 cases**, with identical ordered test IDs and identical
67,989-byte compact recordings. Isolation and cleanup were clean. Read
M3_1_VERIFICATION §16. The offline row is `[x]`; the required full-data/source
branch stays `[!]`. That prior handoff selected **M3.2** for independent supplied-Bar work.
The controller has now assigned that slice; its current status follows.

**Current M3.2 status — 2026-09-06 Pacific:** the three approved supplied-Bar
participation calculations have fresh protected proof. Both supervisor runs
passed **637 tests**, including all **46 M3.2 cases**, in 262.14 and 271.11
seconds. Ordered test IDs and 10,041-byte compact recordings match; isolation and
cleanup were clean. Read M3_2_VERIFICATION §8 and M3_2_LOCAL_CHECKS. The separate
required definition/source branches stay blocked. Proposed independent next build
after review: **M3.6**, with scope and ordering reasons in
M3_2_VERIFICATION §6. No M3.3–M3.5 work or unfinished feature is removed.

**Current M3.6 status — 2026-09-06 Pacific:** the request-window repair has fresh
protected proof. Both runs passed **665 tests**, including all **28 M3.6 cases**,
with matching ordered IDs and byte-identical 9,379-byte compact records. Isolation
and cleanup were clean. Read M3_6_VERIFICATION §12 and M3_6_LOCAL_CHECKS.json.
The separate required source branch stays blocked. Proposed independent next work
after review: **M4.1**. M3.3–M3.5 remain blocked by their exact definition gates
and are not removed.

**Current M4.1 status — 2026-09-06 Pacific:** the assigned common strategy
interface has fresh protected proof. Both runs passed **720 tests**, including all
**55 M4.1 cases**, with matching ordered IDs, clean isolation and cleanup. The
long and short records are byte-identical across runs. Existing records carry
candidate, confidence, stop, target and transition facts. The input context checks
time and identity without approving a trading rule or activating a strategy. See
M4_1_VERIFICATION §7 and M4_1_SUPERVISOR_TESTS.json. Proposed next milestone after
review: **M4.2**.

**Current M4.2 status — 2026-09-06 Pacific:** the shared transition engine,
append-only storage and expanded protected proof are complete. Both fresh runs
passed **826 tests**, including all **56 M4.2 cases** and the four database checks
added after review, in **280.13 and 255.66 seconds**. Ordered IDs and required
recordings match; isolation and cleanup passed. All 39 published artifact hashes
and all 808 tested file contents matched before records-only finalization. See
M4_2_VERIFICATION §13 and M4_2_LOCAL_CHECKS.json. Code, tests, configuration and
protection are unchanged. The entire milestone still changes **16 paths**.
Proposed next after independent review: **M4.3**, bounded in M4_2_VERIFICATION §5.
Earlier failures, the narrower 822-test selection and its premature completion
claim remain historical.

- [x] M0.1 repository map, supported by PREBUILD_REVIEW.
- [~] M0.2 static source/local-metadata evidence complete for this preparation; current entitlement, event/availability coverage, chain completeness/units, borrow, adjustment history and shared capacity still need dependent proof.
- [x] M0.3 deterministic definitions: M0.3A approved under D-090 and preserved; M0.3B research rules are frozen under RESEARCH_AUTHORIZATION_20260913.md, while exact replay dates remain source-gated. HOD_COMP_RS, OR_FAILURE_REV, FIRST_PULLBACK_VWAP, INDEX_OPEN_DRIVE_BREADTH, GAP_FADE_FAILED_OPEN, CAT_FIRST_CONSOL and VP_ACCEPT_LVN research definitions are frozen by M0.3C through M0.3I. M0.3I crossing-rule wording is corrected and has protected proof. All PLAYBOOKS §13 strategy rows now have a frozen research version. Their separate source gates remain open. No old proposal or operational rule is approved by inference.
- [x] **M0.4:** C04-01–C04-07 pass under pre-import isolation. New tests and launcher preserve actual existing interfaces; runtime/deployment comparison and remaining limits are recorded in M0_4_VERIFICATION.md. Only the M0.4 slices of AT-01/04/10 close.
- [x] **M1.1:** six additive shared clock helpers; 41 new clock cases plus 84 existing cases pass in each of two protected processes. Legacy functions and pre-import child protection are unchanged. Only AT-02's clock portion closes; M2.2/M3.6 retain data finality, availability, missing-minute and revision proof.
- [x] **M1.2:** strict non-secret configuration namespace, all-off/null defaults, stable version/hash and fixed snapshot through the existing loader. The independent combined selection passed 194 cases in each of two protected processes, including 48 new configuration cases; zero failures/errors/skips or unexpected isolation denials. Actual YAML and both process proofs have the same hash. No proposed strategy values were adopted.
- [x] **M1.3:** thirteen immutable canonical record types, strict versioned serialization, source/time/quality/missingness, structural candidate facts, fixed configuration attribution and separate linked results. The final independent selection passed 363 tests in each of two protected processes, with identical record output and zero failures/errors/skips or unexpected isolation denials. See M1_3_VERIFICATION.md.
- [x] **M2.1:** three pure offline Schwab bar/quote/option mappings; 41 new cases pass twice. The independent combined selection passes 420 cases in each of two protected processes, with identical three-record output and no unexpected isolation denials. See M2_1_VERIFICATION.md. Provider semantics, live wiring and dynamic freshness remain outside this bounded completion.
- [x] **M2.2:** repaired offline historical-bar requests, normalization, scheduled coverage and immutable available-time views are complete with fresh supervisor proof. Both protected runs passed 424 tests, including 75 M2.2 cases and both peer-history callers. XML test IDs and history outputs match; no unexpected isolation denials or cleanup failures occurred. All 771 saved file contents matched before records-only finalization; code, tests and protection remain unchanged. Read [M2_2_VERIFICATION.md](./M2_2_VERIFICATION.md) §11 and [M2_2_LOCAL_CHECKS.json](./M2_2_LOCAL_CHECKS.json). The earlier 418-test proof and [launcher errors](./M2_2_LAUNCHER_LIMITATION.txt) remain historical. This checkbox records implementation and evidence completion, not the supervisor's pending independent acceptance. M0.2 source evidence and M3.6 actual opening-range features remain open.
- [x] **M2.3:** second offline source-time repair, successful protected proof and records-only finalization are complete for independent acceptance review. Repeated quote/trade times cannot hide a same-session source time before recovery; a source time after original availability stays visibly invalid after the clock catches up. Both fresh supervisor runs passed 490 tests, including 87 M2.3 cases and both named repair tests, with identical 43-decision recordings and clean isolation/cleanup. All 776 saved file contents matched before finalization; code, tests and protection remain unchanged. See [M2_3_VERIFICATION.md](./M2_3_VERIFICATION.md) §12 and [M2_3_LOCAL_CHECKS.json](./M2_3_LOCAL_CHECKS.json). This checkbox records bounded offline implementation and evidence completion; the supervisor's separate reviewer decides acceptance. All prior owner work and the required live branch are preserved.
- [!] **M2.3 live-provider completion:** full streaming transport, official field/partial-update meanings, current entitlement/subscriptions, authentication refresh/resubscription, measured cadence/quote/trade timing, continuity/warm-up and shared capacity remain blocked by data and separately supervised access. Reopening proof and existing-source-first route are in M2_3_VERIFICATION §7. This required branch is not completed by the offline prerequisite.
- [x] **M2.4 offline prerequisite:** supplied SPY/QQQ/11-sector reference snapshots,
  per-symbol Quote/history coverage and explicit unsupported VIX are implemented
  with successful protected evidence and records-only finalization. Both supervisor
  runs passed 537 tests, including 46 M2.4 cases and the stock-sector caller, with
  identical test IDs/reference recordings and clean isolation/cleanup. All 781 saved
  file contents matched before finalization; code/tests/protection are unchanged.
  See M2_4_VERIFICATION §9 and M2_4_LOCAL_CHECKS.json. Independent review decides
  acceptance. This finished offline row does not complete the required source row.
- [!] **M2.4 source completion:** current per-symbol reference L1/minute/history
  coverage, supported spot-VIX identity/type/field/time semantics, historical
  sector membership and shared source capacity require separately supervised
  evidence. Exact existing-source-first reopening proof is M2_4_VERIFICATION §7.
  Passing synthetic snapshots cannot complete this required branch.
- [x] **M3.1 offline core price features:** fifth repair code, 54 protected cases
  and compact end-to-end recording have fresh supervisor proof. Both protected
  runs passed 591 tests with identical ordered IDs and identical 67,989-byte
  recordings; isolation and cleanup were clean. See M3_1_VERIFICATION §16.
  This offline row does not complete the required source row below.
- [!] **M3.1 full-data/source completion:** full eligible-trade VWAP, actual opening
  trade identity, trade-condition/cancel/correction treatment and compatible actual
  daily/minute/premarket source coverage remain blocked.
  Synthetic tests cannot close them; reopening proof is in M3_1_VERIFICATION.md §6.
- [x] **M3.2 offline participation prerequisite:** `RVOL_OPEN5_MEAN20_V1`,
  `PM_RVOL_MEAN20_V1` and `DOLLAR_VOLUME_CLOSE_PROXY20_V1` are implemented in
  `participation_features.py`. Both protected supervisor runs passed 637 tests,
  including all 46 M3.2 cases, with identical ordered IDs and identical compact
  recordings. Isolation and cleanup were clean. Production code and protection
  are unchanged by the test-only timeout repair. See M3_2_VERIFICATION §8.
- [!] **M3.2 required definition/source completion:** general same-time/cumulative
  RVOL needs its own exact adopted definition. D-090 tape intensity and projected
  current-minute volume need verified trade eligibility/correction/coverage and
  minute-start counters; final bars cannot supply those paths. Actual compatible
  current plus 20-prior-session opening/premarket/daily coverage also needs
  separately supervised source evidence. See M3_2_VERIFICATION §5 for reopening.
- [ ] **M3.3–M3.5:** retained. The strategy-specific VWAP, swing, structure,
  benchmark, warm-up and compression research definitions are frozen by M0.3B
  through M0.3I. Their separate source and historical-data gates remain blocked.
  M3.3 may proceed first with supplied inputs without claiming source completion.
- [x] **M3.6 offline opening range:** the supplied-record five-minute high/low/
  mid/width calculation and its request-window repair have fresh protected proof.
  Both runs passed 665 tests, including all 28 M3.6 cases, with matching ordered
  IDs, byte-identical compact records, and clean isolation and cleanup. See
  M3_6_VERIFICATION §12 and M3_6_LOCAL_CHECKS.json.
- [!] **M3.6 source completion:** actual compatible opening-minute coverage,
  original publication/finality, missing/no-trade meaning, revisions/corrections,
  price/share adjustment and eligible-venue basis require separately supervised
  evidence under M0.2/M2.2. Synthetic cases cannot complete this row.
- [x] **M4.1 — shared strategy interface:** both protected runs passed 720 tests,
  including all 55 M4.1 cases, with matching ordered IDs, clean isolation and
  cleanup, and byte-identical long/short records. Canonical records and all earlier
  owner work are preserved. No trading strategy, transition engine, live consumer
  or new product rule is implemented. See M4_1_VERIFICATION §7.
- [x] **M4.2 — state transition engine:** implementation, expanded protected
  proof and records are complete. Both runs passed 826 tests, including all 56
  M4.2 cases and the four added database checks, with matching long/short records,
  matching ordered IDs and clean isolation/cleanup. Existing M4.1/canonical records, supplied
  rules, database transactions/migrations and all owner inputs are preserved.
  Complete transition facts, fixed session/configuration and rule attribution
  remain immutable. See M4_2_VERIFICATION §13. No required live/data/definition
  gate belongs to this common mechanism; prior blocked rows stay open.
- [x] **M4.3 — offline structural risk/target prerequisite:** D-090 §6 supplied-input
  selector and all 105 M4.3 cases have fresh protected proof. Both supervisor runs
  passed 892 tests with matching ordered IDs, clean isolation/cleanup and
  byte-identical long/short recordings. See M4_3_VERIFICATION §8.
- [!] **M4.3 required structure/definition/source completion:** adopted full
  catalog producers/applicability/priority, actual anchor-path and family coverage,
  valid increments, compatible source/correction history, and applicable soft
  invalidation/runner definitions remain unavailable. Exact owners and supervised
  reopening proof are M4_3_VERIFICATION §4. Supplied fixtures cannot close this row.
- [x] **M4.4 — offline supplied confidence composition and attribution prerequisite:**
  implementation and protected proof are complete. Exact
  supplied weights, scores, factor versions and feature/session/configuration
  references are retained; missing factors cannot yield a score. The unchanged
  launcher failure remains historical. Both fresh supervisor runs passed 949
  tests, including all 68 M4.4 cases, with matching ordered IDs, clean isolation
  and cleanup, and byte-identical long/short recordings. See M4_4_VERIFICATION §8
  and M4_4_LOCAL_CHECKS.json.
- [!] **M4.4 required full confidence definition/source completion:** adopted
  factor roster, scales/normalization, factor-to-component formulas, missingness/
  freshness rules and actual compatible point-in-time source/correction coverage
  remain unavailable. M0.3B's B-SCORE is still proposed. M16.4 retains calibration
  and M5.1 retains full durable attribution. Exact owners and reopening proof are
  M4_4_VERIFICATION §4. Supplied examples cannot close this required row.
- [x] **M4.5 — offline supplied candidate assembly and consistency prerequisite:**
  implementation and protected proof are complete. Both fresh supervisor runs
  passed 1,045 tests, including all 96 M4.5 cases, with matching ordered IDs,
  clean isolation/cleanup and byte-identical long/short recordings. Existing
  candidate/suppression/confluence records are reused with complete supplied
  confidence and context attribution. No new expiry duration, scoring, cooldown,
  deduplication or trading rule. See M4_5_VERIFICATION §8 and
  M4_5_LOCAL_CHECKS.json. The local launcher failure remains historical.
- [x] **M4.6 — existing delivery adapter and non-network sinks:** primary-attribution
  repair, fresh protected proof and records-only finalization are complete.
  Both runs passed 1,193 tests, including all 130 M4.6 cases and 48 new rejection
  cases. Ordered IDs and expanded long/short recordings match; isolation and
  cleanup passed. All 828 tested file contents matched before finalization.
  See M4_6_VERIFICATION §13. Old sender behavior and all switches are unchanged.
  No required gate remains for this offline boundary; independent review decides
  acceptance. Full durable recovery and actual delivery proof retain later owners.
- [~] **M4.7 — minimum options and portfolio path:** this former definition-blocked
  row is historical. D-100 and `M47_FIRST4_RESEARCH_V1` now freeze the minimum
  first-four option and portfolio rules. The implementation handoff at the end
  of this section records current code and pending AT-08/AT-09 protected proof.
  Source, historical execution, calibration and live gates remain separate.
- [x] **M5.1 — research event store:** implementation, repaired protected proof
  and records-only finalization complete. Both fresh runs passed 1,249 tests,
  including all 23 storage cases, twelve identity checks and both required Batch 2
  storage tests. Ordered IDs and expanded long/short recordings match; isolation
  and cleanup passed. All 833 tested contents matched before finalization.
  See M5_1_VERIFICATION section 15. Independent review decides acceptance.
  M5.5 retains full recovery; no required gate remains for this common store.
- [x] **M5.2 — offline supplied-bar outcome evaluator:** repaired implementation,
  fresh protected proof and records-only finalization complete. Both protected
  runs passed 1,250 tests, including all 49 M5.2 cases and both Batch 2 storage
  checks, in 304.67/306.15 seconds within the 420-second limit. Ordered IDs match;
  long/short recordings are byte-identical at 52,588/52,594 bytes. The evaluator
  uses exact decimal values for the inclusive 0.35 extension and 1.50 remaining-
  room boundaries. See M5_2_VERIFICATION section 20. Independent review decides
  acceptance. The required source/definition gate below stays open.
- [!] **M5.2 required actual-source and executable-profit completion:** actual
  compatible point-in-time adjusted minute coverage, gaps/halts/corrections and
  the remaining adopted costs/borrow/statistical terms are unavailable in this
  offline lane. M0.2/M0.3/M5.2/M5.4/M16–M17 retain these gates. Synthetic Bars
  cannot close them. Exact reopening proof is M5_2_VERIFICATION section 8.
- [x] **M5.3 — offline historical replay:** the runner stops when research
  records and state changes use different databases. A two-connection test covers
  the repaired AT-10 boundary. The fresh protected run passed 1,235 tests, and
  both fresh recording runs passed 26 tests with matching replay output. See
  M5_3_VERIFICATION and M5_3_SUPERVISOR_TESTS.json. Independent review decides
  acceptance. All switches remain off.
- [!] **M5.4 — reaction-delay framework:** the required 0/5/15/30/60-second
  study needs compatible point-in-time data at those horizons. That data is not
  available in this offline lane. Unsupported sub-minute results must not be
  made from one-minute bars. Reopen this milestone only with the source proof
  retained by M0.2, M2.3 and M5.2.
- [x] **M5.5 — durable session and delivery recovery:** recovery reads the M5.1
  store and the existing database framework only. One intent keeps one final
  delivery fact; a crash before any send may retry while unexpired, a crash after
  the send started stays UNKNOWN, and an expired intent never sends. State
  recovery restores a complete stored chain or fails closed. Acknowledgment and
  outcome stay separate records. The protected broad run passed 1,254 tests and
  both fresh recording processes passed 28 tests with byte-identical artifacts.
  See M5_5_VERIFICATION, M5_5_SUPERVISOR_TESTS.json and M5_5_LOCAL_CHECKS.json.
  Independent review decides acceptance. Delivery stays
  recorded, all switches remain off, and M18 retains full load and failure
  hardening.
- [!] **M6.1 approved-rule gate:** the exact ARMED thresholds and eligibility
  rules come from M03B_ORB5_V1, which is still PROPOSED in M0.3B, and section 10
  keeps the shared prior-session bar-profile and swing/AVWAP producer with
  M3.5/M4.3. No threshold may be adopted by inference. The offline state-machine
  slice may proceed with supplied inputs; the rule-bearing branch reopens only
  after that definition is adopted.
- [x] **M6.1 — offline eligibility/state machine for `CRVOL_ORB5`:**
  `consensus_engine/orb5_eligibility.py` reports twelve supplied gates and the
  state they support through ARMED: the half-open evaluation window, opening
  range, minimum price, median dollar volume, opening RVOL, OR width over daily
  ATR, three-valued stock-in-play, VWAP side, the actionable quote and spread,
  mandatory halt/macro status and the supplied M4.3 preliminary geometry. No
  threshold is hardcoded; the caller supplies every value, window minute, feature
  binding and status fact. `Orb5EligibilityMachine` proposes canonical
  transitions for the M4.2 engine and advances only after storage acknowledges
  them. Two fresh protected runs of the full `tests/trade_alerts_contracts`
  selection passed 1,397 tests in 321.49 and 319.15 seconds by pytest's own
  figure (controller wall 324.632 and 322.335 seconds), inside the 420-second
  limit, and each run's results.xml shows the 143 M6.1 cases passing. A separate
  repeatability phase ran the 20 recording node IDs, 30 tests per run, twice in
  fresh processes, in 102.80 and 102.88 seconds. All runs had zero failures,
  errors and skips, clean isolation and cleanup, and byte-identical long/short
  recordings at 3,832 and 3,826 bytes. Every earlier milestone recording, including
  the M5.3 replay fingerprint, is unchanged. See M6_1_VERIFICATION.md and
  M6_1_LOCAL_CHECKS.json. Independent review decides acceptance. This finished
  offline row does not close the required gate row above.
- [!] **M6.2 approved-rule gate:** the exact buffer, acceptance minimum,
  participation minimums, stale-extension, attempt quota and post-action cooldown
  values come from M03B_ORB5_V1, which is still PROPOSED in M0.3B. No value may
  be adopted by inference. The offline supplied-input slice may proceed; the
  rule-bearing branch reopens only after that definition is adopted.
- [!] **M6.2 tape and projection source gate:** `INTENSITY_15S_MEAN20_V1`,
  verified minute-start volume baselines, trade eligibility, corrections,
  sub-minute coverage and their 20-prior-session references remain blocked under
  M3.2 and M0.2/M2.3. Final one-minute bars cannot supply those paths, and the
  supplied fixtures here establish none of them.
- [x] **M6.2 — offline actionable trigger for `CRVOL_ORB5`:**
  `consensus_engine/orb5_trigger.py` implements the supplied-input slice of D-090
  sections 4-5: the recomputed pre-crossing buffer and candidate boundary, the
  freeze at t0, the consecutive same-arm crossing test, the ten-sample acceptance
  window from the supplied open second through the supplied close second, the
  tape and projected-quote arms kept strictly separate, the fresh last trade at
  or beyond the frozen boundary, the current M6.1 eligibility and M4.3 geometry,
  the inside-range close that both invalidates and resets, the pending-bar
  exception that holds action without moving the deadline, and the attempt quota
  and post-action cooldown held by `Orb5TriggerMachine`. No threshold is
  hardcoded; the caller supplies every value and names its own definition
  reference. The owner proposes canonical transitions for the M4.2 engine and
  advances only after storage acknowledges them. Two protected runs of the full
  `tests/trade_alerts_contracts` selection, each a separate published phase in
  its own fresh process, passed **1,616 tests in 335.08 and 336.01 seconds** by
  pytest's own figure (JUnit 335.003 and 335.943, controller wall 338.513 and
  339.425), inside the 420-second limit, and each run's results.xml shows the
  **219 M6.2 cases** passing. A separate repeatability phase ran the 21 recording
  node IDs, 32 tests per run, twice in fresh processes, in 107.67 and 106.05
  seconds, exit code 0 both times, with 37 artifacts per run and 35
  byte-identical. Ordered test IDs are identical, all runs had zero failures,
  errors and skips and clean isolation and cleanup, and of the 38 artifact files
  in each full run 35 are byte-identical, with only `output.txt`, `results.xml`
  and `pipeline-obs.jsonl` differing in timing text. The M6.2 recordings match at
  **5,065 and 5,051 bytes**, and the M6.1 eligibility recording and M5.3 replay
  fingerprint are unchanged. See M6_2_VERIFICATION.md and M6_2_LOCAL_CHECKS.json.
  Independent review decides acceptance. This finished offline row does not close
  either required gate row above.
- [!] **M6.3 approved-rule gate:** the confidence floor, the component weights,
  the factor roster and the reward minimums for this strategy come from
  M03B_ORB5_V1, which is still PROPOSED, and from the M4.3 catalog and M4.4
  factor gates, which stay open. No value may be adopted by inference. The
  offline supplied-input slice may proceed; the rule-bearing branch reopens only
  after those definitions are adopted.
- [!] **M6.3 structure and source gate:** the anchor path, the ATR, the AVWAP,
  the profile and the other structural families, the soft invalidation, the
  runner and the upstream score producers remain blocked under M3.2, M4.3, M4.4
  and M0.2/M2.3. The supplied fixtures here establish none of them.
- [x] **M6.3 — offline risk, targets and confidence for `CRVOL_ORB5`:**
  `consensus_engine/orb5_risk_confidence.py` composes three supplied results at
  one instant: the M6.2 trigger assessment, the M4.3 geometry result and the M4.4
  confidence result. It re-checks that both supplied results describe this frozen
  attempt at this exact arm, direction, crossing, instant and boundary, then
  reports the stop, targets and confidence they already carry. It calculates no
  stop, target, R multiple, factor, score or weight, and it applies no quality
  cutoff: the confidence floor is reported as undefined instead. Any unknown
  input keeps the outcome unavailable; a definite refusal keeps it rejected; a
  complete confidence never repairs refused geometry and the reverse. Each field
  is populated only by the gate that passed for it. Two protected runs of the
  full `tests/trade_alerts_contracts` selection, each a separate published phase
  in its own fresh process, passed **1,696 tests in 330.37 and 334.71 seconds** by
  pytest's own figure (JUnit 330.303 and 334.636, controller wall 333.567 and
  338.006), inside the 420-second limit, and each run's results.xml shows the
  **80 M6.3 cases** passing. A separate repeatability phase ran the 22 recording
  node IDs, 34 tests per run, twice in fresh processes, in 107.84 and 106.49
  seconds, exit code 0 both times, with 39 artifacts per run and 37
  byte-identical. Ordered test IDs are identical, all runs had zero failures,
  errors and skips and clean isolation and cleanup, and of the 40 artifact files
  in each full run 37 are byte-identical, with only `output.txt`, `results.xml`
  and `pipeline-obs.jsonl` differing in timing text. The M6.3 recordings match at
  **3,045 and 3,039 bytes**, and the M6.2 trigger recordings, the M6.1
  eligibility recording and the M5.3 replay fingerprint are unchanged. See
  M6_3_VERIFICATION.md and M6_3_LOCAL_CHECKS.json. Independent review decides
  acceptance. This finished offline row does not close either required gate row
  above.
- [!] **M6.4 approved-rule gate:** the thresholds, buffers, acceptance minimums,
  participation minimums, quotas, cooldowns, weights, factor roster and reward
  minimums these scenarios supply still come from M03B_ORB5_V1, which is
  PROPOSED, and from the M4.3 catalog and M4.4 factor gates, which stay open. A
  passing scenario adopts no value by inference.
- [!] **M6.4 source and historical-data gate:** the six scenarios are synthetic
  supplied records. Actual point-in-time minute, tape, quote, catalyst,
  halt/macro and 20-prior-session coverage, finality, corrections and adjustment
  history remain blocked under M0.2, M2.3, M3.1, M3.2 and M3.6. No walk-forward,
  ablation, shadow validation or promotion evidence is produced here; M16 and
  M17 keep those owners. Nothing here measures profit or edge.
- [x] **M6.4 — offline replay and synthetic tests for `CRVOL_ORB5`:**
  `consensus_engine/orb5_replay.py` adds the M4.1 adapter that drives the M6.1
  eligibility machine, the M6.2 attempt owner and the M6.3 composition through
  the M5.3 replay runner over one chronological sequence of supplied evaluation
  instants. `tests/trade_alerts_contracts/test_orb5_replay.py` replays the six
  named scenarios: the clean catalyst breakout and its mirrored short twin both
  reach ALERT_TRIGGERED with a READY composition; the low-RVOL fakeout and the
  too-wide opening range stay WATCHING and open no attempt even with the same
  supplied crossing; the resistance attempt runs out its own deadline to
  WAITING_FOR_RESET and returns to ARMED on a supplied inside-range close; and a
  stale quote at the attempt evaluation invalidates the open attempt and keeps
  the composition UNAVAILABLE. No threshold is hardcoded, the replay rules are
  exactly the union of the M6.1 and M6.2 pairs, transitions advance only after
  the caller records them, and `heads_up`/`actionable` stay empty because
  candidate assembly and delivery keep their M4.5/M4.6 owners. Each scenario is
  replayed twice in separate fresh databases and must render identical JSON,
  identical fingerprints and one deterministic combined proof artifact. See
  M6_4_VERIFICATION.md and M6_4_LOCAL_CHECKS.json. The controller's published
  protected stage supplies this row's counts, timings and artifact hashes; no
  builder-local figure is recorded here. Independent review decides acceptance.
  This finished offline row does not close either required gate row above.
- [x] **M7.1 definition gate resolved by M0.3C:** `M03C_HOD_COMP_RS_V1` freezes
  the `HOD_COMP_RS` HOD/LOD ownership, compression windows, overlap and seeding
  rules, distance cutoffs, trigger buffer and acceptance duration in PLAYBOOKS
  section 16. This definition-only resolution does not close the separate source
  and historical-data gate below.
- [!] **M7.1 source and historical-data gate:** every bar measured here is a
  synthetic supplied record. Actual point-in-time minute coverage, finality,
  corrections and adjustment history remain blocked under M0.2, M2.3, M3.1, M3.2
  and M3.6. Nothing here measures profit or edge.
- [x] **M7.1 — point-in-time HOD/LOD and compression for `HOD_COMP_RS`:**
  `consensus_engine/hod_compression.py` measures, from one supplied canonical
  minute batch at one evaluation instant, the HOD/LOD frozen at a supplied
  instant and one compression window. The reference reads only the session
  minutes that had ended at the freeze instant and requires unbroken coverage
  from the open, so a later or final-session extreme cannot leak backwards. The
  window reports its high, low, recent range, prior range, bar count, ratio,
  whether it began at or after the freeze, and the distances from the window
  extremes to the frozen reference in supplied minute-ATR units. The caller
  supplies the overlap answer, both bar counts, the freeze instant, the ATR and
  its own definition reference, so the open PLAYBOOKS section 13 questions stay
  the caller's; the module compares no measurement against any threshold and
  carries none of the playbook's numbers. Any missing, provisional, untraded,
  non-contiguous or unexpectedly overlapping interval keeps its own value
  unavailable with a named reason, and the reference and window are refused
  independently. `tests/trade_alerts_contracts/test_hod_compression.py` covers
  the freeze against a later high, both supplied window definitions, every named
  refusal and one deterministic recording. See M7_1_VERIFICATION.md and
  M7_1_LOCAL_CHECKS.json. The controller's published protected stage supplies
  this row's counts, timings and artifact hashes; no builder-local figure is
  recorded here. Independent review decides acceptance. This finished offline row
  does not close either required gate row above.
- [x] **M7.2 definition gate resolved by M0.3C:** `M03C_HOD_COMP_RS_V1` freezes
  the `HOD_COMP_RS` benchmark, RS15 lookback, warm-up, return basis, trend rules
  and eligibility cutoffs in PLAYBOOKS section 16. This definition-only
  resolution does not close the separate source and historical-data gate below.
- [!] **M7.2 source and historical-data gate:** every stock and benchmark minute
  measured here is a synthetic supplied record. Actual benchmark instruments,
  reference-market coverage and point-in-time minute coverage, finality,
  corrections and adjustment history remain blocked under M0.2, M2.3, M2.4, M3.1,
  M3.2 and M3.6. Nothing here measures profit or edge.
- [x] **M7.2 — RS and trend eligibility for `HOD_COMP_RS`:**
  `consensus_engine/rs_trend_eligibility.py` measures, from two supplied
  canonical minute batches at one evaluation instant, the stock return and the
  benchmark return over the caller's own lookback and their difference, and then
  evaluates the eligibility path through ARMED. The lookback never shortens
  itself: before the supplied number of session minutes has elapsed the warm-up
  flag is 0 and both returns stay unavailable with a named reason, because which
  shorter window is acceptable is exactly the open PLAYBOOKS section 13 question.
  The caller supplies the bar count, the benchmark symbol, the return basis and
  every threshold with its own definition reference, so the module compares only
  supplied numbers and carries none of the playbook's. Thirteen gates are
  reported: the evaluation window, the M7.1 reference and compression flags, the
  minimum price, dollar volume, relative volume, the open move, the RS warm-up,
  the RS trend, the VWAP side, the quote and spread, and the mandatory halt and
  macro facts; six support SETUP_FORMING and twelve support ARMED, and a missing,
  stale, ambiguous or wrongly identified input stays UNKNOWN and never passes.
  The trend gate mirrors for a short. `HodCompRsEligibilityMachine` proposes
  canonical transitions for the M4.2 engine and the M5.1 store and advances only
  after the caller confirms a recorded transition.
  `tests/trade_alerts_contracts/test_rs_trend_eligibility.py` covers the
  measurement, both supplied return bases, every named refusal, all thirteen
  gates in both directions, the machine contract and one deterministic recording
  built from the real M7.1 and M7.2 producers. No existing module, test,
  configuration, migration or protected launcher file changed. See
  M7_2_VERIFICATION.md and M7_2_LOCAL_CHECKS.json. The controller's published
  protected stage supplies this row's counts, timings and artifact hashes; no
  builder-local figure is recorded here. Independent review decides acceptance.
  This finished offline row does not close either required gate row above.
- [x] **M7.3 definition gate resolved by M0.3C:** `M03C_HOD_COMP_RS_V1` freezes
  the `HOD_COMP_RS` trigger buffer, acceptance duration and share, participation
  fallback, heads-up distance, stale-extension limit and session quota in
  PLAYBOOKS section 16. This definition-only resolution does not close the
  separate source and historical-data gate below.
- [!] **M7.3 source and historical-data gate:** every observation, tape
  intensity, projected volume and minute close measured here is a synthetic
  supplied record. Actual tape and quote coverage, point-in-time finality,
  corrections and adjustment history remain blocked under M0.2, M2.3, M2.4, M3.1,
  M3.2 and M3.6. Nothing here measures profit or edge.
- [x] **M7.3 — heads-up and actionable path for `HOD_COMP_RS`:**
  `consensus_engine/hod_comp_rs_trigger.py` freezes one structure from the
  supplied M7.1 reference extreme, compression range and ATR and the caller's own
  buffer floor and volatility multiple, and then reports two paths. The heads-up
  notice reports one approaching structure only while the supplied M7.2
  eligibility is ARMED, the supplied M7.1 distance is inside the caller's own
  cutoff and the last trade still stands inside the frozen boundary. The
  actionable path tests the crossing on the caller's own grid and then reports
  six gates: the structure still active inside its acceptance window, the
  acceptance share over the fixed sample grid, the participation arm, the last
  trade beyond the boundary, the M7.2 eligibility and the move not already stale
  in R. The caller supplies every number with its own definition reference, so
  the module compares only supplied numbers and carries none of the playbook's.
  The two participation arms stay separate: the tape arm consumes only its own
  supplied intensity and the quote-projection arm only its own supplied
  projection, so enabling one can never repair the other. A missing, stale,
  ambiguous, late, uncovered or wrongly identified input stays UNKNOWN and never
  passes, and one unknown sample keeps the whole acceptance count unknown. Only a
  compression-close invalidation, a broken-coil close, lost coverage at the arm's
  own instant, a mandatory halt or an unknown mandatory input ends a structure
  outright; a merely failing known gate leaves it running until its own supplied
  deadline. `HodCompRsTriggerMachine` owns one structure serially, reserves its
  number, enforces the supplied session quota and cooldown, proposes canonical
  transitions for the M4.2 engine and the M5.1 store, and advances only after the
  caller confirms a recorded transition; an alert that already fired records its
  inside-compression close as WAITING_FOR_RESET and never re-arms silently.
  `tests/trade_alerts_contracts/test_hod_comp_rs_trigger.py` covers the frozen
  structure, the crossing test, both reported paths in both directions and both
  participation modes, every named refusal, the owner contract and one
  deterministic recording built from the real M7.1, M7.2 and M7.3 producers. No
  existing module, test, configuration, migration or protected launcher file
  changed. See M7_3_VERIFICATION.md and M7_3_LOCAL_CHECKS.json. The controller's
  published protected stage supplies this row's counts, timings and artifact
  hashes; no builder-local figure is recorded here. Independent review decides
  acceptance. This finished offline row does not close either required gate row
  above.
- [x] **M7.4 definition gate resolved by M0.3C:** `M03C_HOD_COMP_RS_V1` freezes
  the `HOD_COMP_RS` stop, target, score, cooldown and suppression rules in
  PLAYBOOKS section 16. This definition-only resolution does not close the
  separate source and historical-data gate below.
- [!] **M7.4 source and historical-data gate:** every observation, score, stop,
  target and prior action composed here is a synthetic supplied record. Actual
  tape and quote coverage, point-in-time finality, corrections and adjustment
  history remain blocked under M0.2, M2.3, M2.4, M3.1, M3.2 and M3.6. Nothing
  here measures profit or edge.
- [x] **M7.4 — risk, confidence and suppression for `HOD_COMP_RS`:**
  `consensus_engine/hod_comp_rs_risk_confidence.py` composes four supplied things
  at one evaluation instant: the M7.3 `TriggerAssessment`, the caller's own
  structural stop and targets, the M4.4 confidence result, and the caller's own
  suppression policy and prior-action history. It re-checks that every supplied
  part describes this frozen structure at this exact instant and then reports
  what they already carry; it calculates no stop, no target, no R multiple, no
  score and no weight. The supplied reading must use this arm, direction,
  structure number, crossing and evaluation instant and must already have been
  available; an entry inside the frozen boundary, a stop on the wrong side, a
  stop inside the frozen compression, a target behind the entry and a target
  claiming more reward than its own prices show never pass, while how far outside
  the coil the stop sits and how much reward a target must show stay the caller's
  own undefined numbers. No quality cutoff is applied: the confidence floor is
  reported as undefined instead, so a final score of 0 and one of 100 both
  compose. The suppression decision reads only the caller's own history: a second
  actionable for the same structure, the session's structure quota in this
  direction, the cooldown since the latest action in this direction and an
  outstanding opposite-direction action inside the caller's own window, each
  reported in one fixed order. A heads-up never suppresses the actionable, the
  other direction consumes neither quota nor cooldown, and a missing, incomplete,
  stale or ahead-of-evaluation history stays UNKNOWN so a duplicate can never
  pass on silence alone. Any unknown keeps the whole outcome UNAVAILABLE, a
  definite refusal is REJECTED, and an otherwise complete action the history
  suppresses is SUPPRESSED. The `SuppressionEvent` record itself keeps its M4.5
  owner: this module reports the reasons that caller would record.
  `tests/trade_alerts_contracts/test_hod_comp_rs_risk_confidence.py` covers the
  composed path in both directions and both arms, every named refusal, every
  suppression reason and its ranking, the undefined names, and one deterministic
  recording built from the real M7.3 and M4.4 producers over the M4.2 engine and
  the M5.1 store. No existing module, test, configuration, migration or protected
  launcher file changed. See M7_4_VERIFICATION.md and M7_4_LOCAL_CHECKS.json. The
  controller's published protected stage supplies this row's counts, timings and
  artifact hashes; no builder-local figure is recorded here. Independent review
  decides acceptance. This finished offline row does not close either required
  gate row above.
- [x] **M7.5 definition gate resolved by M0.3C:** `M03C_HOD_COMP_RS_V1` freezes
  the complete `HOD_COMP_RS` replay and outcome rule set in PLAYBOOKS section 16.
  This definition-only resolution does not turn the earlier synthetic scenarios
  into historical evidence and does not close the separate source and
  historical-data gate below.
- [!] **M7.5 source and historical-data gate:** the five scenarios are synthetic
  supplied records. Actual point-in-time minute, tape, quote, benchmark,
  halt/macro and prior-session coverage, finality, corrections and adjustment
  history remain blocked under M0.2, M2.3, M2.4, M3.1, M3.2 and M3.6. No
  walk-forward, ablation, shadow validation or promotion evidence is produced
  here; M16 and M17 keep those owners. Nothing here measures profit or edge.
- [x] **M7.5 — offline replay and synthetic tests for `HOD_COMP_RS`:**
  `consensus_engine/hod_comp_rs_replay.py` adds the M4.1 adapter that drives the
  M7.2 eligibility machine, the M7.3 structure owner and the M7.4 composition
  through the M5.3 replay runner over one chronological sequence of supplied
  evaluation instants. `tests/trade_alerts_contracts/test_hod_comp_rs_replay.py`
  replays the five named scenarios: the clean compression break and its mirrored
  short twin each report a heads-up, cross their own frozen boundary and reach
  ALERT_TRIGGERED with a READY composition; the failed break never meets the
  supplied acceptance share, runs out its own deadline to WAITING_FOR_RESET and
  returns to ARMED on a supplied inside-compression close; the RS-weak case keeps
  every supplied setup gate passing at SETUP_FORMING and opens nothing even with
  the same supplied structure and crossing; and a supplied move already extended
  past the caller's own limit keeps the structure at CROSSING_OBSERVED with a
  REJECTED composition that still reports the stop and confidence beside its
  refusal. No threshold is hardcoded, the replay rules are exactly the union of
  the M7.2 and M7.3 pairs, transitions advance only after the caller records
  them, and `heads_up`/`actionable` stay empty because candidate assembly and
  delivery keep their M4.5/M4.6 owners. Each scenario is replayed twice in
  separate fresh databases and must render identical JSON, identical fingerprints
  and one deterministic combined proof artifact. A recorded heads-up keeps the
  exact frozen structure it described: a later supplied structure with changed
  prices or a changed ATR is refused for long and for short, so the noticed
  boundary cannot be walked. See M7_5_VERIFICATION.md. Because that repair
  changed the module and its tests, the earlier published figures and hashes are
  invalidated; the controller's rerun of the focused
  `tests/trade_alerts_contracts/test_hod_comp_rs_replay.py` phase, the
  `tests/trade_alerts_contracts` acceptance phase and the two-run repeatability
  phase supplies the fresh figures and hashes. Independent review
  decides acceptance. This finished offline row does not close either required
  gate row above.
- [x] **M8.1 definition gate resolved by M0.3D:** `M03D_OR_FAILURE_REV_V1`
  freezes the meaningful excursion, crossing-based failure timer, inside-
  acceptance window, mandatory close, stronger failure-bar arm and reversal
  ownership. This definition result does not alter M8.1's tested supplied-input
  code or close its separate source and historical-data gate.
- [!] **M8.1 source and historical-data gate:** the opening range, the attempt
  records, the breakout extreme and the reacceptance close are synthetic
  supplied records. Actual point-in-time minute, tape and quote coverage,
  finality, corrections and adjustment history remain blocked under M0.2, M2.3,
  M2.4, M3.1, M3.2 and M3.6. Nothing here measures profit or edge.
- [x] **M8.1 — ORB→failure transition support:** the shared offline support that
  lets a supplied opening-range break hand over to a failure/reversal owner.
  `consensus_engine/or_failure_handoff.py` reuses the M3.6 opening-range
  snapshot, the M6.2 attempt records and the M4.2 transition engine exactly as
  those milestones produce them. The reversal direction is the mirror of the
  break; only a supplied M6.2 ending of `INSIDE_OR_CLOSE_INVALIDATION` or
  `ACCEPTANCE_DEADLINE_PASSED` hands anything over; the supplied M3.6 snapshot
  must carry the M3.6 feature version, the same instrument, a complete range and
  extrema equal to the frozen attempt's own opening range; the supplied breakout
  extreme must lie beyond the frozen buffered boundary and clear the caller's own
  ATR multiple; and only an available final close after the crossing, strictly
  inside the unbuffered range and within the caller's own window, reports
  FAILURE_FORMING. A close past that window and a lost coverage flag close a
  taken-over handoff, while a pending or unavailable input stays an explicit
  UNKNOWN at the breakout attempt. The supplied rules stop before
  `OR_FAILURE_REV` ARMED and ALERT_TRIGGERED, which stay with M8.2 together with
  the trigger, stop, targets and score. `OrFailureHandoffMachine` advances only
  after the caller confirms each recording, records the break before its failure,
  refuses a changed attempt, a second handoff of the same ended attempt and a
  fall back from the recorded failure, and closes a withdrawn handoff explicitly
  instead of dropping it. `tests/trade_alerts_contracts/test_or_failure_handoff.py`
  covers the supplied contracts, all five gates with every named refusal in both
  directions, the owner's proposals, refusals, release, expiry and restore, a
  refused recording, and one long/short path through the real M4.2 engine and
  M5.1 store writing the deterministic `m8_1_or_failure_handoff_proof.json`
  recording. See M8_1_VERIFICATION.md. The implementation and its coverage are
  finished, and all three protected selections ran with no failures, no errors
  and no skips and with clean isolation and cleanup: the focused
  `tests/trade_alerts_contracts/test_or_failure_handoff.py` selection, the whole
  `tests/trade_alerts_contracts` acceptance selection in one child process, and
  the two-process repeatability selection, whose runs wrote a byte-identical
  `m8_1_or_failure_handoff_proof.json` and left every earlier milestone recording
  unchanged. The two earlier attempts could not finish the directory selection
  because the launcher capped each child process at 420 seconds; the controller
  has since raised that cap itself under its own separately reviewed protection
  repair, so the single directory run reports instead of timing out and the split
  groups are no longer needed. No build session edited, bypassed or retried a
  protection file, and nothing in the module or its coverage changed to make the
  directory fit; see M8_1_LAUNCHER_LIMITATION.txt and M8_1_LOCAL_CHECKS.json. The
  controller's published phases supply the figures and hashes; no builder-run
  number is recorded. Independent review decides acceptance. This offline row
  does not close the source and historical-data gate; M0.3D separately closes
  the definition gate. All switches stay off.
- [x] **M8.2 definition gate resolved by M0.3D:** `M03D_OR_FAILURE_REV_V1`
  freezes the confirmation arms, displacement, acceptance, stop, targets,
  inclusive 0.40R staleness and research score floor. This definition result
  does not alter M8.2's tested supplied-input code or close its separate source
  and historical-data gate.
- [!] **M8.2 source and historical-data gate:** the handoff, the last trade, the
  confirmation close, the failure bar, the inside acceptance, the quote, the
  stop, the targets and the scores are synthetic supplied records. Actual
  point-in-time minute, tape and quote coverage, finality, corrections and
  adjustment history remain blocked under M0.2, M2.3, M2.4, M3.1, M3.2 and M3.6.
  Nothing here measures profit or edge.
- [x] **M8.2 — `OR_FAILURE_REV`:** the strategy that consumes the M8.1 handoff on
  supplied inputs. `consensus_engine/or_failure_rev.py` carries one handed-over
  failed break the rest of the PLAYBOOKS section 5 chain,
  `FAILURE_FORMING -> ARMED -> ALERT_TRIGGERED`, reusing the M8.1 assessment, the
  M6.2 attempt records, the M2.3 quote decision, the M4.3 risk and target
  records, the M4.4 composition and the M4.2 engine exactly as those milestones
  produce them. Only a current M8.1 FAILURE_FORMING handoff opens the reversal; a
  handoff from another instant, an unknown M8.1 gate and a handoff that is not
  failure forming each keep the owner below ARMED, and a closed handoff closes
  the reversal with it. The supplied last trade must stand back inside the failed
  edge and clear the caller's own ATR multiple; each confirmation arm — the
  mandatory final close back inside the range and the stronger break of the
  supplied failure bar's own extreme — is its own supplied definition and neither
  stands in for the other; the supplied inside-acceptance share, spread, stop,
  targets and confidence are re-checked, never recomputed; and a move that
  already ran past the caller's own maximum R closes the reversal instead of
  being reported late. The supplied geometry must be framed on this direction,
  attempt, crossing and instant, the entry must lie inside the failed range, the
  stop must sit beyond the break's own furthest traded price, and a stated reward
  the supplied prices do not support is refused. No number of the module's own
  and no confidence cutoff is applied. `OrFailureRevMachine` advances only after
  the caller confirms each recording, records ARMED before the actionable state,
  refuses a different break once one is taken over, refuses a fall back from an
  actionable reversal and closes a withdrawn reversal explicitly instead of
  dropping it. `tests/trade_alerts_contracts/test_or_failure_rev.py` covers the
  supplied contracts, all nine gates with every named refusal in both directions,
  both confirmation arms, the owner's proposals, refusals, expiry and restore, a
  refused recording, and one long/short path through the real M4.2 engine and
  M5.1 store writing the deterministic `m8_2_or_failure_rev_proof.json`
  recording. See M8_2_VERIFICATION.md. The implementation and its coverage are
  finished, and all three protected selections ran with no failures, no errors
  and no skips and with clean isolation and cleanup: the focused
  `tests/trade_alerts_contracts/test_or_failure_rev.py` selection, the whole
  `tests/trade_alerts_contracts` acceptance selection in one child process, and
  the two-process repeatability selection, whose runs wrote a byte-identical
  `m8_2_or_failure_rev_proof.json`. An earlier session in the same build run
  wrote the module and its coverage and stopped at its own API session limit
  before any protected run; that partial work was preserved and only its fixtures
  were repaired, in the test file alone. No build session edited, bypassed or
  retried a protection file; see M8_2_LOCAL_CHECKS.json. The controller's
  published phases supply the figures and hashes; no builder-run number is
  recorded. Independent review decides acceptance. This offline row does not
  close the source and historical-data gate; M0.3D separately closes the
  definition gate. All switches stay off.
- [x] **M8.3 `FIRST_PULLBACK_VWAP` definition gate resolved by M0.3E:** the impulse and
  reversal-bar definitions, swing confirmation, pullback counting, the
  slope/cross convention, the retracement band, the volume-contraction ratio, the
  VWAP distances and the AVWAP question are frozen for research in
  M0_3E_DEFINITION_PACKET.md and PLAYBOOKS §18. Every definition used
  by the offline row is supplied by the caller, no leg is judged valid there, and
  a complete measurement adopts nothing.
- [!] **M8.3 source and historical-data gate:** the minute bars, the minute ATR
  and the VWAP are synthetic supplied records. Actual point-in-time minute
  coverage, finality, corrections and adjustment history remain blocked under
  M0.2, M2.3, M2.4, M3.1 and M3.2. Nothing here measures profit or edge.
- [x] **M8.3 — impulse/pullback primitives:** the shared offline impulse and
  pullback support the `FIRST_PULLBACK_VWAP` playbook needs, on supplied inputs.
  `consensus_engine/impulse_pullback.py` measures one impulse leg over the
  caller's own supplied frozen window and the pullback that followed it, reusing
  the M2.2 canonical `Bar`, `FeatureValue` and `FeatureSnapshot` records, the
  M3.1 `HistoryBatch` coverage view and the M1.2 session clock exactly as those
  milestones produce them. The supplied `PullbackPolicy` carries the direction,
  the minimum pullback length and whether the legs read from the bar extremes or
  the closes, and the impulse window's own start and freeze instants are supplied
  too, so nothing here decides where an impulse began. One snapshot reports
  nineteen named values: the impulse origin, extreme, distance, bar count and
  volume, whether the extreme printed after its origin, the pullback extreme, bar
  count, reversal-bar high and low and volume, the pullback depth, retracement
  and volume ratio, each leg's own completeness flag, and the impulse distance
  and both extremes against the supplied VWAP in supplied minute-ATR units. The
  impulse stays frozen while a later high prints, the pullback walks forward one
  whole completed minute at a time, and each leg refuses on its own: an uncovered,
  non-contiguous, provisional, missing, untraded, contradicted or foreign-type
  window keeps its own values unavailable by name without blocking the other leg.
  An out-of-order extreme, a pullback deeper than its impulse and a negative
  retracement are reported as measured, a flat impulse and a volumeless impulse
  name their zero instead of dividing, and a missing supplied ATR or VWAP leaves
  only its own distances unavailable. No rule number of the module's own is
  adopted. `tests/trade_alerts_contracts/test_impulse_pullback.py` covers the
  policy contract, both directions on one mirrored session, both reading
  conventions, the frozen impulse, the pullback window and its minimum length,
  every named refusal, the reported geometries, both zero-division reasons, the
  ATR and VWAP distances, incompatible or absent history, a closed day, the
  public scope checks, deep immutability and the deterministic
  `m8_3_impulse_pullback_proof.json` recording. See M8_3_VERIFICATION.md. The
  implementation and its coverage are finished, and all three protected
  selections ran with no failures, no errors and no skips and with clean
  isolation and cleanup: the focused
  `tests/trade_alerts_contracts/test_impulse_pullback.py` selection, the whole
  `tests/trade_alerts_contracts` acceptance selection in one child process, and
  the two-process repeatability selection, whose runs wrote a byte-identical
  `m8_3_impulse_pullback_proof.json`. No build session edited, bypassed or
  retried a protection file; see M8_3_LOCAL_CHECKS.json. The controller's
  published phases supply the figures and hashes; no builder-run number is
  recorded. Independent review decides acceptance. This offline row does not
  close the source and historical-data gate; M0.3E separately closes the
  definition gate. All switches stay off.
- [x] **M8.4 `FIRST_PULLBACK_VWAP` definition gate resolved by M0.3E:** the impulse and
  reversal-bar definitions, swing confirmation, pullback counting, the
  slope/cross convention, the retracement band and its kill value, the
  volume-contraction ratio, the VWAP distances, the trigger offset, the spread
  limit, the reward minimum, the confidence floor and the AVWAP question are
  frozen for research in M0_3E_DEFINITION_PACKET.md and PLAYBOOKS §18. Every threshold used
  by the offline row is supplied by the caller,
  which completed pullback is the first one is not decided there, and a passing
  gate adopts nothing.
- [!] **M8.4 source and historical-data gate:** the M8.3 measurement, the minute
  ATR, the VWAP level, slope and cross count, the relative-strength reading, the
  last trade and the quote are synthetic supplied records. Actual point-in-time
  coverage, finality, corrections, adjustment history and tape/quote cadence
  remain blocked under M0.2, M2.3, M2.4, M3.1, M3.2 and M7.2. Nothing here
  measures profit or edge.
- [x] **M8.4 — `FIRST_PULLBACK_VWAP`:** the strategy that carries one supplied
  M8.3 impulse and pullback measurement the rest of the PLAYBOOKS section 6 chain
  on supplied inputs. `consensus_engine/first_pullback_vwap.py` reports fifteen
  named gates through `PULLBACK_FORMING -> ARMED -> ALERT_TRIGGERED`: the M8.3
  measurement, the impulse size and order, the impulse distance from VWAP, the
  last trade against the VWAP, the VWAP slope, the VWAP crosses, relative
  strength, the retracement band, the pullback volume ratio, the pullback
  support, the reversal-bar trigger, the quote spread, which pullback of the
  session this is, the supplied stop and targets and the supplied M4.4
  confidence. It reuses the M8.3 `FeatureSnapshot` and `PullbackPolicy`, the M6.2
  `Observation`, the M2.3 `QuoteEventDecision`, the M4.4 `ConfidenceResult`, the
  M4.2 `TransitionRules` and the M1.3 canonical risk, target, session and
  transition records exactly as those milestones produce them. The supplied
  `PullbackVwapPolicy` carries every threshold, and the supplied VWAP slope and
  relative-strength readings are read in the trade's own direction because the
  convention belongs to the definition gate. Only a current, complete measurement
  of this symbol, direction and instant opens the chain; an incomplete impulse or
  pullback leg keeps the owner at a forming pullback while naming the leg's own
  M8.3 reason. The trigger level is the measured reversal-bar extreme offset by
  the greater of the caller's own absolute minimum and its own multiple of the
  supplied minute ATR. Lost coverage, a cross count above the supplied maximum, a
  retracement beyond the supplied kill value and a pullback ordinal beyond the
  supplied maximum close the setup; every other failing known gate leaves the
  owner where it stood. The supplied geometry is re-checked against the measured
  reversal bar and pullback extreme and never calculated, and no confidence
  cutoff is applied: the floor, the stop pad, the reward minimum, the impulse
  definition, the pullback counting, the slope convention, the AVWAP question and
  the tape-acceleration preference are named in `unavailable` instead.
  `FirstPullbackVwapMachine` proposes canonical M4.2 transitions, records the
  formed pullback before the action, advances only after the caller confirms the
  recording, refuses a second impulse window, a fall back and a reopen, can
  expire and can be restored from explicit saved facts.
  `tests/trade_alerts_contracts/test_first_pullback_vwap.py` covers every
  supplied record contract, the rules chain, one actionable continuation in both
  directions on the mirrored M8.3 session, every named refusal on each gate, both
  zero-division reasons, the exact trigger boundary, the owner's full lifecycle
  and restore checks, a refused recording and the deterministic
  `m8_4_first_pullback_vwap_proof.json` recording through the real M4.2 engine and
  M5.1 store. See M8_4_VERIFICATION.md. The implementation and its coverage are
  finished, and all three protected selections ran with no failures, no errors and
  no skips and with clean isolation and cleanup: the focused
  `tests/trade_alerts_contracts/test_first_pullback_vwap.py` selection, the whole
  `tests/trade_alerts_contracts` acceptance selection in one child process, and
  the two-process repeatability selection, whose runs wrote a byte-identical
  `m8_4_first_pullback_vwap_proof.json`. No build session edited, bypassed or
  retried a protection file; see M8_4_LOCAL_CHECKS.json. The controller's
  published phases supply the figures and hashes; no builder-run number is
  recorded. Independent review decides acceptance. This offline row does not
  close the source and historical-data gate; M0.3E separately closes the
  definition gate. All switches stay off.
- [!] **M8.5 cross-strategy definition gate:** primary-thesis ownership,
  equal-score tie breaking, the merge rule, opposite-direction suppression and
  reversal ownership remain unresolved under PLAYBOOKS section 11, MASTER_SPEC
  section 10, M0.3 and M4.7. The approximate three-minute and 0.25-ATR priors
  are not adopted. M0.3B is still PROPOSED.
- [!] **M8.5 source and historical-data gate:** the candidates, minute ATR and
  M8.1 handoff evidence are synthetic supplied records. Actual same-symbol
  overlap, point-in-time ATR coverage, outcome correlation and portfolio
  behavior remain blocked under M0.2, M2.3, M2.4, M4.7 and M9. Nothing here
  measures profit or edge.
- [x] **M8.5 — cross-strategy interaction tests:** the offline interaction
  report for supplied candidates from the first four playbooks.
  `consensus_engine/cross_strategy_interaction.py` retains every candidate and
  reports every same-symbol pair in stable order, the time distance, trigger and
  stop distance in the supplied ATR, lifetime overlap, confidence comparison,
  the documented playbook relationship and any declared M8.1/M8.2 transition.
  The caller supplies the merge window, ATR multiple and whether both supplied
  price regions or either one must pass. Same-direction records are labeled as
  overlapping, separate or unknown; opposite directions are labeled as a
  conflict, a sequence or a backed declared transition. The report never picks a
  primary, breaks an equal-score tie, merges, suppresses or sends anything, and
  every unresolved choice stays named in `unavailable`.
  `tests/trade_alerts_contracts/test_cross_strategy_interaction.py` covers the
  policy and record contracts, stable all-pair reporting, both directions, exact
  supplied boundaries, non-overlapping lifetimes, both region rules, missing
  ATR, conflicts, sequences, confidence order, equal scores, the real M8.1
  handoff, refused declarations, the first-four playbook labels, future and
  conflicting records and the deterministic
  `m8_5_cross_strategy_interaction_proof.json` recording. See
  M8_5_VERIFICATION.md and M8_5_LOCAL_CHECKS.json. Offline implementation and
  fresh protected proof cover the supporting-record identity repair. Independent
  review remains. The historical focused
  stage passed the exact repaired case in one run. Acceptance passed the whole
  `tests/trade_alerts_contracts` directory in one run. The separate repeatability
  selection passed in two runs with matching test IDs and byte-identical
  required recordings. The records preserve each phase's exact selectors,
  figures, hashes, artifact paths and the complete tested-source manifest.
  All tested file contents matched before records-only finalization. Code,
  tests and protection stayed unchanged. Independent review decides acceptance.
  This offline row does not close either required gate above. All switches stay off.
- [x] **M9.1 — Historical replay #1–#4:** the required bounded assessment records
  `INSUFFICIENT_DATA` for all four playbooks without running a synthetic record as
  historical evidence. M9_1_VERIFICATION.md names the exact missing source and
  definition evidence, the responsible prerequisite areas and the reopening
  test. The controller's protected focused and broad phases each passed the
  whole `tests/trade_alerts_contracts` directory once at 2,922 tests. Its separate
  repeatability phase passed the 35 recording selectors twice at 59 tests per
  run, with matching ordered results and required recordings. No return, edge,
  shadow, promotion or activation claim was made. The separate required gate
  below stays open, and all switches stay off.
- [!] **M9.1 historical replay gate:** `INSUFFICIENT_DATA` for `CRVOL_ORB5`,
  `HOD_COMP_RS`, `OR_FAILURE_REV` and `FIRST_PULLBACK_VWAP`. The repository has
  deterministic supplied-record replays but no verified point-in-time historical
  dataset for these four playbooks. Research definitions for all four are now
  frozen through M0.3E; their definitions do not supply the
  missing history. No replay rule may be chosen after seeing returns. Reopen only with the dated
  source manifest and point-in-time coverage from M0.2, M2.2, M2.3, M2.4, M6.4,
  M7.5, M8.2 and M8.4, approved frozen definitions from M0.3, and the approved
  execution/outcome policy from M5.2, as listed in M9_1_VERIFICATION section 3.
- [x] **M9.2 — initial validation report:** published the four M9.1
  `INSUFFICIENT_DATA` results, missing evidence, responsible owner milestones and
  reopening tests without upgrading their evidence stage. The report is now in
  `docs/initial_strategy_validation.md`. The protected focused phase selected the
  whole `tests/trade_alerts_contracts` directory and passed 2,922 tests in one
  run with a controller wall time of 522.087 seconds. The protected broad
  acceptance phase also selected the whole directory and passed 2,922 tests in
  one run with a controller wall time of 521.483 seconds. The separate
  repeatability phase selected its published 35 recording checks and passed 59
  tests in each of two runs with a controller wall time of 294.463 seconds; its
  required recordings and ordered results matched. The report records all three
  artifact directories, their file hashes, the complete tested-source manifest
  and source hash. The M9.1 historical replay gate stays open. All switches stay
  off.
- [!] **M9.3 — shadow mode:** blocked before implementation. M4.7's adopted
  options and portfolio rules, the selected M0.2 provider/queue/storage/disk/
  memory budgets, validated input continuity and AT-13 bounded-load proof are
  not complete. Reopen only after those owner milestones publish their required
  proof. No live input, delivery or activation is authorized by this row.
  M9_3_VERIFICATION.md records the failed controller acceptance run: storage
  filled during database setup, then temporary test folders could not be created.
  This is outside the milestone's documentation-only change; protection needs
  separately reviewed environment repair before another acceptance run.
- [!] **M0.2 — current data and shared-capacity audit:** historical bounded audit
  (current source/access, capacity and spending status is in the final M0.2 row
  below and DATA_REQUIREMENTS §§44–48). That earlier offline audit is complete in DATA_REQUIREMENTS §§44–48. Code, offline tests and saved output
  are now separated for every required feed. Three saved days passed the narrow
  collector proof, but the latest dated run, 2026-09-11 Pacific, saved no option
  files and no stock bars. Current entitlement, official field and streaming
  limits, tape/depth, canonical VIX, low-latency catalyst coverage, complete
  sector/minute history and historical option quotes remain blocked by data or
  supervised access. Account-wide request control is absent: the configured
  regular-session collector can reach 47 Schwab requests per minute before other
  callers, while its 110-per-minute bucket is process-local. The saved sample
  uses 1.8 GB, both option parts and compacted chains are retained, the filesystem
  is 98% used with 1.8 GB free, and no parquet retention or safe reserve is set.
  Reopen with the exact source and capacity checks in DATA_REQUIREMENTS §48. No
  provider call, credential read, purchase, deletion or activation occurred.
- [!] **M0.3B — controlled research revision:** owner-decision blocker removed
  on 2026-09-13 Pacific by RESEARCH_AUTHORIZATION_20260913.md. The agent owns
  remaining research parameters and must publish versioned deterministic rules
  for both opening ranges, all three entries and both directions, reasonable
  stop/exit alternatives including fixed 3R, and untouched final-validation data.
  Incorporate adopted research definitions into the governing authorities before
  dependent implementation. D-090 remains immutable as a historical arm. This
  reopening does not approve `M03B_ORB5_V1` verbatim, close M0.2 source gates,
  manufacture historical evidence or authorize live activation. Earlier mentions
  of M0.3B being PROPOSED describe the old packet; this row is current research
  authority. Missing definitions remain unfinished work for the agent, not a
  reason to ask the owner to select routine research parameters. Version
  `M03B_OR_RESEARCH_V2` now freezes all twelve base combinations, two stops,
  three exits, 72 result arms, comparison control, costs, reporting and boundary
  cases. The required coverage-only audit found no qualifying source manifest,
  so exact development/calibration/final dates and the manifest hash cannot be
  recorded honestly. Replay remains blocked until M0.2 supplies that source
  proof. No results were opened and all switches stay off. The five other
  unresolved PLAYBOOKS §13 rows remained required after M0.3D. This count is
  historical; PLAYBOOKS §22 records the current fully frozen definition status.
- [x] **M0.3C — HOD_COMP_RS deterministic research definitions:** freeze the
  PLAYBOOKS §13 `HOD_COMP_RS` windows, HOD/LOD ownership, RS warm-up,
  compression seeding, acceptance, tape fallback, stop/target, score and outcome
  rules with mirrored boundary examples. Version `M03C_HOD_COMP_RS_V1` is now
  frozen in M0_3C_DEFINITION_PACKET.md and incorporated into PLAYBOOKS §16,
  DATA_REQUIREMENTS §50, TESTING_AND_VALIDATION §71 and D-093. Protected document
  acceptance passed: the focused and broad stages each passed 2,922 tests, and
  two fresh repeatability runs passed 59 tests each with 47 recording files
  matching byte for byte. See M0_3C_VERIFICATION.md. This definition work is independent of M0.3B's
  missing source manifest and does not authorize replay or live use.
- [x] **M0.3D — OR_FAILURE_REV deterministic research definitions:** version
  `M03D_OR_FAILURE_REV_V1` freezes the PLAYBOOKS §13 meaningful excursion,
  crossing-based timer, inside acceptance, mandatory close and stronger
  failure-bar arm, reversal ownership, mirrored stop/target, score and outcome
  rules, including separate structural, fixed 2R and fixed 3R exit arms, with
  boundary examples. It is incorporated into PLAYBOOKS §17,
  DATA_REQUIREMENTS §51, TESTING_AND_VALIDATION §72 and D-094. This independent
  definition work passed protected document acceptance: the focused and broad
  stages each passed 2,922 tests, and two fresh repeatability runs passed 59
  tests each with 47 recording files matching byte for byte. See
  M0_3D_VERIFICATION.md. It does not establish source coverage, authorize replay
  or permit live use. All switches stay off.
- [x] **M0.3E — FIRST_PULLBACK_VWAP deterministic research definitions:** version
  `M03E_FIRST_PULLBACK_VWAP_V1` freezes the PLAYBOOKS §13 impulse, two-bar swing
  confirmation, independent pullback count, duration-normalized volume,
  three-minute VWAP slope, strict close-cross convention, exact 0.65/0.70 depth
  roles, reversal bar, first-versus-second priority, mirrored stop/targets,
  score and outcome rules with boundary examples. It is incorporated into
  PLAYBOOKS §18, DATA_REQUIREMENTS §52, TESTING_AND_VALIDATION §73 and D-095.
  Protected document acceptance passed: the focused and broad stages each
  passed 2,922 tests, and two fresh repeatability runs passed 59 tests each
  with 47 recording files matching byte for byte. See M0_3E_VERIFICATION.md.
  This independent definition work does not establish source
  coverage, authorize replay or permit live use. All switches stay off.
- [x] **M0.3F — INDEX_OPEN_DRIVE_BREADTH deterministic research definitions:**
  version `M03F_INDEX_OPEN_DRIVE_BREADTH_V2` freezes the PLAYBOOKS §13 full,
  sector-proxy and hybrid breadth components and coverage, mirrored short
  treatment, drive-efficiency denominator and zero handling, exact 0.35/0.40
  retracement roles, ten-second acceptance and warning, reduced-priority and
  suppression behavior with boundary examples. It is incorporated into
  PLAYBOOKS §19, DATA_REQUIREMENTS §53, TESTING_AND_VALIDATION §74 and D-096.
  Review found V1 did not select a VWAP mode or define the Up Volume interval
  and observation sequence. V2 now selects `SESSION_VWAP_BAR_HLC3_V1` throughout
  and session-to-evaluation per-trade directional shares with exact predecessor,
  neutral, ordering and correction rules. Earlier protected proof belongs to V1. V2 passed the controller's protected
  focused and broad stages plus two fresh repeatability runs; independent review
  decides acceptance. See M0_3F_VERIFICATION.md.
  Full and hybrid source/history gates remain blocked. This does not authorize
  replay or live use. All switches stay off.
- [x] **M0.3G — GAP_FADE_FAILED_OPEN deterministic research definitions:**
  version `M03G_GAP_FADE_FAILED_OPEN_V1` freezes the PLAYBOOKS §13
  three-minute open-extension window, later inclusive 180-second failed reclaim,
  same-instant stock-minus-SPY from-open benchmark, exact C/D/B/A catalyst
  treatment, stop priority beyond both opening and reclaim extremes, targets,
  score, outcome rules and mirrored gap-down boundary examples. It is
  incorporated into PLAYBOOKS §20, DATA_REQUIREMENTS §54,
  TESTING_AND_VALIDATION §75 and D-097. The controller's protected focused and
  broad stages plus two fresh repeatability runs passed; independent review
  decides acceptance. See M0_3G_VERIFICATION.md. Source and historical-data gates stay open. This does not
  authorize replay or live use. All switches stay off.
- [x] **M0.3H — CAT_FIRST_CONSOL deterministic research definitions:** version
  `M03H_CAT_FIRST_CONSOL_V1` freezes the PLAYBOOKS §13 class-C conflict,
  material and contradictory news, point-in-time classification, first
  consolidation, exact 0.50/0.65 roles, risk, targets, score, outcomes and
  boundary examples. It is incorporated into PLAYBOOKS §21,
  DATA_REQUIREMENTS §55, TESTING_AND_VALIDATION §76 and D-098. The controller's
  protected focused and broad stages plus two fresh repeatability runs passed;
  independent review decides acceptance. See M0_3H_VERIFICATION.md. Source and
  historical-data gates stay open. This does not
  authorize replay or live use. All switches stay off.
- [x] **M0.3I — VP_ACCEPT_LVN deterministic research definitions:** version
  `M03I_VP_ACCEPT_LVN_V1` freezes volume allocation, bins, value area, VPOC,
  LVN/HVN shelves, stability/adjacency, acceptance, stop precedence, zero prior
  volume, refill penalties, score, matched control, outcomes and boundary
  examples. It is incorporated into PLAYBOOKS §22, DATA_REQUIREMENTS §56,
  TESTING_AND_VALIDATION §77 and D-099. Review repair makes the first buffered
  break crossing 1 and the fourth total crossing the immediate kill, with one
  count in the packet, worked example and governing records. Corrected-source
  focused, acceptance and repeatability proof is recorded in
  M0_3I_VERIFICATION.md; independent review decides acceptance. Source and
  historical-data gates stay open. This does not
  authorize replay or live use. All switches stay off.
- [ ] **M3.3 — Relative-strength engine:** implement the dependency-ready
  supplied-input stock-versus-SPY/QQQ/sector calculations from the frozen
  research definitions. Separate source and historical-data gates remain open.
- [ ] M3.3–M5.2 required blocked branches and M5.4, plus M5.6–M19
  implementation/evidence, remain incomplete. Full M2.3 live-provider and M2.4
  data-access requirements also remain unfinished.
- [!] **M3.3 source and historical-data completion:** actual point-in-time stock,
  SPY, QQQ and sector mapping, minute-bar and eligible-trade coverage, original
  availability, correction and compatible adjustment proof remain blocked under
  M0.2/M2.2/M2.4. Synthetic supplied records cannot close this gate.
- [!] **M3.3 — Relative-strength engine:** unaccepted. Selected revised final
  bars are not rejected, and five direct required rejection cases remain absent.
  Existing collected checks passed; independent review rejected completion.
  Sol/Astra attempts are exhausted. Leave actual code and missing tests for
  human review; require fresh protected proof and acceptance on reopening.
- [!] **M3.4 source and historical-data completion:** actual point-in-time bars,
  each interval's same-mode VWAP, current price, original availability, finality,
  corrections, venue coverage and compatible adjustments remain blocked.
  Synthetic supplied records cannot close this gate.
- [ ] **M3.4 — VWAP context:** supplied-input slope, distance, cross-count and
  above/below calculations are implemented. Protected proof and independent
  review remain required; its separate source gate stays open.
- [ ] **M3.5 — Structural geometry:** proposed after M3.4 protected proof and
  independent review.

**Historical M5.2 saved handoff: M5.3. M5.3 passed independent review on
2026-09-09 Pacific and is recorded as accepted in controller state. M5.5
implementation and proof are complete and awaiting independent acceptance; M6.1
is the next dependency-ready milestone, with its rule-bearing branch still
gated.**
**Current M5.2 handoff — 2026-09-08 Pacific:** **blocked for the required
source/definition gate**. Both fresh protected runs with the 420-second limit
passed 1,246 tests in 306.46/305.01 seconds, including all 45 M5.2 cases and both
Batch 2 storage checks, with identical ordered IDs, zero failures/errors/skips,
clean isolation/cleanup and byte-identical 52,588/52,594-byte recordings.
All 63 published hashes matched. The evaluator uses exact decimal values for the
inclusive 0.35 extension and 1.50 remaining-room boundaries. This is the exact-
boundary repair proof finalized in M5_2_VERIFICATION section 16. The required
separate source/definition row stays `[!]`; synthetic Bars cannot close it.
Proposed independent next_milestone is **M5.3** only after independent review.
No actual data coverage or executable profit is established.

**Current M5.2 repair handoff — 2026-09-08 Pacific:** the exact 0.35 extension
comparison now uses `Fraction("0.35")`. Four protected cases cover the inclusive
boundary and a value just above it for long and short candidates. Fresh protected
proof is the sole remaining offline step, so the offline row is temporarily `[~]`.
The required source/definition row remains `[!]`. Proposed next_milestone remains
**M5.3** after proof and independent review.

**Current M5.2 fixture repair handoff — 2026-09-09 Pacific:** the four boundary
cases now keep the frozen target price and target R multiple consistent, so the
canonical candidate is valid and the cases isolate the exact 0.35 comparison.
Production code did not change in this repair. The unchanged protected launcher
stopped before collection at its initial `os.chown`; fresh supervisor proof is
the sole remaining offline step. The offline row stays `[~]`, the separate
required source/definition row stays `[!]`, and proposed next_milestone stays
**M5.3** after proof and independent review.

**Current M5.2 decimal fixture repair handoff — 2026-09-09 Pacific:** the exact
0.35 long and short cases still used binary decimal math to build their 1.50R
target. The fixture now uses exact decimal values for entry, risk and target, so
candidate checks pass and the cases isolate the intended 0.35 comparison. The
unchanged protected launcher stopped before collection at its initial `os.chown`.
Fresh supervisor proof is the sole remaining offline step. The offline row stays
`[~]`, the separate required source/definition row stays `[!]`, and proposed
next_milestone stays **M5.3** after proof and independent review.

**Final M5.2 decimal fixture proof handoff — 2026-09-09 Pacific:** both fresh
protected runs passed 1,250 tests in 304.67/306.15 seconds, including all 49
M5.2 cases and both Batch 2 storage checks. Ordered IDs match; isolation and
cleanup passed; long/short recordings are byte-identical at 52,588/52,594
bytes. The offline row is `[x]`. The separate required source/definition row
stays `[!]`; synthetic bars do not establish actual coverage or profit. Saved
next_milestone is **M5.3** after independent review. See M5_2_VERIFICATION
section 20 and M5_2_SUPERVISOR_TESTS.json. All switches remain off.

**Current M5.3 repair handoff — 2026-09-09 Pacific:** the replay runner now
fails closed unless research records and state changes use the same isolated
temporary database. A two-connection test covers the reported AT-10 gap. Code
and tests changed, so earlier proof is historical. The latest prior proof is
`c6c62c816cf4` for acceptance and `aa00678d16fb` for repeatability; the still
older `af00da6ada4d` and `f508173e9357` proof remains dated history. The protected
launcher stopped before collection at its first `os.chown` with `OSError 22`.
Fresh protected focused, broad and repeatability proof is the only remaining
offline step. M5.4 stays data-blocked. M5.5 becomes dependency-ready only after
M5.3 acceptance. All switches and earlier required gates remain open.

**Final M5.3 proof handoff — 2026-09-09 Pacific:** the repaired protected
acceptance run passed 1,235 tests in 300.299 seconds. The separate two-run
recording check passed 26 tests in 195.65 seconds and produced matching replay
output. The complete 844-entry tested-source record matches source hash
`707c9e7071b02c02dbe87e10360fe9c32bc641e3703544330af87f2ddf7fb18b`.
The offline row is `[x]` for independent review. M5.4 remains data-blocked.
Saved next_milestone is **M5.5** after M5.3 independent acceptance. All switches
and earlier required gates remain open.

**Historical M5.5 interruption handoff — 2026-09-09 Pacific:** M5.3 independent review passed
and controller state records that acceptance. The first M5.5 builder falsely
reported the acceptance missing because its work packet omitted the completed
milestones and acceptance history. That controller-only handoff bug is fixed and
all 124 controller tests pass. The build is paused with M5.5 at the interrupted
review stage; no M5.5 product code or test was written. On resume, the controller
must repair the false blocked result through normal independent review, then
retry M5.5 with the recorded acceptance visible. Keep delivery recorded and all
switches off. M5.4 and all earlier required gates remain open.

**Final M5.5 proof handoff — 2026-09-09 Pacific:** the new
`consensus_engine/session_recovery.py`, the transition-engine `restore` addition
and the new `ACKNOWLEDGMENT` store kind are implemented with 19 focused cases.
The controller-published protected focused stage passed 1,254 tests in 323.19
seconds, the broad acceptance stage passed 1,254 tests in 313.07 seconds, and the
two fresh recording processes passed 28 tests each in 194.683 seconds total with
byte-identical artifacts, including the unchanged M5.3 replay fingerprint
`2356f8e1`. Their proof is `published-artifacts-7ea0158b0c9f`,
`published-artifacts-573eaf0533d1` and `published-artifacts-ae450c7a169a` in the
20260909-163637-638505 build run. The complete 851-entry tested-source record in
M5_5_TESTED_SOURCE_MANIFEST.json matches source hash
`ce6313a72c90285a49a3e1e09e3d777b12bf949efc44056dd29823939c5c9b2b`, and the
mechanical figures are finalized in M5_5_SUPERVISOR_TESTS.json,
M5_5_LOCAL_CHECKS.json and the readable M5_5_CONTROLLER_EVIDENCE.json copy.
Earlier same-day stages are dated history: two were interrupted by a full host
disk and a refused usage window, and the clean 23:13–23:21 stages were
republished only because the M5.5 record files were written after them. No
source, test, configuration or protected input changed across any of those runs
and every recorded artifact hash held. The offline row is `[x]` for independent
review. M5.4 stays data-blocked and M18 keeps full load and failure hardening.
The named next milestone is **M6.1**, now open in the progress list above with
its own `[!]` approved-rule gate for M03B_ORB5_V1; only its offline
supplied-input state-machine slice is dependency-ready. All switches and earlier
required gates remain open.

**Final M6.1 proof handoff — 2026-09-10 Pacific:** the new
`consensus_engine/orb5_eligibility.py` and
`tests/trade_alerts_contracts/test_orb5_eligibility.py` implement and prove the
offline eligibility path through ARMED on supplied inputs. No existing module,
configuration, migration or protected launcher file changed. Two fresh protected
runs of the full `tests/trade_alerts_contracts` selection passed 1,397 tests in
321.49 and 319.15 seconds by pytest's own figure (controller wall 324.632 and
322.335 seconds), inside the 420-second limit, and the 143 M6.1 cases pass inside
each of those runs; a standalone single-file run of that test file was
builder-local and is not published proof. The separate controller repeatability
phase ran the 20 recording node IDs, 30 tests per run, twice in fresh processes,
in 102.80 and 102.88 seconds, exit code 0 both times, with 35 artifacts per run
and 33 byte-identical. All runs had zero failures, errors and skips, no
unexpected isolation denials and passing cleanup. Of 36 artifacts per full run,
33 are byte-identical; only `output.txt`, `results.xml` and `pipeline-obs.jsonl`
differ, and only in timing text. The M6.1 recordings match at 3,832 and 3,826 bytes
(`f7e25fc2…`, `d0e4cd03…`), and the M5.3 replay fingerprint is unchanged. Tested
milestone files: `consensus_engine/orb5_eligibility.py` `2ca34145…` and
`tests/trade_alerts_contracts/test_orb5_eligibility.py` `907a3a46…`. The offline
row is `[x]` for independent review; the separate `[!]` approved-rule gate stays
open because the exact ARMED thresholds still need the PROPOSED M03B_ORB5_V1
definition. ARMED is a reported state at one instant, not a trigger, an alert or
permission to act. Named next milestone: **M6.2**, now open in the progress list
above. All switches remain off and D-091 stays $0 used and $0 reserved.

**Final M6.2 proof handoff — 2026-09-10 Pacific:** the new
`consensus_engine/orb5_trigger.py` and
`tests/trade_alerts_contracts/test_orb5_trigger.py` implement and prove the
offline actionable-trigger path on supplied inputs. No existing module,
configuration, migration or protected launcher file changed. Two published
phases each ran the full `tests/trade_alerts_contracts` selection once in its own
fresh process: the focused phase (source `/tmp/trade-alerts-m04-bnmqnbgf`) passed
**1,616 tests in 335.08 seconds** by pytest's own figure (JUnit 335.003,
controller wall 338.513) and the acceptance phase (source
`/tmp/trade-alerts-m04-um9nsjx9`) passed **1,616 tests in 336.01 seconds** (JUnit
335.943, controller wall 339.425), both inside the 420-second limit, with the
**219 M6.2 cases** passing inside each run and taking 6.25 and 6.28 seconds of
case time. Each full run wrote 38 artifact files, and comparing the two, **35 are
byte-identical**, with only `output.txt`, `results.xml` and `pipeline-obs.jsonl`
differing in timing text and observation timestamps. The separate controller
repeatability phase (source `/tmp/trade-alerts-m04-n2vgvetx`) ran the 21
recording node IDs, 32 tests per run, twice in fresh processes, in 107.67 and
106.05 seconds (JUnit 107.674 and 106.053), exit code 0 both times, with 37
artifacts per run and no `pipeline-obs.jsonl`, of which 35 are byte-identical and
only `output.txt` and `results.xml` differ. Ordered test IDs match within each
comparison, and every run reports zero failures, errors and skips, no unexpected
isolation denials and passing cleanup. The M6.2 recordings match at 5,065 and
5,051 bytes (`cd9817b4…`, `e8a84855…`) across all four runs; the M6.1
eligibility recording (`f7e25fc2…`) and the M5.3 replay fingerprint
(`2356f8e1…`) are unchanged. A single-file run of the new test file was
builder-local and is not published proof. Tested milestone files: `consensus_engine/orb5_trigger.py` `eba26708…`
and `tests/trade_alerts_contracts/test_orb5_trigger.py` `d3014413…`. The offline
row is `[x]` for independent review; the separate `[!]` approved-rule and
tape/projection source gates stay open. ALERT_TRIGGERED is a reported state at
one instant, not an alert, a delivery or permission to act. Named next
milestone: **M6.3**, now open in the progress list above. All switches remain off
and D-091 stays $0 used and $0 reserved.

**Historical M8.4 handoff — 2026-09-12 Pacific:** the new
`consensus_engine/first_pullback_vwap.py` and
`tests/trade_alerts_contracts/test_first_pullback_vwap.py` implement and cover
the offline `FIRST_PULLBACK_VWAP` strategy that consumes the M8.3 measurement, on
supplied synthetic records. No existing module, test, configuration, migration or
protected launcher file changed; the reused
`consensus_engine/impulse_pullback.py`, `consensus_engine/orb5_trigger.py`,
`consensus_engine/quote_events.py`, `consensus_engine/confidence.py`,
`consensus_engine/state_transitions.py`,
`consensus_engine/strategy_interface.py`,
`consensus_engine/trade_alerts_config.py`,
`consensus_engine/trade_alerts_models.py` and
`consensus_engine/utils/time_context.py` are unchanged. The required selection is
the whole `tests/trade_alerts_contracts` directory, with
`tests/trade_alerts_contracts/test_first_pullback_vwap.py` as the focused
selector, and this milestone states a repeatability need, because
`m8_4_first_pullback_vwap_proof.json` is a recorded artifact that must be
compared between two fresh processes. Every earlier milestone recording in the
same runs, including the M8.1 handoff, M8.2 reversal and M8.3 measurement
recordings, must stay unchanged. The controller's protected stages supply every
figure and hash for M8_4_VERIFICATION.md and M8_4_LOCAL_CHECKS.json; the builder
published no number of its own. All three selections — focused, the
whole-directory acceptance run in one child process, and the two-process
repeatability run — ran clean under the protected launcher in this build session,
with no failures, no errors and no skips, clean isolation and cleanup, and
byte-identical recordings between the two repeatability processes. See
M8_4_VERIFICATION.md. The offline row is `[x]` pending independent review; the
separate `[!]` definition and source/historical-data gates stay open. A reported
ALERT_TRIGGERED describes supplied inputs at one instant: it is not an alert, an
approved rule, a backtest result, an edge claim or permission to act. Named next
milestone: **M8.5**, now open in the progress list above. All switches remain off
and D-091 stays $0 used and $0 reserved.

**Current M8.5 identity repair — 2026-09-13 Pacific:** the independent
review refused acceptance because supporting evidence was not linked to its
stock, saved session or original setup. Canonical supporting records and a
saved session are now required, checked and retained in the report, with both
directions and both assessment types covered by tests. Missing identity is refused.
Additional review found that a reversal failure label could accompany a failed
handoff check, and gate/structural input identities were omitted. The actual
handoff gate must now pass; all such source IDs are required with separate
crossing and assessment availability checks. The recording now covers both
directions and both assessment types, including reordered supporting records
and full recorded source contents. The controller ran the protected focused and broad selections once each and the
recording selection twice. Every run passed with zero failures, errors or skips,
clean isolation and cleanup, matching test IDs, and byte-identical required
recordings. Independent review remains. M9.1 waits for M8.5 acceptance. The historical
proof and failure records below remain unchanged. Separate definition and
historical-data gates remain open, and all switches stay off.

**Historical M8.5 handoff — 2026-09-12 Pacific:** the new
`consensus_engine/cross_strategy_interaction.py` and
`tests/trade_alerts_contracts/test_cross_strategy_interaction.py` implement and
cover the offline interaction report for supplied candidates from the first four
playbooks. The report retains every candidate and gives stable same-symbol pair
facts for time, supplied ATR price regions, lifetime overlap, confidence order,
documented relationships and declared M8.1/M8.2 transitions. It does not choose
a primary, break an equal-score tie, merge, suppress, persist or send anything.
The controller's focused stage passed the exact repaired case
`tests/trade_alerts_contracts/test_cross_strategy_interaction.py::test_region_rule_and_missing_atr_stay_visible_without_guessing`
in one run. The synthetic example's equal entry and stop had caused the
failure before the report ran. Its stop is now 97.5, with separate distance and
gate assertions. Shared risk validation stays unchanged. Acceptance passed the
whole `tests/trade_alerts_contracts` directory in one run. The separate
recording selection passed in two repeatability runs; required recordings and
test IDs match. M8_5_LOCAL_CHECKS.json and M8_5_VERIFICATION.md preserve exact
phase selectors, figures, artifact paths, hashes, comparisons and the complete
tested-source manifest. Every tested file content matched before records-only
finalization. Code, tests and protection stayed unchanged. The earlier sandbox
launcher limitation is historical; no test rerun was needed in this session.
The offline row is `[x]` with protected proof complete, pending independent
review; the separate `[!]` definition and source/historical-data gates stay open.
Named next milestone: **M9.1**, now open in the progress list
above; it must record the exact blocked or insufficient-data result if required
history is unavailable. All switches remain off and D-091 stays $0 used and $0
reserved.

**Historical M8.3 handoff — 2026-09-12 Pacific:** the new
`consensus_engine/impulse_pullback.py` and
`tests/trade_alerts_contracts/test_impulse_pullback.py` implement and cover the
shared offline impulse and pullback measurement the `FIRST_PULLBACK_VWAP`
playbook needs, on supplied synthetic records. No existing module, test,
configuration, migration or protected launcher file changed; the reused
`consensus_engine/historical_bars.py`,
`consensus_engine/trade_alerts_models.py` and
`consensus_engine/utils/time_context.py` are unchanged. The required selection is
the whole `tests/trade_alerts_contracts` directory, with
`tests/trade_alerts_contracts/test_impulse_pullback.py` as the focused selector,
and this milestone states a repeatability need, because
`m8_3_impulse_pullback_proof.json` is a recorded artifact that must be compared
between two fresh processes. Every earlier milestone recording in the same runs,
including the M8.1 handoff and M8.2 reversal recordings, must stay unchanged. The
controller's protected stages supply every figure and hash for
M8_3_VERIFICATION.md and M8_3_LOCAL_CHECKS.json; the builder published no number
of its own. All three selections — focused, the whole-directory acceptance run in
one child process, and the two-process repeatability run — ran clean under the
protected launcher in this build session, with no failures, no errors and no
skips, clean isolation and cleanup, and byte-identical recordings between the two
repeatability processes. See M8_3_VERIFICATION.md. The offline row is `[x]`
pending independent review; the separate `[!]` definition and
source/historical-data gates stay open. A measured impulse and pullback describe
supplied bars at one instant: they are not an alert, an approved rule, a backtest
result, an edge claim or permission to act. Named next milestone: **M8.4**, now
open in the progress list above. All switches remain off and D-091 stays $0 used
and $0 reserved.

**Historical M8.2 handoff — 2026-09-12 Pacific:** the new
`consensus_engine/or_failure_rev.py` and
`tests/trade_alerts_contracts/test_or_failure_rev.py` implement and cover the
`OR_FAILURE_REV` strategy that consumes the M8.1 handoff, on supplied synthetic
records. No existing module, test, configuration, migration or protected launcher
file changed; the reused `consensus_engine/or_failure_handoff.py`,
`consensus_engine/orb5_trigger.py`,
`consensus_engine/opening_range_features.py`, `consensus_engine/quote_events.py`,
`consensus_engine/confidence.py`, `consensus_engine/state_transitions.py`,
`consensus_engine/strategy_interface.py`, `consensus_engine/event_store.py`,
`consensus_engine/transition_store.py`, `consensus_engine/trade_alerts_models.py`
and `consensus_engine/trade_alerts_config.py` are unchanged. The required
selection is the whole `tests/trade_alerts_contracts` directory, with
`tests/trade_alerts_contracts/test_or_failure_rev.py` as the focused selector,
and this milestone states a repeatability need, because
`m8_2_or_failure_rev_proof.json` is a recorded artifact that must be compared
between two fresh processes. Every earlier milestone recording in the same runs,
including the M8.1 handoff recording, must stay unchanged. The controller's
protected stages supply every figure and hash for M8_2_VERIFICATION.md and
M8_2_LOCAL_CHECKS.json; the builder published no number of its own. All three
selections — focused, the whole-directory acceptance run in one child process,
and the two-process repeatability run — ran clean under the protected launcher in
this build session, with no failures, no errors and no skips, clean isolation and
cleanup, and byte-identical recordings between the two repeatability processes.
An earlier session in the same build run wrote the module and its coverage and
then stopped at its own API session limit before any protected run; that partial
work was preserved and only its fixtures were repaired, in the test file alone,
as M8_2_VERIFICATION.md section 5 lists. See M8_2_VERIFICATION.md. The offline
row is `[x]` pending independent review; the separate `[!]` definition and
source/historical-data gates stay open. A reported ALERT_TRIGGERED describes
supplied records at one instant: it is not an alert, a sent message, a backtest
result, an edge claim or permission to act. Named next milestone: **M8.3**, now
open in the progress list above. All switches remain off and D-091 stays $0 used
and $0 reserved.

**Historical M8.1 handoff — 2026-09-12 Pacific:** the new
`consensus_engine/or_failure_handoff.py` and
`tests/trade_alerts_contracts/test_or_failure_handoff.py` implement and cover the
shared offline support that hands one ended supplied opening-range break over to
a failure/reversal owner in the mirrored direction, on supplied synthetic
records. No existing module, test, configuration, migration or protected launcher
file changed; the reused `consensus_engine/orb5_trigger.py`,
`consensus_engine/opening_range_features.py`,
`consensus_engine/state_transitions.py`,
`consensus_engine/strategy_interface.py`, `consensus_engine/event_store.py`,
`consensus_engine/transition_store.py`, `consensus_engine/trade_alerts_models.py`
and `consensus_engine/trade_alerts_config.py` are unchanged. The required
selection is the whole `tests/trade_alerts_contracts` directory, with
`tests/trade_alerts_contracts/test_or_failure_handoff.py` as the focused
selector, and this milestone states a repeatability need, because
`m8_1_or_failure_handoff_proof.json` is a recorded artifact that must be compared
between two fresh processes. Every earlier milestone recording in the same runs,
including the M3.6 opening-range recording, the M6.1 eligibility recordings, the
M6.3 risk recordings, the M6.4 scenario artifact, the M7.1 compression recording,
the M7.2 RS recording, the M7.3 trigger recording, the M7.4 composition proof and
the M7.5 scenario artifact, must stay unchanged. The controller's protected
stages supply every figure and hash for M8_1_VERIFICATION.md and
M8_1_LOCAL_CHECKS.json; the builder published no number of its own. All three
selections — focused, the whole-directory acceptance run in one child process,
and the two-process repeatability run — ran clean under the protected launcher in
the build session, with no failures, no errors and no skips, clean isolation and
cleanup, and byte-identical recordings between the two repeatability processes.
The two earlier attempts could not finish the directory selection inside the
launcher's own 420-second per-run cap and timed out in the controller's
verification; the controller has since raised that cap itself under its own
separately reviewed protection repair, so the single directory run now reports
and the earlier split-group workaround is retired.
M8_1_LAUNCHER_LIMITATION.txt records the original timeout, the two groups and
that resolution, including the launcher hash change the controller made. No build
session edited, bypassed or retried a protection file. See M8_1_VERIFICATION.md.
The offline row is `[x]` pending
independent review; the separate `[!]` definition and source/historical-data
gates stay open. A reported FAILURE_FORMING describes supplied records at one
instant: it is not an alert, a sent message, a backtest result, an edge claim or
permission to act. Named next milestone: **M8.2**, now open in the progress list
above. All switches remain off and D-091 stays $0 used and $0 reserved.

**Historical M7.5 handoff — 2026-09-11 Pacific:** the new
`consensus_engine/hod_comp_rs_replay.py` and
`tests/trade_alerts_contracts/test_hod_comp_rs_replay.py` implement and cover the
five named `HOD_COMP_RS` scenarios over the M5.3 replay runner: the clean
compression break, its mirrored short twin, the failed break, the RS-weak case
and the stale extension, still on supplied synthetic records. No existing module,
test, configuration, migration or protected launcher file changed; the reused
`consensus_engine/hod_comp_rs_risk_confidence.py`,
`consensus_engine/hod_comp_rs_trigger.py`,
`consensus_engine/rs_trend_eligibility.py`,
`consensus_engine/historical_replay.py`, `consensus_engine/state_transitions.py`,
`consensus_engine/event_store.py` and `consensus_engine/strategy_interface.py`
are unchanged. The required selection is the whole `tests/trade_alerts_contracts`
directory, with `tests/trade_alerts_contracts/test_hod_comp_rs_replay.py` as the
focused selector, and this milestone states a repeatability need, because
`m7_5_hod_comp_rs_scenarios.json` is a recorded artifact that must be compared
  between two fresh processes. A repair then made the owner keep the frozen
  structure a recorded heads-up described and refuse a later crossing structure
  with changed prices or a changed ATR, for long and for short, so the earlier
  published proof is invalidated and the controller's rerun supplies the fresh
  figures and hashes for M7_5_VERIFICATION section 5 and
  M7_5_LOCAL_CHECKS.json. Every earlier milestone recording in the same
runs, including the M3.6 opening-range recording, the M6.1 eligibility
recordings, the M6.3 risk recordings, the M6.4 scenario artifact, the M7.1
compression recording, the M7.2 RS recording, the M7.3 trigger recording and the
M7.4 composition proof, must stay unchanged. See M7_5_VERIFICATION.md. The
offline row is `[x]` for independent review; the separate `[!]` definition and
source/historical-data gates stay open. A replayed scenario describes supplied
inputs at supplied instants: it is not an alert, a sent message, a backtest
result, an edge claim or permission to act. Named next milestone: **M8.1**, now
open in the progress list above. All switches remain off and D-091 stays $0 used
and $0 reserved.

**Historical M7.4 handoff — 2026-09-11 Pacific:** the new
`consensus_engine/hod_comp_rs_risk_confidence.py` and
`tests/trade_alerts_contracts/test_hod_comp_rs_risk_confidence.py` implement and
cover the `HOD_COMP_RS` composition of one reported trigger with the caller's own
supplied stop and targets, the M4.4 confidence result and the caller's own
suppression policy and history, still on supplied synthetic records. No existing
module, test, configuration, migration or protected launcher file changed: the
launcher still hashes to `a4ffdd55…` with child `85285dee…`, and the reused
`consensus_engine/hod_comp_rs_trigger.py` (`fa9a534c…`),
`consensus_engine/rs_trend_eligibility.py` (`6a53d814…`),
`consensus_engine/orb5_trigger.py` (`eba26708…`),
`consensus_engine/confidence.py` (`4169b372…`),
`consensus_engine/state_transitions.py` (`eb29559e…`),
`consensus_engine/strategy_interface.py` (`c0df609b…`) and
`consensus_engine/trade_alerts_models.py` (`b9674913…`) are unchanged. The
required selection is the whole `tests/trade_alerts_contracts` directory, with
`tests/trade_alerts_contracts/test_hod_comp_rs_risk_confidence.py` as the focused
selector, and this milestone states a repeatability need, because
`m7_4_hod_comp_rs_risk_confidence_proof.json` is a recorded artifact that must be
compared between two fresh processes. The controller's published protected stage
supplies every count, timing and artifact hash for this milestone; no
builder-local figure is quoted anywhere in this record. Every earlier milestone
recording in the same runs, including the M3.6 opening-range recording, the M6.1
eligibility recordings, the M6.3 risk recordings, the M6.4 scenario artifact, the
M7.1 compression recording, the M7.2 RS recording and the M7.3 trigger recording,
must stay unchanged. See M7_4_VERIFICATION.md and M7_4_LOCAL_CHECKS.json. The
offline row is `[x]` for independent review; the separate `[!]` definition and
source/historical-data gates stay open. READY describes supplied inputs at one
instant and SUPPRESSED reports the caller's own history decision: neither is an
alert, a sent message, an edge claim or permission to act, and no
`SuppressionEvent` is written here. Named next milestone: **M7.5**, now open in
the progress list above. All switches remain off and D-091 stays $0 used and $0
reserved.

**Historical M7.3 handoff — 2026-09-11 Pacific:** the new
`consensus_engine/hod_comp_rs_trigger.py` and
`tests/trade_alerts_contracts/test_hod_comp_rs_trigger.py` implement and cover
the `HOD_COMP_RS` heads-up notice and the actionable path through
ALERT_TRIGGERED, still on supplied synthetic records. No existing module, test,
configuration, migration or protected launcher file changed: the launcher still
hashes to `a4ffdd55…` with child `85285dee…`, and the reused
`consensus_engine/orb5_trigger.py` (`eba26708…`),
`consensus_engine/rs_trend_eligibility.py` (`6a53d814…`),
`consensus_engine/hod_compression.py` (`23b93c99…`),
`consensus_engine/state_transitions.py` (`eb29559e…`),
`consensus_engine/strategy_interface.py` (`c0df609b…`),
`consensus_engine/trade_alerts_models.py` (`b9674913…`) and
`consensus_engine/trade_alerts_config.py` (`b1416922…`) are unchanged. The
required selection is the whole `tests/trade_alerts_contracts` directory, with
`tests/trade_alerts_contracts/test_hod_comp_rs_trigger.py` as the focused
selector, and this milestone states a repeatability need, because
`m7_3_hod_comp_rs_trigger_proof.json` is a recorded artifact that must be
compared between two fresh processes. The controller's published protected stage
supplies every count, timing and artifact hash for this milestone; no
builder-local figure is quoted anywhere in this record. Every earlier milestone
recording in the same runs, including the M3.6 opening-range recording, the M6.1
eligibility recordings, the M6.4 scenario artifact, the M7.1 compression
recording and the M7.2 RS recording, must stay unchanged. See
M7_3_VERIFICATION.md and M7_3_LOCAL_CHECKS.json. The offline row is `[x]` for
independent review; the separate `[!]` definition and source/historical-data
gates stay open. A reported heads-up is a notice and ALERT_TRIGGERED describes
supplied inputs at one instant only: neither is an alert, a sent message, an edge
claim or permission to act. Named next milestone: **M7.4**, now open in the
progress list above. All switches remain off and D-091 stays $0 used and $0
reserved.

**Historical M7.2 handoff — 2026-09-11 Pacific:** the new
`consensus_engine/rs_trend_eligibility.py` and
`tests/trade_alerts_contracts/test_rs_trend_eligibility.py` implement and cover
the relative-strength measurement and the `HOD_COMP_RS` eligibility path through
ARMED, still on supplied synthetic records. No existing module, test,
configuration, migration or protected launcher file changed: the launcher still
hashes to `a4ffdd55…` with child `85285dee…`, and the reused
`consensus_engine/hod_compression.py` (`23b93c99…`),
`consensus_engine/orb5_eligibility.py` (`2ca34145…`),
`consensus_engine/historical_bars.py` (`073772ef…`),
`consensus_engine/trade_alerts_models.py` (`b9674913…`),
`consensus_engine/state_transitions.py` (`eb29559e…`) and
`consensus_engine/strategy_interface.py` (`c0df609b…`) are unchanged. The
required selection is the whole `tests/trade_alerts_contracts` directory, with
`tests/trade_alerts_contracts/test_rs_trend_eligibility.py` as the focused
selector, and this milestone states a repeatability need, because
`m7_2_rs_trend_proof.json` is a recorded artifact that must be compared between
two fresh processes. The controller's published protected stage supplies every
count, timing and artifact hash for this milestone; no builder-local figure is
quoted anywhere in this record. Every earlier milestone recording in the same
runs, including the M3.6 opening-range recording, the M6.1 eligibility
recordings, the M6.4 scenario artifact and the M7.1 compression recording, must
stay unchanged. See M7_2_VERIFICATION.md and M7_2_LOCAL_CHECKS.json. The offline
row is `[x]` for independent review; the separate `[!]` definition and
source/historical-data gates stay open. ARMED describes supplied inputs at one
instant only: it is not a trigger, an alert, an edge claim or permission to act.
Named next milestone: **M7.3**, now open in the progress list above. All switches
remain off and D-091 stays $0 used and $0 reserved.

**Historical M7.1 handoff — 2026-09-11 Pacific:** the new
`consensus_engine/hod_compression.py` and
`tests/trade_alerts_contracts/test_hod_compression.py` implement and cover the
point-in-time HOD/LOD freeze and the compression window measurement for
`HOD_COMP_RS`, still on supplied synthetic records. No existing module, test,
configuration, migration or protected launcher file changed: the launcher still
hashes to `a4ffdd55…` with child `85285dee…`, and the reused
`consensus_engine/historical_bars.py` (`073772ef…`),
`consensus_engine/trade_alerts_models.py` (`b9674913…`),
`consensus_engine/core_price_features.py` (`3a8f8115…`) and
`consensus_engine/opening_range_features.py` (`5f3f911f…`) are unchanged. The
required selection is the whole `tests/trade_alerts_contracts` directory, with
`tests/trade_alerts_contracts/test_hod_compression.py` as the focused selector,
and this milestone states a repeatability need, because
`m7_1_hod_compression_proof.json` is a recorded artifact that must be compared
between two fresh processes. The controller's published protected stage supplies
every count, timing and artifact hash for this milestone; no builder-local figure
is quoted anywhere in this record. Every earlier milestone recording in the same
runs, including the M3.6 opening-range recording and the M6.4 scenario artifact,
must stay unchanged. See M7_1_VERIFICATION.md and M7_1_LOCAL_CHECKS.json. The
offline row is `[x]` for independent review; the separate `[!]` definition and
source/historical-data gates stay open. A measured window describes supplied bars
at one instant only: it is not a setup, an arming decision, an alert, an edge
claim or permission to act. Named next milestone: **M7.2**, now open in the
progress list above. All switches remain off and D-091 stays $0 used and $0
reserved.

**Historical M6.4 handoff — 2026-09-11 Pacific:** the new
`consensus_engine/orb5_replay.py` and
`tests/trade_alerts_contracts/test_orb5_replay.py` implement and cover the six
named synthetic scenarios over the M5.3 replay runner, still on supplied inputs.
No existing module, test, configuration, migration or protected launcher file
changed: `consensus_engine/orb5_eligibility.py` still hashes to `2ca34145…`,
`consensus_engine/orb5_trigger.py` to `eba26708…`,
`consensus_engine/orb5_risk_confidence.py` to `36a73ed9…`,
`consensus_engine/historical_replay.py` to `379a1861…`, and the launcher to
`a4ffdd55…` with child `85285dee…`. The required selection is the whole
`tests/trade_alerts_contracts` directory, and this milestone states a
repeatability need, because `m6_4_orb5_scenarios.json` is a recorded artifact
that must be compared between two fresh processes. The controller's published
protected stage supplies every count, timing and artifact hash for this
milestone; no builder-local figure is quoted anywhere in this record. Every
earlier milestone recording, including the M6.3, M6.2 and M6.1 recordings and
the M5.3 replay fingerprint, must stay unchanged. See M6_4_VERIFICATION.md and
M6_4_LOCAL_CHECKS.json. The offline row is `[x]` for independent review; the
separate `[!]` approved-rule and source/historical-data gates stay open. A
replayed scenario describes supplied inputs at those instants only: it is not an
alert, a backtest result, an edge claim or permission to act. Named next
milestone: **M7.1**, now open in the progress list above. All switches remain off
and D-091 stays $0 used and $0 reserved.

**Final M6.3 proof handoff — 2026-09-10 Pacific:** the new
`consensus_engine/orb5_risk_confidence.py` and
`tests/trade_alerts_contracts/test_orb5_risk_confidence.py` implement and prove
the offline composition of the M4.3 selector result and the M4.4 confidence
result at the frozen M6.2 trigger. No existing module, test, configuration,
migration or protected launcher file changed: `consensus_engine/orb5_trigger.py`
still hashes to `eba26708…` and the launcher to `a4ffdd55…` with child
`85285dee…`. Two published phases each ran the full
`tests/trade_alerts_contracts` selection once in its own fresh process: the
focused phase (source `/tmp/trade-alerts-m04-19hrzllq`) passed **1,696 tests in
330.37 seconds** by pytest's own figure (JUnit 330.303, controller wall 333.567)
and the acceptance phase (source `/tmp/trade-alerts-m04-4im0o63e`) passed
**1,696 tests in 334.71 seconds** (JUnit 334.636, controller wall 338.006), both
inside the 420-second limit, with the **80 M6.3 cases** passing inside each run
and taking 4.338 and 4.361 seconds of case time. Each full run wrote 40 artifact
files, and comparing the two, **37 are byte-identical**, with only `output.txt`,
`results.xml` and `pipeline-obs.jsonl` differing in timing text and observation
timestamps. The separate controller repeatability phase (source
`/tmp/trade-alerts-m04-sj_kmihs`) ran the 22 recording node IDs, 34 tests per
run, twice in fresh processes, in 107.84 and 106.49 seconds (JUnit 107.842 and
106.497), exit code 0 both times, with 39 artifacts per run and no
`pipeline-obs.jsonl`, of which 37 are byte-identical and only `output.txt` and
`results.xml` differ. Ordered test IDs match within each comparison, and every
run reports zero failures, errors and skips, no unexpected isolation denials and
passing cleanup. The M6.3 recordings match at 3,045 and 3,039 bytes
(`3ca696f4…`, `6a0baf9e…`) across all four runs; the M6.2 trigger recordings
(`cd9817b4…`, `e8a84855…`), the M6.1 eligibility recording (`f7e25fc2…`) and
the M5.3 replay fingerprint (`2356f8e1…`) are unchanged. A builder-local run of
the launcher is not published proof and no figure from it is quoted. Tested
milestone files: `consensus_engine/orb5_risk_confidence.py` `36a73ed9…` and
`tests/trade_alerts_contracts/test_orb5_risk_confidence.py` `d97abefc…`, under
verified manifest source hash `61373220…`. The offline row is `[x]` for
independent review; both `[!]` M6.3 gate rows stay open. READY here means the
supplied composition held together at one instant; it is not an alert, an
approved rule, a quality cutoff or permission to act. Named next milestone:
**M6.4**, now open in the progress list above. All switches remain off and D-091
stays $0 used and $0 reserved.

**Historical M5.1 handoff — 2026-09-08 Pacific:** completed for independent review.
The proof returned at 01:44:34 Pacific passed 1,249 tests in each protected run,
including all 23 storage cases and both required trade-tracking checks. Expanded
long/short recordings match at 12,092/12,113 bytes with all six rejection paths
per direction. Isolation/cleanup passed. All 59 published hashes and 833 tested
contents matched before records-only finalization. Code/tests/protection stayed
unchanged. See M5_1_VERIFICATION section 15 and M5_1_LOCAL_CHECKS.json.
Preserve all twelve milestone paths. Its saved proposed next_milestone was **M5.2**,
within section 7 of that record, after independent acceptance. M4.7 and all earlier
required blocked rows remain open. Earlier launcher errors and timeouts are
historical in M5_1_VERIFICATION sections 10–14.

**Historical — M4.6 was completed for independent review.**
Fresh proof returned at 22:03:30 Pacific passed 1,193 tests in each run, including
all 130 M4.6 cases. Expanded long/short recordings match at 28,043/28,094 bytes;
ordered IDs match and isolation/cleanup passed. M4_6_VERIFICATION §13 and
M4_6_LOCAL_CHECKS.json save the inspected proof. Code/tests/protection did not
change during finalization. Earlier proofs and launcher failures are historical.
At that historical handoff M4.7 stayed `[!]` and the proposed next milestone was
M5.1. D-100 and the current M4.7 handoff supersede only that old definition state.
**Historical M4.6 pre-proof handoff — 2026-09-07 Pacific:** the same offline
rendering and full selection were previously ready_for_verification; the unchanged
launcher then stopped before collection (§4). The §7/§8 proof and then the §10
component-link repair proof supersede this historical state.
**Historical M4.5 handoff — 2026-09-07 Pacific:** supplied candidate assembly,
separate suppression and explicit expiry checks have completed protected proof.
Both fresh supervisor runs passed 1,045 tests, including all 96 M4.5 cases, with
matching ordered IDs, clean isolation/cleanup and byte-identical long/short
recordings. Read M4_5_VERIFICATION §8 and M4_5_LOCAL_CHECKS.json. The local
ownership-step failure remains historical. Status: completed for independent review.
No required live/data/definition gate belongs to this common assembly mechanism;
automatic strategy/portfolio behavior remains M0.3/M4.7/M6–M15 and full retention
remains M5.1/M5.5. All earlier blocked rows above remain required.

**Historical M4.4 handoff — 2026-09-07 Pacific:** supplied composition and attribution
have completed protected proof. Both fresh supervisor runs passed 949 tests,
including all 68 M4.4 cases, with matching ordered IDs, clean isolation/cleanup
and byte-identical long/short recordings. Read M4_4_VERIFICATION §8 and
M4_4_LOCAL_CHECKS.json. The local launcher failure remains historical. Keep the
required [!] row above: full factor definitions, missingness/freshness rules and
actual source readiness remain blocked. Return blocked with independent
next_milestone M4.5 for review. Full scoring cannot be declared complete from
synthetic examples.

**Historical M4.3 handoff — 2026-09-07 Pacific:** offline implementation and protected
proof are complete. Both runs passed 892 tests, including all 105 M4.3 cases,
with matching IDs, clean isolation/cleanup and matching long/short recordings.
Read M4_3_VERIFICATION §8 and M4_3_LOCAL_CHECKS.json. The separate required [!]
row above remains blocked; this handoff returns blocked with independent
next_milestone M4.4 for review.
The full structure/definition/source gate cannot be completed by synthetic cases.
Earlier M4.2-to-M4.3 handoffs are historical; M4.2 remains complete.

At that historical M4.3 handoff, M0.2 history/finality/adjustment/corporate-action coverage, M0.3B adoption, the other
seven definitions and every full-data feature remained required. Current research authority and definition status are recorded above. Actual source
checks and any purchase belong to separately authorized supervised work. No
purchase is needed for this offline scope; D-091 stays $0 used and $0 reserved.
Synthetic examples establish neither provider coverage nor trading returns.

The two broader legacy listener tests that attempted outbound reactions remain
an explicit M18.4 test-isolation gap; they are not claimed passing or added to
the failing-test list. Preserve all owner files and the repaired M2.2 source/tests.
Do not redo completed M0.3B preparation, M0.4, M1.1–M1.3 or M2.1 work, or rebuild
M2.2 after this completed records-only verification handoff.

M4.6/M4.7/M5.5 retain the minimum delivery/options/recovery prerequisites before M9. M14/M15/M18 retain complete refinement/hardening. M10.7/M13.7 preserve full-data completion. If the proposed bar-profile catalog is adopted, its shared minimum producer belongs to M3.5/M4.3 before #1; Strategy #8-specific logic still belongs to M13. This removes a circular dependency without calling estimates full trade data.

Every FR-001–FR-031 and additional required capability retains its PREBUILD_REVIEW map row and owner. A blocked required feature is not optional or indefinitely deferred. Engineering readiness, adopted trading definitions, provider coverage and demonstrated profitability are different gates. No generated kickoff grants live activation, orders, deployment, Git mutation, extra spending or adoption of unseen rules.

M3.4 supplied-input VWAP context uses accepted canonical bars, core price
features and session timing; it does not call the unaccepted relative-strength
engine. Independent prerequisite work does not close M3.3, downstream strategy,
source, historical-data, profit or live-use gates.

## Current independent prerequisite route — 2026-09-13 Pacific

- [!] **M3.3 supplied-input implementation:** remains unaccepted for selected
  revised-bar rejection and five missing direct rejection checks. Existing
  passing collected proof does not establish these cases or acceptance.
- [!] **M3.3 source and historical-data completion:** remains separately blocked
  on verified original availability, point-in-time mapping, actual minute/trade
  coverage, corrections and compatible adjustments. No synthetic proof closes it.
- [!] **M3.4 source and historical-data completion:** actual point-in-time bars,
  each interval's same-mode VWAP, current price, original availability, finality,
  corrections, venue coverage and compatible adjustments remain blocked.
  Synthetic supplied records cannot close this gate.
- [x] **M3.4 — VWAP context:** supplied-input slope, distance, cross-count and
  above/below calculations have protected focused, broad acceptance and
  two-run repeatability proof. It uses accepted canonical bars, M3.1 core price
  features and session timing without M3.3. See M3_4_VERIFICATION.
- [ ] **M3.5 — Structural geometry:** proposed next after M3.4 independent review.
  It does not close M3.3 or either source gate.

## Current M3.4 blocked review — 2026-09-13 Pacific

The supplied-input VWAP calculations and collected protected proof were reviewed
as sound. This is not full milestone acceptance. Keep the source and historical
obligation separate and unresolved; M3.5 was explicitly confirmed independent.

- [!] **M3.4 source and historical-data completion:** actual point-in-time bars,
  same-mode VWAP, current-price original availability, finality, correction
  history, session identity, venue coverage and compatible adjustments remain
  unresolved. Synthetic proof does not establish trading results.
- [ ] **M3.5 — Structural geometry:** reviewer-confirmed independent next work.
  It does not depend on accepting the blocked source obligation or relative
  strength and does not close downstream strategy, source or live gates.

## Historical M3.5 implementation handoff — 2026-09-13 Pacific

- [!] **M3.5 source and historical-data completion:** actual point-in-time price,
  ATR, level, path and swing-bar availability, finality, corrections, session,
  venue and compatible adjustment evidence remain required. Any adopted
  prior-session profile family also needs its separate source history.
- [~] **M3.5 — Structural geometry:** the offline supplied-input calculation is
  implemented; recording publication is repaired and new protected proof is
  pending. It covers retracement, compression, drive
  efficiency, signed distance to level, two-by-two plateau swings, risk/reward
  and supplied ATR buffers without selecting a strategy rule. Prior protected
  counts remain historical in M3_5_VERIFICATION: neither repeatability run
  published the M3.5 recording, so M3.5 byte repeatability was not proved.
  The repaired test writes to the protected run's published output folder.
  The controller must publish and compare both fresh-process M3.5 recordings
  after the focused and required broader stages. Independent review decides
  acceptance; the separate source row above stays blocked.
- [ ] **M0.2 — current data and shared-capacity audit:** proposed independent next
  work after M3.5 review. The owner permits a separately assigned bounded
  read-only source check with zero additional spending. Keep every existing
  source gate open until that check supplies its own evidence.

## Current M3.5 protected-proof handoff — 2026-09-13 Pacific

- [!] **M3.5 source and historical-data completion:** actual point-in-time price,
  ATR, level, path and swing-bar availability, finality, corrections, session,
  venue and compatible adjustment evidence remain required. Synthetic supplied
  records do not close this separate gate.
- [x] **M3.5 — Structural geometry:** the supplied-input calculation passed the
  protected focused and broad acceptance stages with 2994 tests in each stage.
  Two fresh repeatability runs passed 62 tests each and published byte-identical
  `m35-structural-geometry-proof.json` files. See M3_5_VERIFICATION for the exact
  selectors, run records, fingerprints, tested-source manifest and controller
  evidence. Independent review decides acceptance.
- [ ] **M0.2 — current data and shared-capacity audit:** proposed independent next
  work after M3.5 review under the owner's bounded read-only source authority
  with zero additional spending. Keep all source gates open until that work has
  its own evidence.

## Current M0.2 capability-audit result — 2026-09-13 Pacific

- [!] **M0.2 — current data and shared-capacity audit:** record reconciliation
  is finished in DATA_REQUIREMENTS §§44–48 and M0_2_CAPABILITY_AUDIT.json;
  required source and capacity qualification remains blocked. The separately
  authorized 21:09 Pacific Schwab check made two free successful GETs: a SPY
  quote and a restricted SPY chain, 20 contracts over five September 14–18
  expirations. Friday quote/option timestamps remained stale on Sunday despite
  real-time/delay flags. Official units, NBBO fidelity, full entitlement,
  continuity, historical coverage and executable-profit gates remain open.
  The sandbox login failure is only a prior local limitation. Verified
  XNYS.PILLAR / EQUS.MINI 13-ETF inventories contain 4,257,208 / 4,483,742 rows;
  DATA_REQUIREMENTS §44.2 and the JSON audit record exact ranges, hashes,
  incomplete opening windows and four / fifteen provider-degraded dates.
  The valid selected60 v3 inventory also exists, with 40,278,360 scanned
  identities/timestamps. Inventory does not establish full-market coverage,
  original availability, corrections, adjustments, point-in-time universe or
  sector membership; stock selection bias and exposed historical final dates
  remain separate blockers. Tape, canonical VIX, low-latency catalysts,
  qualified historical bars/options/borrow, untouched final validation,
  account-wide request control, retention, memory and latency remain unresolved.
  L2 is an optional blocked enhancement. Current owner authority is 175 GB
  Google Drive build storage, with normal archive admission stopping at 165 GB,
  and up to $60 total Databento API use, a FRESH total (owner decision D-101,
  2026-09-16, superseding the $40 cap). The prior $16 reservation and $24
  unreserved amount are retired and consume none of the $60. Live ledger:
  /root/trade-alerts-builder/databento-spend-ledger.json. Spending inside $60
  needs no further approval. Older roadmap entries below that state "$40 cap,
  $16 reserved, $24 unreserved" are historical records of past attempts and are
  superseded by this line.
  This attempt repairs stale records and the invalid M10.1 dependency choice;
  it preserves prior failures, attempts and published protected proof without
  claiming independent acceptance. All switches remain off.
- [ ] **M0.2A — offline shared-storage retention and capacity contract:**
  proposed independent shared prerequisite, subject to fresh reviewer
  confirmation. Read existing collector/compaction code and local metadata;
  publish explicit retained-record classes, retention periods, disk reserve,
  peak-memory and compaction budgets, plus a bounded protected-test plan for
  source/compact parity, interruption, reopen and disk-full handling. Separate
  measured facts from proposed limits; keep unknown growth/memory measurements
  open. Existing local evidence is enough for this contract work, which does
  not depend on strategy results or qualified historical market inputs. Do not
  delete/offload data, edit private ledgers, contact providers, activate cleanup
  or change production. Acceptance of this contract cannot close M0.2 capacity
  without later measured implementation proof.

M10.1 is not independent: it implements Strategy #5. Required early #1–#4
validation remains open under ROADMAP §14, MASTER_SPEC §19, D-041 and
CONTINUE_AUTOMATED step 8. No #5–#8 implementation is eligible until that gate
closes or an explicit owner decision changes the order. Delegated research-rule
selection does not change it. M0.2A is the only proposed next row from this
blocked assessment; the independent reviewer must confirm its dependency.

## Current M0.2A contract handoff — 2026-09-13 Pacific

- [~] **M0.2A — offline shared-storage retention and capacity contract:** the
  repaired version 2 contract is published in M0_2A_STORAGE_CONTRACT. It separates
  observed metadata from chosen limits and defines retained record classes,
  7/30/750-day periods with legal holds, a 12,000,000,000-byte or 15% disk
  reserve, a 1,500,000,000-byte peak-memory limit, a 256,000,000-byte batch
  limit, a 15-minute compaction limit and the bounded protected test plan. It
  changes no collector code, activates no cleanup and removes no data. Current
  free space remains below the chosen reserve. The earlier controller's focused and
  broad protected phases each passed 2994 tests; the separate repeatability
  phase passed 62 tests in each of two runs. M0_2A_STORAGE_CONTRACT section 8
  records the exact selectors, timings, hashes, artifact directories and tested
  source. Those selections omitted `tests/test_full_chain_collector.py` and
  were insufficient for acceptance. Section 9 preserves the review failure
  and attempt 2 repair: publish chain/open-interest/proof as one set, budget
  every output, and specify failure/retry cases at every member boundary.
  Section 10 records the subsequent collector import failure and the separately
  owner-approved, installed test setup repair: a read-only collector file and
  sanitized temporary-output settings. Repair count 2 and rejected attempts are
  preserved. No fresh pass or independent acceptance is claimed.
  The repaired contract awaits that focused collector check and the expanded
  controller-required broader selection. New figures come from the controller;
  the known local launcher ownership error was not retried. No M0.2B failure
  cases are claimed implemented or passed by this document-only milestone.
  M0.2 capacity remains blocked until later implementation and measured proof.
- [ ] **M0.2B — offline shared-storage implementation and protected proof:**
  proposed next shared prerequisite after M0.2A acceptance, subject to reviewer
  confirmation. Implement the off-by-default bounded compactor, complete
  chain/open-interest/proof set publication,
  admission check and dry-run retention planner defined by M0.2A. Run the named
  parity, reopen, interruption, disk-full, reserve, retention and resource tests.
  Do not activate cleanup or remove/offload owner data. A later measured
  saved-data run is still required before M0.2 capacity can close.

## M0.2A finalization — 2026-09-13 Pacific

- [x] **M0.2A — offline shared-storage retention and capacity contract:** the
  repaired protected focused and acceptance phases each passed 3001 tests with
  the collector check included. The separate repeatability phase passed 62
  tests in each of two runs and was stable. M0_2A_STORAGE_CONTRACT section 11
  records the exact selectors, timings, hashes, artifacts and tested-source
  manifest. This accepts the offline contract only. M0.2 implementation,
  measured capacity, source qualification, cleanup activation and live use
  remain separate gates.
- [ ] **M0.2B — offline shared-storage implementation and protected proof:**
  proposed next shared prerequisite after M0.2A, subject to reviewer
  confirmation. Implement the off-by-default bounded compactor, complete
  chain/open-interest/proof set publication, admission check and dry-run
  retention planner. Run the named protected parity, reopen, interruption,
  disk-full, reserve, retention and resource cases. Do not activate cleanup or
  remove/offload owner data. A later measured saved-data run is still required
  before M0.2 capacity can close.

## Historical M0.2B submission — 2026-09-13 Pacific

The completion claim below was rejected at review. The selections passed but
omitted required cases and did not establish the promised bounded merge,
source verification, admission or missing-data publication behavior. Current
repair status follows this historical submission.

- [~] **M0.2B — historical unaccepted implementation submission:** the
  off-by-default bounded compactor, complete chain/open-interest/proof set,
  verified pointer reader, full-output admission check and dry-run retention
  planner are implemented. The existing daily collector is unchanged and the
  new switch remains off. The eight named synthetic cases cover parity, retry,
  interruption, recovery, no-space failures, reserve math, retention and
  resource limits; interruption and no-space cases cover every publication
  checkpoint with and without a prior set. The protected focused phase passed
  86 tests once, the broad acceptance phase passed 3080 tests once, and the
  separate repeatability phase passed 62 tests in each of two stable runs. The
  focused and broad fresh processes produced the same M0.2B storage-proof hash.
  See M0_2B_VERIFICATION, M0_2B_CONTROLLER_EVIDENCE.json and
  M0_2B_TESTED_SOURCE_MANIFEST.json. No owner data was read, removed or
  offloaded. Capacity, cleanup activation, source qualification and live use
  remain open.
- [ ] **M0.2C — measured saved-data capacity and safe-activation assessment:**
  proposed next shared prerequisite after M0.2B acceptance. Measure the bounded
  compactor on an approved saved-data copy without deleting originals, compare
  source and compact records, record actual bytes, peak memory and wall time,
  and decide whether capacity supports a separately reviewed activation. Keep
  cleanup and all live switches off unless that later review explicitly permits
  them. This work does not close market-source qualification by itself.
- [ ] **M3.3 — Relative-strength engine focused repair:** owner-approved
  independent next work after M0.2B review. Reject selected 15-minute bars with
  revision greater than zero and add the five named direct rejection cases.
  Preserve the earlier blocked assessment and failed proof as history. The
  separate source and historical-data completion gate remains blocked.


## Current M0.2B repair handoff — 2026-09-13 Pacific

- [~] **M0.2B — offline shared-storage implementation repair:** attempt 2
  replaces the accumulated in-memory merge with bounded disk-backed processing,
  inventories retained and temporary bytes, checks reserve during writes,
  validates current source identities, and keeps empty open interest
  unpublished. Direct failure and recovery cases and expanded recordings are
  written. Fresh protected focused/broad and two-process recovery proof are
  pending; no new pass or independent acceptance is claimed. Earlier passing
  proof, rejected attempts and counters remain historical. See
  M0_2B_VERIFICATION sections 2 and 5. All switches stay off; saved-data capacity,
  cleanup activation, market-source and historical evidence remain separate.
- [ ] **M3.3 — Relative-strength engine focused repair:** owner-reopened next
  shared prerequisite after M0.2B's safe review boundary, subject to independent
  reviewer confirmation. Reject selected 15-minute revisions above zero and
  add the named direct rejection cases. Preserve previous failures and the
  separate unresolved source/historical obligation. This is not authorization
  to advance Strategy 5–8 or to change the early-validation order.

## M0.2B finalization — 2026-09-14 Pacific

- [x] **M0.2B — offline shared-storage implementation and protected proof:**
  the repaired protected focused and broad acceptance phases each passed 3388
  tests. The separate repeatability phase passed 62 tests in each of two fresh
  processes and was stable. M0_2B_VERIFICATION records the exact selectors,
  timings, hashes, artifact folders and tested-source manifest. This accepts
  the offline storage path only. Saved-data capacity, cleanup activation,
  market-source qualification, historical evidence and live use remain separate
  gates. All switches remain off.
- [ ] **M3.3 — Relative-strength engine focused repair:** owner-reopened next
  shared prerequisite, subject to independent reviewer confirmation. Reject
  selected 15-minute revisions above zero and add the five named direct
  rejection cases. Preserve the prior rejected proof and blocked assessment as
  history. Its separate source and historical-data completion gate stays blocked.
- [~] **M3.3 — Relative-strength engine focused repair:** owner-approved repair
  rejects every selected 15-minute bar with revision above zero. Five direct
  cases cover revised bars, wrong units, wrong instrument types, wrong sessions
  and incompatible 15-minute adjustment bases. Fresh protected focused/broad
  and two-process recording proof plus independent review remain required. The
  earlier failures and separate source/historical-data gate remain preserved.
- [ ] **M4.7 — minimum options and portfolio path:** proposed next independent
  shared prerequisite after M3.3 review. Reconcile and freeze its remaining
  first-four-playbook rules under the owner's research delegation, then build
  only the minimum offline shared path. Reviewer must confirm dependency order;
  source, historical, early-validation and live gates remain separate.

## M4.7 implementation handoff — 2026-09-14 Pacific

- [~] **M4.7 — minimum options and portfolio path:**
  `M47_FIRST4_RESEARCH_V1` is frozen and the pure offline shared path is built.
  It handles complete-chain option filters and score/rank order, preserves stock
  validity for poor or unavailable options, creates literal-UTF-8 candidate
  fingerprints, records complete batches with fixed anchors and conflicts, and
  applies fixed producer cooldown and intent-expiry boundaries. AT-08/AT-09
  fixtures are added. Fresh protected focused, broad and two-process recording
  proof plus independent review remain required. Source units, complete real
  chains, historical execution, calibration, M14/M15, early validation and live
  use stay separate gates. All switches remain off.
- [ ] **M0.2C — measured saved-data capacity and safe-activation assessment:**
  next independent shared data prerequisite after M4.7 review. It uses an
  approved saved-data copy without deleting originals and does not activate
  cleanup or close market-source qualification. Reviewer must confirm the
  dependency before the controller advances.

## M3.3 owner-reopened repair finalization — 2026-09-14 Pacific

- [x] **M3.3 — Relative-strength engine focused repair:** selected first-15-minute
  bars with revision above zero are rejected. Five direct cases cover revised
  bars, wrong units, wrong instrument types, wrong sessions and incompatible
  15-minute adjustment bases. The controller's protected focused and broad
  phases each passed 2999 tests. Its two-process repeatability phase passed 62
  tests in each fresh process and produced byte-matching M3.3 recordings. See
  M3_3_VERIFICATION.md for exact selectors, timings, hashes, artifact folders
  and the complete tested-source manifest. The prior rejected proof remains
  historical. The separate source and historical-data gate stays blocked. All
  switches remain off.
- [ ] **M4.7 — minimum options and portfolio path:** proposed next independent
  shared prerequisite after M3.3 review. Reconcile and freeze its remaining
  first-four-playbook rules under the owner's research delegation, then build
  only the minimum offline shared path. Reviewer must confirm dependency order;
  source, historical, early-validation and live gates remain separate.

- [~] **M4.7 — minimum options and portfolio path:** implementation and AT-08/
  AT-09 fixtures are ready for fresh protected proof and independent review.
  Attempt 2 corrects a test that assumed input order for simultaneous opposite
  candidates; the frozen fingerprint tie determines the incumbent. The prior
  focused failure remains recorded in M4_7_VERIFICATION. Fresh focused, broad
  and separate two-process recording proof remain pending.
  The definition, source, historical, calibration and live boundaries in the
  M4.7 implementation handoff remain unchanged. All switches remain off.
- [ ] **M0.2C — measured saved-data capacity and safe-activation assessment:**
  proposed next independent shared data prerequisite after M4.7 review. Reviewer
  must confirm the dependency before the controller advances.

## M4.7 finalization — 2026-09-14 Pacific

- [!] **M4.7 — minimum options and portfolio path: BLOCKED, NOT ACCEPTED.** Independent review rejected incomplete AT-08/09 boundaries, unchecked reversal ownership, moving group anchor and missing parent-release record, absent durable cooldown/quota/expiry recovery, and missing fresh-process M4.7 recording comparison. Passing historical focused1/broad3020/repeat62+62 evidence remains valid only for its collected cases; it does not cure these issues. The attempt limit and all old failures are preserved. Actual source, historical execution, calibration, strategy validation and live gates remain separately open. All switches remain off.
- [ ] **M0.2C — measured saved-data capacity and safe-activation assessment:**
  proposed next independent shared data prerequisite around blocked M4.7, subject to fresh independent review confirmation. Use
  an approved saved-data copy without deleting originals; measure bytes, peak
  memory and wall time, and compare source and compact records. Cleanup remains
  off. This work does not close market-source qualification. Reviewer must
  confirm the dependency before the controller advances.

## M0.2C capacity handoff — 2026-09-14 Pacific

- [x] **M0.2C bounded admission assessment:** the approved 2026-08-31 candidate
  inventory is recorded without reading prices or changing owner files. Local
  free space was already below the frozen 12,000,000,000-byte reserve before an
  isolated copy or compactor working files. The run correctly did not start.
  See M0_2C_CAPACITY_ASSESSMENT. This finished check is not performance, parity,
  source or activation proof.
- [!] **M0.2C measured saved-data capacity and safe-activation assessment:
  BLOCKED, NOT COMPLETE.** The unchanged admission rule blocks the isolated-copy
  run. Source/compact record equality, actual output bytes, peak memory and wall
  time remain unmeasured. Cleanup and all live switches remain off. Reopen after
  the existing storage manager finishes eligible recovery and fresh local
  capacity passes the full admission formula. Remote build storage does not
  replace the local reserve.
- [ ] **M0.2D — offline shared request queue and recorded-load AT-13 proof:**
  proposed independent shared data prerequisite around the M0.2C capacity block,
  subject to fresh reviewer confirmation. Implement one off-by-default offline
  queue with fixed account ceiling, priorities, maximum length, expiry and
  timeouts. Use recorded requests only; prove that interactive reads win, expired
  research work is dropped, overload is bounded and no call occurs after expiry.
  Do not contact a provider, activate a runtime path or advance Strategies 5-8.

## M0.2D implementation handoff — 2026-09-14 Pacific

- [x] **M0.2D — offline shared request queue and recorded-load AT-13 proof:**
  the disabled `M02D_REQUEST_QUEUE_V1` SQLite queue and direct recorded-load
  cases are implemented. The fixed offline limits are 110 dispatches per rolling
  60 seconds, 256 pending requests, four priority classes, and explicit class
  expiry/timeouts. Tests cover priority, stale research with no call, bounded
  overload and displacement, reopening the shared ceiling, slow replies,
  throttling, authentication failure and an offline-only dispatch boundary.
  Fresh protected focused, broad and two-process recording proof passed with
  zero failures, errors or skips. The recorded queue proof matches byte for byte
  across both fresh repeatability processes. No consumer is wired and all
  switches stay off. See M0_2D_VERIFICATION. Independent acceptance remains.
- [ ] **M0.2E — current provider-limit and source-contract reconciliation:**
  proposed next shared data prerequisite after M0.2D review. Reconcile the
  recorded queue ceiling and intended consumers with existing dated access proof
  and official provider limits, subscription rules, fields and units. Use current
  saved evidence first; make no new provider request or purchase. Keep source,
  continuity, historical, capacity and live gates open unless their own evidence
  is complete. Reviewer must confirm dependency order.

## M0.2E implementation handoff — 2026-09-14 Pacific

- [x] **M0.2E — current provider-limit and source-contract reconciliation:**
  the saved two-request Schwab access proof, disabled M0.2D queue and public
  official provider documents are reconciled in DATA_REQUIREMENTS section 60,
  CODING_STANDARDS section 75 and M0_2E_SOURCE_RECONCILIATION. Fresh protected
  focused, broad and two-process recording proof passed with zero failures,
  errors or skips and stable recording comparisons. The queue's 110-
  dispatch rolling ceiling is a local safety limit, not a Schwab allowance.
  Schwab numeric account/stream limits, entitlement, time units, NBBO meaning,
  continuity and finality remain unknown. XNYS.PILLAR stays separate from the
  derived component-venue EQUS.MINI source; missing OHLCV rows stay missing
  without source-backed no-trade proof. No provider request, credential read,
  purchase, runtime wiring or live action occurred. Independent acceptance
  remains pending. M0.2 source, history, capacity and live gates stay open. All
  switches remain off. See M0_2E_VERIFICATION.
- [ ] **M0.2F — retained Databento minute-source manifest and offline adapter:**
  proposed next independent shared data prerequisite after M0.2E review. Use the
  existing immutable XNYS.PILLAR and EQUS.MINI files under bounded read-only
  source authority. Preserve separate publisher/venue identity, gaps, provider-
  degraded dates, raw message times, unknown original availability/finality and
  source hashes. Add no provider request or purchase, and do not call inventory
  qualifying historical, point-in-time, correction-complete or executable proof.
  Reviewer must confirm dependency order before the controller advances.

## M0.2F implementation handoff — 2026-09-14 Pacific

- [~] **M0.2F — retained Databento minute-source manifest and offline adapter:**
  the two immutable 13-ETF inventories are recorded separately with their file
  hashes, request ranges, counts, opening gaps and provider-degraded dates. The
  pure offline adapter preserves raw message time, source identity and unknown
  availability/finality/correction facts without reading a file or joining
  feeds. Direct cases and one fresh-process recording case are ready. Protected
  focused, broad and two-process recording proof plus independent review remain
  required. Source, history, capacity, validation and live gates stay open. All
  switches remain off. See M0_2F_VERIFICATION.
- [ ] **M0.2G — coverage-only session manifest and split-admission report:**
  proposed next shared data prerequisite after M0.2F review. Derive exact covered
  symbol/date rows from inventory only, before reading strategy results, and
  decide whether a chronological split may be frozen. Keep the split unavailable
  while required stock, tape, correction, point-in-time or untouched-final facts
  are missing. Preserve executable and source gates.
  Reviewer must confirm dependency order before the controller advances.

## M0.2F finalization — 2026-09-14 Pacific

- [x] **M0.2F — retained Databento minute-source manifest and offline adapter:**
  the two immutable 13-ETF inventories remain separate with their file hashes,
  request ranges, counts, opening gaps and provider-degraded dates. The offline
  adapter preserves raw message time, source identity and unknown availability,
  finality and correction facts. Protected focused and broad phases passed 11
  and 3048 tests. The separate repeatability phase passed 64 tests in each of
  two fresh processes and produced matching M0.2F recordings. See
  M0_2F_VERIFICATION for exact selectors, timings, hashes, artifact folders and
  the complete tested-source manifest. Source, history, capacity, validation and
  live gates stay open. All switches remain off.
- [ ] **M0.2G — coverage-only session manifest and split-admission report:**
  proposed next shared data prerequisite after M0.2F review. Derive exact covered
  symbol/date rows from inventory only, before reading strategy results, and
  decide whether a chronological split may be frozen. Keep the split unavailable
  while required stock, tape, correction, point-in-time or untouched-final facts
  are missing. Preserve executable and source gates. Reviewer must confirm
  dependency order before the controller advances.

## M0.2G blocked assessment — 2026-09-14 Pacific

- [x] **M0.2G bounded coverage-only inventory assessment:**
  `M0_2G_COVERAGE_ONLY_MANIFEST.json` records 22,958 separate
  dataset/symbol/date inventory rows and an exact empty qualifying-row list.
  No source file, price, volume, return or strategy result was opened. See
  M0_2G_SPLIT_ADMISSION_REPORT.
- [!] **M0.2G coverage-only session manifest and split admission: BLOCKED, NOT
  COMPLETE.** Zero rows meet the full first-four source rule. Required stock,
  tape, original-availability, finality, correction, adjustment, point-in-time
  membership, borrow, historical option and untouched-final facts remain
  missing. The qualifying manifest fingerprint and all three chronological date
  lists stay null. Replay, promotion and live gates remain blocked.
- [ ] **M0.2H — first-four historical source coverage-and-cost preflight:**
  proposed next independent shared data step around the M0.2G source block,
  subject to fresh reviewer confirmation. Map each missing stock, tape,
  correction, point-in-time, borrow and historical option fact to saved or
  official evidence and record a bounded acquisition plan and cost before any
  request. Do not inspect strategy results, spend, contact a provider or advance
  Strategies 5-8 in the preflight.

## M0.2H implementation handoff — 2026-09-14 Pacific

Historical implementation status; see the finalization and corrected comparison
below for current proof. Both next-step rows now reflect the bounded assignment.

- [~] **M0.2H — first-four historical source coverage-and-cost preflight:**
  `M0_2H_SOURCE_ACQUISITION_SPEC.json` freezes the exact 60-stock plus SPY
  research set, historical and forward holdout bounds, seven required record
  shapes and six unsent Databento cost checks. Existing selected60 and ETF
  inventories and the dated Schwab check are preserved as limited evidence.
  Historical borrow and catalyst sources remain unidentified. All requested
  prices remain unknown; this milestone made zero provider requests, credential
  reads, downloads, reservations or spending. Fresh protected documentation
  verification and independent review remain required. Source qualification,
  chronological split, replay, executable claims, promotion and live use stay
  blocked. Strategies 5-8 remain behind early first-four validation.
- [!] **M0.2 qualifying historical source and split:** still blocked by complete
  stock tape/NBBO coverage, original availability, finality/corrections,
  adjustments, point-in-time membership, historical borrow/options, catalyst
  history and untouched qualifying final dates. M0.2H is a request plan, not
  acquired or qualified data.
- [ ] **M0.2I — bounded free source cost check:**
  proposed next shared data step only after fresh independent M0.2H review
  permits advancement. Execute only the six preregistered
  `Historical.metadata.get_cost` requests, once each and serially. No retries or
  additional reference, entitlement, coverage or symbology requests are assigned;
  those facts remain unresolved gates. Record returned costs and failed,
  unavailable or unattempted requests without requesting source records,
  downloading data, refreshing tokens, changing reservations or the ledger,
  inspecting prices or returns, purchasing or spending. Cost estimates do not
  qualify coverage or historical execution. Preserve the $40 cap, $16 reserved,
  $24 unreserved and unknown billing. Stop before any expanded operation; later
  acquisition still requires a qualifying route within that cap and local
  storage admission. Reviewer must confirm dependency order.

## M0.2H finalization — 2026-09-14 Pacific

- [x] **M0.2H — first-four historical source coverage-and-cost preflight:**
  the finite 60-stock plus SPY request plan, historical and forward holdout
  bounds, seven record shapes and six unsent cost checks are frozen. The
  protected focused and broad phases each passed 3,048 tests. The separate
  repeatability phase passed 64 tests in each of two protected runs with stable
  matching artifacts. `M0_2H_SOURCE_PREFLIGHT.md` records the exact selectors,
  controller wall times, published artifact folders, tested source hash and
  complete tested-source list. This completed preflight made no provider
  request, credential read, download, reservation or spend. It does not qualify
  a source or split, and all live switches remain off. The corrected records-only
  comparison is `M0_2H_RECORDS_ONLY_COMPARISON.json`; fresh independent review
  must accept the correction before M0.2I advances.
- [!] **M0.2 qualifying historical source and split:** still blocked by complete
  stock tape/NBBO coverage, original availability, finality/corrections,
  adjustments, point-in-time membership, historical borrow/options, catalyst
  history and untouched qualifying final dates. M0.2H is a request plan, not
  acquired or qualified data.
- [ ] **M0.2I — bounded free source cost check:**
  proposed next shared data step only after fresh independent M0.2H review
  permits advancement. Execute only the six preregistered
  `Historical.metadata.get_cost` requests, once each and serially. No retries or
  additional reference, entitlement, coverage or symbology requests are assigned;
  those facts remain unresolved gates. Record returned costs and failed,
  unavailable or unattempted requests without requesting source records,
  downloading data, refreshing tokens, changing reservations or the ledger,
  inspecting prices or returns, purchasing or spending. Cost estimates do not
  qualify coverage or historical execution. Preserve the $40 cap, $16 reserved,
  $24 unreserved and unknown billing. Stop before any expanded operation; later
  acquisition still requires a qualifying route within that cap and local
  storage admission. Reviewer must confirm dependency order.

## M0.2I implementation handoff — 2026-09-14 Pacific

Historical V1 handoff. The later V2 evidence-reconciliation section holds the
current M0.2I status.

- [~] **M0.2I — bounded free source cost check:** all six preregistered
  `Historical.metadata.get_cost` calls were started once, serially, with the
  frozen request fields. The sandbox denied the named credential read and local
  name lookup failed before any provider connection. No response or cost was
  returned, so all six costs remain `UNKNOWN`; no retry is permitted. No source
  record request, download, token refresh, reservation, ledger change, result
  inspection or spending occurred. See `M0_2I_COST_CHECK_RESULT.json` and
  `M0_2I_COST_CHECK.md`. Fresh protected document checks and independent review
  remain required. All switches remain off.
- [!] **M0.2 qualifying historical source and split:** still blocked by
  unavailable cost evidence plus complete stock tape/NBBO coverage, original
  availability, finality/corrections, adjustments, point-in-time membership,
  historical borrow/options, catalyst history and untouched qualifying final
  dates. The failed free checks do not qualify a source or split.
- [ ] **M0.2J — bounded source-access recovery decision:** proposed next shared
  data step after M0.2I review. Confirm whether a fresh task may send any cost
  request after these six calls failed before a provider connection. Do not
  treat this row as retry authority. Preserve the frozen request set, no-retry
  history, $40 cap, $16 reservation, $24 unreserved amount, local storage gate
  and all source, validation and live blockers. Reviewer must confirm the exact
  authority and dependency before the controller advances.

## M0.2I V2 evidence reconciliation — 2026-09-14 Pacific

- [~] **M0.2I — bounded free source cost check:** the original V1 record stays
  unchanged with six local SDK failures, zero provider connections and zero
  provider responses. A separately assigned and independently reviewed V2 task
  sent three POST cost requests once each and in order. `EQUS.MINI` trades
  returned USD 101.393871814013 and `mbp-1` returned USD 931.397507786751, both
  with HTTP 200. `OPRA.PILLAR` `cmbp-1` returned HTTP 400 for an unknown specific
  cause, so the task stopped and the remaining three OPRA requests were not
  attempted. There were no retries, downloads, source-record requests,
  reservations, ledger changes or new spending. Dates before March 28, 2023
  remain unpriced. See `M0_2I_COST_CHECK_V2_RESULT.json` and
  `M0_2I_COST_CHECK_V2.md`. Fresh protected document checks and independent
  review remain required. All switches remain off.
- [!] **M0.2 qualifying historical source and split:** still blocked. Each
  returned estimate exceeds the USD 24 unreserved amount, while billing remains
  unknown. Complete stock tape/NBBO, original availability, corrections and
  finality, adjustments, point-in-time membership, historical borrow/options,
  catalyst history, untouched qualifying final dates and local capacity also
  remain unresolved. Estimates are not bills, account authorization or source
  qualification. No qualifying split, replay, promotion, profit or live claim
  is permitted.
- [ ] **M0.2J — source and budget blocked assessment:** proposed next shared
  data boundary after M0.2I review. Record the owner/data decision required by
  the two estimates above the remaining cap, the unknown OPRA HTTP 400 cause,
  the three unattempted OPRA costs and the other unpriced or unidentified source
  groups. This row authorizes no retry, provider request, download, purchase,
  reservation, ledger change or cap change. Reviewer must confirm eligibility
  and the exact boundary before the controller advances.

## M0.2I protected finalization — 2026-09-14 Pacific

- [!] **M0.2I — bounded free source cost check: BLOCKED.** Protected acceptance
  passed 3,048 tests, and two fresh repeatability processes each passed 64 tests
  with stable compared output. The record is complete and preserves V1. V2
  returned two estimates above the USD 24 unreserved amount, then stopped on an
  OPRA HTTP 400 whose specific cause is unknown; three OPRA requests and dates
  before March 28, 2023 remain unpriced. No retry, download, source request,
  purchase, reservation, ledger change or new spending occurred. The test proof
  does not qualify a source or close the source, split, capacity, replay,
  promotion or live gates. All switches remain off.
- [!] **M0.2J — source and budget blocked assessment: SUPERSEDED.** The
  independently reviewed V2 recovery already resolved the proposed access step,
  and the M0.2I records now state the actual source and budget boundary. Another
  assessment would repeat the same facts and is not a concrete dependency-ready
  milestone. Further source progress requires new owner or data authority that
  changes the source, cost or budget boundary.
- [ ] **M4.7A — owner-reopened first-four options and portfolio repair:** the
  owner delegated the direction decision and the supervisor chose the separately
  reviewed focused repair in
  `repairs/codex-subscription/m47-reopen-proposal/PROPOSAL.md`. Preserve the
  original M4.7 failed attempts, blocked record and historical proof. Rebuild
  reversal release from checked original producer evidence; keep the original
  group anchor separate from the current owner; restore parent release, quota,
  mechanical clocks, fingerprints, absolute expiry and cooldown facts; add the
  missing AT-08/AT-09 boundary cases; and add a meaningful M4.7 recording that
  is collected and byte-compared in both fresh repeatability processes. This is
  an offline first-four shared repair. It does not close source, capacity,
  replay, promotion, profit or live gates. Fresh independent review must confirm
  this exact scope and order before implementation advances.


## M4.7A implementation handoff — 2026-09-14 Pacific

- [~] **M4.7A — owner-reopened first-four options and portfolio repair:** the
  focused offline repair is implemented. A reversal claim now carries and
  rechecks the original ORB attempt, failed-break handoff, reversal request,
  saved session and canonical supporting records before ownership can change.
  The saved group keeps its original anchor separate from its current owner and
  records the checked parent release. Each wrapper carries explicit producer
  counts, reset state, original mechanical clocks, identity, session close and
  absolute delivery deadline. The event store checks these facts when reopening
  the exact saved projection. New cases cover both option directions, expiry and
  age edges, missing proof, exact score parts, forged release claims, changed
  source values, missing recovery facts and saved recovery. The M4.7 recording
  includes option scores and reasons, every independent identity, the checked
  release, fixed anchor/current owner and recovery facts. Fresh protected focused,
  broad and two-process M4.7 recording proof plus independent review remain.
  All earlier M4.7 failures and proof remain historical. Source, capacity,
  historical execution, calibration, early validation, profit and live gates
  remain blocked. All switches remain off.

## M4.7A protected acceptance — 2026-09-15 Pacific

- [x] **M4.7A — owner-reopened first-four options and portfolio repair:**
  accepted. Build run `20260914-060429-391233-build` published passing focused
  (2 tests), broad (3070 tests) and two-process repeatability (65 tests each,
  stable, `m4_7_options_portfolio.json` byte-compared) protected proof; see
  `M4_7_VERIFICATION.md`. All earlier M4.7 blocked history and attempts remain
  historical. Source field units, complete real chains, historical option
  execution, calibration, early strategy validation, profitability, shadow use
  and live use remain separately blocked. All switches remain off.
- [ ] **M9.3 — shadow mode:** proposed next milestone. M4.7A resolves the
  adopted options/portfolio dependency that was blocking this row. The separate
  M0.2 provider/queue/storage/disk/memory budget and continuity proof and a
  separately reviewed environment repair for the prior storage/temporary-folder
  acceptance failure remain open and unresolved by this record. Independent
  review must confirm eligibility before the controller advances.

## M9.3 blocked assessment — 2026-09-15 Pacific

- [!] **M9.3 — shadow mode: BLOCKED.** M4.7A's acceptance above clears only the
  adopted options and portfolio dependency. The milestone's other named
  prerequisites are still open: the selected M0.2 provider, queue, storage, disk
  and memory budgets and the validated input continuity they depend on. The last
  M0.2 rows stay `[!]`, with both returned cost estimates above the USD 24
  unreserved amount, an unknown OPRA HTTP 400 cause, unpriced dates and
  unresolved local capacity, so no agent step can close them; that boundary needs
  an owner or data decision. The earlier M9.3 controller acceptance run also
  failed on test-environment storage (database or disk full during setup, then
  temporary test folders could not be created); that environment repair needs its
  own reviewed assignment. The complete M9.3 change is records only:
  `trade_alerts_build_docs/ROADMAP.md` and
  `trade_alerts_build_docs/M9_3_VERIFICATION.md`. No product code, test,
  configuration or protected input changed, and no new protected run is claimed.
  No shadow input, delivery, activation, spending or profit claim is added here.
  No dependency-ready next milestone remains: every other open row is a blocked
  source, data, capacity or owner-decision gate. All switches remain off.

## M0.2 / M9.3 owner-decision release — 2026-09-16 Pacific

The 2026-09-15 M9.3 assessment above named five things no agent step could
close. The owner answered all of them on 2026-09-16. Decisions are recorded in
`DECISIONS_AND_OPEN_QUESTIONS.md` section 54 (D-101 to D-105) and in
`/root/trade-alerts-builder/repairs/codex-subscription/owner-active-supervision.json`.

- **"Cost estimates above the USD 24 unreserved amount."** RESOLVED. Databento
  authority is now **USD 60, a fresh total** (D-101). The $16 reservation and
  $24 unreserved amount are retired and consume none of it.
- **"Unknown OPRA HTTP 400 cause."** RESOLVED (D-105). `BRK.B.OPT` is invalid
  because `.` is the OPRA root/type separator; the correct parent is
  `BRKB.OPT`. Verified with `metadata.get_cost`. Every other OPRA request in
  the frozen set prices normally once that one symbol is corrected.
  `M0_2H_SOURCE_ACQUISITION_SPEC.json` is corrected.
- **"Unpriced dates."** RESOLVED. The paid window is fixed at one year,
  2025-09-15 to 2026-09-15 (D-102), and every schema in it has been priced.
- **"Unresolved local capacity."** RESOLVED. The system journal was vacuumed to
  200 MB and `~/.openclaw/db-backups` was moved to the authorized Drive folder
  with upload / re-download / SHA256 round-trip proof per file
  (`archives/storage-manager/db-backups-transfer.json`). The newest backup is
  retained locally. `fixed_reserve_bytes` and `reserve_fraction` are unchanged.
- **"Test-environment storage failure during the M9.3 acceptance run."** The
  cause was the same full disk; the capacity work above is its repair. It still
  needs its own verification run, which is now possible.

### D-104 changes the M0.2 acceptance bar

M0.2 no longer requires that every field be proven. A field that cannot be
obtained is **recorded as a gap**, and every rule depending on it is **switched
off and labelled untested**. A missing field is never approximated, proxied or
filled so a test can run through it, and any result produced with a rule
switched off must say which rules were off.

This applies to the gates money cannot open: original availability, corrections
and finality, point-in-time index membership, historical borrow, and
complete-chain proof. Each becomes a recorded gap with its dependents disabled,
not a halt on the whole milestone. Evidence standards for the fields that ARE
obtained are unchanged, and no replay, alert, order or deployment is authorized.

### Paid history acquired under this release

EQUS.MINI, `raw_symbol`, 2025-09-15 to 2026-09-15, 17 names (D-102): `trades`,
`bbo-1m`, `ohlcv-1m`. Estimated USD 22.47 of the USD 60. Ledger:
`/root/trade-alerts-builder/databento-spend-ledger.json`. Data:
`/home/openclaw/.openclaw/research-data/databento/core17-1y_2025-09_to_2026-09/`.
Tick `mbp-1` was priced at USD 548 and deliberately NOT bought: intrabar path
(whether a stop was hit before a target) is answered by tick `trades`, and the
spread for a fill model is estimated from `bbo-1m`. Full option chains were
priced at USD 1,088 and above and are NOT bought; option requests, if any, are
restricted to the contracts and dates a signal actually selects, within the
10% ITM to 10% OTM band (D-103) and the existing 0-7 DTE limit.

All switches remain off. No live activation, order, alert, deployment or
profit claim is added here.

### Free option-chain source checked before any option spending — 2026-09-16

`post-no-preference/options` on DoltHub (free, no login, cloned locally at
`/home/openclaw/.openclaw/research-data/todo-111/dolt`) was checked first, as
the plan required. Measured, not assumed:

- Coverage of the D-102 universe is 12 of 17. NVDA, MSFT, AAPL, GOOGL, AMZN,
  META, AVGO, TSLA, BRK.B, LLY, SPY and XLV return rows for the week of
  2026-08-17. QQQ, IWM, GLD, USO and VXX return **zero rows**.
- It is one **end-of-day** snapshot per contract per trading day, and the
  strike ladder is sampled: SPY showed 29-44 distinct strikes per day against
  a real chain of hundreds.

It therefore cannot price a 0-7 DTE entry or exit at a real intraday
timestamp, which is what the strategies under test need. It is a **usable
reference for contract existence, expiry ladders and end-of-day level checks
only**, and is recorded as such. It is **not** a substitute for paid option
quotes and does not close any M0.2 option gate.

Consequence: no option data has been bought. USD 37.53 of the USD 60 remains.
Any later option purchase stays targeted — only the contracts and dates a
signal actually selects, inside the D-103 10% ITM to 10% OTM band and the
existing 0-7 DTE limit — because a full year of chains prices at USD 1,088 and
above, which the budget cannot cover.
