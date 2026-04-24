# 00 — System Map (Discovery Phase 0)

**Date:** 2026-04-24
**Scope:** Capability-oriented map of the `consensus_engine` Discord trade-idea bot. Phase-1 researchers will use this to blind-map candidate features against existing capabilities. Defects/refactors live in `plans/AUDIT_RESEARCH_2026-04-24.md` (out of scope here).
**Repo root:** `/root/.openclaw/workspace`

---

## 1. Pipelines

For each active input → output cycle: entry, scanner, research, analysis, alert, Discord. State on/off + blocking calls + queue/latency.

### 1.1 Discord TweetShift tweet flow (sole Phase-1 firer)

**Status:** ON. Sole live alert trigger.

| Stage | File:line |
|-------|-----------|
| Entry (Discord Gateway WS) | `consensus_engine/scanners/discord_tweetshift.py:284–337` (`_connect_once`) |
| Message dispatch | `discord_tweetshift.py:209–267` (`_handle_dispatch` → `MESSAGE_CREATE` → channel match) |
| Wired into main loop | `consensus_engine/main.py:336` (`tweetshift_listener.run`) |
| Tweet handler | `main.py:553–653` (`process_tweet`) |
| Dedup | `main.py:568` (`db.check_seen_tweet`); mark `:570` |
| Multimodal parser | `consensus_engine/analysis/tweet_parser.py:145–180` (`parse_tweet` → `process_multimodal_tweet`) |
| Quality gate | `main.py:505–525` (`_passes_quality_gate`) — blocks `8-K`, `edgar`, `form 4`, `< 10` chars, base score < 20 |
| Market-cap filter | `main.py:597`; impl `consensus_engine/utils/tickers.py` (`validate_ticker_market_cap`) |
| Signal store (dual write) | `db.py:578–619` (`insert_signal`) — writes `ticker_signals` + Q2b `signal_events` for `SourceType.TWITTER` |
| Per-analyst cooldown | `main.py:609`; impl `db.py:714–781` (`check_alert_cooldown`) — high-conv bypass, precision-scaled minutes |
| Degraded-mode suppress | `main.py:613–620` |
| Phase-1 instant Discord ping | `main.py:624`; impl `consensus_engine/alerts/discord.py:316–363` (`send_instant_ping`) |
| Persist alert + alert_message | `main.py:628–643` (`db.insert_alert`, `db.insert_alert_message`) |
| Phase-2 fire-and-forget xref | `main.py:644–653` — `asyncio.create_task` of `_run_cross_reference_and_followup` |
| Phase-2 timeout enforcement (Q2a) | `main.py:672–696` — `asyncio.wait_for(asyncio.shield(xref_task), timeout=cfg.intervals.cross_reference_timeout)` (default 120 s) |
| Phase-2 followup post | `main.py:710`; impl `alerts/discord.py:471–507` (`send_detail_followup`) |
| Phase-2 skip-reason edits | `main.py:694–699` → `alerts/discord.py:366–397` (`edit_instant_ping`) |
| Atlas enqueue side-effect | `db.py:799–804` (called from `insert_alert`) |
| Shadow-mode calibration log | `main.py:715–731` → `analysis/calibration.py:143–175` (`log_shadow_prediction`) |

Blocking calls in this flow: none in Phase-1 (Finnhub `/quote` is async aiohttp). Phase-2 invokes yfinance via `_fetch_yfinance_price` only inside the separate `price_outcome_loop` ThreadPoolExecutor.
Latency (P-1 to P-2): bounded by `intervals.cross_reference_timeout=120` (`config/consensus.yaml:88`).
Exit channel: Discord text channel `cfg.api_keys.discord_channel_id`.

### 1.2 YouTube intelligence flow (transcript → signals → standalone alert + xref boost)

**Status:** ON (`youtube.enabled: true` `config/consensus.yaml:224`).

| Stage | File:line |
|-------|-----------|
| Poll loop entry | `consensus_engine/scanners/youtube.py:821–843` (`youtube_poll_loop`) |
| Wired into main | `main.py:339` (`asyncio.create_task(youtube_poll_loop)`) |
| Channel sources | DB `youtube_channels` (seeded from `/root/.openclaw/sources.json`) + YAML `youtube.channel_ids` (`youtube.py:771–775`) |
| RSS metadata | `youtube.py:35–77` (`fetch_channel_videos_rss`) |
| Two-stage gate | `youtube.py:510–525` (`use_two_stage` + `gemini_enabled` + `analyze`) |
| Stage A — Gemini evidence extract | `analysis/gemini_video_parser.py` (`extract_evidence_with_gemini`); call site `youtube.py:211` |
| Stage B — classify spans | `analysis/video_classifier.py` (`classify_evidence`); call site `youtube.py:217` |
| Stage C — catalyst resolver/verify | `analysis/catalyst_resolver.py:179–197` (`resolve_and_verify_catalysts`); call site `youtube.py:218` |
| Confidence floor (`min_confidence=0.5`) | `youtube.py:222–238`; cfg `youtube.classifier.min_confidence` (`:271`) |
| Persist signals/levels/setups/catalysts/macro | `youtube.py:255–356` |
| Standalone HIGH-conviction alert | `youtube.py:371–392` + `_send_two_stage_alerts` `:395–479`; gated by `youtube.standalone_alerts` (`config/consensus.yaml:232`) and `youtube.min_trust` (`:233`) — channel trust read from DB |
| Legacy fallback (Gemini fast-path / transcript+parser) | `youtube.py:527–599` |
| Alert delivery | direct POST via `_send_youtube_alert` `youtube.py:171–192` |
| Xref boost feed-in | `cross_reference.py:159–214` (`_get_youtube_context`) — last-7-day mentions; `score_boost` 5/10/15 mapped from conviction; rolled into `breakdown.llm_boost` at `cross_reference.py:295` |
| Level-proximity alerter (sub-pipeline) | `main.py:405–452` (`_check_youtube_level_alerts`) — runs inside `fetch_loop` every 300 s; near-price dedup `youtube.near_price_dedup_pct` (`:275`) and `youtube.level_alert_proximity_pct` (default 0.005) |

