# OpenClaw Signal Engine — Audit, Research & Tiered Proposals

**Date:** 2026-04-24
**Scope:** Pre-mainstream precision audit of the signal-first retail alert engine at `/root/.openclaw/workspace`.
**Authorship:** Three parallel analysis agents (Audit / Research / Pushback+Proposals) + synthesis pass.
**Drafts preserved at:** `plans/audit-draft-2026-04-24.md` · `plans/research-draft-2026-04-24.md` · `plans/pushback-proposals-draft-2026-04-24.md`.

> **Corrections to pre-verified facts.** Before anything else, three assumptions going into the audit turned out wrong and must not propagate:
>
> 1. **`calibrate()` is NOT dead code by grep — only unreferenced in `main.py` / `cross_reference.py`.** It IS invoked at `alerts/discord.py:101` (the "P(up 1h)" field in every Phase-2 embed) and `alerts/commands.py:876` (`!score`). But the model file `.omc/state/calibration_model.pkl` doesn't exist on disk, so `_load_models()` returns `{}` and `_identity(score) = score/100` is what the user sees labeled "Calibrated conf." This is live-facing but untrained — more dangerous than pure dead code, because it's lying to the user in every Phase-2 embed.
> 2. **SEC watchers aren't "disabled by default" in the abstract.** They were *enabled* from 2026-03-31 to 2026-04-07 and produced **395 of the 575 alerts ever logged (68.7%).** They got flipped off after the 2026-04-07 parser fix and haven't fired since.
> 3. **`reliability_engine.py` source file is MISSING from disk.** Only `consensus_engine/analysis/__pycache__/reliability_engine.cpython-310.pyc` remains. The import at `cross_reference.py:328–330` is guarded by `alerts.reliability_engine_enabled: false` at `config/consensus.yaml:194`. **Flipping that flag true will crash every xref.** Not a disabled feature — a deleted module load-bearing behind a flag.

---

## Executive Summary — "If you only change 5 things this month"

Ranked by `empirical evidence × expected precision/recall lift ÷ engineering cost`. Every claim below is backed by a SQL row count or `file:line` citation in the detailed sections that follow.

1. **Turn calibration on in shadow mode today.** The scoring rubric is empirically broken. Non-SEC alerts at the 30-score band hit 94.1% at 1h (n=17); the 60-band hits 20.6% (n=34). Higher scores are performing **worse** at 1h — non-monotonic. Meanwhile, `calibrate()` at `alerts/discord.py:101` runs on every Phase-2 embed, but the model was never trained, so users see `score/100` labeled as a "Calibrated probability." Q1: ~40 LOC, one flag, shadow-mode logs predictions vs `hit_24h` without suppressing anything — zero rollback risk.

2. **Replace the blanket 6h cooldown with per-analyst precision weighting.** The DB already has the evidence: analyst 1h hit rates range from **14.3% (kpak82, n=7) to 82.9% (TeresaTrades, n=41)**. Meanwhile `check_alert_cooldown()` at `db.py:672–682` is a ticker-level `COUNT(*)` that ignores analyst identity — a confirming tweet from an 80%-hit-rate analyst is dropped because a 14%-hit-rate analyst fired the same ticker 6 hours ago. M3: ~80 LOC, no new dep, reuses `source_performance`.

3. **Fix Phase-2 silent-drop AND the `signal_events` data-coupling bug.** `alert_messages` shows **78.4% of all alerts (451/575) have `followup_msg_id IS NULL`** — three of every four Phase-1 pings never get the promised score breakdown. Current-state (2026-04-20/23) drop rate is 75–89%. Separately, `cross_reference.py:333` reads from `signal_events` which has **23 rows ever, all from one YouTube video** (`4mSyMr8PGLI`); tweets write to `ticker_signals` (252 rows) and are effectively invisible to the xref's canonical query. Q2: `asyncio.wait_for` with the already-declared `cfg.intervals.cross_reference_timeout=120` (`config/consensus.yaml:88`) + explicit "Phase 2 skipped" edit; separately, route tweets into `signal_events` or retarget the xref read.

4. **Exempt HIGH-conviction tweets from `require_market_confirmation` — *and* fix the parser that near-hardcodes `base_score=25`.** The `market_ok` early-exit at `engine.py:294–308` is a *mainstream-confirmation* gate — it filters out the pre-mainstream setups that are the stated product edge. M6 is a one-line exemption, but only bites once the parser actually produces a 20/25/30 distribution: **570/575 alerts (99.1%) have `base_score=25`**, only 3 are HIGH (30). Treat as one combined intervention.

5. **Kill three phantom features.** (a) `max_alerts_per_hour: 10` at `config/consensus.yaml:188` — zero code references. (b) `regime_detector` at `config/consensus.yaml:197–202` declares `enabled: true` with zero call sites in flow files. (c) `reliability_engine_enabled` flag at `config/consensus.yaml:194` — its source file is missing from disk. Configs that lie are worse than configs that don't exist.

---

## Part 1 — Audit

Every claim below is one of: (a) `file:line`, (b) SQL row count from `consensus.db` measured 2026-04-24, or (c) "no evidence in DB — claim is structural." Full SQL appendix in `plans/audit-draft-2026-04-24.md`.

### Source-by-source summary

| # | Source | Current rubric weight | Wired? | Evidence | Verdict |
|---|--------|-----------------------|--------|----------|---------|
| 1 | discord_tweetshift | base 20/25/30 + 20×additional analysts | **YES** — sole Phase-1 firer | 575 alerts, 451 Phase-2 drops | **FIX** — 78% drop + flat conviction + xref blind to tweets |
| 2 | YouTube Gemini pipeline | feeds `signal_events`; standalone at min_trust 0.5 | Active | 45 videos, 49 signals, 12 HIGH — **0 standalone alerts fired** | **FIX** — delivery path broken |
| 2b | YouTube levels alerter (`main.py:404–451`) | standalone Discord post | Active | 25 fires / 24h; 19 (76%) are repeats on 4 ticker-level pairs | **FIX** — dedup at `main.py:430` broken |
| 3 | News cascade (`scanners/news.py`) | +15 + catalyst tier | Active (xref only) | ~60% hit rate on sampled breakdowns | **KEEP — refine** (body text dropped) |
| 4 | Calibration | Phase-2 "P(up)" field | **LIVE but untrained** | 22 snapshots, all `total_sources:0` | **FIX IMMEDIATELY** — lying to user |
| 5 | Regime detector | +20 abstain declared | **NO** — 0 call sites | structural | **KILL or wire** |
| 6 | Reddit / social | +10 each | Scanner runs, scoring inert | social_reddit=0 on 5/5 recent; 908 `reddit_posts` ingested, never scored | **FIX** — under-leveraged |
| 7 | Options | +10 flat | Unclear | options_flow=0 on 5/5 recent | **KILL or rebuild** |
| 8 | SEC EDGAR / 8-K watcher | +15 via xref | Off since 2026-04-07 | 395 historical alerts; 0% 1h / 91% 24h hit (n=11) | **UNDER-LEVERAGED** |
| 9 | volume_scanner / earnings_calendar / reddit_trend | 0 | **NO** — not imported in `main.py` | structural | **UNDER-LEVERAGED** |
| 10 | SearXNG | Tier 4 news | Active | only title ranked; `content` dropped | **UNDER-LEVERAGED** |

