# TODO #111 round 3 - rejection ledger, session of 2026-09-03

Ten entry rules, six genuinely different mechanisms, measured on development
data only - everything before 2025-07-01. Sixty NYSE large caps, one-minute bars,
EQUS.MINI feed. Every trade closes on the first touch of +1.0% in its favour or
-0.5% against it, capped at 14 trading days. Returns are gross.

**The bar is 60 in 100. Nothing here reached 36.**

New in round 3: each idea is scored against a **matched** baseline that trades
at the same time of day with no trigger at all. Round 2 used one baseline for
everything, and the odds of this bracket are not the same at 09:45 as at 15:30.

| Idea | Mechanism | Trades | Target first | vs its own baseline | Average per trade | Verdict |
|---|---|---|---|---|---|---|
| *(no trigger at all - one trade a day at 11:30, direction alternating)* | *the yardstick* | 32,190 | **34.00%** | - | -0.0179% | the yardstick |
| *(no trigger at all - one trade a day at 11:00, direction alternating)* | *the yardstick* | 32,860 | **34.77%** | - | -0.0033% | the yardstick |
| First break of the first fifteen minutes' range, with the break | the opening range (owner-named) | 32,010 | **34.08%** | +0.08 points | -0.0050% | rejected |
| First break of the first fifteen minutes' range, faded | the opening range (owner-named) | 32,010 | **33.41%** | -0.60 points | -0.0169% | rejected |
| First break of the overnight range, with the break | the overnight range (owner-named) | 15,073 | **34.23%** | +0.23 points | +0.0049% | rejected |
| First break of the overnight range, faded | the overnight range (owner-named) | 15,073 | **33.72%** | -0.28 points | -0.0062% | rejected |
| Opening-range break **and** the other 59 agree | two conditions that must agree | 18,135 | **34.63%** | +0.63 points | +0.0049% | rejected |
| Opening-range break, only on unusually wide mornings | the character of the day | 5,692 | **34.35%** | +0.34 points | +0.0004% | rejected |
| At 11:00, buy what has climbed all morning | the time of day as the condition | 18,166 | **35.94%** | +1.17 points | +0.0168% | rejected |
| On a day going nowhere, fade its high and its low | the character of the day | 5,971 | **33.36%** | -1.41 points | -0.0396% | rejected |
| At 11:00, buy the 6 strongest of 60, short the 6 weakest | the name's place among all sixty | 6,624 | **34.19%** | -0.58 points | -0.0075% | rejected |
| At 11:00, short the 6 strongest of 60, buy the 6 weakest | the name's place among all sixty | 6,624 | **33.95%** | -0.82 points | -0.0055% | rejected |

The best of the ten was **At 11:00, buy what has climbed all morning** at 35.94%, which is +1.17 points away from
doing nothing at the same time of day. The bar is **24 points above it**.

## The ceiling test - the result that settles it

Seven mechanisms landing on the baseline raises a fair question: is the next
mechanism worth building? So the friendliest possible test was run, one no
trigger could ever beat, because it is allowed to cheat with hindsight.

Forget triggers entirely. Split the development data in half at 2024-05-01. In the
first half, look up which combinations of *stock, hour of the day and direction*
reached the target first most often - 20 of them, out of 708 that had enough
history to judge. Then trade exactly those, unchanged, in the second half.

| | Trades | Target first |
|---|---|---|
| First half, everything | 188,792 | 34.42% |
| First half, the 20 cherry-picked | | **44.11%** |
| Second half, everything | 190,894 | 34.28% |
| Second half, the same cherry-picked | 5,057 | **37.93%** |

Picking with hindsight reached 44.11%. Carried forward, the very same picks fell
to 37.93% - about 38% of the apparent edge survived, and what survived is
22.1 points short of the bar. Something real is in there: 37.93% on 5,057 trades is
not luck against a 34.28% baseline. It is simply nowhere near enough.

