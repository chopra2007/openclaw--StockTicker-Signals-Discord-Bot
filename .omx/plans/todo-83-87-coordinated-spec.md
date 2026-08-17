# Coordinated specification for TODO #83-#87

## Goal

Finish all five owner-visible upgrades without weakening existing alert meaning, stored-history truth,
Discord delivery safety, or the separate high-probability trade-measurement work already present in the
shared working tree.

## Shared rules

- Keep every existing user-visible fact unless a TODO explicitly changes it.
- Treat stored history as evidence, not as automatically correct output.
- Keep reading accuracy separate from later price performance.
- Show missing or uncertain evidence plainly.
- Use Pacific time for every owner-visible date and time.
- Do not read or expose secret values.
- Preserve the pending -> posted -> archived morning-brief delivery record and no-duplicate-post behavior.
- Keep VVIX/VIX leadership display-only. It must not alter a score, gate, or alert.
- Keep the Discord feature-answer model chain separate from alert, `!all`, and morning-brief models.
- Preserve unrelated existing edits in `config/consensus.yaml`, `consensus_engine/cross_reference.py`,
  `tests/test_i13_apewisdom_zscore.py`, and the untracked `None` path.

## #83 and #84 — analyst-group alert

### Required behavior

- Remove `SWARM` from the title and footer only. Keep internal names unchanged.
- Title: ticker, analyst count, and elapsed span.
- Show group bias as bullish, bearish, mixed, or unclear.
- Show a short, faithful reason for each analyst. Use `reason not stated` when the source does not state one.
- Keep analyst links, owner ping, price, and current delivery behavior.
- Remove the owner-visible non-Pacific clock range. Prefer elapsed time; use Pacific time if a clock is needed.
- Do not infer direction from card color.

### Data boundary

- Keep production detection in `consensus_engine/analysis/herding.py`.
- Match each group member to the stored post using ticker, analyst, and the exact group window.
- Use the direction already stored for the post. Missing or neutral values become `unclear`.
- Reuse the existing parsed summary when it is durably available. Otherwise use a safely clipped source excerpt.
- Do not add a new AI call while sending the alert.

### Proof

- Rebuild every recoverable group, including repeated join events.
- Compare old and new cards. Only requested wording and the new direction/reason details may differ.
- Independently review every contributing post without seeing the proposed label first.
- Require zero bullish/bearish reversals and zero unsupported reasons.
- Save one reproducible row per group member with source text, independent reading, proposed reading,
  agreement, first-tweet price anchor, exact-vs-daily price label, raw and benchmark-adjusted results,
  and 24-hour, 5-day, and 21-session outcomes where available.
- Show counts before rates. Do not show a rate for fewer than 10 resolved cases.
- Inspect an all-bullish render, a mixed render, a real Discord test card, and the next new real group.

## #85 — grounded Discord feature answers

### Required behavior

- Answer real feature questions by reading current code or stored data.
- Use plain English and answer every part of a multi-part question.
- Correct a false premise instead of agreeing with it.
- Never claim a code or setting change happened when it did not.
- Keep code-changing requests bounded; this work does not make the bot a self-deployer.

### Required signal-breadth answer

`Our own signal breadth` counts every qualifying bullish or bearish ticker seen in the bot's own
signals during the last five calendar days. It is not a fixed ticker list. Neutral, ApeWisdom, SEC,
and Form-4 rows do not count. There are no two ticker slots to add; a ticker enters automatically
when a qualifying signal arrives.

### Proof

- Recover every feature question and adjacent follow-up available in the selected latest 100 `#chat`
  messages.
- Add only missing required coverage: breadth, VVIX/VIX, expected move, alert scores, analyst groups,
  and a wrong-premise question.
- Before grading an answer, independently write the expected facts from current files or the database.
- Replay through the same mention/`!ask` path used by the owner.
- Grade factual claims, missed parts, invented files/settings, false change claims, plain language,
  completion time, and cost.
- Test a multi-turn follow-up.
- Use the current model as control, then test capable current models from the live catalog, strong
  models first. Pick the least expensive model that passes reliably.
- If the model chain changes, sync only the agent chain, restart the gateway, and prove the exact
  breadth example plus two other real questions in Discord.

## #86 — VVIX/VIX lead and streak

### Required behavior

- Put the conclusion before the raw levels.
- Up lead: both rise and VVIX rises more. Down lead: both fall and VVIX falls more in magnitude.
- Show the percentage-point difference and consecutive stored market-day count.
- Mixed directions, equal moves, zero prior values, stale data, and missing rows must not extend a streak.
- Weekends and market holidays must not break a valid streak between consecutive stored market dates.
- A VVIX-up/VIX-down case may be shown as a one-day divergence, never as a multi-day predictive streak.
- Keep the trailing-year percentile and descriptive-only warning.

### Proof

- Replay all stored `vol_of_vol_daily` rows in date order.
- Independently recalculate both daily changes, the lead, and streak for each row.
- Compare recoverable historical market cards with their stored rows.
- Separately measure the next 1- and 5-market-session VIX move after each three-day up lead.
- Report counts before rates and do not claim prediction from fewer than 10 resolved cases.
- Inspect the real current Discord render.

## #87 — morning brief card and expected-move charts

### Required behavior

- Build one compact main card with this stable order: Overnight, Levels to Watch, High-Conviction
  Calls, Macro, Top Tickers.
- Keep a material top story only when it does not bury those five sections.
- Do not silently cut off the end of a brief. Empty sections must say clearly that no usable item exists.
- Use a deterministic fallback when the AI output is missing or invalid.
- Reuse `compute_em`, `build_em_embed`, and `render_chart`; do not duplicate expected-move math.
- Daily SPY expected move is required when usable quotes exist.
- Weekly SPY expected move is best effort and must never delay or block the brief.
- Send the main card plus one or two PNG files without breaking size guards, mention blocking,
  retries, or the single delivery record.
- Archive readable brief text plus enough expected-move numbers or image details to understand the post.
- Produce the displayed date and time with `ZoneInfo("America/Los_Angeles")`.

### Proof

- Replay all 78 archived brief texts through the card builder. Confirm the five sections survive and
  no text is silently cut off.
- Compare every date whose inputs can still be reconstructed with stored source records.
- Independently check daily SPY chart numbers against all saved nearest-expiration SPY snapshots.
- Do not claim an old weekly replay because the old full weekly chains were not stored.
- Prove weekly with one current real chain used by `!emw`.
- Inspect the actual daily and weekly PNGs, the Discord test card in `#chat`, and the next scheduled brief.

## Completion gate

Each feature-sized change needs focused tests, all affected tests found by caller/text search, required
broader checks, real owner-visible proof, a local saved change, and honest TODO records. The final gate
also requires the Ultragoal cleanup pass, post-cleaner verification, architecture-invariant proof,
and independent code-reviewer plus architect approval.
