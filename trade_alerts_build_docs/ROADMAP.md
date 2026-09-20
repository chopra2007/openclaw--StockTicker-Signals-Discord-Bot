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

## M9.3 status after the owner-decision release — 2026-09-16 Pacific

- [!] **M9.3 — shadow mode: still BLOCKED, now on proof rather than on an owner
  decision.** The release above answers every owner question the 2026-09-15
  assessment named, but it does not itself publish the proof M9.3 depends on:
  the selected mode's M0.2 provider/queue/storage/disk/memory budgets and
  validated input continuity have not been measured and recorded under the D-104
  bar (gaps recorded, dependent rules switched off and labelled untested), and
  the storage repair has not had its own verification run. The complete M9.3
  change stays records only: `trade_alerts_build_docs/ROADMAP.md` and
  `trade_alerts_build_docs/M9_3_VERIFICATION.md`. No code, test, configuration
  or protected input changed, and no new protected run is claimed. All switches
  remain off.
- [ ] **M0.2K — D-104 gap register and selected-mode budget and continuity
  proof:** using only data already held (the D-102 core17 EQUS.MINI one-year
  files, the 13-ETF inventories and existing collector dates), record each
  field that cannot be obtained as a gap with its dependent rules switched off
  and labelled untested, and measure and record the selected mode's provider,
  queue, storage, disk and memory budgets and input continuity, including a
  verification run of the storage repair. Shared data prerequisite work only; no
  new provider request, spending, Strategy 5-8 work, replay result, alert, order
  or activation. Independent review must confirm eligibility before the
  controller advances.

## M0.2K finalization — 2026-09-16 Pacific

- [x] **M0.2K — D-104 gap register and selected-mode budget and continuity
  proof:** `M0_2K_GAP_REGISTER.json` records ten D-104 gaps (original
  availability, corrections/finality, point-in-time index membership,
  historical borrow, complete real option chain, option intrabar tick path, the
  free DoltHub reference source's coverage/timestamp limits, pre-2023-03-28 OPRA
  pricing, catalyst history, and the collector-date-2026-09-11 and 13-ETF
  provider-degraded coverage holes) plus two fields obtained without a gap, each
  with its dependent rules named as switched off and labelled untested; nothing
  is approximated or filled. `M0_2K_VERIFICATION.md` selects the offline
  recording-sink shadow mode M9.3 names and measures its budgets: Databento
  provider (USD 60 authority, USD 22.4702 spent, USD 37.53 remaining, ledger
  `/root/trade-alerts-builder/databento-spend-ledger.json`); the frozen offline
  queue ceiling (110/60s, max length 256, disabled); storage/disk (free
  13,149,548,544 bytes now exceeds the 12,046,114,407-byte reserve by about
  1.10 GB, curing the 2026-09-14 disk-full admission failure for plain reads;
  the bounded compactor's own larger working-space reservation is separately
  recorded as still not admitted); and memory (1.5 GB `peak_memory_bytes`
  ceiling against about 4.9 GiB available). Input continuity is shown by 13
  contiguous monthly files per schema spanning the full 2025-09-15 to
  2026-09-15 window with no date gap. The storage-repair verification run
  reran the two files that failed the 2026-09-15 M9.3 acceptance
  (`test_orb5_replay.py`, `test_rs_trend_eligibility.py`) through the protected
  launcher, one fresh process: 225 passed in 41.55s, exit code 0, artifacts at
  `/tmp/trade-alerts-m04-ve9o341n/run-1`, no disk-full or temporary-folder
  error. No new provider request, spending, Strategy 5-8 work, replay result,
  alert, order or activation occurred. All switches remain off.
- [ ] **M9.3 — shadow mode:** proposed next milestone. M0.2K above publishes the
  selected mode's provider/queue/storage/disk/memory budgets, input continuity
  and the storage-repair verification run that the 2026-09-15 blocked
  assessment named as missing; M4.7A already resolved the adopted
  options/portfolio dependency. The bounded compactor's own admission gap and
  every D-104-recorded field gap and its disabled dependent rules stay open and
  unresolved by this record. Independent review must confirm eligibility before
  the controller advances.

## M9.3 blocked assessment — missing replay adapters — 2026-09-16 Pacific

- [!] **M9.3 — shadow mode: BLOCKED.** M9.3's own text requires proving "the
  initial pipeline with the first four playbooks," using the shared M5.3
  `Strategy` protocol and `HistoricalReplayRunner` (`consensus_engine/historical_replay.py`)
  that M0.2K's selected offline recording-sink shadow mode is built on. Reading
  the four playbook modules before writing anything shows only two of the four
  have that adapter: `consensus_engine/orb5_replay.py` (`Orb5ReplayStrategy`,
  built under M6.4) and `consensus_engine/hod_comp_rs_replay.py`
  (`HodCompRsReplayStrategy`, built under M7.5) both subclass `Strategy` and
  are driven by `HistoricalReplayRunner.run()` today, as
  `tests/trade_alerts_contracts/test_orb5_replay.py` and
  `test_rs_trend_eligibility.py` already prove. `consensus_engine/or_failure_rev.py`
  (`OrFailureRevMachine`) and `consensus_engine/first_pullback_vwap.py`
  (`FirstPullbackVwapMachine`), built under M8.2 and M8.4, only expose their own
  `ReversalRequest`/`ReversalAssessment` and `PullbackRequest`/`PullbackAssessment`
  shapes; neither subclasses `Strategy` or is callable from
  `HistoricalReplayRunner`. Phase 8 of this ROADMAP (M8.1 through M8.5) never
  reserved a milestone for that adapter step the way M6.4 and M7.5 did for the
  first two playbooks, so this is a real gap in the plan itself, not a data or
  owner-decision gate: building two new ~500-line `Strategy` adapters that
  correctly re-derive `StrategyState`/`StrategyStateTransition` from each
  Machine's existing gate logic is new, unscoped, strategy-specific
  implementation work with its own correctness risk, not a same-session
  extension of M9.3's records-only budget/continuity proof. It needs its own
  milestone, definition review and protected test coverage before M9.3 can
  honestly say all four playbooks ran through the initial pipeline, so it is
  not attempted here. No code, test, configuration or protected input changed
  in this M9.3 attempt; only this record and the M8.6 row below were added.
  Nothing here claims trigger, edge, delivery or promotion evidence, and no
  switch is enabled.
- [ ] **M8.6 — replay adapters for `OR_FAILURE_REV` and `FIRST_PULLBACK_VWAP`:**
  proposed next milestone. Add the M5.3 `Strategy`-protocol adapters for
  `OrFailureRevMachine` and `FirstPullbackVwapMachine`, mirroring the pattern
  `orb5_replay.py`/M6.4 and `hod_comp_rs_replay.py`/M7.5 already used for the
  first two playbooks, with their own offline replay/synthetic test coverage.
  This reuses only already-adopted M8.2/M8.4 gate logic and the existing M5.3
  runner; it adds no new threshold, source claim or spending. Independent
  review must confirm eligibility before the controller advances. Closing it
  is what would let a future M9.3 attempt honestly run all four playbooks
  through the shared pipeline.

## M8.6 finalization — 2026-09-16 Pacific

