# OpenClaw High-Probability Trades Master Plan

Status: Approved master plan; Batch 1 is READY
Evidence source: `.omc/plans/openclaw-full-audit-2026-08.md`

## Goal

Make the bot reliably find the best available trade ideas, mainly options and secondarily shares, for holding periods from the same day to several weeks.

The owner wants:

- Win rate as the main score.
- Positive results after realistic trading costs as a required safety check.
- A daily digest of 3–5 ranked ideas.
- Permission for the bot to show fewer than three actionable trades, including zero, when evidence is weak.
- No personal ticker, direction, position-size, or strategy exclusions.
- No automated order placement.
- No more than **$10 per month of new spending beyond current costs**.

An idea and a recommended trade are different:

- The digest may show 3–5 ranked ideas for research.
- Only ideas that pass the proven threshold may be labeled actionable.
- The bot must never weaken its threshold merely to fill five slots.

## Three principles

1. **Measure before optimizing.** A better score is useless when trade direction, delivery status, exact contract, or result is missing.
2. **Prove results on later data.** Rules are frozen before evaluation. Historical gaps are never filled with guesses, and later information cannot leak into earlier scores.
3. **Prefer small reversible steps.** Each fresh session completes one batch, proves it works, records rollback instructions, and stops.

## Top three decision drivers

1. **Trustworthy trade outcomes.** Every recommendation must be traceable from source evidence through delivery and final result.
2. **Realistic options execution.** Exact contracts, executable quotes, spreads, and the owner’s real fees must be included.
3. **Evidence of useful ranking.** A new ranking must beat a simple comparison on untouched later data without relying on one ticker, source, week, or market condition.

## Current consensus

These conclusions follow from the audit evidence and the owner’s answers:

1. The current stored win-rate results are not trustworthy enough to guide score tuning. Trade direction is missing from important evaluation records. A successful short idea can therefore look like a loss. Also, 53 of 456 recent sent alerts were absent from the main evaluation records.
2. Current options profitability is unknown. The database does not preserve enough exact contract and price information to calculate realistic entries, exits, spreads, and fees.
3. The bot should not add more sources or a more complicated AI model yet. Better scoring cannot repair incomplete results.
4. Some scoring logic can create false confidence. Opposing analysts can count as agreement. A cached score can be reused for a different same-ticker situation. Related sources can be counted more than once.
5. The system already gathers enough information to begin a serious experiment after measurement is repaired.
6. The first target is not to prove the old bot was profitable. That cannot be recovered honestly from missing historical fields. The target is a clean future-only record that can prove or disprove the new ranking method.
7. High win rate alone is insufficient. A strategy can win often and still lose money if losses are much larger than wins. Owner-visible ranking may launch only when both win rate and after-cost results pass.

## Options considered

### Option A — Large rewrite

Replace the main controller, database flow, scorer, and alert output together.

Why rejected: it would mix measurement repair with behavior changes, make failures hard to isolate, and create a difficult rollback in central files.

### Option B — Staged measurement-first delivery

Repair the record of decisions and outcomes, add exact trade tracking, repair safety and speed, collect clean data, then test and release a ranking.

**Preferred.** It gives the fastest honest path to the owner’s goal while keeping each change testable and reversible.

### Option C — Start shadow ranking immediately

Build a new score from the current records and begin comparing it silently.

Why invalid today: missing direction, missing decision links, and incomplete options prices would contaminate the comparison. Shadow ranking becomes valid only after the measurement gate passes.

## Architecture decision record: ADR-001

### Title

Use a staged, versioned, future-only trade evidence chain.

### Status

Accepted for this plan. Implementation remains pending.

### Context

The audit found that current records do not reliably join source evidence, direction, scoring, delivery, exact options contracts, and later results. Optimizing the score now would optimize against incomplete labels.

### Decision

Create a stable chain of identifiers for candidate, decision, alert attempt, trade plan, delivery, quote, and outcome. Direction is part of that identity, not optional descriptive text. Write original facts as immutable append-only events. Corrections create a new event that refers to the prior event; they never overwrite the original fact. Derived summaries may be rebuilt from those events. Save every state, including rejection, attempted delivery, failure, and unresolved outcomes. Store exact options contracts and executable quotes. Version scoring, fee, and result rules. Use only point-in-time evidence. Promote a ranking only after it passes the defined gate on later untouched data.

### Consequences

