# final-plan.md — TODO #36, six fixes (2026-06-11 diagnosis)

Build spec for Pass 5. Every approach below was re-evaluated against the goal by a read-only agent; where the TODO's diagnosed approach was wrong or unbuildable, the corrected approach and the evidence are noted. Deep evidence per issue in `eval-agent-1.md` … `eval-agent-4.md`.

## 1. System Overview

Six independent fixes to the Discord stock-signal bot. Two are environment/config ops (gateway + plugins), four are code changes (price math, live price source, a new embed field, the help text). No new subsystems; each fix touches existing code paths. Build order is chosen so the environment fixes (which also resolve a third issue for free) land first, code fixes next, and the help-text rewrite last so it reflects the final working state.

## 2. Per-fix design

### FIX A — Gateway crash on reboot (Issue 2) + remove web-search-plus-plugin-v2 (Issue 4) + mention warnings (Issue 1)
**Diagnosis correction:** the TODO blamed plugin version drift. The real mechanical cause is **file ownership**: `/home/openclaw/.openclaw/state/` (root:root 700) and `state/openclaw.sqlite` (root:root 600) are unreadable by the gateway, which runs as user `openclaw` → "unable to open database file" → "required secrets are unavailable". Flip happened during a root-session plugin install on 2026-06-10. Plugin drift (discord on disk 2026.5.18 vs required 2026.6.5) is a real but secondary problem. `web-search-plus-plugin-v2` is still fully present (the memory note claiming it was removed is wrong); the gateway currently *ignores* it as a stale entry rather than crashing on it.

**Steps (run as listed; all need sudo):**
1. `sudo chown openclaw:openclaw /home/openclaw/.openclaw/state && sudo chmod 700 /home/openclaw/.openclaw/state`
2. `sudo chown openclaw:openclaw /home/openclaw/.openclaw/state/openclaw.sqlite`
3. Check `/home/openclaw/.openclaw/npm/` ownership; if root-owned, `sudo chown -R openclaw:openclaw /home/openclaw/.openclaw/npm` (else the `openclaw`-run plugin updates fail).
4. `sudo chown -R openclaw:openclaw /home/openclaw/.openclaw/extensions/brave /home/openclaw/.openclaw/extensions/web-search-plus-plugin-v2`
5. `sudo -u openclaw openclaw plugins uninstall web-search-plus-plugin-v2` (CLI removes disk + installs.json cleanly — do NOT hand-edit installs.json; it has a policyHash).
6. Remove `"web-search-plus-plugin-v2"` from `plugins.entries` AND `plugins.allow` in `/home/openclaw/.openclaw/openclaw.json`. **After editing as root, restore owner:** `sudo chown openclaw:openclaw openclaw.json && sudo chmod 600 openclaw.json` (ownership trap — editing as root crash-loops the gateway).
7. `sudo -u openclaw openclaw plugins update discord`
8. `sudo -u openclaw openclaw plugins update brave` (brave is on disk at the correct version but installs.json is stale; it has a configured API key — UPDATE, don't remove).
9. Prevent recurrence: add `ExecStartPre=+/bin/chown -R openclaw:openclaw /home/openclaw/.openclaw/state` to the gateway service drop-in (the existing drop-in already chowns openclaw.json + sources.json but not state/).
10. `sudo systemctl daemon-reload && sudo systemctl reset-failed openclaw-gateway.service && sudo systemctl start openclaw-gateway.service` (reset-failed needed — unit hit StartLimitBurst 9/10; plain restart may refuse).
11. Verify: `systemctl status openclaw-gateway.service` = active; `curl http://127.0.0.1:18789/` responds.

**Issue 1 (mention warnings) — also apply a defensive code fix.** Fixing the gateway stops the two doctor-warning boxes from being printed, so the current code would post clean answers. But relying solely on a clean gateway is fragile (any future drift silently re-leaks boxes into Discord). Apply the structural fix: in `consensus_engine/main.py` `_handle_mention` (~545-559), add `--json` to the `openclaw agent --local` subprocess call and parse `payloads[0].text` as the answer; keep the current raw-stdout path as a fallback if JSON parse fails. `--json` routes ALL warnings (doctor boxes + `[secrets]` preamble) to stderr.

**Safe to do live:** yes. Gateway is already down (failed); the consensus-engine Discord bot is a separate service and keeps running; `channels.discord.enabled` is false so no live gateway Discord connection is interrupted.

### FIX B — Smart-levels shows previous close as "current price" (Issue 5)
**Confirmed.** `main.py:1531 _fetch_yfinance_price` (sync, built for 1h/24h outcome tracking) falls back to `history(period="5d")` last Close. Called from `_check_youtube_level_alerts` (`main.py:939`, runs every 300s in `fetch_loop`), printed as `current ${price}` at `main.py:986`.

**Approach (best of three evaluated — reuse, not raw swap):** Replace the `_fetch_yfinance_price` fan-out in `_check_youtube_level_alerts` with the project's designated live-price helper `get_live_quote_price` (`consensus_engine/api_adapters.py:274`, async, Finnhub `/quote` `c`-field, returns `None` on failure) — the same anchor the sibling code `scanners/youtube.py:456 _safe_live_price` already uses. Use `asyncio.gather` over the level tickers. **On `None`, skip that ticker's alert** (do not fall back to a stale close under the "current" label). Add a market-open guard (reuse `FinnhubContext.market_ok` / `_is_weekend_pause`): in-hours render `current $X`; when closed render `last close $X (market closed)` — Finnhub free `/quote` doesn't return live extended-hours prices, so the label must be honest after hours.
**Rate limit:** low risk (5-min cycle, only tickers with a stored YouTube level in last 14 days). Optional hardening: route the fan-out through `rate_limiter.acquire("finnhub")` if the level set ever exceeds ~40 tickers.

### FIX C — Fwd P/E uses next-FY EPS, not rolling NTM (Issue 3) — ⚠ NEEDS USER DECISION
**Confirmed + correction.** `snapshot.py:101 "fwd_pe": _num(info.get("forwardPE"))`. yfinance `forwardPE` = price ÷ next-full-fiscal-year EPS (NVDA $12.73) = ~16. **The TODO's suggested fix (sum the next 4 quarters' EPS) is not buildable: yfinance exposes only 2 forward quarters (`0q`,`+1q`), never 4 — confirmed on NVDA/AAPL/MSFT/TSLA/SOFI.** And a true rolling-next-12-months EPS for NVDA ≈ $10.26 → P/E **~20**, NOT the ~24 the user cited. The user's ~24 (=200/8.35) corresponds to the **current-fiscal-year** consensus EPS (yfinance `earnings_estimate.loc['0y','avg']` = 8.96 → 204.87/8.96 = **22.9 ≈ 24**).

