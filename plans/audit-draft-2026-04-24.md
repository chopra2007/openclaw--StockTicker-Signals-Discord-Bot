# Audit — Phase B Draft (2026-04-24)

## Audit Summary Table

| # | Source | Current weight (rubric) | Wired? | Evidence class | Verdict |
|---|--------|-------------------------|--------|----------------|---------|
| 1 | discord_tweetshift | 20/25/30 base + 20×n analysts | YES (sole Phase-1 firer) | empirical (575 alerts, 451 Phase-2 drops) | **FIX** (78% Phase-2 drop; `base_score=25` flat on 99% of alerts) |
| 2 | YouTube Gemini pipeline (Stage A→B→C) | feeds `signal_events` + standalone (min_trust 0.5) | YES | empirical (49 signals, 23 signal_events from 1 video) | **FIX** (signal_events effectively single-video; no alerts fired despite 12 HIGH conviction) |
| 2b | YouTube levels alerter (`main.py:404-451`) | standalone Discord post | YES | empirical (25 fires, 4 tickers dominate) | **FIX** (near-price dedup broken; TALK/XLK/SMH fire every 1–4h on repeat) |
| 3 | News cascade (`scanners/news.py`) | +15 (news_catalyst) | YES (xref only) | empirical (breakdowns show 15 pts ~45% of time) | KEEP — pulling weight |
| 4 | Calibration | Phase-2 embed "P(up)" field | YES (called), but model never trained | empirical (0 model file; 22 snapshots, all `total_sources:0`) | **KILL display** (identity fallback masquerading as calibrated) |
| 5 | Regime detector | `+20 abstain_boost` declared | **NO** (never invoked in main.py/cross_reference.py) | structural (0 call sites) | **KILL** or wire |
| 6 | Reddit/social scanners | +10 (social_reddit) | Scanner runs, scoring inert | empirical (social_reddit=0 on every sampled alert) | **FIX** (764k apewisdom rows → 0 reddit score ever awarded) |
| 7 | Options flow | +10 (options_flow) | Unclear (zero on every sampled alert) | empirical (options_flow=0 on 5/5 recent alerts) | **KILL or wire** |
| 8 | SEC Edgar / 8-K watcher | +15 (sec_filing) via xref | **Off** since 2026-04-07 | empirical (395 SEC-8K alerts, 0% 1h hit, 91% 24h hit in thin sample) | UNDER-LEVERAGED |
| 9 | `volume_scanner.py` / `earnings_calendar.py` / `reddit_trend.py` | 0 (not wired) | **NO** | structural (0 import in main.py) | UNDER-LEVERAGED |
| 10 | SearXNG | Tier 4 of news cascade | YES | structural (only title/URL ranked; `content` field dropped) | UNDER-LEVERAGED |

Legend: `signal_events` row counts measured 2026-04-24; alert counts span 2026-03-28 → 2026-04-23.

---

## 1. discord_tweetshift — sole Phase-1 firer

Code path: `process_tweet()` at `consensus_engine/main.py:552-652` — parse → quality gate (`:504-524`) → market-cap filter (`:596`) → cooldown (`:608`) → degraded-mode gate (`:612-619`) → instant ping (`:623`) → fire-and-forget xref (`:643-652`). **Four findings with evidence:**

