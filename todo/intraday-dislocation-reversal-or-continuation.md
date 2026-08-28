# Test whether a big early-morning stock move snaps back or keeps going

**Status:** DONE (rejected direction)
**Created:** 2026-08-28

**CURRENT STATUS (2026-08-28):** REJECTED — all six rules failed. A rule needed
to earn 40 basis points on the average trade before costs; the best earned 5.09.
Every rule lost money after costs, in all five time blocks. Nothing was turned
on, production is unchanged, no money was spent, and the 182 sealed dates were
never opened. An independent check rebuilt 100 signals and 60 complete trades
from the raw exchange files with zero mismatches, so this is not a machinery bug.
Full write-up: `.omc/research/intraday-dislocation/FINAL-VERDICT.md`.

The reason in one line: after an extreme move, these 60 stocks behave almost
exactly like ordinary ones over the next half hour. The one effect above noise is
a 6 basis point drift down after a big rise — smaller than the 10 basis points by
which our two price feeds disagree about the same move, and under a third of what
it costs to trade.

**Next avenue, ranked first of three:** stop testing 20-to-60-minute holds. All
nine mechanisms rejected across #93, #96, #97, #100 and #103 tried to predict a
move that size, where a 20 basis point cost eats half the raw material. Holding
for days instead of minutes costs nothing extra to test — the daily price data is
free and already used here — and makes the cost hurdle roughly ten times easier.
The other two avenues are in the final verdict.

**The owner's broader goal — a repeatable automated trade that makes money after
costs — remains unmet.**

## The goal

The owner wants a repeatable, automated, short-duration share trade that still
makes money after real trading costs. This item tests one new idea only:

> After the regular market opens, some liquid stock moves abnormally far
> compared with the other 59 stocks in our data. Is the next tradeable move a
> snap-back (reversal), a continuation, or neither?

Version one is shares only. No options — we have no dated option bid/ask
history to prove an option trade (see #100).

## What is being tested

Six rules, frozen before any profit number is read:

1. Buy after an extreme downward move (direct reversal).
2. Short after an extreme upward move (direct reversal).
3. Buy after an extreme downward move, but only once it stops making new lows.
4. Short after an extreme upward move, but only once it stops making new highs.
5. Short after an extreme downward move (continuation).
6. Buy after an extreme upward move (continuation).

## Data

Local paid Databento files only, no new spend:
`/home/openclaw/.openclaw/research-data/databento/opening-auctions/selected60_2023-01_to_2026-08`

60 liquid NYSE names, one-minute bars, 2023-03-28 to 2026-08-22. There is no
SPY or sector ETF in the files, so the "market" is an equal-weighted average of
the 60 names computed from the same minutes.

Important honesty limit: the 60 names were chosen using liquidity rankings from
sessions ending 2026-08-21. So the last 182 dates are *profit-sealed* (their
strategy profits were never read) but not fully untouched.

## Related work — do not reopen or retune any of these

- #93 opening-auction pressure — REJECTED, no edge.
- #96 extreme PUT-flow morning shortlist — soaking.
- #97 six trade methods — all rejected.
- #100 PUT-flow option trade — insufficient data.
- #101 make builders prove their tests match the goal.

## Files

- Prompt: `.omc/plans/profitable-intraday-dislocation-feature-prompt.md`
- Research folder: `.omc/research/intraday-dislocation/`
- Research code: `scripts/research/intraday_dislocation_*.py`

## Open questions

- Does cross-sectional reversal survive a 20 bps round-trip cost in 2023-2026
  large-cap NYSE names? Prior literature says the raw effect is partly bid-ask
  bounce, which a trader cannot capture.
