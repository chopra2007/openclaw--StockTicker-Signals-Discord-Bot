# TODO #111 — option strategy tournament: the frozen matrix

**Frozen:** 2026-09-03 (Pacific), before any new option outcome was read.
**Author:** the Opus orchestrator. Nothing below may change once the first new
exit price is looked at. Amendments, if any, get their own dated section at the
bottom and must be written before the outcome that would motivate them.

58 complete tests across 7 profit mechanisms. Every test is a full rule: a
trigger, a structure, an expiry, strikes, an exit, and a period. A different
strike or stop inside one mechanism is a **variant**, not a new mechanism.

---

## 0. Rules that apply to every test

### 0.1 Underlying and data

- Underlying: **SPY** only.
- Option quotes: Databento `OPRA.PILLAR`, schema `cbbo-1m` — the minute
  national best bid and offer. No trade bars are ever substituted for quotes.
- Daily SPY prices: `data/mmhl_daily/SPY.json`.
- Daily VIX: `research-data/todo-111-condor/vix_daily.json`.
- No quote is ever invented. A missing minute is skipped and counted.

### 0.2 The master date grid

One candidate entry per ISO week: the **Wednesday** signal session, else
Tuesday, else Thursday, taken from the sessions that have a complete free
signal. Counts, already computed and fixed:

| period | role | weeks |
|---|---|---|
| 2014-01-01 – 2018-12-31 | discovery | 260 |
| 2019-01-01 – 2021-12-31 | confirmation | 158 |
| 2014-01-01 – 2021-12-31 | **development** (the two above) | **418** |
| 2022-01-01 – 2026-08-31 | **sealed** | **242** |

Mechanism 5 (scheduled events) adds its own dates outside this grid; every
other mechanism only ever *subsets* the grid.

The sealed period stays shut until every finalist is frozen.

### 0.3 Entry

- **Time:** 10:00 America/New_York on the session **after** the signal session
  D. (7:00 a.m. Pacific.)
- Every trigger input is measured at or before the close of D. Nothing from the
  entry session or later ever enters a trigger.
- The entry minute must be complete: every leg of the structure must have a
  `cbbo-1m` record stamped exactly at 10:00 exchange time. No nearby minute is
  substituted. Otherwise the week is skipped and counted as a skip.

### 0.4 Expiry and strike reference

Read from the one-minute snapshot of the **whole SPY chain** at the entry
minute, and from nothing else:

- **Expiry E** — among listed expiries in the mechanism's day window, the one
  with the **most quoted strikes** at that minute; ties go to the expiry
  closest to the window's target. Day windows: 30–45 days (target 37) for
  mechanisms 1, 2, 3, 4; 5–20 days (target 10) for mechanism 5; near 7–20
  (target 14) and far 45–75 (target 60) for mechanism 7.
- A strike counts as **listed** when the snapshot quotes it with `ask > 0`. A
  0.00 bid is a real quote and is used as it stands.
- **Spot S** — the put-call parity spot: take the strike `k*` whose call and put
  mids are closest together, then `S = k* + mid(call) - mid(put)`.
- **ATM strike** — the listed strike nearest S.
- **Expected move EM** — `mid(ATM call) + mid(ATM put)` on E.
- **Boundary m** — a strike distance measured in expected moves.
  `lower(m) = S - m*EM`, `upper(m) = S + m*EM`.
  Short put at boundary m = the highest listed put strike at or below
  `lower(m)`. Short call at boundary m = the lowest listed call strike at or
  above `upper(m)`.
- **Wing width** is **$5** everywhere: long put = short put − 5, long call =
  short call + 5. If a required strike is not listed on E, the week is skipped.
- `m = 1.0` reproduces the already-tested expected-move condor boundary.
  Roughly, over a 37-day expiry, `m = 0.6` ≈ a 30-delta strike, `m = 1.0` ≈ 16
  delta, `m = 1.4` ≈ 9 delta. Deltas are not modelled; the expected-move
  boundary is the frozen definition, because it needs no interest rate,
  dividend, or volatility assumption.

### 0.5 Liquidity gate at entry

Checked at the entry minute, on **every** leg of the structure:

