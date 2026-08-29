# Research and test professional day-trader methods

**Status:** DONE 2026-08-29
**Created:** 2026-08-28

**CURRENT STATUS (2026-08-29):** **DONE — SHARES: NO PASS. OPTIONS:
UNTESTABLE.** All three share methods failed every profit gate. Nothing was
built, nothing turned on, no data bought, no production code touched. **The 182
sealed days were never opened** — no method earned the right to be tested there.

Full report: `.omc/research/professional-day-trader-methods/FINAL-VERDICT.md`
Frozen policy fingerprint `dfaed21e0939830f2e963c714399d315233e072576e4802049dc76cbdaed149d`.

| Rule | Trades | Earned before any cost | Needed |
|---|---|---|---|
| M1 opening continuation after acceptance + quiet retest | 390 | **+4.7 bps** | +40 |
| M2 failed push past yesterday's agreed value | 1,524 | **+1.3 bps** | +40 |
| M3 opening-range failed extension (Fibonacci) | 4,115 | **−2.2 bps** | +40 |

### The four things worth keeping from this run

1. **The overnight range cannot be rebuilt from this data.** Measured, not
   assumed: the NYSE feed has **zero** pre-market bars; the consolidated feed
   has a typical of **four** pre-market minutes per company-day, and only 4.1%
   of company-days reach 30. Every overnight-range method is excluded on data.
   Earlier runs discarded these bars at extraction and never measured this.

2. **The owner's conditional-bundle hypothesis is right in direction and an
   order of magnitude too small.** The bare trigger earns +1.7 bps; adding
   location, market state, relative strength, the quiet retest and the room veto
   takes it to +4.7; tightening activity to what the sources actually say
   (relative volume 2.5) takes it to **+9.3**. Every ingredient pulls the right
   way. The bar is +40.

3. **The failure is a size problem, not a direction problem.** M1 beats a coin
   flip 998 times in 1,000 and beats a benchmark that picks companies at random.
   It loses because its median hold is **three minutes** and **194 of its 390
   trades reach their target and still lose money** — the move is smaller than
   the cost of catching it. Any future attempt must hold for hours, not minutes.

4. **The options track is arithmetic, not opinion.** The project holds two-sided
   option quotes for **3 trading days on 11 companies** against a gate needing
   250 spreads over 100 days. Cheapest honest fix, priced from vendor pages
   actually fetched: **ThetaData $40/month** (bid, ask and size every minute back
   to 2020, whole chain per request so both legs share a timestamp). Nothing was
   bought. **This is the one open decision for the owner.**

### Closed by this run — do not re-propose

- Opening continuation with acceptance, retest and context (M1).
- Failed push past the prior value area (M2) — this also closes the
  volume-at-price / value-area family, which had **zero** peer-reviewed support
  and recurs in 6 of 8 practitioner families.
- Opening-range failed extension, Fibonacci or otherwise (M3) — negative before
  costs in all three variants, and the **plain midpoint beats the Fibonacci
  level**.

### Honest weaknesses, recorded

- **Five of seven review agents failed to deliver** (session limit, or wrote
  nothing, or stalled at a skeleton). The lead performed the second-designer,
  independent-rebuild and hostile-review roles. The rebuild used separate,
  non-importing code — a second code path, not a second person. The clean-room
  review is the one outside check that landed, and it found the run's most
  important defect: the placebo could not detect market drift, so a drift
  benchmark was added as a required gate before any number was read.
- A threshold was chosen knowing **sealed trade counts** (never outcomes). Redone
  from development data alone; the peek is disclosed and was not acted on.
- One real look-ahead defect was caught **before** any number existed: the
  eligibility filter used the whole day's bar count. Fixed; all tables rebuilt.
- Two engineering faults found and fixed mid-run (a sizing model implying
  impossible leverage; a bootstrap allocating 6.5 GB), neither touching a profit
  number.

## The goal

Find a small number of share setups, or defined-risk option setups, that make
more money than they cost to trade. Research what working traders actually do —
including sources outside academic finance — turn the recurring practices into
exact rules, freeze the rules before looking at any profit, and test them
honestly.

Two separate verdicts are owed, one for shares and one for credit spreads,
because the evidence for the two can differ.

Driving prompt: `.omc/plans/profitable-day-trader-method-research-prompt.md`
All new work goes under `.omc/research/professional-day-trader-methods/`.

## What is already closed and may not be retried

From TODO #93, #97, #100, #103, #104 — do not retune or rename these:
plain 15-minute opening-range breakout; generic VWAP reclaim; opening-auction
pressure; early-session dislocation reversal or continuation; extreme overnight
gap fade; generic options-flow direction; last stored implied volatility as a
direction call; generic earnings timing; social attention alone; sector
rotation / factor momentum / 200-day regime as a standalone fast signal;
same-time-of-day repetition; volume-conditioned reversal; the 5-day pairs rule.

## Data correction recorded this session

The all-symbol XNYS daily file DOES exist. TODO #104's inventory recorded it as
missing because it looked under the wrong parent folder. Real path:
`/home/openclaw/.openclaw/research-data/databento/opening-auctions/universe-selection/xnys-pillar_ohlcv-1d_ALL-SYMBOLS_2023-01-01_2026-08-22.dbn.zst`
(192 MB).

## Constraints

- No brokerage order placed, previewed or staged. No data bought. No production
  code, service, timer, score, Discord output or alert changed.
- Nothing built or turned on in this run — research only.
