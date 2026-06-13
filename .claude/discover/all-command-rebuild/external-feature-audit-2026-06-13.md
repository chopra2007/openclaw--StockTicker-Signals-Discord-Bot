# `!all` external feature audit — 2026-06-13

**Purpose:** TODO #6 (`!all` quality umbrella) asks for a deep audit of what rival per-ticker tools surface that `!all` does NOT — with a **live pre-flight** of every promising source from this VPS (discipline rule 2 in `todo/all-command-quality.md`). A feature whose source is blocked is NOT a candidate until a workaround is documented.

**Method:** WebSearch for each competitor's per-ticker page sections, then `curl`/yfinance pre-flight from this VPS to confirm the field is extractable. All pre-flight numbers below are real, captured 2026-06-13.

---

## 0. What `!all` ALREADY surfaces (do NOT re-propose)

Confirmed by reading `embed.py` (fields list, lines 759-813), `scanners/snapshot.py`, `scanners/options.py`, `analysis/peer_comparison.py`, `scanners/earnings_move.py`, `structured_fields.py`.

**Embed fields (deterministic):**
- Direction, Confidence label, Price (live Finnhub `/quote`)
- R:R (reward:risk of the plan)
- Rel Vol (today vs 20-day avg volume)
- Max Pain (nearest weekly + monthly), P/C OI ratio
- Earnings ±X.X% (avg abs % move over last N prints)
- Sector Strength (peer relative strength, 5-day vs curated peer mean)
- 📊 Snapshot: analyst PT mean/high/low + count + rating, forward P/E (rolling-FY), short % of float, days-to-cover, 52-week high/low distance
- 🐦 Today's Tweets (TweetShift volume + bull/bear split + example)
- Pattern (chart pattern), YouTube analyst-call links

**LLM narrative (writeup):** trade-plan table (SL/TP1-3, buy zone, swing horizon, expected move, catalysts with evidence), thesis paragraph, risks, cross-source conflicts.

So `!all` already has the **#1 most-ubiquitous block** (analyst PT/rating, fwd P/E, short interest) and a solid options/technical layer. The gaps below are what it's MISSING.

---

## 1. The audit table

Sorted by best ratio of ubiquity-to-cheapness **with pre-flight = worked/N-A**. Build cost: trivial = piggyback on a fetch `!all` already does; medium = one new bounded fetch; big = new pipeline/multi-ticker logic.

| # | Feature (gap) | Where seen | Build cost | How common | Pre-flight access (from this VPS, 2026-06-13) |
|---|---|---|---|---|---|
| 1 | **EPS-estimate-revision trend** ("34 analysts raised, 3 cut — last 30d") | Seeking Alpha (EPS Revisions factor grade), Yahoo (EPS trend) | **Trivial** — new yfinance table, but tiny | 2/8 competitors as a headline grade; revisions data ~universal underneath | **WORKED** — `yf.Ticker('NVDA').eps_revisions` → 0q: 34 up / 3 down (7-day: 34 up / 3 down). Clean DataFrame. |
| 2 | **Analyst-consensus momentum** ("rating ↑ vs 3 months ago") | TipRanks (analyst consensus trend), Yahoo (recommendation trend), Koyfin | **Trivial** — yfinance `.recommendations` table | TipRanks core; ~half of tools | **WORKED** — `yf.Ticker('AMD').recommendations` → now 5SB/37B/9H score 3.92 vs 3m-ago 3.86 (shift +0.06). TSLA 3.43. |
| 3 | **Institutional + insider ownership %** ("Inst 69%, Insider 4%, Insider Trans −0.3%") | Finviz, TipRanks, SimplyWallSt, Yahoo Holders | **Trivial** — already in the `.info` `!all` fetches | **Near-universal** (5/8) | **WORKED (zero new fetch)** — `.info` has `heldPercentInstitutions=0.7086`, `heldPercentInsiders=0.0398`. Finviz HTML also confirms (Inst Own 69.19%, Insider Trans −0.30%). |
| 4 | **Stocktwits community sentiment + trend** ("73% bullish, −3 pts in 5d; 650k watchers") | Stocktwits, WallStreetZen, most retail tools | **Medium** — one new HTTP call (no key) | Retail-tool staple (4/8) | **WORKED** — `api.stocktwits.com/api/2/symbols/NVDA/sentiment.json` HTTP 200: 61 daily points, today 73.09% bull, 5d delta −2.7 pts. `watchlist_count=649,827`. No key, no rate-limit hit. |
| 5 | **Valuation-vs-peers / quality grades** (PEG 0.63, P/S 19.6, margins 63%, rev growth +85%) | Seeking Alpha (factor grades), SimplyWallSt (snowflake), Finviz, Koyfin | **Trivial** — already in the `.info` fetch | Sell-side standard (5/8) | **WORKED (zero new fetch)** — `.info`: `pegRatio=0.63`, `priceToSalesTrailing12Months=19.6`, `profitMargins=0.63`, `revenueGrowth=0.852`, `grossMargins=0.74`. |
| 6 | **Next earnings DATE countdown** ("Earnings in 18d — 2026-06-XX") | TipRanks, Yahoo, every tool | **Trivial** — `.info` `earningsTimestamp` (already fetched) | **Universal** | **WORKED (zero new fetch)** — `.info` `earningsTimestamp=1787774400`. (Note: `!all` already computes `next_catalyst_days` from this for the trade plan; it is NOT shown as a standalone visible field.) |
| 7 | **TradingView-style technical-rating gauge** ("Strong Buy 18/26 indicators") | TradingView (Summary gauge), Finviz | **Medium** — compute from candles `!all` already has | TradingView signature; ~half | **N/A (compute locally)** — `!all` already pulls OHLCV + RSI/EMA/ATR; a 26-indicator confluence gauge is local math, no new source. |
| 8 | **Beta / volatility context** ("Beta 2.20 — moves ~2× the market") | Finviz, Yahoo, Koyfin, SimplyWallSt | **Trivial** — already in `.info` | Common (4/8) | **WORKED (zero new fetch)** — `.info` `beta=2.202`. Finviz confirms 2.20. |
| 9 | **DCF / fair-value gap** ("12% below fair value") | SimplyWallSt (signature), some Koyfin | **Big** — needs a DCF model + assumptions | SimplyWallSt core; 1-2/8 | **PARTIAL** — `.info` has `freeCashflow=46.3B`, `totalCash`, `totalDebt`, growth rates — inputs exist, but a defensible DCF needs assumptions/peer WACC. High build, easy to get wrong. NOT a cheap lever. |
| 10 | **Options GEX / gamma exposure** ("gamma flip at $X") | Unusual Whales, options-flow bots | **Big** | Options-bot staple; ~3/8 | **PARTIAL** — yfinance option chain (already fetched for max-pain) has the OI/strike data to approximate dealer gamma, but a credible GEX needs full greeks per strike + spot-gamma modeling. Big build, easy to mislead. NOT cheap. |
| 11 | **Dark-pool prints / block trades** | Unusual Whales, FlowAlerts | **Big** | Options-bot only; 2/8 | **BLOCKED** — UW data is paid/Cloudflare-gated; no free dark-pool feed found from this VPS. Not a candidate. |
| 12 | **Hedge-fund / 13F position changes** ("3 funds added") | TipRanks, WhaleWisdom | **Big** | TipRanks; 2/8 | **PARTIAL** — SEC 13F is public (pipeline `!all` partly has via SEC EDGAR) but parsing 13F holdings → per-ticker fund deltas is a heavy quarterly-data build. Deferred. |
| 13 | **Blogger / news sentiment score** | TipRanks (blogger sentiment), SA | **Medium** | TipRanks; 2/8 | **N/A-ish** — `!all` already ingests news + does LLM thesis; a separate numeric "blogger sentiment" adds little over the existing narrative. Low value. |
| 14 | **ESG / sustainability rating** | Yahoo, SimplyWallSt | **Medium** | 2/8 | Not relevant to a swing-trade signal bot. Skip. |

