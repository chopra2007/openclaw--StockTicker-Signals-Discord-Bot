# Local-Windows Routines — Design (Stage 2/4)

**Date:** 2026-04-30  
**Author:** architect (stage 2 of 4)  
**Inputs:** `local-win-routines-discovery.md` (stage 1)  
**Output consumer:** planner (stage 3) — folds these designs into the final implementation plan  
**Scope:** READ-ONLY design. No code edits. No trading logic. Pure data ingestion + observability.

---

## 0. Cross-Cutting Decisions (apply to ALL routines)

### 0.1 Transport: Windows desktop → Linux engine

The Windows routines run on the operator's PC; the engine and `ticker_signals` table live on the Linux server. Discovery doc §"Architecture Overview" says all sources funnel through `db.insert_signal(TickerSignal)`. We therefore need a transport.

**Three candidate transports — recommendation in §0.2:**

| Transport | Latency | Auth | Reliability | Effort |
|---|---|---|---|---|
| (A) New HTTPS ingest endpoint on engine, POST `TickerSignal` JSON | <500ms | Bearer token in `/root/.openclaw/.env` | High; needs aiohttp.web route added to engine | Medium |
| (B) JSONL queue file dropped into a synced dir (Syncthing/SSHFS), engine tails it | 1–10s | Filesystem | Medium; ordering + partial-write hazards | Low |
| (C) Discord relay channel (TweetShift-style; new `#desktop-feed`), engine listener parses | 200–800ms (Gateway) | Already wired (Discord token) | High; reuses proven path | Low |

### 0.2 Recommended transport: (C) Discord relay channel

- The engine **already** has a working Discord Gateway listener (`scanners/discord_tweetshift.py`, discovery §3) — adding a parallel `DesktopFeedListener` for `#desktop-feed` reuses code, auth, retries, and the proven reconnect logic added 2026-04-19 (memory digest §"System Reliability Improvements").
- Each Windows routine posts a single-line JSON message via a self-bot in the operator's private server (or via webhook). The engine listener parses, validates, calls `db.insert_signal(...)`.
- **Why not (A):** adds new attack surface to the engine (publicly-reachable HTTP) and a new auth scheme.
- **Why not (B):** filesystem sync introduces ordering ambiguity and we already have a stuck-loop detection paradigm for Discord, none for file-tail.

**Open question for planner:** the message format under (C). Proposal:
```json
{"v":1,"src":"<routine_id>","ticker":"NVDA","source_type":"reddit","source_detail":"r/wallstreetbets|post:abc123","raw_text":"...","sentiment":"neutral","detected_at":1714521600.123}
```
The listener fills `expires_at` server-side via `TickerSignal.expires_at` (discovery §"Database Schema": `detected_at + 7200`).

### 0.3 SourceType enum gap — flagged as OPEN QUESTION

Discovery doc §"SourceType Enum" comment says "40+ total" but the actual `models.py:9–18` defines only **9 values**: `TWITTER, REDDIT, STOCKTWITS, APEWISDOM, GOOGLE_TRENDS, NEWS, SEC_FILING, YOUTUBE, VOLUME_BREAKOUT`. Discovery doc is overstated.

**Implication for design:** several proposed routines need NEW `SourceType` enum values (e.g. `SEEKING_ALPHA`, `BENZINGA`, `EMAIL`, `DISCORD_DM`, `CLIPBOARD`, `BOOKMARK`, `TRADINGVIEW`, `PODCAST`). The planner must decide whether to:
- (i) Add new enum values (requires touching `models.py`, `db.py` insert path, plus any `source_type IN (...)` queries — `db.py:783` uses an explicit list for `get_social_signals`),
- (ii) Reuse `NEWS` for SA/Benzinga and stuff routine identifier into `source_detail`, accepting loss of typed filtering.

**Architect recommendation:** option (i). The `source_type` column is the only typed query handle; squashing distinct sources into `NEWS` will pollute the news-cascade query path and break weighted scoring downstream.

### 0.4 Sentiment field — flagged as OPEN QUESTION

Discovery doc §"Default Assignment Rules" notes Reddit/StockTwits/ApeWisdom hardcode `NEUTRAL`. **No routine in this design infers sentiment.** All defaults to `Sentiment.NEUTRAL`. Two exceptions:
- **Seeking Alpha** analyst rating (`Buy`/`Sell`/`Hold`) is a *publisher-asserted* label, not inference — propose mapping `Buy→BULLISH, Sell→BEARISH, Hold→NEUTRAL`.
- **Benzinga** "Pro Movers" tags include a published direction arrow — same direct mapping where present.

Anything requiring tone analysis stays `NEUTRAL`. Planner should confirm this is acceptable for SA/Benzinga (the only divergence from "no sentiment models" rule).

### 0.5 Dedup strategy per routine

Discovery doc §"Summary: All Ingestion Paths" shows dedup is per-source: TTL-only for `ticker_signals`, `INSERT OR IGNORE` on `reddit_posts.id`, URL hash for news. Each routine below specifies its dedup strategy and whether a new sidecar table is needed.

### 0.6 Browser stack

