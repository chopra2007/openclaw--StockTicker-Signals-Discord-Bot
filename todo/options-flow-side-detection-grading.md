# Grade the options-flow buy/sell-side tag against real outcomes

**Status:** SOAKING
**Created:** 2026-08-09

## CURRENT STATUS (2026-08-09)

Built and shipped LIVE this session — not gated behind a grading step. Full
detail in `.omc/plans/options-flow-buyresell-sweeps-spec.md`.

**What shipped:**
- `classify_flow_side(last_price, bid, ask)` — tags every options-flow hit
  BUY / SELL / AMBIGUOUS from the trade price vs. the same-snapshot bid/ask
  (within 25% of the spread from the ask = BUY, 25% from the bid = SELL,
  middle 50% = can't tell). Fails to AMBIGUOUS on any bad/missing quote.
- `#options-flow` alerts: BULLISH/BEARISH now comes from buy/sell-side ×
  call/put (a big SELLER of calls is bearish, not bullish — the old code
  guessed from call/put alone and got that backwards) — this is
  `options_flow.side_labels_live: true`.
- A real "🔥 SWEEP" tier for the rare, higher-conviction case: vol/OI ≥ 50x
  (the measured strongest bucket from #57's grading) AND an aggressive fill
  (trade printed at-or-through the ask/bid, not just near it). Replaced the
  old dead `_is_sweep` code that was never wired to anything.
- Every alert also gets an additive `side: BUY (at-ask)` tag either way.

**Why it's marked SOAKING, not DONE:** the user asked to ship the side-aware
BULLISH/BEARISH label live immediately rather than wait ~2 weeks and grade it
first (the original, more cautious plan). So it's live and UNGRADED — we
don't yet know if buy/sell-side actually predicts direction better than the
old call/put-only guess.

**Verified this session (real data, market closed — Sunday):**
- Ran the live scanner against real yfinance option chains (AAPL, NVDA,
  TSLA, SPY, QQQ, etc.) — confirmed real bid/ask flow through, side
  classification is correct, and 3 real contracts (TSLA/QQQ puts sold below
  bid) hit the SWEEP tier with the right label.
- The new `flow_side`/`bid`/`ask` columns landed cleanly on the LIVE
  production database (migration confirmed via `sqlite3`).
- Full regression suite: 3126 passed, 0 failed.

**NOT verified this session (owed, market was closed):**
- A real `#options-flow` alert actually posting in Discord with the side tag
  during live market hours.
- A real production DB row landing with non-null `flow_side`/`bid`/`ask`
  from the engine's own autonomous scan loop (not a manual script).

## Next steps

1. **Monday market open:** confirm a real live alert posts with the side tag
   and the DB is collecting real `flow_side`/`bid`/`ask` rows organically.
2. **Autonomous 2-week check — already scheduled, no action needed:** a
   systemd timer (`task_1786293326_e1bc93`, created 2026-08-09) fires
   `/root/task_system/scripts/notify_options_flow_side_grading.sh` on
   **2026-08-23 09:00 PDT**. It runs the new `scripts/grade_options_flow_side.py
   --report` and writes the verdict to `/root/task_system/notifications.log`,
   which surfaces automatically the next time a session starts (existing
   convention, CLAUDE.md). Verified armed at creation time:
   `systemctl status task_1786293326_e1bc93.timer` showed `enabled` /
   `active (waiting)`.
   - Methodology: cluster to 1 event per ticker-day-side (same anti-drift
     trick as #57's original grading), then look ONLY at events where the new
     side-aware call disagrees with the old call/put-only guess — that's the
     one number that actually says whether the tag helped or hurt.
3. If the grading says side-aware is WORSE, that's a real finding worth
   acting on — the label is live now, so a bad call has been showing up in
   real alerts since 2026-08-09, not just sitting in shadow data.

## Reliability caveat (found while setting this up — separate issue, not fixed)

The deferred-task system has at least one stale entry: task `1782704382_12c893`
(scheduled 2026-07-05, `notify_reliability_soak.sh`) is still `pending` in
`/root/task_system/tasks.db`, its timer now shows `disabled`/`inactive`, and
there's no log file — meaning it likely never actually fired. Root cause not
investigated (out of scope for this session). Worth checking
`systemctl status task_1786293326_e1bc93.timer` again as 2026-08-23
approaches, rather than blindly trusting it fires.

## Files involved

- `consensus_engine/scanners/options.py` — `classify_flow_side`, `_flow_tier`,
  `format_flow_alert`
- `consensus_engine/models.py` — `FlowHit.bid/.ask/.flow_side/.flow_side_note`
- `consensus_engine/db.py` — `options_flow.flow_side/bid/ask` columns,
  `insert_options_flow`
- `config/consensus.yaml` — `options_flow.side_collect`,
  `options_flow.side_labels_live`, `options_flow.sweep_vol_oi`
- `tests/test_options_flow.py` — full coverage of the above
