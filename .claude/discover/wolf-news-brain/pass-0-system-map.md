# Pass 0 — System Map (wolf-news-brain)

Synthesized from 6 parallel source-reading explorers. Every claim below is anchored to `file:line` read from actual source (not inferred from filenames). Items I could NOT verify from source are marked **[INFERRED]**.

Health at map time: `consensus-engine` **active**, `openclaw-gateway` **active**, `/root/.openclaw → /home/openclaw/.openclaw` symlink **intact**.

---

## 1. Component Inventory (only parts relevant to the Wolf feature)

### Ingestion / scanners (`consensus_engine/scanners/`)
- **No base class / interface.** `__init__.py` is a docstring only. Three conventions: **Pattern A** background loop coroutine `async def xxx_loop(stop_event, record_ok=None, record_err=None)` (gmail, youtube); **Pattern B** class with `.run(stop_event)` (TweetShift); **Pattern C** on-demand fetch fn wrapped by a loop in `main.py` (sec, news, reddit).
- **`gmail_watcher.py` (432 lines)** — the thing being rebuilt. `gmail_watcher_loop` at `:373`. Auth `SCOPES` at `:26` is `[gmail.readonly, gmail.labels]` but the **token was minted with `gmail.modify`** (`oauth_connect.py:29`) so labeling works; rebuild should align the declared SCOPES to `gmail.modify`. `_decode_body` `:164-177` returns the first **text/plain** part only — no HTML, no images. Wolf emails are HTML-only → returns `""` → early-exit `:277-279` marks processed, never retried. Output seam: `db.insert_signal(TickerSignal(...))` `:327-333` with `source_type=SourceType.DESKTOP_AUTH`, `sentiment=NEUTRAL`. Dedup: `seen_gmail_messages` (by Gmail message_id) + `seen_gmail_bodies` (SHA-1 of body, 24h window). `OpenClawProcessed` label applied via `messages().modify()`.
- **`utils/tickers.py` `extract_tickers`** — regex `:83`; **blacklist `:6-65` suppresses exactly the macro symbols Wolf uses**: SPY, QQQ, VOO, DOW, FED, CPI, GDP, PMI, ISM, ETF, SEC, IMF, NASDAQ. Rebuild must bypass this for macro and add an LLM extraction path; keep the regex only as a supplementary stock-symbol scan.

### LLM + vision (`consensus_engine/llm_client.py`, `analysis/`, `models/`)
- **`call_with_fallback(role, messages, *, max_tokens=1024, temperature=0.3, timeout=30, chain=None)`** `:61-155` — the one public text-LLM entry. Returns `""` on chain exhaustion (canonical "unavailable"). **No `response_format=json` flag** — JSON is forced by prompt ("Return ONLY raw JSON, first char `{`") + fence-strip + regex `\{.*\}` fallback (pattern in `captions_llm_parser.py:84-118`). Provider routing `:46-58`: `groq/`→Groq else OpenRouter. Chains from `config/consensus.yaml:224-261` (roles: `primary`, `text`, plus an explicit `all_command_chain`).
- **Vision is NOT wired for arbitrary images.** The only native Gemini SDK call (`analysis/gemini_video_parser.py:753-767`) sends a **YouTube video URL** (`mime_type="video/*"`) — server-side sampling, no `inline_data`/image bytes path. `models/vision_model.py:analyze_image(image_url)` `:77-88` DOES send an image via OpenRouter (OpenAI `image_url` content block, model `google/gemma-4-31b-it:free`) but **has zero callers** — it is unwired. So: to read chart images we either (a) wire up `analyze_image` (OpenRouter, easy) or (b) add a native Gemini image path modeled on the video parser using `types.Part.from_uri(file_uri=url, mime_type="image/jpeg")` / `from_bytes(...)`.
- **Gemini quota machinery to reuse** (`gemini_video_parser.py`): keys `GEMINI_API_KEY[/2/3]` `:94` (only 1+2 populated); `_key_exhausted_until` per-key, reset at **Pacific midnight** `:135-137`; round-robin `_get_available_gemini_client()` `:147-169`; `_is_quota_error` `:172-180`; 503 retry `_503_backoffs=[0,6]`; `rate_limiter.acquire("gemini")` paces ≥6s (`utils/rate_limiter.py:30`); `BudgetManager.can_consume_gemini()` daily caps (`consensus.yaml:515-518`: 2M in / 500k out / 100 video calls).
- **Keys load from `.env.service`** for the systemd service (NOT `workspace/.env`); dev sessions read `~/.openclaw/.env`. Gemini keys read directly from `os.environ`, not via `cfg.get_api_key`.