- `bid > 0`, `ask > 0`, `bid_size >= 1`, `ask_size >= 1`;
- `(ask - bid) / mid <= 0.25`.

Any failure skips the week. The skip reason is recorded.

### 0.6 Fills and costs

- **Every buy and every sell, entry and exit, fills at the midpoint of the bid
  and ask.** This is the owner's standing rule and it overrides every earlier
  fill instruction in this project.
- **Commission is reported separately** and is never folded into the fill:
  **$0.45 per contract per side**. One option = $0.90 round trip; a two-leg
  spread = $1.80; a four-leg structure = $3.60. Commission is charged against
  a **one-contract-per-leg** position.
- Every row reports the gross return **and** the return after that commission.

### 0.7 Return definitions

For a **credit** structure with entry credit `C` (midpoint) and cost to close
`X` (midpoint):

- `return_on_credit = (C - X) / C`
- `max_risk = width - C` per spread (condor: the wider of its two sides, since
  only one side can finish in the money)
- `return_on_max_risk = (C - X) / max_risk`

For a **debit** structure with entry debit `D` and closing value `V`:

- `return_on_debit = (V - D) / D`
- `max_risk = D`, so `return_on_max_risk = (V - D) / D`

Commission-adjusted versions subtract the dollar commission from the numerator
before dividing. A trade is a **win** when its commission-adjusted dollar profit
is above zero.

### 0.8 Exit

- Walk every regular-session minute (09:30–16:00 exchange time) strictly after
  the entry minute in which **all** legs are quoted.
- The **first** minute at which the test's target or stop is touched ends the
  trade, at that minute's midpoint prices.
- **Hard cap: 14 trading days.** If neither is touched, the trade closes at the
  last complete quoted minute on or before the 14th trading day after entry, at
  midpoint prices. Some tests use a 7-day cap; that is stated in the row.
- Targets and stops are stated as a fraction of the entry credit (credit
  structures) or of the entry debit (debit structures), before commission.
- A minute in which any leg is unquoted is skipped, never filled in. The
  missing-minute rate is reported.

### 0.9 Named exit sets

| code | target | stop | cap |
|---|---|---|---|
| X1 | +50% of credit | −100% of credit | 14 trading days |
| X2 | +25% of credit | −100% of credit | 14 trading days |
| X3 | +50% of credit | −200% of credit | 14 trading days |
| X4 | +50% of credit | −100% of credit | 7 trading days |
| Y1 | +50% of debit | −50% of debit | 14 trading days |
| Y2 | +100% of debit | −50% of debit | 14 trading days |
| Y3 | +100% of debit | no stop | 14 trading days |
| Y4 | +50% of debit | −50% of debit | 7 trading days |

### 0.10 Named triggers (all free, all known before entry)

Measured at the close of signal session D.

- `implied = VIX(D)/100`
- `realised = stdev(last 20 daily SPY log returns through D) * sqrt(252)`
- `VRP = implied - realised`
- `ATR% = 14-day average true range / close, on D`
- `calm = ATR%(D) <= the 90th percentile of the trailing 500 sessions`

| code | condition |
|---|---|
| **V2** | `VRP >= 0.02` and `calm` — the already-frozen premium-selling signal |
| **V0** | `VRP >= 0.00` and `calm` — the same idea, wider sample |
| **C1** | `VRP <= 0.00` and `calm` — implied cheap against recent realised |
| **C2** | `ATR%(D) > ATR%(D-5)` and `ATR%(D)` in the top 25% of the trailing 250 sessions — movement is expanding |
| **C3** | compression break: the 20-session close range divided by close, measured through D−1, sits in the bottom 20% of its trailing 250 readings, **and** \|SPY return on D\| ≥ 1.5 × ATR%(D) |
| **U1** | uptrend + momentum: close > 50-day average, 20-day average > 50-day average, and the trailing 12-month total return is in the top third of its own trailing 5-year history |
| **U2** | close on D is the highest close of the last 60 sessions, and `ATR%(D)` is at or below its trailing 250-session median |
| **D1** | the exact mirror of U1 (below both averages, bottom third of 12-month return) |
| **D2** | close on D is the lowest close of the last 60 sessions |
| **S1** | skew rich: `skew_ratio = mid(short put at m=1.0) / mid(short call at m=1.0)` at the entry minute, in the **top 20%** of its own prior readings on this grid (expanding window, minimum 40 prior readings) |
| **S2** | skew cheap: the same ratio in the **bottom 20%** of its own prior readings |
| **E1** | event implied move is cheap: `implied_event_move / historical_event_move <= 0.90` |
| **E2** | event implied move is rich: the same ratio `>= 1.30` |
| **T1** | term structure inverted: near-expiry annualised straddle price ÷ far-expiry annualised straddle price, in the top 20% of its own prior readings |
| **T2** | the same ratio in the bottom 20% |

