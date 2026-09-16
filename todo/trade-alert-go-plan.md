# Agreed plan — run on "go" (owner decisions, 2026-09-16)

TODO #117. Detail: `todo/finish-automated-trade-alert-build.md`.
Surfaces: `/root/trade-alerts-builder/**`, `trade_alerts_build_docs/**`,
`~/.openclaw/db-backups`. Do NOT restart the Discord bot or consensus engine.

## Owner decisions given this session (authoritative)

1. **Databento budget: USD 60, fresh total.** Replaces the old $40 authority
   and its $16 of standing reservations. Spend at own discretion up to $60,
   no further approval needed.
2. **Universe (confirmed):** NVDA, MSFT, AAPL, GOOGL, AMZN, META, AVGO, TSLA,
   BRK.B, LLY, SPY, QQQ, IWM, XLV, GLD, USO, VXX.
3. **History depth:** 1 year is enough.
4. **Options moneyness:** 10% in-the-money to 10% out-of-the-money. Build spec
   separately limits to 0-7 DTE.
5. **db-backups -> Google Drive.** Builder `runs` stays local.
6. **M0.2 acceptance bar relaxed to option (a):** a field that cannot be
   obtained is RECORDED AS A GAP, and every rule depending on it is SWITCHED
   OFF and labelled untested. Never approximate a missing field and test
   through it. Owner's words: "testing some data is better than testing
   nothing because 1 aspect wasn't able to be downloaded." Record this as an
   owner decision in the build docs - it changes M0.2 from "every field
   proven" to "proven or documented".

## Steps

1. **Disk.** System journal already vacuumed (2.2 GB freed; 11 GB free now).
   Move `~/.openclaw/db-backups` (4.7 GB) to Drive via the existing verified
   mover at `/root/trade-alerts-builder/archives/storage-manager/`
   (rclone, upload -> re-download -> SHA256 match -> only then drop local).
   Target: clear the 12 GB reserve. NOTE the reserve is
   `max(12 GB fixed, 15% of disk)` = 11.25 GB on a 75 GB disk, so ~12 GB is
   the real bar. Do not lower either limit.
2. **BRK.B fix.** `BRK.B` + `.OPT` = `BRK.B.OPT`, which Databento rejects
   (`symbology_invalid_symbol`) because the dot is the separator. This is the
   unexplained HTTP 400 that has blocked M0.2I since 2026-09-14. Verified:
   remove BRK.B and every OPRA request prices instantly. Equity requests with
   BRK.B are fine - options parent format only. Fix the symbol format in the
   frozen list (`M0_2H_SOURCE_ACQUISITION_SPEC.json` contains BRK.B).
3. **Buy the stock bundle, ~$23.** 1 year, 17 names, EQUS.MINI:
   - `trades` (tick-level, for intrabar path) ~ $20.67
   - `bbo-1m` (1-min best bid/offer, for spread/fill model) ~ $0.68
   - `ohlcv-1m` (1-min bars, for signals) ~ $1.12
   Rationale: tick QUOTES (`mbp-1`) are $548 and are NOT needed. Intrabar path
   (did the stop hit before the target) is answered by tick trades; the spread
   is estimated from 1-min BBO. Do not buy mbp-1.
4. **Options: price before buying.** Full chains do not fit - 1 year of
   `cbbo-1m` across 16 underlyings is $1,088. Instead: run the signal
   generator over the new stock data, extract actual entry/exit timestamps and
   the strikes that would have been chosen, then request only those contracts
   on only those days. Check the free DoltHub option-chain set (real bid/ask,
   2019+) FIRST - if it covers these names, spend nothing.
5. **Update the build's budget documents** to the $60 fresh total so the
   controller enforces the right figure, and record decisions 2-6 above as
   owner decisions.
6. **Restart the controller** and work milestones. M9.3 is blocked behind
   M0.2; expect the controller to stop again on gates money cannot open
   (original availability, corrections/finality, point-in-time membership,
   historical borrow, complete-chain proof). Under decision 6, record those as
   gaps and disable the dependent arms rather than halting the whole milestone.

## Measured reference numbers (free cost checks, 2026-09-16)

Stocks, 1 yr, 17 names: mbp-1 $548.06 | trades $20.67 | ohlcv-1m $1.12 | bbo-1m $0.68
Options, 1 yr, 16 names, full chain: cbbo-1m $1,088 | ohlcv-1m $6,435 |
trades $12,874 | cmbp-1 $21,434
Options slices: SPY alone 1 yr $180 | SPY+QQQ+IWM 1 yr $395 |
all 16 for 1 month $91 | all 16 for 3 months $295

## Standing rules

No live activation, no broker/Discord/provider live calls, no orders, no
deployment, no bot restarts, no new strategy rules, no Git push. All switches
stay off. Do not hand-edit `state.json`. Do not re-open an accepted milestone.
Controller recovery is `python3 controller.py --clear-attention resume`
(NOT `buildctl resume --clear-attention` - buildctl takes one word and
silently ignores the flag), then `./buildctl start`.