Blocking calls: Playwright stealth browser opens at `scanners/youtube.py:813–818` for transcript fallback path. Gemini calls run via aiohttp inside `gemini_video_parser`.

### 1.3 SEC watcher flow (DEFAULT OFF)

**Status:** OFF — `config/consensus.yaml:94` `scanners.sec_background_watchers_enabled: false`.

| Stage | File:line |
|-------|-----------|
| Wiring gate | `main.py:343–347` — only attaches loops when flag true |
| 8-K ATOM feed loop | `main.py:188–221` (`sec_8k_watcher_loop`); 900 s interval |
| Recent-filings polling loop | `main.py:224–257` (`sec_edgar_polling_loop`); 300 s interval |
| 8-K parser/dedup | `consensus_engine/scanners/sec_watcher.py:38–155` |
| EDGAR submissions | `consensus_engine/scanners/sec_edgar.py:64–141` (`check_recent_filings`) |
| Form-4 parser | `sec_edgar.py:173–302` (`fetch_form4_details`) — only called from `alerts/commands.py:507` (manual `!form4`); not wired into background |
| Significance classifier | `sec_edgar.py:144–170` (`classify_filing_significance`) |
| Output | by design these write `signal_events`/`ticker_signals` only — never trigger standalone alert (CLAUDE.md rule + `main.py:206`/`:242` log lines) |
| Xref consumption | `cross_reference.py:80–88` (`_run_sec_check`) — invoked unconditionally in xref `gather` regardless of background flag |

### 1.4 Cross-reference (Phase-2 followup)

**Status:** ON, called for every fired Phase-1 alert.

| Stage | File:line |
|-------|-----------|
| Async-task call site | `main.py:644–653` (`asyncio.create_task(_run_cross_reference_and_followup)`) |
| Followup orchestrator | `main.py:656–746` |
| `cross_reference()` core | `cross_reference.py:217–334` |
| Cache (5-min) | `consensus_engine/utils/xref_cache.py` via `get_cached_xref/cache_xref` (`cross_reference.py:225,320`) |
| Parallel `gather` of 7 sources | `cross_reference.py:231–240` — news/sec/social/technical/other-analysts/options/youtube |
| Per-source semaphores | `cross_reference.py:26–29` (`_sem_news=3 _sem_social=5 _sem_technical=3 _sem_llm=2`) |
| Per-source timeouts | `cross_reference.py:233–239` — 15/10/5/20/5/15/8 s + LLM 15 s `:247` |
| LLM scorer | `cross_reference.py:242–252` → `analysis/llm_scorer.py:102–181` (`score_confidence`) |
| Score assembly | `cross_reference.py:254–293` — base + analysts + news + sec + technical + llm + options + social_breakdown |
| Result cache write | `cross_reference.py:320` (`cache_xref`) |
| `signal_events` window read (always-on, post Q2b) | `cross_reference.py:328–332` (`db.get_signal_events_for_ticker`, 3600 s window) |
| Final embed | `_run_cross_reference_and_followup` → `send_detail_followup` `main.py:710` |
| Precision engine sibling | `main.py:666–668` → `engine.py:267–399` (`analyze_signal`) — runs in same task group; `market_ok` early exit at `engine.py:321–335` with HIGH-conv & SEC-catalyst bypass via `skip_market_gate` `:301–305` |

### 1.5 Catalyst resolver flow (YouTube subcomponent)

**Status:** ON inside the YouTube two-stage pipeline only.

| Stage | File:line |
|-------|-----------|
| Module | `consensus_engine/analysis/catalyst_resolver.py` |
| Entry | `catalyst_resolver.py:179–197` (`resolve_and_verify_catalysts`) — called from `youtube.py:218` |
| Relative-date logic | `catalyst_resolver.py:88–127` (`_resolve_relative_date`) — `_NEXT_WEEKDAY_RE` / `_BARE_WEEKDAY_RE` / dateutil fallback |
| Earnings verify | `catalyst_resolver.py:142–172` (`_verify_earnings`) — pulls Finnhub calendar via `scanners/earnings_calendar.py:25–47` (`fetch_earnings_calendar`) |
| Persist | `db.insert_youtube_catalyst` (called in `youtube.py:326–341`) |
| Output | `verified` field on each `CandidateCatalyst` (1/0/-1); surfaces in standalone YT alerts via `_format_verified` |

Blocking: none (aiohttp). No standalone Discord output — feeds YT alert formatter and DB only.

### 1.6 Calibration output path

**Status:** SHADOW MODE ON (`calibration.shadow_mode.enabled: true` `config/consensus.yaml:201`); retrain disabled (`:202`).

| Stage | File:line |
|-------|-----------|
| Module | `consensus_engine/analysis/calibration.py` |
| Public sync `calibrate()` | `calibration.py:52–72` — identity fallback when no model |
| Async `retrain()` | `calibration.py:75–126` — never auto-invoked; no scheduler call site |
| Shadow logger | `calibration.py:143–175` (`log_shadow_prediction`) — merges into `decision_snapshots.feature_vector_json` |
| Live call sites | `main.py:717` (shadow at xref complete), `alerts/discord.py:107` (Phase-2 embed), `alerts/commands.py:877` (`!score`) |
| Discord output (Q1-aware) | `alerts/discord.py:97–121` (`_calibrated_section`) — when no trained model + shadow_mode true, renders `score/100 (uncalibrated)` instead of fake "Calibrated conf" |
| Model file path | `.omc/state/calibration_model.pkl` (`calibration.py:40`) — does NOT exist on disk currently |

### 1.7 News cascade (`scanners/news.py`)

**Status:** ON, xref-only. No standalone alert.

| Stage | File:line |
|-------|-----------|
| Entry | `consensus_engine/scanners/news.py:279–303` (`news_cascade`) |
| Tier order | `news_cascade.tiers` — `finnhub → google_rss → brave → searxng` (`config/consensus.yaml:74–80`) |
| Tier 1 Finnhub /company-news | `news.py:110–153` |
| Tier 2 Google News RSS | `news.py:156–203` |
| Tier 3 Brave Search | `news.py:206–253` |
| Tier 4 SearXNG | `news.py:256–276` |
| Catalyst classifier | `news.py:50–56` (regex `_CATALYST_PATTERNS` `:26–47`) — classifies title only; body discarded at `:265` (uses `f"{title} {content}"` for SearXNG only) |
| Trusted-source filter | `news.py:65–69` (`news.trusted_sources` `config/consensus.yaml:113–129`) |
| Caller | `cross_reference.py:76` (`_run_news_cascade`) — only path |
| Score impact | `cross_reference.py:256` — `_get_catalyst_score(catalyst_type)` returns tier 25/15/8 from `scoring.catalyst_tiers` (`config/consensus.yaml:48–72`) |

