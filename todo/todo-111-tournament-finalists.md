# TODO #111 tournament — the frozen finalists

**Frozen:** 2026-09-04, Pacific. **No sealed 2022-2026 option data has been
downloaded or read at the time of writing.** The sealed download is queued and
will run after this file exists. Nothing below may change once a sealed outcome
is looked at.

Chosen by the Opus orchestrator from `results_dev.json`, against the rules in
sections 9, 10 and 11 of the frozen matrix. Five is the maximum the matrix
allows and five are taken.

## The five

| # | trigger | structure | exit | dev trades | win rate | after commission | per $ of max risk | profit factor | max drawdown vs total profit |
|---|---|---|---|---|---|---|---|---|---|
| **11** | VRP>=0.02 + calm | put credit spread at 1.0x expected move, $5 wide | +50% / **-200%** / 14 days | 265 | 84.5% | **+14.31%** | +2.28% | 1.59 | $708 vs $2,596 |
| **40** | put/call skew in the cheapest 20% of its own history | same spread | +50% / -100% / 14 days | 82 | 80.5% | **+18.67%** | +3.00% | 1.88 | $362 vs $1,057 |
| **16** | VRP>=0.00 + calm | same spread | +50% / -100% / 14 days | 310 | 74.2% | +7.27% | +1.09% | 1.25 | $516 vs $1,457 |
| **1** | VRP>=0.02 + calm | same spread | +50% / -100% / 14 days | 265 | 72.8% | +5.47% | +0.83% | 1.18 | $668 vs $951 |
| **10** | VRP>=0.02 + calm | same spread | **+25%** / -100% / 14 days | 265 | 84.9% | +4.98% | +0.72% | 1.29 | **$352 vs $828** |

Every one is positive after commission in **both** halves of development:

| # | discovery 2014-2018 | confirmation 2019-2021 |
|---|---|---|
| 11 | 155 trades, +10.67% | 110 trades, +19.44% |
| 40 | 55 trades, +20.95% | 27 trades, +14.03% |
| 16 | 185 trades, +9.36% | 125 trades, +4.18% |
| 1 | 155 trades, +5.92% | 110 trades, +4.85% |
| 10 | 155 trades, +3.18% | 110 trades, +7.52% |

## Why these five and not others

- **Test 1 is carried because the plan requires it.** It is the version that was
  already identified as promising before this tournament started, and its only
  honest test is the sealed period. It is not the best of the five and was not
  chosen for its numbers.
- **Test 11 is test 1 with one change**: the stop widened from -100% to -200% of
  the credit. That single change is the largest effect found anywhere in the
  tournament. It is not a case of losses being deferred rather than avoided:
  target hits rose from 186 to 208 while only 17 more trades reached the time
  cap, and stop-outs fell from 68 to 29. Tests 10 and 12 are its neighbours and
  are also positive, so it is not one magic parameter.
- **Test 40 is the only genuinely different reason for the trade.** It fires when
  downside protection is unusually cheap against its own history, not when
  volatility is expensive. Its sample is the smallest at 82 trades and it can at
  best come out PROMISING, NOT PROVEN.
- **Test 16 tests whether the volatility filter earns its keep.** Same spread and
  exit as test 1 on a looser entry, 310 trades instead of 265.
- **Test 14, the iron condor, was dropped despite ranking fourth.** Its worst
  drawdown, $1,984, is larger than the $764 it made in total. Its `X1` sibling
  (test 7) is outright negative in confirmation. The condor family is weak and
  including it would spend a sealed slot on a structure the development data
  already argues against.

## The uncomfortable fact about this set

**All five are put credit spreads.** That is not diversification and it is not
what a portfolio is supposed to look like. It is what the evidence supports:
every call credit spread tested loses money (test 4 at -11.75%, test 39 at
-29.30%), the condors are weak, and the buying mechanisms were either rejected
or never got their data. The edge found here is one-sided — it is paid for
taking downside risk in a calm market, and the mirror image of it does not pay.
The sealed test will say whether even that survives.

## What is NOT in this set, and why

- **Mechanism 3 (directional debit spreads) is unfinished, not rejected.** Its
  data download was throttled by the provider part-way through; more than half
  its dates are missing. An early partial reading put it at the top of the
  table, which is exactly why it is excluded — a half-downloaded sample is not
  a random sample. It must be completed and judged on its own.
- **Mechanism 5 (scheduled events) is selected but unpriced.** Its triggers,
  dates and structures are computed and frozen; only the minute data is missing.
- **Mechanism 2 (cheap-volatility buying) is partly complete and losing.** Every
  variant with data is negative.
- **Mechanism 6 (put-flow) passed its selection gate** but its data was not
  bought before the throttling hit.

## The sealed test

All five run together on 2022-01-01 to 2026-08-31, one entry per ISO week, same
grid, same midpoint fills, same $0.45 per contract per side. `test 40`'s skew
percentile needs a chain reading at every grid date, so the full 242-week sealed
grid is required. Estimated cost about $2.75 of the $5.00 reserve; the run has
spent $8.19 of its $20.00 ceiling.

The sealed evaluation may only be run by
`scripts/research/todo_111_tourney_sealed.py evaluate 1 10 11 16 40`, which
refuses to run without an explicit finalist list and stamps that list and a
timestamp into its output before it opens a single leg file.
