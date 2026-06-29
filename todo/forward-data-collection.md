# Start saving the data future features need to test on

**Status:** IN PROGRESS — Tier-1 Items 1+2 + Tier-2 #3/#5 BUILT (2026-06-29); deploy + soak pending
**Created:** 2026-06-28

## CURRENT STATUS (2026-06-29, run `todo-55-47-research`) — Tier-1 Item 2 + Tier-2 #3/#5 BUILT
Three forward-loggers built + tested + committed on branch `worktree-todo-55-47-discover`
(commit c2210ff); **NOT yet deployed** (merge to master + engine restart + install 2 timers).
- **Tier-1 Item 2 — analyst track-record producer (`source_performance_shadow`):** built SAFE.
  It writes a NEW shadow table, NOT the live `source_performance`, because 3 live flags
  (`per_analyst_cooldown`, I2 `analyst_accuracy_weight`, I10 `strong_requires_hard_evidence`)
  would change alerts the instant the live table fills (19 analysts cross ≥5 day one — verified).
  Grading is sign-adjusted by `catalyst_type` (bearish set → down move = hit). Verified on a copy
  of the live DB: 365 rows / 28 handles / 53 shadow rows, live `source_performance` stayed **0**.
  **Live check owed before promotion:** a soak + a shadow-delta analysis (would-be cooldown/score
  deltas vs flat). 1h is near-random — never promote on 1h alone (24h primary). `consensus_logodds`
  I7 still OFF; do NOT flip until the shadow validates.
- **Tier-2 #3 — `iv_snapshots`:** daily ATM-IV / expected-move logger (`scripts/iv_snapshot_daily.py`
  reusing `expected_move.compute_em`) + `iv-snapshot-daily.timer` (22:35 UTC, not installed).