S1, S2, T1 and T2 are ranked against an **expanding** history of prior entries
only. No future reading ever enters a percentile.

### 0.11 Structures

| code | legs (one contract each) | credit or debit |
|---|---|---|
| PCS(m) | sell put at boundary m, buy put 5 lower | credit |
| CCS(m) | sell call at boundary m, buy call 5 higher | credit |
| IC(m) | PCS(m) + CCS(m) | credit |
| STRAD | buy ATM call + buy ATM put | debit |
| STRANG(m) | buy call at boundary m + buy put at boundary m | debit |
| CDS | buy ATM call, sell call at boundary 0.6 | debit |
| PDS | buy ATM put, sell put at boundary 0.6 | debit |
| RR+ | PCS(1.0) + CDS — defined-risk bullish risk reversal | net |
| RR− | CCS(1.0) + PDS — defined-risk bearish risk reversal | net |
| CAL | sell ATM straddle on the near expiry, buy ATM straddle on the far expiry | debit |
| CAL− | the reverse of CAL | net |

For a net structure (RR+, RR−, CAL−) the entry cash flow may be either sign;
returns are always taken against `max_risk`, and `return_on_credit` is reported
as not-applicable when the entry cash flow is a debit.

---

## 1. Mechanism 1 — managed option-premium selling (16 tests)

Expiry window 30–45 days. Wing $5.

| # | trigger | structure | exit | note |
|---|---|---|---|---|
| 1 | V2 | PCS(1.0) | X1 | **the pre-frozen candidate** — do not tune |
| 2 | V2 | PCS(0.6) | X1 | nearer-the-money variant |
| 3 | V2 | PCS(1.4) | X1 | further-out variant |
| 4 | V2 | CCS(1.0) | X1 | |
| 5 | V2 | CCS(0.6) | X1 | |
| 6 | V2 | CCS(1.4) | X1 | |
| 7 | V2 | IC(1.0) | X1 | the already-rejected condor, at midpoint fills and the new exit |
| 8 | V2 | IC(0.6) | X1 | |
| 9 | V2 | IC(1.4) | X1 | |
| 10 | V2 | PCS(1.0) | X2 | take profit earlier |
| 11 | V2 | PCS(1.0) | X3 | wider stop |
| 12 | V2 | PCS(1.0) | X4 | shorter cap |
| 13 | V2 | IC(1.0) | X2 | |
| 14 | V2 | IC(1.0) | X3 | |
| 15 | V2 | IC(1.0) | X4 | |
| 16 | V0 | PCS(1.0) | X1 | the candidate on a wider, less selective sample |

## 2. Mechanism 2 — cheap-volatility buying (8 tests)

Expiry window 30–45 days.

| # | trigger | structure | exit |
|---|---|---|---|
| 17 | C1 | STRAD | Y1 |
| 18 | C1 | STRANG(0.6) | Y1 |
| 19 | C2 | STRAD | Y1 |
| 20 | C2 | STRANG(0.6) | Y1 |
| 21 | C3 | STRAD | Y1 |
| 22 | C3 | STRANG(0.6) | Y1 |
| 23 | C1 | STRAD | Y2 |
| 24 | C3 | STRAD | Y2 |

## 3. Mechanism 3 — directional debit spreads (10 tests)

Expiry window 30–45 days. The short leg of every debit spread sits at
boundary 0.6.

