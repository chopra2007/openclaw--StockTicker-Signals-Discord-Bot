# Research Draft — Phase C (2026-04-24)

Research-phase input for the synthesis pass. No executive summary, no audit, no proposals — only findings with citations (URL + author/handle + date where available).

---

## 1. Executive bullets (5, one line each)

- **LLM multi-agent debate is no longer hypothetical.** TauricResearch/TradingAgents has ~40.8k GitHub stars as of 2026-03 and ships a Bull/Bear researcher debate + Risk-Manager adjudicator with native Anthropic/Claude 4.6 support — this is the closest analogue to a "contradiction resolver" that exists off the shelf ([TradingAgents README, v0.2.2, 2026-03](https://github.com/TauricResearch/TradingAgents)).
- **Insider Form 4 "cluster buys" have a peer-reviewed 4.8% / 12-month alpha** signal that's free via openinsider.com — the engine currently ignores it despite Form 4 already being stored with +15 points ([Lakonishok & Lee, RFS 2002; MarketTriage signal guide, 2025](https://markettriage.com/insider-trading-signals)).
- **Backwardated options term structure + negative risk-reversal is a documented bullish-catalyst tell** — cheaper and more reliable than vol/OI ratio alone; retail-accessible through CBOE daily stats and Interactive Brokers' IBKR Quant coverage ([IBKR Quant, Mastering Vol Term Structure, 2025](https://www.interactivebrokers.com/campus/ibkr-quant-news/mastering-options-volatility-term-structure/)).
- **Sentiment-to-price divergence peaks at 3–10 days, near-zero at 1 day.** That's the opposite of what a "tweet → instant ping" engine optimises for — cross-reference cache should be tuned to sub-week horizons, not same-day ([arXiv 2507.09739, Enhancing Trading Performance with LLM Sentiment, 2025-07](https://arxiv.org/html/2507.09739v1)).
- **Microsoft's RD-Agent-Quant doubled benchmark ARR using 70% fewer factors** in 2025 real-market tests — proves automated factor mining now clears retail feasibility, which reframes how "feature engineering" should be budgeted ([arXiv 2505.15155, R&D-Agent-Quant, 2025-05](https://arxiv.org/html/2505.15155v2)).

---

## 2. Alternative data streams the engine doesn't use

### 2.1 OpenInsider + SEC Form 4 *velocity* (cluster buys)
Source `http://openinsider.com/latest-cluster-buys` (free, no API key, scrape-friendly). Signal: count of unique insiders buying within a rolling 10-day window, dollar-weighted, flagged at `≥3 insiders`. Lakonishok & Lee (RFS 2002) found heavy insider buying beat market by ~4.8%/yr; Cohen-Malloy-Pomorski (J.Finance 2012) separated "opportunistic" from "routine" trades, the former being the alpha-bearing subset ([MarketTriage, Insider Trading Signals, 2025](https://markettriage.com/insider-trading-signals)). 13radar's "Insider Cluster Buys" and Blank Capital's "Smart Money Matrix" both productionise this for retail in 2025 ([13radar, 2025](https://www.13radar.com/insider/cluster-buys/)). Fit: SEC EDGAR scanner already fetches Form 4 and adds +15 pts; a *velocity* column (distinct CIKs in trailing 10d) is a one-scanner addition.

### 2.2 FRED macro rails (2s10s, HY OAS, NFCI)
Source `https://fred.stlouisfed.org/series/T10Y2Y` + DGS10, BAMLH0A0HYM2, NFCI. Free API: 120 req/60 sec with a free key — effectively unlimited for daily series. Signal: regime-gate input. As of 2025-10 the 2s10s normalised to +53 bp after 16 months inverted — the longest inversion on record without a recession ([eco3min, Yield Curve History, 2025](https://eco3min.fr/en/yield-curve-inversion-history-2s10s-spread/); [FRED T10Y2Y](https://fred.stlouisfed.org/series/T10Y2Y)). Paired with HY-OAS widening this is the textbook risk-off gate. Fit: `regime_detector.py` already exists but is never called; FRED is the cheapest input that could populate it.

### 2.3 CBOE daily put/call + SKEW
Source `https://www.cboe.com/us/options/market_statistics/daily/` + `https://www.cboe.com/us/indices/dashboard/skew/` — free HTML, daily post-close. Signal: aggregate P/C > 1.0 → bearish, < 0.7 → euphoric ([YCharts, CBOE Equity P/C, 2025](https://ycharts.com/indicators/cboe_equity_put_call_ratio)); ticker-level `volume > open interest` is a documented directional tell ([Barchart, 2025](https://www.barchart.com/stocks/quotes/$VIX/put-call-ratios)). Fit: market-wide context (alert-happy in a SKEW-120 environment?) for the dead `regime_detector`.

### 2.4 Rejected/acknowledged
- **Tiingo** ($10/mo, free US EOD) — duplicates yfinance; no new signal. ([Tiingo](https://www.tiingo.com/))
- **Polygon.io free** — 5 req/min for aggregates is too tight for fan-out; free tier offers nothing finnhub-3000/day doesn't ([Polygon pricing review, 2026](https://www.ksred.com/the-complete-guide-to-financial-data-apis-building-your-own-stock-market-data-pipeline-in-2025/)).

---

## 3. Signal primitives (mechanism + citation + fit)

### 3.1 Form 4 cluster-buy velocity
Count unique insiders buying ≥ $10k open-market stock within 10 days; Cohen-Malloy-Pomorski (J.Finance 2012) show opportunistic clusters materially outperform ([MarketTriage, 2025](https://markettriage.com/insider-trading-signals)). Fit: reuses existing Form-4 fetch; one COUNT-DISTINCT query over the trailing window.

### 3.2 Options term-structure inversion + risk-reversal
Front-month IV > back-month IV (backwardation) with negative 25Δ risk-reversal (calls > puts) historically precedes short-term rallies into binary catalysts ([IBKR Quant, Term Structure, 2025](https://www.interactivebrokers.com/campus/ibkr-quant-news/mastering-options-volatility-term-structure/); [MenthorQ Skew & Term Structure, 2025](https://menthorq.com/guide/skew-and-term-structure/)). Fit: upgrades `scanners/options.py` from a single vol/OI ratio to a three-feature vector, still free via yfinance.

### 3.3 Isolation Forest multivariate anomaly
`sklearn.ensemble.IsolationForest` scores each ticker-day on 5–10 features (volume, spread, mention-count, IV-rank); top 1% flagged. Cited in [Springer Comp. Economics, 2025](https://link.springer.com/article/10.1007/s10614-025-11274-8) (S&P 500, IsoForest + CatBoost) and [ScienceDirect OPTUNA-IF, 2025](https://www.sciencedirect.com/science/article/pii/S2666827025001537). Fit: unsupervised — works even while calibration is dead code.

### 3.4 Sector-ETF cross-asset confirmation
Alert on ticker X only if its GICS sector ETF (XLK, XLF, XLV…) confirms the same session, or X shows top-decile relative strength vs that ETF. 2025 sector dispersion was extreme: XLK +23.9% YTD vs worst sector ~1%, amplifying the value of sector-relative confirmation ([ETF.com, AI Boom Splits Market, 2025](https://www.etf.com/sections/features/ai-boom-splits-market-best-and-worst-sector-etfs-2025); [StockCharts breadth, 2025](https://articles.stockcharts.com/article/spy-hits-key-moment-bearish-breadth-signal-triggers-yield-spreads-channel-march-2025/)). Fit: 11 yfinance pulls joined at scoring time.

### 3.5 McClellan Oscillator breadth-thrust gate
Breadth thrust = McClellan Oscillator moves ≥ 100 points deep-negative → strong-positive, or crosses zero-line ([StockCharts ChartSchool, 2025](https://chartschool.stockcharts.com/table-of-contents/market-indicators/mcclellan-oscillator); [QuantifiedStrategies, 2025](https://www.quantifiedstrategies.com/mcclellan-oscillator-and-summation-index/)). Fit: scalar market-wide gate derived from daily NYSE advancers/decliners — dampen single-name alerts when breadth collapses.

### 3.6 Sentiment→price horizon correction (retune, not new source)
[arXiv 2507.09739 (2025-07)](https://arxiv.org/html/2507.09739v1) reports S&P 500 sentiment has near-zero signal at 1 day, peaks 3–10 days, decays by day 20. Fit: cross-reference cache window, not ingest latency — load-bearing for the architecture pushback lane.

---

## 4. LLM / agent patterns deployed in 2025–2026

### 4.1 Multi-agent debate with bull/bear researchers + risk manager
TauricResearch/TradingAgents (arXiv 2412.20138); v0.2.2 released 2026-03 with Anthropic Claude 4.6 effort control. Runs Analyst → Bull/Bear Researcher debate → Trader → Risk-Manager pipeline; ~40.8k stars as of 2026-03 ([TradingAgents README, 2026](https://github.com/TauricResearch/TradingAgents); [Ultra Lab GitHub weekly, 2026-03-25](https://ultralab.tw/en/blog/ai-finance-github-projects-2026)). Fit: could be bolted onto Phase-2 cross-reference for contradiction resolution over conflicting sources.

### 4.2 Retrieval-augmented alpha mining (RAG over filings + news)
MarketSenseAI 2.0 — arXiv 2502.00415 (2025-02, revised 2025-10). HyDE-based retrieval over SEC filings, earnings calls, expert reports; reports 125.9% cumulative return on S&P 100 2023–2024 vs 73.5% index. FinGPT is the OSS sibling ([AI4Finance-Foundation/FinGPT](https://github.com/AI4Finance-Foundation/FinGPT); [arXiv 2306.06031 v2](https://arxiv.org/html/2306.06031v2)). Fit: ancillary — Vault/Atlas/Alfred already cover nightly research + morning briefing; RAG is not a replacement.

### 4.3 Self-consistency voting (flagged, not yet trading-deployed)
[arXiv 2505.10772 (2025-05)](https://arxiv.org/html/2505.10772v1); [arXiv 2502.18581 (2025-02)](https://arxiv.org/pdf/2502.18581). Well-validated on reasoning tasks but no public trading deployment yet — note, don't propose top-tier.

---

## 5. OSS repos to lift from

| Repo | URL | Stars | Last commit / release | What to steal |
|---|---|---|---|---|
| TauricResearch/TradingAgents | https://github.com/TauricResearch/TradingAgents | ~40.8k (2026-03) | v0.2.2 released 2026-03 with Claude 4.6 support | Bull/Bear debate + Risk-Manager adjudication pipeline; lift the orchestration graph and re-wire it around Phase-2 cross-reference. |
| microsoft/qlib | https://github.com/microsoft/qlib | 40.8k (2026-04-16 per star-history.com) | Active; RD-Agent integration Q2 2025 | Factor-library scaffolding and purged-CV utilities; MLPipeline patterns for evaluating `alert_history` labels. |
| OpenBB-finance/OpenBB | https://github.com/OpenBB-finance/OpenBB | ~54.7k–66k (2026-04) | Last update 2026-04-19 per repo page | Data-provider abstraction (unified wrappers for FRED, CBOE, yfinance). Lift as reference; do not add full dependency. |
| nautechsystems/nautilus_trader | https://github.com/nautechsystems/nautilus_trader | ~17k+ (2026-04) | v2026.04.06 released (option chains + greeks) | Event-driven architecture for the signal bus if the engine ever goes live; not needed pre-live. |
| polakowo/vectorbt | https://github.com/polakowo/vectorbt | ~6.8k (2026-01) | v0.28.4 released 2026-01-26 | Vectorised backtest patterns to retroactively score `alert_history` against price bars. |
| guanquann/Stocksera | https://github.com/guanquann/Stocksera | (unread, ~1k est.) | Active (recent commits) | 60+ alternative data scrapers (borrow fees, short interest, subreddits); cherry-pick scraper functions. |

*Stars / last-commit taken from the live GitHub pages and mirrors where cited; numbers are 2026-03/04 snapshots. Where the exact live count was unreachable (vectorbt mid-range), I quoted the range observed.*

---

## 6. Conflicts resolved

**Sentiment signal horizon.** Retail-blog guides (most r/algotrading top posts) push "instant tweet → instant trade"; peer-reviewed work ([arXiv 2507.09739, 2025-07](https://arxiv.org/html/2507.09739v1)) finds S&P 500 sentiment has near-zero signal at 1 day, peaks 3–10 days, decays by 20. **Side with the academic work.** The user's tweet-ingest is the trigger; the cross-reference *cache* should extend to a multi-day hit window, which is separable from ingest speed.

**MlFinLab license.** Despite 4.2k+ stars and textbook purged-CV / triple-barrier labels, MlFinLab is *not* open for commercial use ([hudson-and-thames/mlfinlab](https://github.com/hudson-and-thames/mlfinlab)). **Do not depend on it.** Lift algorithms from the López de Prado book directly (personal use OK) or use BSD-licensed equivalents in Qlib / skfolio.

---

## 7. Appendix — Full query log

1. `OpenInsider Form 4 cluster buying signal velocity 2025 trading strategy backtest` → **hit** (openinsider.com, MarketTriage, 13radar cited).
2. `Tiingo free tier Alpha Vantage FRED macro data retail algo trading 2025` → **hit** (pricing data captured; Tiingo rejected as duplicate of yfinance).
3. `CBOE put call ratio IV rank skew free data signal 2025 retail options` → **hit** (CBOE daily stats + YCharts P/C + Barchart SKEW).
4. `Microsoft Qlib FinRL nautilus-trader github stars 2026 retail quant framework` → **hit** (frameworks confirmed, star counts partial — filled in later).
5. `Marcos Lopez de Prado arxiv 2025 purged cross validation` → **miss on specific 2025 paper**; only the 2018 book / derivative works surfaced. Noted and deprioritised.
6. `LLM multi-agent trade idea debate stock signal Anthropic Claude 2025 github` → **hit** (TradingAgents identified).
7. `TradingAgents github stars researcher risk manager debate Anthropic 2026` → **hit** (40,792 stars 2026-03 per Ultra Lab).
8. `isolation forest anomaly detection equity volume price python 2025 research` → **hit** (Springer 2025 + ScienceDirect OPTUNA paper).
9. `sector ETF cross-asset confirmation divergence signal stock 2025 breadth` → **hit** (ETF.com 2025 sector dispersion; StockCharts breadth).
10. `short interest velocity borrow fee squeeze signal retail 2025 finviz` → **partial hit** (Finviz + Fintel confirmed; no academic velocity citation found — noted).
11. `OpenBB-finance stars commits 2026` → **hit** (54.7k–66k range, 2026-04-19 last update).
12. `microsoft qlib RD-Agent automated quant research 2025 latest release` → **hit** (arXiv 2505.15155 R&D-Agent-Quant).
13. `McClellan oscillator breadth thrust signal 2025` → **hit** (StockCharts ChartSchool + QuantifiedStrategies).
14. `MarketSenseAI 2.0 FinGPT RAG deployment 2025` → **hit** (arXiv 2502.00415).
15. `"structured output" trade thesis schema JSON LLM alert classifier 2025 deployed` → **partial miss** — generic structured-output references only; no specific trade-thesis deployment — excluded to avoid fabrication.
16. `self-consistency voting LLM trading signal ensemble 2025 paper arxiv` → **miss on trading-specific** — only general reasoning papers; flagged as "deprioritised, not yet trading-deployed."
17. `nautilus-trader github stars release 2026` → **hit** (17k+; 2026-04-06 release).
18. `Hudson Thames mlfinlab github stars active 2025` → **hit** (~4.2k stars; non-commercial licence noted as conflict).
19. `options skew term structure inversion stock catalyst retail 2025 free API` → **hit on concepts + IBKR / MenthorQ citations**; **miss on a truly free API** — retail must derive from yfinance chains manually.
20. `vectorbt github stars latest release 2025 pandas` → **hit** (6.8k stars; v0.28.4 released 2026-01-26).
21. `TradingView webhooks alert to python bot retail 2025 free signal` → **hit** but **rejected for engine fit**: overlaps TweetShift-style ingest, not a new signal; noted.
22. `Robot Wealth blog 2025 systematic trading` → **weak hit** (general site confirmed; June-2025 Euan Sinclair AMA referenced but no specific deep post URL); included as generic citation only.
23. `r/algotrading top posts 2025 smart money options flow unusual data retail` → **weak hit**; community corroboration only, no load-bearing single-post citation.
24. `Alpha Architect insider buying cluster 12 month alpha signal study 2024 2025` → **partial miss**; Alpha Architect search did not return the specific 2024–2025 article, fell back to Lakonishok/Lee (2002) + Cohen-Malloy-Pomorski (2012) as the academic foundation via MarketTriage secondary citation.
25. `Polygon.io free tier stocks API 2025 rate limits aggregates` → **hit** (5 req/min confirmed; rejected for engine fit).

**Not findable with clean citations** (so synthesis should not assert them): a specific 2025 López de Prado arXiv paper; a production "self-consistency voting on trading signals" deployment (pattern exists in LLM-reasoning research but not yet trading-specific); a single canonical Alpha Architect 2024–2025 cluster-buy article. These are flagged as gaps, not fabricated.
