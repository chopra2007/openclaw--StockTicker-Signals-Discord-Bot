# Move live options data onto the Schwab Trader API (real-time, official)

**Status:** OPEN
**Created:** 2026-06-29

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