- Old records remain useful for operations and limited diagnostics, but not as proof of options profitability.
- Clean proof takes at least the observation period and the required resolved sample.
- Database changes must be additive and compatible during rollout.
- Old and new records must run side by side through at least one full market cycle before readers switch.
- The system may produce fewer actionable trades than the owner’s desired daily idea count.
- Results become reproducible and honest enough to support later improvement.

### Rejected alternatives

- Guess missing historical direction or contracts.
- Tune the current score before fixing the records.
- Force a fixed number of actionable trades every day.
- Add more paid data or another AI model before proving the need.

## Batch ledger

Only one batch may be `READY`. A fresh implementation session executes only that batch and stops.

| Batch | Name | Status | Gate to complete |
|---|---|---|---|
| 1 | Measurement integrity | **READY** | Direction, lifecycle, linkage, atomic writes, cache isolation, disagreement handling, and tests pass |
| 2 | Exact options and share tracking | PENDING | Batch 1 complete; exact contract and fee results reproducible |
| 3 | Safety and scoring correctness | PENDING | Batches 1–2 complete; prices, delivery, privacy, and source independence verified |
| 4 | Speed and reliability | PENDING | Correctness stable; command timing and failure containment proven |
| 5 | Clean observation sample | PENDING | Collection integrity gate passes for at least 20 trading days and required sample grows |
| 6 | Ranking experiments | PENDING | Clean sample available; chronological development and untouched evaluation defined |
| 7 | Shadow daily ranking | PENDING | Proposed ranking passes internal checks and runs without changing owner-visible output |
| 8 | Controlled owner-visible release | PENDING | Actionable gate passes; probability wording waits for the separate calibration gate |

After a batch passes, its session marks it `COMPLETE` and may mark only the next batch `READY`. It must not execute the newly ready batch in the same session.

## Permanent measurement decisions

### Future-only proof

Never invent missing historical direction, contracts, quotes, delivery times, or outcomes. Fill an old field only when an existing structured value makes it unambiguous. Otherwise store `unknown`, show the count, and exclude it with a reason.

### Every decision stays in the denominator

Save every eligible decision, including sent, suppressed, rejected, timed out, failed during scoring, failed during Discord delivery, and unresolved. Reports show how many reached each step.

Alert lifecycle events must distinguish at least: attempt created, send started, confirmed delivered, rejected before send, timed out, and failed. An attempted alert never disappears merely because no confirmation arrived.

### Immutable source of truth

Original candidate, decision, delivery-attempt, quote, and outcome facts are append-only. Never repair an original row in place. A correction appends a new version with a reason, prior-event reference, creation time, and actor or process version. Reader projections may be rebuilt or replaced, but the original event history remains available for reconciliation.

### Exact direction

Every trade candidate and result includes `long` or `short`. Direction is included in candidate identity, duplicate detection, cache identity, trade identity, and result identity. Neutral research notes are allowed, but they are not trades. Opposing directions count as disagreement.

### Exact options contract

An options result identifies one actual contract and stores at least:

- Complete standard option contract symbol, underlying ticker, call or put, and buy or sell action. The symbol must come from structured contract data. Never reconstruct it from alert text.
- Strike, expiration date, and contract multiplier.
- Provider quote time, local receipt time, computed quote age, bid, ask, midpoint, spread in dollars and percent, underlying price, volume, and open interest when available.
- Market session and quote source at entry and at every exit observation.
- Alert delivery time and planned entry rule.
- Executable entry price, target, stop, and exit time.
- Bid and ask at exit and executable exit price.
- Number of contracts, contract multiplier, price-data source, missing-data reason, fee data and fee-rule version, result-rule version, and scorer version.

Use the ask as a conservative simulated purchase price and the bid as a conservative simulated sale price. Treat the spread as a trading cost separate from formal fees.

### Append-only evidence

The original candidate, direction, contract, score, quote, and delivery record are immutable. Later quotes, exits, outcomes, corrections, and new rule versions are separate linked records. Never overwrite the point-in-time evidence that produced an alert.

Before collection starts, freeze maximum quote age by market session. A crossed quote, stale quote, missing bid or ask, invalid negative price, or missing contract identity is unusable and remains counted with its reason. A zero bid at a required exit is not silently dropped. Apply the frozen conservative rule, such as a zero executable value when the contract is still valid, or mark `cannot close` when market state makes execution unknowable. Keep those groups separate in reports.

### Correct fees

The owner pays **$0.45 per contract per transaction**. Store this as versioned fee data rather than a number hidden in calculation code.

For one contract:

- Buy fee: $0.45.
- Sell fee: $0.45.
- Normal round-trip contract fee: $0.90.

