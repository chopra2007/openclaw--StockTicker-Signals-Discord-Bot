# MASTER_SPEC.md

## 1. Purpose

This document is the top-level contract for the intraday human-in-the-loop trading alert system. It defines project scope, end-state, architecture, functional requirements, non-functional requirements, project boundaries, and the relationship among supporting specifications.

Detailed strategy rules are in `PLAYBOOKS.md`. Data availability is governed by `DATA_REQUIREMENTS.md`. Evidence standards are governed by `TESTING_AND_VALIDATION.md`. Engineering conventions are governed by `CODING_STANDARDS.md`. Documentation routing and conflict precedence are governed by `PROJECT_INDEX.md`.

## 2. Status Vocabulary

Use:
- `CONFIRMED`
- `PROVISIONAL`
- `NEEDS VALIDATION`
- `BLOCKED BY DATA`

These labels distinguish approved project facts from engineering priors and unresolved research.

## 3. Project Objective

Build a modular intraday alert platform that detects high-quality discretionary trading setups in U.S. stocks and ETFs, produces timely heads-up/actionable alerts with structural stops, targets, confidence, and option-contract guidance, and persistently records enough information to validate every mechanical alert.

The primary operating window is premarket preparation through approximately 07:15 Pacific, with the main regular-session focus 06:30–07:15 Pacific.

The system is human-in-the-loop. It does not place trades.

Core objective:

```text
EV ≈ Probability × Payoff × Frequency × Execution Feasibility
```

The platform should favor repeatable, testable, human-executable setups rather than maximal theoretical complexity.

## 4. End-State

The finished platform should support:

```text
market adapters
→ normalized events
→ shared feature engine
→ market/sector/catalyst context
→ strategy runtime/state machines
→ heads-up/actionable candidates
→ structural risk/targets
→ confidence
→ options selection
→ cross-strategy dedup/confluence
→ Discord alerts
```

Parallel research path:

```text
raw/normalized data
→ immutable event store
→ feature/state snapshots
→ outcomes
→ deterministic replay
→ walk-forward / ablation / reaction-delay analysis
→ live shadow
→ strategy promotion / modification / rejection
→ continuous strategy health monitoring
```

## 5. In Scope

### Markets and instruments
- U.S. equities
- U.S. ETFs
- listed equity/ETF options
- bullish and bearish setups

### Time window
- premarket preparation
- regular session open through approximately 07:15 Pacific

### Detection and alerting
- deterministic strategy detection
- stateful setup formation
- heads-up alerts
- actionable alerts
- structural invalidation
- structural targets
- reward/risk checks
- confidence scoring
- regime/context inputs
- confluence and deduplication
- option ranking
- human review checklist

### Research and validation
- immutable mechanical alerts
- state transitions
- feature snapshots
- MFE/MAE
- deterministic replay
- reaction-delay evaluation
- cost/slippage sensitivity
- walk-forward
- ablation
- confidence calibration
- human accepted/rejected analysis
- overlap/confluence analysis
- strategy health
- champion/challenger testing

### Infrastructure
- reuse existing Schwab/Openclaw/Discord/options infrastructure
- data-source health
- configuration/versioning
- observability
- safe degradation
- deployment/runbook documentation

## 6. Out of Scope Unless Explicitly Expanded

- automatic stock or option order placement
- automatic entries/exits/stops
- automated brokerage position management
- automatic portfolio synchronization
- realized brokerage P&L accounting
- autonomous capital allocation or position sizing
- autonomous strategy creation
- unapproved ML replacement of deterministic strategies
- live automatic parameter tuning
- HFT, co-location, FPGA, latency arbitrage, market making
- institutional order-book dependencies as core requirements
- futures
- forex
- crypto
- commodities
- bonds
- international equities
- replacing thinkorswim/full charting
- building a generic arbitrary-strategy trading terminal

Any scope expansion requires a documented use case, dependencies/cost, and updates to this file and affected supporting documents.

## 7. Current Infrastructure Context

Repository inspection confirms a Python application in `consensus_engine`, with existing Schwab request adapters, stock/options analysis, unusual-options scanning, Discord delivery, and SQLite measurement records. See [PREBUILD_REVIEW.md](./PREBUILD_REVIEW.md) for exact modules, evidence levels, and limitations.

Provider access is owner-reported context. This review did not contact broker or Discord services. Current account permissions, streaming availability, history coverage, and live latency remain unverified. Code support is not proof of those operational capabilities.

Build this as an extension of the existing bot. Reuse the existing Python entry point, asynchronous task lifecycle, configuration, provider authentication, delivery path, and database migration framework. A new language, replacement bot/framework, or major rewrite requires an explicit proposal and owner approval. Logical layers below do not imply separate processes, schedulers, or duplicate databases.