| # | trigger | structure | exit |
|---|---|---|---|
| 25 | U1 | CDS | Y1 |
| 26 | U1 | CDS | Y3 |
| 27 | U2 | CDS | Y1 |
| 28 | U2 | CDS | Y3 |
| 29 | D1 | PDS | Y1 |
| 30 | D1 | PDS | Y3 |
| 31 | D2 | PDS | Y1 |
| 32 | D2 | PDS | Y3 |
| 33 | U1 | CDS | Y4 |
| 34 | D1 | PDS | Y4 |

Test 25 is the option expression of the long-horizon momentum signal that
previously worked on shares over three months. Its old three-month share result
proves nothing here and is not carried forward as evidence.

## 4. Mechanism 4 — skew and relative value (8 tests)

Expiry window 30–45 days. The skew reading is taken at the entry minute from
the chain snapshot, before any outcome.

| # | trigger | structure | exit |
|---|---|---|---|
| 35 | S1 | RR+ | X1 |
| 36 | S1 | PCS(1.0) | X1 |
| 37 | S1 | CCS(1.0) | X1 |
| 38 | S2 | RR− | X1 |
| 39 | S2 | CCS(1.0) | X1 |
| 40 | S2 | PCS(1.0) | X1 |
| 41 | S1 | RR+ | Y1 |
| 42 | S1 | RR+ | X4 |

## 5. Mechanism 5 — scheduled-event volatility (8 tests)

Dates come from published FOMC decision days, CPI release days and employment
("jobs report") release days, 2014–2026. Release dates are announced months
ahead, so using them is not future information; the **outcome** of a release
never enters a trigger.

- **Entry:** 10:00 exchange time on the last session **before** the release.
- **Expiry:** 5–20 days, target 10.
- **Exit:** the normal exit walk, capped at the close of the **second** session
  after the release or the exit set's cap, whichever is sooner.
- `implied_event_move = mid(ATM straddle) / S` at entry.
- `historical_event_move` = the median of `|close-to-close return|` on the
  release day itself, over that class's **previous 12** occurrences. Expanding
  window; the first 12 occurrences of each class are used to prime it and are
  not traded.

| # | event class | trigger | structure | exit |
|---|---|---|---|---|
| 43 | FOMC | E1 | STRAD | Y1 |
| 44 | FOMC | E2 | IC(1.0) | X1 |
| 45 | CPI | E1 | STRAD | Y1 |
| 46 | CPI | E2 | IC(1.0) | X1 |
| 47 | jobs report | E1 | STRAD | Y1 |
| 48 | jobs report | E2 | IC(1.0) | X1 |
| 49 | all three pooled | E1 | STRAD | Y1 |
| 50 | all three pooled | E2 | IC(1.0) | X1 |

Tests 49 and 50 pool the classes. The pooling reason and the timing rule are
frozen here, before any event outcome is read.

## 6. Mechanism 6 — external-information option trades (4 tests, feasibility-gated)

Reopens `todo/put-flow-option-trade-system.md`. **Gate, decided before any
outcome:** the tests run only if the exact morning shortlist can be
reconstructed for each historical date from records that existed that morning.
If it cannot, all four rows are recorded as `NOT TESTABLE` with the reason, and
no money is spent on them. The June–August 2026 sample is preliminary in any
case: it covers one market regime.

| # | selection | structure | exit |
|---|---|---|---|
| 51 | put-flow morning shortlist | buy ATM put | Y1 |
| 52 | put-flow morning shortlist | buy put at boundary 0.6 | Y1 |
| 53 | put-flow morning shortlist | PDS | Y1 |
| 54 | put-flow morning shortlist | buy ATM put | Y4 |

## 7. Mechanism 7 — calendar spreads (4 tests, optional lane)

Near expiry 7–20 days, far expiry 45–75 days, both ATM.

| # | trigger | structure | exit |
|---|---|---|---|
| 55 | T1 | CAL | Y1 |
| 56 | T2 | CAL− | Y1 |
| 57 | T1 | CAL | Y4 |
| 58 | T1 | CAL | hold to the near expiry, capped at 14 trading days |

---

## 8. What every row of the results table must contain

One machine-readable row per test, losers included, never omitted:

