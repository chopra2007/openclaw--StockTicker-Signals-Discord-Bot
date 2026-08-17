# Make VVIX leadership and streaks obvious

**Status:** DONE 2026-08-17
**Created:** 2026-08-17

**CURRENT STATUS (2026-08-17):** DONE and live. `compute_vvix_lead_streak()` in
`consensus_engine/alerts/commands.py` computes each day's VVIX and VIX percentage change, the
percentage-POINT lead between them, and the consecutive same-direction streak; the `!market`
fear-of-fear card now shows that comparison ABOVE the raw levels. The trailing-year percentile line
and the descriptive-only warning are unchanged, and nothing new feeds a score or fires an alert.

Proof: replayed against all 23 stored `vol_of_vol_daily` rows — 22 dates, 0 mismatches against an
independent recomputation from the raw closes (`.omx/evidence/todo-86/replay-verification.md`); and
read back off a REAL Discord `!market` card after restarting the engine, which rendered
`No same-direction VVIX lead today` — correct for 2026-08-14, where both indexes fell but VVIX fell
LESS, so it is not a downward lead.

Wording decision honoured: the card states the streak as a plain fact with no foreshadowing
language. The reason is in the data — across the 23 real market days there are ZERO three-day upward
lead streaks and ZERO two-day downward ones; the longest streak of any kind is one day, and only 5
of 22 days show a lead at all. The predictive question the owner asked is therefore not answered
negatively, it is *unanswerable* with the history that exists. Forward VIX after each single-day
lead is recorded as raw counts only (1 up-lead day, 4 down-lead days) — far below the 10 resolved
cases needed to claim any rate.

An adversarial independent review (`.omx/evidence/todo-86/independent-verification.md`) found and
fixed one real bug: two moves of the same percentage computed off different price scales (VVIX ~90
vs VIX ~14) differ by ~1e-15 in binary, so a bare `>` scored a tie as a lead and would have rendered
"leading higher by 0.0 pts". Fixed with a 1e-9 tolerance shared by both the today-check and the
streak walk. The existing tie test had passed for the wrong reason (same-scale numbers compute to
exactly 0.0) and was rebuilt to use realistic differing scales.

Remaining open choice, deliberately NOT decided here: whether a VVIX-up / VIX-down divergence should
get its own icon. It has not been needed yet — no such day has appeared in the stored history.

## What the user wants

The `Fear of fear (VVIX vs VIX)` section should make these facts obvious at a glance:

- How much stronger or weaker VVIX is than VIX today, in percentage terms.
- Whether VVIX has been leading VIX higher or lower for more than one market day in a row.
- A three-day upward lead should stand out because it may foreshadow higher volatility.

## What worked so far

- TODO #81 is done. The live card now shows, for example,
  `VVIX 87.5 (-2.2% today) vs VIX 14.2 (-2.6% today)`.
- `vol_of_vol_daily` already holds one VVIX and VIX close per market date. No new outside data source
  is needed.
- The feature is correctly display-only. Past research did not prove tradeable edge, so this must not
  change a score or fire an alert.

## What does not work and why

The owner must subtract the two daily changes mentally. The card also fetches only the newest and
previous stored rows, so it cannot say whether a lead has persisted for two, three, or more market
days.

## Exact display meaning

Use percentage-point difference, not a confusing “percent of a percent.” Examples:

- `VVIX leading higher by 2.0 pts today · ↑ 3 market days`
- `VVIX leading lower by 1.4 pts today · ↓ 2 market days`
- `No same-direction VVIX lead today`

For an upward lead on a market day, both indexes must rise and VVIX's daily percentage gain must be
larger. For a downward lead, both must fall and VVIX's loss must be larger in magnitude. Mixed
directions do not extend either streak. If testing shows a clearer plain-English treatment for a
VVIX-up / VIX-down divergence, show it as a separate one-day divergence, not as a multi-day lead.

Count consecutive stored market dates. Weekends and market holidays must not break a streak. A stale
or missing data gap should stop the streak rather than guess.

## Next steps, in order

1. Read enough recent rows from `vol_of_vol_daily` to compute each day's VVIX and VIX percentage
   change and the current consecutive lead streak.
2. Put the comparison before the raw levels so the conclusion is visible first. Use a clear arrow or
   colored marker, but keep the actual percentages in the same field.
3. Keep the existing trailing-year percentile and descriptive-only warning.
4. Add tests for a 3-day upward lead, a 2-day downward lead, mixed directions, equal moves, a weekend,
   missing rows, zero prior values, and stale data.
5. Render real current data and inspect the actual Discord card before marking this done.

## Historical verification required before DONE

- Replay the calculation over every row in `vol_of_vol_daily`. For each date, independently recompute
  both daily changes, the percentage-point lead, and the streak length from raw values.
- Compare any recoverable historical `!market` cards in `#chat` to the matching database row. A stale
  date, wrong sign, broken weekend streak, or disagreement between card and data is a failure.
- Because the owner specifically cares about a three-day VVIX lead foreshadowing volatility, measure
  what VIX did over the next 1 and 5 market sessions after every qualifying streak. Show raw counts
  before rates and do not claim predictive value from fewer than 10 resolved cases.
- Keep calculation accuracy separate from predictive usefulness. The display may be correct even if
  the historical signal has no edge; in that case the card must stay descriptive and must not imply a
  proven forecast.
- Have Codex inspect the replay rows and the final real Discord render before closing.

## Files / code involved

- `consensus_engine/alerts/commands.py` — fetches the VVIX row and renders the `!market` field.
- `consensus_engine/db.py` — `vol_of_vol_daily` table.
- `tests/test_vvix_residual.py` — current display and daily-change coverage.
- `todo/vvix-vix-daily-change.md` — completed first step and its safe omission rules.

## Open questions

- Whether to emphasize a VVIX-up / VIX-down divergence with its own icon. Decide from real rendered
  examples; do not turn that display choice into a prediction or score.
