# Pass 1 — Candidate Components & Improvements (wolf-news-brain)

**Adaptation note:** the feature set is FIXED by `todo/wolf-macro-brain.md` (interview rounds 1–6). So Pass 1 is not open-ended feature invention. It is: (a) the spec's build components restated as candidates, each redundancy-checked against the Pass 0 map, plus (b) **technical-approach decisions** and (c) **improvement candidates** the kickoff explicitly invites ("better way → take it", "new improvement → build it"). Source-quality tag: **H** = production-validated/official-docs, **M** = widely-used pattern, **L** = blog-grade.

Real-world facts confirmed this pass: `beautifulsoup4 4.14.3` + `lxml` installed (no new dep); `google.genai` installed; gmail token at `/root/.openclaw/gmail/token.json`; real Wolf charts present at `/tmp/wolf_charts/` (e01_1.jpg 131KB, e01_2.jpg 111KB).

---

## A. Core build components (from spec — each non-redundant vs Pass 0 gaps)

### C1 — Wolf email reader rebuild (Gap #1, #2, #3)
- **Function:** Replace `_decode_body` (text/plain-only) with HTML extraction + chart-image vision + LLM structured extraction. Keep the regex stock scan as a supplement; bypass the macro blacklist.
- **Rationale:** Wolf emails are HTML-only with the real signal in remote chart images; current watcher extracts nothing.
- **Approach decision (H):** `BeautifulSoup(html, "lxml").get_text(separator="\n", strip=True)` for text (strip `<style>/<script>/<head>` first). Chart URL filter = keep `<img src>` whose path contains `wolfonwallstreet-trade.com/.../wp-content/uploads/`; drop sendgrid/tracking/`/wf/open`/`/trk` and `width|height<=5` pixels. Extend `_decode_body` to return `(text, html)` and walk MIME falling back to `text/html`.

### C2 — Chart vision extraction (Gap #2)
- **Function:** For each load-bearing chart, extract `{instrument, direction, levels[{price,role,label,confidence}], patterns, indicators(3C), raw_caption}`.
- **Approach decision (H):** **Native Gemini flash via `google.genai`, downloading image bytes first then `types.Part.from_bytes(data, mime_type)`** — NOT `from_uri` (unreliable for arbitrary HTTP image URLs on Gemini 2.0/2.5 family; confirmed issue). One chart per call (multi-image-in-one-call degrades per-chart accuracy). Reuse the video parser's key rotation / `_mark_key_exhausted` (Pacific-midnight reset) / `rate_limiter.acquire("gemini")` / `BudgetManager`.
- **Cost cap (H):** ≤5 charts/email, prioritize charts the email TEXT references; worst case ~50 calls/day, well within free-tier RPD.

### C3 — Stateful thesis store + state machine (Gap #4)
- **Function:** Track each major thesis through `forming → diverging → imminent → acting`, `active` until `invalidated`. New SQLite table `macro_theses` (+ `thesis_outcome_checks`).
- **Approach decision (M):** monotonic stage advance (never regress); `UNIQUE(scope_level,identifier,direction,status='active')` = one active thesis per instrument+direction; opposite-direction new call invalidates the old (flip); price-invalidation with 0.5% buffer; **store `price_at_creation`** at open.

### C4 — Direction-aware confluence engine (Gap #5)
- **Function:** Normalize every source into a common `Stance` {scope_level, identifier, direction, level?, source_cluster, source_detail, timestamp, conviction}; match Wolf's stance vs the last ~21d pool; output agree/disagree counts, tier (surface/high/critical), `divided` flag.
- **Approach decision (M):** scope via `data/sector_map.yaml` (63→10 ETF) + an asset-class canonical map (USO→OIL, GLD→GOLD, TLT→BONDS, ^TNX→YIELDS, IBIT→BTC, UUP→DXY…); dedup key `source_cluster|source_detail|day_bucket` (3 tweets/analyst/day = 1 vote); populate the dormant `contradiction_index`. **Reuse, don't rebuild** A3 `consolidation.py` cluster skeleton.
- **Redundancy check:** 3/4 sources already emit direction (YouTube stored; Twitter `ParsedTweet.direction`; options `FlowHit.side`; SEC `insider_buy_or_sell()`); only the comparison layer is missing → cheap.

