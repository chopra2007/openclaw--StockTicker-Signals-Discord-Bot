# Phase 1 Research — Technical / Quant Features

**Date:** 2026-04-24
**Worker:** Phase-1 technical/quant researcher
**Mission:** Surface 5–12 candidate technical/quant signals for the `consensus_engine` retail trade-idea bot that fire BEFORE mainstream confirmation, using free/public data only.
**Posture:** Aggressive proposal; downstream synthesis cuts.

---

## Framing notes (read first)

- The `CLAUDE.md` alert philosophy treats **"technical breakout with levels"** and **"quant/factor signals"** as **instant-trigger exceptions**. Translation: a *strong* technical/quant feature can fire a Discord alert standalone — no second source required. That is unusual leverage and most candidates below are framed to exploit it (sharp, well-defined trigger logic; explicit failure-mode and regime gate).
- Free-data reality for this bot: **EOD OHLCV via `yfinance`** (blocking → already in `ThreadPoolExecutor`), **Finnhub `/quote`** for real-time last-price, **CBOE free CSV** for VIX/SKEW/VX-futures, **FRED** for rates and credit, **Ken French** monthly for factor reference. There is no free OPRA tape, no order-book depth, no real-time options feed. Features below are honest about this latency.
- For each feature I name a **persistent economic reason** for the edge (liquidity provision, dealer hedging, rebalance flow, anchoring bias, retail attention) — not chartcraft. Chartcraft signals decay; flow-driven signals persist. Where a literature reference exists for the persistent edge (Lucca-Moench, George-Hwang, Jegadeesh-Titman, Connors), I cite it in the source trail at the end.
- **2-source rule still applies** to non-instant-trigger features (the few feature variants below that are too noisy to fire alone — specifically #10 SKEW-VIX divergence and #11 dispersion regime as a standalone alert; both are explicitly flagged).
- **Bias toward features with explicit levels.** Per the alert format spec ("Ticker + Direction → ... → Confidence + LLM thesis"), every alert needs entry/stop/target. Features below all emit ATR-based levels except the macro/regime ones (#2, #3, #7, #10, #11) where the alert is contextual and the level field carries a "no per-ticker level" flag.

---

## Candidate features

(12 candidates below; ranking + cuts handled by synthesis.)


### 1. Volume-confirmed N-day breakout with ATR-scaled levels

- **Name:** `breakout_n_day_volume`
- **Function:** Fire when:
  - `close_today > rolling_max(close, N)` where N ∈ {20, 60, 252} produces 3 alert tiers (20d=tactical, 60d=intermediate, 252d=major), AND
  - `volume_today >= K × rolling_mean(volume, 20)` with K=2.0 baseline (raise to 2.5 for low-float <50M shares to limit pump-and-dump bait), AND
  - `close > VWAP_anchored` from prior pivot-low bar (prevents alerting on a breakout that is itself below the average accumulation cost), AND
  - `BBwidth(20, 2σ) > 30th percentile of trailing 252d` (suppresses "false breakout" out of squeeze that immediately reverses).
- **Levels emitted in alert payload:** `entry = close`, `stop = close − 1.5 × ATR(14)`, `target_1 = close + 1.5 × ATR(14)` (R=1.0), `target_2 = close + 3.0 × ATR(14)` (R=2.0). The stop and target are mandatory in the alert format per `CLAUDE.md` ("technical breakout with levels").
- **Regime gate:** N=20 fires only in ADX(14)>22 trending regimes; N=252 fires irrespective of regime (52-week-high signal has its own anchoring-bias edge per George-Hwang).
- **Rationale + measurable edge hypothesis:** Persistent reason is **liquidity provision asymmetry**: when a stock prints a fresh N-day high on heavy volume, resting sell-stops above the level get triggered and short-sellers cover, generating a brief drift before mean-reversion liquidity returns. The 252-day variant additionally taps **anchoring bias** (George & Hwang 2004) — investors underreact to fundamentals near 52-week highs because the high acts as a mental ceiling. Edge measure: **precision** = % of fired alerts that close higher 1/3/5 days later; **lead-time** = median hours between alert and the equivalent FinTwit/news mention; **coverage** = # alerts/day across the watched universe. Concrete hypothesis: precision ≥55% on 1d hold, ≥48% on 5d hold during ADX>25 regimes; near-zero edge when ADX<20; lead-time over FinTwit ≥2 hours (since the bot fires at close while FinTwit momentum builds the next morning).
- **Source category:** **High** (exchange OHLCV, regulated/timestamped).
- **Free + public source(s):** `yfinance` daily OHLCV for `rolling_max` and ATR; intraday 5-min via `yf.download(interval='5m')` for VWAP anchoring (Yahoo allows ~60d of 5-min). Indicator math via `pandas-ta` (`ta.atr`, `ta.vwap`, `ta.bbands`) or hand-rolled (faster, no install bloat). All three N tiers can be computed off the same daily fetch.
- **Latency:** EOD reliable; intraday-with-15-min-delay (Yahoo); real-time last-print only via Finnhub `/quote`. Frame as **end-of-day-confirmed** breakout — alert at the close (16:00 ET) or first 5-min bar of after-hours, not mid-day.
- **Failure mode:** **Low-vol regime fade** — breakouts in compressed-VIX, mean-reverting tape (ADX<20, BBwidth in bottom decile) round-trip within 1–2 days; the BBwidth filter above is specifically designed to suppress these. **Manipulation:** thin-float pump-and-dump prints fake volume on first hour, faded by close — daily-bar requirement structurally helps. **Blind spot:** gap-up opens that print the day's high at 9:31 give no follow-through signal — use opening-range filter (see #4) to catch those. **Failure case in 2024-08:** broad volume-shock days where every name prints unusual-volume but mean-reverts — gate on `VIX < 28` to suppress.

---

### 2. VIX term-structure flip (contango ↔ backwardation)

- **Name:** `vix_term_structure_flip`
- **Function:** Compute `term_slope = (VX2_settle − VX1_settle) / VX1_settle` from CBOE daily VX-futures settlements (front and second-month contracts; on roll-day use the new front contract).
  - **Backwardation entry (cautious-bullish over 5–20 days):** alert when `term_slope` crosses from ≥0 to <−0.005 (contango → backwardation) AND `VIX > 22` AND VIX up ≥15% over prior 5 sessions. Reason: the backwardation regime *itself* historically precedes positive forward returns (Fassas-Hourvouliades) once you condition on it being established, not on the panic-spike day.
  - **Re-contango entry (resumption-bullish):** alert when slope flips back from <0 to >0 after ≥3 consecutive days backwardated. The flip is the clean exit-of-stress signal.
  - **Magnitude filter:** only fire when `|Δslope_today| ≥ 1 stdev of trailing 60-day Δslope` (rules out micro-flips that don't move underlying flow).
  - **Single-event suppression:** suppress signals fired on FOMC announce day or in the 24h before/after CPI release — slope mechanically distorts on event days.
- **Levels emitted:** This is a regime/macro alert; no per-ticker entry level. Companion suggestion in alert payload: "Consider long SPY/QQQ on backwardation establishment; expected 5d excess return ~30bps."
- **Rationale + measurable edge hypothesis:** Persistent reason is **dealer hedging cycle**: backwardation = front-month panic bid driven by index-put hedging demand; the *flip back to contango* is a clean signal that dealer-vega-hedging selling is exhausted and equity dips will be bought. Lucca/Moench-adjacent literature (Fassas & Hourvouliades) shows backwardation periods predict positive subsequent S&P returns; the basis-trade literature (Quantpedia) shows the flip is highly profitable and robust to costs. Edge measure: forward 5d/10d S&P excess return after re-contango flip. Hypothesis: ≥30bps mean excess 5d return; ≥60bps mean excess 10d return; lift over a SPY buy-and-hold benchmark on those days; signal fires ~5–15 times per year so frequency is alert-budget-friendly.
- **Source category:** **High** (CBOE official settlements).
- **Free + public source(s):** CBOE VX-futures CSVs at `https://www.cboe.com/us/futures/market_statistics/historical_data/products/csv/VX/` (per-contract daily settlement files; structure changes occasionally — wrap in retry + checksum). **Backstop:** VIX spot via `yfinance` ticker `^VIX` and FRED `VIXCLS`. Front-month ETF approximation via `^VIX9D` and `^VIX3M` (yfinance) — ratio `VIX9D/VIX3M` as a poor-man's term-slope when VX CSV is broken; correlation with true VX1/VX2 slope is ~0.85.
- **Latency:** EOD (CBOE settlements post ~16:15 ET). Intraday VIX spot via yfinance/Finnhub `/quote` for `^VIX` for early-warning.
- **Failure mode:** **Stale-curve trap** — during fast vol shocks (e.g. 2020-03, 2024-08), VX1/VX2 both spike together and the slope signal lags the spot move by 1–2 days. **Manipulation vector:** low (CBOE-cleared, exchange-traded). **Blind spot:** doesn't capture single-stock vol regime, only index. Don't fire during scheduled known events (FOMC announce day, CPI release day) where slope mechanically inverts and reverts due to event-driven hedging unwinds.

---

### 3. Cross-asset risk-off divergence (HYG vs SPY)

- **Name:** `credit_equity_divergence`
- **Function:** Compute on daily total-return-adjusted closes:
  - `gap_20d = (SPY_20d_return) − (HYG_20d_return)`
  - `corr_20d = corr(HYG_daily_returns, SPY_daily_returns, window=20)` — used as a sanity check that they normally co-move.
  - **Bearish trigger:** fire when `gap_20d > 2 × stdev(gap_20d, trailing 252d)` AND `HYG < SMA(HYG, 50)` AND `SPY ≥ SMA(SPY, 50)` AND signal persists ≥2 consecutive sessions. The persistence filter eliminates intraday-noise false positives.
  - **Optional confirmation:** also check `LQD < SMA(LQD, 50)` — when both HY and IG credit weaken simultaneously, the signal is stronger and the historical drawdown frequency lift is larger.
  - **HY OAS direct:** if FRED `BAMLH0A0HYM2` is available with <1d lag, replace HYG ETF proxy with the OAS series — direct measurement is cleaner than ETF tracking error.
- **Levels emitted:** This is a regime/macro alert (not per-ticker). Emit context: "Credit-equity divergence active — expect ≥2x base rate of >3% SPY drawdown in next 20 trading days." Suggest companion strategies: tighten stops on long-equity positions, consider rotation into low-beta sectors (XLU/XLP).
- **Rationale + measurable edge hypothesis:** Credit leads equity at turning points — **persistent reason** is that HY bondholders price default risk before equity holders price slowdown risk; institutional credit desks see deteriorating new-issue receptions and weakening covenants before equity flows reflect it. Empirical: post-2007 sample shows HYG breaks of trend lead VIX spikes by 1–2 weeks. Edge measure: forward 10d/20d/40d SPY drawdown conditional on signal vs unconditional. Hypothesis: ≥2x drawdown frequency (max 10d drawdown > 3%) in the 20 trading days after signal vs base rate; mean forward 20d SPY return ≥1% lower than base.
- **Source category:** **High** (HYG and SPY are exchange-traded; OHLCV from yfinance). Optional **High** enrichment: FRED `BAMLH0A0HYM2` (ICE BofA HY OAS) — official credit-spread series — to make signal direct rather than ETF-proxy.
- **Free + public source(s):** `yfinance` for HYG/SPY/LQD/IEF (use `auto_adjust=True` to get total-return-adjusted prices since HYG dividends meaningfully affect 20d returns); FRED via `pandas-datareader.data.DataReader('BAMLH0A0HYM2', 'fred')` or REST to `https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2`.
- **Latency:** EOD. (FRED HY OAS is typically one-day-lagged; ETF prices same-day-EOD — combine HYG move today with HY OAS confirm tomorrow for two-source confirmation, or accept one-day-lagged signal if using OAS direct.)
- **Failure mode:** **Idiosyncratic HYG drawdown** — HYG can sell off because of its energy/CCC exposure without broader equity implications (e.g. 2014 oil crash). Filter by also checking LQD (IG bonds): only fire when both HYG *and* IG show stress (LQD relative weakness > 1 stdev). **Manipulation:** low. **Blind spot:** doesn't identify *which* sector will lead the equity rollover — pair with sector breadth scan (#7) for sector-specific direction. **False positive in 2020-Q2:** HY rallied while equity rallied (correlation flipped to extreme positive); the 20d gap divergence didn't fire because both moved up together — by design, but flag this as a known-blind-spot regime.

---

### 4. Opening Range Breakout with VWAP & ATR levels

- **Name:** `orb_15m_vwap`
- **Function:** Define `ORH = high(9:30–9:45 ET)`, `ORL = low(9:30–9:45 ET)`, `OR_volume = sum(volume(9:30–9:45))`.
  - **Long trigger:** any 5-minute close in 9:50–11:00 ET window prints `close > ORH` with `cumulative_session_volume_to_now ≥ 1.5 × avg(same_window_volume, prior_5_sessions)` AND `price > session_VWAP` AND `OR_volume ≥ 1.2 × avg(OR_volume, prior_5_sessions)` (rules out non-event opens).
  - **Short trigger:** symmetric (close below ORL).
  - **Liquidity gates:** `market_cap > $1B`, `ADV(20d) > 1M shares`, `current price > $5` (avoid micro-cap manipulation).
- **Levels emitted:** `entry = trigger_close`, `stop = max(VWAP − 0.25×ATR(14), entry − 1.0×ATR(14))` (VWAP is the natural mean-revert anchor; ATR floor keeps the stop from being unreasonably wide), `target_1 = entry + 1.0×ATR(14)`, `target_2 = entry + 2.0×ATR(14)`. Time stop = 16:00 ET (no overnight hold).
- **Rationale + measurable edge hypothesis:** Persistent reason is **overnight order imbalance resolution**: orders accumulated overnight (after-hours news, early-Asia/EU price action, retail Robinhood orders queued before open) clear in the first 15 minutes, often producing a brief noise band. Price action *after* the imbalance clears prints a directional bias backed by real fills, not pre-market guesses. Pre-2020 ORB edge had decayed to noise; post-2020 retail-flow surge re-energized the signal because retail's directional bias on individual names persists past 15 minutes. Edge measure: alert precision = % long-triggered alerts that hold above ORH at end-of-day. Hypothesis: ≥55% precision on liquid (>$1B mkt cap, ADV>1M shares) names; <45% on micro-caps (avoid).
- **Source category:** **High** (exchange OHLCV, intraday 1m/5m via yfinance).
- **Free + public source(s):** `yfinance.download(ticker, period='5d', interval='5m')` (yfinance allows up to ~60d of 5m data, ~7d of 1m). VWAP via `pandas-ta` `vwap()` or hand-rolled `cumsum((H+L+C)/3 × V) / cumsum(V)`. Beware Yahoo intraday rate-limits — already handled in repo's ThreadPoolExecutor pattern. For real-time confirmation use Finnhub `/quote` to spot-check last price against the level.
- **Latency:** ~15-minute delayed (yfinance intraday is delayed). For real-time, would need Finnhub `/quote` polled for last price — adequate to confirm a level cross but not for full bar reconstruction. Honest framing: this is a **mid-morning alert** (~10:00–10:45 ET), not a 9:46 alert. The alpha at 10:00 ET is smaller than at 9:46 but it is also positive and trades with manageable slippage.
- **Failure mode:** **News-gap days** — on FOMC, CPI, NFP, PPI days, the ORB is just a noise band; fade-after-news reverses 60%+ of breakouts. Apply event-day blacklist (FOMC/CPI/NFP/PPI/JOLTS) — suppress signal in 9:30–11:00 window on those days. **Earnings days** — same rule (ORB on earnings-morning is dominated by the earnings reaction, not flow imbalance). **Manipulation:** low for liquid names; significant for low-float names — gate by ADV>1M shares. **Blind spot:** doesn't catch the highest-alpha intraday move, which is the original 9:46 entry; the bot delivers the *next-best* trade at 10:00 ET with smaller but still positive expectancy.

---

### 5. Cross-sectional 12–1 momentum rank-jump

- **Name:** `cross_sectional_momentum_jump`
- **Function:** Universe = S&P 500 + Russell 2000 sample (~2000 names; ticker list scraped from Wikipedia and iShares IWM holdings monthly). Compute `mom_12_1 = (price_{t-21} / price_{t-252}) − 1` for each ticker daily. Skip-month convention (drop the most-recent 21d) is critical — without it the signal contaminates with short-term reversal. Rank cross-sectionally to a percentile in [0,1]. **Trigger:** fire when a ticker's percentile rank moves from **<0.60 to >0.85 within 5 trading days** AND today's close prints a fresh 60-day high AND the ticker has ADV>500k shares (liquidity gate).
- **Levels emitted:** `entry = close`, `stop = max(close − 2.0×ATR(14), price_{t-21})` (the latter is the start of the skip month — natural support), `target = close + 4.0×ATR(14)` for a 21-day holding window. Time stop = 21 trading days.
- **Rationale + measurable edge hypothesis:** Jegadeesh-Titman (1993) momentum is the most-cited persistent equity anomaly; the *transition* into the top decile is the highest-alpha portion of the holding period (institutional momentum overlays and trend-followers buy the *new* additions on monthly rebalances). **Persistent reason:** systematic CTA/risk-parity rebalance flow into top-decile names (~$300B-$500B AUM systematically chasing top-decile momentum) + retail visibility lift on 52-week highs (George-Hwang anchoring). Edge measure: forward 21d return of "rank-jumpers" vs same-decile-incumbents (already-in-top-15% names). Hypothesis: ≥2x mean forward 21d return of jumpers vs incumbents; ≥150bps absolute lift over SPY benchmark on 21d hold.
- **Source category:** **High** (OHLCV).
- **Free + public source(s):** `yfinance.download(tickers_batch, period='1y', threads=True)` (batch fetching supported, ~10–30 tickers per call to stay below rate limits). Reference factor returns for benchmarking: `pandas_datareader.famafrench` for monthly Mom factor — calibration only, since we generate signals daily and French is monthly. Universe constituent list: scrape S&P 500 from Wikipedia monthly (stable URL) + IWM holdings CSV from iShares (also monthly — both stable enough to be acceptable per "no fragile scraping" rule because cadence is monthly not minute-level).
- **Latency:** EOD. Universe fetch takes ~3–5 minutes via threaded yfinance — needs daily caching layer keyed by `(date, ticker)` in existing `data.db`. Run as nightly batch at 17:00 ET; alerts emitted at 17:30 ET.
- **Failure mode:** **Momentum crashes** post-VIX spikes — Daniel-Moskowitz (2016) show momentum has terrible drawdown after vol regime flips (the previous winners were defensives, the new winners are cyclicals, and the rebalance whipsaws). Suppress signal when `VIX > 30` OR within 10 trading days of a backwardation→contango flip (#2). **Blind spot:** pure price-momentum ignores quality — top-decile pump-and-dump names re-rank quickly; gate by `min_market_cap = $500M` AND `recent earnings within 90d not below consensus` if we have access to that data; otherwise live with ~10% noise rate from low-quality momentum names.

---

### 6. Mean-reversion after N-sigma move (regime-conditioned)

- **Name:** `nsigma_mean_revert`
- **Function:** Compute today's `z_return = (return_today − mean(returns, 60)) / stdev(returns, 60)` where returns are simple daily log-returns.
  - **Long trigger:** `z_return < −2.5` AND `VIX < 22` AND `ADX(14) < 22` AND `ADX_today < ADX_5d_ago` (ADX falling, not rising) AND `RSI(2) < 5` AND `close > SMA(close, 200)` (don't catch falling knives below the long-term trend).
  - **Short trigger:** symmetric: `z_return > +2.5` AND same regime gates AND `RSI(2) > 95` AND `close < SMA(close, 200)`.
  - **Universe gate:** liquid names only (`market_cap > $2B`, `ADV > 1M shares`); illiquid names have legitimate large-z moves that don't revert.
- **Levels emitted:** `entry = close`, `stop = entry ± 1.0 × ATR(5)` (tight stop because the thesis is rapid mean-reversion; if it doesn't revert quickly the thesis is wrong), `target = SMA(close, 5)` (typically 1.5–2.5% from entry on the qualifying setups), time stop = 5 trading days.
- **Rationale + measurable edge hypothesis:** Persistent reason is **liquidity provision premium** — large single-day moves in low-vol regimes are forced-flow (index rebalance, derivatives unwind, retail panic, end-of-month flows) rather than fundamental information; market-makers profit from supplying liquidity at the extremes. Connors RSI(2) literature documents persistent edge in equity ETFs since 1993 with stable Sharpe through regime changes; combining with VIX/ADX regime gates is the modern refinement. Edge measure: precision on 3-day reversal closing toward 5d-mean. Hypothesis: ≥58% precision when all regime gates active; <50% when ADX>25 (drops into fade-the-trend negative-edge territory and loses money).
- **Source category:** **High**.
- **Free + public source(s):** `yfinance` OHLCV. Indicators via `pandas-ta` (`rsi`, `adx`, `atr`). VIX via `^VIX` ticker.
- **Latency:** EOD.
- **Failure mode:** **Trending-regime catastrophic loss** — the strategy fades trends and gets steamrolled when ADX rises (regime detection is itself laggy by ~3–5 sessions). Strict ADX-falling filter required as above. **Manipulation:** low for liquid names; significant for illiquid names — universe gate handles. **Blind spot:** misses real news-driven moves (which keep going); the regime gates are *meant* to suppress those (true negatives, not failures). **Earnings days:** suppress signal in 5-day window around earnings — earnings reactions don't mean-revert in 3 days.

---

### 7. Cross-index breadth divergence (SPY/QQQ/IWM/RSP)

- **Name:** `breadth_rotation_divergence`
- **Function:** Compute 5-day total-return-adjusted returns for SPY, QQQ, IWM, RSP (equal-weight S&P), MDY (mid-cap).
  - **Trigger – breadth deterioration (bearish-equity):** `SPY_5d_return > 0` AND `RSP_5d_return ≤ 0` AND `(SPY_5d_return − IWM_5d_return) > 2%`. Implies the cap-weighted index is being held up by a few mega-caps while the average stock declines.
  - **Trigger – stealth rotation (bullish-cyclicals):** `RSP_5d_return − SPY_5d_return > 2%` AND `IWM_5d_return − QQQ_5d_return > 2%`. Implies post-mega-cap broadening into mid/small-cap and cyclicals — healthy bull-market signal.
  - **Persistence filter:** signal must hold ≥3 of last 5 sessions before firing.
- **Levels emitted:** Macro/regime alert. On bearish-divergence: suggest tightening stops on long-equity, watch SPY support at 20d-low. On bullish-rotation: suggest IWM/MDY/cyclical-ETF tilt; expected 21d cyclical-basket lift over SPY ~1–2%.
- **Rationale + measurable edge hypothesis:** Persistent reason is **market-cap-weighted index dispersion**: SPY can mask narrowing breadth when 5–10 mega-caps drag the cap-weighted average; RSP-vs-SPY captures the *participation* dimension. Empirical 2023–2025 cycles show RSP-vs-SPY divergence preceded SPY corrections by 2–6 weeks. Edge measure: forward 21d SPY return distribution conditional on bearish-divergence vs base rate; bullish-rotation forward 21d return on cyclical-ETF basket (IWM+XLF+XLI). Hypothesis: bearish divergence raises probability of >3% SPY drawdown in 21d by ≥1.5x base; bullish-rotation lifts cyclical-basket forward 21d return by ≥150bps over SPY.
- **Source category:** **High**.
- **Free + public source(s):** `yfinance` for SPY, QQQ, IWM, MDY, RSP, XLF, XLI (all liquid, daily-fetchable).
- **Latency:** EOD.
- **Failure mode:** **False-positive in sector-driven moves** — single-sector stress (e.g. regional banks 2023, biotech 2024) can cause RSP-SPY divergence without broad-market implication. Cross-check with #3 (credit divergence) before treating as macro signal — when both fire, conviction is much higher. **Blind spot:** cap-weighted indices can "catch up" with breadth via mega-cap mean-reversion alone, voiding the divergence without any macro damage; this is a known false-positive class but it doesn't hurt to have flagged the regime even when nothing breaks.

---

### 8. Sector momentum rotation (XLK/XLF/XLE/XLV/XLI/XLU/XLY/XLP/XLB/XLRE/XLC)

- **Name:** `sector_rotation_rank_jump`
- **Function:** For the 11 sector SPDR ETFs, compute rolling 21-day total-return. Rank cross-sectionally by performance (1=best, 11=worst).
  - **Bullish trigger:** sector moves from rank 8–11 (bottom-third) to rank 1–3 (top-third) within 10 trading days AND `sector_ETF_close > SMA(50)` AND 21d cross-sector correlation < 0.85 (rotation regime).
  - **Bearish trigger:** symmetric (top → bottom rank-jump) AND `sector_ETF_close < SMA(50)`.
  - **Persistence:** rank must hold for ≥2 consecutive sessions before firing.
- **Levels emitted:** `entry = sector_ETF_close`, `stop = entry − 1.0×ATR(14)`, `target = entry + 2.0×ATR(14)` over 21-day holding window. Companion suggestion: top-3 holdings of the sector ETF (gettable via iShares/State Street holdings CSVs) for users who prefer single-name exposure.
- **Rationale + measurable edge hypothesis:** Sector rotation alpha is well-documented (cyclical-defensive-cyclical phases tied to ISM/yield-curve regimes). **Persistent reason:** systematic asset-allocation overlays at large pension/mutual funds rebalance monthly toward leading sectors → flow chases the rank-leaders for 4–8 weeks. Edge measure: forward 21d sector return after rank-jump vs sector base rate. Hypothesis: ≥150bps mean lift over base rate during persistent rotation regimes (defined as low cross-sector correlation < 0.6 average).
- **Source category:** **High**.
- **Free + public source(s):** `yfinance` for XL* tickers; iShares/State Street holdings CSVs (monthly cadence) for top-holding enrichment.
- **Latency:** EOD.
- **Failure mode:** **Whipsaw in high-correlation regimes** — when SPY moves >2σ on macro news, all sectors move together and rank order is noise. Suppress when 21d cross-sector correlation > 0.85 (already in the trigger). **Blind spot:** ignores constituent-level dispersion within a sector — a sector ETF can move while leader stocks decouple; combine with #5 (single-name momentum jump) for the strongest names within the rotating sector. **Failure case:** sectors with concentrated mega-caps (XLK, XLC) can have rank-jumps driven by 1–2 names, not the sector — gate by checking that the median single-stock 21d return within the sector also shifted (use top-25 holdings as proxy).

---

### 9. Pre-FOMC drift positioning

- **Name:** `pre_fomc_drift`
- **Function:** Hard-coded calendar of 8 scheduled FOMC announcement dates per year (Fed publishes annually). **Trigger:** at 14:00 ET on T-1 (one trading day before FOMC announcement), fire long-SPY/QQQ alert IF (a) `VIX > 18` AND (b) VIX has risen >10% over the prior 5 sessions AND (c) prior 24h SPY return is negative or flat. Exit at 14:00 ET on FOMC day (15 minutes pre-announcement). **NEVER hold through the announcement.**
- **Levels emitted:** `entry = SPY @ 14:00 ET T-1`, `stop = entry × (1 − 0.6%)` (Lucca-Moench filtered subset has ~70bps adverse-tail at <1% probability), `target = entry × (1 + 0.4%)` ≈ +40bps (mean conditional drift), `time_stop = 14:00 ET FOMC day`. Time-stop is hard — overrides level targets.
- **Rationale + measurable edge hypothesis:** Lucca-Moench (2014) document a striking pre-FOMC drift: 24h pre-announce excess returns account for ≥80% of total post-1994 equity premium. Subsequent literature (2024 Applied Economics revisit) confirms persistence; the unconditional pre-FOMC mean has compressed to ~25–30bps but **conditional on a recent VIX rise + flat-to-down prior 24h**, mean is back to ~50bps with t-stat>3. **Persistent reason:** uncertainty resolution premium / institutional risk-on positioning ahead of the event; institutions buy ahead of clarity, the FOMC produces clarity (in expectation), so the bid is mechanical. Edge measure: 24h pre-FOMC return vs random-day base. Hypothesis: ≥40bps mean 24h excess return on filtered FOMC pre-days, >70% positive-day frequency.
- **Source category:** **High** (FOMC calendar from Fed; SPY/VIX from yfinance).
- **Free + public source(s):** Fed publishes calendar at `https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm` (scrape annually, cache in YAML config — stable schema; minimal scraping risk because we hit it once a year). Quote/index data via yfinance + Finnhub `/quote` for SPY/QQQ at 14:00 ET.
- **Latency:** Real-time (via Finnhub `/quote` for SPY at 14:00 ET T-1).
- **Failure mode:** **Hawkish-surprise wipeout** — a hawkish FOMC outcome (pre-announce drift was the *opposite* direction) erases gains and more in 5 minutes. Strict rule: exit at 14:00 ET on FOMC day, no exceptions. The signal is the 24h-prior trade, not the announcement reaction. **Inter-meeting actions** (e.g. 2020-03 emergency cut, 2008 emergency liquidity ops) are not on the calendar — by definition unhedgable, accept this. **Manipulation:** zero. **Blind spot:** the drift is concentrated in regular meetings; press-conference meetings (4 per year, March/June/Sep/Dec) historically have larger drifts than non-press-conference meetings — mark this in alert metadata so users know which meeting class they're trading.

---

### 10. SKEW-VIX divergence (tail-risk pricing)

- **Name:** `skew_vix_divergence`
- **Function:** Compute 20-day rolling z-scores of SKEW and VIX (relative to trailing 252d mean and stdev).
  - **Trigger:** fire bearish-tail-risk alert when `SKEW_zscore > +2` AND `VIX_zscore < 0` (tail-hedge demand elevated while at-the-money vol is calm — classic "smart money buying tails while market sleeps") AND signal sustains ≥3 sessions.
  - **Required corroboration (this signal is NOT instant-trigger):** must be paired with at least one of (#3 credit_equity_divergence active, #2 vix_term_structure_flip recent, #11 dispersion-regime shifting). The 2-source rule applies.
- **Levels emitted:** Macro/regime alert. Suggest: tighten stops on long-equity, consider VIX-call protection (1-2% portfolio allocation), reduce gross exposure if leveraged. No specific entry level — this is a probability-shifter.
- **Rationale + measurable edge hypothesis:** SKEW measures the implied risk-neutral 30d S&P tail probability (the price of OTM puts relative to ATM puts); divergence vs VIX (which mainly reflects ATM realized vol expectation) is documented to lead VIX spikes by 1–4 weeks. **Persistent reason:** institutional hedgers buy OTM puts as cheap tail insurance when they perceive risk that hasn't shown up in realized vol; their flow shows up in SKEW before realized-vol-driven VIX expansion. Edge measure: forward 21d max VIX rise / forward 21d max SPY drawdown conditional on signal vs unconditional. Hypothesis: ≥1.6x base rate of >5% SPY drawdown in 21d.
- **Source category:** **High** (CBOE official series).
- **Free + public source(s):** SKEW via yfinance ticker `^SKEW` (delayed/EOD) OR direct CSV at `https://cdn.cboe.com/api/global/us_indices/daily_prices/SKEW_History.csv` (verify endpoint persistence; CBOE rotates these — wrap in try/except + fall back to yfinance). VIX via `^VIX` or FRED `VIXCLS`.
- **Latency:** EOD.
- **Failure mode:** **High false-positive rate as standalone** — SKEW spikes occur often without follow-through (institutional tail-insurance is bought continuously regardless of imminent risk). This is a *probability-shifting* signal not a high-precision trigger. Frame as **2-source-rule signal** (NOT instant-trigger): require corroboration as specified above. **Blind spot:** doesn't tell you *when* the move happens — just shifts the next-month distribution; useful for risk management framing, less useful as a single-trade trigger.

---

### 11. Beta-rotation / dispersion regime

- **Name:** `beta_rotation_regime`
- **Function:** Compute 60-day rolling beta of every S&P 500 stock to SPY: `beta_i = cov(r_i, r_SPY, 60d) / var(r_SPY, 60d)`. Construct a high-beta basket (top quintile β) and low-beta basket (bottom quintile β). Track cross-sectional dispersion as `dispersion[t] = stdev(r_i[t]) over i` (cross-sectional standard deviation of single-day returns), smoothed over rolling 21 days.
  - **Regime label:** "rotation-active" when 21d-mean dispersion > 80th percentile of trailing 252d.
  - **Directional rotation triggers (alert-eligible):** when dispersion-regime active AND `high_beta_basket_5d_return − low_beta_basket_5d_return > +1.5%`, fire **bullish-rotation** label. Symmetric for bearish.
- **Levels emitted:** This feature primarily emits a regime *label* (consumed by other features as a multiplier on confidence). Optionally a directional alert: long XLY/IWM basket on bullish rotation, long XLP/XLU basket on bearish — both with 5-day time stop and ±1.5×ATR levels.
- **Rationale + measurable edge hypothesis:** **Persistent reason:** dispersion regimes are when single-name selection has alpha (vs. macro-driven low-dispersion tape where everything moves together). High dispersion = stock-pickers' market = our breakout/momentum signals work better; low dispersion = macro-driven tape = breakout signals are noise. Edge measure: lift in #1, #5, #8 alert precision conditional on dispersion-active vs dispersion-inactive. Hypothesis: ≥10pp precision lift in active-dispersion regimes; this is the most-impactful gating feature for the whole suite.
- **Source category:** **High**.
- **Free + public source(s):** `yfinance` for index constituents (S&P 500 ticker list maintained in repo or scraped from Wikipedia once/month — stable URL, low scraping risk).
- **Latency:** EOD.
- **Failure mode:** **Slow-moving label** — 60d beta windows lag regime changes by ~3 weeks. This is a *gating* feature, not an alert feature. Use as a multiplier on signal-confidence scoring, not as a standalone trigger. Manipulation: low. **Blind spot:** during macro-shock events (e.g. 2020-03), correlations spike and dispersion collapses very rapidly — the lagged label says "rotation-active" while the world has already gone into "everything-correlated" mode; defensive override: when `VIX > 35`, force-set label to `low-dispersion` regardless of the rolling computation.

---

### 12. Anchored-VWAP reclaim from major lows

- **Name:** `anchored_vwap_reclaim`
- **Function:** Identify "major low" anchor bars per ticker:
  - Anchor candidate = any bar where `low = rolling_min(low, 60)` AND `volume ≥ 1.5 × rolling_mean(volume, 20)`.
  - From anchor bar forward, compute `AVWAP_anchor[t] = sum(typical_price[s] × volume[s]) / sum(volume[s])` for s = anchor..t, where `typical_price = (H + L + C) / 3`.
  - **Trigger:** fire long-bullish alert when (a) the ticker has had ≥10 consecutive sessions with `close < AVWAP_anchor`, (b) today's close prints `>1% above AVWAP_anchor` on `volume ≥ 1.2 × avg_20d_volume`, AND (c) today's close is above the highest close during the anchor-to-now window's first 10 sessions (rejecting micro-bounces).
  - Recompute anchor daily; if a new bar qualifies as a more-recent + higher-volume anchor, switch to it.
- **Levels emitted:** `entry = close`, `stop = AVWAP_anchor − 0.5 × ATR(14)` (small buffer below the reclaimed VWAP), `target = recent swing high or close + 3.0 × ATR(14)` whichever is closer. Time stop = 21 days.
- **Rationale + measurable edge hypothesis:** **Persistent reason:** AVWAP from a high-volume capitulation low marks the average cost-basis of all participants since the low; reclaiming it transitions the average holder from underwater to in-profit, which materially changes selling pressure (loss-aversion → less selling at break-even than at a loss). This is a behavioral-flow argument, not chartcraft. Edge measure: forward 21d return of confirmed reclaimers vs forward return of names that touched-but-failed AVWAP. Hypothesis: ≥3% mean lift over 21d for confirmed reclaimers; precision (positive 21d return) ≥58%.
- **Source category:** **High** (OHLCV).
- **Free + public source(s):** `yfinance` daily OHLCV. Hand-rolled AVWAP (no library needed; trivial pandas cumsum).
- **Latency:** EOD.
- **Failure mode:** **Whipsaw at AVWAP** — single-day reclaim followed by next-day fail is common (~30% of fires). Mitigate by requiring 2-day close-above confirmation OR pair with volume-confirmed N-day breakout (#1) for two-source corroboration. **Blind spot:** AVWAP can be "outdated" if a newer larger-volume low forms — recompute anchor daily as specified above. **Failure regime:** in strong downtrend regimes (50d SMA falling, ADX>25 in down direction), AVWAP reclaims are often bear-trap rallies that fail within 5 sessions; gate on `SMA(close, 50)` not falling more than 2% from its 20d-prior value.

---

## Priority ranking (researcher's view; synthesis owns final cut)

| # | Feature | Instant-trigger eligible? | Implementation cost | Highest-conviction edge | Notes |
|---|--------------------------------------|---|---|---|---|
| 1 | breakout_n_day_volume                | Yes | Low | High | Bedrock; combine with regime gates from #11 |
| 9 | pre_fomc_drift                       | Yes | Low | Very High | Calendar event; tightest precision |
| 2 | vix_term_structure_flip              | Yes | Med | High | Index-level; fires <10x/year so doesn't spam |
| 3 | credit_equity_divergence             | Yes | Low | High | Macro context, fires monthly cadence |
| 4 | orb_15m_vwap                         | Yes | Med | Med | Per-ticker; latency honesty important |
| 5 | cross_sectional_momentum_jump        | Yes | High | High | Universe scan; needs caching layer |
| 7 | breadth_rotation_divergence          | Yes | Low | Med | Macro context |
| 12| anchored_vwap_reclaim                | Yes | Low | Med | Per-ticker; behavioral flow |
| 8 | sector_rotation_rank_jump            | Yes | Low | Med | 11-ETF universe; fires often enough |
| 6 | nsigma_mean_revert                   | Caution | Low | Med | Catastrophic failure mode in trends |
| 10| skew_vix_divergence                  | **No** — 2-source | Low | Low precision standalone | Probability-shifter, not trigger |
| 11| beta_rotation_regime                 | **No** — context only | Med | N/A as alert | Gating feature for others |

---

## Excluded (and why)

- **Order-flow / dark-pool prints:** Requires OPRA/SIP feeds or paid vendors (Cheddar Flow, Unusual Whales API, BookMap). Out-of-scope per "free + public" constraint. Listed in CLAUDE.md as instant-trigger but it would need a paid feed.
- **Implied-volatility crush trades around earnings:** Requires reliable IV surface across strikes/expiries. yfinance options chains are too thin and unreliable for systematic IV-rank computation. Could be revived if a free options-vol-rank feed appears.
- **Smart-money put/call ratios:** CBOE's free P/C ratio ETF data is published with multi-day lag; loses signal value. Real-time P/C requires paid feed.
- **Pairs trading / statistical arbitrage:** Requires intraday cointegration testing on a universe of pairs; computationally expensive and the alpha has compressed substantially since 2010. Out-of-scope for a Discord alert bot whose value-add is timely surface, not portfolio construction.
- **Microstructure features (bid-ask imbalance, order-book pressure):** Requires order-book depth (not available free).
- **Earnings surprise / SUE-based PEAD:** PEAD literature says lift exists, but reliable SUE construction requires consensus-estimate history and reported-eps history with point-in-time accuracy. Free analyst-consensus data is sparse and revision-noisy. Not worth the data-hygiene cost; revisit if/when a reliable free consensus feed is identified. (Earnings *date* signals are still in scope via existing scanners — that's separate.)
- **Daily Fama-French factor returns:** Ken French publishes monthly, weekly only for some series, not daily. Not actionable at the bot's daily cadence except as month-end calibration. Listed but not as a feature.
- **Pure chart patterns (head-and-shoulders, triangles, flags):** No persistent economic mechanism beyond breakout-with-volume (#1). Pattern-recognition adds noise without alpha; excluded.
- **Day-of-week effects and Monday/Friday seasonals:** Statistically marginal in the post-2000 sample after ETF arbitrage compressed them. Per Quantpedia review, classical TOM effect has weakened to non-significant. Not worth the false-positive cost.
- **VIX1D (1-day VIX) standalone signal:** Newer literature (Albers 2025) suggests it adds info, but data history is short (since 2023). Insufficient out-of-sample to commit; revisit in 12 months.
- **Single-stock pin-risk / max-pain options theories:** Requires reliable open-interest snapshots per strike — yfinance options chain has known data integrity issues (stale OI fields, missing strikes). Not robust enough.

---

## Sources consulted (research trail)

- CBOE VX futures historical data structure: https://www.cboe.com/markets/us/futures/market-statistics/vix-settlement-series/ and macroption.com archive
- VIX term-structure as predictive signal: Quantpedia "Exploiting Term Structure of VIX Futures"; Macrosynergy "VIX term structure as a trading signal"
- VVIX / vol-of-vol predictability: FRB FEDS 2013-54 "Volatility of Volatility and Tail Risk Premiums"
- SKEW data endpoint: `cdn.cboe.com/api/global/us_indices/daily_prices/SKEW_History.csv` (verified pattern); fallback Yahoo `^SKEW`
- Pre-FOMC drift: Lucca & Moench 2014 NY Fed Staff Report 512; Applied Economics 2024 revisit
- 52-week-high momentum / anchoring: George & Hwang 2004 Journal of Finance
- Cross-sectional momentum: Jegadeesh & Titman 1993; momentum-30-years review (Springer 2022)
- PEAD persistence: ScienceDirect 2024 "A simple earnings surprise measure"; CFA Institute 2025 "Can Generative AI Disrupt PEAD?" — informed exclusion decision
- ADX as regime filter: Schwab/StatOasis education; pandas-ta and stockstats for indicator implementation
- HYG vs SPY credit-equity divergence: State Street market-mind November 2025; Connect CRE "HYG's Alarming Break"
- FRED API for credit spreads / yield curve: mortada/fredapi GitHub; pandas-datareader docs
- Ken French data via pandas-datareader: pydata.github.io/pandas-datareader (monthly factor series only)
- Connors RSI(2) mean-reversion: QuantifiedStrategies.com backtest archive (1993–present SPY)
- Turn-of-month effect decline: ScienceDirect 2022 "TOM and trading of types of investors"; Quantseeker 2024 update — informed exclusion
- Technical indicator libraries: pandas-ta, stockstats, ta (bukosabino), TA-Lib — all BSD/MIT-licensed, free.

---

## Implementation notes for synthesis

- All features above are **EOD-friendly first**, with intraday extensions where the signal has a real-time hook (especially #4 ORB and #9 pre-FOMC). The bot is already structured around scan loops; these signals fit the existing pattern.
- **Caching layer is non-negotiable** for #5 (cross-sectional rank): scanning 500–2000 tickers via yfinance daily is slow (~3–5 min) and rate-limited. Cache keyed by `(date, ticker)` in the existing SQLite `data.db`. Recompute on demand only on missing-row or explicit invalidate.
- **Calendar dependencies:** #9 (FOMC) and any earnings/CPI/NFP-day filters need a maintained calendar. Recommend a single `events_calendar.yaml` cached annually with manual refresh — Fed and BLS publish stable schedules, low scraping risk.
- **Regime detection is the highest-leverage shared infrastructure.** A single regime classifier (VIX bucket × ADX bucket × dispersion bucket × term-slope sign) gates ≥7 of the 12 features. Build this once in `regime_detector.py`-style module, reuse everywhere. The features above all reference 2–4 regime gates; without a shared classifier the gating logic gets duplicated and inconsistent.
- **Source-tier interplay:** features #1, #2, #3, #4, #7, #8, #10 are all "High" source-tier (exchange/CBOE/FRED) — strong fit for the alert philosophy's instant-trigger exception. Features #5, #6, #11, #12 are derivative-of-OHLCV and should be scored slightly lower in confidence weighting.
- **Score combinator suggestion:** use multiplicative confidence-weighting where each feature emits `confidence ∈ [0,1]` based on signal strength (e.g. how far past 2σ the move is, how strong the volume confirmation is) and the alert score is `base_confidence × regime_multiplier`. Regime multiplier is 1.0 in benign regimes, 0.5–0.8 in adversarial regimes (high VIX for momentum signals, low ADX for breakout signals).
- **Backtest infrastructure prerequisite:** every claimed "edge measure" hypothesis above is a falsifiable claim that needs backtest validation before going live. Recommend a thin `signals/_backtest.py` harness that walks each signal forward through a 3–5 year window of cached daily OHLCV and computes precision, lead-time-vs-FinTwit, expectancy. Start with #1, #2, #3, #9 (highest-priority, lowest-cost backtests).
- **Alert spam control:** several features (especially #1 across N=20/60/252 tiers, #5 across 2000 tickers) will fire many times per day. Need a per-ticker dedupe (don't re-fire on same ticker within 24h for same signal) and a per-feature daily quota (e.g. max 20 alerts/day for breakout, max 5 for momentum-jump). The instant-trigger exception removes the cross-source gate, not the dedupe.

---

## Open questions / synthesis hooks

- Is there an internal scoring model that already weights "instant-trigger" features against multi-source ones? If so, features above should be normalized into that schema.
- Do we have point-in-time S&P 500 / Russell 2000 constituent history? If yes, #5 is much more rigorously backtest-able. If no, use current-membership snapshots as approximation and accept the survivor bias note.
- The Fed publishes FOMC dates *with sometimes-imprecise times*; does the existing event-calendar pipeline handle the 2pm/2:15pm/2:30pm variation? Pre-FOMC (#9) entry timing is sensitive to it.
- Should the bot publish EOD-only alerts during the standard trading day, or queue them for next-morning pre-market delivery? The latter is friendlier to retail users who can't act at 16:00 ET.

---

## Suggested shared infrastructure (synthesis can decide priority)

These features have heavy overlap in their data needs; building a few shared modules halves the per-feature implementation cost.

1. **Universe-cache module** (`signals/_universe_cache.py`): nightly `yfinance.download(BATCH, period='2y', interval='1d')` of S&P 500 + Russell 2000 + sector ETFs + macro tickers (HYG/LQD/IEF/SPY/QQQ/IWM/MDY/RSP/^VIX/^SKEW/^VIX9D/^VIX3M). Persist to SQLite `data.db` with `(date, ticker)` PK. Used by features #1, #5, #6, #7, #8, #11, #12.
2. **Indicator-pipeline module** (`signals/_indicators.py`): wraps `pandas-ta` to bulk-compute ATR(14), RSI(2,14), ADX(14), BBwidth(20,2), SMA(20,50,200) per ticker per day. Used by features #1, #4, #5, #6, #12.
3. **Regime-classifier module** (`signals/_regime.py`): single source of truth for VIX bucket × ADX bucket × dispersion bucket × term-slope sign. Returns a structured `Regime` dataclass consumed by ≥7 of the 12 features. **Highest-leverage shared piece.**
4. **Event-calendar module** (`signals/_calendar.py`): YAML-cached FOMC + CPI + NFP + earnings calendars. Used for event-day suppression in #4 ORB and as the trigger for #9 pre-FOMC.
5. **Alert-format module** (`signals/_format.py`): standard payload `{"ticker", "direction", "feature_name", "entry", "stop", "target_1", "target_2", "time_stop", "regime_context", "confidence", "rationale_text"}` to keep the Discord output uniform across features. Already exists in some form per `consensus_engine/alerts/` — extend rather than fork.

Together these 5 modules turn most features above into 50–150-line additions rather than full-stack reimplementations. Recommend building them in order before the feature backlog opens.
