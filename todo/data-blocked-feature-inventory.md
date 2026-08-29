# Keep every data-blocked feature ready for a future test

**Status:** ONGOING
**Created:** 2026-08-29

**CURRENT STATUS (2026-08-29):** Audited the full TODO list. Six coded features
still lack enough market evidence for a trustworthy decision. Three more ideas
were researched or fully specified but correctly stopped before coding because the
required history does not exist here. Keep them here until free forward
collection becomes sufficient or the owner chooses a paid historical source.
Do not call any item below a proven trading edge.

## Coded features waiting on more market evidence

### 1. Wolf confluence timing gate — TODO #20

- **What exists:** The gate is coded and records when at least two independent
  source groups agree, with one fast-moving source. Collection is on; changing
  live alert levels is off.
- **What is missing:** The original replay had only 6 paired examples. Its
  locked minimum is 10, using saved 5-day and 20-day outcomes.
- **Free route:** Keep `wolf.confluence.timing.collect` on and rerun
  `scripts/wolf_timing_backtest.py` when the paired count reaches 10.

### 2. Analyst accuracy promotion — TODO #55, supported by #61 and #62

- **What exists:** The analyst scorecard, nightly grading, Discord display,
  readiness check, and automatic re-test are built. The live scoring table is
  intentionally empty, so the result cannot change an alert yet.
- **What is missing:** At the last recorded decision, no analyst cleared the
  locked confidence bar at the horizon the scoring code uses. The loggers keep
  adding graded calls.
- **Free route:** Keep the current outcome loggers running. Revisit only when at
  least one analyst's lower confidence bound is above 50% at the chosen
  horizon. Do not promote merely because time passed.

### 3. Unusual-options-flow predictive value — TODO #56, live feature from #57

- **What exists:** The unusual-flow alert is live, and the project stores flow
  events plus later stock outcomes. The historical replay program is not built.
- **What is missing:** No owned two-year options history can show whether the
  original volume/open-interest and premium rule predicted later moves across
  different market periods.
- **Free route:** Let the existing forward `options_flow` and 5-day/20-day
  outcome records mature, then build the replay from those owned records.
- **Paid route:** A historical options dataset can answer sooner, but price the
  exact fields first. Trade volume alone cannot prove option profit.

### 4. NFCI score multiplier — TODO #67

- **What exists:** NFCI is fetched, cached, shown in plain language, and its
  score multiplier is coded but off.
- **What is missing:** Old candidate records lack the exact cutoff, full score
  inputs and weights, and the point-in-time NFCI value/date needed to reproduce
  a before-and-after decision.
- **Free route:** First add those missing fields to every new candidate. Then
  collect at least 12 weekly NFCI readings and 100 candidates within five
  points of the cutoff before deciding whether the multiplier helps.

### 5. Options-flow buy/sell-side direction — TODO #80

- **What exists:** BUY, SELL, AMBIGUOUS, and SWEEP labels are live. Bid and ask
  are stored for new flow rows, and the grading program exists.
- **What is missing:** The latest recorded test had 78 disagreement cases. The
  side-aware direction was right 57.7%, but that was not strong enough to rule
  out luck. The locked next check is 165 cases.
- **Free route:** Keep collecting live bid/ask flow rows and rerun
  `scripts/grade_options_flow_side.py --report` at 165 disagreement cases.

### 6. Morning PUT option trade — TODO #100

- **What exists:** The frozen contract selector and observer-only monitor are
  built, tested, and scheduled. The monitor starts at 6:30 a.m. Pacific on
  trading days and saves real bid and ask each minute. The owner-only option
  card remains off.
- **What is missing:** The historical sample has no usable entry/exit quotes.
  The locked test needs 100 trades over 30 signal dates, then 40 more untouched
  trades. The live monitor had produced only 2 eligible option trades from its
  first 6 stock positions.
- **Free route:** Keep the current monitor running; the prior estimate was about
  five months at one eligible option trade per day.
- **Faster route:** A fresh Databento account may cover the narrow pull with its
  signup credit. The known paid fallback is one month of ThetaData at $40.
  Recheck current price and exact coverage before spending.

## Research-ready ideas stopped before coding

These are saved because the research work is reusable, but they are not built
features. They must never be reported as coded or working.

### 7. Paid option-surface market top/bottom predictor — TODO #47

- The free daily-data predictor was tested thoroughly and rejected. Do not
  revive it under a new name.
- A different, richer option-surface test was designed but not built. It needs
  historical implied-volatility, skew, gamma, and downside-risk data. The
  earlier estimate was about $50 for one month of Alpha Vantage premium.
- `vol-collect-daily.timer` is currently active and keeps the free forward path
  alive. A future test must remain a new paid-data experiment, not a claim that
  the rejected free predictor was merely short on samples.

### 8. Defined-risk credit-spread methods — TODO #106

- The share methods were tested and rejected. Do not retest or rename them.
- The separate credit-spread track was not testable. A trustworthy result needs
  synchronized bid, ask, and size for both legs at entry and exit. The project
  had only 3 trading days across 11 companies; the gate needs 250 spreads over
  100 days.
- The cheapest recorded source was ThetaData at $40 for one month. A free
  self-owned route would require saving synchronized full-chain snapshots at
  the planned entry and exit times during open market hours. The current PUT
  monitor covers selected contracts, not the full credit-spread test.

### 9. Schedule 13D follower owner card — TODO #107

- The filing rule, timing policy, costs, and pass/fail checks are frozen. No
  returns were calculated and no feature was built.
- A trustworthy historical test needs point-in-time common-share/listing
  history, company actions, delistings and cash outcomes, full-universe opening
  prices that were actually tradable, and measured filing-delivery timing.
- A free forward route can start daily security-definition, company-action,
  filing-arrival, and opening-quote snapshots now. That will test future filings
  but cannot repair missing old records. A paid source must be checked for all
  fields together; a price file alone is not enough.

## Explicit exclusions from this holding list

- TODO #47's free-data top/bottom rules: tested and rejected.
- TODO #93, #97, #103, #104, and the share side of #106: tested and rejected.
- TODO #96's stock portfolio: it failed its harsh borrow-cost gate; that is a
  measured result, not a missing-data result.
- Planned but uncoded menu ideas such as analyst target disagreement, flow
  hedge discounts, and learned weights: not included because no feature or
  frozen test is ready yet.

## Rules for reopening an item

1. Check how much usable data is stored now; do not rely on the old row count.
2. Confirm every required field and timestamp exists before paying or testing.
3. Get a free cost quote or trial first. Never buy data automatically.
4. Freeze the test before reading profit results.
5. Keep stock-return evidence separate from option-profit evidence.
6. If self-collecting during open market hours, store raw bid, ask, size,
   contract/security identity, and the exact capture time in Pacific time.
