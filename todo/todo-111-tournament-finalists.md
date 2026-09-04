# TODO #111 tournament — the frozen finalists (REVISED)

**Revised and re-frozen:** 2026-09-04, Pacific, **before any sealed 2022-2026
outcome was downloaded or read.** The sealed window is still shut.

## Why this file was rewritten

An earlier version of this file, committed as `25faa1c`, froze five finalists
that were **all put credit spreads**. That list was made while the data provider
was throttling us and **mechanism 3 (directional call debit spreads) was still
half-downloaded** — more than half its dates missing. I excluded it then
precisely because a partial sample was topping the table and a half-downloaded
sample is not a random one.

The throttling then cleared and **the development data finished**. All 37 funded
tests are now complete; zero remain incomplete. Judged on complete data,
mechanism 3 is the best-performing mechanism in the tournament by the frozen
ranking rule.

Revising the list now is legitimate and is the honest thing to do: the sealed
period has not been opened, no sealed outcome exists, and the previous list was
built on an admitted data gap that has since closed. **This file supersedes the
one in `25faa1c`.** The old list is left in git history rather than deleted.

## The five

Ranked by commission-adjusted profit per dollar of maximum risk, which is the
frozen ranking rule.

| # | mechanism | when it trades | structure | exit | trades | wins | after cost | per $ risked | profit factor | worst drawdown vs total made |
|---|---|---|---|---|---|---|---|---|---|---|
| **28** | 3 | SPY at a 60-day high, market calm | buy at-the-money call, sell the 0.6x-expected-move call | +100%, **no stop**, 14 days | 54 | 68.5% | **+18.28%** | **+18.28%** | **2.29** | $962 vs $3,030 |
| **26** | 3 | uptrend + 12-month momentum in its own top third | same call spread | +100%, no stop, 14 days | 121 | 65.3% | +12.12% | +12.12% | 1.47 | $2,434 vs $4,083 |
| **11** | 1 | VIX high against SPY's own recent movement, calm | put credit spread at 1.0x expected move, $5 wide | +50% / **−200%** / 14 days | 265 | **84.5%** | +14.31% | +2.28% | 1.59 | $708 vs $2,596 |
| **40** | 4 | downside protection unusually cheap vs its own history | same put spread | +50% / −100% / 14 days | 82 | 80.5% | +18.67% | +3.00% | **1.88** | **$362 vs $1,057** |
| **1** | 1 | VIX high against recent movement, calm | same put spread | +50% / −100% / 14 days | 265 | 72.8% | +5.47% | +0.83% | 1.18 | $668 vs $951 |

Every one is positive after commission in **both** halves of development:

| # | discovery 2014-2018 | confirmation 2019-2021 |
|---|---|---|
| 28 | 30 trades, +9.67% | 24 trades, +29.03% |
| 26 | 51 trades, +13.23% | 70 trades, +11.30% |
| 11 | 155 trades, +10.67% | 110 trades, +19.44% |
| 40 | 55 trades, +20.95% | 27 trades, +14.03% |
| 1 | 155 trades, +5.92% | 110 trades, +4.85% |

## Why each one

- **28 and 26 are the same idea at two strengths** and they support each other:
  buy a call spread when SPY is already going up, and do not cut the winner
  short. Their neighbours are positive too — test 27 (same trigger, tighter
  exit) at +7.06%, tests 25 and 33 at +4.77% and +3.42% — so this is not one
  magic parameter. Test 28 has the smaller sample at 54 trades and the bigger
  per-trade number; test 26 has 121 trades and is steadier.
- **11 is the largest reliable sample in the tournament**, 265 trades, and it is
  the single biggest *effect* found: the same trade as test 1 with the stop
  widened from −100% to −200% of the credit, which roughly triples the profit.
- **40 has the best risk shape of the five** — profit factor 1.88 and a worst
  drawdown of $362 against $1,057 made — and it is the only rule that fires for
  a completely different reason: that downside protection has become cheap.
- **1 is carried because the mission requires it.** It is the version that
  looked promising before this tournament and its only honest test is the sealed
  period. It is the weakest of the five and was not chosen on its numbers.

## What changed from the superseded list

Dropped: **10** and **16**. Both are close variants of test 1 and both survive as
PROMISING, NOT PROVEN, but with mechanism 3 now eligible they no longer earn a
scarce sealed slot. Added: **26** and **28**.

## The one-sided pattern, now confirmed twice

Both winning mechanisms only work in one direction, and the mirror of each
loses money:

- selling **put** spreads works; selling **call** spreads loses (−11.47% at the
  1.0x boundary, −29.30% on the skew trigger)
- buying **call** spreads in an uptrend works; buying **put** spreads in a
  downtrend loses badly (−8.87%, −17.23%, −3.47% across its three exits)

Whatever is being paid for here, it is paid for carrying **upside-and-calm**
exposure. There is no symmetric version of it in this data.

## Also worth stating plainly

Every **volatility-buying** test lost money once complete: straddles and
strangles on cheap-volatility and expanding-movement triggers came in between
−0.75% and −6.00%. The iron condors are weak; the best makes $764 against a
$1,984 drawdown. Those are now settled on complete data, not on a gap.

## The sealed test

All five run together on 2022-01-01 to 2026-08-31 on the same weekly grid, same
midpoint fills, same $0.45 per contract per side. Test 40's skew percentile
needs a chain reading at every grid date, so the full 242-week sealed grid is
required — those snapshots are downloading now and are structural only (they say
where the strikes are; they contain no trade outcome).

The sealed evaluation may only be run by

```
python3 scripts/research/todo_111_tourney_sealed.py evaluate 1 11 26 28 40
```

which refuses to run without an explicit finalist list and stamps that list and
a timestamp into its output before it opens a single leg file.

## Sealed sample sizes — known before the test runs

From `selection_sealed.json`, built before any sealed outcome was read:

| # | sealed dates its trigger fires on |
|---|---|
| 1 | 160 |
| 11 | 160 |
| 26 | 58 |
| 28 | 32 |
| 40 | resolves once the chain snapshots land |

This is stated in advance because it caps what the sealed test can prove.
**HISTORICAL WINNER needs at least 100 sealed trades.** Only tests 1 and 11 can
reach that bar. Tests 26 and 28 — the best-performing mechanism on development —
**cannot become historical winners in this run whatever they return**, because
the trigger simply does not fire often enough in 2022-2026. Test 28 in
particular has 32 sealed dates against a 30 floor, so a handful of skips would
put it under.

That is a limit of the sample, not a verdict. If the call spreads come through
the sealed period positive, the honest label stays **PROMISING, NOT PROVEN** and
the right next step is more history — the grid could be widened beyond one entry
per week — rather than a claim the data cannot support.
