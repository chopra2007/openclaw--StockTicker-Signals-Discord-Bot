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

## Where this plan stands — 2026-09-19 PDT

Steps 1-5 are **done**. Step 6 is **in progress and running unattended**.

1. Disk — done. 13 GB free; the 12 GB reserve was never lowered.
2. BRK.B — done. The options parent symbol is `BRKB.OPT`, not `BRK.B.OPT`.
3. Stock bundle — bought. Billed **$22.47**, exactly the quote. One year of
   `trades`, `bbo-1m` and `ohlcv-1m` for all 17 names, 2025-09-15 to
   2026-09-14, in `~/.openclaw/research-data/databento/`
   `core17-1y_2025-09_to_2026-09/`. **$37.53 of the $60 remains.**
4. Options — still not bought, by design. DoltHub was checked first and is
   reference-only (misses QQQ, IWM, GLD, USO, VXX; one end-of-day price per
   contract). Targeted quotes cost roughly **$0.41 per name-day**, so about 90
   name-days fit in what is left. They get bought only once the signal run
   names the exact days and strikes.
5. Budget documents — done, recorded as owner decisions D-101 to D-112.
6. Controller — running. 53 steps accepted, now past **M9.1BC**. Four
   playbooks read real bars; the 18-candidate sweep, the 30-second entry fill
   with real spread and commission, the two-part exit and the price-level
   catalog are built. **No ranking and no profit figure yet** — the build
   correctly refuses while the exit side is uncosted and two D-104 gaps stand.

### Decisions added since the original plan

- **D-106** take every alert within 30 seconds; fills modelled in that window.
- **D-107** train on 9 names (NVDA, MSFT, AAPL, TSLA, LLY, SPY, QQQ, XLV, USO),
  prove on 8 unseen (GOOGL, AMZN, META, AVGO, BRK.B, IWM, GLD, VXX).
- **D-108** the success bar, frozen before any search runs.
- **D-109** two option-exit arms: sell 4 of 5 at 1.20x then runner to 2.00x or
  breakeven; and the same first leg with a 0.85x trailing runner.
- **D-110** offline research may use PROVISIONAL bars on its own named path.
- **D-112** the retained-file read assignment for the adapter-count run.

### Controller fixes made to keep it running

- Published-file ceiling raised 128 to 512 (`MAX_PUBLISHED_ARTIFACT_FILES`).
- Step IDs may carry two letters (`M9.1AA` onward), in `controller.py` and both
  result schemas. The build used to die at `M9.1Z`.
- `resume-watchdog.py` restarts the build after known-harmless stops only.

### Next

Run the adapter counts under D-112, cost the exit side, then the real search:
tune on the nine training names, prove once on the eight held-out names, judge
against D-108. Only then buy the targeted option quotes and test the D-109 arms.

**Trap:** never edit a workspace file while a review is pending — it causes
"source changed before review". Check the stage first.
