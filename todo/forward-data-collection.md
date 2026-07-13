# Start saving the data future features need to test on

**Status:** OPEN — loggers LIVE (2026-06-29, commit 8e28f23) — Tier-1 Items 1+2 + Tier-2 #3/#5 deployed; both daily timers running and all four tables filling forward. Analyst scorecard (Tier-1 Item 2) runs SHADOW-only in `source_performance_shadow` (live `source_performance` intentionally empty); promotion to live is a manual soak-gated decision (would fire 3 scoring flags) — shadow-delta analysis run 2026-07-03, see notes below. STILL UNBUILT (①): Tier-2 #4 realized-vs-implied + Tier-3 #6 stocktwits / #7 EPS-revision loggers. (Prior "deploy + soak pending" was written pre-deploy — stale.)
**Created:** 2026-06-28

**CURRENT STATUS (2026-07-12):** The catalyst scorecard (#55 rebuild) is BUILT and fully plumbed: posts with a real catalyst are graded against their own sector (169 scored calls, 60 fully graded), a nightly timer re-grades automatically at 4:30pm PT (`catalyst-grading.timer`, failure → Discord alert), long-tail tickers resolve via a Yahoo sector fallback (skips 38→2), and the scores display live in Discord (`!catalysts`, plus small-sample-adjusted rates on `!leaderboard`). Display-only — nothing feeds live alert scoring yet. Next concrete step: re-run the shadow-delta/promotion analysis once the catalyst table accrues enough graded rows (the 2026-07-03 HOLD below still stands).

**➡️ 2026-07-11: user gave the scoring framework to BUILD from — see "User direction — 2026-07-11" at the bottom of this file. That is now the design goal (catalyst-classified, sector-relative scoring), superseding the earlier "just repoint 1h→24h / HOLD" framing. A fresh session should plan from it.**

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

### Session notes — 2026-07-03 (scorecard shadow-delta analysis)
- **Worked on:** the promotion decision-support the 2026-07-02 audit asked for — quantify the blast radius of promoting the analyst scorecard SHADOW→LIVE (read-only DB analysis; nothing changed).
- **Verdict: HOLD.** Framing correction: `per_analyst_cooldown`, I2 `analyst_accuracy_weight`, and I10 are ALREADY `enabled:true`; they no-op only because the live `source_performance` table is empty (0 rows), so "promotion" = populating that table (copy shadow→live / repoint readers), NOT flipping a switch.
- **Why HOLD:** at the **1h** horizon all three flags read, no analyst beats a coin flip at 95% confidence — max Wilson lower-bound **0.484 < 0.50** (unusual_whales, n=48). Replaying the last ~2.7 months (3,126 snapshots, 67 STRONG): I2 is downside-only (all 18 eligible analysts weight < 1.0) → **4 STRONG demotions (QCOM ×1, META ×2), ~1.5/month**; `per_analyst_cooldown` = **0** suppressions; I10 = **0** (all 67 STRONGs already carry hard evidence, and no analyst LB reaches the 0.65 rescue bar); I7 stays OFF (needs code + ≥2 clusters, not a data decision). So promoting today = pure downside, no upside.
- **Two cheap prep steps before any future promotion:** (a) repoint `get_analyst_precision`/`_lb` from `'1h'` (the producer's own docstring calls it "near-random") to the honest `'24h'` — no effect today (table empty) but the correct base to grade on; (b) gate promotion on a real stat threshold (≥1 analyst Wilson-LB > 0.50 at the used horizon — the current leader needs ~n≈120 1h samples vs 48 today, ~2.5×), then a ~2-week shadow-compare soak on the demotion set.
- **Next:** let the 3 live loggers accrue; revisit promotion only after the stat gate clears. The horizon-mismatch repoint (a) is the highest-value cheap follow-up if/when promotion is on the table.

### User direction — 2026-07-11 (how to build the analyst scorecard — plan from this)

The user gave the scoring framework. A new session should turn this into a plan (design + adversarial review) before building.

**Core idea:** don't score every analyst post. Only score posts that carry a real, directional catalyst, and score short-term vs long-term catalysts differently.

**Step 1 — classify the post first (is there anything to score?).**
After reading the analyst's post, decide what kind of price-mover it is:
- **Short-term catalyst** (should move the price soon): unusual options activity, merger/acquisition, new product *release*, lawsuit, company scandal.
- **Long-term catalyst** (moves the price slowly): solidifying competitive moat, a pattern of rising forward guidance, a new product not shipping for 1+ years.
- **Neither / can't tell:** it's just news, not a catalyst or a directional bet → **nothing to score on that post.** Skip it.

**Step 2 — scoring a SHORT-TERM catalyst.**
- Look at the stock's **daily and weekly % change over the next 30 days.**
- If the stock moves **in the analyst's direction more than its sector does**, it's a **win.**
- The **wider the margin vs the sector, the bigger the bonus** on that win. (So beating the sector by a lot > beating it by a little.)
- (Sector = measure against the stock's sector/peer benchmark, not the raw move — a stock rising because the whole sector rose is not the analyst being right.)

**Step 3 — scoring a LONG-TERM catalyst.**
- Track it over a **longer period.** Decide *smartly* how — the session designs this:
  - Daily stats probably don't need to be recorded for these (too noisy over a long horizon).
  - If the catalyst is **too vague or too unlikely**, it may not be worth tracking at all — **don't** open a scoring "bet" on it. Save resources for higher-probability bets.

**Open design questions for the planning session:**
- What classifies a post as short vs long vs no-catalyst? (Likely an LLM classification step on the post text — the bot already extracts structured fields from tweets.)
- Exactly which sector/peer benchmark to compare against (there's a coarse sector map and a finer peer-group file already).
- How to size the sector-margin bonus (linear? capped?).
- Long-term: what horizon, what checkpoints, and the vague/unlikely cutoff that means "don't track."
- How this new per-post catalyst score relates to the existing (near-random 1h/24h) analyst-precision tables — replace, or run alongside.

This supersedes the "just repoint 1h→24h" framing as the *goal*; that repoint may still be a cheap sub-step, but the real design is the catalyst-classified, sector-relative scoring above.

### Session notes — 2026-07-12 (#55 catalyst scorecard BUILT, commit 7edf7a4)

Built the catalyst-relative analyst scorecard (discover run `todo-55-20-plan`). It runs
**alongside** the near-random 1h/24h `source_performance`, not instead of it — promotion
is a later, separately-gated decision (same HOLD pattern as `source_performance_shadow`).

- New: `consensus_engine/analysis/benchmark_grading.py` (shared spine), `scripts/grade_analyst_catalysts.py`.
- New SHADOW tables: `analyst_catalyst_scores`, `long_term_catalyst_bets`.
- `models/text_model.py` now labels each post's `catalyst_horizon` / `catalyst_kind` / `catalyst_likelihood`.
- A win = the stock **beat its sector/peer ETF** over the same 21 sessions. Rising with the sector is not a win.
- First real run (260 LLM calls): 43 short rows, 28 graded, 14 long-term bets opened.
  **152 of 260 posts (58%) carry no directional catalyst at all** — the existing scorecard grades
  all of those, which is the mechanical reason it reads near-random. Premise now measured, not asserted.
- Coverage limit: 38 of 260 posts skipped, no benchmark (34 tickers: RKLB, HIMS, IREN, LULU…).
  yfinance `.info['industry']` fallback deferred to v1.1 (plan graft 6).

**Owed:** shadow-delta analysis before promotion · `eb_shrunk_precision()` is built + unit-tested but
has **no caller** (no live catalyst display yet) · no nightly timer yet (runs on demand).
Full log: `.claude/discover/todo-55-20-plan/pass-5-execution-log.md`.

### Session notes — 2026-07-12 later (#55 three leftover gaps CLOSED, same day)

1. **Display wired.** New `!catalysts` Discord command (catalyst scorecard: raw "X of N" +
   EB-shrunk "adjusted" % + `eb_shrunk_precision` "all calls" contrast column) and an
   "adj 24h" column on `!leaderboard`. Display-only; the Wilson-LB promotion gate is
   untouched. Proven live: real `!catalysts` / `!leaderboard` messages answered in #chat.
2. **Nightly timer live.** `catalyst-grading.{service,timer}` (repo copies in `scripts/`),
   23:30 UTC nightly, `Persistent=true`, `OnFailure=alert@%n` → #errors-style Discord alert.
   Two grader bugs fixed en route: (a) classification cache key used salted `hash()` — the
   disk cache could NEVER match across runs, so every nightly would re-buy the same LLM calls
   and the oldest-first cap would starve new posts (now sha1, content-only); (b) an LLM outage
   was cached as "no catalyst" forever (now retried next run; wholesale failure exits non-zero).
3. **Benchmark fallback live.** `resolve_benchmark_dynamic()`: curated tables → shared 30-day
   sector cache → one Yahoo lookup → sub-industry group (RKLB→ITA) or sector ETF (HIMS→XLV);
   still never guesses SPY. Backfill re-run: unresolvable 38→2 (CRBL dead, SOXL leveraged ETF —
   correct skips), 52 posts graded via the fallback, scorecard 43→112 rows (57 graded).

**Still owed (unchanged):** shadow-delta analysis before any promotion into live scoring.
