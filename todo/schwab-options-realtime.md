# Move live options data onto the Schwab Trader API (real-time, official)

**Status:** OPEN
**Created:** 2026-06-29

**CURRENT STATUS (2026-06-30):** Auth + feed access is DONE and PROVEN LIVE. App registered on the
Schwab developer portal; App Key + Secret + callback (`https://127.0.0.1`) are in BOTH
`/root/.openclaw/.env` and `.env.service` (markers `SCHWAB_APP_KEY` / `SCHWAB_APP_SECRET` /
`SCHWAB_CALLBACK_URL` / `SCHWAB_APP_NAME`). First OAuth login done by hand (no adapter code): built the
authorize URL from the App Key, user logged in via browser, pasted the `https://127.0.0.1/?code=…`
redirect back, code exchanged server-side for a token. Token saved at
`/root/.openclaw/schwab_token.json` (owner openclaw, 0600), schwab-py-compatible shape
`{creation_timestamp, token:{access_token, refresh_token, expires_in:1800, …, scope:"api"}}`.
**Live AAPL chain pulled OK** via `GET /marketdata/v1/chains?symbol=AAPL` → `status:SUCCESS`,
`underlyingPrice:289.36`, **`isDelayed:False`** (real-time confirmed), 75 contracts, native
delta/gamma/theta/vega/rho + IV per contract. Both API products (Trading + Market Data) are enabled
on the app (the chain call would 401 otherwise). Gotcha proven: **auth codes expire in ~30s** — must
exchange immediately after the user pastes the redirect URL (first attempt failed `invalid_grant`).
**NEXT concrete step:** build the adapter (below) — this session only proved the pipe works.

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
