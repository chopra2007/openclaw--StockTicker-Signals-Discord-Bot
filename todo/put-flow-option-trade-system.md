# Turn the morning PUT shortlist into a measured option trade

**Status:** OPEN
**Created:** 2026-08-27

**CURRENT STATUS (2026-08-27):** The option rule is frozen and hashed, the
contract selector is built and proven against a real morning, and the live
monitor ships today. The historical test could **not** be finished, and the
reason is data, not the trade. Verdict on the history: **INSUFFICIENT DATA** —
no PASS, no option recommendation, option display stays OFF.

**The one thing blocking the historical test.** Nobody can price a put in
June 2026 without the bid and ask that were quoted at the time, and we cannot
get them:

- Yahoo is free but returns **404 for every expired contract**, and serves only
  **8 days of one-minute data per request**. Its total reach on our 181-trade
  sample is about **15 trades**.
- Barchart's option export has **no bid column and no ask column** — only traded
  prices, volume, open interest and greeks. Confirmed from the live page.
- Our stored Databento key is **dead** — every call returns 401, so the ~$8.47
  of credit on that account cannot be spent or even checked.
- Everything else that genuinely has minute bid/ask needs a **new account or a
  credit card**, which only the owner can create.

**The exact owner action that unblocks it** (either one, both are ~$0):

1. Open a fresh Databento account (databento.com). New teams get **$125 of free
   historical credit**. The whole 181-trade pull is OPRA `cbbo-1m` at $2.00/GB
   and is estimated at **well under $5**, so it costs nothing. Credits expire
   six months after signup.
2. Or ThetaData "Options Value", **$40 for one month, cancel anytime**, which
   has 1-minute historical bid/ask back to 2020 including expired contracts.

Databento is the better one: cheaper, no card, and it is the same vendor the
project already uses.

**How long the free route would take, if you'd rather not decide.** The monitor
now records real bid and ask every minute for the contracts the rule picks, so
the evidence does build on its own — just slowly. Across the two real mornings
so far the rule produced **2 option trades from 6 positions**, about one a day.
The gates need 100 trades over 30 signal dates to judge the full sample, and 40
more on a stretch never looked at. At one a day that is roughly **five months**.
Buying the history costs about $0 and answers it this week. That is the whole
trade-off.

**What is still worth having, and is shipping anyway.** The free minute bars we
could get are far too thin to model an intraday exit — across the 12 contracts
downloaded there are 50,492 one-minute bars but only **891 with any volume
(1.8%)**, and for some contracts it is under 1%. So the forward monitor is the
only honest route: from today it records real Schwab bid/ask every minute for
the contracts the frozen rule actually picks. That builds the exact evidence the
historical test cannot buy.

**What the frozen rule did on the two real mornings it has now seen.**

2026-08-26 (DKS, SUI, MSTR, MARA): 2 option trades, 2 refusals.
- DKS $121.98 -> **DKS Sep 18 $120 PUT**, $4.90/$5.10, open interest 3,158
- MARA $11.49 -> **MARA Sep 11 $11.50 PUT**, $0.80/$0.88, open interest 443
- SUI and MSTR -> no option trade, the nearest strike's quote was too wide

2026-08-27 (AMD, META): **0 option trades, 2 refusals** — and this one matters
more than the data problem. At 6:35 a.m. Pacific the puts near the money on AMD
and META were quoted 14% to 48% apart. The limit is 10%. Not one strike came
close, on two of the most heavily traded options in the country. A 25% gap means
you lose a quarter of the position the moment you buy it.

That is a finding about the trade, not about the data: five minutes after the
open, market makers have not tightened up yet. The stock version works at 6:35
because a stock has one price. The option version may not be tradeable at that
moment at all. **The timing was NOT moved** — changing it after seeing a bad
result is the retuning this whole exercise refuses to do.

Running tally: six positions, two option trades, four refusals.

**Also fixed today, found only because it ran for real:** the monitor service
crashed every 15 seconds all day (2,309 restarts) because the module's `enabled`
switch had been split in two and the job still called the old name, and my unit
file had an unbounded restart policy. Both fixed; the restart policy now stops
after three failures in ten minutes. The stock-pair trades were never affected —
the option layer failed soft exactly as designed, and AMD and META entered
normally.

## Why this exists

TODO #96 already finds up to four extreme-PUT stocks each morning and trades
them as a stock pair (short the stock, long SPY). That is only the candidate
generator. It has never been tested whether the natural way to express the same
idea — buying a put — works after real costs.

## The plan being executed

`.omc/plans/finish-put-flow-option-trade-system-prompt.md`

Nine frozen candidates: three option structures (at-the-money put, 5%
out-of-the-money put, at-the-money/5% put debit spread) times three exit rules
(hold to the fourth session; +25%/-35%; +50%/-35%). One rule may be promoted,
and only if it clears every frozen gate on a chunk of history that was never
looked at while choosing.

## Known hard constraint found on day one

Yahoo returns one-minute history ONLY for contracts that have not expired yet
(a live contract such as `DKS260918P00120000` returns 2,953 one-minute rows;
an expired one such as `DDOG260605P00260000` returns 404 "may be delisted").
So the free path cannot rebuild the June–August sample. That is a data-source
problem, not proof the trade is bad.

## Links

- TODO #96 `extreme-put-flow-morning-shortlist.md` — the stock-pair feature (keep soaking)
- TODO #98 `live-edge-portfolio-and-data-gap-closure.md` — stays open until this answers the option question
- TODO #99 `make-auction-research-tests-work-in-ci.md` — the CI test repair done alongside this
- Results: `.omc/research/put-flow-option-trade-system/`

## Files involved

- `consensus_engine/analysis/put_flow_option_capture.py`
- `consensus_engine/analysis/put_flow_shortlist.py`
- `scripts/put_flow_shortlist_job.py`
- `scripts/research/put_flow_option_*.py`
- `config/consensus.yaml` (`put_flow_shortlist`)
