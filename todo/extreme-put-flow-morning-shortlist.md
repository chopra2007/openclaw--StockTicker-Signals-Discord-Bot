# Extreme PUT-flow morning shortlist

**Status:** SOAKING until 2026-09-26
**Created:** 2026-08-24

**CURRENT STATUS (2026-08-24, late evening):** Pre-open hardening is DONE and
proven. The card no longer claims every PUT was bought — it says "extreme PUT
activity" and shows the real option-side label per name, taken from the existing
#options-flow classifier. The frozen rule did not move: the live selector still
reproduces the frozen 188 picks exactly. Four timers are armed for the morning
(6:10 readiness, 6:15 watch card, 6:35 entry, 6:40 entry proof), all Pacific.

**Next two things to look at, in order:**

1. **2026-08-25 after 6:40 a.m. Pacific — the entry check.** The 6:35 job should
   enter AMZN, GOOGL, META and BMNR. Silence from the 6:10 and 6:40 checks means
   it went right. Any message in the #errors room names the exact failed check.
2. **2026-08-31 — the exit check.** Those four close at 6:35 a.m. Pacific and a
   result card is posted.

## Pre-open hardening — DONE 2026-08-24

Execution contract: `.omc/plans/todo-96-preopen-hardening-prompt.md`.

1. **The option side is shown, not invented.** Each shortlist row now copies the
   `flow_side` already stored by the #options-flow scanner. No second classifier
   was written. A row collected before that label existed reads "side not
   recorded — older than the label" and stays that way.
2. **The label cannot pick or rank a name.** Proved two ways: the selection code
   never reads it, and the live selector replayed over all 53 signal dates still
   produces the frozen 188 picks with zero differences.
3. **The false wording is gone.** "heavy PUT buying" became "extreme PUT
   activity" on the card, in the module, in this file and in the independent
   verification write-up. The card now says in plain words that the pair is
   bearish because of the SIZE of the PUT trading, and that the option-side
   label describes one print and does not choose the names.
4. **The label is frozen at pick time.** `put_flow_shortlist` stores its own copy
   (`flow_side`, `flow_side_note`), so re-grading a source row later cannot
   rewrite what a posted card said. `--side-report` counts closed results
   separately for PUT BUY, PUT SELL, side-unclear and not-recorded.
5. **Two new checks, both silent when things are fine.** 6:10 a.m. readiness and
   6:40 a.m. entry proof. A real failure posts ONE message naming the exact
   check, through the existing #errors machinery, which fires on the change
   rather than the state.
6. **Short availability is real, not guessed.** Schwab's quote does carry it —
   `isShortable`, `isHardToBorrow` and `htbRate` in the response's `reference`
   block. All three are stored with the entry and shown on the entry card. Only
   an explicit "not shortable" rejects a name; a missing field is never read as
   a No. All four names for 2026-08-25 came back shortable, not hard to borrow,
   borrow rate 0.0.
7. **The whole morning was rehearsed on a separate database** — 42 checks, all
   passed, covering all four labels, zero and four candidates, stale stock
   price, stale SPY price, halted stock, unshortable stock, a duplicate run, a
   Discord failure, a valid entry, a valid four-session exit, a readiness
   failure, an entry-proof failure, and weekend/holiday dates. Plus one real
   Schwab request to prove live access and the response shape.

**Known limit of the 6:10 check:** the 6:15 job is what creates each day's
rows, so on a normal morning the 6:10 check runs before they exist. On those
days it proves ACCESS — the switch is on, the three other timers are armed, the
private room answers, Schwab answers for SPY — but it has no rows to inspect.
It does check the rows whenever they already exist, which is the case for
2026-08-25 because the card went out the previous evening. The rows are always
fully checked after entry, at 6:40. If a row-shape check before entry turns out
to matter, the place for it is the start of the 6:35 entry job, not here.

**The other limitation worth knowing:** `flow_side_note` (the short reason like
"at-ask") was computed by the scanner but never saved to the database until now.
The column exists from tonight, so notes accumulate from here — but the four
names waiting for 2026-08-25 have no note, only the label. Nothing was
back-filled, because deriving the note after the fact would mean re-running the
classifier on old numbers, and that is the guessing this ticket forbids.

