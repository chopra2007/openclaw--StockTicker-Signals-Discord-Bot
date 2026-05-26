# Cross-ref scorer's `breakdown.direction` is None on manual `!all`

**Status:** OPEN.

**Layperson:** When a user runs `!all <TICKER>` manually, the cross-reference scorer's `breakdown.direction` field is None because no alerting workflow ran. The aggregator falls back to the literal string `"neutral"` and passes it downstream as the direction signal. This broke catalyst mining in production all session (Commit 15 fixed catalysts; other features may still be silently affected).

**Where:** `consensus_engine/alerts/all_command/aggregator.py:505-508`:
```python
direction_str = (
    getattr(getattr(score_result, "breakdown", None), "direction", None)
    or "neutral"
)
```

Then `direction_str` is passed to `gap_fill.run_gap_fill(direction=...)`. Before Commit 15, gap_fill skipped catalyst queries entirely when direction was "neutral" — meaning catalysts were NEVER mined for manual `!all` calls, only for cross-ref-scorer-triggered runs.

**Other consumers to audit:** anywhere `direction == "neutral"` gates behavior. Grep for `direction.*neutral` and `direction != "neutral"` across the codebase. Each hit needs to be reviewed for whether "manual !all" should be treated as "neutral" or as "use the StructuredFields direction computed later".

## Fix options

1. **Pass StructuredFields direction (computed via `structured_fields.compute_direction(score_breakdown)`)** instead of `score_result.breakdown.direction`. StructuredFields direction IS populated for manual `!all` calls — it's what the embed shows.
2. **Compute direction earlier** in the aggregator pipeline so the value is available before `gap_fill` fires.
3. **Add an `is_manual_invocation` flag** so downstream consumers can branch on that instead of mis-relying on a "neutral" direction.

**Discovered:** Commit 15 root-cause investigation (gemini-quality-all-command discover run 2026-05-19). Verified by patching `gap_fill.run_gap_fill` to log incoming `direction` — saw `direction='neutral' anchors_count=0` for an AMD invocation that the embed correctly rendered as BULLISH.

**Severity:** medium. Catalyst-mining was the most visible victim (it's now fixed by ungating in gap_fill, but the symptom keeps recurring as new features get gated on direction).
