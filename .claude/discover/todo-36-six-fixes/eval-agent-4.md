# Eval Agent 4 — Issues 5 & 6 (read-only investigation)

Repo: `/home/openclaw/.openclaw/workspace`. No files edited, no live tests run.

---

## ISSUE 5 — Smart-levels "current price" is actually the previous close

### Root cause: CONFIRMED

The smart-levels proximity check (`_check_youtube_level_alerts`) prices every ticker
through `_fetch_yfinance_price`, a helper that was written for slow 1h/24h *outcome*
backfill, not for live alerting.

- `consensus_engine/main.py:939` `_check_youtube_level_alerts()` — runs inside
  `fetch_loop` (`main.py:875`, `interval=300`, i.e. once every **5 minutes**, wired
  at `main.py:700`).
- `main.py:956-959` submits `_fetch_yfinance_price` for every distinct ticker to the
  default thread-pool executor, then gathers.
- `main.py:1531` `_fetch_yfinance_price(ticker) -> float` (**sync/blocking**,
  docstring literally says *"Blocking helper for 1h/24h price outcome tracking."*):
  1. tries `stock.fast_info` for `lastPrice`/`last_price`/`regularMarketPrice`;
  2. **on empty fast_info (common on yfinance free tier) falls through to**
     `stock.history(period="5d", interval="1d")` and returns `close.iloc[-1]` —
     **the last daily Close = the previous close, not a live price.**
- That value is interpolated into the alert text at `main.py:986`:
  `... — current ${current_price:.2f}`.

So the bug is exactly as diagnosed: the word "current" can show yesterday's close.

### The engine already has a real-time Finnhub quote path (two of them)

There are **two** sync-vs-async layers; the relevant one is async:

1. **`consensus_engine/api_adapters.py:274`**
   `async def get_live_quote_price(ticker: str) -> float | None`
   - Async. Builds a `FinnhubAdapter`, calls `_fetch_quote`, reads the `c` field
     (Finnhub real-time price), returns `None` on any failure / 0 (fail-open).
   - **This is the project's intended live-price helper.** It is already the
     anchor used by the YouTube level-classification code via
     `scanners/youtube.py:456` `_safe_live_price()` (which just wraps
     `get_live_quote_price` with a try/except → `None`).
2. `main.py:1079` `async def _fetch_price(ticker)` — older inline duplicate of the
   same Finnhub `/quote` call (`c` field). Used elsewhere in main.py. Functionally
   identical but **not** the DRY choice; `get_live_quote_price` is the shared one.

Underneath, `FinnhubAdapter._fetch_quote` (`api_adapters.py:60`) hits
`https://finnhub.io/api/v1/quote` and returns the raw dict. NOTE: `_fetch_quote`
itself does **not** call the rate limiter — it is unthrottled at that layer.

### Rate-limit math with the 300s interval — LOW risk

- Finnhub free tier = 60 calls/min; the project's limiter is configured for it at
  `utils/rate_limiter.py:23` `"finnhub": 1.0` (1 req/sec).
- Smart-levels runs **once per 5 minutes** and prices **only the distinct tickers
  that have a stored YouTube level in the last 14 days** (`youtube_levels` table,
  `main.py:946`). That's a small set — realistically a handful to low dozens, not
  hundreds.
- Even an unthrottled burst of, say, 30 quotes in one 5-minute cycle is **0.1
  calls/sec averaged**, far under the 60/min cap. **Swapping to Finnhub here does
  not blow the budget.**
- Adversarial caveat: `get_live_quote_price` → `_fetch_quote` is **not** wrapped by
  the limiter, so a one-shot burst of N tickers fires N near-simultaneous requests.
  If the level set ever grew large (40+), that single burst could momentarily exceed
  60/min and earn a 429. Cheap insurance: route these through
  `rate_limiter.acquire("finnhub")` (the limiter is async and already used by
  `technical.py`, `earnings_calendar.py`), OR keep the existing concurrent gather but
  cap fan-out. Given today's small level set this is a "nice to have," not required.
