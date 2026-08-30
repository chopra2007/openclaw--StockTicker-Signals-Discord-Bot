# Trade 20 liquid tech names, and hunt for free options data first

**Status:** OPEN
**Created:** 2026-08-29

**CURRENT STATUS (2026-08-29):** Built and scheduled. The collector saves
one-minute Schwab stock quotes and bars for 20 trade names plus market context,
then uses licensed Databento option data for the nearest four expirations and a
15% strike band. Raw Schwab option chains are not stored because this account's
terms prohibit that. Both timers are active, SPX forward collection is on, and
the free-data search found no usable 100-day intraday source. Two gates remain:
the existing Databento key is rejected, and the first real trading-day files
cannot be inspected until Monday, 2026-08-31. Keep this item open until both are
cleared.

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

## Job 1 — BUILD THIS: a full option-chain collector for 20 names

**Approved by the owner 2026-08-29.** This is the buildable feature. Everything
else on the page is research around it.

**Implementation safety note (2026-08-29):** the repository's Schwab client
states that raw per-strike chains cannot be stored under this account's
personal-use terms. The build therefore uses Schwab only for stock data and
uses licensed Databento OPRA rows for stored option chains.

### 1a. Why a FULL chain and not just the strikes a rule wants

Every option capture built so far was made for one specific rule, so the moment a
new rule appears the 100-day clock restarts. `put_flow_option_monitor.py` saves
only the contracts its frozen selector picked — change the strike or expiry rule
and the stored data is useless. A full chain snapshot is general: save the whole
chain and any future rule can be tested against data already in hand.

### 1b. What this one collector unblocks

| Blocked item | Why a full chain fixes it |
|---|---|
| #106 credit spreads | Needs both legs quoted at the same instant. A full chain contains every spread that could be built, not only the ones we thought of today. Gate is 250 spreads over 100 days. |
| #100 morning PUT trade | The current monitor saves only the frozen selector's contracts. A full chain lets a later session re-pick strikes and expiries without restarting the clock. |
| #56 unusual options flow | We record that a big trade happened but not whether buying it paid. The chain supplies the price it would have cost and what it was worth later. |
| #47 option-surface predictor | Implied volatility and skew are computed *from* a chain. This is exactly what the ~$50/month Alpha Vantage quote was for — buildable ourselves from owned data. |
| #80 buy/sell-side direction | Already stores bid/ask per flow row; the surrounding chain adds the context that row is missing. |

### 1c. The build spec

