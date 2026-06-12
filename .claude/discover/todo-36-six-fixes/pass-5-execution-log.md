# Pass 5 — Execution log (TODO #36)

Run: todo-36-six-fixes. Mode: plan-first (user approved plan), build in same session.
User decision: Fwd P/E shows ~24 (current-fiscal-year EPS basis).

## What was built + verified

### FIX A — Issues 2 / 4 / 1 (gateway crash, plugin removal, mention warnings)
**Root cause was broader than the TODO diagnosed.** Not just plugin drift — a June-10 root login left **5,118 files** across `/home/openclaw/.openclaw` owned by root, including the gateway's `state/openclaw.sqlite`, `plugins/installs.json`, and `agents/.../sessions.json` (all mode-600 → the `openclaw` service user couldn't open them → "unable to open database file"). The engine survived because most files are world-readable; the gateway's 600-mode files were not.
- `chown -R openclaw:openclaw /home/openclaw/.openclaw` (0 root-owned left).
- Added `ExecStartPre=+/bin/chown -R openclaw:openclaw …/state` to the gateway drop-in `10-selfheal.conf` (recurrence guard the TODO missed).
- web-search-plus-plugin-v2: `openclaw plugins uninstall --force` removed it from openclaw.json (entries+allow) + disk; cleared the stale plugin-index deadlock by deleting the SQLite `installed_plugin_index` snapshot row + the `installs.json` file and regenerating clean (`plugins registry --refresh`). Conflict warning → gone.
- brave: UPDATEd (was on disk at correct version, installs.json stale, has API key). discord: already current.
- Gateway: `reset-failed` (hit StartLimitBurst 9/10) + start → **active, 0 restarts, listening on 18789, clean start, 0 "unable to open database" errors**.
- Issue 1 code fix: `_handle_mention` now calls `openclaw agent --local --json` and parses `payloads[0].text` via new `_extract_agent_reply` (legacy raw path kept as fallback). `--json` routes all doctor-warning boxes + `[secrets]` preamble to stderr. `!ask` shares this path (delegates to `_handle_mention`), so both are fixed.
- **Verified end-to-end:** real `_handle_mention("what is 7×6")` with a live `--json` subprocess → posted **one reply "42", zero warning-box lines**.

### FIX B — Issue 5 (smart-levels showed previous close as "current")
- `_check_youtube_level_alerts` now prices via `get_live_quote_price` (Finnhub `/quote` `c`, async) instead of `_fetch_yfinance_price` (which fell back to the previous daily close). On None → skip the alert (no stale price). `_fetch_yfinance_price` left intact for its other caller (outcome tracking).
- New `_us_market_open()` (Mon–Fri 9:30–16:00 ET). Label is now `current $X` in-hours, `last close $X (market closed)` after-hours (Finnhub free `/quote` returns the last regular-session price after hours).
- **Verified:** Finnhub live prices returned (SPY 737.76, NVDA 204.87); at 21:53 ET `_us_market_open()=False` → after-hours alerts correctly say "last close … (market closed)".

### FIX C — Issue 3 (Fwd P/E wrong: 16 vs ~24)
- TODO's "sum next 4 quarters" was unbuildable (yfinance gives only 2 forward quarters). User chose current-FY basis.
- `_fetch_info` now also pulls `earnings_estimate.loc['0y','avg']` (current-FY consensus EPS) into synthetic key `_eps_cfy`; `fwd_pe = price / eps_cfy` (omit if EPS missing or ≤0). Label stays "Fwd P/E". yfinance `forwardPE` no longer used.
- **Verified via real !all gather:** NVDA 22.9 → renders "Fwd P/E 23" (was 16); AMD 66 (genuine low current-FY consensus EPS); present on AAPL/SOFI too.

### FIX D — Issue 3a (new "Today's Tweets" bull/bear field)
- TODO's bull/bear word-classifier was unnecessary — `ticker_signals.sentiment` already stores bullish/bearish per tweet. Also the TODO's query key was wrong (`source_type='twitter'`, not `'tweetshift'`).
- New `db.get_twitter_signals_today(ticker, day_start_epoch)` (full trading day, midnight ET via zoneinfo). New `_summarize_tweets_today` → {total, bull, bear, example(random non-empty)}. Wired as a task appended LAST in the aggregator gather (stable positional unpack) → `StructuredFields.tweets_today` → new `🐦 Today's Tweets` embed field (omitted when 0).
- **Verified via real !all gather:** AMD → "3 total · 3 bull · 0 bear" + example tweet; NVDA → field omitted (no tweets today). Real per-ticker volume ~3-6/day (TODO's "10" was high).

### FIX E — Issue 6 (!help stale) + BONUS bug
- Live-tested 20+ commands in-process (real handlers, captured the Discord send). 18/19 inline commands returned real data (status: 5127 signals; performance: 2171 alerts; leaderboard, levels: 8 zones; macro; etc.). `!transcript` confirmed working (fetched 2089 chars). `!all` verified separately.
- **BONUS — found & fixed a real crash:** `!yt-mentions <TICKER>` raised `NameError: is_valid_ticker is not defined` (commands.py imported only `is_valid_ticker_format`; line 395 called the un-imported `is_valid_ticker`). The util's docstring says user commands should use `is_valid_ticker_format` anyway (skips the blacklist so ETFs work) — switched line 395 to it. **Verified:** `!yt-mentions NVDA` now returns "5 results".
- HELP_TEXT: added `!cluster`, `!transcript`, noted `!readme` alias, fixed stale "list all 6 features" → "all features". No hard dead links existed.

## Files changed
consensus_engine/main.py, scanners/snapshot.py, db.py, alerts/all_command/{aggregator,embed,structured_fields}.py, alerts/commands.py, tests/test_all_command_snapshot.py
Env/config (not in git): state/ + extensions ownership, openclaw.json (web-search-plus removed), installs.json regen, gateway drop-in 10-selfheal.conf.

## Verification
- Targeted suites: 244 passed in touched modules (after updating the 1 snapshot test for new fwd_pe semantics); 39 passed in commands/mention/ask/dispatch.
- Engine: restarted twice, active; gateway active; symlink intact. (DEGRADED_MODE at startup = pre-first-poll source health + Brave 402 quota, pre-existing.)
- Full-suite regression vs `.test-baseline`: dispatched to separate verifier agent (see state.json).