Add only actual regulatory or exchange fees confirmed by the owner or broker. Store those separately from the contract fee. Do not assume a generic extra closing fee. Store fee values as versioned data, support multiple contracts and the contract multiplier, and make every result reproducible without a hard-coded historical assumption.

The calculation must apply the contract multiplier explicitly:

`gross dollars = (exit option price - entry option price) × contract multiplier × contract count`

`net dollars = gross dollars - per-transaction contract fees - confirmed separate regulatory or exchange fees`

For a normal one-contract round trip with no confirmed extra charge, contract fees total $0.90. Actual regulatory or exchange fees are stored as separate named values so they can be audited and changed without rewriting price history.

### Fixed test rules

Before scored collection begins, freeze one primary horizon, entry, stop, target, and exit rule for every recommendation. Same-day, five-trading-day, and twenty-trading-day secondary observations never count as three independent wins. A win is a positive net result after spread and all confirmed costs under the primary rule. Also freeze overnight gaps, stop-and-target in the same bar, duplicates, contradictions, missing or zero bids, stale or crossed quotes, expiration, early-assignment risk, adjusted contracts, splits and other corporate actions, trading halts, contracts that cannot be closed, and share spread and slippage rules. A change creates a new version and never silently rewrites old results.

### Point-in-time evidence

A score may use only information available before it was created. Later outcomes, revisions, and future source accuracy cannot enter an earlier score.

### Silent proof before promotion

New rankings run invisibly first. They cannot replace owner-visible ranking until they pass the promotion gate.

### Spending control

Start with existing sources and free collection. Track every proposed recurring cost. Total new recurring cost stays at or below **$10 per month beyond current spending**. No paid service starts without authority for that external charge.

## Audit evidence anchors

Fresh sessions must use the audit report for exact findings and then verify current code before editing. Known anchor files are:

- `.omc/plans/openclaw-full-audit-2026-08.md` — findings, evidence labels, unknowns, and original ranked recommendations.
- `consensus_engine/analysis/llm_scorer.py` — AI scoring and direction handling reviewed by the audit.
- `consensus_engine/alerts/all_command/aggregator.py` — `!all`, evidence gathering, time-budget, and duplicate-work findings.
- `consensus_engine/db.py` — decision, alert, outcome, cache, cleanup, and database performance paths.
- `config/consensus.yaml` — current feature settings, database path, cache timing, options settings, and public-safety finding. Never copy identifier values into plans or reports.
- `.test-baseline` — the existing known failing-test list.
- `docs/agents/PROJECT_RULES.md` — current definition of done, checks, ownership, and production rules.
- `docs/agents/MEMORY_GUIDE.md` — rules for private project memory.

File locations and line numbers may drift. The implementation session must confirm current symbols before changing them. Do not broaden edits merely because a large central file is open.

## Batch 1 — Repair measurement integrity

### Work

Create additive, versioned database tables or columns for stable candidate, decision, alert, and outcome IDs; direction; lifecycle status and reason; scorer and rule versions; input fingerprint; creation time; delivery attempt and confirmed delivery times; and outcome error or missing-data reason. Original point-in-time records are append-only.

Create the new storage before changing live readers. Dual-write the old and new paths for at least one full market cycle, compare counts and safe field coverage, then switch readers. Rollback disables the new reader while preserving every new record.

Then:

- Save a decision before expensive scoring or delivery begins.
- Update it through every later state.
- Save related decision, alert, and initial result records together so only all or none are written.
- Preserve failures and suppressed decisions.
- Fix the score cache key so it includes ticker, direction, analyst or source, catalyst, base score, rule version, and an appropriate time bucket.
- Treat opposing analysts as disagreement.
- Keep analyst identity and direction attached to later grading.
- Ensure the score shown to the owner matches the score stored for evaluation.

### Acceptance criteria

For all records after cutover:

- 100% of trade candidates have a direction.
- 100% have a current or terminal status.
- 100% of sent alerts have a linked decision.
- Delivery failures and timeouts remain visible.
- Different same-ticker directions cannot share a cached final score.
- Opposing directions do not increase agreement.
- A forced write failure leaves no half-written related records.
- Old and new write counts reconcile for one full market cycle before any reader switch.
- No original direction, contract, quote, score, or delivery time can be overwritten.

### Rollback

Use additive columns or tables. Keep old readers working during transition. Put new writes behind one feature setting. On trouble, disable the new writer and return to the prior reader. Do not delete old records or perform a destructive historical rewrite.

### Execution entry — implementation complete, gate waiting

