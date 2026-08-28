# Turn the morning PUT shortlist into a measured option trade

**Status:** AWAITING APPROVAL: a free Databento account (or $40 ThetaData) is the only way to test the option rule on history
**Created:** 2026-08-27

**CURRENT STATUS (2026-08-27):** Finished and answered. Verdict **INSUFFICIENT
DATA** — the option idea was not rejected, it could not be tested. Nothing
promoted, no option recommendation, the option section on the card stays OFF,
TODO #96 untouched and still working. The contract selector and the live monitor
are built, tested and running; the monitor timer fires at 6:30 a.m. Pacific and
records real bid and ask every minute for the contracts the frozen rule picks.
Two blockers, both measured, are written up below and in
`.omc/research/put-flow-option-trade-system/FINAL-VERDICT.md`. The only thing
left is one owner decision: a fresh Databento account (free) or ThetaData ($40,
one month) unblocks the historical test this week; otherwise the forward monitor
gets there on its own in roughly five months.

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

---

## Session notes — 2026-08-27

**Verdict reached: INSUFFICIENT DATA.** Nothing promoted, no option
recommendation, `option_trade.display` stays `false`, `verdict: UNDECIDED` in
config. TODO #96 untouched.

**Frozen first, then measured.** The whole rule — nine candidates (3 structures
x 3 exit rules), strike and expiry choice, liquidity tests, commissions, the
60/40 split and all twelve gates — was written and hashed as
`f284dbe96350cb16c6c4f527ab6f20b8d6ffa3d5f93aca1656f3e94e8209ffb0` before any
outcome was read. Three cases the policy did not name were resolved later, each
also before reading outcomes, and written to `policy-clarifications.md` rather
than by editing the hashed file. **C3** is the load-bearing one and it makes the
rule stricter: the nearest listed strike is chosen first and the liquidity tests
can only veto it. Never stepping outward means the rule cannot hunt until
something qualifies.

**All twelve gates: INSUFFICIENT DATA.** Gate 1 wants 100 trades / 30 dates /
40 stocks. The real numbers were 0 / 0 / 0.

**Why, measured rather than assumed.** Of the 181 frozen trades: **124 never had
an option chain stored at all** (the rule cannot even name a contract), **42**
have a nameable contract that has since expired, **15** have data — and those
still produce nothing measurable, because at **2.7% traded-minute density** most
contracts have no trade in the 6:35-6:40 entry window. Yahoo 404s on every
expired contract and has no bid/ask; Barchart's export has no bid or ask column;
the stored Databento key returns 401 (verified twice, independently).

**A second problem, and the more serious one.** At 6:35 on 2026-08-27 every
near-the-money put on AMD ($474) and META ($570) was quoted **14% to 48%** apart
against a 10% limit. Two of the most heavily traded options in the country. That
is about the trade, not the data, and would still be true with a perfect
database. **The timing was not moved to a friendlier hour.**

**Built and live (observer only, display off):**
- `consensus_engine/analysis/put_flow_option_monitor.py` + its CLI wrapper
- four tables: selections, one-minute summaries, immutable events, run health
- `put-flow-option-monitor.timer`, 6:30 a.m. Pacific on trading days
- 54 real selection rows. Its two picks, hand-checked: **DKS Sep 18 $120 PUT**
  ($4.90/$5.10, OI 3,158) and **MARA Sep 11 $11.50 PUT** ($0.80/$0.88, OI 443).

**What running it for real cost, and what it taught.** The monitor service
crashed on startup every 15 seconds for the whole trading day — **2,309
restarts** — because `enabled()` had been split into `select_enabled()` /
`monitor_enabled()` and the CLI still called the old name, and the unit file had
no restart ceiling. The stock trades were never touched: the option layer failed
soft exactly as designed and AMD and META entered normally. Both fixed. There is
now a test that parses the CLI and asserts every symbol it reaches for exists —
it fails on precisely that bug when reintroduced.

**Independent verification: CONFIRMED WITH DEFECTS.** The verifier rebuilt every
data figure from the raw files without using the builder's code and matched all
41 contracts exactly. Six defects, including a `NameError` that would have
crashed the loop the first time any position touched its target or stop. All six
fixed, each with a test.

**Tests:** 3,768 passed, 1 skipped, 0 failed. One test deselected — a Gemini
video test that never returns; proved pre-existing on commit `f390d17` and
tracked as TODO #102.

**Commits:** `0222db2` (research tooling), `93e5453` (verdict + corrections),
`fa2be81` (production selection and monitor). Plus `ef1b53c` for #99 and
`e914997` for #102.

**Still open — one owner decision.** Either unblocks the historical test:
a fresh Databento account ($125 free credit, whole pull under $5) or ThetaData
at $40 for one month. The free forward route works too but needs roughly five
months at ~1 option trade a day.