### 1.8 SearXNG path

**Status:** ON. Used as Tier 4 of news cascade and as Atlas news source.

| Stage | File:line |
|-------|-----------|
| Module | `consensus_engine/scanners/searxng.py` |
| Entry | `searxng.py:29–57` (`search_searxng`) |
| Endpoint | `cfg.searxng.base_url` default `http://localhost:8888` (`searxng.py:31`; `config/consensus.yaml:25–27`) |
| Timeout | `searxng.timeout` default 10 s |
| Result fields returned | `{title, url, content}` (`searxng.py:17–26`) |
| Callers | `scanners/news.py:260` (`_search_searxng` Tier 4) and `research/sources.py:111` (`fetch_news_section`) |

### 1.9 Atlas / Vault / Alfred

**Status:** ON, both `atlas.enabled: true` and `alfred.enabled: true` (`config/consensus.yaml:318,329`).

#### Atlas worker

| Stage | File:line |
|-------|-----------|
| Module | `consensus_engine/research/atlas.py` |
| Worker loop | `atlas.py:76–94` (`atlas_worker_loop`) |
| Sweep loop (daily 08:00 ET) | `atlas.py:139–168` (`atlas_sweep_loop`) |
| Wired into main | `main.py:349–350` (worker + sweep created) |
| Trigger 1 — alert side-effect | `db.py:799–804` — every `insert_alert` enqueues `(ticker, "alert")` |
| Trigger 2 — daily sweep | `atlas.py:122–136` (`_sweep_once`) — top-N session tickers |
| Lease semantics | `db.acquire_atlas_lease` — `lease_ttl_seconds=1800` (`atlas.py:80`) |
| Source adapters | `consensus_engine/research/sources.py:67–104` analyst, `:107–128` news (SearXNG), `:175–192` SEC |
| Vault writer | `consensus_engine/research/vault.py:29–67` — atomic write `{vault_path}/tickers/{TICKER}.md` (`vault.path` default `/root/.openclaw/vault`) |

#### Alfred briefing

| Stage | File:line |
|-------|-----------|
| Module | `consensus_engine/briefing/alfred.py` |
| Loop | `alfred.py:295–321` (`alfred_loop`) |
| Wired into main | `main.py:351` |
| Post window | `alfred.post_window_et: ["08:50","09:00"]` (`config/consensus.yaml:331`) |
| Briefing data builder | `alfred.py:19–83` (`build_briefing_data`) — alerts + youtube_levels + youtube_signals + macro + top tickers |
| LLM synth | `alfred.py:86–120` (`_llm_synthesize`) — same `llm.model` as scorer |
| Outbox state machine | `alfred.py:241–280` (`post_briefing`) — pending → posted → archived |
| Discord destination | `alfred.channel_id` / `api_keys.discord_briefing_channel_id` (`config/consensus.yaml:330`) |
| Vault archive | `alfred.py:224–238` (`_write_vault_briefing` → `{vault_path}/macro/briefings/{session_key}.md`) |

### 1.10 Auxiliary loops wired in `run_live`

| Loop | File:line | Interval |
|------|-----------|----------|
| `fetch_loop` (apewisdom + reddit + stocktwits + google_trends) | `main.py:369–380`, `main.py:128–181` (`fetch_signals`) | 300 s |
| YouTube level proximity check | `main.py:405–452` (`_check_youtube_level_alerts`) — called from inside `fetch_loop` | 300 s |
| `price_outcome_loop` (1h/24h fill via yfinance) | `main.py:807–832` — uses ThreadPoolExecutor (4 workers) | 300 s |
| `source_health_updater_loop` | `main.py:749–780` | 60 s (`source_health.poll_interval`) |
| `macro_digest_loop` | `main.py:455–476` | hourly check; posts at `youtube.macro_digest_utc_hour` |
| Weekend pause watchdog | `main.py:312–331` | sleeps until Friday 3pm ET, resumes Sunday 2pm ET |

---

## 2. Capabilities Matrix

