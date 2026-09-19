# CODING_STANDARDS.md

## 1. Purpose

This document defines the canonical implementation standards for the intraday human-in-the-loop trading alert system.

It governs architecture, Python implementation, typing, interfaces/contracts, configuration, logging, error handling, dependency management, testing expectations, naming, documentation, persistence boundaries, strategy modularity, data-model separation, observability, versioning, and performance discipline.

It does not redefine project scope, strategy logic, data availability, validation methodology, or build order.

## 2. Core Engineering Principles

Priority:

```text
correctness
→ data integrity
→ determinism
→ state correctness
→ testability
→ auditability
→ maintainability
→ alert latency
→ throughput
→ micro-optimization
```

This is a human-in-the-loop system, not HFT.

## 3. Repository-First Engineering

Before creating a new module:

```text
SEARCH EXISTING REPOSITORY
→ IDENTIFY EQUIVALENT FUNCTIONALITY
→ REUSE / EXTEND
→ CREATE NEW ONLY IF NEEDED
```

Do not duplicate existing market-data adapters, Schwab clients, Discord clients, options utilities, DB models, schedulers, logging, configuration, or technical indicators.

Avoid sweeping rewrites. Prefer small adapters, shared abstractions, incremental refactors, and compatible extensions.

## 4. Separation of Concerns

Canonical processing boundaries:

```text
RAW PROVIDER DATA
→ PROVIDER ADAPTER
→ CANONICAL MARKET MODEL
→ FEATURE ENGINE
→ MARKET CONTEXT
→ STRATEGY STATE MACHINE
→ RISK / TARGET ENGINE
→ CONFIDENCE ENGINE
→ OPTIONS ENGINE
→ PORTFOLIO ORCHESTRATOR
→ ALERT RENDERER
→ DELIVERY
```

Parallel:

```text
EVENTS / SNAPSHOTS
→ RESEARCH STORE
→ OUTCOME EVALUATOR
→ REPLAY / VALIDATION / MONITORING
```

Provider-specific payloads belong only in adapter code. Strategy modules must consume canonical models.

## 5. Canonical Data Models

Use explicit typed models for important domain objects:
- Bar
- Quote
- OptionQuote
- CatalystEvent
- FeatureSnapshot
- StrategyStateTransition
- AlertCandidate
- OptionRecommendation
- OutcomeRecord
- SuppressionEvent

Models should validate critical invariants, serialize predictably, use timezone-aware timestamps, preserve source metadata, and distinguish unavailable data from zero.

## 6. Python Version / Style

Use the repository's existing supported Python version. If none exists, Python 3.11+ is the preferred provisional baseline.

Follow existing formatters/linters. If none exist, use PEP 8 with black-compatible formatting and ruff-compatible linting.

Readable code over clever code.

## 7. Type Hints

New production Python should use type hints for:
- public functions/methods
- interfaces/protocols
- domain models
- strategies
- provider adapters
- feature functions
- storage interfaces

Use explicit optional types rather than sentinel numeric values.

## 8. Domain Types / Naming

Prefer enums or constrained types for:
- Direction
- StrategyStatus
- AlertStatus
- DataQuality
- StrategyState
- OptionType
- SessionType
- SuppressionReason

Naming:
- modules/functions/variables: `snake_case`
- classes: `PascalCase`
- true constants: `UPPER_SNAKE_CASE`

Canonical strategy IDs:
- `CRVOL_ORB5`
- `HOD_COMP_RS`
- `OR_FAILURE_REV`
- `FIRST_PULLBACK_VWAP`
- `INDEX_OPEN_DRIVE_BREADTH`
- `GAP_FADE_FAILED_OPEN`
- `CAT_FIRST_CONSOL`
- `VP_ACCEPT_LVN`

Do not casually rename IDs used by config/storage/logging/reports.

## 9. Strategy Architecture

Each strategy should expose behavior through a common interface/protocol conceptually supporting:
- strategy_id/version
- required_data
- update/current_state
- heads_up/actionable
- invalidate/expire/reset
- confidence
- stop
- targets
- serialization as needed

Exact shape may follow existing architecture.

Strategies must not recalculate shared features such as VWAP, ATR, RVOL, HOD/LOD, RS, gap, spread, OR, or option scores.

## 10. Strategy Logic Organization

Separate:
- eligibility
- state transitions
- heads-up
- actionable condition
- invalidation
- expiry
- confidence composition
- stop selection
- target selection

Avoid giant functions containing mixed logic.

State must be explicit rather than inferred only from scattered booleans.

Strategy-local state such as reference HOD, breakout extreme, impulse origin/high, compression start, or pullback number should be explicit and serializable/recoverable where required.

## 11. State Transition Events

Meaningful transitions should emit structured metadata:
- strategy_id/version
- symbol
- old/new state
- timestamp
- reason
- feature snapshot reference

Expected strategy rejection is a domain result, not an exception.

## 12. Guard Conditions

Use early guards for invalid mandatory inputs such as stale quotes, halts, missing features, invalid spreads, or impossible states.

Fail safe: do not fire actionable alerts from corrupted/stale mandatory data.

## 13. Configuration

No scattered magic thresholds.

Material thresholds belong in validated, versioned configuration.

Configuration should document meaning, units, status (`CONFIRMED`, `PROVISIONAL`, etc.) where practical.

Validate at startup and reject impossible values.

Use a fixed configuration snapshot for a live/replay session unless dynamic reconfiguration is explicitly designed.

Store config version/hash with alerts and research runs.

## 14. Feature Engine Standards

Each feature should define:
- inputs
- lookback
- units
- warm-up
- point-in-time behavior
- missing-data behavior
- update frequency

Prefer pure functions where practical.

Explicitly handle division by zero, NaN, infinity, invalid price/volume, missing bars, zero midpoint, and invalid Greeks.

Clamp 0–100 normalized scores explicitly.

## 15. Confidence Representation

Prefer a structured confidence object containing:
- setup score
- context score
- execution score
- final score
- component factors

Keep setup confidence separate from research confidence.

## 16. Structural Risk / Targets

Use explicit risk/target structures containing:
- entry reference
- hard stop
- risk/share
- rationale
- target label
- target price
- R multiple
- source

Support explicit rejection such as `INSUFFICIENT_RR` rather than forcing a target.

## 17. Options Engine Boundary

Options code must not sit inside strategy trigger methods.

Flow:

```text
underlying candidate
→ underlying validity
→ options service
→ contract recommendation or rejection
```

Shared option factors should be implemented once:
- spread
- delta fit
- volume
- OI
- DTE fit
- IV
- gamma/theta

Missing Greeks are unavailable/degraded, not zero.

Recommendations should include score and reasons.

## 18. Portfolio Orchestration

Deduplication/confluence occurs outside individual strategy modules.

Strategies emit candidates independently. Orchestrator determines:
- primary strategy
- confluence
- duplicate suppression
- conflicting-direction handling

Use stable structure IDs where practical.

Keep data-source duplicate handling separate from alert duplicate handling.

## 19. Alert Rendering

Renderer receives a complete candidate and formats it. It must not recalculate stops, targets, confidence, or strategy logic.

Version externally consumed alert schemas when needed.

## 20. Persistence

Separate immutable facts from derived outcomes.

Logical collections/tables may include:
- strategy_events
- state_transitions
- feature_snapshots
- alerts
- suppression_events
- option_snapshots
- outcomes
- human_decisions
- research_runs

Do not rewrite original alert-time confidence/trigger/stop/targets after the fact.

Use stable IDs for alerts, transitions, research runs, hypotheses, and versions.

## 21. Timestamps / Ordering

Use timezone-aware timestamps, stored as absolute instants internally, with Pacific display using `ZoneInfo("America/Los_Angeles")`.

No naive datetimes for trading events.

Where multiple provider events share timestamps, preserve deterministic ordering using source sequence, received timestamp, or local sequence where available.

## 22. Logging

Use structured logging where supported.

Recommended fields:
- event_type
- strategy_id/version
- symbol
- timestamp
- state
- reason
- data_source
- data_quality
- alert_id

Suggested levels:
- DEBUG: high-volume detail
- INFO: important normal events
- WARNING: recoverable degradation
- ERROR: failed operation
- CRITICAL: integrity compromise

Do not log every quote at INFO.

Never log API tokens, refresh tokens, client secrets, Discord webhooks, auth headers, or unnecessary account identifiers.

## 23. Error Handling

Do not silently swallow broad exceptions.

Expected domain failures should use explicit errors or result states such as:
- DataUnavailable
- DataStale
- InvalidFeatureInput
- ConfigurationError
- ProviderRateLimit
- PersistenceFailure

Strategy suppression reasons are not exceptions.

Retries are for transient infrastructure failures only, with bounded attempts/backoff/jitter.

## 24. Graceful Degradation

Mandatory unavailable → suppress.

Modifier unavailable → omit/degrade if explicitly allowed.

Optional unavailable → continue.

Every proxy/degraded mode must be visible in event metadata.

## 25. Provider Reconnects

Streaming adapters must handle disconnect, auth refresh, resubscription, duplicates, stale state, and warm-up/data continuity before actionable alerts resume.

## 26. Testing Expectations

