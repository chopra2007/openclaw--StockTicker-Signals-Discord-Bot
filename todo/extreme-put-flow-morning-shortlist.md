# Extreme PUT-flow morning shortlist

**Status:** SOAKING until 2026-09-26
**Created:** 2026-08-24

**CURRENT STATUS (2026-08-24):** Built, tested, and turned ON in owner-only mode
the same session. All eight frozen gates passed on stored data and an
independent verifier reproduced every headline number from scratch. The two
timers are armed. What the soak buys: real posted cards and real 6:35 a.m.
entries and exits accruing in `put_flow_shortlist`, which is the only thing that
can tell us whether the live feature behaves like the historical test. First
real card fires 6:15 a.m. Pacific on 2026-08-25.

## What this is, in plain words

Yesterday the options scanner sometimes sees a burst of PUT buying in a stock
that is enormous compared with how many of those contracts were already open —
50 times bigger or more. That burst turns out to carry real information about
the next few days.

Each morning this feature turns yesterday's biggest bursts into **zero to four**
stocks to watch. The trade it supports is a **pair**: put equal dollars into
shorting the stock and into buying SPY. That hedge matters — it is what makes
the result about the stock rather than about the market.

## The measured evidence

Stored data, 2026-06-01 to 2026-08-14. Every trade priced at the real first
print at or after 6:35 a.m. Pacific, held four trading sessions, then closed at
the first print at or after 6:35 a.m. Pacific.

| What | Number |
|---|---|
| Trades | 181 |
| Mornings | 53 |
| Different stocks | 82 |
| Average result after a 0.25% round-trip cost | **+1.83%** |
| Trades that made money | **65.2%** (conservative lower estimate 58.0%) |
| 95% range for the average (grouped by morning) | +0.70% to +2.96% |
| Profit factor (money won per money lost) | 2.01 |
| Biggest single stock's share of the profit | 7.0% (AAPL) |
| First half of the period | +2.50% |
| Second half of the period | +1.22% |

All eight frozen pass/fail gates passed. The unhedged stock short was measured
separately — +1.69% average, 60.8% winners — and it also cleared gates 1 to 7,
but **the feature only ever shows the pair trade**, because the pair is what the
required outcome specified and it is the safer of the two.

Same-morning comparisons: the picked stocks beat both the lower-ranked extreme
PUT names and the stocks with no extreme PUT flow on the same mornings.

## The frozen rule

Lives in `consensus_engine/analysis/put_flow_shortlist.py` as module constants,
deliberately NOT as config keys, so no future session can quietly retune them.

1. PUT side only.
2. Single stocks only — index and sector funds are excluded.
3. Day volume divided by open interest at least 50.
4. At least 500 contracts and at least $250,000 traded.
5. One event per stock per day: its biggest burst.
6. Rank by burst size, keep at most four.
7. The newer BUY/SELL tag is NOT used as a filter — its history is too short.
8. Zero names is a normal day.

The live selector was replayed over all 53 signal dates and produced the frozen
188 picks **exactly** — same stocks, same mornings, same ranks, zero differences.

## What runs, and when (all Pacific)

- `put-flow-shortlist-watch.timer` — 6:15 a.m. weekdays. Picks from yesterday's
  completed session, saves the rows, posts the watch card. The card says plainly
  that nothing is valid until the 6:35 price check.
- `put-flow-shortlist-trade.timer` — 6:35 a.m. weekdays. Closes anything due,
  then takes fresh Schwab prices for each stock and SPY, throws out anything
  missing, stale, crossed, or halted, records the simulated entry, updates the
  card.

Nothing places an order. Every entry and exit is simulated and stored.

## Files

- `consensus_engine/analysis/put_flow_shortlist.py` — the frozen rule, calendar,
  quote checks, pair arithmetic
- `scripts/put_flow_shortlist_job.py` — the three jobs and the cards
- `consensus_engine/db.py` — the `put_flow_shortlist` table
- `config/consensus.yaml` — the `put_flow_shortlist:` block
- `tests/test_put_flow_shortlist.py` — 29 focused tests
- `/etc/systemd/system/put-flow-shortlist-{watch,trade}.{service,timer}`

Research and proof:

- `.omc/plans/extreme-put-flow-morning-shortlist-build-prompt.md` — the build contract
- `.omc/research/extreme-put-flow-morning-shortlist/` — frozen candidate list and
  its fingerprint, the frozen borrow rule, the exact-entry results, every trade,
  and the independent verification
- `scripts/research/put_flow_{freeze_candidates,fetch_bars,exact_entry_test}.py`

## Known risk

**Borrow cost is not included.** Nothing in this project stores a daily borrow
rate, so the results are before the cost of borrowing the stock to short it. The
hardest-to-borrow names were removed rather than charged, using a rule written
down before any result existed: drop a stock under $5, or under $50 million
median daily dollar volume over the prior 20 sessions. Seven of the 188
candidates were dropped that way. A stock can clear both bars and still cost a
percent or two a year to borrow, which would eat into a +1.83% four-day result
only slightly — but this is a real, disclosed gap, not a solved problem.

Second risk: two and a half months of one market regime. The second half of the
period was weaker than the first (+1.22% against +2.50%). That is what the soak
is for.

## Related

- TODO #93 (opening-auction edge) is **closed and rejected** and stays closed.
  This is a different mechanism on different data and does not reopen it.
- TODO #57 built the options-flow grading this rests on.
- TODO #80 (grade the BUY/SELL tag) is untouched — this feature does not use it.
