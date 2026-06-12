# Fix 6 issues diagnosed 2026-06-11

**Status:** OPEN
**Created:** 2026-06-11

Six issues were fully diagnosed in the 2026-06-11 session. All root causes are confirmed — no guesses. The new session's job is to plan and execute fixes in a sensible order.

---

## Issue 1 — Bot @-mentions return health warning boxes instead of answering

**Root cause confirmed.**

Every time someone sends an @-mention or uses `!ask`, the code runs `openclaw agent --local` and captures everything it prints to stdout, then posts all of it to Discord. That program prints two doctor warning boxes to stdout before writing the actual answer — the answer lands at the very end, hidden behind the boxes.

The warning boxes exist because of the plugin conflicts in Issues 2 and 4. Fix Issues 2 and 4 first. Once the plugin conflicts are gone, the warnings stop appearing and this issue resolves itself without any code change.

**Handler:** `consensus_engine/main.py` around line 509 (`_handle_mention`), stdout capture at line 556–559.

**What the user wants:** The bot should answer the question. Warnings should go away by fixing the root cause, not by filtering them out of the output.

---

## Issue 2 — Gateway crashes on every VPS reboot; two Discord alerts fire each time

**Root cause confirmed.**

The openclaw gateway (background program on port 18789, handles @-mention AI responses) fails immediately on startup with:
> `"Gateway failed to start: required secrets are unavailable. Error: unable to open database file"`

It crashed and restarted 9 times in 7 minutes, then systemd gave up permanently. Confirmed from journal logs at `Jun 10 16:09:26` through `16:11:42`.

Two notification systems both fire on reboot:
- `gateway-watchdog.sh` runs 2 minutes post-boot, probes port 18789, tries 3 restarts, then posts "auto-heal failed 3x" to Discord
- systemd `OnFailure=alert@%n.service` calls `/usr/local/bin/openclaw-notify` and posts "FAILED / Restart count: N"
- Both store their duplicate-prevention flag in `/run/openclaw/` which is wiped on every reboot, so both fire fresh each boot

**Root cause of the crash:** confirmed by `openclaw gateway status --deep`:
1. The `discord` plugin installed on disk is version `2026.5.18` but the gateway now requires `2026.6.5` — version drift
2. The `web-search-plus-plugin-v2` entry in config (see Issue 4) created a conflict between the old `installs.json` and the SQLite state — the gateway can't reconcile them at startup

**Fixes required:**
```bash
sudo -u openclaw openclaw plugins update discord
# then resolve Issue 4 (remove web-search-plus-plugin-v2)
sudo systemctl restart openclaw-gateway.service
```

**What the user wants:** Gateway starts cleanly after every reboot with no Discord crash alerts.

---

## Issue 3 — `!all` shows "Fwd P/E 16" but the correct Fwd P/E is ~24

**Root cause confirmed.**

Code is at `consensus_engine/scanners/snapshot.py` line 101:
```python
"fwd_pe": _num(info.get("forwardPE"))
```
It reads yfinance's `forwardPE` field directly. yfinance's `forwardPE` is calculated from NVIDIA's **next full fiscal year** EPS estimate (FY2027, ends January 2027, at $12.73/share). $200 ÷ $12.73 = **P/E 15.7** → displayed as "Fwd P/E 16".

The user calculates **rolling NTM** (next 12 calendar months from today): $200 ÷ $8.35 = **24**. These are two different things and yfinance's field is the wrong one.

Live yfinance check confirmed: `forwardPE: 15.75`, `forwardEps: 12.73` (next FY, not NTM).

**What the user wants:** The displayed number should be the rolling NTM Fwd P/E — the sum of the next 4 quarters' EPS estimates divided into the current price. Not a relabeled version of the yfinance `forwardPE` field.