| Capability | Module | Data source | Trigger logic | Scoring contribution | Output channel | Wired? |
|------------|--------|-------------|---------------|----------------------|----------------|--------|
| Tweet ingest | `scanners/discord_tweetshift.py` | Discord Gateway WS | `MESSAGE_CREATE` on `discord_feed_channel_id` | base 20/25/30 + analysts × 20 (max 3) | Phase-1 ping + Phase-2 embed | YES — `main.py:336` |
| Slash commands listener | `scanners/discord_tweetshift.py:269–282` + `alerts/commands.py` | Discord Gateway | `MESSAGE_CREATE` on `discord_channel_id` w/ `!` prefix | n/a | command reply | YES |
| ApeWisdom | `scanners/social.py:177` (`scan_apewisdom`) | apewisdom REST | poll 300 s | xref `+10` (`cross_reference.py:46`) | xref breakdown | YES (`main.py:133`) |
| Reddit (PRAW/RSS) | `scanners/social.py:46`, `utils/reddit.py` | Reddit OAuth or RSS | poll 300 s, gated `social.reddit_enabled` (default false) | xref `+10` (≥2 mentions) | xref breakdown | PARTIAL — call site exists `main.py:144` but flag default false |
| StockTwits | `scanners/social.py:105` | Playwright stealth | poll 300 s, gated `social.stocktwits_enabled: false` (`config/consensus.yaml:104`) | xref `+10` | xref breakdown | NO — flag false (`config/consensus.yaml:104`) |
| Google Trends (Pytrends) | `scanners/social.py:303` | pytrends | poll 300 s, auto-disable on 3× 24h failures | xref `+5` | xref breakdown | YES; auto-degrades to Exa fallback |
| Google Trends (Exa fallback) | `scanners/social.py:388` | Exa AI search | invoked when pytrends disabled | xref `+5` | xref breakdown | YES (chained from combined) |
| Google Trends (SerpAPI cron) | `scanners/social.py:481` | SerpAPI | external cron @ 5:50am only | xref `+5` | xref breakdown | PARTIAL — only via cron, not in `run_live` |
| Reddit trend digest | `scanners/reddit_trend.py:108` (`crawl_and_get_trending`) | Reddit | manual `!trend` in `alerts/commands.py:276` | n/a | digest embed | PARTIAL — only via command, not background loop (`config/consensus.yaml:87` `intervals.reddit_trend: 14400` is unread) |
| News cascade | `scanners/news.py` | Finnhub→GoogleRSS→Brave→SearXNG | called from xref `_run_news_cascade` | tiered 25/15/8 (`config/consensus.yaml:48–72`) | xref breakdown | YES (`cross_reference.py:233`) |
| Volume scanner | `scanners/volume_scanner.py:86` | Finnhub `/quote` + yfinance volume | `cfg.volume_scanner.watchlist` only | none — would emit BreakoutResult; no scoring hook | digest format only | NO — no main.py import; `volume_scanner.enabled: true` `config/consensus.yaml:160` is unread |
| Earnings calendar | `scanners/earnings_calendar.py:50` (`scan_upcoming_earnings`) | Finnhub `/calendar/earnings` | only via catalyst_resolver verify (`catalyst_resolver.py:157`) and command | none for direct scoring | Discord digest format | PARTIAL — no scheduled background loop |
| Options flow (yfinance chains) | `scanners/options.py:89` (`check_unusual_options`) | yfinance options chain | called inside xref `_run_options_check` | xref `+10` if `has_unusual_activity` (`cross_reference.py:264`) | xref breakdown | PARTIAL — `executor` defaults to `None` at `cross_reference.py:217` so `check_unusual_options` short-circuits to `None` (`options.py:149–150`); empirically `options_flow=0` |
| Options sweep market scan | `scanners/options.py:134` (`scan_unusual_options_market`) | yfinance options | manual command only | none (digest) | format string | NO main loop wiring |
| SEC EDGAR `check_recent_filings` | `scanners/sec_edgar.py:64` | SEC EDGAR REST | called from xref `_run_sec_check` (`cross_reference.py:80–88`) AND `sec_edgar_polling_loop` | xref `+15` if filings (`cross_reference.py:257`) | xref breakdown | YES from xref; background loop YES only when `scanners.sec_background_watchers_enabled: true` |
| SEC 8-K ATOM watcher | `scanners/sec_watcher.py` | EDGAR ATOM | `sec_8k_watcher_loop` 900 s | stores signal only (no standalone) | DB `ticker_signals` w/ `SourceType.SEC_FILING` | NO by default — `config/consensus.yaml:94` |
| Form-4 detail parser | `scanners/sec_edgar.py:173` (`fetch_form4_details`) | EDGAR XML | manual `!form4` (`alerts/commands.py:507`) | none in scoring | command reply text | PARTIAL — command only; CLAUDE.md says +15 xref but not coded |
| YouTube intelligence (two-stage) | `scanners/youtube.py` + `analysis/gemini_video_parser.py` + `analysis/video_classifier.py` + `analysis/catalyst_resolver.py` | YouTube RSS + Gemini Flash + Playwright transcript fallback | `youtube_poll_loop` 600 s | xref `score_boost` 5/10/15 by conviction (`cross_reference.py:201–202`); rolled into `breakdown.llm_boost` `:295` | standalone Discord alert (HIGH conv) + xref boost | YES (`main.py:339`) |
| YouTube level alerter | `main.py:405–452` | DB `youtube_levels` + Finnhub current price | inside `fetch_loop` 300 s | none | direct Discord message | YES |
| Catalyst resolver (date+earnings verify) | `analysis/catalyst_resolver.py` | dateutil + Finnhub calendar | called from YouTube two-stage `youtube.py:218` | `verified` flag persisted; not in `breakdown` | metadata field on YT signal | YES inside YT pipeline |
| News cascade body classifier | `scanners/news.py:50–56` (`_classify_catalyst`) | regex over title text only | inside news cascade | tier-based 25/15/8 | catalyst_type field | YES; PARTIAL coverage (body discarded for Tiers 1–3) |
| Technical filters (RSI/EMA/VWAP/RVOL/ATR) | `analysis/technical.py:243` (`verify_technical`) + `analysis/indicators.py` | Finnhub `/quote` + Yahoo `/v8/finance/chart` | called from xref `_run_technical` | `+2` per filter cap 12 (`cross_reference.py:32–38`; `config/consensus.yaml:44–45`) | xref breakdown | YES |
| LLM confidence scorer | `analysis/llm_scorer.py:102` (`score_confidence`) | OpenRouter chat | called inside xref when catalyst OR technical present | scaled `score/100 × llm_boost_max=15` (`cross_reference.py:261–262`) | xref breakdown | YES |
| Calibration | `analysis/calibration.py` | sklearn IsotonicRegression / Platt | live `calibrate()` call sites; `retrain()` never auto-invoked | not added to `breakdown`; surfaced as Phase-2 embed text only | Phase-2 embed | PARTIAL — shadow-mode logging YES; trained model NO; `retrain_enabled: false` (`config/consensus.yaml:202`) |
| Regime detector | `analysis/regime_detector.py` | DB `ticker_signals` last-1h sentiment mix | `detect_regime()` | declared `abstain_score_boost: 20` | none | NO — zero callers (verified by `grep`) |
| Precision engine | `engine.py:267` (`analyze_signal`) | Finnhub + Brave + Exa + SerpApi + Firecrawl (escalating) | called from `_run_cross_reference_and_followup` `main.py:666` | independent score; classifies `STRONG_ALERT/WATCHLIST/IGNORE` | `Precision Engine` field in Phase-2 embed | YES (`precision_engine.enabled: true` `config/consensus.yaml:279`) |
| Source health monitor | `main.py:749` + `_record_source_ok/_record_source_error` | in-process counters | `source_health_updater_loop` 60 s | drives `DEGRADED_MODE` flag (`alerts.suppress_when_degraded: false`) | DB `source_health` table; suppress hint `main.py:613–620` | YES |
| Atlas research (vault writer) | `research/atlas.py` + `research/sources.py` + `research/vault.py` | TweetShift+SearXNG+SEC EDGAR via DB+API | `enqueue_atlas_job` triggered from `db.insert_alert`; nightly sweep at 08:00 ET | none in alert score | `{vault_path}/tickers/{TICKER}.md` markdown file | YES |
| Alfred morning briefing | `briefing/alfred.py` | DB alerts + yt levels + yt signals + macro + research_sections | `alfred_loop` 60 s tick + 08:50–09:00 ET window | none | Discord briefing channel + `{vault_path}/macro/briefings/{session_key}.md` | YES |
| Macro digest | `main.py:455–476` (`macro_digest_loop`) + `alerts/commands.py.build_macro_digest` | DB `youtube_macro` | hourly check, posts at `youtube.macro_digest_utc_hour=11` | none | Discord alerts channel | YES |
| Weekend pause | `main.py:89–122,312–331` | system clock | Fri 3pm → Sun 2pm ET | n/a | command listener only | YES |

