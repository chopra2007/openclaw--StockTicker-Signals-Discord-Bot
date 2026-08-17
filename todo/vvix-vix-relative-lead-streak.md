# Make VVIX leadership and streaks obvious

**Status:** OPEN
**Created:** 2026-08-17

**CURRENT STATUS (2026-08-17):** Not started. TODO #81 already added the daily percentage change for
VVIX and VIX, and the live card now shows both numbers. The comparison still requires mental math and
does not show whether the same relationship has lasted across several market days. The owner added a
historical-proof requirement for every feature; 23 saved VVIX/VIX market-day rows are currently
available. Next: build the lead/streak calculation, replay every saved row, and separately measure
whether a three-day lead actually preceded higher volatility before using predictive wording.

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