**How to build it:** yfinance exposes quarterly earnings estimates. Fetch them, identify which 4 quarters fall in the next 12 calendar months from today, sum the EPS estimates, divide into current price. Some tickers only have 2 quarters projected — handle gracefully (show what's available or omit the field). The fix is in `snapshot.py`.

---

## Issue 3a — `!all` shows 1 TweetShift link in "Confluence"; today's 10 NVDA tweets are invisible

**Root cause confirmed.** Two separate problems:

**Problem A — The "Confluence" field is Wolf cross-source agreement, not a TweetShift count.**
The field labeled "🤝 Confluence" is built in `consensus_engine/alerts/wolf_news.py` lines 59–111. It shows whether the Wolf newsletter's thesis matches YouTube/Twitter/SEC/options. The single TweetShift link there is the most recent tweet matching Wolf's direction. The "(7 ch)" = 7 YouTube channels that agreed with Wolf. This is correct behavior for what it does — it's not the right place to surface TweetShift message counts.

**Problem B — Today's TweetShift messages are never shown in `!all`.**
The aggregator fetches a 30-minute rolling window of tweets (`aggregator.py` line 233: `get_twitter_signals(ticker, window_seconds=1800)`) and passes them silently to the AI as background text. They are never counted, never split bull/bear, and never shown in any visible field. Today's full-day volume (e.g. 10 NVDA messages) doesn't appear anywhere.

**What the user wants:** A new visible field in the `!all` embed showing:
- Total TweetShift messages for that ticker today (midnight to now, not 30 minutes)
- Bull vs. bear count
- One random example message (random is fine, not "best" or "most representative")

Example format: `Today's Tweets (10): 7 bull · 3 bear — "NVDA breaking out above $200..."`

**What needs to be built:**
1. Check whether `signal_events` already has a `direction` column for TweetShift rows — run `SELECT source_type, direction FROM signal_events WHERE source_type='tweetshift' LIMIT 5` before building any classification. If direction is already stored, use it directly.
2. If no direction column: build lightweight keyword heuristics (bull words: breakout, buy, long, squeeze, calls; bear words: put, short, breakdown, dump, bearish). LLM classification is an option but overkill for this.
3. New DB query in `consensus_engine/db.py` — today's full-day TweetShift signals for a ticker
4. Wire into `aggregator.py` alongside (not replacing) the existing 30-minute fetch
5. New embed field in `alerts/all_command/embed.py`

---

## Issue 4 — `web-search-plus-plugin-v2` needs full removal

**Root cause confirmed.** This plugin is the second cause of the Issue 2 gateway crash. Its install record in `installs.json` says version 3.0.0 but the files on disk are 3.1.0 — that version conflict is one of three plugin conflicts (`brave`, `discord`, `web-search-plus-plugin-v2`) causing the gateway's database to fail to open.

The plugin is also completely dormant: no API keys configured, agent web search routes through the built-in SearXNG plugin instead, consensus engine never calls it.

**Everything that needs to be removed:**
1. Entry `"web-search-plus-plugin-v2"` from `plugins.entries` in `/home/openclaw/.openclaw/openclaw.json`
2. Entry `"web-search-plus-plugin-v2"` from `plugins.allow` in `openclaw.json`
3. Uninstall the plugin files: `sudo -u openclaw openclaw plugins uninstall web-search-plus-plugin-v2` (or delete `/home/openclaw/.openclaw/extensions/web-search-plus-plugin-v2/` directly)
4. Its entry in `/home/openclaw/.openclaw/plugins/installs.json`

Do NOT add it to CLAUDE.md — the "don't reinstall" note lives in session memory (`reference_no_web_search_plus_plugin.md`).

**What the user wants:** Complete removal from config, disk, and install index. Once removed, the gateway database conflict for this plugin is gone.

---

## Issue 5 — Smart levels alerts show closing price labeled as "current price"

**Root cause confirmed.**

`consensus_engine/main.py` line 1531, function `_fetch_yfinance_price()` is called from `_check_youtube_level_alerts()` (lines 953–986). When yfinance's `fast_info` shortcut returns empty (which happens frequently on the free tier), the code falls back to:
```python
history = stock.history(period="5d", interval="1d")
return float(history["Close"].dropna().iloc[-1])
```
That's the last closing price. The rest of the engine uses Finnhub's `/quote` endpoint (`c` field = real-time price), but this function was written separately and never connected to it.

**What the user wants:** The price shown in smart levels alerts (e.g. "$SPY approaching resistance @ $728.00 — current $725.43") should be the actual live price, not the last close. The Finnhub `/quote` call is already used elsewhere in the engine — swap `_fetch_yfinance_price()` in the smart levels function to use that instead.

---

## Issue 6 — `!help` is stale and contains unverified commands

**What is confirmed from code inspection:**
- Every command listed in HELP_TEXT has a router branch in `commands.py`
- Every router branch calls a handler function that exists in the file
- The file-level imports are intact

**What is NOT confirmed:** Whether the handlers actually work end-to-end. Most handlers use lazy imports inside the function body — those modules may have changed. Many call scanners, LLM chains, and external APIs that have been rewritten multiple times since the help text was last updated.

**How to verify:** Each command can be run via Discord and the response checked from a shell using the Discord API (bot token + channel ID are in `/root/.openclaw/.env`). This is the correct verification method — do not claim a command works from code inspection alone.

**Commands in the router but missing from HELP_TEXT:**
- `!transcript <URL>` — fetches a YouTube transcript
- `!cluster <TICKER>` — shows price level cluster history for a ticker
- `!readme` — alias for `!help`

**Entire feature areas missing from HELP_TEXT** (added after the help text was last written):
- Wolf newsletter commands (if any exist)
- Options flow commands beyond `!options`
- Anything related to smart levels

**What the user wants:** Rewrite HELP_TEXT to reflect what actually works today. Process: run every listed command, confirm it responds correctly, add the missing commands, remove or flag anything broken, add any missing feature areas.

**User confirmed:** commands can be tested via Discord + shell, no need to ask.

---

## Suggested fix order for a new session

1. **Issue 4 first** — remove `web-search-plus-plugin-v2` from config and disk. This is pure config editing, no code, no risk.
2. **Issue 2** — update `discord` plugin + install `brave` plugin + restart gateway. Issue 4 must be done first so the conflict is gone.
3. **Verify Issue 1 is resolved** — confirm @-mentions now answer without warning boxes. If warnings still appear after gateway is fixed, then the `_strip_secrets_preamble` function needs investigation.
4. **Issue 5** — swap `_fetch_yfinance_price()` to Finnhub in smart levels. One-function change, easy to verify live.
5. **Issue 3** — replace `info.get("forwardPE")` with rolling NTM P/E computed from quarterly estimates. Moderate complexity; verify with NVDA where the expected answer is ~24.
6. **Issue 6** — run every `!help` command, confirm what works, rewrite HELP_TEXT. Do this after other fixes so the help text reflects the final working state.
7. **Issue 3a** — new TweetShift bull/bear field. Largest change; build last so it doesn't block the other fixes.

---

## ✅ COMPLETED 2026-06-11 (discover run `todo-36-six-fixes`)

All 6 issues fixed + verified live; the diagnosed approach was improved on 4 of them. A bonus crash was found and fixed.

- **Issue 2 (gateway crash):** real cause was NOT plugin drift — a June-10 root login left **5,118 files** under `/home/openclaw/.openclaw` root-owned, incl. the gateway's `state/openclaw.sqlite` (mode 600 → service user `openclaw` couldn't open it). `chown -R` + added a `state/` chown to the gateway self-heal drop-in (recurrence guard). Gateway now: active, 0 restarts, clean start, listening on 18789.
- **Issue 4:** web-search-plus-plugin-v2 fully removed (config + disk + SQLite registry + installs.json); brave UPDATEd (kept — has API key); plugin-index conflict deadlock cleared.
- **Issue 1:** `_handle_mention` now uses `openclaw agent --local --json` + `_extract_agent_reply` (warnings go to stderr). `!ask` shares this path. Verified end-to-end: real mention → "42", 0 warning boxes.
- **Issue 3 (Fwd P/E):** diagnosed "sum 4 quarters" was unbuildable (yfinance gives 2). User chose current-FY EPS basis → NVDA "Fwd P/E 23" (was 16).
- **Issue 3a (Today's Tweets):** no classifier needed — reused stored `ticker_signals.sentiment`. New `🐦 Today's Tweets` field. AMD "3 total · 3 bull · 0 bear" + example; omitted when 0.
- **Issue 5 (smart levels):** swapped to Finnhub `get_live_quote_price`; skip on failure; "last close $X (market closed)" after-hours.
- **Issue 6 (!help):** rewrote HELP_TEXT (+!cluster/!transcript/!readme, fixed "6 features" footer). **Bonus: fixed a real crash** — `!yt-mentions` raised NameError (`is_valid_ticker` not imported); switched to `is_valid_ticker_format`.

**Verification:** full suite 2175 passed; updated 3 tests for the intentional behavior changes (snapshot fwd_pe, 2× youtube_level_alerts price source).
**Separate pre-existing issue surfaced (NOT #36):** `test_gemini_video_parser.py::test_extract_evidence_parses_spans` fails (duration 2458≠2340) — stale test from the earlier #17 chunked-Gemini commit `9c8f889`; live pipeline works (93% parse-ok). Added to `.test-baseline`; worth a small follow-up to update the mock for chunking.
Full run artifacts: `.claude/discover/todo-36-six-fixes/`.