## 8. Approved Strategy Portfolio

1. `CRVOL_ORB5` — Catalyst/RVOL 5-minute Opening Range Breakout
2. `HOD_COMP_RS` — HOD/LOD Compression Break + Relative Strength
3. `OR_FAILURE_REV` — Opening Range Failure Reversal
4. `FIRST_PULLBACK_VWAP` — First Pullback to VWAP/AVWAP Continuation
5. `INDEX_OPEN_DRIVE_BREADTH` — Index/ETF Opening Drive + Breadth
6. `GAP_FADE_FAILED_OPEN` — Gap Fade After Failed Open
7. `CAT_FIRST_CONSOL` — Earnings/News First Consolidation Continuation
8. `VP_ACCEPT_LVN` — Prior-Value Acceptance → LVN Expansion

Initial research/design ranking:
1. CRVOL_ORB5 — 88.8
2. HOD_COMP_RS — 88.1
3. OR_FAILURE_REV — 86.9
4. FIRST_PULLBACK_VWAP — 86.8
5. INDEX_OPEN_DRIVE_BREADTH — 86.1
6. GAP_FADE_FAILED_OPEN — 85.0
7. CAT_FIRST_CONSOL — 84.3
8. VP_ACCEPT_LVN — 81.9

These are design/research scores, **not historical performance estimates**.

## 9. Research Ranking Weights

The original strategy-discovery composite used:
- Structural Edge — 14%
- Machine Detectability — 12%
- Human Discretion Value — 8%
- Alert Lead — 9%
- Data Accessibility — 10%
- Historical Testability — 8%
- Frequency — 6%
- Reward/Risk — 8%
- Regime Robustness — 7%
- Execution Simplicity — 5%
- False-Positive Resistance — 7%
- Options Suitability — 6%

## 10. Strategy Relationships

Do not treat all indicators as independent strategies.

