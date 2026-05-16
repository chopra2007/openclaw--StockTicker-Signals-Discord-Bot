# `!all <TICKER>` — External Feature Audit
**Date:** 2026-05-16 · **TODO ref:** [TODO #7](../TODO.md#7-optimize-all-output-quality--feature-surface-open-ended-initiative) · **Discover run:** `external-feature-audit-2026-05-16`

## How to use this audit

This is a **menu**, not a checklist. Pick ONE ship, write a focused spec for it, run it against the Layer-C / Gemini blind-compare in TODO #1, deploy. Don't try to "do the audit" — that's how the !all rebuild produced "v1 ships but quality fails Gemini bar."

Skim order for a fresh session:
1. **§1 The 14 ships** — bundle-corrected ranking; this is the actionable menu
2. **§4 Per-ship risk caveats** — cross-model Gemini + Codex agreement on what will bite you
3. **§5 Pre-flight reality** — what's reachable from this VPS vs what needs a workaround
4. **§2 The full audit table** — reference inventory (everything researchers surfaced, all 5 spec columns)

Underlying scratch: `.claude/discover/external-feature-audit-2026-05-16/` (5 researcher reports + 2 preflight passes + critic + cross-model artifacts).

---

## §0 What `!all` already produces (excluded from candidate set)

Per [TODO #7 architecture map](../TODO.md#7-optimize-all-output-quality--feature-surface-open-ended-initiative): trade plan (direction / confidence label / buy zone / TP1-TP3 / stop loss), horizon (breakout timeframe, swing horizon, magnitude band, earnings-only catalyst countdown), basic technicals (RSI / SMA20-50-200 / ATR / volume / chart_pattern), 18 evidence blocks fed to the 5-model narrator (news from Finnhub + Brave + SearXNG, SEC EDGAR, TweetShift Twitter, Reddit/social, YouTube yt_signals/yt_options/yt_evidence, internal Discord history, vault excerpts), LLM-synthesized prose narrative, contradict-detection retry via `output_filter.py`, Discord embed + vault markdown + 15-min xref_cache. Everything below is filtered to features the bot does NOT already render or compute.

---

## §1 The 14 ships — bundle-corrected ranking

Bundle corrections from Pass-3 adversarial review: many pass-2 "separate top-25" features are derivatives of the same data path (e.g. five GEX features fall out of one chain parser + one dealer assumption). The list below counts **independent ships**, with bundle membership in parens.

| Ship | Bundle members | Why first | Build | Pre-flight | Caveat |
|---|---|---|---|---|---|
| **1. Format & UX Pack** | N1/N2/N3/N4/N5/N7 (splittable into 5×1-hr PRs) | Universal across competitors AND universal cheapness — by pass-2's own commonality × cheapness score, ties rank 1 (5×5×5=125). Visually transforms embed from "engineer-tool" to "trader-tool" with zero data work. | trivial each | N/A (format) | N7 (relative dates) depends on TODO #4 time-context fix. |
| **2. Narrative Pack v1** | M1 (TL;DR header), M2 (Bear Case), M3 (variant perception), M6 (enumerated risks) | 4 competitor format-families converge on these. Highest "completeness" win for zero data work. | trivial (prompt) → medium (quality_bar constraint, per critic) | N/A | **Codex risk:** counter-thesis can contradict COMPUTED SIGNAL — prompt must be reconciliation-aware. **Gemini risk:** LLM may hallucinate negative catalysts for fundamentally strong tickers. Ship with both prompt clauses + structured `quality_bar.py` constraint. |
| **3. Insider Activity Pack** | A1+A2+A4+A5 (one yfinance dataframe + one info key) | 6 competitor sources, free data, real narrative signal. | trivial | N/A — `yf.Ticker.insider_transactions` + `info["heldPercentInsiders"]` confirmed live | **Both models flagged:** RSU/option exercises vs real open-market buys can flip the net-delta sign. Filter by `Transaction` type. **Critic:** yfinance insider feed lags SEC RSS — coverage will be sparse for small caps. |
| **4. Short Pressure Pack** | B1+B2 (one `.info` payload) | 6 sources, free, highly requested for retail names. | trivial | N/A — `info["shortPercentOfFloat", "shortRatio"]` confirmed live | **Both models flagged:** yfinance short data is up to **4 weeks stale** (mirrors bimonthly FINRA file). **Mitigation:** consider ChartExchange daily-shortvol file (preflight HAS_DATA 190k) as fresher overlay. Mega-cap blunting also flagged — narrator should temper "squeeze risk" framing on big floats. |
| **5. Analyst Pack** | D1+D5 (yfinance `.info` already returns 5 keys) | 6 competitor sources. **Pass-3 bonus finding:** yfinance `.info` exposes `recommendationMean / recommendationKey / targetMeanPrice / targetHigh-/Low-/MedianPrice / numberOfAnalystOpinions` — no Finnhub call needed. Pass-2's "/stock/recommendation already wired?" was wrong (it's NOT wired) but the simpler yfinance path makes it irrelevant. | trivial | N/A (yfinance live-verified) | **Both models flagged:** targets lag price + anchoring effect (users won't exit before "avg" target). Narrator should frame target as "consensus benchmark, not a forecast." Small-coverage names (n<5 analysts) skew distributions — gate display below n=5. |
| **6. Earnings Track Record Pack** | E1+E5+E8 (one `earnings_dates` call) | 4 sources, free, directly actionable ahead of next report. | trivial | N/A — `yf.Ticker.earnings_dates` returns `EPS Estimate / Reported EPS / Surprise(%)`; live-verified | **Both flagged:** estimate/actual mismatch + fiscal-quarter alignment errors (Codex); yfinance earnings dates often "estimated" and shift (Gemini). Show only when (a) earnings within 30 days or (b) most recent print < 14 days. Outside that window it's screen-space waste. |
| **7. Catalyst Pack** | L1+L2+L3+L4+E6 | 3 competitor format families distinguish Hard (dated) vs Soft (timing-uncertain) catalysts and event-type-label. Bot today only handles earnings countdown. | trivial-to-medium — extend `compute_next_catalyst_days` to merge ex-div, options expiry, FDA/contract/M&A signals already surfaced by news_catalyst + add BMO/AMC tag | N/A — Finnhub `/calendar/earnings` already wired; `yf.dividends`/`yf.options.expirations` confirmed | Show only the **nearest** catalyst of each type — multi-catalyst lists become noise. |
| **8. Implied Move ±$ / ±%** | E2 / F16 | 4 sources; converts chain into immediately-usable range. | trivial — `0.85 × (ATM_call + ATM_put)` mid-price | N/A — yfinance `option_chain` live-verified (25 expiries on AAPL) | **Both flagged:** `0.85 ×` is folklore — for high-skew tickers (post-bad-news names) understates by 10-20%. Wide spreads / broken ATM strike selection on thin chains overstates wildly. **Mitigation:** only emit when ATM bid-ask spread < X% AND OI > Y; otherwise omit. |
| **9. Max Pain Pack** | F1+F1a (max pain + pin-risk OI cluster) | 7 competitor sources cite it. Most-asked options metric in fintwit. | trivial — argmin over chain | N/A | **Both flagged:** illiquid weeklies create false "pin" levels; trade-plan implication is ambiguous (magnet, not direction). Frame as "near-term gravity level," not "target." Demote from pass-2 #1 to here (mid-pack) because directional value is genuinely lower than insider / analyst / earnings packs. |
| **10. Put/Call & OI Pack** | F8+F9 | 4 sources; pairs with implied-move and max-pain without heavy model risk. | trivial — chain aggregation | N/A | **Codex risk:** aggregating across all expiries hides the only positioning that matters. **Mitigation:** report PCR per-expiry-bucket (front-week / front-month / quarterly), not single number. Top 3 OI strikes: per-side, per-nearest-expiry only. |
| **11. EPS Revisions Pack** | D2 (revisions count 7/30/60/90d) | Leading indicator value > pure commonality score. Zacks's actual moat (Earnings ESP derives from this). | medium — Finnhub `/stock/recommendation` historical OR compute from analyst estimate timeline | N/A (Finnhub free-tier) | **Codex risk:** revisions cluster around earnings prints — 7d window is dominated by post-print catch-up. Gate against earnings-week or document the bias. |
| **12. Dark-Pool Pack** | F13+F13a (DP % of vol + DIX-equivalent buy-pressure) | 3 sources, FINRA file confirmed `HAS_DATA` (510k bytes daily file). | medium — FINRA RegSHO CSV parse + cache | worked (FINRA `cdn.finra.org/equity/regsho/daily/CNMSshvol*.txt`) | 2-week disclosed lag on official "ATS Transparency" file. The daily short-sale-volume file is fresher but is short-sale-volume not net DP. Be precise about which metric is shown. |
| **13. Forward Forecast Pack** | J1+J2+J4 (Forward PE FY+1/FY+2 + revenue/EPS estimates + PEG) | 4 sources. | trivial — `info["forwardPE", "pegRatio"]` live-verified | N/A | Forward PE = current price / next-12mo EPS estimate — same anchoring caveat as D1. |
| **14. Mention Velocity** | I2 (cross-source Reddit + Twitter + Stocktwits multiplier vs 30d median) | 3 sources; leading-indicator on social ignition. Bot already ingests Reddit + Twitter — half-built. | medium — needs cross-source aggregation + 30d-median persistence | N/A for Reddit/Twitter; partial for Stocktwits (web page CF-blocked but `api.stocktwits.com/api/2/streams/symbol/<T>.json` is open) | Polarity alone is noisier than velocity; ship velocity-Δ before polarity ratio. |

### Items deliberately HELD OUT of the top 14 (and why)

| Ship | Why held | Move to top 14 when… |
|---|---|---|
| **Dealer Positioning Pack** (F2/F3/F4/F5/F6 — GEX, zero-gamma flip, Call/Put Wall, 0DTE GEX, vol regime) | Cross-model agreement: dealer-net assumption ("dealers short calls / long puts") is the load-bearing input and is **systematically wrong-sign for non-SPX single names**. SpotGamma is paid because the dealer split for single-name equities is non-trivial. Pass-2 rated these "trivial" because the formula is documented — but the formula's inputs aren't free for single tickers. | Either (a) you can defend the dealer-net for the bot's actual ticker universe (e.g. mega-cap subset only), or (b) a paid dealer-positioning feed lands. Until then, **ship with prominent caveat** if at all. |
| Smart-Score 1-10 composite (G1) | Every competitor brands their own; bot would need to define & defend its weights. Higher-leverage to ship the underlying signals (top 14) first so the composite has real inputs. | After 5+ of the top 14 have shipped — then the composite has data to weight. |
| 5-axis radar A-F (G2) | Same as G1 — derived feature; needs the input signals first. | Same. |
| Fair Value % chip (G5) | Needs own DCF model — substantial spec work. | After Forward Forecast Pack (#13) lands so the inputs exist. |
| Peer comp mini-table (K1) | Comp-list selection is the medium-build part the audit hand-waved. | After a sector→peer mapping exists in the codebase. |
| IV rank/percentile (F7) | 252d distribution needs liquid options for 1y — sparse/noisy for mid/small caps. | Gate to S&P 500 universe and ship. |
| Bull/Base/Bear scenarios linked to TPs (M4) | Structural change to `levels.py` — not pure narrator. | After Narrative Pack v1 ships and the slot exists. |
| Multi-timeframe technical verdict (H1) | Aggregation across timeframes needs more than 1d candles aggregated correctly. | After existing technicals refactor (TODO #3 Phase 2.x). |
| Anchored VWAP from earnings (H2) | Single-source (fintwit) — high-signal but unvalidated commonality. | Validate with a 4-week paper-trade test first. |
| Conditional bracket plan (H3) | Collides with existing TP1/TP2/TP3 framing. | After deciding whether the embed shifts to bracket-plan-first format. |
| Snowflake-style risks/rewards bullets (M10) | Overlaps with M6 (enumerated risks). Pick one frame. | If M6 lands well and the format wants a more bullet-y rendering. |
| Composable subcommand product-shape (Q1) (`!gex AAPL`, `!si AAPL`) | Product-architecture decision, not feature. | When `!all` quality is good enough that users want sliced-and-diced variants. |

### Out-of-scope (paid / proprietary / infra not present)

- **Real-time options tape** (sweeps F12 / blocks F14 / golden sweeps F17) — Polygon $200+/mo, dxFeed $1500+/mo
- **Cost-to-borrow** (B4) — Ortex API paid; Fintel paid; no good free source
- **Shorts daily P&L** (B7) — derivative of B4
- **Dark-pool ladder by price bucket** (F14) — UW proprietary
- **Economic Moat label** (G6) — Morningstar paid
- **Performance attribution** (M11) — requires backtest pipeline (small project, not a feature)
- **Football field chart** (P6) — image-render + Discord attach pipeline
- **"People also own" / Robinhood co-ownership** (P2) — no Robinhood API access

---

## §2 The full audit table

Per [TODO #7 spec](../TODO.md#7-optimize-all-output-quality--feature-surface-open-ended-initiative): one row per missing feature with **Feature / Where I saw it / Build cost / How common / Pre-flight access**. Sorted by category for findability; for leverage-rank see §1. Bundle membership noted to prevent double-counting.

| ID | Feature | Where I saw it | Build | Common | Pre-flight | Bundle |
|---|---|---|---|---|---|---|
| **A. Insider activity** | | | | | | |
| A1 | Insider transactions delta % (3m net buy/sell) | Finviz · Yahoo · Simply Wall St · TipRanks · Benzinga · OpenInsider | trivial | 6 | N/A (yfinance live) | Ship 3 |
| A2 | Cluster-buy flag (3+ insiders in 14d) | OpenInsider · Bespoke · Simply Wall St · fintwit | trivial | 4 | N/A (derive from A1) | Ship 3 |
| A4 | Insider ownership % | r/SecurityAnalysis · Yahoo · Finviz | trivial | 3 | N/A (`info["heldPercentInsiders"]` live) | Ship 3 |
| A5 | CFO/CEO role-weighted buy badge | OpenInsider · fintwit | trivial | 2 | N/A (filter A1 by `Position`) | Ship 3 |
| A6 | "Skin-in-the-game" management composite (A4 + capital-allocation track record) | r/SecurityAnalysis | medium | 1 | N/A (needs definition) | Second-wave |
| **B. Short pressure** | | | | | | |
| B1 | Float Short % | Finviz · Yahoo · Fintel · Stocktwits · S3 · Ortex | trivial | 6 | N/A (live) | Ship 4 |
| B2 | Days-to-Cover badge | Finviz · Yahoo · Fintel · S3 · Ortex | trivial | 5 | N/A (live) | Ship 4 |
| B3 | Short Interest delta WoW | Ortex · ChartExchange · Finviz · S3 | medium | 4 | worked (ChartExchange 190k) **but pass-2 preflighted wrong FINRA file** | Stretch |
| B4 | Cost-to-borrow % | Ortex · S3 · Fintel | big | 3 | paid only | OOS |
| B5 | FTD accumulation flag | ChartExchange · SEC FTD CSV · fintwit | medium | 3 | worked (SEC bimonthly CSV) | Stretch |
| B6 | S3-style compound chain ("$X SI %M; Y shs; Z%; B% borrow") | S3 · @ihors3 | trivial (format) | 1 | N/A (once B1/B2 live) | N/A bundle |
| B7 | Shorts daily P&L $ | S3 only | medium | 1 | needs B4 | OOS |
| **C. Institutional / 13F** | | | | | | |
| C1 | Institutional ownership % | Yahoo · Finviz · WhaleWisdom · TipRanks | trivial | 4 | N/A (`info["heldPercentInstitutions"]` live) | Ship 3 if added |
| C2 | 13F net buy/sell top 20 funds | TipRanks · WhaleWisdom · Bespoke | medium | 3 | worked (WhaleWisdom 231k) **but 45-day lag** | Second-wave |
| C3 | Top institutional holders + concentration | WhaleWisdom · Yahoo · Fintel | trivial | 3 | N/A (yfinance `institutional_holders` live) | N/A bundle |
| C4 | ETF exposure (top 5 ETFs holding ticker) | Koyfin · TradingView · Finviz | medium-to-big (per critic) | 3 | partial (etf.com / Finviz tab) | Second-wave |
| **D. Analyst** | | | | | | |
| D1 | Buy/Hold/Sell distribution + 12-mo target h/a/l | StockAnalysis · Robinhood · Yahoo · Finviz · TipRanks · Investing · Benzinga | trivial | 7 (+1 from Benzinga rescue) | N/A (yfinance `.info` 5 keys live — NOT wired yet) | Ship 5 |
| D2 | EPS revision count up/down rolling 7/30/60/90d | Yahoo · Zacks · fintwit | medium | 3 | N/A (Finnhub free-tier) | Ship 11 |
| D3 | Per-firm price target list with extremes | StockAnalysis · TipRanks | medium | 2 | worked (StockAnalysis 138k) | Second-wave |
| D4 | Recommendation timeline (upgrade/downgrade ladder) | Finviz · Fintel · Benzinga | trivial | 3 | N/A (Finnhub `/stock/upgrade-downgrade`) | Second-wave |
| D5 | Recom 1.00–5.00 numeric | Finviz | trivial (format) | 1 | N/A (derive from D1) | Ship 5 |
| **E. Earnings analytics** | | | | | | |
| E1 | Earnings surprise history 4Q grid | Yahoo · Zacks · Finviz · StockAnalysis | trivial | 4 | N/A (yfinance `earnings_dates` live) | Ship 6 |
| E2 | Implied move ±$/±% (straddle) | UW · eWhispers · MarketChameleon · fintwit | trivial | 4 | N/A (yfinance chain live) | Ship 8 |
| E3 | Historical avg post-ER ±% (8Q) | eWhispers · MarketChameleon · Estimize | trivial | 3 | N/A (yfinance dates + price t+1) | Ship 6 add |
| E4 | Whisper EPS vs consensus delta | Estimize · eWhispers · fintwit | medium | 3 | worked (Estimize **browser-UA only**, 62k) | Stretch |
| E5 | Beat streak ("8/8") | eWhispers · fintwit | trivial | 2 | N/A (derive E1) | Ship 6 |
| E6 | Reporting time tag BMO/AMC | eWhispers · UW | trivial | 2 | N/A (Finnhub calendar) | Ship 7 |
| E7 | Earnings ESP % (Zacks proprietary) | Zacks | medium | 1 | CF-blocked direct; computable from D2 timeline | Second-wave |
| E8 | EPS/Sales surprise % header stat | Finviz · Yahoo | trivial | 2 | N/A (derive E1) | Ship 6 |
| E9 | Pre-earnings IV crush expected % | MarketChameleon · fintwit | medium | 2 | partial (MC blocked) | Second-wave |
| **F. Options flow / derivatives** | | | | | | |
| F1 | Max Pain per nearest weekly + monthly | UW · OptionStrat · FlashAlpha · InsiderFinance · Barchart · MarketChameleon · fintwit | trivial | 7 | N/A (yfinance chain live) | Ship 9 |
| F1a | Pin-risk strike for OPEX (closest OI cluster) | SqueezeMetrics · fintwit | trivial | 2 | N/A (chain) | Ship 9 |
| F2 | GEX signed total | UW · SpotGamma · FlashAlpha · InsiderFinance | trivial-formula / **medium-with-honest-caveats** (critic) | 4 | N/A (chain) **but dealer-net wrong on non-SPX** | Held out |
| F3 | Zero-Gamma flip level | UW · SpotGamma · FlashAlpha | trivial (derive F2) | 3 | same | Held out |
| F4 | Call Wall / Put Wall strikes | UW · SpotGamma · InsiderFinance · fintwit | trivial (derive F2) | 4 | same | Held out |
| F5 | 0DTE GEX % of chain | UW · fintwit | trivial (subset F2) | 2 | same | Held out |
| F6 | Volatility regime label (Dampening / Explosive) | UW · SpotGamma | trivial (classifier on F2) | 2 | same | Held out |
| F7 | IV rank & IV percentile | Barchart · MarketChameleon · Fintel | medium (gate to large-cap) | 3 | N/A (yfinance + 252d) | Second-wave |
| F8 | Put/Call ratio (vol + OI, per-expiry-bucket) | UW · Barchart · CBOE · fintwit | trivial | 4 | N/A | Ship 10 |
| F9 | Top 3 OI strikes per side, nearest expiry | fintwit · Barchart · UW | trivial | 3 | N/A | Ship 10 |
| F10 | IV skew (25Δ put IV − call IV) | fintwit · MarketChameleon | trivial | 2 | N/A | Second-wave |
| F11 | HV-IV spread | fintwit · MarketChameleon | trivial | 2 | N/A | Second-wave |
| F12 | Sweep premium alerts ($X) live | UW · FlowAlgo · Cheddar · Tradytics | big | 4 | paid | OOS |
| F13 | Dark pool % of daily volume | UW · FINRA ATS · Tradytics | medium | 3 | worked (FINRA daily file, 510k) | Ship 12 |
| F13a | DIX-equivalent buy-pressure (single-name) | SqueezeMetrics interpretation · scratch-r5 | medium | 1 | worked (same FINRA file) | Ship 12 |
| F14 | DP ladder by price bucket | UW only | big | 1 | proprietary | OOS |
| F15 | Vanna / Charm exposure | UW · SpotGamma | medium | 2 | N/A (math) | Second-wave |
| F16 | Dealer-implied expected move (=E2 re-framed) | UW · MarketChameleon · eWhispers | trivial | 3 | N/A | Bundled with Ship 8 |
| F17 | Block / "Golden Sweep" $1M+ alerts | UW · FlowAlgo · Cheddar · Tradytics | big | 4 | paid | OOS |
| F18 | Sweep classification (Sweep / Block / Golden / RepeatedHit) | UW · FlowAlgo · scratch-r5 | medium | 3 | partial (poor-man's version via same-bar OI jumps) | Second-wave |
| **G. Composite scoring** | | | | | | |
| G1 | Smart-Score-style composite 1-10 | TipRanks | medium | 1 | N/A (own) | Held — needs inputs first |
| G2 | 5-axis radar A-F (Val/Growth/Profit/Momentum/Revisions) | Seeking Alpha · Simply Wall St · WallStreetZen · Zacks VGM | medium | 4 | partial (SimplyWallSt worked) | Held — needs inputs first |
| G3 | Disqualifying-threshold logic | Seeking Alpha | trivial (gate G2) | 1 | N/A | Bundled with G2 |
| G4 | Percentile rank vs peer cohort | Koyfin · Fintel | medium | 2 | partial | Second-wave (needs K1) |
| G5 | Fair Value % premium/discount chip | Simply Wall St · Morningstar · WallStreetZen | medium | 3 | N/A (own DCF) | Second-wave |
| G6 | Economic Moat label + Uncertainty Rating | Morningstar | big | 1 | proprietary judgment | OOS |
| G7 | Zen-style historical-return-by-grade ("Hold avg +7.5%/yr") | WallStreetZen | medium | 1 | needs backtest | Second-wave |
| **H. Technical / levels** | | | | | | |
| H1 | Multi-timeframe technical verdict (D/W/M Strong Buy → Strong Sell) | TradingView · Investing.com | medium | 2 | partial (TV worked / IC CF-blocked) | Second-wave |
| H2 | Anchored VWAP from last earnings date + above/below | fintwit (Mancini · Stewie) | trivial | 1 (high-signal) | N/A | Second-wave (validate first) |
| H3 | Conditional bracket plan ("Above X → Y/Z; below X → A/B") | fintwit (Mancini) | trivial (narrator + levels.py) | 1 (high-signal) | N/A | Second-wave (collides with TP framing) |
| H4 | Candlestick pattern callouts | Investing.com · Finviz · fintwit | medium (TA-Lib) | 3 | N/A | Second-wave |
| H5 | Power Earnings Gap reclaim label | fintwit (Stewie) | medium | 1 | N/A | Second-wave |
| H6 | Initial Balance high/low + revisit stat | fintwit | medium | 1 | partial (1m bars limited) | Second-wave |
| H7 | Algorithmic S/R levels | Tradytics · Investing.com | medium | 2 | N/A | Second-wave |
| H8 | Seasonality (weekly/monthly win rates) | Tradytics | medium | 1 | N/A | Second-wave |
| H9 | Pivot points + S/R | Investing.com · Finviz | trivial (yesterday OHLC) | 2 | N/A | Second-wave |
| H10 | 2B reversal label (stop-run + reverse near key level) | fintwit (Stewie) | medium | 1 (high-signal) | N/A | Second-wave |
| **I. Sentiment / social** | | | | | | |
| I1 | Stocktwits Bull%/Bear% + msg vol Δ + watchers | Stocktwits · fintwit | medium | 1 (canonical) | partial (web CF-blocked; `api.stocktwits.com/api/2/streams/symbol/<T>.json` open) | Second-wave |
| I2 | Mention velocity Δ vs 30d median (cross-source) | AltIndex · WSBMentions · fintwit | medium | 3 | N/A (Reddit+Twitter own; Stocktwits via API path) | Ship 14 |
| I3 | News sentiment polarity per headline | TipRanks · Finnhub `/news-sentiment` | trivial | 2 | N/A (Finnhub) | Second-wave |
| I4 | WSB mention rank change ("#14 → #2") | AltIndex · WSBMentions | medium | 2 | N/A (own daily scan) | Second-wave |
| I5 | Bloggers/authors aggregated opinion | TipRanks · SA · Simply Wall St narratives | medium | 3 | CF-blocked all 3 | Second-wave |
| I6 | TradingView community ideas bull/bear count | TradingView | medium | 1 | worked | Second-wave |
| I7 | Catalyst-class post tagging (academic taxonomy) | scratch-r4 (ACM 2023) | medium (classifier) | 1 (academic) | N/A | Second-wave |
| **J. Valuation extensions** | | | | | | |
| J1 | Forward PE FY+1 / FY+2 | StockAnalysis · Yahoo · Finviz · sell-side | trivial | 4 | N/A (`info["forwardPE"]` live) | Ship 13 |
| J2 | FY+1/FY+2 revenue + EPS forecasts with growth % | StockAnalysis · Yahoo · Koyfin | trivial | 3 | N/A (Finnhub `/stock/estimate`) | Ship 13 |
| J3 | Reverse DCF "what's priced in" (implied growth) | r/SecurityAnalysis · fintwit | medium | 2 | N/A (own) | Second-wave |
| J4 | PEG ratio (with growth basis stated) | Finviz · Yahoo · StockAnalysis | trivial | 3 | N/A (`info["pegRatio"]` live) | Ship 13 |
| J5 | Margin of safety vs intrinsic value % | r/SecurityAnalysis · Simply Wall St | trivial (derive G5) | 2 | N/A | Bundled with G5 |
| **K. Peer / sector** | | | | | | |
| K1 | Peer comp mini-table (3 comps, P/E + growth + margins) | Finviz · WallStreetZen · Koyfin · Zacks · Simply Wall St · sell-side | medium (per critic — comp-selection is the work) | 6 | partial | Second-wave |
| K2 | Industry Rank ("#3 of 11") | WallStreetZen · Zacks · Yahoo growth row | medium | 3 | worked (WSZ) | Second-wave |
| K3 | Growth-estimate row vs industry/sector/SP500 | Yahoo Analysis | medium | 1 | N/A (Finnhub + sector aggregates) | Second-wave |
| K4 | Sector relative strength rank | fintwit · Finviz | trivial (sector ETF perf) | 2 | N/A | Second-wave |
| **L. Catalyst calendar** | | | | | | |
| L1 | Catalyst type tagging (Hard dated vs Soft) | sell-side · fund letters · DD posts | trivial (narrator) | 3 families | N/A | Ship 7 |
| L2 | Event-type label (earnings/FDA/contract/M&A/ex-div/split) | DD · sell-side · UW | medium (extend catalyst calc) | 3 families | N/A | Ship 7 |
| L3 | Ex-dividend date + countdown | UW · Yahoo · StockAnalysis | trivial (yfinance `dividends`) | 3 | N/A | Ship 7 |
| L4 | Options expiry countdown nearest weekly + monthly | UW · OptionStrat | trivial (`options.expirations`) | 2 | N/A | Ship 7 |
| L5 | Splits + ratio + last split date | Yahoo · StockAnalysis | trivial (`splits`) | 2 | N/A | Second-wave |
| **M. Narrative structure** | | | | | | |
| M1 | TL;DR / one-line header above narrative | DD · sell-side · fund letters | trivial (narrator) | 3 families | N/A | Ship 2 |
| M2 | Explicit Bear Case section | DD · sell-side · fund letters · Simply Wall St | trivial (prompt) → **medium (structured quality_bar constraint, per critic)** | 4 | N/A | Ship 2 |
| M3 | Variant perception ("market thinks X, we think Y") | fund letters · sell-side · DD | trivial | 3 | N/A | Ship 2 |
| M4 | Bull/Base/Bear scenarios linked to TP1/TP2/TP3 | sell-side · fund letters | trivial-narrator + light levels.py change | 2 families | N/A | Held out (structural) |
| M5 | Valuation methodology disclosure (which multiple drove target) | sell-side · fund letters | trivial (narrator) | 2 families | N/A | Second-wave |
| M6 | Enumerated risk factors with mitigants | sell-side · fund letters · DD | trivial → medium | 3 families | N/A | Ship 2 |
| M7 | "What would invalidate this thesis" / kill criteria | fund letters · Tarasoff premortem | trivial (narrator) | 1 family (high-signal) | N/A | Second-wave |
| M8 | Position sizing / conviction tier line | fund letters · sell-side tier language | trivial (narrator) | 2 families | N/A | Second-wave |
| M9 | Auto-Bulls / Auto-Bears thesis pair tile | Benzinga · Morningstar | trivial (narrator structured) | 2 | N/A | Held — overlaps M2 |
| M10 | Snowflake-style Risks/Rewards bullets | Simply Wall St · Investing.com SWOT | trivial (narrator) | 2 | N/A | Held — overlaps M6 |
| M11 | Performance attribution — own !all track record | fund letters | big (per critic — needs backtest pipeline) | 1 family | N/A | OOS (separate spec) |
| **N. Format / UX micro-patterns** | | | | | | |
| N1 | Cashtag formatting `$AAPL` | fintwit universal | trivial | universal | N/A | Ship 1 |
| N2 | Direction emoji (🟢 long / 🔴 short / ⚡️ sweep / 🚨 insider / 🎯 hit) | fintwit · UW | trivial | universal | N/A | Ship 1 |
| N3 | Premium compact notation ($2.4M / $437K / $1.2bn) | fintwit · UW · FlowAlgo | trivial | universal | N/A | Ship 1 |
| N4 | ↓/↑/⇄ arrow icons for level direction | UW | trivial | 1 | N/A | Ship 1 |
| N5 | One-liner plain-English interpretation under metric | UW · SpotGamma · Simply Wall St | trivial (narrator) | 3 | N/A | Ship 1 |
| N6 | Compound metric chain with semicolons (S3 style) | S3 · fintwit | trivial | 1 | N/A | Ship 1 (stretch) |
| N7 | Relative date phrasing ("ER in 3 sessions") | fintwit · Tradytics | trivial (formatter) | 2 | N/A | Ship 1 (gated on TODO #4) |
| N8 | Bull/bear emoji on Net Premium (Net flow sign) | UW · scratch-r3 | trivial | 1 | N/A (once F8 exists) | Ship 1 add |
| **O. Macro overlay** | | | | | | |
| O1 | 10Y / DXY / VIX direction overlay | fintwit macro · sell-side | medium (yfinance + classifier) | 2 | N/A | Second-wave |
| O2 | CPI/PPI/payroll print countdown | fintwit macro | medium (Finnhub `/calendar/economic`) | 1 | N/A | Second-wave |
| O3 | Sector ETF performance side-by-side | Finviz · fintwit | trivial (sector ETF via yfinance) | 2 | N/A | Second-wave (overlaps K4) |
| **P. Single-source novelties** | | | | | | |
| P1 | Government / Pelosi-style Congressional trades | Benzinga only | medium (Capitol Trades / STOCK Act feed) | 1 | partial | Second-wave (distinctive) |
| P2 | "People also own" / Robinhood co-ownership | Robinhood only | big | 1 | partial (needs Robinhood API) | OOS |
| P3 | Bond holdings + YTM cross-reference | TradingView only | big (separate bond source) | 1 | worked but irrelevant | OOS |
| P4 | ESG controversy level | Yahoo Sustainability · Morningstar | medium | 2 | partial | Second-wave |
| P5 | Dividend growth streak years | Investing.com · StockAnalysis | trivial (yfinance dividends scan) | 2 | N/A | Second-wave |
| P6 | Football field valuation chart | sell-side only | big (image render + Discord attach) | 1 family | N/A compute, big render | OOS |
| **Q. Product shape** | | | | | | |
| Q1 | Composable subcommand pattern (`!gex AAPL`, `!si AAPL`, `!flow AAPL` decomposed from `!all`) | Tradytics · UW Discord bot | product-arch | 2 | N/A | Held — quality decision |

---

## §3 Pre-flight access summary (corrected after Pass-3 verification)

### Confirmed accessible from this VPS

- **Local data (no scrape needed):**
  - **yfinance `.info`** — 184 keys including `shortPercentOfFloat`, `shortRatio`, `heldPercentInsiders`, `heldPercentInstitutions`, `forwardPE`, `pegRatio`, `trailingPE`, `dividendYield`, `beta`, `marketCap`, `recommendationMean`, `recommendationKey`, `targetMeanPrice`, `targetHighPrice`, `targetLowPrice`, `targetMedianPrice`, `numberOfAnalystOpinions` (live-verified on AAPL 2026-05-16)
  - **yfinance `insider_transactions`** — 74 rows for AAPL, columns Shares/Value/Insider/Position/Transaction/Start Date/Ownership
  - **yfinance `earnings_dates`** — `EPS Estimate / Reported EPS / Surprise(%)` columns
  - **yfinance `option_chain`** — 25 expiries for AAPL, full call+put grids with strike/bid/ask/lastPrice/OI/IV/volume
  - **Finnhub free-tier endpoints** — already wired: `/quote`, `/company-news`, `/calendar/earnings`, `/stock/earnings`, `/stock/profile2` (no wiring for `/stock/recommendation`, `/stock/upgrade-downgrade`, `/news-sentiment` yet)
- **Public-fetch sources that returned real content** (browser UA used unless noted):
  - **FINRA RegSHO daily short-vol** (`cdn.finra.org/equity/regsho/daily/CNMSshvol*.txt`) — 510k bytes — `HAS_DATA`
  - **SEC fails-to-deliver bimonthly CSV** (sec.gov/data-research) — assumed accessible (pattern matches other SEC sources already used)
  - **Finviz** — 245k bytes — `HAS_DATA` (`Short Float / Short Ratio / Insider Trans` strings present)
  - **OpenInsider** — 54k bytes — `HAS_DATA` (Filing Date / Trade Type / cluster strings present)
  - **StockAnalysis dot com** — 138k bytes — `HAS_DATA`
  - **ChartExchange** — 190k bytes — `HAS_DATA` (Short Volume / FTD / Reg SHO)
  - **Estimize** — 62k bytes — `HAS_DATA` **but only with browser UA** (default-UA: 118 bytes — silent fail)
  - **TradingView** — 540k bytes — `HAS_DATA` (Technicals / RSI / MACD)
  - **Morningstar** — 1.1MB — `HAS_DATA` (Capital Allocation / Fair Value / Moat / Uncertainty)
  - **NasdaqDotCom** — 283k bytes — `HAS_DATA`
  - **GoogleFinance** — 1MB — `HAS_DATA`
  - **WhaleWisdom** — 231k bytes — `HAS_DATA`
  - **Benzinga** — 827k bytes — `HAS_DATA` (Analyst Ratings + Options Activity + Squawk; ALSO has Insider Trades + Short Interest sections — credit to A1/B1)
  - **WallStreetZen** — 403k bytes — `HAS_DATA`
  - **SimplyWallSt** — 2.3MB — `HAS_DATA`
  - **OptionStrat** — 81k bytes (404 status but real content rendered)

### Blocked / restricted

| Source | Status | Workaround |
|---|---|---|
| **UnusualWhales `/stock/AAPL`** | 200 + 16k JS-shell body — **NO data extractable** (keyword sniff returned zero matches) | Use only as inspiration for format/UX patterns; derive equivalent data from yfinance + FINRA + CBOE |
| **TipRanks** | 403 + CF-challenge | Derive composite from existing signals (yfinance + Finnhub + own narrative) instead of scraping Smart Score |
| **Seeking Alpha** | 403 + CAPTCHA | Derive own factor grades from yfinance fundamentals + Finnhub estimates |
| **Stocktwits web** | 403 + CF | Use unofficial JSON API at `api.stocktwits.com/api/2/streams/symbol/<T>.json` (open) |
| **Fintel** | 403 + CF | Implement Insider-Sentiment 0-100 formula directly from yfinance + Form 4 data |
| **Investing.com** | 403 + CF | TradingView (worked) for technicals; SWOT via LLM on existing evidence bundle |
| **MarketChameleon** | 200 + 12k DENIED page | yfinance options chain + 252d history for IV rank; E3 covers earnings move history |
| **BarChart options page** | 403 | Derive unusual-options via volume-vs-OI spike detection on yfinance chain |
| **Zacks** | bot-walled | Compute Earnings-ESP-style metric from D2 revision timeline |
| **Yahoo Finance** | 307 → consent dialog | Use yfinance library (which routes through query2.finance.yahoo.com bypassing the dialog) |
| **WSJ Markets** | 401 | StockAnalysis covers equivalent fields |
| **Nitter** | 0-byte response | Twitter / X data via TweetShift (already wired) |

---

## §4 Per-ship adversarial risk caveats

Cross-model agreement matrix from Pass-3 (Codex + Gemini stress test, both received identical prompt enumerating top-10 features, both returned KEEP/DROP/RISK per feature). Where both flagged the same risk, ship-decision should bake in the mitigation:

| Ship | Both-model risk | Required mitigation in spec |
|---|---|---|
| **9. Max Pain** | False "pin" levels on illiquid weeklies / chain holes | Frame as "near-term gravity," not "target"; gate to expiries with min OI > N |
| **Held: Dealer Positioning (F2-F6)** | Dealer-net assumption wrong-sign on non-SPX single names (SpotGamma's actual moat) | Don't ship without dealer-net feed OR gate to SPX/SPY/QQQ only |
| **10. P/C ratio** | All-expiry aggregation hides positioning that matters | Report per-expiry-bucket (front-week / front-month / quarterly), not single ratio |
| **8. Implied Move** | `0.85 ×` is folklore; broken on thin chains | Only emit when ATM spread < X% AND OI > Y; otherwise omit |
| **3. Insider Activity** | RSU/option exercises masquerade as buys; flips net-delta sign | Filter `Transaction` type before computing delta — open-market only |
| **4. Short Pressure** | 4-week yfinance staleness; mega-cap blunting | Use yfinance for headline, ChartExchange daily file as freshness check; narrator tempers "squeeze" framing for large floats |
| **5. Analyst Pack** | Targets lag price + consensus anchoring | Frame target as "consensus benchmark, not forecast"; suppress display when `numberOfAnalystOpinions < 5` |
| **2. Narrative Pack** | Counter-thesis can contradict COMPUTED SIGNAL / hallucinate negatives | Add explicit "reconcile against COMPUTED SIGNAL" clause in prompt; ship Bear Case via `quality_bar.py` structured constraint, not free-form prompt |

**Single-model risks** (lower-confidence but worth noting in spec): C1 standalone is "static trivia" without delta (Codex); E1 fiscal-quarter alignment errors (Codex); F9 OI top-strikes hides expiry-specific positioning (Codex).

---

## §5 What this audit did NOT research (honest gaps)

1. **Bot-relative cost-vs-impact** — the audit ranks by competitor-feature commonality × dev-cost × accessibility. It does NOT rank by **expected improvement in the Gemini blind-compare** (TODO #1's quality bar). Some features may be "obvious adds" by competitor-count but produce no measurable lift in the Layer-C eval.
2. **Token-budget interaction with narrator** — adding 3-5 new evidence blocks to the existing 18 may push past the 15k-input-token cap noted in TODO #7 architecture. The audit doesn't model evidence-pruning trade-offs.
3. **Cache invalidation cost** — many of the proposed features change on daily/weekly cadence (insider, short, 13F). The 15-min xref_cache TTL is appropriate for narrative but may waste a full re-fetch for static-ish data. Consider per-feature TTLs.
4. **Embed character limits** — Discord embed fields cap at 1024 chars per field; if format-pack (Ship 1) compresses content but data-packs (Ships 3-13) all want display lines, the embed may not fit. A dedicated `embed.py` overflow strategy is unscoped.
5. **Mobile vs desktop rendering** — emoji + arrow icons render differently across Discord clients; some accessibility considerations weren't researched.
6. **Cookied / authenticated scrapes** — pass-3 verified `firecrawl-instruct` exists as an alternative for CF-blocked sources but didn't actually try it. If a feature is judged worth the cost, that path is open.

---

## §6 How to scope a session from this audit

Workflow:

1. **Pick one Ship** from §1. Read the "Caveat" column and any §4 entry.
2. **Write a focused spec** (one feature, one PR-sized change). Place at `.omc/plans/<ship-name>.md`.
3. **Pre-flight the actual call signature** the feature needs — not just "the homepage loads." E.g. for Ship 11 (EPS Revisions), probe Finnhub `/stock/recommendation?symbol=AAPL&token=$KEY` end-to-end before claiming feasible.
4. **Define the user-observable outcome** crisply, per TODO #7 execution discipline rule #1 ("the embed now shows N for every ticker", not "N integration is in").
5. **Implement, ship, then run Layer C blind-compare** (TODO #1) against NVDA/AMD/TSLA. v2 ships only when 3/3 are prefer-all or tie.
6. **Mark the Ship complete in this audit** (edit §1's "Why first" column with "✅ shipped <date> commit <sha>").
7. **Delete this file when all top-14 ships have shipped OR when this audit becomes stale** (>90 days from 2026-05-16).

Caveats about this audit becoming stale:
- yfinance can break suddenly (Yahoo anti-bot pushes have killed `.info` before)
- Finnhub free-tier endpoints have shifted (some moved to paid)
- Competitor sites change UX — re-run pre-flight before relying on a "worked" tag older than 30 days

---

**Run artifacts:** `.claude/discover/external-feature-audit-2026-05-16/`
- `state.json` — discover run metadata
- `scratch-r1-free-consumer-tools.md` — Finviz/Yahoo/StockAnalysis/TradingView/Stocktwits/Robinhood/Investing/WallStreetZen/SimplyWallSt/Zacks
- `scratch-r2-premium-tools.md` — TipRanks/SeekingAlpha/Benzinga/SimplyWallSt/Koyfin/Morningstar/Fintel/WSJ/Zacks
- `scratch-r3-options-flow.md` — UW/Tradytics/FlowAlgo/Cheddar/SpotGamma/Barchart/MarketChameleon/OptionStrat/InsiderFinance/WhaleWisdom/FlashAlpha
- `scratch-r4-retail-dd-sellside.md` — WSB/SecurityAnalysis/options-DD/sell-side initiation/hedge-fund letters
- `scratch-r5-fintwit-patterns.md` — fintwit data citation patterns across 8 account clusters
- `scratch-critic-pass3.md` — adversarial review (8 missed features + 7 underranked + 7 overranked + 6 preflight wrongs + 9 failure modes + 6 bundling errors)
- `pass-2-filtered.md` — interim ranked draft (superseded by §1 of this doc)
- `pass-3-stress-tested.md` — Pass-3 corrections + cross-model agreement matrix
- `preflight-probes.txt` / `preflight-probes-v2.txt` — 26 sources × HTTP probe results
