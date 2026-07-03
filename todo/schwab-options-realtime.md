# Move live options data onto the Schwab Trader API (real-time, official)

**Status:** OPEN
**Created:** 2026-06-29

**CURRENT STATUS (2026-07-02 eve):** BUILT + LIVE — and the last piece, the autonomous flow-loop alert
switch, is now **FLIPPED ON** (watched flip, user-approved). `flow_loop_enabled: true`; engine restarted
+ verified healthy (active/running, DEGRADED_MODE was a 60s post-restart transient; gate `main.py:424-427`
now routes the loop to Schwab; 27 flow tests pass). The misleading "~15-min-delayed" alert footer was
removed → `_Unusual-flow instant trigger._`. Go-live evidence:
`.claude/go-live-evidence/features_schwab_options_flow_loop_enabled.md`. Because the market was closed at
flip time, no real alert fires until **Mon 2026-07-06 open**. To tune from live data while it runs, a
REPORT-ONLY numbers run is scheduled Mon 10:00 PDT (`task_1783053334_aadb62.timer` →
`scripts/run_flow_shadow_report.sh`): it records per-contract volume / OI / vol-OI ratio / premium for
every disagreed contract (commit `fb9ff57`), posted to #chat + saved to `.claude/flow-shadow/detail_*.csv`.
Next session: read Monday's live alerts + numbers, confirm sane, tune thresholds if needed, then mark
this item DONE. See the dated updates below for the 2026-07-01 shadow result.

**Related follow-up (open):** `!em` also runs on Schwab now but its footer (`expected_move.py:463-474`)
still hardcodes "yfinance · delayed" — same mislabel the flow footer had. Flagged for a yes/no; not
fixed (needs a source field on `ExpectedMoveResult`).

**CURRENT STATUS (2026-06-30 eve):** BUILT + LIVE. The adapter and the full swap shipped this session
(discover run `schwab-options-realtime`) and the on-demand switches are ON in production
(`consensus.yaml features.schwab_options/quotes/ohlcv.enabled: true`); engine restarted + healthy.
- **New client** `consensus_engine/scanners/schwab_client.py` — real-time chains (native greeks/IV),
  quotes, price-history; thread+process-safe token auto-refresh (fcntl.flock); sync token-bucket
  rate-limiter (110/min) + 429 cooldown; SPY/QQQ full-chain 502 avoided by bounding every fetch to the
  nearest N expirations; glitch-tick overflow guard. Live-verified end-to-end.
- **LIVE now:** `!options`, `!em` (IV ÷100 verified → EM ±1.28% sane, not 100× off), `!all` max-pain,
  the live-quote path (`get_quote`/`get_live_quote_price`, Finnhub fallback — now carries volume),
  and OHLCV for peer-RS + VIX cross-asset (yfinance fallback). Daily options-chain snapshot LOGGER
  (`schwab-options-snapshot-daily.timer`, 15:50 PDT) + weekly re-auth reminder
  (`schwab-reauth-check.timer`) enabled. New DB table `schwab_options_snapshots` (schema v24).
- **DELIBERATELY kept on yfinance (RISK-5):** `wolf_outcomes` 5d/20d outcome labels + `earnings_move`
  2y — dividend-ADJUSTED historical closes feed calibration; Schwab is split-only + earnings_move is
  coupled to yfinance `get_earnings_dates`. Zero real-time benefit there. Commented at both sites.
- **ONLY remaining piece — the autonomous flow-loop alert switch** (`features.schwab_options.flow_loop_enabled`)
  stays OFF. Its thresholds (`options_flow.min_vol_oi=10/min_volume=500/min_premium_usd=250k`) were tuned
  on the delayed yfinance feed; flipping it changes messages that post on their own, and the market was
  closed tonight so no live shadow-compare was possible. A one-shot compare is SCHEDULED for
  2026-07-01 10:00 PDT (`scripts/schwab_flow_shadow_compare.py --apply` via task `1782879041_08e8ad`,
  wrapper `scripts/run_flow_shadow.sh`). **User approved fully-autonomous completion (2026-06-30):** the
  compare now AUTO-flips `flow_loop_enabled: true` + restarts the engine + posts "✅ now live" to #chat IF
  both feeds agree (≥1 qualifying hit AND ≤2 exclusives per side); a 0-vs-0 quiet snapshot OR a material
  divergence HOLDS (posts a note, no change). Verified end-to-end 2026-06-30 eve (after-hours → 0 hits →
  correctly HELD, no flip). Shipped in commit `fcd8d71`.
