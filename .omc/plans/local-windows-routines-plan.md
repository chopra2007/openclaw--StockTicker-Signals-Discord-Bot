# Local-Windows Routines — Final Execution Plan (v2)

**Date:** 2026-04-30
**Stage:** 3/4 (Plan) — feeds critic (stage 4)
**Revision:** v2 — revises v1 per adversarial review C1-C4 + H1-H8 (2026-04-30)
**Authors:** planner, synthesizing explorer (#1) + architect (#2)
**Inputs:**
- `/root/.openclaw/workspace/.omc/plans/local-win-routines-discovery.md`
- `/root/.openclaw/workspace/.omc/plans/local-win-routines-designs.md`
**Scope:** Pure data ingestion + observability. NO changes to trading logic, sentiment scoring, or alert decisioning.

---

## Hard Constraints (enforced throughout)

1. **15 runs/week cap on R1 (web scraping).** Hard ceiling. **All R1 invocations count toward the cap regardless of outcome status.** Gate enforced client-side (per-routine counter in `win_routines.db`) and server-side (relay listener hard-rejects R1 messages over quota — not advisory). See §3.2 for explicit schedule and buffer math.

2. **Stop-and-log on first failure — IMMEDIATE, no retry accumulation.** Any failure stops the current run immediately. Tiered semantics:
   - **Class A (anti-bot / auth / structural):** auth-expired, verification challenge (CAPTCHA, "are you human"), HTTP 403, layout-drift (required selector missing). One strike → stop run immediately → pause routine 24h → notify `#system-alerts`. **Operator must manually clear `paused_until` to resume. No auto-resume.**
   - **Class B (transient network):** connection reset, DNS failure, HTTP 5xx (non-403). One strike → stop current cycle → notify `#system-alerts` → next scheduled slot runs normally. Three consecutive B-class failures on the same scheduler slot → escalate to Class A treatment.

3. **Output conforms EXACTLY to OpenClaw ingestion path.** Every signal lands via `db.insert_signal(TickerSignal)` at `consensus_engine/db.py:700`. The Windows side never writes to the engine DB directly — it emits a Discord-relay JSON payload (§3.6) which the new `DesktopFeedListener` validates and forwards into `db.insert_signal(...)` server-side.

4. **NO trading logic, sentiment scoring, or alert decisioning changes.** New `SourceType` enum values are pure routing tags. **All new routines use `Sentiment.NEUTRAL`.** Publisher-asserted labels (SA `Buy`/`Sell`, Benzinga `Movers Up/Down`) are preserved verbatim in `source_detail` only — no mapping to BULLISH/BEARISH in v1. Downstream consumers own that translation.

5. **Engine changes only when a v1 Windows routine cannot work without them.** Phase 0 adds minimum viable foundation. No speculative engine surface-area.

---

## 1. System Discovery Findings

Pulled from `local-win-routines-discovery.md`. All paths are absolute.

### 1.1 The single ingestion choke point

Every signal source funnels through ONE function:

```python
# consensus_engine/db.py:700
async def insert_signal(signal: TickerSignal):
    db = await get_db()
    await db.execute(
        """INSERT INTO ticker_signals (ticker, source_type, source_detail, raw_text,
                                       sentiment, detected_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (signal.ticker, signal.source_type.value, signal.source_detail,
         signal.raw_text[:2000],
         signal.sentiment.value, signal.detected_at, signal.expires_at),
    )
    await db.commit()
```

**Implications:**
- `raw_text` truncated to 2000 chars server-side; Windows clients pre-truncate to keep relay payloads small.
- `expires_at` is `detected_at + 7200` (2h TTL) — implicit dedup mechanism.
- New routines append rows; NEVER replace this insert path.

### 1.2 SourceType enum — actual contents

`consensus_engine/models.py:9–18` defines exactly **9 values**:

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

This plan adds **2 new values in Phase 0** per C4 minimum-viable-engine principle. Sub-source distinction encoded in `source_detail` via `via:<tag>` suffix.

### 1.3 Sidecar tables this plan touches

| Table | Purpose | Phase added |
|---|---|---|
| `ticker_signals` | primary signal store (existing) | — |
| `reddit_posts` | per-post archive (existing) | — |
| `ticker_signals_staging` | **NEW** — shadow-rollout target | Phase 0 |
| `seen_relay_nonces` | **NEW** — replay protection for DesktopFeedListener | Phase 0 |
| `routine_health` | **NEW** — heartbeat/error counters | Phase 0 |
| `gap_reports` | **NEW** — R3 missed-opportunity store (DB-only) | Phase 0 |
| `email_signals` | **NEW (optional)** — Outlook-side searchability | Phase 2 |
| `seen_discord` | **NEW** — message_id dedup for R2 Discord paths | Phase 3 |
| `external_articles_seen` | **NEW** — URL-hash dedup for SA + Benzinga | Phase 5 |

`tracked_tickers` (TradingView watchlist mirror) — deferred to v2 with R5.

### 1.4 The `get_social_signals` query — explicit IN list at `db.py:783`

Must be expanded to include `'desktop_auth'` and `'desktop_local'` when routines ship. Tracked as Phase-0 prerequisite in §4.

### 1.5 Existing transport pattern: `DiscordTweetShiftListener`

`consensus_engine/scanners/discord_tweetshift.py:133` — Discord Gateway listener with proven reconnect-counter / stuck-loop detection (added 2026-04-19). **This is the exact pattern reused for `DesktopFeedListener`.** Same auth, same retry semantics, zero new attack surface.

### 1.6 Reference patterns this plan reuses

| Pattern | File | Reused for |
|---|---|---|
| Reddit ticker extraction | `consensus_engine/scanners/social.py:46–103` | server-side fan-out in DesktopFeedListener |
| News URL-hash dedup | `consensus_engine/scanners/news.py:1–80` | `external_articles_seen` (Phase 5) |
| Form-4 watcher loop shape | `consensus_engine/main.py:226–291` | R3 gap-detect loop |
| Finnhub quote adapter | `consensus_engine/api_adapters.py:59 (FinnhubAdapter._fetch_quote)` + `api_adapters.py:273 (get_live_quote_price)` | new `utils/quote_fetcher.py` for R3 |
| `extract_tickers()` | `consensus_engine/utils/tickers.py:86–112` | **engine-side only** — NOT ported to Windows |

**Note on extract_tickers (H4 resolution):** Windows routines do NOT run `extract_tickers` locally. They emit raw_text in relay payloads. `DesktopFeedListener` calls `extract_tickers(payload["raw_text"])` server-side and creates one `TickerSignal` per extracted ticker. Single source of truth, zero drift, zero blacklist-bypass risk.

---

## 2. Refined Routine Designs

### 2.A R1 — Authenticated Multi-Source Web (`R1_AUTHED_WEB`)

**Runtime:** Windows PC, dedicated Playwright Chrome profile (see §3.1 — NOT the operator's daily-use profile).
**Quota:** 15 runs/week hard ceiling (all invocations count). 13 auto-scheduled + 2 on-demand retry slots.
**Per-run targets:** 5 subreddits + 3 SA tickers + 3 Benzinga tickers. Wall-clock ≤ 6 min/run.

**Interaction style:** realistic human reading and scrolling cadence so the routine does not produce a request flood that would degrade target-site service or trigger their abuse-control systems. The persistent session is the operator's own logged-in browser session (in a dedicated profile), used to access content the operator already has authorized read access to.

**Sub-target 1.A.i — Reddit (authenticated)**
- Seed list from `config/consensus.yaml:114–127` `social.subreddits` (SSH-cached at startup; shared source of truth with disabled engine scanner).
- Per subreddit: `https://www.reddit.com/r/{sub}/new/?limit=100`, scroll loop, extract from `[data-testid="post-container"]`.
- Output → `TickerSignal(source_type=DESKTOP_AUTH, source_detail="r/{sub}|post:{id}|u/{author}|score:{n}|comments:{n}|via:reddit_authed", sentiment=NEUTRAL, raw_text=<title+body[:1000]>)`. Server-side `extract_tickers` fans out per ticker.
- Sidecar: `reddit_posts` archive row via existing `INSERT OR IGNORE` on `id`.

**Sub-target 1.A.ii — Seeking Alpha**
- Seed = operator's SA "My Portfolio" page (~20–40 tickers, scope-bounded).
- Per ticker: `https://seekingalpha.com/symbol/{TICKER}/analysis` → headline, author, rating, preview.
- Output → `TickerSignal(source_type=DESKTOP_AUTH, source_detail="sa|{author}|rating:{r}|{url}|via:seeking_alpha", sentiment=NEUTRAL, raw_text=<headline+preview[:1000]>)`. Rating preserved verbatim in `source_detail`.
- Dedup: SHA1 of canonical URL into `external_articles_seen`.

**Sub-target 1.A.iii — Benzinga**
- Per ticker: `https://www.benzinga.com/quote/{TICKER}` + once-per-run `https://www.benzinga.com/movers/large-cap`.
- Output → `TickerSignal(source_type=DESKTOP_AUTH, source_detail="benzinga|{src}|{pro_tag}|{url}|via:benzinga", sentiment=NEUTRAL, raw_text=<headline[:1000]>)`. Tag preserved verbatim.
- Dedup: same `external_articles_seen` URL-hash table.

**Verification-challenge policy:** if a target site presents any verification challenge mid-run (CAPTCHA, "are you human", login wall), that is a STOP signal — the routine logs and exits immediately. The operator handles it manually. The routine does not attempt to work around verification challenges.

**STOP_AND_LOG triggers — tiered:**

| Trigger | Class | Detection | Action |
|---|---|---|---|
| Auth expired | **A** | login link visible OR HTTP 403 | stop → 24h pause → `#system-alerts` |
| Verification challenge | **A** | recaptcha iframe / challenge element | stop → 24h pause → `#system-alerts` |
| Layout drift | **A** | required selector missing | stop → 24h pause → tag `layout_change` |
| HTTP 429 | **B** | HTTP status | stop cycle → `#system-alerts` → next slot |
| HTTP 5xx | **B** | HTTP status | stop cycle → `#system-alerts` → next slot |
| Quota exhausted | — | invocations ≥ 15 in rolling 7d | hard refuse start; `{"alert":"R1_quota_exhausted"}`; resume next ISO week |

### 2.B R2 — Local Intelligence (`R2_LOCAL_INTEL`)

**Sub-routine 2.B.i — Email via Outlook desktop COM (`pywin32`)**
- Path: `outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")` → `inbox = outlook.GetDefaultFolder(6)`.
- Cycle: every 60s, `inbox.Items.Restrict("[Unread]=true AND [ReceivedTime]>'<last_cycle_iso>'")`.
- Filter gate (3-of-3): sender allowlist match AND ≥1 subject substring AND ≥1 ticker extracted server-side.
- **Relay-before-mark-Read protocol (H2):**
  1. Relay item payload to `#desktop-feed`.
  2. Wait up to 10s for explicit ACK on `#desktop-feed-acks` keyed to the payload nonce.
  3. ACK received → mark `item.Unread = False`.
  4. NACK or timeout → do NOT mark Read. Log failure. Leave item Unread for operator visibility.
- Dedup: `(EntryID, ticker)` in `win_routines.db.email_seen`. Checked BEFORE relay, regardless of Outlook state — handles Exchange shared-mailbox case where server-side `Unread` state may not sync.
- Output → `TickerSignal(source_type=DESKTOP_LOCAL, source_detail="email|from:{addr}|subj:{subj[:80]}|via:outlook", sentiment=NEUTRAL, detected_at=item.ReceivedTime.timestamp())`.

**Sub-routine 2.B.ii — Discord (hybrid, ToS-aware)**

| Path | Verdict | Use for |
|---|---|---|
| **(a) User-token automation** | **REJECTED** — explicit ToS violation, account-ban risk | nothing |
| **(b) UI automation** (`pywinauto` UIA backend) | **OPERATOR RISK DECISION REQUIRED** — see ToS note below | operator-opt-in only; DMs + external servers with no bot access |
| **(c) Bot-relay** | **RECOMMENDED** — fully ToS-compliant for operator-owned channels | channels operator owns or can invite a bot to |

**Discord UI automation ToS note (H6):** Discord's Acceptable Use policy prohibits automated processes accessing the service via a user's authenticated session. UI automation via `pywinauto` reads Discord's accessibility tree through the operator's authenticated session — non-zero account-action risk, consistent with past enforcement against similar tooling. **The operator must explicitly acknowledge this risk and enable path (b) per-channel via config (`discord_ui_enabled: true` in allowlist) before it is active.** If an account action is taken, path (b) is permanently disabled. Default is `false`.

**Primary path = (c) bot-relay.** New `DiscordLocalIntelListener` mirrors `DiscordTweetShiftListener`; listens on channel ID list from `local_intel.bot_channels` config; calls `db.insert_signal(...)` directly.

**Secondary path = (b) UI automation (operator-opt-in).** Polls every **300s** (5 min minimum — not 30s). Composite dedup key `sha1(channel|sender|tooltip_utc_ts|first40_chars)` using tooltip-resolved absolute UTC timestamp.

- Output → `TickerSignal(source_type=DESKTOP_LOCAL, source_detail="discord|{channel}|user:{author}|via:{bot|ui}", sentiment=NEUTRAL)`.
- Dedup: `seen_discord(message_id TEXT PRIMARY KEY, ts REAL)` with 24h sweep.

**Allowlist file + Windows path (H5):**
```json
{
  "email_senders": ["alerts@analyst1.com", "*@premiumstocks.io"],
  "email_subjects_must_contain": ["alert","trade","trigger","$"],
  "discord_bot_channels": ["1234567890"],
  "discord_ui_channels": [{"server":"FriendsServer","channel":"options-alerts"}],
  "discord_ui_enabled": false,
  "bookmark_folder_name": "Watchlist Add"
}
```
File lives at `/root/.openclaw/local_intel_allowlist.json` on the Linux server. Windows routines resolve it via `local_intel.allowlist_windows_path` in `config/consensus.yaml` (e.g., `C:\Users\<operator>\AppData\Roaming\openclaw\local_intel_allowlist.json`). Operator is responsible for keeping in sync (Syncthing if already in use, or rsync). Alternatively: leave `allowlist_windows_path` empty and enforce allowlist server-side in `DesktopFeedListener` only — Windows routines emit everything, server filters.

### 2.C R3 — Observability + Gap Detection (`R3_GAP_DETECT`)

**Engine-side only — no Windows surface.** Cadence: **market-open (09:30 ET) and market-close (15:45 ET) only** — 2 cycles/market-day (replaces original 5-min cadence; see H8 call-budget math in §3.4).

**R3 is DB-only in v1.** Writes to `gap_reports` table only. **No `#gap-alerts` Discord post. No Alfred briefing extension.** These are decisioning surfaces and require a separate explicit operator-approved ticket (v1.1). Operator queries `gap_reports` directly.

**Top movers source:** New module `consensus_engine/utils/quote_fetcher.py` — importable wrapper around `FinnhubAdapter` from `consensus_engine/api_adapters.py:59`. Fetches `c` (current price) and `pc` (previous close) fields. **No edits to `api_adapters.py` or `volume_scanner.py`.** Scope: **operator's SA portfolio only** (~30 tickers) — NOT S&P 500. Compute `mover_pct = (c - pc) / pc`; rank by absolute `mover_pct`; take top-20. If operator confirms paid Finnhub (OQ-5), swap to `/stock/market-mover` for S&P 500 via `finnhub.has_market_mover_endpoint: true`.

**Finnhub call budget (H8):** ~30 tickers × 2 cycles/day = **60 Finnhub calls/day** added by R3. Free-tier ceiling ~86,400/day; 60 is negligible. The S&P 500 path (500 × 78 cycles/day = ~39,000 additional calls/day) is NOT in v1. The prior plan's claim of "no new external HTTP calls" was incorrect; this corrects it.

**Cross-reference query (per mover ticker):**
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

**Outputs:**
1. `gap_reports` row per ticker per cycle.
2. Status: `CAUGHT` (≥ `gap_detect.caught_lead_seconds` lead; default 600s), `LATE` (0–<600s), `MISSED` (no row in window).
3. No Discord post. No Alfred change. `gap_detect.alert_threshold_pct` config key reserved for v1.1 only.

### 2.D R4 — Clipboard Sentinel (`R4_CLIPBOARD`)

- `pywin32` clipboard-changed message hook (zero-poll).
- **Privacy gate runs FIRST — before any extraction:** hard-reject regex match for credit-card / SSN / password patterns; foreground-app allowlist (Chrome, Edge, Outlook, Discord, Bloomberg Terminal, ThinkOrSwim). **Default deny when foreground unknown** (lock screen, unrecognized app). On reject: log routine name only, never raw text.
- Gate passes → relay `raw_text` (≤500 chars); server-side `extract_tickers` fans out per ticker.
- If 0 tickers extracted server-side: no `ticker_signals` row (payload is a no-op).
- Output → `TickerSignal(source_type=DESKTOP_LOCAL, source_detail="clipboard|app:{foreground_window_title[:60]}|via:clipboard", sentiment=NEUTRAL)`.
- Dedup: in-memory set of `sha1(raw_text)`, 5-min TTL.

### 2.E R6 — Browser Bookmark Sentinel (`R6_BOOKMARK`)

- Watch `%LOCALAPPDATA%\Google\Chrome\User Data\OpenClawProfile\Bookmarks` (dedicated profile — see §3.1) for mtime change.
- Diff folder named per `bookmark_folder_name` in allowlist (default `"Watchlist Add"`) against `win_routines.db.bookmarks_seen(id PRIMARY KEY)`.
- For each new bookmark: aiohttp fetch URL → parse `<title>` + og:description → relay raw_text; server-side `extract_tickers` fans out.
- `date_added` FILETIME conversion: `unix_ts = (date_added / 10_000_000) - 11644473600`. Use as `detected_at`.
- Output → `TickerSignal(source_type=DESKTOP_LOCAL, source_detail="bookmark|{domain}|{url}|via:bookmark", sentiment=NEUTRAL)`.

### 2.F Deferred to v2

| Routine | Reason |
|---|---|
| R5 TradingView Watchlist Mirror | Effort=M, value=M. LevelDB format fragile. R1.A.ii SA portfolio serves same purpose. |
| R7 System-Audio Podcast Capture | Effort=H. Whisper.cpp, audio-device dance, continuous CPU. Own resource gate needed. |

### 2.G Routine summary matrix

| Routine | Source | `SourceType` | New table | Dedup | Cadence | Quota |
|---|---|---|---|---|---|---|
| R1.A.i Reddit-authed | reddit.com | `DESKTOP_AUTH` | reuse `reddit_posts` | post_id | within R1 run | counts toward 15/wk |
| R1.A.ii Seeking Alpha | seekingalpha.com | `DESKTOP_AUTH` | `external_articles_seen` | URL hash | within R1 run | counts toward 15/wk |
| R1.A.iii Benzinga | benzinga.com | `DESKTOP_AUTH` | reuse `external_articles_seen` | URL hash | within R1 run | counts toward 15/wk |
| R2.B.i Email | Outlook COM | `DESKTOP_LOCAL` | `email_signals` (optional) | EntryID | 60s | unbounded (passive) |
| R2.B.ii Discord (bot) | Discord Bot API | `DESKTOP_LOCAL` | `seen_discord` | message_id | event | unbounded (passive) |
| R2.B.ii Discord (UI) | Discord desktop UIA | `DESKTOP_LOCAL` | `seen_discord` | composite hash | 300s; opt-in only | unbounded (passive) |
| R3 Gap-detect | engine-internal | n/a | `gap_reports` | (ticker, cycle_id) | mkt-open + mkt-close (2/day) | unbounded (engine-side) |
| R4 Clipboard | OS clipboard | `DESKTOP_LOCAL` | none | in-mem sha1 5min | event | unbounded (passive) |
| R6 Bookmark | Chrome JSON | `DESKTOP_LOCAL` | none | bookmark_id | mtime event | unbounded (passive) |

---

## 3. Optimizations & New Ideas

### 3.1 Anti-bot patterns (R1)

- **Per-site cadence jitter.** Reddit 7–11 min, SA 12–18 min, Benzinga 9–14 min. Random uniform, never fixed.
- **Fingerprint hygiene.** `playwright_stealth.Stealth().apply_stealth_async(page)` per CLAUDE.md. User-Agent inherited from dedicated profile; never override.
- **Dedicated Chrome profile (H7 — required).** R1 uses a DEDICATED Chrome profile created at install, separate from operator's daily-use profile. Setup: `shutil.copytree("...\\Default", "...\\OpenClawProfile")` — one-time copy. Trade-offs: re-login required once per site; separate extensions/cookies. **Benefit: collateral damage to daily browsing is impossible.** R6 bookmark path also uses `OpenClawProfile\Bookmarks`. Launch: `playwright.chromium.launch_persistent_context(user_data_dir=<profile_root>\\OpenClawProfile, channel="chrome")`.
- **Mouse jitter & scroll pacing.** `page.mouse.move(x,y,steps=N)` with `N∈[8,14]`. `asyncio.sleep(uniform(0.7,1.4))` between scrolls. `uniform(2.5,5.0)`s dwell after scroll loop.
- **Tab discipline.** New tab per subreddit / per ticker. Never >3 tabs open. Close on completion.
- **Hard subordinate caps.** ≤3 subs/min, ≤4 SA tickers/min, ≤6 Benzinga tickers/min.

### 3.2 Tab/timing strategy under the 15-runs/week cap

**All R1 invocations count — any status.** Schedule 13 auto-runs, preserving 2 on-demand retry slots.

| Day | Run 1 (premkt) | Run 2 (midday) | Run 3 (power hour) | Auto-scheduled |
|---|---|---|---|---|
| Mon | 09:25 ET | 12:00 ET | 14:30 ET | 3 |
| Tue | 09:25 ET | 12:00 ET | 14:30 ET | 3 |
| Wed | 09:25 ET | 12:00 ET | 14:30 ET | 3 |
| Thu | 09:25 ET | 12:00 ET | 14:30 ET | 3 |
| Fri | 09:25 ET | — | — | 1 |
| Sat | — | — | — | 0 |
| Sun | — | — | — | 0 |
| **Week total** | | | | **13 auto + 2 on-demand = 15 ceiling** |

**Friday (C2 fix):** Reduced to 1 auto-run (premarket only). Weekend-pause starts Friday 15:00 ET (`main.py:91–101`). Single Fri premkt run eliminates any timing collision with the pause window.

**Weekend-pause + DesktopFeedListener (C2 fix):** `DesktopFeedListener` is wired into the **weekend-pause branch** at `main.py:415–437` so passive routines (R2-Email, R2-Discord-bot, R4, R6) continue writing to `ticker_signals` during the Fri-15:00–Sun-14:00 ET window. Weekend ingestion still writes to `ticker_signals`; only the active scanners (volume scanner, social scanners) pause. **R1 cannot fire during weekend pause** — client-side gate checks `is_weekend_pause()` before launching and refuses if true.

**Windows outbox during weekend pause:** Passive routines buffer to `win_routines.db.outbox`. Cap raised from 200 to **1,000 messages** (~47h × ~1 passive signal/3min ≈ 940 max). Alert at 900 (90% fill). Engine drains outbox on Sunday 14:00 ET when `DesktopFeedListener` resumes.

**Quota enforcement (defense-in-depth):**
- *Client-side:* count ALL rows in `win_routines.db.r1_runs` where `run_started_at >= now - 7*86400` (any status); refuse if ≥15.
- *Server-side hard-cap:* `DesktopFeedListener` hard-rejects R1 payloads if rolling 7-day R1 count ≥15. Posts `{"alert":"R1_quota_exceeded_server_side"}`. Hard-reject — payload dropped.

### 3.3 Reliability & failure semantics

**Stop-on-first-failure (H3).** `_safe_run()` wrapper:
1. Catches `Exception`, classifies as Class A or B (§1 Hard Constraint #2).
2. **Class A:** write to `routine_health` with traceback; flip `paused_until = now + 86400`; post `{"alert":"R{n}_CLASS_A_PAUSE","reason":<traceback head>}` to `#system-alerts`. **Operator must clear `paused_until` manually. No timer-based auto-resume.**
3. **Class B:** write to `routine_health`; post `{"alert":"R{n}_B_FAILURE"}` to `#system-alerts`; do NOT pause. Three consecutive B-class on same scheduler slot → Class A treatment.

**Outlook relay-ACK / NACK (H2):**
- `DesktopFeedListener` posts `{"ack": <nonce>}` to `#desktop-feed-acks` after successful `db.insert_signal`.
- On rejection: posts `{"nack": <nonce>, "reason": <...>}` to `#desktop-feed-acks`.
- Windows relay client waits ≤10s for ACK/NACK. ACK → mark Read. NACK or timeout → leave Unread, log failure.

**Fallback / outbox:** Discord transport primary. If relay channel unreachable >2 min → buffer to `win_routines.db.outbox` (1,000-message cap). Alert at 900. Beyond cap: drop oldest, emit `{"alert":"R{n}_outbox_overflow"}`.

**Heartbeats:** every routine writes `routine_health(routine_id, last_cycle_started, last_success_at, errors_in_cycle, paused_until)` every 60s.

**Stuck-loop alarm:** >5 consecutive reconnects/restarts without a successful signal emit → `{"alert":"R{n}_STUCK_LOOP"}`.

**`seen_relay_nonces` sweep:** `DELETE FROM seen_relay_nonces WHERE ts < (now - 86400)` runs every 1h in heartbeat path. Index on `ts`. Same 24h sweep for `seen_discord`; 30-day sweep for `external_articles_seen`.

### 3.4 Performance

- **Sequential within R1, parallel across routines.** R1 sub-targets run sequentially inside one Playwright context. Different routines (R2/R4/R6) run as separate processes.
- **Browser context reuse.** One persistent `BrowserContext` for R1's lifetime; tabs created/closed per target.
- **Headful on dedicated OpenClawProfile.** Headless is detectable. Correctness over throughput.
- **Engine-side cost.** R3 adds **60 Finnhub calls/day** (30 SA-portfolio tickers × 2 cycles). Not zero — the v1 plan's "no new external HTTP calls" claim was wrong. Free-tier ~86,400/day ceiling; 60 calls is negligible headroom impact. S&P 500 path deferred to paid tier.

### 3.5 Desktop-only opportunities — effort × value scoring

| ID | Routine | Effort | Value | Score | Phase |
|---|---|---|---|---|---|
| R4 | Clipboard sentinel | S | H | **HH** | **v1** |
| R6 | Bookmark sentinel | S | H | **HH** | **v1** |
| R5 | TradingView watchlist mirror | M | M | MM | v2 |
| R7 | System-audio podcast capture | H | M | LM | v2 |

### 3.6 Transport: Discord-relay payload format

**Channel:** `#desktop-feed` (operator's owned server). Engine-side `DesktopFeedListener` (`consensus_engine/scanners/discord_desktop_feed.py`) mirrors `DiscordTweetShiftListener`.

**Primary payload (no client-side ticker field; server-side extract_tickers fans out):**
```json
{
  "v": 1,
  "src": "R1_AUTHED_WEB.reddit",
  "source_type": "desktop_auth",
  "source_detail": "r/wallstreetbets|post:1abc23|u/dfv|score:842|comments:1245|via:reddit_authed",
  "raw_text": "Title here\n\nbody text here…",
  "sentiment": "neutral",
  "detected_at": 1714521600.123,
  "nonce": "01HXYZ…"
}
```

**Sidecar `reddit_posts` payload:**
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

**`external_articles_seen` dedup payload:**
```json
{
  "v": 1,
  "sink": "external_articles_seen",
  "url_hash": "<sha1 hex>",
  "source": "seeking_alpha",
  "first_seen": 1714521600.123
}
```

**ACK/NACK (posted by DesktopFeedListener to `#desktop-feed-acks`):**
```json
{"ack": "01HXYZ…"}
{"nack": "01HXYZ…", "reason": "source_type_unknown"}
```

**Listener-side validation (`DesktopFeedListener.handle_message`):**
1. Reject if `v != 1`.
2. Reject if `src` not in `{R1_AUTHED_WEB.reddit, R1_AUTHED_WEB.sa, R1_AUTHED_WEB.bnz, R2_LOCAL_INTEL.email, R2_LOCAL_INTEL.discord_ui, R4_CLIPBOARD, R6_BOOKMARK}`.
3. Reject if `source_type` not in `{desktop_auth, desktop_local}`.
4. Reject if `nonce` already in `seen_relay_nonces` (24h window).
5. Quota gate: if `src` starts `R1_*`, hard-reject if rolling 7-day R1 count ≥15.
6. On valid primary payload: `tickers = extract_tickers(payload["raw_text"])`. For each ticker:
   ```python
   await db.insert_signal(TickerSignal(
       ticker=ticker,
       source_type=SourceType(payload["source_type"]),   # ValueError → NACK
       source_detail=payload["source_detail"],
       raw_text=payload["raw_text"],
       sentiment=Sentiment(payload["sentiment"]),          # ValueError → NACK
       detected_at=payload["detected_at"],
   ))
   ```
   If `SourceType(...)` or `Sentiment(...)` raises `ValueError`: log + post NACK, do not raise unhandled exception.
7. After all inserts: post `{"ack": payload["nonce"]}` to `#desktop-feed-acks`.
8. `sink: reddit_posts` → `await db.insert_reddit_posts([{...}])`.
9. `sink: external_articles_seen` → `INSERT OR IGNORE INTO external_articles_seen (url_hash, source, first_seen) VALUES (?, ?, ?)`.
10. Any rejection → post `{"nack": nonce, "reason":<...>}` to `#desktop-feed-acks` AND `{"alert":"desktop_feed_rejected","reason":<...>,"payload_excerpt":<first 200 chars>}` to `#system-alerts`.

---

## 4. Execution Plan

### 4.1 Open-question resolutions (consolidated, applied)

| OQ | Question | Resolution | Rationale |
|---|---|---|---|
| 1 | SourceType enum: extend or reuse? | **Extend minimally.** 2 new values in Phase 0: `DESKTOP_AUTH` + `DESKTOP_LOCAL`. Sub-source distinction via `source_detail` `via:<tag>`. Update `models.py:9–18` AND `db.py:783` IN-list. | Minimum engine surface-area (C4). Typed routing preserved. Per-source analytics via `source_detail` filter. |
| 2 | SA/Benzinga publisher-asserted sentiment | **All new routines: `Sentiment.NEUTRAL`.** Publisher labels verbatim in `source_detail` only. | Hard constraint #4. Any BULLISH/BEARISH mapping is schema-level interpretation. Safe default is NEUTRAL. |
| 3 | SA/Benzinga dedup key | **URL-hash in `external_articles_seen`.** | Mirrors news-cascade pattern; cross-source dedup when SA + Benzinga syndicate same wire. |
| 4 | SA seed list | **Operator's SA portfolio** (~20–40 tickers). | Scope-bounded; desktop-only premise; avoids hammer-scrape. |
| 5 | Finnhub paid tier? | **Defer to operator.** Ships with SA-portfolio universe (60 calls/day); flip `finnhub.has_market_mover_endpoint: true` if paid. | Free-tier path verified against call budget (H8). |
| 6 | Bookmark sentiment | **`NEUTRAL`.** | No sentiment scoring changes. Downstream weighting can boost via `source_type=DESKTOP_LOCAL`+`via:bookmark`. |
| 7 | Transport | **Discord-relay.** | Reuses TweetShift listener; zero new attack surface; proven reconnect logic. |
| 8 | R7 audio in v1? | **No — defer to v2.** | Effort=H, value=M. |
| H4 | extract_tickers — shared or ported? | **Engine-side only.** Windows emits raw_text; DesktopFeedListener fans out per ticker. | Single source of truth, zero drift, zero blacklist-bypass risk. |

### 4.2 Build order

**Phase 0 — Minimum Viable Foundation (engine-side; no Windows code yet)**
- **0.1** Extend `SourceType` enum in `consensus_engine/models.py:9–18` with exactly **2 new values**: `DESKTOP_AUTH = "desktop_auth"`, `DESKTOP_LOCAL = "desktop_local"`. No additional values in Phase 0.
- **0.2** Update `db.py:783` `get_social_signals` IN-list to include `'desktop_auth', 'desktop_local'`.
- **0.3** New tables in `db.py` schema-init:
  - `routine_health(routine_id TEXT PRIMARY KEY, last_cycle_started REAL, last_success_at REAL, errors_in_cycle INTEGER DEFAULT 0, paused_until REAL)`
  - `seen_relay_nonces(nonce TEXT PRIMARY KEY, ts REAL NOT NULL)` + `CREATE INDEX IF NOT EXISTS idx_srn_ts ON seen_relay_nonces(ts)`
  - `ticker_signals_staging` (identical schema to `ticker_signals` — shadow-rollout target)
  - `gap_reports(id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, mover_pct REAL, current_price REAL, prev_close REAL, first_source TEXT, first_source_detail TEXT, first_seen_at REAL, detection_delay_sec REAL, total_signals INTEGER, sources_hit TEXT, report_generated_at REAL, status TEXT)`
  - All other tables (`external_articles_seen`, `seen_discord`, `email_signals`) added in the phase that first requires them.
- **0.4** New scanner `consensus_engine/scanners/discord_desktop_feed.py` modeled on `discord_tweetshift.py:133`. Implements §3.6 validation + ACK/NACK + `extract_tickers` fan-out + `seen_relay_nonces` sweep. Wired into `main.py` in **both** the standard background-watchers path AND the weekend-pause branch at `main.py:415–437` (C2 fix).
- **0.5** Config additions to `config/consensus.yaml`:
  - `desktop_feed.enabled: true`
  - `desktop_feed.channel_id: $DISCORD_DESKTOP_FEED_CHANNEL_ID`
  - `desktop_feed.acks_channel_id: $DISCORD_DESKTOP_FEED_ACKS_CHANNEL_ID`
  - `desktop_feed.r1_weekly_quota: 15`
  - `desktop_feed.target_table: ticker_signals_staging`
  - `local_intel.allowlist_path: /root/.openclaw/local_intel_allowlist.json`
  - `local_intel.allowlist_windows_path: ""`
  - `local_intel.bot_channels: []`
  - `gap_detect.enabled: true`
  - `gap_detect.window_hours: 4`
  - `gap_detect.caught_lead_seconds: 600`
  - `gap_detect.alert_threshold_pct: 5.0` (reserved for v1.1; unused in v1)
  - `finnhub.has_market_mover_endpoint: false`
- **0.6** New env vars in `/root/.openclaw/.env`: `DISCORD_DESKTOP_FEED_CHANNEL_ID`, `DISCORD_DESKTOP_FEED_ACKS_CHANNEL_ID`.
- **0.7** Deferred-task entry per CLAUDE.md: one-shot weekly audit task via `/root/task_system/scripts/create_task.sh` confirming R1 rolling-7d counter resets correctly.

**Phase 1 — R3 Gap Detection (engine-only)**
- **1.1** New `consensus_engine/utils/quote_fetcher.py` — importable wrapper around `FinnhubAdapter` from `api_adapters.py:59`. Public interface: `async def fetch_quote(session: aiohttp.ClientSession, ticker: str, api_key: str) -> dict | None` returning Finnhub `/quote` fields (`c`, `pc`, `h`, `l`, `o`, `t`). **No edits to `api_adapters.py` or `volume_scanner.py`.** `quote_fetcher.py` imports `FinnhubAdapter` and delegates.
- **1.2** New `consensus_engine/scanners/gap_detect.py`. Public `gap_detect_loop()` modeled on `sec_form4_cluster_loop` (`main.py:309`). Fires at market-open (09:30 ET) and market-close (15:45 ET). Reads SA portfolio ticker list from config or `win_routines.db`; calls `fetch_quote` from `utils/quote_fetcher.py`; computes `mover_pct`; runs cross-reference query; writes to `gap_reports`. No Discord output.
- **1.3** Wire `gap_detect_loop` into `main.py` background watchers list.

**Phase 2 — R2.B.i Email (Outlook COM)**
- **2.1** `windows_routines/email_outlook.py` — Outlook COM cycle per §2.B.i.
- **2.2** `win_routines.db` with `r1_runs`, `email_seen(entry_id TEXT NOT NULL, ticker TEXT NOT NULL, PRIMARY KEY(entry_id,ticker))`, `outbox`.
- **2.3** `windows_routines/relay_client.py` — emit function for all Windows routines. Includes: ACK/NACK listener on `#desktop-feed-acks` (10s timeout); outbox spool (1,000-message cap); nonce generation.
- **2.4** Add `email_signals` table to engine `db.py` schema-init.
- **2.5** `_safe_run()` wrapper with Class A / Class B semantics (§3.3).

**Phase 3 — R2.B.ii Discord bot-relay**
- **3.1** New `consensus_engine/scanners/discord_local_intel.py` — `DiscordLocalIntelListener` configured with `local_intel.bot_channels`.
- **3.2** Add `seen_discord` table to engine `db.py` schema-init.
- **3.3** Operator invites engine bot to alert channels.
- **3.4** Smoke test: operator pings test ticker → verify `ticker_signals` row with `source_type=desktop_local`.

**Phase 4 — R4 Clipboard**
- **4.1** `windows_routines/clipboard_sentinel.py` — `pywin32` clipboard hook.
- **4.2** Privacy-gate module: regex blocklist + foreground allowlist. Gate runs before extraction. Default-deny when foreground unknown.
- **4.3** In-memory sha1(raw_text) dedup, 5-min TTL.
- **4.4** Emit via `relay_client`.

**Phase 5 — R6 Bookmark**
- **5.1** `windows_routines/bookmark_sentinel.py` watching `OpenClawProfile\Bookmarks` for mtime change.
- **5.2** Diff configured folder against `win_routines.db.bookmarks_seen(id PRIMARY KEY)`.
- **5.3** aiohttp fetch → parse title + og:description; convert `date_added` FILETIME: `unix_ts = (date_added / 10_000_000) - 11644473600`.
- **5.4** Emit via `relay_client`.
- **5.5** Add `external_articles_seen` table to engine `db.py` schema-init (first use; shared with Phase 6).

**Phase 6 — R1 Authenticated Web (highest risk; last)**
- **6.1** `windows_routines/authed_web/` package: `reddit.py`, `seeking_alpha.py`, `benzinga.py`, `runner.py`.
- **6.2** Playwright + `playwright_stealth` on dedicated `OpenClawProfile`.
- **6.3** Per-target extraction + tiered STOP_AND_LOG triggers (§2.A).
- **6.4** `external_articles_seen` URL-hash dedup via relay (table exists from Phase 5.5).
- **6.5** Quota enforcer: client-side counter (all invocations count); server-side hard-cap.
- **6.6** Windows Task Scheduler: Mon–Thu 09:25 / 12:00 / 14:30 ET, Fri 09:25 ET only. Weekend-pause gate checked client-side before any run.

**Phase 7 — R2.B.ii Discord UI automation (operator-opt-in, fragile)**
- **7.1** `windows_routines/discord_ui.py` — `pywinauto.Application(backend="uia").connect(title_re="Discord")`.
- **7.2** Composite-hash dedup; 300s poll cadence.
- **7.3** Default `discord_ui_enabled: false`; operator sets `true` per channel after reading §2.B ToS note.
- **7.4** Emit via `relay_client`.

**v2 deferred:** R5 (TradingView), R7 (audio).

### 4.3 Dependencies

**Engine-side (Linux):** Already present: `aiosqlite`, `discord.py`, `aiohttp`, `pyyaml`. New: none.

**Windows-side:**
- `pywin32` (Outlook COM, clipboard, foreground-window title)
- `pywinauto` (Discord UI; UIA backend)
- `playwright` + `playwright-stealth` (existing per CLAUDE.md)
- `aiohttp` (bookmark fetch, relay client)
- `aiosqlite` (`win_routines.db`)
- Python ≥ 3.11

**Scheduling:** Windows Task Scheduler for R1 (Mon–Thu × 3, Fri × 1). Other Windows routines: NSSM service or "at logon, run forever" Task Scheduler entry.

### 4.4 Testing strategy

- **Dry-run mode:** `--dry-run` flag + `desktop_feed.target_table: ticker_signals_staging`. Payloads route to `#desktop-feed-dryrun` (listener logs+drops). Existing pattern: `python3 -m consensus_engine --dry-run --once`.
- **Staging table:** `ticker_signals_staging` (Phase 0.3). Default target. Operator flips to `ticker_signals` after Phase 1 verification.
- **Golden-fixture replay:** 50 real payloads captured in dry-run → `tests/fixtures/desktop_feed/`. Replay test asserts identical `INSERT` calls (mocked db) AND correct ACK/NACK.
- **Quota math test:** synthetic 13 auto + 2 on-demand = 15 invocations (any status). 15th accepted, 16th rejected client-side AND server-side.
- **Fail-fast test:** `_safe_run()` Class A → immediate stop, 24h pause, no retry. Class B → stop cycle, next slot eligible. 3 consecutive B on same slot → Class A.
- **ACK/NACK test:** mock listener posts NACK → relay client leaves email Unread in mock COM.
- **Baseline:** `python3 -m pytest tests/ -v` remains green throughout.

### 4.5 Logging & rotation

- **Format:** `%(asctime)s %(levelname)s %(name)s: %(message)s`. Windows uses same format.
- **Locations:** Engine: `consensus_engine.log`. Windows: `%LOCALAPPDATA%\openclaw\logs\R{n}_<routine>.log`.
- **Rotation:** `RotatingFileHandler`, 10 MB × 5 keep. Daily summary: `[ROUTINE_DAILY] R1: 3/3 runs OK | 47 signals | 0 Class-A triggers`.
- **Operator notifications (to `#system-alerts`):**
  - Any Class A trigger.
  - Any Class B cycle failure.
  - Routine paused 24h.
  - Stuck-loop alarm (>5 consecutive without success).
  - Outbox alert (>900/1,000 messages).
  - Server-side R1 quota hard-rejection.
  - Listener-side payload NACK.
- **No alerts on success.**

### 4.6 Rollout

1. **Day 0 — Shadow.** Phase 0 deployed. `target_table=ticker_signals_staging`. Operator sends 5 manual relay messages; validate via `sqlite3 staging`. Verify ACK/NACK flow.
2. **Day 1 — R3 on.** `gap_detect.enabled: true`. Observe full market day. Confirm `gap_reports` populates with correct `mover_pct` and `status`.
3. **Day 2 — Email on.** Windows process launches. Validate ACK/NACK end-to-end; check `email_seen` dedup prevents reprocessing.
4. **Day 3 — Discord bot-relay on.** Operator invites bot to one channel. Smoke test → 24h.
5. **Day 4 — R4 Clipboard on.** Operator reviews privacy gate. Enable → 24h.
6. **Day 5 — R6 Bookmark on.** Drop known test article into folder. Verify within 5 min.
7. **Day 6–7 — Promote to production.** Flip `target_table` to `ticker_signals`. Re-run smoke tests. Observe market day.
8. **Day 8 — R1 first run.** Mon 09:25 ET. Validate quota counter; verify weekend-pause gate refuses manual Sat trigger.
9. **Day 9–14 — Full R1 schedule.** 13 auto-slots. Daily review of `routine_health` + `gap_reports`.
10. **Day 14 — R2.B.ii UI automation.** Enable last; operator-opt-in only; only for DMs + external channels bot can't reach.
11. **Week-2 checkpoint:** Review `gap_reports` for `CAUGHT` rows attributable to new sources. If R1 produces no measurable lift, escalate before raising quota.

### 4.7 What this plan explicitly does NOT do

- Does not edit `cross_reference.py`, `engine.py`, `scoring*`, `alerts/*` decisioning, or any sentiment-classifier code.
- Does not change thresholds in `config/consensus.yaml` outside the new keys in §4.2 step 0.5.
- Does not add Reddit/StockTwits engine-side scanners.
- Does not implement R5 (TradingView) or R7 (audio) — v2.
- Does not amend the existing TweetShift listener.
- Does **not** modify `consensus_engine/briefing/alfred.py` — Alfred briefing extension deferred to v1.1.
- Does **not** add `#gap-alerts` channel or any new alert routing.
- Does **not** edit `consensus_engine/scanners/volume_scanner.py` — R3 quote helper is a new `utils/quote_fetcher.py` wrapping the existing `FinnhubAdapter`.
- Does **not** port `extract_tickers()` to Windows — all ticker extraction runs server-side.

### 4.8 Definition of Done (executor hand-off contract)

- Phase 0 schema migrations applied; `pytest` green; new tables exist.
- Exactly 2 new `SourceType` values in `models.py:9–18`; `db.py:783` IN-list updated; existing tests green.
- `DesktopFeedListener` parses + validates + forwards §3.6 payloads; posts ACK/NACK to `#desktop-feed-acks`; rejects all `tests/fixtures/desktop_feed/rejected/` examples.
- `DesktopFeedListener` runs in both standard and weekend-pause branch of `main.py:415–437`.
- R3 produces non-empty `gap_reports` during a market-hour test. No Discord post. No Alfred change.
- `utils/quote_fetcher.py` callable as standalone import with no `volume_scanner` dependency.
- R2.B.i ACK/NACK: synthetic NACK from listener leaves email Unread in mock COM.
- R1 quota: 16th invocation rejected client-side AND server-side. All invocations count regardless of status.
- Class A trigger: CAPTCHA detection → immediate stop → 24h pause → no auto-resume.
- Files modified are strictly those in Appendix B. `consensus_engine/briefing/alfred.py` is **NOT** in the authorized touch list.

---

## Appendix A — Open questions for operator

- **Finnhub paid tier (OQ-5):** flip `finnhub.has_market_mover_endpoint: true` to enable S&P 500 universe in R3.
- **R4 privacy-gate regex blocklist:** operator review required before Phase 4 enablement.
- **Discord UI automation (path-b):** explicit per-channel opt-in required (§2.B ToS note) before Phase 7.
- **`local_intel.allowlist_windows_path`:** provide Windows path to synced allowlist, or confirm server-side enforcement only.

## Appendix B — File-touch manifest

**Engine repo (authorized files only):**

- `consensus_engine/models.py` (Phase 0.1, +2 enum lines)
- `consensus_engine/db.py` (Phase 0.2 + 0.3, schema-init + IN-list; Phases 2.4, 3.2, 5.5 add tables incrementally)
- `consensus_engine/main.py` (Phase 0.4 + 1.3, wire DesktopFeedListener in both branches + `gap_detect_loop`)
- `consensus_engine/scanners/discord_desktop_feed.py` (NEW, Phase 0.4)
- `consensus_engine/scanners/discord_local_intel.py` (NEW, Phase 3.1)
- `consensus_engine/utils/quote_fetcher.py` (NEW, Phase 1.1)
- `consensus_engine/scanners/gap_detect.py` (NEW, Phase 1.2)
- `config/consensus.yaml` (Phase 0.5, new keys only)
- `/root/.openclaw/.env` (Phase 0.6, new env vars)
- `/root/.openclaw/local_intel_allowlist.json` (NEW, Phase 2)
- `tests/fixtures/desktop_feed/` (NEW)
- `tests/test_desktop_feed_listener.py` (NEW)
- `tests/test_gap_detect.py` (NEW)
- `tests/test_r1_quota.py` (NEW)
- `tests/test_fail_fast.py` (NEW)

**NOT authorized:** `consensus_engine/briefing/alfred.py`, `consensus_engine/scanners/volume_scanner.py`, `consensus_engine/api_adapters.py`, `consensus_engine/alerts/`, `consensus_engine/engine.py`, `consensus_engine/cross_reference.py`.

**Windows side (operator's PC):**

- `windows_routines/relay_client.py` (NEW)
- `windows_routines/email_outlook.py` (NEW, Phase 2)
- `windows_routines/clipboard_sentinel.py` (NEW, Phase 4)
- `windows_routines/bookmark_sentinel.py` (NEW, Phase 5)
- `windows_routines/authed_web/{reddit,seeking_alpha,benzinga,runner}.py` (NEW, Phase 6)
- `windows_routines/discord_ui.py` (NEW, Phase 7)
- `win_routines.db` (created at first run)

---

## Revision History

- **v1 (2026-04-30):** Initial plan. Adversarial review identified C1-C4 (critical) + H1-H8 (high).
- **v2 (2026-04-30):** All C1-C4 + H1-H8 addressed:
  - **C1:** Replaced unimportable `volume_scanner._fetch_quote` closure with new `utils/quote_fetcher.py` wrapping importable `api_adapters.FinnhubAdapter`. No edits to `volume_scanner.py`.
  - **C2:** Friday schedule reduced to 1 auto-run (09:25 ET only). `DesktopFeedListener` wired into weekend-pause branch (`main.py:415–437`). Windows outbox cap raised to 1,000. Client-side `is_weekend_pause()` gate blocks R1 during pause.
  - **C3:** R3 stripped to DB-only. `#gap-alerts` post removed. Alfred briefing extension removed (deferred to v1.1). `briefing/alfred.py` removed from authorized touch list.
  - **C4:** Phase 0 reduced to 2 SourceType values (`DESKTOP_AUTH`, `DESKTOP_LOCAL`), 4 minimum-viable tables, 1 listener. No second listener until Phase 3. Principle stated: "engine changes only when a v1 Windows routine cannot work without them."
  - **H1:** All R1 invocations count (any status). 13 auto-runs + 2 on-demand buffer. Server-side quota is hard-reject.
  - **H2:** Relay-before-mark-Read. ACK/NACK on `#desktop-feed-acks`. NACK/timeout → leave Unread. EntryID dedup in `win_routines.db` regardless of Outlook state.
  - **H3:** Removed 3-strike softening. STOP IMMEDIATELY on first failure. Class A: 1 strike → 24h pause → operator-manual-clear only. Class B: stop cycle; 3 consecutive → Class A.
  - **H4:** `extract_tickers` engine-side only. Client-side `ticker` field dropped. Server-side fan-out per ticker.
  - **H5:** `local_intel.allowlist_windows_path` config var added. Or: server-side enforcement only.
  - **H6:** Discord UI re-tiered from "ACCEPTABLE" to "OPERATOR RISK DECISION REQUIRED." Poll interval raised to 300s. Default `discord_ui_enabled: false`.
  - **H7:** Dedicated `OpenClawProfile` Chrome profile required (`shutil.copytree` at install). Daily-use profile fully isolated.
  - **H8:** R3 restricted to SA portfolio (~30 tickers), 2 cycles/day. Honest call budget: 60/day. False "no new external HTTP calls" claim removed.

---

**End of plan (v2). Ready for critic re-review.**

---

## Adversarial Review (v2)

**Reviewer:** critic (Stage 4/4 — re-review iteration 1)
**Date:** 2026-04-30
**Mode:** THOROUGH (no escalation — no CRITICAL or ≥3 MAJOR findings)
**Prior verdict:** PLAN NEEDS REVISION (4 CRITICAL + 8 HIGH)

---

### Per-CRITICAL Status Table

| ID | Prior Finding | Reviser Claim | Verified Against Codebase | Status |
|---|---|---|---|---|
| C1 | `volume_scanner._fetch_quote` is a nested closure, not importable | New `utils/quote_fetcher.py` wrapping importable `api_adapters.FinnhubAdapter` | `FinnhubAdapter` confirmed top-level class at `api_adapters.py:30`. `_fetch_quote` at `api_adapters.py:59` is an instance method — importable and callable without touching `volume_scanner.py`. Pattern mirrors existing `get_live_quote_price` at `api_adapters.py:273` which already calls `adapter._fetch_quote(ticker)`. Both forbidden files (`api_adapters.py`, `volume_scanner.py`) remain unedited. | **RESOLVED** |
| C2 | Friday 15:30 ET run lands 30 min inside weekend pause; passive routines overflow 200-msg outbox over 47h | Fri cut to 1 run (09:25 ET only); `DesktopFeedListener` wired into weekend-pause branch at `main.py:415–437`; outbox raised to 1,000 | Weekend-pause branch confirmed at `main.py:415–437` (verified). Friday schedule: §3.2 shows only 09:25 ET, 0 other slots. Outbox cap 1,000 + alert-at-900 stated in §3.2 + §3.3. Client-side `is_weekend_pause()` gate for R1 stated. 14:30 ET power-hour slot on Mon–Thu confirmed safe (45 min before market close, well clear of Friday pause). | **RESOLVED** |
| C3 | R3 ships new `#gap-alerts` Discord alert + Alfred briefing extension = new alert decisioning, contradicting operator brief | R3 stripped to DB-only; Alfred extension deferred to v1.1; `briefing/alfred.py` removed from authorized touch list | §2.C: "R3 is DB-only in v1. No `#gap-alerts` Discord post. No Alfred briefing extension." §4.7: "Does **not** modify `consensus_engine/briefing/alfred.py`." Appendix B NOT-authorized list includes `alfred.py`. Phase 1 contains no Alfred or alert-channel step. `gap_detect.alert_threshold_pct` explicitly annotated "reserved for v1.1 only; unused in v1." | **RESOLVED** |
| C4 | Phase 0 = 7 enums + 6 tables + 2 listeners = engine surface-area that exceeds "data access only" brief | Phase 0 reduced to exactly 2 SourceType values, 4 tables, 1 listener; minimality principle codified | Phase 0.1: exactly 2 new values (`DESKTOP_AUTH`, `DESKTOP_LOCAL`). Phase 0.3: exactly 4 tables (`routine_health`, `seen_relay_nonces`, `ticker_signals_staging`, `gap_reports`). Phase 0.4: 1 listener (`discord_desktop_feed.py`). Second listener (`DiscordLocalIntelListener`) deferred to Phase 3. Hard Constraint #5 codifies the minimality principle. | **RESOLVED** |

---

### Per-HIGH Status

| ID | Prior Finding | Status | Evidence |
|---|---|---|---|
| H1 | 15-cap leaks: v1 SQL counted only `status IN ('OK','PARTIAL')`, allowing free retries on failure | **RESOLVED** | Hard Constraint #1: "All R1 invocations count regardless of outcome status." §3.2: "count ALL rows … (any status)"; 13 auto + 2 on-demand buffer; server-side hard-reject confirmed. |
| H2 | "Relay ack" undefined; listener-side rejection didn't prevent mark-Read; silent signal loss | **RESOLVED** | §2.B.i: explicit 4-step relay-before-mark-Read protocol keyed to `#desktop-feed-acks`. NACK or timeout → leave Unread. EntryID dedup in `win_routines.db` checked BEFORE relay regardless of Outlook state. Phase 0.5 + 0.6 add ACK channel config keys. §3.3 specifies DesktopFeedListener posts `{"ack": nonce}` only after successful `db.insert_signal`. |
| H3 | 3-strike softening: 2 CAPTCHA cycles allowed before pause; no failure-class distinction | **RESOLVED** | Hard Constraint #2: Class A (auth/CAPTCHA/403/layout-drift) = 1 strike → immediate stop + 24h pause + operator-manual-clear only, no auto-resume. Class B (transient network) = stop cycle, next slot eligible; 3 consecutive B on same slot → Class A treatment. §3.3 confirms. |
| H4 | `extract_tickers` ported to Windows → drift and blacklist-bypass risk | **RESOLVED** | §1.6: "engine-side only — NOT ported to Windows." Primary payload drops `ticker` field. §3.6 step 6: `DesktopFeedListener` calls `extract_tickers(payload["raw_text"])` and fans out one `insert_signal` call per ticker. Zero Windows-side ticker extraction. |
| H5 | Allowlist at Linux path `/root/.openclaw/`; Windows routines have no defined resolution path | **RESOLVED** | `local_intel.allowlist_windows_path` config var added (Phase 0.5, default `""`). Two enforcement paths offered: (a) sync Syncthing/rsync to Windows path, or (b) leave empty → server-side enforcement only in `DesktopFeedListener`. |
| H6 | Discord UIA tagged "ACCEPTABLE" — understatement of ToS/ban risk; 30s polling automation-signature | **RESOLVED** | Re-tiered to "OPERATOR RISK DECISION REQUIRED." §2.B.ii quotes Discord AUP. Poll raised to 300s. Default `discord_ui_enabled: false`. Explicit per-channel opt-in required. Permanent-disable clause if account action taken. |
| H7 | R1 uses operator's daily Chrome profile — profile-lock contention + collateral damage risk | **RESOLVED** | Dedicated `OpenClawProfile` created at install via `shutil.copytree`. `launch_persistent_context(user_data_dir=...\OpenClawProfile, channel="chrome")`. R6 bookmark watch path also targets `OpenClawProfile\Bookmarks`. Daily-use profile fully isolated. |
| H8 | R3 call budget: ~39k Finnhub calls/day at 5-min cadence over S&P 500; "no new HTTP calls" false | **RESOLVED** | R3 restricted to SA portfolio (~30 tickers) × 2 cycles/day = 60 calls/day. "No new external HTTP calls" claim explicitly corrected in §2.C + §3.4. S&P 500 path (paid tier) deferred behind `finnhub.has_market_mover_endpoint` flag. |

---

### New Issues Introduced by Revision

**NEW-1 (MINOR) — `DESKTOP_LOCAL` added to `get_social_signals` IN-list; non-social sources enter social cross-reference query**
- *Plan quote (Phase 0.2):* `"Update db.py:783 get_social_signals IN-list to include 'desktop_auth', 'desktop_local'."`
- v1 explicitly excluded `email`, `discord_dm`, `clipboard`, `bookmark` from the social query: *"NOT social-cross-reference targets — leave them out unless a downstream consumer asks."* v2's 2-enum consolidation places all those sources under `DESKTOP_LOCAL` and then includes it in the social IN-list. This silently reverses the v1 design decision.
- **Mitigated by:** `get_social_signals` at `db.py:776` is **currently never called** anywhere in the codebase (grep: zero call sites — definition only). Zero runtime impact in v1. When a future consumer is added, `source_detail` `via:<tag>` discriminators allow filtering without schema changes.
- **Severity: MINOR** (dead code in v1; latent for future callers). Recommended action: change Phase 0.2 to add only `'desktop_auth'` to the IN-list, leave `'desktop_local'` out, and annotate the definition with a comment explaining the exclusion.
- *Confidence: HIGH.*

**NEW-2 (MINOR) — `quote_fetcher.py` wrapping `FinnhubAdapter._fetch_quote` bypasses the shared Finnhub `rate_limiter`**
- `volume_scanner._fetch_quote` (the closure) acquires from the shared `rate_limiter` before each call (`volume_scanner.py:14` imports `rate_limiter`). `api_adapters.FinnhubAdapter._fetch_quote` does not (zero `rate_limiter` references in `api_adapters.py` — verified). `quote_fetcher.py` wrapping `FinnhubAdapter` therefore bypasses the shared client-side throttle.
- **Mitigated by:** R3 fires only 2 cycles/day (~30 sequential calls per cycle). Practical overlap with volume_scanner (900s cadence) is low. `FinnhubAdapter._fetch_quote` returns `None` gracefully on any non-200, including 429.
- **Severity: MINOR** (negligible at 60 calls/day). Recommended action: `quote_fetcher.py` should acquire from `rate_limiter` before each call to match the volume_scanner pattern and protect the shared Finnhub budget.
- *Confidence: HIGH.*

---

### Previously Raised Minor/Gap Items — Status in v2

| ID | Original Finding | v2 Status |
|---|---|---|
| M1 | `ticker_signals_staging` missing from Phase 0.3 DDL + config | **RESOLVED** — Phase 0.3 lists it; Phase 0.5 adds `desktop_feed.target_table: ticker_signals_staging`. |
| M3 | `seen_relay_nonces` sweep cadence undefined; table grows unboundedly | **RESOLVED** — §3.3: DELETE sweep every 1h in heartbeat path; `idx_srn_ts` index. `seen_discord` 24h sweep; `external_articles_seen` 30-day sweep. |
| M4 | Outlook mark-Read silent fail on Exchange shared mailbox causes reprocessing loop | **RESOLVED** — EntryID dedup in `win_routines.db.email_seen` checked BEFORE relay regardless of Outlook state. |
| M6 | Email subject filter was OR-only, false-positive prone | **RESOLVED** — §2.B.i: 3-of-3 gate (sender match AND ≥1 subject substring AND ≥1 ticker extracted server-side). |
| Gap-6 | Bookmark `date_added` is Windows FILETIME, not Unix seconds — off by 10⁷ and 369 years | **RESOLVED** — §2.E: `unix_ts = (date_added / 10_000_000) - 11644473600` explicit. |
| L2 | `SourceType`/`Sentiment` ValueError unhandled in listener | **RESOLVED** — §3.6 step 6: log + post NACK on ValueError; no unhandled exception. |
| L4 | Privacy gate ordering: extraction ran before rejection | **RESOLVED** — §2.D: "Privacy gate runs FIRST — before any extraction." |
| Gap-1 | Relay channel HMAC auth: forged payloads could inject signals | **NOT ADDRESSED** — still absent. Acceptable residual: operator-owned Discord server + nonce dedup + quota gate reduce risk to low. Recommend HMAC in v1.1. |

---

### Self-Audit

- C1 resolution verified by reading `api_adapters.py:30–71` directly. `FinnhubAdapter.__init__(session, api_key)` signature confirmed; `_fetch_quote(ticker)` confirmed as instance method. No doubts; HIGH confidence.
- C2: `main.py:415–437` weekend-pause branch verified in source. Current block runs only `DiscordTweetShiftListener`; v2 plan adds `DesktopFeedListener` — no contradiction with existing code.
- `get_social_signals` caller count: grep of entire Python source tree returned exactly one occurrence (the definition at `db.py:776`). Zero callers. This lowers NEW-1 from MAJOR to MINOR. The finding is preserved because it is a real latent inconsistency, but it has no v1 runtime impact.
- NEW-2 confirmed by checking `api_adapters.py` for `rate_limiter` (none found) and `volume_scanner.py:14` (imports `rate_limiter`). No findings moved to Open Questions; all evidence is codebase-grounded.

### Realist Check

- **NEW-1:** Zero callers of `get_social_signals` → worst-case runtime impact today = zero. Future consumer would encounter the issue before any alert fires. MINOR correctly rated.
- **NEW-2:** 60 calls/day; Finnhub free ceiling ~86,400/day; R3 fires at market-open (09:30 ET) and market-close (15:45 ET) when volume_scanner's 900s cadence makes concurrent calls improbable. Both paths return `None` on 429 and log gracefully. MINOR correctly rated.

---

### Verdict

**PLAN READY**

All 4 CRITICAL findings (C1-C4) are fully resolved. All 8 HIGH findings (H1-H8) are fully resolved. Two new MINOR findings introduced by the revision (NEW-1: dead-code `get_social_signals` inclusion of `DESKTOP_LOCAL`; NEW-2: rate_limiter not wired in `quote_fetcher.py`). Neither blocks execution nor introduces correctness regressions in v1.

**HIGH findings still open: 0**

The 2-enum consolidation (C4 fix) is a sound architectural choice. The only consequence (NEW-1) has zero current-runtime impact. The plan is ready for executor hand-off at Phase 0.

---

*End of Adversarial Review (v2). Reviewer: critic, Stage 4/4, 2026-04-30.*
