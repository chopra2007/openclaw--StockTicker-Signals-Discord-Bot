# TODO #111 round 3 — handoff and the owner's decision list

**Written 2026-09-03 (Pacific).** Read with
`.omc/research/todo-111-round3/rejection-ledger.md`, which has every number.

## What happened in round 3

Six genuinely different mechanisms, ten entry rules, all measured on
development data only. All ten rejected. Then a ceiling test that settles
whether an eleventh is worth building.

The two strategies you named yourself were built and tested first, and both got
a fair run in both directions:

- **Fifteen-minute opening-range breakout** — 32,010 trades, reached the target
  first 34.08% of the time, against 34.00% for doing nothing at all at the same
  time of day.
- **Overnight-range breakout** — 15,073 trades, 34.23%, against the same 34.00%.

Then four more mechanisms, each aimed at one of the directions you pointed at:
two conditions that must agree, the day's own character, the time of day as the
reason to trade, and the name's place among all sixty. The best of the whole set
was the 11:00 trend-day trade at **35.94%**. The bar is **60%**.

## The result that matters most

Ten more rejections would have been a weak answer to "keep going", so the last
test asked a different question: **is the next idea worth building at all?**

Split the development years in half. In the first half, look up — with full
hindsight, which no real strategy is allowed — the twenty best combinations of
stock, hour of day and direction. Trade exactly those, unchanged, in the second
half.

- Cherry-picked with hindsight: **44.11%**
- The same picks, carried forward: **37.93%**, on 5,057 trades
- Doing nothing at all: **34.28%**

So something real does survive — 37.93% against 34.28% on five thousand trades
is not luck. It is also **22 points short of the bar**, and it came from
cheating. A rule that has to be decided in advance can only do worse than that.

**Plain conclusion: nothing in this data comes close to the 60-in-100 bar.** Six
different mechanisms landed on the baseline, and hindsight itself only carries
37.93% forward. To be exact about what the ceiling test proves: it rules out
*picking* — any rule that names the right stocks, hours and directions once and
leaves them alone. It does not mathematically rule out every possible trigger,
because a trigger reacts to the day as it happens. But two independent lines of
evidence now point the same way, and neither is close.

## The decisions that are yours

**1. Intraday option prices — still the open one.** The option half of your
finish line has never been tested and cannot be. The only option data here is
one end-of-day snapshot a week from 2019–2022, which cannot see whether an
option touched +20% before it touched -20%. Buying intraday option history is
the only way to test it. Nothing was bought; nothing was signed up for.

**2. Information from outside the price series — blocked by time, not by
money.** You named this and it is the most promising untried direction, because
it is the one kind of information the ceiling test does not cover. Your bot
collects it: 1.58 million ticker signals, 213,713 options-flow records. But the
oldest record is from **July 2026** — three months old. The development period
ends July 2025. There is simply no history to test on yet. In roughly two years
of continued collecting there will be. Nothing to decide today; it is a matter
of waiting, and the collecting is already running.

**3. The bar itself.** This is the real fork, and it is yours alone. The 60-in-100
bar at +1.0% against -0.5% has now been measured against seventeen entry rules
across two rounds and a hindsight ceiling, and nothing has come within twenty
points of it. Three honest ways forward:

- **Keep the bar and change the data** — buy intraday option prices, or wait for
  the outside-information history to build. Both are covered above.
- **Keep the bar and change the horizon.** The one method this project has ever
  found that actually made money was the #111 momentum test: +6.89% on
  development data, +10.74% on sealed data, verified three times. It was
  rejected only because it holds for three months, and your horizon is minutes
  to days. That was a horizon decision, not a "does it work" decision.
- **Change the reward-to-risk shape.** The bar's difficulty is mostly geometry:
  asking for +1.0% before -0.5% means winning twice as often as chance. A target
  and stop closer to equal size needs far less accuracy for the same money. This
  would be a new finish line, and only you can set it.

Nothing here changes without you. The loop is stopped, not abandoned, and every
number is on disk.

## For the next session

- Do not re-run rounds 2 or 3. Both ledgers stand as the record.
- The sealed period, 2025-07-01 onward, was **never opened**. It is still clean.
- The harnesses are reusable as they are:
  `scripts/research/todo_111_round2_bracket.py` (the exit engine),
  `todo_111_round3_prescreen.py` (add a family to `FAMILIES` and it is measured),
  `todo_111_round3_panel.py` (anything that ranks names against each other),
  `todo_111_round3_ceiling.py` (the hindsight test, re-usable on any new data).
- The second feed, XNYS.PILLAR, is still unused. It exists to confirm a claimed
  edge against a fuller tape. There has never been an edge to confirm.
- $0.00 was spent. No order was placed, real or paper. No alert was enabled.