---

## 3. Strengths

1. **Two-phase Discord alert split** — instant Phase-1 ping is async-decoupled from xref latency. Phase-2 timeout (`asyncio.wait_for(asyncio.shield(xref), timeout=120)` `main.py:676`) and explicit "Phase 2 skipped" edits (`main.py:694–699`) prevent silent failures.
2. **Per-source semaphores + per-source timeouts in xref** — `cross_reference.py:26–29` (3/5/3/2) plus 7 distinct `_with_timeout` budgets `:233–239`. One slow tier never blocks the others.
3. **Budget manager with daily atomic rollups** — `engine.py:50–151` (`BudgetManager.consume`) tracks Finnhub/Brave/Exa/SerpApi/Firecrawl/Gemini per UTC day in `api_usage_daily`. Escalation in `analyze_signal` (`engine.py:339–376`) only spends Exa→SerpApi→Firecrawl as score crosses thresholds.
4. **Three-stage YouTube evidence pipeline** — Stage A Gemini extracts spans (`gemini_video_parser`), Stage B classifies (`video_classifier`), Stage C verifies dates against Finnhub earnings calendar (`catalyst_resolver._verify_earnings`). External calendars treated as truth, LLM as witness.
5. **Per-analyst precision-weighted cooldown (M3)** — `db.check_alert_cooldown` `:714–781` scales window length from `cooldown_hours*60` down to `floor_minutes` based on `source_performance.rolling_accuracy`; HIGH-conviction full bypass; analyst < 5 samples falls back to blanket.
6. **Outbox-style Alfred briefing state machine** — `alfred.py:241–280` cycles `pending → posted → archived` with idempotent retry on Discord post failure; vault archive only after Discord success.
7. **Atomic file writes everywhere** (vault tickers `vault.py:60–63`, calibration model `calibration.py:213–224`, briefing archives `alfred.py:224–238`) — `tmp + os.replace` pattern means crashes never leave half-written state.
8. **Source-health driven `DEGRADED_MODE`** — `main.py:68–86` per-source `last_ok`/`error_rate`, `main.py:82–86` triggers when ≥2 critical sources unhealthy, footer flag on Phase-1 embed at `alerts/discord.py:340`.

---

## 4. Capability Gaps (NOT bug fixes — additive surface area)

Each line: WHAT is missing · WHY it would matter for a free-tier signal-first retail engine.

- **No insider Form-4 velocity / cluster-buy signal** — `fetch_form4_details` exists at `scanners/sec_edgar.py:173` but only as a manual `!form4` command. No rolling "N distinct insiders bought $X in trailing 10 days" computation. Cluster buys are peer-reviewed alpha (Lakonishok-Lee 2002, Cohen-Malloy-Pomorski 2012) and openinsider.com is free.
- **No options term-structure / IV-rank / put-call skew feature** — `scanners/options.py` is binary (`has_unusual_activity` from vol/OI). No IV percentile, no front-month vs back-month comparison, no risk-reversal at 25Δ. Term-structure inversion before binary catalysts is documented retail edge (IBKR 2025).
- **No short-interest / borrow / utilization delta** — Stocksera-style scrapers absent. Free FINRA bi-monthly reports + IBKR utilization API exist; no scanner.
- **No dark-pool / lit-vs-dark print divergence** — no FINRA ATS-N data ingest.
- **No earnings-drift (PEAD) tracker** — `scan_upcoming_earnings` exists but nothing tracks N-day post-print drift to score similar setups.
- **No FRED / macro-rails ingest** (2s10s, HY OAS, NFCI, DGS10) — `regime_detector` reads only DB sentiment counts (`regime_detector.py:62–68`); FRED is free 120 req/min.
- **No CBOE put/call ratio / SKEW market-wide gate** — daily HTML free; no scanner.
- **No sector-ETF cross-asset confirmation** — `cross_reference.py` has zero notion of GICS sector. 11 SPDR sector ETFs free via yfinance; no divergence check.
- **No correlated-pair divergence** (e.g. NVDA vs SMH) — no pair-trade signal at all.
- **No McClellan oscillator / breadth-thrust gate** — NYSE advance/decline data accessible; no scanner.
- **No Reddit upvote / comment-velocity weighting** — `reddit_posts` has `score` and `num_comments` columns populated but `_compute_metrics` (`scanners/reddit_trend.py:49–75`) only counts mentions and unique authors.
- **No Reddit post-velocity (Δposts/Δhour)** — current trending logic is flat counts, not derivatives.
- **No StockTwits message volume / bull-bear ratio** — `social.py:105` returns trending tickers only, no sentiment ratio.
- **No Google Trends "interest by region" delta** — `pytrends.interest_over_time` only; geo-regional dispersion unused.
- **No Discord-channel cross-mention scoring** — multiple analysts firing same ticker within minutes already scored (`additional_analysts`), but no detection of "same analyst pivoted from short→long in 24h" (regime-flip on a single name).
- **No Twitter list / top-N analyst tier weighting** — every `additional_analyst` is worth flat 20 pts (`config/consensus.yaml:36`); no tiering by `source_performance.rolling_accuracy`.
- **No options-flow notional dollar threshold** — `scanners/options.py` filters only by `vol/OI ≥ 3` and `vol ≥ 100`; no dollar-volume floor.
- **No sentiment-horizon-aware xref cache** — `xref_cache` is a single 5-min window; sentiment/social signals empirically peak at 3–10 days (arXiv 2507.09739).
- **No SearXNG body-text NLP** — `news.py:265` joins `title + content` only for SearXNG tier, but tiers 1–3 (Finnhub/Google RSS/Brave) regex over headline only; substantial content is dropped.
- **No company-name fuzzy match** in catalyst classifier — `_headline_relevant` checks exact ticker or company string (`news.py:80–87`); no aliases (e.g. "Alphabet" for GOOGL).
- **No news-source contradiction signal** — engine sums catalyst points; no detection of "Reuters bullish, Bloomberg bearish" within 1 hr.
- **No price-action divergence vs catalyst direction** — alert fires on bullish news even if intraday tape is selling; `market_ok` gate is single-bar, no divergence over 5/15/30 min.
- **No 13F institutional-flow tracker** — quarterly but free; no scanner.
- **No insider-cluster + price-confirmation combined signal** (free win once Form-4 velocity exists).
- **No CFTC COT positioning data** — weekly free.
- **No earnings whisper-number / consensus-revision feed** — Finnhub `epsEstimate` available in `scan_upcoming_earnings` but no Δ tracking.
- **No biotech catalyst calendar** (FDA AdCom, PDUFA dates) — `_CATALYST_PATTERNS` regex matches "fda approv" in headlines after the fact; no forward calendar.
- **No SEC Schedule 13D/G "activist filed" alerter** — `_RELEVANT_FORMS` includes them (`sec_edgar.py:24`) but no proactive watch.
- **No after-hours / pre-market quote awareness** — `_fetch_price` returns Finnhub `c` (current) only; ETH/PMK gaps invisible.
- **No backtest harness against `alert_history`** — DB has 575 alerts with 1h/24h outcomes; no walk-forward CV consumer.
- **No Reddit "due diligence" post detection** (long-form WSB DD posts have higher hit-rate than meme posts) — current trend logic treats all `[DD]` and `[YOLO]` as flat mentions.

