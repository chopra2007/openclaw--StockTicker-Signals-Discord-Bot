# Trade 20 liquid tech names, and hunt for free options data first

**Status:** OPEN
**Created:** 2026-08-29

**CURRENT STATUS (2026-08-29):** Nothing built yet. Three jobs, in this order:
(1) pick the 20 names and start saving every field they need TODAY, because a
field not saved today cannot be recovered later; (2) hunt for a free source that
already holds *past* minute-by-minute option prices — if one exists it skips the
100-day wait entirely; (3) act on the extra suggestions below. Job 1 and job 2
run at the same time. Do not wait for the hunt to finish before starting to save
data — that is the whole point.

---

## Why this exists

Two recent research runs (#104, #106) rejected every share rule tested. Both
ended at the same wall on the options side: we hold 3 days of two-sided option
quotes on 11 companies, against a bar that needs 100 days. And the owner's point
from this session, which is correct and decides the whole data question:

> A credit spread can be up 5x during the day — you could buy it back for almost
> nothing — and if you don't take it, the stock moves through your short strike
> and you pay to close at a loss.

So **exit timing decides the trade**, which means end-of-day option data is not
enough. Any real test needs prices *through* the day, not one snapshot at the
close. That kills the cheap Cboe end-of-day idea for testing exits, though EOD
data is still fine for picking which strikes were liquid.

---

## Job 1 — 20 names, and save everything they need starting now

**The owner's instruction, verbatim in spirit:** don't come back in 100 days and
say a field was forgotten. So the capture list below is deliberately wider than
what any one rule needs.

### 1a. Pick the 20 names

Current stock history is 60 **NYSE** large caps (Databento EQUS.MINI +
XNYS.PILLAR, 2023-2026). **Most big tech is NASDAQ-listed** — AAPL, MSFT, NVDA,
AMZN, GOOGL, META, TSLA, AVGO, AMD, NFLX, COST, ADBE, INTC, MU, QCOM. Before
anything else, check which of the wanted 20 already have history in
`data/mmhl_minute/` and `data/mmhl_daily/`, and which need to be pulled.
EQUS.MINI is consolidated so it should carry NASDAQ names; XNYS.PILLAR will not.
Verify, don't assume.

Rough candidate 20 (tech-heavy, all deeply liquid, all with active weekly
options): AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO AMD NFLX MU QCOM INTC PLTR
CRM ORCL SMCI COIN + SPY QQQ. Owner should confirm or swap names.

### 1b. The full capture list — everything a future test could need

Per name, per minute, saved forward from day one:

**Stock side**
- 1-minute open/high/low/close/volume — already have the pipeline.
- 1-minute **bid, ask, and the size on each side**. This is the gap that has
  wrecked prior work: trade-only bars mean "I got filled at the next minute's
  open" is an *assumption*, never a measurement. Every past result carries that
  as an unremovable weakness.
- Extended hours too (04:00-06:30 and 13:00-17:00 Pacific), not just the regular
  session. Prior extracts threw pre-market away and it took a re-extract to get
  it back.
- Trading halts and their reasons.

**Options side** (this is where the money is, and where we have nothing)
- Full chain snapshot every minute during the session: **bid, ask, bid size, ask
  size, last, volume** for every strike within a sensible band, for the nearest
  few expirations. Not just the strikes a rule wants today — a rule invented in
  three months will want different strikes.
- **Open interest**, once a day. It only updates overnight and it is
  unreconstructible after the fact. Free from yfinance.
- The underlying price stamped at the same instant as the option quote, so a
  spread's value is never mixed across time.

**Things that quietly matter and get forgotten**
- Splits and dividends (three splits already bit us: ANET, APH, NOW).
- Earnings announcement date **and** whether it was before the open or after the
  close. Recording this forward is far more reliable than digging it up later.
- Short borrow rate and hard-to-borrow flags — Schwab's `/quotes` reference block
  already exposes `isShortable` / `isHardToBorrow` / `htbRate`.
- SEC Rule 201 short-sale restriction, with the **time** it triggered, not just a
  whole-day flag. The whole-day flag made #106's counts an upper bound only.
- Index/sector context: SPY, QQQ, and the sector ETF, on the same minute grid.
- Whether the day was a half day (early close) — phantom prints after half-day
  closes are a known trap in our minute files.

### 1c. Disk space — measured, not guessed

- Compressed parquet: ~30 bytes a row (our stock bars run 12.4).
- Live-forward, only what actually fires: ~23 MB a year.
- 20 names, full option chains, every minute, 100 days: order of **1-2 GB**,
  depending on how many strikes and expirations are kept. There is ~25 GB free.
  Space is not the constraint. Discipline about *what* gets saved is.

---

## Job 2 — hunt for free minute-by-minute option prices

**The test that decides whether a source is useful:** does it hold the **past**,
or only **right now**? A source that shows today's chain still means a 100-day
wait. A source with history skips the wait entirely. That is the only question
that matters at first contact.

**Second test:** does it have prices *through the day*, or one end-of-day number?
Per the owner's point above, one number a day cannot test an exit.

**A warning to state up front:** SPX is a cash-settled index option, European
style, no early assignment. Free SPX data tests an **SPX method**. It says
nothing about a spread on AAPL. If we go this route, the rule we test has to be
an SPX rule — which is fine, SPX 0DTE is one of the most traded instruments in
the world, but it must be an honest choice, not a substitution smuggled in.

### Leads to check, each UNVERIFIED until someone opens it

| Lead | What to check |
|---|---|
| OptionsDX | Advertises free historical option chain downloads including SPX/SPY. Check: how far back, intraday or EOD, does it carry bid/ask. Highest-value lead if intraday. |
| Alpaca free tier | Free account reportedly includes historical options bars from early 2024. Check the actual granularity and whether quotes or trades only. |
| Polygon.io free tier | Options endpoints exist; free tier is rate-limited and may cap history. Check the real limits. |
| Tradier developer sandbox | Free key, option chains with bid/ask. Almost certainly live-only — confirm. |
| Databento free credit | $125 of credit on a free account; already noted in TODO #100. Check what OPRA history that actually buys. |
| Cboe DataShop free samples | Cboe publishes sample files. Check whether a sample covers enough days to be useful. |
| GitHub archives | People have been archiving SPX 0DTE chains publicly for years. Search for repos and public datasets; check licence and completeness. |
| Public option charts | Some sites chart an option contract's price minute by minute. If one is scrapeable, a chart read to the nearest few cents is enough for a rule that trades 40 bps of edge. |
| ThetaData $40/mo | The known-good paid fallback. Their tier gives real minute option data. This is the answer if free fails — and it is now the *only* option-data purchase worth considering, because end-of-day data cannot test exits. |

Grade every source the same way #106 graded its sources, and write the results
into `.omc/research/` before spending a day on any one of them.

---

## Job 3 — other suggestions worth doing

1. **Start collecting while researching.** If the free hunt takes three weeks and
   fails, we should be three weeks into the 100 days, not at zero. Costs nothing
   but disk. This is the single highest-value item on the page.
2. **Get quotes for the stocks too, not just the options.** Every share result so
   far rests on an assumed fill. Real bid/ask would let us finally measure what a
   fill actually costs instead of charging a flat 20-40 basis points and hoping.
3. **Keep the sealed period sealed.** The 2025-12-01 → 2026-08-21 window has now
   survived two research runs unopened (#104, #106). It is the most valuable
   asset in the project. Any new work uses the development window only.
4. **Don't re-test what's already dead.** Rejected, with evidence: opening
   auction (#93), event reaction, six trade methods (#97), intraday dislocation
   (#103), three share methods (#104), three professional methods (#106).
   Anything new should be a genuinely different mechanism, or use genuinely new
   data — options being the obvious example of new data.
5. **Save the earnings calendar forward from today.** Accurate before-open /
   after-close timing is painful to reconstruct and easy to record live.
6. **Log open interest daily starting now.** It is free, it is tiny, and it can
   never be filled in for a day that has passed.

---

## Definition of Done

1. The 20 names are chosen and written down, with a note for each on whether its
   stock history already exists locally.
2. A collector runs every session and saves the full 1b list, with its output
   inspected on a real trading day — real rows, real timestamps, eyeballed.
3. `.omc/research/` holds a graded table of every free-data lead, each marked
   HAS HISTORY / LIVE ONLY, and INTRADAY / EOD ONLY.
4. A one-line recommendation: free source found (name it), or start the 100-day
   clock, or buy ThetaData at $40.

## Files involved

- `data/mmhl_minute/`, `data/mmhl_daily/` — existing stock history
- `scripts/research/pdtm_*.py` — #106's research code, reusable
- `consensus_engine/analysis/put_flow_option_monitor.py` — existing option capture
- `.omc/research/professional-day-trader-methods/` — #106's source-grading format

## Open questions

- Does the owner want to trade the 20 names, or SPX, or both? Free data may only
  exist for SPX, and they are different instruments.
- Nearest expiration only, or several? Several multiplies the data by ~5.
- How wide a strike band? Too narrow and a future rule can't be tested; too wide
  and it's 5x the storage.