All web-scraping routines use **Playwright + `playwright_stealth`** (already in repo per CLAUDE.md: `Stealth().apply_stealth_async(page)`). Each routine attaches to the operator's existing logged-in Chrome profile via `playwright.chromium.launch_persistent_context(user_data_dir="C:/Users/<u>/AppData/Local/Google/Chrome/User Data", channel="chrome")`. This carries cookies, soft-paywall whitelisting, and ad-block extensions transparently.

---

## ROUTINE 1 — Authenticated Multi-Source Extraction Engine

**Routine ID:** `R1_AUTHED_WEB`  
**Cadence:** Loop with per-target jitter. Reddit 7–11 min, SA 12–18 min, Benzinga 9–14 min (random uniform per cycle).  
**Runtime location:** Windows PC, persistent Playwright context.

### 1.1 Reddit target

**Seed list source:** Read from `consensus.yaml:114–127` `social.subreddits` array (discovery §"Reddit Scanner"). Currently:  
`wallstreetbets, stocks, investing, options, pennystocks`.  
The Windows routine reads the same key remotely (via SSH `cat` at startup, cached for the session) — single source of truth, no drift with the engine's own (disabled) Reddit scanner.

**Entry URLs:** `https://www.reddit.com/r/{sub}/new/?limit=100` (NEW tab, not HOT — analyst posts are time-sensitive).

**Browser actions per cycle per subreddit:**
1. `await page.goto(url, wait_until="domcontentloaded")` — 30s timeout.
2. Wait selector `[data-testid="post-container"]` (timeout 8s; if absent → `STOP_AND_LOG: layout_change`).
3. Scroll loop: `await page.mouse.wheel(0, random.randint(800,1400))` × 4–6 with `asyncio.sleep(random.uniform(0.7, 1.4))` between scrolls — picks up first ~120 posts.
4. For each `[data-testid="post-container"]`:
   - Title: `[slot="title"]` innerText
   - Author: `a[data-testid="post_author_link"]` innerText
   - Score: `[id^="vote-arrows"] + div` innerText (parse `1.2k`→1200)
   - Comment count: `a[data-click-id="comments"] span` innerText
   - Post ID: parse from `<faceplate-tracker source="post"><a href>` href → `/comments/{id}/...`
   - Body (if expandable): click `button[data-testid="post-content-expand"]` only if present, otherwise leave empty (avoid forced expansion that triggers anti-bot).
5. **No comment expansion in v1** — overhead too high. Defer to Routine 1.5 (deferred follow-up).

**Anti-bot behavior:**
- Random `mouse.move(x, y, steps=N)` where N=8–14, before each scroll (jitter).
- Per-page dwell: `asyncio.sleep(random.uniform(2.5, 5.0))` after scroll loop, before extraction.
- Tab close + `await context.new_page()` between subreddits (fresh referrer).
- User-Agent inherited from Chrome profile (no override).
- Hard cap: max 3 subreddits per minute regardless of cycle length.

**Soft-paywall:** N/A for Reddit. The persistent Chrome profile carries the operator's logged-in session, which automatically suppresses NSFW/age-gate modals and the "open in app" interstitial.

**Extraction → output schema** (cites discovery §"Database Schema"):

| TickerSignal field | Source | Concrete value example |
|---|---|---|
| `ticker` | `extract_tickers(title + " " + body)` (discovery §"Reddit Scanner" step 2) | `"NVDA"` |
| `source_type` | New enum value `REDDIT_AUTHED` *(or reuse `REDDIT` — see §0.3)* | `"reddit_authed"` |
| `source_detail` | `f"r/{sub}|post:{post_id}|u/{author}|score:{score}|comments:{n_comments}"` | `"r/wallstreetbets|post:1abc23|u/dfv|score:842|comments:1245"` |
| `raw_text` | `f"{title}\n\n{body}"` truncated to 2000 chars (discovery §"Database Schema": "capped 2000 chars at insert" — applied server-side by `db.py:710`) | full title + body |
| `sentiment` | Hardcoded `Sentiment.NEUTRAL` (matches discovery §"Default Assignment Rules") | `"neutral"` |
| `detected_at` | `time.time()` at extraction (NOT post creation time, to align with TTL window) | `1714521600.123` |
| `expires_at` | Server-side: `detected_at + 7200` (discovery §"Dedup & TTL Logic") | `1714528800.123` |

**Sidecar archive (mirrors existing pattern):** Push the same posts via the relay to also populate `reddit_posts` (discovery §"Secondary Social Detail Table"). Dedup via existing `INSERT OR IGNORE` on `reddit_posts.id` (discovery line 122). The Windows routine emits a second JSON line `{"v":1,"sink":"reddit_posts","id":"1abc23","subreddit":"wallstreetbets","title":"...","author":"...","score":842,"num_comments":1245,"created_utc":1714521000,"fetched_at":1714521600.123}`.

**Dedup within session:** maintain in-memory `set[post_id]` per cycle. Skip re-emission within 4 hours (post_id LRU of size 5000). Cross-source overlap (same ticker on Reddit + SA + Benzinga) is **expected** and desirable — TTL handles cross-source aggregation downstream.