---

## 5. Constraints already in code

Hard ceilings, blocking calls, declared knobs (`file:line` for each).

- **Finnhub free tier — `/quote` + `/company-news` + `/calendar/earnings` only**, assumed via choice of endpoint at `consensus_engine/main.py:537`, `scanners/news.py:125`, `scanners/earnings_calendar.py:35`, `scanners/technical.py:34`, `scanners/volume_scanner.py:103`.
- **Daily Finnhub call budget = 3000** at `config/consensus.yaml:281`; consumed in `engine.py:308` (2 calls/Phase-2 alert).
- **Brave Search daily budget = 200** (`config/consensus.yaml:282` + `news_cascade.brave_daily_budget: 50` `:82`).
- **Exa = 100/day, SerpApi = 25/day, Firecrawl = 10 credits/day** at `config/consensus.yaml:283–285`. Atomic decrement via `engine.BudgetManager.consume` (`engine.py:73–94`).
- **Gemini daily budget = 2 M input / 500 K output / 100 video calls** at `config/consensus.yaml:286–288`. Auto-escalates resolution (`youtube.gemini.media_resolution: auto`, `config/consensus.yaml:260–269`).
- **Gemini per-key floor = 6 s between calls** (`config/consensus.yaml:242` `youtube.rate_limit.gemini_min_interval_sec: 6.0`).
- **yfinance is blocking** — runs inside `concurrent.futures.ThreadPoolExecutor` at `main.py:809–832` (price outcome loop, 4 workers); also inside `scanners/options.py:97–112` and `scanners/volume_scanner.py:65–82` via `loop.run_in_executor`.
- **Playwright stealth browser is blocking-context** — opened once per YouTube scan cycle at `scanners/youtube.py:813–818`; reused across `process_video` tasks via async semaphore `:813`.
- **SearXNG runs on `localhost:8888`** (`scanners/searxng.py:31`; `config/consensus.yaml:26`); 10 s timeout.
- **xref cache window = 5 min** (per `utils/xref_cache.py` — implied by `cross_reference.py:225,320`).
- **Phase-2 cross-reference timeout = 120 s** (`config/consensus.yaml:88`); enforced at `main.py:672–676`.
- **Per-source xref timeouts** (cross_reference.py): news 15 s, sec 10 s, social 5 s, technical 20 s, analysts 5 s, options 15 s, youtube 8 s, llm 15 s — `cross_reference.py:233–252`.
- **Per-source semaphores** (cross_reference.py): news=3, social=5, technical=3, llm=2 — `cross_reference.py:26–29`.
- **Default cooldown = 6 h ticker-level** (`config/consensus.yaml:187`); **per-analyst floor = 30 min** (`:195`); **HIGH-conviction bypass enabled** (`:196`); enforced `db.py:714–781`.
- **`min_base_score_for_alert: 20`** (`config/consensus.yaml:190`) gates `_passes_quality_gate` at `main.py:525`.
- **`high_conviction_threshold: 30`** (`config/consensus.yaml:298`) — used by Q9/M6 bypass at `engine.py:301–305` and cooldown bypass at `db.py:761–765`.
- **`require_market_confirmation_for_low_conviction: true`** (`config/consensus.yaml:297`) — `engine.py:321` early-exit unless HIGH conv or SEC catalyst (`:305`).
- **`require_mainstream_for_strong: true`** (`config/consensus.yaml:296`) — `engine.py:247` downgrades STRONG to WATCHLIST without mainstream domain.
- **YouTube poll = 600 s** (`config/consensus.yaml:226`); max 3 videos/channel (`:227`); concurrency = 4 (`:230`).
- **YouTube classifier confidence floor = 0.5** (`config/consensus.yaml:271`); standalone alert floor `min_trust = 0.5` (`:233`).
- **Fetch loop interval = 300 s** (`main.py:337`).
- **Price outcome loop interval = 300 s** (`main.py:828`); 4-worker `ThreadPoolExecutor`.
- **Source health poll = 60 s** (`config/consensus.yaml:172`); `DEGRADED_MODE` triggers when ≥2 critical sources (`finnhub`, `yfinance`) unhealthy (`config/consensus.yaml:175–177`).
- **`max_error_rate = 0.3`** for any single source (`config/consensus.yaml:174`); `degraded_freshness_multiplier = 5` (`:173`).
- **Source max ages**: finnhub 60 s, yfinance 300 s, apewisdom 600 s, reddit 600 s, discord_tweetshift 120 s (`config/consensus.yaml:178–183`).
- **LLM model = `minimax/minimax-m2.5`** (`config/consensus.yaml:152`); free-tier text/vision variants at `:153–154`. `min_confidence: 70` (`:155`); `max_tokens: 1024` (`:156`).
- **`signal_ttl_hours: 2`** (`config/consensus.yaml:308`) — `ticker_signals` rows expire and pruned via `db.prune_expired` (`db.py:808–817`).
- **`alert_history_days: 90`** (`config/consensus.yaml:309`).
- **Ticker market-cap floor = $100 M** (`config/consensus.yaml:167`); cache 7 days (`:168`).
- **Volume scanner watchlist defined but unwired** — `cfg.volume_scanner.watchlist` (`scanners/volume_scanner.py:92`) is empty in YAML; `volume_scanner.enabled: true` (`config/consensus.yaml:160`) is unread by any loop.
- **Reddit trend interval declared but unread** — `intervals.reddit_trend: 14400` (`config/consensus.yaml:87`) has no consumer (only manual `!trend` command).
- **Pytrends auto-disable = 3 failures / 24h** — `scanners/social.py:300–329`; mutates `cfg._config["social"]["pytrends_enabled"]` in place.
- **Atlas lease TTL = 1800 s** (`config/consensus.yaml:322`); cache_days = 7 (`:319`); max sweep = 10 tickers (`:320`); sweep at 08:00 ET (`:321`).
- **Alfred post window = 08:50–09:00 ET** (`config/consensus.yaml:331`); ET = `America/New_York`.
- **Weekend pause window = Fri 3pm ET → Sun 2pm ET** hard-coded in `main.py:89–122`.
- **Discord bot intents = GUILDS|GUILD_MESSAGES|MESSAGE_CONTENT** (`scanners/discord_tweetshift.py:30`); requires privileged `MESSAGE_CONTENT` intent.
- **Discord WS reconnect backoff = 5 s → 120 s exponential** (`scanners/discord_tweetshift.py:351,369`).
- **`/tmp/consensus_engine.lock` flock prevents concurrent `--live`** (`main.py:861–867`).
- **API keys all in `/root/.openclaw/.env`** (per CLAUDE.md), referenced via `$VAR_NAME` in `config/consensus.yaml:8–22`.
- **Source channels list at `/root/.openclaw/sources.json`** (per CLAUDE.md and `db.get_approved_youtube_channels`).

