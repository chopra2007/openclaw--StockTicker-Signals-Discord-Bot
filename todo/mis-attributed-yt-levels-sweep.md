# Sweep mis-attributed YouTube levels/setups + gate !all trade-plan targets

**Status:** OPEN
**Created:** 2026-06-09

## What happened
Turning on the !all features at session close surfaced a live bug: `!all NVDA` showed
**TP3 $700** on a $208 stock. Root cause: YouTube video `P5E-8qlhwws` (channel StockedUp,
2026-06-08) is a MULTI-TICKER video whose QQQ/SPY/index numbers (700–760) got dumped onto NVDA
— stored in BOTH `youtube_levels` (ids 469/472/474/475/476 = 700–740) AND `youtube_setups`
(id 18, targets `[742,735,720,700]`). The !all trade plan pulled TP1/2/3 straight from that
setup. This is the SAME class as the purged NVDA-850 hallucination, but item B's purge only
anchored on 5 specific video_ids and missed this one.

## What I fixed this session (immediate, visible bug)
- Suppressed `youtube_levels` NVDA ≥ $400 (the 700–740 set) → `suppressed=1`.
- Suppressed `youtube_setups` id 18 (the NVDA 700-target setup) → `suppressed=1`.
- Verified: `!all NVDA` TP3 now $234.73 (sane, near the $208 price). SMART LEVELS live, clean.
- B3 per-number ticker tagging is now ON, which PREVENTS this mis-attribution going forward.

## What's still open (didn't do at close)
1. **Sweep the rest of `P5E-8qlhwws`** — it also has QQQ (425–760), SPY (500–756), MSFT
   (256–500) levels. Those are within ~2x of each ticker's price so they're borderline, but
   the video demonstrably scrambled tickers, so the whole video's output is suspect. Decide:
   suppress the entire video's levels/setups, or verify each ticker.
2. **Sweep ALL stored youtube_levels/setups for wild values** — apply item C's gate logic
   (≥2x or ≤0.5x the ticker's live price) to the STORED data as a one-time cleanup, not just at
   display. There may be other mis-attributed levels beyond StockedUp.
3. **Gate !all's trade-plan targets through the level-sanity check (item C extension).** Item
   C's design decided "!all is safe by ranking" and did NOT filter !all. This bug proves that
   wrong — a mis-attributed setup target reached TP3 unfiltered. Add `classify_level`/
   `filter_levels_for_display` (or the ≥2x/≤0.5x gate) to the trade-plan target selection in
   `consensus_engine/alerts/all_command/levels.py` (TP1/2/3 padding ~line 1548/1698) and the
   setup/level read in `aggregator.py:1105`, so a wild target can never reach the trade plan
   even if the underlying data is bad.

## Files
- `consensus_engine/alerts/all_command/levels.py` (tp1/2/3 build, ~1548/1689/1698)
- `consensus_engine/alerts/all_command/aggregator.py` (~1105 trade_plan)
- `consensus_engine/analysis/level_display_sanity.py` (the gate to reuse)
- DB: `youtube_levels`, `youtube_setups` (suppressed flag)

## Note
The suppressions above are in the LIVE consensus.db (not in git — DB is gitignored). If the DB
is ever restored from a pre-2026-06-09 backup, re-apply them.