**→ Two options for the user (see decision block at end). Recommended: Option A (current-FY EPS).**
**Approach if Option A:** in `snapshot.py`, fetch `yf.Ticker(t).earnings_estimate.loc['0y','avg']` (extend `_fetch_info` to also return `earnings_estimate` — it currently returns only `.info`); `fwd_pe = price / eps_cfy` when `eps_cfy` and `> 0` and `price` present, else **omit the field** (matches the file's existing no-data behavior). Price = existing `.info` chain (currentPrice→regularMarketPrice→previousClose), no extra fetch. Label stays "Fwd P/E" (current-FY basis; drop the "NTM" wording since it isn't strictly NTM).

### FIX D — New "Today's Tweets" bull/bear field in !all (Issue 3a)
**Correction:** the TODO's check query is wrong — there is no `source_type='tweetshift'`; tweets are stored as `source_type='twitter'`. The bull/bear direction is **already stored** — no classifier needed (not keyword, not LLM). Use `ticker_signals.sentiment` (bullish/neutral/bearish) + `raw_text` (the example tweet). This is the direction the alert pipeline itself already uses; re-deriving with keywords risks disagreeing with it.

**Approach:**
1. `db.py` (~near `get_twitter_signals`, line ~1070): add `get_twitter_signals_today(ticker, day_start_epoch)` — same `ticker_signals` table, SELECT `sentiment, raw_text` (the existing 30-min query omits sentiment), filter `detected_at >= day_start_epoch`. Keep the existing 30-min fetch untouched (still feeds the narrator).
2. `aggregator.py` (`_gather_all_sources` ~233): add a parallel `twitter_today` task alongside the existing 30-min task; add to gather/unpack/data-dict (~315/343/388). Build `{total, bull, bear, example}` (bull=bullish count, bear=bearish count; example = a random row with non-empty `raw_text`). Day start = today midnight in **America/New_York** via `zoneinfo.ZoneInfo` (NOT the hardcoded `main.py:49` -4h offset, which breaks in winter).
3. `embed.py` `build_embed`: append a field after the `📊 Snapshot` block (~797): `🐦 Today's Tweets (N): X bull · Y bear — "example…"`. **Skip the field entirely if N=0** (don't render "(0)").
**Reality note:** real per-ticker volume is ~3-6/day for busy names, so many tickers will show `(1)` or nothing — that's expected, not a bug.

### FIX E — Rewrite !help (Issue 6)
**Confirmed:** no hard dead links (every documented command routes). Gaps are omissions: `!transcript`, `!cluster`, `!readme` (alias of `!help`) are in the router but missing from HELP_TEXT (`commands.py:141-182`); footer "list all 6 features" is stale. No `!wolf`/`!chart`/extra-options commands exist — don't invent them.

**Approach:** live-test commands in dependency waves (cheapest/most-reliable first), then rewrite HELP to match reality:
- Wave A (DB-only, deterministic): status, signals, analysts, active-tickers, alert-history, leaderboard, source-health, levels, cluster, yt-mentions, feature-health, sec — prove the router is alive.
- Wave B (single external API): trend, performance, options, technical, google-trends, apewisdom, market-view.
- Wave C (LLM chains): all, ask.
- Wave D (YouTube/transcript/vision — most fragile, VPS IP is YouTube-blacklisted, budget for failure): transcript, yt, yt-health, yt-evidence.
Then: add `!transcript`/`!cluster`, note `!readme` alias, annotate/remove anything that fails Wave D, fix the footer. Test via the documented **#chat ClaudeCode webhook** (bot reacts 👀 when it reads the command — bots can't see their own gateway messages). Confirm `discord_tweetshift: Discord Gateway READY` for the current boot before pinging.

## 3. Data flow / integration points (files touched)
- `consensus_engine/main.py` — `_handle_mention` (Issue 1 `--json`); `_check_youtube_level_alerts` (Issue 5 live price + market-open label).
- `consensus_engine/scanners/snapshot.py` — `_fetch_info` + fwd_pe line (Issue 3).
- `consensus_engine/db.py` — new `get_twitter_signals_today` (Issue 3a).
- `consensus_engine/alerts/all_command/aggregator.py` — wire today-tweets task (Issue 3a).
- `consensus_engine/alerts/all_command/embed.py` — new field (Issue 3a).
- `consensus_engine/alerts/commands.py` — HELP_TEXT rewrite (Issue 6).
- Env/config (no repo code): `state/` + `openclaw.sqlite` ownership, `openclaw.json`, gateway drop-in, plugin installs (Issues 2/4).

## 4. Failure handling
- Issue 3: missing/≤0 EPS → omit field. Issue 3a: 0 tweets → skip field; empty raw_text → counts only; multi-ticker tweet example may be off-ticker (acceptable v1). Issue 5: `None` price → skip alert; market closed → "last close" label. Issue 2/4: if npm dir root-owned, chown before plugin updates; reset-failed before start.

## 5. Feature activation
These are bug FIXES to existing visible output, not speculative features — they go live on deploy, not behind flags. After code fixes: restart `consensus-engine.service` (and confirm `openclaw-gateway.service` active for Issues 1/2). Issue 3a's new field and Issue 3's number appear in the next `!all`; Issue 5's label in the next smart-levels alert.

## 6. Verification checklist (Pass 5 must show real evidence for each)
1. `systemctl status openclaw-gateway.service` = active after a `reset-failed`+start; `curl 127.0.0.1:18789/` responds. (Reboot-persistence: drop-in chown present.)
2. web-search-plus-plugin-v2 absent from openclaw.json entries+allow, installs.json, and extensions/ dir. openclaw.json owner = openclaw:openclaw 600.
3. Real @-mention in Discord returns the answer with NO warning boxes (test via #chat webhook; show the bot's reply).
4. Real `!all NVDA`: Fwd P/E renders ~22-24 (not 16); new 🐦 Today's Tweets field renders with bull/bear counts + example (or is correctly absent if 0 tweets). Show the embed.
5. Smart-levels: a real proximity alert (or a forced test invocation) shows a live price in-hours / "last close … (market closed)" after-hours — not a silent previous close labeled "current".
6. `!help` output matches the rewrite (includes !transcript/!cluster, !readme alias noted, footer fixed); each Wave A-D command live-tested with its actual Discord response recorded; anything broken is annotated, not silently listed as working.
7. Regression gate: full test suite vs `.test-baseline` shows zero new failures. (Commit locally per fix; push deferred to session close per CLAUDE.md — do NOT push mid-session.)

## ⚠ DECISION NEEDED FROM USER (Issue 3)
The number you cited (~24) and the words you used ("rolling NTM / next 12 months") point at two different things:
- **Option A — show ~24 (current fiscal-year P/E).** Matches the ~24 you expect and what most retail sites show; reliable data on every ticker. (Recommended.)
- **Option B — show ~20 (strict next-12-months / true NTM).** Matches the "NTM" wording exactly, but it's not the ~24 number, and the data is sparse (yfinance only gives 2 forward quarters, so part is estimated).