1. **`base_score` is effectively a constant.** 570 of 575 alerts (99.1%) have `base_score=25`; only 3 are high (30) and 2 low (20). The 3-tier conviction rubric at `config/consensus.yaml:30-34` does not produce a distribution in practice — the parser hard-codes or near-hard-codes medium. `min_base_score_for_alert=20` at `config/consensus.yaml:191` is only meaningful for `neutral` direction tweets (`-5` penalty at `main.py:522-523`).
2. **Tweets are invisible to cross-reference scoring.** `process_tweet` writes to `ticker_signals` (252 twitter rows; apewisdom has 764k on the same table), but `cross_reference.py:333` reads `signal_events` — which has **only 23 rows total, all from one YouTube video**. The xref layer has never seen a tweet. Structural data-coupling bug.
3. **Cooldown race.** `kpak82` fired MSFT at 16:15 and 16:41 on 2026-03-29 — **26 min apart**, through a 6-hour cooldown gate. `main.py:608` checks cooldown *before* `insert_alert` at `:627`, and the send path is async — parallel tweets for the same ticker can both pass the read. Structural.
4. **Phase-2 orphan rate is 78.4%** (`alert_messages`: 451 of 575 have `followup_msg_id IS NULL`). By day: 0% on 2026-03-28-to-30, then 84-100% during 2026-03-31-to-4-07 (SEC flood window), 1% on 2026-04-08 (SEC fix deploys), 0% on 2026-04-12/15, and **regressed to 75-89%** on 2026-04-20/23. `main.py:655-701` uses `asyncio.create_task(...)` without `asyncio.wait_for` — `cfg.intervals.cross_reference_timeout=120` is declared at `config/consensus.yaml:88` but never consumed at the xref call site.

## 2. YouTube Gemini pipeline (Stage A→B→C)

45 videos persisted, 49 `youtube_signals` rows (high=12, medium=23, low=14), 0 suppressed (`classifier.min_confidence=0.5` at `config/consensus.yaml:271` not biting). **Zero** of the 12 HIGH-conviction signals produce an `alert_messages` row with a YouTube-style `analyst`. `standalone_alerts: true` and `min_trust: 0.5` at `config/consensus.yaml:232-233` imply a path exists; the data shows the path is broken or trust-gated to zero channels. `api_usage_daily` on 2026-04-23 shows Gemini usage at 771k/21k tokens against 2M/500k budget — cost is fine, delivery is not. Also: only the 23 `signal_events` for video `4mSyMr8PGLI` ever reached the xref layer's canonical source table — the other 22 videos' signals are orphaned.

## 2b. YouTube levels alerter (`main.py:404-451`)

14-day back-catalog sweep (`main.py:407`); alerts when current price within `youtube.level_alert_proximity_pct` (default 0.5%). **25 alerts in 24h, 19 of 25 (76%) are repeats on 4 ticker-level pairs** — TALK $5.17 support (7×), XLK ~$158 resistance (7×), SMH $482.50 resistance (5×), BE $230 resistance (3×). Dedup at `main.py:430` (`was_level_recently_alerted`) is too permissive; `near_price_dedup_pct=0.5` at `:275` does not enforce per-ticker-per-price uniqueness. Precision class: **noise** — user's alerts channel is being flooded with identical "approaching level" pings once current price parks nearby.

## 3. News cascade (`scanners/news.py`)

Xref-only, scores `+15 news_catalyst` plus catalyst_tier points per `config/consensus.yaml:38,48-72`. 5 most recent breakdowns: BKR/GOOG/META show +15 news, AMZN/AMD show +0 — ~60% hit rate, real pull-weight. Cascade order `finnhub → google_rss → brave → searxng` (`config/consensus.yaml:75-80`), stops at first catalyst. **Structural gap:** `scanners/news.py:279-302` classifies on headline text only; `searxng.content` and `google_rss.description` are discarded. 39/160 (24.4%) of `alert_history` rows have empty `catalyst_type`. Body-text NLP is the next unit of lift available for $0.

## 4. Calibration — DEAD but LIVE-FACING

**Correction to pre-verified fact:** `calibrate()` IS invoked at `alerts/discord.py:101` (Phase-2 "P(up 1h)" embed field) and `alerts/commands.py:876` (!score). The grep-miss claim only held for `main.py`/`cross_reference.py`. But **`retrain()` is never called** anywhere (0 grep hits outside `calibration.py`); the `MODEL_PATH=.omc/state/calibration_model.pkl` file does not exist on disk (verified 2026-04-24). `_load_models()` returns `{}`, `_models.get(horizon)` returns None, and `_identity(score)=score/100` is what the user sees labeled "Calibrated conf" in every Phase-2 embed. Two levels of dead: (a) model untrained, and (b) the 22 `decision_snapshots` feeding it show `total_sources:0, signal_event_count:0` — the feature vector is empty because the snapshot is written before xref populates it. The live code is telling the user a raw score divided by 100 is a probability.

