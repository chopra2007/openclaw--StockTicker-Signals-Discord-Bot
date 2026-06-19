# Phase-3 follow-up — judge the forward-collected data (TODO #47)

Phase 3 was an honest NO-GO on free data (see `backtest/PHASE3-REPORT.md`). The real bet is the
Track-B forward-collection now running daily (`vol-collect-daily.timer`):
- `CBOE_PUTCALL` — put/call ratios (total/equity/index/etp)
- `NYSE_BREADTH` — true NYSE adv/dec issues **and UP/DOWN VOLUME** (what ABINYSE lacks)

These can't be backfilled, so they accumulate forward. A scheduled reminder fires ~2026-09-19.

## When enough history exists, do this (each is a small, frozen, pre-registered change):
1. **Refresh + check coverage:** `python3 -m src.run_update` (and confirm the daily timer kept
   collecting): `python3 -c "from src.data import store; print(store.provenance('CBOE_PUTCALL')['rows']); print(store.provenance('NYSE_BREADTH')['rows'])"`.
   Note: NYSE_BREADTH is forward-only — ~63 rows after 3 months is a FIRST LOOK, not a full
   backtest; the up/down-volume Lowry leg likely needs 6-12 months to be testable.
2. **Add a put/call leg to the TOP watch-state:** in `src/signals/conditions_phase3.py`,
   `watch_state_components()`, append e.g. `"putcall_fear": U.trailing_percentile(CBOE_PUTCALL_total, 252)`
   (high put/call = fear; decide orientation and pre-register it). Add `CBOE_PUTCALL` to `_SERIES`
   in run_phase3.py's `_ALL` and to `store.load_panel`.
3. **Add a Lowry 90/90 up/down-VOLUME leg to the BOTTOM detector:** in `b_thrust`, OR-confirm the
   thrust with a Lowry signal from `NYSE_BREADTH` (up_volume/(up+down) >= 0.90 on the thrust day,
   or 80/80 back-to-back). This is the genuinely-new signal the broad-US ABI feed couldn't provide.
4. **Freeze a new pre-registration** (`preregistration_phase4.yaml`) BEFORE scoring — copy the
   Phase-3 contract, add the new legs/cells, keep the 7-gate kill-gate + alert budget.
5. **Re-run:** `python3 -m src.run_phase3` (or a phase4 runner) and read the GO/NO-GO per side.
   Add `tests/test_lookahead_phase3.py` entries for any new construction first (the look-ahead test
   is load-bearing). Full suite must stay green.

## Honesty bar (unchanged): opportunity-set null + temporal hold-out + QQQ transfer + benchmark
battle + alert budget. A NO-GO is fine — ship descriptive-only. If the put/call leg helps the top
watch-state's QQQ transfer clear significance, that's the first real signal worth pursuing.

The descriptive complacency gauge already shipped: `python3 -m src.show_fragility`.