### Storage (`consensus_engine/db.py`, `consensus.db`)
- **SQLite, single global `AsyncConnection`** (asyncio.Lock-serialized, WAL, `busy_timeout=5000`, `check_same_thread=False`). Access via `await db.get_db()` then `await conn.execute(...)` + `await conn.commit()`. Path `database.path` = `…/workspace/consensus.db`.
- **Schema in code, idempotent.** `SCHEMA` string `:75-630` (all `CREATE TABLE IF NOT EXISTS`); `_run_column_migrations` `:646-706` (`ALTER TABLE … ADD COLUMN`, PRAGMA-guarded); `POST_MIGRATION_INDICES` `:634-643`; `schema_version` audit log `:759-775` (current high = **14**). **Recipe to add tables**: append `CREATE TABLE IF NOT EXISTS` to SCHEMA, (optionally) add column tuples to migrations list, append `(15, "desc")` to `_schema_versions`.
- **Existing gmail tables** `seen_gmail_messages` `:609-615`, `seen_gmail_bodies` `:616-620` — reuse verbatim.
- **No existing "thesis call with lifecycle" table.** Closest: `alert_history` `:90-106` (ticker+catalyst+confidence + 1h/24h price outcome backfill, but **no direction/stage/levels/invalidation**); `signal_events` `:247-261` (has `direction` but is an event log); `youtube_signals` `:212-228` (direction+conviction+macro_thesis, no lifecycle). **Verdict: build new tables** for thesis-state, market-read, tracked-calls+outcomes.

### Confluence sources — directional stance availability (THE key feasibility question)
| Source | Module | Direction today | Scope | Level | Timestamp | Verdict |
|---|---|---|---|---|---|---|
| **YouTube** | `db.py:youtube_signals` + `youtube_levels`; `analysis/video_classifier.py`; aggregated as `YouTubeContext` in `cross_reference.py:200-276` | `long/short/neutral` **stored** | ticker + macro | `youtube_levels.price` | `extracted_at` | **DERIVABLE — already structured, just query** |
| **Twitter/TweetShift** | `analysis/tweet_parser.py` → `ParsedTweet.direction` + `final_signal` `:225-233` | `long/short/neutral` (in-memory; this is the pipeline trigger) | ticker + macro (type B) | `OptionsDetail.strike` | `parsed_at` | **FULLY DERIVABLE — richest stance in system** |
| **Options flow** | `scanners/options.py` → `OptionsResult`/`FlowHit.side` | CALL/PUT (in-memory only) | ticker | `FlowHit.strike` | `last_trade_ts` | **DERIVABLE — but `side` not persisted; re-query or add column** |
| **SEC Form 4** | `scanners/sec_edgar.py:fetch_form4_details` + `insider_buy_or_sell:171` | Buy/Sell (functions exist) | ticker | `transaction.price` | `transaction.date` | **DERIVABLE — funcs exist but xref layer drops direction** |
- **Existing multi-source machinery** (reuse skeleton, NOT direction-aware yet): A3 `analysis/consolidation.py` counts independent **source clusters** firing for a ticker (`SOURCE_CLUSTERS` news/retail/analyst/video/official) but does **not compare directions**. A1 `analysis/contradiction.py` has a `contradiction_index` field that gates STRONG→WATCHLIST, **but `cross_reference.py` never populates it** (effectively always 0.0). `ScoreBreakdown` is purely additive (no direction agreement). **So the confluence engine is cheap: read 4 stances + Wolf's stance, compare direction at market/sector/stock/asset scope within a ~2-3wk window, populate a real agreement/contradiction value.**

