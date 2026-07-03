# Pass 0 — Real-System Failure Map (reliability-hardening)

**Date:** 2026-06-28 PDT · **Method:** live `journalctl` (consensus-engine + gateway, 48–72h) + actual source reads (orchestrator + 4 researchers). Every claim below is verified against current code/logs at commit `f044485`.

> **HEADLINE:** The bot is **substantially more resilient than the brief's symptom list assumes.** Much of what the brief lists as "missing" already exists (persistent budget tracking, exponential backoff, parallel news race, full yfinance off-loading, a retry classifier, a feature-flag system). Several listed symptoms are **refuted outright** or are **intentional design**. The genuine reliability work is a **focused set of ~12 gaps**, and several of those are about **unifying / persisting existing infrastructure** rather than building anything new. This is exactly why the brief said "verify, don't trust the list."

---

## A. What the LIVE LOGS actually show (production failure map)

| Frequency (48–72h) | Signature | Source | Reality |
|---|---|---|---|
| 199× | `Google Trends (Exa fallback): 0/10 tickers with data` | social.py | **Exa-as-Google-Trends fallback is effectively DEAD** — returns nothing every cycle |
| ~250× combined | `Source 'exa' blocked … (backoff)` / `backing off … after 3..39 failures` | rate_limiter | Exa fails *every* call → failure count climbs forever → stuck at the 600 s cap permanently |
| 13–18× | `Brave monthly quota exhausted (HTTP 402) — circuit open until restart` | news.py | Brave 402 monthly-quota circuit trips; in-memory, "until restart" |
| 7× | `peer_comparison: timed out for IWM` (also NET, WMT, AMAT, LRCX, GS, COST) | peer_comparison | yfinance throttle blows the fixed 12 s ceiling → relative-strength field silently dropped |
| 7× | `_safe_send 429 — sleeping 0.3s (attempt=1/3)` | alerts.discord | Discord rate-limit; 3-attempt retry already handles it |
| 6× | `LLM … connection error (retryable): TimeoutError` + `LLM fallback hit qwen/...` | llm_client | Chain-walking failover working as designed |
| 4× each | `serpapi: key 'serpapi/2/3' out of searches (HTTP 429)` → `all keys exhausted` | gap_fill (!all) | 3-key SerpAPI rotation, all exhausted; in-memory (resets on restart) |
| 5× | `Discord Gateway op:9 INVALID_SESSION (reconnect)` | tweetshift | Recovers cleanly (known, benign) |
| 10× | `Unknown key name 'OOMScoreAdj' … ignoring` | systemd (gateway + engine) | OOM protection silently not applied |

**No hard crashes, no service flapping, no GATEWAY drift** in the window. Both services `active`. The noise is **WARNINGS from degrading external sources**, not internal faults. The single loudest real problem is **Exa stuck dead** (≈450 log lines), then **Brave 402**.

---

## B. Component inventory (resilience-relevant subsystems)

