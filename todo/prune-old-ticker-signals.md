# Prune old ticker_signals to shrink the DB + backups — ONLY if the old rows are truly useless

**Status:** OPEN
**Created:** 2026-07-05

## ⚠️ HARD REQUIREMENT — investigate before deleting (user directive)
Do NOT delete anything until you have PROVEN the old signals have no use. This deletes a lot of
data (3.35M rows), so the burden of proof is on "safe to delete," not "probably fine." Check and
THINK about whether anything — a live query, a backtest, the eval module, a future feature, or the
historical record itself — actually reads the old/expired rows. **Only if they are genuinely
useless is this feature warranted.** If any real use exists, either don't build it, or ARCHIVE
(move to a compressed side table / export) instead of deleting.

## Why it looks attractive (verified 2026-07-05)
- `ticker_signals` = **368 MB of data + ~170 MB of indexes ≈ 83% of the entire 644 MB DB** (biggest
  table by far; a "signal row" = a saved record that a source mentioned a ticker).
- 3,354,028 rows spanning 2026-04-07 → now (~3 months).
- **3,350,026 rows (99.88%) are already PAST their `expires_at`; only ~4,002 are still live.** On the
  surface the working set is tiny and the rest is an expired firehose log.
- Pruning/archiving the expired rows would likely cut the DB — and every nightly backup — by MORE
  THAN HALF (backups are currently ~616 MB × 7).

## The investigation checklist (do ALL of this first)
1. **Read every consumer of `ticker_signals`** and determine if any reads rows OLDER than the live
   window (i.e. relies on expired history):
   - `consensus_engine/db.py`, `consensus_engine/main.py`,
     `consensus_engine/scanners/gmail_watcher.py`, `consensus_engine/scanners/finra_short_volume.py`,
     `consensus_engine/research/sources.py`, `consensus_engine/alerts/commands.py`,
     `consensus_engine/analysis/_deprecated/regime_detector.py` (the `_deprecated` one may be dead —
     confirm it's not imported).
   For each: does its WHERE clause filter to live/recent rows only, or does it ever scan history?
2. **Check the eval/backtest path** — `consensus_engine/eval/` and any backtest/replay work
   (options-history, forward-loggers, #55/#56) may want the raw signal history for future analysis.
   Deleting it forecloses backtests we haven't built yet. Decide if that history has research value.
3. **Confirm the expiry semantics** — `expires_at` is a per-signal TTL; verify an "expired" signal is
   truly done being used (not just past a soft display window that some code still reads).
4. **Decide delete vs archive** — if the rows have any plausible future value (backtests, audit),
   ARCHIVE them (e.g. `VACUUM INTO` a signals-history file, or move to a compressed table) rather
   than hard-delete. Only hard-delete if provably useless AND unrecoverably low-value.

## If (and only if) it clears the bar — build it
- Add a retention step to the EXISTING nightly maintenance job (`/root/task_system/scripts/db_maintenance.sh`)
  that runs the agreed policy (e.g. `DELETE FROM ticker_signals WHERE expires_at < now - <grace>`),
  in a transaction, then a `VACUUM INTO` so the file actually shrinks (a plain DELETE frees pages but
  doesn't shrink the file in WAL mode).
- Do it in stages (e.g. delete >90d first, watch), keep a pre-prune backup, and confirm the live
  ~4k-row working set and all 7 consumers still behave (drive `!all` + a scan cycle after).
- Measure the before/after DB + backup size and log it.

## Open questions
- Is the `_deprecated/regime_detector.py` reader actually imported anywhere, or dead code?
- Do we want to KEEP a downsampled/archived copy of signal history for future backtests, even if we
  prune the live table?