### C5 — #news channel + proactive alerts (Gap #6, #7)
- **Function:** New #news Discord channel; post on stage-change + level-break + confluence; @-mention the user on `critical` (Wolf+2) ANYTIME incl. overnight.
- **Approach decision (M):** model the post path on `briefing/alfred.py:_send_discord_briefing` (parameterize `channel_id`); add `api_keys.discord_news_channel_id`. @-mention requires a NEW path that sets `content="<@id> …"` + `allowed_mentions={"users":[id]}` (the default `{"parse":[]}` suppresses mentions); add `DISCORD_OWNER_USER_ID`.

### C6 — Digest scheduler (Gap #8, #9)
- **Function:** event-triggered midday (~1min after the ~12–1:05pm PT email) + nightly Wrap (window **7pm–2am PT**, crosses midnight) + clock Sunday 10am + Sunday add-on; quiet day = no digest; weekly recap with outcome tracking.
- **Approach decision (M):** new loop in `main.py` task list; copy `alfred_loop` window pattern but **add a midnight-crossing window helper** (`cur >= start or cur <= end`) — no existing helper handles it. Pacific via `ZoneInfo("America/Los_Angeles")`. Digest text via Alfred-style `_llm_synthesize` (skip the hostile-sanitize phase; DB-sourced).

### C7 — Beneficiary inference for BIG catalysts only (Gap #10)
- **Function:** For war-escalation / Fed-surprise–class catalysts Wolf mentions, infer up/down sectors+names (oil spike → up XLE/OIH/HAL/SLB; risk: airlines/cruise). Mark as the bot's inference.
- **Approach decision (M):** LLM call gated to catalysts Wolf flags as big; never independent calendar/news scanning.

### C8 — Full Gmail history backfill (Gap #11)
- **Function:** One-shot ingest of All Mail (not just inbox) to seed thesis state.
- **Approach decision (M):** reuse the rebuilt reader over a historical query; idempotent via `seen_gmail_messages`; rate/budget-aware on vision (cap or skip charts for very old emails to save quota).

### C9 — (LATER) `!all` + existing-alert integration
- **Function:** surface Wolf regime/theses/confluence inside `!all` and ticker alerts. **Explicitly phase-2 per spec.** Not in the first build.

---

## B. Improvement candidates (kickoff-invited; beyond the literal spec)

- **I1 (H) — Anti-hallucination on chart levels:** require a per-level `confidence`; treat `<0.7` as `null` (don't guess); validate each extracted level within ±~30% of the instrument's recent close (Finnhub/yfinance quote already wired). Rationale: digit transposition (7340→7430) and invented intermediate levels are the dangerous vision failure modes.
- **I2 (M) — Text-referenced chart prioritization:** parse email text first; run vision only on charts the text mentions → fewer calls, higher signal, lower quota burn.
- **I3 (M) — `!thesis list` Discord command + evidence log:** keep raw `snippet` per stage transition in `evidence_log_json`; a read command surfaces current theses/stages for manual correction. Rationale: extraction-quality safety valve.
- **I4 (M) — Stale-thesis auto-expiry (90d) + sprawl caps** (10 market / 20 sector / 30 stock). Rationale: prevent never-invalidating + thesis sprawl.
- **I5 (M) — Asset-direction normalization doc in the extraction prompt:** "rates higher" → `direction=bear, identifier=BONDS` (bull BONDS = price up = yields down). Rationale: bonds/yields sign confusion is a classic bug.
- **I6 (L) — Low-res image fallback:** if a chart JPEG is too compressed for confident level reads, return raw caption text only rather than fabricated levels.

---

## C. Constraints honored
- **Free/public data only** (Gemini free tier, yfinance, existing keys) — no new paid source proposed.
- **No fragile scraping / ToS issues** — Gmail API (authorized), image fetch from the newsletter's own CDN.
- **No redundancy** — every C-item maps to a Pass 0 gap; reuse existing LLM client, Gemini quota stack, A3 cluster skeleton, Alfred digest pattern, DB migration pattern, sector_map.

## D. Open technical risks to resolve in Pass 3
1. **Vision accuracy on real hand-annotated Wolf charts** — must do a LIVE probe (charts available at `/tmp/wolf_charts/`). This is the load-bearing feasibility question for the whole feature.
2. **SendGrid URL wrapping** — confirm chart `<img src>` are direct CDN URLs vs click-tracking-wrapped, against a REAL email.
3. **Quota under burst** — 5 emails landing at once × charts; 15 RPM cap; queue via rate limiter.
4. **Confluence scope-matching correctness** — market-call vs SPY-stance cross-counting rules; avoid double-counting.