Every new behavior requires tests appropriate to risk.

Minimum:
- unit tests for deterministic calculations
- state transition tests
- edge cases

Integration tests when crossing modules.

Regression tests for meaningful bugs.

Tests should describe behavior, not `test_case_4` style labels.

Avoid wall-clock, live APIs, random external responses, and unordered behavior in unit tests. Inject clocks/providers/storage where practical.

## 27. Mocking / External APIs

Prefer small fakes, fixtures, and in-memory repositories over excessive internal mocking.

Separate unit, integration, and live-provider smoke tests.

Unit tests must not require real credentials.

## 28. Replay Tests

Replay tests use fixed inputs and reproducible outputs.

Intentional strategy behavior changes require new version plus updated expected fixture.

Non-semantic refactors should preserve output.

## 29. Dependency Management

Use the repository's existing package manager and dependency conventions.

Do not introduce a second package-management system without strong reason.

Avoid heavy TA dependencies for simple transparent calculations when maintainable in shared code.

ML may be used later for research/ranking/calibration only after explicit decision; it must not silently replace approved deterministic strategy logic.

## 30. Concurrency / Mutable State

Use the repository's existing concurrency model.

Avoid broad global mutable dictionaries. Make state ownership explicit.

Per-symbol strategy state may key by strategy ID, symbol, direction, and session.

Reset session-specific state explicitly at boundaries.

Do not retain unbounded in-memory history; use bounded rolling windows and persistence.

## 31. Performance

Measure before optimizing.

Useful metrics:
- event processing latency
- feature update latency
- strategy evaluation latency
- alert orchestration latency
- Discord delivery latency
- queue depth

Prefer algorithmic improvements, incremental rolling calculations, and reduced copying before complex concurrency.

Replay prioritizes throughput; live prioritizes predictable latency.

## 32. DataFrames vs Domain Objects

Pandas is suitable for historical/batch research. Lightweight typed objects may be preferable for live event processing.

Do not force one representation everywhere.

## 33. Units / Precision

Use clear units in names:
- `gap_pct`
- `spread_bps`
- `risk_per_share`
- `atr_dollars`
- `atr_pct`

Preferred percentage internal convention: decimal (`0.01 = 1%`) unless repo standard differs.

Normalize price levels to valid tick increments where required.

## 34. Time Windows

Session times come from a canonical market/session service. Strategy windows belong in strategy config. Avoid scattered hardcoded 06:30/07:15 values and ambiguous duration literals.

## 35. Documentation / Formulas

Document non-obvious formulas, units, lookback, rationale, and point-in-time constraints.

Comments should explain assumptions/workarounds, not restate obvious code.

TODOs must be actionable and traceable. Important unresolved items also belong in `DECISIONS_AND_OPEN_QUESTIONS.md`.

## 36. Documentation Synchronization

If implementation confirms a provisional data fact, update `DATA_REQUIREMENTS.md`.

If an approved strategy rule changes, update/version `PLAYBOOKS.md`.

If a system-wide convention changes, update this document.

Use `PROJECT_INDEX.md` for drift and authority rules.

## 37. API / Database Compatibility

Avoid breaking existing consumers where practical.

If breaking changes are required, update consumers, tests, docs, and migration notes coherently.

Use existing DB migration framework. Migrations should be explicit, versioned, reversible where practical, and tested.

Index high-value fields when query needs justify it.

## 38. Research Reproducibility

Research run metadata should include:
- strategy version
- config hash
- code revision
- dataset ID
- execution model

A future developer should be able to reproduce historical results from recorded metadata.

Material shared-feature definition changes may require feature versioning.

## 39. Strategy Versioning / Champion-Challenger

Do not mutate history when a strategy changes.

Use new strategy/config versions.

If only thresholds differ, prefer same implementation + different versioned config rather than duplicating whole strategy files.

Research variants must be clearly separate from production config.

New strategy versions should default to SHADOW unless explicitly promoted.

## 40. Environment Separation

Where supported, separate:
- development
- research/replay
- shadow
- production

Replay must not accidentally send production alerts.

Use alert-sink abstraction where practical: Discord, DB-only, console/dev, test collector.

Persist actionable events and delivery intent atomically before delivery so Discord failure does not erase research facts.

## 41. Idempotency / Duplicates

Design retried persistence, delivery, outcomes, and backfills to be idempotent where practical.

Provider reconnects may produce duplicate events; normalization should handle them.

Do not allow one source duplicate to generate multiple strategy alerts.

## 42. Feature Missingness / Required Data

Features should preserve missingness quality metadata.

Strategies identify features as:
- MANDATORY
- MODIFIER
- OPTIONAL

Runtime:
- mandatory unavailable → suppress
- modifier unavailable → degraded context/no modifier
- optional unavailable → continue

Use explicit kill/suppression reasons rather than generic `setup_invalid` when possible.

## 43. Research Boundary

Historical execution assumptions belong in validation/research, not strategy logic.

Keep distinct:
- trigger_price
- alert_price
- modeled_entry_price
- actual_manual_trade_price if ever supplied

Human decisions are separate records and must not change mechanical validity.

## 44. Security

Least privilege.

Broker tokens only to modules that need them. Discord credentials only to delivery layer. Research jobs should not require trading credentials unnecessarily.

Use existing environment/secret-management mechanism. Never commit secrets.

Sanitize exception payloads before logging.

## 45. Review Checklists

### General
- duplicate existing function?
- point-in-time safe?
- changed approved behavior?
- thresholds configurable?
- units clear?
- errors explicit?
- tests adequate?
- stale data could alert?
- state recoverable?
- replay deterministic?

### Strategy
- ID/version correct
- required data explicit
- eligibility/state/heads-up/actionable match `PLAYBOOKS.md`
- stale/invalidation/expiry handled
- structural stop/targets
- confidence preserved
- human checks represented
- long/short tested

### Data adapter
- timestamps normalized
- source preserved
- missing fields explicit
- staleness measurable
- reconnect/rate limit/duplicates handled
- secrets protected
- fixtures exist

### Research
- no look-ahead
- dataset identified
- strategy/config version stored
- execution/cost model explicit
- same-bar ambiguity handled
- OOS separated
- suppressed alerts not silently removed
- uncertainty represented

## 46. Avoided Patterns

Do not build:
- one giant `trading_bot.py`
- one scanner function for all strategies
- duplicated indicators
- provider payloads inside strategy logic
- hardcoded credentials
- hidden global config
- mutable historical alert records
- automatic threshold tuning
- production black-box ML
- a generic strategy DSL
- giant base classes
- general-purpose trading terminal

Prefer composition and concrete needs.

## 47. Restart / Recovery

On process restart during the session, restore or deterministically reconstruct enough state to preserve:
- opening range
- HOD/LOD references
- breakout attempts
- impulse origin
- pullback counts
- alert cooldown
- prior alert structures

Do not resume actionable alerts until required data/state continuity is valid.

## 48. Definition of Done — Shared Component

```text
[ ] Public contract defined.
[ ] Type hints present.
[ ] Point-in-time behavior documented.
[ ] Missing-data behavior explicit.
[ ] Unit tests pass.
[ ] Edge cases tested.
[ ] Logging/metrics appropriate.
[ ] No strategy-specific assumptions leaked in.
[ ] Reused by intended consumers.
```

## 49. Definition of Done — Strategy

```text
[ ] Approved config exists.
[ ] Required data declared.
[ ] State machine implemented.
[ ] Eligibility implemented.
[ ] Heads-up implemented.
[ ] Actionable trigger implemented.
[ ] Invalidation implemented.
[ ] Expiry implemented.
[ ] Staleness implemented.
[ ] Suppression implemented.
[ ] Stop logic implemented.
[ ] Targets implemented.
[ ] Confidence components implemented.
[ ] Option integration uses shared engine.
[ ] Human checks represented.
[ ] State transitions observable.
[ ] Unit/synthetic tests pass.
[ ] Replay integration works.
[ ] No duplicated shared feature logic.
```

This does not mean the strategy is profitable or active.

## 50. Final Coding Principle

The system should make the correct path the easy path.

Architecture should discourage look-ahead, duplicated indicators, unversioned thresholds, stale-data alerts, silent proxy use, mixed underlying/options logic, and mutable research history while supporting deterministic strategies, shared features, explicit states, structural risk, observable decisions, reproducible replay, controlled validation, and safe multi-session development.

## 51. Existing host and compatibility boundaries

Use `consensus_engine/__main__.py` and `main.py` for the existing application lifecycle; `config.py` and `config/consensus.yaml` for non-secret configuration; `scanners/schwab_client.py` for authentication/request reuse; `db.py` for migrations and transactions; and the existing Discord delivery path. See the exact reusable symbols and limitations in PREBUILD_REVIEW. These are integration boundaries, not permission to modify code during this review.

The README declares Python 3.10+, while deployment may select a newer interpreter. Preserve the repository's supported version and verify deployed/test versions at M0.4; do not silently raise the minimum to 3.11. Keep `requirements.txt`, `requirements-dev.txt`, `pytest.ini` and existing deployment conventions. New dependencies, a replacement framework, a different language or a major rewrite need an explicit proposal. Existing synchronous data calls must run through the established asynchronous wrapper/thread boundary rather than block the main event loop.