### 1. discord_tweetshift — the sole Phase-1 firer

Flow: `process_tweet()` at `main.py:552–652` — parse → quality gate (`:504–524`) → market-cap filter (`:596`) → cooldown (`:608`) → degraded-mode gate (`:612–619`) → instant ping (`:623`) → fire-and-forget xref (`:643–652`). Four load-bearing findings:

- **Conviction rubric is de-facto constant.** 570/575 alerts (99.1%) have `base_score=25`; 3 high (30), 2 low (20). `config/consensus.yaml:30–34` declares a 3-tier conviction ladder that the parser does not produce. Any downstream gate that keys on HIGH (30) — M6, the proposed SEC Form-4 velocity gate, the regime-detector abstain boost — bites on <1% of traffic until the parser is fixed.
- **Tweets are invisible to the xref canonical query.** `insert_signal()` writes tweets into `ticker_signals` (252 twitter rows) and ApeWisdom into the same table (764,435 rows). `cross_reference.py:333` reads `signal_events`, which has 23 rows total, all from one YouTube video. Structural data-coupling defect.
- **Cooldown race confirmed.** `kpak82` fired MSFT at 16:15 and 16:41 on 2026-03-29 — 26 min apart, through a 6-hour cooldown. `main.py:608` checks cooldown *before* `insert_alert` at `:627`, and the send path is async — parallel tweets for the same ticker can both pass the read side.
- **Phase-2 orphan rate is 78.4%**. `alert_messages`: 451 of 575 have `followup_msg_id IS NULL`. By day: 0% on 2026-03-28–30, 84–100% during the SEC flood window 2026-03-31 → 4-07, 1% on 2026-04-08 (SEC fix deployed), **regressed to 75–89% on 2026-04-20/23** — three of every four current alerts are orphaned. `main.py:655–701` uses `asyncio.create_task(...)` without `asyncio.wait_for`; `cfg.intervals.cross_reference_timeout=120` is declared at `config/consensus.yaml:88` but never consumed at the call site.

### 2. YouTube Gemini pipeline (Stage A → B → C)

45 videos persisted, 49 `youtube_signals` rows (12 HIGH, 23 MEDIUM, 14 LOW), zero suppressed — `classifier.min_confidence=0.5` at `config/consensus.yaml:271` is not biting. **Zero of the 12 HIGH-conviction signals produced an `alert_messages` row** with a YouTube analyst. `standalone_alerts: true` and `min_trust: 0.5` at `config/consensus.yaml:232–233` imply a delivery path exists; the data says it's broken or trust-gated to zero channels. Token usage on 2026-04-23: 771k in / 21k out (budget 2M / 500k) — cost fine, delivery not. Also: only the 23 `signal_events` for video `4mSyMr8PGLI` reached the xref's canonical source table; the other 22 videos' signals are orphaned.

### 2b. YouTube levels alerter (`main.py:404–451`)

14-day back-catalog sweep, alert when price within `youtube.level_alert_proximity_pct` (default 0.5%). Last 24h: 25 alerts, **19 (76%) repeats on 4 ticker-level pairs** — TALK $5.17 (7×), XLK $158 (7×), SMH $482.50 (5×), BE $230 (3×). Dedup at `main.py:430` (`was_level_recently_alerted`) is too permissive; `near_price_dedup_pct=0.5` at `:275` doesn't enforce per-ticker-per-price uniqueness. This is flooding the channel.

### 3. News cascade (`scanners/news.py`)

Xref-only, +15 `news_catalyst` + tier points. Last 5 breakdowns: BKR/GOOG/META show +15, AMZN/AMD show +0 → ~60% hit rate, pulling weight. **Structural gap:** `news.py:279–302` classifies on headline text only; `searxng.content` and `google_rss.description` are discarded before the regex. 39/160 (24.4%) of `alert_history` rows have empty `catalyst_type` — Phase-2 is silently dropping the tag in one of every four firings. Body-text NLP is the next unit of free lift.

### 4. Calibration — live-facing, untrained

`calibrate()` is invoked at `alerts/discord.py:101` and `alerts/commands.py:876`. `retrain()` is never called (0 grep hits outside `calibration.py`). `MODEL_PATH=.omc/state/calibration_model.pkl` does not exist. `_load_models()` returns `{}`; `_models.get(horizon)` returns `None`; `_identity(score) = score/100` is what the user sees labeled "Calibrated conf." Two levels of dead: (a) model untrained, and (b) the 22 `decision_snapshots` feeding it show `total_sources:0, signal_event_count:0` — the feature vector is empty because the snapshot is written before xref populates it. The live code is telling the user that a raw score divided by 100 is a probability.

### 5. Regime detector — ornamental

Module at `consensus_engine/analysis/regime_detector.py` exists; config declares `enabled: true` at `config/consensus.yaml:198` with thresholds `:199–202`. Zero grep hits on `regime_detector` in `main.py`, `cross_reference.py`, or `engine.py`. Never writes state to DB, never influences scoring. Structural.

### 6. Reddit / social

Social scanners (`scan_apewisdom`, `scan_reddit`, `scan_google_trends`) run from `main.py:120–220`. Volumes: apewisdom 764,435 rows, google_trends 3,067, twitter 252 in `ticker_signals`. Last 5 alert breakdowns: `social_reddit=0` on all 5, `social_apewisdom=10` on 4/5, `google_trends=0` on 5/5. **`social_reddit: +10` at `config/consensus.yaml:42` has never fired** in the last 5 alerts sampled — 908 `reddit_posts` rows ingested with `score` and `num_comments` columns populated but never consulted. Upvote and comment-velocity features are sitting on disk, unused.

### 7. Options

`options_flow: +10` at `config/consensus.yaml:47`. `options_flow=0` on all 5 recent breakdowns. IV rank, skew, and term-structure have no rubric line at all. A 0%-fire scorer is ornamentation.

### 8. SEC EDGAR / 8-K watcher — disabled with real history