## 5. Regime detector — DEAD

Module exists at `consensus_engine/analysis/regime_detector.py`; config declares `enabled: true` at `config/consensus.yaml:198` with thresholds `:199-202`. **0 grep hits on `regime_detector` in main.py, cross_reference.py, or engine.py.** Never writes state to DB, never influences scoring. Ornamental config. *Structural evidence.*

## 6. Reddit / social

Social scanners (`scan_apewisdom`, `scan_reddit`, `scan_google_trends`, `scan_stocktwits`-disabled) all run from `main.py:120-220`. Scale: apewisdom 764,435 rows, google_trends 3,067, twitter 252 in `ticker_signals`. **Rubric empirics from 5 recent alerts:** `social_reddit=0` on all 5, `social_apewisdom=10` on 4/5, `google_trends=0` on 5/5. `social_reddit` is functionally dead — Reddit is scraped to 908 `reddit_posts` rows and 764k mentions, and never earns a point. `reddit_posts.score` and `num_comments` columns exist and are populated but never consulted outside `db.py`. Upvote/velocity lift is *structurally* on the table but zero code path picks it up.

## 7. Options

`options_flow: +10` rubric line at `config/consensus.yaml:47`. **Empirical:** `options_flow=0` on all 5 recent breakdowns. Either not wired or never clears threshold. IV rank, skew, and term-structure have no line in the rubric at all. A 0%-fire scorer is ornamentation.

## 8. SEC Edgar / 8-K watcher — disabled with real history

`sec_background_watchers_enabled: false` at `config/consensus.yaml:94`, gated at `main.py:342`. But watchers **were** enabled 2026-03-31 through 2026-04-07 and produced **395 SEC-8K alerts** (68.7% of all 575 alerts ever). They got flipped off after the 2026-04-07 fix. `final_score=0` on 384/395 (97%): almost every SEC-8K alert either triggered Precision Engine early-exit at `engine.py:294-308` (`market_ok=false`) or got Phase-2-silent-dropped. **Empirical precision of SEC-8K** (alert_messages→alert_history join, n=11 matched): **0.0% 1h hit, 90.9% 24h hit.** Tiny sample, but it says SEC-8Ks mean-revert over 24h, not 1h — and the Precision Engine's 1h market-confirmation gate is structurally incompatible with a 24h-horizon source. UNDER-LEVERAGED. Counterpoint: the 2026-03-31-to-4-07 flood is directly responsible for the Phase-2 drop regression (84-100% drops that week). Re-enabling without a rate limiter would reproduce it.

## 9. `volume_scanner.py` / `earnings_calendar.py` / `reddit_trend.py` — structurally dead

All three modules are written, but none is imported in `main.py`. `volume_scanner.enabled: true` at `config/consensus.yaml:160` (rvol threshold 5.0) and `intervals.reddit_trend: 14400` at `:87` are config ghosts — no code reads them. Working modules, no wiring.

## 10. SearXNG

Tier 4 of news cascade (`config/consensus.yaml:80`). Returns `{title, url, content, engines, score}`; `news.py` classifies only on `title`. `content` (often a full-sentence snippet) is dropped before any regex. Self-hosted on `localhost:8888` (`config/consensus.yaml:25-27`) — free compute already paid for. Structural gap.

---

## Rubric Audit — per-tier empirical verdict

Rubric lives at `config/consensus.yaml:30-72`. Verdicts below are per-tier: KEEP / RE-WEIGHT / KILL.