- Shared-budget note: the same `finnhub` limiter key is used by `!technical`,
  earnings calendar, and the main scoring loop. A once-per-5-min handful of quotes is
  negligible against that shared budget.

### After-hours / pre-market — the real adversarial point

Finnhub free-tier `/quote` `c` field is the **last regular-session trade price**.
After the close it returns the day's close; pre-market/after-hours it does **not**
return live extended-hours prints on the free tier. So:

- During market hours: Finnhub `c` is genuinely live — strict improvement over the
  yfinance-close fallback. ✅
- After hours / weekends: Finnhub `c` ≈ the regular-session close — i.e. the **same
  number** the yfinance fallback returns. So the swap doesn't make after-hours
  *worse*, but it also doesn't magically produce a live extended-hours price.
- The honest fix for the *label* is therefore **two parts**:
  1. Swap the price source to Finnhub live (fixes the in-hours wrongness).
  2. Make the word "current" honest after hours — when the market is closed, the
     alert should say something like `last close $X` / `(market closed)` rather than
     `current $X`. The engine already has a market-hours notion
     (`FinnhubContext.market_ok` and weekend-pause logic `_is_weekend_pause`), so a
     market-open check is available without new infrastructure.

### Recommended approach (ranked)

1. **REUSE the existing unified helper — `get_live_quote_price`** (DRY, async-native).
   In `_check_youtube_level_alerts`, drop the `run_in_executor(_fetch_yfinance_price)`
   fan-out and instead `await asyncio.gather(*(get_live_quote_price(t) for t in
   tickers))`. It already returns `None` on failure, which the existing
   `if isinstance(... Exception) or not current_price: continue` guard handles.
   Do NOT call raw Finnhub or duplicate `_fetch_price` — `get_live_quote_price` is the
   project's designated live-price function and is what the sibling YouTube
   level-anchor code already uses, so reusing it keeps both paths consistent.
