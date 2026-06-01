# Final Plan — Wolf newsletter → trade-finding macro brain (wolf-news-brain / TODO #20)

Build-ready spec. Every Pass-3 Critical/Major/Security finding is folded in as a hard requirement (tagged `[C-1]`, `[SEC-CRIT]`, etc.). Spec source of truth: `todo/wolf-macro-brain.md`. Build order = spec order: **reader → state → confluence → alerts/digests → backfill → (later) !all**. One VERIFIED phase beats three half-built.

---

## 1. System Overview

A new **#news lane** that is *architecturally separate* from the existing fast ticker-alert pipeline. Wolf emails are read (HTML + chart vision + LLM extraction) into a **stateful thesis store**; a **direction-aware confluence engine** compares each Wolf thesis against other sources; proactive **#news alerts** fire on stage-change / level-break / confluence-tier, with a **critical @-ping**; **scheduled digests** summarize the regime. `!all` integration is explicitly **phase 2**.

**Load-bearing architectural rule [C-1]:** Wolf data writes ONLY to new tables and feeds ONLY the #news lane. It does **not** call `db.insert_signal`/touch `ticker_signals`, so it can never inject into the existing #chat alert path or `!all` discovery. **[C-2]** The Wolf watcher + digest scheduler run on `stop_event` (shutdown only), NOT `combined_stop` — so they survive the weekend pause (Wolf is a 7-day feed). **[C-3]** Confluence computes its OWN agreement value in new tables; it never reads or writes the existing live `contradiction_index`.

---

## 2. Component Architecture (new modules)

### 2.1 `consensus_engine/scanners/gmail_watcher.py` — REBUILD in place
- **Purpose:** poll Gmail for Wolf emails, hand each to the parser, persist results to the thesis store, trigger alerts/digests.
- **Keep:** the `gmail_watcher_loop(stop_event, record_ok, record_err)` signature (so main.py wiring is minimal), the dedup tables (`seen_gmail_messages`/`seen_gmail_bodies`), the `OpenClawProcessed` label, the three-gate intake (sender allowlist + subject + auth).
- **Change:** (a) **drive on `stop_event`** not `combined_stop` `[C-2]`; (b) extend `_decode_body` → `(text, html)` walking MIME with a **text/html fallback** via BeautifulSoup `[C1]`; (c) replace the `extract_tickers→insert_signal` body with `wolf_email_parser.parse_email(...)` → `wolf_theses.ingest(...)` `[C-1]`; (d) align declared `SCOPES` to `gmail.modify`; (e) **Wrap detection by chart-count/size**, not subject keyword — loosen/booststrap `subject_substrings` so Wraps aren't dropped (verify vs real email) `[Minor]`; (f) tighten `_auth_results_pass` to word-boundary regex `[SEC-MED]`.