| Rubric item | Value | Empirical verdict | Why |
|-------------|-------|-------------------|-----|
| `conviction.high` | 30 | **KILL as 3-tier** | 570/575 alerts = base=25; only 3 high + 2 low exist in DB. Not a distribution — a default value. |
| `conviction.medium` | 25 | KEEP (de facto only) | 99.1% of alerts |
| `conviction.low` | 20 | **KILL as 3-tier** | 2/575 alerts |
| `additional_analyst` | 20 | KEEP | fires on ~10% of breakdowns; AMD example has +20 |
| `news_catalyst` | 15 | KEEP | ~60% fire rate on recent breakdowns, still driving dispersion |
| `sec_filing` | 15 | KEEP when watchers on | 2/5 recent alerts show +15; historical SEC-8K window shows scoring applied |
| `social_apewisdom` | 10 | KEEP | Fires on 80% of recent alerts |
| `social_stocktwits` | 10 | **KILL** | disabled at `config/consensus.yaml:104`; 0 fires ever |
| `social_reddit` | 10 | **KILL** | 0 fires across 5 recent alert breakdowns despite 908 reddit_posts + 764k apewisdom rows |
| `google_trends` | 5 | **RE-WEIGHT or KILL** | 0 fires across 5 recent breakdowns; pytrends rate-limiting is brittle |
| `technical_per_filter` / `technical_max` | 2 / 12 | KEEP | fires on most alerts; AMD had 0, others 4-6 pts |
| `llm_boost_max` | 15 | KEEP | fires sporadically (GOOG +8, AMZN +20 — note AMZN exceeded max, bug?) |
| `options_flow` | 10 | **KILL** | 0 fires across 5 recent breakdowns |
| `catalyst_tiers.high (25)` — Earnings Beat / M&A / FDA / Gov Contract / Short Squeeze | 25 | **KEEP direction, small sample** | M&A (n=15): 46.7% 1h hit / 60% 24h hit. Short Squeeze (n=2): 50% / 100%. Earnings Beat (n=1): 100% / null. Empirically a top-tier pick. |
| `catalyst_tiers.medium (15)` — Analyst Upgrade / SEC Filing / Insider Buying / Guidance / Analyst Downgrade | 15 | **RE-WEIGHT UP** | Analyst Upgrade (n=39): 35.9% / 61.5%. Analyst Downgrade (n=25, treated as +15 bull??): 36% / 85.7%. Downgrades are producing *higher* 24h hit rates than upgrades — this is a direction-bug, not a tier-weight issue. |
| `catalyst_tiers.low (8)` — Partnership / Patent / Product Launch / Breaking News / Dividend | 8 | **RE-WEIGHT** | Partnership (n=3): 66.7% / 0%. Dividend (n=18): 50% / 62.5%. Product Launch (n=9): 44.4% / 75%. Dividends hitting 50/62 are out-performing expected — tier-low label wrong, or tier-low is fine and top rubric needs fewer points. |
| `catalyst_type` empty | — | **FIX pipeline** | 39/160 = 24.4% of rows have empty catalyst_type. Phase-2 is silently dropping the tag in 1 of 4 firings. |

**The empirical join that matters:** `final_score` vs forward return, excluding SEC flood (n=120 non-SEC, with a measured 1h outcome):
- 30-band (final 25-34): 94.1% 1h hit (n=17). **Strongest band.**
- 40-band: 58.3%
- 50-band: 44.0%
- 60-band: 21.2% (!!)
- 70-band: 25.0%
- 80+: 100% (n=3, unreliable)

This is **inverted monotonicity** above 30. The engine's higher-scored alerts are performing *worse* than its mid-scored ones at the 1h horizon. Either `confidence_score` is mis-calibrated (plausible — calibration layer is dead), or higher scores correlate with precision-engine early-exit survivors that got published anyway, or the scoring multipliers are over-counting correlated sources (news + apewisdom + technical all spike together for mainstream names that had already moved). **This alone is the single strongest argument for turning calibration on and re-binning by empirical quantile.**

---

## Raw SQL Output Appendix

### (1) `signal_events` by source_type

```
('youtube', 23, 1776847299.586029, 1776847299.613659)
```
Only 23 rows, all from YouTube, all from one video_id `4mSyMr8PGLI`. **Tweets never land in `signal_events`.** (cross_reference queries this table at `:333`.)

### (2) `source_performance` — EMPTY