- **Tier-2 #5 — `cross_asset_shadow`:** persist the daily E2 VIX-term + FRED HY-credit ratios. The
  deployed config is `cross_asset.enabled=true, shadow=false`, so it now fires in the LIVE path too
  (the FRED credit ratio is point-in-time, can't be backfilled).
- Real coverage note: only **359/3103** labeled alerts carry a non-empty `analyst_mentions` (~28
  handles) — the earlier "3,103 ready" was an overstatement.
- DEPLOY STEPS (go-live): merge branch→master, restart `consensus-engine.service`, install+enable
  `iv-snapshot-daily.timer` + `source-performance-shadow-daily.timer`. None change live alerts.

### Earlier today (Tier-1 Item 1 — 5d/20d labels, run `trade-edge-features`)
The #1 unlock — **+5d/+20d outcome labels** — is built, live, and backfilled.
`decision_snapshots` now has `outcome_price_5d` / `outcome_price_20d`; the live engine
fills them going forward, and history was backfilled: **2,154 rows have a 5-day label,
890 have a 20-day label**. This starts the data clock the failed trade-edge features
(sector-rotation / factor / trend) need to be re-tested on a matching horizon in ~2-3
months. (`alert_history` 5d/20d columns were intentionally NOT added — redundant; the
re-test and `calibration.retrain` read `decision_snapshots`.) Still open: Tier-1 Item 2
(`source_performance` producer), Tier-2/3 logging.
Shipped in discover run `trade-edge-features` (commit c08928f; one-off backfill via
`scripts/backfill_decision_outcomes.py`; daily fill rides the live `price_outcome_loop`).

## The goal in one line
Begin a cheap, append-only forward-log of the inputs and outcomes that future
features will need, so the next time we build a slow-signal feature it already
has history to prove itself on — instead of failing its backtest for lack of the
right recorded data.

## Why (the core finding)
Several features came back "NO-EDGE" or "no-op" not because the idea was bad but
because (a) the right **outcome label** was never recorded, or (b) the source
data is **point-in-time and can't be backfilled**. The fix is to start logging
now. We already do this for some things (vol-indicator "Track-B"); this item is
the complete sweep. Source: 3-agent forward-collection audit, 2026-06-28.

**Verified fact:** the engine grades every alert at **only +1h and +24h** — no
+5d/+20d anywhere. Confirmed in code:
- `alert_history`: only `price_1h_later`, `price_24h_later` (`consensus_engine/db.py:104-106`)
- `decision_snapshots`: only `outcome_price_1h`, `outcome_price_24h` (`db.py:280-281`)
- `price_outcome_loop` iterates only `("price_1h_later","price_24h_later")` (`consensus_engine/main.py:1762-1763`)
- `shadow_predictions` only gets `"1h"`/`"24h"` rows (`main.py:1620-1621`)
- `calibration.py` retrains only `"1h"`/`"24h"` (`consensus_engine/analysis/calibration.py:17`)

## Next steps, priority-ordered

### TIER 1 — highest leverage, cheap, do first
1. **Add +5d and +20d forward outcome labels to every alert.** THE #1 UNLOCK. **[DONE 2026-06-29 — decision_snapshots side live + backfilled; see CURRENT STATUS.]**
   - Unblocks: the whole trade-edge family that died NO-EDGE (sector-rotation /
     factor / trend — see memory `project_market_wide_no_edge.md`, which were
     judged on a 1h/24h ruler against 1-month/2-month signals), the
     conviction-scoring rework (#32 Phase-2 goal), "market layer as a risk/sizing
     filter", and it makes **sector seasonality even measurable** (verdict on
     seasonality was NO-GO-as-signal / maybe-tiny-nudge, but untestable until
     these labels exist).
   - Data: closing price at +5 and +20 trading days after `alerted_at`, per alert.
   - Backfillable? The *label* is backfillable for existing rows (yfinance daily
     OHLCV keyed on stored `ticker` + `alerted_at`), but statistical power accrues
     forward (the postmortem had only ~48 graded alerts). So: backfill once AND
     extend the live loop.
   - Hook: add columns `price_5d_later`/`price_20d_later` to `alert_history`
     (`db.py:94-107`) and `outcome_price_5d`/`outcome_price_20d` to
     `decision_snapshots` (`db.py:269-282`) via the existing migration path;
     extend the loop tuple at `main.py:1762` and `update_snapshot_outcomes`
     (`db.py:3136-3148`); `get_alerts_needing_price_update` must gate on alert age
     (only fetch once 5/20 trading days have passed); one-time backfill mirroring
     `scripts/backtest.py:285`.
   - Effort: ~half a day.

2. **Build the missing `source_performance` producer.**
   - Unblocks: the I7 `consensus_logodds` switch (left OFF in #32/#42 — it is a
     proven no-op *because this table is empty*), analyst track-record weighting,
     herding/consolidation priors.
   - Finding: the table is read in ~6 places (`db.py:1225`,
     `analysis/consolidation.py:132`, `analysis/herding.py:185`) but has **zero
     writers** — no `INSERT/UPDATE source_performance` exists anywhere.
   - Data: rolling hit-rate per source/analyst per horizon, from labeled outcomes
     joined to `decision_snapshots.sources_json`.
   - Hook: new producer at the outcome-labeling point (`main.py` price loop) or in
     `calibration.retrain`; write into `source_performance` (`db.py:330`).
   - Effort: medium. Can start on 1h/24h; gets much better after Tier-1 #1.

### TIER 2 — point-in-time data that CANNOT be backfilled (every day not logged is gone)
3. **Daily per-ticker implied-vol / expected-move snapshot.**
   - Unblocks: the per-ticker option-surface the top/bottom detector wanted but
     couldn't get free (#47 — VRP, IV-rank, dealer-gamma; its research file
     `vol-indicator-accuracy-research.md` explicitly says "can't backfill, collect
     NOW"); plus `!em` calibration (#51).
   - Data: ATM implied vol, straddle-implied expected move, spot — per watchlist
     ticker, once daily.
   - Backfillable? NO — yfinance exposes only the current snapshot. The math
     already runs in `consensus_engine/scanners/expected_move.py` but is **never
     persisted**.
   - Hook: new `iv_snapshots` table + a daily timer calling the existing
     expected-move math over the active watchlist ∪ liquid core.
   - Effort: low-medium (computation exists; add storage + timer).

4. **Realized-move vs implied-expected-move** (pairs with #3).
   - Unblocks: `!em` calibration ("did the move stay inside the implied band?") +
     a per-ticker vol-risk-premium signal.
   - Realized side backfillable; the implied side is #3 (not) — so this only works
     if #3 starts now. The forward loop from Tier-1 #1 fills the realized side.

5. **FRED HY-OAS daily log + persist the E2 cross-asset shadow ratios.**
   - Unblocks: the E2 `cross_asset` master-flip decision + any credit-regime feature.
   - Findings: credit leg uses FRED `BAMLH0A0HYM2` (`analysis/cross_asset.py:66`),
     but FRED now serves only a rolling ~3-year HY-OAS window (older =
     non-backfillable). The E2 shadow path currently logs ratios **journal-only**
     (`cross_asset.py:281,288,322,329` are `log.info("[E2 shadow]…")`) — nothing
     lands in the DB, so the master-flip blast-radius can't be analyzed.
   - Hook: in the shadow branch of `cross_asset.py`, write a row to a small
     `cross_asset_shadow` table instead of only `log.info`. (FRED key is now in
     `.env.service` per #32.)

### TIER 3 — cheap, direction less certain
6. **Stocktwits retail-sentiment time series** — % bullish, message volume,
   watcher count per ticker, timestamped. Now fetched live for `!all` and
   discarded (Cloudflare-gated, no clean free history → must log forward). New
   `stocktwits_sentiment` table.
7. **EPS-revision counts time series** — up/down revision counts (30d) per ticker,
   timestamped. yfinance gives only the current snapshot; fetched for `!all`, not
   stored.

## Do NOT forward-log these (backfillable later — build the producer when the feature is built)
- Options-flow predictive value (#18): `options_flow` stores `spot` at detection
  (`db.py:438-453`) but no forward price — backfillable from `ticker`+`detected_at`.
- YouTube setup/catalyst accuracy: `youtube_setups` (`db.py:457-476`) has no
  outcome — backfillable.
- Insider-cluster edge: `form4_clusters` (`db.py:555-567`) — backfillable.

## Already collected forward — do NOT rebuild
`regime_daily`, CBOE put/call + NYSE up/down volume (vol Track-B), FINRA short
volume, `apewisdom_mentions`, `wolf_call_outcomes`, and the 1h/24h outcomes.

## Recommended order
1 → 2 first (cheapest, unblock the most, #2 leans on #1). Then 3 → 4 → 5 (true
point-in-time data lost every day it isn't logged). Then 6 → 7. Start Item 1
today so the 2–3 month data clock begins.

## Open questions
- IV-snapshot universe: active watchlist ∪ liquid core, or wider?
- Retention/size policy for the new tables.

## Related items
- #47 (market top/bottom detector) — main beneficiary of Tier-2 #3 + the options history (#56).
- #56 (buy 2yr options history) — the paid-data companion to this forward-logging.
- #18 (options flow) — backtestable via #56, not via forward-logging.
- #32 / #42 (signal switches) — Tier-1 #2 unblocks the OFF "I7" switch.