### Alerts, scoring, Discord output (`consensus_engine/cross_reference.py`, `alerts/`, `briefing/`)
- **Scoring seam**: `cross_reference.py:score_ticker(ticker, base_score, direction)` `:281` returns `ScoreBreakdown` (`base + analysts + news + sec + technical + llm_boost + options + consensus + youtube`, `.total` authoritative). Catalyst tiers + `alerts.min_base_score_for_alert=20` in YAML.
- **Discord posting = REST (bot token), not webhook.** Primitive `alerts/discord.py:_safe_send` `:53` POSTs to `/channels/{id}/messages`. **`_safe_send_kwargs` `:28` forces `allowed_mentions={"parse":[]}` — suppresses ALL @-mentions by default.** Channel-id-parameterized send fns: `send_command_reply(channel_id,…)` `:602`, `send_command_embed_reply(channel_id,…)` `:640`. Cleanest plain-text model: `briefing/alfred.py:_send_discord_briefing` `:170`. Channel ids in `consensus.yaml api_keys.*` as `$ENV`. **New #news channel** = add `discord_news_channel_id: "$DISCORD_NEWS_CHANNEL_ID"`.
- **@-ping the user does NOT exist yet.** No `DISCORD_OWNER_USER_ID` anywhere. To do it: add the id to env/yaml, and post with `content="<@id> …"` + `allowed_mentions={"users":[id]}` (must bypass the `{"parse":[]}` default).
- **Narrator for digest reuse**: `alerts/all_command/narrator.py` two-phase: `sanitize_hostile_text` `:262` (9 concurrent free-tier calls — only for hostile web snippets) + `synthesize_narrative(...)` `:860` (primary chain, max_tokens=8000). **For DB-sourced digests, copy Alfred's simpler `_llm_synthesize(prompt)` `:89`** (skip the sanitize phase).
- **Briefing/digest analog = Alfred** (`briefing/alfred.py`): `post_briefing` `:225` is a 3-stage transactional outbox (pending→posted→archived to `vault/macro/briefings/`). `build_briefing_data` `:21` pulls overnight `alert_history`, `youtube_levels`/`youtube_signals`, macro regime, top tickers. This is the direct model for the Wolf digests.

### Engine wiring + scheduling (`consensus_engine/main.py`)
- **Task registry** `:649-677`: `combined_stop=asyncio.Event()` `:629` (set on shutdown OR Friday-3pm-ET weekend pause). Existing tasks incl. `gmail_watcher_loop(combined_stop, _record_source_ok, _record_source_error)` `:676`. **Recipe**: append `asyncio.create_task(...)` to the final `tasks.extend([...])` block; pure schedulers omit the record callbacks (like `alfred_loop`).
- **Scheduled-loop templates**: `atlas_sweep_loop` (`research/atlas.py:139`) polls 60s, fires once/day when `(now.hour,now.minute) >= (hh,mm)` ET with a `YYYY-MM-DD` guard — **best for once-per-day**. `chain_health_loop` (`health.py:341`) computes `_seconds_until_next(hh,mm)` and sleeps exactly — **best for exact wake**. `alfred_loop` (`briefing/alfred.py:279`) uses `_in_post_window(now_et, [start,end])` `:267-276` — **best for a window**.
- **Pacific time**: `zoneinfo.ZoneInfo("America/Los_Angeles")` (no pytz). Existing windows use ET. **`_in_post_window` does NOT handle midnight-crossing windows** — the Wolf nightly Wrap window **7pm–2am PT** needs a two-branch check (`cur >= start or cur <= end`). Must write this.
- **Config**: `cfg.get("dot.path", default)` `config.py:70-79`, cached, `$ENV` expansion, **no hot reload — restart required**. `gmail_watcher:` block `consensus.yaml:673-689` (enabled:false, paths, poll 60s, sender_allowlist, subject_substrings, caps).
- **Service restart**: `sudo systemctl restart consensus-engine`; unit at `/etc/systemd/system/consensus-engine.service` (`ExecStart=python3 -m consensus_engine --live`, `EnvironmentFile=-…/.env.service`, `Restart=always`). No hot reload. Verify after: both services active + symlink intact.

---

