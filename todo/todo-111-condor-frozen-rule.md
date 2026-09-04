# TODO #111 — SPY expected-move iron condor: the frozen rule

**Frozen:** 2026-09-03 (Pacific), before any option outcome was read.
**Amended the same day, still before any outcome was read** — two selector
defects found while validating the first downloads: the 37-day target was
choosing thin weekly expiries that do not list a $5 wing, and a wing with a
0.00 bid was being treated as unlisted. Both are marked below. No trade return
had been computed when these were changed. Superseded hash:
`d560b8c3298e2b2c64df0f7f221142761d968c965f16d89ec44d5bba0607cf0f`.
Nothing below may change once the first exit price is looked at.

## What is being tested

One candidate — a SPY iron condor whose two short strikes sit just outside the
options-implied expected move — plus two smaller tests declared here in advance
so they cannot be picked afterwards:

- **T1** the whole four-leg condor
- **T2** the put credit spread alone (the two lower strikes)
- **T3** the call credit spread alone (the two upper strikes)

All three run on the same dates, the same strikes and the same fills.

## The signal (all inputs free, all known before entry)

Evaluated at the close of a signal session **D**:

- `implied  = VIX close on D / 100` — the 30-day options-implied move, annualised
- `realised = standard deviation of the last 20 daily SPY log returns x sqrt(252)`
- **`VRP = implied - realised`**, in annualised volatility points
- `ATR% = 14-day average true range of SPY on D, divided by the close`
- `calm  = ATR% is at or below the 90th percentile of the previous 500 sessions`

**Entry condition: `VRP >= 0.02` and `calm`.**

One entry per calendar week: the Wednesday session, else Tuesday, else Thursday.
0.02 was chosen only to make the sample large enough (279 development entries,
160 untouched) and was fixed before any option price was downloaded. The full
count table for every threshold from 0.00 to 0.06 is in the session report.

Code: `scripts/research/todo_111_condor_signal.py`. Dates:
`research-data/todo-111-condor/signal_dates.json`.

## The four legs (chosen from the entry-minute chain, nothing later)

At the entry minute a one-minute national-best-bid-and-offer snapshot of the
whole SPY chain is read. From that snapshot alone:

1. **Expiration E** — among the listed expiries 30 to 45 calendar days out, the
   one with the **most quoted strikes** at that minute; ties go to the expiry
   closest to 37 days. Depth, not the calendar, picks the expiry: the thin
   weeklies in that window do not list the strikes a condor needs.
2. **Spot S** — the mid of the at-the-money call and put is not used for spot;
   S is the SPY underlying price at that minute, taken from the strike whose
   call and put mids are closest together (the standard put-call parity strike).
3. **Expected move EM** — `mid(ATM call) + mid(ATM put)` on expiry E, where the
   ATM strike is the listed strike nearest S.
4. **Boundaries** — `lower = S - EM`, `upper = S + EM`.
5. **Short put** = highest listed strike at or below `lower`.
   **Long put**  = that strike minus 5.
   **Short call** = lowest listed strike at or above `upper`.
   **Long call**  = that strike plus 5.
6. A strike counts as listed when the snapshot quotes it with `ask > 0`; a
   0.00 bid is a real quote for a far wing and is kept. If any of the four
   strikes is not listed on E, the week is skipped.

## Entry

- **Time:** 10:00 exchange local time on the session after D (7:00 a.m. Pacific).
- **Liquidity check, at that minute, for each of the four legs:** bid > 0,
  ask > 0, bid size >= 1, ask size >= 1; and for each short leg
  `(ask - bid) / mid <= 0.25`. Any failure skips the week.
- **Fills, deliberately conservative:** short legs sold at the **bid**, long legs
  bought at the **ask**.
- **Credit** `C = bid(short put) + bid(short call) - ask(long put) - ask(long call)`.
  If `C <= 0` the week is skipped.

## Exit — the frozen TODO #111 option gate, unchanged

- Cost to close at any minute:
  `X = ask(short put) + ask(short call) - bid(long put) - bid(long call)`.
- Return at that minute: `R = (C - X) / C`.
- Walk every regular-session minute after entry. The **first** minute where
  `R >= +0.20` or `R <= -0.20` ends the trade at that minute's R.
- **Hard cap of 14 trading days.** If neither is touched, the trade closes at
  the last quoted minute of the 14th trading day, at the same conservative
  prices.
- A minute counts only when all four legs are quoted in it. Missing minutes are
  skipped, never filled in, and the missing-minute rate is reported.
- T2 and T3 use the same rule on their own two legs and their own credit.

## Pass or fail

The round-2 option bar, unchanged:

- at least **100 trades in development and 100 in the untouched period**
- win rate at least **60%**
- average return at least **+4.00%** a trade
- returns are **gross** — no commission, no slippage beyond the bid/ask already
  charged by the fill rule
- every trade closes inside 14 trading days by construction

## Periods

- **Development:** 2019-01-01 through 2021-12-31 signals — in full,
  2014-01-01 through 2021-12-31.
- **Untouched:** 2022-01-01 through 2026-08-31. Its option data is not
  downloaded or looked at until the development result is written down.

## Money

Databento OPRA.PILLAR, `cbbo-1m` at $2.00/GB and `definition` at $5.00/GB.
Hard ceiling **$20.00**. Every request is cost-estimated first and written to
`research-data/todo-111-condor/spend_ledger.json`.