---

## 6. CLI / process surface

| Mode | Command | Entry | Loop set assembled |
|------|---------|-------|--------------------|
| One-cycle scan | `python3 -m consensus_engine --once` | `main.py:871` → `run_once` `:264–269` | `fetch_signals` only |
| Live | `python3 -m consensus_engine --live` | `main.py:859–869` (also acquires `/tmp/consensus_engine.lock` flock) → `run_live` `:272–366` | `tweetshift` + `fetch_loop` + `price_outcome_loop` + `youtube_poll_loop` + `source_health_updater_loop` + `macro_digest_loop` + (sec watchers if enabled) + `atlas_worker_loop` + `atlas_sweep_loop` + `alfred_loop` |
| Dry run | `--dry-run --once` | `main.py:852` sets `cfg.dry_run = True` | Discord posts logged only (`alerts/discord.py:325`, `:373`, `:402`, `:446`, `:473`) |
| Status | `--status` | `main.py:854–857` | Prints help text; no health probe |

The `--live` lock at `main.py:861–867` prevents two engines posting to Discord simultaneously. `--once` does not acquire the lock.

`__main__.py` re-exports `main` from `main.py` (`/root/.openclaw/workspace/consensus_engine/__main__.py`), so `python3 -m consensus_engine` and `python3 -m consensus_engine.main` are equivalent.

## 7. DB-schema landmarks (read by multiple capabilities)

For Phase-1 researchers proposing additive scanners: these tables are the durable inputs/outputs.

| Table | Writer | Reader | Purpose |
|-------|--------|--------|---------|
| `ticker_signals` | `db.insert_signal` `:578–619` | `cross_reference._run_social_check` (via `db.get_signal_counts_by_source`), `regime_detector.detect_regime` `:62–68` | Raw cross-reference pool; `signal_ttl_hours: 2` (`config/consensus.yaml:308`) → pruned by `db.prune_expired` |
| `signal_events` | `db.insert_signal` for `TWITTER` (`db.py:602–618`); + an analogous YouTube write at `db.py:1824` | `cross_reference.py:328–332` (`get_signal_events_for_ticker`, 3600 s window) | Canonical scoring-time source events, post-Q2b |
| `alert_history` | `db.insert_alert` `:784–805` (also enqueues atlas `:799–804`) | `db.check_alert_cooldown` `:738–743`, `briefing/alfred.py:25–33`, `db.get_top_tickers_session` | Durable alert log + outcome backfill (`price_1h_later`, `price_24h_later`) |
| `alert_messages` | `db.insert_alert_message` `:876` + `db.update_alert_message_followup` `:897` | analyst-precision queries, audit metrics | Phase-1↔Phase-2 message pairing; `followup_msg_id IS NULL` is the orphan signal |
| `decision_snapshots` | `db.record_decision_snapshot` (called from `main.py:722`) + shadow-prob merge `calibration.py:171–175` | `calibration.retrain` `:91–99`, `!score` debug | Calibration training set + shadow predictions |
| `source_performance` | written by analyst-precision backfill (not in this map) | `db.check_alert_cooldown` `:768`, `db.get_analyst_precision` `:700` | Per-analyst rolling 1h/24h hit rate |
| `source_health` | `db.upsert_source_health` (called from `main.py:764`) | `!status` and audit | Per-source freshness + error rate |
| `youtube_videos` / `youtube_signals` / `youtube_levels` / `youtube_setups` / `youtube_catalysts` / `youtube_macro` | `scanners/youtube.py:255–356` | xref `_get_youtube_context` `:159–214`, level alerter `main.py:425`, alfred `:36–58` | Two-stage evidence persistence |
| `research_jobs` / `research_sections` | `db.enqueue_atlas_job` `:1954`, `db.upsert_research_section` (called from `atlas.py:39–44`) | `atlas.atlas_worker_loop`, `vault.write_ticker_vault` | Atlas leased-queue + per-ticker vault snapshots |
| `briefing_runs` | `db.upsert_briefing_run` (called from `alfred.py:255–280`) | `alfred.post_briefing` outbox state machine | Idempotent briefing dispatch |
| `api_usage_daily` | `engine.BudgetManager._ensure_row` `:62–71` + `consume` `:73–94` | `engine.BudgetManager.can_consume` `:96`, `pct_used` `:114` | Daily atomic budget caps |
| `pipeline_metrics` | `db.record_metric` `:827`; xref records latency keys `xref_news_cascade_ms` etc. (`cross_reference.py:323–324`) | none in active code (audit/inspection only) | Per-component latency telemetry |
| `reddit_posts` | `db.insert_reddit_posts` (called from `scanners/reddit_trend.py:119`) | `db.get_reddit_posts_since` (called from `reddit_trend.py:124`) | Trend-scan corpus; `score`/`num_comments` columns ingested but unused for scoring |

