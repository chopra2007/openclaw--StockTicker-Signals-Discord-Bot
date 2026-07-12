# Near-real-time unusual options flow

**Status:** DONE 2026-05-29 — status line backfilled 2026-07-12 (TODO #72 cleanup; the header and session notes had already recorded completion).
**Created:** 2026-05-29

**Goal (plain):** the bot should read live-ish options data — the options chain, open interest, and volume — and alert on *unusual* options activity, **close to real-time, not 24-hour-old data.** Both the research AND the build happen in a fresh session (user's instruction).

**HARD CONSTRAINT (user, 2026-05-29): must be FREE.** Paying for a real-time options-flow feed is OFF the table. The research job is to find the *freshest free* source. Don't evaluate paid feeds except to note they're excluded.

---

## STEP 1 — Research the data source FIRST (do this before any code)

The whole feature lives or dies on the data source. Figure out, for each candidate, the **latency** (how fresh), the **cost**, and whether it has a usable **API**. Then recommend the best "close to real-time, not 24h" path for a free/low-budget bot, and surface the pay-vs-free decision to the user.

Candidates to evaluate (verify each — don't assume):
- **yfinance `option_chain`** — returns strike / lastPrice / volume / openInterest / impliedVolatility per expiry. Free, no key. BUT options data is typically **~15-min delayed or EOD**, and yfinance is rate-limit-fragile. Probe it: `import yfinance as yf; t=yf.Ticker('AAPL'); oc=t.option_chain(t.options[0]); print(oc.calls[['strike','volume','openInterest','impliedVolatility']].head())`.
- **Firecrawl-scrape a public unusual-options page** (e.g. `barchart.com/options/unusual-activity`) — Firecrawl is already configured in this repo (see memory `reference_apis`). Likely ~15-20 min delayed, free-ish. Check terms-of-service.
- **Polygon.io** — has an options API (chains, trades). Free tier is limited/delayed; real-time options needs a paid tier. Confirm current free-tier limits + cost.
- **Tradier** — **WONTFIX (2026-06-06, Wave 8 #31).** The free/sandbox tier serves **15-min-delayed** option chains — the SAME freshness as the yfinance source already shipped (#18, LIVE). Real-time Tradier requires a **funded brokerage account**, which violates the HARD CONSTRAINT above (must be FREE). So Tradier adds zero freshness over what we have and costs a funded account to do better → closed. (Verified no Tradier code exists in `consensus_engine/`; nothing to remove.)
- **Alpha Vantage / CBOE delayed** — confirm whether they expose OI/volume and at what delay.
- **Dedicated paid flow feeds** (Unusual Whales API, FlowAlgo, CheddarFlow) — **OUT OF SCOPE: paid.** Listed only so the new session doesn't chase them. The free path is the job.
- **Check free API tiers carefully** — Polygon.io and Tradier may gate options behind paid plans; confirm what their *free* tier actually returns before committing. Alpha Vantage has free options endpoints (confirm OI/volume + delay).

**Hard fact (verified this session):** Finnhub free tier has **NO options** data — real-time `/quote` only (per CLAUDE.md Key Design Decisions). Don't plan around Finnhub for options.

**Realistic free ceiling:** truly real-time options *time-and-sales / sweep* flow is a paid product and is OFF the table. The best FREE data is ~15-min-delayed (or EOD) option chains with volume/OI (yfinance) or ~15–20-min-delayed scraped "unusual activity" pages. So "close to real-time, not 24h" realistically means **~15-min-fresh**. The research must confirm the actual freshest-free delay and pick the best free source within that ceiling.

## STEP 2 — Reuse what already exists (verified this session)
- `consensus_engine/scanners/options.py` has **`scan_unusual_options_market(watchlist, ...)`** which is **DORMANT — it has NO caller** anywhere in `consensus_engine/` (found in the 2026-05-29 audit). Read it first: it may already implement detection logic worth reviving instead of rebuilding.
- The `!all` aggregator already carries `data['options_unusual']` and `yt_options` — there's existing options plumbing to study (`consensus_engine/alerts/all_command/aggregator.py`).
- **Alert policy already supports this:** CLAUDE.md "Alert Philosophy" lists *"unusual options activity"* and *"unusual flow"* as **instant-trigger exceptions** — they alert with NO second source required. So the alerting rule is already in place; this feature just needs to feed it.
- Watchlist: `db.get_active_tickers(min_signals=1)` (db.py:868) is the shared active-ticker list to scan.

## STEP 3 — Define "unusual" (detection)
What makes flow "unusual" (put thresholds in `config/consensus.yaml`):
- Volume far exceeding open interest (e.g. day volume > N× OI on a strike) — fresh positioning.
- Large premium / block / sweep size above a $ threshold.
- Call/put skew, far-OTM activity, short-dated expiry concentration.

## STEP 4 — Build (after the source + detection are settled)
Poll the chosen source for the watchlist on an interval → detect unusual strikes → score → fire an alert via the existing instant-trigger path → write to a table for `!all` cross-reference. Verify with a real ticker showing real unusual flow (real-world test, not just unit tests — per DoD).

## Open questions for the user (decide during the new session)
(Pay-vs-free is already DECIDED: **free only**.)
1. **Scope:** scan the active watchlist (`get_active_tickers`) or a fixed list? How many tickers (free sources are rate-limited)?
2. **Thresholds:** what volume/OI ratio and premium size count as "unusual" (avoid alert spam)?
3. **Acceptable freshness:** confirm ~15-min-delayed free data is good enough (it's the realistic free ceiling), or whether EOD-only is also acceptable as a fallback.

## Definition of Done
A real options-flow alert fires on a ticker with genuine unusual activity, with the freshness the user signed off on, verified end-to-end (not just "code runs"). Both services stay healthy; full test suite vs `.test-baseline` clean.