- Recorded in Pacific time: 2026-08-12 12:00 AM PDT.
- Batch state: implementation complete; measurement gate **WAITING**. Batch 1 remains READY. Every later batch remains PENDING.
- Production files: `consensus_engine/measurement.py`, `consensus_engine/db.py`, `consensus_engine/main.py`, `consensus_engine/cross_reference.py`, `consensus_engine/alerts/discord.py`, `consensus_engine/alerts/all_command/aggregator.py`, and `config/consensus.yaml`.
- Operational proof: `scripts/check_batch1_measurement_gate.py` opens SQLite in read-only mode, reports aggregate JSON only, and exits successfully only when the full Batch 1 clean-data gate passes.
- Database migration: schema version 32 applied at 2026-08-12 12:00:03 AM Pacific. All six append-only tables are present: `measurement_candidates_v1`, `measurement_decision_events_v1`, `measurement_alert_events_v1`, `measurement_delivery_events_v1`, `measurement_outcome_events_v1`, and `measurement_corrections_v1`. Their no-update and no-delete protections are present. Corrections are linked new events.
- Settings: `measurement.batch1.collect_enabled: true`; `measurement.batch1.reader_enabled: false`; rule version `batch1-v1`; scorer version `consensus-v1`; score-cache bucket 300 seconds. Old readers remain authoritative.
- Verification: fresh full suite passed with 3179 passed, 1 skipped, and 20 warnings in 425.04 seconds. `.test-baseline` is empty, and its former test now passes. Saved change: `52c0927`.
- Live state: engine restarted at 2026-08-12 12:00:00 AM Pacific. Services are active, and the workspace symlink resolves correctly.
- Rollback setting: set `measurement.batch1.collect_enabled: false`. Leave `measurement.batch1.reader_enabled: false`. Preserve all collected rows.
- Clean-data cutover: `2026-08-12T00:00:00-07:00`.
- Future gate command: `python3 scripts/check_batch1_measurement_gate.py --since 2026-08-12T00:00:00-07:00`.
- Current live read-only result: WAIT with 0 completed regular market sessions, 0 candidates, and 0 confirmed deliveries.
- Scheduled follow-up: task `1786518088_84cd1d` will run the checker and resume this durable goal at 2026-08-12 1:20 PM Pacific.
- Independent review: **APPROVE**, with no blockers. Batch 1 remains READY and waiting for the live gate; do not mark it complete or start Batch 2 until the checker prints PASS.

## Batch 2 — Add exact options and share tracking

### Work

For every eligible options idea, select one exact contract with a versioned rule. A pre-send quote is selection evidence only. Save confirmed delivery time, then use the first usable quote received at or after confirmed delivery as the simulated entry. Freeze a maximum delivery-to-entry delay before collection. Record selection-to-delivery and delivery-to-entry delays. Capture later quotes required by the frozen exits, calculate ask-to-enter and bid-to-exit results, and preserve missing quotes or zero bids as explicit states.

The first promoted options cohort is buy-to-open calls and puts only. Store other option strategies as research-only until separate entry, exit, margin, assignment, and risk rules are frozen and proved. This is staged proof, not a permanent trade-type exclusion.

Start with existing sources. Before paying for new quotes, prove current sources cannot provide the required timestamps and contract history.

For shares, store direction, entry time and price rule, exit price, spread, versioned commission and slippage, stop and target path, and halt or missing-data status. Define planned risk as the frozen entry-to-stop loss plus spread and fees, using quantity and multiplier. Report equal-weighted results per recommendation and dollars per  planned risk. Short-share ideas also require point-in-time borrow availability, borrow cost, dividends, and corporate actions; otherwise they remain research-only.

### Acceptance criteria

- An options result cannot exist without an exact contract.
- Entry and exit quotes include timestamps.
- One normal one-contract round trip uses $0.90 in contract fees.
- Any additional fee is named and based on a confirmed charge.
- Spread is reported separately.
- Missing quotes remain counted.
- Unusable liquidity is marked ineligible before a performance claim.
- One stored result can be reproduced from its fields alone.
- Stale, crossed, missing-side, and zero-bid exit quotes are unusable and remain visible by reason.
- Contract adjustments, expiry, early-assignment risk, halts, gaps, and positions that cannot be closed have explicit versioned outcomes.

### Rollback

Collect into new versioned tables first. Keep visible alerts unchanged until collection is stable. Disable quote collection independently if it harms normal operation. Preserve collected records.

## Batch 3 — Repair safety and scoring correctness

### Work