- Re-auth deadline: **2026-07-08 01:56 UTC ≈ 2026-07-07 18:56 PDT** (refresh does NOT extend it — the
  reminder fires from 2 days out). Full API-capabilities/future-features research is in the section below.

### Session note — 2026-07-02 — the scheduled shadow-compare ran, held OFF, DEFERRED (user decision)

The 2026-07-01 10:00 PDT auto-compare (task `1782879041_08e8ad`) ran on schedule during real market
hours and worked correctly — it just didn't like what it saw, so it correctly declined to flip
`flow_loop_enabled`. Result (`scripts/schwab_flow_shadow_compare.py --apply`, log
`/root/task_system/logs/1782879041_08e8ad.log`):

- Schwab found **201** qualifying unusual-options-activity hits across 31 tickers.
- The old yfinance feed found **182** hits across 27 tickers.
- **178 overlapped.** But **23 tickers were Schwab-only** (would fire a NEW alert Schwab sees and
  yfinance doesn't — e.g. AAPL, GOOGL, META, CRWV, IWM, HOOD), and **4 were yfinance-only** (Schwab
  would MISS an alert the old feed catches — CRWV, META, QQQ, SPY).
- Verdict written to the log: `RE-TUNE thresholds first — hit sets diverge materially`. `SHADOW_ACTION=HELD`.
  This is the correct behavior per the auto-flip rule (only flip if ≤2 exclusives/side; 23 and 4 are both
  well over that bar) — nothing broke, the switch is just not ready.
- (Note: systemd's own wrapper for that task shows as `failed (timeout)` in `systemctl status` — that's
  cosmetic, the task's own log confirms `SUCCESS after attempt 1` at the same timestamp; the outer
  service unit just doesn't consider "printed a HELD verdict" a clean exit. Not a real failure, don't
  chase it.)

**Decision (user, 2026-07-02): leave `flow_loop_enabled` OFF for now, park this for a later session.**
Why it needs work before it's a quick flip: the alert thresholds
(`options_flow.min_vol_oi` / `min_volume` / `min_premium_usd`) were tuned against the old,
~15-minute-delayed yfinance feed. Schwab's real-time feed sees things faster and more completely, so at
today's thresholds it fires on 23 tickers the delayed feed would never catch in time anyway — that's not
necessarily wrong, but it's a big enough behavior change (more alerts, different tickers) that it
shouldn't happen via an unattended auto-flip. Re-running the compare script again won't fix this by
itself (the divergence is structural, not a one-off noisy day) — next time this is picked up, start by
re-tuning the three thresholds specifically for Schwab's speed/completeness before re-testing, not by
just re-running `schwab_flow_shadow_compare.py --apply` and hoping for a closer match.