**What this does and does not prove.** It is a ceiling on *picking* - on any rule
that says which stock, at which hour, in which direction, decided once and left
alone. Inside that class nothing survives past 37.93%, so no amount of searching
harder for the right stocks and hours gets near 60. It is not a proof about every
possible trigger, because a trigger reacts to what is happening on the day and
this test does not. What it does do is put a number on how much of an apparent
edge in these bars is real once it has to face fresh data: about 38% of it. Six
mechanisms landing on the baseline and a hindsight ceiling of 37.93% are two
independent things pointing the same way.

## What each idea was, and why it was worth trying

- **The two the owner named.** The fifteen-minute opening range is the box the
  first quarter hour builds; the overnight range is the box built between
  yesterday's close and today's open. Both are traded on the first break of
  either side. The thinking behind them is the same: those levels are where
  resting orders pile up, so once price leaves the box there is nothing holding
  it. Both were tested in both directions, because a break that fails is just
  as tradable an idea as one that runs, and neither direction moved.
- **Opening-range break with the group agreeing.** The first idea in this
  project that required two separate things to be true at the same moment: the
  name breaks its own range *and* the other fifty-nine are moving the same way.
  A break the whole market is pushing should be harder to reverse than one
  name's own business.
- **Opening-range break only on wide mornings.** The bracket needs a 1% move
  before it can win. On a quiet day neither level is reached. This asks whether
  the kind of day matters more than the trigger does - taking the identical
  break, but only when the morning range is at least half again this name's own
  recent normal.
- **The 11:00 trend-day trade.** No chart pattern at all: at one fixed moment
  each day, look at whether the name has held one direction all morning, and
  trade that direction. A name being steadily accumulated for ninety minutes is
  being bought by someone who is not finished.
- **Fading a day that is going nowhere.** The mirror of it. If by 11:00 the
  name has crossed and re-crossed its own morning range, its high and low are
  where the two sides keep turning it around, so sell the high and buy the low.
- **Rank among all sixty.** The only mechanism here that does not look at the
  traded name's own chart to decide. At 11:00 the sixty names are put in order
  by how far they have moved since their own opens, and the six extremes at
  each end are traded - momentum one way, reversal the other.

## Two things could not be tested at all, and neither is a rejection

- **Anything using information outside the price series.** The owner named this
  direction, and this project really does collect insider filings, analyst
  mentions, options flow and news. The problem is when it started collecting.
  The bot's own database holds 1,581,606 ticker signals and 213,713 options-flow
  records, and the oldest of them are dated 2026-07-30 and 2026-06-01. The
  development period ends 2025-07-01. The number of records older than that is
  4, and those 4 are rows whose timestamp is a placeholder rather
  than a date. So the entire collection sits inside the sealed period, which may
  not be read - and even if the seal were opened it would give about three
  months of history against a finish line that needs 200 trades. There is
  nothing to test this direction on today; there will be, after a couple more
  years of collecting.
- **Every option idea.** Unchanged from round 2: the only local chains are one
  end-of-day snapshot a week, 2019 to 2022. They cannot see whether an option
  touched +20% before -20%. This is the owner's outstanding decision.

## The arithmetic, once more

A +1.0% target against a -0.5% stop pays two to one, so a coin-flip stock reaches
the target first about a third of the time - measured here at 34.00% with no
trigger at all. To reach it 60 times in 100 a rule must predict an average move
of +0.40% in the trade's direction, per trade, within fourteen days. Every short-
horizon share study this project has run measured a gross edge of one to five
basis points. +0.40% is forty basis points.

## Raw numbers

- `.omc/research/todo-111-round3-prescreen-equs.json` - the eight screened families, each with its long and short halves
- `.omc/research/todo-111-round3-panel-equs.json` - the two cross-sectional families
- `.omc/research/todo-111-round3-ceiling-equs.json` - the ceiling test
- Harnesses: `scripts/research/todo_111_round3_prescreen.py`, `todo_111_round3_panel.py`, `todo_111_round3_ceiling.py`
- The second feed, XNYS.PILLAR, was not run. It exists to confirm a claimed edge
  against a fuller tape by checking whether a touch really happened. There is no
  claimed edge to confirm, and a second opinion on a non-result is not evidence.
