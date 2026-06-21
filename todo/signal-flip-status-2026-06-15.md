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
| **FINRA short-volume term** `features.finra_short_volume.enabled` (E1) | Adds up to +5 confluence when short-volume spikes on a bullish call | Replay over 1873 past alerts: ≤177 candidates, +5 cap, fails safe on stale data. **LIVE+firing 2026-06-15** — fresh daily data, 2 tickers (CRWV, SMH) qualify today |
| **FRED HY-credit leg** `features.cross_asset.fred_leg_enabled` (E2-FRED) | Second regime leg: down/up-weights bullish alerts when high-yield credit spreads widen (stress) / tighten (calm) | BUILT 2026-06-15 (key provided). 24 unit tests pass; live end-to-end proven (VIX 1.15 + credit 1.023 → 1.086). Leg flag ON but **stays dark** — its master `features.cross_asset.enabled` is still false (see E2 row below) |

**Also applied — NOW LIVE (gateway restarted 2026-06-15 18:58):** OpenClaw transcript
hygiene — `truncateAfterCompaction: true`, `maxActiveTranscriptBytes: "5mb"` (stop the live
chat file ballooning), and repointed `memorySearch.extraPaths` to the live memory folder
(was a stale May-5 copy). All under `agents.defaults` in `openclaw.json`. Gateway came back
healthy on a fresh boot; a live @-mention healthcheck got a reply, so the restart was clean.

### ✅ E1 (FINRA) caveat RESOLVED — now firing on fresh data
E1 was inert over the weekend (FINRA doesn't publish Sat/Sun, term ignores data >24h old).
As of **Mon 2026-06-15**: the daily fetch loop pulled today's file (5,558 rows, latest
published ~3h ago), and **2 tickers (CRWV, SMH) already qualify for the +5** short-squeeze
boost. The weekend caveat no longer applies — E1 is doing real work.

---

## ⛔ Still OFF — why, and what's needed to turn each on

All of these are #32 "Phase-2" signal-scoring switches. The plan AND the outside-model review
require them to go on **one at a time, after the first one (I4-full) has soaked** — never
bundled — because they change live alert behavior and a simultaneous flip would be an
un-debuggable alert storm.

| Switch (config key) | What it does | Why it's OFF | What's needed to flip it ON |
|---|---|---|---|
| **I4-full** `features.single_score.enabled` | Unifies the bot's two different score numbers into one | ✅ **FLIPPED ON 2026-06-21** (user "flip on the switch so we can monitor it", #50). Flipped during weekend pause; live signals resume Sun 11:00 PDT, so the soak window starts this afternoon | DONE — now soaking. Watch `grep 'I4-full shadow'` + `!market-view`. Evidence: `.claude/go-live-evidence/features_single_score_enabled.md`. The next three (I3/I10/E2) were the ones waiting on this soak |
| **I3 contradiction** `features.contradiction_index_live.enabled` | Down-grades a signal when sources flatly disagree | Must wait until AFTER I4-full (else it activates together with I10 + E2-VIX = alert storm) | After I4-full soaks: flip alone, watch |
| **I10 hard-evidence** `features.strong_requires_hard_evidence.enabled` | A "STRONG" alert must have a hard technical component | Only meaningful after I4-full unifies the scores; same one-at-a-time rule | After I4-full soaks: flip alone, watch |
| **E2 cross-asset master** `features.cross_asset.enabled` | The ±15% confirm/veto multiplier — now combines BOTH legs: VIX term-structure + FRED HY-credit (averaged, then clamped) | Turns on a LIVE multiplier + its log at once (no shadow-first), and ±15% can push a score across the alert line. Now activates two legs at once | Flip LAST, after I4-full + an offline replay across calm AND stressed regimes covering BOTH legs (better: add a true shadow-only mode first) |
| **E2 FRED leg** `features.cross_asset.fred_leg_enabled` | The credit-spread half of E2 — high-yield spreads widening = stress = veto; tightening = calm = confirm | **BUILT 2026-06-15** (key now in `.env.service`; was the only blocker). Leg flag is ON, but inert because the E2 master above is off | Nothing to build. It comes alive automatically when the E2 master is flipped — so include the credit leg in that one replay |
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

---

## Activation log — 2026-06-16 (run `todo-active-sweep-2026-06-16`, Codex-reviewed)

**FLIPPED LIVE this session (one scoring switch, per policy):**
- **I10 `strong_requires_hard_evidence` → ON** (`consensus.yaml:804`). Downgrade-only (STRONG→WATCHLIST only when a STRONG lacks ALL hard evidence; never creates an alert). Gate passed: backtest `scripts/backtest_i10_hard_evidence.py` = **0/56** historical STRONGs demote (all carry news/sec/options>0); 14-day `[I10 shadow]` = 8 evals, all `would_demote=False`. Regression gate clean (2243 pass, baseline-only failure). Live-verified: real `!all NVDA` renders clean, engine healthy with flag ON.

**ENABLED LIVE (pure-data, no scoring change):**
- **I14-display via `regime_daily` seed** — `scripts/backfill_regime_daily.py` seeded 247 rows (all `normal`), z-correctness gate 10/10 vs pandas. `lookup_regime()` → `normal, shift=0, cold_start=False`. Display now renders `Regime: normal (z=0.1)` (was "warming up"); **zero cutoff change** (shift 0 verified pre-seed). DB backup `consensus.db.pre-regime-bak`. Daily self-healing timer `regime-daily.timer` installed (22:30 UTC).

**STILL OFF — named exceptions (build→test→flip rule):**
- **I4-full `single_score`** — display-cosmetic, 0 tier moves, un-backtestable on stored data (precision total unstored), NOT a keystone (verified: I3/I10/E2 don't depend on it). Low value; leave OFF.
- **I3 `contradiction_index_live`** — inert now (30d `[I3 shadow]` = 0). Flipping arms a **dead-`min_actors` trap** (a single opposing leg ≥0.5 solo-downgrades a STRONG). EXCEPTION: needs a code decision (wire `min_actors` into `evaluate_contradiction`, or sign-off) before flipping.
- **E2 `cross_asset`** — confirm side not backtestable (gating field unstored), veto side needs forward stressed data (legit wait), FRED dilutes VIX, `regime_widening` is a config no-op. OFF.
- **I7 `consensus_logodds`** — needs CODE enablers (no `source_performance` writer; `signal_events` never forms a 2nd cluster), ~0 lift. OFF (defer comment added at `:808`).
- **I13 `apewisdom_zscore`** — data-blocked until ~2026-06-24 (14-day baseline). Reminder scheduled (task `1781606545_cbbbb2`, no auto-flip).
- **I14-widening `regime_widening_graduated`** — **config no-op**: graduated shift clamps to `cutoff_ceiling-base_high = 90-80 = 10` = static panic shift. Inert by config math, not data. OFF.

**Also this session:** #45 agent tool-loop fixed (`main.py` abort-guard on `meta.aborted` + kill orphaned subprocess + `--timeout` 240→120 / outer wait 270→150 + softened steering; live-verified 26s convergence, no stub); `scripts/backtest.py` ALERT-filter fixed (total_alerts 0→1856); #38 orphan transcripts cleared 143→11 (rest = #39); #20 confluence header marked DONE+LIVE; #41 "Built switches default to ON" rule added to CLAUDE.md.