**Failure modes & STOP_AND_LOG triggers:**
| Trigger | Detection | Action |
|---|---|---|
| Auth expired | `[href*="/login"]` visible OR HTTP 403 from `/r/.json` probe | Post `{"alert":"reddit_auth_expired"}` to `#system-alerts`; pause for 24h |
| CAPTCHA shown | Page contains `iframe[src*="recaptcha"]` OR `[id*="challenge"]` | Same |
| Layout change | Post-container selector missing 3 cycles in a row | Same |
| 429 / 503 | HTTP status from any sub | Exponential backoff 5min → 30min → cycle pause |
| Post body >2KB | text length check | Truncate, append `"...[TRUNCATED]"` (matches engine cap at `db.py:710`) |

### 1.2 Seeking Alpha target

**Seed list source:** OPEN QUESTION flagged. Two candidates:
- (A) Operator's SA "My Portfolio" page (`https://seekingalpha.com/account/portfolio`) — implicit watchlist.
- (B) Active tickers from `db.get_active_tickers()` (referenced in memory digest §"Model & Source Changes"; SerpAPI scanner pivoted away from this in Apr-16).

**Recommendation:** (A) — leverages the *desktop-only* premise (operator-curated SA portfolio). Limits scrape volume to ~20–40 tickers and avoids hammering SA with 500+ ticker pages.

**Entry URLs:**
1. `https://seekingalpha.com/account/portfolio` → extract ticker list (DOM: `[data-test-id="symbol-link"]`).
2. For each ticker (round-robin, ~3 per cycle): `https://seekingalpha.com/symbol/{TICKER}/analysis`.

**Browser actions per ticker:**
1. Goto, wait `[data-test-id="post-list"]` (timeout 8s).
2. Soft-scroll x2 to render lazy-loaded analyst cards.
3. For each `[data-test-id="post-list-item"]`:
   - Headline: `a[data-test-id="post-list-item-title"]` innerText + `href` (full URL).
   - Author: `a[data-test-id="post-list-item-author"]` innerText.
   - Rating: `[data-test-id="rating-display"]` aria-label (e.g. `"Buy"`, `"Strong Sell"`, `"Hold"`).
   - Published: `time` attribute `datetime` → ISO8601.
   - Article preview: first `p` after the headline (premium content gated; preview is ~200 chars).
4. **No full-article fetch in v1** — premium articles trip a hard paywall even with login. Headline + rating + preview is sufficient signal.

**Anti-bot:** same primitives as Reddit (mouse jitter, scroll pacing, per-tab dwell). SA fingerprints heavily — `playwright_stealth` MUST be applied. Hard cap: 4 ticker pages per minute.

**Soft-paywall handling:** Logged-in Chrome profile bypasses the metered wall. If `[data-test-id="paywall"]` appears, log to `#system-alerts` and skip ticker for the cycle.

**Output schema:**

| TickerSignal field | Source | Example |
|---|---|---|
| `ticker` | URL path `/symbol/{TICKER}/...` (already known per request) | `"AAPL"` |
| `source_type` | New `SEEKING_ALPHA` enum (preferred per §0.3) | `"seeking_alpha"` |
| `source_detail` | `f"sa|{author}|rating:{rating}|{article_url}"` | `"sa|JoeAnalyst|rating:Buy|https://seekingalpha.com/article/123"` |
| `raw_text` | `f"{headline}\n\n{preview}"` truncated 2000 (server-side) | combined |
| `sentiment` | Map `Buy→BULLISH, Strong Buy→BULLISH, Sell→BEARISH, Strong Sell→BEARISH, else→NEUTRAL` (§0.4) | `"bullish"` |
| `detected_at` | `time.time()` at extraction | now |
| `expires_at` | server-side `+7200` | +2h |

**Dedup key (OPEN QUESTION resolved by recommendation):** SHA1 of canonical `article_url` (strip query params, lowercase). Maintain a new sidecar table `external_articles_seen(url_hash TEXT PRIMARY KEY, source TEXT, first_seen REAL, ticker TEXT)` — mirrors the news-cascade URL-hash pattern (discovery §"Summary: All Ingestion Paths" → news row uses URL hash). Routine emits `INSERT OR IGNORE` via the relay; skip downstream signal emission if dedupe rejects.

**Failure modes:** auth expired (`a[href*="/account/login"]` visible), CAPTCHA, layout change, 429 — same STOP_AND_LOG pattern as 1.1.

### 1.3 Benzinga target