Use additive adapters and migrations. Preserve legacy quote fields, cache behavior, scoring semantics, command outputs and measurement attribution for existing consumers. Define new freshness/data-mode fields separately when legacy contracts cannot express them. Reuse calculation primitives only after checking units, lookback, seed and session semantics; the existing daily technical VWAP/RVOL filters are not the proposed intraday definitions.

## 52. Durable evaluation and delivery

One owner serializes each instrument/session state update. Define an event order, late/revised-data policy, bounded queue and explicit overload behavior; dropping a price event must not silently preserve a false acceptance window. Persist stable input IDs, structure IDs and frozen references so a restart reproduces the same transitions and suppressions.

Commit the immutable candidate, component strategy evaluations, suppression/confluence links and delivery intent together before outbound delivery. Use the existing transaction framework. Keep delivery attempts and acknowledgments append-only and separately keyed by alert and sink. A full disk or failed transaction suppresses sending and exposes an operational fault; it cannot produce an unrecorded mechanical alert.

Reuse the existing Discord sender behind a sink adapter. Add bounded expiry-aware retry, provider-directed retry delays, a confirmed message reference when available, and explicit UNKNOWN delivery after an ambiguous timeout. A crash after a successful send but before acknowledgment storage must not blindly repost. Reconcile using available message evidence or retain UNKNOWN for review. Local deduplication alone cannot promise exactly one remote message.

