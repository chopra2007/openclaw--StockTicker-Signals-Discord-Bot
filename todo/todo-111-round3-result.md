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

---

## The owner's answers, 2026-09-03

**On the months-long momentum method — keep it.** His words: *"since I can trade
more than one strategy simultaneously, i'd like to keep this as an option."* So
#111 momentum is no longer disqualified by its three-month holds. It was never a
"does it work" problem — it made +6.89% on development data and +10.74% on
sealed data, verified three times. It can run alongside a short-horizon rule
rather than instead of one. Nothing is live and nothing was enabled.

**On the shape of the bracket — tested, and here is the answer.**

He asked to try an even +0.5% target against a -0.5% stop instead of +1.0%
against -0.5%. Measured on the same data, same entry rules, only the shape
changed:

| Entry rule | +1.0% / -0.5% | +0.5% / -0.5% |
|---|---|---|
| No trigger at all (11:30) | 34.00% | **49.66%** |
| No trigger at all (11:00) | 34.77% | **50.56%** |
| 15-minute opening-range breakout | 34.08% | **50.27%** |
| Overnight-range breakout | 34.23% | **50.07%** |
| 11:00 trend-day trade | 35.94% | **53.06%** |

The win rate jumps about sixteen points across the board. That looks like a much
better strategy and it is not one, for a reason worth being precise about:

- At **+1.0% / -0.5%**, each win pays twice what each loss costs, so 60 wins in
  100 averages +0.40% a trade.
- At **+0.5% / -0.5%**, each win pays exactly what each loss costs, so the same
  +0.40% a trade needs **90 wins in 100**.

Every rule moved up, and so did the line it had to clear, by the same amount.
The 11:00 trend-day trade went from 35.94% against a 60% bar to 53.06% against a
90% bar — no closer. Its average per trade stayed at +0.02%, which is where it
was before.

**What this does tell you, and it is useful.** The even bracket is close to a
coin flip: 49.66% with no trigger at all, where pure chance says 50%. That is a
clean confirmation that these one-minute bars have essentially no directional
drift over the next few days. It also means the shape of the bracket is a free
choice — pick whichever suits how you actually trade, because it does not create
or destroy an edge. The edge has to come from the entry, and that is what has
not been found.

Numbers: `.omc/research/todo-111-round3-bracket-shape-equs.json`. Harness:
`scripts/research/todo_111_round3_bracket_shape.py` — it takes any family in the
round-3 pre-screen and any target/stop pair, so a different shape can be tried
in about fifteen minutes.
