# YouTube Intelligence System — Master Roadmap

Living document. All future plans and WIP live in `plans/`.
Source plans: `ytplan.md` (operational), `ytplan2.md` (unified/aspirational), `IMPLEMENTATION_PLAN.md` (precision routing).

---

## Current Decision Architecture

Precision engine gates suppression/alert/IGNORE. Cross-reference provides breakdown enrichment. Reliability engine is Week 4, currently disabled via config flag.

---

## ✅ Week 1 — MVP (SHIPPED)

Commits: `a0895f9` (MVP), `0865243` (reasoning-model fix + Task #6 validation).

| Task | Status | Notes |
|---|---|---|
| 1. Data models (ParsedVideo, VideoTickerMention, PriceLevel, MacroThesis, SourceType.YOUTUBE) | ✅ | `consensus_engine/models.py` |
| 2. DB schema (youtube_signals, youtube_levels; youtube_videos/transcripts pre-existed) | ✅ | `consensus_engine/db.py` — 4 helper fns |
| 3. `video_parser.py` — LLM extraction, 300-word chunking, merge logic, regex fallback | ✅ | Groq → OpenRouter fallback |
| 4. `scanners/youtube.py` — call parser after transcript fetch | ✅ | |
| 5. `cross_reference.py` — 8th source, `_get_youtube_context()`, +15/+10/+5 boost by conviction | ✅ | |
| 6. Validation on real Shorts URL | ✅ | Report: `.omc/research/week1-task6-video-parser-validation.md` |
| 7. Reasoning-model LLM fix (minimax content=null) | ✅ | Fixed in video_parser/tweet_parser/llm_scorer |

**Verification:** 233/233 tests pass. End-to-end live test:
Supadata → SPY long/high → DB → `YouTubeContext(score_boost=15)`.

---

## ⏳ Week 2 — Alerting & On-Demand Commands

### 2a. Standalone YouTube Alerts (Subsystem 5 in ytplan.md)
- [x] Trigger: `parsed_video.overall_conviction == HIGH` AND `tickers[].direction != neutral` — 🔄 worker-1 (task 4)
- [x] Channel credibility gate (config threshold, default 0.5) — 🔄 worker-1 (task 3)
- [ ] Phase 1 alert format (🎬 YouTube Signal) via `alerts/discord.py` — in plan (task 4)
- [ ] Phase 2 follow-up reuses existing cross-reference reply path — in plan
- [ ] Config keys: `youtube.standalone_alerts`, `youtube.standalone_alert_min_conviction` — in plan (task 4)

### 2b. Discord Commands (Subsystem 7)
File: `consensus_engine/alerts/commands.py`
- [ ] `!yt <URL>` — on-demand full analysis with oEmbed title/channel fetch — in plan (task 9)
- [ ] `!levels $TICKER` — query `youtube_levels` sorted by confidence — in plan (task 9)
- [ ] `!yt-mentions $TICKER` — query `youtube_signals` last 7 days — in plan (task 9)
- [ ] `!macro` — digest from `youtube_macro` — in plan (task 9)

### 2c. Macro Thesis Persistence (Subsystem 3, partial)
- [ ] New table `youtube_macro` (schema in ytplan.md lines 144-156) — in plan (task 4)
- [ ] Write macro_thesis from parser output in scanner integration — in plan (task 4)
- [ ] Simple `!macro` digest (top 3 themes across channels) — in plan (task 9)

### 2d. Hygiene
- [x] Close global aiohttp `get_session()` on daemon exit — ✅ Phase 4b done (`utils/http.close_session()` called in `run_live` shutdown path)
- [x] Tighten `video_parser._call_openrouter` to handle `finish_reason=length` — 🔄 worker-1 (task 1)
- [x] Fix video_parser Direction enum mismatch — 🔄 worker-1 (task 1)
- [x] Gate reliability engine behind config flag — 🔄 worker-1 (task 2)
- [x] Precision engine as gating decision-maker in `main.py` — ✅ Phase 0c done (IGNORE suppresses follow-up, classification persisted in breakdown)

---

## ⏳ Week 3 — Level Alerting & Market View

### 3a. Level Proximity Alerter (Subsystem 2, completion)
- [ ] Background loop checks current price vs stored S/R levels (0.5% default) on every tweet poll cycle — in plan (task 10)
- [ ] Config: `youtube.level_alert_proximity_pct`
- [ ] Discord alert format: "🎯 $SPY approaching $650 (support flagged by Channel X 3 days ago)"
- [ ] Cooldown to avoid re-firing same level (`youtube_level_alerts` table, 4hr cooldown) — in plan (task 10)

### 3b. Daily Macro Digest
- [ ] Background loop posting daily `!macro` result to Discord #alerts at configurable UTC hour — in plan (task 10)
- [ ] DB timestamp flag to prevent duplicate daily posts

### 3c. Composite Market Direction Score (Subsystem 3, completion)
- [ ] `market_score()` combining: youtube_macro avg, tweet sentiment, SPY/QQQ technicals, social
- [ ] Output: `STRONGLY_BULLISH | BULLISH | NEUTRAL | BEARISH | STRONGLY_BEARISH` + confidence
- [ ] `!market-view` Discord command

### 3d. Channel Credibility Tracker (Subsystem used by 2a gate)
- [ ] New table `youtube_channels` (credibility_score, total_calls, correct_calls)
- [ ] Outcome tracker: after N days, compare stored calls to actual price action
- [ ] `!channel-score` Discord command

---

## ⏳ Week 4 — Volatility & Hardening

### 4a. Volatility Prediction (Subsystem 6)
- [ ] Fear/greed phrase scoring across transcripts
- [ ] 30-day rolling baseline per channel
- [ ] Alert on 1.5σ deviation

### 4b. Unified Reliability Engine (pulls from ytplan2.md §4)
- [ ] `SignalEvent` schema with `quality_score`, `latency_sec`, `provenance`, `model_version`
- [ ] Per-source reliability weight: `W = R_class · R_entity · Q · D · I`
- [ ] Contradiction index: `C = min(S_bull, S_bear) / max(S_bull, S_bear)`
- [ ] `UNCERTAIN` / `INSUFFICIENT_EVIDENCE` abstain paths
- [ ] Origin-graph / independence discount (prevent echo amplification)

### 4c. Calibration
- [ ] Isotonic/Platt calibration pipeline on walk-forward holdout
- [ ] Calibrated confidence displayed in alerts (not raw heuristic)

---

## ⏳ Week 5+ — Probabilistic Outputs & Memory (ytplan2.md scope)

### 5a. Probabilistic Trade Ideas (ytplan2.md §5.3)
- [ ] Output: `P(up/down/flat)` per horizon, entry/invalidation/target bands, EV
- [ ] `NO_TRADE` when EV≤0 or contradiction too high

### 5b. Scenario Retrieval (ytplan2.md §6)
- [ ] Immutable decision snapshots (feature vector + weights + outcomes)
- [ ] pgvector similarity retrieval
- [ ] Realized-outcome backfill job

### 5c. Degraded Modes & Freshness Gates (ytplan2.md §7-8)
- [ ] Per-source heartbeat monitors
- [ ] Modes: `NORMAL`, `DEGRADED_NARRATIVE`, `DEGRADED_FLOW`, `NO_TRADE_MODE`
- [ ] Snapshot-locked as-of watermark so all inputs share a timestamp
- [ ] p95 latency targets: ingest≤15s, score≤20s, publish≤10s

---

## ✅ Precision-First Decision Engine (ACTIVE)

Gating layer: `engine.py` `analyze_signal()` returns `STRONG_ALERT | WATCHLIST | IGNORE` for each signal.
`IGNORE` suppresses the Discord follow-up embed. Cross-reference (`cross_reference.py`) runs in parallel for breakdown enrichment only — it does not gate alerts.

- [x] `adapter_protocols.py` (Finnhub, Brave, Exa, SerpApi, Firecrawl, Marketstack, Apify)
- [x] `api_adapters.py` implementations
- [x] `engine.py` with `BudgetManager` (daily caps in SQLite) + `analyze_signal()` escalation
- [x] Decision output: `STRONG_ALERT | WATCHLIST | IGNORE`
- [x] Integrated with tweet pipeline — precision classification gates Discord follow-up; xref score persisted as enrichment alongside `precision_classification` in `alert_breakdown`

---

## 📋 Known Tech Debt (from prior sessions)

Per `MEMORY.md` auto-memory:
- [ ] `requirements.txt` missing — users currently pip install ad-hoc (project_codex_review.md)
- [ ] Per-source timeout counters for observability (project_codex_review.md)
- [ ] TUI input-clear bug (project_outstanding_work.md)

---

## ✅ Resolved Decisions

1. **Plan reconciliation:** `ytplan2.md` extends `ytplan.md` — ytplan2 is the Week 4-5 reliability/calibration/probabilistic hardening layer on top of the ytplan MVP. The two plans are not competing; ytplan2 kicks in after Week 3.

2. **Precision engine role:** Precision engine (`engine.py`) is the **primary gating layer** — it decides STRONG_ALERT / WATCHLIST / IGNORE. Cross-reference (`cross_reference.py`) runs as a parallel enrichment pass and contributes breakdown detail, but does not gate the alert. IGNORE from precision suppresses the Discord follow-up.

3. **Channel credibility cold start:** Default all channels to `credibility_score = 0.5` until outcome tracking accumulates data.

4. **Level proximity cadence:** Check on every tweet poll cycle (not a separate timer loop). Minimises extra infrastructure while keeping responsiveness tied to active market hours.

5. **Metadata fetch for `!yt <URL>`:** Use oEmbed (`https://www.youtube.com/oembed?url=...&format=json`) for title and channel. Simpler and official; Invidious API available as fallback if needed.

6. **Macro digest format:** Both — `!macro` on-demand command (task 9) plus a scheduled daily Discord post at a configurable UTC hour on weekdays (task 10, `youtube.macro_digest_utc_hour` config key).

---

## 🗂 File Conventions

- This doc: `plans/ROADMAP.md` — master state, updated each session
- Per-task plans: `plans/week-N-task-M-<slug>.md`
- Research artifacts: `.omc/research/<slug>.md` (already used for Task #6)
- Drafts/discarded: `plans/archive/`

Last updated: 2026-04-17 (ytfinal session — precision engine activated, session close fix, Week 2 progress reflected).