`sec_background_watchers_enabled: false` at `config/consensus.yaml:94`, gated at `main.py:342`. Watchers **were** enabled 2026-03-31 → 2026-04-07 and produced **395 SEC-8K alerts** (68.7% of all 575 ever). Disabled after the 2026-04-07 fix. `final_score=0` on 384/395 (97%) — almost every SEC-8K alert either tripped the Precision Engine early-exit (`market_ok=false` at `engine.py:294–308`) or got Phase-2-silent-dropped. Empirical precision (`alert_messages → alert_history` join, n=11 matched): **0.0% 1h hit, 90.9% 24h hit.** Tiny sample, but the direction is unambiguous — SEC-8Ks mean-revert over 24h, not 1h. The Precision Engine's **1h** `market_ok` gate is structurally incompatible with a **24h-horizon catalyst**. Disabling the watcher means the single highest-edge pre-mainstream source in retail is off.

### 9. volume_scanner / earnings_calendar / reddit_trend — structurally dead

All three exist; none is imported in `main.py`. `volume_scanner.enabled: true` at `config/consensus.yaml:160` and `intervals.reddit_trend: 14400` at `:87` are config ghosts — no code reads them.

### 10. SearXNG

Tier 4 of news cascade. Returns `{title, url, content, engines, score}`; `news.py` classifies only `title`. `content` (often a full-sentence snippet) is dropped. Free compute already paid for (`localhost:8888`).

### Rubric empirical audit (the load-bearing table)

Non-SEC `final_score` → forward return (n=120 alerts with a measured 1h outcome):

| Band | n | 1h hit | 24h hit |
|------|----|--------|---------|
| 20s (final=29) | 7 | 40.0% | 0% |
| **30s (final=39)** | **17** | **94.1%** | **100%** |
| 40s | 27 | 53.8% | 75.0% |
| 50s | 28 | 39.3% | 75.0% |
| 60s | 34 | 20.6% | 59.1% |
| 70s | 9 | 11.1% | 71.4% |

**This is inverted monotonicity above 30.** The engine's higher-scored alerts are performing *worse* than mid-scored ones at 1h. Either `confidence_score` is mis-calibrated (the calibration layer is dead, so probably yes), the scoring multipliers are double-counting correlated sources (news + apewisdom + technical all spike together for mainstream names), or high scores correlate with Precision-Engine early-exit survivors that got published anyway. **This one chart is the strongest single argument on this page for turning calibration on and re-binning by empirical quantile.**

### Per-analyst precision (from `alert_messages → alert_history` join)

| Analyst | n | matched | 1h hit | 24h hit |
|---------|----|---------|--------|---------|
| TeresaTrades | 41 | 41 | 82.9% | null |
| Sarge986 | 6 | 5 | 60.0% | 0% |
| ripster47 | 7 | 4 | 50.0% | 100% |
| MarketRebels | 39 | 31 | 45.2% | 50.0% |
| OptionAlert | 8 | 7 | 42.9% | null |
| WallStJesus | 5 | 5 | 40.0% | 80.0% |
| DeItaone | 9 | 9 | 37.5% | 33.3% |
| OMillionaires | 12 | 9 | 33.3% | 60.0% |
| The_RockTrading | 23 | 15 | 33.3% | 50.0% |
| kpak82 | 7 | 7 | 14.3% | 71.4% |
| preetkailon | 5 | 1 | 0.0% | 0.0% |
| **SEC-8K** | **395** | **11** | **0.0%** | **90.9%** |

Precision spreads from 14% to 83% at 1h. Per-analyst weighting is the cheapest, highest-lift change available; training data is already sitting in `alert_history`.

### Catalyst tier empirical hit rate

The rubric at `config/consensus.yaml:48–72` assigns catalyst tiers 25/15/8. The DB says:

| Catalyst | n | 1h | 24h |
|----------|----|----|-----|
| Analyst Downgrade | 25 | 36.0% | **85.7%** |
| Analyst Upgrade | 39 | 35.9% | 61.5% |
| Dividend | 18 | 50.0% | 62.5% |
| M&A | 15 | 46.7% | 60.0% |
| Product Launch | 9 | 44.4% | 75.0% |

Analyst **downgrades** are producing higher 24h hit rates than upgrades on bullish alerts — probably a direction-bug (short-trade downgrades being scored as long-trade confirmations). Dividends at 50/62 are out-performing their tier-low label. The rubric is directionally correct but numerically wrong.

---

## Part 2 — Research findings (2025–2026 landscape)

Every claim below carries URL + author + date (or explicit `[date unknown]`). Full query log and rejected candidates in `plans/research-draft-2026-04-24.md`.

### 2.1 Most surprising findings (5 bullets)