- Reject AI-written prices or trade levels that cannot be traced to structured market data.
- Mark Discord delivery successful only after confirmation and preserve delivery failure.
- Remove owner or Discord identifiers from public settings and use the approved private settings path.
- Keep secrets and private text out of process arguments, logs, and errors.
- Prevent related social posts from counting as independent confirmation.
- Separate evidence by direction in YouTube and other summaries.
- Add visible source contribution details to every score.

### Acceptance criteria

- Every visible price traces to stored market data.
- Failed delivery cannot be marked delivered.
- Public repository settings contain no private identifiers.
- One underlying event cannot masquerade as several independent confirmations.
- Stored source contributions add up to the final score.

### Rollback

Use separate settings for strict price validation, source grouping, and delivery tracking. Do not roll back privacy repair unless its replacement is equally safe.

## Batch 4 — Improve speed and reliability

### Work

- Build one shared evidence bundle per command so sources and AI work are not fetched twice.
- Enforce the full `!all` budget from command start.
- Return a clear partial result when one source is slow.
- Display data age.
- Match database cache life to the promised cache life.
- Prevent one failed source from cancelling other successful sections.
- Move slow database work away from the live command path where safe.
- Replace row-by-row outcome fetches with bounded batches and the shared provider guard.
- Make startup cleanup bounded and indexed.
- Add an index only after the exact slow query is confirmed.

### Acceptance criteria

- A source is fetched no more than once per `!all` run unless a documented retry occurs.
- `!all` returns within its configured full time limit.
- Partial results name unavailable sections.
- Cached results show age.
- One failed source does not erase successful sections.
- Outcome collection respects the shared provider-call cap.
- Startup has no unbounded full-table cleanup.

### Rollback

Make the shared bundle and timeout controller independently disableable. Preserve the correct older path until the replacement passes.

## Batch 5 — Collect a clean observation sample

Do not tune ranking while this sample grows.

Continue until at least 20 trading days have passed and at least 100 independent resolved recommendations exist for the method being evaluated. Longer horizons remain unresolved until they finish naturally.

Produce a daily integrity report with eligible, rejected, scored, sent, delivery-failed, resolved, unresolved, missing-direction, missing-contract, missing-quote, missing-link, source-failure, and new-cost counts. Also report usable-quote rate; stale, crossed, and zero-bid rates; quote age by market session; selection-to-delivery and delivery-to-entry delay; missing exits; provider gaps; old/new dual-write count differences; projection rebuild differences; and outcome completion by primary horizon.

Do not move on unless post-cutover records show at least 99% of attempted alerts with a final status, at least 99% of delivered alerts linked to a complete trade record, zero reconstructed direction, contract, delivery time, or original quote, no silent delivery failures, exactly reproducible entry and exit calculations, reproducible fees, and visible unresolved or excluded records. The promoted evaluation uses only records created after the rules were frozen. Any unexplained gap blocks promotion and is investigated; the clean cohort used for the final claim must have complete required direction and linkage. If the gate fails, fix collection and restart the affected clean window.

## Batch 6 — Build and test ranking methods

Start with the simplest explainable ranking. Evaluate direction-specific source history, independent agreement, disagreement penalty, catalyst timing, freshness, market conditions, liquidity, spread, open interest, expiration distance, expected move, technical confirmation, side-aware options flow, and duplicate-event penalties.

Do not keep a factor unless a point-in-time test shows it helps later data.

Compare against the current score where valid, a simple source-plus-direction rule, a simple liquidity-qualified rule, no trade for profit comparison, and an appropriate broad-market directional move.

Use chronological development data. Reserve the latest 30% as untouched evaluation data. Choose rules on development data only and inspect the reserved data once. If a rule changes after inspection, require a new future evaluation period.

Report win rate, confidence range, count, unresolved count, average win, average loss, after-cost net dollars, result per $100 planned risk, losing streak, measured drawdown, horizon, direction, instrument, and market-condition groups.

## Actionable strategy promotion gate

Pre-register one candidate ranking version, its one primary result, and its frozen comparison before opening evaluation data. An owner-visible actionable strategy requires all of the following on untouched later data:

- At least **100 total independent resolved recommendations**.
- At least **30 independent resolved recommendations in every displayed cohort**. A cohort is any separate group for which the bot displays a win rate or probability, such as options, shares, long, short, or a named horizon.
- Observed **after-cost win rate of at least 60%**.
- The lower end of the 95% confidence range is above 50%.
- Positive average net result after spread and confirmed fees.
- Positive average result per unit of planned risk.
- Better results than the frozen simple comparison rule, with the lower end of the 95% range for the paired improvement above zero.
- No single ticker, source, week, or market condition explains most of the gain.
- All measurement-integrity checks remain clean.