**Seed list source:** Same SA portfolio (assume operator's watchlist is consistent across sites). Cycle through tickers at 9–14 min jitter.

**Entry URLs:**
1. `https://www.benzinga.com/quote/{TICKER}` — ticker page with news + Pro signals.
2. `https://www.benzinga.com/movers/large-cap` — daily top movers (low refresh, once per cycle).

**Browser actions per ticker:**
1. Goto + wait `[data-cy="news-feed"]`.
2. For each `article` element:
   - Headline: `h3` innerText.
   - URL: `a` href → absolute.
   - Source: small text (`[data-cy="source"]`) — "Benzinga", "PR Newswire", "Reuters".
   - Timestamp: `time` element → ISO.
   - Pro tag (if any): `[class*="pro-tag"]` innerText (e.g. "Movers", "Options Activity").

**Anti-bot:** Benzinga is less aggressive than SA. Same primitives, slightly relaxed jitter (1.5–3s page dwell).

**Soft-paywall:** Benzinga Pro content is gated — logged-in profile assumed. If Pro tag present but body redacted (`[class*="pro-paywall"]`), capture headline+source only.

**Output schema:**

| TickerSignal field | Source | Example |
|---|---|---|
| `ticker` | URL path or extracted from headline via `extract_tickers` | `"TSLA"` |
| `source_type` | New `BENZINGA` enum | `"benzinga"` |
| `source_detail` | `f"benzinga|{source_label}|{pro_tag or '-'}|{article_url}"` | `"benzinga|Reuters|Options Activity|https://..."` |
| `raw_text` | `headline` truncated 2000 | headline string |
| `sentiment` | If `pro_tag in {"Movers Up","Bullish Options"}→BULLISH`, `{"Movers Down","Bearish Options"}→BEARISH`, else `NEUTRAL` | per-tag |
| `detected_at` | now | now |
| `expires_at` | +7200 server-side | +2h |

**Dedup key:** Same `external_articles_seen` URL-hash table as SA (cross-source dedup if SA + Benzinga publish identical syndicated wire stories — desirable).

**Failure modes:** identical to 1.1/1.2.

### 1.4 Cross-target session controls

- Single Playwright `BrowserContext` per process (cookies shared across tabs). One tab per target, never >3 tabs open.
- A heartbeat row to a new `routine_health` table every 60s with `routine_id="R1_AUTHED_WEB", last_cycle_started, last_success_target, errors_in_cycle`. Surfaces in Routine 3 gap-detection.
- Reconnect counter pattern (memory digest §"System Reliability Improvements"): >5 consecutive cycle failures → emit `{"alert":"R1_STUCK"}` to `#system-alerts`.

---

## ROUTINE 2 — Local Intelligence Ingestion Engine

**Routine ID:** `R2_LOCAL_INTEL`  
**Runtime:** Windows PC. Two sub-routines (Email + Discord) running as separate Python processes under a single supervisor (the supervisor is the planner's call).

### 2.1 Email — recommended path: **Outlook desktop COM via `pywin32`**

**Path comparison:**

| Path | Pros | Cons | Recommended |
|---|---|---|---|
| Outlook desktop COM (`win32com.client.Dispatch("Outlook.Application")`) | Reads from already-open Outlook session; no creds needed; Exchange/IMAP/POP all unified; supports rules, folders, categories | Requires Outlook running; Windows-only (acceptable here) | **YES** |
| IMAP via `imaplib` against Gmail/Exchange | Cross-platform; runs headless | Requires app password (Gmail blocks raw passwords); needs OAuth refresh dance for Exchange; cred storage burden | No |
| Thunderbird `.msf` parsing | Free | Brittle parser, no incremental delta, file locks while TB is open | No |
| Browser-based Gmail scrape | Works for Gmail only | Slow, fragile, paywall-style anti-bot | No |
| `.eml` / `.pst` file scrape | Works offline | No incremental delivery; PST is opaque without COM anyway | No |

**Outlook COM flow (per cycle, every 60s):**
1. `outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")`
2. `inbox = outlook.GetDefaultFolder(6)` (Inbox)
3. Filter for unread items received since last cycle: `inbox.Items.Restrict("[Unread]=true AND [ReceivedTime]>'<last_cycle_iso>'")`
4. For each item:
   - **Sender allowlist check** — see §2.3 for source.
   - Subject + Body (plain text via `.Body`, NOT HTMLBody to dodge tracker pixels).
   - Extract tickers via `extract_tickers(subject + " " + body[:5000])` (utility lives at `consensus_engine/utils/tickers.py:86`, ported to Windows side as a copy or fetched via SSH/HTTP at startup).
5. Mark item **Read** ONLY after successful relay ack — avoids data loss on crash.
6. **No interpretation** — no "this looks bullish" inference. Pure ticker extraction.

**Output schema (per ticker per email):**

| TickerSignal field | Source | Example |
|---|---|---|
| `ticker` | `extract_tickers()` output | `"MU"` |
| `source_type` | New `EMAIL` enum | `"email"` |
| `source_detail` | `f"email|from:{sender_addr}|subj:{subject[:80]}"` | `"email|from:alerts@analyst.com|subj:MU 4/24 calls hitting"` |
| `raw_text` | `f"{subject}\n\n{body}"` truncated 2000 | combined |
| `sentiment` | `Sentiment.NEUTRAL` (no inference per §0.4) | `"neutral"` |
| `detected_at` | item.ReceivedTime → Unix ts | per-email |
| `expires_at` | server-side +7200 | +2h |

**Dedup key:** `(EntryID, ticker)` tuple stored in routine-local SQLite (`win_routines.db`). Outlook EntryID is stable per item. Sidecar table on engine side optional — if planner wants cross-routine searchability: `email_signals(entry_id TEXT, ticker TEXT, subject TEXT, sender TEXT, received_at REAL, PRIMARY KEY(entry_id, ticker))`.

**Failure modes:**
| Trigger | Detection | Action |
|---|---|---|
| Outlook not running | COM dispatch raises `pywintypes.com_error` | Auto-launch Outlook; if 3 launches fail → `#system-alerts` |
| Restrict syntax break (Outlook version bump) | Empty result + items visible in UI | Fall back to full-folder scan with manual time filter |
| Massive backlog (>500 unread) | item count > threshold | Process in 50-item batches, alert if backlog >2h old |

### 2.2 Discord — three-path comparison and recommendation

**Path comparison (spec asked for this explicitly):**

| Path | How it works | ToS risk | Reach | Reliability | Verdict |
|---|---|---|---|---|---|
| **(a) User-token automation** (`discord.py-self`, raw Gateway with user token) | Connects to Discord Gateway as user; reads ALL channels + DMs in real time | **HIGH — explicit ToS violation; account ban risk; Discord actively detects self-bots** | Full (every server user is in, every DM) | High when undetected, ZERO when banned | **Reject** |
| **(b) UI automation of Discord desktop app** (`pywinauto` + accessibility tree, fallback OCR) | Reads on-screen content from Discord Electron app | None | Whatever's currently visible to user; can scroll programmatically | Medium — fragile to Discord UI redesigns; requires app foreground or accessibility-tree polling | **Acceptable for read-only of arbitrary servers/DMs** |
| **(c) Bot-relay** (operator-controlled bot in their own server, invited to channels they admin) | Standard Discord Bot API; same as TweetShift | None | ONLY channels the bot is invited to; **CANNOT read DMs sent to user; CANNOT read external servers** | High — proven by TweetShift integration (memory: `project_tweetshift.md`) | **Best for channels operator controls** |

**Recommendation: hybrid.**
- **Primary path = (c) Bot-relay** for any server the operator admins or can invite a bot to. Reuses the engine's existing Discord Gateway code (discovery §"Discord Gateway Listener (TweetShift)") — just add a new listener for a new channel ID `discord_local_intel_channel_id`. The "local intel" Discord bot lives on the engine, not Windows; the operator invites it to their watch-channels.
- **Secondary path = (b) UI automation** ONLY for DMs and external servers the operator can't add a bot to. Polled at 30s intervals via Discord desktop accessibility tree (`pywinauto.Application(backend="uia").connect(title_re="Discord")` then walk the message-list element). Slower, fragile, but ToS-safe.
- **(a) User-token: explicitly forbidden.** Document in plan as a tempting shortcut to NOT take.

**Bot-relay flow (path c):**
1. Engine-side new listener `DiscordLocalIntelListener` mirrors `DiscordTweetShiftListener` structure.
2. For each message in allowlisted channels:
   - Apply sender allowlist (see §2.3).
   - Extract tickers from `message.content`.
   - Call `db.insert_signal(TickerSignal(...))` directly — same path as TweetShift.

**UI-automation flow (path b, secondary):**
1. Windows process polls Discord app every 30s.
2. For configured DM/external channels: scroll to active conversation, read latest 20 messages from `[ListItem]` accessibility nodes.
3. Maintain seen-message set keyed on `(channel_name, sender, timestamp_displayed, first_40_chars)` (Discord's UI doesn't expose message_id — this is the dedup compromise).
4. Emit via Discord relay channel (§0.2) just like other Windows routines.

**Output schema:**

| TickerSignal field | Source | Example |
|---|---|---|
| `ticker` | `extract_tickers(message_text)` | `"SPX"` |
| `source_type` | New `DISCORD_DM` enum (or reuse TweetShift's `TWITTER` if it's a tweet relay — distinguish via `source_detail`) | `"discord_dm"` |
| `source_detail` | `f"discord|{channel}|user:{author}|via:{path}"` where `path∈{bot,ui}` | `"discord|alerts-server#options|user:Trader1|via:bot"` |
| `raw_text` | message content truncated 2000 | text |
| `sentiment` | `NEUTRAL` (no inference) | `"neutral"` |
| `detected_at` | message timestamp (path c: `message.created_at.timestamp()`; path b: `time.time()` since UI doesn't give precise ts) | unix ts |
| `expires_at` | server-side +7200 | +2h |

**Dedup:**
- Path c: Discord `message.id` → routine-local `seen_discord(message_id PRIMARY KEY, ts REAL)` with 24h sweep.
- Path b: composite key per above; same table with `message_id` synthesized as `sha1(channel|sender|ts|first40)`.

**Failure modes:**
| Trigger | Detection | Action |
|---|---|---|
| Bot disconnect | Gateway close event | Reconnect with backoff (reuse engine reconnect-counter pattern from memory digest) |
| UI app closed (path b) | `connect()` raises `ElementNotFoundError` | Auto-launch Discord; if 3 fails → `#system-alerts` |
| Discord UI redesign (path b) | Accessibility-tree walk returns empty for >5 cycles | Pause path b, fall back to path c only, alert |

### 2.3 Sender/channel allowlist source

**Single source of truth:** new file `/root/.openclaw/local_intel_allowlist.json`:
```json
{
  "email_senders": ["alerts@analyst1.com", "*@premiumstocks.io"],
  "email_subjects_must_contain": ["alert", "trade", "trigger", "$"],
  "discord_bot_channels": ["1234567890"],
  "discord_ui_channels": [{"server":"FriendsServer","channel":"options-alerts"}]
}
```
Mirrors the `sources.json` pattern (discovery §"YouTube Scanner": "Channels list: `/root/.openclaw/sources.json`"). Operator edits one file.

---

## ROUTINE 3 — Observability + Gap Detection Engine

**Routine ID:** `R3_GAP_DETECT`  
**Cadence:** Every 5 min during market hours (9:30–16:00 ET); hourly otherwise.  
**Runtime:** Engine-side (no Windows component required) — but classified here because it ties together the new Windows ingestion sources to surface coverage gaps.

### 3.1 "Top movers" source

Discovery doc identifies two existing options:
- **Finnhub `/quote`** — real-time price only, no ranked-mover endpoint on free tier (CLAUDE.md §"Key Design Decisions": "Finnhub free tier: real-time quotes only").
- **`yfinance`** in `ThreadPoolExecutor` — used for historical OHLCV (CLAUDE.md same section); provides `Ticker.info` and screener-like data.

**Recommendation:** use the Finnhub-quote loop the volume scanner already runs (`scanners/volume_scanner.py:99` `_fetch_quote`) as the *raw price feed*, then derive movers via:
```
mover_pct = (current_price - prev_close) / prev_close
```
Top-30 absolute % movers among S&P 500 + watchlist tickers (operator's SA portfolio cached from Routine 1).

**No new external API call.** Reuse `volume_scanner._fetch_quote` and add a thin `get_top_movers(n=30)` helper alongside `scan_volume_breakouts` (no edits made by architect — flagged for planner/executor).

**Open question for planner:** does the operator have a paid Finnhub tier that exposes `/stock/market-mover`? If yes, prefer that single call to N quote calls.

### 3.2 Cross-reference query

For each ticker in top-movers list, query `ticker_signals` for the last N hours (default N=4, configurable):

```sql
SELECT source_type, source_detail, MIN(detected_at) AS first_seen, MAX(detected_at) AS last_seen, COUNT(*) AS hits
FROM ticker_signals
WHERE ticker = ? AND detected_at >= ?
GROUP BY source_type, source_detail
ORDER BY first_seen ASC
```

**Cites:** schema fields `ticker`, `source_type`, `source_detail`, `detected_at` (discovery §"Database Schema"). The `ORDER BY first_seen ASC` reveals which source caught the ticker first — the headline metric.

### 3.3 Output: missed-opportunity report

**Report row schema:**

| Field | Type | Source |
|---|---|---|
| `ticker` | TEXT | from movers list |
| `mover_pct` | REAL | (current - prev_close) / prev_close |
| `current_price` | REAL | Finnhub `/quote` `c` |
| `prev_close` | REAL | Finnhub `/quote` `pc` |
| `first_source` | TEXT | smallest `first_seen` row's `source_type` (NULL = MISSED) |
| `first_source_detail` | TEXT | matching `source_detail` |
| `first_seen_at` | REAL | `MIN(detected_at)` |
| `detection_delay_sec` | REAL | mover_detected_at − first_seen_at; positive = good (we saw it before move), negative = caught late |
| `total_signals` | INTEGER | `COUNT(*)` across all sources |
| `sources_hit` | TEXT | comma-joined distinct `source_type` |
| `report_generated_at` | REAL | `time.time()` |
| `status` | TEXT | enum `MISSED` / `LATE` / `CAUGHT` (rules below) |

**Status rules:**
- `CAUGHT`: detection_delay_sec ≥ 600 (we saw it ≥10min before the move)
- `LATE`: 0 ≤ detection_delay_sec < 600
- `MISSED`: no rows in `ticker_signals` for ticker in window

### 3.4 Where the report goes

Spec asked: Discord channel? file drop? DB table for morning briefing?

**All three, layered:**
1. **DB table `gap_reports`** (new, persistent) — primary store; powers historical analysis.
2. **Discord** — only for `MISSED` status with `mover_pct ≥ 5%`; posts to a new `#gap-alerts` channel (config key `alerts.discord_gap_channel_id`, ENV `$DISCORD_GAP_CHANNEL_ID`). Quiet by design — no spam on `LATE`/`CAUGHT`.
3. **Alfred briefing prepend** — the morning Alfred briefing (discovery §"Background Watchers", `briefing/alfred.py`) already calls `db.get_top_tickers_session`. Add a new section "Yesterday's Gaps" sourced from `gap_reports WHERE status='MISSED' AND report_generated_at >= session_start`. Alfred already fetches data via `build_briefing_data` (alfred.py:19); the planner adds one query.

### 3.5 Failure modes

| Trigger | Action |
|---|---|
| Finnhub `/quote` 429 | Backoff to 60s/ticker; alert if persistent >10min |
| `gap_reports` write fails | Log, skip, retry next cycle |
| No movers returned (market closed) | Quiet skip; don't post empty report |
| Alfred briefing time-of-day check fails | Inherit existing alfred guard at `alfred.py:283` `_in_post_window` |

---

## ADDITIONAL DESKTOP-ONLY ROUTINES

Per spec, propose 2–4 more. Four below, ranked by signal/effort.

### ROUTINE 4 — Clipboard Sentinel (`R4_CLIPBOARD`)

**Why desktop-only:** clipboard is per-user OS state, invisible to a server.

**Premise:** when the operator copies a ticker (`$NVDA`, `NVDA`) from any source — broker UI, news article, screen-capture OCR, chart — that's an attention signal. Free, frictionless, captures attention happening BEFORE the operator types into a ticker box.

**Flow:**
1. Background `pywin32` clipboard watcher (`win32clipboard.OpenClipboard()` polled every 2s; or use `pywin32` clipboard-changed window message for zero-poll).
2. On change, take text content, run `extract_tickers()`.
3. If 1–3 tickers extracted (more = probably a list paste; ignore noise), emit signal.

**Output schema:**

| TickerSignal field | Value |
|---|---|
| `ticker` | extracted |
| `source_type` | new `CLIPBOARD` enum |
| `source_detail` | `f"clipboard|app:{foreground_window_title[:60]}"` (gives WHERE the copy came from) |
| `raw_text` | clipboard content truncated 2000 |
| `sentiment` | `NEUTRAL` |
| `detected_at` | `time.time()` |

**Dedup:** in-memory set with 5-min TTL — same ticker copy within 5min is one signal. No persistence needed.

**Failure modes:** clipboard contains binary (image) → catch `TypeError` and skip. Clipboard locked by another app → 50ms retry.

**Risk callout:** privacy. Clipboard captures EVERYTHING the operator copies. The routine should:
- Hard reject anything matching credit-card, SSN, password-pattern regexes.
- Operator-configurable allowlist of foreground app titles (e.g., only fire when foreground is Chrome/Edge/Outlook/Discord; skip when foreground is `1Password`/`Bitwarden`/`KeePass`).
- Never log full raw_text locally if any blacklisted pattern matched.

### ROUTINE 5 — TradingView Watchlist Mirror (`R5_TV_WATCHLIST`)

**Why desktop-only:** TradingView desktop app stores watchlist locally; no public API for personal watchlists.

**Premise:** keep the engine's "active tickers" concept synced to the operator's TradingView watchlist — single canonical watchlist. Today the engine uses `db.get_active_tickers()` (memory digest §"Model & Source Changes"); this routine becomes a *writer* into that table.

**Flow:**
1. Read TradingView desktop app config: `%APPDATA%/TradingView/Local Storage/leveldb/` (the watchlist is in the leveldb store).
2. Alternative if leveldb access flaky: scrape via Playwright at `https://www.tradingview.com/watchlists/` (operator logged in).
3. Dedup against last-known watchlist (stored in `win_routines.db`); compute add/remove diff per cycle (15 min).
4. Emit a single status signal per cycle: `{"sink":"active_tickers","tickers":["NVDA","AAPL",...],"source":"tradingview"}`.

**Output:** does NOT emit `TickerSignal` (it's a roster, not a signal). Lands in a new sidecar `tracked_tickers(ticker TEXT PRIMARY KEY, source TEXT, added_at REAL, removed_at REAL NULL)`.

**Dedup:** primary key on ticker; UPDATE on removal only.

**Failure modes:** leveldb format change → fallback to Playwright. TradingView session expired → `#system-alerts`.

### ROUTINE 6 — Browser Bookmark Sentinel (`R6_BOOKMARK`)

**Why desktop-only:** Chrome bookmark file is local; no cloud API.

**Premise:** operator drops articles into a Chrome folder named "Watchlist Add" while researching; this routine treats each new bookmark as a high-trust signal (operator manually selected it).

**Flow:**
1. Watch `%LOCALAPPDATA%\Google\Chrome\User Data\Default\Bookmarks` (JSON file) for mtime change.
2. Parse JSON, find folder with name `"Watchlist Add"`, list children.
3. Diff against last-known set (in `win_routines.db`).
4. For each new bookmark:
   - Fetch URL via aiohttp (no JS render needed for headlines).
   - Parse `<title>` and `<meta property="og:description">`.
   - `extract_tickers(title + " " + description)`.

**Output schema:**

| TickerSignal field | Value |
|---|---|
| `ticker` | extracted |
| `source_type` | new `BOOKMARK` enum |
| `source_detail` | `f"bookmark|{domain}|{url}"` |
| `raw_text` | `f"{title}\n{description}"` truncated 2000 |
| `sentiment` | `BULLISH` (operator-curated implies attention; this is the one routine where the OPERATOR'S act of bookmarking is the assertion — not text analysis) — **flag for planner**: is this acceptable as a publisher-asserted label? |
| `detected_at` | bookmark `date_added` from JSON |

**Dedup:** bookmark `id` field from Chrome JSON.

**Failure modes:** JSON parse error → skip cycle. URL fetch 4xx → log, continue with title-only signal.

### ROUTINE 7 — System-Audio Podcast Capture (`R7_AUDIO`) — *highest effort, defer to v2*

**Why desktop-only:** captures system audio (Bloomberg radio, market podcasts, Real Vision streams playing on the operator's PC).

**Flow sketch:**
1. WASAPI loopback capture via `soundcard` Python lib → 30s rolling buffer.
2. On voice-activity end, push buffer to local `whisper.cpp` (CPU-mode) for transcription.
3. `extract_tickers(transcript)`; emit signal per ticker mentioned.

**Output schema:** `source_type=PODCAST` (new enum), `source_detail=f"podcast|app:{foreground_window_title}|t+{relative_seconds}s"`, `raw_text=transcript_chunk`, `sentiment=NEUTRAL`.

**Effort:** high. Whisper.cpp setup, audio device permission dance, GPU optional. **Recommend: defer past v1 cut.** Listed for completeness; planner may scope it out.

**Risk callout:** unlike Routines 4–6, audio capture is continuous and bandwidth-heavy; whisper inference can spike CPU. Deserves its own resource-limit gate and on/off toggle.

---

## Cross-Routine Summary Matrix

| Routine | Source | New `SourceType` | New table | Dedup | Cadence | Effort |
|---|---|---|---|---|---|---|
| R1 Reddit-authed | reddit.com | `REDDIT_AUTHED` (or reuse `REDDIT`) | reuse `reddit_posts` | post_id (existing) | 7–11min | M |
| R1 SA | seekingalpha.com | `SEEKING_ALPHA` | `external_articles_seen` | URL hash | 12–18min | M |
| R1 Benzinga | benzinga.com | `BENZINGA` | reuse `external_articles_seen` | URL hash | 9–14min | M |
| R2 Email | Outlook COM | `EMAIL` | `email_signals` (optional) | EntryID | 60s | L |
| R2 Discord (bot) | Discord Bot API | `DISCORD_DM` | reuse `seen_discord` | message_id | event-driven | L |
| R2 Discord (UI) | Discord desktop | same | same | composite hash | 30s | M |
| R3 Gap-detect | Finnhub + DB | n/a (writes report) | `gap_reports` | (ticker, day) | 5min mkt-hrs | L |
| R4 Clipboard | OS clipboard | `CLIPBOARD` | none | in-mem 5min | event-driven | S |
| R5 TradingView | TV leveldb | n/a (roster) | `tracked_tickers` | ticker pkey | 15min | M |
| R6 Bookmark | Chrome JSON | `BOOKMARK` | none | bookmark_id | mtime-driven | S |
| R7 Audio | WASAPI loopback | `PODCAST` | none | n/a | continuous | H (defer) |

---

## OPEN QUESTIONS for planner (consolidated)

1. **§0.3 SourceType enum extension vs reuse** — add 7 new enum values to `models.py` and update `db.py:783` `get_social_signals` source_type list, OR squash into existing enums via `source_detail` discriminator? Architect recommends the former.
2. **§0.4 SA/Benzinga publisher-asserted sentiment** — confirm `Buy/Sell` rating mapping is acceptable (technically not "sentiment inference" but a published label).
3. **§0.5 SA/Benzinga dedup key** — discovery flagged this; architect recommends URL hash via new `external_articles_seen` table.
4. **§1.2 SA seed list** — operator's SA portfolio (recommended) vs `db.get_active_tickers()`?
5. **§3.1 Finnhub tier** — does operator have access to `/stock/market-mover` (paid)? If yes, replace N quote calls with one.
6. **§6 Bookmark sentiment** — is `BULLISH` justified by operator's act of bookmarking, or default to `NEUTRAL`?
7. **§0.2 Transport** — confirm Discord-relay (recommended) vs HTTPS endpoint vs file-sync. Affects engine surface area.
8. **R7 audio routine in v1 or v2** — architect recommends v2 due to effort.

---

## References (file:line)

- `consensus_engine/models.py:9–18` — `SourceType` enum (9 values, NOT 40+)
- `consensus_engine/models.py:27–40` — `TickerSignal` dataclass + `expires_at` property (`+7200`)
- `consensus_engine/db.py:700–741` — `insert_signal()` with TWITTER routing into `signal_events`
- `consensus_engine/db.py:710` — server-side raw_text 2000-char truncation
- `consensus_engine/db.py:744–759` — `insert_signals()` batch path
- `consensus_engine/db.py:783` — explicit `source_type IN (...)` list (must be updated if new enums added)
- `consensus_engine/utils/tickers.py:86–112` — `extract_tickers()` (used by all routines for ticker discovery)
- `consensus_engine/utils/tickers.py:83` — `_TICKER_PATTERN` regex
- `consensus_engine/scanners/social.py:46–70` — Reddit reference scanner pattern (engine-side mirror to R1.1)
- `consensus_engine/scanners/news.py:1–80` — news-cascade pattern; URL-hash dedup precedent for R1.2/R1.3
- `consensus_engine/scanners/discord_tweetshift.py` — bot-relay precedent for R2.2 path (c)
- `consensus_engine/scanners/volume_scanner.py:99` — `_fetch_quote` reuse target for R3.1
- `consensus_engine/briefing/alfred.py:19` — `build_briefing_data` extension point for R3.4
- `consensus_engine/briefing/alfred.py:283` — `_in_post_window` time-of-day guard
- `config/consensus.yaml:114–127` — `social.subreddits` list (R1.1 seed source)
- `config/consensus.yaml:142–143` — `news.trusted_sources` (where SA/Benzinga were referenced but never scanned)
- `consensus_engine/main.py:130–183` — `fetch_signals` poll-loop entry point
- `consensus_engine/main.py:226–291` — Form 4 watcher loop (pattern for any new engine-side loops)
- `/root/.openclaw/sources.json` — config-file precedent for the new `local_intel_allowlist.json` (§2.3)
- discovery doc §"Summary: All Ingestion Paths" — full per-source ingestion matrix
- discovery doc §"Seekingalpha & Benzinga: OPEN QUESTIONS" — origin of dedup-key OPEN QUESTION (now answered in §1.2/1.3)

---

**End of design document.** Planner (stage 3) — fold these into a sequenced execution plan, resolve the 8 open questions above, and write the final plan file. Critic (stage 4) will then adversarially review.
