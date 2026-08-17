# Show analyst direction and catalyst inside the alert

**Status:** OPEN
**Created:** 2026-08-17

**CURRENT STATUS (2026-08-17):** Not started. The last 10 live `#alerts` messages were checked. They
show analyst names, the time window, and a price, but not whether the group is bullish, bearish, mixed,
or unclear, and not why they are talking about the stock. The owner expanded the job: Codex must review
every tweet used in a full historical group replay, compare the proposed direction/catalyst readout to
the original post, and examine where the stock went from the first tweet. Next: build that replay and
accuracy report before choosing the final card wording.

## What the user wants

The owner should be able to read one `#alerts` card and immediately know:

- Whether the analysts are bullish, bearish, mixed, or unclear.
- The catalyst or setup each analyst is reacting to.
- Which analyst said what, without opening every source link.
- Whether Codex independently agrees that each displayed direction and catalyst faithfully reads the
  original analyst post.
- Where the stock went after the first tweet, so the audit also shows whether the directional call
  later worked.

## What worked so far

- `signal_events.direction` already stores `long` or `short` for directional analyst posts.
- `ticker_signals.sentiment` and `ticker_signals.raw_text` already store the direction and original
  post text.
- `ParsedTweet.summary` is already produced when the tweet is read. Reuse or retain that existing
  summary if it is good enough; do not add another model call while the alert is being sent.
- The current analyst names are clickable and should stay clickable.
- A real four-analyst RDDT group from 2026-08-13 was easy to understand from stored data: all four
  were bullish, and the shared catalyst was RDDT joining the S&P 500. The live card did not show either
  fact.
- There is enough history for a real replay. Checked on 2026-08-17: 4,147 stored analyst posts across
  830 tickers and 34 analysts; 2,078 short-catalyst score rows; 271 long-catalyst bets; 6,544 alert
  rows with both entry and 24-hour prices; and 6,063 with both entry and 5-day prices. The latest 100
  messages in both `#twitter` and `#chat` were also readable.
- `scripts/grade_analyst_catalysts.py` already classifies stored posts and grades short catalysts
  against the stock's own sector or peer group at 5, 10, 15, 20, and 21 market sessions. Reuse its
  price and benchmark rules where they fit instead of building a contradictory score.

## What does not work and why

`SwarmResult` carries only analyst names and first-post times. `format_swarm_alert()` therefore can
only render names, window, and price. The sender later looks up source links, but it does not look up
direction or the stored tweet text.

Some stored rows are neutral or have no direction. The card must say `unclear` for those rows instead
of guessing. A generic activity post such as “popular stocks with increasing option volume” is not a
directional catalyst and must not be dressed up as one.

The existing graders do not prove this card is accurate. They grade individual posts or delivered
alerts; they do not reconstruct each analyst group, compare the exact proposed card text to every
source tweet, or anchor the review to the group's first tweet. That missing link is part of this task.

Price movement and reading accuracy are two different checks. A faithfully read bullish tweet can
still be a losing call. A stock going up does not prove that an invented bullish label was faithful.
Keep those verdicts separate in the report.

The current `Window` field also prints a non-Pacific clock range. Any touched replacement must show
Pacific time or omit the clock range; owner-visible output must not show another time-zone label.

## Target card shape

Keep it compact. One possible shape is:

```text
Bias: 🟢 4 bullish · 0 bearish · 0 unclear
Main reason: RDDT is being added to the S&P 500

@ripster47 — 🟢 Bullish — S&P 500 addition; long-term hold
@unusual_whales — 🟢 Bullish — confirmed S&P 500 addition
@OMillionaires — 🟢 Bullish — weekly calls tied to the inclusion
@data168 — 🟢 Bullish — bought calls on the S&P 500 news
```

If the analysts disagree, the headline must say `Mixed`, then show each analyst's own side. If a
reason is absent, say `reason not stated`.

## Next steps, in order

1. Trace the exact post rows that opened or joined a group. Match by ticker, analyst, and the group's
   time window so an older post is never attached to the wrong analyst.
