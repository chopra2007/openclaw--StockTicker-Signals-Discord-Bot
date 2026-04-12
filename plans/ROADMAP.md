# YouTube Intelligence System — Master Roadmap

Living document. All future plans and WIP live in `plans/`.
Source plans: `ytplan.md` (operational), `ytplan2.md` (unified/aspirational), `IMPLEMENTATION_PLAN.md` (precision routing).

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
- [ ] Trigger: `parsed_video.overall_conviction == HIGH` AND `tickers[].direction != neutral`
- [ ] Channel credibility gate (config threshold, default 0.5)
- [ ] Phase 1 alert format (🎬 YouTube Signal) via `alerts/discord.py`
- [ ] Phase 2 follow-up reuses existing cross-reference reply path
- [ ] Config keys: `youtube.standalone_alerts`, `youtube.standalone_alert_min_conviction`

### 2b. Discord Commands (Subsystem 7)
File: `consensus_engine/alerts/commands.py`
- [ ] `!yt <URL>` — on-demand full analysis. **Requires** new `fetch_video_metadata(url)` helper (oEmbed or Invidious `/api/v1/videos/{id}` for title/channel/duration — parser currently receives metadata from RSS only)
- [ ] `!levels $TICKER` — query `youtube_levels` sorted by confidence
- [ ] `!yt-mentions $TICKER` — query `youtube_signals` last 7 days
- [ ] `!macro` — digest from `youtube_macro` (requires 2c)

### 2c. Macro Thesis Persistence (Subsystem 3, partial)
- [ ] New table `youtube_macro` (schema in ytplan.md lines 144-156)
- [ ] Write macro_thesis from parser output in scanner integration
- [ ] Simple `!macro` digest (top 3 themes across channels)

### 2d. Hygiene
- [ ] Close global aiohttp `get_session()` on daemon exit (currently emits "Unclosed client session" warnings on script termination — harmless in long-running daemon, noisy in CLI/tests)
- [ ] Tighten `video_parser._call_openrouter` to handle `finish_reason=length` explicitly (log + retry with more tokens)

---

## ⏳ Week 3 — Level Alerting & Market View

### 3a. Level Proximity Alerter (Subsystem 2, completion)
- [ ] Background loop checks current price vs stored S/R levels (0.5% default)
- [ ] Config: `youtube.level_alert_proximity_pct`
- [ ] Discord alert format: "🎯 $SPY approaching $650 (support flagged by Channel X 3 days ago)"
- [ ] Cooldown to avoid re-firing same level

### 3b. Composite Market Direction Score (Subsystem 3, completion)
- [ ] `market_score()` combining: youtube_macro avg, tweet sentiment, SPY/QQQ technicals, social
- [ ] Output: `STRONGLY_BULLISH | BULLISH | NEUTRAL | BEARISH | STRONGLY_BEARISH` + confidence
- [ ] `!market-view` Discord command

### 3c. Channel Credibility Tracker (Subsystem used by 2a gate)
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

## 🔀 Precision-First Signal Engine (IMPLEMENTATION_PLAN.md)

Independent track — likely Week 6+ or parallel. Not wired to YouTube system yet.

- [ ] `adapter_protocols.py` (Finnhub, Brave, Exa, SerpApi, Firecrawl, Marketstack, Apify)
- [ ] `api_adapters.py` implementations
- [ ] `engine.py` with `BudgetManager` (daily caps in SQLite) + `analyze_signal()` escalation
- [ ] Decision output: `STRONG_ALERT | WATCHLIST | IGNORE`
- [ ] Integrate with tweet pipeline (replace/augment current cross-reference)

**Open question:** is this replacing the current cross_reference.py routing, or running alongside it? (see Questions below)

---

## 📋 Known Tech Debt (from prior sessions)

Per `MEMORY.md` auto-memory:
- [ ] `requirements.txt` missing — users currently pip install ad-hoc (project_codex_review.md)
- [ ] Per-source timeout counters for observability (project_codex_review.md)
- [ ] TUI input-clear bug (project_outstanding_work.md)

---

## ❓ Open Questions for Akash

1. **Plan reconciliation:** `ytplan.md` and `ytplan2.md` overlap but have different philosophies (ytplan = pragmatic 10-subsystem build, ytplan2 = full reliability/calibration/probabilistic architecture). Do you want ytplan2 to **replace** ytplan Weeks 4+ or **extend** it? My default: treat ytplan2 as Weeks 4-5 hardening layer on top of ytplan MVP.
2. **Precision engine (IMPLEMENTATION_PLAN.md):** Is this a **replacement** for the existing tweet cross-reference routing, or a **parallel track** (e.g., for a different signal class)? Your call affects whether it's urgent or deferrable.
3. **Channel credibility cold start:** How should we seed `credibility_score` before outcome tracking has data? Options: (a) all 0.5, (b) manual per-channel config, (c) derived from subscriber count. Default: (a).
4. **Level proximity cadence:** Check every minute? Every 15 min? On every tweet poll cycle? Cheaper = less responsive.
5. **Metadata fetch for `!yt <URL>`:** Prefer oEmbed (simpler, official) or Invidious `/api/v1/videos/{id}` (richer, already cascaded)? I'd default to oEmbed for reliability.
6. **Macro digest format:** daily Discord summary, on-demand `!macro` only, or both?

Answer inline in this file or reply in chat — I'll update the roadmap accordingly.

---

## 🗂 File Conventions

- This doc: `plans/ROADMAP.md` — master state, updated each session
- Per-task plans: `plans/week-N-task-M-<slug>.md`
- Research artifacts: `.omc/research/<slug>.md` (already used for Task #6)
- Drafts/discarded: `plans/archive/`

Last updated: 2026-04-11 (end of session after Week 1 Task #6 + reasoning-model fix).