```
(Total rows: 0)
```
The canonical per-source performance table is empty. No `fired_count` / `hit_count` column exists on that table (schema is `entity_id, horizon, rolling_accuracy, sample_count, updated_at`) — and even on the schema that exists, there are 0 rows. **Reliability engine is not writing to its own evidence store.**

### (3) Repeat-fire tickers — cooldown effectiveness

```
('TSLA', 8, 2, 1, 8, 6)
('MSFT', 7, 2, 4, 7, 5)
('META', 5, 0, 3, 5, 3)
('PLTR', 5, 0, 0, 5, 3)
('CIFR', 3, 3, 1, 3, 2)
('NVDA', 3, 2, 0, 3, 1)
... (plus many n=1 tickers)
```
Columns: `ticker | alerts | hits_1h | hits_24h | measured_1h | measured_24h`. TSLA 8 alerts over 26 days (cooldown intact). MSFT had two same-analyst alerts 26 min apart on 2026-03-29 (cooldown race). PLTR 5 fires, **0 hits at either horizon** (pure noise).

### (4) Time-of-day skew

```
('00', 1, 65.0) ('01', 14, 61.9) ('02', 1, 39.0) ('04', 1, 44.0)
('08', 1, 27.0) ('09', 4, 53.0) ('10', 5, 54.4) ('11', 5, 55.0)
('12', 13, 55.8) ('13', 54, 48.2) ('14', 32, 60.5) ('15', 3, 56.3)
('16', 3, 65.7) ('17', 4, 61.5) ('18', 4, 53.0) ('19', 2, 58.0)
('20', 4, 53.5) ('21', 1, 65.0) ('22', 2, 38.0) ('23', 6, 60.3)
```
UTC hours. Hour 13 UTC = 09:00 ET (market open): 54 alerts (9.4% of all) — alert density concentrated around US open + first hour. Overnight hour 01 UTC has 14 alerts (2.4%) — also active, likely SEC-8K residue.

### (5) Calibration dead

```
22 decision_snapshots rows
Every feature_vector_json: {"total_sources": 0, "unique_source_types": 0, "bull_count": 0, ..., "signal_event_count": 0}
```
Snapshot feature vectors are empty. Not only is the calibration model untrained — the inputs never got wired either.

### (6) Phase-2 silent drop (headline finding)

```
instants=575, missing_phase2=451, missing_instant=0
```
**78.4% of instant alerts never receive a Phase-2 follow-up embed.** By day:
```
2026-03-28: 0/8 drop
2026-03-29: 0/10 drop
2026-03-30: 0/1 drop
2026-03-31: 77/92 (84%) — SEC spam begins
2026-04-01: 106/106 (100%)
2026-04-02: 85/85 (100%)
2026-04-03: 47/47 (100%)
2026-04-06: 66/66 (100%)
2026-04-07: 34/34 (100%) — SEC still flooding
2026-04-08: 1/67 (1%) — SEC fix deployed, normal service resumes
2026-04-12: 0/9
2026-04-15: 0/4
2026-04-20: 8/9 (89%) — regression begins again
2026-04-22: 0/1
2026-04-23: 27/36 (75%) — current state: 3 of 4 alerts are orphaned
```

### (7) Conviction tier empirical (by base_score band using alert_messages → alert_history join)

```
base_score=20: n=2, 1h hit=null, 24h hit=null
base_score=25: n=570, 1h hit=47.1%, 24h hit=62.3%
base_score=30: n=3,   1h hit=33.3%, 24h hit=100%
```
No usable signal in the 3-tier rubric — sample concentrations make it indistinguishable from a flat "25".

### (8) Non-SEC final_score bucket lift (the real calibration evidence)

```
final_score=29 (band 20): n=7,  1h=40.0%, 24h=0.0%
final_score=39 (band 30): n=17, 1h=94.1%, 24h=100.0%
final_score=44 (band 40): n=27, 1h=53.8%, 24h=75.0%
final_score=54 (band 50): n=28, 1h=39.3%, 24h=75.0%
final_score=60 (band 60): n=34, 1h=20.6%, 24h=59.1%
final_score=75 (band 70): n=9,  1h=11.1%, 24h=71.4%
final_score=83 (band 80): n=3,  1h=100%, 24h=null
final_score=100 (band 100): n=1
```
1h hit rate is NON-MONOTONIC with final_score. 30-band outperforms 80-band. Calibration must be turned on.