## 2. Data Sources Currently In Use
- **Gmail/Wolf** — connected, watcher **disabled** (text/plain+regex only). The feature's primary new input.
- **Twitter via TweetShift** (Discord gateway) — primary live trigger; full directional parse.
- **YouTube** (14 channels, `/root/.openclaw/sources.json`) — captions/vision → structured direction+levels, persisted.
- **Options flow** (yfinance ~15-min) — unusual call/put, persisted partially.
- **SEC** (EDGAR 8-K + Form 4 insider/cluster) — background watchers gated by `scanners.sec_background_watchers_enabled`.
- **News cascade, Reddit/ApeWisdom/StockTwits, SearXNG, Google Trends** — feed cross-reference scoring.
- **Finnhub** (real-time quotes) + **yfinance** (OHLCV).

## 3. Data Flow (current)
```
sources (tweet/yt/options/sec/news/...) ─▶ ticker_signals / per-source tables
        │                                          │
        ▼                                          ▼
  cross_reference.score_ticker(ticker,base,dir) ─▶ ScoreBreakdown(.total)
        │                                          │
        ▼                                          ▼
  classify (STRONG/WATCHLIST) ─▶ alerts/discord.py (REST) ─▶ #chat (alerts), #briefing (Alfred)
        ▲
  schedulers: alfred_loop (08:50-09:00 ET brief), atlas_sweep, macro_digest, chain_health
```
Gmail/Wolf currently dead-ends: HTML body → `""` → nothing inserted.

## 4. Strengths (reuse, don't rebuild)
- Mature **LLM client with failover** + a proven **JSON-by-prompt** extraction pattern (captions parser).
- A working **Gemini quota/key-rotation/budget** stack (Pacific-midnight reset) — directly reusable for chart images.
- **3 of 4 confluence sources already emit a directional stance**; A3 already clusters sources by independence — confluence is cheap.
- **Alfred** is a complete, transactional, scheduled digest pipeline to clone (DB pull → LLM synth → Discord → vault archive).
- **Idempotent migration pattern** + clean async DB access → adding thesis/market-read/calls tables is low-risk.
- **ZoneInfo** timezone idiom + 3 scheduling templates (exact-wake / window / once-per-day).

## 5. Gaps (genuine absences this feature must fill)
1. **HTML email reading** — `_decode_body` has no text/html branch. (rebuild)
2. **Chart-image vision on arbitrary remote images** — only video-URL vision is wired; `analyze_image` exists but unused. (wire/extend)
3. **LLM structured extraction for macro/thesis** — none today; macro symbols are actively blacklisted. (new)
4. **Stateful thesis tracking** (stage machine forming→divergences→imminent/acting, key levels, active/invalidated) — no table, no logic. (new)
5. **Direction-aware confluence** — sources have directions but nothing compares them; `contradiction_index` is never populated; no market/sector/asset-class scope matching; no ~2-3wk window. (new, but cheap)
6. **#news channel + proactive stage/level-break alerts** — no #news channel, no proactive post path beyond Alfred's morning brief. (new channel + posting)
7. **@-mention the user** — no owner-id, default mention-suppression. (new)
8. **Midnight-crossing schedule window** (7pm–2am PT Wrap) — no helper handles it. (new)
9. **Event-triggered digests** (fire ~1min after the midday/Wrap email lands) + **clock Sunday 10am** + **Sunday add-on** + **quiet-day = no digest** + **weekly recap with outcome tracking**. (new scheduler)
10. **Beneficiary inference for BIG catalysts only** — none today. (new, scoped)
11. **Full Gmail history backfill** (All Mail, not just inbox) to seed thesis state. (new one-shot)

## 6. Notes for later passes
- Spec/requirements are COMPLETE (rounds 1–6 in `todo/wolf-macro-brain.md`). Passes 1–3 here **validate/improve/stress-test** the fixed approach, not invent features.
- Build order (spec): **reader → state → confluence → alerts/digests → backfill → (later) !all**.
- Shared-file tripwire (test everything using them if touched): `gmail_watcher.py`, `main.py`, `llm_client.py`, `config.py`+`consensus.yaml`, `db.py`, `alerts/all_command/narrator.py`+`aggregator.py`.
- Hard gate: sign-off before creating #news / first live post / flipping `enabled:true`.