Every separately promoted instrument, direction, setup, or primary-horizon group must pass its own gate. A group below the sample requirement remains research-only. Any rule change after evaluation starts requires a new future evaluation period. If the method fails any gate, continue silently or reject it. Do not relax the gate to claim success.

### Numeric probability and high-probability label gate

Actionable does not automatically mean calibrated probability. Display rank and evidence first. A numeric probability or the words high probability require untouched later data to show all of the following:

- Score bands are calibrated: a claimed 70% group wins near 70% within its stated uncertainty.
- Probability error is better than the base-rate forecast.
- Higher-ranked eligible ideas outperform lower-ranked eligible ideas.
- The cohort also passes the actionable strategy gate.

Until then, the bot may say actionable, but it must not display a numeric probability or high-probability claim.

## Batch 7 — Shadow daily ranking

Generate a silent daily list at the future digest time. Store rank, direction, research-only or actionable label, score and version, supporting and opposing reasons, liquidity, horizon, exact contract when applicable, and rejection reason.

The shadow system may produce zero actionable trades. It records top research ideas without changing visible alerts. Disable the shadow scheduler for rollback.

## Batch 8 — Controlled owner-visible release

Show one concise daily digest with up to five ideas. Each item states research-only or actionable, ticker and direction, contract or share plan, expected holding period, entry rule, stop and target, main support, main disagreement or risk, data age, spread/liquidity warning, and score/rule version.

Before release, record the exact setting that disables each stage. Roll out in three steps: silent ranking, owner-only informational ranking that does not replace existing alerts, then a limited actionable release after every promotion gate passes. Each step preserves collected evidence.

Automatically disable actionable output if direction or required record linkage falls below 100%, a visible delivery lacks its saved record, quotes exceed the frozen age, outcome calculations stop reproducing, or privacy checks fail. Return to silent mode if rolling after-cost results become negative or the frozen paired comparison advantage disappears. Continue safe collection after rollback. Verify that visible deliveries match saved delivery records. Review again after 20 additional trading days. Never automate trading.

## Test strategy

### Unit tests

- Long and short outcome calculations.
- Required direction and lifecycle states.
- Complete cache-key separation by direction, source, analyst, catalyst, base score, time bucket, and version.
- Opposing directions reduce rather than increase agreement.
- One-contract and multiple-contract fees at $0.45 per contract per transaction.
- Ask entry, bid exit, spread, missing bid, zero bid, expired contract, and missing quote.
- Same-day, five-day, twenty-day, target-first, stop-first, gap, and same-bar rules.
- Duplicate and contradictory candidate rules.
- Score contribution totals.
- Duplicate-event idempotency and out-of-order lifecycle events.
- Append-only correction supersession and projection rebuild from events.
- Fee and rule version changes without rewriting older results.
- Confidence range and cohort minimum calculations.

### Integration tests

- Candidate-to-decision-to-alert-to-delivery-to-outcome linkage.
- All-or-none database write when a forced failure occurs.
- Process failure between lifecycle stages and safe retry.
- Retry after uncertain delivery without inventing success.
- Dual-write mismatch detection.
- Old-reader rollback while new writes continue.
- Projection rebuild matches the active read model.
- Additive migration against a copy of the current database shape.
- Scoring timeout, suppression, failure, and delivery failure remain stored.
- Exact contract quote collection and later exit collection.
- Stored trade result reproduces from stored fields.
- Public settings load private identifiers from the approved private location.
- Shared evidence prevents repeated provider work.
- Provider guard caps outcome collection.

### End-to-end tests

- One safe synthetic long share path.
- One safe synthetic short share path.
- One safe synthetic call path.
- One safe synthetic put path.
- One rejected wide-spread option.
- One command with a failed source returns a named partial result.
- One failed Discord delivery remains failed in the database.
- One daily shadow run creates ranked research ideas without owner-visible delivery.
- One rollback setting restores the prior visible behavior.

End-to-end tests must not send real Discord messages, place orders, or call paid providers unless the batch has explicit safe authorization and an approved test target.

### Observability checks

- Daily reconciliation of candidates, decisions, sent alerts, deliveries, and outcomes.
- Missing direction, contract, quote, delivery, and linked-record counts.
- Source failure and timeout counts.
- Per-stage timing and complete-command timing.
- Duplicate provider-fetch counts.
- Database lock, write-failure, and partial-state counts.
- Current scorer, rule, and fee versions.
- New recurring monthly cost.
- Ranking sample size, cohort size, confidence range, concentration, and unresolved count.