Key relationships:
- Premarket high/low break is an ORB subtype/context.
- VWAP reclaim/rejection is usually a first-pullback/trend subtype.
- Relative strength is usually context/confluence.
- VWAP deviation belongs to mean-reversion/gap-fade family.
- First catalyst consolidation (#7) is primary early catalyst continuation; later HOD compressions may become #2.
- #8 may often function as context rather than independent trigger.

One market opportunity should be represented by a `TradeThesis`/candidate containing:
- primary strategy
- supporting signals
- structure ID
- direction
- trigger
- stop
- targets
- confidence

Suggested dedup prior:
- same symbol/direction
- triggers/stops within ~0.25 ATR
- within ~3 minutes
→ merge into primary + confluence

Opposite-direction conflicts should generally suppress lower-confidence candidates until the primary thesis invalidates, except intentional transitions such as #1 → #3/#6.

## 11. Functional Requirements

### FR-001 — Repository-first implementation
Codex must inspect existing architecture before building replacements.

### FR-002 — Canonical data models
Provider payloads must be normalized into source-independent domain models.

### FR-003 — Canonical market clock
All session logic must use exchange-aware, timezone-aware market-session services.

### FR-004 — Shared feature engine
Shared calculations such as VWAP, ATR, RVOL, HOD/LOD, opening range, gap, relative strength, compression, retracement, breadth context, and structural R:R must not be duplicated across strategies.

### FR-005 — Stateful strategy runtime
Strategies must expose explicit states and transitions.

Canonical superset:
- NOT_ELIGIBLE
- WATCHING
- SETUP_FORMING
- ARMED
- ALERT_TRIGGERED
- INVALIDATED
- EXPIRED

Strategy-specific substates are allowed.

### FR-006 — Heads-up alerts
Where setup structure allows, emit heads-up before actionable trigger.

### FR-007 — Actionable alerts
Actionable alerts must contain enough information for rapid human evaluation.

### FR-008 — Structural invalidation
Stops must represent thesis invalidation, not arbitrary fixed percentage risk.

### FR-009 — Structural targets
Targets use observable structure and R multiples.

### FR-010 — Minimum R:R enforcement
Candidates with insufficient structural reward may be suppressed.

### FR-011 — Confidence
Confidence is a relative quality score, not win probability.

### FR-012 — Confidence transparency
Persist setup/context/execution components and factor contributions.

### FR-013 — Options separation
Underlying setup validity must be determined before options quality.

### FR-014 — Poor option quality outcome
Support: `STOCK SETUP VALID — OPTIONS QUALITY POOR`.

### FR-015 — Cross-strategy deduplication
Portfolio orchestration merges redundant opportunities and records confluence.

### FR-016 — Alert suppression
Shared cooldown, expiry, duplicate, and per-structure suppression rules.

### FR-017 — Immutable mechanical alerts
Alert-time trigger, price, stop, targets, confidence, versions, and feature snapshots must remain immutable.

### FR-018 — Research event store
Persist meaningful strategy transitions, candidates, alerts, suppressions, option snapshots, and metadata.

### FR-019 — Outcome evaluation
Calculate MFE, MAE, maximum R, target/stop hits, and timing.

### FR-020 — Deterministic replay
Historical data must run through the same or equivalent live strategy runtime chronologically.

### FR-021 — Point-in-time integrity
No future HOD, daily volume, VWAP, news, breadth membership, profile, option data, or other future information may leak into historical decisions.

### FR-022 — Reaction-delay analysis
Evaluate 0/5/15/30/60-second entry delay where data resolution permits.

### FR-023 — Walk-forward validation
Separate training/parameter selection from locked future test periods.

### FR-024 — Ablation
Important filters must be removable/configurable for research comparison.

### FR-025 — Human decision research
Mechanical alert status must remain separate from `ACCEPTED`, `REJECTED`, `NO_DECISION`.

### FR-026 — Strategy lifecycle
Support:
- DEVELOPMENT
- SHADOW
- PROVISIONAL
- ACTIVE
- DEGRADED
- DISABLED
- REJECTED
- INSUFFICIENT_DATA where needed

### FR-027 — Data-quality modes
Mandatory data must expose valid/stale/unavailable/degraded states. Optional data must never silently appear valid when absent.

### FR-028 — Observability
Track state transitions, suppressions, stale data, delivery failures, option rejections, provider health, and latency.

### FR-029 — No silent fallback
Every proxy/degraded mode must be explicit in stored metadata.

### FR-030 — Versioning
Alerts and research runs must preserve strategy version and config hash/version.

### FR-031 — No automatic live optimization
Monitoring may recommend changes or launch challengers in shadow, but cannot silently retune production strategy parameters.

## 12. Non-Functional Requirements

- deterministic behavior where possible
- auditability
- reproducibility
- low alert noise
- safe degradation
- robust restart behavior
- no secret leakage
- point-in-time correctness
- modularity
- reuse of existing infrastructure
- testability
- production/research separation
- enough performance for morning intraday monitoring without HFT complexity

## 13. Architecture

Target logical architecture:

```text
MARKET PROVIDERS
    ↓
PROVIDER ADAPTERS
    ↓
NORMALIZED EVENTS
    ↓
FEATURE ENGINE
    ↓
MARKET / SECTOR / CATALYST CONTEXT
    ↓
STRATEGY RUNTIME
    ↓
CANDIDATE ENGINE
    ↓
RISK / TARGETS
    ↓
CONFIDENCE
    ↓
OPTIONS
    ↓
DEDUP / CONFLUENCE ORCHESTRATOR
    ↓
ALERT RENDERER
    ↓
DISCORD
```

Research path:

```text
NORMALIZED EVENTS / FEATURES / STATE
    ↓
IMMUTABLE EVENT STORE
    ↓
OUTCOMES
    ↓
REPLAY
    ↓
WALK-FORWARD / ABLATION / REGIME / HUMAN / OPTIONS ANALYSIS
    ↓
STRATEGY VALIDATION REPORTS
```

Monitoring path:

```text
ACTIVE/SHADOW ALERTS
    ↓
ROLLING HEALTH
    ↓
DATA / EXECUTION / SIGNAL DIAGNOSIS
    ↓
WARNING / INVESTIGATION / HYPOTHESIS
    ↓
CHALLENGER
```

## 14. Canonical Alert Candidate

Conceptual schema:

```json
{
  "alert_id": "...",
  "schema_version": "1",
  "timestamp": "...",
  "session_date": "...",
  "symbol": "...",
  "direction": "LONG|SHORT",
  "alert_type": "HEADS_UP|ACTIONABLE",
  "primary_strategy": "CRVOL_ORB5",
  "strategy_version": "...",
  "config_hash": "...",
  "structure_id": "...",
  "trigger_price": 0.0,
  "alert_price": 0.0,
  "hard_stop": 0.0,
  "soft_invalidation": "...",
  "targets": [],
  "risk_per_share": 0.0,
  "confidence": 0,
  "confidence_breakdown": {},
  "confluence": [],
  "human_checks": [],
  "data_mode": {},
  "option_recommendation": null,
  "expires_at": "...",
  "suppression_reason": null
}
```

Exact repository schema may differ, but semantic information must remain.

## 15. Options Requirements

General starting prior:
- 0–7 DTE universe
- same-week preferred where suitable
- common delta target around absolute 0.50–0.70, often ~0.60
- 0DTE only with stricter policies, especially liquid index ETFs
- spread, volume, OI, IV, Greeks, DTE, and gamma/theta suitability considered
- OptionScore provisional threshold ~65
- stricter 0DTE threshold may be ~75

These are engineering priors requiring empirical calibration.

## 16. Data Policy

Data priority:
1. existing repository sources
2. existing Schwab access
3. free authoritative/public sources
4. free proxies
5. paid data only after evidence justifies it

Known blockers:
- reliable low-latency catalyst/news feed
- historical received timestamps for catalysts
- full point-in-time breadth history/membership
- historical Level 2
- historical NBBO unless discovered
- historical OPRA-quality options
- true historical volume-at-price

Approved fallbacks:
- sector breadth proxy for #5
- price/volume abnormality + `UNKNOWN` catalyst state where playbook permits
- 1m bar approximate profile for #8
- projected current 1m volume / L1 proxies when time-and-sales unavailable

## 17. Validation Philosophy

Do not manufacture win rates or claim profitability from literature or implementation.

Primary validation objective:

```text
Does this strategy appear to have repeatable,
forward-usable,
human-executable positive expected value
after realistic delays, spreads, slippage,
regime variation, and parameter uncertainty?
```

Expectancy in R is the primary strategy metric. MFE/MAE, drawdown, reaction robustness, parameter stability, and OOS/shadow consistency are required.

## 18. Continuous Monitoring

Monitor rolling:
- expectancy
- PF
- MFE/MAE
- alert frequency
- reaction decay
- data quality
- execution quality
- confidence calibration
- human decision behavior
- options quality
- regime mix

Health states may be `GREEN`, `YELLOW`, `ORANGE`, `RED`.

Monitoring must distinguish signal degradation, execution degradation, data degradation, regime scarcity, human-selection drift, and options deterioration.

No automatic tuning.

## 19. Implementation Order

Recommended:
1. repository/data audit
2. shared time/config/domain/data foundation
3. shared analytics
4. strategy runtime and alert foundation
5. event store/outcomes/replay
6. #1
7. #2
8. #3
9. #4
10. early replay/shadow validation
11. #5
12. #6
13. #7 if catalyst data supports it
14. #8 experimental
15. options refinement, portfolio orchestration, advanced validation
16. production hardening
17. continuous monitoring/champion-challenger

Do not build all eight before validating the first four.

## 20. Definition of Done

The platform is complete when:
- the shared runtime exists;
- all eight playbooks have the full implementation checklist, tests, replay path, and tracked data dependencies; an identity stub alone does not complete a strategy;
- every implemented data mode is objectively replayable; unavailable faithful modes remain explicitly blocked and cannot be counted as completed;
- data limitations are explicit;
- alerts support human decision-making;
- options remain separate from underlying edge;
- every mechanical alert can be evaluated;
- human discretionary value can be measured;
- strategies can be promoted, modified, disabled, or rejected based on evidence;
- active strategies can be monitored for degradation;
- future Codex sessions do not need original conversation history.

Implementation completeness does **not** imply all eight strategies are profitable or active.

A valid final portfolio may include `ACTIVE`, `SHADOW`, `DISABLED`, `REJECTED`, and `BLOCKED BY DATA` strategies.

## 21. Integration and release contract

The existing bot remains the host. New strategy behavior starts behind separate configuration switches; existing commands, scanners, scores, alerts, and measurement records retain their behavior. A setup quality score cannot be substituted for the existing consensus score or represented as a win probability.

Record the immutable mechanical candidate, feature references, suppression decision, and delivery intent before sending an alert. Delivery results, human choices, option enrichment, and outcomes are separate linked records. An options outage preserves the underlying setup with an explicit options-unavailable result. A late option result cannot rewrite the original alert.

Historical replay has no broker/Discord credentials and uses isolated storage and a non-network alert sink. Live shadow uses authorized live inputs but defaults to a recording sink. It does not establish actual Discord delivery or human reaction evidence. Any later notification validation uses the existing delivery adapter under the then-authorized rollout scope.

Keep setup states, strategy lifecycle, data quality, evidence stage, and delivery status as separate fields. A blocked full-data mode is not a rejected strategy; a passing software test is not a profitable strategy. Approved proxy modes remain labeled and separately evaluated.

Before the first live shadow, complete the early storage/recovery, minimal dedup/options, and delivery-isolation milestones in ROADMAP. Later options, portfolio, hardening, and monitoring phases still deliver their complete listed functionality. A blocked strategy or required capability keeps an owner milestone, evidence gap, reopening condition, and acceptance test; it is never silently removed.

All visible clock times in this document set are Pacific. Market-session boundaries come from the exchange calendar and `ZoneInfo("America/Los_Angeles")`; display conversion does not change a strategy's trading window.
