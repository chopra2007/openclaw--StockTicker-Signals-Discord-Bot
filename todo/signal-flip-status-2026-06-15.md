# Flip status — what's switched ON, what's still OFF, and how to turn the rest on

**Status:** OPEN (the OFF items below are the remaining work)
**Created:** 2026-06-15

Single source of truth for every switch touched or considered in the `todo-sweep-2026-06-13`
build (executed 2026-06-15). Plain-English first, exact config key in `code font`.

---

## ✅ Switched ON this session (LIVE)

| Switch (config key) | What it does | Proof it's safe |
|---|---|---|
| **Wolf direction guard** `wolf.direction_guard.enabled` (was already on; the RULE TEXT was rewritten) | Reads a "bounce up to a level from below + topping pattern" as a SHORT, not a buy; stops "200-day" becoming a fake $200 target | A/B 10×/email on 5 real emails: wrong IGV-buy 5/10 → 0/10; S&P/Nasdaq 9/9 buy → 8/7 sell; controls unchanged |
| **Wolf staleness sweep** `wolf.staleness.enabled` | Nightly: retires (hides, doesn't delete) calls Wolf has gone quiet on | First live run retired 8 genuinely-stale calls, left fresh ones |
| **EPS-revision field** `features.snapshot.eps_revisions` | `!all` shows "EPS rev 34↑ 3↓ (30d)" — analysts raising/cutting estimates | Live `!all NVDA`/`TSLA` rendered it; runs <34s |
| **Stocktwits field** `features.stocktwits_sentiment.enabled` | `!all` shows "💬 Retail 74% bullish · +1/5d · 650k watching" | Live `!all NVDA` rendered it (fetched via `requests` — Cloudflare blocks the bot's normal fetcher) |
| **Chat memory** `chat_memory.enabled` | Saves redacted summaries of past chats so the bot can recall month-old conversations after a restart | Live: bot correctly recalled a ~May-20 conversation; 0 secret leaks; hallucination-trap refused |
| **Weighted Wolf votes** `wolf.confluence.weighted_votes_enabled` (I15) | Down-weights stale/duplicate agreeing sources in the Wolf confluence score | Dry-run on the 17 live theses: 0 tier changes, 0 new @-ping alerts |
| **FINRA short-volume term** `features.finra_short_volume.enabled` (E1) | Adds up to +5 confluence when short-volume spikes on a bullish call | Replay over 1873 past alerts: ≤177 candidates, +5 cap, **0 alerts change today**; fails safe on stale data. ⚠️ see caveat below |

**Also applied (config on disk, takes effect on the bot's NEXT restart):** OpenClaw transcript
hygiene — `truncateAfterCompaction: true`, `maxActiveTranscriptBytes: "5mb"` (stop the live
chat file ballooning), and repointed `memorySearch.extraPaths` to the live memory folder
(was a stale May-5 copy).

### ⚠️ Caveat on E1 (FINRA)
E1 is ON but **inert until a trading day delivers fresh data**. The short-volume data only
refreshes on weekdays (FINRA doesn't publish weekends), and the term ignores data older than
24h. The build added the missing daily fetch loop (`finra_short_volume_loop`), so it will start
firing on the next trading day. No action needed — just know it does nothing over the weekend.

---

## ⛔ Still OFF — why, and what's needed to turn each on

All of these are #32 "Phase-2" signal-scoring switches. The plan AND the outside-model review
require them to go on **one at a time, after the first one (I4-full) has soaked** — never
bundled — because they change live alert behavior and a simultaneous flip would be an
un-debuggable alert storm.

| Switch (config key) | What it does | Why it's OFF | What's needed to flip it ON |
|---|---|---|---|
| **I4-full** `features.single_score.enabled` | Unifies the bot's two different score numbers into one | Changes the decision score for EVERY signal (highest blast radius); it's the gate the next three depend on | Build/run an I4-full replay (old vs new score vs alert tier), review the delta, then flip it ALONE and watch a few days |
| **I3 contradiction** `features.contradiction_index_live.enabled` | Down-grades a signal when sources flatly disagree | Must wait until AFTER I4-full (else it activates together with I10 + E2-VIX = alert storm) | After I4-full soaks: flip alone, watch |
| **I10 hard-evidence** `features.strong_requires_hard_evidence.enabled` | A "STRONG" alert must have a hard technical component | Only meaningful after I4-full unifies the scores; same one-at-a-time rule | After I4-full soaks: flip alone, watch |
| **E2 VIX multiplier** `features.cross_asset.enabled` | ±15% score nudge based on the volatility term structure | Turns on a LIVE multiplier + its log at once (no shadow-first), proven on only 1 data point, and ±15% can push a score across the alert line | Flip LAST, after I4-full + an offline replay across calm AND stressed VIX regimes (better: add a true shadow-only mode first) |
| **E2 FRED leg** `features.cross_asset.fred_leg_enabled` | Credit-spread confirm/veto from Fed data | **Unbuildable** — no FRED API key and zero code behind it | Register a free FRED key, then build the leg |
| **I7 consensus log-odds** `features.consensus_logodds.enabled` | Scales score by how many independent sources cluster | A pure no-op today — the consolidation engine runs in shadow-only mode and every event is single-cluster | Build the enabler: take consolidation out of shadow-only so multi-cluster events occur, then flip |
| **I14 regime widening** `features.regime_widening_graduated.enabled` | Widens alert thresholds during market panic | A pure no-op today — the `regime_daily` table is empty, so the classifier never reaches "panic" | Build the enabler: seed `regime_daily` with 252-day volatility history, then flip |
| **I13 ApeWisdom z-surge** `features.apewisdom_zscore.enabled` | Flags unusual Reddit/Stocktwits mention spikes | **Data-blocked** — needs a 14-day baseline per ticker; only ~5 days exist (started ~June 10), and there's no historical backfill | Wait until ~**2026-06-24** for enough days to accumulate, re-check the spike distribution, then flip |
| **Alert score floor** `alerts.min_base_score_for_alert` (I9) | A minimum score before any alert fires | Deliberately held at **0** — raising it deletes ~98% of real tentative analyst calls (that's signal, not noise) | Leave at 0 (per the analyst-tweet-register finding) |

---

## Cross-references
- Broader Phase-2 context: `signal-features-phase2.md` (#32).
- Wolf direction/staleness detail: `wolf-hedged-stance-and-stale-theses.md` (#26).
- `!all` levers: `all-command-quality.md` (#6).
- Chat memory: `bot_chat_memory_redesign.md` (#39).
- Full run record: `.claude/discover/todo-sweep-2026-06-13/`.