### Standard verification order

1. Run the smallest test that proves the changed behavior.
2. Run the affected file or feature test group.
3. Run type, format, lint, and static checks required by current project rules.
4. Compare the broader test result with `.test-baseline`.
5. Run the independent verifier path.
6. Perform only the approved narrow live health check.
7. Record exact evidence in this plan before changing batch status.

## Experiment queue

Run one change at a time where possible:

1. Direction-correct source history.
2. Independent agreement versus disagreement.
3. Exact-contract liquidity and spread filters.
4. Catalyst timing.
5. Market-condition handling.
6. Side-aware unusual options flow.
7. Evidence freshness.
8. Technical confirmation.
9. Expiration and strike rules.
10. Source-removal tests to identify noise.

Every experiment records hypothesis, dates, version, development sample, untouched evaluation sample, comparison, result, keep/reject/more-data decision, and new monthly cost.

## Do not pursue yet

- Another general AI model.
- More social-media sources.
- Automatic trading.
- Complex machine learning before a clean sample exists.
- Historical results reconstructed from guesses.
- Repeated threshold changes on the same evaluation period.
- A forced five-trade quota.
- A new paid provider without a demonstrated data gap.
- A large rewrite of the central controller.
- Public probabilities without exact direction and trading costs.

## Fresh-session execution protocol

A fresh session executes **only the one batch marked `READY`**.

It must:

1. Read `AGENTS.md` and current project rules.
2. Start at the private project-memory router named in AGENTS.md and follow only one or two relevant links.
3. Read this master plan and the relevant audit findings.
4. Inspect current code because it may have changed.
5. State the active batch’s finish conditions and smallest safe rollback.
6. Use one owner for every shared central file.
7. Implement only the READY batch.
8. Run the required unit, integration, end-to-end, observability, and standard checks in proportion to that batch.
9. Obtain a separate verifier or reviewer decision.
10. Update the ledger, evidence, rollback notes, and reviewer changelog.
11. Mark the current batch `COMPLETE` only when its gate is proved.
12. Mark the next batch `READY` only after the current gate passes.
13. Stop. Do not execute the next batch in the same session.

If current evidence contradicts this plan, record the conflict and repair the plan before implementation. Do not silently choose a materially different design.

## Agent roster and ownership

- **Leader:** owns the batch, plan state, shared-file ownership, integration, stop decisions, and final evidence.
- **Explore agent:** maps exact current symbols and call paths. Read-only. It reports facts about the repository and does not propose broad redesign.
- **Executor:** owns a bounded implementation area assigned by the leader. It must not edit a shared central file owned by another agent.
- **Test engineer:** writes or reviews hostile tests for the batch’s failure modes.
- **Verifier:** independently checks acceptance criteria, test evidence, privacy, rollback, and whether the batch may be marked complete.
- **Code reviewer:** used when a batch changes several central paths or security-sensitive behavior.

Prefer at most three helpers plus the leader. Every helper is told that other agents share the workspace and must not revert their changes.

## OMX workflow and staffing hints

### Primary durable path: Ultragoal

Use `$ultragoal` to hold the durable batch state when the OMX goal runtime is available. Launch it with a plain instruction equivalent to:

`Read the master plan, execute only its one READY batch, prove its gate, update the ledger, and stop.`

Ultragoal owns persistence and the batch stop condition. It does not authorize work from later pending batches.

### Parallel implementation path: Team

Use `$team` only after the READY batch scope and file ownership are clear. Suitable lanes are:

1. Read-only current-path mapping.
2. One bounded implementation owner.
3. Test design and hostile cases.
4. Independent verification after integration.

Do not give two workers the same central file. The leader integrates and owns final checks.

### Team verification path

The required path is:

1. Explorer reports current code map and drift from audit.
2. Leader freezes the batch file list and acceptance criteria.
3. Executor makes the bounded changes.
4. Test engineer runs the hostile test set and reports exact failures.
5. Executor repairs only failures within the batch.
6. Verifier independently checks the gate, standard test result, privacy, rollback, and plan evidence.
7. Leader marks the batch complete or leaves it active/blocked. A worker may not self-approve completion.

### Performance Goal

Use `$performance-goal` **only for Batch 4**, after correctness and measurement are stable. Its target must be the measured `!all` and data-path limits in Batch 4. Do not use speed work to alter trade scoring or omit slow evidence silently.

### Ralph fallback

