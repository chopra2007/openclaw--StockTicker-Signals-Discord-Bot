# Show analyst direction and catalyst inside the alert

**Status:** OPEN
**Created:** 2026-08-17

**CURRENT STATUS (2026-08-17):** Not started. The last 10 live `#alerts` messages were checked. They
show analyst names, the time window, and a price, but not whether the group is bullish, bearish, mixed,
or unclear, and not why they are talking about the stock. The needed direction and original tweet text
already exist in the database. Next: design one compact card that shows the group view and each
analyst's reason without adding a second AI call to the instant-alert path.

## What the user wants

The owner should be able to read one `#alerts` card and immediately know:

- Whether the analysts are bullish, bearish, mixed, or unclear.
- The catalyst or setup each analyst is reacting to.
- Which analyst said what, without opening every source link.

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

## What does not work and why

`SwarmResult` carries only analyst names and first-post times. `format_swarm_alert()` therefore can
only render names, window, and price. The sender later looks up source links, but it does not look up
direction or the stored tweet text.

Some stored rows are neutral or have no direction. The card must say `unclear` for those rows instead
of guessing. A generic activity post such as “popular stocks with increasing option volume” is not a
directional catalyst and must not be dressed up as one.

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
7. Render the RDDT example and at least one mixed-direction example, then inspect the actual Discord
   cards before marking this done.

## Files / code involved

- `consensus_engine/analysis/herding.py` — builds `SwarmResult` and knows the exact group window.
- `consensus_engine/alerts/discord.py` — formats and sends the card.
- `consensus_engine/db.py` — `signal_events` and `ticker_signals` hold direction and raw text.
- `consensus_engine/models.py` — `ParsedTweet.direction`, `.summary`, and `.raw_text`.
- `consensus_engine/main.py` — inserts each parsed tweet before group detection runs.
- `tests/test_analyst_swarm.py` — group behavior and current card tests.

## Open questions

- Whether the existing parsed summary is consistently short and factual enough to store and display.
  Answer this with real recent tweets before choosing a new database field.
- When several analysts repeat the same catalyst, show one shared `Main reason` plus short analyst
  lines rather than repeating the same sentence four times.