## What this is, in plain words

Yesterday the options scanner sometimes sees a burst of PUT trading in a stock
that is enormous compared with how many of those contracts were already open —
50 times bigger or more. That burst turns out to carry real information about
the next few days. What was measured is the SIZE of the PUT activity, not proof
that anyone was buying: the rule never looked at who started the trade.

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
- TODO #80 still owns the statistical BUY/SELL grading decision. This feature
  may display and store the existing tag now, but it must not use the tag as a
  selection filter until that evidence exists.

---

## Session notes — 2026-08-24

Built end to end in one session, from the build prompt at
`.omc/plans/extreme-put-flow-morning-shortlist-build-prompt.md`.

**What happened, in order:**

1. Reproduced every number in the build prompt from `consensus.db` before
   touching code. All matched: 2,680 events, 349 extreme PUT events at 33.5%,
   188 picks over 53 mornings and 88 stocks, +1.795% average. The only
   differences were in the resampled 95% range and the early/late split, both
   from a different random seed and a one-day difference in where an odd number
   of dates splits. Neither changes a conclusion.
2. Froze the candidate list and its fingerprint
   (`5b7cfcc12ec454113bb7b5bdb7713938d8f129f21977e252b175d2db9ab98427`), then
   wrote down the hard-to-borrow rule, both **before** fetching a single price.
3. Found that Schwab `/pricehistory` serves 5-minute bars back about six months.
   That covered the whole window, so **nothing was bought** — the Databento
   credit is untouched at $8.471612 and no auction data was purchased. All 89
   tickers returned complete bars; zero trades were unpriceable.
4. Ran the exact 6:35 a.m. Pacific test. **All eight gates passed.**
5. One real methodology fix along the way: the first version of gate 8 compared
   the 53-morning selected average against a 26-morning control. A "same-date
   comparison" has to be date-matched or it compares different markets. Fixed to
   re-average the selected group over exactly the control's mornings. This was
   correcting a bug in the gate, not loosening it — and it is worth knowing that
   the ranked-5th-to-8th names earn nearly as much as the top four, so the edge
   is in the extreme-PUT filter, not in the ranking.
6. Built the feature, then **replayed the live selector over all 53 signal
   dates**: it produced the frozen 188 picks exactly — same stocks, mornings and
   ranks, zero differences. That is the proof the morning job uses the same rule
   as the test, rather than an assertion that it does.
7. Turned it ON owner-only in the same session and posted a real card, read back
   from Discord.

**Proof run:**

- 29 focused tests pass; full suite 3,579 passed, 0 failed (`.test-baseline` is
  empty, so zero regressions).
- `db.py` and `config/consensus.yaml` are both tripwire files, so `!all NVDA`
  and an @-mention were both re-checked in Discord — both answer correctly.
- Real Schwab quotes exercised both entry branches on a scratch copy of the
  database: the freshness guard refused all four names at 8pm ("quote is 11714s
  old"), and with the window widened it stored real entries (GOOGL $348.06,
  BMNR $24.14, SPY $763.47) while the halt guard correctly rejected AMZN and
  META as "closed". The exit path produced +1.71% from a -1.96% stock move
  against a flat SPY, less the 0.25% cost.
- Services active, symlink correct, no drift or AI-health failures, ownership
  clean.

**An independent agent** rebuilt the whole pipeline with its own code, forbidden
to import any of the builder's scripts. Verdict CONFIRMED: every headline number
matched to the decimal, all 12 hand-checked trades matched, and seven specific
error checks (look-ahead, exit spacing, cost sign, trade direction,
forward-looking selection columns, duplicate candidates, off-calendar prices)
came back clean. One sentence in its report described the trade as buying rather
than shorting — its numbers were computed correctly, only the prose slipped, and
that sentence is now corrected in the report.

**First live card** posted 2026-08-24 evening for signal date 2026-08-24, so the
6:15 job on 2026-08-25 will correctly skip re-posting (duplicate guard) and the
6:35 job will enter AMZN, GOOGL, META and BMNR.

**What to look at first next session:** whether the 6:35 entries actually filled
on 2026-08-25, and the result card due 2026-08-31.