### (9) Catalyst tier hit rate

```
('Analyst Upgrade',   n=39, 1h=35.9%, 24h=61.5%)
('',                  n=39, 1h=64.9%, 24h=60.0%) — empty catalyst_type
('Analyst Downgrade', n=25, 1h=36.0%, 24h=85.7%) — NOTE: downgrades on bullish alerts
('Dividend',          n=18, 1h=50.0%, 24h=62.5%)
('M&A',               n=15, 1h=46.7%, 24h=60.0%)
('Product Launch',    n=9,  1h=44.4%, 24h=75.0%)
('Partnership',       n=3,  1h=66.7%, 24h=0.0%)
('IPO',               n=3,  1h=33.3%, 24h=50.0%)
('Breaking News',     n=3,  1h=0.0%,  24h=66.7%)
('Short Squeeze',     n=2,  1h=50%,   24h=100%)
('Patent',            n=1,  1h=100%,  24h=null)
('Insider Selling',   n=1,  1h=0.0%,  24h=0.0%)
('Earnings Miss',     n=1,  1h=100%,  24h=null)
('Earnings Beat',     n=1,  1h=100%,  24h=null)
```

### (10) Per-analyst empirical precision

```
('SEC-8K',       n=395, matched=11, 1h=0.0%,  24h=90.9%)
('TeresaTrades', n=41,  matched=41, 1h=82.9%, 24h=null)
('MarketRebels', n=39,  matched=31, 1h=45.2%, 24h=50.0%)
('The_RockTrading', n=23, matched=15, 1h=33.3%, 24h=50%)
('OMillionaires', n=12, matched=9,  1h=33.3%, 24h=60%)
('DeItaone',     n=9,   matched=9,  1h=37.5%, 24h=33.3%)
('OptionAlert',  n=8,   matched=7,  1h=42.9%, 24h=null)
('ripster47',    n=7,   matched=4,  1h=50%,   24h=100%)
('kpak82',       n=7,   matched=7,  1h=14.3%, 24h=71.4%)
('Sarge986',     n=6,   matched=5,  1h=60%,   24h=0%)
('preetkailon',  n=5,   matched=1,  1h=0%,    24h=0%)
('WallStJesus',  n=5,   matched=5,  1h=40%,   24h=80%)
```
**Precision spreads from 14% to 83% at 1h** — per-analyst weighting would be the cheapest, highest-lift change in the engine, and the data to train it is already sitting in `alert_history`.

### (11) `ticker_signals` storage volumes

```
('apewisdom',     764,435 rows)
('google_trends', 3,067 rows)
('twitter',       252 rows)
```
`ticker_signals` is the signal table used by `insert_signal()`. **`signal_events` (the one xref reads) has 23 rows.** Two parallel tables with near-zero overlap — data-coupling defect.

### (12) `xref_cache` freshness

```
min=2026-04-08 09:20:51, max=2026-04-23 17:45:36, count=107
```
No TTL enforcement visible in this table (only `cached_at`); 107 rows over 15 days ≈ 7/day, consistent with alert volume.

### (13) `youtube_level_alerts` — repeat-fire dominance

```
TALK support $5.17 (Lottery Stocks): 7 alerts in 24h
XLK resistance $158/$156.54 (TheStockWatch): 7 alerts
SMH resistance $482.50 (Figuring Out Money): 5 alerts
BE resistance $230 (TheStockWatch): 3 alerts
GME entry_low $25.38: 1
MSFT resistance $421.45: 1
TSLA support $379.57: 1
```
**19 of 25 alerts (76%) are repeats on 4 ticker-level pairs.** Dedup at `main.py:430` is broken.

---

**End of Phase B draft.**
