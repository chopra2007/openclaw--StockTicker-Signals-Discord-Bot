# TODO #111 round 2 — the baseline, and the sealed period

Written 2026-09-03 (Pacific).

## The baseline: how often the target comes first for no reason at all

Take a minute at random during the regular session, buy (or short) at the next
minute's open, and close on the first touch of +1.0% in your favour or -0.5%
against you, with a hard 14-trading-day cap. How often does the target come
first?

| Feed | Trades | Target first | Average per trade |
|---|---|---|---|
| EQUS.MINI | 695,484 | **34.47%** | -0.026% |
| XNYS.PILLAR | 730,536 | **34.56%** | -0.042% |

Split by side, on EQUS.MINI: buying wins 36.38% of the time, shorting 32.55%.
That gap is the market's long-run upward drift, and it is small.

Two independent feeds of the same 60 names land within a tenth of a point of
each other, and both land on the arithmetic: a coin-flip stock hits a target
that is twice as far away as its stop about 33 times in 100 (0.5 ÷ 1.5).

**So the owner's bar is 60 in 100 against a starting point of 34 in 100.** A
rule has to be nearly twice as accurate as chance, on every trade it takes.

Entries were sampled one an hour through the regular session, both directions,
all 60 symbols, 2023 to 2026. Returns are gross — no commission, no spread, no
slippage. Exits were decided on one-minute bars.

Details: `.omc/research/todo-111-round2-baseline-equs.json` and
`...-xnys.json`, including a per-symbol breakdown. The friendliest single name
for buying was JPM at 39.5%; the least friendly was DHR at 33.3%. No name
anywhere near 60.

## The sealed period

Declared **before** any candidate rule was measured:

- **Development period — free to look at:** everything before **2025-07-01**.
  The last entry signal is taken three weeks earlier so no trade runs past the
  seal.
- **Sealed period — untouched:** **2025-07-01 onward**, about fourteen months.
  No file in `scripts/research/todo_111_round2_prescreen.py` can read it; the
  sealed bars are dropped from the table before any feature is computed.

The seal is opened once, for a rule that has already been frozen.

One honest note: the baseline table above was measured across the whole span,
including the sealed months, before the split was declared. It is a structural
constant of the bracket rather than a choice — theory says 33.3%, both feeds
say 34.5% — and no rule was selected from it. Every candidate measurement from
this point on is development-only.

## What the baseline rules out

Any idea whose entry trigger leaves the target-first rate near 34 in 100 is
dead on arrival, and there is no threshold tuning that saves it. The cheap
pre-screen kills those before a full frozen backtest is ever run, and records
the number either way.