### 2.2 `consensus_engine/analysis/wolf_vision.py` — NEW
- **Purpose:** read one chart image → structured JSON.
- **Inputs:** image URL (from email HTML). **Outputs:** `ChartRead` dict `{instrument, timeframe, direction, levels:[{price,role,label,confidence}], patterns, indicators, raw_caption}` or `None`.
- **Core logic:** `fetch_chart_bytes(url)` with SSRF guard `[SEC-HIGH]` (https-only, host allowlist = newsletter CDN, `allow_redirects=False`, 10MB cap, reject private/loopback IPs, content-type image/*) → native `google.genai` `types.Part.from_bytes(data, mime_type)` (NOT `from_uri`) → **multi-model fallback** `["gemini-flash-latest","gemini-2.5-flash","gemini-flash-lite-latest"]` (503/quota → next) `[probe-confirmed]` → reuse the video parser's key rotation/`_mark_key_exhausted`/`rate_limiter.acquire("gemini")`/`BudgetManager`. **Validation:** confidence<0.7 → drop level; validate each price within ±30% of a recent quote (Finnhub/yfinance) → else flag low-confidence; one chart per call; cap 5 charts/email, prioritize text-referenced.

### 2.3 `consensus_engine/analysis/wolf_email_parser.py` — NEW
- **Purpose:** turn a full email into a validated `WolfExtraction`.
- **Inputs:** `(text, html, subject, sender, ts)`. **Outputs:** `WolfExtraction{ regime, theses:[WolfSignal], catalysts:[...], chart_reads:[...] }`.
- **Core logic:** BeautifulSoup text extract + `_extract_chart_image_urls(html)` (keep `wp-content/uploads/`, drop sendgrid/tracking/≤5px); LLM structured extraction via `call_with_fallback(role="primary", max_tokens≈4096, temperature=0.1, timeout=60)` with **JSON-by-prompt + anti-injection clause** `[SEC-CRIT]`; merge chart reads (from `wolf_vision`) with text; **validate every field** (enum clamp for direction∈{bull,bear,neutral}/stage∈{forming,diverging,imminent,acting}, ticker regex `^[A-Z\^]{1,10}$`, level range, confidence gate) — reject/clamp, never forward raw `[SEC-CRIT]`. **Asset-direction normalization** in the prompt (rates up → BONDS bear) `[M-4/I5]`. Keep the regex symbol scan as a supplement.

### 2.4 `consensus_engine/analysis/wolf_theses.py` — NEW
- **Purpose:** the stateful thesis store + state machine.
- **Inputs:** `WolfExtraction`. **Outputs:** thesis ids touched + stage-change/level-break events.
- **Core logic:** `ingest(extraction)` → per `WolfSignal`: `match_or_create_thesis` (exact active match on scope+identifier+direction; opposite-direction → invalidate-and-close the old `[M-1]`; else create with `price_at_creation` fetched at open); stage transition **allows downgrade** + explicit "Wolf drops it" close `[M-1]`; `check_price_invalidation(thesis)` with 0.5% buffer; **level-less theses capped to surface tier + short auto-expiry** `[M-2]`; sprawl caps (10 market/20 sector/30 stock); 90-day stale expiry. Emits events the alert layer consumes.

### 2.5 `consensus_engine/analysis/wolf_confluence.py` — NEW
- **Purpose:** direction-aware agreement vs other sources. **Never touches the live `contradiction_index`** `[C-3]`.
- **Inputs:** a Wolf thesis (as a `Stance`). **Outputs:** `ConfluenceResult{agree_count, disagree_count, tier, divided, agreeing[], disagreeing[]}`.
- **Core logic:** `build_stance_pool(window_days=21)` from existing tables → normalize to `Stance` (mapping per source); `_scopes_match` per the **explicit scope matrix** (§4); dedup key `source_cluster|source_detail|day_bucket`; **Wolf-echo filter** (drop stances referencing Wolf/the newsletter) `[M-3]`; **YouTube capped to one video-cluster vote** (reuse A3 `SOURCE_CLUSTERS`) `[M-3]`; **recency decay** + **require ≥1 non-Wolf level-bearing stance before high/critical** `[M-4]`; tiers surface(0)/high(≥1)/critical(≥2); `divided = agree≥1 and disagree≥agree`. Equal-weighting kept as a noted product risk.

### 2.6 `consensus_engine/alerts/wolf_news.py` — NEW
- **Purpose:** post to #news; @-ping on critical.
- **Core logic:** plain/embed POST modeled on `briefing/alfred.py:_send_discord_briefing` but `channel_id` = `cfg.get("api_keys.discord_news_channel_id")`; `send_critical_ping(text)` overrides `allowed_mentions={"users":[owner_id]}` and builds content from **validated enum fields only** `[SEC-CRIT]`; **critical-ping rate limit ≤3/hr + batch overflow into next digest** `[SEC-HIGH]`. Critical tier additionally **requires a non-Wolf corroborator** `[M-4]`. Alerts fire only on stage-CHANGE / level-break / tier-change (not every mention) — honors Alert Philosophy.

### 2.7 `consensus_engine/briefing/wolf_digest.py` — NEW
- **Purpose:** scheduled + event-triggered digests, weekly recap.
- **Core logic:** `wolf_digest_loop(stop_event)` on `stop_event` `[C-2]`, polls 60s; **midnight-crossing window helper** `in_window(now_pt, start, end)` (`cur>=start or cur<=end` when end<start) for the **7pm–2am PT Wrap** window; event-triggered midday/nightly (fire ~1min after the email lands), clock Sunday 10am PT + Sunday add-on; **quiet day = no digest, no "nothing to report"**; once-per-slot guard key (date+slot); Alfred-style transactional outbox (pending→posted→archived to vault); render via Alfred-style `_llm_synthesize` (skip hostile-sanitize). Weekly recap reads `thesis_outcome_checks`.

### 2.8 Beneficiary inference (in `wolf_email_parser` or a small helper)
- BIG catalysts only (Wolf-flagged); LLM infers up/down names; **always labelled "bot inference"**; cap names per catalyst; never independent calendar scanning `[C7]`.

### 2.9 Backfill — `scripts/wolf_backfill.py` (one-shot)
- All-Mail query via the rebuilt reader; idempotent via `seen_gmail_messages`; **text-first, cap/skip charts on old emails** to save quota; throttled; NOT in the live loop. Seeds thesis *state* (not historical confluence) `[C8]`.

---

## 3. Data Flow Pipeline (new in **bold**)
```
Gmail poll (stop_event) ─▶ three-gate intake ─▶ **_decode_body→(text,html)**
   ─▶ **wolf_email_parser.parse_email** ──(per chart)──▶ **wolf_vision.read (SSRF-guarded, Gemini fallback)**
   ─▶ **validated WolfExtraction** ─▶ **wolf_theses.ingest** (match/create/advance/invalidate)
        │                                   │
        │                                   ▼
        │                         **macro_theses / thesis_outcome_checks**
        ▼                                   │
 **wolf_confluence.evaluate**◀─ build_stance_pool(21d) from youtube_signals/signal_events/options/sec
        │  (Wolf-echo filtered, YT cluster-capped, recency-decayed)
        ▼
 stage-change / level-break / tier event ─▶ **alerts/wolf_news** ─▶ #news  (critical ⇒ @-ping, rate-limited)
        ▲
 **wolf_digest_loop (stop_event)**: event midday/nightly(7pm-2am PT) + Sun 10am + weekly recap ─▶ #news
```

---

## 4. Data Structures

### New SQLite tables (schema v15; append `CREATE TABLE IF NOT EXISTS` to `db.py` SCHEMA; bump `_schema_versions` to `(15, "wolf macro-brain")`)
```sql
CREATE TABLE IF NOT EXISTS macro_theses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope_level TEXT NOT NULL,           -- market|sector|stock|asset
  identifier  TEXT NOT NULL,           -- canonical: SPX,XLE,NVDA,OIL,GOLD,BONDS,YIELDS,BTC,DXY
  direction   TEXT NOT NULL,           -- bull|bear
  stage       TEXT NOT NULL DEFAULT 'forming',
  source      TEXT NOT NULL DEFAULT 'wolf',
  key_levels_json TEXT NOT NULL DEFAULT '[]',
  price_at_creation REAL,
  created_at REAL NOT NULL, last_updated REAL NOT NULL, invalidated_at REAL,
  status TEXT NOT NULL DEFAULT 'active', -- active|invalidated
  has_levels INTEGER NOT NULL DEFAULT 0, -- M-2 gate: 0 => surface tier only
  evidence_log_json TEXT NOT NULL DEFAULT '[]',
  outcome_direction_confirmed INTEGER, outcome_level_hit REAL, outcome_checked_at REAL,
  UNIQUE(scope_level, identifier, direction, status)
);
CREATE INDEX IF NOT EXISTS idx_theses_scope ON macro_theses(scope_level, identifier);
CREATE INDEX IF NOT EXISTS idx_theses_status ON macro_theses(status);

CREATE TABLE IF NOT EXISTS thesis_outcome_checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thesis_id INTEGER NOT NULL,
  checked_at REAL NOT NULL, spot_price REAL NOT NULL,
  direction_confirmed INTEGER, level_hit REAL, pct_move REAL, notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_toc_thesis ON thesis_outcome_checks(thesis_id);

CREATE TABLE IF NOT EXISTS wolf_digest_log (   -- once-per-slot guard + outbox
  slot_key TEXT PRIMARY KEY,                    -- e.g. 2026-05-31|nightly
  state TEXT NOT NULL, content TEXT, posted_msg_id TEXT, created_at REAL NOT NULL
);
```
- **`Stance`** (in-memory dataclass): `{scope_level, identifier, direction(bull|bear|neutral), level?, source_cluster, source_detail, timestamp, conviction, raw_ref}`.
- **Scope matrix (§ M-5, write as a tested table before coding confluence):** market = {SPY,QQQ,IWM,SPX,NDX,RUT,VIX}; sector = sector ETFs (XLK,XLF,…,SMH,IGV); stock = `sector_map.yaml` members; asset = {OIL(USO,CL=F),GOLD(GLD,GC=F),BONDS(TLT,IEF),YIELDS(^TNX),BTC(IBIT,BTC-USD),DXY(UUP)}. Cross-rules: market↔market only; sector matches same-sector stocks; stock/asset = exact identifier; cross-scope does NOT count (or counts at a documented discount — default: not counted). Worked examples included in the module docstring + unit tests.

### Stance pool sources (verify during build, don't assume)
YouTube → `youtube_signals`(+`youtube_macro`,`youtube_levels`); Twitter+SEC+options → `signal_events`(has `direction`,`source_type`,`ticker`,`recorded_at`). **Verify** options/twitter/sec actually write `signal_events` with a usable `direction`; if options `FlowHit.side` isn't persisted, add a `signal_events` write in the options path (CALL→long/PUT→short).

---

## 5. Integration Plan (exact connection points)
- **`main.py` task list** (final `tasks.extend([...])` ~line 674): the existing `gmail_watcher_loop(...)` stays but must now be driven by `stop_event` (change inside the loop, not the wiring); ADD `asyncio.create_task(wolf_digest_loop(stop_event))`. Confirm the watcher uses `stop_event` not `combined_stop` `[C-2]`.
- **`db.py`:** append the 3 tables to `SCHEMA`; add `(15, "wolf macro-brain")` to `_schema_versions`; add access fns (`upsert_thesis`, `get_active_theses`, `invalidate_thesis`, `insert_outcome_check`, digest-log get/set) using the standard `await get_db()` + parameterized `?` pattern. Keep new tables on the hardcoded migration lists `[SEC-MED]`.
- **`config/consensus.yaml`:** extend `gmail_watcher` (add `charts_per_email_cap: 5`, `cdn_allowlist`, `wrap_min_charts`); add `wolf` block (`enabled:false`, tiers, confluence_window_days:21, ping caps); add `digest` block (midday/nightly/sunday times PT, `wrap_window_pt:["19:00","02:00"]`); add `api_keys.discord_news_channel_id: "$DISCORD_NEWS_CHANNEL_ID"`, `api_keys.discord_owner_user_id: "$DISCORD_OWNER_USER_ID"`.
- **Env:** `DISCORD_NEWS_CHANNEL_ID`, `DISCORD_OWNER_USER_ID`, (opt) `GEMINI_API_KEY3` in BOTH `.env` and `.env.service`, then `chown openclaw:openclaw` + `chmod 600` `[SEC-LOW]`. `chmod 600 credentials.json` `[SEC-MED]`.
- **Reuse (don't rebuild):** `llm_client.call_with_fallback`; gemini key/quota stack in `gemini_video_parser`; `briefing/alfred.py` post + synth patterns; A3 `consolidation.SOURCE_CLUSTERS`; `data/sector_map.yaml`; DB migration pattern.

---

## 6. Failure Handling
- **No text/HTML-only:** still run vision on charts; never early-exit on empty text.
- **Vision 503/quota:** model fallback → key rotation → skip chart, degrade to text caption; thesis without level = surface tier (no @-ping) `[M-2]`.
- **Level misread:** confidence<0.7 + price-range guard → drop/flag, don't forward.
- **Conflicting Wolf vs others:** `divided` flag surfaced, not silently dropped.
- **Quiet day:** no digest, no note.
- **Restart mid-digest:** `wolf_digest_log` outbox guards against dup/loss.
- **Prompt injection:** validated-fields-only; injection_attempt flag → neutral `[SEC-CRIT]`.
- **SSRF/oversize image:** guard rejects → skip chart `[SEC-HIGH]`.
- **Ping storm:** ≤3/hr, batch overflow `[SEC-HIGH]`.
- **Weekend:** loops on `stop_event` keep running `[C-2]`.

---

## 7. Feature Activation Plan
1. Land code with `gmail_watcher.enabled:false` (no behavior change; safe to commit/run).
2. Create the **#news** Discord channel; set `DISCORD_NEWS_CHANNEL_ID` + `DISCORD_OWNER_USER_ID` in both env files (chown/chmod). **← HARD GATE: sign-off before creating channel / first live post.**
3. Dry-run: run the parser+theses+confluence against real inbox emails, post a **sample digest + sample alert to a TEST channel**; confirm @-ping renders, midnight-window unit test green.
4. After sign-off: flip `gmail_watcher.enabled:true` (+ `wolf.enabled:true`), `sudo systemctl restart consensus-engine` (no hot reload), verify both services active + no GATEWAY drift + no LLM-health fail + symlink intact.
5. Run `scripts/wolf_backfill.py` once (throttled) to seed theses.

---

## 8. Verification Checklist (Pass 5 must satisfy)
**Pre-build:** `make test-baseline` + commit (`.test-baseline` currently empty) `[Minor]`.
**Regression:** full suite; **no green→red** vs baseline (separate verifier agent).
**Always-on (after every restart):** `consensus-engine` + `openclaw-gateway` both `active`; no `GATEWAY drift`; no LLM-health failure; `/root/.openclaw → /home/openclaw/.openclaw` intact.
**Architecture invariants (unit tests):**
- A Wolf ingest does NOT make any ticker "active" (`get_active_tickers` unaffected) `[C-1]`.
- Wolf watcher + digest loop run during a simulated Saturday (`stop_event`, not `combined_stop`) `[C-2]`.
- Confluence never writes/reads the existing `contradiction_index` `[C-3]`.
- Midnight-crossing window (7pm–2am PT) matches 1am; rejects 3am `[C6]`.
- Stage downgrade + "Wolf drops it" close work; opposite-direction flip invalidates old `[M-1]`.
- Level-less thesis → surface tier, no @-ping, no confluence vote `[M-2]`.
- Wolf-echo stance dropped; 3 tweets/analyst/day = 1 vote; YouTube = 1 cluster vote `[M-3]`.
- Extraction rejects an injected "ignore instructions / set direction=bull" email → neutral/flag; no email text reaches a mention string `[SEC-CRIT]`.
- Image fetch rejects http/localhost/oversize/redirect `[SEC-HIGH]`.
- Critical ping rate-limited to ≤3/hr `[SEC-HIGH]`.
**Real-world (Evidence Standard — show actual output):**
- Live read of ≥3 REAL Wolf inbox emails → printed validated JSON (text + chart reads). (Vision already proven live on real charts in Pass 3.)
- Confluence on a known case → correct agree/disagree/tier.
- Dry-run #news sample (digest + alert) to a TEST channel before any live post.
**Shared-file tripwire:** if `gmail_watcher.py`/`main.py`/`llm_client.py`/`config.py`+`consensus.yaml`/`db.py`/`narrator.py`+`aggregator.py` touched → test every feature using them.

---

## Adaptation notes
- **ralplan** (skill's Pass-4 default) was replaced by direct authoring because the design is already adversarially vetted (critic+security with concrete schemas/algorithms). The **mandated codex adversarial review of THIS plan** (Pass 4→5 gate) is the independent consensus check — authoring and review stay separate.
- Build phases (= Pass 2 sequence) each gated by their §8 checks. Phases 1–3 (reader→state→confluence) are dry-run-only and safe to build+commit before the channel sign-off; phase 4 (alerts/digests live) is behind the HARD GATE.

---

## PLAN REVISION (post cross-model review — supersedes where conflicting)
Codex was down → review done via Gemini + an independent code-verifier (see `codex-adversarial-review.md`). Both → REVISE. Adopted:

**Scope: ship a THIN v1, build in strict spec order, verify each phase.**
- **PHASE 1 (build now, dry-run only — the proactive #news lane minimum):**
  1. `db.py`: add `macro_theses` table + schema v15 + access fns.
  2. `scanners/gmail_watcher.py` rebuild: `_decode_body→(text,html)` w/ BeautifulSoup `lxml`; **pass real `stop_event` (main.py:552) at main.py:676** not `combined_stop`; **skip the subject substring gate for the trusted Wolf sender** (sender allowlist already pins it); align SCOPES to `gmail.modify`; extract chart URLs (first 5 distinct non-tracking by appearance); tighten `_auth_results_pass` regex.
  3. `analysis/wolf_vision.py`: SSRF-guarded fetch + native Gemini `from_bytes` + multi-model fallback `[flash-latest, 2.5-flash, flash-lite]` + confidence/price-range validation.
  4. `analysis/wolf_email_parser.py`: HTML text → LLM JSON extraction (anti-injection + enum/ticker/level validation); **append ChartRead as structured fields linked by identifier** (no multimodal prompt in v1).
  5. `analysis/wolf_theses.py`: match/create/advance(**allow downgrade**)/invalidate; level-less → surface tier; **sprawl cap → invalidate oldest least-recently-updated of that scope + log**; 90d stale expiry; store `price_at_creation`.
  6. `alerts/wolf_news.py`: post stage-change + level-break to #news; critical @-ping (validated-fields-only content) with ≤3/hr rate limit — **post the message immediately; suppress only the @-ping on limit**.
  - Phase-1 verification: live-read ≥3 real emails (show output); thesis transitions on a real sequence; dry-run sample to a TEST channel. **HARD GATE** before creating #news / live post / `enabled:true`.
- **PHASE 2 (after phase-1 live-verified): confluence engine.** MUST first run `scripts/verify_confluence_sources.py`; read THREE tables (`signal_events` twitter/youtube; `options_flow` side→dir; `ticker_signals[sec]` sentiment→dir) — NOT just signal_events (BLOCKER fix); skip `direction=NULL` analyst-cluster rows; scope matrix; Wolf-echo filter; YT cluster-cap; recency decay; non-Wolf level-bearing requirement for high/critical.
- **PHASE 3: digests + weekly recap + outcome tracking.** Digest synthesis from validated/enum fields ONLY (output-injection guard) + synthesis-injection test; midnight-crossing window helper; quiet-day skip; `wolf_digest_log` outbox.
- **PHASE 4: beneficiary inference** (big catalysts only, labelled inference, capped names). **PHASE 5: backfill.** **Later: `!all` integration.**

**Path correction (global):** all data-file refs are `consensus_engine/data/*.yaml`.

**Pre-build chore:** `make test-baseline` + commit (`.test-baseline` is empty) before any feature code.

---

## PLAN REVISION v2 (post real-Codex review on gpt-5.5 — supersedes v1 where conflicting)
Codex verified against live source (couldn't read the plan files — sandbox denied entry to the workspace — so it reviewed code+spec+GitHub). It found ONE blocker the earlier reviewers missed, now verified against `main.py:552-691` + entrypoint `main.py:1400 (live; Codex cited 1383 from GitHub)`:

1. **[BLOCKER — corrects v1's C-2 fix] Separate top-level supervisor, NOT raw stop_event inside run_live's gather.**
   `run_live` does `await asyncio.gather(*tasks)` (main.py:680). On the Friday-3pm pause, all `combined_stop` tasks exit; a Wolf loop bound to raw `stop_event` would keep running → gather never returns → the weekend command-listener (main.py:560-601: your `!`commands + @mentions) never starts. **Fix:** keep `gmail_watcher_loop` OUT of run_live's task list. Add a new top-level coroutine `wolf_news_supervisor(stop_event)` that runs the Wolf gmail watcher (+ later the digest scheduler) and launch both from the entrypoint: replace `asyncio.run(run_live(stop))` (main.py:1400 (live; Codex cited 1383 from GitHub)) with `asyncio.run(_run_all(stop))` where `_run_all` does `await asyncio.gather(run_live(stop), wolf_news_supervisor(stop))`. The supervisor loops on `stop_event` (shutdown only) so it survives the weekend; it must wrap its body in try/except so a Wolf crash never takes down run_live.
   - NOTE: this means the existing `gmail_watcher_loop(combined_stop,...)` at main.py:676 (old text/plain watcher) should be REMOVED from the run_live task list as part of the rebuild (the rebuilt watcher lives in the supervisor). Tripwire: confirm nothing else depends on it being in that list.
2. **[NEW] Durable outbox for ALERTS too (not just digests).** New table `wolf_news_alerts(id, dedupe_key UNIQUE, status, discord_message_id, payload_json, created_at, posted_at)`; build a `pending` row, then post, then mark `posted` (model on Alfred `briefing_runs` pending→posted, alfred.py:219-255). A crash can't double-post or lose an alert. dedupe_key = thesis_id + stage (so the same stage never alerts twice).
3. **[NEW] Wolf-specific processing/dedupe table** (don't rely on text-only `seen_gmail_bodies`). New `wolf_emails_processed(message_id PK, html_sha1, image_urls_sha1, parse_status, error, processed_at)`; mark the Gmail message processed (label) ONLY after durable Wolf state is written — so an image-only email is never lost or replayed.
4. **[NEW — simplify] Phase-1 alerts fire ONLY on a new or stage-changed thesis.** Defer key-level-break monitoring to phase-2 (no price-watcher for Wolf levels exists; existing level alerts only query youtube_levels at main.py:702/731-738). v1 needs no price polling.
5. **[NEW minor]** On supervisor startup, do a test `messages().modify` (label) to verify the token really has `gmail.modify` before processing; evaluate ALL `Authentication-Results` headers (not just the first); persist skipped-due-budget/cap telemetry.

**Revised PHASE-1 module list (supersedes v1's):**
- `db.py`: add `macro_theses` + `wolf_news_alerts` + `wolf_emails_processed` to SCHEMA; `_schema_versions` → (15,...). (macro_theses already added this session.)
- `analysis/wolf_vision.py` (new) — unchanged from v1.
- `analysis/wolf_email_parser.py` (new) — unchanged from v1 (validation/anti-injection/ChartRead-as-fields).
- `analysis/wolf_theses.py` (new) — match/create/advance(allow downgrade)/invalidate; level-less→surface; sprawl-cap→invalidate-oldest-LRU; emits new/stage-change events only (no level-break in v1).
- `scanners/gmail_watcher.py` (rebuild) — HTML decode; skip subject gate for trusted Wolf sender; gmail.modify + startup label test; multi-header auth; write to wolf_emails_processed; hand parse→theses; **stays out of run_live**.
- `alerts/wolf_news.py` (new) — durable-outbox post to #news; new/stage-change only; critical @-ping (validated-fields-only) ≤3/hr, post message now / suppress only the ping.
- `main.py` — add `wolf_news_supervisor(stop_event)` + `_run_all`; remove old gmail task from run_live gather; entrypoint gathers both. (tripwire)
- `config/consensus.yaml` — `news_alerts.{enabled,channel_id,test_channel_id,allow_mentions}`; extend `gmail_watcher`. Keep enabled:false.

**Re-review:** after phase-1 code is written, re-run Codex (gpt-5.5) on the actual DIFF — but first fix the sandbox so root can read the workspace (otherwise it falls back to GitHub and can't verify local changes).