- **LLM multi-agent debate is no longer hypothetical.** TauricResearch/TradingAgents has ~40.8k GitHub stars as of 2026-03 and ships a Bull / Bear researcher debate + Risk-Manager adjudicator with native Claude 4.6 support — the closest off-the-shelf analogue to a "contradiction resolver." [TradingAgents README, v0.2.2, 2026-03](https://github.com/TauricResearch/TradingAgents)
- **Insider Form-4 "cluster buys" have peer-reviewed ~4.8% / 12-month alpha** and are free via openinsider.com. The engine stores Form 4 but ignores cluster velocity. [Lakonishok & Lee, *RFS* 2002]; [MarketTriage signal guide, 2025](https://markettriage.com/insider-trading-signals).
- **Backwardated options term structure + negative risk-reversal is a documented pre-catalyst tell** — cheaper and more reliable than vol/OI alone; retail-accessible through CBOE daily stats and `yfinance` option chains. [IBKR Quant, Mastering Vol Term Structure, 2025](https://www.interactivebrokers.com/campus/ibkr-quant-news/mastering-options-volatility-term-structure/).
- **Sentiment-to-price divergence peaks at 3–10 days, is near-zero at 1 day.** Directly contradicts a "tweet → instant ping" posture for sentiment-type sources; `signal_events` should retain a multi-day cache window, separable from ingest latency. [arXiv 2507.09739, 2025-07](https://arxiv.org/html/2507.09739v1).
- **Microsoft's RD-Agent-Quant doubled benchmark ARR using 70% fewer factors** in 2025 — automated factor mining now clears retail feasibility, which reframes X2 (self-play backtest). [arXiv 2505.15155, 2025-05](https://arxiv.org/html/2505.15155v2).

### 2.2 Alternative data streams the engine doesn't use

- **OpenInsider + SEC Form-4 velocity (cluster buys).** `http://openinsider.com/latest-cluster-buys` — free, no API key, scrape-friendly. Signal: unique insiders buying within rolling 10-day window, dollar-weighted, flagged at ≥3 insiders. Academic support: Lakonishok & Lee (RFS 2002); Cohen-Malloy-Pomorski (J. Finance 2012) on opportunistic vs routine trades. Productionized for retail in 2025 by [13radar](https://www.13radar.com/insider/cluster-buys/) and Blank Capital's "Smart Money Matrix." **Fit:** SEC EDGAR scanner already fetches Form 4; a `distinct-CIK count in trailing 10d` column is one-scanner additive.
- **FRED macro rails (2s10s, HY OAS, NFCI).** `https://fred.stlouisfed.org/series/T10Y2Y` + DGS10, BAMLH0A0HYM2, NFCI. 120 req/min free. Signal: regime-gate input. The 2s10s normalised to +53 bp in 2025-10 after 16 months inverted — the longest inversion on record without recession ([eco3min 2025](https://eco3min.fr/en/yield-curve-inversion-history-2s10s-spread/)). **Fit:** the dead `regime_detector` needs inputs; FRED is the cheapest.
- **CBOE daily put/call + SKEW.** `https://www.cboe.com/us/options/market_statistics/daily/` + skew dashboard. Free HTML, post-close. Signal: aggregate P/C > 1.0 bearish, < 0.7 euphoric; ticker-level vol > OI directional tell ([YCharts, 2025](https://ycharts.com/indicators/cboe_equity_put_call_ratio); [Barchart, 2025](https://www.barchart.com/stocks/quotes/$VIX/put-call-ratios)). **Fit:** market-wide context for `regime_detector` and a per-ticker feature for `scanners/options.py`.
- **Rejected:** Polygon.io free tier (5 req/min, duplicates yfinance); Tiingo ($10/mo for real-time, no new signal vs yfinance).

### 2.3 Signal primitives with real citations

1. **Form-4 cluster-buy velocity** — Cohen-Malloy-Pomorski (J. Finance 2012) on opportunistic clusters; [MarketTriage, 2025](https://markettriage.com/insider-trading-signals). Trivial to add on top of the existing SEC EDGAR fetch.
2. **Options term-structure inversion + negative risk-reversal** — front-month IV > back-month IV plus calls > puts at 25Δ precedes short-term rallies into binary catalysts. [IBKR Quant 2025](https://www.interactivebrokers.com/campus/ibkr-quant-news/mastering-options-volatility-term-structure/); [MenthorQ 2025](https://menthorq.com/guide/skew-and-term-structure/). Upgrades `scanners/options.py` from one ratio to a three-feature vector.
3. **Isolation Forest multivariate anomaly.** `sklearn.ensemble.IsolationForest` over 5–10 daily per-ticker features (volume, spread, mention-count, IV rank); top 1% flagged. [Springer Comp. Economics, 2025](https://link.springer.com/article/10.1007/s10614-025-11274-8); [ScienceDirect OPTUNA-IF, 2025](https://www.sciencedirect.com/science/article/pii/S2666827025001537). Unsupervised — works while calibration is dead.
4. **Sector-ETF cross-asset confirmation.** Alert on X only if GICS sector ETF (XLK/XLF/XLV…) confirms; 2025 sector dispersion was extreme — XLK +23.9% YTD vs worst sector ~1% ([ETF.com, 2025](https://www.etf.com/sections/features/ai-boom-splits-market-best-and-worst-sector-etfs-2025)).
5. **McClellan Oscillator breadth-thrust gate.** Scalar market-wide gate from NYSE advancer/decliner feed; moves ≥100 points deep-negative → strong-positive are classic thrust signals. [StockCharts ChartSchool, 2025](https://chartschool.stockcharts.com/table-of-contents/market-indicators/mcclellan-oscillator).
6. **Sentiment horizon retune.** [arXiv 2507.09739, 2025-07](https://arxiv.org/html/2507.09739v1) — S&P 500 sentiment near-zero at 1d, peaks 3–10d, decays by day 20. Reframe cross-reference cache (not ingest speed) to a multi-day window.

### 2.4 LLM / agent patterns deployed in 2025–2026

- **Multi-agent debate + risk-manager adjudicator.** TauricResearch/TradingAgents; v0.2.2 (2026-03) with Anthropic Claude 4.6 effort control. ~40.8k stars. Pipeline: Analyst → Bull/Bear Researcher debate → Trader → Risk-Manager. [repo](https://github.com/TauricResearch/TradingAgents); [arXiv 2412.20138]; corroborated by [Ultra Lab AI-Finance roundup, 2026-03-25](https://ultralab.tw/en/blog/ai-finance-github-projects-2026). **Fit:** bolt onto Phase-2 xref as the X4 contradiction-resolver proposal.
- **Retrieval-augmented alpha mining.** MarketSenseAI 2.0 ([arXiv 2502.00415, 2025-02, revised 2025-10]) — HyDE retrieval over filings, earnings calls, expert reports; 125.9% cumulative return on S&P 100 2023–2024 vs 73.5% index. FinGPT is the OSS sibling ([AI4Finance-Foundation/FinGPT](https://github.com/AI4Finance-Foundation/FinGPT); [arXiv 2306.06031v2]). **Fit:** ancillary — Vault/Atlas/Alfred already cover nightly research + morning briefing; no replacement needed.
- **Self-consistency voting on trading signals specifically — NOT YET deployed in public 2025–2026 work.** Pattern exists in general LLM reasoning papers ([arXiv 2505.10772](https://arxiv.org/html/2505.10772v1); [arXiv 2502.18581](https://arxiv.org/pdf/2502.18581)) but not in a trading pipeline. Flagged — don't propose as proven.

### 2.5 OSS repos to lift from

| Repo | URL | Stars | Last activity | What to steal |
|------|-----|-------|---------------|---------------|
| TauricResearch/TradingAgents | https://github.com/TauricResearch/TradingAgents | ~40.8k (2026-03) | v0.2.2 released 2026-03 w/ Claude 4.6 | Bull/Bear debate + Risk-Manager orchestration graph |
| microsoft/qlib | https://github.com/microsoft/qlib | 40.8k (2026-04-16 star-history) | RD-Agent integration 2025-Q2 | Purged-CV utilities + factor-library scaffolding (X2 moonshot dependency) |
| OpenBB-finance/OpenBB | https://github.com/OpenBB-finance/OpenBB | ~54.7k–66k (2026-04) | 2026-04-19 | Data-provider abstraction patterns (FRED, CBOE, yfinance unified) |
| nautechsystems/nautilus_trader | https://github.com/nautechsystems/nautilus_trader | ~17k+ (2026-04) | v2026.04.06 release (option chains + greeks) | Event-driven bus patterns when/if engine goes live |
| polakowo/vectorbt | https://github.com/polakowo/vectorbt | ~6.8k (2026-01) | v0.28.4, 2026-01-26 | Vectorised backtest for retroactively scoring `alert_history` vs price bars |
| guanquann/Stocksera | https://github.com/guanquann/Stocksera | ~1k (est) | recent | 60+ alt-data scrapers (borrow fees, short interest); cherry-pick fn's |

### 2.6 Conflicts resolved

- **Sentiment horizon.** r/algotrading consensus: "instant tweet → instant trade." Peer-reviewed work ([arXiv 2507.09739, 2025-07]): S&P 500 sentiment has near-zero 1-day signal, peaks 3–10d. **Side with the paper.** The user's tweet-ingest remains the trigger; the *cross-reference cache* should extend to a multi-day hit window — separable from ingest latency.
- **MlFinLab license.** Textbook purged-CV and triple-barrier labels, 4.2k stars — but **not open for commercial use** ([hudson-and-thames/mlfinlab](https://github.com/hudson-and-thames/mlfinlab)). Lift algorithms from the López de Prado book directly or use BSD equivalents in Qlib / skfolio. Don't depend on mlfinlab.

### 2.7 Gaps — what research could NOT confirm (don't fabricate these)

1. No 2025 López de Prado arXiv paper surfaced — cite the 2018 book and derivatives only.
2. No public 2025–2026 deployment of self-consistency voting on trading signals specifically.
3. No canonical Alpha Architect 2024–2025 cluster-buy article; fell back to Lakonishok & Lee (2002) + Cohen-Malloy-Pomorski (2012).
4. No truly free options term-structure/skew API; retail must derive from `yfinance` chains.
5. No peer-reviewed "short interest velocity" backtest per se; metric is commercially used but academic support is thin.
6. Star / commit counts are 2026-03/04 snapshots with ranges, not live reads (Exa credits exhausted mid-run).

---

## Part 3 — Architecture pushback

### 3.1 Phase 1 / Phase 2 split
*For:* decoupling the instant ping from xref latency IS the product thesis — retail wins or loses in seconds. *Against:* `main.py:655–701` wraps the entire followup pipeline in one `try/except` that only logs. `asyncio.gather(xref_task, precision_task)` at `:668` has no timeout; the `intervals.cross_reference_timeout: 120` knob at `config/consensus.yaml:88` is declared and unused. Also, `SignalClass.IGNORE` at `:684` silently skips `send_detail_followup` — so even a successful xref can produce zero Phase-2 message. User sees a lonely ping and can't tell whether Phase 2 was skipped deliberately or dropped. **Verdict: split is correct, implementation is broken.** Keep the split; add `asyncio.wait_for` + an explicit "Phase 2 skipped — low precision" edit so silence never equals failure. SQL: 78.4% drop rate (audit Part 1).

### 3.2 `cooldown_hours: 6`
*For:* blocks repeat pings on viral tickers. *Against:* `check_alert_cooldown()` at `db.py:672–682` ignores analyst identity, conviction, and time-since-last-move — confirming tweets from different top-5 analysts are dropped, same-analyst mid-breakout "raising target" tweets are dropped, 6 hours is long enough for a full breakout-reverse cycle. **Verdict: too blunt.** Replace with per-analyst cooldown that shortens for high-hit-rate analysts; exempt HIGH conviction (once conviction actually distributes — see Audit §1).

### 3.3 `min_base_score_for_alert: 20`
*For:* intuitive, explainable. *Against:* 20 is the floor of the conviction ladder, not a calibrated threshold. The `calibrate()` module was built to replace exactly this decision with a per-analyst probability; `decision_snapshots` already has the features. **Verdict: threshold is fine; the wrong question.** 20 vs 22 doesn't matter — per-analyst vs global does.

### 3.4 Free-tier OpenRouter LLMs
*For:* `minimax/minimax-m2.5:free` + `google/gemma-4-31b-it:free` cost $0; `llm_boost_max: 15` caps blast radius. *Against:* `:free` tier routinely 429s and silently substitutes smaller models during peak hours — same tweet at 10am vs 2pm can get two different boosts. Non-deterministic alerting. On the 18–25 score band where 15 points of LLM boost flips an alert from suppressed to fired, model quality is load-bearing. **Verdict: downgrade risk is unpriced.** Keep free for bulk triage; move tie-breaks to Claude Haiku 4.5.

### 3.5 `reliability_engine_enabled: false`
*For:* staged rollout is legitimate if weights are unvalidated. *Against:* the source file `reliability_engine.py` is **missing from disk** — only `__pycache__/reliability_engine.cpython-310.pyc` remains. The import at `cross_reference.py:328–330` is guarded by the flag, so nothing fails — but flipping the flag true will crash every xref. Not staged rollout — a deleted module load-bearing behind a flag. **Verdict: restore or delete.** Within a week.

### 3.6 `require_market_confirmation: true` + `market_ok` early-exit
*For:* if the ticker isn't moving on Finnhub at scan time, most alerts are rumor noise. *Against:* the stated edge is catching setups BEFORE mainstream confirmation. `market_ok` IS a mainstream-confirmation check — requiring it filters out exactly the class of signals the user wants first. SEC-8K empirical: 0% 1h / 91% 24h — the 1h gate is structurally incompatible with a 24h-horizon catalyst. **Verdict: most damaging gate in the system.** Exempt HIGH-conviction analyst tweets and SEC-8K/Form-4 sources; keep the gate for noisier sources (Reddit, SearXNG).

### 3.7 `max_alerts_per_hour: 10`
*For:* none — zero code references. *Against:* on a bad news day correlated sources could fire 40 alerts/hr, drowning real signal. **Verdict: enforce or delete.** A phantom guardrail is strictly worse than no guardrail because it lies to future readers.

### 3.8 SEC background watchers off
*For:* SEC filings are bursty and 90% of 8-Ks are 5.02 officer-departures. *Against:* SEC is the single highest edge-per-dollar source in retail. Form-4 velocity and 8-K items 1.01/2.01/8.01 produce real price response. The parser fix in `project_sec_alert_fix.md` already exists. Disabling proactively means SEC only helps when a tweet happens to reference it — never surfaces "executive just bought $5M at $X" before Twitter picks it up, which is the exact "before mainstream" signal the engine was built for. **Verdict: disabled for the wrong reason.** Re-enable with item-type filtering (allow 1.01/2.01/8.01 + Form 4 > $500k; suppress 5.02/exhibit-only) and exempt from `market_ok`.

---

## Part 4 — Tiered proposals

Every proposal populates all 5 required fields. Lift-per-cost in Part 5.

### 4.1 Quick wins (≤3 days, ≤2 files, no new dep)

| # | Name | Module | Precision impact (+ why) | Recall impact (+ why) | Complexity | Kill-switch SQL |
|---|------|--------|---------------------------|------------------------|------------|------------------|
| Q1 | **Calibration ON in shadow mode** | `analysis/calibration.py`; add pre-alert call at `main.py:615` | +5–10 pp — converts a global threshold into per-analyst probability via `decision_snapshots`. Directly addresses inverted monotonicity (94% vs 21% at 30/60 bands). | 0 in shadow mode. Enforcement drops recall by suppressed low-trust analyst volume (intended). | 1 file + 1 flag `calibration.shadow_mode`. ~40 LOC. | `SELECT AVG(ABS(calibrated_prob-hit_24h)) FROM decision_snapshots WHERE calibrated_prob IS NOT NULL` — > 0.25 for 2 weeks → off. |
| Q2 | **Phase-2 timeout + "skipped" message + fix `signal_events` coupling** | `main.py:655–701`; `cross_reference.py:333` OR `insert_signal()` in `db.py` | +2–3 pp — users stop acting on stale Phase-1 pings silently invalidated. Xref becomes aware of tweet signals (currently blind). | +0. Pure UX + data-path fix. | 1–2 files, ~50 LOC. Add `asyncio.wait_for(gather, timeout=cfg.get("intervals.cross_reference_timeout"))` + explicit Discord edit; route tweets into `signal_events` or retarget read. | `SELECT COUNT(*) FROM alert_messages WHERE followup_msg_id IS NULL AND created_at<strftime('%s','now','-1 day')` — > 0 → timeout fired but message edit failed. |
| Q3 | **Kill `max_alerts_per_hour` (or enforce)** | `config/consensus.yaml:188` (delete) OR `main.py:608` (enforce) | 0 if deleted; +1–2 pp if enforced (drowning events are noisiest). | 0 or -1–2 pp. | 1 line delete, OR ~8 LOC rolling-window. | `SELECT COUNT(*)/24.0 FROM alert_history WHERE alerted_at>strftime('%s','now','-24 hours')` — > 10/hr sustained → enforce justified. |
| Q4 | **SearXNG `content` body enrichment** | `scanners/searxng.py` + `scanners/news.py:279–302` | +3–5 pp — body matching catches "raised guidance", "beat Q", "FDA approval" that headlines miss. | +1–2 pp new catalyst matches. | 1 file, ~25 LOC. | `SELECT COUNT(*) FROM signal_events WHERE source_type='searxng' AND created_at>strftime('%s','now','-7 days')` — body matches don't lift catalyst count by 20% → revert. |
| Q5 | **Wire `volume_scanner.py` into main loop** | `main.py` + existing `scanners/volume_scanner.py` | +2–4 pp on new alerts — RVOL > 5× + move > 1% is tape-confirmation. | +15–25 pp — currently zero volume-breakout signals surface. | 1 file edit, ~20 LOC; config at `:159–163` already exists. | `SELECT COUNT(*), AVG(hit_24h) FROM alert_history WHERE catalyst_type='volume_breakout'` — hit_rate < 0.2 after 30d → disable. |
| Q6 | **Wire OR delete `regime_detector`** | `config/consensus.yaml:197–202` + `main.py` + `engine.py` | +4–6 pp on regime-transition days (`abstain_score_boost: 20`). 0 if deleted. | -3–5 pp on bad-regime days (intended). | ~50 LOC wire, or 6-line config delete. | `SELECT strftime('%H',alerted_at), AVG(hit_24h) FROM alert_history GROUP BY 1` — high-VIX hour hit_rate < 0.3 vs 0.55 → suppression justified. |
| Q7 | **Reddit upvote / comment-velocity weighting** | `scanners/social.py` or `scanners/reddit_trend.py` | +3–4 pp — a ticker with 5 mentions + 2000 upvotes is not the same signal as 20 mentions + 3 upvotes. | +0–1 pp — mostly reweighting. | 1 file, ~40 LOC; PRAW already returns the columns. | `SELECT AVG(hit_24h) FROM alert_history WHERE consensus_breakdown LIKE '%reddit%'` — new weighting doesn't outperform by 10% → revert. |
| Q8 | **Fix YouTube levels alerter dedup** (NEW — surfaced by audit 2b) | `main.py:404–451`, specifically `was_level_recently_alerted` at `:430` and `near_price_dedup_pct` at config `:275` | +0 direct; reduces channel fatigue that desensitises user to real signals. | 0. | 1 file, ~20 LOC. Enforce per-ticker-per-price dedup window of 6h. | `SELECT ticker||level_price, COUNT(*) FROM youtube_level_alerts WHERE alerted_at>strftime('%s','now','-1 day') GROUP BY 1 HAVING COUNT(*)>2` — > 4 rows/day → dedup still broken. |
| Q9 | **Fix conviction parser to actually distribute 20/25/30** (NEW — surfaced by audit §1) | `analysis/tweet_parser.py` | Unblocks M6, SEC-8K exemption, regime abstain. Currently 99.1% of alerts are 25 — every conviction-keyed gate is nearly inert. | 0 direct. | 1 file; extent depends on current logic. ~60 LOC. | `SELECT base_score, COUNT(*) FROM alert_history GROUP BY 1` — if distribution is still >90% single-tier after 2 weeks, parser fix didn't bite. |

### 4.2 Medium bets (1–4 weeks, kill-switch required)

| # | Name | Module | Precision (+ why) | Recall (+ why) | Complexity | Kill-switch |
|---|------|--------|---------------------|-----------------|------------|---------------|
| M1 | **Re-enable SEC watcher with item-type + dollar filter** | `scanners/sec_watcher.py` + `sec_edgar.py` + `config/consensus.yaml:94` | +6–10 pp — 8-K items 1.01/2.01/8.01 and Form-4 > $500k have peer-reviewed alpha (Lakonishok-Lee 2002, Cohen-Malloy-Pomorski 2012). Currently zero proactive. | +10–15 pp — full new proactive source. | 2 files, ~200 LOC. Reuse `project_sec_alert_fix.md` parser. No new dep. | `SELECT AVG(hit_24h),COUNT(*) FROM alert_history WHERE catalyst_type LIKE 'sec_%' AND alerted_at>strftime('%s','now','-30 days')` — < 0.35 → disable. |
| M2 | **Options IV rank + put/call skew + term-structure** | `scanners/options.py` + new `analysis/options_features.py` | +8–12 pp — IV percentile > 80 + bullish skew inversion is canonical smart-money positioning (Sinclair 2020). | +3–5 pp. | 1 new file (~150 LOC) + 1 edit; needs CBOE free daily CSV. | `SELECT AVG(hit_24h) FROM alert_history WHERE consensus_breakdown LIKE '%iv_rank%'` — doesn't outperform baseline by 5 pts → revert. |
| M3 | **Per-analyst cooldown (replaces blanket 6h)** | `db.py:672–682` (rewrite `check_alert_cooldown`) | +5–8 pp — 14%-to-83% analyst precision spread is the single largest per-entity exploitable signal in the DB. | +15–20 pp — same-analyst confirming tweets within 6h currently dropped. | 1 file, ~80 LOC; uses existing `source_performance`. | `SELECT COUNT(*) FROM alert_history WHERE ticker IN (SELECT ticker FROM alert_history GROUP BY ticker HAVING COUNT(*)>5) AND alerted_at>strftime('%s','now','-1 day')` — single-ticker > 5/day → tighten. |
| M4 | **Claude Haiku 4.5 for tie-break LLM scoring** | `analysis/llm_scorer.py` | +4–7 pp on 15–25 score band where boost is load-bearing. Haiku 4.5 is deterministic (no silent free-tier downgrade). | +0–1 pp. | 1 file, ~60 LOC; needs `ANTHROPIC_API_KEY`. | `SELECT AVG(hit_24h) FROM alert_history WHERE base_score BETWEEN 18 AND 25 AND alerted_at>strftime('%s','now','-30 days')` — lift < +3 pp → revert to free. |
| M5 | **Delete dead calibration/regime/reliability code paths** (fallback KILL if Q1+Q6 aren't chosen) | `analysis/calibration.py` + `analysis/regime_detector.py` + `.pyc` + config | 0 direct; +2–3 pp indirect — prevents accidental flag-flip crashes (reliability_engine .pyc behind flag at `:194`). | 0. | 3 files deleted + ~15 config lines removed. | `grep -r calibrate\( consensus_engine/ \| wc -l` → > 0 after deletion = kill missed a call site. |
| M6 | **Exempt HIGH-conviction from `require_market_confirmation`** | `engine.py:294–308` | +8–12 pp — the engine exists specifically to catch pre-mainstream setups; the gate currently kills them. | +10–15 pp. **Depends on Q9** (conviction parser fix) — without Q9, this bites on 0.5% of alerts. | 1 file, ~15 LOC. | `SELECT AVG(hit_24h) FROM alert_history WHERE base_score>=30 AND alerted_at>strftime('%s','now','-30 days')` — lift < +3 pp on exempt band → revert. |

### 4.3 Moonshots (>1 month, research-cited)

| # | Name | Module | Precision (+ why) | Recall (+ why) | Complexity | Kill-switch |
|---|------|--------|---------------------|-----------------|------------|---------------|
| X1 | **Cross-asset confirmation layer** (sector ETF + correlated-pair divergence) | new `analysis/cross_asset.py` + hook in `cross_reference.py` | +10–15 pp — tweets on X that the sector ETF isn't confirming are historically low-hit-rate (ETF.com 2025 sector dispersion). | -3–5 pp — intentional filtering. | ~300 LOC. Needs GICS sector mapping + 11 yfinance pulls. | `SELECT AVG(hit_24h) FROM alert_history WHERE consensus_breakdown LIKE '%sector_divergence%'` — doesn't outperform by 8 pp → revert. |
| X2 | **Self-play backtest loop for rubric auto-tuning** | new `backtest/` package | +15–25 pp — every threshold in `config/consensus.yaml:30–72` is hand-chosen; walk-forward CV over `alert_history × hit_1h/24h` derives optimal rubric (López de Prado *Advances in Financial ML* Ch 6–7). | 0 mechanically. | ~800 LOC; deps probably already present. Needs ≥1000 labeled alerts — DB currently has 575. Wait for more. | `SELECT AVG(hit_24h) FROM alert_history WHERE alerted_at>strftime('%s','now','-60 days')` — post-tune hold-out doesn't exceed current by 5 pp → revert. |
| X3 | **Positioning-extreme feature (CBOE put/call + CFTC COT)** | new `analysis/positioning.py` + CBOE daily + CFTC weekly fetchers | +6–10 pp — retail-options positioning extremes (21-day P/C z > 2) mean-revert (Sinclair 2020). | +2–5 pp net new signal. | ~250 LOC. Free data. | `SELECT AVG(hit_24h) FROM alert_history WHERE catalyst_type='positioning_extreme'` — < 0.4 after 90d → disable. |
| X4 | **LLM-adjudicated contradiction resolver** (Haiku over Phase-2 source dump) | new `analysis/contradiction.py`; invoked after xref | +8–12 pp — currently the engine sums scores even when Reddit is bullish, options is bearish, analyst is bullish. Haiku adjudicator with "name the contradiction and pick a side" prompt resolves the tie with reasoning. Precedent: TauricResearch/TradingAgents Risk-Manager. | -2–4 pp (adjudicator will veto). | ~400 LOC + Haiku API. | `SELECT AVG(hit_24h) FROM alert_history WHERE consensus_breakdown LIKE '%adjudicator%'` — doesn't outperform summed-score by 6 pp → disable. |

### 4.4 Explicit KILL recommendations (4)

1. **`max_alerts_per_hour: 10` at `config/consensus.yaml:188`** — zero code refs. Enforce (Q3) or delete.
2. **`regime_detector` stanza at `config/consensus.yaml:197–202`** — if not wired within 30 days, kill. `enabled: true` that does nothing is the worst of all worlds.
3. **`reliability_engine_enabled` flag at `config/consensus.yaml:194` OR restore the missing `reliability_engine.py`** — the .py source file is absent from disk; only `.pyc` remains. Flipping the flag will crash xref. Restore or delete within a week.
4. **Narrow `require_market_confirmation: true` at `config/consensus.yaml:297`** — as currently applied at `engine.py:294–308` it early-exits signals before the mainstream move, the explicit opposite of the product thesis. Exempt HIGH-conviction analyst tweets and all SEC-derived sources (M6).

---

## Part 5 — Ranked top-3 (lift per unit engineering cost)

Calculus: Expected 24h-hit-rate lift in percentage points ÷ Engineering-cost score (1–5 scale). Higher = better.

| Rank | Proposal | Expected lift | Eng cost | Lift/cost | Notes |
|------|----------|---------------|----------|-----------|-------|
| **1** | **Q1 — Calibration ON (shadow mode)** | +5 to +10 pp precision | 1 (~40 LOC, 1 flag) | **~7.5** | Module already written. Shadow = zero risk. Directly addresses the inverted-monotonicity finding (94% @30-band vs 21% @60-band) that is the single most damning data point in the DB. |
| **2** | **M3 — Per-analyst precision weighting** | +5–8 pp precision + +15–20 pp recall | 2 (~80 LOC, no new dep) | **~6.5** (using precision-weighted lift) | Training data already in `alert_history`. 14%-to-83% spread per analyst is the largest exploitable per-entity signal in the system. Kills the blunt 6h cooldown in the same PR. |
| **3** | **Q2 — Phase-2 timeout + fix `signal_events` data-coupling** | +2–3 pp precision (less false-alarm UX); fixes silent data-coupling blind spot | 1–2 (~50 LOC, 1 flag) | **~2.5 raw, but high strategic weight** | Not a precision win per se but solves the single most embarrassing defect (78.4% Phase-2 drop rate, currently 75–89% on 2026-04-20/23). Also fixes the `signal_events` read-target bug that makes xref blind to tweets. Shipping this is a credibility floor for everything else. |

### Runners-up in ranked order

- **Q9 — Fix the conviction parser** (unblocks M6 and every conviction-keyed gate; currently 99.1% of alerts are `base_score=25`).
- **M6 — Exempt HIGH-conviction from `require_market_confirmation`** (once Q9 is done; one-line fix that resolves the product-thesis contradiction).
- **Q5 — Wire `volume_scanner`** (15–25 pp net-new recall; entire source currently off).
- **M1 — Re-enable SEC watcher with item-type filter** (requires M6 to not get early-exited; big recall + precision but depends on 2 other changes).
- **Q4 — SearXNG body enrichment** (25 LOC; free lift).

### Why M6 is not in the top 3 even though it has the highest single-lift estimate

M6 is a one-line fix (`if tweet.base_score >= 30: skip market_ok gate`). Standalone lift is +8–12 pp precision and +10–15 pp recall. BUT only **3 of 575 alerts (0.5%)** currently qualify as HIGH conviction because of the Q9 parser defect. Without Q9 first, M6 bites on essentially zero traffic. The *combined* Q9 + M6 intervention belongs in a single PR, not as two ranked items.

### Why X2 is not in the top 3

Self-play backtest auto-tuning has the highest theoretical lift (+15–25 pp) and the data-path is clear. But (a) the DB has 575 labeled alerts — López de Prado purged-CV needs ≥1000 for stable walk-forward CV, (b) 800 LOC of new code, and (c) Q1 calibration gives most of the same information for 5% of the cost. Revisit X2 once DB reaches ~1500 alerts and Q1 is proven.

---

## Part 6 — Verification checklist

- [x] Every audit paragraph carries `file:line` OR a SQL row count (see Part 1 subsections and raw SQL appendix in `plans/audit-draft-2026-04-24.md`).
- [x] Every research bullet carries URL + author/date (or explicit `[date unknown]`) — see Part 2 and full query log in `plans/research-draft-2026-04-24.md`.
- [x] Every proposal has all 5 required fields (module / precision why / recall why / complexity / kill-switch) — Part 4 tables.
- [x] Top-3 shows lift and cost estimates, not just ranks — Part 5 table.
- [x] At least 2 proposals are explicit KILL recommendations — 4 listed (Part 4.4): `max_alerts_per_hour`, `regime_detector` stanza, `reliability_engine_enabled`, narrow `require_market_confirmation`.
- [x] At least 1 research contradiction named and resolved — sentiment horizon (retail blogs vs arXiv 2507.09739); MlFinLab license.
- [x] No buzzword-only items; no abstraction-layer-only items; no paid-API items without ROI math (M4 Haiku justified by 18–25 band being load-bearing; no other paid proposals).
- [x] Calibration and regime_detector dead-code status confirmed — **partially corrected**: `calibrate()` IS live-invoked at `alerts/discord.py:101` and `alerts/commands.py:876` (untrained fallback); `regime_detector` confirmed zero call sites.
- [x] Phase-2 silent-drop rate quantified — **78.4% (451/575), currently regressed to 75–89% on 2026-04-20/23**.
- [x] Vault/Atlas/Alfred NOT proposed as future work — confirmed LIVE in prod 2026-04-23.
- [x] `max_alerts_per_hour` addressed — Q3 enforces or deletes.

### Pre-verified facts that turned out wrong (do not propagate)

1. "Calibration is dead code" — it's **live but untrained** at `alerts/discord.py:101` and `alerts/commands.py:876`; retrain() is never called; model file missing.
2. "SEC watchers disabled by default" — currently true, but they fired 395 of the 575 historical alerts (2026-03-31 → 2026-04-07) before being flipped off after the 2026-04-07 fix.
3. "Cross-reference is fire-and-forget with no timeout" — confirmed, and empirical consequence is **78.4% Phase-2 orphan rate**.
4. "`signal_events` is where signals live" — it has **23 rows total, all from one YouTube video**. Tweets write to `ticker_signals` (252 rows). `cross_reference.py:333` reads `signal_events`. Structural data-coupling defect not in any pre-verified assumption.
5. "`reliability_engine.py` is a staged-rollout module" — the .py **source file is missing from disk**, only `.pyc` remains. Flipping `alerts.reliability_engine_enabled: true` will crash xref.

### Research queries that could not be closed (don't fabricate)

1. No specific 2025 López de Prado arXiv paper found; cite 2018 book only.
2. No public 2025–2026 deployment of self-consistency voting on trading signals specifically.
3. No canonical Alpha Architect 2024–2025 cluster-buy article; used Lakonishok & Lee (2002) + Cohen-Malloy-Pomorski (2012) via MarketTriage secondary.
4. No truly free options term-structure/skew API; derive from `yfinance` chains.
5. No peer-reviewed "short interest velocity" backtest.
6. OSS star/commit counts are 2026-03/04 snapshots with ranges, not live (Exa credits exhausted mid-run).

---

## Part 7 — Next step

The user's stated plan: review this deliverable, start a new session, run `/ralplan --deliberate` to pressure-test the proposals and produce an execution plan. The natural target for `/ralplan --deliberate` is the **top-3 combined PR** (Q1 + Q2 + M3) plus the **KILL list** (Part 4.4), because those five changes together:

- Address every corrected pre-verified fact (calibration untrained, Phase-2 drop, signal_events coupling, reliability_engine missing file).
- Provide the load-bearing empirical lift (inverted monotonicity fix via Q1; per-analyst spread exploitation via M3).
- Cost ~170 LOC total across 4–5 files; revertible by three config flags.
- Unblock the bigger-lift items (Q9 → M6 → M1 SEC re-enable) once the empirical scaffolding exists.

Q9 (conviction parser fix) should be ralplan's first question: the parser-fix effort sizing is unknown and it blocks 2 of the 3 highest-theoretical-lift proposals (M6, conviction-keyed regime gating). Depending on effort, it slots as the 4th Quick or a Small Medium.