## Goal
Replace the free **yfinance** option-chain feed (unofficial, ~15-min delayed, throttle-prone)
with the **Charles Schwab "Trader API – Individual"** as the live options data source for:
- the **`!options <TICKER>`** command (unusual activity: vol/OI ratios, put/call, sweeps), and
- the **background options-flow loop** that posts instant unusual-flow alerts to the options-flow
  channel (`scan_options_flow` / `options_flow_loop`, built under #18), and
- (likely) the **`!em <TICKER>`** expected-move command (#52), which also reads the chain.

This is the real-time-free brokerage upgrade #18's detail file already named (it said "Tradier";
Schwab is the same category and the user already holds a funded Schwab account → real-time data).

## Why Schwab is a genuine upgrade (not just a swap)
Research run 2026-06-29 (web + schwab-py/community docs). Key findings:
- **Live option chains WITH greeks (delta/gamma/theta/vega/rho) + implied volatility**, native.
  yfinance gives IV only — greeks must be computed. Schwab returns them per contract.
- **Real-time** for a funded account holder (user confirmed live account → real-time, not the
  15-min delay that gates some feeds). Current yfinance feed is ~15-min delayed.
- **Official API, ~120 requests/min.** yfinance is unofficial and the scanner already had to be
  hardened around Yahoo outages/throttling — see `consensus_engine/scanners/options.py` C13
  (all-fetch-failed outage detector) + C20 (`get_yahoo_semaphore` rate-limit cap). An official
  feed should remove that whole class of silent-failure/throttle pain.
- **Free** (no API fee; needs the brokerage account, which the user has).

## Why this is NOT blocked by the #47 limitation
#47 (top/bottom detector) needs **historical** option chains back to 2008 — Schwab is
**live-snapshot-only** (no as-of-date history), so it's a hard NO for #47. But `!options` and the
flow loop only ever read **today's** chain, so the live-only limitation is irrelevant here. This is
the opposite use case. (#47's only path stays the ~$50 Alpha Vantage backfill; see also #56 =
massive.com $29 history for backtesting. Schwab does NOT serve either history need.)

## What to build
1. **A Schwab option-chain client/adapter** — OAuth2 three-legged flow; pull `/marketdata/v1/chains`
   for a ticker; map the response (calls/puts with strike, expiration, volume, openInterest,
   lastPrice/mark, greeks, IV) into the existing `OptionsResult` / chain shape the scanner expects.
2. **Wire it as the primary source** behind `check_unusual_options` + `scan_options_flow`
   (`consensus_engine/scanners/options.py`), with **yfinance kept as fallback** if the Schwab token
   is expired/unavailable (so the bot degrades, never goes dark).
3. **Config + keys:** Schwab client_id/secret + token store. Per project convention API creds live
   in BOTH `/root/.openclaw/.env` AND `/root/.openclaw/.env.service`; thresholds/flags in
   `config/consensus.yaml`. Gate the new source behind a config flag, default OFF until live-verified.
4. **(Optional, enabled by native greeks):** richer flow signals now possible — e.g. real dealer-gamma
   flavor / gamma-weighted unusual flow on a live ticker — since greeks come free from Schwab.
5. **`!em`** (#52): same chain source → swap there too once the adapter exists.

## The real operational cost — weekly re-auth
Schwab OAuth: access token expires every 30 min (auto-refresh ~29 min), but the **refresh token
expires every 7 days**, forcing a **manual browser re-login weekly**. For an always-on bot this is a
babysitting chore. Plan for it:
- Build a refresh-token rotation + a clear alert (to #chat or notifications.log) when re-auth is due,
  and keep yfinance fallback live so a lapsed token never blacks out `!options`.
- This 7-day re-auth is THE reason to keep yfinance as an automatic fallback, not rip it out.

## Other catches
- **Personal-use / no-redistribution license.** Posting unusual-activity *summaries* to the user's own
  Discord is fine; rebroadcasting raw Schwab quotes as a data feed is not. Keep output as derived
  summaries (which it already is), don't expose raw chains.
- App registration is manually reviewed (~1–3 business days); callback URL must be exact HTTPS
  (`https://127.0.0.1:8182` works for local).
- Index symbols (`$SPX`) are less reliable than ETFs on Schwab; for SPY-type tickers it's fine.

## Files / code involved
- `consensus_engine/scanners/options.py` — `check_unusual_options`, `scan_options_flow`,
  `_detect_unusual_activity`, the C13/C20 yfinance hardening (the pain this replaces).
- `consensus_engine/alerts/commands.py` — `_handle_options`, `_options_and_reply`,
  `_build_options_embed` (the `!options` command path); `!em` path for #52.
- `options_flow_loop` (the 15-min background loop feeding the options-flow channel, from #18).
- `config/consensus.yaml` — new source flag + thresholds; `.env` + `.env.service` — Schwab creds.

## Open questions
- Best Python wrapper: `schwab-py` (alexgolec) vs `schwabdev`, or a thin hand-rolled client to avoid a
  heavy dep. (schwab-py is mature but its author declines to deeply document the chain schema.)
- Can the weekly refresh-token re-auth be automated headless, or is a human browser step unavoidable?
  (If unavoidable, the alert-when-due path is mandatory.)
- Does real-time Schwab flow change the unusual-activity thresholds (vol/OI≥5, vol≥500, premium≥$250k
  from #18, since raised 5×→10× in #38)? Re-tune against live Schwab data before flipping the flag ON.

## Cross-refs
- [[options-flow-realtime]] (#18) — the original live-flow build this upgrades; already named a
  brokerage real-time upgrade as the future step.
- #47 (`vol-indicator-accuracy-research`) — why Schwab can't help THERE (needs history; Schwab is live-only).
- #56 (`options-history-backtest`) — the history need Schwab also can't serve.
- #52 (`!em` expected-move) — same chain source, swap together.

---

## API CAPABILITIES RESEARCH (2026-06-30)
Grounded in schwab-py docs (Context7 `/websites/schwab-py_readthedocs_io_en`) + the live probe this
session. Two API products are attached to the app; one OAuth token unlocks BOTH:

### A. Market Data API  (`https://api.schwabapi.com/marketdata/v1`) — read-only quotes/history
- **Option chains** (`/chains`) — VERIFIED LIVE. Real-time calls+puts, all strikes/expiries, greeks
  (delta/gamma/theta/vega/rho), IV, volume, OI, bid/ask/last/mark. This is the #57 core.
- **Option expiration list** (`/expirationchain`) — every expiration date for a symbol.
- **Quotes** (`/quotes`, `/{symbol}/quotes`) — real-time quotes for equities, ETFs, options, indices,
  mutual funds, futures, forex. Replaces the Finnhub free `/quote` we use now (and Finnhub's caps).
- **Price history / OHLCV** (`/pricehistory`) — candles by minute/day/week/month. Minute granularity
  ≈ last 48 days; daily goes back years. Replaces the yfinance-in-a-threadpool OHLCV path.
- **Movers** (`/movers/{index}`) — top gainers/losers/most-active for $SPX/$COMPX/$DJI etc.
- **Market hours** (`/markets`) — is the market open, session times.
- **Instruments / search** (`/instruments`) — symbol lookup + fundamentals (CUSIP, description).

### B. Trader API  (`https://api.schwabapi.com/trader/v1`) — YOUR ACCOUNT (read + TRADE)
This is the page the user first landed on. It can **read balances/positions AND place real orders.**
- Accounts: `/accounts/accountNumbers`, `/accounts`, `/accounts/{acct}` — balances & positions.
- Orders: GET/POST `/accounts/{acct}/orders`, GET/PUT/DELETE `/…/orders/{id}`,
  `/accounts/{acct}/previewOrder` — place / replace / cancel / preview real trades.
- Transactions: `/accounts/{acct}/transactions` — full trade history.
- User preferences: `/userPreference`.
- ⚠️ This is live-money access. Anything trade-related must be gated behind an explicit, off-by-default
  switch + confirmation. Not needed for #57's read-only options goal — flagged here for the roadmap.

### C. Streaming API  (websocket, `StreamClient`) — PUSH real-time, not poll
- `level_one_equity_subs`, `level_one_option_subs`, plus futures/forex — server PUSHES quote updates
  live instead of us polling every 15 min. Also chart & order-book streams.
- Big deal: today the options-flow loop POLLS yfinance on a timer; streaming = true tick-level
  unusual-flow detection with no polling lag and no rate-limit dance.

## FUTURE FEATURES this key unlocks (idea bank — not committed)
Ordered rough easy→ambitious. User's own examples folded in (trading bot / better history / backtest log).

1. **#57 itself** — real-time `!options`, unusual-flow alerts, `!em` on official chains + greeks. (in progress)
2. **Better historical OHLCV backbone** — move the whole engine's price history off yfinance onto
   `/pricehistory` (official, no throttle). Steadier RVOL/52-wk/technical signals. *(user idea: "better historical data")*
3. **Quotes backbone swap** — real-time `/quotes` replaces Finnhub free tier → fewer rate caps, one auth.
4. **Daily options-chain snapshot logger** → builds our OWN options history file over time. Directly
   feeds #56's backtest need and #47's top/bottom detector — Schwab is live-only, but if WE log the live
   chain daily, in N months we own the history nobody sells us cheaply. *(user idea: "tracking daily data to build a backtest file")*
5. **Native greeks flow signals** — dealer-gamma / gamma-weighted unusual flow, delta-adjusted volume;
   only possible now that greeks come free per contract.
6. **Streaming unusual-flow** — swap the 15-min poll loop for a live websocket tick feed (Streaming API).
7. **Real expected-move / IV-rank surfaces** — `!em`, IV-percentile, term-structure, skew — all from the
   real-time chain + expiration list.
8. **Portfolio-aware alerts** — read the user's ACTUAL Schwab positions (`/accounts`) so alerts can say
   "you hold this" / P&L context. Read-only, still sensitive (personal holdings) — gate it.
9. **Paper/automated trading bot** — the Trader API can place/preview/cancel real orders. Could auto-act
   on high-conviction signals, or run a preview-only "what I'd trade" shadow. *(user idea: "a trading bot")*
   HIGHEST RISK: real money, off-by-default, explicit per-trade confirm, heavy testing, start preview-only.

## Open decisions for the research write-up (when #57 is built out)
- Which of 2/3 (history + quote backbone swap) ride along with #57 vs become their own TODO items?
- #4 daily-snapshot logger is the cheapest high-value add (turns a live-only feed into owned history) —
  likely worth splitting into its own item so it starts collecting ASAP (same logic as #55).
- Trading (#8/#9) is a category change (read-only intel bot → acts on the account). Own decision + its
  own risk plan before ANY code; not to be smuggled in via #57.

### Session notes — 2026-06-30
- **Worked on:** Registered app confirmed; added `SCHWAB_*` creds to both env files (comments stripped,
  values copied to `.env.service` without displaying); did the first OAuth login by hand and PROVED the
  real-time feed live (AAPL chain, `isDelayed:False`, greeks present); token saved to
  `/root/.openclaw/schwab_token.json`. Researched the full API ability set + future-feature bank (above).
- **Decisions:** No adapter code yet — this session was creds + live proof only. yfinance stays as the
  planned fallback. Trading endpoints exist but are out of scope for #57 and gated for the future.
- **Next:** Build the Schwab chain adapter in `consensus_engine/scanners/options.py` (map → OptionsResult,
  flag-gated, yfinance fallback), add the weekly re-auth reminder, then wire `!options`/flow-loop/`!em`.
  Re-run the auth-code exchange fast (codes die in ~30s).

### Session notes — 2026-06-30 (build session, discover run `schwab-options-realtime`)
- **Worked on:** Built the whole thing. `schwab_client.py` (client + token refresh + rate limiter);
  wired Schwab-primary/yfinance-fallback into `options.py` (unusual/flow/max-pain), `expected_move.py`
  (`!em` chain + chart), the quotes backbone (`api_adapters.get_quote`/`get_live_quote_price` +
  `sector_confirmation`), the OHLCV backbone (`utils/prices.fetch_history` → peer_comparison + cross_asset
  VIX), `main.py` `_fetch_price`. Daily snapshot logger + systemd timer, weekly re-auth reminder + timer,
  DB table (schema v24), config flags + conftest guard, 13 new unit tests. Flipped on-demand flags ON,
  restarted engine (healthy), scheduled the flow-loop shadow-compare.
- **Live proof:** AAPL `!options` embed (top 37,949 vs 175 OI, ~$4.1M, 66/34 call/put), `!em` ±1.28%
  (IV ÷100 correct), SPY/NVDA flow + max-pain, `get_quote` c=289.36/v=65.1M, `fetch_history` tz-aware NY;
  logger 6/6 incl SPY/QQQ (`delayed=0`); reauth reminder 6.9d PT; regression gate 2522 pass / 0 regressions.
- **Key decisions:** hand-rolled client (no schwab-py dep); split flag so the autonomous alert loop is
  gated separately (`flow_loop_enabled`, still OFF); bound every chain fetch to nearest-N expirations
  (SPY/QQQ full chain 502s from Schwab); kept wolf_outcomes+earnings_move on yfinance (RISK-5 div-adjust).
- **Fixed a pre-existing ownership trap surfaced by the restart:** `/home/openclaw/.openclaw/openclaw.json`
  was root:root 600 (unreadable by openclaw → `❌ GATEWAY config unreadable`); chowned back to openclaw.
- **Last 5% AUTOMATED + user-approved (2026-06-30):** 2026-07-01 ~10:00 PDT the scheduled shadow-compare
  runs with `--apply` — auto-flips `flow_loop_enabled: true`, restarts the engine, posts "✅ now live" IF
  both feeds agree (≤2 exclusives/side, ≥1 hit); holds + posts a note otherwise. Commit `fcd8d71` (pushed;
  recovered a prior close-push that a stale `/tmp/pytest-prepush.log` had silently blocked). **After it
  fires, next session must commit the live `consensus.yaml` flag change** (the wrapper edits + notes it in
  notifications.log, but a scheduled task can't push).
