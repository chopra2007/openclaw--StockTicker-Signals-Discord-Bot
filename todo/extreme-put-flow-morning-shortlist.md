# Extreme PUT-flow morning shortlist

**Status:** SOAKING until 2026-09-26
**Created:** 2026-08-24

**CURRENT STATUS (2026-08-26):** Entries are filling cleanly and the option and
borrow data is now being saved. But the portfolio test says this is NOT a clean
pass: run as a real overlapping account it clears six of seven frozen checks and
**fails the seventh once a harsh 20%-a-year stock-borrowing fee is charged**. The
honest sentence is: the isolated-trade test passed; portfolio viability did not.
The signal rule was not changed and nothing was retuned. #96 stays owner-only and
stays soaking. Detail below.

**1. The entries filled.** AMZN, GOOGL, META and BMNR all entered at 6:35 a.m.
Pacific this morning, all four shortable and not hard to borrow, borrow rate
0.0. The 6:10 readiness check and the 6:40 entry proof were both silent, which
is what a clean morning looks like. They close 2026-08-31.

**2. The portfolio test says this is NOT a clean pass.** The published +1.83%
is an average of trades looked at one at a time. Run as a real account — up to
four new trades a morning, four days each, several open at once, SPY legs
stacking — it clears six of seven frozen checks but **fails the seventh once a
harsh 20%-a-year stock-borrowing fee is charged**. So the honest sentence is:
**the isolated-trade test passed; portfolio viability did not.** Details below
under "The portfolio test". The signal rule was NOT changed and nothing was
retuned. #96 stays owner-only and stays soaking.

**Also new (TODO #98):** from tomorrow morning the system starts SAVING the
option chain and the borrow fields at every entry, every daily mark and every
exit. That is the only route to ever answering "would buying a put have made
money?" and "what did borrowing actually cost?", neither of which was ever
recorded before today.

**Updated 2026-08-27 (TODO #100):** "permanently unknown" was too strong. The
exact bid and ask quoted at the time really are gone for an expired contract,
but an approximate minute-by-minute trade path is often still buyable, cheaply.
The option question was asked properly and came back **INSUFFICIENT DATA** — no
rule promoted, no option recommendation, and the option display stays off.

**Next two things to look at, in order:**

1. **2026-08-26 after 6:50 a.m. Pacific.** Did the new option and borrow saving
   actually store rows for the four open positions? Silence from the 6:50 check
   means yes; the report is written to the deferred-task notifications file.
2. **2026-08-31 — the exit check.** Those four close at 6:35 a.m. Pacific, a
   result card is posted, and it will be the first trade with a closing option
   quote saved beside it.

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

## The portfolio test — six of seven checks pass, one fails

Full report: `.omc/research/put-flow-portfolio-audit/RESULT.md`. Independently
rebuilt from scratch by a second agent that was forbidden to read the builder's
code: **CONFIRMED**, every number matched, 12 trades hand-checked, no defect
found (`independent-verification.md`).

Every rule was written down and fingerprinted **before** a single number was
computed (`frozen-portfolio-policy.sha256`, fingerprint
`24a94ad3f8faadfb9e028f6bd6b680fe6e23416d27731e8e1e7ed2e4b9a4918a`).

A pretend $100,000 account, $6,250 per leg, at most 16 pairs open at once,
priced every trading day at 6:35 a.m. Pacific — the same clock the live rule
uses. Borrow cost does not exist in this project's records, so four rates were
tried rather than one flattering guess.

| | 0% borrow | 20% borrow |
|---|---:|---:|
| Total over 12 weeks | +20.7% | +17.1% |
| Worst peak-to-valley dip | 5.1% | 5.3% |
| Money won per dollar lost | 2.00 | 1.78 |

Six checks pass under both. **Check 4 fails at 20% borrow**: the 95% range for
the typical day's return is −0.038% to +0.565%, so it includes zero. At 0%
borrow the same range is +0.013% to +0.607% and passes. The verifier re-ran it
with eight different random starting numbers; all eight failed at 20% and all
eight passed at 0%, so this is a real gap, not a coin flip.

The rule was "all seven or it does not count." It does not count.

**What that does and does not mean.** It does not mean the edge is fake — the
account never came close to losing money, it stayed ahead even at a brutal
100%-a-year borrow rate, and the three neighbouring entry times (6:35, 6:40,
6:45 a.m. Pacific) all stay positive with more than a dollar won per dollar
lost. It means the daily-return statistics stop being convincingly positive
once a harsh borrow cost is charged, and that borrow cost is still a guess.
Which is exactly why TODO #98 starts measuring the real one.

**Nothing about the live rule changed because of this test.** The timing
comparison was a falsification check, not a contest, and production timing was
not moved toward whichever row looked best.

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

All eight frozen pass/fail gates passed **for trades looked at one at a time**.
Run as a portfolio those same trades fail one of seven portfolio checks under a
harsh borrow assumption — see "The portfolio test" above. The unhedged stock short was measured
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

### Session notes — 2026-08-24

- **Worked on:** Pre-open hardening, from `.omc/plans/todo-96-preopen-hardening-prompt.md`. The card's option-side label (copied from the existing #options-flow classifier, frozen into the row), the "PUT buying" → "extreme PUT activity" wording fix applied to the already-posted 2026-08-25 card in place, real Schwab short availability, and two new silent morning checks at 6:10 and 6:40.
- **Decisions:** (1) Did NOT back-fill `flow_side_note` for the four waiting rows — deriving it after the fact means re-running the classifier on old numbers, which this ticket forbids; the column exists so notes accumulate from here. (2) Did NOT add a row-shape check to the 6:35 entry job, even though the 6:10 check cannot see rows that the 6:15 job has not created yet — changing the live entry path hours before its first real run was the worse trade. Written up in the "Known limit of the 6:10 check" section above. (3) Trimmed the card text and tightened its length test to 1950 chars, because the real post carries an "@owner " prefix the old 2000-char test ignored.
- **Next:** 2026-08-25 after 6:40 a.m. Pacific — did AMZN, GOOGL, META and BMNR actually enter, and were the 6:10/6:40 checks silent? Then the 2026-08-31 result card. First real open is the one thing tonight could not simulate.

### Session notes — 2026-08-26

- **Worked on:** not the rule — only what is claimed about it, plus the new data
  collection hanging off the same 6:35 job. See TODO #98.
- **The entry check from last session is answered:** AMZN, GOOGL, META and BMNR
  all entered at 6:35 a.m. Pacific on 2026-08-25, all shortable, and the 6:10
  and 6:40 checks were both silent. Four more entered 2026-08-26 (DKS, SUI,
  MSTR, MARA).
- **Decisions:** the frozen rule file was not touched — zero diff across every
  commit this session, and the live selector still reproduces the frozen 188
  picks exactly (re-verified after all the changes landed). The portfolio
  finding changed the DESCRIPTION, not the rule.
- **Next:** 2026-08-31, when the first four close and a result card is posted.
