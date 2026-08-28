# Find one share-trading rule that actually makes money, and ship it today

**Status:** DONE 2026-08-28 (NO PASS — no rule earned its costs)
**Created:** 2026-08-28

**CURRENT STATUS (2026-08-28):** **NO PASS.** All three rules failed. Every one
of them needed to earn 40 basis points a trade before costs (80 for a two-stock
pair) and they earned +1.0, −0.4 and +3.3. A basis point is one hundredth of one
percent.

The usual objection — "your trading costs were too harsh" — does not apply here.
Set the cost to **zero** and the three rules still earn +1.0, −0.4 and +3.3
against a bar of 20. There is nothing to buy at any price.

Nothing was built, nothing was turned on, production is unchanged, no money was
spent, and the 182 sealed days were never opened. An independent agent rebuilt
all three rules from the raw exchange files without touching the builder's code:
4,554 signals and 3,580 complete trades, all matched. A hostile reviewer tried
to break the result and concluded it stands.

Three real defects were found by those reviewers and fixed — the account's own
losses were choosing which trades it could afford, 24 funds were being traded as
if they were shares, and the cheap-stock cost floor was charged at half rate.
Every fix made the rules look worse.

Full write-up: `.omc/research/immediate-profitable-share-feature/FINAL-VERDICT.md`

## What this is

The owner does not want another research memo. Using only data already on this
machine, test exactly three share-trading rules, end to end, today:

1. **Same time of day continuation** — a stock that tends to move a certain way
   in, say, the 11:00-11:30 half hour keeps doing it. (Heston, Korajczyk and
   Sadka.)
2. **Yesterday's move plus yesterday's volume** — whether a move keeps going or
   snaps back depends on how heavy the trading was. (Llorente, Michaely, Saar
   and Wang.)
3. **Two near-identical companies drifting apart** — buy the laggard, short the
   leader, wait for them to close the gap. (Gatev, Goetzmann and Rouwenhorst.)

Everything is frozen in writing before any profit number is computed. If none of
the three clears every profit and risk gate, the answer is
`NO PASS` and nothing is turned on.

## Closed already — do not re-open

Opening-auction pressure (#93), early-session dislocation (#103), gap fade,
earnings timing, options-flow direction, stored volatility, social attention,
opening-range breakout, VWAP reclaim, sector rotation, and any option rule with
no historical bid and ask.

## Files

- Prompt: `.omc/plans/profitable-feature-today-execution-prompt.md`
- Work folder: `.omc/research/immediate-profitable-share-feature/`
- Research code: `scripts/research/ipsf_*.py`

## Follows

#93 (opening auction, no edge), #97 (six methods, all rejected), #100 (put-flow
options, insufficient data), #103 (intraday dislocation, no edge).


## What this closes, and what it does not

**Closed for good:** the same-half-hour repetition idea. Take the safety exit
away entirely and it is worth minus five hundredths of a basis point across
422,338 observations. Do not re-propose it.

**Closed:** the "big move on heavy volume snaps back" idea, in large US
companies, in these years.

**NOT closed:** pairs trading in general. What was tested closes the position
after five days and 95 of every 100 trades were still apart when the clock ran
out. Holding for seven weeks does capture a real convergence — about 24 basis
points at its best — but a pair costs 40 to trade, so it still does not pay.
Anyone re-proposing pairs must explain how they beat that 40.

**The limit that matters most:** both stock lists were chosen in August 2026, so
every company in them survived to 2026. That flatters buying-the-dip rules. It
makes this NO PASS safer, and it would have to be fixed before any future
result in the same universe could be believed the other way.