2. **Add a yfinance fallback only if you want resilience when Finnhub is down/None.**
   Finnhub-primary → yfinance-fallback is defensible, BUT the yfinance fallback is
   exactly the previous-close path that caused this bug, so if you keep it, the label
   must reflect that it may be stale. Simplest honest behavior: if Finnhub returns
   `None`, **skip the alert** (don't fire a proximity alert off a stale close) rather
   than firing with a wrong "current."
3. **Raw Finnhub swap** (calling `/quote` inline) — works but duplicates code; reject
   in favor of option 1.

**Net recommendation:** reuse `get_live_quote_price`; on `None`, skip rather than
fall back to a stale close; and add a market-open guard so the alert text says
"last close" instead of "current" when the market is closed. Optional hardening:
wrap the per-cycle fan-out in the `finnhub` rate limiter if the level set ever grows.

---

## ISSUE 6 — `!help` (HELP_TEXT) audit

`HELP_TEXT` lives at `consensus_engine/alerts/commands.py:141-182`. The router is
`_route_command_inner` at `commands.py:214-438`. Every branch below was read; each
calls a handler that exists in the same file (handler line numbers verified via grep).

### Authoritative router command list (canonical name + aliases → handler)

| Command (canonical) | Aliases accepted | Handler | Notes |
|---|---|---|---|
| `!help` | `!readme` | inline → sends `HELP_TEXT` | `commands.py:221` `command in ("help","readme")` |
| `!status` | — | `_handle_status` | DB only |
| `!trend` | — | `_handle_trend` | Reddit trend crawl |
| `!performance` | — | `_handle_performance` | DB only |
| `!scan <T>` | — | `_handle_scan` → `cross_reference` | full xref (news+sec+tech+options+LLM) |
| `!ask <q>` | — | `_handle_ask` | **LLM chain** |
| `!all <T>` | — | `_handle_all` → `all_command.handle_all` | **LLM synthesis** (`call_with_fallback`) |
| `!signals <T>` | — | `_handle_signals` | DB only |
| `!analysts <T>` | — | `_handle_analysts` | DB only |
| `!active-tickers` | `active_tickers`, `active` | `_handle_active_tickers` | DB only |
| `!news <T>` | — | `_handle_news` → `news_cascade` | external news APIs |
| `!sec <T>` | — | `_handle_sec` → SEC EDGAR | external SEC |
| `!options <T>` | — | `_handle_options` → `check_unusual_options` | yfinance options chain |
| `!technical <T> [long\|short]` | — | `_handle_technical` | Finnhub + yfinance |
| `!google-trends <T>` | `trends`, `gtrends` | `_handle_google_trends` | trends scanner |
| `!serpapi-trends` | — | `_run_serpapi_trends` | cron-oriented; SerpAPI |
| `!apewisdom` | — | `_handle_apewisdom` | external API |
| `!alert-history <T>` | `history` | `_handle_alert_history` | DB only |
| `!leaderboard` | — | `_handle_leaderboard` | DB only |
| `!source-health` | `source_health` | `_handle_source_health` | DB only |
| `!transcript <URL>` | — | `_handle_transcript` → `fetch_transcript_cascade` | **YouTube transcript (recently rewritten / IP-blacklist sensitive)** |
| `!market-view <T>` | `market_view`, `marketview` | `_handle_market_view` | DB + calibration |
| `!levels <T>` | — | `_handle_levels` | DB only |
| `!yt <URL>` | — | `_handle_yt` → transcript + `parse_video_transcript` | **transcript + LLM + (vision)** |
| `!yt-mentions <T>` | `yt_mentions` | `_handle_yt_mentions` | DB only |
| `!macro` | — | `_handle_macro` | DB digest |
| `!yt-follow <@/URL>` | `yt_follow` | `_handle_yt_follow` | writes follow list |
| `!yt-health` | `yt_health` | `_handle_yt_health` | DB + Gemini budget |
| `!yt-evidence <video_id>` | `yt_evidence` | `_handle_yt_evidence` | DB only |
| `!feature-health` | `feature_health` | `_handle_feature_health` | config/flags |
| `!shadow-mode-report <feat>` | `shadow_mode_report`, `shadow-report` | `_handle_shadow_mode_report` | DB |
| `!cluster <T>` | — | `_handle_cluster_history` | DB (SEC Form-4 cluster) |

Unknown command → `commands.py:437` replies `Unknown command !x. Try !help.`

### DIFF: HELP_TEXT vs router

**In router but MISSING from HELP_TEXT (undocumented working commands):**
- `!transcript <URL>` — confirmed missing. (router `commands.py:359`)
- `!cluster <TICKER>` — confirmed missing. (router `commands.py:427`)
- `!readme` — confirmed; it's an **alias of `!help`** (`commands.py:221`), not
  documented as such.
- `!serpapi-trends` — missing (arguably intentional: it's a cron-facing command).
- `!active-tickers` IS documented (HELP line 153). Its aliases `active`/`active_tickers`
  are not, but that's minor.
- Several **alias forms** are undocumented but harmless: `!trends`/`!gtrends` (for
  google-trends), `!history` (for alert-history), `!marketview`, `!shadow-report`.

**In HELP_TEXT but NO router branch (DEAD DOC — will return "Unknown command"):**
- `!feature-health` is documented (HELP line 181) AND routed — OK.
- ⚠️ **`!shadow-mode-report` is documented (HELP line 182) and routed — OK.**
- ⚠️ The HELP "Feature Flags" footer says *"list all 6 features"* — stale wording;
  the engine now has far more than 6 features. Cosmetic, not a dead command.
- No HELP_TEXT line maps to a totally-absent router branch — i.e. **no hard dead
  doc**, but several documented commands are thin wrappers whose *handlers* may fail
  at runtime (see high-risk list). The bigger HELP problem is **omission**, not dead
  links.

**Feature areas scanned for and result:**
- Wolf newsletter: **NO `!wolf*` command exists** in the router. Wolf runs as
  background loops (`wolf_news_supervisor`, `wolf_confluence_loop`,
  `wolf_digest_loop`, `wolf_beneficiary_loop` — `main.py:865-872`) posting to #news.
  There is nothing for `!help` to document here; do not invent a `!wolf` command.
- Options-flow beyond `!options`: only `!options` exists as a command; the
  autonomous options watcher is a background loop, not a command.
- Smart-levels: surfaced via `!levels` (documented) and `!cluster` (undocumented);
  the proximity *alerts* are background (Issue 5), not a command.
- `!chart`: **no such command.** `!brief`: **no such command** (briefing is a loop).
  Don't add either to HELP.

### High-risk commands needing live test FIRST (depend on recently-rewritten APIs)

These are the ones most likely to be broken end-to-end despite intact imports:

1. **`!transcript`** — depends on `fetch_transcript_cascade`. The VPS IP is
   YouTube-blacklisted; per project memory only Gemini server-side fetch + Supadata
   work, and `youtube_transcript_api`/`yt-dlp` were removed. **Highest risk of
   returning an error.**
2. **`!yt <URL>`** — transcript + `parse_video_transcript` + LLM + possibly vision.
   Same transcript fragility plus LLM-chain and Gemini-vision dependencies. **High
   risk.**
3. **`!all`** — `call_with_fallback` LLM synthesis (5-model chain, groq budget). Most
   complex output path; quality + provider-failure risk.
4. **`!ask`** — heavyweight LLM chain. Provider/quota risk.
5. **`!options`** / `!technical` — yfinance options chain + Finnhub; subject to
   yfinance rate-limit/empty-data flakiness.
6. **`!yt-health`** — reads Gemini budget; should work but touches the YT pipeline.

Lower risk (DB-only, deterministic): `!status`, `!signals`, `!analysts`,
`!active-tickers`, `!levels`, `!yt-mentions`, `!yt-evidence`, `!alert-history`,
`!performance`, `!leaderboard`, `!source-health`, `!market-view`, `!cluster`,
`!feature-health`, `!shadow-mode-report`, `!macro`, `!yt-follow`.

### Recommended ordering (smarter than "test all then rewrite")

Don't test in HELP order. Group by dependency and **test the risky external-API
commands first** so failures surface early and the build phase can decide
remove-from-help vs fix:

- **Wave A (cheap, DB-only):** confirm the whole router dispatches and the bot is
  alive. Fast, no quota cost.
- **Wave B (external data, single API):** `!options`, `!technical`, `!news`, `!sec`,
  `!google-trends`, `!apewisdom`, `!trend`.
- **Wave C (LLM chains):** `!ask`, `!all`, `!scan` (xref triggers LLM boost).
- **Wave D (YouTube/transcript/vision — most fragile):** `!transcript`, `!yt`,
  `!yt-health`. Test last and budget for failure.

Then rewrite HELP_TEXT to: (a) add `!transcript`, `!cluster`, note `!readme` alias;
(b) drop/annotate any command that fails Wave D and can't be fixed; (c) fix the "all
6 features" stale line.

### Proposed command → expected-observable-response test matrix (build phase)

| Command (example) | Expected observable response (pass = this shape, not an error/Unknown) |
|---|---|
| `!help` | The HELP_TEXT block posts; multiple sections, no "Unknown command" |
| `!readme` | Same HELP_TEXT block (proves alias) |
| `!status` | `**Engine Status**` + "Active signals: N" + last-alert line |
| `!signals NVDA` | `**Active Signals — $NVDA**` with per-source counts, OR "No active signals" |
| `!analysts NVDA` | analysts list OR "No analysts mentioned $NVDA in the last hour" |
| `!active-tickers` | `**Active Tickers (N)**` list OR "No active tickers right now" |
| `!levels NVDA` | `**Price Levels — $NVDA**` zones OR "No price levels found" |
| `!cluster NVDA` | Form-4 cluster history reply OR a clean "no cluster" message (NOT "Unknown command") |
| `!alert-history NVDA` | `**Alert History — $NVDA**` rows OR "No alert history" |
| `!performance` | `**Alert Performance**` win-rate block OR "No alert data yet" |
| `!leaderboard` | `**Analyst Leaderboard**` OR "No analyst performance data yet" |
| `!source-health` | `**Source Health**` table (code block) with finnhub/yfinance rows |
| `!market-view NVDA` | `**Market View — $NVDA**` verdict+score OR "No decision snapshots… run !scan first" |
| `!feature-health` | feature list with enabled/last-flip |
| `!shadow-mode-report regime_classifier` | KPI report OR a clean "no shadow data" message |
| `!yt-mentions NVDA` | YouTube signals for NVDA OR "no mentions" |
| `!yt-evidence <id>` | up-to-10 evidence spans OR "no evidence" |
| `!macro` | macro digest text |
| `!yt-follow @SomeChannel` | confirmation it was added to follow list (use a throwaway/known handle) |
| `!news NVDA` | `**News — $NVDA**` Type+Summary OR "No news found" |
| `!sec NVDA` | `**SEC Filings — $NVDA**` OR "No SEC filings in the last 72h" |
| `!options NVDA` | `**Options Flow — $NVDA**` put/call ratio OR "No options data available" |
| `!technical NVDA long` | `**Technical — $NVDA (LONG) k/6 filters passed**` with ✅/❌ rows |
| `!google-trends NVDA` | `**Google Trends — $NVDA**` interest change % OR "No Google Trends data" |
| `!apewisdom` | `**ApeWisdom Trending**` numbered list OR "No ApeWisdom data" |
| `!trend` | "Running trend scan…" then a trend digest OR "No trending tickers" |
| `!scan NVDA` | "Scanning $NVDA…" then `**$NVDA Scan — Score: N**` breakdown |
| `!ask <question>` | a substantive LLM answer (may split across messages), not an error |
| `!all NVDA` | full multi-source synthesized analysis embed/text, not an error/empty narrative |
| `!transcript <yt-url>` | `**Transcript** (...chars)` + preview. **EXPECT POSSIBLE FAILURE** (VPS IP blacklist) — if it errors, that's the finding |
| `!yt <yt-url>` | full on-demand video analysis (tickers/conviction/levels). **EXPECT POSSIBLE FAILURE** (transcript+vision+LLM) |
| `!yt-health` | 7-day pipeline health + Gemini budget snapshot |
| `!notacommand` | "Unknown command `!notacommand`. Try `!help`." (negative-path sanity) |

### Live-test method — CONFIRMED to exist (do NOT run now)

- **Bot token + channel IDs** are in `/root/.openclaw/.env`: keys present include
  `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`, `DISCORD_NEWS_CHANNEL_ID`,
  `DISCORD_BRIEFING_CHANNEL_ID`, `DISCORD_FEED_CHANNEL_ID`, `DISCORD_OWNER_USER_ID`.
- **Documented webhook** (memory file `discord_webhook.md`): a bot cannot receive its
  OWN messages over the gateway, so to make the bot *process* a `!command` you POST
  via the **ClaudeCode webhook** (sender identity differs):
  `https://discord.com/api/webhooks/1508945176335482880/4533lxLkFmSsiPAYGkhZddvgbwUuvk707MbtjqV5BFXog_t4lkSHyd2ak6QdLtGc-mxu`
  to **#chat** (`1468890179698692147`). The bot reacts 👀 when it reads the message.
  Example (build phase):
  ```
  source /root/.openclaw/.env && curl -s -X POST -H "Content-Type: application/json" \
    -d '{"content":"<@1468886193054814352> !status","username":"ClaudeCode"}' \
    "https://discord.com/api/webhooks/1508945176335482880/4533lxLkFmSsiPAYGkhZddvgbwUuvk707MbtjqV5BFXog_t4lkSHyd2ak6QdLtGc-mxu"
  ```
- Per CLAUDE.md / memory: before pinging, confirm `discord_tweetshift: Discord
  Gateway READY` for the current boot (or wait ≥30s after a consensus-engine
  restart). Method confirmed available; not exercised in this read-only pass.