- [x] **M8.6 — replay adapters for `OR_FAILURE_REV` and `FIRST_PULLBACK_VWAP`:**
  `consensus_engine/or_failure_rev_replay.py` (`OrFailureRevReplayStrategy`) and
  `consensus_engine/first_pullback_vwap_replay.py`
  (`FirstPullbackVwapReplayStrategy`) add the M5.3 `Strategy`-protocol adapters
  for `OrFailureRevMachine` (M8.2) and `FirstPullbackVwapMachine` (M8.4),
  mirroring `orb5_replay.py`/M6.4 and `hod_comp_rs_replay.py`/M7.5: every
  threshold, handed-over M8.1 handoff or M8.3 measurement, observation,
  confirmation, structural reading and confidence result is supplied by the
  caller for one exact instant, `heads_up`/`actionable` stay `None`, and
  `invalidate`/`expire` keep the same M8.2/M8.4 boundary of never letting a
  caller assert an outcome the supplied evidence did not produce. Unlike the
  first two playbooks these two machines have no separate eligibility owner, so
  each adapter proposes directly against its one M8.2/M8.4 machine, including
  the staged `SETUP_FORMING -> ARMED -> ALERT_TRIGGERED` transition pair in one
  evaluation when the supplied inputs already pass every gate. No new
  threshold, source claim or spending is added; the two machines' own frozen
  M8.2/M8.4 rules are reused unchanged (`or_failure_rev_replay_rules()` and
  `first_pullback_vwap_replay_rules()` equal `reversal_rules()` and
  `pullback_rules()` exactly). New offline synthetic test coverage:
  `tests/trade_alerts_contracts/test_or_failure_rev_replay.py` and
  `test_first_pullback_vwap_replay.py`, each with a clean-trigger scenario and a
  missing-last-trade arm-only scenario run through the real M5.3
  `HistoricalReplayRunner`, the real M4.2 `StateTransitionEngine` and the real
  M5.1 `SQLiteTransitionStore`/`ResearchEventStore`, plus byte-identical
  replay-determinism checks, a recorded scenario proof, and the same
  Strategy-interface/boundary/immutability/backward-time/invalidate/expire/reset
  coverage style the M6.4 and M7.5 adapters use. Controller-recorded focused
  protected run (`selection_reason`: "builder named directly affected checks",
  per `test_summary.focused`): selector `tests/trade_alerts_contracts`, runs 1,
  test count 3160, exit code 0, controller wall_seconds 594.718, published
  artifacts `published-artifacts-9cc15931f359`. Controller-recorded broad
  acceptance run (`selection_reason`: "unknown dependency impact; safe broad
  fallback", per `controller-evidence.json`): selector
  `tests/trade_alerts_contracts`, runs 1, test count 3160, exit code 0,
  controller wall_seconds 586.807, published artifacts
  `published-artifacts-5f63d4f61c62`. Controller-recorded repeatability run
  (`selection_reason`: "recording output requires fresh-process comparison",
  per `test_summary.repeatability`): the named list of 45
  recording/deterministic selectors (including
  `test_or_failure_rev_replay.py::test_the_same_supplied_scenario_replays_byte_identically`,
  `test_or_failure_rev_replay.py::test_the_two_scenarios_record_one_deterministic_proof`,
  `test_first_pullback_vwap_replay.py::test_the_same_supplied_scenario_replays_byte_identically`
  and `test_first_pullback_vwap_replay.py::test_the_two_scenarios_record_one_deterministic_proof`),
  runs 2, test count 71, exit code 0, controller wall_seconds 335.972,
  published artifacts `published-artifacts-2c74f8308614`. All three phases
  are from build run `20260916-090228-828429-build`. Zero failures,
  errors or skips in any recorded run. `controller-evidence.json` records one
  mechanical test entry (the broad full-directory run); the focused phase also
  ran the full `tests/trade_alerts_contracts` directory rather than only the
  two directly affected files, per `test_summary.focused.selectors`, and this
  record reflects that. Earlier drafts of this record cited artifact folders
  left in the same run directory by earlier controller stages
  (`published-artifacts-a542abd9c89c`, `published-artifacts-b26341f4894f`,
  `published-artifacts-b426c8fde11d`, `published-artifacts-f079b6ba7a70`,
  `published-artifacts-5072df07aaf2`, `published-artifacts-3c96fc530a2f`) and
  a focused-phase test count of 90; those citations did not match the
  controller's current published evidence and are corrected here. No live
  activation,
  broker/Discord/provider call, application run, message, order, deployment,
  bot restart or spending occurred; all switches remain off. This closes the
  plan gap the 2026-09-16 M9.3 blocked assessment named; it does not itself
  claim trigger, edge, delivery, promotion, source, historical-execution or
  live evidence, and every D-104-recorded field gap and its disabled dependent
  rules stay open and unresolved by this record.
- [ ] **M9.3 — shadow mode:** proposed next milestone. All four first-playbook
  Strategy-protocol adapters now exist (`Orb5ReplayStrategy`/M6.4,
  `HodCompRsReplayStrategy`/M7.5, `OrFailureRevReplayStrategy`/M8.6,
  `FirstPullbackVwapReplayStrategy`/M8.6), M0.2K already published the selected
  offline recording-sink shadow mode's provider/queue/storage/disk/memory
  budgets, input continuity and the storage-repair verification run, and M4.7A
  already resolved the adopted options/portfolio dependency. The bounded
  compactor's own admission gap and every D-104-recorded field gap and its
  disabled dependent rules stay open and unresolved by this record. Independent
  review must confirm eligibility before the controller advances.

## M9.3 finalization — 2026-09-16 Pacific

- [x] **M9.3 — shadow mode:** `consensus_engine/shadow_pipeline.py` implements
  the engineering-pilot shared session over the four Strategy-protocol
  adapters (`Orb5ReplayStrategy`/M6.4, `HodCompRsReplayStrategy`/M7.5,
  `OrFailureRevReplayStrategy`/M8.6, `FirstPullbackVwapReplayStrategy`/M8.6),
  driven through the real M5.3 `HistoricalReplayRunner`, the real M4.2
  `StateTransitionEngine` and the real M5.1 `SQLiteTransitionStore`/
  `ResearchEventStore`, recording to the sink by default per M9.3's own text.
  New offline synthetic coverage:
  `tests/trade_alerts_contracts/test_shadow_pipeline.py`, including
  byte-identical replay-determinism and one deterministic recorded pilot proof
  across the shared session. Controller-recorded focused protected run
  (`selection_reason`: "builder named directly affected checks"): selector
  `tests/trade_alerts_contracts/test_shadow_pipeline.py`, runs 1, test count 17,
  exit code 0, controller wall_seconds 18.298, published artifacts
  `published-artifacts-096ceb39584b`. Controller-recorded broad acceptance run
  (`selection_reason`: "unknown dependency impact; safe broad fallback"):
  selector `tests/trade_alerts_contracts`, runs 1, test count 3177, exit code
  0, published artifacts `published-artifacts-effaa9698503`. Controller-recorded
  repeatability run (`selection_reason`: "recording output requires
  fresh-process comparison"): the named list of 45 recording/deterministic
  selectors (including
  `test_shadow_pipeline.py::test_the_same_shared_session_replays_byte_identically`
  and
  `test_shadow_pipeline.py::test_the_shared_session_records_one_deterministic_pilot_proof`),
  runs 2, test count 73, exit code 0, controller wall_seconds 344.648,
  published artifacts `published-artifacts-ec41ed8a7b4d`. All three phases are
  from build run `20260916-135437-689602-build`; verification handoff manifest
  `verified-manifest.json`, source hash
  `a933a339cfed8bcf5d27d52e1d0539ed95ed6ff6208d271d7efd86d7b36af1f6`. Zero
  failures, errors or skips in any recorded run. Review confirmed protected
  supervisor tests passed and asked only for this evidence/roadmap
  finalization; no code, test, configuration or protected input changed in
  this finalization pass. This proves safe recording and input continuity for
  the initial pipeline across the first four playbooks, per M9.3's own text; it
  is the engineering pilot only, not the M17 evidence-bearing promotion gate.
  No live activation, broker/Discord/provider call, application run, message,
  order, deployment, bot restart or spending occurred; all switches remain
  off. The bounded compactor's own admission gap and every D-104-recorded
  field gap and its disabled dependent rules stay open and unresolved by this
  record. This does not claim trigger, edge, delivery, human-reaction or
  promotion evidence.
- [ ] **M9.4 — human decision tags:** proposed next milestone. M9.3's shared
  pilot session and recording sink now exist across all four first-playbook
  adapters; independent review must confirm eligibility, exact scope and any
  remaining dependency before the controller advances.

## M9.4 blocked assessment — 2026-09-16 Pacific

- [x] **M9.4 human-decision-tag capability:** the canonical `HumanDecisionRecord`
  (`consensus_engine/trade_alerts_models.py`), its append-only
  `ACKNOWLEDGMENT` storage in the M5.1 research event store
  (`consensus_engine/event_store.py`) and its recovery read path
  (`SessionRecovery.record_acknowledgment`/`acknowledgments` in
  `consensus_engine/session_recovery.py`) already implement the offline
  ACCEPTED/REJECTED/NO_DECISION tag, free-text note and optional manual trade
  price MASTER_SPEC §20 requires so "alerts support human decision-making."
  Existing coverage in `tests/trade_alerts_contracts/test_domain_models.py` and
  `tests/trade_alerts_contracts/test_session_recovery.py` already exercises this
  record end to end; no new field, table or code path is required or added by
  this milestone. This checkbox records that this offline capability exists; it
  is not a new trigger, delivery or human-reaction evidence claim.
- [!] **M9.4 — human decision tags: BLOCKED on the early #1–#4 validation gate,
  as this milestone's own text requires.** MASTER_SPEC §19 and D-041 require
  completing early validation of playbooks #1–#4 before #5–#8 implementation.
  M9.1's historical replay gate is still `INSUFFICIENT_DATA` for all four
  playbooks (line 829 above) and M9.3's accepted shadow pilot is explicitly the
  engineering pilot only, not the M17 evidence-bearing promotion gate; neither
  supplies real trigger, expectancy, MFE/MAE, reaction-decay or human-decision
  data because no live activation, delivery or human reaction is authorized or
  has occurred. There is therefore no real `HumanDecisionRecord` population to
  measure "human decision drift" or "human-selection drift" against, so the
  early-validation gate stays open exactly as this milestone's own text
  requires, and Strategy #5–#8 implementation (M10.1 and later) stays behind it
  absent an explicit owner decision changing that order. No source, historical,
  delivery or live gate is closed or narrowed by this record. All switches
  remain off; no application ran, no message or order was sent and no spending
  occurred.
- No independent shared/data prerequisite is currently open in this roadmap:
  M0.2K, M4.7A, M8.6 and M9.3 are all accepted above and no further `[ ]` shared
  prerequisite row remains. The only path past this gate is either qualifying
  historical/live evidence for M9.1/M9.3 or an explicit owner decision to
  reorder implementation; this record proposes no next milestone.

## M9.1 assessment is stale — 2026-09-16 Pacific

The M9.4 stop of 2026-09-16 14:29 rests on M9.1's `INSUFFICIENT_DATA` verdict.
That verdict is dated **2026-09-13**, which is before two things that changed
its inputs: the paid EQUS.MINI history now on disk, and owner decision D-104.
This section records the current facts. It does **not** re-open, re-decide or
accept M9.1, calculate any return, choose any parameter, or authorize live
action; a fresh assessment under the normal build and review path still owes
that work.

Measured 2026-09-16 from
`/home/openclaw/.openclaw/research-data/databento/core17-1y_2025-09_to_2026-09/`:
**251 trading sessions, 2025-09-15 to 2026-09-14, 17 symbols**, schemas
`ohlcv-1m`, `bbo-1m` and `trades`. The 17 include the benchmark and reference
names SPY, QQQ, IWM, XLV, GLD, USO and VXX (D-102).

Against M9.1 section 2's five missing-evidence bullets:

1. **Minute bars, quotes, benchmark/reference and participation inputs** — now
   held for the 17 names: `ohlcv-1m` for bars, `bbo-1m` for quotes, `trades`
   for the tick path, volume for participation, and the seven benchmark names
   above. On 2026-09-13 none of this existed locally.
2. **Original source and availability times, finality, revisions, corrections,
   adjustments** — a **D-104 gap**, already entered in
   `M0_2K_GAP_REGISTER.json`. Every rule depending on it is switched off and
   labelled untested. It is not approximated or filled.
3. **The prior-session history each playbook needs** — 251 sessions supports
   the M0_3B walk-forward rule (at least 60 training sessions, consecutive
   20-session test blocks advancing by 20) with room for multiple folds.
4. **Corporate-action and historical-universe handling** — point-in-time
   membership is a **D-104 gap** in the same register, dependents off.
5. **Approved frozen definitions and an execution/outcome policy per playbook**
   — **still genuinely open.** This is definition work, not a data or owner
   gate, and choosing any threshold, timing, participation, risk or confidence
   value after seeing returns remains forbidden.

So M9.1's blocker is no longer "no historical dataset exists". It is bullet 5,
plus two recorded gaps whose dependent rules stay off.

### The part that remains an owner decision

M9.4's stop also says M9.3's shadow pilot supplies no real trigger or
human-reaction evidence and that no live activation is authorized to produce
it. That is unchanged and is **not** resolved here. Human-reaction evidence
cannot be manufactured offline. Under D-104 it is a gap: record it, switch off
every rule that depends on it, label those untested, and do not approximate it.
No live activation, alert, order or deployment is authorized by this section.

## M9.4 / early validation gate — owner decisions of 2026-09-16 evening

The 2026-09-16 17:36 M9.4 stop named two things: no human-decision evidence,
and M9.1's historical replay still `INSUFFICIENT_DATA`. Both now have owner
answers. Full text in `DECISIONS_AND_OPEN_QUESTIONS.md` sections 55-57.

- **Human-decision evidence — closed by D-106.** The owner will take every
  alert, within 30 seconds, with no skipping. The discretionary variable is
  removed rather than measured, so the system's measured result is the owner's
  result. Fills are modelled from the price path 0-30 seconds after alert time,
  using real quotes, never the trigger price. No rule may lean on human
  judgement to rescue a weak trigger. This is a stated policy, not observed
  behaviour, and authorizes no live activation.
- **Parameter selection — unblocked by D-107.** Choosing thresholds by
  measuring returns is approved, provided the proof comes from a held-out set.
  Tune on 9 named symbols, prove on 8 never-inspected symbols. No date holdout,
  by owner choice; the study therefore proves generalisation across symbols
  only, not across time, and must say so.
- **Pass/fail — fixed by D-108, frozen before the search runs.** Mean profit
  per trade after costs with a bootstrap lower bound above zero, at least 60%
  winning weeks, and a worst drawdown recoverable in about six average winning
  weeks.

M9.1's remaining bullet-5 obstacle — "thresholds, timing rules, participation
rules, risk choices and confidence floors are not all approved" — is what D-107
resolves: they are now chosen by measured search on the training symbols rather
than by prior approval. The two D-104 gaps behind M9.1 (original availability
and finality; point-in-time membership) stay recorded gaps with their dependent
rules switched off.

All switches remain off. No live activation, alert, order, deployment or profit
claim is created by this section.

## M9.4 finalization — 2026-09-16 Pacific

- [!] **M9.4 — human decision tags: gate still open, now on execution rather
  than on an owner decision.** D-106, D-107 and D-108 (above) answer every
  policy question the 2026-09-16 14:29 and 17:36 stops named: how a human
  decision is modelled, how parameters may be chosen, and what "passes" means.
  They do not themselves run the walk-forward search, produce the held-out
  9-train/8-test proof, or evaluate it against D-108's bar. That empirical
  study is real work against the 251-session `core17-1y` dataset and is not a
  roadmap edit; this milestone's own text ("complete the required early #1-4
  validation") is not satisfied until it runs and either passes or records its
  own exact BLOCKED/INSUFFICIENT_DATA result. No such run has occurred. This
  finalization changed only `trade_alerts_build_docs/ROADMAP.md`; no code,
  test, configuration or protected input changed. All switches remain off; no
  application ran, no message or order was sent and no spending occurred.
- [ ] **M9.1 — Historical replay #1-4 (reopened under D-104/D-106/D-107/D-108):**
  the next concrete step is the frozen, pre-registered walk-forward parameter
  search itself — tune on the 9 named training symbols, prove on the 8 named
  held-out symbols, apply D-108's frozen pass bar — using the now-held 251
  session `core17-1y` dataset, with the two D-104 gaps (original
  availability/finality; point-in-time membership) kept as recorded gaps and
  their dependent rules switched off and labelled untested. Independent review
  must confirm this scope before implementation begins.

### Two owner option-exit arms added — 2026-09-16 evening

`EXIT_OWNER_SCALE80_V1` and `EXIT_OWNER_SCALE80_TRAIL15_V1` are preregistered
in `DECISIONS_AND_OPEN_QUESTIONS.md` section 58 (D-109), before any return has
been read. Both scale out 4 of 5 contracts at 1.20x the entry premium; one
takes the runner at 2.00x or a breakeven stop, the other trails it 15% below
its high-water mark. Midpoint fills throughout, never held to expiry, stop
resolves first inside a shared one-minute observation.

They do not alter the 72 stock arms in M0_3B, which remain frozen and are
measured in R on the underlying. The option arms are measured in option premium
and are reported separately, on targeted option data bought only for the days
and strikes the surviving setups select. The one-minute quote granularity is a
recorded limitation of the trailing arm in particular.

## M9.1 build-scope inventory — 2026-09-17 Pacific (partial, code unchanged)

This session read the 2026-09-16 reopening text above ("the next concrete step
is the frozen, pre-registered walk-forward parameter search itself") against
the actual repository to see what that step needs. No code, test,
configuration or protected input changed; this is a records-only inventory of
a genuine implementation gap, not a data or owner gate.

**What exists.** `consensus_engine/databento_minute_bars.py` converts one
already-decoded DBN OHLCV-1m row into a canonical `Bar`; it has no reader for
the actual retained files under
`/home/openclaw/.openclaw/research-data/databento/core17-1y_2025-09_to_2026-09/`
(1.2 GB across `ohlcv-1m`, `bbo-1m`, `trades`, 17 symbols, 251 sessions).
`core_price_features.py`, `opening_range_features.py` and
`participation_features.py` compute D-090 features from a supplied
`HistoryBatch`/`Bar` sequence, with no I/O of their own. `orb5_replay.py`,
`hod_comp_rs_replay.py`, `or_failure_rev_replay.py` and
`first_pullback_vwap_replay.py` each drive their strategy's existing state
machine, but only over caller-supplied `EligibilityRequest`/`TriggerRequest`
instants, thresholds and confidence results for one already-identified
instant; none of them derives those instants from raw bars. `outcome_evaluator.py`
resolves outcomes for exactly one strategy (`CRVOL_ORB5`, `BAR_ONLY_ORB5_O1_PROXY_V1`)
using next-bar-open entry with no spread, slippage or commission model; it does
not implement the D-106 0-30-second post-alert tick-fill window or the D-107
real-`bbo-1m`-spread/cost requirement, and no outcome evaluator exists yet for
`HOD_COMP_RS`, `OR_FAILURE_REV` or `FIRST_PULLBACK_VWAP`.

**What is missing before a real search can run**, all as new code with its own
tests, none of which exists today:

1. a bulk loader from the retained `core17-1y` DBN files into canonical
   `Bar`/quote/trade records, per symbol per session;
2. an adapter per playbook from that canonical history into the
   `EligibilityRequest`/`TriggerRequest`/confidence inputs each replay module
   already accepts (the state machines themselves need no change);
3. a D-106/D-107-compliant fill and cost model (0-30s post-alert window,
   `bbo-1m` spread, modeled slippage, commissions) shared across playbooks,
   and outcome evaluators for the three playbooks that do not have one;
4. the frozen parameter grid over the eight open settings (D-043, D-044,
   D-045, D-048, D-049, D-052, D-054, D-055) and playbook-combination choices,
   pre-registered before any result is read, plus the enforced 9-train/8-held-out
   symbol split from D-107;
5. the D-108 evaluator itself: per-trade mean profit after costs with a
   bootstrap confidence interval, weekly win-rate (>=60%), and worst-drawdown
   recoverable within about six average winning weeks, computed only on the
   held-out eight and frozen before the search runs.

None of items 1-5 exists in the repository under any name. This is
substantially more than one milestone step can safely absorb in a single
session without risking exactly the kind of shortcut D-104 forbids (filling a
missing input so a test can run through it). Building it in one uninspected
pass would also make it hard for independent review to check the frozen grid,
the split enforcement and the cost model each on their own, which the roadmap
text above already asks review to confirm before implementation proceeds.

**Recommendation, not yet acted on:** split the reopened M9.1 step into
reviewed sub-steps — (a) the bulk `core17-1y` loader, (b) per-playbook
bar-to-replay-input adapters plus the missing outcome evaluators with the
D-106/107 fill and cost model, (c) the frozen grid/split pre-registration
record, (d) the D-108 evaluator, (e) the search run itself against the
held-out eight. This session performed no data load, no feature computation
against real bars, no signal generation, no parameter choice and no return
calculation. The two D-104 gaps (original availability/finality;
point-in-time membership) remain recorded gaps with dependent rules off. All
switches remain off; no application ran, no message or order was sent and no
spending occurred.

## M9.1A — core17-1y OHLCV-1m bulk loader — 2026-09-17 Pacific

Implements build-scope item (a) from the inventory above only: a bulk loader
from the retained `core17-1y` OHLCV-1m DBN files into the existing canonical
`DatabentoMinuteRecord`/`Bar` adapter. New module
`consensus_engine/core17_bar_loader.py`, new tests
`tests/trade_alerts_contracts/test_core17_bar_loader.py`.

`verify_retained_files` hashes every file a batch-job manifest lists and
raises rather than proceeding on a missing file, size mismatch or hash
mismatch; no network call. `reverse_symbol_map` builds instrument-id-to-symbol
from one file's Databento symbology and raises on an unresolved, partial or
duplicate mapping. `iter_ohlcv_1m_records` converts already-decoded,
duck-typed OHLCV-1m rows (not the live `databento` package) through the
existing `normalize_databento_ohlcv_1m` adapter, raising on any row whose
instrument does not resolve or whose session date is not in the retained
condition list, rather than dropping it. Context received/available/normalized
times are all set to each bar's own close instant (`start + 1 minute`): the
retained batch files carry no real receipt-latency timestamp (verified by
inspecting a real decoded record: no `ts_recv` field), so this records the
earliest instant the bar could exist rather than inventing a latency figure.
`open_core17_ohlcv_1m_file` is a thin integration wrapper around the real
`databento.DBNStore` and the real retained files; it is deliberately not
exercised by the offline contract tests, since the retained files and the
`databento` decode path are outside the protected sandbox mount.

A read-only local inspection (not a protected test run, not repeated as
evidence below) confirmed the real retained `core17-1y` OHLCV-1m
2025-09-15..30 file decodes with `databento` 0.84.0, that its
`symbology.mappings` resolves all 17 raw symbols to instrument ids with no
`not_found`/`partial` entries, and that `condition.json` dates use
`"available"`/`"degraded"` values matching
`DatabentoMinuteContext.provider_condition`. No decoded row exposes a
`ts_recv` field, confirming the batch files carry no real receipt-latency
timestamp.

The two D-104 gaps (original availability/finality; point-in-time membership)
stay recorded gaps with dependent rules off, unchanged by this loader. No
signal generation, no feature computation, no parameter choice and no return
calculation happens in this module. All switches remain off; no application
ran, no message or order was sent and no spending occurred.

Still missing before a real walk-forward search can run: (b) per-playbook
bar-to-replay-input adapters, a D-106/107-compliant fill and cost model, and
outcome evaluators for `HOD_COMP_RS`, `OR_FAILURE_REV` and
`FIRST_PULLBACK_VWAP`; (c) the frozen parameter-grid/split pre-registration
record; (d) the D-108 statistical evaluator; (e) the search run itself. Items
(b)-(e) are unstarted; this row implements (a) only.

- [x] **M9.1A — core17-1y OHLCV-1m bulk loader:** implemented as described
  above. Controller-published protected proof (run
  `/root/trade-alerts-builder/runs/20260917-074102-485403-build`,
  `verification_handoff` source hash
  `29e114a8038f3adaae6283262848e2437f94d73185dac7eff30e6728e70cd4d4`): focused
  phase (`tests/trade_alerts_contracts/test_core17_bar_loader.py`,
  `tests/trade_alerts_contracts/test_databento_minute_bars.py`), 21 tests,
  3.063s wall, exit 0; broad acceptance phase over
  `tests/trade_alerts_contracts`, 3187 tests, exit 0; repeatability phase, 2
  fresh-process runs, 73 recording selectors each (see published artifacts
  `published-artifacts-cfb872e50dfd`, top-level acceptance artifacts, and
  `published-artifacts-434322edef47`), stable and hash-compared across both
  runs. No code, test or protected input changed since that manifest; this
  finalization records only the ROADMAP row. The controller's broad acceptance
  artifact (`published-artifacts-5d9bb5501f51`) records 597.257 controller wall
  seconds for its 3187 tests.
- [!] **M9.1 — Historical replay #1-4 (reopened), sub-step handoff —
  2026-09-17 Pacific:** too large for one session. Only sub-step M9.1A (the
  bulk loader) is built and proven; sub-steps (b)-(e) above are unstarted, so
  the walk-forward search has not run and M9.1 has no pass, BLOCKED or
  `INSUFFICIENT_DATA` result of its own yet. Work continues at M9.1B. The two
  D-104 gaps stay recorded gaps with dependent rules off. No code, test or
  protected input changed in this handoff record.
## M9.1B — shared D-106/D-107 fill and cost model — 2026-09-17 Pacific

Implements one piece of build-scope item (b) from the inventory above: the
shared fill and cost model that D-106 (0-30 second post-alert window) and
D-107 (real spread, modeled slippage, commissions) require, ahead of the
per-playbook adapters and the three missing outcome evaluators, which remain
unbuilt (see M9.1C below). New module `consensus_engine/fill_cost_model.py`,
new tests `tests/trade_alerts_contracts/test_fill_cost_model.py`.

`model_fill` takes an alert time, a direction, a sequence of already-normalized
trade-print `Quote` records, a sequence of top-of-book `Quote` snapshots, and
an explicit `FillCostPolicy` (caller-supplied `slippage_bps` and
`commission_per_share`; these are cost-realism inputs, not searched or
returns-chosen strategy parameters). The window is fixed at D-106's 30 seconds
and is not configurable. The fill price is the first valid trade print at or
after alert time within that window — never the most favorable print in the
window, and never the trigger price. Its cost is the half-spread from the most
recent valid quote at or before that print (or, absent one, the earliest valid
quote still inside the window), plus the policy's slippage and commission. A
trade print or quote below `VALID` quality is excluded rather than used
un-labeled. Absence of a usable trade print or quote inside the window is
returned as an explicit `NO_TRADE_IN_WINDOW`/`NO_QUOTE_AT_FILL` status with a
null price, per D-104, rather than approximated. No data is fetched, no alert
instant is chosen, no position is sized and no stop/target outcome is
evaluated here.

The two D-104 gaps (original availability/finality; point-in-time membership)
are unaffected by this model and stay recorded gaps with dependent rules off.
No signal generation, no feature computation against real bars, no parameter
search and no return calculation happens in this module. All switches remain
off; no application ran, no message or order was sent and no spending
occurred.

Still missing before a real walk-forward search can run: per-playbook
bar-to-replay-input adapters and outcome evaluators for `HOD_COMP_RS`,
`OR_FAILURE_REV` and `FIRST_PULLBACK_VWAP` that consume this fill/cost model
(build-scope item (b), remainder); the frozen parameter-grid/split
pre-registration record (item (c)); the D-108 statistical evaluator (item
(d)); and the search run itself (item (e)).

- [x] **M9.1B — shared D-106/D-107 fill and cost model:** implemented as
  described above. Focused local run (not the controller's published proof):
  `tests/trade_alerts_contracts/test_fill_cost_model.py`, 15 tests, passed
  twice in separate fresh processes with 0 failures/errors/skips. The
  controller's own protected focused/broad/repeatability runs are the proof of
  record for acceptance and are not restated here.
- [!] **M9.1 — Historical replay #1-4 (reopened), sub-step handoff —
  2026-09-17 Pacific:** still too large for one session. Sub-steps M9.1A (bulk
  loader) and M9.1B (fill/cost model) are built; per-playbook adapters and the
  three missing outcome evaluators, the frozen grid/split record, the D-108
  evaluator and the search run itself are unstarted, so the walk-forward
  search has not run and M9.1 has no pass, BLOCKED or `INSUFFICIENT_DATA`
  result of its own yet. Work continues at M9.1C. The two D-104 gaps stay
  recorded gaps with dependent rules off. No code, test or protected input
  changed in this handoff record.
## M9.1C — shared D-106/D-107 outcome evaluator for HOD_COMP_RS, OR_FAILURE_REV, FIRST_PULLBACK_VWAP — 2026-09-17 Pacific

The named M9.1C scope bundled two different-sized pieces: per-playbook
raw-bar-to-replay-input adapters (deriving RS trend, compression, distance,
extension and tape-intensity features from `core17_bar_loader` bars for each
of `HOD_COMP_RS`'s M7.2/M7.3 machine, `OR_FAILURE_REV`'s and
`FIRST_PULLBACK_VWAP`'s equivalents) and the three playbooks' missing
D-106/107-compliant outcome evaluators. Reading the three replay modules and
their composed-outcome dataclasses (`HodCompRsOutcome`, `ReversalAssessment`,
`PullbackAssessment`) showed all three already expose the same shape once
composed — `risk: RiskLevel | None`, `targets: tuple[TargetLevel, ...]`,
`confidence`, `status`, `evaluated_at` — so one evaluator can resolve any of
their outcomes without playbook-specific logic, while the adapters (deriving
those composed values from raw bars in the first place) are separate,
substantially larger, unbuilt work with no shared shape across playbooks.
Following the same too-large-for-one-session split used for M9.1A/M9.1B, this
session builds only the shared evaluator; the adapters move to M9.1D.

New module `consensus_engine/playbook_outcome_evaluator.py`, new tests
`tests/trade_alerts_contracts/test_playbook_outcome_evaluator.py`.
`evaluate_playbook_outcome` accepts one already-composed `risk`/`targets` pair
for `HOD_COMP_RS`, `OR_FAILURE_REV` or `FIRST_PULLBACK_VWAP` only (a fourth
`strategy_id` raises), models entry with `fill_cost_model.model_fill` (D-106's
fixed 0-30s post-alert window and D-107's real spread/slippage/commission —
never the trigger price, never the most favorable print in the window), and
then resolves the stop/target path bar-by-bar from supplied history using the
same stop-first-conservative rule the existing `CRVOL_ORB5`
`BAR_ONLY_ORB5_O1_PROXY` evaluator already uses, generalized from that
evaluator's fixed two units to one unit per supplied target so it also
supports single- or three-target playbooks. `NO_TRADE_IN_WINDOW` and
`NO_QUOTE_AT_FILL` (from the fill model) and incomplete bar coverage all stay
explicit `UNKNOWN`/`CENSORED` results per D-104, never approximated. It
derives no eligibility, trigger or structural input from raw bars; it
evaluates an outcome that another owner already composed.

The two D-104 gaps (original availability/finality; point-in-time membership)
are unaffected by this evaluator and stay recorded gaps with dependent rules
off. No signal generation, no feature computation against real bars, no
parameter search and no return calculation happens in this module. All
switches remain off; no application ran, no message or order was sent and no
spending occurred.

Still missing before a real walk-forward search can run: the per-playbook
raw-bar-to-replay-input adapters for `HOD_COMP_RS`, `OR_FAILURE_REV` and
`FIRST_PULLBACK_VWAP` (build-scope item (b), remainder — this is M9.1D); the
frozen parameter-grid/split pre-registration record (item (c)); the D-108
statistical evaluator (item (d)); and the search run itself (item (e)).

- [x] **M9.1C — shared D-106/D-107 outcome evaluator:** implemented as
  described above. Focused local run (not the controller's published proof):
  `tests/trade_alerts_contracts/test_playbook_outcome_evaluator.py` (11
  tests) together with `test_fill_cost_model.py` and `test_outcome_evaluator.py`
  (75 tests total), passed in one run with 0 failures/errors/skips; the new
  file alone also passed twice in separate fresh processes with identical
  results. The controller's own protected focused/broad/repeatability runs are
  the proof of record for acceptance and are not restated here.
- [!] **M9.1 — Historical replay #1-4 (reopened), sub-step handoff —
  2026-09-17 Pacific:** still too large for one session. Sub-steps M9.1A (bulk
  loader), M9.1B (fill/cost model) and M9.1C (shared outcome evaluator) are
  built; the per-playbook raw-bar-to-replay-input adapters, the frozen
  grid/split record, the D-108 evaluator and the search run itself are
  unstarted, so the walk-forward search has not run and M9.1 has no pass,
  BLOCKED or `INSUFFICIENT_DATA` result of its own yet. Work continues at
  M9.1D. The two D-104 gaps stay recorded gaps with dependent rules off. No
  code, test or protected input changed in this handoff record.
## M9.1D — blocked before implementation: core17 bars can never reach `FINAL` in the existing shared history path — 2026-09-17 Pacific

Read before editing: `consensus_engine/databento_minute_bars.py`,
`consensus_engine/historical_bars.py`, `consensus_engine/outcome_evaluator.py`,
`consensus_engine/playbook_outcome_evaluator.py`. No code, test, configuration
or protected input changed in this session; this is a records-only finding
from tracing the exact data path M9.1D's adapters would have to feed.

`normalize_databento_ohlcv_1m` (the only conversion from `core17_bar_loader`
rows to a canonical `Bar`) unconditionally sets `is_final=False`,
`adjustment_basis="UNKNOWN"`, and the `DatabentoMinuteRecord`-level
`finality="UNKNOWN"`, because no source proof of finality exists for the
retained files (the recorded D-104 gap). That is correct on its own.

But every existing shared consumer of minute bars for this walk-forward step
reads bar usability through `HistoryBatch.coverage_at`, and that method's
status ladder is: `not bar.is_final` -> `"PROVISIONAL"`, checked *before* the
`"NO_TRADE"`/`"FINAL"` branch. Since core17 bars are permanently
`is_final=False`, every interval built from them is permanently
`"PROVISIONAL"` and can never become `"FINAL"` or `"NO_TRADE"`. Every
consumer that gates on `status == "FINAL"` is unconditionally blocked, not
just the finality-dependent fact itself:

- `rs_trend_eligibility._lookback_return` (`RS_WINDOW_` + status when not in
  `("FINAL", "NO_TRADE")`) — RS, median dollar volume, RVOL, open return all
  read this.
- `relative_strength_features._first_fifteen_return` — same ladder.
- `outcome_evaluator.py:111,180` and `playbook_outcome_evaluator.py:147,187`
  (the M9.1C shared evaluator built two sessions ago) — entry-bar selection
  and the stop/target path both require `item.status == "FINAL"` and stop
  scanning explicitly `break`s on the first non-`FINAL` interval.

So a bar-to-replay-input adapter built against the existing shared history
contract would not produce a working eligibility/trigger/outcome pipeline
with gaps in the specific D-104-named areas (original availability,
finality, corrections, PIT membership) — it would produce **no usable
feature or outcome at all**, for every minute, because the *entire* history
coverage ladder is gated on finality, not only the finality-labelled facts.

This is a scope beyond D-104's own text. D-104 says a missing field is a
recorded gap with *its* dependents switched off; it does not say the
underlying obtained price/volume becomes unusable everywhere. Making core17
research bars usable for this walk-forward step — while still recording
finality/corrections/PIT as open gaps and not silently upgrading them to
proven — needs a decision on how (or whether) the shared `HistoryBatch`
contract, which live/production code also depends on, should treat a
`PROVISIONAL`-forever bar for offline research use, separate from any live
evidentiary path. That is a definition/architecture question for the owner
or an explicit reviewed research-arm decision, not something this session
should resolve unilaterally inside the shared production module. Until that
decision exists, no per-playbook adapter (`HOD_COMP_RS`, `OR_FAILURE_REV`,
`FIRST_PULLBACK_VWAP`) can be built or tested against real core17 bars: it
would either silently bypass the finality gate (forbidden) or produce
100% `UNKNOWN`/`CENSORED` output (proves nothing, not a real search).

No provider call, spend, or code/test change happened in this session. All
switches stay off.

- [!] **M9.1D — per-playbook raw-bar-to-replay-input adapters:** blocked
  before implementation by the finding above. The remaining build-scope item
  (b) — adapters from `core17_bar_loader` bars into each playbook's existing
  `EligibilityRequest`/`TriggerRequest` inputs for `HOD_COMP_RS`,
  `OR_FAILURE_REV` and `FIRST_PULLBACK_VWAP` — cannot proceed until an owner
  or reviewed-research decision states how a permanently-`PROVISIONAL`
  (finality-unknown) bar may be used for offline research feature/outcome
  computation without changing the live `HistoryBatch` evidentiary contract.
  Independent review must confirm the finding and the required decision
  before any further M9.1D implementation attempt.

### M9.1D unblocked — provisional bars are usable for offline research, 2026-09-17

M9.1D stopped because Databento history is permanently `PROVISIONAL`: finality
cannot be established, so `HistoryBatch.complete` and `final_bars` exclude every
bar and no per-playbook adapter can read anything.

D-110 settles it. Offline research computes over PROVISIONAL bars through its
own explicitly-named path. `complete` and `final_bars` keep their exact present
meaning and the live evidentiary contract is untouched, so no production caller
can consume finality-unknown bars by accident. Every research result records
that its bars were finality-unknown and how many intervals were provisional.
The finality gap stays open in `M0_2K_GAP_REGISTER.json` with its dependent
rules switched off; D-110 permits only the rules that do not require proven
finality. No live path may read the research accessor. All switches stay off.

## M9.1D sub-step — D-110 research-bar accessor built; per-playbook adapters still open — 2026-09-17 Pacific

Following the same too-large-for-one-session split used for M9.1A/M9.1B/M9.1C,
this session builds only the shared D-110 accessor the three per-playbook
adapters all need; the adapters themselves move to M9.1E.

`consensus_engine/research_bar_access.py` adds `research_coverage_at`, the one
explicitly-named research path D-110 requires. It calls the existing untouched
`HistoryBatch.coverage_at` and admits `PROVISIONAL` intervals (in addition to
the `FINAL`/`NO_TRADE` intervals the live `final_bars` already admits) into a
new `ResearchCoverage.bars`; `MISSING`/`NOT_ENDED`/`CONFLICT`/quality- and
convention-rejected intervals stay excluded exactly as they are from
`final_bars`. `historical_bars.py` itself is not modified: `complete` and
`final_bars` keep their exact present meaning (condition 1). Every
`ResearchCoverage` carries `.label()`, naming decision D-110, the exact
`M0_2K_GAP_REGISTER.json` "corrections and finality" gap field, and the
final/no-trade/provisional/excluded interval counts, satisfying condition 2's
labelling requirement. No live module imports this new file (condition 3). The
finality gap itself is not touched or closed in `M0_2K_GAP_REGISTER.json`
(condition 4).

New offline synthetic test coverage:
`tests/trade_alerts_contracts/test_research_bar_access.py`, covering: the live
`coverage_at`/`final_bars` view still rejects provisional bars unchanged; the
new research view admits them and reports correct final/no-trade/provisional/
excluded counts; the research view exactly equals `final_bars` when finality
is already established (no behavior change for already-final data); missing
and not-yet-ended intervals stay excluded from the research view too; the
label's exact decision/gap-field/count fields; and a `RecordError` on a
non-`HistoryBatch` argument. Locally run once through the protected launcher
for orientation only (not protected acceptance evidence):
`tests/trade_alerts_contracts/test_research_bar_access.py` (6 passed) and the
directly affected `tests/trade_alerts_contracts/test_historical_bars.py`,
confirming the live contract is unchanged (75 passed), both exit code 0.
Controller-published protected proof for this milestone follows separately
from build run `20260917-152402-043294-build` and supersedes these self-run
numbers.

No code path here derives eligibility, trigger or structural input from raw
bars; it only decides which bars a research caller may see. The three
per-playbook adapters from raw `core17_bar_loader` bars into `HOD_COMP_RS`,
`OR_FAILURE_REV` and `FIRST_PULLBACK_VWAP`'s existing `EligibilityRequest`/
`TriggerRequest` inputs (each backed by 600-1200 line eligibility/trigger
modules) remain unbuilt; each is independent, larger, strategy-specific
implementation work that does not fit in the same session as this shared
accessor. No provider call, spend, or live/alert/order action occurred in this
session. All switches stay off.

- [x] **M9.1D — D-110 research-bar accessor:** implemented as described above;
  `consensus_engine/research_bar_access.py` and its test file are the complete
  change. This closes the blocking finding from the "blocked before
  implementation" record above by giving offline research a way to read
  `PROVISIONAL` bars without touching the live `HistoryBatch` contract.
## M9.1E sub-step — `HOD_COMP_RS` RS/benchmark lookback research adapter; the rest of `HOD_COMP_RS` and both other playbooks still open — 2026-09-17 Pacific

Read before editing: `consensus_engine/rs_trend_eligibility.py`,
`consensus_engine/research_bar_access.py`. Tracing what a real per-playbook
adapter needs found that `RsTrendPolicy` binds nine `REQUIRED_ROLES`
(`MEDIAN_DOLLAR_VOLUME`, `RVOL`, `OPEN_RETURN`, `DAILY_ATR_PCT`,
`SESSION_VWAP`, `RS`, `RS_WARMUP_COMPLETE`, `REFERENCE_EXTREME_COMPLETE`,
`COMPRESSION_COMPLETE`) plus two quote-derived gates
(`QUOTE_ACTIONABLE`/`SPREAD_BPS`) before `HOD_COMP_RS` eligibility can be
assessed at all, and each role needs its own real-bar (or real-quote) adapter
threaded through `research_coverage_at`, mirroring one already-adopted M7.x
feature builder each. That is far more than one session, so this session
narrows further than the "one playbook at a time" split the M9.1D record
proposed: it builds only the `RS`/`RS_WARMUP_COMPLETE` pair, the two roles
`rs_trend_eligibility.build_rs_trend_snapshot`'s own lookback-return measurement
computes purely from minute price bars.

New module `consensus_engine/hod_comp_rs_research_adapter.py` adds
`build_rs_trend_snapshot_from_research`, mirroring `build_rs_trend_snapshot`'s
window-selection, contiguity, no-trade and instrument-type checks exactly
(same refusal reasons), but admitting `PROVISIONAL` intervals as ready in
addition to `FINAL`/`NO_TRADE`, and calling the new-in-M9.1D
`research_coverage_at` for each side (stock, benchmark) solely to attach that
side's D-110 label (decision, gap field, final/no-trade/provisional/excluded
counts) to the result. `historical_bars.py` and `rs_trend_eligibility.py` are
untouched (no code path here modifies a shared production module or its
status ladder). The produced `FeatureSnapshot` carries its own
`RESEARCH_RS_FEATURE_VERSION`/`RESEARCH_RS_DATA_MODE`, distinct from the live
`RS_FEATURE_VERSION`/`RS_DATA_MODE`, so an `RsTrendPolicy` binding cannot match
it by accident; only a policy that names these research identifiers explicitly
can bind to it for replay.

New offline synthetic test coverage:
`tests/trade_alerts_contracts/test_hod_comp_rs_research_adapter.py` (8 cases),
covering: a `PROVISIONAL`-only history producing the same RS/benchmark/return
numbers a `FINAL` history would (the live function would refuse this with
`RS_WINDOW_PROVISIONAL`); the D-110 label naming decision/gap-field/interval
counts on each side; warm-up-incomplete, missing-interval and no-traded-interval
refusals behaving exactly like the live function's; a missing benchmark history
leaving that side's label `None` while the stock side still succeeds; and the
explicit symbol/instrument-type/benchmark-identity validation. Locally run once
through the protected launcher for orientation only (not protected acceptance
evidence): the new file (8 passed) and the directly affected
`tests/trade_alerts_contracts/test_rs_trend_eligibility.py` plus
`tests/trade_alerts_contracts/test_research_bar_access.py`, confirming both
existing contracts are unchanged (163 passed combined), both exit code 0.
Controller-published protected proof for this milestone follows separately
and supersedes these self-run numbers.

No code path here derives an eligibility gate, a trigger or a structural input;
it only measures one already-adopted return calculation over real, research-
admissible bars. Remaining `HOD_COMP_RS` build-scope (the other seven
`REQUIRED_ROLES` and the two quote gates) and the two other named playbooks'
(`OR_FAILURE_REV`, `FIRST_PULLBACK_VWAP`) adapters entirely remain unbuilt. No
provider call, spend, or live/alert/order action occurred in this session. All
switches stay off.

- [!] **M9.1E — per-playbook raw-bar-to-replay-input adapters (`HOD_COMP_RS`,
  `OR_FAILURE_REV`, `FIRST_PULLBACK_VWAP`):** too large for one session, and
  smaller-grained than the original "one playbook at a time" split anticipated:
  even one playbook (`HOD_COMP_RS`) needs one adapter per bound role. Only the
  `RS`/`RS_WARMUP_COMPLETE` pair is built, as described above. Work continues
  at M9.1F. The two D-104 gaps stay recorded gaps with dependent rules off. No
  provider call or spend occurred.
## M9.1F sub-step — `REFERENCE_EXTREME_COMPLETE`/`COMPRESSION_COMPLETE` research adapter; five roles still open — 2026-09-17 Pacific

Following the same too-large-for-one-session split used for M9.1A-E, this
session narrows M9.1F's named seven-role scope to the one pair that shares a
single already-adopted computation: `REFERENCE_EXTREME_COMPLETE` and
`COMPRESSION_COMPLETE` are both completion flags over `hod_compression.py`'s
one frozen-reference/compression-window measurement, so one adapter covers
both roles, exactly mirroring the M9.1E `RS`/`RS_WARMUP_COMPLETE` pairing.

Read before editing: `consensus_engine/hod_compression.py`,
`consensus_engine/hod_comp_rs_research_adapter.py` (the M9.1E precedent this
session's module structure copies), `consensus_engine/research_bar_access.py`.

New module `consensus_engine/hod_compression_research_adapter.py` adds
`build_hod_compression_snapshot_from_research`, mirroring
`hod_compression.build_hod_compression_snapshot`'s frozen-reference window and
compression-window selection, contiguity, no-trade and instrument-type checks
exactly (same refusal reasons: `REFERENCE_WINDOW_NOT_COVERED`,
`INCOMPLETE_COMPRESSION_WINDOW`, `NO_TRADED_REFERENCE_INTERVAL`,
`NO_TRADED_COMPRESSION_INTERVAL`, `INCOMPATIBLE_*`, ...), but admitting
`PROVISIONAL` intervals as ready in addition to `FINAL`/`NO_TRADE`, and calling
the M9.1D `research_coverage_at` once over the shared minute history to attach
one D-110 label (decision, gap field, final/no-trade/provisional/excluded
counts) to the result. `historical_bars.py` and `hod_compression.py` are
untouched (no code path here modifies a shared production module or its status
ladder). The produced `FeatureSnapshot` carries its own
`RESEARCH_HOD_COMPRESSION_FEATURE_VERSION`/`RESEARCH_HOD_COMPRESSION_DATA_MODE`,
distinct from the live `FEATURE_VERSION`/`DATA_MODE`, so a live `RsTrendPolicy`
binding cannot match it by accident; only a policy that names these research
identifiers explicitly can bind to it for replay.

New offline synthetic test coverage:
`tests/trade_alerts_contracts/test_hod_compression_research_adapter.py`
(13 cases), covering: `PROVISIONAL`-only history producing the same
reference/compression numbers `FINAL` history would (the live function would
refuse this with `REFERENCE_PROVISIONAL`/`COMPRESSION_PROVISIONAL`); the D-110
label naming decision/gap-field/interval counts once for the shared history;
the reference staying frozen and never reading a later bar; an untraded
reference minute and a short/untraded/missing compression window refusing by
the same names as the live function; incompatible/absent history named for
every feature with no label; a closed day and a wrong interval refused by
name; and explicit symbol/instrument-type/policy/freeze-instant validation.
Locally run once through the protected launcher for orientation only (not
protected acceptance evidence): the new file (13 passed) plus the directly
affected `tests/trade_alerts_contracts/test_hod_compression.py`,
`tests/trade_alerts_contracts/test_rs_trend_eligibility.py` and
`tests/trade_alerts_contracts/test_hod_comp_rs_research_adapter.py`, confirming
all three existing contracts are unchanged (193 passed combined), exit code 0.
Controller-published protected proof for this milestone follows separately and
supersedes these self-run numbers.

No code path here derives an eligibility gate, a trigger or a structural input;
it only measures one already-adopted extreme/window computation over real,
research-admissible bars. Remaining `HOD_COMP_RS` build-scope (the five roles
`MEDIAN_DOLLAR_VOLUME`, `RVOL`, `OPEN_RETURN`, `DAILY_ATR_PCT`, `SESSION_VWAP`,
plus the two quote-derived gates, which stay out of this bar-only scope
entirely) and the two other named playbooks' (`OR_FAILURE_REV`,
`FIRST_PULLBACK_VWAP`) adapters entirely remain unbuilt. No provider call,
spend, or live/alert/order action occurred in this session. All switches stay
off.

- [!] **M9.1F — `REFERENCE_EXTREME_COMPLETE`/`COMPRESSION_COMPLETE` research
  adapter:** implemented as described above; the remaining five roles move to
  M9.1G. The two D-104 gaps stay recorded gaps with dependent rules off. No
  provider call or spend occurred. Marked `[!]`, not `[x]`, because this
  milestone handed off with build status `blocked`: its own adapter pair is
  built and proven, but M9.1F's full stated scope is not finished. The
  controller's `roadmap_ok(..., blocked=True)` check requires `[!]` on a
  blocked handoff, exactly as M9.1E above.
## M9.1G — `HOD_COMP_RS` remaining role adapters built — 2026-09-17 Pacific

New module `consensus_engine/hod_comp_rs_role_adapter.py` adds
`build_hod_comp_rs_role_snapshot_from_research`, covering the five remaining
bar-only `RsTrendPolicy` roles in one session: `MEDIAN_DOLLAR_VOLUME`, `RVOL`,
`OPEN_RETURN`, `DAILY_ATR_PCT` and `SESSION_VWAP`. `MEDIAN_DOLLAR_VOLUME`/
`RVOL` mirror `participation_features._calculate`'s "daily"/"opening" window
selection exactly (same required-slot, symbol, interval, unit and mode checks,
same median-of-20/ratio-of-20 arithmetic); `OPEN_RETURN`/`SESSION_VWAP` mirror
`core_price_features`'s `_opening`/`_session` window selection the same way.
Every one admits a `PROVISIONAL` interval as ready where the live function
stops at `FINAL`/`NO_TRADE`, through `research_bar_access.research_coverage_at`
(D-110), exactly following the M9.1E/M9.1F precedent. `participation_features.py`
and `core_price_features.py` are untouched (no code path here modifies a
shared production module or its status ladder).

As named in the prior M9.1G row, `core_price_features.py`'s
`DAILY_ATR_14_SMA_V1` is `USD_PER_SHARE`, not the bound `DAILY_ATR_PCT` role's
implied ratio unit. This session's explicit derivation divides that mirrored
daily ATR by the prior regular-session close (the same prior-close computation
`core_price_features._daily`/`_opening` already use for `GAP_OPEN_V1`), not a
direct USD pass-through. The other four roles' units already matched their
live counterparts and needed no derivation.

Every result carries one D-110 label per supplied history side
(`opening_history`, `daily_history`, `minute_history`). The produced
`FeatureSnapshot` carries its own `RESEARCH_ROLE_FEATURE_VERSION`/
`RESEARCH_ROLE_DATA_MODE`, distinct from the live D-090 versions/modes, so a
live `RsTrendPolicy` binding cannot match it by accident; only a policy that
names these research identifiers explicitly can bind to it for replay.

New offline synthetic test coverage:
`tests/trade_alerts_contracts/test_hod_comp_rs_role_adapter.py` (10 cases),
covering: hand-computed values for all five roles from already-`FINAL` history;
the same values from all-`PROVISIONAL` history (the live functions would
refuse this); the D-110 label naming decision/gap-field/interval counts on
each of the three supplied history sides; the `DAILY_ATR_PCT` price
normalization against the live USD figure; each role's own missing-history
reason when a side is absent; a quiet certified-no-trade reference day
contributing zero volume without blocking (matching the live function); a
dropped reference day staying incomplete rather than shortened; incompatible
symbol/instrument-type refusals by name; and explicit symbol/instrument-type
validation. Run once through the protected launcher together with the three
directly affected existing contracts
(`tests/trade_alerts_contracts/test_hod_comp_rs_role_adapter.py`,
`tests/trade_alerts_contracts/test_participation_features.py`,
`tests/trade_alerts_contracts/test_core_price_features.py`,
`tests/trade_alerts_contracts/test_rs_trend_eligibility.py`), confirming all
three existing contracts are unchanged: 267 passed, exit code 0. This was a
self-run orientation pass only, not protected acceptance evidence; the
controller's own published protected proof for this milestone follows
separately and supersedes these numbers.

The two quote-derived gates (`QUOTE_ACTIONABLE`, `SPREAD_BPS`) still need real
quote data, separate from `core17_bar_loader`/`databento_minute_bars` records,
and stay out of this bar-only adapter's scope entirely. No code path here
derives an eligibility gate, a trigger or a structural input; it only measures
five already-adopted bar computations over real, research-admissible bars. No
provider call, spend, or live/alert/order action occurred in this session. All
switches stay off.

- [x] **M9.1G — `HOD_COMP_RS` remaining role adapters (`MEDIAN_DOLLAR_VOLUME`,
  `RVOL`, `OPEN_RETURN`, `DAILY_ATR_PCT`, `SESSION_VWAP`):** implemented as
  described above; all five roles built in this one session, so this
  milestone's own stated scope is complete. Every `HOD_COMP_RS` role
  (`RS`/`RS_WARMUP_COMPLETE` from M9.1E, `REFERENCE_EXTREME_COMPLETE`/
  `COMPRESSION_COMPLETE` from M9.1F, and these five from M9.1G) now has a
  research adapter; only the two quote-derived gates remain, and they need
  real quote data outside this bar-only scope. `OR_FAILURE_REV` and
  `FIRST_PULLBACK_VWAP` adapters remain fully open, so the reopened parent
  `M9.1 — Historical replay #1-4` is still not complete; work continues at
  M9.1H. The two D-104 gaps stay recorded gaps with dependent rules off. No
  provider call or spend occurred.
## M9.1H — `OR_FAILURE_REV` tape/minute-close bar adapter built — 2026-09-17 Pacific

`HOD_COMP_RS` now has every bar-only role adapter M9.1E-G built; this session
starts `OR_FAILURE_REV`'s own adapter chain. `OrFailureRevMachine`
(`consensus_engine/or_failure_rev.py`) needs a supplied `Observation` (the tape
read `LAST_BACK_INSIDE_RANGE`/`DISPLACEMENT_FROM_EDGE` use) and a supplied
`MinuteClose` (the mandatory-arm confirmation read `FAILURE_CONFIRMATION`
uses) at each evaluation instant; those are the two inputs this session's new
module, `consensus_engine/or_failure_rev_research_adapter.py`
(`build_or_failure_rev_bar_inputs_from_research`), derives from real minute
bars, exactly mirroring the M9.1E/F/G PROVISIONAL-admitting pattern: the same
`historical_bars.HistoryBatch.coverage_at` revision/interval-status selection
the live callers already assume, with `research_bar_access.research_coverage_at`
(D-110) admitting a `PROVISIONAL` interval as ready where a real tape/quote
feed would never have produced one. The selected bar is the most recently
ended real minute interval at or before `evaluated_at`; that one bar's close
stands for both the tape print and the minute close, exactly as a real
single-arm feed reporting the current minute would. Every `record_id` this
module produces names its own `RESEARCH_OR_FAILURE_REV_V1` origin plus the
source bar's own record ID, so it cannot be mistaken for a live tape/quote
record. `orb5_trigger.py`, `or_failure_rev.py` and `or_failure_handoff.py` are
untouched.

The remaining `OR_FAILURE_REV` inputs -- `FailureBar` (needs the M8.1
breakout-extreme chain to identify which bar is "the" failure bar, not just
the latest one), `InsideAcceptance`, the quote decision, the structural risk
reading, and the M8.1 `HandoffAssessment`/`BreakoutExtreme` chain this reversal
consumes -- still need their own real-data adapters and stay open build-scope
for a later M9.1H sub-step; `FIRST_PULLBACK_VWAP` remains fully unbuilt after
this session, per the same one-playbook/one-sub-step-at-a-time split M9.1D-G
used.

New offline synthetic test coverage:
`tests/trade_alerts_contracts/test_or_failure_rev_research_adapter.py` (10
cases), covering: the latest-ended bar supplying both the tape read and the
minute close identically; `PROVISIONAL` bars usable here exactly as already-
`FINAL` ones, each correctly labelled by count; evaluating before any bar has
ended yet finding nothing ready; a certified no-trade bar reporting
`NO_TRADE_AT_LATEST_BAR` rather than a stale or invented price; a bar missing
from history falling back to the prior ready bar rather than inventing one;
absent minute history and an incompatible symbol/interval/unit/venue basis
each refused by name with no label produced; an incompatible instrument type
on the otherwise-selected bar refused by name; and explicit
record-ID-prefix/instrument-type validation. Run once through the protected
launcher together with `tests/trade_alerts_contracts/test_orb5_trigger.py` and
`tests/trade_alerts_contracts/test_historical_bars.py`, confirming both
existing contracts are unchanged: 304 passed, exit code 0. This was a
self-run orientation pass only, not protected acceptance evidence; the
controller's own published protected proof for this milestone follows
separately and supersedes these numbers.

No code path here derives a gate, a trigger, an alert or a live consumable
input: it only measures one bar-native tape/close pair over real,
research-admissible bars. No provider call, spend, or live/alert/order action
occurred in this session. All switches stay off.

- [x] **M9.1H — `OR_FAILURE_REV` tape/minute-close bar adapter:** implemented
  as described above; the tape-read/minute-close pair is built and proven, but
  `OR_FAILURE_REV`'s full stated input set is not finished and
  `FIRST_PULLBACK_VWAP` remains fully open, so the reopened parent
  `M9.1 — Historical replay #1-4` is still not complete; work continues at
  M9.1I. The two D-104 gaps stay recorded gaps with dependent rules off. No
  provider call or spend occurred.
## M9.1I — `OR_FAILURE_REV` breakout-extreme/failure-bar adapter built — 2026-09-17 Pacific

`OR_FAILURE_REV` now has its tape-read/minute-close pair from M9.1H; this
session adds the M8.1 `BreakoutExtreme` (`consensus_engine/or_failure_handoff.py`)
and the M8.2 `FailureBar` (`consensus_engine/or_failure_rev.py`), extended into
the existing `consensus_engine/or_failure_rev_research_adapter.py` module
(`build_or_failure_rev_extreme_inputs_from_research`) rather than a new file,
since it shares the same D-110 `research_coverage_at`/`HistoryBatch.coverage_at`
basis-checking helpers M9.1H already built there.

PLAYBOOKS section 5 names the stronger trigger as "below failure-bar low" for a
failed upside break; the failure bar is the real minute bar that produced the
break's own furthest traded price since it crossed the opening range, and its
opposite side (not a second bar's price) is the stronger-trigger level. So one
bar is identified per evaluation -- the ready interval, among every one ending
strictly after the supplied `crossed_at` and at or before `evaluated_at`, whose
high is furthest out for a failed upside break or whose low is furthest out for
a failed downside break -- and both `BreakoutExtreme.price` and
`FailureBar.high`/`FailureBar.low` are read from that one bar, exactly
mirroring the M9.1H PROVISIONAL-admitting, incompatible-basis-refusing pattern.
A certified no-trade bar has no usable high/low and is excluded from the
search rather than read as a zero excursion. `or_failure_handoff.py` and
`or_failure_rev.py` are untouched; `orb5_trigger.py` and `orb5_replay.py` are
also untouched.

The remaining `OR_FAILURE_REV` inputs -- `InsideAcceptance`, the quote decision,
the structural risk reading, and the M8.1 `HandoffAssessment` chain around this
pair -- still need their own real-data adapters and stay open build-scope for a
further M9.1 sub-step; `FIRST_PULLBACK_VWAP` remains fully unbuilt after this
session, per the same one-playbook/one-sub-step-at-a-time split M9.1D-H used.

New offline synthetic test coverage (appended to
`tests/trade_alerts_contracts/test_or_failure_rev_research_adapter.py`, which
already held the M9.1H cases): 10 new cases, covering: a failed upside break
taking its extreme from the bar with the furthest high; a failed downside break
taking its extreme from the bar with the furthest low; bars at or before the
crossing excluded from the search; no ready bar since the crossing reporting a
pending (not lost) extreme; missing minute history and an incompatible
symbol/interval/unit/venue basis each refused by name with no label produced;
an incompatible instrument type on the otherwise-selected bar refused by name;
a certified no-trade bar excluded from the extreme search; `PROVISIONAL` bars
usable here exactly as already-`FINAL` ones; and the crossing-after-evaluation
and unsupported-direction input checks. Run once through the protected
launcher together with `tests/trade_alerts_contracts/test_or_failure_rev.py`
and `tests/trade_alerts_contracts/test_or_failure_handoff.py`, confirming both
existing contracts are unchanged: 300 passed, exit code 0. This was a
self-run orientation pass only, not protected acceptance evidence; the
controller's own published protected proof for this milestone follows
separately and supersedes these numbers.

No code path here derives a gate, a trigger, an alert or a live consumable
input: it only identifies one bar-native extreme/failure-bar pair over real,
research-admissible bars. No provider call, spend, or live/alert/order action
occurred in this session. All switches stay off.

- [!] **M9.1I — `OR_FAILURE_REV` breakout-extreme/failure-bar adapter:**
  implemented as described above; the extreme/failure-bar pair is built and
  proven, but `OR_FAILURE_REV`'s full stated input set is not finished and
  `FIRST_PULLBACK_VWAP` remains fully open, so the reopened parent
  `M9.1 — Historical replay #1-4` is still not complete; work continues at
  M9.1J. The two D-104 gaps stay recorded gaps with dependent rules off. No
  provider call or spend occurred.
## M9.1J — `OR_FAILURE_REV` `InsideAcceptance` adapter built — 2026-09-17 Pacific

`OrFailureRevMachine` now has its tape/close pair (M9.1H) and its extreme/
failure-bar pair (M9.1I); this session adds the `INSIDE_ACCEPTANCE` gate's own
`InsideAcceptance` (`consensus_engine/or_failure_rev.py`), extended into the
existing `consensus_engine/or_failure_rev_research_adapter.py` module
(`build_or_failure_rev_acceptance_from_research`) rather than a new file, since
it reuses the same D-110 `research_coverage_at`/basis-checking helpers M9.1H/I
already built there.

PLAYBOOKS section 13 leaves "the inside-acceptance window" itself unresolved,
and M0.3B is PROPOSED, so this adapter adopts no window of its own: the caller
supplies `window_start`/`window_end` exactly as it already supplies every other
`ReversalPolicy` threshold, and this only computes the real bar-native share of
that caller-named window spent with a bar's close strictly inside the supplied
opening-range edges. A certified no-trade or wrong-instrument-type bar inside
the window is excluded from the share (mirroring the M9.1I failure-bar
exclusion) and breaks `coverage_complete` rather than being read as a covered
minute; a window not yet fully elapsed reports a real partial share marked
incomplete rather than an invented final one.

The remaining `OR_FAILURE_REV` inputs -- the quote decision and the structural
risk reading -- and the M8.1 handoff chain's own real-data adapter still need
their own real-data adapters and stay open build-scope for a further M9.1
sub-step; `FIRST_PULLBACK_VWAP` remains fully unbuilt after this session, per
the same one-playbook/one-sub-step-at-a-time split M9.1D-I used.

New offline synthetic test coverage (appended to
`tests/trade_alerts_contracts/test_or_failure_rev_research_adapter.py`, which
already held the M9.1H/M9.1I cases): 10 new cases, covering: the full-window
real share of bars closing back inside the range; `PROVISIONAL` bars usable
here exactly as already-`FINAL` ones; a window not yet fully elapsed reporting
a real partial share marked incomplete; a window that has not started yet; a
window with no ready bar; missing minute history and an incompatible symbol
each refused by name with no label produced; an incompatible instrument type
breaking the whole window's coverage; a certified no-trade bar leaving a
coverage hole while still sharing the rest; and the window-must-have-positive-
duration/range-ordering/instrument-type input checks. Run once through the
protected launcher together with `tests/trade_alerts_contracts/test_or_failure_rev.py`
and `tests/trade_alerts_contracts/test_or_failure_handoff.py`, confirming both
existing contracts are unchanged: 310 passed, exit code 0. This was a
self-run orientation pass only, not protected acceptance evidence; the
controller's own published protected proof for this milestone follows
separately and supersedes these numbers.

No code path here derives a gate, a trigger, an alert or a live consumable
input: it only computes one bar-native share over real, research-admissible
bars within a window the caller names. No provider call, spend, or live/alert/
order action occurred in this session. All switches stay off.

- [!] **M9.1J — `OR_FAILURE_REV` `InsideAcceptance` adapter:** implemented as
  described above; the acceptance share is built and proven, but
  `OR_FAILURE_REV`'s full stated input set is not finished (the quote decision,
  the structural risk reading and the M8.1 handoff chain's own real-data
  adapter remain open) and `FIRST_PULLBACK_VWAP` remains fully open, so the
  reopened parent `M9.1 — Historical replay #1-4` is still not complete; work
  continues at M9.1K. The two D-104 gaps stay recorded gaps with dependent
  rules off. No provider call or spend occurred.
## M9.1K — `OR_FAILURE_REV` `ReversalStructural` stop/target adapter built — 2026-09-17 Pacific

`OrFailureRevMachine` now has its tape/close pair (M9.1H), its extreme/failure-
bar pair (M9.1I) and its `InsideAcceptance` share (M9.1J); this session adds
the `RISK_TARGETS` gate's own `ReversalStructural` reading, extended into the
existing `consensus_engine/or_failure_rev_research_adapter.py` module
(`build_or_failure_rev_structural_from_research`), reusing the same D-110
`research_coverage_at`/basis-checking helpers M9.1H-J already built there.

PLAYBOOKS section 17 incorporates the frozen `M0_3D_DEFINITION_PACKET.md`
section 6 rule this adapter implements exactly: the raw stop is the breakout
extreme moved `0.05 * frozen_ATR_1m` further from entry, rounded outward (up
for a short reversal, down for a long one) to the caller-supplied price
increment; the target catalog is built from the frozen opening-range midpoint,
the selected as-of session VWAP measured here from real minute bars up to
`evaluated_at` (summed `hlc3 * volume` over every ready traded bar since the
session open, admitting `PROVISIONAL` through D-110 exactly like the M9.1H/I/J
reads), and the opposite opening-range edge; T1 is the nearest admitted level
at least 1.5R ahead of entry, T2 the nearest distinct level beyond it at least
2.5R ahead. `entry_reference` and `breakout_extreme_price` are supplied facts
from their own producers (the M0.3A entry search and the M9.1I extreme); this
adapter only measures the geometry those facts and real bars imply. Per D-104,
an unknown price increment or an unavailable breakout extreme leaves the whole
stop unavailable by name (`PRICE_INCREMENT_UNKNOWN`/`BREAKOUT_EXTREME_UNAVAILABLE`)
rather than approximated, and a VWAP-incomplete catalog leaves the stop
standing with an empty `targets` tuple, which the existing `RISK_TARGETS` gate
in `or_failure_rev.py` already reads as `GEOMETRY_TARGETS_UNAVAILABLE` -- no gate
code changed. `consensus_engine/or_failure_rev.py`, `or_failure_handoff.py` and
`orb5_trigger.py` are untouched.

The remaining `OR_FAILURE_REV` input -- the quote decision (`QuoteEventDecision`
needs a real bid/ask quote stream this project has no source for, so it cannot
be derived from bar-only history at all, unlike every other M9.1H-K input) --
and the M8.1 handoff chain's own real-data adapter still need their own
producers and stay open build-scope for a further M9.1 sub-step;
`FIRST_PULLBACK_VWAP` remains fully unbuilt after this session, per the same
one-playbook/one-sub-step-at-a-time split M9.1D-J used.

New offline synthetic test coverage (appended to
`tests/trade_alerts_contracts/test_or_failure_rev_research_adapter.py`, which
already held the M9.1H/I/J cases): 11 new cases, covering: a long reversal's
stop as the downside extreme minus the ATR pad; a long reversal finding the
VWAP target first then the opposite edge as T2; a short reversal's stop as the
upside extreme plus the ATR pad; outward rounding (down for long, up for
short) at a coarse 0.25 increment; an unavailable breakout extreme and an
unknown price increment each leaving risk unavailable by its own name rather
than approximated; a stop on the wrong side of entry reported as
`INVALID_STOP_GEOMETRY` rather than a negative risk figure; missing/
incompatible minute history each still supplying the stop but leaving the
target catalog empty; no traded bar yet leaving the catalog incomplete; and
the direction/range-ordering input checks. Run once through the protected
launcher together with `tests/trade_alerts_contracts/test_or_failure_rev.py`
and `tests/trade_alerts_contracts/test_or_failure_handoff.py`, confirming both
existing contracts are unchanged: 321 passed, exit code 0. This was a
self-run orientation pass only, not protected acceptance evidence; the
controller's own published protected proof for this milestone follows
separately and supersedes these numbers.

No code path here derives a gate, a trigger, an alert or a live consumable
input: it only measures one bar-native stop/target geometry over real,
research-admissible bars and caller-supplied facts. No provider call, spend,
or live/alert/order action occurred in this session. All switches stay off.

- [!] **M9.1K — `OR_FAILURE_REV` `ReversalStructural` stop/target adapter:**
  implemented as described above; the stop/target geometry is built and
  proven, but `OR_FAILURE_REV`'s quote decision cannot be derived from
  bar-only history at all (it needs a real bid/ask quote stream this project
  has no source for) and the M8.1 handoff chain's own real-data adapter
  remains open, and `FIRST_PULLBACK_VWAP` remains fully open, so the reopened
  parent `M9.1 — Historical replay #1-4` is still not complete; work continues
  at M9.1L. The two D-104 gaps stay recorded gaps with dependent rules off. No
  provider call or spend occurred.
## M9.1L — the M8.1 handoff chain's own real-data opening range built — 2026-09-17 Pacific

`OrFailureHandoffMachine`'s `HandoffRequest` (`consensus_engine/or_failure_handoff.py`)
needs three bar-native supplied facts: `breakout_extreme` and `minute_close`,
already built from real bars by M9.1I/M9.1H, and `opening_range` -- the M3.6
`FeatureSnapshot` its `RANGE_GATE` checks by exact `feature_version` match. The
live builder, `opening_range_features.build_opening_range_snapshot`, only
admits `FINAL`/`NO_TRADE` bars, and M9.1D already found Databento history is
permanently `PROVISIONAL` for this project, so it can never complete from real
data. This session adds the missing piece: new module
`consensus_engine/or_failure_handoff_research_adapter.py`
(`build_or_failure_handoff_opening_range_from_research`), mirroring the M9.1D
research-bar-accessor precedent M9.1E-K already used -- it reuses
`build_opening_range_snapshot`'s exact five-minute high/low/mid/width
definition, `FEATURE_VERSION` and revision-selection/conflict logic unchanged,
only replacing its `HistoryBatch.coverage_at` call with `research_bar_access.
research_coverage_at`'s D-110 `PROVISIONAL`-admitting view. The produced
`FeatureSnapshot.feature_version` stays exactly the live
`OPENING_RANGE_VERSION`, since the underlying definition is identical and only
the finality admission differs, so `RANGE_GATE`'s version check binds to it
directly; the research provenance is carried in `metadata.data_mode`
(`RESEARCH_BAR_OPENING_RANGE_V1`) and the returned D-110 label, not a second
version. Combined with the existing M9.1H/M9.1I reads, a `HandoffRequest` can
now be built entirely from real bars for the first time; only the
caller-supplied `TriggerAssessment` (the M6.2 attempt) and `HandoffPolicy`
(the caller's own unresolved-rule thresholds) remain outside this module's
scope, exactly as they already are for a live caller. `OR_FAILURE_REV`'s one
remaining gap -- the quote decision -- still needs a real bid/ask quote source
this project does not have, so it stays not buildable offline; no change was
made there.

New offline synthetic test coverage
(`tests/trade_alerts_contracts/test_or_failure_handoff_research_adapter.py`,
new file): 18 cases, covering: final and `PROVISIONAL` bars both reaching the
live `feature_version` and completing the range (proving the live builder's
own `OPENING_RANGE_PROVISIONAL` block is the only thing that changed); the
range-not-yet-ended, certified-no-trade, all-no-trade, conflicting/overlapping,
missing-history, wrong-symbol, wrong-instrument-type, holiday and
explicit-input-validation cases mirrored from the M3.6 `test_opening_range_
features.py` suite; a same-selected-bar check that the new module's close/
extreme reads agree with the existing M9.1H/M9.1I builders; and one true
end-to-end integration reusing the M8.1 fixture helpers unchanged (`attempt`/
`policy`/`extreme`/`reacceptance` from `test_or_failure_handoff.py`) with only
the live `opening_range()` builder swapped for this module's research one,
forcing all five opening bars `PROVISIONAL`, and asserting `evaluate_or_
failure_handoff` still reaches `RANGE_GATE` `PASS` and `FAILURE_FORMING`,
exactly as the live-bar fixture already proves elsewhere in that file. A
recording case following the M3.6 precedent writes a hash-compared JSON proof
to `/tmp/m91l-or-failure-handoff-opening-range-proof.json`. Run once through
the protected launcher together with `test_or_failure_handoff.py`,
`test_opening_range_features.py`, `test_or_failure_rev_research_adapter.py`
and `test_or_failure_rev.py`, confirming every existing contract is unchanged:
363 passed, exit code 0. This was a self-run orientation pass only, not
protected acceptance evidence; the controller's own published protected proof
for this milestone follows separately and supersedes these numbers.

No code path here derives a gate, a trigger, an alert or a live consumable
input beyond the one M8.1 `RANGE_GATE` this proves compatibility with: it only
builds one bar-native `FeatureSnapshot` over real, research-admissible bars.
No provider call, spend, or live/alert/order action occurred in this session.
All switches stay off.

- [!] **M9.1L — the M8.1 handoff chain's own real-data opening range:**
  implemented as described above; the handoff's `HandoffRequest` can now be
  built entirely from real bars (`opening_range`, `breakout_extreme` and
  `minute_close` all have research adapters), but `OR_FAILURE_REV`'s quote
  decision still cannot be derived from bar-only history at all, and
  `FIRST_PULLBACK_VWAP` remains fully unbuilt, so the reopened parent
  `M9.1 — Historical replay #1-4` is still not complete; work continues at
  M9.1M. The two D-104 gaps stay recorded gaps with dependent rules off. No
  provider call or spend occurred.
- [ ] **M9.1M — `FIRST_PULLBACK_VWAP`'s first bar-native input:** proposed next
  milestone. `OR_FAILURE_REV` now has every bar-native input it can ever have
  offline (the quote decision needs a real bid/ask quote source this project
  does not have); `FIRST_PULLBACK_VWAP` remains fully unbuilt. Read
  `consensus_engine/first_pullback_vwap.py`'s own input set before choosing
  where to start; one sub-step at a time if a single session cannot fit the
  whole remaining scope, per the same split M9.1D-L used. The two D-104 gaps
  stay recorded gaps with dependent rules off. Independent review must confirm
  eligibility before the controller advances.

## M9.1M — `FIRST_PULLBACK_VWAP`'s first bar-native input: research impulse/pullback measurement — 2026-09-18 Pacific

`OR_FAILURE_REV` has every bar-native input it can ever have offline (M9.1H-L);
`FIRST_PULLBACK_VWAP` (`consensus_engine/first_pullback_vwap.py`) remained fully
unbuilt. Its `PullbackRequest.measurement` is the M8.3 `FeatureSnapshot`
`impulse_pullback.build_impulse_pullback_snapshot` produces, and that builder
only admits `FINAL`/`NO_TRADE` minutes -- the same permanently-`PROVISIONAL`
Databento block M9.1D already found. This session adds the first
`FIRST_PULLBACK_VWAP` sub-step: new module
`consensus_engine/impulse_pullback_research_adapter.py`
(`build_impulse_pullback_snapshot_from_research`), mirroring
`impulse_pullback.py`'s own window-selection, freeze, ordering, retracement,
volume-ratio and VWAP-distance arithmetic exactly, with one change: readiness
admits `PROVISIONAL` alongside `FINAL`/`NO_TRADE` through D-110's
`research_bar_access.research_coverage_at`, exactly the M9.1E precedent already
used for `HOD_COMP_RS`'s `RsTrendPolicy` inputs. `atr_1m` and `vwap` stay
caller-supplied scalars unchanged, since deriving either from bars is not part
of this sub-step's scope.

The produced `FeatureSnapshot` uses its own `RESEARCH_IMPULSE_PULLBACK_
FEATURE_VERSION`/`RESEARCH_IMPULSE_PULLBACK_DATA_MODE`, distinct from
`impulse_pullback.FEATURE_VERSION`/`DATA_MODE`, because
`first_pullback_vwap._measurement`'s `MEASUREMENT_GATE` checks both the
feature version and the data mode strictly (unlike `OR_FAILURE_REV`'s
`RANGE_GATE`, which only checks the feature version), so a live
`PullbackRequest` cannot bind to this research output by accident -- exactly
the M9.1E `RS`-snapshot rationale, not the M9.1L opening-range rationale. No
matcher or policy binding this research version into `PullbackRequest.measurement`
exists yet; that remains open build-scope for a further sub-step, along with
the rest of `FIRST_PULLBACK_VWAP`'s input set (VWAP context, relative
strength, the last-trade observation, the quote decision -- which needs a real
bid/ask quote source this project does not have -- the structural stop/target
and the M4.4 confidence). `impulse_pullback.py` and `first_pullback_vwap.py`
are both untouched.

New offline synthetic test coverage
(`tests/trade_alerts_contracts/test_impulse_pullback_research_adapter.py`, new
file): 13 cases, covering: `PROVISIONAL` bars usable here exactly as
already-`FINAL` ones, with the distinct research feature version/data mode
confirmed different from the live ones; the D-110 label naming the
provisional/final interval counts; a later high never moving the frozen
impulse; an unready/untraded/wrong-instrument-type/missing impulse minute each
still refused by their own live-mirrored name; a missing or no-trade pullback
minute refused the same way; missing history, wrong symbol and unknown-basis
cases named for every feature with no D-110 label produced; the daily-interval
and holiday refusals; and the symbol/instrument-type/policy input checks. A
recording case writes a hash-compared JSON proof to
`/tmp/m91m-impulse-pullback-research-proof.json`. Run once through the
protected launcher together with `test_impulse_pullback.py`,
`test_first_pullback_vwap.py` and `test_first_pullback_vwap_replay.py`,
confirming every existing contract is unchanged: 266 passed, exit code 0. This
was a self-run orientation pass only, not protected acceptance evidence; the
controller's own published protected proof for this milestone follows
separately and supersedes these numbers.

No code path here derives a gate, a trigger, an alert or a live consumable
input: it only measures one bar-native impulse/pullback leg over real,
research-admissible bars. No provider call, spend, or live/alert/order action
occurred in this session. All switches stay off.

- [!] **M9.1M — `FIRST_PULLBACK_VWAP`'s first bar-native input:** implemented as
  described above; the research impulse/pullback measurement is built and
  proven, but nothing yet binds it into `PullbackRequest.measurement`, and
  `FIRST_PULLBACK_VWAP`'s remaining inputs (VWAP context, relative strength,
  last trade, quote decision, structural stop/target, confidence) are still
  open, so the reopened parent `M9.1 — Historical replay #1-4` is still not
  complete; work continues at M9.1N. The two D-104 gaps stay recorded gaps
  with dependent rules off. No provider call or spend occurred.
## M9.1N sub-step — `FIRST_PULLBACK_VWAP`'s relative-strength input built; the rest still open — 2026-09-18 Pacific

Following the same too-large-for-one-session split used for M9.1A-M, this
session narrows M9.1N's named scope to one input:
`PullbackRequest.relative_strength` (`first_pullback_vwap.RelativeStrength`).
`rs_trend_eligibility.RsWindowPolicy` already names the exact stock-return-
minus-benchmark-return computation with no adopted number of its own -- "Nothing
here adopts a number", per that module's own docstring -- and M9.1E's
`hod_comp_rs_research_adapter.build_rs_trend_snapshot_from_research` already
computes it from real, `PROVISIONAL`-admissible bars for `HOD_COMP_RS`. That
computation is entirely the caller's own supplied `RsWindowPolicy` applied to
two supplied `HistoryBatch`es, so it is playbook-neutral; nothing about it is
specific to `HOD_COMP_RS`.

New module `consensus_engine/first_pullback_vwap_research_adapter.py`
(`build_relative_strength_from_research`) reuses that M9.1E computation
unchanged and reshapes its `RS_LOOKBACK_V1` value and reason into a
`first_pullback_vwap.RelativeStrength` record instead of a `FeatureSnapshot`.
`coverage_complete` is true exactly when both the stock's and the benchmark's
own bar coverage were computed at all (a compatible history was supplied and a
regular session existed), independent of whether the RS value itself could be
measured yet (for example, before warm-up); a value that could not be measured
always carries its own named reason instead, exactly mirroring
`RelativeStrength.__post_init__`'s own "missing value needs a missing reason"
rule. `first_pullback_vwap.py`, `impulse_pullback_research_adapter.py` and
`hod_comp_rs_research_adapter.py` are all untouched.

Binding the M9.1M research measurement into a usable `PullbackRequest`, the
VWAP context, the last-trade observation and the structural stop/target all
remain open build-scope for a further M9.1 sub-step; the quote decision needs a
real bid/ask quote source this project does not have and stays out of scope,
exactly like `OR_FAILURE_REV`'s own.

New offline synthetic test coverage
(`tests/trade_alerts_contracts/test_first_pullback_vwap_research_adapter.py`,
new file): 8 cases, covering: `PROVISIONAL` bars reading the same value as
already-`FINAL` ones; warm-up-incomplete coverage staying complete with an
absent value and its own named reason; a missing benchmark or stock history
each read as incomplete coverage with its own named reason; no regular session
read as incomplete coverage; a quiet no-trade interval refused by name with
coverage still complete; the record ID requirement; and the result standing as
a valid `RelativeStrength` record under its own `__post_init__` contract. Run
once through the protected launcher together with `test_hod_comp_rs_research_
adapter.py`, `test_impulse_pullback_research_adapter.py`,
`test_first_pullback_vwap.py` and `test_first_pullback_vwap_replay.py`,
confirming every existing contract is unchanged: 253 passed, exit code 0. This
was a self-run orientation pass only, not protected acceptance evidence; the
controller's own published protected proof for this milestone follows
separately and supersedes these numbers.

No code path here derives a gate, a trigger, an alert or a live consumable
input on its own: it only measures one bar-native relative-strength reading
over real, research-admissible bars, in the same shape a later sub-step's
`PullbackRequest` will need. No provider call, spend, or live/alert/order
action occurred in this session. All switches stay off.

- [!] **M9.1N — `FIRST_PULLBACK_VWAP`'s relative-strength input:** implemented
  as described above; the research relative-strength reading is built and
  proven, but binding the M9.1M measurement into a usable `PullbackRequest` and
  `FIRST_PULLBACK_VWAP`'s remaining inputs (VWAP context, last trade,
  structural stop/target) are still open, so the reopened parent
  `M9.1 — Historical replay #1-4` is still not complete; work continues at
  M9.1O. The two D-104 gaps stay recorded gaps with dependent rules off. No
  provider call or spend occurred.
## M9.1O sub-step — the M9.1M/M9.1N readings bound into a usable `PullbackRequest`; the rest still open — 2026-09-18 Pacific

Following the same too-large-for-one-session split used for M9.1A-N, this
session narrows M9.1O's named scope to the first named piece: binding the
M9.1M research impulse/pullback measurement and the M9.1N research relative-
strength reading into one usable `first_pullback_vwap.PullbackRequest`.
Neither `impulse_pullback_research_adapter.py` nor
`first_pullback_vwap_research_adapter.py` assembles a `PullbackRequest`
itself, exactly like `or_failure_handoff_research_adapter.py`/M9.1L left
`HandoffRequest` assembly to the caller (`test_or_failure_handoff_research_
adapter.py`'s own `test_the_produced_snapshot_binds_the_real_m81_range_gate_
end_to_end`); this session adds that same caller-side assembly for
`FIRST_PULLBACK_VWAP` and no new production module, since none is needed.

New offline synthetic test coverage
(`tests/trade_alerts_contracts/test_first_pullback_vwap_request_research_
binding.py`, new file): 9 cases proving the two readings actually fit
`PullbackRequest`'s own contract and documenting exactly what each does and
does not bind to the live gates. `impulse_pullback_research_adapter.py`'s own
docstring deliberately gives its snapshot a distinct `feature_version`/
`data_mode` so `first_pullback_vwap._measurement` can never bind it by
accident (unlike M9.1L's opening-range research, which kept the live
`feature_version` unchanged); this session's own case confirms `MEASUREMENT_
GATE` stays `UNKNOWN` with `MEASUREMENT_VERSION_MISMATCH` here, by design, not
a false `PASS`. `RelativeStrength` carries no version check in `first_
pullback_vwap._relative_strength`, so the M9.1N reading binds and evaluates
genuinely: cases cover a real-bar reading passing `RS_GATE` against a low
supplied minimum, the same reading failing against a higher one,
`PROVISIONAL` bars binding the live gate exactly like `FINAL` ones,
before-warm-up and missing-benchmark readings surfacing their own named
reason on the live gate, confirmation that no combination here reaches
`ALERT_TRIGGERED` (the remaining unsupplied inputs keep it out of reach), and
that `measurement`/`relative_strength` must still be their own canonical
records. Run once through the protected launcher together with
`test_first_pullback_vwap_research_adapter.py`, `test_impulse_pullback_
research_adapter.py` and `test_first_pullback_vwap.py`, confirming every
existing contract is unchanged: 216 passed, exit code 0. This was a self-run
orientation pass only, not protected acceptance evidence; the controller's own
published protected proof for this milestone follows separately and
supersedes these numbers.

VWAP context, the last-trade observation, the quote decision, the structural
stop/target and the M4.4 confidence all still need their own real-bar
producers and remain open build-scope for a further M9.1 sub-step; the quote
decision needs a real bid/ask quote source this project does not have and
stays out of scope, exactly like `OR_FAILURE_REV`'s own.

No code path here derives a gate, a trigger, an alert or a live consumable
input on its own: `MEASUREMENT_GATE` and every other unsupplied gate stay
`UNKNOWN`, and the assembled request never reaches `ALERT_TRIGGERED`. No
provider call, spend, or live/alert/order action occurred in this session. All
switches stay off.

- [!] **M9.1O — `FIRST_PULLBACK_VWAP`'s remaining bar-native inputs:**
  implemented as described above; the M9.1M measurement and M9.1N
  relative-strength reading are bound into a usable `PullbackRequest` and
  proven, but the VWAP context, the last-trade observation, the structural
  stop/target, the quote decision and the M4.4 confidence are still open, so
  the reopened parent `M9.1 — Historical replay #1-4` is still not complete;
  work continues at M9.1P. The two D-104 gaps stay recorded gaps with
  dependent rules off. No provider call or spend occurred.
## M9.1P — `FIRST_PULLBACK_VWAP`'s VWAP context and last-trade observation built — 2026-09-18 Pacific

Following the same split used for M9.1D-O, this session builds the two named
bar-native inputs `first_pullback_vwap.py`'s `PullbackRequest.vwap`/
`last_trade` still needed. `first_pullback_vwap_research_adapter.py` (the
M9.1N module) gains two new functions rather than a new file, since both
reuse that module's existing D-110/basis-check conventions directly.

`build_last_trade_from_research` reproduces the M9.1H
`OrFailureRevBarInputs` tape-read pattern exactly (newest ready bar at or
before `evaluated_at`, `PROVISIONAL` admitted through D-110), producing only
the `Observation` half of that pair since `FIRST_PULLBACK_VWAP` has no
`MinuteClose`-shaped input; the observation always carries `mode=TAPE`.

`build_vwap_context_from_research` computes the real, volume-weighted
`hlc3`-average VWAP level over every ready traded bar from the regular
session open through `evaluated_at`, the same computation
`or_failure_rev_research_adapter._session_vwap` already uses for
`OR_FAILURE_REV`'s own structural target catalog (M9.1K), admitting
`PROVISIONAL` through D-110. PLAYBOOKS section 6 leaves the VWAP slope
convention and the cross-count convention unresolved --
`first_pullback_vwap.py`'s own `UNDEFINED` tuple already names
`VWAP_SLOPE_CONVENTION_UNDEFINED` for exactly this gap -- so per D-104 this
session computes no slope or cross count: the produced `VwapContext` always
reports `slope=None`, `crosses=None` and that reason whenever a level is
otherwise available, which still lets `PRICE_VS_VWAP` (`_vwap_side`)
evaluate genuinely from a real level while `VWAP_SLOPE`/`VWAP_CROSSES` stay
`UNKNOWN` by name -- exactly what `VwapContext.__post_init__`'s own contract
allows a partially known context to report, since `_vwap_reason` only checks
availability/`coverage_complete`, not which individual field is populated.

New offline synthetic test coverage
(`tests/trade_alerts_contracts/test_first_pullback_vwap_vwap_and_last_trade_
research_adapter.py`, new file): 20 cases proving both producers against
`orb5_trigger.Observation` and `first_pullback_vwap.VwapContext`'s own
contracts directly, covering: the latest-ended-bar tape read and its
`PROVISIONAL`-admitting behaviour, evaluating before any bar has ended, a
certified no-trade bar reporting `NO_TRADE_AT_LATEST_BAR` rather than a stale
price, a missing bar falling back to the prior ready one, missing/
incompatible history and an incompatible instrument type for the tape read;
the VWAP level matching an independently computed volume-weighted average,
`PROVISIONAL` bars producing the same level as `FINAL` ones, only bars up to
the evaluated instant being weighted, before-any-trade leaving the level
absent while `coverage_complete` stays true, a certified no-trade bar being
excluded from the weighted average, missing/incompatible history, an
incompatible instrument type excluding every bar (not just one), a weekend
instant having no regular session, and both explicit-input checks; a final
case per producer confirms the result stands as its own canonical
`Observation`/`VwapContext` record. Run once through the protected launcher
together with `test_first_pullback_vwap_research_adapter.py`,
`test_first_pullback_vwap.py` and `test_or_failure_rev_research_adapter.py`,
confirming every existing contract is unchanged: 256 passed, exit code 0.
This was a self-run orientation pass only, not protected acceptance evidence;
the controller's own published protected proof for this milestone follows
separately and supersedes these numbers.

The structural stop/target, the quote decision (which needs a real bid/ask
quote source this project does not have and stays out of scope, exactly like
`OR_FAILURE_REV`'s own) and the M4.4 confidence still need their own real-bar
producers and remain open build-scope for a further M9.1 sub-step.

No code path here derives a gate, a trigger, an alert or a live consumable
input on its own: nothing computed in this session reaches `ALERT_TRIGGERED`
on its own, and `VWAP_SLOPE`/`VWAP_CROSSES` stay `UNKNOWN` by design. No
provider call, spend, or live/alert/order action occurred in this session.
All switches stay off.

- [!] **M9.1P — `FIRST_PULLBACK_VWAP`'s VWAP context and last-trade
  observation:** implemented as described above; the real VWAP level and the
  real tape-read observation are built and proven, but the VWAP slope and
  cross-count conventions stay an explicit recorded D-104 gap
  (`VWAP_SLOPE_CONVENTION_UNDEFINED`), and the structural stop/target, the
  quote decision and the M4.4 confidence are still open, so the reopened
  parent `M9.1 — Historical replay #1-4` is still not complete; work
  continues at M9.1Q. The two D-104 gaps stay recorded gaps with dependent
  rules off. No provider call or spend occurred.
## M9.1Q — `FIRST_PULLBACK_VWAP`'s structural raw stop built; the target catalog still open — 2026-09-18 Pacific

Following the same too-large-for-one-session split used for M9.1D-P, this
session narrows M9.1Q's named scope to the first piece of the structural
stop/target: the raw stop `first_pullback_vwap.PullbackStructural` needs.
`first_pullback_vwap_research_adapter.py` (the M9.1N/M9.1P module) gains a
third function, `build_pullback_structural_from_research`.

PLAYBOOKS section 6 gives the raw stop as `pullback_low - 0.05 * frozen_ATR_1m`
for a long continuation and `pullback_high + 0.05 * frozen_ATR_1m` for a short
one, rounded outward to the caller's own supplied price increment -- exactly
the same `extreme -/+ 0.05*ATR` arithmetic `or_failure_rev_research_adapter
.build_or_failure_rev_structural_from_research` (M9.1K) already uses for
`OR_FAILURE_REV`'s own stop, reproduced here (that helper is private to its
own module) rather than duplicated with a different number. `entry_reference`
and `pullback_extreme_price` are caller-supplied facts from their own
producers (the M0.3A entry search and the M8.3 measurement this playbook
already reads unchanged), exactly like M9.1K's `entry_reference`/
`breakout_extreme_price`; this adapter only measures the stop geometry those
facts and the supplied price increment imply. No bar is read to compute the
stop, so the returned `label` is always `None` this session.

The target catalog PLAYBOOKS section 6 and the M0.3E packet section 7 name
(the frozen impulse extreme, regular-session HOD/LOD available at trigger,
prior-day high/low/close and whole/half-dollar levels between entry and the
furthest supplied structural level) needs its own real-bar producer reading
multiple sessions' history, unlike M9.1K's simpler three-level catalog, and
remains open build-scope for a further M9.1 sub-step; `targets` is always `()`
here. An unpriceable stop (an unavailable pullback extreme, an unknown price
increment, or geometry that lands on the wrong side of entry) reports
`risk=None` with its own named `missing_reason` per D-104, never an
approximated number.

New offline synthetic test coverage
(`tests/trade_alerts_contracts/test_first_pullback_vwap_structural_research_
adapter.py`, new file): 9 cases proving the producer against
`first_pullback_vwap.PullbackStructural`'s own contract directly, covering: a
long stop below the pullback low by the ATR pad, a short stop above the
pullback high by the pad, outward rounding in both directions, an unavailable
pullback extreme, an unknown price increment, a stop on the wrong side of
entry, the record-ID-prefix/direction input checks, the supplied instants
being carried through unchanged, and a final case confirming the result
stands as its own canonical `PullbackStructural` record. Run once through the
protected launcher together with `test_first_pullback_vwap_research_adapter.py`,
`test_first_pullback_vwap_vwap_and_last_trade_research_adapter.py`,
`test_first_pullback_vwap.py` and `test_or_failure_rev_research_adapter.py`,
confirming every existing contract is unchanged: 265 passed, exit code 0. This
was a self-run orientation pass only, not protected acceptance evidence; the
controller's own published protected proof for this milestone follows
separately and supersedes these numbers.

No code path here derives a gate, a trigger, an alert or a live consumable
input on its own: the produced `PullbackStructural` still needs the
`RISK_TARGETS` gate's own re-check against the measured pullback, which
`first_pullback_vwap._structural` already performs unchanged, and an empty
`targets` tuple already reads as `GEOMETRY_TARGETS_UNAVAILABLE` there. No
provider call, spend, or live/alert/order action occurred in this session.
All switches stay off.

- [!] **M9.1Q — `FIRST_PULLBACK_VWAP`'s structural raw stop:** implemented as
  described above; the real raw-stop geometry is built and proven from
  caller-supplied facts, but the target catalog, the quote decision and the
  M4.4 confidence are still open, so the reopened parent
  `M9.1 — Historical replay #1-4` is still not complete; work continues at
  M9.1R. The two D-104 gaps stay recorded gaps with dependent rules off. No
  provider call or spend occurred.
- [ ] **M9.1R — `FIRST_PULLBACK_VWAP`'s structural target catalog:** proposed
  next milestone. Read `consensus_engine/first_pullback_vwap.py`'s
  `PullbackStructural.targets` need and the M0.3E packet section 7's target
  rule (frozen impulse extreme, regular-session HOD/LOD available at trigger,
  prior-day high/low/close, and known whole/half-dollar levels between entry
  and the furthest supplied structural level, merged and sorted by directional
  distance, T1 at least 1.5R away and T2 the nearest distinct level from
  2.5R-4R) before choosing the exact real-bar computation this catalog needs;
  one sub-step at a time if a single session cannot fit the whole remaining
  scope, per the same split M9.1D-Q used. The quote decision (which needs a
  real bid/ask quote source this project does not have) and the M4.4
  confidence stay out of this sub-step's scope. The two D-104 gaps stay
  recorded gaps with dependent rules off. Independent review must confirm
  eligibility before the controller advances.

## M9.1R — `FIRST_PULLBACK_VWAP`'s structural target catalog built — 2026-09-18 Pacific

Following the same split used for M9.1D-Q, this session builds the M0.3E
section 7 target catalog `build_pullback_structural_from_research` (the
M9.1N/P/Q module) left open: `PullbackStructural.targets` is no longer always
`()`. The frozen impulse extreme is a new caller-supplied fact
(`impulse_extreme_price`), exactly like `pullback_extreme_price`'s own
convention; regular-session HOD/LOD and the prior regular session's high/low/
close are read here from real minute bars via two new helpers,
`_session_extremes` and `_prior_day_ohlc`, admitting `PROVISIONAL` through
D-110 exactly like `_session_vwap`'s own read for the M9.1K catalog. Known
whole-dollar/half-dollar levels strictly between entry and the furthest of
those real levels are generated arithmetically by a third new helper,
`_dollar_half_levels`. A new `_build_target_catalog` helper keeps only levels
ahead in the trade direction, merges exact prices while retaining every
label, sorts by directional distance, and picks T1 (nearest level at least
1.5R away) and T2 (nearest distinct later level from 2.5R through 4R) exactly
per the M0.3E section 7 rule.

The session HOD/LOD read only counts real traded bars from the regular
session open through `evaluated_at`; the prior-day read requires the entire
prior regular session's expected minutes to be present and ready (D-104: no
partial-session approximation). Either source being unavailable, or no
qualifying T1 among whatever real/whole/half-dollar levels are ahead in the
trade direction, leaves `targets=()`, which the existing `RISK_TARGETS` gate
already reads as `GEOMETRY_TARGETS_UNAVAILABLE` -- exactly the M9.1K
precedent for its own absent-VWAP/no-T1 case; this module does not
distinguish "known absence" from "incomplete inputs" beyond that existing
reading. Every new parameter (`symbol`, `instrument_type`,
`impulse_extreme_price`, `minute_history`) defaults to `None`, so every
M9.1Q-era call keeps its exact stop-only, `targets=()`, `label=None` result
unchanged.

The remaining `FIRST_PULLBACK_VWAP` inputs (the quote decision, which needs a
real bid/ask quote stream this project has no source for and so cannot be
derived at all; and the M4.4 confidence) still need their own producers and
stay open build-scope for a further M9.1 sub-step; `first_pullback_vwap.py`,
`impulse_pullback_research_adapter.py`, `hod_comp_rs_research_adapter.py` and
`or_failure_rev_research_adapter.py` are all untouched.

New offline synthetic test coverage
(`tests/trade_alerts_contracts/test_first_pullback_vwap_target_catalog_research_
adapter.py`, new file): 11 cases proving the producer against
`first_pullback_vwap.PullbackStructural`'s own contract directly, covering: T1
from the nearest qualifying real level (prior-day high), T2 from the nearest
qualifying whole/half-dollar level, the mirrored short-direction merge/sort,
a duplicate price merging two labels into one target, a missing impulse
extreme leaving the stop intact with no targets, every new parameter omitted
reproducing the exact M9.1Q stop-only result, an incompatible symbol, no
traded session bar yet, an incomplete prior-session window, no qualifying T1
among the available levels, and a final case confirming the produced targets
stand as their own canonical `TargetLevel`/`PullbackStructural` records. Run
once through the protected launcher together with
`test_first_pullback_vwap_structural_research_adapter.py`,
`test_first_pullback_vwap_research_adapter.py`,
`test_first_pullback_vwap_vwap_and_last_trade_research_adapter.py`,
`test_first_pullback_vwap.py` and `test_or_failure_rev_research_adapter.py`,
confirming every existing contract is unchanged: 276 passed, exit code 0.
This was a self-run orientation pass only, not protected acceptance evidence;
the controller's own published protected proof for this milestone follows
separately and supersedes these numbers.

No code path here derives a gate, a trigger, an alert or a live consumable
input on its own: the produced `PullbackStructural` still needs the
`RISK_TARGETS` gate's own re-check against the measured pullback, which
`first_pullback_vwap._structural` already performs unchanged. No provider
call, spend, or live/alert/order action occurred in this session. All
switches stay off.

- [!] **M9.1R — `FIRST_PULLBACK_VWAP`'s structural target catalog:**
  implemented as described above; the real target-catalog geometry is built
  and proven from caller-supplied facts plus real session/prior-day bars, but
  the quote decision and the M4.4 confidence are still open, so the reopened
  parent `M9.1 — Historical replay #1-4` is still not complete; work
  continues at M9.1S. The two D-104 gaps stay recorded gaps with dependent
  rules off. No provider call or spend occurred.
- [ ] **M9.1S — `FIRST_PULLBACK_VWAP`'s quote decision and M4.4 confidence:**
  proposed next milestone. With M9.1M-R, every bar-native
  `FIRST_PULLBACK_VWAP` input (`RelativeStrength`, last-trade `Observation`,
  `VwapContext`, and now the full `PullbackStructural` stop/target catalog)
  is built and proven from real minute bars. The two inputs PLAYBOOKS section
  6 still names -- the quote-decision `Observation`
  (`policy.mode=QUOTE_PROJECTED`), which needs a real bid/ask quote stream
  this project has no source for, and the M4.4 confidence score (M0.3E
  section 8) -- remain open. Read `first_pullback_vwap.py`'s own
  `PullbackRequest`/`_structural` consumers and the M0.3E section 8 score
  formula before deciding whether either piece can be built offline at all,
  or whether both stay a recorded D-104 gap; one sub-step at a time if a
  single session cannot fit the whole remaining scope, per the same split
  M9.1D-R used. The two D-104 gaps stay recorded gaps with dependent rules
  off. Independent review must confirm eligibility before the controller
  advances.

## M9.1S — both remaining `FIRST_PULLBACK_VWAP` inputs confirmed unbuildable offline; no code change — 2026-09-18 Pacific

This session read `first_pullback_vwap.py`'s `PullbackRequest` (its existing
`quote: QuoteEventDecision | None = None` and `confidence: ConfidenceResult |
None = None` fields), `quote_events.py`'s `QuoteEventDecision` (which requires
a real `Quote`, i.e. an actual bid/ask), and the M0.3E section 8
`FIRST_PULLBACK_VWAP_SCORE_V1` formula, to decide whether the quote decision or
the M4.4 confidence score can be computed from the retained `core17-1y`
minute-bar files at all.

They cannot, and this is not a new limitation:

- The quote-decision `Observation` (`policy.mode=QUOTE_PROJECTED`) and
  `QuoteEventDecision` both require a real bid/ask quote stream. The retained
  `core17-1y` files are OHLCV-1m/BBO-1m/trades bar and tape data, not a
  reconstructable NBBO quote feed, and M0.2E/M0.2I already found this project
  has no qualifying source for one (Schwab's current-access check is a dated,
  bounded, non-historical read; Databento's OPRA/NBBO cost check stopped at
  the first HTTP 400). This matches the D-104 original-availability/finality
  gap pattern already recorded for this project.
- The M0.3E section 8 score is `UNKNOWN` whenever any one of its twelve named
  factors is missing, with no rescale. Three of its four execution-component
  factors — `spread_bps`, `quote_age_seconds`, and (with it) staleness
  headroom's use of a live extension — are themselves quote-stream reads, so
  the score inherits the identical missing-source gap; it cannot be computed
  offline from bars alone, independent of the quote-decision gap above.

Both findings match the existing project-wide pattern rather than a new one:
`consensus_engine/confidence.py` (M4.4) is a pure caller-supplied composition
with no factor formulas of its own, and `hod_comp_rs_replay.py` and
`or_failure_rev_replay.py` — the two playbooks whose own real-data replay
inputs are already fully built (M9.1E-L) — likewise only ever accept
`confidence: ConfidenceResult | None` as a caller-supplied, optional field;
neither playbook computes it from real bars either. `PullbackRequest` already
carries both `quote` and `confidence` as optional fields with full validation
(`first_pullback_vwap.py` lines 436-440, 470-475), so no dataclass, adapter or
research-binding change is needed to leave them supplied-or-null: they already
are. No code changed this session.

With M9.1M-R (relative strength, VWAP context, last-trade, impulse/pullback
measurement, and the structural stop/target catalog) already built and proven
from real minute bars, and this session confirming the two remaining named
inputs are a recorded D-104-style gap rather than unbuilt work, every
`FIRST_PULLBACK_VWAP` bar-native input now has real-data coverage matching
`HOD_COMP_RS` and `OR_FAILURE_REV`. That completes build-scope item (b) (the
per-playbook bar-to-replay-input adapters plus the shared outcome evaluator
and fill/cost model, item (b) of the 2026-09-17 M9.1 build-scope inventory —
`playbook_outcome_evaluator.py`/M9.1C already covers `HOD_COMP_RS`,
`OR_FAILURE_REV` and `FIRST_PULLBACK_VWAP`, and `fill_cost_model.py`/M9.1B is
shared) for all four playbooks. Items (c) the frozen parameter grid/train-
held-out split pre-registration, (d) the D-108 statistical evaluator, and (e)
the search run itself are still unstarted; no application ran, no signal was
generated and no return was calculated.

No test file changed, since no code changed; the existing
`tests/trade_alerts_contracts/test_first_pullback_vwap.py`,
`test_first_pullback_vwap_request_research_binding.py` and the M9.1M-R
research-adapter test files already cover the `quote`/`confidence` optional-
field validation this session confirmed needed no change.

- [x] **M9.1S — `FIRST_PULLBACK_VWAP`'s quote decision and M4.4 confidence:**
  both confirmed unbuildable offline as described above and recorded as a
  D-104-style gap matching the existing `HOD_COMP_RS`/`OR_FAILURE_REV`
  supplied-confidence pattern; no code changed. With M9.1M-R, every
  `FIRST_PULLBACK_VWAP` bar-native input now has real-data coverage, completing
  build-scope item (b) for all four playbooks. The reopened parent
  `M9.1 — Historical replay #1-4` is still not complete: items (c) the frozen
  grid/split pre-registration, (d) the D-108 evaluator and (e) the search run
  itself remain unstarted; work continues at M9.1T. The two D-104 gaps stay
  recorded gaps with dependent rules off. No provider call or spend occurred.
## M9.1T — frozen parameter grid, playbook-combination and split pre-registration record — 2026-09-18 Pacific

This session builds build-scope item (c) from the 2026-09-17 M9.1 inventory:
pre-registering, before any result is read, the parameter grid over the eight
open settings (D-043, D-044, D-045, D-048, D-049, D-052, D-054, D-055), the
playbook-combination candidates, and confirmation of the D-107 9-train/
8-held-out split. New file
[M9_1T_PARAMETER_GRID_PREREGISTRATION.md](./M9_1T_PARAMETER_GRID_PREREGISTRATION.md)
and new decision
[D-111](./DECISIONS_AND_OPEN_QUESTIONS.md#60-d-111--agent-selected-m91t-parameter-grid-and-playbook-combination-preregistration)
freeze: 2 candidates for D-043 (5m/15m, reusing the already-frozen
`M03B_OR_RESEARCH_V2` range definitions), 3 for D-044 (RVOL 1.5/2.0/2.5), 3
paired candidates for D-045 (acceptance window/prior), 2 for D-048
(compression on/off), 2 for D-049 (RS mandatory/report-only), 2 for D-052
(confirmed/faster entry), 2 for D-054 (VWAP mandatory/relaxed) and 2 for D-055
(AVWAP off/on) — 18/4/2/4 per-strategy configurations for `CRVOL_ORB5`/
`HOD_COMP_RS`/`OR_FAILURE_REV`/`FIRST_PULLBACK_VWAP` — plus 5 playbook-
combination candidates (each playbook solo, and all four combined), with a
two-stage design (per-playbook winning configuration on the training nine,
then playbook-combination selection on the training nine, then a single
stage-3 D-108 pass on the held-out eight) and fixed tie-break rules, instead
of the 576-cell flat cross that a single combined grid would produce. This is
a pure documentation/records change; no production module changed.

No code, test or protected input changed. This is documentation-only research
preregistration, not a search run: no training or held-out result was read,
no signal was generated, no application ran and no spend occurred. Items (d)
the D-108 evaluator itself and (e) the search run remain unstarted; work
continues at M9.1U. The two D-104 gaps and the M9.1S quote-decision/M4.4-
confidence gap stay recorded gaps with dependent rules off.

- [x] **M9.1T — the frozen parameter grid, train/held-out split
  pre-registration record:** implemented as described above — build-scope
  item (c), the eight-setting grid, playbook-combination candidates and the
  D-107 split, all frozen before any result is read. The reopened parent
  `M9.1 — Historical replay #1-4` is still not complete: items (d) the D-108
  evaluator and (e) the search run itself remain unstarted; work continues at
  M9.1U. The two D-104 gaps stay recorded gaps with dependent rules off. No
  provider call or spend occurred.
- [ ] **M9.1U — the D-108 evaluator:** proposed next milestone. Build-scope
  item (d) from the 2026-09-17 M9.1 inventory: implement the frozen D-108
  success-bar evaluator (per-trade mean profit after costs with bootstrap
  lower bound, >=60% weekly win rate, drawdown recoverable within about six
  average winning weeks), computed only on the held-out eight and only after
  the M9.1T stage-1/stage-2 training-set selection is complete. One sub-step
  at a time if a single session cannot fit the whole remaining scope. The two
  D-104 gaps stay recorded gaps with dependent rules off. Independent review
  must confirm eligibility before the controller advances.

## M9.1U — the D-108 success-bar evaluator built, no search run — 2026-09-18 Pacific

This session builds build-scope item (d) from the 2026-09-17 M9.1 inventory:
new module `consensus_engine/d108_evaluator.py` implements the frozen D-108
bar (`DECISIONS_AND_OPEN_QUESTIONS.md` section 57) as a pure function over an
already-resolved sequence of per-trade `resolved_r` values (each already
reflecting the D-106/D-107 modeled fill and cost from
`playbook_outcome_evaluator.py`/`outcome_evaluator.py`) with their close
times. `evaluate_d108(candidate_id, trades)` computes all three named
measures on whatever trade sequence it is given:

1. **Profit** — mean R per trade, with a bootstrap lower bound above zero.
   The bootstrap reuses this project's existing dependence-aware convention
   (`M0_3B_DEFINITION_PACKET.md` section 5): a circular moving-block resample
   over ordered calendar weeks (the D-108 unit here, not sessions), 10,000
   draws, primary block length `L=10` with `L=5`/`L=20` sensitivities, a
   frozen `NumPy Generator(PCG64(seed))` derived from a canonical-JSON SHA256
   hash of the candidate ID, week count, block length and resample count, and
   the same nearest-rank quantile rule at the ordinary one-sided `q=0.05`
   (95%) — this is a single frozen measurement, not one of the 72-arm family
   comparisons, so no Bonferroni-style allocation applies. A sensitivity that
   flips the primary's pass/fail sets `review_required` and fails profit,
   mirroring the existing `REVIEW_REQUIRED` convention rather than averaging
   the three block lengths.
2. **Consistency** — fraction of calendar weeks with net-positive summed R
   >= 0.60.
3. **Survivability** — worst peak-to-trough drawdown on the chronological
   cumulative-R curve, divided by the average positive-week R, compared
   against the ~6-winning-week bar; explicitly reported as failing (not a
   crash or a silent pass) when there is no winning week to size a recovery
   rate from, and trivially passing when there is no drawdown. Worst losing
   streak is computed and reported alongside, never as pass/fail, per D-108.

`evaluate_d108` raises `RecordError` on an empty trade sequence or a blank
candidate ID rather than returning a default pass or fail — a configuration
with zero held-out trades has no D-108 result. This module runs the frozen
bar over a supplied sequence; it has no loader, adapter, search loop or
clock of its own, does not choose a configuration, and does not read any
result before the caller supplies it, so writing and testing it here reads
no held-out data and computes no return for any real candidate.

New test file `tests/trade_alerts_contracts/test_d108_evaluator.py` (18
cases): empty/blank-input rejection, a strong all-winning synthetic pattern
passing all three measures, a losing synthetic pattern failing all three, the
60% consistency boundary on both sides, a recoverable and an unrecoverable
drawdown, the explicit no-winning-week and no-drawdown edge cases, the
losing-streak figure, bootstrap determinism and candidate-ID-sensitivity of
the frozen seed, the configured resample/block-length constants, the
sensitivity `review_required` disagreement path, and the `as_dict` shape.
Focused run: `python3 scripts/testing/run_trade_alerts_contracts.py
tests/trade_alerts_contracts/test_d108_evaluator.py` — 18 passed, run twice in
two fresh isolated processes with matching results (same seeds/hashes/lower
bounds both times, as the bootstrap is fully deterministic).

Item (e), the search run itself (stage 1/2/3 over the real `core17-1y` bars,
per `M9_1T_PARAMETER_GRID_PREREGISTRATION.md` section 3), remains unstarted;
no application ran, no signal was generated, no real trade was evaluated and
no spend occurred. The reopened parent `M9.1 — Historical replay #1-4` is
still not complete: work continues at M9.1V. The two D-104 gaps and the
M9.1S quote-decision/M4.4-confidence gap stay recorded gaps with dependent
rules off. No provider call occurred.

- [x] **M9.1U — the D-108 success-bar evaluator:** implemented as described
  above — build-scope item (d), a pure profit/consistency/survivability
  function over already-resolved per-trade R, reusing the project's existing
  circular moving-block bootstrap convention. With items (a)-(d) of the
  2026-09-17 M9.1 build-scope inventory now built, only item (e), the search
  run itself, remains before the reopened parent `M9.1 — Historical replay
  #1-4` can complete; work continues at M9.1V. The two D-104 gaps stay
  recorded gaps with dependent rules off. No provider call or spend occurred.
## M9.1V part 1 — frozen stage-1/stage-2 search catalog and training-set ranking rule built; no bars loaded, no search run — 2026-09-18 Pacific

Build-scope item (e), the last item of the 2026-09-17 M9.1 inventory, is too
large for one session: it needs the `core17_bar_loader.py` wiring, four
playbook adapters driven through 18+4+2+4 stage-1 configurations and 5
stage-2 combinations across nine training tickers and roughly a year of
minute bars, then one held-out-eight `d108_evaluator.evaluate_d108` pass.
This session builds the first piece only: new module
`consensus_engine/search_run_config.py` reproduces
`M9_1T_PARAMETER_GRID_PREREGISTRATION.md` sections 1-3 as pure data plus one
pure comparison function — the D-107 training/held-out ticker split, the
per-playbook stage-1 candidate grids (18/4/2/4, built as a fixed
`itertools.product` cross in each table's own axis order so every
candidate's `table_order` matches its preregistered tie-break priority), the
five stage-2 playbook-combination candidates, and
`rank_training_candidates`, which applies the frozen tie-break (highest
mean profit, then weekly win rate, then lowest drawdown, then lowest
`table_order`) to caller-supplied `TrainingMeasurement` values. It loads no
bars, drives no adapter, computes no profit/win-rate/drawdown figure itself,
and reads no training or held-out result — `TrainingMeasurement` is a plain
value the caller must compute elsewhere and supply.

New test file `tests/trade_alerts_contracts/test_search_run_config.py` (16
cases): the exact D-107 split and its 9/8 disjoint sizes, the frozen
four-playbook name tuple, each playbook's grid size (18/4/2/4) against both
the built candidates and the recorded `STAGE1_GRID_SIZES`, unique candidate
IDs per playbook, each grid containing its table-listed current-default
candidate, fixed zero-based `table_order` per playbook, the five stage-2
candidate IDs and their `playbooks` tuples (including `ALL_FOUR` matching the
frozen four-playbook order), empty-sequence rejection, and the tie-break
rule exercised at each of its four levels (profit, then win rate, then
drawdown, then table order) plus a trivial single-candidate case. Focused
run: `python3 scripts/testing/run_trade_alerts_contracts.py
tests/trade_alerts_contracts/test_search_run_config.py` — 16 passed, run
twice in two fresh isolated processes with matching results (pure data and
arithmetic, no randomness).

Stage 1 itself (loading real bars and driving the adapters through this
catalog on the training nine) remains unstarted; no application ran, no
signal was generated, no real trade was evaluated and no spend occurred. The
reopened parent `M9.1 — Historical replay #1-4` is still not complete: work
continues at M9.1W (wiring `core17_bar_loader.py` output into one
playbook's adapter and running that playbook's stage-1 grid on the training
nine). The two D-104 gaps and the M9.1S quote-decision/M4.4-confidence gap
stay recorded gaps with dependent rules off.

- [!] **M9.1V — the stage-1/stage-2/stage-3 walk-forward search run:**
  part 1 (the frozen stage-1/stage-2 config catalog and training-set ranking
  rule) implemented as described above. Build-scope item (e) is still not
  complete: loading real bars, driving the four adapters through this
  catalog on the training nine (stage 1), the combination search (stage 2)
  and the held-out D-108 pass (stage 3) remain unstarted; the reopened
  parent `M9.1 — Historical replay #1-4` is still not complete. Work
  continues at M9.1W. The two D-104 gaps and the M9.1S
  quote-decision/M4.4-confidence gap stay recorded gaps with dependent rules
  off. No provider call, application run or spend occurred.
- [ ] **M9.1W — wire `core17_bar_loader.py` into one playbook's
  research adapter and run that playbook's stage-1 grid on the training
  nine:** proposed next sub-step. Load the retained `core17-1y` OHLCV-1m
  bars for the nine training tickers, drive one playbook's built adapter
  (`CRVOL_ORB5`'s existing path is the smallest-wiring candidate) through
  its `search_run_config.STAGE1_CANDIDATES` grid, and use
  `rank_training_candidates` to pick that playbook's stage-1 winner. One
  sub-step at a time if a single session cannot fit the whole remaining
  scope, per the same split M9.1D-V used. The two D-104 gaps and the M9.1S
  quote-decision/M4.4-confidence gap stay recorded gaps with dependent rules
  off throughout. Independent review must confirm eligibility before the
  controller advances.

## M9.1W part 1 — per-ticker, per-session bar grouping built; no adapter driven, no search run — 2026-09-18 Pacific

The full M9.1W scope (loader output into one playbook's adapter and that
playbook's whole stage-1 grid on the training nine) is too large for one
session. This session builds the first piece only: new module
`consensus_engine/search_run_bars.py`, `group_session_bars`, which takes
already-converted `DatabentoMinuteRecord` values (from
`core17_bar_loader.iter_ohlcv_1m_records`) and a ticker list, and returns one
time-ordered bar tuple per (ticker, session). A duplicate bar for the same
ticker and minute raises. A session with any non-AVAILABLE provider condition
is held back and listed in `degraded_sessions`, so dependent rules stay off and
labelled untested (D-104) rather than running on a proxy. It computes no
signal, return or parameter figure and reads no result.

New test file `tests/trade_alerts_contracts/test_search_run_bars.py` (6
cases): time-ordered grouping by ticker and session, dropped-ticker counting,
duplicate-minute rejection, degraded-session hold-back, ticker-list validation
and non-record rejection. Focused run of that file through the protected
launcher — 6 passed in each of two fresh isolated processes the launcher ran.
The controller's own published stages will supply the official counts and
timings.

No application ran, no signal was generated, no real trade was evaluated, no
provider call and no spend occurred. The reopened parent `M9.1 — Historical
replay #1-4` is still not complete. Work continues at M9.1X (driving one
playbook's adapter over these grouped bars).

- [!] **M9.1W — wire `core17_bar_loader.py` into one playbook's research
  adapter and run its stage-1 grid:** part 1 (session bar grouping) built as
  described above. Driving `CRVOL_ORB5`'s adapter through its stage-1 grid on
  the training nine and picking its winner with `rank_training_candidates`
  remain unstarted. The two D-104 gaps and the M9.1S
  quote-decision/M4.4-confidence gap stay recorded gaps with dependent rules
  off. No provider call, application run or spend occurred.
- [ ] **M9.1X — drive `CRVOL_ORB5`'s research adapter over the grouped
  training-nine bars for one stage-1 candidate:** proposed next sub-step.
  Turn `search_run_bars.group_session_bars` output into the adapter's
  per-instant inputs and resolve one candidate's trades to per-trade R, then
  extend to the 18-candidate grid and `rank_training_candidates`. Independent
  review must confirm eligibility before the controller advances.

## M9.1X part 1 — grouped bars wrapped as a `HistoryBatch` for the research adapters; no ORB5 adapter driven, no search run — 2026-09-18 Pacific

The full M9.1X scope is too large for one session, and a check of the code
showed that `CRVOL_ORB5` has no research adapter of its own yet (only the
supplied-input replay owner `orb5_replay.py`); the earlier note calling it the
"existing path" meant that replay owner. Every built research adapter reads a
`HistoryBatch`, so this session builds the shared bridge first:
`search_run_bars.history_batch_for(grouped, ticker, session, conventions)`
wraps one grouped (ticker, session) as a `HistoryBatch` over that session's
regular hours. The caller supplies `conventions`; nothing is defaulted. The
loader labels volume units unknown, so a caller that cannot name them passes
UNKNOWN and the adapters refuse the batch (D-104) instead of running on a
guess. The loader also labels every ticker's `instrument_type` as ETF; that is
recorded here as a known mislabel for stocks and is not corrected in this step.

Three new cases in `tests/trade_alerts_contracts/test_search_run_bars.py` (9
in the file now): a grouped session feeds `OR_FAILURE_REV`'s existing bar
adapter, unknown conventions leave the adapter with no price, and degraded,
absent or malformed sessions and non-convention input are rejected. One
focused protected-launcher run of that file: 9 passed. The controller's
published stages will supply the official counts and timings.

No application ran, no signal, trade or result was produced, no provider call
and no spend occurred. The reopened parent `M9.1 — Historical replay #1-4` is
still not complete.

- [!] **M9.1X — drive `CRVOL_ORB5`'s research adapter over the grouped
  training-nine bars:** part 1 (`HistoryBatch` bridge) built as described
  above. The ORB5 research adapter itself, one candidate's per-trade R, the
  18-candidate grid and `rank_training_candidates` remain unstarted. The two
  D-104 gaps and the M9.1S quote-decision/M4.4-confidence gap stay recorded
  gaps with dependent rules off.
- [ ] **M9.1Y — build the `CRVOL_ORB5` bar-native research adapter:** proposed
  next sub-step. Produce ORB5's `Observation`/`MinuteClose`/opening-range
  inputs from a `HistoryBatch` made by `history_batch_for`, reusing the
  `OR_FAILURE_REV` bar reads where they fit, and decide how the unknown volume
  units and ETF mislabel are handled. Independent review must confirm
  eligibility before the controller advances.

## M9.1Y part 1 — `CRVOL_ORB5` bar-native research reads built; no trigger driven, no search run — 2026-09-18 Pacific

New module `consensus_engine/orb5_research_adapter.py`. It builds the reads
that one-minute bars can honestly supply to `Orb5TriggerMachine`:
`build_orb5_bar_observations` (one TAPE `Observation` per grid instant, priced
from the latest ready bar with its true age, so finer grid instants reuse the
same close and the policy's maximum age makes them stale instead of inventing
intra-minute prices), and `opening_range_from_bars` (high/low over the first N
regular minutes, only if every minute has a ready traded bar). Basis checks
reuse the `OR_FAILURE_REV` adapter, so UNKNOWN volume units are refused. The
loader's `ETF` label for every ticker is left as is: a stock session named
`EQUITY` reports INCOMPATIBLE_INSTRUMENT_TYPE, a recorded gap, until the label
is fixed in its own step. `bar_tape_intensity` is always an explicit gap
(`NO_15S_TAPE_FROM_MINUTE_BARS`): the 15-second tape intensity cannot come from
minute bars, so any ORB5 rule that needs it stays off and labelled untested
(D-104). Outputs carry the D-110 label.

New test file `tests/trade_alerts_contracts/test_orb5_research_adapter.py` (7
cases). One focused protected-launcher run of that file: 7 passed. The
controller's published stages will supply the official counts and timings.

No application ran, no signal, trade or result was produced, no provider call
and no spend occurred. The reopened parent `M9.1 — Historical replay #1-4` is
still not complete.

- [!] **M9.1Y — build the `CRVOL_ORB5` bar-native research adapter:** part 1
  (observations, opening range, intensity gap) built as described above. The
  frozen-candidate/geometry/eligibility inputs, driving one candidate to
  per-trade R, the 18-candidate grid and `rank_training_candidates` remain
  unstarted. The two D-104 gaps and the M9.1S quote-decision/M4.4-confidence
  gap stay recorded gaps with dependent rules off.
- [ ] **M9.1Z — fix the loader's stock `ETF` label and wire the ORB5 reads
  into one candidate's per-trade R:** proposed next sub-step. Independent
  review must confirm eligibility before the controller advances.

## M9.1Z part 1 — stock `EQUITY` label fixed in the bar loader; no candidate driven, no search run — 2026-09-18 Pacific

`DatabentoMinuteContext` (`consensus_engine/databento_minute_bars.py`) and
`iter_ohlcv_1m_records` (`consensus_engine/core17_bar_loader.py`) now take an
`instrument_type` of `ETF` or `EQUITY`. The default stays `ETF`, so every
existing core-17 ETF file is labelled exactly as before. The caller states the
label for a whole file; it is never guessed from the symbol, and any other
value is refused. A stock file labelled `EQUITY` now passes the ORB5 adapter's
instrument check, and an `ETF`-labelled batch asked for as `EQUITY` (or the
reverse) still reports INCOMPATIBLE_INSTRUMENT_TYPE. No stock file was read
and no bar was decoded; this is only the offline label contract.

Two new cases in `tests/trade_alerts_contracts/test_orb5_research_adapter.py`.
One focused protected-launcher run of that file plus the core17 loader,
Databento minute bar and search-run bar test files: 39 passed. The
controller's published stages will supply the official counts and timings.

No application ran, no signal, trade or result was produced, no provider call
and no spend occurred. The reopened parent `M9.1 — Historical replay #1-4` is
still not complete.

- [!] **M9.1Z — fix the loader's stock `ETF` label and wire the ORB5 reads
  into one candidate's per-trade R:** part 1 (the label fix) is built as
  described above. Wiring the reads into one candidate's per-trade R (frozen
  candidate, geometry and eligibility inputs, the 18-candidate grid and
  `rank_training_candidates`) is unstarted. The two D-104 gaps and the
  M9.1S quote-decision/M4.4-confidence gap stay recorded gaps with dependent
  rules off.
- [ ] **M9.1AA — wire the ORB5 bar reads into one candidate's per-trade R:**
  proposed next sub-step. Independent review must confirm eligibility before
  the controller advances.

## M9.1AA part 1 — `CRVOL_ORB5` first crossing frozen from bar reads; no per-trade R, no search run — 2026-09-18 Pacific

`find_orb5_crossing` in `consensus_engine/orb5_research_adapter.py` walks the
bar-native observations after the opening range, tests each consecutive pair
with the existing `evaluate_crossing` against the buffered boundary, and
freezes the first fresh crossing as a `FrozenCandidate` (both directions). It
returns no candidate, with a reason, when the basis, opening range or ATR is
missing, or when nothing crosses. The ATR is supplied by the caller: one
session of bars cannot give it, so a missing ATR is a recorded gap
(`ATR_UNAVAILABLE`). Nothing beyond the frozen candidate is driven.

Two new cases in `tests/trade_alerts_contracts/test_orb5_research_adapter.py`.
One focused protected-launcher run of that file: 11 passed. The controller's
published stages will supply the official counts and timings.

Not built, and why the milestone is larger than one session: the trigger's
participation gate needs `INTENSITY_15S_MEAN20_V1`, which minute bars cannot
supply, so the TAPE arm cannot reach ALERT_TRIGGERED on bars alone; eligibility
needs quote and status inputs this source lacks; geometry, the D-106/D-107
fill and cost, and the walk to stop/target for one trade's R are unstarted.
Those rules stay off and labelled untested (D-104); none is approximated.

No application ran, no signal, trade or result was produced, no provider call
and no spend occurred. The reopened parent `M9.1 — Historical replay #1-4` is
still not complete.

- [!] **M9.1AA — wire the ORB5 bar reads into one candidate's per-trade R:**
  part 1 (first-crossing freeze) built as described above. Decide which
  participation/eligibility gates run or are recorded off, then geometry, fill
  and cost, and the stop/target walk to per-trade R, the 18-candidate grid and
  `rank_training_candidates` remain unstarted. The two D-104 gaps and the
  M9.1S quote-decision/M4.4-confidence gap stay recorded gaps with dependent
  rules off.
- [ ] **M9.1AB — decide the ORB5 gate coverage on bars and build geometry plus
  the stop/target walk for one frozen candidate:** proposed next sub-step.
  Independent review must confirm eligibility before the controller advances.

## M9.1AB part 1 — ORB5 bar gate coverage decided, geometry and stop/target walk built; no search run — 2026-09-18 Pacific

New `consensus_engine/orb5_trade_walk.py`.

- Gate coverage (D-104): on bars only the boundary crossing runs. Acceptance,
  participation, last-trade-beyond-boundary, eligibility and cost/slippage are
  recorded OFF and untested with a reason each (`bar_gate_coverage`). None is
  approximated.
- Geometry: `STOP_FAR_OR_EDGE_V2` from the frozen candidate (ORL minus, or ORH
  plus, 0.05 x frozen ATR, rounded outward to the supplied tick) and fixed
  `EXIT_FIXED_2R_V2`/`EXIT_FIXED_3R_V2` targets at E ± kR. An unknown tick, a
  missing entry or a stop not adverse to entry gives no geometry.
- Walk: reads ready bars from the entry time. A bar touching both stop and
  target is a stop; a bar opening beyond the stop exits at that open; a target
  is credited at exactly k R. A missing bar before an exit, or no exit by the
  close, is unresolved. R is gross of cost.

The entry price and time are caller-supplied: bars cannot give the D-106
quote-based fill, so that fill stays unbuilt and no entry is invented.

Three new cases in `tests/trade_alerts_contracts/test_orb5_research_adapter.py`.
One focused protected-launcher run of that file: 14 passed. The controller's
published stages will supply the official counts and timings.

Not built, which is why the milestone is larger than one session: the D-106/D-107
entry fill and cost from quotes, the `EXIT_D090_STRUCTURE_V2` two-unit exit,
wiring crossing to geometry to walk into one per-trade R record, the
18-candidate grid and `rank_training_candidates`. No application ran, no signal,
trade or result was produced, no provider call and no spend occurred. The
reopened parent `M9.1 — Historical replay #1-4` is still not complete.

- [!] **M9.1AB — decide the ORB5 gate coverage on bars and build geometry plus
  the stop/target walk for one frozen candidate:** built as described above.
  Entry fill/cost, the D090 structure exit, per-trade R wiring, the grid and
  ranking remain unstarted. The two D-104 gaps and the M9.1S quote-decision/
  M4.4-confidence gap stay recorded gaps with dependent rules off.
- [ ] **M9.1AC — wire crossing, geometry and walk into one candidate's per-trade
  R record:** proposed next sub-step. Independent review must confirm
  eligibility before the controller advances.

## M9.1AC part 1 — crossing, geometry and walk wired into one per-trade R record; no search run — 2026-09-18 Pacific

`build_orb5_trade_record` in `consensus_engine/orb5_trade_walk.py` runs
`find_orb5_crossing`, `build_orb5_geometry` and `walk_orb5_trade` for one
direction and one fixed exit (`EXIT_FIXED_2R_V2` or `EXIT_FIXED_3R_V2`) and
returns one `Orb5TradeRecord`: status, gross R, reason, the frozen candidate,
geometry, walk, the caller's stated entry source, the bar gate coverage and the
D-110 label. No candidate, no entry time, or no geometry gives an unresolved
record with a reason and no R. An entry before the crossing, an unknown exit or
a blank entry source is refused. The entry price and time stay caller-supplied;
the D-106 quote-based fill is not built and none is invented.

One new case in `tests/trade_alerts_contracts/test_orb5_research_adapter.py`.
One focused protected-launcher run of that file: 15 passed. The controller's
published stages will supply the official counts and timings.

Not built, which is why the milestone is larger than one session: the
D-106/D-107 entry fill and cost from quotes, the `EXIT_D090_STRUCTURE_V2`
two-unit exit, the 18-candidate grid and `rank_training_candidates`. Gates
recorded OFF stay OFF and untested (D-104). No application ran, no signal,
trade or result was produced, no provider call and no spend occurred. The
reopened parent `M9.1 — Historical replay #1-4` is still not complete.

- [!] **M9.1AC — wire crossing, geometry and walk into one candidate's per-trade
  R record:** built as described above. Entry fill/cost, the D090 structure
  exit, the grid and ranking remain unstarted. The two D-104 gaps and the M9.1S
  quote-decision/M4.4-confidence gap stay recorded gaps with dependent rules off.
- [ ] **M9.1AD — run the per-trade R record over the 18-candidate grid for
  training sessions and rank:** proposed next sub-step. Independent review must
  confirm eligibility before the controller advances.

## M9.1AD part 1 — the 18-candidate `CRVOL_ORB5` grid run built over supplied sessions; no search run — 2026-09-18 Pacific

New `consensus_engine/orb5_grid_run.py`. `run_orb5_grid` takes caller-supplied
training sessions (bars, ATR, tick, entry price/time and stated entry source),
runs `build_orb5_trade_record` for both directions once per opening range, and
gives every one of the 18 frozen stage-1 candidates a tally (trades, unresolved,
mean gross R, weekly gross win rate) with its records.

Finding (D-104): on bars only the D-043 opening-range axis can change a result.
The D-044 participation and D-045 acceptance gates are OFF, so the 18 candidates
fall into two groups of nine with identical records, and each tally names the
untested axes. R is gross of cost and the entry is caller-supplied, so the
result is `NOT_RANKABLE`: no `TrainingMeasurement` is built and
`rank_training_candidates` is not called, because a table-order tie would be
picked as a false winner. The blockers are listed in `ranking_blockers`.

One new case in `tests/trade_alerts_contracts/test_orb5_research_adapter.py`.
One focused protected-launcher run of that file: 16 passed. The controller's
published stages will supply the official counts and timings.

Not built, which is why the milestone is larger than one session: the D-106/D-107
quote-based entry fill and cost, the `EXIT_D090_STRUCTURE_V2` exit, the real
training-session inputs (ATR, tick, entries) and any real run. No application
ran, no signal, trade or result was produced, no provider call and no spend
occurred. The reopened parent `M9.1 — Historical replay #1-4` is still not
complete.

- [!] **M9.1AD — run the per-trade R record over the 18-candidate grid for
  training sessions and rank:** the grid runner is built as described above;
  ranking is blocked (cost off, D-044/D-045 untested, entry fill supplied). The
  two D-104 gaps and the M9.1S quote-decision/M4.4-confidence gap stay recorded
  gaps with dependent rules off.
- [ ] **M9.1AE — build the D-106/D-107 quote-based entry fill and cost for one
  ORB5 trade:** proposed next sub-step. Independent review must confirm
  eligibility before the controller advances.

## M9.1AE part 1 — D-106/D-107 quote-based entry fill and entry-side cost for one ORB5 trade; no search run — 2026-09-18 Pacific

`build_orb5_quote_filled_record` in `consensus_engine/orb5_trade_walk.py` uses the
frozen crossing time as the alert time and calls the existing
`fill_cost_model.model_fill` (first valid trade print in the 0-30 second window,
real half-spread from the quote at that print, modeled slippage and commission
from a caller-supplied `FillCostPolicy`). The modeled price and print time become
the entry passed to `build_orb5_trade_record`. No print or no quote in the window
gives status `NO_FILL` with the fill reason and no R. Only the entry side is
costed. No exit quotes exist in the inputs, so exit-side spread, slippage and
commission are recorded OFF and untested (D-104) in `cost_scope`, and the walk
reads bars that start at or after the print time. Nothing is approximated.

One new case in `tests/trade_alerts_contracts/test_orb5_research_adapter.py`.
One focused protected-launcher run of that file plus `test_fill_cost_model.py`:
32 passed. The controller's published stages will supply the official counts and
timings.

Not built, which is why the milestone is larger than one session: the
`EXIT_D090_STRUCTURE_V2` two-unit exit, the real training-session inputs (ATR,
tick, trade prints, quotes) and any real run. No application ran, no signal,
trade or result was produced, no provider call and no spend occurred. The
reopened parent `M9.1 — Historical replay #1-4` is still not complete.

- [!] **M9.1AE — build the D-106/D-107 quote-based entry fill and cost for one
  ORB5 trade:** built as described above (entry side only). The D090 structure
  exit and real inputs remain unstarted. The two D-104 gaps and the M9.1S
  quote-decision/M4.4-confidence gap stay recorded gaps with dependent rules off.
- [ ] **M9.1AF — build the `EXIT_D090_STRUCTURE_V2` two-unit exit for one ORB5
  trade:** proposed next sub-step. Independent review must confirm eligibility
  before the controller advances.

## M9.1AF part 1 — `EXIT_D090_STRUCTURE_V2` two-unit exit for one ORB5 trade; no search run — 2026-09-18 Pacific

`build_orb5_structure_exit_record` in `consensus_engine/orb5_trade_walk.py`
adds the D-090 structure exit. `select_orb5_structure_targets` takes a
caller-supplied level catalog: only levels ahead of entry count, equal prices
merge with every label kept, any level closer than 1.5R suppresses the trade,
T1 is the nearest level at or beyond 1.5R and T2 the next distinct level at or
beyond 2.5R (or none). An incomplete catalog gives `CATALOG_INCOMPLETE` and no
R, never "no obstacle" (D-104). The walk closes one unit at T1, the other at T2
or the session close, keeps the stop unchanged after T1, closes every open unit
at a stop, resolves a stop-and-target bar stop first, and exits a gap through
the stop at the open. The bar-proxy horizon is the last regular bar's close; a
missing bar or close is unresolved. R is `sum(exit-entry)/(2*R)`, gross of cost;
cost stays OFF and untested.

One new case in `tests/trade_alerts_contracts/test_orb5_research_adapter.py`.
One focused protected-launcher run of that file: 18 passed. The controller's
published stages will supply the official counts and timings.

Not built, which is why the milestone is larger than one session: a real level
catalog producer (PMH/PML, PDH/PDL, ATR, AVWAP, profile), the grid run using this
exit, real training-session inputs and any real run. No application ran, no
signal, trade or result was produced, no provider call and no spend occurred. The
reopened parent `M9.1 — Historical replay #1-4` is still not complete.

- [!] **M9.1AF — build the `EXIT_D090_STRUCTURE_V2` two-unit exit for one ORB5
  trade:** built as described above from a caller-supplied catalog. The catalog
  producers and real inputs remain unstarted. The two D-104 gaps and the M9.1S
  quote-decision/M4.4-confidence gap stay recorded gaps with dependent rules off.
- [ ] **M9.1AG — let the 18-candidate grid run use the D090 structure exit:**
  proposed next sub-step. Independent review must confirm eligibility before the
  controller advances.

## M9.1AG part 1 — the 18-candidate grid run uses `EXIT_D090_STRUCTURE_V2`; no search run — 2026-09-18 Pacific

`run_orb5_grid` in `consensus_engine/orb5_grid_run.py` now accepts
`EXIT_D090_STRUCTURE_V2` besides the two fixed-R exits (any other name still
raises). `Orb5Session` gained `levels` and `catalog_complete`, read only by the
structure exit; the default is an incomplete catalog, which gives an unresolved
`CATALOG_INCOMPLETE` trade and never "no obstacle" (D-104). A structure trade
closes when its last unit closes, and that time sets its week for the weekly
gross win rate. The result is still `NOT_RANKABLE` for the same three blockers
(cost off, D-044/D-045 untested, caller-supplied entry).

The old case that expected the structure exit to be refused now uses an unknown
exit name. One new case in
`tests/trade_alerts_contracts/test_orb5_research_adapter.py` covers the grid on
the structure exit and the incomplete-catalog path.

Test status (controller proof, source hash
`ffc5eadfc3f105fc18b6a4221bcccb6d0ae78798bffd03de5b77b5a96672d1e2`, all exit 0):
- Focused: 1 run, selector `tests/trade_alerts_contracts/test_orb5_research_adapter.py`,
  19 tests, controller wall 10.732 s.
- Broad acceptance: 1 run, selector `tests/trade_alerts_contracts`, 3431 tests.
- Repeatability: 2 fresh runs, 76 tests, controller wall 343.134 s, stable, over the
  discovered recording selectors (published artifacts
  `published-artifacts-ef8a9c72f5c5`). No new recording selector was added by this
  sub-step.
The session itself made no protected run and did not self-run the family.

Not built, which is why the milestone is larger than one session: a real level
catalog producer (PMH/PML, PDH/PDL, ATR, AVWAP, profile), real training-session
inputs and any real run. No application ran, no signal, trade or result was
produced, no provider call and no spend occurred. The reopened parent
`M9.1 — Historical replay #1-4` is still not complete.

- [!] **M9.1AG — let the 18-candidate grid run use the D090 structure exit:**
  built as described above from caller-supplied catalogs. Catalog producers and
  real inputs remain unstarted. The two D-104 gaps and the M9.1S
  quote-decision/M4.4-confidence gap stay recorded gaps with dependent rules off.
- [ ] **M9.1AH — build the D-090 structural level catalog producer from bars:**
  proposed next sub-step (levels the supplied bars can honestly give; the rest
  recorded OFF and untested). Independent review must confirm eligibility before
  the controller advances.

## M9.1AH part 1 — D-090 level catalog producer from supplied features; no search run — 2026-09-18 Pacific

`build_orb5_level_catalog` in `consensus_engine/orb5_level_catalog.py` builds one
catalog per direction. PDH/PDL and PMH/PML are read from a `FeatureSnapshot`
made by `build_core_price_snapshot`; the OR measured move is `ORH + width` (long)
or `ORL - width` (short) from an available bar-native opening range. Each family
reports `PRESENT` or `UNKNOWN` with a reason. ATR projection (the snapshot does
not carry the prior close), confirmed daily swings and the prior-session bar
profile are not built and stay `UNKNOWN`, so `complete` is always false and
`select_orb5_structure_targets` gives `CATALOG_INCOMPLETE`. No proxy level is
added and nothing is read as "no obstacle" (D-104).

One new case in `tests/trade_alerts_contracts/test_orb5_research_adapter.py`. The
controller's published stages will supply the official counts and timings; this
session made no self-run of the contracts family.

Not built, which is why the milestone is larger than one session: the ATR
projection (needs the prior close exposed), daily swings, the bar profile, real
training-session inputs and any real run. No application ran, no signal, trade
or result was produced, no provider call and no spend occurred. The reopened
parent `M9.1 — Historical replay #1-4` is still not complete.

- [!] **M9.1AH — build the D-090 structural level catalog producer from bars:**
  partly built as described above. ATR, swing and profile families remain
  unbuilt. The two D-104 gaps and the M9.1S quote-decision/M4.4-confidence gap
  stay recorded gaps with dependent rules off.
- [ ] **M9.1AI — add the ATR-projection level family to the catalog:** proposed
  next sub-step (expose the prior close, then build the prior-close ± daily ATR
  levels; swings and profile follow). Independent review must confirm eligibility
  before the controller advances.

## M9.1AI part 1 — ATR-projection level family added to the catalog; no search run — 2026-09-18 Pacific

`build_core_price_snapshot` now also emits `PRIOR_REGULAR_CLOSE_V1` (the prior
final regular-session daily close it already computed for the gap). The catalog
producer builds `ATR_PROJECTION` (`PRIOR_CLOSE_DAILY_ATR_LEVELS_V1`, packet
4.2) as prior close plus and minus `DAILY_ATR_14_SMA_V1`, both from the
snapshot. If either is absent or missing the family is `UNKNOWN` with that
reason and no level is added. A level behind entry is left to the D-090
selector. Confirmed daily swings and the prior-session bar profile stay
`UNKNOWN`, so `complete` is still false (D-104).

The existing catalog case in `test_orb5_research_adapter.py` was extended, and
the daily-history identity list in `test_core_price_features.py` now names the
new feature. Both files were opened by pytest outside the launcher and skipped
there, so no result is claimed; the controller's protected stages will supply
counts and timings. This session did not self-run the contracts family.

Not built: daily swings, the bar profile, real training-session inputs and any
real run. No application ran, no signal, trade or result was produced, no
provider call and no spend occurred. The reopened parent `M9.1 — Historical
replay #1-4` is still not complete.

- [!] **M9.1AI — add the ATR-projection level family to the catalog:** built as
  described above. Swing and profile families remain unbuilt. The two D-104
  gaps and the M9.1S quote-decision/M4.4-confidence gap stay recorded gaps with
  dependent rules off.
- [ ] **M9.1AJ — add the confirmed daily swing level family to the catalog:**
  proposed next sub-step (`DAILY_SWING_PLATEAU_2X2_V1` over 63 completed
  sessions; the bar profile follows). Independent review must confirm
  eligibility before the controller advances.

## M9.1AJ part 1 — confirmed daily swing level family added to the catalog; no search run — 2026-09-18 Pacific

`build_daily_swings` in `consensus_engine/core_price_features.py` builds
`DAILY_SWING_PLATEAU_2X2_V1` (packet 4.3) from a daily `HistoryBatch`: the 63
immediately preceding completed sessions, daily bars only. A plateau is a
maximal run of exactly equal highs (lows); it is confirmed only if both left and
both right neighbors are strictly below (above) and the run does not touch a
series edge. A certified no-trade session breaks a run and is never a neighbor.
A missing session, wrong interval or unknown basis gives `UNKNOWN`; a complete
window with no swing gives `KNOWN_EMPTY`. `build_orb5_level_catalog` takes an
optional `daily_history` and `evaluated_at` and adds `DAILY_SWING_HIGH` and
`DAILY_SWING_LOW` levels; without them `DAILY_SWING` stays `UNKNOWN`
(`MISSING_DAILY_HISTORY`). The prior-session bar profile is still `UNKNOWN`, so
`complete` is still false (D-104).

New case `test_daily_swings_use_two_strict_neighbors_and_plateaus` in
`tests/trade_alerts_contracts/test_core_price_features.py`. The controller's
published stages will supply the official counts and timings; this session made
no self-run of the contracts family.

Not built: the prior-session bar profile, real training-session inputs and any
real run. No application ran, no signal, trade or result was produced, no
provider call and no spend occurred. The reopened parent `M9.1 — Historical
replay #1-4` is still not complete.

- [!] **M9.1AJ — add the confirmed daily swing level family to the catalog:**
  built as described above. The bar profile remains unbuilt. The two D-104 gaps
  and the M9.1S quote-decision/M4.4-confidence gap stay recorded gaps with
  dependent rules off.
- [ ] **M9.1AK — add the prior-session bar profile level family to the catalog:**
  proposed next sub-step (`PRIOR_SESSION_BAR_PROFILE_V1`, packet 4.6, from the
  prior session's one-minute bars). Independent review must confirm eligibility
  before the controller advances.

## M9.1AK part 1 — prior-session bar profile level family added to the catalog; no search run — 2026-09-18 Pacific

`build_prior_session_profile` in `consensus_engine/core_price_features.py` builds
`PRIOR_SESSION_BAR_PROFILE_V1` (packet 4.6, `BAR_APPROX_PROFILE`) from the prior
regular session's one-minute bars: bin width is `max(1, ceil(0.01 * ATR / tick))`
ticks, volume is spread evenly over price inside each bar (a flat bar goes to its
bin, the last bin keeps its upper edge), POC ties go to the midpoint nearest the
prior close then the lower one, and the 70% value area grows one adjacent bin at
a time by the same tie order. All arithmetic is exact fractions. The prior close
and daily ATR are the snapshot's own values at the same evaluation time, so the
ATR is the one that closed with the prior session. Any unexplained minute slot,
missing input, invalid tick, no positive-volume bar or mismatched minute/daily
basis gives `UNKNOWN` with a reason; nothing is filled in (D-104).
`build_orb5_level_catalog` takes optional `minute_history` and `tick`, and adds
`PROFILE_POC`, `PROFILE_VAL` and `PROFILE_VAH`. Without them the family stays
`UNKNOWN`, so `complete` is false. The old `NOT_BUILT` table is gone.

New case `test_prior_session_bar_profile_bins_poc_and_value_area` in
`tests/trade_alerts_contracts/test_core_price_features.py`. Pytest outside the
launcher skips these files, so no result is claimed here; the controller's
protected stages will supply the counts and timings. This session did not
self-run the contracts family.

All four packet 4 catalog families are now built. Not built: real
training-session inputs (bars, tick, a session builder that feeds the catalog
into the grid run) and any real run. No application ran, no signal, trade or
result was produced, no provider call and no spend occurred. The reopened parent
`M9.1 — Historical replay #1-4` is still not complete.

- [!] **M9.1AK — add the prior-session bar profile level family to the catalog:**
  built as described above. Real inputs and any run remain unstarted. The two
  D-104 gaps and the M9.1S quote-decision/M4.4-confidence gap stay recorded gaps
  with dependent rules off.
- [ ] **M9.1AL — build one ORB5 session record from supplied bars and the
  catalog:** proposed next sub-step (assemble `Orb5Session` from minute/daily
  history, the snapshot and the catalog producer, so the grid run needs no
  hand-made levels). Independent review must confirm eligibility before the
  controller advances.

## M9.1AL part 1 — one ORB5 session record built from supplied bars and the catalog; no search run — 2026-09-18 Pacific

`build_orb5_session` in the new `consensus_engine/orb5_session_builder.py` builds a
`FeatureSnapshot` from supplied minute, daily and optional premarket history, then
one `Orb5LevelCatalog` for each direction and each opening range (5 and 15
minutes), and returns an `Orb5Session`. `Orb5Session` gained a `catalogs` field
keyed by `(direction, opening-range minutes)`; `run_orb5_grid` uses a present key
over the old single `levels`/`catalog_complete` pair, because the measured-move
level depends on both (the old fields still work as the fallback). An opening
range not finished at `evaluated_at` is unavailable, so a 15-minute catalog never
reads later bars. The prior-session profile reads a separately supplied prior
session minute history. ATR, tick and the entry fill stay caller-supplied (the
D-106 quote fill still does not exist). Any family the inputs cannot prove stays
`UNKNOWN`, the catalog incomplete and the trade unresolved (D-104).

New case `test_session_builder_keys_catalogs_by_direction_and_opening_range_without_lookahead`
in `tests/trade_alerts_contracts/test_orb5_research_adapter.py`. Pytest outside the
launcher skips that file, so no protected result is claimed; the controller's
protected stages will supply counts and timings. This session did not self-run the
contracts family.

Not built: real training-session inputs (a loader that supplies real bars, tick,
ATR and prior-session history per ticker-day) and any real run. No application
ran, no signal, trade or result was produced, no provider call and no spend
occurred. The reopened parent `M9.1 — Historical replay #1-4` is still not
complete.

- [!] **M9.1AL — build one ORB5 session record from supplied bars and the
  catalog:** built as described above. Real inputs and any run remain unstarted.
  The two D-104 gaps and the M9.1S quote-decision/M4.4-confidence gap stay
  recorded gaps with dependent rules off.
- [ ] **M9.1AM — feed real training-session bars into `build_orb5_session`:**
  proposed next sub-step (load per ticker-day minute, daily and prior-session
  history from the existing local files, build the sessions, no search run).
  Independent review must confirm eligibility before the controller advances.

## M9.1AM part 1 — training-session records built from grouped bars; no search run — 2026-09-18 Pacific

`build_training_sessions` in the new `consensus_engine/orb5_training_sessions.py`
takes the output of `search_run_bars.group_session_bars` and a list of
(ticker, session) pairs, wraps each day's bars and the previous regular session's
bars as `HistoryBatch` values, and calls `build_orb5_session`. A pair with no
usable bars or a degraded session is listed in `skipped` with its reason and no
session is built. A day with no loaded prior session is listed in
`without_prior_session`, and its prior-session family stays `UNKNOWN`. Daily
history is not in the retained minute files and is not derived from minutes, so
the families that need it stay `UNKNOWN` and the catalog incomplete (D-104). ATR
and tick come only from the caller's mappings. No entry price or time is set,
because the D-106 quote fill does not exist, so these sessions resolve no trade
yet. The evaluation time is the open plus a caller-stated number of minutes, and
it must be at least the longer opening range.

New case `test_training_sessions_skip_degraded_and_missing_days_and_fill_nothing_in`
in `tests/trade_alerts_contracts/test_orb5_research_adapter.py`. It is offline
and synthetic, so it proves only that contract. Pytest outside the launcher skips
that file. The controller's protected stages will supply counts and timings. This
session did not self-run the contracts family.

Not built: the reading of the real retained files into these sessions
(`open_core17_ohlcv_1m_file` for the real bars, the condition list, real ATR and
tick), a real daily-bar source, and any real run. No application ran, no signal,
trade or result was produced, no provider call and no spend occurred. The
reopened parent `M9.1 — Historical replay #1-4` is still not complete.

- [!] **M9.1AM — feed real training-session bars into `build_orb5_session`:**
  the pure grouping-to-session step is built as described above. The real-file
  read and any run remain unstarted. The two D-104 gaps and the M9.1S
  quote-decision/M4.4-confidence gap stay recorded gaps with dependent rules off.
- [ ] **M9.1AN — read the retained `core17-1y` files into the session builder:**
  proposed next sub-step (call the existing loader on the local retained files
  for the training dates, group, and build the sessions, with no search run).
  Independent review must confirm eligibility before the controller advances.

## M9.1AN part 1 — retained `core17-1y` files read into the session builder; no search run — 2026-09-18 Pacific

`load_retained_training_sessions` in the new `consensus_engine/orb5_retained_sessions.py`
opens each caller-named retained monthly file with `open_core17_ohlcv_1m_file`
(which checks the file's sha256 against its manifest first), groups the records
for the tickers in the requested pairs, and calls `build_training_sessions`. Empty
or duplicate file lists and empty pairs are refused. A prior-session day in an
unnamed file is not loaded, so its family stays `UNKNOWN` (D-104). No entry is
set and no search is run. The opener is injectable so the offline contract needs
no real file.

New case `test_retained_file_loader_opens_named_files_and_builds_sessions` in
`tests/trade_alerts_contracts/test_orb5_research_adapter.py`. It is synthetic and
proves only that contract. Pytest outside the launcher skips that file, so no
result is claimed; the controller's protected stages will supply counts and
timings. This session did not self-run the contracts family.

Not built: a real run over the retained files, real ATR and tick, a real daily
bar source and the D-106 quote fill. No application ran, no signal, trade or
result was produced, no provider call and no spend occurred. The reopened parent
`M9.1 — Historical replay #1-4` is still not complete.

- [!] **M9.1AN — read the retained `core17-1y` files into the session builder:**
  the loader is built as described above. Real reading, ATR/tick inputs and any
  run remain unstarted. The two D-104 gaps and the M9.1S
  quote-decision/M4.4-confidence gap stay recorded gaps with dependent rules off.
- [ ] **M9.1AO — supply real ATR and tick per ticker-day to the retained-file loader:**
  proposed next sub-step (derive or read the inputs from existing local sources
  without proxies; unavailable ones stay recorded gaps). Independent review must
  confirm eligibility before the controller advances.

## M9.1AO part 1 — ATR and tick source check; both stay recorded gaps — 2026-09-18 Pacific

This step looked for a real ATR value per ticker-day and a real tick per ticker in
existing local sources, without a proxy. The retained `core17-1y` files hold only
1-minute bars. Daily history is not in them, and daily ATR is not derived from
minutes (OQ-006, the exact ATR convention, is still open). No tick-size table exists
in the retained files or the project sources for these tickers. So no ATR or tick
mapping was built. `load_retained_training_sessions` keeps taking them only from the
caller, and a missing one stays `None` and its dependent rules stay off and labelled
untested (D-104). No code, test or config changed in this step.

No application ran, no signal, trade or result was produced, no provider call and
no spend occurred. The reopened parent `M9.1 — Historical replay #1-4` is still not
complete.

- [!] **M9.1AO — supply real ATR and tick per ticker-day to the retained-file loader:**
  no real ATR or tick source exists locally; both are recorded gaps with dependent
  rules off. The real daily-bar source (a separate data gate) and the D-106 quote
  fill remain unbuilt.
- [ ] **M9.1AP — run the retained-file loader over the local `core17-1y` files with ATR and tick left unset:**
  proposed next sub-step (count built, skipped and no-prior-session ticker-days only;
  no entry, no trade, no result). Independent review must confirm eligibility before
  the controller advances.

## M9.1AP part 1 — retained-file loader run over the local `core17-1y` files; counts only — 2026-09-18 Pacific

This step ran the existing `load_retained_training_sessions` once per ticker group
over the 13 local retained `ohlcv-1m` monthly files (job `EQUS-20260916-47J8PRKRBB`,
sha256 checked against its manifest by the opener) for all 17 D-102 names and all 261
dates in the retained `condition.json`. Evaluation was 15 minutes after the open (the
longer opening range). Conventions were `timestamp=START`, `session=REGULAR`, every
other label left `UNKNOWN`. ATR and tick were left unset (recorded gaps, see M9.1AO).
No code, test or config changed; the throwaway runner lived outside the project
(`/tmp/m91ap_run.py`, not kept as a product file). Counts only; no entry, trade,
signal, return or result was produced or looked at.

| group | tickers | ticker-days | built | skipped (degraded) | skipped (no usable bars) | no prior session | run seconds |
|---|---|---|---|---|---|---|---|
| ETF | SPY QQQ IWM XLV GLD USO VXX | 1827 | 1743 | 14 | 70 | 14 | 536 |
| stock | NVDA MSFT AAPL GOOGL AMZN META AVGO TSLA BRK.B LLY | 2610 | 2490 | 20 | 100 | 20 | 711 |
| total | 17 | 4437 | 4233 | 34 | 170 | 34 | (two runs in parallel) |

An SPY-only trial run gave 249 built, 2 degraded, 10 no usable bars, 2 no prior
session, consistent with the ETF group. The 10 no-usable-bar days per ticker were not
checked against the market calendar here, so no reason is claimed for them. Built
sessions still have daily-history families `UNKNOWN`, ATR/tick `None` and no entry
(D-106 quote fill not built), so they resolve no trade and the catalog is incomplete;
dependent rules stay off and labelled untested (D-104). The read shows the retained
files load and group; it is not source qualification, and the point-in-time
membership, original-availability and finality gaps stand. Not repeated in a second
fresh process; no protected test was added or run for this step, because nothing
testable changed. No provider call and no spend occurred. The reopened parent
`M9.1 — Historical replay #1-4` is still not complete.

- [!] **M9.1AP — run the retained-file loader over the local `core17-1y` files with ATR and tick left unset:**
  the run is done as counted above. No entry, trade or result exists; the D-104 gaps and
  the M9.1S quote-decision/M4.4-confidence gap stay recorded gaps with dependent rules off.
- [ ] **M9.1AQ — explain the 170 no-usable-bar and 34 degraded ticker-days from the retained files:**
  proposed next sub-step (list them by date against the retained condition list only;
  no proxy, no fill). Independent review must confirm eligibility before the controller advances.

## M9.1AQ part 1 — the skipped ticker-days listed by date; counts only — 2026-09-18 Pacific

This step re-ran the existing `load_retained_training_sessions` for two tickers
(SPY as ETF, NVDA as EQUITY) over the same 13 retained files, evaluation 15
minutes after the open, and listed the skipped and no-prior-session dates. The
throwaway runner lived outside the project (`/tmp/m91aq_run.py`). No code, test or
config changed. Both tickers gave the same 12 skipped dates and 2 no-prior dates:

- DEGRADED_SESSION: 2025-10-10 and 2025-10-13. The retained `condition.json` marks
  exactly these two of its 261 dates `degraded` (259 are `available`), so the
  skips match the provider's own degraded-date flags. They stay skipped; nothing
  was filled in.
- NO_USABLE_BARS (10): 2025-11-27, 2025-12-25, 2026-01-01, 2026-01-19, 2026-02-16,
  2026-04-03, 2026-05-25, 2026-06-19, 2026-07-03, 2026-09-07. These are weekdays
  in the condition list that hold no regular-session bars in the files. They match
  the usual US exchange full-closure weekdays (Thanksgiving, Christmas, New
  Year's Day, MLK Day, Presidents Day, Good Friday, Memorial Day, Juneteenth,
  Independence Day observed, Labor Day) by general knowledge only. No official
  calendar source was checked here, so that match is a reading, not qualification.
- No prior session: 2025-09-15 (first retained date) and 2025-10-14 (the day after
  the degraded 2025-10-13 was skipped). Their prior-session family stays `UNKNOWN`.

Per-ticker counts from M9.1AP (10 no-usable-bar, 2 degraded, 2 no-prior per
ticker) fit this list, but the other 15 tickers' dates were not listed here.
Nothing is a signal, trade or result. No protected test was added or run because
nothing testable changed. The point-in-time membership, original-availability and
finality gaps stand. No provider call and no spend occurred. The reopened parent
`M9.1 — Historical replay #1-4` is still not complete.

- [!] **M9.1AQ — explain the 170 no-usable-bar and 34 degraded ticker-days from the retained files:**
  explained for SPY and NVDA as above; the D-104 gaps and the M9.1S
  quote-decision/M4.4-confidence gap stay recorded gaps with dependent rules off.
- [ ] **M9.1AR — confirm the other 15 tickers skip the same 12 dates:**
  proposed next sub-step (list skipped dates per ticker from the retained files; no
  proxy, no fill, no entry or result). Independent review must confirm eligibility
  before the controller advances.

## M9.1AR part 1 — the other 15 tickers skip the same 12 dates; counts only — 2026-09-18 Pacific

This step re-ran the existing `load_retained_training_sessions` once per ticker
(evaluation 15 minutes after the open, `timestamp=START`, `session=REGULAR`, other
labels `UNKNOWN`) over the same 13 retained `ohlcv-1m` files for the 15 D-102 names
not listed in M9.1AQ: QQQ, IWM, XLV, GLD, USO, VXX (ETF) and MSFT, AAPL, GOOGL, AMZN,
META, AVGO, TSLA, BRK.B, LLY (EQUITY). The throwaway runner lived outside the project
(`/tmp/m91ar_run.py`, the M9.1AQ runner reused unchanged). No code, test or config
changed. Every one of the 15 tickers returned exactly the same 12 skipped dates as SPY
and NVDA in M9.1AQ (2 DEGRADED_SESSION: 2025-10-10, 2025-10-13; 10 NO_USABLE_BARS:
2025-11-27, 2025-12-25, 2026-01-01, 2026-01-19, 2026-02-16, 2026-04-03, 2026-05-25,
2026-06-19, 2026-07-03, 2026-09-07) and the same 2 no-prior-session dates
(2025-09-15, 2025-10-14). With SPY and NVDA that is all 17 tickers, so the M9.1AP
totals (170 no usable bars, 34 degraded, 34 no prior) equal 17 x 10, 17 x 2 and 17 x 2.
The no-usable-bar dates still match exchange closures by general knowledge only; no
official calendar was checked, so that is a reading, not qualification. Nothing is a
signal, trade or result. No protected test was added or run because nothing testable
changed; not repeated in a second process. Point-in-time membership, original-availability
and finality gaps stand. No provider call and no spend occurred. The reopened parent
`M9.1 — Historical replay #1-4` is still not complete.

- [!] **M9.1AR — confirm the other 15 tickers skip the same 12 dates:**
  confirmed as above; the D-104 gaps and the M9.1S quote-decision/M4.4-confidence gap
  stay recorded gaps with dependent rules off.
- [ ] **M9.1AS — check the 10 no-usable-bar dates against an official exchange holiday calendar:**
  proposed next sub-step (read-only, only a source already local or free public official
  page; if none is available record the gap; no proxy, no fill, no entry or result).
  Independent review must confirm eligibility before the controller advances.

## M9.1AS part 1 — 8 of the 10 no-usable-bar dates match the official NYSE holiday page; 2 stay a recorded gap — 2026-09-18 Pacific

This step made one free, read-only HTTP GET of the public NYSE "Holidays & Trading
Hours" page (`https://www.nyse.com/trade/hours-calendars`, HTTP 200, no login, no
credential, no provider account, no spend, no retry). The page says all NYSE markets
observe the listed holidays "for 2026, 2027, and 2028". It lists, for 2026: New Year's
Day Thursday January 1; Martin Luther King, Jr. Day Monday January 19; Washington's
Birthday Monday February 16; Good Friday Friday April 3; Memorial Day Monday May 25;
Juneteenth Friday June 19; Independence Day observed Friday July 3; Labor Day Monday
September 7. These match exactly 8 of the 10 NO_USABLE_BARS dates from M9.1AQ/AR:
2026-01-01, 2026-01-19, 2026-02-16, 2026-04-03, 2026-05-25, 2026-06-19, 2026-07-03,
2026-09-07. Those 8 are now confirmed as official full-closure days, so their skip is
correct on an official source, not only by general knowledge.

The other 2 dates, 2025-11-27 (Thanksgiving) and 2025-12-25 (Christmas), are NOT on
that page: it has no 2025 column. They stay a recorded gap, still a reading by general
knowledge only. No proxy, no fill, no other source was tried. The 2 DEGRADED_SESSION
dates (2025-10-10, 2025-10-13) are provider flags, not holidays, and were not part of
this check. The throwaway parse ran outside the project on a `/tmp` copy of the page.
No code, test or config changed; no protected test was added or run because nothing
testable changed. Nothing is a signal, trade or result. Point-in-time membership,
original-availability and finality gaps stand. The reopened parent
`M9.1 — Historical replay #1-4` is still not complete.

- [!] **M9.1AS — check the 10 no-usable-bar dates against an official exchange holiday calendar:**
  done for 8 of 10 as above; 2025-11-27 and 2025-12-25 remain a recorded gap; the D-104
  gaps and the M9.1S quote-decision/M4.4-confidence gap stay recorded gaps with
  dependent rules off.
- [ ] **M9.1AT — check 2025-11-27 and 2025-12-25 against an official 2025 exchange holiday source:**
  proposed next sub-step (read-only; only a source already local or a free public official
  page that lists 2025; if none is available record the gap; no proxy, no fill, no entry
  or result). Independent review must confirm eligibility before the controller advances.

## M9.1AT part 1 — the free public NYSE pages have no 2025 column; 2 dates stay a recorded gap — 2026-09-18 Pacific

This step made two free, read-only HTTP GETs of public NYSE pages, no login, no
credential, no provider account, no spend, no retry. `nyse.com/publicdocs/nyse/markets/nyse/NYSE_Holidays.pdf`
returned HTTP 404. `nyse.com/markets/hours-calendars` returned HTTP 200 (same
"for 2026, 2027, and 2028" page as M9.1AS); the saved copy has zero occurrences of
"2025" and lists Thanksgiving Day and Christmas Day only in the 2026-2028 tables. So
2025-11-27 and 2025-12-25 are still NOT confirmed on an official source and remain a
recorded gap, a reading by general knowledge only. No proxy, no fill, no other source
was tried. The throwaway fetch ran outside the project on `/tmp` copies. No code, test
or config changed; no protected test was added or run because nothing testable changed.
Nothing is a signal, trade or result. Point-in-time membership, original-availability
and finality gaps stand. The reopened parent `M9.1 — Historical replay #1-4` is still
not complete.

- [!] **M9.1AT — check 2025-11-27 and 2025-12-25 against an official 2025 exchange holiday source:**
  the two free public NYSE pages tried list no 2025; both dates stay a recorded gap; the
  D-104 gaps and the M9.1S quote-decision/M4.4-confidence gap stay recorded gaps with
  dependent rules off.
- [ ] **M9.1AU — look for a 2025 holiday listing already stored locally:**
  proposed next sub-step (read-only, local files only, no provider call or spend; if none
  lists 2025 keep the gap and stop this calendar thread; no proxy, no fill, no entry or
  result). Independent review must confirm eligibility before the controller advances.

## M9.1AU part 1 — a local third-party calendar lists both 2025 dates; still no official 2025 source — 2026-09-18 Pacific

This step was local and read-only: no provider call, no network, no credential, no
spend. A search of the project files (excluding `.claude`, `.firecrawl`, `.git` and this
ROADMAP) found no stored holiday listing that names 2025-11-27 or 2025-12-25. The
project's `pandas_market_calendars` package (version 5.3.2, already used by
`consensus_engine/utils/time_context.py`) has an NYSE calendar that lists both dates as
holidays. That is a third-party library, not an official exchange source, so it is only
corroboration of the general-knowledge reading. It does not close the gap: the two dates
are still not confirmed on an official source. `config/consensus.yaml`
`alfred.market_holidays` is an empty list. No proxy, no fill, no entry or result. No
code, test or config changed and no protected test was added or run because nothing
testable changed. The calendar thread stops here: no further free official 2025 source is
known. Point-in-time membership, original-availability and finality gaps stand. The
reopened parent `M9.1 — Historical replay #1-4` is still not complete.

- [!] **M9.1AU — look for a 2025 holiday listing already stored locally:**
  no stored official listing; only the third-party package calendar lists both dates
  (corroboration, not official); both dates stay a recorded gap; the D-104 gaps and the
  M9.1S quote-decision/M4.4-confidence gap stay recorded gaps with dependent rules off.
- [ ] **M9.1AV — record the parent M9.1 state after the calendar thread closes:**
  proposed next sub-step (records only: list which #1-4 replay pieces are done, which
  rules are off because of D-104 gaps, and the one remaining concrete data or owner
  boundary; no proxy, no fill, no entry or result). Independent review must confirm
  eligibility before the controller advances.

## M9.1AV part 1 — parent M9.1 state after the calendar thread closes — 2026-09-18 Pacific

Records only. No code, test, config or input changed; no protected test was added or
run; no provider call, credential read, network call or spend occurred. Nothing here is
a signal, trade or result.

Done (each accepted or recorded in its own row above):
- Shared pieces: core17-1y bulk loader (M9.1A), D-106/D-107 fill and cost model
  (M9.1B), outcome evaluator (M9.1C), research-bar accessor (M9.1D), frozen parameter
  grid and train/held-out split (M9.1T), D-108 success-bar evaluator (M9.1U).
- Bar-native inputs have real-data coverage for all four playbooks (M9.1E-S);
  the `FIRST_PULLBACK_VWAP` quote decision and M4.4 confidence are a recorded gap (M9.1S).
- `CRVOL_ORB5`: bar-native research adapter, crossing/geometry/walk, quote-based entry
  fill, D090 structure exit, structural level catalog families, session builder and the
  retained-file loader (M9.1Y-AN). The loader ran over the 13 local retained `ohlcv-1m`
  files for all 17 names and 261 dates: 4437 ticker-days, 4233 built, 34 degraded and
  170 no-usable-bar skipped, 34 with no prior session (M9.1AP), identical 12 skipped
  dates for every ticker (M9.1AQ, M9.1AR).
- Calendar thread: 8 of the 10 no-usable-bar dates match the official NYSE 2026-2028
  page (M9.1AS); 2025-11-27 and 2025-12-25 have no official 2025 source found and stay
  a recorded gap, with only the third-party package calendar as corroboration (M9.1AT,
  M9.1AU). The thread is closed.

Rules off and labelled untested (D-104): anything needing original availability or
finality, point-in-time membership, historical borrow, or complete-chain proof; the
`FIRST_PULLBACK_VWAP` quote decision and M4.4 confidence; ATR and tick (no local source,
M9.1AO), so built sessions keep daily-history families `UNKNOWN` and resolve no trade.

Not done: the stage-1 grid run on the training nine, the stage-2 combination search and
the stage-3 held-out D-108 pass have not started for any playbook; the other three
playbooks have no retained-file loader run. The one remaining concrete boundary is the
missing real ATR/tick per ticker-day (a data gate); the source/qualification, final-date
and live gates stand. The reopened parent `M9.1 — Historical replay #1-4` is still not
complete.

- [!] **M9.1AV — record the parent M9.1 state after the calendar thread closes:**
  recorded as above; the parent stays incomplete; the D-104 gaps and the M9.1S
  quote-decision/M4.4-confidence gap stay recorded gaps with dependent rules off.
- [ ] **M9.1AW — decide whether ATR can come from the retained bars' own daily aggregates:**
  proposed next sub-step (read-only assessment against the retained files and D-104: is
  a prior-session ATR derivable without proxy or fill; tick stays a gap unless a real
  source exists; no entry, no result). Independent review must confirm eligibility
  before the controller advances.

## M9.1AW part 1 — ATR from the retained bars' own daily aggregates: not derivable without a proxy; stays a recorded gap — 2026-09-18 Pacific

Records only. No code, test, config or input changed; no protected test was added or
run; no provider call, credential read, network call or spend occurred. Nothing here is
a signal, trade or result.

Read-only assessment against the frozen definition and the shared code:
- `DAILY_ATR_14_SMA_V1` (M0_3_DEFINITION_PACKET) needs the 15 immediately preceding
  completed regular sessions of daily bars, true range against the preceding daily
  close, and says a missing session or adjustment reference is `UNKNOWN`, with no
  older-day substitute.
- The shared builder (`consensus_engine/core_price_features.py`, `_daily`) reads a
  `1d` history batch with its own coverage record. The retained `core17-1y` files are
  `ohlcv-1m` only, so there is no `1d` batch, coverage record or adjustment reference.
- Building daily high, low and close by aggregating the minute bars would be a
  substitute for that daily source, not the source itself: the minute files come from
  the `EQUS.MINI` venue-aggregated feed, whose daily high, low and close can differ
  from an official daily bar, and OQ-006 (the exact ATR convention) is still open.
  D-104 says a field that cannot be obtained is recorded as a gap and never
  approximated, so ATR is not derived this way.
- Tick has no local source (M9.1AO) and stays a gap.

Result: ATR and tick stay recorded gaps. Every rule that needs them stays off and
labelled untested: the daily-ATR families, the ATR buffer and stop pad, and so any
trade resolution in the built sessions. The real daily-bar source (a separate data
gate) is still needed. The reopened parent `M9.1 — Historical replay #1-4` is still
not complete.

- [!] **M9.1AW — decide whether ATR can come from the retained bars' own daily aggregates:**
  no; that would be a proxy for a missing `1d` source (D-104); ATR and tick stay
  recorded gaps with dependent rules off.
- [ ] **M9.1AX — run the retained-file loader for the other three playbooks' bar-native inputs:**
  proposed next sub-step (counts only over the local `core17-1y` files for playbooks
  #2-4, ATR and tick left unset; no entry, no trade, no result). Independent review
  must confirm eligibility before the controller advances.

## M9.1AX part 1 — no retained-file loader exists for playbooks #2-4; nothing run; the missing piece is named — 2026-09-18 Pacific

Records only. No code, test, config or input changed; no protected test was added or
run; no provider call, credential read, network call or spend occurred. Nothing here is
a signal, trade or result.

Read-only check of the shared code against this step's proposal:
- The M9.1AP loader (`load_retained_training_sessions`) feeds only the `CRVOL_ORB5`
  session builder. Its chain is retained file -> `group_session_bars` ->
  `build_training_sessions` -> `Orb5Session`. It is `CRVOL_ORB5`-specific.
- Playbooks #2-4 (`HOD_COMP_RS`, `OR_FAILURE_REV`, `FIRST_PULLBACK_VWAP`) have
  bar-native research adapters (M9.1E-S) that each take one supplied history batch and
  a decision moment. No code turns grouped retained bars into those batches per
  ticker-day, and no code chooses the decision moments. So there is nothing existing to
  "run" over the retained files for #2-4; a count would need a new builder plus offline
  tests, which is a code step and not a run.
- Some adapters take a 1-minute ATR (`atr_1m`). That is a different input from the
  daily ATR ruled a gap in M9.1AW. Whether a 1-minute ATR can be read from the same
  retained minute bars without a proxy has not been assessed and stays open; until it
  is, those inputs stay unset and dependent rules off (D-104).
- `FIRST_PULLBACK_VWAP` keeps its quote decision and M4.4 confidence as a recorded gap
  (M9.1S).

Result: the step as proposed cannot be run with existing code. The parent
`M9.1 — Historical replay #1-4` is still not complete; the stage-1 grid run, stage-2
search and stage-3 held-out D-108 pass have not started; the daily ATR/tick data gate
and the source/final/live gates stand.

- [!] **M9.1AX — run the retained-file loader for the other three playbooks' bar-native inputs:**
  not runnable: no #2-4 retained-file loader exists; handed to a code sub-step below.
- [ ] **M9.1AY — build the retained-file to history-batch builder for playbooks #2-4:**
  proposed next sub-step (offline code plus focused tests: group retained minute bars
  per ticker-day into the history batches the #2-4 adapters take, with `atr_1m` unset
  unless it is shown derivable from the same bars without a proxy; no entry, no trade,
  no result, no D-104 gap filled). Independent review must confirm eligibility before
  the controller advances.

## M9.1AY part 1 — retained-file history-batch builder for playbooks #2-4 built offline — 2026-09-18 Pacific

Offline code and focused tests only. No provider call, credential read, network call,
spend, real retained file read or run occurred. Nothing here is a signal, trade or result.

- New `consensus_engine/retained_history_batches.py`: `build_history_batches` and
  `load_retained_history_batches` group retained minute bars per named (ticker, session)
  pair and wrap each session, plus the prior session when it was loaded, as a
  `HistoryBatch`. The batches are the input the #2-4 research adapters take.
- A degraded or absent session is skipped with a reason; a missing prior session is
  listed, not filled; duplicate pairs and empty/duplicate file lists are rejected. The
  caller supplies the source conventions; nothing is defaulted.
- No decision moment is chosen and no entry is set. `atr_1m` is not produced: no
  derivation from the same bars without a proxy has been shown, so it stays unset and
  dependent rules stay off (D-104). Daily ATR/tick stay recorded gaps.
- New focused tests: `tests/trade_alerts_contracts/test_retained_history_batches.py`
  (3 cases, run with `test_orb5_research_adapter.py`; controller stage supplies the
  published counts).

The parent `M9.1 — Historical replay #1-4` is still not complete; source/final/live gates
stand.

- [x] **M9.1AY — build the retained-file to history-batch builder for playbooks #2-4:**
  builder and focused offline tests done; controller protected stages supply the proof.
- [ ] **M9.1AZ — choose the decision moments for playbooks #2-4 over the retained batches:**
  proposed next sub-step (offline code plus focused tests: a finite, preregistered list of
  decision moments per playbook applied to the batches from M9.1AY, with `atr_1m` unset;
  no entry, no trade, no result). Independent review must confirm eligibility before the
  controller advances.

## M9.1AZ part 1 — preregistered decision moments for playbooks #2-4 built offline — 2026-09-18 Pacific

Offline code and focused tests only. No provider call, credential read, network call,
spend, real retained file read or run occurred. Nothing here is a signal, trade or result.

- New `consensus_engine/retained_decision_moments.py`, version
  `M91AZ_DECISION_MOMENTS_V1`, fixed before any result: every 5 minutes from open+5
  through close-5 New York time (09:35-15:55 on a full day, 77 moments; early-close
  aware), the same grid for `HOD_COMP_RS`, `OR_FAILURE_REV` and `FIRST_PULLBACK_VWAP`,
  matching the M0.3I five-minute bands. Each playbook's own rules still decide
  eligibility at a moment. `plan_decision_moments` applies the grid to the M9.1AY
  batches; `atr_1m` stays unset and dependent rules stay off (D-104).
- New focused tests: `tests/trade_alerts_contracts/test_retained_decision_moments.py`
  (3 cases, run with `test_retained_history_batches.py`; controller stage supplies the
  published counts).

The parent `M9.1 — Historical replay #1-4` is still not complete; source/final/live gates
and the daily ATR/tick gap stand.

- [x] **M9.1AZ — choose the decision moments for playbooks #2-4 over the retained batches:**
  grid and focused offline tests done; controller protected stages supply the proof.
- [ ] **M9.1BA — run the #2-4 research adapters over the planned decision moments:**
  proposed next sub-step (offline code plus focused tests: call the existing bar-native
  adapters at each planned moment, count ready/not-ready inputs with reasons; no entry,
  no trade, no result; ATR/tick and quote inputs left as recorded gaps). Independent
  review must confirm eligibility before the controller advances.

## M9.1BA part 1 — #2-4 bar-native adapters run over the planned moments, built offline — 2026-09-18 Pacific

Offline code and focused tests only. No provider call, credential read, network call,
spend, real retained file read or run occurred. Nothing here is a signal, trade or result.

- New `consensus_engine/retained_adapter_run.py`, version `M91BA_ADAPTER_RUN_V1`:
  `run_adapters` calls, at each planned moment, the `OR_FAILURE_REV` tape/close reader and
  the `FIRST_PULLBACK_VWAP` last-trade and VWAP-level readers, and counts ready and
  not-ready moments per input with the adapter's own reason.
- Not called, listed in `NOT_CALLED` and left as recorded gaps with dependents off
  (D-104): `atr_1m`, VWAP slope/crosses, the quote decision and the `HOD_COMP_RS`
  policy-driven inputs. A missing instrument type is rejected, not defaulted.
- New focused tests: `tests/trade_alerts_contracts/test_retained_adapter_run.py`
  (2 cases, run with `test_retained_decision_moments.py`; controller stage supplies the
  published counts).

The parent `M9.1 — Historical replay #1-4` is still not complete; source/final/live gates
and the daily ATR/tick gap stand.

- [x] **M9.1BA — run the #2-4 research adapters over the planned decision moments:**
  runner and focused offline tests done; controller protected stages supply the proof.
- [ ] **M9.1BB — run the adapter counts over the retained files:**
  proposed next sub-step (a run over the real retained minute files for the named
  ticker-days, publishing ready/not-ready counts only; no entry, no trade, no result; needs
  an explicitly assigned read of retained files). Independent review must confirm
  eligibility before the controller advances.

## M9.1BB part 1 — retained-file to adapter-counts entry point built offline — 2026-09-18 Pacific

Offline code and focused tests only. No provider call, credential read, network call,
spend, real retained file read or run occurred. Nothing here is a signal, trade or result.

- New `consensus_engine/retained_count_run.py`, version `M91BB_RETAINED_COUNT_RUN_V1`:
  `run_retained_counts` chains the M9.1AY loader, the M9.1AZ moment plan and the M9.1BA
  adapter run and returns counts plus the skipped and no-prior-session lists. It picks no
  files or tickers; the caller supplies them, with the source conventions and instrument
  types. `NOT_CALLED` gaps stay recorded with dependents off (D-104).
- New focused tests: `tests/trade_alerts_contracts/test_retained_count_run.py` (2 cases;
  controller stage supplies the published counts).
- The run over the real retained files is NOT done: it needs an explicitly assigned read
  of retained files (named ticker-days, files, conventions), which this milestone was not
  given. Handed off, not accepted as a whole.

The parent `M9.1 — Historical replay #1-4` is still not complete; source/final/live gates
and the daily ATR/tick gap stand.

- [!] **M9.1BB — run the adapter counts over the retained files:**
  entry point and focused offline tests done; the real-file run is blocked on an
  explicitly assigned retained-file read. Handed to M9.1BC.
- [ ] **M9.1BC — publish adapter counts from the real retained files:**
  proposed next sub-step (execute `run_retained_counts` once over the named retained
  minute files under an explicit read assignment; publish ready/not-ready counts only; no
  entry, no trade, no result). Independent review must confirm eligibility and that the
  read is assigned before the controller advances.

## M9.1BC — real retained-file count run not assigned — 2026-09-18 Pacific

Records only. No code, test, provider call, credential read, network call, spend or
retained-file read occurred. The work packet for this milestone named no ticker-days, no
retained files and no source conventions, so there is no explicit read assignment. Nothing
here is a signal, trade or result. The `M91BB_RETAINED_COUNT_RUN_V1` entry point is
unchanged and still has no published counts from real files.

The parent `M9.1 — Historical replay #1-4` is still not complete; source/final/live gates
and the daily ATR/tick gap stand.

- [!] **M9.1BC — publish adapter counts from the real retained files:**
  blocked on an explicit read assignment (named ticker-days, files, source conventions,
  instrument types). Handed to M9.1BD.
- [ ] **M9.1BD — publish adapter counts once a retained-file read is assigned:**
  proposed next sub-step (execute `run_retained_counts` once over the assigned files;
  publish ready/not-ready counts only; no entry, no trade, no result). Independent review
  must confirm the read assignment exists before the controller advances.
  **The read assignment now exists: D-112 in DECISIONS_AND_OPEN_QUESTIONS.md**, recorded
  2026-09-19, naming the job directory, the manifest-verified files, the nine D-107
  training ticker-days, the per-ticker instrument types and the full `HistoryConventions`
  set. Use it verbatim; do not choose files, tickers or conventions yourself, and do not
  read the eight held-out names.

## M9.1BC — real retained-file count run executed, zero ready — 2026-09-19 Pacific

The D-112 read assignment was used verbatim: the 13 manifest-verified `*.dbn.zst` files
(all hashes matched), the nine D-107 training names only (NVDA, MSFT, AAPL, TSLA, LLY,
SPY, QQQ, XLV, USO), the D-112 instrument types and the full D-112 `HistoryConventions`
set, over the 261 session dates in `condition.json` (2349 ticker-day pairs). `run_retained_counts`
(`M91BB_RETAINED_COUNT_RUN_V1`) ran once, offline, local files only. No held-out name was
read. No code or test changed, and there was no provider call, credential read, spend, entry,
trade, R or profit figure. The full output is `M9_1BC_RETAINED_COUNTS.json` in this directory
(sha256 `c3020a51f101b2ca57e151c963e803ef8083dff402915747c43b8738f36fc0a9`). It was produced
by a run outside the protected launcher, so it is an observed record, not controller proof.

Counts published: 2241 sessions used; 108 ticker-days skipped (90 `NO_USABLE_BARS`,
18 `DEGRADED_SESSION`); 18 without a prior session; 515,727 decision moments called.
**Ready: 0.** Not ready, all `INCOMPATIBLE_PRICE_UNIT`: `FIRST_PULLBACK_VWAP` `last_trade`
171,909, `FIRST_PULLBACK_VWAP` `vwap_level` 171,909, `OR_FAILURE_REV` `tape_and_close` 171,909.
Not called, still recorded gaps with dependents off (D-104): `atr_1m`, `vwap_slope`,
`vwap_crosses`, `quote_decision`, `hod_comp_rs_policy_inputs`.

Cause found: the adapters accept only `conventions.price == "USD_PER_SHARE"` and
`conventions.volume == "SHARES"` (see `_basis_reason` in
`first_pullback_vwap_research_adapter.py`), while D-112 supplies the labels `TRADE` and
`TRADE`. This is a label mismatch between D-112 and the adapter vocabulary, not a finding
about the bars. Nothing was relabelled to make counts appear. Counts under other labels
would need a new supervisor decision that states the price and volume units.

The parent `M9.1 — Historical replay #1-4` is not complete; source/final/live gates, the
D-104 gaps and the daily ATR/tick gap stand.

- [x] **M9.1BC — publish adapter counts from the real retained files:** done; run executed
  once under D-112, counts above, zero ready.
- [x] **M9.1BD — publish adapter counts once a retained-file read is assigned:** covered by
  the same single run; no second run was made.
- [ ] **M9.1BE — record the price and volume unit labels for the retained bars:**
  proposed next sub-step. A supervisor decision must state the units the EQUS.MINI bars
  carry (D-112 gave `TRADE`, the adapters need `USD_PER_SHARE` and `SHARES`), then the
  count run is repeated under those labels. Independent review must confirm the decision
  exists before advancing; do not choose the labels in the builder.

## M9.1BE — unit labels not supplied — 2026-09-19 Pacific

Records only. No code, test, provider call, credential read, network call, spend or
retained-file read occurred. The work packet and DECISIONS_AND_OPEN_QUESTIONS.md hold no
decision after D-112, so no supervisor statement exists of the price and volume units the
EQUS.MINI bars carry. D-112 gives `TRADE` for both; the adapters accept only `USD_PER_SHARE`
and `SHARES`. The builder does not choose the labels, and nothing was relabelled. The
`M9_1BC_RETAINED_COUNTS.json` record (zero ready, all `INCOMPATIBLE_PRICE_UNIT`) is unchanged.

The parent `M9.1 — Historical replay #1-4` is not complete; source/final/live gates, the
D-104 gaps and the daily ATR/tick gap stand.

- [!] **M9.1BE — record the price and volume unit labels for the retained bars:**
  blocked on a supervisor decision that states the price and volume units (not written yet).
  Handed to M9.1BF.
- [ ] **M9.1BF — repeat the retained-file count run under decided unit labels:**
  proposed next sub-step. Runs only once a decision after D-112 states the units; then
  execute `run_retained_counts` once over the same D-112 files and nine training names and
  publish ready/not-ready counts only. Independent review must confirm the decision exists
  before advancing; do not choose the labels in the builder.

## M9.1BF — still no unit-label decision — 2026-09-19 Pacific

Records only. No code, test, provider call, credential read, network call, spend or
retained-file read occurred. DECISIONS_AND_OPEN_QUESTIONS.md still ends at D-112 and the work
packet carries no later decision, so no supervisor statement of the price and volume units the
EQUS.MINI bars carry exists. `run_retained_counts` was not run again; a repeat under the same
`TRADE` labels would give the same zero-ready result, and the builder does not choose labels.
`M9_1BC_RETAINED_COUNTS.json` is unchanged.

The parent `M9.1 — Historical replay #1-4` is not complete; source/final/live gates, the
D-104 gaps and the daily ATR/tick gap stand.

- [!] **M9.1BF — repeat the retained-file count run under decided unit labels:**
  blocked on a supervisor decision after D-112 that states the price and volume units (not
  written yet). Handed to M9.1BG.
- [ ] **M9.1BG — repeat the retained-file count run once a unit-label decision exists:**
  proposed next sub-step. When a decision after D-112 states the units, execute
  `run_retained_counts` once over the same D-112 files and nine training names and publish
  ready/not-ready counts only. Independent review must confirm the decision exists before
  advancing; do not choose the labels in the builder.

## M9.1BG — still no unit-label decision — 2026-09-19 Pacific

Records only. No code, test, provider call, credential read, network call, spend or
retained-file read occurred. DECISIONS_AND_OPEN_QUESTIONS.md still ends at D-112 and the work
packet carries no later decision, so no supervisor statement of the price and volume units the
EQUS.MINI bars carry exists. `run_retained_counts` was not run again; the builder does not
choose labels and nothing was relabelled. `M9_1BC_RETAINED_COUNTS.json` is unchanged.

The parent `M9.1 — Historical replay #1-4` is not complete; source/final/live gates, the
D-104 gaps and the daily ATR/tick gap stand.

- [!] **M9.1BG — repeat the retained-file count run once a unit-label decision exists:**
  blocked on a supervisor decision after D-112 that states the price and volume units (not
  written yet). Handed to M9.1BH.
- [ ] **M9.1BH — repeat the retained-file count run once a unit-label decision is written:**
  proposed next sub-step. When a decision after D-112 states the units, execute
  `run_retained_counts` once over the same D-112 files and nine training names and publish
  ready/not-ready counts only. Independent review must confirm the decision exists before
  advancing; do not choose the labels in the builder.

## M9.1BH — still no unit-label decision — 2026-09-19 Pacific

Records only. No code, test, provider call, credential read, network call, spend or
retained-file read occurred. DECISIONS_AND_OPEN_QUESTIONS.md still ends at D-112 and the work
packet carries no later decision, so no supervisor statement of the price and volume units the
EQUS.MINI bars carry exists. `run_retained_counts` was not run again; the builder does not
choose labels and nothing was relabelled. `M9_1BC_RETAINED_COUNTS.json` is unchanged.

The parent `M9.1 — Historical replay #1-4` is not complete; source/final/live gates, the
D-104 gaps and the daily ATR/tick gap stand.

- [!] **M9.1BH — repeat the retained-file count run once a unit-label decision is written:**
  blocked on a supervisor decision after D-112 that states the price and volume units (not
  written yet). Handed to M9.1BI.
- [ ] **M9.1BI — repeat the retained-file count run once a unit-label decision is recorded:**
  proposed next sub-step. When a decision after D-112 states the units, execute
  `run_retained_counts` once over the same D-112 files and nine training names and publish
  ready/not-ready counts only. Independent review must confirm the decision exists before
  advancing; do not choose the labels in the builder.

## M9.1BI — still no unit-label decision — 2026-09-19 Pacific

Records only. No code, test, provider call, credential read, network call, spend or
retained-file read occurred. DECISIONS_AND_OPEN_QUESTIONS.md still ends at D-112 and the work
packet carries no later decision, so no supervisor statement of the price and volume units the
EQUS.MINI bars carry exists. `run_retained_counts` was not run again; the builder does not
choose labels and nothing was relabelled. `M9_1BC_RETAINED_COUNTS.json` is unchanged.

The parent `M9.1 — Historical replay #1-4` is not complete; source/final/live gates, the
D-104 gaps and the daily ATR/tick gap stand.

- [!] **M9.1BI — repeat the retained-file count run once a unit-label decision is recorded:**
  blocked on a supervisor decision after D-112 that states the price and volume units (not
  written yet). Handed to M9.1BJ.
- [ ] **M9.1BJ — repeat the retained-file count run once a unit-label decision is on file:**
  proposed next sub-step. When a decision after D-112 states the units, execute
  `run_retained_counts` once over the same D-112 files and nine training names and publish
  ready/not-ready counts only. Independent review must confirm the decision exists before
  advancing; do not choose the labels in the builder.

## M9.1BJ — still no unit-label decision — 2026-09-19 Pacific

Records only. No code, test, provider call, credential read, network call, spend or
retained-file read occurred. DECISIONS_AND_OPEN_QUESTIONS.md still ends at D-112 and the work
packet carries no later decision, so no supervisor statement of the price and volume units the
EQUS.MINI bars carry exists. `run_retained_counts` was not run again; the builder does not
choose labels and nothing was relabelled. `M9_1BC_RETAINED_COUNTS.json` is unchanged.

The parent `M9.1 — Historical replay #1-4` is not complete; source/final/live gates, the
D-104 gaps and the daily ATR/tick gap stand.

- [!] **M9.1BJ — repeat the retained-file count run once a unit-label decision is on file:**
  blocked on a supervisor decision after D-112 that states the price and volume units (not
  written yet). Handed to M9.1BK.
- [ ] **M9.1BK — repeat the retained-file count run once a unit-label decision exists on record:**
  proposed next sub-step. When a decision after D-112 states the units, execute
  `run_retained_counts` once over the same D-112 files and nine training names and publish
  ready/not-ready counts only. Independent review must confirm the decision exists before
  advancing; do not choose the labels in the builder.

## M9.1BK — still no unit-label decision — 2026-09-19 Pacific

Records only. No code, test, provider call, credential read, network call, spend or
retained-file read occurred. DECISIONS_AND_OPEN_QUESTIONS.md still ends at D-112 and the work
packet carries no later decision, so no supervisor statement of the price and volume units the
EQUS.MINI bars carry exists. `run_retained_counts` was not run again; the builder does not
choose labels and nothing was relabelled. `M9_1BC_RETAINED_COUNTS.json` is unchanged.

The parent `M9.1 — Historical replay #1-4` is not complete; source/final/live gates, the
D-104 gaps and the daily ATR/tick gap stand.

- [!] **M9.1BK — repeat the retained-file count run once a unit-label decision exists on record:**
  blocked on a supervisor decision after D-112 that states the price and volume units (not
  written yet). Handed to M9.1BL.
- [ ] **M9.1BL — repeat the retained-file count run once a unit-label decision is in the decision log:**
  proposed next sub-step. When a decision after D-112 states the units, execute
  `run_retained_counts` once over the same D-112 files and nine training names and publish
  ready/not-ready counts only. Independent review must confirm the decision exists before
  advancing; do not choose the labels in the builder.

## M9.1BL — still no unit-label decision — 2026-09-19 Pacific

Records only. No code, test, provider call, credential read, network call, spend or
retained-file read occurred. DECISIONS_AND_OPEN_QUESTIONS.md still ends at D-112 and the work
packet carries no later decision, so no supervisor statement of the price and volume units the
EQUS.MINI bars carry exists. `run_retained_counts` was not run again; the builder does not
choose labels and nothing was relabelled. `M9_1BC_RETAINED_COUNTS.json` is unchanged.

The parent `M9.1 — Historical replay #1-4` is not complete; source/final/live gates, the
D-104 gaps and the daily ATR/tick gap stand. Sub-steps M9.1BE to M9.1BL are the same wait on
one missing decision; further sub-steps add no new work until that decision is written.

- [!] **M9.1BL — repeat the retained-file count run once a unit-label decision is in the decision log:**
  blocked on a supervisor decision after D-112 that states the price and volume units (not
  written yet). Handed to M9.1BM.
- [ ] **M9.1BM — repeat the retained-file count run once a unit-label decision is written down:**
  proposed next sub-step. When a decision after D-112 states the units, execute
  `run_retained_counts` once over the same D-112 files and nine training names and publish
  ready/not-ready counts only. Independent review must confirm the decision exists before
  advancing; do not choose the labels in the builder.

## M9.1BM — still no unit-label decision — 2026-09-19 Pacific

Records only. No code, test, provider call, credential read, network call, spend or
retained-file read occurred. DECISIONS_AND_OPEN_QUESTIONS.md still ends at D-112 and the work
packet carries no later decision, so no supervisor statement of the price and volume units the
EQUS.MINI bars carry exists. `run_retained_counts` was not run again; the builder does not
choose labels and nothing was relabelled. `M9_1BC_RETAINED_COUNTS.json` is unchanged.

The parent `M9.1 — Historical replay #1-4` is not complete; source/final/live gates, the
D-104 gaps and the daily ATR/tick gap stand. Sub-steps M9.1BE to M9.1BM are the same wait on
one missing decision; further sub-steps add no new work until that decision is written.

- [!] **M9.1BM — repeat the retained-file count run once a unit-label decision is written down:**
  blocked on a supervisor decision after D-112 that states the price and volume units (not
  written yet). Handed to M9.1BN.
- [ ] **M9.1BN — repeat the retained-file count run once a unit-label decision is available:**
  proposed next sub-step. When a decision after D-112 states the units, execute
  `run_retained_counts` once over the same D-112 files and nine training names and publish
  ready/not-ready counts only. Independent review must confirm the decision exists before
  advancing; do not choose the labels in the builder.
  **The unit-label decision now exists: D-113 in DECISIONS_AND_OPEN_QUESTIONS.md**, recorded
  2026-09-19 Pacific. It corrects D-112: `price = "USD_PER_SHARE"` and `volume = "SHARES"`.
  Every other D-112 convention is unchanged. Use D-113 verbatim, set
  `evidence_reference = "D-113"`, and do not choose any label yourself.

## M9.1BM — D-113 found; the one-process count run is too slow for one session — 2026-09-19 Pacific

The unit-label decision now exists (D-113: `price = "USD_PER_SHARE"`, `volume = "SHARES"`), so this
step is no longer waiting on a decision. The builder ran `run_retained_counts` once as ONE process
(not three) over the D-112 files and the nine D-107 training names, with D-113 verbatim and
`evidence_reference = "D-113"`. The eight held-out names were not read. No code, test, provider call,
credential read, network call or spend occurred, and nothing else was changed.

The run did not finish, so there is no result: no `M9_1BN_RETAINED_COUNTS.json` was written and
`M9_1BC_RETAINED_COUNTS.json` is unchanged. Facts seen while it ran:

- After about 1 hour 49 minutes it had called about 122,000 of the 515,727 decision moments
  (about 24%), which puts a full run at roughly 7 hours. It used about 1.6 GB of memory and one CPU.
- A stack sample showed the time going into `expected_intervals` in `historical_bars.py`, which
  builds a full `pandas_market_calendars` schedule once per decision moment
  (`coverage_at` -> `session_dates`). The earlier M9.1BC run was fast only because every moment
  stopped early on the wrong unit label.
- The builder stopped its own process so it would not compete with the controller's protected
  runs. Any partial tally it held is discarded, not published.

This is a speed limit, not a finding about any playbook. The parent `M9.1 — Historical replay #1-4`
is not complete; source/final/live gates, the D-104 gaps and the daily ATR/tick gap stand.

- [!] **M9.1BM — one-process count run under D-113 could not finish inside one session:**
  the run needs about 7 hours; the per-moment calendar rebuild is the cost. Handed to M9.1BN.
- [ ] **M9.1BN — finish the retained-file count run under D-113:**
  next sub-step. Either (a) start the same single-process `run_retained_counts` detached
  (`setsid nohup`, one process, write the output file once at the end) and collect it when it
  ends, without the builder waiting on it; or (b) as its own reviewed change with focused tests,
  reuse the session calendar across moments in `historical_bars.expected_intervals`. Under (b)
  the change must leave every existing test and recording unchanged. Do not choose labels
  (D-113 stands), files or tickers, do not read the eight held-out names, and publish
  ready/not-ready counts only: no entry, no trade, no R, no profit figure.

## M9.1BN — calendar reuse added (option b); the count run is still to do — 2026-09-19 Pacific

Chose option (b). `session_dates` and `session_bounds` in `consensus_engine/utils/time_context.py`
now memoise the NYSE schedule lookup (pure per date range; `session_dates` still returns a fresh
list each call). Results are unchanged; only the per-moment calendar rebuild is avoided. New focused
tests: `tests/trade_alerts_contracts/test_session_calendar_cache.py` (repeat call reuse, caller
mutation isolation, empty ranges, holiday and early-close bounds). No provider call, credential
read, network call or spend. No labels, files or tickers chosen; the eight held-out names were not
read. The count run was not executed here, so there is no `M9_1BN_RETAINED_COUNTS.json` and
`M9_1BC_RETAINED_COUNTS.json` is unchanged. The controller stage will supply protected test figures.
I ran the two new tests once directly as a quick check only; that is not a protected result.
D-104 gaps, the daily ATR/tick gap and source/final/live gates stand.

- [!] **M9.1BN — calendar reuse built; count run not yet executed:** the parent M9.1 is not
  complete. Handed to M9.1BO.
- [ ] **M9.1BO — run the retained-file count once under D-113 with the cached calendar:**
  next sub-step. Run single-process `run_retained_counts` over the D-112 files and nine training
  names with D-113 verbatim, `evidence_reference = "D-113"`, write the output once at the end,
  publish ready/not-ready counts only. No labels, files or tickers chosen by the builder; no
  held-out names; no entry, trade, R or profit figure.

## M9.1BO — count run started detached under D-113; not finished in this session — 2026-09-19 Pacific

The builder started `run_retained_counts` once as ONE detached process (`setsid nohup`) over the
D-112 files and the nine D-107 training names, with D-113 verbatim (`price = "USD_PER_SHARE"`,
`volume = "SHARES"`, `evidence_reference = "D-113"`). The eight held-out names are not read. No code,
test, provider call, credential read, network call or spend occurred, and no label, file or ticker was
chosen by the builder. The driver is `/tmp/m91bn_run.py` (the M9.1BC driver with only those labels
changed); it writes `/tmp/m91bn_counts.json` once at the end and prints the summary to `/tmp/m91bn.out`.

At the time of writing the process had run for over 45 minutes and had not written its output, so
there is no result yet and `M9_1BC_RETAINED_COUNTS.json` is unchanged. A stack sample shows the time
is now in the per-minute interval loop of `expected_intervals` (`historical_bars.py`), called once per
decision moment through `coverage_at`. The schedule cache from M9.1BN removed the calendar rebuild but
not this loop, so the run is still slow (earlier estimate about 7 hours; not re-measured). The builder
did not stop the process this time and did not wait for it.

This is a speed limit, not a finding about any playbook. The parent `M9.1 — Historical replay #1-4` is
not complete; source/final/live gates, the D-104 gaps and the daily ATR/tick gap stand.

- [!] **M9.1BO — count run started detached under D-113; output not yet written:** the run needs
  hours; the builder did not wait for it. Handed to M9.1BP.
- [ ] **M9.1BP — collect the finished D-113 retained-file count output:**
  next sub-step. If `/tmp/m91bn_counts.json` exists and the process has ended, copy it to
  `trade_alerts_build_docs/M9_1BN_RETAINED_COUNTS.json`, record its sha256 and publish
  ready/not-ready counts only (no entry, trade, R or profit figure). If the process is gone with no
  file, rerun the same detached driver once and record that. Do not choose labels, files or tickers
  and do not read the eight held-out names.

## M9.1BP — count run still running; nothing to collect yet — 2026-09-19 Pacific

The detached D-113 count process started under M9.1BO (`/tmp/m91bn_run.py`) is still running: about 57
minutes of CPU time, about 1.6 GB of memory, and `/tmp/m91bn_counts.json` and `/tmp/m91bn.out` do not
exist or are empty. So there is no output to copy, no sha256 to record, and no counts to publish. The
process is not gone, so the "rerun once" branch does not apply. The builder did not stop it, did not wait
for it, and changed no code, test, label, file or ticker. The eight held-out names are not read. No
provider call, credential read, network call or spend occurred. `M9_1BC_RETAINED_COUNTS.json` is
unchanged and no `M9_1BN_RETAINED_COUNTS.json` exists.

This is a speed limit, not a finding about any playbook. The parent `M9.1 — Historical replay #1-4` is
not complete; source/final/live gates, the D-104 gaps and the daily ATR/tick gap stand.

- [!] **M9.1BP — count run still running; no output to collect:** hours remain. Handed to M9.1BQ.
- [ ] **M9.1BQ — collect the finished D-113 retained-file count output:**
  next sub-step. Same as M9.1BP: if `/tmp/m91bn_counts.json` exists and the process has ended, copy it
  to `trade_alerts_build_docs/M9_1BN_RETAINED_COUNTS.json`, record its sha256 and publish ready/not-ready
  counts only. If the process is gone with no file, rerun the same detached driver once and record that.
  Do not choose labels, files or tickers and do not read the eight held-out names.

## M9.1BQ — count run still running; nothing to collect yet — 2026-09-19 Pacific

The detached D-113 count process (`/tmp/m91bn_run.py`) is still running: about 1 hour 13 minutes elapsed
and about the same in CPU time, about 1.6 GB of memory. `/tmp/m91bn_counts.json` does not exist and
`/tmp/m91bn.out` is empty. So there is no output to copy, no sha256 to record, and no counts to publish.
The process is not gone, so the "rerun once" branch does not apply. The builder did not stop it, did not
wait for it, and changed no code, test, label, file or ticker. The eight held-out names are not read. No
provider call, credential read, network call or spend occurred. `M9_1BC_RETAINED_COUNTS.json` is
unchanged and no `M9_1BN_RETAINED_COUNTS.json` exists.

This is a speed limit, not a finding about any playbook. The parent `M9.1 — Historical replay #1-4` is
not complete; source/final/live gates, the D-104 gaps and the daily ATR/tick gap stand.

- [!] **M9.1BQ — count run still running; no output to collect:** hours remain. Handed to M9.1BR.
- [ ] **M9.1BR — collect the finished D-113 retained-file count output:**
  next sub-step. Same as M9.1BQ: if `/tmp/m91bn_counts.json` exists and the process has ended, copy it
  to `trade_alerts_build_docs/M9_1BN_RETAINED_COUNTS.json`, record its sha256 and publish ready/not-ready
  counts only. If the process is gone with no file, rerun the same detached driver once and record that.
  Do not choose labels, files or tickers and do not read the eight held-out names.

## M9.1BR — count run still running; nothing to collect yet — 2026-09-19 Pacific

The detached D-113 count process (`/tmp/m91bn_run.py`) is still running: about 1 hour 30 minutes elapsed
and about the same in CPU time, about 1.6 GB of memory. `/tmp/m91bn_counts.json` does not exist and
`/tmp/m91bn.out` is empty. So there is no output to copy, no sha256 to record, and no counts to publish.
The process is not gone, so the "rerun once" branch does not apply. The builder did not stop it, did not
wait for it, and changed no code, test, label, file or ticker. The eight held-out names are not read. No
provider call, credential read, network call or spend occurred. `M9_1BC_RETAINED_COUNTS.json` is
unchanged and no `M9_1BN_RETAINED_COUNTS.json` exists.

This is a speed limit, not a finding about any playbook. The parent `M9.1 — Historical replay #1-4` is
not complete; source/final/live gates, the D-104 gaps and the daily ATR/tick gap stand.

- [!] **M9.1BR — count run still running; no output to collect:** hours remain. Handed to M9.1BS.
- [ ] **M9.1BS — collect the finished D-113 retained-file count output:**
  next sub-step. Same as M9.1BR: if `/tmp/m91bn_counts.json` exists and the process has ended, copy it
  to `trade_alerts_build_docs/M9_1BN_RETAINED_COUNTS.json`, record its sha256 and publish ready/not-ready
  counts only. If the process is gone with no file, rerun the same detached driver once and record that.
  Do not choose labels, files or tickers and do not read the eight held-out names.

## M9.1BS — count run still running; nothing to collect yet — 2026-09-19 Pacific

The detached D-113 count process (`/tmp/m91bn_run.py`) is still running: about 1 hour 47 minutes elapsed
and about the same in CPU time (106 minutes), about 1.6 GB of memory. `/tmp/m91bn_counts.json` does not
exist and `/tmp/m91bn.out` is empty. So there is no output to copy, no sha256 to record, and no counts to
publish. The process is not gone, so the "rerun once" branch does not apply. The builder did not stop it,
did not wait for it, and changed no code, test, label, file or ticker. The eight held-out names are not
read. No provider call, credential read, network call or spend occurred.
`M9_1BC_RETAINED_COUNTS.json` is unchanged and no `M9_1BN_RETAINED_COUNTS.json` exists.

This is a speed limit, not a finding about any playbook. The parent `M9.1 — Historical replay #1-4` is
not complete; source/final/live gates, the D-104 gaps and the daily ATR/tick gap stand.

- [!] **M9.1BS — count run still running; no output to collect:** hours remain. Handed to M9.1BT.
- [ ] **M9.1BT — collect the finished D-113 retained-file count output:**
  next sub-step. Same as M9.1BS: if `/tmp/m91bn_counts.json` exists and the process has ended, copy it
  to `trade_alerts_build_docs/M9_1BN_RETAINED_COUNTS.json`, record its sha256 and publish ready/not-ready
  counts only. If the process is gone with no file, rerun the same detached driver once and record that.
  Do not choose labels, files or tickers and do not read the eight held-out names.

## M9.1BS — D-113 retained-file count output collected — 2026-09-19 Pacific

The detached D-113 count run (D-114: three detached shards NVDA,MSFT,AAPL / TSLA,LLY,SPY / QQQ,XLV,USO, merged by
`/root/trade-alerts-builder/m91_count_merge.py`) has finished. Its output `/tmp/m91bn_counts.json` is copied to
`trade_alerts_build_docs/M9_1BN_RETAINED_COUNTS.json` (7,833 bytes, sha256
`38088dd403b2627fbce9f41dcfe97cfc1940be3b87f7808c167c2a40596d5224`; the two files match). The run was not repeated.
The builder changed no code, test, label, file or ticker and did not read the eight held-out names.
No provider call, credential read, network call or spend occurred.

Counts only (no entry, trade, R or profit figure):
- 13 files verified, 261 sessions, 2,349 pairs; 2,241 sessions used; 108 skipped
  (90 NO_USABLE_BARS, 18 DEGRADED_SESSION); 515,727 moments called.
- Ready per adapter: FIRST_PULLBACK_VWAP last_trade 76,404; FIRST_PULLBACK_VWAP vwap_level 76,404;
  OR_FAILURE_REV tape_and_close 76,404. Total per adapter 171,909.
- Not ready per adapter: 95,505, which is 5/9 of 171,909. Reasons: INCOMPATIBLE_INSTRUMENT_TYPE for last_trade and
  tape_and_close; NO_TRADED_SESSION_BAR_YET for vwap_level.
- Not called: atr_1m, vwap_slope, vwap_crosses, quote_decision, hod_comp_rs_policy_inputs.

Bug exposed (D-115, recorded, not fixed here): `open_core17_ohlcv_1m_file` stamps every bar as ETF by default and
takes no per-ticker type, so the five stock names are discarded and only the four ETFs are measured. The stocks were
not relabelled as ETFs. This is a speed and measurement finding, not a finding about any playbook.
The parent `M9.1 — Historical replay #1-4` is not complete; source/final/live gates, the D-104 gaps and the daily
ATR/tick gap stand.

- [x] **M9.1BS — D-113 retained-file count output collected and published.**
- [ ] **M9.1BT — per-ticker instrument type for the core17 minute-file opener:**
  next sub-step. Let `open_core17_ohlcv_1m_file` take the true instrument type per ticker (stock or ETF, from the
  frozen list, no relabelling), add offline tests, then rerun the counts as a detached job
  (`setsid nohup ... </dev/null &`). Do not read the eight held-out names.

## M9.1BT — per-ticker instrument type added; new count run launched, not finished — 2026-09-19 Pacific

Code: `iter_ohlcv_1m_records` and `open_core17_ohlcv_1m_file` in `consensus_engine/core17_bar_loader.py` take an
optional `instrument_types` map (raw symbol to `ETF`/`EQUITY`). When given, it wins over the single default; a symbol
not in the map is skipped (not labelled ETF), so undeclared and held-out names are not read. Without the map the old
`ETF` default is unchanged. Three offline tests were added to `tests/trade_alerts_contracts/test_core17_bar_loader.py`
(per-ticker type, undeclared symbol skipped, default unchanged). The driver `/root/trade-alerts-builder/m91_count_part.py`
now passes the D-112 types for the nine training names (five `EQUITY`, four `ETF`) to both the opener and the adapter run.
A first launch failed at once because my first version raised on undeclared names in the file; I changed it to skip and
relaunched. Neither launch read the held-out names' data into a result.

The three detached shards (same split as D-114) write `/tmp/m91bt/part_{1,2,3}.json`; they were still running when this
session ended. Merge with `m91_count_merge.py` when all three exist. No protected run happened in this session: a plain
pytest of the affected files reported only skips outside the launcher, so the controller stage supplies test figures.
No provider call, credential read, network call or spend occurred.

The parent `M9.1 — Historical replay #1-4` is not complete; source/final/live gates and D-104 gaps stand.

- [!] **M9.1BT — code fix done; count run still running:** hours remain. Handed to M9.1BU.
- Note (2026-09-19 Pacific, late): the three shards launched earlier were gone with no part files; relaunched once with setsid, still running when this session ended.
- Note (2026-09-20 Pacific, early): the shards were gone again with no part files; relaunched once more with setsid and seen running 20 seconds later. Still running when this session ended.
- Note (2026-09-20 Pacific, morning): checked again; no `m91_count_part` process and no `part_*.json` in `/tmp/m91bt/` (only empty logs from 02:14). The shards died a third time with no output. No relaunch in this session.
- [ ] **M9.1BU — collect the finished stock-typed D-113 count output:**
  next sub-step. If all three `/tmp/m91bt/part_*.json` exist and no `m91_count_part` process is running, merge them,
  publish as `trade_alerts_build_docs/M9_1BT_RETAINED_COUNTS.json` with its sha256, counts only, and compare with
  `M9_1BN_RETAINED_COUNTS.json`. If a shard died with no file, relaunch that shard once detached. Do not read held-out names.