- **News cascade** (`scanners/news.py`): production runs **parallel** (`news_cascade.parallel: true`, consensus.yaml:107) via `asyncio.as_completed`, **cancels losers on first hit** (serial variant `_news_cascade_serial` is the code default but YAML overrides). Tiers (5): `recent_earnings, finnhub, google_rss, brave, searxng`. **Exa / SerpAPI / Firecrawl adapters exist in `api_adapters.py` but are NOT wired into the news cascade** (brief's 7-tier order is wrong); they're used by the precision engine and `!all` gap-fill instead.
- **Provider adapters** (`api_adapters.py`): Finnhub quote/news adapters; all I/O is `aiohttp` with `_TIMEOUT`; 7 `except Exception` handlers, all `log.debug(...); return None` (log-and-drop → caller tries next).
- **LLM client** (`llm_client.py`): OpenRouter free-model **chain-walking** (any error → next model, by design, line 6), one 0.5 s retry only when the rate-limiter reports the source blocked (line 132), Groq **head-start circuit breaker** (lines 34–61, 120 s cooldown, in-memory) for `!all` synthesis latency.
- **Rate limiter** (`utils/rate_limiter.py`): global singleton, 16 sources, per-source min-interval + exponential backoff `min(30·2^(n-3), 600)` after ≥3 failures; `report_success` resets the count. **No jitter. All state in-memory.**
- **Retry classifier** (`utils/burst_retry.py`): pure functions `classify_retry` / `parse_retry_after` / `next_backoff` / `is_per_day_quota` (QUOTA_BLOCKED/TRANSIENT/PERMANENT). Used **only** by youtube.py, wolf_vision.py, gemini_video_parser.py.
- **Daily budget** (`engine.py:53 DailyBudgetTracker` → SQLite `api_usage_daily`): `consume()`/`can_consume()` **gate** sources against `precision_engine.budget.{col}` (default 9999 = effectively off); tracks `skipped_sources`; UTC-keyed; **persists**.
- **Caches**: `XRefCache` L1 in-mem + L2 SQLite (300 s); `!all` cache 900 s version-keyed (persists); VIX 15-min TTL; ticker-alias `lru_cache`.
- **Async hot paths**: `main.py` extended-price, `options.py`, `snapshot.py`, `peer_comparison.py`, `cross_asset.py`, `earnings_calendar.py`, `expected_move.py`, `earnings_move.py` — **all yfinance/blocking calls already off-loaded** to thread executors.
- **Scanners**: `sec_edgar.py` (aiohttp + rate_limiter throttle, fail-closed). `youtube.py` — live path is **Supadata API + Gemini** (the "Playwright-stealth" module docstring is **stale dead code**; VPS IP is blacklisted); a **paced serial drain (~1 video/min, `youtube.pace_seconds=60`)** with single-flight Gemini chain — serial **by design** (Gemini ≤10 RPM), with graceful per-video quota re-queue (`quota_blocked`, no attempt bump). No breaker → a *sustained* Supadata+Gemini outage re-queues forever behind a once-per-3-days advisory log. `stocktwits_sentiment.py` (`!all` reader): requests-in-executor, 4 s/endpoint, 90 s negative cache, single-flight — fine.
- **Feature flags** (`utils/feature_flags.py`): `read_feature_state` reads `features.{name}.enabled` from YAML; flip writes a SQLite audit row but **requires a YAML edit + restart** to take effect.
- **Validation data**: `decision_snapshots` + `shadow_predictions` SQLite tables present (db.py:269/287) — the stored-data backtest substrate.

---

## C. CONFIRMED REAL GAPS (verified, file:line) — the Pass 2–4 candidate pool

| ID | Gap | Evidence | Severity (live-alert) |
|---|---|---|---|
| **G1** | rate_limiter backoff has **no jitter** → synchronized retry storms when sources back off together | rate_limiter.py:78 | med |
| **G2** | **All breaker/limiter state is in-memory** → restart re-probes dead sources from scratch, resets every breaker | rate_limiter.py; news.py:363; llm_client.py:39; gemini_video_parser.py:95; gap_fill.py | med |
| **G3** | **Exa (Google-Trends fallback) perpetually dead** → `0/10` every cycle, ≈450 log lines, wasted cycle time; nothing says "source dead → stop probing this cycle + surface it" | social.py:365–408 + rate_limiter | **high** (noise + wasted time; a dead signal source) |
| **G4** | **Brave 402 circuit in-memory "until restart"**, no monthly-reset date → restart re-hits 402, burns a call | news.py:363, 397–400 | med |
| **G5** | **Budget tracking fragmented + TZ-inconsistent**: DailyBudgetTracker (SQLite/UTC/gating), Brave JSON (UTC), SerpAPI dict (in-mem/**local-TZ**) | engine.py:53; news.py:321; gap_fill.py:57 | med |
| **G6** | **social.py `_has_market_cap` fails OPEN** → under yfinance throttle the market-cap quality gate silently becomes a no-op (junk tickers pass) | social.py:32–38, gates at 279/479/568 | **high** (signal quality) |
| **G7** | **Max-pain math O(strikes²) on the event loop** → biggest on-loop CPU stall in `!all` for SPY/QQQ/IWM-class chains | options.py:594/616 | med-high |
| **G8** | **Options-flow watcher sequential N+1** → serial per-ticker awaits delay the unusual-flow **instant-trigger** alert | options.py:362–364 | med-high |
| **G9** | **Chain `.iterrows()` parse on the loop** → CPU on loop for wide ETF chains | options.py:180/366; expected_move select_atm | low-med |
| **G10** | **peer_comparison 12 s-timeout fragility** → uncached ETF `.info` front-loads, blows ceiling under throttle, silently nulls relative-strength | peer_comparison.py:119–121, 199 | med |
| **G11** | **http.py shared session has no default timeout** → a caller that forgets `ClientTimeout` can hang | utils/http.py | med |
| **G12** | **OOMScoreAdj typo on both systemd units** (correct: `OOMScoreAdjust`); engine lacks `MemoryMax`; neither has `WatchdogSec` | /etc/systemd/system/*.service:27 | low-op |
| **G13** | **`burst_retry` (jittered backoff + Retry-After parsing) unused by news cascade / main LLM client** → opportunity to *apply existing helper*, not build new | burst_retry.py importers | (enabler) |
| **G14** | **api_adapters handlers log at `debug` AND never call `rate_limiter.report_failure`** → direct adapter callers (precision engine via `ExaAdapter`/`SerpApiAdapter`/`FirecrawlAdapter`) get **zero backoff**; a flapping/exhausted key is hammered every call, and a systematically-failing adapter is invisible at INFO | api_adapters.py:70/92/145/201/244/291/318 | med |
| **G15** | stocktwits: the 20 s Cloudflare wait is in `social.py:130` (`scan_stocktwits`, Playwright async — yields, doesn't block thread); it DOES have a soft breaker via `rate_limiter` (3 fails → backoff). `stocktwits_sentiment.py` (`!all` reader) is fine (4 s/endpoint, executor, 90 s negative cache). **Mostly a non-gap** — kept only as a note | social.py:129-134 | low/none |
| **G16** | **options.py:227 `_ts_to_epoch` returns `0.0` on parse error → staleness guard treats `lt=0.0` as falsy → SKIPPED → a stale/unparseable contract can fire an INSTANT unusual-flow alert** (staleness filter is load-bearing on a no-second-source instant-trigger path) | options.py:227 + 268 | **med-high** |
| **G17** | **options flow scan `except Exception: pass` (no log) → a systemic yfinance break returns empty silently, looking identical to "no unusual flow today"** → masks an outage of a primary instant-trigger source (also a Pass-3 "fix-masks-outage" item) | options.py:164/307/555 | med |
| **G18** | **LLM 0.5 s soft-retry vs ≥30 s rate-limiter backoff mismatch** → when the shared `openrouter` bucket is backed off (≥30 s), the 0.5 s sleep clears nothing, the 2nd `acquire()` also fails, every chain model (all `openrouter`) is silently skipped → **LLM synthesis returns `""` = BLANK THESIS on a live alert.** Most direct path to a degraded live alert | llm_client.py:131-136 | **high** |
| **G19** | **Groq circuit breaker only guards the `head_start`/`!all` strategy** → the default `serial` synthesis path has no breaker; a stalled/rate-limited Groq costs up to the full 30 s timeout every poll cycle with no adaptive skip | llm_client.py:268, 328-333 | med |

---

## D. REFUTED / REFINED brief claims — DO NOT build fixes for non-problems

| Brief claim | Verdict | Evidence |
|---|---|---|
| "Blocking sync yfinance in the event loop, many hot paths" | **REFUTED** — all off-loaded; real issue is CPU *math* on loop (G7/G9) | run_in_executor at main.py:168/1769, options.py:173/316, snapshot.py:126/180, peer_comparison.py:121/172, cross_asset.py:270/312, earnings_*:90/93, expected_move:319 |
| "Duplicate `intervals:` block silently dropped" | **REFUTED** — one `intervals:` only | consensus.yaml:114; no dup top-level keys |
| "db.py rollback swallowed" | **REFUTED** — rolls back **and re-raises** | db.py:3921–3923 |
| "StockTwits waits 20 s, no breaker" | **REFUTED (timeout)** — 4 s/endpoint, off-loaded, 2-worker pool (no-breaker part true but low impact → G15) | stocktwits_sentiment.py:30/36/87 |
| "YouTube serial ~20–30 s/video [bug]" | **REFINED** — serial **by design** (inner chain `Semaphore(1)`, Gemini ≤10 RPM); concurrency "buys nothing" | youtube.py:1228/1233 |
| "openclaw.json drifted from consensus.yaml" | **REFUTED (currently)** — they MATCH (fragility, not an active bug) | consensus.yaml:331–335 ↔ openclaw.json agents.defaults.model |
| "~27 fixed sleeps, no backoff anywhere" | **REFUTED** — 13 sleeps; main.py:753 already `sleep(2**attempt)`; rest are politeness pauses | repo grep |
| "No daily-budget tracking that survives restart" | **REFUTED** — DailyBudgetTracker (SQLite) + Brave JSON both persist | engine.py:53; news.py:321 |
| "Circuit breakers exist ONLY for Groq" | **PARTIAL** — Brave-402 + Gemini-per-key bench also exist (none persist → G2) | news.py:363; gemini_video_parser.py:95 |

---

## E. WHAT ALREADY EXISTS — DO NOT REBUILD (redundancy guard)

1. Per-source rate limiting + exponential backoff — `utils/rate_limiter.py` (16 sources).
2. Retry classification + Retry-After parsing + jittered/capped backoff helper — `utils/burst_retry.py` (pure functions; reusable but under-used).
3. Circuit breakers — Groq (`llm_client.py:39`), Brave-402 (`news.py:363`), Gemini per-key bench (`gemini_video_parser.py:95`).
4. Two-level xref cache (L1 mem + L2 SQLite) + version-keyed `!all` cache — `utils/xref_cache.py`, `alerts/all_command/cache.py`.
5. Persistent daily budget gate (SQLite, UTC) — `DailyBudgetTracker` / `api_usage_daily` (`engine.py:53`, `db.py:199`).
6. File-persisted Brave daily counter (UTC) — `news.py:321`.
7. SerpAPI 3-key rotation — `gap_fill.py:57` (in-memory).
8. Shared aiohttp session (`TCPConnector(limit=30)`) — `utils/http.py` (no default timeout).
9. Full yfinance off-loading to thread executors — all 8 hot-path files.
10. Parallel-race news cascade with loser cancellation — `news.py:478`.
11. Feature-flag system (YAML-read + SQLite audit) — `utils/feature_flags.py`.
12. Stored-data validation substrate — `decision_snapshots`, `shadow_predictions`.

---

## F. Process / degradation notes

- **r3 (error-swallowing/scanners)** never delivered its formatted report through the (flaky) agent-messaging channel; r1 likewise sent only idle-notifications. **Their entire scope was independently re-covered by orchestrator greps + reads** (social.py fail-open, db.py rollback, options/snapshot swallows, youtube semaphore, stocktwits timeout, api_adapters handlers) — evidence above is first-hand, not second-hand. Recorded as a layout degradation, not a coverage gap.
- North-star tension flagged for Pass 3: G6 (fail-open ticker gate) and G3 (dead Exa) both touch the rule **"never drop a real signal"** — naive fail-closed / hard-disable would *lose* signals under transient throttling. Fixes must distinguish *transient* from *persistent* failure.