## 8. External-API surface (free or already-paid)

For dedup against Phase-2 candidate features.

- **Finnhub** (key required, free tier): `/quote` (`main.py:537`, `engine.FinnhubAdapter`), `/company-news` (`news.py:125`), `/calendar/earnings` (`earnings_calendar.py:35`).
- **Yahoo Finance** (no key): `/v8/finance/chart/{ticker}` (`technical.py:54`), and `yfinance` Python lib for option chains and history (blocking → ThreadPoolExecutor).
- **SEC EDGAR** (User-Agent only): `data.sec.gov/submissions/CIK{cik}.json` (`sec_edgar.py:81`), `www.sec.gov/files/company_tickers.json` (`sec_edgar.py:39`), 8-K ATOM feed `/cgi-bin/browse-edgar?action=getcurrent&type=8-K` (`sec_watcher.py:23–26`), Form-4 archives `Archives/edgar/data/{cik}/{accession}/{file}` (`sec_edgar.py:186–189`).
- **Reddit** (OAuth or RSS fallback): `utils/reddit.fetch_subreddit_posts` (called from `scanners/social.py:52` and `scanners/reddit_trend.py:104`).
- **ApeWisdom** (no key): direct REST (`scanners/social.py:177`).
- **Google Trends** (no key, soft rate-limit): `pytrends.TrendReq` (`scanners/social.py:303`).
- **YouTube** (no key, RSS): `youtube.com/feeds/videos.xml` (`youtube.py:44`); transcript caption tracks via stealth Playwright (`youtube.py:84–164`).
- **Gemini** (key required, free tier): video calls via `gemini_video_parser`; budgets at `config/consensus.yaml:286–288`.
- **OpenRouter** (key required): `openrouter.ai/api/v1/chat/completions` for `llm_scorer` (`llm_scorer.py:125`), `briefing/alfred._llm_synthesize` (`alfred.py:95`), `research/sources._summarize_with_llm` (`sources.py:36`).
- **Brave / Exa / SerpApi / Firecrawl** (keys required): adapters in `consensus_engine/api_adapters.py`; budgets atomic in `engine.BudgetManager`.
- **Discord REST** (bot token): `/api/v10/channels/{id}/messages` POST/PATCH from `alerts/discord.py:344` `:386` `:435` `:457` `:486`, `briefing/alfred.py:198`, `main.py:394`, `scanners/youtube.py:183`.
- **Discord Gateway WS** (bot token): `wss://gateway.discord.gg/?v=10&encoding=json` (`scanners/discord_tweetshift.py:26`).
- **SearXNG** (self-hosted, no key): `localhost:8888/search?format=json` (`scanners/searxng.py:31,42`).

No paid APIs assumed. Phase-1 candidates should default-route through this surface or accept "no implementation possible without new key/budget".

## 9. Routing of well-known concepts to existing modules

When a Phase-1 candidate names a concept, this is where it currently lands:

| Concept | Existing module | Status |
|---------|-----------------|--------|
| "options flow" | `scanners/options.py` | binary unusual flag only |
| "insider trading" | `scanners/sec_edgar.fetch_form4_details` + `_RELEVANT_FORMS` includes `4` | manual command only |
| "earnings catalyst" | `scanners/earnings_calendar.py` + `analysis/catalyst_resolver.py:142` | YT-pipeline use only |
| "news catalyst" | `scanners/news.py` + `_classify_catalyst` | YES, in xref |
| "social momentum" | `scanners/social.py` + `scanners/reddit_trend.py` | partial (apewisdom on, others gated) |
| "regime / breadth" | `analysis/regime_detector.py` | NOT WIRED |
| "reliability / source quality" | `db.source_performance` + `db.check_alert_cooldown` precision scaling | YES |
| "calibration" | `analysis/calibration.py` | shadow-mode YES, model NO |
| "technical breakout" | `analysis/technical.py` filters + `engine._score_finnhub` | YES |
| "morning brief" | `briefing/alfred.py` | YES |
| "research note" | `research/atlas.py` + `research/vault.py` | YES |
| "level alerts" | `main.py:_check_youtube_level_alerts` | YES (YT-only source) |
| "macro thesis" | `youtube_macro` table + `macro_digest_loop` | YES |
| "cross-asset / sector confirmation" | none | MISSING |
| "short interest" | none | MISSING |
| "dark pool" | none | MISSING |
| "options term structure / IV rank" | none | MISSING |
| "FRED macro" | none | MISSING |
| "CBOE skew / put-call" | none | MISSING |
| "13F institutional" | none | MISSING |
| "Form-4 cluster velocity" | partial (raw fetch only) | MISSING aggregation |
| "backtest" | none in `consensus_engine/`; `backtest.py` at repo root is unused stub | MISSING |
