# Grade the options-flow buy/sell-side tag against real outcomes

**Status:** OPEN
**Created:** 2026-08-09

## CURRENT STATUS (2026-08-24)

Returned to active after the soak ended. A fresh rerun against the live database found 78
cases where the side-aware direction changed the old call/put-only guess. It
was correct on 57.7% (`z=1.36`), which is encouraging but still could be luck.
Keep collection and the current live label unchanged. Do not call this a proven
trading edge. The next concrete check is when the disagreement sample reaches
at least 165 cases, roughly double today's sample.

## Earlier status (2026-08-09)

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

**The 2-week grading check is scheduled, not manual.** `scripts/grade_options_flow_side.py`
(new this session) plus a systemd timer (`task_1786293326_e1bc93`, confirmed
`enabled`/`active (waiting)`) fire on 2026-08-23 09:00 PDT and write the
verdict to `notifications.log` — no session needs to remember to check.

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

### Session notes — 2026-08-09
- **Worked on:** Built and shipped the whole options-flow buy/sell-side +
  SWEEP-tier feature (TDD, full regression gate, engine restart, real-data
  verification). Then built and scheduled the autonomous 2-week grading check
  after the user asked whether it would happen without them remembering.
- **Decisions:** User chose to ship `side_labels_live: true` immediately
  rather than wait for grading (told plainly this means the label is live
  ungraded). User chose "🔥 SWEEP" as the tier label, no disclaimer footer.
  25% of the bid-ask spread confirmed as the buy/sell threshold.
- **Next:** Nothing to do manually — `task_1786293326_e1bc93` fires
  2026-08-23 09:00 PDT and writes its verdict to `notifications.log`. A future
  session should just read that when it shows up. Also worth re-checking the
  timer is still armed as that date nears (see reliability caveat above).

### Grading result — 2026-08-23 Pacific

- Re-ran `python3 scripts/grade_options_flow_side.py --report` against the live
  database rather than trusting the scheduled notice. The current sample is
  78 disagreement events, and the side-aware direction was correct on 57.7%.
- This is encouraging but still not clearly better than chance (`z=1.36`).
  Keep collection and the current live label unchanged. Do not promote this
  result as a proven trading edge. Re-grade after the disagreement sample has
  grown materially.