2. Prefer the already-produced parsed summary. If it is not retained, store that value when the tweet
   is first read, or fall back to a short, safely clipped excerpt from `ticker_signals.raw_text`.
3. Add direction and reason details to the data passed into `format_swarm_alert()`.
4. Build a plain aggregate: all bullish, all bearish, mixed, or unclear. Never infer direction from
   the red embed color; red currently means “loud,” not bearish.
5. Replace the owner-visible non-Pacific window with Pacific time or an elapsed span only.
6. Add tests for all-bullish, all-bearish, mixed, missing direction, missing reason, long text, and
   Discord field-size limits.
7. Run the full historical review below, fix every systematic error it finds, and rerun from scratch.
8. Render the RDDT example and at least one mixed-direction example, then inspect the actual Discord
   cards before marking this done.

## Codex review and price backtest required before DONE

This is a hard completion gate, not an optional quality pass.

1. Reconstruct every recoverable analyst-group event from the saved `#twitter` posts and database rows
   using the same analyst-count and time-window rules as production. Do not hand-pick only clean groups.
2. For every tweet used in those groups, give Codex the original post text and useful source material
   without showing it the bot's proposed label first. Codex must independently return:
   - bullish, bearish, neutral, mixed, or unclear;
   - the explicit catalyst or setup, or `not stated`;
   - the short phrase in the post that supports its decision;
   - `unverified` when a claimed real-world event cannot be corroborated from the available source.
3. Compare the independent Codex read to the card's proposed per-analyst line and group headline.
   Review every disagreement. The gate requires zero bullish-to-bearish reversals, zero unsupported
   catalysts, and every genuinely uncertain case displayed as `unclear` or `reason not stated`.
4. Anchor the outcome check to the first tweet in the group. A later analyst joining must not reset the
   starting price or make the move look better.
5. For each group, record the first usable price after that tweet, the raw stock move, the best and
   worst move reached afterward, and the 24-hour, 5-day, and 21-market-session results when available.
   Also show the move after subtracting the matching sector or peer-group move. Raw movement tells the
   owner where the stock went; the benchmark-adjusted move shows whether the call added stock-specific
   value.
6. Use exact intraday entry prices when history supports them. When an old post has only daily bars,
   label that row `daily-price approximation` and keep it separate from exact-entry results. Never
   silently mix the two.
7. Keep two verdict columns: `tweet read accurate?` and `direction later worked?`. A losing but
   faithfully read call passes the first and fails the second.
8. Run the automated replay over all recoverable groups. Codex must review every tweet that contributes
   to those groups, in bounded batches if needed. Save the full audit artifact so another session can
   reproduce the exact rows and judgments.
9. Report counts before rates. Do not show a percentage for a group with fewer than 10 resolved cases.
10. After the offline replay passes, wait for a new real analyst group, compare its displayed readout
    to the source tweets and live price path, and inspect the actual Discord card before closing.

## Files / code involved

- `consensus_engine/analysis/herding.py` — builds `SwarmResult` and knows the exact group window.
- `consensus_engine/alerts/discord.py` — formats and sends the card.
- `consensus_engine/db.py` — `signal_events` and `ticker_signals` hold direction and raw text.
- `consensus_engine/models.py` — `ParsedTweet.direction`, `.summary`, and `.raw_text`.
- `consensus_engine/main.py` — inserts each parsed tweet before group detection runs.
- `scripts/grade_analyst_catalysts.py` — existing post classifier and benchmark-relative outcome path.
- `consensus_engine/analysis/benchmark_grading.py` — shared stock-minus-benchmark calculations.
- `consensus_engine/analysis/source_performance.py` — existing 24-hour and 5-day analyst outcomes;
  useful evidence, but not a substitute for the group replay.
- `tests/test_analyst_swarm.py` — group behavior and current card tests.

## Open questions

- Whether the existing parsed summary is consistently short and factual enough to store and display.
  Answer this with real recent tweets before choosing a new database field.
- When several analysts repeat the same catalyst, show one shared `Main reason` plus short analyst
  lines rather than repeating the same sentence four times.
- How much exact intraday price history is recoverable for the oldest group events. The plan above
  already defines the honest fallback: separate and label daily-price approximations.
