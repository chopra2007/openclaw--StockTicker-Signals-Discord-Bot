# TODO #111 — SPY expected-move iron condor: development result

**Verdict: REJECTED on development.** The untouched period was never opened.
Every number below is written by the scripts that computed it; nothing is typed
by hand.

## What was tested

A SPY iron condor whose two short strikes sit just outside the options-implied
expected move, entered at 7:00 a.m. Pacific, closed on the first touch of +20%
or -20% of the credit, with a hard 14-trading-day cap. The frozen rule is
`.omc/research/todo-111-condor/FROZEN-RULE.md`
(sha256 `5668ed1e4182f56bcd22bcc5e99cf03cfe3101824ae2772671f282da36790aa3`),
with three mechanical points settled in `policy-clarifications.md`. Both were
written before any trade return existed.

Entry days were fixed first, from free daily data only — VIX against SPY's own
recent movement, plus a calm-market filter — so the sample was chosen before a
dollar was spent.

## The result

| | condor | put spread alone | call spread alone |
|---|---|---|---|
| trades | 241 | 241 | 241 |
| win rate | 29.88% | 36.10% | 28.63% |
| average per trade | -14.75% | -8.86% | -10.93% |
| best | 30.19% | 47.14% | 40.62% |
| worst | -338.97% | -181.25% | -76.06% |

The bar is a **60%** win rate and **+4.00%** a trade. The condor won
29.88% and averaged -14.75%. All
three tests fail, and they fail by a wide margin rather than narrowly.

## Why it failed — the part worth keeping

Of 241 condors, **72 went up and 169 went down**.

- The average winner is **+20.8%** and the average
  loser is **-29.9%**. At that shape the rule needs
  a **59%** win rate just to break even. It got 29.88%.
- **The -20% stop does not cap the loss.** It can only act on a minute when the
  market is open, and the position gaps overnight:
  43 trades finished worse than -25%,
  14 worse than -40%,
  5 worse than -100%, and the worst was
  -338.97%. This is the same nine-to-one loser that killed the round-1
  credit spread, only smaller — managing the trade shrank it, it did not remove it.
- **The +/-20% band is close to the cost of trading the structure.** Getting in
  and straight back out of four legs costs a median **9% of the credit** — and
  on the very first trade in the sample (2014-01-03) it cost 21.5%, which
  tripped the stop one minute after entry. Nine of 241 trades stopped
  inside the first minute for that reason.

## Was the sample fair?

38 of 279
entry weeks were dropped, almost all because the $5 wing strike was not listed
on that expiry, and 5 because a short leg was quoted more than 25% wide. The
dropped weeks were **calmer**, not stormier — median VIX 13.3 against 14.4 on
the weeks that traded — so dropping them did not quietly remove the hard weeks.

## The data

- Databento `OPRA.PILLAR`, schema `cbbo-1m` (minute national best bid and offer).
- 246 four-leg files checked: **0 problems**.
  Every file carries the right dataset and schema, the four contracts asked for,
  no duplicated timestamps, and no negative prices.
- Minutes per leg: median 6035.
- **All four legs were quoted in 100.0%
  of regular-session minutes.** Missing-minute rate across the whole study:
  1.43e-06. No minute was ever invented.
- One trade was re-computed by hand from the raw quotes and matched the script
  exactly: 2014-01-03, credit $0.93, cost to close $1.13 one minute later,
  return -21.51%.

## Money

| | |
|---|---|
| spent | **$3.4836** |
| ceiling | $20.00 |
| planned before starting | $6.41 |
| untouched-period data, estimated and reserved | $2.81 — **not spent** |
| Databento credit left | about **$121.52** of $125 |

527 requests, every one cost-estimated before it was sent, all recorded
in `research-data/todo-111-condor/spend_ledger.json`.

## What happens to the untouched period

Nothing. It stays sealed. A candidate that fails development is rejected there;
spending $2.81 to watch it fail again buys
nothing, and the 2022-2026 window stays clean for the next candidate.

## What this does and does not settle

- It **does** settle the expected-move iron condor at 30-45 days on SPY with a
  +/-20% first-touch bracket. That exact rule loses money.
- It **does not** settle short option premium in general. Two things are now
  measured rather than assumed, and both point the same way: an overnight gap
  walks straight through a percentage stop, and a +/-20% band on a four-leg
  structure is only about twice the cost of opening and closing it.
- The next honest version of this family would need a wider bracket, fewer legs,
  or a defined-loss exit that does not rely on a price being quotable, and it
  should be argued before it is bought.
