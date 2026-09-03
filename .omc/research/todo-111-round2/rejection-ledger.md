# TODO #111 round 2 — rejection ledger, session of 2026-09-03

Eleven entry triggers, measured on development data only (everything before
2025-07-01), on 60 NYSE large caps, one-minute bars, EQUS.MINI feed. Every
trade closes on the first touch of +1.0% in its favour or -0.5% against it,
capped at 14 trading days. Returns are gross.

**The number that decides everything: a randomly chosen entry reaches the
target first 34.47% of the time. The owner's bar is 60%.**

| Idea | Trades | Target first | Average per trade | Verdict |
|---|---|---|---|---|
| *(no trigger at all — the baseline)* | 695,484 | **34.47%** | -0.026% | the yardstick |
| Quiet half hour, then a break out of it | 53,883 | 35.29% | -0.037% | rejected |
| Choppy path, fade the last 15 minutes | 235,721 | 34.49% | -0.031% | rejected |
| 15-minute overshoot, faded | 143,053 | 34.31% | +0.003% | rejected |
| Name pulls away from the other 59, fade it | 182,236 | 34.31% | +0.002% | rejected |
| Steady half-hour drift (a worked order) | 208,210 | 34.20% | -0.002% | rejected |
| Trending path, ride the trend | 211,898 | 34.16% | -0.008% | rejected |
| One-minute spike on heavy volume, faded | 11,765 | 34.08% | -0.008% | rejected |
| Break of the last half hour's range | 190,897 | 34.11% | -0.023% | rejected |
| Name pulls away from the other 59, ride it | 182,236 | 33.78% | -0.007% | rejected |
| 15-minute overshoot, ridden | 143,053 | 33.74% | -0.005% | rejected |
| One-minute spike on heavy volume, ridden | 11,765 | 33.68% | -0.007% | rejected |

The whole spread from best to worst is **1.6 percentage points**, and it sits
around the number you get by picking a minute at random. The bar is
**25 points higher than any of them**. No threshold tweak closes a gap that
size — moving a trigger's sensitivity shifts the trade count, not the odds.

Raw numbers, including a long/short split for each idea:
`.omc/research/todo-111-round2-prescreen-equs.json`.

## Why none of them moved

The bracket pays two to one, so a coin-flip stock reaches the far level first
about a third of the time. To reach it 60 times in 100, a trigger has to
predict an average move of **+0.40% in the trade's direction**, per trade,
within a few days. That is a very large edge to ask of a one-minute chart
pattern, and it is roughly a hundred times larger than the 1-to-5 basis points
of gross edge that every earlier short-horizon study in this project (#103,
#104, #106) actually measured.

One thing worth the owner knowing: the two halves of the share bar say the same
thing. 60 wins in 100 at +1.0% against 40 losses at -0.5% averages exactly
+0.40%. So there is no way to satisfy the win rate without also satisfying the
average — the finish line is one condition, not two, and it is a demanding one.

## What each idea was, and why it was worth trying

- **Spike on heavy volume, ridden** — a one-minute move far larger than the
  name's normal minute, on more than triple its normal volume, is usually news
  arriving; news is absorbed over hours.
- **Spike on heavy volume, faded** — or it is one impatient order, and the
  price snaps back when that order finishes.
- **15-minute overshoot, faded / ridden** — a crowd chasing a short move either
  overshoots and reverts, or keeps going. Both directions tested.
- **Break of the last half hour's range** — resting orders cluster at an
  obvious edge; once they are gone there is nothing until the next shelf.
- **Quiet half hour then a break** — a narrow range means both sides are
  balanced, and the side that gives way tends to keep giving way.
- **Steady half-hour drift** — a large move with no big single minute inside it
  is a big order being worked, and it is not finished in half an hour.
- **Trending path / choppy path** — aimed at the arithmetic rather than the
  direction: a path that keeps going reaches the far level more often than a
  coin flip does, whichever way the trade points. It did not.
- **Pulls away from the other 59, ridden / faded** — the only two ideas that use
  information from outside the one stock: the name's half-hour move with the
  whole group's move taken out.

## Not tested, and why

- **Every option idea.** There is no intraday option price history on this
  machine. The free weekly chains are one end-of-day snapshot a week and cannot
  see whether an option touched +20% before -20%. Parked for the owner.
- **Opening-range breakout, gap fade, post-earnings drift, intraday
  dislocation.** All previously measured and rejected in #93, #97, #103 and
  #106; the mission forbids re-running a rejected family.
- **The second feed (XNYS.PILLAR).** It is there to confirm a claimed edge by
  checking a touch against a fuller tape. There is no claimed edge to confirm.
  The baseline itself was checked on both feeds and agreed to within a tenth of
  a point.
- **The sealed period.** Never opened. Nothing earned the right to it.