Escape external text and prevent unintended mentions. The renderer only formats frozen facts; AI text is optional enrichment and cannot alter trigger, stop, target, quality or eligibility. Missing AI output must still leave a complete deterministic alert. Respect current Discord payload limits and rate headers rather than invent fixed provider limits. [Discord webhook confirmation](https://docs.discord.com/developers/resources/webhook), [rate handling](https://docs.discord.com/developers/topics/rate-limits).

## 53. Isolation, recovery and rollout acceptance

Offline tests/replay use an explicitly injected temporary database, fake providers, fixed clocks and a recording sink, with credential reads and network calls configured to fail. Existing `db.DB_PATH` must be set for isolated database work; an invented environment override is unsafe. Loading the application or its dry-run mode is not an offline test.

On restart restore the persisted session/config/version, prior candidates, delivery state, cooldowns, OR, frozen HOD/LOD, impulses and pullback counts. Rebuild warm-up only from available-time-safe records; suppress actionable output until continuity is proven. Never replay an expired alert merely because it was pending at shutdown.

Stage the extension with independent collection/evaluation/delivery switches. Rollback disables the new path and returns to the previous code/config while preserving additive records. Verify old commands and scanners with the new path off and on. Preserve existing file ownership and deployment user. Private provider payloads and machine-local credentials stay outside public documentation and test fixtures. Retention must keep enough versioned inputs to reproduce accepted research runs.

## 54. Existing release controls

Use the exact failing-test-ID comparison in `.test-baseline`, `Makefile` and `scripts/pre-push`; never refresh the baseline merely to absorb a newly broken test. New strategy switch tests must exercise off and on paths. The existing flag-flip checker does not detect an absent flag becoming true, so release acceptance must cover both absent-to-enabled and disabled-to-enabled transitions.

M0.4 must compare checked-in deployment units with installed unit definitions and identify the approved source before any later deployment. The review found drift in startup checks, failure reporting and resource limits; copying the checked-in unit is not a proven safe rollback. No unit/configuration change is made in this review. Check Python/dependency support before choosing the deployed interpreter; changing the supported runtime is an explicit compatibility decision.

## 55. Implemented shared clock contract

M1.1 extends `consensus_engine/utils/time_context.py`; see
[M1_1_VERIFICATION.md](./M1_1_VERIFICATION.md). New consumers reuse `as_utc`,
`format_pacific`, `session_date_at`, `premarket_bounds`, `regular_session_window`
and `session_phase`. Existing `session_dates`, `session_bounds`, open-now and
prompt helpers keep their compatibility contracts.

New instants require an explicit offset/time zone. Session-date lookup returns
the exchange calendar date, including on closed days; it does not imply an open
session. Bounds/phase establish that separately. Premarket start is an explicit
Pacific clock-time argument, with no platform default. Regular windows take
caller-supplied elapsed offsets from scheduled open, use inclusive starts and
exclusive ends, and stop at the actual close. M1.2 owns validated settings and
M1.3 owns record serialization. Clock boundaries never establish bar finality,
coverage or feature readiness.

## 56. Implemented configuration foundation — M1.2

Use `config.get_trade_alerts_config()` once when a new session starts and retain
its `TradeAlertsConfig` snapshot. The existing `load_config`, `get`, mutable cache,
environment resolution for legacy settings and `reload` remain compatible.
The pure validation model in `consensus_engine/trade_alerts_config.py` does not
read files, environment variables, providers or storage. The existing loader
validates a present `trade_alerts` section before environment expansion; snapshot
capture validates again. Failed validation does not populate an empty cache.

Schema version `1` centralizes five configuration areas under `trade_alerts`:
`strategies`, `data`, `options`, `alerts` and `research`, plus `config_version` and
`evaluation_enabled`. Only known fields are accepted. Booleans and elapsed-minute
integers have strict types. Version labels are literal 1–64-character identifiers,
starting with a letter/digit and otherwise allowing letters/digits/dot/underscore/
hyphen. The default config label is `FOUNDATION_V1`. Unknown fields, invalid values
and environment references in this section fail without echoing the supplied value.

All eight strategy IDs are present in the normalized snapshot. Their `enabled`
values default false; `strategy_version` and `window` default null. An explicit
window supplies integer `start_minutes` and `end_minutes` satisfying
`0 <= start < end <= 1440`. Consumers pass these elapsed offsets to M1.1's
`regular_session_window`, which clips at the actual close. The optional
`data.premarket_start` is a quoted Pacific `HH:MM` string, with no default;
M1.1's `premarket_bounds` still checks the chosen date's pre-open constraint.
Clock-format validation alone does not establish a valid session or data coverage.

`data.collection_enabled`, `options.enabled`, `alerts.delivery_enabled` and
`research.enabled` default false. Option/research `policy_version` defaults null.
The alert `sink` defaults `recording` and also supports the identifier `discord`.
An enabled strategy requires an explicit version and window; evaluation requires
at least one enabled strategy. Enabled options/research require explicit policy
versions; requested delivery requires evaluation and the Discord sink identifier.
Disabled sections may retain explicit values without activating anything.

These checks validate the configuration's shape and internal consistency. A
version label or true switch is not approval, a complete policy, provider access
or runtime readiness. No strategy threshold, M0.3B proposal or D-090 numeric
research rule is a new default. Consumers must still enforce their approved
strategy, data, replay-sink and release gates under M4/M5/M9/M17/M18. No new
runtime consumes these switches in M1.2.

The fixed snapshot stores canonical JSON and its SHA-256 hash. Normalize missing
engineering defaults, sort keys, use compact separators, ASCII-escaped strings
and UTF-8 bytes, and include both version fields. Only the dedicated namespace is
hashed; never include the legacy root configuration, credentials or machine paths.
`as_dict()` returns a detached copy; input changes, cached dictionary edits and
reloads cannot mutate the snapshot. Consumers persist the canonical JSON, version
and hash with session records in M1.3/M5.1; persistence/restart/replay proof is not
completed here. Extend this versioned shape compatibly when later approved rules
need fields; preserve the ability to read earlier snapshots. See
[M1_2_VERIFICATION.md](./M1_2_VERIFICATION.md) for actual proof and limits.

## 57. Canonical record contract — M1.3

`consensus_engine/trade_alerts_models.py` contains the additive record layer;
legacy `models.py`, provider mappings and measurement tables keep their existing
contracts. See [M1_3_VERIFICATION.md](./M1_3_VERIFICATION.md) for execution status
and evidence. This layer contains facts and validation, not strategy evaluation,
provider access, persistence or delivery.

Records use frozen dataclasses, typed nested values and tuples. IDs and instants
come from callers; constructors do not invent current times or identifiers.
`as_dict()` returns detached JSON-compatible values, `to_json()` writes sorted,
compact, ASCII-escaped JSON, and typed `from_json()` or `record_from_json()` restores
the record. Schema version 1 and the record type are explicit. Unknown versions,
types, missing/extra serialized fields, duplicate JSON keys, malformed nested
values, naive instants, booleans supplied as numbers and non-finite numbers fail.
Later incompatible field changes require a versioned reader; do not relabel old
stored records with the current version.

Source metadata preserves instrument/source/session identity, separate source,
received, available and normalized instants, optional sequence, revision, mode
and quality. Instrument type is EQUITY/ETF/OPTION/UNKNOWN; session identity must
be a canonical YYYY-MM-DD calendar date. New instants reuse M1.1's `as_utc`; visible formatting reuses
`format_pacific`. Availability is explicitly supplied, never inferred from a
cache read or a bar's start. A later normalization does not replace original
availability. Revision records receive their own caller-supplied identity; they
cannot mutate an earlier frozen record. Quality supports the five DATA §4 states
plus explicit `UNKNOWN`. These fields do not prove provider coverage or freshness.

Bars retain start/end/finality and price, volume and adjustment conventions.
Unavailable OHLCV stays null; a certified no-trade interval has null prices and
explicit zero volume. A final bar cannot be available before its end. This is
record consistency only; certified no-trade records also require final/VALID
evidence. M2.2/M3.6 still prove actual finality and complete opening
range inputs. Quotes retain distinct quote/trade instants and nullable values,
including last-trade size. Base state labels are constrained; strategy-specific
substates are separate. Legal transitions remain a runtime contract.
Option records preserve exact contract identity, expiry, strike, side, multiplier,
deliverable, volume/OI and optional Greeks; absent values and flags stay unknown.

Feature snapshots carry definition versions, units, missing reasons and input
references. Candidates preserve heads-up/actionable type, structure, direction,
setup/lifecycle/evidence labels, structural risk and targets, score components
and factors, confluence, human checks, expiry and configuration/session references.
Prices, risk geometry and score bounds are validated without selecting any new
trading cutoff or calculating a score. Target sources and R multiples are frozen
facts. A score is relative quality, never a win probability.

Options recommendations have separate recommended/poor/unavailable results.
Unavailable options do not require an invented contract. Delivery, human choices,
suppression and outcomes are separate linked records. Modeled/manual prices live
in the result/decision records, not the mechanical candidate. Outcomes retain
nullable MFE/MAE in instrument price dollars, maximum R, stop and individual target
hit facts/times, policy attribution, coverage and input references. Unknown results
are not zero returns or false hit flags. No outcome or fill model is executed here.

`SessionRecord.from_config()` copies M1.2's existing fixed snapshot; restoring a
session checks the canonical settings against its version and SHA-256. Candidate
references identify that session and configuration. M5 owns validating linked
record existence/identity, atomic storage and restart/replay integrity. Holding
an ID/hash, setting an enum-like label or constructing a mechanically-valid record
does not establish approved strategy rules, data eligibility, an allowed runtime
transition, delivery, a trade or profitability. Those gates retain their roadmap
owners. No live path imports this layer in M1.3.

## 58. M2.1 offline Schwab normalization contract

`consensus_engine/scanners/schwab_normalization.py` is a pure companion to the
existing Schwab client. Its three functions, `normalize_schwab_bar`,
`normalize_schwab_quote` and `normalize_schwab_option_quote`, accept raw REST
response pieces before legacy conversion and return M1.3 records. They introduce
no client, authentication, request, cache, database, configuration switch or live
consumer. Existing caller interfaces and field meanings remain unchanged.

Callers supply record identity, original `SourceMetadata`, response identity and
explicit observation context. Source must be `SCHWAB`; another provider must use
its own source and adapter. Metadata cannot be relabeled to conceal a fallback.
The raw candle timestamp is preserved as source time; its interval start/end are
caller-supplied facts. Quote snapshots use the original quote timestamp as source
time, falling back to trade time only when quote time is absent, and retain both
individual times. A newer trade never refreshes the sides. Missing original event times
remain null. Supplied source time must agree; no current time or ID is generated.
Original receipt and availability survive later normalization and duplicate reads.
Revisions remain separate caller-identified immutable records.

Bar boundaries, finality and adjustment conventions need independent evidence.
Neither an index timestamp nor elapsed wall time proves finality or coverage.
Unspecified finality stays false and unspecified adjustment stays unknown.
Incomplete or impossible candles fail explicitly; the mapper does not create
missing intervals, infer a certified no-trade bar or fill missing volume with zero.

Canonical equity `last` is raw `quote.lastPrice`, paired with raw `tradeTime`.
The old client's `c` continues to prefer regular-session last price. Preserve
millisecond precision, separate quote/trade times, nullable sizes and delay status.
Caller-supplied quality/status are evidence inputs, not freshness calculated here.
A valid quote needs a quote timestamp, two positive reported sides, valid supplied quality
and explicit non-delayed status. Crossed quotes, contradictory identities/times
and a valid label on delayed data fail. Unknown/stale/degraded context must not
be silently upgraded. Numerical age, session and stock/option skew gates remain
with M0.2/M0.3 and M2.3/M14.2; normalization does not complete those live gates.

Options retain the exact raw contract symbol and enclosing response context for
underlying, expiry and side, plus strike, multiplier and non-standard/deliverable
facts. Contradictory supplied/raw context fails. OI as-of time is an explicit
caller fact or null; it is never copied from quote or retrieval time. Preserve
signed Greeks and the existing client's percent-to-fraction volatility convention.
Unknown flags and optional invalid/sentinel values remain null. Valid zero counts
remain zero; non-positive volatility remains unavailable under the existing
convention. Sizes, Greeks and OI retain reported values without asserting verified
provider units or publication timing. Those M0.2 evidence questions remain open.

Use raw synthetic payloads through the protected launcher. Test deterministic
round trips, original availability, revisions, missingness, contradictory context,
invalid geometry/times, delay status and unchanged legacy conversions. No new
strategy formula, age threshold, streaming field map or runtime activation belongs
to this mapping milestone.

## 59. M2.2 historical interface — offline contract

`consensus_engine/historical_bars.py` adds a pure offline request, batch and
coverage interface. [M2_2_VERIFICATION.md](./M2_2_VERIFICATION.md) records actual
status; this written contract is not a passing test or provider evidence.

`HistoryRequest` uses explicit absolute start/end times with an exclusive end.
The shared exchange calendar defines expected scheduled bars, excluding closed
hours, holidays and weekends and honoring shortened sessions. Minute edges must
align to whole minutes. Daily means a whole regular session; a partial daily
request fails. Premarket requires an explicit Pacific start; no default is added.
Its provider arguments reuse `schwab_client.get_price_history_payload()`, which
contains the existing request construction/authentication path before table
conversion. `get_price_history()` retains its signature and legacy table output;
`prices.fetch_history()` retains its existing fallback behavior. The raw function
propagates request failure and performs no fallback. It is synchronous and must
use the host's existing thread boundary if later called from an asynchronous task.
No live consumer is added.

`normalize_schwab_history()` requires the raw response symbol, a candles list,
one original `SchwabBarContext` per candle and `HistoryConventions`. It reuses
M2.1 normalization; source timestamp is not assumed to be the interval start.
START/END stamps must match their declared boundary; EXPLICIT records an
independently supplied mapping. Daily calendar-day aggregates cannot satisfy a
regular-session contract. Original received/available/normalized times, revisions,
prices, volume, quality and adjustment basis stay on the immutable Bar records.
Empty responses supply no bars. They never certify no-trade intervals.
Finality and publication conventions each need a known label and the source
evidence reference. `UNKNOWN` and `UNSPECIFIED` references, ignoring case and
outer spaces, remain unknown and block complete coverage while preserving the
supplied records. Setting `is_final` alone cannot establish complete coverage.

`HistoryBatch.coverage_at()` considers only records whose original availability
is at or before the evaluation time. It selects the highest available revision
per expected interval; a newer provisional or invalid revision blocks the
interval. Equal-revision differing facts are CONFLICT; exact repeated facts count
once and report their duplicate count. Different record IDs and local received/
available/normalized times are ignored when comparing repeated market facts;
the earliest available copy wins, so a re-fetch never refreshes original data.
Source time, sequence, OHLCV, finality, quality and conventions must still agree.
Reusing one ID for changed facts fails. Archive
exports retain every input revision; they are not an evaluation view.

Coverage distinguishes NOT_ENDED, MISSING, PROVISIONAL, final/no-trade, bad quality,
unknown/incompatible conventions and conflicting observations. MISSING means no
observation was available then, not confirmed feed loss or certified zero volume.
A just-ended observed provisional bar stays PROVISIONAL. Unexpected available
records overlapping a requested interval remain visible and block complete
coverage. Disjoint outside-scope records, such as postmarket bars returned for a
premarket request, remain visible separately without blocking the requested set. Mixed
sources or symbols fail; mixed/unknown data modes and incompatible price/volume/
adjustment conventions cannot silently become complete. Convention/venue evidence
references are caller facts, not externally verified here. A future source event
cannot claim earlier availability. No external capability is inferred from labels.

`complete` requires a nonempty set of expected intervals all final and valid under
the supplied conventions. It describes coverage only. Certified no-trade bars
retain null prices and zero volume; even complete all-no-trade coverage cannot
produce opening-range extrema. M3.6 owns the actual range and traded-input gate.
`final_bars` is the covered subset and must not be used to hide missing intervals.
All new switches remain off; no provider, storage, feature or strategy runtime is
activated. The archive identifies interface version M22_V1; canonical Bar readers
retain schema version 1. No existing record shape or trading rule changes.


## 60. M2.3 offline normalized Quote event contract

`consensus_engine/quote_events.py` consumes existing immutable `Quote` snapshots.
It adds no transport, raw stream mapping, background task, queue, file access,
configuration default, clock read or live consumer. One caller serializes each
source/instrument/type/session/data-mode stream. The existing REST normalizer and
canonical models remain unchanged. M2_3_VERIFICATION records execution status.

`QuoteEventPolicy` requires a known version and finite positive maximum quote age,
trade age and observation gap, in seconds. Equality is within the supplied limit.
There are no numeric defaults. Null policy is allowed but cannot produce usable
data. A version identifies supplied policy; it is not trading approval.

`QuoteEventStream.consume()` uses an explicitly supplied, timezone-aware,
nondecreasing evaluation time. It never reads the current clock. A future
available-time record cannot replace current facts. Source, instrument/type,
session and mode must match the fixed scope; ages use quote/trade timestamps
separately. Current source quality/status, delayed/unknown delay, missing positive
prices/times, wrong session and original availability remain explicit. Missing
sizes are preserved; no new size threshold or trade-volume rule is introduced.

A repeated latest snapshot ignores its new local ID, receipt, availability,
normalization and opaque sequence for duplicate comparison. It keeps the original
record and forwards nothing. Quote/trade timestamps each advance independently;
only their corresponding new observations can forward. A sequence jump does not
imply missing messages without a defined provider sequence contract. Older
snapshots reject as OUT_OF_ORDER and lose continuity, including older duplicates
outside the retained latest snapshot. Same-time changed price/size facts conflict.
No partial-update merge or guessed sequence ordering is performed. A reused current
record ID cannot change facts. Full historical ID/link enforcement remains M5.

Explicit revision records remain visible without forwarding a new observation;
they lose continuity and need a new unrevised observation before confirmation.
Bad/missing snapshots replace current data with an unusable result; the last good
quote cannot hide new missingness. This includes a missing or wrong-session source
time even when quote/trade timestamps are unchanged. A same-session source time
before recovery cannot be ignored over a healthy snapshot. A source time after
original availability is retained with `INVALID_SOURCE_TIME`; waiting for that
source time does not make the record valid. A retained snapshot remembers whether
it was rejected on consumption, so a same-time cache cannot replace that bad input
or heal it. New healthy observations clear that marker; recovery still needs fresh
matching proof. Time/fact watermarks remain for each component.
Same-time cache data cannot heal a missing snapshot. Only a current record and two
component watermarks are retained; decision persistence belongs to the caller/M5.
No unbounded event history or parallel mutable state owner is added.

Connect/disconnect, a caller-reported gap, out-of-order/conflicting input and
invalid data clear continuity. Elapsed gaps use original availability of new
observations, never cache read times. Reconnect does not erase watermarks or
restore continuity. Confirmation needs explicit non-unknown evidence tied to the
current epoch and record, a newly consumed healthy observation in that epoch,
and source/quote/trade times at or
after the recovery boundary. Epochs prevent old recovery proof from being reused.
The caller must independently establish warm-up/coverage for that scope; this
method validates attribution, not the truth of a provider claim.

`QuoteEventDecision` is frozen and has detached deterministic JSON marked M23_V1.
It records the current original Quote, policy, separate ages, connection,
continuity/epoch/reference, reasons and action/input identity. `usable` describes
the retained current snapshot under these checks, not acceptance of an ignored
input. Downstream sampling uses **only** `forward_quote` / `forward_trade`;
inspection, confirmation, duplicate, rejected and recovery inputs do not forward.
A new last-trade snapshot is not a complete tape feed or certified trade count.
Feature acceptance, VWAP/RVOL and tape-count logic remain M3/M6; M5 retains durable
replay/recovery. All live streaming and provider evidence remain M0.2/M2.3 gates.


## 61. M2.4 supplied reference-input contract

`consensus_engine/reference_inputs.py` gathers existing canonical records via
M2.3 `QuoteEventDecision` and M2.2 `HistoryBatch.coverage_at`. It adds no client,
stream owner, clock read, database, background task, configuration default or
live consumer. See [M2_4_VERIFICATION.md](./M2_4_VERIFICATION.md) for actual status;
written tests are not passing evidence.

`ReferenceScope` fixes one of SPY/QQQ and DATA §12's 11 sector ETFs, known source,
quote/history modes, an explicit versioned quote policy or null, and a matching
history request or null. Empty/unknown source or mode labels cannot establish
coverage. No live numerical age or history-window policy is introduced.

`build_reference_snapshot` takes an aware evaluation instant and its calendar
session. Quote decisions must be evaluated at exactly that instant. Earlier
usable decisions remain visible but cannot pass a current check; later decisions
or unavailable quotes cannot supply earlier values. The original M2.3 reasons,
separate quote/trade ages, continuity and policy stay visible. Source, ETF identity,
instrument type, mode and session must match each scope. Canonical Quote validation
already rejects quote/trade times after original availability; M2.3 rejects a
future availability. M2.4 does not duplicate or weaken either rule.

History uses the exact supplied request and source. It retains original M2.2
scheduled intervals, missing/finality/revision/quality states and conventions.
An absent batch still shows its expected intervals; an absent request cannot
invent a window. Each selected bar must also match the ETF type and history mode.
Historical requests may cover earlier sessions; their records must match those
requested sessions, not be relabeled as today's data. Consumers must check the
reference row's `history_complete`, not borrow an inner covered subset.

Thirteen expected ETF rows and one explicit VIX row are emitted in a stable order.
Counts describe supplied usable quotes or complete requested history only; neither
is provider-wide coverage or a breadth score. Quote and history availability are
independent. Missing references do not borrow other symbols, silently substitute
proxies, renormalize weights or select a return/relative-strength formula.

Stock lookup reuses `analysis.wolf_scope.stock_sector_etf` and its unchanged source
file. Returned pairs are frozen separately as CURRENT_MAP_ONLY with historical
membership UNAVAILABLE. Unknown mappings stay null. Current lookup does not prove
historical availability, sector composition or any expected ETF's market data.
VIX remains UNSUPPORTED_INDEX_INPUT because current canonical instrument types and
QuoteEventStream do not support an index contract. Existing VIX text/transport
aliases are preserved; no index record, ETF substitute or VIX price is fabricated.

`ReferenceSnapshot` contains frozen nested records/tuples, detached `as_dict` values
and deterministic M24_V1 JSON. Original times, per-symbol policy, request and
conventions stay attributable. Caller dictionary/stream changes and later history
or map revisions cannot mutate the saved output. This is a supplied-record snapshot,
not full M5 durable replay or M2.4 live source integration. All switches remain off.

## 62. M3.1 supplied-record core price features

`consensus_engine/core_price_features.py` is a pure offline calculation boundary.
It consumes M2.2 history and an explicit identified opening trade. It performs no
fetch, clock read, storage, configuration change or activation. Existing Wilder ATR
and generic VWAP callers are unchanged.

`D090_CORE_PRICE_FEATURES_V1` uses D-090's fixed 20-minute and 14-day arithmetic
ATR, bar HLC3 session VWAP and current/prior/premarket extrema. It selects scheduled
slots before availability checks. Unexpected malformed records block only the
required slots they overlap, including a needed preceding minute close and any
intervening certified no-trade slots. An unrelated older or prior-session malformed
record cannot erase a complete selected window. Missing, revised-invalid or
incompatible required input stays missing. Certified no-trade minutes add zero without inventing a price.
The first traded minute after certified no-trade opening minutes uses its own
high minus low; it does not require an invented prior close. An older missing
daily session blocks the 14-day ATR but does not erase a complete immediately
prior session's high, low or close.

Minute ATR previous-close lookup is limited to traded regular-session minutes in
the same session. A premarket close cannot enter regular-session true range,
including when the regular open is a certified no-trade minute. Minute VWAP,
minute ATR and current HOD/LOD require a `1m` history request. Daily ATR and prior
levels require a `1d` request. A daily bar cannot stand for a minute session, and
the last minute of a date cannot stand for its daily bar.

Session open requires a separately identified compatible opening trade; it does
not require daily history or a prior close. Its source and price basis must match
the supplied history basis. Gap additionally requires a usable positive prior close.
Its trade/source time cannot follow its original availability or the evaluation
time. Prior-session levels, prior close and the valid opening observation are not
coupled to completion of the older 15-session ATR window.
Price-producing M3.1 features require the exact `USD_PER_SHARE` convention. Bar
VWAP additionally requires `SHARES`; a wrong volume unit blocks VWAP without
erasing ATR or extrema that do not use volume. Each feature checks only its needed
history. A gap also requires the daily close and opening observation to share the
same source, adjustment and venue/eligibility basis. Opening prices must be finite
and positive. Opening instruments must be EQUITY or ETF and match the supplied
history type; OPTION, UNKNOWN and mismatched types cannot supply open or gap.
Full eligible-trade VWAP remains a separate blocked mode.

Instrument checks, opening compatibility and snapshot identity use M2.2's selected
available-time coverage, including its latest revision selection. Raw future or
superseded revisions cannot supply or change identity. With no selected identity,
the output stays UNKNOWN. Premarket extrema require the complete current session's 01:00 Pacific
to scheduled-open window from the shared calendar. Overall request start does not
establish that boundary: truncated same-day requests remain incomplete, while
complete current windows within multi-session requests remain usable.

## 63. M3.2 supplied-Bar participation contract

`consensus_engine/participation_features.py` adds a pure
`build_participation_snapshot` beside the existing price features. It reuses M2.2
coverage, M1.1 calendar helpers and M1.3 immutable FeatureSnapshot/FeatureValue
records. Its explicit symbol and EQUITY/ETF scope never come from future input.
There is no I/O, runtime consumer, configuration change or new trading threshold.
Existing daily relative-volume and Wilder/weighted-price helpers remain unchanged.

`D090_PARTICIPATION_FEATURES_V1` implements only D-090 F-02's
`RVOL_OPEN5_MEAN20_V1`, `PM_RVOL_MEAN20_V1` and
`DOLLAR_VOLUME_CLOSE_PROXY20_V1`. Select the exact 20 prior exchange sessions
before looking at data. Minute features require the full current and reference
windows; opening volume always uses the first five minutes, and premarket always
uses 01:00 Pacific through the scheduled open. Dollar volume uses only the 20
prior regular-session daily bars. Decimal arithmetic precedes numeric serialization;
no display rounding or strategy comparison is performed here.

The caller supplies one history source/venue/adjustment basis per calculation.
Required Bar units, modes, instrument type, finality and original availability
must agree. The input histories retain the original source conventions and
evidence references; snapshot input IDs link the selected records to those
histories. Keep these histories when storing research under M5. Missing values
retain explicit reasons and available input IDs; no zero-volume substitution
or older-session substitution occurs. A certified zero current volume may
produce zero RVOL. A zero reference denominator stays unavailable. Missing daily
close cannot be invented even for a certified no-trade daily interval.

Only observations overlapping required windows enter M2.2 selection. Malformed
overlapping records block the result; disjoint records cannot change its identity,
mode or volume. Latest available revisions govern each newly built snapshot,
with duplicate/conflict rules delegated to M2.2. Each returned snapshot freezes
its chosen values and input revisions; later data cannot alter it. Callers must
retain the original ready snapshot rather than overwrite its recorded facts.
A bounded calendar-window cache holds no input data or live state.

The result is supplied-record evidence only. Full source proof and the remaining
M3.2 branches stay blocked under M3_2_VERIFICATION §5. No generic cumulative,
tape, projected-minute or exact traded-dollar mode is silently substituted.

## 64. M3.6 supplied-Bar opening-range contract

`consensus_engine/opening_range_features.py` adds the pure
`build_opening_range_snapshot` calculation. It reuses M1.1 session bounds, M2.2
available-time coverage and M1.3 immutable feature records. It performs no fetch,
clock read, storage, configuration change, switch activation or live work.

`D090_OPENING_RANGE_5M_V1` uses exactly the five scheduled one-minute intervals
starting at the regular-session open. High and low use traded final Bars only;
mid is `(high + low) / 2` and width is `high - low`. Decimal arithmetic happens
before numeric serialization. The complete value is true only when all five
scheduled intervals are final and available and at least one contains a trade.
Before then, all four prices remain unavailable. A certified no-trade interval
contributes no invented price.

The caller supplies symbol, EQUITY/ETF type and one minute-history batch. Required
source, mode, session, `USD_PER_SHARE`, `SHARES`, adjustment and venue basis must
be known and compatible. The calculation selects only revisions available by the
evaluation time. A later revision changes only a newly built snapshot. Missing,
provisional, invalid, conflicting, mixed-mode or malformed overlapping records
keep the range incomplete. Wider history requests are allowed, but records outside
the five opening slots cannot affect the result. The batch's original request must
include every one of the five opening intervals. Archived Bars outside a truncated
or disjoint request cannot be used to manufacture complete requested coverage.

The returned FeatureSnapshot contains high, low, mid, width and an explicit
complete value. Input IDs preserve the selected opening records. This is a
supplied-record software contract only. Actual provider coverage, finality,
corrections and compatible source evidence remain blocked under M0.2/M2.2 and
M3_6_VERIFICATION §4. No strategy trigger or profitability result is created.

## 65. M4.1 common strategy interface

`consensus_engine/strategy_interface.py` defines interface version `M41_V1` using
the repository's existing typed-interface and frozen-dataclass conventions. It
does not register a strategy, import the application, fetch data, read settings,
read a clock, write storage or send output. No live consumer is added.

`Strategy` exposes strategy ID/version, required-data declarations, current setup
state, update, heads-up/actionable results, invalidate, expire, reset, confidence,
stop and targets. It reuses `AlertCandidate`, `StrategyStateTransition`,
`SessionRecord`, `ConfidenceBreakdown`, `RiskLevel` and `TargetLevel`. No duplicate
candidate, score or risk record shape is introduced. Incomplete subclasses cannot
inherit unimplemented operations. A runtime member-presence check is only a shape
check; it does not prove implementation behavior, approval or readiness.

`RequiredData` declares a name, MANDATORY/MODIFIER/OPTIONAL role, definition version
and data mode. Unknown definition/mode labels cannot masquerade as a specified
contract. The declaration does not certify coverage or define a fallback.
`StrategyState` holds a canonical setup state and optional separate substate;
lifecycle, evidence, data quality and delivery remain distinct.

`StrategyContext` fixes the session/settings record, underlying symbol/type,
direction and explicit evaluation instant. Its canonical feature snapshots,
current QuoteEventDecision and catalyst records are immutable supplied values.
It rejects future availability, future feature evaluation/classification,
source time after original availability, duplicate input IDs and wrong quote/
catalyst identity. Feature snapshots belong to the current session and may carry
explicit reference symbols. Consumers select symbol, definition, units and mode
together; another instrument's identically named feature is not a substitute.
The quote decision must be evaluated at this exact instant for this underlying.
Prior catalyst events remain allowed when already available. Missing/unknown
data stays visible. Older features are not refreshed by making a new context.

One caller serializes each strategy's instrument/direction/session updates. Update,
invalidate and expire return canonical transitions for later persistence. Getter
methods expose only the latest evaluation, without generating new alerts on reads.
An implementation replaces prior outputs on each update and emits no actionable
from invalid mandatory data. Reset clears session state and outputs using the
supplied fixed session; earlier immutable records do not change. The interface
does not supply a trading transition graph, expiry duration, confidence formula,
stop/target selection, deduplication or reset policy. Those remain with M4.2–M4.7,
M5 and the approved playbook implementations. Test-only behavior is not a playbook.

Execution status and the bounded next step are in
[M4_1_VERIFICATION.md](./M4_1_VERIFICATION.md). All switches remain off.

## 66. M4.2 supplied-rule state transitions and append-only storage

`consensus_engine/state_transitions.py` implements `M42_V1`. `TransitionRules`
requires an initial M4.1 StrategyState and exact allowed state/substate pairs.
There is no default graph, inferred terminal edge, expiry duration or trading
eligibility rule. Empty rules allow no changes. Identity, rules and the complete
canonical SessionRecord/configuration are frozen in `TransitionScope`.

`StateTransitionEngine.apply()` takes an existing canonical transition and M4.1
context. Both must match the owner session, symbol, underlying type, direction,
strategy/version and evaluation time. Source time cannot follow original
availability; availability/normalization cannot follow evaluation. Referenced
features must be in the context; input references must be direct context records
or parent IDs explicitly carried by its feature snapshots. Parent references are
not proof of raw-record existence; M5.1 owns complete retention/link integrity.
Unknown market inputs may support an explicit invalidation, never an inferred
favorable trading decision. Strategy consumers still own mandatory-data gates.

One asynchronous lock serializes apply/reset for each owner. Accepted times cannot
move backward. Equal-time transitions retain explicit call order through a local
positive position and predecessor ID. Old state/substate must match exactly and
the proposed edge must appear in the supplied rules. Contract inconsistencies
raise RecordError without recording or changing state. An identical latest retry
returns the same entry; changed facts cannot reuse its ID. Only the current state
and last entry are retained. No unbounded in-memory transition archive is added.

The injected asynchronous sink receives a frozen `TransitionEntry`. State advances
only after its acknowledgment; errors propagate without advancing memory. Callers
must await successful recording before releasing dependent output. Same-session
reset, invalidation and expiry require explicit allowed transitions. `reset()`
accepts a distinct later SessionRecord and resets only current memory. Earlier
records remain unchanged. A fresh instance may replay the same ordered inputs;
this does not implement automatic restart reconstruction or restore a playbook's
private state, cooldowns, candidates or delivery.

`consensus_engine/transition_store.py` receives the existing AsyncConnection,
never a database path or implicit default connection. Additive migration 35 in
`db.py` creates `trade_alerts_transitions_v1`. Each row preserves the complete
canonical transition JSON, scope JSON, stable owner identity, position and
predecessor. The stable identity includes session record ID, symbol, type,
direction and strategy ID; changing version/configuration/rules cannot silently
fork that same owner's stored sequence. The original scope remains available for
later M5 reuse. No old table, version note or transaction method is changed.

The existing `execute_transaction()` checks predecessor/scope and appends one row
atomically. Identical saved retries add nothing. Reused IDs, competing positions
and inconsistent scope cannot overwrite facts; update/delete triggers enforce
append-only storage. The store rereads the full row before acknowledging an
identical save. `read()` restores ordered canonical transitions and checks the
requested scope against stored scope. Full atomic candidate/delivery bundles,
raw/feature storage and crash/restart recovery remain M5.1/M5.5. All switches stay
off and no application consumer is added. Execution evidence is M4_2_VERIFICATION.

## 67. M4.3 supplied D-090 risk/target contract

`consensus_engine/structural_risk.py` implements the pure
`D090_B_RISK_TARGETS_V1` selector for the two adopted B research variants.
`PriceInput` binds one existing FeatureSnapshot value to an explicit common
source/venue/adjustment price-basis label. Required units are USD_PER_SHARE;
unknown values, definitions, modes, basis and identity remain unavailable.
Derived producer names may differ while their explicitly supplied underlying
basis must agree. No supplied label establishes external source truth.

`RiskTargetRequest` fixes direction, variant, crossing/evaluation times and five
feature inputs: path anchor, crossing-frozen ATR_1M_20_SMA_V1, increment, boundary
and eligible latest trade. Frozen inputs must already be available at crossing;
anchor/entry snapshots must describe this trigger. Path modes remain distinct:
ELIGIBLE_TRADE_PATH and QUOTE_LAST_TRADE_PATH_ESTIMATE. Complete path coverage and
known evidence are explicit caller facts; path production and source proof remain
required upstream. Identity/time mismatches, conflicting snapshot IDs and future
revisions cannot supply earlier geometry. There is no implicit clock or fetch.

Exact rational arithmetic from canonical decimal text implements outward floor/
ceiling stop rounding, positive directional R and the inclusive 0.35 extension
limit before numeric serialization. Zero ATR stays known; no ATR-denominator
check is being performed here. Unknown/zero tick and nonpositive stop/risk cannot
be used. B remains unrounded. Existing RiskLevel and TargetLevel shapes do not
change. Expected missing data and geometry rejections return explicit results;
invalid typed contracts raise RecordError without I/O.

`StructuralCatalog` retains a supplied version, original metadata, common price
basis, all seven D-090 families and typed per-level target/obstacle roles. Complete
coverage must be available now and extend through evaluation. Missing families,
unknown evidence, late/stale or incompatible levels block the catalog; no family
is silently optional. Sort directional prices, merge equal prices with every
label/input link, reject nearer blocking obstacles, choose admitted T1 >=1.5R
and next distinct T2 >=2.5R. No T1 rejects; no T2 stays unavailable. No multiple,
AVWAP/profile producer, applicability rule, soft invalidation or runner is invented.

The frozen result retains the full supplied request, raw stop, canonical risk,
extension, canonical targets, merged labels/links and missing reasons. READY
means supplied geometry, not strategy readiness. Deterministic JSON and detached
exports support later M5 retention without a second database. No live consumer,
configuration change, new dependency or activation is added. Actual execution
and remaining full-service gates are in M4_3_VERIFICATION §§3–4.

## 68. M4.4 supplied confidence composition contract

`consensus_engine/confidence.py` adds pure `compose_confidence`, version `M44_V1`.
It reuses M4.1 StrategyContext and existing immutable feature, confidence and
session records. No live consumer, loader, clock read, factor producer, storage,
configuration default or score cutoff is added. Execution status and full
definition/source gates are in [M4_4_VERIFICATION.md](./M4_4_VERIFICATION.md).

ConfidencePolicy identifies the strategy/version, supplied policy version, exact
three weights and complete required term roster. Each Setup/Context/Execution
component declares exactly one score and at least one factor contribution. Terms
bind exact feature names, definition versions and data modes to canonical snapshot
IDs through ConfidenceRequest. All selected values use SCORE_POINTS. Scores are
already normalized upstream and must lie in 0–100; factor contributions remain
finite signed supplied values. No factor-to-score normalization or additive
formula is assumed. Those full definitions remain blocked under M0.3/M4.4.

Weights are explicit finite fractions in [0,1] and must sum exactly to one using
their decimal text. No supplied weight changes, missing-factor renormalization,
substitute or omission occurs. All declared terms are required even at zero
weight. Unknown inputs return UNAVAILABLE and no ConfidenceBreakdown. Malformed
policy/bindings raise RecordError. A non-null strategy version in the saved
session cannot contradict the supplied policy version for that strategy.

The existing context rejects future/unattributed records and duplicate IDs.
Composition also requires current evaluated scores, matching underlying/type,
session, declared definition/mode, valid or explicitly degraded quality, known
source time and feature input references included in the snapshot's references.
An older score cannot be refreshed by a new request. Reference-market ancestors
may support a supplied underlying score; another instrument's score cannot be
substituted directly. Supplied labels/references never prove actual source truth.

Exact rational weighting precedes numeric serialization and display rounding.
The existing ConfidenceBreakdown holds the three scores, final bounded score and
unchanged named/versioned factor values. The full immutable result keeps original
features, term membership, weights, policy and fixed session/configuration. It
exports detached deterministic JSON for later M5 retention alongside candidates.
The compact breakdown alone is insufficient attribution; no second store or new
canonical record version is introduced. READY means supplied composition, not
approved policy, trading eligibility, calibrated probability or profitability.

## 69. M4.5 supplied candidate assembly contract

`consensus_engine/candidate_assembly.py` adds pure `assemble_candidate`,
`assemble_suppression` and `candidate_is_expired`, version `M45_V1`. Existing
canonical record shapes and readers are unchanged. There is no loader, clock
read, store, provider, renderer, live registration or configuration change.

Assembly receives explicit prices, canonical risk/targets, state, structure ID,
expiry, validity, lifecycle, evidence, quality and human checks. Direction,
creation time and session/configuration references come from the fixed M4.1
context. Metadata must match its underlying/type/session and be available at
evaluation. Known configured strategy versions cannot be contradicted. Geometry
must match direction and R when supplied, including on heads-ups. No target,
score cutoff, validity decision, state graph or expiry duration is selected.

The full M4.4 result must match the exact context and strategy/version. Its
supplied calculation is checked through the existing composition function; an
altered score/status/reason cannot masquerade as that result. Primary and bound
confidence snapshots must remain in candidate input references. Missing confidence
or primary snapshot yields UNAVAILABLE with no candidate. Missing required valid
actionable prices/risk/targets or unusable supplied quality/source facts also
yield no candidate. Known zero confidence stays zero. Explicit degraded inputs
cannot be concealed behind VALID summary quality. Mandatory feature selection and
numerical freshness policy remain with adopted strategy definitions.

CandidateAssembly retains the full context, confidence result and every supplied
component candidate, including unlinked opposing candidates for later research.
Confluence links must identify distinct supplied candidates of the same direction
and exact strategy. Components match the underlying/session/configuration and
must already exist by evaluation. No primary priority, expiry-based component
selection, price-distance rule, merging or confidence bonus is inferred. Original
component bytes are retained; they are never overwritten by the assembled result.

The candidate begins with PENDING delivery status. This creates no delivery intent
transaction or send. Suppression uses a separate canonical record with the caller's
explicit reason and current context, either before a candidate exists or linked
to its original facts. Later suppression can reference the candidate's preserved
inputs. Expiry inspection uses an explicit aware instant at/after creation;
equality with expires_at is expired. It neither changes state nor creates a
suppression reason, cooldown or retry. Deterministic detached exports support M5
retention; input IDs alone do not prove stored raw-record existence.

M4_5_VERIFICATION records execution status. M0.3/M4.7/M6–M15 retain automatic
strategy/suppression/portfolio definitions and behavior; M5 retains complete
storage/recovery. No required source or trading-definition gate belongs to this
common supplied assembly mechanism. All earlier blocked branches remain open.

## 70. M4.6 offline rendering and supplied delivery boundary

`consensus_engine/alert_delivery.py` implements `M46_V1`. RenderedAlert formats
existing immutable candidate/option records only. It preserves supplied prices,
risk, target multiples/sources, confidence components, quality/mode, expiry and
human checks. Unknown facts stay unavailable; zero remains known. All dates use
the shared Pacific formatter. External markup, mentions and line breaks are
escaped. Rich and plain output contain the same full text. Complete fallback must
fit one 2,000-character message, conservatively counted in UTF-16 units; oversized
input raises RecordError instead of losing facts or claiming partial delivery.
No AI output, score/target calculation or option selection is required.

The new `alerts/discord.py:send_trade_alert_payload` reuses existing payload safety
with an explicitly supplied POST operation, aware clock, sleep and total attempt
bound. No client, authentication, destination or current clock is selected. It
requires complete-message confirmation, uses complete plain fallback after 400,
obeys explicit provider retry delays on 429 and rechecks expiry before each
attempt and after waiting. Server ambiguity, missing confirmation and transport
errors stay UNKNOWN without blind retry or raw exception text. Earlier sender
functions and last-chunk return values are unchanged; they cannot masquerade as
this structured complete-message receipt.

`deliver_candidate` requires matching candidate, fixed session and complete M4.5
assembly, including full confidence/context and component records. The injected
delivery boundary reuses `assemble_candidate` to recheck primary identity,
strategy/version, creation time, original PENDING status, required primary feature,
input references, full confidence calculation and component links. Its reconstructed
assembly must equal the supplied assembly because copied assemblies have no
constructor guard. Missing or mismatched facts fail before storage or send;
valid unlinked research components remain intact. The injected
store receives those immutable facts, optional option result, rendered text and
PENDING intent together; it must acknowledge atomic persistence before sending
and reject an unresolved repeated intent. A separate SEND_STARTED record precedes
the sink, and a canonical final DeliveryRecord remains linked to original facts.
Storage failure sends nothing. A failed final save retains its result in a typed
error for reconciliation; cancellation leaves the persisted start marker.
Actual durable storage/link resolution and crash recovery remain M5.1/M5.5.

Replay/shadow default to RecordingSink and reject DiscordSink even if saved
settings name discord. Recording uses REJECTED_BEFORE_SEND / RECORDING_ONLY and
no remote message reference. `offline_test` explicitly allows fake transport under
the protected launcher. No live mode, consumer or switch activation is added.
M4_6_VERIFICATION records actual execution status, the next independent M5.1
storage scope and the separately blocked M4.7 policy gate. Full AT-06/10 and
notification proof retain their existing M5.5/M9/M15/M17 owners.

## 71. M5.1 typed append-only research event store

`consensus_engine/event_store.py` implements `ResearchEventStore`, version
`M51_V1`. It persists supplied immutable canonical records append-only through
the host database transaction wrapper and a new additive
`trade_alerts_research_events_v1` table (update/delete triggers abort). Each row
carries a stable record_id, record type, typed kind, session, SHA-256
fingerprint, typed links and the serialized facts. Reusing a stored id with
different facts, a different kind, or a link to an already-stored record outside
its allowed role is rejected. Missing linked inputs stay unresolved and are never
turned into favourable facts.

`store_assembly` and `save_intent` write each bundle as one atomic transaction;
a failure on one row leaves no partial bundle. `save_intent` satisfies the
injected M4.6 delivery boundary and refuses a duplicate pending intent.
`save_result` appends the SEND_STARTED and final delivery records. Reopen preserves
every stored byte. This is append-only storage, not a strategy, option ranker,
outcome rule, live sender, dedup, or full M5.5 recovery. Reset the database path
and reopen to restore records during offline validation, exactly as for the M4.2
transition store.


M5_1_VERIFICATION section 7 records the repaired contract. INSERT-time checks
cover both already stored targets and earlier unresolved links, including
same-bundle writes. Identical facts retain their first recorded row; conflicting
session/configuration and exact option-contract links fail. Full supplied
assembly/confidence/context, history requests/conventions/revisions, delivery
text/options and receipt reasons/attempts are retained in versioned envelopes.
History and assembly retries are idempotent; repeated delivery intents are
refused. links() reports RESOLVED or UNAVAILABLE without inventing raw records.
All writes use the host transaction; no live database path is selected here.


M5_1_VERIFICATION section 10 repairs candidate primary FEATURELINK identity.
Within the write transaction, an AlertCandidate's primary FeatureSnapshot must
match its metadata instrument_id, instrument_type and session. Enforce this
whether the candidate or feature is inserted first, including inside one bundle.
Reject mismatches without partial writes. INPUTLINK reference-market ancestors
remain permitted; this does not impose an underlying identity on every ancestor.

## 72. M3.3 supplied-input relative-strength features

`consensus_engine/relative_strength_features.py` is the shared pure calculation
for the frozen relative-strength definitions. `RS15_SPY_CLOSE_V1` uses only the
first 15 completed regular-session one-minute bars and stays fixed after warm-up.
From-open features use supplied first and current eligible trades at one evaluation
for stock, SPY, QQQ and the caller-supplied sector ETF. Each reference remains
independent, so one missing reference cannot hide the others.

The module selects no sector mapping, source, clock, threshold or strategy action.
It requires positive trades, known compatible units, sessions and adjustment
bases, original availability, the three-second freshness rules and exact input
record links. Missing, provisional, revised, certified-no-trade, stale, future or
incompatible facts produce named unavailable values. No live consumer or switch
is added.

## 73. M0.2B offline shared-storage implementation

`consensus_engine/full_chain_storage.py` implements contract version
`M02B_STORAGE_V2`. It is an offline library with an explicit disabled default.
The existing collector exposes it through `compact_option_day_bounded`; the
collector configuration keeps `bounded_compaction_enabled: false`. The existing
daily collector path is unchanged and no cleanup is activated.

The compactor inventories retained and incomplete bytes itself and checks the
M0.2A reserve formula before each write. Its indexed scratch database is capped
at C bytes; rows are decoded and emitted in bounded streams, with memory/time
checks throughout. Scratch remains retained and counted; no deletion runs. It enforces
separate byte limits for chain, open interest, proof and publication metadata,
plus decoded-batch, peak-memory and wall-time limits. It reads source parts in
sorted path order, keeps the last duplicate key, creates an explicit empty open
interest file when data is missing, and writes a fixed proof that binds every
source and output hash. It publishes a complete immutable set through one
atomic pointer. Empty open interest leaves an unpublished missing-data result.
Readers resolve that pointer once and verify current source identities and all
set members. Source paths in proof are relative to the configured root.
Failures retain source parts, the prior pointer and prior set. An interrupted
unpublished directory can be rebuilt only from the same deterministic source
identity.

`plan_retention` is dry-run only. It reports eligible old minute parts,
temporary files and notification markers inside the configured root. It never
deletes a file. Minute parts qualify only after a complete published set with
nonmissing open interest, explicitly supplied complete-day status, the complete
current source inventory and seven days after verified publication. Temporary
siblings require valid recovery, matching member bytes and a full 24-hour wait.
Unknown scratch remains held. Legal holds on files and ancestors always win.
Primary and supporting records are not cleanup targets in this milestone.

Fresh repair proof is pending in `M0_2B_VERIFICATION.md`; prior passing proof was insufficient. Synthetic files can prove
only this offline contract. Actual saved-data capacity, cleanup activation,
source qualification and live use remain separate gates.

## 74. M0.2D offline shared request queue

`consensus_engine/request_queue.py` implements `M02D_REQUEST_QUEUE_V1` as a
SQLite-backed offline queue. It has no runtime registration or provider adapter
and is disabled by default. Dispatch accepts only a finite `RecordedProvider`;
an arbitrary function cannot cross that boundary.

The fixed engineering limits are 110 dispatches in a rolling 60-second window
and 256 queued requests. The four classes, in order, are interactive,
actionable, background and research. Their expiry/timeout seconds are 5/2,
10/5, 60/15 and 300/15. These are conservative offline load-test values. The
110 ceiling preserves the existing code's headroom setting; it is not a claim
about current provider entitlement.

One immediate SQLite write lock serializes queue admission, final expiry and
account-ceiling checks, and the dispatch record across processes that share the
same file. Equal-priority requests use enqueue time and request ID for stable
order. A higher-priority request displaces the newest lowest-priority queued
request when the queue is full. An equal or lower priority request is rejected.
Both results remain recorded. Expired work is recorded and never passed to the
recorded provider. Slow, throttled, authentication and other recorded failures
have explicit final states.

This milestone does not wire existing consumers, contact a provider, establish
current subscription limits or make the queue safe for live use. Protected
execution and independent review remain pending in `M0_2D_VERIFICATION.md`.

## 75. M0.2E provider-source boundaries

M0.2D's 110-dispatch rolling limit is a configurable local safety ceiling, not
a provider account limit. Code, comments, settings and operator-facing output
must not label it as Schwab's allowance. Before any runtime wiring, one shared
queue must cover interactive commands, actionable reads, background collection
and research collection, and account-specific official evidence must establish
the usable request and subscription limits.

A Schwab adapter must retain each original time field name and value, the raw
source time, local received time and the delay flag. Until an official source
defines a field's unit, conversion is an explicitly labeled interpretation and
cannot establish freshness or finality. `realtime=true` or `isDelayed=false`
does not replace a time-age check. Missing official units, entitlement or NBBO
meaning stays unavailable rather than being inferred from field names, HTTP
success or values that resemble epoch milliseconds.

Databento adapters and manifests must identify `XNYS.PILLAR` and `EQUS.MINI` as
different sources. `XNYS.PILLAR` is direct NYSE Integrated data. `EQUS.MINI` is
a derived component-venue aggregate with anonymized trade venue identity. Do not
combine overlapping OHLCV volumes, rewrite either publisher identity, or present
their union as a complete consolidated tape. A missing OHLCV row stays missing
unless separate source evidence certifies a no-trade interval. Provider message
times do not by themselves establish the historical record's original
availability, correction state or finality.

These are source-preservation rules for future work. M0.2E adds no provider
client, runtime consumer, timestamp conversion or live switch.

## 76. M0.2F offline retained-minute adapter

`consensus_engine/databento_minute_bars.py` accepts one already-decoded Databento
`ohlcv-1m` row and explicit caller context. It is not a file reader or provider
client. The caller supplies the immutable file fingerprint, raw symbol,
instrument ID, session, observed receipt/availability times and provider
condition. No clock time, identity, correction or finality fact is invented.

Raw DBN prices use the documented fixed `1e9` representation. Raw `publisher_id`
and `ts_event` remain recorded, with the latter kept as nanoseconds alongside the canonical timestamp.
The adapter rejects sub-microsecond event times because the common record cannot
preserve them exactly. It rejects wrong identities, non-minute event times,
incomplete rows and zero-price manufactured placeholders. The two supported
datasets keep different publisher and venue labels, and every returned bar has
`is_final=false` until separate source evidence establishes finality.
