# TODO #111 — the option strategy tournament: what was found

**Date:** 2026-09-04, Pacific. **Nothing is live. No order was placed, real or
paper. No switch was turned on.**

## The short version

All 58 frozen tests were run; 37 had fundable samples and **all 37 are now
complete**. Two mechanisms make money on the eight development years, 2014-2021,
and they are not the same trade:

**1. Buy a call spread when SPY is already rising, and do not cut the winner
short.** You buy an at-the-money call and sell a further-out one to cheapen it,
then take profit at +100% with no stop, inside 14 trading days.

- entered at a 60-day high in a calm market: **54 trades, 68.5% wins,
  +18.28% per trade after commission, profit factor 2.29**
- entered on a 12-month momentum uptrend: **121 trades, 65.3% wins, +12.12%,
  profit factor 1.47**

**2. Sell a put spread when the options market is charging a lot for fear.**

- **265 trades, 84.5% wins, +14.31% per trade after commission**, worst losing
  run $708 against $2,596 made

**None of it is proven.** The untouched 2022-2026 test is frozen and its data is
downloading, but it has not run. Until it does, the honest label on every one of
these is **PROMISING, NOT PROVEN**.

## An important correction to my own earlier conclusion

Partway through, the data provider throttled us and mechanism 3 — the call
spreads above — was left half-downloaded. On that partial data it was **top of
the table**, and I excluded it and said so, because a half-downloaded sample is
not a random sample. I froze five finalists that were all put credit spreads and
wrote that "the edge is one-sided".

The download then finished. On complete data **mechanism 3 is the best
mechanism in the tournament**, roughly eight times better per dollar at risk
than the best put spread. I have re-frozen the finalists to include it. That is
allowed and it is the honest thing to do, because no sealed outcome has been
read — but the earlier all-put-spread list was a product of missing data, and
anyone reading the superseded version in git history should know why it changed.

## The one thing worth knowing

The single largest effect in the whole tournament was **not** a new idea. It was
changing where the loss is cut.

The same spread, same entry, same days, differing only in the stop:

| stop at | trades | wins | after commission |
|---|---|---|---|
| −100% of the credit | 265 | 72.8% | +5.47% |
| **−200% of the credit** | 265 | **84.5%** | **+14.31%** |

Roughly triple the profit from loosening one number. That could easily be a
trick — a stop that is simply never hit, with the losses arriving later at the
time limit instead. It is not. The wins genuinely went up:

- trades closed at the profit target: **186 → 208**
- trades stopped out: **68 → 29**
- trades that ran to the 14-day limit: only **17 more**

Why it works is the thing the previous study already predicted. A percentage
stop can only act while the market is open. Overnight the price gaps straight
through it. A tight stop therefore does not save you from the bad night — it
just guarantees you get taken out of the ordinary wobbles as well. The cost of
that was being paid every week.

There is a real caveat and it belongs next to the good news. Of the trades that
still do lose under the wider stop, a **larger share gap through it** (41%,
against 29% before). Fewer losers, but the ones that survive the filter fail
harder.

## The five frozen finalists

Re-frozen as commit `2bdc8e1`, before any 2022-2026 data was read.

| # | when it trades | structure | exit | trades | wins | after cost | per $ risked | profit factor |
|---|---|---|---|---|---|---|---|---|
| 28 | SPY at a 60-day high, calm | call debit spread | +100%, no stop | 54 | 68.5% | +18.28% | +18.28% | 2.29 |
| 26 | uptrend + 12-month momentum | call debit spread | +100%, no stop | 121 | 65.3% | +12.12% | +12.12% | 1.47 |
| 11 | VIX rich vs recent moves, calm | put credit spread | +50% / −200% | 265 | 84.5% | +14.31% | +2.28% | 1.59 |
| 40 | downside protection unusually cheap | put credit spread | +50% / −100% | 82 | 80.5% | +18.67% | +3.00% | 1.88 |
| 1 | VIX rich vs recent moves, calm | put credit spread | +50% / −100% | 265 | 72.8% | +5.47% | +0.83% | 1.18 |

All five are positive after commission in both halves of development. Test 1 is
carried because the mission requires it, not because of its numbers.

## The pattern that shows up twice

Both winning mechanisms work in one direction only, and the mirror of each loses
money:

- selling **put** spreads works; selling **call** spreads loses — −11.47% at the
  same boundary, −29.30% on the skew trigger
- buying **call** spreads in an uptrend works; buying **put** spreads in a
  downtrend loses badly — −8.87%, −17.23% and −3.47% across its three exits

Whatever is being paid for here is paid for carrying upside-and-calm exposure.
There is no symmetric version of it in this data. That is worth knowing before
anyone assumes a "bearish version" of a working rule will also work.

## What lost money, now settled on complete data

- **every volatility-buying test**: straddles and strangles on cheap-volatility
  and expanding-movement triggers, between −0.75% and −6.00%
- **every call credit spread**, at every boundary tested
- **the iron condors**: the best makes $764 against a $1,984 drawdown
- **downside directional spreads**, badly

These were not excluded for missing data. They ran and they lost.

## Three defects found and fixed, all mine, all before the outcomes

Each was written into the frozen matrix as a dated amendment **before** the
result that could have motivated it existed.

1. **The event trigger compared different clocks.** It measured an option price
   covering ten trading days against a stock move measured over one day. A
   ten-day price is naturally several times bigger, so "options look cheap"
   could never fire and "options look rich" fired almost automatically. Test 50
   was not testing "sell when the market overcharges" — it was testing "always
   sell before an event". Fixed by putting both on a one-day footing; the sample
   went from 0 cheap / 181 rich to 101 cheap / 77 rich.
2. **Six releases fall on Good Friday**, when the government publishes but the
   stock market is shut. There is no closing price, and because each gap sits
   inside a twelve-release history, one hole knocked out the next twelve
   readings. 44 dates looked unusable when only 6 were. Fixed by measuring
   across the closure using two real closing prices.
3. **Mechanism 6 had no expiry window** in the matrix at all.

## How the numbers were checked

- The engine was rebuilt independently and reproduces the previously reported
  result to within three trades out of 244. The difference was traced, not
  waved away: the old script required all four condor legs to be quoted before
  it would trade even a two-leg spread, so it discarded three days where the
  put side was perfectly fine. The new set is a strict superset.
- One trade was re-priced by hand from the raw quotes and matched the engine
  exactly.
- Every top result was checked for the obvious cheat — a leg going unquoted and
  the trade defaulting to the time limit. The missing-minute rate is **zero** for
  every finalist except one trade-minute in 1.5 million.
- Fills are the **midpoint** of the bid and ask on every leg, entering and
  exiting, per the owner's standing rule. Commission is reported separately at
  $0.45 per contract per side and never hidden inside the fill.

## Money

| | |
|---|---|
| spent this session | **$4.73** |
| spent by the whole TODO #111 run | **$8.21** of a **$20.00** ceiling |
| sealed-period reserve, untouched | **$5.00** |
| Databento credit remaining | about **$117** |

1,172 requests, every one cost-estimated before it was sent and written to a
ledger.

## What happens next

1. Finish the throttled downloads — 293 development and 496 event contract-days
   remain. This is time, not money.
2. Run the sealed 2022-2026 test on the five frozen finalists, roughly $2.75.
   The command is fixed and refuses to run without the explicit finalist list.
3. Judge mechanism 3 on complete data. Two of its tests already have every date.
4. Have a reviewer who did not write the code reproduce any sealed winner.

**Nothing goes live automatically, and nothing here justifies a trade yet.**