Use the **existing Schwab client** (`consensus_engine/` Schwab integration,
shipped and live since #57), **not yfinance** — yfinance option chains run about
15 minutes stale, which is useless for a minute-level exit rule. Schwab is
real-time. Chain requests must be bounded to the nearest N strikes; a full SPY
chain is over 500 contracts and will blow the rate limit.

- **When:** every minute, 06:30–13:00 Pacific, trading days only.
- **What:** for each of the 20 tickers, every strike within roughly ±15% of the
  current price, across the nearest 4 expirations — bid, ask, bid size, ask
  size, last, volume.
- **Plus:** the underlying stock price stamped on the same timestamp, so a
  spread's value is never mixed across two moments.
- **Plus:** one open-interest snapshot a day. It only updates overnight and can
  never be filled in for a day that has passed.
- **Where:** daily parquet files, one per date, compressed.
- **Observer only:** no orders, no alerts, no change to live scoring or any
  Discord output. Nothing user-facing moves.
- **Proof of done:** one real trading day's output inspected row by row — real
  timestamps, sane spreads, the expected strike count — before calling it done.
  Not a replay of stored data.

### 1d. The prompt to build it

> Build a full option-chain collector for the 20 tickers in TODO #109 using the
> existing Schwab client. Every minute from 6:30am to 1:00pm Pacific on trading
> days, save bid/ask/sizes/last/volume for every strike within ±15% of spot
> across the nearest 4 expirations, plus the underlying price on the same
> timestamp, to daily parquet files. Bound each chain request to nearest-N
> strikes. Add a once-daily open-interest snapshot. Observer only — no orders,
> no alerts, no changes to live scoring. Prove it with one real trading day's
> output inspected row by row before calling it done.

### 1e. Watch out for

- Schwab's token needs a weekly re-login, and a root-owned token file has killed
  the options feed before (2.1 days lost). Check file ownership after any edit.
- Rate limits: 20 tickers x 4 expirations every minute is a lot of calls. Bound
  the strikes and measure the real call count before scheduling it.
- The service reads `/root/.openclaw/.env.service`, not `.env`. Any new key goes
  in both.

### 1f. Pick the 20 names

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

### 1g. The full capture list — everything a future test could need

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

### 1h. Disk space — measured, not guessed

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

**Job 1 (the build) — this is what "complete #109" means first:**

1. The 20 names are chosen and written into the collector's config, each with a
   note on whether its stock history already exists locally.
2. The collector is coded, scheduled, and running as an observer — no orders, no
   alerts, no live scoring touched.
3. One real trading day's output has been inspected row by row: real timestamps,
   sane bid/ask spreads, the expected number of strikes, the underlying price on
   the same stamp. A replay of stored data is NOT proof.
4. The once-daily open-interest snapshot has landed real rows.
5. Tests pass and the regression baseline is unchanged.

**Job 2 (the hunt) — runs alongside, finishes after:**

6. `.omc/research/` holds a graded table of every free-data lead, each marked
   HAS HISTORY / LIVE ONLY, and INTRADAY / EOD ONLY.
7. A one-line recommendation: free source found (name it), or keep the collector
   running for 100 days, or buy ThetaData at $40.

**Not in scope:** testing any trading rule. This item builds the data supply
only. No rule may be declared profitable off the back of it.

### Session notes — 2026-08-29

- Chosen trade names: AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, AVGO, AMD,
  NFLX, MU, QCOM, INTC, PLTR, CRM, ORCL, SMCI, COIN, NOW, and PANW. All 20 have
  local daily stock files; none has the required local minute history.
- Added SPY and QQQ as option context, SPY/QQQ/XLK/SMH as stock context, and SPX
  forward collection because no usable free intraday history was found.
- Built `scripts/full_chain_collector.py`, its config, two scheduled tasks, a
  strict daily proof report, and focused tests. The stock path also records
  bid/ask sizes, extended-hours bars, halts, earnings times, dividends, splits,
  and early closes.
- Both scheduled tasks are active. The stock timer starts Monday at 04:00
  Pacific; the daily option job runs at 13:20 Pacific. Weekend skip runs passed.
  A separate proof check is scheduled for 15:30 Pacific under task
  `1788058600_02e314`, so the first files are checked automatically.
- Focused checks passed as the `openclaw` account: 24 passed. The project gate
  reached 3,816 passed and reported no new failures. Its sealed test area also
  hid the account's Databento package from one unrelated auction-research test;
  the real service account imports Databento 0.85.0 successfully.
- Research is saved at `.omc/research/todo-109/free-options-data.md`. Databento
  is the best technical fit, with a hard $2 daily ceiling in the collector, but
  the existing key returned an authentication failure. That blocks raw option
  rows until the access is renewed. Monday's live files still must be inspected
  before this task can be marked done.

## Files involved

- `data/mmhl_minute/`, `data/mmhl_daily/` — existing stock history
- `scripts/research/pdtm_*.py` — #106's research code, reusable
- `consensus_engine/analysis/put_flow_option_monitor.py` — existing narrow option capture; the model for the new collector, but it saves selected contracts only
- Schwab client + `/root/.openclaw/.env.service` — real-time chains (#57, live since 2026-06-30)
- `.omc/research/professional-day-trader-methods/` — #106's source-grading format

## Open questions

- Does the owner want to trade the 20 names, or SPX, or both? Free data may only
  exist for SPX, and they are different instruments.
- Nearest expiration only, or several? Several multiplies the data by ~5.
- How wide a strike band? Too narrow and a future rule can't be tested; too wide
  and it's 5x the storage.