Use `$ralph` only as an explicit fallback when durable Ultragoal or coordinated Team execution is unavailable and one agent can safely own the entire READY batch. Ralph still follows the one-batch limit, independent verification requirement, and ledger stop condition.

If the current Codex App session cannot run OMX terminal workflows directly, use native Codex agents with the same roster and verification path rather than launching a hidden or unsupported runtime.

## Batch handoff requirements

Record after every batch:

- Batch status.
- Files changed.
- Database changes.
- Feature settings added.
- Tests run and exact results.
- Existing known failures.
- New failures.
- Approved live health checks.
- Performance before and after where relevant.
- Privacy checks.
- Remaining risks.
- Exact rollback.
- Clean-data cutover time when applicable.
- Recommended next batch.

Follow current repository rules for saving changes and any service action. Never restart a service, push externally, buy a subscription, or change credentials merely because it appears in this plan.

## Pre-mortem

Assume the effort failed. The likely reasons are:

1. **Failed and suppressed alerts still vanish.** Warning: counts do not reconcile. Prevention: save decisions first, require lifecycle states, and run daily reconciliation.
2. **Future information leaks into scores.** Warning: unusually strong tests collapse later. Prevention: point-in-time joins, chronological evaluation, versions, and one-look untouched data.
3. **Options results assume impossible fills.** Warning: profits concentrate in wide-spread or zero-bid contracts. Prevention: ask entry, bid exit, timestamps, liquidity rules, and visible missing data.
4. **Win rate rises while money is lost.** Warning: frequent small wins and rare large losses. Prevention: require positive after-cost dollars and result per planned risk.
5. **Weak trades are forced to fill the digest.** Warning: bottom ranks perform far worse. Prevention: separate research ideas from actionable trades and allow zero actions.
6. **One month or market condition is overfit.** Warning: most gain comes from one week, ticker, source, or condition. Prevention: chronological tests, concentration checks, and future confirmation.
7. **Database work slows the bot.** Warning: delays, locks, or incomplete states rise. Prevention: additive records, small transactions, measured indexes, bounded work, and rollback settings.
8. **New spending exceeds the limit.** Warning: several small tools lack one total. Prevention: one cost ledger and a hard +$10 monthly ceiling.
9. **Private information reaches public files or logs.** Warning: identifier or secret-shaped strings appear in scans. Prevention: private settings, safe logging, argument checks, and a public-safety scan each batch.
10. **A large rewrite causes unrelated failures.** Warning: one batch touches unrelated commands and collectors. Prevention: one bounded batch, one owner for central files, additive changes, and independent review.

## Reviewer changelog

Append one entry per review. Do not erase earlier entries.

### Review entry template

- Date and time in Pacific time:
- Reviewer role or agent:
- Plan or batch reviewed:
- Evidence inspected:
- Blocking findings:
- Non-blocking findings:
- Required changes made:
- Verification result:
- Decision: APPROVE / REVISE / BLOCK

### Entries

- Date and time in Pacific time: 2026-08-11
- Reviewer role or agent: Architect
- Plan or batch reviewed: Master plan draft
- Evidence inspected: Audit-backed plan and architecture boundaries
- Blocking findings: Append-only evidence, dual-write cutover, complete contract identity, quote usability, fee data, and staged release needed strengthening
- Non-blocking findings: Stronger proof delays visible ranking and may yield fewer ideas
- Required changes made: Added immutable point-in-time records, one-cycle reconciliation, reader rollback, full quote metadata and edge cases, stored fee values, hard integrity gates, and staged visible release
- Verification result: Changes applied; Architect re-review APPROVE; Critic APPROVE
- Decision: REVISE

- Date and time in Pacific time: 2026-08-11
- Reviewer role or agent: Critic
- Plan or batch reviewed: Revised master plan
- Evidence inspected: Principles, alternatives, database lifecycle, option execution, proof gates, tests, rollout, rollback, and fresh-session protocol
- Blocking findings: Pre-delivery entry, undefined initial option strategy, multiple horizon counting, probability wording, paired comparison, risk rules, failure tests, rollout stops, daily execution checks, and file manifest
- Non-blocking findings: Strong proof may delay visible ranking
- Required changes made: Entry moved after confirmed delivery; buy-to-open calls and puts are the first cohort; one primary result per recommendation; actionable and calibrated probability gates separated; paired comparison and risk rules strengthened; failure tests, stop rules, daily checks, and pre-edit manifest added
- Verification result: Architect APPROVE; Critic APPROVE
- Decision: APPROVE