### Pre-flight notes worth keeping (saves the next session a redo)

- **Finviz is ACCESSIBLE from this VPS** — the old `/quote.ashx?t=` URL now 301-redirects to `/quote?t=` → `/stock?t=`. A plain `curl` to the old URL returns `HTTP 301, 0 bytes` and looks "blocked," but **following the redirect (`curl -L`) returns HTTP 200, 300 KB**, and the snapshot table parses cleanly (regex on `snapshot-td2` cells). **Verdict: WORKED** — but everything Finviz gives (Inst Own, Insider, short %, perf, beta) is also in yfinance `.info`, so prefer yfinance (no scraping fragility, no anti-bot risk).
- **Stocktwits needs NO key** — `api.stocktwits.com/api/2/symbols/<T>/sentiment.json` (daily bull/bear % series) and `/streams/symbol/<T>.json` (live messages + `watchlist_count`) both returned HTTP 200, hundreds of KB, no auth. This is the one genuinely-new *external* data source that is cheap and worked.
- **Unusual Whales / dark-pool / real GEX: paid or Cloudflare-gated.** Confirmed not freely accessible. Anything in that bucket is out until a paid source is approved.

---

## 2. The high-leverage shortlist (cheap × ubiquitous × pre-flight green)

The rows that are **trivial/medium build AND worked/N-A** are #1, #2, #3, #4, #5, #6, #8. Of these, the ones that add *new* information `!all` doesn't already imply:

1. **EPS-estimate-revision trend (#1)** — single best ratio. Trivial (one tiny yfinance table), worked, and it is *forward-looking analyst conviction* — distinct from the static price-target `!all` already shows. "34 up / 3 down (30d)" is a clean, decision-useful signal.
2. **Stocktwits community sentiment + 5-day trend (#4)** — the only cheap *new external* source; retail-ubiquitous; `!all`'s existing "Today's Tweets" is TweetShift (analyst tweets), NOT the broad retail crowd. Different signal.
3. **Fundamentals/quality one-liner (#3+#5+#8 bundled)** — all from the `.info` snapshot.py ALREADY fetches, so literally zero new latency: PEG, rev growth, margins, beta, institutional ownership. One compact line.

(#6 next-earnings-date is trivial but the number already feeds the trade plan; surfacing it as a visible field is a nice-to-have, low novelty.)

See Part C in `.claude/discover/todo-sweep-2026-06-13/research/all-command.md` for the concrete build plan on the top 2.