`test_id, mechanism, trigger, structure, expiry_window, strikes_rule,
exit_rule, data_dates, eligible_weeks, skipped_weeks, skip_reasons,
dev_trades, discovery_trades, confirmation_trades, sealed_trades,
win_rate, win_rate_ci_low, win_rate_ci_high, avg_gross_return,
median_gross_return, avg_return_after_commission, avg_return_on_credit_or_debit,
avg_return_on_max_risk, profit_factor, total_profit_usd, max_drawdown_usd,
max_simultaneous_risk_usd, best_trade, worst_trade, n_target_exits,
n_stop_exits, n_time_exits, n_overnight_gap_through_stop, yearly_results,
discovery_vs_confirmation, profit_share_best_trade, profit_share_best_5_trades,
profit_share_best_date, profit_share_best_year, entry_median_spread_pct,
entry_median_bid_size, entry_median_ask_size, databento_cost_usd, verdict`

Win-rate uncertainty is a Wilson 95% interval. Profit factor is gross winning
dollars ÷ gross losing dollars, after commission. Max drawdown is on the
running sum of commission-adjusted dollar profit, trades in date order. Max
simultaneous risk is the largest total `max_risk` open on any one day.

## 9. Cheap rejection rules (applied before any heavy check)

A test is rejected on the spot, with its numbers kept, when any of these is
true on **development**:

1. fewer than 30 development trades;
2. average commission-adjusted return at or below zero;
3. profit factor below 1.00;
4. the single best trade supplies more than 50% of all positive profit;
5. the single best calendar year supplies more than 80% of all positive profit;
6. discovery (2014–2018) and confirmation (2019–2021) disagree in sign.

## 10. Advancing to finalist

A test may be frozen as a finalist only when:

- it survives section 9;
- it is positive after commission in **both** discovery and confirmation;
- at least one neighbouring setting inside the same mechanism (a different
  boundary m, or a different exit set) is also positive after commission — one
  magic parameter is not a finalist;
- it has at least 30 development trades, and the sealed grid can supply at
  least 30 more.

**At most five finalists**, all frozen at once, before a single sealed outcome
is downloaded or read.

## 11. Verdict levels

- **REJECTED** — negative, or structurally incapable of reaching the goal.
- **PROMISING, NOT PROVEN** — positive screen, not enough independent history.
- **FINALIST** — cleared development and confirmation, frozen before sealed.
- **HISTORICAL WINNER** — at least 100 development and 100 sealed trades, at
  least 60% wins, at least +4% average gross return, positive after the stated
  commission, positive return on maximum risk, acceptable drawdown and
  concentration, and an independent Sonnet reproduction that did not write the
  code.

Ranking is by **commission-adjusted profit per dollar of maximum risk**, then
stability across time, then drawdown, then win rate. Never by win rate alone.

## 12. Money

- Already spent by this run: **$3.4836** of a **$20.00** hard ceiling.
- Development budget for this tournament: **$7.00** additional, hard.
- Sealed-period reserve for all finalists together: **$5.00**.
- Remainder: failure and retry buffer. Nothing may be sent that could push the
  total past $20.00.
- Measured unit costs from the existing ledger: **$0.0079** per whole-chain
  entry-minute snapshot (median), **$0.0009** per contract per date for the
  14-trading-day minute file.
- Every request is cost-estimated with the official estimator first and
  appended to `research-data/todo-111-tournament/spend_ledger.json` before the
  data is kept.
- Never download a full chain for a whole day. One entry-minute snapshot on a
  predeclared date, then only the named legs.

## 13. Data already owned, and therefore free

- 279 entry-minute whole-chain snapshots, 2014-01-03 to 2021-12-09, on the V2
  dates. These support strike selection, skew, term structure and expected
  move for every mechanism at $0.
- 246 four-leg minute files for the `m = 1.0` condor legs on those dates. These
  support tests 1, 4, 7, 10–15, 36, 37, 39 and 40 at $0.

---

## 14. Freeze record

- Machine-readable copy: `research-data/todo-111-tournament/frozen_matrix.json`,
  written by `scripts/research/todo_111_tourney_matrix.py`.
- `frozen_matrix.json` sha256:
  `a7aefb340cf21b437f5dab2c6c0572fbc7bf852689263399b559e0d4f717c4cd`
- This file was committed before any new option outcome was computed. The
  commit that adds it is the freeze timestamp.
