# Local-Windows Routines — Final Execution Plan

**Date:** 2026-04-30
**Stage:** 3/4 (Plan) — feeds critic (stage 4)
**Authors:** planner, synthesizing explorer (#1) + architect (#2)
**Inputs:**
- `/root/.openclaw/workspace/.omc/plans/local-win-routines-discovery.md`
- `/root/.openclaw/workspace/.omc/plans/local-win-routines-designs.md`
**Scope:** Pure data ingestion + observability. NO changes to trading logic, sentiment scoring, or alert decisioning.

---

## Hard Constraints (enforced throughout)

1. **15 runs/week cap on R1 (web scraping).** ≤ 3 runs/weekday Mon–Fri, 0 runs Sat/Sun. Gate enforced both client-side (per-routine counter persisted in `win_routines.db`) and server-side (relay listener rejects R1 messages over quota). See §3.4 for the explicit schedule.
2. **Stop-and-log on every failure.** No silent continuation, no swallow-and-retry-forever. Every failure path posts to `#system-alerts` AND increments `routine_health.errors_in_cycle`. After 3 consecutive cycle failures the routine pauses itself for 24h.
3. **Output conforms EXACTLY to OpenClaw ingestion path.** Every signal lands via `db.insert_signal(TickerSignal)` at `consensus_engine/db.py:700`. The Windows side never writes to the engine DB directly — it emits a Discord-relay JSON payload (§3.6) which the new `DesktopFeedListener` validates and forwards into `db.insert_signal(...)` server-side. Wire-format and SQL inline below.
4. **NO trading logic, sentiment scoring, or alert decisioning changes.** New `SourceType` enum values are pure routing tags. Sentiment defaults to `Sentiment.NEUTRAL`; the only non-neutral assignments are *publisher-asserted labels* (Seeking Alpha "Buy"/"Sell" rating, Benzinga "Movers Up"/"Movers Down" tag) — these are pass-throughs, not inferences. Bookmark routine downgraded to `NEUTRAL` per §2.E open-question resolution.

---

## 1. System Discovery Findings

Pulled from `local-win-routines-discovery.md`. All paths are absolute.

### 1.1 The single ingestion choke point

Every signal source — ApeWisdom, Reddit, SEC Form 4, YouTube, TweetShift Discord — funnels through ONE function:

```python
# consensus_engine/db.py:700
async def insert_signal(signal: TickerSignal):
    db = await get_db()
    await db.execute(
        """INSERT INTO ticker_signals (ticker, source_type, source_detail, raw_text,
                                       sentiment, detected_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (signal.ticker, signal.source_type.value, signal.source_detail,
         signal.raw_text[:2000],          # server-side 2000-char truncation
         signal.sentiment.value, signal.detected_at, signal.expires_at),
    )
    if signal.source_type == SourceType.TWITTER:
        # Routes into signal_events for cross_reference scoring (db.py:716–740).
        ...
    await db.commit()
```

**Implications all routines must respect:**
- `raw_text` is truncated to 2000 chars *server-side*; Windows clients should still pre-truncate to keep relay payloads small.
- `expires_at` is `detected_at + 7200` (2h TTL) — this is the implicit dedup mechanism for `ticker_signals` (no UNIQUE constraint).
- New routines append additional rows but NEVER replace this insert path.

### 1.2 SourceType enum — actual contents

`consensus_engine/models.py:9–18` defines exactly **9 values** (NOT "40+" as discovery doc summary line said — that was overstated):

```python
class SourceType(str, Enum):
    TWITTER = "twitter"
    REDDIT = "reddit"
    STOCKTWITS = "stocktwits"
    APEWISDOM = "apewisdom"
    GOOGLE_TRENDS = "google_trends"
    NEWS = "news"
    SEC_FILING = "sec_filing"
    YOUTUBE = "youtube"
    VOLUME_BREAKOUT = "volume_breakout"
```

This plan adds **7 new values** (resolution to OQ-1, §4).

### 1.3 Sidecar tables this plan touches

| Table | Purpose | Owner |
|---|---|---|
| `ticker_signals` | primary signal store (existing) | `db.insert_signal` |
| `reddit_posts` | per-post archive (existing, `INSERT OR IGNORE` on `id`) | `db.insert_reddit_posts` |
| `external_articles_seen` | **NEW** — URL-hash dedup for SA + Benzinga (mirrors news-cascade pattern) | this plan |
| `email_signals` | **NEW (optional)** — Outlook-side searchability | this plan |
| `seen_discord` | **NEW** — message_id dedup for R2 Discord paths | this plan |
| `tracked_tickers` | **NEW** — TradingView watchlist mirror (R5; deferred — see §3.5) | this plan |
| `gap_reports` | **NEW** — R3 missed-opportunity store | this plan |
| `routine_health` | **NEW** — heartbeat/error counters surfacing in R3 | this plan |

### 1.4 The `get_social_signals` query — explicit IN list at `db.py:783`

```sql
SELECT source_type, source_detail, raw_text, sentiment, detected_at
FROM ticker_signals
WHERE ticker = ?
  AND source_type IN ('reddit', 'stocktwits', 'apewisdom', 'google_trends')
  AND detected_at >= ?
ORDER BY detected_at DESC
```

This explicit list **must** be expanded to include the new `reddit_authed`, `seeking_alpha`, `benzinga` values when those routines ship — otherwise authed-Reddit + SA + Benzinga signals will be invisible to social cross-reference scoring. Tracked as Phase-0 prerequisite in §4.

### 1.5 Existing transport pattern: `DiscordTweetShiftListener`

`consensus_engine/scanners/discord_tweetshift.py:133` defines a Discord Gateway listener for the `#twitter` channel that:
- Connects via the engine's existing Discord bot token.
- Parses TweetShift-relayed embeds.
- Calls `db.insert_signal(TickerSignal(...))`.
- Has the reconnect-counter / stuck-loop detection added 2026-04-19 (memory digest §"System Reliability Improvements").

**This is the exact pattern reused for the new `DesktopFeedListener` (§3.6).** Same auth, same retry semantics, same stuck-loop alarms — zero new attack surface.

### 1.6 Reference patterns this plan reuses

| Pattern | File | Reused for |
|---|---|---|
| Reddit ticker extraction | `consensus_engine/scanners/social.py:46–103` | R1.1 Reddit-authed |
| News URL-hash dedup | `consensus_engine/scanners/news.py:1–80` | `external_articles_seen` (R1.2/1.3) |
| Form-4 watcher loop shape | `consensus_engine/main.py:226–291` | new server-side loops (R3) |
| Volume-scanner quote helper | `consensus_engine/scanners/volume_scanner.py:99` | R3 top-movers |
| Alfred briefing data builder | `consensus_engine/briefing/alfred.py:19, 283` | R3 morning-briefing extension |
| `extract_tickers()` | `consensus_engine/utils/tickers.py:86–112` | every routine |

---

## 2. Refined Routine Designs

Three primary routines (R1, R2, R3) plus the recommended top-2 desktop-only additions (R4, R6). R5 deferred to v2; R7 (audio capture) deferred to v2 per architect recommendation.

### 2.A R1 — Authenticated Multi-Source Web (`R1_AUTHED_WEB`)

**Runtime:** Windows PC, persistent Playwright + `playwright_stealth` Chrome profile.
**Quota:** **15 runs/week** total (the operator's hard cap). 3 runs/weekday Mon–Fri (premarket / midday / power-hour). 0 runs Sat/Sun.
**Per-run targets:** 5 subreddits + 3 SA tickers + 3 Benzinga tickers. Wall-clock ≤ 6 min/run.

**Sub-target 1.A.i — Reddit (authenticated)**
- Read seed list from `config/consensus.yaml:114–127` `social.subreddits` (cached at startup over SSH; single source of truth shared with the disabled engine-side scanner).
- Per subreddit: `https://www.reddit.com/r/{sub}/new/?limit=100`, scroll loop, extract from `[data-testid="post-container"]`.
- Anti-bot: mouse jitter, randomized scroll, 2.5–5.0s dwell, fresh tab per subreddit.
- Hard cap: 3 subs/min within a run.
- Output → `TickerSignal(source_type=REDDIT_AUTHED, source_detail="r/{sub}|post:{id}|u/{author}|score:{n}|comments:{n}", sentiment=NEUTRAL)`.
- Sidecar: also emit a `reddit_posts` archive row using existing `INSERT OR IGNORE` on `id`.

**Sub-target 1.A.ii — Seeking Alpha**
- Seed = operator's SA "My Portfolio" page (resolution to OQ-4: scope-bounded, ~20–40 tickers; avoids 500+ ticker hammer-scrape).
- Per ticker: `https://seekingalpha.com/symbol/{TICKER}/analysis` → headline, author, rating, preview.
- Output → `TickerSignal(source_type=SEEKING_ALPHA, source_detail="sa|{author}|rating:{r}|{url}", sentiment=map(rating))`.
- Rating map (publisher-asserted, not inferred): `Strong Buy/Buy → BULLISH`, `Strong Sell/Sell → BEARISH`, `Hold/none → NEUTRAL`.
- Dedup: SHA1 of canonical URL into `external_articles_seen`.

**Sub-target 1.A.iii — Benzinga**
- Per ticker: `https://www.benzinga.com/quote/{TICKER}` (news feed) + once-per-run `https://www.benzinga.com/movers/large-cap`.
- Output → `TickerSignal(source_type=BENZINGA, source_detail="benzinga|{src}|{pro_tag}|{url}", sentiment=map(pro_tag))`.
- Pro-tag map (publisher-asserted): `Movers Up / Bullish Options → BULLISH`, `Movers Down / Bearish Options → BEARISH`, else `NEUTRAL`.
- Dedup: same `external_articles_seen` URL-hash table as SA.

**STOP_AND_LOG triggers (any one trips, run aborts immediately):**
| Trigger | Detection | Action |
|---|---|---|
| Auth expired | login link visible OR HTTP 403 | post `{"alert":"R1_auth_expired","target":"reddit\|sa\|bnz"}` to `#system-alerts`; pause that target 24h |
| CAPTCHA | recaptcha iframe / challenge id | same |
| Layout drift | required selector missing 3 cycles in a row | same; tag `layout_change` |
| 429 / 503 | HTTP status | exponential 5min → 30min → cycle pause |
| Quota exhausted | run counter ≥ 15 within rolling 7d | hard refuse start; post `{"alert":"R1_quota_exhausted"}`; resume next ISO week boundary |

**Failure semantics:** stop the run, write the failure to `routine_health`, surface to operator. Never silently re-attempt. Quota counters do NOT roll over to next week.

### 2.B R2 — Local Intelligence (`R2_LOCAL_INTEL`)

Two sub-routines, each its own process under a Windows supervisor (planner accepts architect's recommendation).

**Sub-routine 2.B.i — Email via Outlook desktop COM (`pywin32`)**
- Path: `outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")` → `inbox = outlook.GetDefaultFolder(6)`.
- Cycle: every 60s, `inbox.Items.Restrict("[Unread]=true AND [ReceivedTime]>'<last_cycle_iso>'")`.
- Sender allowlist + subject-substring filter from new file `/root/.openclaw/local_intel_allowlist.json` (mirrors `sources.json` precedent).
- Mark items Read **only after the relay ack** (no data loss on crash).
- No content interpretation. Pure `extract_tickers()`.
- Output → `TickerSignal(source_type=EMAIL, source_detail="email|from:{addr}|subj:{subj[:80]}", sentiment=NEUTRAL, detected_at=item.ReceivedTime.timestamp())`.
- Dedup: `(EntryID, ticker)` in routine-local SQLite `win_routines.db`. Optional engine-side `email_signals(entry_id, ticker, …, PRIMARY KEY(entry_id,ticker))` for cross-routine search.

**Sub-routine 2.B.ii — Discord (hybrid, ToS-safe)**

Three paths considered. Operator's verdict (propagated verbatim from team-lead brief):

| Path | Verdict | Use for |
|---|---|---|
| **(a) User-token automation** | **REJECTED** — explicit ToS violation, account-ban risk. Document as a tempting shortcut to NOT take. | nothing |
| **(b) UI automation of Discord desktop app** (`pywinauto` UIA backend) | **ACCEPTABLE** — ToS-safe, fragile to UI redesigns | DMs and external servers operator can't add a bot to |
| **(c) Bot-relay** (engine-owned bot in operator's server) | **RECOMMENDED** — reuses TweetShift listener pattern | Channels operator owns or can invite a bot to |

**Primary path = (c) bot-relay.** New `DiscordLocalIntelListener` mirrors `DiscordTweetShiftListener` (`scanners/discord_tweetshift.py:133`); listens on channel ID `discord_local_intel_channel_id` (config); calls `db.insert_signal(...)` directly. Engine-side, not Windows.

**Secondary path = (b) UI automation.** Windows process every 30s walks Discord's accessibility tree. Composite dedup key `sha1(channel|sender|ts|first40_chars)` since the UI doesn't expose `message_id`. Emits via the Discord-relay JSON path (§3.6) like every other Windows routine.

- Output → `TickerSignal(source_type=DISCORD_DM, source_detail="discord|{channel}|user:{author}|via:{bot|ui}", sentiment=NEUTRAL)`.
- Dedup table: new engine-side `seen_discord(message_id TEXT PRIMARY KEY, ts REAL)` with 24h sweep.

**Allowlist file** (single source of truth, ops-editable):
```json
{
  "email_senders": ["alerts@analyst1.com", "*@premiumstocks.io"],
  "email_subjects_must_contain": ["alert","trade","trigger","$"],
  "discord_bot_channels": ["1234567890"],
  "discord_ui_channels": [{"server":"FriendsServer","channel":"options-alerts"}]
}
```

### 2.C R3 — Observability + Gap Detection (`R3_GAP_DETECT`)

**Engine-side only — no Windows surface.** Cadence: every 5 min during market hours (9:30–16:00 ET), hourly otherwise.

**Top movers source:** reuse `volume_scanner._fetch_quote` (`scanners/volume_scanner.py:99`); compute `mover_pct = (c - pc) / pc`; rank top-30 absolute % movers across S&P 500 ∪ operator's SA portfolio (cached from R1.A.ii). **No new external API call.** If the operator later confirms paid Finnhub access (OQ-5), swap to a single `/stock/market-mover` call.

**Cross-reference query (per top-mover ticker):**
```sql
SELECT source_type, source_detail,
       MIN(detected_at) AS first_seen,
       MAX(detected_at) AS last_seen,
       COUNT(*)         AS hits
FROM ticker_signals
WHERE ticker = ? AND detected_at >= ?
GROUP BY source_type, source_detail
ORDER BY first_seen ASC;
```

**Outputs (layered):**
1. `gap_reports` row per ticker per cycle (primary store).
2. `#gap-alerts` Discord post **only** when `status='MISSED'` AND `mover_pct ≥ 5%` (quiet by design).
3. Alfred morning briefing — extend `briefing/alfred.py:19 build_briefing_data` with one query: `SELECT * FROM gap_reports WHERE status='MISSED' AND report_generated_at >= session_start`.

**Status rules:** `CAUGHT` (≥10min lead), `LATE` (0–<10min), `MISSED` (no row in window).

### 2.D R4 — Clipboard Sentinel (`R4_CLIPBOARD`) — recommended (top-2 of desktop-only)

**Why:** clipboard = operator-attention signal that's invisible server-side. Effort=S, value=H.

- `pywin32` clipboard-changed window message (zero-poll) → on change, `extract_tickers(clipboard_text)`.
- If 1–3 tickers extracted (>3 = list paste, ignore), emit `TickerSignal(source_type=CLIPBOARD, source_detail="clipboard|app:{foreground_window_title[:60]}", sentiment=NEUTRAL)`.
- Privacy gates (REQUIRED before ship): hard-reject regex match for credit-card / SSN / common password patterns; foreground-app allowlist (Chrome, Edge, Outlook, Discord, Bloomberg Terminal, ThinkOrSwim); never log full `raw_text` if any reject pattern matched.
- Dedup: in-memory set, 5-min TTL.

### 2.E R6 — Browser Bookmark Sentinel (`R6_BOOKMARK`) — recommended (top-2 of desktop-only)

**Why:** operator drops articles into a Chrome folder named `"Watchlist Add"` while researching = high-trust manual curation. Effort=S, value=H.

- Watch `%LOCALAPPDATA%\Google\Chrome\User Data\Default\Bookmarks` for mtime change.
- Diff `"Watchlist Add"` folder against last-known set in `win_routines.db`.
- For each new bookmark: aiohttp fetch URL → parse `<title>` + `<meta og:description>` → `extract_tickers()`.
- Output → `TickerSignal(source_type=BOOKMARK, source_detail="bookmark|{domain}|{url}", sentiment=NEUTRAL)`.
- **Resolution to OQ-6:** sentiment = `NEUTRAL`, NOT `BULLISH`. Bookmarking signals attention, not direction. The constraint "no sentiment scoring changes" overrides the architect's tentative `BULLISH` proposal. Downstream weighting can boost `source_type=BOOKMARK` without us asserting bullishness.
- Dedup: bookmark `id` field from Chrome JSON.

### 2.F Deferred to v2 (rationale)

| Routine | Reason for defer |
|---|---|
| R5 TradingView Watchlist Mirror | Effort=M, value=M (roster sync, not signals). LevelDB format is fragile and TV doesn't expose a public personal-watchlist API. R1.A.ii already pulls operator's SA portfolio which serves the same "active watchlist" purpose for Phase 1. Revisit in v2 if SA portfolio drifts from TV watchlist. |
| R7 System-Audio Podcast Capture | Effort=H. Whisper.cpp setup, audio-device permission dance, continuous CPU spike. Deserves its own resource gate. Defer to v2. |

### 2.G Routine summary matrix

| Routine | Source | New `SourceType` | New table | Dedup | Cadence | Quota |
|---|---|---|---|---|---|---|
| R1.A.i Reddit-authed | reddit.com | `REDDIT_AUTHED` | reuse `reddit_posts` | post_id | within R1 run | counts toward 15/wk |
| R1.A.ii Seeking Alpha | seekingalpha.com | `SEEKING_ALPHA` | `external_articles_seen` | URL hash | within R1 run | counts toward 15/wk |
| R1.A.iii Benzinga | benzinga.com | `BENZINGA` | reuse `external_articles_seen` | URL hash | within R1 run | counts toward 15/wk |
| R2.B.i Email | Outlook COM | `EMAIL` | `email_signals` (optional) | EntryID | 60s | unbounded (passive) |
| R2.B.ii Discord (bot) | Discord Bot API | `DISCORD_DM` | `seen_discord` | message_id | event | unbounded (passive) |
| R2.B.ii Discord (UI) | Discord desktop UIA | `DISCORD_DM` | `seen_discord` | composite hash | 30s | unbounded (passive) |
| R3 Gap-detect | engine-internal | n/a (writes report) | `gap_reports` | (ticker, cycle_id) | 5min mkt-hrs / 1h off | unbounded (engine-side) |
| R4 Clipboard | OS clipboard | `CLIPBOARD` | none | in-mem 5min | event | unbounded (passive) |
| R6 Bookmark | Chrome JSON | `BOOKMARK` | none | bookmark_id | mtime event | unbounded (passive) |

---

## 3. Optimizations & New Ideas

### 3.1 Anti-bot patterns (R1)

- **Per-site cadence jitter.** Reddit 7–11 min, SA 12–18 min, Benzinga 9–14 min. Random uniform within range each cycle. Never a fixed period.
- **Fingerprint hygiene.** `playwright_stealth.Stealth().apply_stealth_async(page)` per CLAUDE.md. Chrome profile inherits operator's real User-Agent; never override.
- **Profile separation.** All R1 traffic uses `playwright.chromium.launch_persistent_context(user_data_dir=<operator's existing Chrome User Data>, channel="chrome")` — same cookies, ad-block, paywall whitelists as the operator's interactive browsing. Crucially, this means the operator's *residential IP* is the source — no datacenter fingerprint.
- **Mouse jitter & scroll pacing.** `page.mouse.move(x,y,steps=N)` with `N∈[8,14]` before each scroll. `asyncio.sleep(uniform(0.7,1.4))` between scrolls. `uniform(2.5,5.0)`s dwell after scroll loop, before extraction.
- **Tab discipline.** New tab per subreddit / per ticker (fresh referrer). Never >3 tabs open in the R1 context. Close on completion.
- **Hard subordinate caps.** ≤3 subs/min, ≤4 SA tickers/min, ≤6 Benzinga tickers/min within a run.

### 3.2 Tab/timing strategy under the 15-runs/week cap

Distribute the 15 runs to maximize coverage of high-attention windows:

| Day | Run 1 (premkt overlap) | Run 2 (midday) | Run 3 (power hour) | Total |
|---|---|---|---|---|
| Mon | 09:25 ET | 12:00 ET | 15:30 ET | 3 |
| Tue | 09:25 ET | 12:00 ET | 15:30 ET | 3 |
| Wed | 09:25 ET | 12:00 ET | 15:30 ET | 3 |
| Thu | 09:25 ET | 12:00 ET | 15:30 ET | 3 |
| Fri | 09:25 ET | 12:00 ET | 15:30 ET | 3 |
| Sat | — | — | — | 0 |
| Sun | — | — | — | 0 |
| **Week total** | | | | **15** |

Rationale: premkt analyst posts settle by ~9:25 ET; midday gives lunch-hour analyst posts; 15:30 ET captures EOD setups before market close. Weekend SA/Benzinga content is stale and not worth a quota slot. Fri 15:30 ET also brushes the start of the existing weekend pause (Fri 3pm ET — memory digest §"Weekend Pause Update").

**Per-run wall-clock budget:** ≤6 min total — 5 subs (~2.5 min) + 3 SA tickers (~1.5 min) + 3 Benzinga tickers (~1.5 min) + transition overhead.

**Quota enforcement (defense-in-depth):**
- *Client-side:* `win_routines.db.r1_runs(run_started_at REAL, run_ended_at REAL, status TEXT)`. Before launch, count rows where `run_started_at >= now - 7*86400 AND status IN ('OK','PARTIAL')`; refuse if ≥15.
- *Server-side:* `DesktopFeedListener` rejects messages with `src` starting `R1_*` if the rolling 7-day count of accepted R1 runs is ≥15. Posts `{"alert":"R1_quota_exceeded_server_side"}` to `#system-alerts` (this should never fire if the client behaves; it's the canary).

### 3.3 Reliability & failure semantics

- **Retry policy:** zero retries on STOP_AND_LOG triggers. One retry with 30s backoff on transient network errors (connection reset, DNS). Beyond that → log + abort cycle.
- **Fallback chains:** Discord transport (path c bot) is primary; if relay channel is unreachable for >2 min the Windows process buffers up to 200 messages to `win_routines.db.outbox` and drains on reconnect. Hard ceiling 200 — beyond that, drop oldest and emit `{"alert":"R{n}_outbox_overflow"}`.
- **Stop-on-failure semantics:** every routine has a `_safe_run()` wrapper that catches `Exception`, writes a `routine_health` row with traceback, and (if the same exception class hit 3× consecutive cycles) flips `routine_health.paused_until = now + 86400` and posts `{"alert":"R{n}_paused_24h","reason":<traceback head>}` to `#system-alerts`. Operator must clear `paused_until` manually to resume — this matches the memory-digest "reliability over speed" priority.
- **Heartbeats:** every routine writes `routine_health(routine_id, last_cycle_started, last_success_at, errors_in_cycle, paused_until)` every 60s. R3 gap-detection tails this table and surfaces stuck routines in the morning briefing.
- **Stuck-loop alarm:** reuses the Discord-listener pattern from 2026-04-19 memory-digest fix — counter increments on each reconnect/cycle-restart; >5 consecutive without a successful signal emit → `{"alert":"R{n}_STUCK_LOOP"}`.

### 3.4 Performance

- **Sequential within R1, parallel across routines.** R1 sub-targets (Reddit / SA / Benzinga) run *sequentially* inside a single Playwright context — protects shared cookies/fingerprint and avoids racing on the residential IP. Different *routines* (R2/R4/R6) run as separate processes and are naturally parallel.
- **Browser context reuse.** One persistent `BrowserContext` for R1's lifetime; tabs created/closed per target. R5 (deferred) would share that context if it ships.
- **Headful vs. headless.** **Headful, on the operator's logged-in profile.** Headless is detectable; headless on a fresh profile would also lose the SA paywall bypass. R1 is built for correctness over throughput.
- **Engine-side cost.** R3 reuses the existing volume-scanner quote loop — no new external HTTP calls, no new DB connection pool. The 7 new `SourceType` enum values cost zero — they're string constants. The new `external_articles_seen`, `seen_discord`, `gap_reports`, `routine_health`, `email_signals` tables add a handful of rows per minute total; SQLite WAL-mode handles this trivially.

### 3.5 Additional desktop-only opportunities — effort × value scoring

| ID | Routine | Effort | Value | Score | Phase |
|---|---|---|---|---|---|
| R4 | Clipboard sentinel | S | H | **HH** | **v1 (recommended)** |
| R6 | Bookmark sentinel | S | H | **HH** | **v1 (recommended)** |
| R5 | TradingView watchlist mirror | M | M | MM | v2 (deferred) |
| R7 | System-audio podcast capture | H | M | LM | v2 (deferred) |

**Top 2 = R4 (Clipboard) + R6 (Bookmark).** Both are S-effort, H-value, fit cleanly under the existing transport, and impose zero quota burden (event-driven on local OS state, not external sites).

### 3.6 Transport: Discord-relay payload format (the EXACT wire format)

**Channel:** new `#desktop-feed` in operator's owned server. Engine-side `DesktopFeedListener` (new file `consensus_engine/scanners/discord_desktop_feed.py`) mirrors `DiscordTweetShiftListener` (`scanners/discord_tweetshift.py:133`).

**Wire format (one JSON per Discord message; line content only — the listener parses `message.content`):**

Primary `TickerSignal` payload:
```json
{
  "v": 1,
  "src": "R1_AUTHED_WEB.reddit",
  "ticker": "NVDA",
  "source_type": "reddit_authed",
  "source_detail": "r/wallstreetbets|post:1abc23|u/dfv|score:842|comments:1245",
  "raw_text": "Title here\n\nbody text here…",
  "sentiment": "neutral",
  "detected_at": 1714521600.123,
  "nonce": "01HXYZ…"
}
```

Sidecar `reddit_posts` payload (for the existing archive table):
```json
{
  "v": 1,
  "sink": "reddit_posts",
  "id": "1abc23",
  "subreddit": "wallstreetbets",
  "title": "Title here",
  "author": "dfv",
  "score": 842,
  "num_comments": 1245,
  "created_utc": 1714521000,
  "fetched_at": 1714521600.123
}
```

`external_articles_seen` dedup payload (R1.A.ii / R1.A.iii first):
```json
{
  "v": 1,
  "sink": "external_articles_seen",
  "url_hash": "<sha1 hex>",
  "source": "seeking_alpha",
  "first_seen": 1714521600.123,
  "ticker": "AAPL"
}
```

**Listener-side validation (in `DesktopFeedListener.handle_message`):**
1. Reject if `v != 1`.
2. Reject if `src` not in `{R1_AUTHED_WEB.reddit, R1_AUTHED_WEB.sa, R1_AUTHED_WEB.bnz, R2_LOCAL_INTEL.email, R2_LOCAL_INTEL.discord_ui, R4_CLIPBOARD, R6_BOOKMARK}`.
3. Reject if `source_type` not in extended `SourceType` enum (§4.1 Phase 0).
4. Reject if `nonce` already seen in last 24h (replay protection — keyed in `seen_discord` or a peer table `seen_relay_nonces(nonce TEXT PRIMARY KEY, ts REAL)`).
5. Quota gate: if `src` starts `R1_*`, check rolling 7d count; reject (server-side) if ≥15.
6. On valid `TickerSignal` payload:
   ```python
   await db.insert_signal(TickerSignal(
       ticker=payload["ticker"],
       source_type=SourceType(payload["source_type"]),
       source_detail=payload["source_detail"],
       raw_text=payload["raw_text"],          # db.py:710 truncates to 2000 server-side
       sentiment=Sentiment(payload["sentiment"]),
       detected_at=payload["detected_at"],
   ))
   ```
   The above runs the literal SQL from §1.1.
7. On `sink: reddit_posts` payload: `await db.insert_reddit_posts([{...}])` (existing function).
8. On `sink: external_articles_seen` payload: `INSERT OR IGNORE INTO external_articles_seen (url_hash, source, first_seen, ticker) VALUES (?, ?, ?, ?)`.
9. Any rejection → log to `#system-alerts` as `{"alert":"desktop_feed_rejected","reason":<...>,"payload_excerpt":<first 200 chars>}` AND return without forwarding.

**Why Discord-relay (resolution to OQ-7):** reuses proven TweetShift gateway code, the reconnect-counter / stuck-loop hardening shipped 2026-04-19, the engine's existing Discord token, and adds zero new attack surface. HTTPS endpoint would require new auth + public exposure; file-sync introduces ordering ambiguity with no stuck-loop detection. Confirmed.

---

## 4. Execution Plan

### 4.1 Open-question resolutions (consolidated, applied)

| OQ | Question | Resolution | Rationale |
|---|---|---|---|
| 1 | SourceType enum: extend or reuse? | **Extend.** Add 7 new values. Update `models.py:9–18` AND `db.py:783` `get_social_signals` IN-list. | `source_type` is the only typed filter handle. Squashing breaks weighted scoring downstream. |
| 2 | SA/Benzinga publisher-asserted sentiment | **Accepted** for SA `Buy/Sell` rating + Benzinga `Movers Up/Down` tag. Pass-through only — explicitly NOT inference. Document in code comment. | Constraint forbids new sentiment *scoring*; mapping a publisher's own label is data preservation, not analysis. |
| 3 | SA/Benzinga dedup key | **URL-hash via new `external_articles_seen` table.** | Mirrors news-cascade pattern; cross-source dedup desirable when SA + Benzinga syndicate same wire. |
| 4 | SA seed list source | **Operator's SA portfolio** (~20–40 tickers). | Scope-bounded; honors desktop-only premise; avoids hammering. |
| 5 | Finnhub paid tier `/stock/market-mover`? | **Defer to operator.** Plan ships with N-quote-call derivation; if operator confirms paid tier, swap to single endpoint via new config flag `finnhub.has_market_mover_endpoint: true`. | Plan must not assume paid features; degradation path is free. |
| 6 | Bookmark sentiment | **`NEUTRAL`** (downgrade from architect's tentative `BULLISH`). | Constraint forbids sentiment scoring changes. `source_type=BOOKMARK` already encodes "operator-curated" trust; downstream weighting can boost without us asserting direction. |
| 7 | Transport | **Discord-relay channel.** | Reuses TweetShift listener; zero new attack surface; proven reconnect logic. |
| 8 | R7 audio in v1? | **No — defer to v2.** | Effort=H, value=M, dedicated resource gate needed. R4+R6 give v1 better S-effort coverage. |

### 4.2 Build order

Dependencies first. Each phase completes before the next begins. Numbered for executor handoff.

**Phase 0 — Foundation (engine-side; no Windows code yet)**
- **0.1** Extend `SourceType` enum in `consensus_engine/models.py:9–18` with: `REDDIT_AUTHED = "reddit_authed"`, `SEEKING_ALPHA = "seeking_alpha"`, `BENZINGA = "benzinga"`, `EMAIL = "email"`, `DISCORD_DM = "discord_dm"`, `CLIPBOARD = "clipboard"`, `BOOKMARK = "bookmark"`. *(7 new values; explicit list — no `PODCAST` since R7 is deferred.)*
- **0.2** Update `db.py:783` `get_social_signals` IN-list to include `'reddit_authed', 'seeking_alpha', 'benzinga'`. (`email`, `discord_dm`, `clipboard`, `bookmark` are NOT social-cross-reference targets — leave them out unless a downstream consumer asks.)
- **0.3** New tables (DDL, in `db.py` schema-init block):
  - `external_articles_seen(url_hash TEXT PRIMARY KEY, source TEXT NOT NULL, first_seen REAL NOT NULL, ticker TEXT)`
  - `seen_discord(message_id TEXT PRIMARY KEY, ts REAL NOT NULL)`
  - `seen_relay_nonces(nonce TEXT PRIMARY KEY, ts REAL NOT NULL)`
  - `email_signals(entry_id TEXT NOT NULL, ticker TEXT NOT NULL, subject TEXT, sender TEXT, received_at REAL, PRIMARY KEY(entry_id, ticker))`
  - `routine_health(routine_id TEXT PRIMARY KEY, last_cycle_started REAL, last_success_at REAL, errors_in_cycle INTEGER DEFAULT 0, paused_until REAL)`
  - `gap_reports(id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, mover_pct REAL, current_price REAL, prev_close REAL, first_source TEXT, first_source_detail TEXT, first_seen_at REAL, detection_delay_sec REAL, total_signals INTEGER, sources_hit TEXT, report_generated_at REAL, status TEXT)`
- **0.4** New scanner `consensus_engine/scanners/discord_desktop_feed.py` modeled on `discord_tweetshift.py:133`. Implements §3.6 listener-side validation. Wires into `main.py` alongside the TweetShift listener.
- **0.5** New listener `DiscordLocalIntelListener` (same file or sibling) for the bot-relay path of R2.B.ii. Reads channel ID list from `discord_local_intel_channel_id` config.
- **0.6** Config additions to `config/consensus.yaml`:
  - `desktop_feed.enabled: true`
  - `desktop_feed.channel_id: $DISCORD_DESKTOP_FEED_CHANNEL_ID`
  - `desktop_feed.r1_weekly_quota: 15`
  - `local_intel.bot_channels: []` (operator fills)
  - `local_intel.allowlist_path: /root/.openclaw/local_intel_allowlist.json`
  - `gap_detect.enabled: true`, `gap_detect.window_hours: 4`, `gap_detect.alert_threshold_pct: 5.0`
  - `finnhub.has_market_mover_endpoint: false` (operator flips if they have paid tier)
- **0.7** New env var: `DISCORD_DESKTOP_FEED_CHANNEL_ID` in `/root/.openclaw/.env`.
- **0.8** Deferred-task entry per CLAUDE.md "Deferred Task System": create a one-shot weekly reset audit task via `/root/task_system/scripts/create_task.sh` that snapshots and resets R1's rolling-7d counter to confirm quota math.

**Phase 1 — R3 Gap Detection (engine-only, fastest E2E validation)**
- **1.1** New module `consensus_engine/scanners/gap_detect.py`. Public `gap_detect_loop()` modeled on `sec_form4_cluster_loop` (`main.py:309`).
- **1.2** Top-mover helper: thin wrapper around `volume_scanner._fetch_quote` (no edits to volume_scanner.py).
- **1.3** Emit-to-`#gap-alerts` helper (only `MISSED` + `mover_pct ≥ 5%`).
- **1.4** Extend `briefing/alfred.py:19 build_briefing_data` with one query: `gap_reports WHERE status='MISSED' AND report_generated_at >= session_start`. Add the new section to the briefing template.
- **1.5** Wire `gap_detect_loop` into `main.py` background watchers list.
- **Why first:** zero Windows surface, exercises the new tables and config plumbing, validates the briefing-template extension point before any R1/R2 traffic.

**Phase 2 — R2.B.i Email (Outlook COM, lowest Windows friction)**
- **2.1** New repo subdir `windows_routines/` (or operator-chosen location on the Windows PC). `email_outlook.py` implementing the Outlook-COM cycle.
- **2.2** Local SQLite `win_routines.db` with `r1_runs`, `email_seen(entry_id, ticker, ts)`, `outbox`.
- **2.3** Discord-relay client (`relay_client.py`) — single emit function used by every Windows routine. Includes outbox spool (§3.3) and nonce generation.
- **2.4** Allowlist loader (`/root/.openclaw/local_intel_allowlist.json`) shared with R2.B.ii, R4, R6.
- **2.5** Supervisor wrapper `_safe_run()` with the 3-strike pause-24h semantics (§3.3).

**Phase 3 — R2.B.ii Discord bot-relay path (engine-side only)**
- **3.1** Configure `DiscordLocalIntelListener` from Phase 0.5 with operator's bot-relay channel IDs.
- **3.2** Operator invites the engine bot to their alert channels.
- **3.3** Smoke test: operator pings a test ticker into a relay channel; verify it lands in `ticker_signals` with `source_type=discord_dm`.
- **Why before R2.B.ii UI path:** bot-relay is the higher-reliability primary; the UI path is a fallback for what the bot can't see (DMs, external servers).

**Phase 4 — R4 Clipboard sentinel**
- **4.1** `windows_routines/clipboard_sentinel.py` using `pywin32` clipboard-changed message hook.
- **4.2** Privacy-gate module: regex blocklist (cards, SSN, password patterns) + foreground-app allowlist. Reject path logs only routine name + ticker (never raw text) when blocklist hits.
- **4.3** In-memory 5-min TTL dedup.
- **4.4** Emit via `relay_client`.

**Phase 5 — R6 Bookmark sentinel**
- **5.1** `windows_routines/bookmark_sentinel.py` watching `Bookmarks` JSON for mtime change.
- **5.2** Diff `"Watchlist Add"` folder against `win_routines.db.bookmarks_seen(id PRIMARY KEY)`.
- **5.3** aiohttp fetch of new URLs → parse `<title>` + og:description.
- **5.4** Emit `TickerSignal(source_type=BOOKMARK, sentiment=NEUTRAL)` (per OQ-6).

**Phase 6 — R1 Authenticated Web (highest risk; saved for last)**
- **6.1** `windows_routines/authed_web/` package with `reddit.py`, `seeking_alpha.py`, `benzinga.py`, `runner.py`.
- **6.2** Persistent Playwright + `playwright_stealth` Chrome profile (operator's existing User Data dir).
- **6.3** Per-target extraction logic + STOP_AND_LOG triggers from §2.A.
- **6.4** `external_articles_seen` URL-hash dedup via relay.
- **6.5** Quota enforcer: client-side counter in `win_routines.db.r1_runs`; server-side rejection in `DesktopFeedListener` (§3.6).
- **6.6** Schedule: Windows Task Scheduler triggers `runner.py` Mon–Fri at 09:25 / 12:00 / 15:30 ET (§3.2). Sat/Sun no triggers.

**Phase 7 — R2.B.ii Discord UI automation (secondary path, fragile)**
- **7.1** `windows_routines/discord_ui.py` using `pywinauto.Application(backend="uia").connect(title_re="Discord")`.
- **7.2** Composite-hash dedup, 30s poll cadence.
- **7.3** Emit via `relay_client`.
- **Why last:** ToS-safe but UI-redesign-fragile; operator should validate path-c bot coverage first and only enable UI path for the residual gap (DMs + external servers).

**v2 deferred:** R5 (TradingView), R7 (audio).

### 4.3 Dependencies

**Engine-side (Linux):**
- Already present: `aiosqlite`, `discord.py` (TweetShift listener), `aiohttp`, `pyyaml`.
- New: none beyond what TweetShift already pulls.

**Windows-side:**
- `pywin32` (Outlook COM, clipboard, foreground-window title)
- `pywinauto` (Discord UI automation; UIA backend)
- `playwright` + `playwright-stealth` (existing in repo per CLAUDE.md)
- `aiohttp` (bookmark URL fetch, relay client)
- `aiosqlite` (`win_routines.db`)
- Python ≥ 3.11 (matches engine)

**Scheduling:**
- Windows Task Scheduler entries for R1 (Mon–Fri × 3 slots).
- The other Windows routines run as long-lived processes under a supervisor (NSSM service or Task Scheduler "at logon, run forever" entry).

### 4.4 Testing strategy

- **Dry-run mode** (`--dry-run` flag on every Windows routine + on `desktop_feed.enabled` config gate): extracts and validates payloads but routes them to a `#desktop-feed-dryrun` channel that the listener consumes only to log+drop. Existing pattern: `python3 -m consensus_engine --dry-run --once` (per project CLAUDE.md "Commands").
- **Staging table:** add `ticker_signals_staging` mirroring `ticker_signals`. Phase 0 ships a config flag `desktop_feed.target_table` defaulting to `ticker_signals_staging`. Operator flips to `ticker_signals` after Phase 1 verification.
- **Golden-fixture replay:** capture 50 real Discord-relay payloads during dry-run; commit to `tests/fixtures/desktop_feed/`. Replay test asserts the listener produces identical `INSERT` calls (mocked db).
- **Quota math test:** unit test that simulates 14 → 15 → 16 R1 runs in a 7-day window and asserts the 15th is accepted, the 16th is rejected with the expected `#system-alerts` payload.
- **Tweet-engine baseline preserved:** existing `python3 -m pytest tests/ -v` must remain green throughout. No edits to scoring / weighting / cross-reference scoring files.

### 4.5 Logging & rotation

- **Format:** existing project pattern — `%(asctime)s %(levelname)s %(name)s: %(message)s` (matches `consensus_engine` logger). Windows routines use the same format.
- **Locations:**
  - Engine-side: existing `consensus_engine.log` in repo root.
  - Windows-side: `%LOCALAPPDATA%\openclaw\logs\R{n}_<routine>.log`.
- **Rotation:** `logging.handlers.RotatingFileHandler`, 10 MB × 5 keep. Daily summary line `[ROUTINE_DAILY] R1: 3/3 runs OK | 47 signals | 0 STOP_AND_LOG triggers`.
- **Operator-notification triggers (post to `#system-alerts`):**
  - Any STOP_AND_LOG trigger (§2.A failure modes).
  - Routine paused 24h after 3 consecutive failures (§3.3).
  - Stuck-loop alarm (>5 cycles without success).
  - Outbox overflow (>200 pending relay payloads).
  - Server-side R1 quota rejection (canary).
  - Listener-side payload rejection (canary).
- **No alerts on success.** Quiet by design — matches the "no spam" axis of the existing alert philosophy in the project CLAUDE.md.

### 4.6 Rollout (shadow → enable one routine → observe → enable next)

1. **Day 0 — Shadow.** Phase 0 deployed. `desktop_feed.target_table=ticker_signals_staging`. Listener accepts payloads, writes to staging, no production effect. Operator sends 5 manual relay messages; planner/operator validate via `sqlite3 staging`.
2. **Day 1 — R3 Gap Detection on.** `gap_detect.enabled: true` in config. Observe a full market day. Confirm `gap_reports` populates and morning briefing's "Yesterday's Gaps" section renders.
3. **Day 2 — Email (R2.B.i) on.** Windows process launches. Observe 24h. Validate `email_signals` rows match Outlook unread items in window.
4. **Day 3 — Discord bot-relay (R2.B.ii path-c) on.** Operator invites bot to one alert channel. Smoke test, then leave on for 24h.
5. **Day 4 — R4 Clipboard on.** Run privacy-gate review with operator first (regex blocklist + foreground app allowlist). Enable for 24h.
6. **Day 5 — R6 Bookmark on.** Operator drops a known test article into `Watchlist Add`. Verify within 5 min.
7. **Day 6–7 — Promote staging → ticker_signals.** Flip `desktop_feed.target_table` config. Re-run smoke tests on R3 / R2.B.i / R2.B.ii / R4 / R6 with production routing. Observe a market day.
8. **Day 8 — R1 first scheduled run.** Mon 09:25 ET premkt slot. Observe entire run end-to-end. Validate quota counter increments and (`SELECT COUNT(*) FROM r1_runs WHERE ...`) stays consistent client-side and server-side.
9. **Day 9–14 — Full R1 schedule.** All 15 weekly slots active. Daily review of `routine_health` + `gap_reports` for trends.
10. **Day 14 — R2.B.ii path-b (UI automation).** Enable last; only for the residual gap that path-c (bot-relay) can't cover.
11. **Critic / verifier checkpoint:** at end of week 2, formally review `gap_reports` for new `CAUGHT` rows attributable to the new sources (compared to baseline week-of-2026-04-23 data). If R1 isn't producing measurable `CAUGHT` lift, escalate before raising the weekly quota.

### 4.7 What this plan explicitly does NOT do

- Does not edit `consensus_engine/cross_reference.py`, `engine.py`, `scoring*`, `alerts/*` decisioning, or any sentiment-classifier code.
- Does not change any threshold in `config/consensus.yaml` outside the new keys listed in §4.2 step 0.6.
- Does not add Reddit/StockTwits engine-side scanners (those remain disabled per project CLAUDE.md and discovery doc).
- Does not implement R5 (TradingView) or R7 (audio) — explicitly v2.
- Does not amend the existing TweetShift listener — the new `DesktopFeedListener` is a sibling, not a modification.

### 4.8 Definition of Done (executor hand-off contract)

- Phase 0 schema migrations applied; `pytest` green; new tables exist.
- All 7 new `SourceType` values appear in `models.py:9–18`; `db.py:783` IN-list updated; existing tests still green.
- `DesktopFeedListener` parses + validates + forwards every payload format in §3.6; rejects every malformed example in `tests/fixtures/desktop_feed/rejected/`.
- R3 produces a non-empty `gap_reports` row set during a market-hour test window; Alfred briefing renders "Yesterday's Gaps".
- R2.B.i (Email) successfully relays a synthetic test email end-to-end into `ticker_signals` with `source_type=email`.
- R1 quota math: synthetic 16-run injection rejects the 16th client-side AND (as canary) server-side.
- Stop-and-log: each STOP_AND_LOG trigger from §2.A produces exactly one `#system-alerts` post and zero downstream signals.
- No file outside `consensus_engine/scanners/`, `consensus_engine/models.py`, `consensus_engine/db.py`, `consensus_engine/main.py`, `consensus_engine/briefing/alfred.py`, `config/consensus.yaml`, `/root/.openclaw/.env`, `/root/.openclaw/local_intel_allowlist.json`, and the new `windows_routines/` tree is modified.
- Critic review (Task #4) passes.

---

## Appendix A — Open questions handed to critic / operator

None remaining from architect's list (all 8 resolved in §4.1). Two items handed forward:

- **Operator confirm:** Finnhub paid tier (OQ-5) — flip `finnhub.has_market_mover_endpoint` if applicable.
- **Operator confirm:** R4 clipboard privacy-gate regex blocklist (cards/SSN/password patterns) — review before Phase 4 Day 4 enablement.

## Appendix B — File-touch manifest

Engine repo (read-only constraint — these are the exact files this plan authorizes the executor to modify):

- `consensus_engine/models.py` (Phase 0.1, +7 enum lines)
- `consensus_engine/db.py` (Phase 0.2 + 0.3, schema-init + IN-list)
- `consensus_engine/main.py` (Phase 0.4 + 0.5 + 1.5, wire new listeners + `gap_detect_loop`)
- `consensus_engine/scanners/discord_desktop_feed.py` (NEW, Phase 0.4)
- `consensus_engine/scanners/gap_detect.py` (NEW, Phase 1.1)
- `consensus_engine/briefing/alfred.py` (Phase 1.4, one query + one section)
- `config/consensus.yaml` (Phase 0.6, new keys only)
- `/root/.openclaw/.env` (Phase 0.7, new env var)
- `/root/.openclaw/local_intel_allowlist.json` (NEW, Phase 2.4)
- `tests/fixtures/desktop_feed/` (NEW, golden-fixture corpus)
- `tests/test_desktop_feed_listener.py` (NEW)
- `tests/test_gap_detect.py` (NEW)
- `tests/test_r1_quota.py` (NEW)

Windows side (operator's PC):

- `windows_routines/relay_client.py` (NEW)
- `windows_routines/email_outlook.py` (NEW, Phase 2)
- `windows_routines/clipboard_sentinel.py` (NEW, Phase 4)
- `windows_routines/bookmark_sentinel.py` (NEW, Phase 5)
- `windows_routines/authed_web/{reddit,seeking_alpha,benzinga,runner}.py` (NEW, Phase 6)
- `windows_routines/discord_ui.py` (NEW, Phase 7)
- `win_routines.db` (created at first run)

---

**End of plan. Ready for critic (Task #4) review.**

---

## Adversarial Review

**Reviewer:** critic (Stage 4/4)
**Date:** 2026-04-30
**Mode escalation:** THOROUGH → **ADVERSARIAL** (escalation triggered: 4 CRITICAL findings + systemic scope-creep pattern)
**Verdict:** **PLAN NEEDS REVISION**

### Pre-commitment predictions (made before detailed verification)

Predicted attack surface: Phase-0 scope-creep, R3 alert-channel-as-decisioning, residential-IP collateral damage, 3-strike vs immediate-stop softening, weekend-pause × Friday-15:30 collision, Outlook mark-Read race, allowlist Linux-path on Windows, ToS-tier downgrade for UI-automation, Finnhub free-tier quota math.

**Hit rate against actual findings:** 9/9. All predicted attack surfaces materialized into rated findings below.

---

### CRITICAL Findings (block execution)

**C1. Phase 1.2 cannot be executed: `volume_scanner._fetch_quote` is a closure, not importable.**
- *Plan quote:* `"Top-mover helper: thin wrapper around volume_scanner._fetch_quote (no edits to volume_scanner.py)."` (§4.2 Phase 1.2)
- *Plan quote:* `"reuse volume_scanner._fetch_quote (scanners/volume_scanner.py:99)"` (§2.C, §1.6)
- *Evidence:* `consensus_engine/scanners/volume_scanner.py:86` defines `async def scan_volume_breakouts(...)`; `_fetch_quote` is defined at `volume_scanner.py:99` — i.e. **inside** that outer function as a nested closure that captures `rate_limiter`, `cfg`, etc. It cannot be imported or called from outside its enclosing scope. R3 cannot reuse it without either (a) refactoring `volume_scanner.py` (which the plan explicitly forbids: "no edits to volume_scanner.py") or (b) duplicating the rate-limiter/HTTP logic. Either path is a real edit that the plan does not authorize.
- *Confidence:* HIGH.
- *Why this matters:* the executor will follow Phase 1.2 verbatim, hit ImportError, and either (i) stop and ask, or (ii) silently refactor `volume_scanner.py` against the plan's rules. Both outcomes break the contract.
- *Fix:* (1) explicitly authorize a refactor of `_fetch_quote` to a module-level helper in `volume_scanner.py`, OR (2) write a brand-new helper `consensus_engine/scanners/gap_detect.py::_finnhub_quote(...)` that duplicates the rate-limiter logic, and update §4.7 ("does NOT do") accordingly. Pick one, commit it in the plan.

**C2. Friday 15:30 ET R1 run lands inside the weekend pause; passive routines accumulate ~47h of unprocessed relay traffic.**
- *Plan quote:* `"Fri | 09:25 ET | 12:00 ET | 15:30 ET | 3"` (§3.2 schedule)
- *Plan quote:* `"15:30 ET also brushes the start of the existing weekend pause (Fri 3pm ET — memory digest §"Weekend Pause Update")."` (§3.2 rationale)
- *Plan quote (Phase 0.4):* `"New scanner consensus_engine/scanners/discord_desktop_feed.py modeled on discord_tweetshift.py:133. ... Wires into main.py alongside the TweetShift listener."`
- *Evidence:* `consensus_engine/main.py:91–101` — `_is_weekend_pause()` returns True for `wd==4 and now.hour >= 15` (Friday 15:00 onward). `main.py:415–437` — during pause the engine **only** runs `DiscordTweetShiftListener` in command-only mode (`_noop_tweet`); ALL other scanners and listeners are stopped. The plan wires `DesktopFeedListener` into the **non-weekend** branch (Phase 0.4 → "alongside the TweetShift listener" at `main.py:485`), but does not specify it should also run during the weekend block. Therefore: (i) the Friday 15:30 R1 run is scheduled to fire 30min after the listener has already shut down; (ii) R2-Email, R2-Discord-bot, R4-Clipboard, R6-Bookmark continue emitting on Windows from Fri 15:00 to Sun 14:00 ET (~47h) but no listener consumes them; (iii) the Windows-side outbox cap is 200 messages (§3.3) — easily overflowed by Email + Clipboard alone over 47h.
- *Confidence:* HIGH.
- *Why this matters:* one R1 quota slot/week guaranteed wasted (15→14 effective). Outbox-overflow alerts will spam `#system-alerts` every weekend. Worse: if executor naively starts `DesktopFeedListener` during the weekend block, that contradicts the project's "weekend pause" reliability philosophy.
- *Fix:* (a) move Friday slot to ≤14:50 ET (10min margin); (b) explicitly state whether `DesktopFeedListener` runs during weekend pause and document the rationale; (c) document a "post-resume drain" path on Sunday 2pm; (d) raise Windows outbox cap above 200 OR pause Windows routines for the weekend pause window.

**C3. R3 ships a NEW alert channel + a NEW morning-briefing section — that's alert decisioning, not "data access only".**
- *Plan quote (Hard Constraint #4):* `"NO trading logic, sentiment scoring, or alert decisioning changes."` (§1)
- *Plan quote:* `"#gap-alerts Discord post only when status='MISSED' AND mover_pct ≥ 5% (quiet by design)."` (§2.C)
- *Plan quote:* `"Alfred morning briefing — extend briefing/alfred.py:19 build_briefing_data with one query: ... Add the new section to the briefing template."` (§2.C, Phase 1.4)
- *Evidence:* a new Discord alert channel with a 5% threshold IS new alert decisioning by any reasonable definition — the plan defines a rule (`MISSED && mover_pct ≥ 5%`) that fires a notification to the operator. Alfred is the operator's primary daily decision input (memory: "Alfred (Morning Briefing) — Daily 8:50–9:00 ET"); modifying its content changes what the operator decides on. §4.7 only says "does not edit alerts/* decisioning" — but alerts/* is a *file path*, not the *concept*. The operator's brief was concept-level.
- *Confidence:* HIGH.
- *Why this matters:* the brief that produced this plan is paraphrased in the team-lead's message: "data access only, no decision-logic changes." A NEW alert channel and a NEW briefing section are decisioning. If the operator approves this plan as-is, they're approving more than they asked for; if they reject it, weeks of work are wasted.
- *Fix:* drop the `#gap-alerts` Discord post AND the Alfred-briefing extension from v1. Land R3 as DB-only (`gap_reports` table, no notification surface). Re-introduce the alert + briefing in a separate explicit operator-approved phase.

**C4. Phase 0 is an engine refactor (7 enums + 6 tables + 2 listeners + 1 background loop), not "data access only".**
- *Plan quote:* `"Phase 0 — Foundation (engine-side; no Windows code yet)"` (§4.2)
- *Plan quote:* `"0.1 Extend SourceType enum ... 0.3 New tables ... 0.4 New scanner ... 0.5 New listener ..."` (§4.2)
- *Evidence:* Phase 0 alone modifies `models.py` (+7 enum values), `db.py` (DDL for 6 new tables + IN-list expansion at line 783), `main.py` (wires 2 new listeners + 1 background loop), `briefing/alfred.py` (1 new query + briefing-template change in Phase 1.4), `config/consensus.yaml` (≥7 new keys), plus 2 new scanner modules. The brief said "data access only." Even before any Windows routine ships, this is a non-trivial engine expansion. Critic counts ≥10 distinct engine-side touches in Phase 0–1, before a single Windows ingestion message lands.
- *Confidence:* HIGH (downgraded by Realist Check from CRITICAL-blocking to CRITICAL-policy: each touch is reviewable in isolation, but the *cumulative scope* still exceeds the brief).
- *Why this matters:* operator's intent — verified against the team-lead's own framing ("Are 6 new tables + a new DesktopFeedListener really 'data access,' or is that scope creep into the engine?") — is that the engine should be touched **as little as possible**. The plan front-loads engine work that defers Windows-routine value to Phase 2+.
- *Fix:* re-scope Phase 0 to the **minimum viable foundation** for the FIRST Windows routine to ship. That is: (a) `DesktopFeedListener` only, (b) ONLY the `EMAIL` enum (since R2.B.i is the first Windows-side routine), (c) `routine_health` table only. Defer all other enums, tables, listeners, and R3 itself to dedicated explicit phases that the operator approves one-at-a-time.

---

### HIGH Findings (cause significant rework)

**H1. 15-runs/week with zero retry buffer is brittle by design.**
- *Plan quote:* `"15 runs/week cap on R1. ≤ 3 runs/weekday Mon–Fri, 0 runs Sat/Sun."` (§1)
- *Plan quote:* `"Schedule: Windows Task Scheduler triggers runner.py Mon–Fri at 09:25 / 12:00 / 15:30 ET"` (Phase 6.6)
- *Evidence:* 5 weekdays × 3 slots = 15 = exact match. §3.2 quota enforcement counts rows where `status IN ('OK','PARTIAL')` — implying STOP_AND_LOG runs with status≠OK do NOT count, which **defeats the cap** (a run that auth-fails immediately is free to retry). Conversely, a successful network-blip-then-recover run that's marked PARTIAL consumes the slot. The semantics are inconsistent.
- *Confidence:* HIGH.
- *Why this matters:* either the cap is leaky (failed runs don't count → Task Scheduler retry logic could exceed 15) or the cap is too tight (one failed Windows trigger = lost coverage for the week). Both outcomes are bad.
- *Fix:* count *every R1 invocation* (any status, including FAIL) toward the weekly cap; reserve 2 slots/week explicitly as retry buffer (i.e., schedule 13 runs, allow 2 retries on demand); document the runtime "what counts" rule in plain English in §1.

**H2. Outlook "Mark Read after relay ack" creates a silent data-loss window.**
- *Plan quote:* `"Mark items Read only after the relay ack (no data loss on crash)."` (§2.B.i)
- *Plan quote:* `"Any rejection → log to #system-alerts ... AND return without forwarding."` (§3.6 step 9)
- *Evidence:* "Relay ack" is undefined in the plan. The most natural read is "Discord-message-posted-successfully." But §3.6 then describes 8 listener-side validation steps any of which can REJECT; in that case Discord acked the post but no row reaches `ticker_signals`. Meanwhile, the Windows side has marked the email Read (because relay ack received). The email is now invisible to the next Outlook poll AND the signal never landed. Silent loss.
- *Confidence:* HIGH.
- *Why this matters:* the operator's #1 reliability priority per memory digest is "Don't miss actionable messages." This path silently misses them.
- *Fix:* either (1) define ACK as "listener inserted row in DB" via an explicit ACK message posted back to a `#desktop-feed-acks` channel that the Windows process tails, OR (2) keep email Unread and rely on EntryID-based dedup in `win_routines.db` so re-processing is idempotent. Pick one, spec it.

**H3. "3-strike pause-24h" is a softening of "STOP IMMEDIATELY on failure" — and it's especially dangerous for anti-bot triggers.**
- *Plan quote (Hard Constraint #2):* `"Stop-and-log on every failure. ... After 3 consecutive cycle failures the routine pauses itself for 24h."` (§1)
- *Plan quote:* `"if the same exception class hit 3× consecutive cycles flips routine_health.paused_until = now + 86400"` (§3.3)
- *Evidence:* the brief said STOP IMMEDIATELY on failure. The plan's wrapper retries silently for 2 cycles before pausing on the 3rd. For network blips that's fine. For anti-bot triggers (CAPTCHA, auth-expired, layout drift), 2 more cycles after detection can escalate from "soft challenge" to "account flagged" to "IP blocked." The plan conflates failure classes under one wrapper.
- *Confidence:* HIGH.
- *Why this matters:* the worst outcome of a single missed routine cycle is small. The worst outcome of three CAPTCHA-tripped cycles in a row is account ban. Asymmetric risk.
- *Fix:* tier the failure semantics. **Class A (immediate-pause-24h, 1 strike):** auth-expired, CAPTCHA, 403, layout-drift. **Class B (3-strike-then-pause):** transient network errors, 5xx. Encode this in §2.A's STOP_AND_LOG table explicitly; today the table conflates both into "STOP_AND_LOG" without specifying which class triggers immediate pause vs accumulator.

**H4. `extract_tickers()` "ported to Windows side as a copy or fetched via SSH/HTTP at startup" creates silent ticker-extraction drift.**
- *Plan quote (Phase 2.B.i / design §2.1):* `"extract_tickers() ... ported to Windows side as a copy or fetched via SSH/HTTP at startup"`
- *Evidence:* `consensus_engine/utils/tickers.py:86–112` `extract_tickers` depends on `_TICKER_PATTERN` regex AND `BLACKLIST` AND `_INSTITUTION_TICKERS` data. A "copy" introduces drift. SSH/HTTP fetch on boot creates a startup dependency on Linux-server availability and a remote-fetch race. Neither path has a checksum or version pin.
- *Confidence:* HIGH.
- *Why this matters:* divergent ticker extraction between Windows-side R1/R2/R4/R6 and engine-side scanners means a ticker that's blacklisted server-side may slip in via a Windows route, polluting `ticker_signals`.
- *Fix:* DO NOT port `extract_tickers` to Windows. Windows routines emit raw text in their relay payloads; the engine-side `DesktopFeedListener` runs `extract_tickers(payload["raw_text"])` and creates one signal **per extracted ticker**. Single source of truth, zero drift. Update §3.6 wire format: drop client-side `ticker` field, add server-side multi-ticker fan-out.

**H5. Allowlist file lives at a Linux server path; routines run on Windows. Cross-host sync mechanism is undefined.**
- *Plan quote (§2.B.ii):* `"single source of truth, ops-editable: ... new file /root/.openclaw/local_intel_allowlist.json"`
- *Plan quote (Phase 2.4):* `"Allowlist loader (/root/.openclaw/local_intel_allowlist.json) shared with R2.B.ii, R4, R6."`
- *Evidence:* `/root/...` is a Linux server path. R2.B.i (Email), R4 (Clipboard), R6 (Bookmark) all run on the Windows PC. The plan does not specify how Windows reads this file: SSHFS mount? Syncthing (already in operator's stack per the architect doc)? rsync at process start? The cross-host sync method is the entire trust boundary for the allowlist.
- *Confidence:* HIGH.
- *Why this matters:* without a sync method, the operator edits the file on Linux, expects Windows routines to honor the change, and they silently don't. Or worse: the routines fail to start because the path doesn't resolve. Either is a deployment blocker discovered in Phase 4 or 5.
- *Fix:* specify (a) Syncthing mount of `/root/.openclaw/` to a Windows path (memory digest implies Syncthing is already in use), OR (b) ship the allowlist as part of the relay-channel config and enforce it server-side in `DesktopFeedListener.handle_message` (single-host enforcement, Windows just emits).

**H6. Discord UI-automation tagged "ACCEPTABLE" understates real ToS risk.**
- *Plan quote (§2.B.ii table):* `"(b) UI automation of Discord desktop app — ACCEPTABLE — ToS-safe, fragile to UI redesigns"`
- *Evidence:* Discord ToS §"Acceptable Use" prohibits "any automated process or service to access or use the Service... including a 'bot,' 'spider,' or 'scraper'." Reading Discord's accessibility tree from a Python process is automated reading of the Service via the user's authenticated session — closer to user-token automation than the plan acknowledges. Past Discord enforcement (e.g., BetterDiscord, plugins, Capnabis-style readers) has resulted in account actions. 30s polling is aggressive enough to look automated.
- *Confidence:* MEDIUM. Discord enforcement is opaque; the threat model is real but the actual trigger likelihood is unknown. Industry consensus is "use at your own risk." Critic's read: this is MEDIUM-HIGH risk, not "acceptable."
- *Why this matters:* the operator's brief explicitly rejected user-token automation due to ban risk. UIA polling is in the same risk class qualitatively, just with a thinner ToS-compliance argument.
- *Fix:* (a) re-tier UIA path to "MEDIUM RISK — operator acknowledgement required"; (b) raise minimum poll interval from 30s to ≥300s (5min) to reduce automation signature; (c) require operator to explicitly enable per-channel via config (no implicit defaults); (d) document "if account action taken, route is permanently disabled."

**H7. Persistent Chrome profile shared with operator's interactive browsing = single-cookie-loss takes out daily browsing.**
- *Plan quote (§3.1):* `"Profile separation. All R1 traffic uses playwright.chromium.launch_persistent_context(user_data_dir=<operator's existing Chrome User Data>, channel='chrome') — same cookies, ad-block, paywall whitelists as the operator's interactive browsing."`
- *Evidence:* one CAPTCHA solve from R1 (or a Reddit anti-bot challenge during a scrape) pollutes the operator's Chrome profile. If R1 fires while the operator has Chrome open with a tab on Reddit/SA/Benzinga, Playwright will fail with profile-lock errors (Chrome's User Data dir lock contention). Lossless profile re-use across an active browser session is non-trivial and the plan does not address it.
- *Confidence:* HIGH.
- *Why this matters:* collateral damage on the operator's daily browsing — a much higher-impact failure than missing one R1 cycle.
- *Fix:* use a CLONED Chrome profile created at install (`shutil.copytree` of User Data once → `OpenClawProfile/`), launched via `--profile-directory="OpenClawProfile"`. Document the trade-off (re-login required once at setup, separate paywall whitelists, separate ad-block extensions). This isolates collateral damage.

**H8. R3 cycle math: 5min × ~530 tickers = ~39k Finnhub calls/day; "no new external HTTP calls" is wrong.**
- *Plan quote (§2.C):* `"reuse volume_scanner._fetch_quote ... compute mover_pct ... rank top-30 absolute % movers across S&P 500 ∪ operator's SA portfolio ... No new external API call."`
- *Plan quote (§3.4):* `"R3 reuses the existing volume-scanner quote loop — no new external HTTP calls"`
- *Evidence:* S&P 500 = ~500 tickers; operator's SA portfolio = ~30 (per design). 5min cycles during 6.5h market hours = 78 cycles/day. 78 × 530 = ~41,300 Finnhub `/quote` calls/day for R3 alone. `config/consensus.yaml:240` shows `finnhub: 60` (per-minute rate limit); free-tier ceiling is ~86,400/day. R3 alone consumes ~48% of free-tier daily budget. Volume scanner already runs every 900s (96 cycles/day × N tickers). The combined load is fragile, and every existing Finnhub-dependent path (signal cross-reference, news cascade Tier 1) competes for the same budget.
- *Confidence:* HIGH.
- *Why this matters:* "no new external HTTP calls" is the false load-bearing claim that justified Phase 1 going first. With paid Finnhub it's fine; with free tier it's a regression risk.
- *Fix:* (a) restrict R3 to operator's SA-portfolio universe only (not S&P 500); (b) reduce R3 cadence to market-open + market-close only (2 cycles/day); (c) require paid Finnhub `/stock/market-mover` (OQ-5) for the S&P 500 universe; (d) re-write the §3.4 claim to be honest about the call budget.

---

### MEDIUM Findings (suboptimal but functional)

**M1. `ticker_signals_staging` referenced in §4.4 / §4.6 but missing from Phase 0.3 DDL.**
- *Plan quote (§4.4):* `"add ticker_signals_staging mirroring ticker_signals. Phase 0 ships a config flag desktop_feed.target_table"`
- *Plan quote (§4.6):* `"desktop_feed.target_table=ticker_signals_staging"`
- *Evidence:* Phase 0.3 lists 6 new tables; `ticker_signals_staging` is NOT among them. Phase 0.6 lists ≥7 config keys; `desktop_feed.target_table` is NOT among them. The shadow rollout (§4.6 Day 0) depends on both. Schema/config drift between sections.
- *Fix:* add `ticker_signals_staging` to Phase 0.3 DDL (with identical schema to `ticker_signals`); add `desktop_feed.target_table: ticker_signals_staging` to Phase 0.6 keys.

**M2. Operator's residential IP becomes a single point of failure for R1.**
- *Plan quote (§3.1):* `"the operator's residential IP is the source — no datacenter fingerprint."`
- *Evidence:* if Reddit / SA / Benzinga rate-limit or block the operator's residential IP, this affects EVERY HTTP request the operator makes from that PC, including manual browsing. Plan handles 429/503 with exponential backoff but doesn't address sustained 24h IP blocks.
- *Fix:* document the risk; add a "circuit breaker" — any 403 or persistent 429 → R1 disabled for 7d; recommend a separate Wi-Fi (e.g., phone hotspot) or VPN profile for R1.

**M3. `seen_relay_nonces` sweep cadence undefined; table grows unboundedly.**
- *Plan quote (§3.6 step 4):* `"Reject if nonce already seen in last 24h ... seen_relay_nonces(nonce TEXT PRIMARY KEY, ts REAL)"`
- *Evidence:* 24h replay window stated; pruning query never specified. Without a sweep, the table grows ~1000 rows/day forever.
- *Fix:* add explicit sweep: `DELETE FROM seen_relay_nonces WHERE ts < (now - 86400)` every 1h in `routine_health` heartbeat path; add index on `ts`.

**M4. Outlook `item.Unread = False` can silently fail on Exchange shared mailboxes; reprocessing loops on stuck items.**
- *Plan quote (§2.B.i):* `"Mark items Read only after the relay ack"`
- *Evidence:* COM-marshalled `Unread` write through Exchange shared-mailbox / delegated-access can return success but server-side state remains Unread. Items reprocess every cycle, hitting EntryID-dedup but consuming polling time.
- *Fix:* track successfully-processed EntryIDs in `win_routines.db.email_seen` regardless of Outlook mark-Read success; query against this DB before processing.

**M5. Discord UI dedup composite hash uses `ts` whose source is unspecified — relative vs absolute; locale-dependent.**
- *Plan quote (§2.B.ii):* `"composite key sha1(channel|sender|ts|first40_chars) since the UI doesn't expose message_id"`
- *Evidence:* Discord UI displays times relative ("5 minutes ago") with absolute ts in tooltip. Accessibility tree may give either. Mismatched ts at next poll = duplicate emission.
- *Fix:* spec "use the tooltip-resolved absolute UTC timestamp"; validate the operator's Discord version exposes it via UIA; fallback to system-clock-at-first-seen.

**M6. Email allowlist subject-substring match is OR not AND — false-positive prone.**
- *Plan quote (allowlist):* `"email_subjects_must_contain: ['alert','trade','trigger','$']"`
- *Evidence:* a subject like "$5 lunch deals — last alert!" matches both `$` and `alert`. OR-of-list is too broad; AND-of-list is too strict.
- *Fix:* require `(sender_match) AND (≥1 subject_substring) AND (≥1 ticker extracted)` as a 3-of-3 gate. Spec it in §2.B.i.

**M7. `Buy → BULLISH` mapping IS sentiment inference, just at the schema layer.**
- *Plan quote (§1 Hard Constraint #4):* `"the only non-neutral assignments are publisher-asserted labels (Seeking Alpha 'Buy'/'Sell' rating, Benzinga 'Movers Up'/'Movers Down' tag) — these are pass-throughs, not inferences."`
- *Evidence:* SA "Buy" is the analyst's directional bet; mapping it to `Sentiment.BULLISH` is a schema-level translation. A pure pass-through would be `Sentiment.NEUTRAL` with the rating preserved verbatim in `source_detail` (already done). The translation is convenient for downstream consumers but it IS the kind of "interpretation" the brief tried to forbid.
- *Fix:* set sentiment=NEUTRAL for SA + Benzinga; rely on `source_detail` rating string. Downstream consumers can map their own translation if/when they need it. Removes the sentiment-scoring-creep risk in v1.

**M8. R3 status-rule magic numbers (10min CAUGHT threshold, 5% MISSED-alert threshold) are baked into the plan with no source.**
- *Plan quote (§2.C / §3.6):* `"CAUGHT (≥10min lead), LATE (0–<10min), MISSED ... mover_pct ≥ 5%"`
- *Evidence:* no rationale for 10min vs 5min vs 15min, nor 5% vs 3% vs 7%. These thresholds will drive the operator's perception of "are we catching things" — wrong defaults will produce noise or silence.
- *Fix:* make both thresholds config (`gap_detect.caught_lead_seconds: 600`, `gap_detect.alert_threshold_pct: 5.0` — the latter is in §4.2 0.6, the former is missing); document a 1-week observation period before committing to defaults.

---

### MINOR Findings

- **L1.** Bookmark folder name `"Watchlist Add"` is hard-coded; should be `bookmark.folder_name` config.
- **L2.** §3.6 step 6 calls `db.insert_signal(TickerSignal(...))` but doesn't specify error handling on `Sentiment(...)` / `SourceType(...)` ValueError when the payload contains an unknown enum value. Spec it.
- **L3.** Phase 1.4 says `"extend briefing/alfred.py:19 build_briefing_data"` without specifying signature change vs new return key — clarify.
- **L4.** Phase 4.2 says privacy gate "rejects" on regex match; but `extract_tickers` is run BEFORE the reject path in §2.D. Clarify ordering: regex-block-check FIRST, then ticker extraction (so blocked text never sees `extract_tickers`).

---

### What's Missing (gaps the plan does not address)

1. **Relay-channel auth boundary:** anyone with bot access to the operator's owned server could post a forged `R1_AUTHED_WEB.reddit` payload and inject signals into `ticker_signals`. §3.6 has a quota gate but no auth gate. Recommendation: HMAC the payload with a shared secret stored in `/root/.openclaw/.env`.
2. **Backpressure for `DesktopFeedListener`:** if `db.insert_signal` is slow, no documented backpressure. TweetShift had a similar issue in 2026-04-19 (memory digest §"System Reliability Improvements"). Spec a max-pending-payload counter and an alert when it exceeds threshold.
3. **Windows-side test strategy:** Phase 0–7 plans tests for the engine listener but no Windows-side test path. How does the executor verify Outlook-COM behavior without an actual Outlook? Spec a mock-COM harness.
4. **Graceful Windows shutdown:** if the operator restarts PC mid-cycle, in-memory dedup sets, outbox spool, and Playwright contexts are lost or corrupted. Spec a "save state on SIGTERM" path and a "recover-from-disk" path on restart.
5. **Chrome profile path discovery:** "operator's existing Chrome User Data" varies — `%LOCALAPPDATA%\Google\Chrome\User Data\Default` for default profile, but multi-profile setups break this. Spec discovery logic + config override.
6. **Bookmark `date_added` magnitude:** Chrome stores `date_added` as 100ns-since-1601 (Windows FILETIME), NOT Unix seconds. Phase 5 says `detected_at = bookmark.date_added` — that's wrong by a factor of 10⁷ AND offset by ~369 years. Spec the conversion.
7. **`external_articles_seen` cleanup:** like `seen_relay_nonces`, this table grows unboundedly. Spec a sweep (e.g., 30-day retention).
8. **Clipboard sentinel + locked screen:** §2.D specifies a foreground-app allowlist but lock-screen has no foreground app. Spec fail-safe behavior (default deny when foreground unknown).
9. **Operator dry-run path for the Friday weekend-pause edge case.** §4.6 has 2-week rollout but no targeted test for the schedule-vs-pause collision flagged in C2.
10. **Path-c (bot-relay) and path-b (UI automation) running concurrently for the same channel:** §2.B.ii doesn't spec what happens if a channel is in both lists — duplicate emissions? §3.6 nonce protection covers it incidentally but it's not documented.

---

### Ambiguity Risks (statements with multiple valid interpretations)

- *Quote (§3.2 quota math):* `"count rows where run_started_at >= now - 7*86400 AND status IN ('OK','PARTIAL')"`
  - **Interpretation A:** failed runs do NOT count → effective cap is unbounded if Task Scheduler retries on failure.
  - **Interpretation B:** failed runs count too, but the SQL says otherwise.
  - Risk if A: cap leaks; if B: cap is artificially tight.

- *Quote (§3.6 step 9):* `"Any rejection → log to #system-alerts ... AND return without forwarding."`
  - **Interpretation A:** the relay client receives no negative-ack, treats Discord-post-success as success.
  - **Interpretation B:** the operator manually reads `#system-alerts` and reacts.
  - Risk: silent data loss (interpretation A is what'll happen).

- *Quote (§2.B.ii table):* `"(b) UI automation ... ACCEPTABLE — ToS-safe"`
  - **Interpretation A:** operator OK'd it; ship it.
  - **Interpretation B:** "acceptable in theory, requires per-deployment risk acknowledgement."
  - Risk: ban under interpretation A.

---

### Multi-Perspective Notes

- **Executor:** Phase 1.2 ("thin wrapper around `volume_scanner._fetch_quote`") is unexecutable as written — `_fetch_quote` is a closure (C1). Phase 2.4 ("allowlist file at `/root/.openclaw/local_intel_allowlist.json` shared with R2.B.ii, R4, R6") gives no Windows-side resolution path (H5). Phase 5.1 ("`detected_at = bookmark.date_added`") is a FILETIME→Unix-ts bug waiting to happen (gap #6). Without these clarifications the executor will either ask for blocking guidance or silently improvise.
- **Stakeholder:** the brief was "data access only, no decision-logic changes." The plan front-loads engine work (Phase 0–1) and ships a new alert channel + new briefing section (R3) before any Windows routine lands. The mismatch is not in any single line — it's structural.
- **Skeptic:** strongest argument against the plan is that the bulk of its **value** lives in R1 (web scraping), which has the **highest** ToS / IP-block / collateral-damage risk; meanwhile the plan front-loads engine refactors that don't depend on R1 working. If R1 fails after Phase 6, weeks of engine surface-area changes have shipped for marginal R2/R4/R6 value. An alternative considered? Plan does not compare against "do nothing on Windows; add Polygon news API + paid Reddit/SA/Benzinga API tiers engine-side." That alternative is lower-risk and lower-effort. Plan owes a rejection rationale.

---

### Verdict Justification

**PLAN NEEDS REVISION.**

Realist Check applied to all CRITICAL/HIGH findings. **No downgrades:**
- **C1** (closure not importable) — executor will hit ImportError on first attempt. STAYS CRITICAL.
- **C2** (Friday-15:30 inside weekend pause) — guaranteed quota slot loss + outbox overflow. STAYS CRITICAL.
- **C3** (R3 = decisioning) — direct contradiction with operator brief. STAYS CRITICAL.
- **C4** (Phase 0 scope creep) — direct contradiction with operator brief. STAYS CRITICAL.
- **H1–H8** all survived pressure-test; no realistic mitigation reduces severity below HIGH.

Mode escalation to ADVERSARIAL was triggered after C1 + C2 surfaced (≥3 MAJOR + systemic-pattern criterion); subsequent passes specifically hunted for cumulative-scope-creep evidence (yielding C3 + C4) and quota-math failures (yielding H8) that thorough-mode often misses.

**For the verdict to upgrade to PLAN READY:** all four CRITICAL findings must be resolved; H1–H8 must be addressed (severity-class softening for H3, IP-isolation for M2/H7, cross-host-allowlist spec for H5, etc.); and the specific minor schema-drift items (M1) must be corrected. Estimate: ~1 day of planner revision.

**For the verdict to upgrade to ACCEPT-WITH-RESERVATIONS** (instead of PLAN READY): only C1–C4 must be resolved; H/M items can be tracked as known follow-ups in an explicit "phase 1.5 hardening" insert.

The plan is structurally sound (good staging, good rollout cadence, clear definition of done, honest open-question handling). The findings above are not a critique of the planner — they are the gap between an excellent plan-as-document and the operator's stricter brief.

---

### Open Questions (unscored — for operator / planner before re-review)

- Does the operator accept `#gap-alerts` as in-scope for "data access only"? If yes, C3 is reduced to a clarifying note. If no, R3 must defer all notification surface to v2.
- Does the operator accept the Phase-0 engine surface-area as in-scope? If yes, C4 is reduced to a clarifying note. If no, Phase 0 must be re-scoped per the C4 fix.
- Does the operator have paid Finnhub access (OQ-5)? If yes, H8 is fully mitigated.
- What is the operator's actual Reddit/SA/Benzinga API access status? The plan assumes "scrape only"; an API path may exist that lowers H6/H7/M2 risk dramatically.
- Is the operator's home internet on a shared residential IP (cable/fiber) or a dedicated link? Affects M2 severity.
- Does the operator already use Syncthing for `/root/.openclaw/`? Affects H5 fix path.

---

*End of Adversarial Review. Reviewed by critic, Stage 4/4. Stage gate: PLAN NEEDS REVISION. Recommend planner revision before executor handoff.*
