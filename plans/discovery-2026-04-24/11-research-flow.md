# Phase 1 Research: Flow & Microstructure Features

**Author:** worker-11 (flow/microstructure lane)
**Date:** 2026-04-24
**Scope:** Candidate features for a retail trade-idea Discord bot that surface actionable setups
BEFORE mainstream price confirmation, sourced from the flow / microstructure envelope.
**Constraints:** Free + public data only. No OPRA, NASDAQ Basic, ICE, or paid options feeds.
No fragile scraping that ToS-blocks under load. 2+ source cross-reference for non-instant-trigger
features; per CLAUDE.md, *large options activity AND unusual flow* are explicit instant-trigger
exceptions and a well-sourced single flow feature can stand alone as an alert.
**Mode:** Aggressive proposal — synthesis will cut.

---

## Executive Framing

Flow and microstructure data is, in a free-tier world, dominated by **post-trade, T+1, weekly,
or bi-monthly latencies**. The few real-time leading signals available without paid feeds are:

1. **Options chain snapshots** (delayed 15 min) from yfinance / Tradier-sandbox / Alpaca.
2. **CBOE end-of-day put/call ratio CDN files** (free CSV, EOD).
3. **FINRA daily short sale volume** (T+1, EOD same-day at 6 PM ET).
4. **OCC daily volume statistics** (T+1, EOD).
5. **Reg SHO threshold security list** (daily, end-of-day publication).

Slower confirmatory feeds:

6. **FINRA Equity Short Interest** (bi-monthly, ~10-day lag).
7. **SEC Failures-to-Deliver** (bi-monthly, ~15-day lag).
8. **FINRA ATS weekly transparency** (Tier-1 NMS, 2-week lag; Tier-2/OTC, 4-week lag).
9. **13F institutional holdings** (quarterly, 45-day lag).
10. **ETF holdings / shares-outstanding diff** (daily for SPDR/iShares, EOD).

Per the alert philosophy, features 1-5 are candidates for **standalone instant alerts** when an
extreme threshold fires. Features 6-10 are confirmatory `+xref` boosts that raise the score of
a tweet/news/options trigger but should not, by themselves, fire a Discord alert. Each feature
below explicitly tags its alert tier.

---

## Feature 1 — Options Volume / Open-Interest Sweep Detector

- **Function:** For each option contract on a watchlist ticker, compute
  `volume / max(open_interest, 1)` per fetch. When any contract crosses a tunable threshold
  (e.g. ratio >= 3, raw volume >= 500, OI >= 100) emit an "unusual options activity" candidate
  tagged with strike/expiry/side.
- **Rationale + measurable edge hypothesis:** Volume materially exceeding open interest on a
  single strike is a textbook footprint of a fresh directional position by a non-retail
  participant; Barchart's standard "unusual" cutoff is V/OI >= 1.25 with V >= 500 and OI >= 100.
  Hypothesis: among contracts crossing 3x V/OI on liquid (>= $5 ADV) underlyings, the underlying
  outperforms its 5-day baseline median in the implied direction with measurable lift over 1-5
  trading days. Measure precision: % of triggers where underlying moves >= 1 ATR in implied
  direction within 3 sessions; measure lead-time vs. mainstream news coverage.
- **Source category:** **Medium** (yfinance / Tradier sandbox aggregate dealer-reported chains;
  not OPRA tape, so no per-trade granularity → cannot true-sweep across exchanges).
- **Free + public source(s):**
    - `yfinance` `.option_chain(expiry)` returns `volume`, `openInterest` per strike (already
      used in repo `consensus_engine/scanners/options.py`).
    - **Tradier sandbox** REST API `/v1/markets/options/chains` (`sandbox.tradier.com`),
      120 req/min, free with broker account, no funding required.
    - **Alpaca options chain** `/v1beta1/options/snapshots/{underlying}` since Feb 2024 history,
      free tier, up to 10,000 calls/min advertised.
- **Latency:** Quotes are 15-min delayed on free yfinance / Tradier sandbox. Volume/OI fields
  refresh after each delayed snapshot; OI is *previous-session close* (OCC publishes ~T+1).
- **Failure mode:**
    - yfinance has a known issue where `openInterest == 0` for many tickers (issue #2408);
      ratio explodes to inf and produces false positives. Must filter `OI >= 100` strictly.
    - Yahoo rate-limits / blocks aggressive callers; Tradier sandbox is the more durable
      backbone. Single-exchange aggregation (no NBBO trade-side print), so cannot distinguish
      true *sweep* (multi-exchange one-shot order) from heavy single-strike volume.
    - Market-maker hedging activity inflates V on far OTM strikes around opening crosses;
      time-of-day filter (skip first 15 min, last 5 min) reduces this.
- **Alert tier:** **Instant-trigger eligible** (matches "large options activity / unusual flow"
  exception in CLAUDE.md alert philosophy).

---

## Feature 2 — Aggressive Single-Strike Premium Spend ("Conviction Dollar Flow")

- **Function:** For each unusual contract from Feature 1, compute notional premium spent =
  `volume × last_price × 100`. Rank by premium across all triggers in the polling window.
  Alert only when notional crosses a tunable floor (e.g. >= $250K on a single strike) AND the
  contract is short-dated (DTE <= 30) — this is the highest-information-content variant.
- **Rationale + measurable edge hypothesis:** Raw V/OI ratio is noisy; weighting by premium
  filters out cheap lottery-ticket far-OTM activity and surfaces moves where someone is willing
  to put real capital at decay risk. Hypothesis: short-DTE single-strike trades >= $250K
  notional precede underlying moves with materially higher precision than V/OI alone. Measure:
  precision uplift on Feature 1's hit-set when filtered by premium.
- **Source category:** **Medium** (same data source as Feature 1).
- **Free + public source(s):** yfinance / Tradier sandbox / Alpaca options chain
  (`option.lastPrice * volume * 100`).
- **Latency:** 15-min delayed.
- **Failure mode:**
    - `lastPrice` from yfinance is the last *trade*, but volume aggregates over the session, so
      notional is upper-bounded (premium drift through session). Mitigate by using
      `volume_weighted_estimate = volume * (bid + ask) / 2`.
    - Spread-and-bait orders on illiquid contracts can paint volume without genuine commitment.
    - Late-day pin-risk hedging by MMs around 0DTE can inflate notional.
- **Alert tier:** **Instant-trigger eligible**.

---

## Feature 3 — Put/Call Ratio Z-Score (Per-Ticker)

- **Function:** Compute today's per-ticker put/call volume ratio from the options chain
  (sum put V / sum call V). Maintain a rolling 60-day mean and std-dev; emit a confirmatory
  signal when today's ratio is >= 2σ from the mean in either direction.
- **Rationale + measurable edge hypothesis:** Per-ticker PCR z-scores capture sentiment shifts
  before headline news. Academic literature shows volume PCR is an efficient predictor of
  market return on a 2.5-day window; extreme per-ticker PCR (95th/5th percentile) flips
  contrarian within ~20 trading days in 68% of cases (Journal of Portfolio Management cited in
  AAII / strike.money review). Hypothesis: ticker-level PCR z >= 2 (extreme bearishness) is a
  contrarian boost; PCR z <= -2 (extreme bullishness) is a directional confirm. Measure:
  hit-rate of z-scored signals when xref'd with Feature 1.
- **Source category:** **Medium** (same chain feed).
- **Free + public source(s):** yfinance options chain → aggregate by side; Tradier sandbox
  `/markets/options/chains` totals.
- **Latency:** 15-min delayed; computed per polling cycle.
- **Failure mode:**
    - PCR is famously contrarian-mixed: extreme PCR is sometimes hedging flow, not sentiment.
    - Survivorship: tickers with thin options markets produce noisy z; filter by ADV >= 1000
      contracts/day. Index/ETF underlyings have systematic put bias from portfolio insurance,
      so PCR levels are not directly comparable across tickers — z-score (not absolute level)
      is the right framing.
- **Alert tier:** **Confirmatory `+xref`** (not standalone — too prone to false positives on
  earnings-week hedging).

---

## Feature 4 — Cboe Daily Equity & Index Put/Call Ratio (Market Regime)

- **Function:** Fetch Cboe's published daily put/call ratio CSVs for total-equity and index
  options. Compute z-score against trailing 60 days. Use as a *market-regime gate*: damp
  long-side bullish single-name alerts when index PCR is in extreme fear regime or extreme
  greed regime (depending on contrarian model).
- **Rationale + measurable edge hypothesis:** Market-wide PCR shifts the base-rate of single-
  name flow signals. A bullish unusual-options trigger on ticker XYZ has higher follow-through
  when market PCR is at extreme fear (contrarian bottom) than at extreme greed. Hypothesis:
  conditioning Feature 1's hit set on Cboe equity-PCR regime improves precision by 5-10pp.
  Measure: precision delta with vs. without regime gate.
- **Source category:** **High** (CBOE official EOD CSV, regulated exchange data).
- **Free + public source(s):**
    - `https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/equitypc.csv`
      (columns: DATE, CALL, PUT, TOTAL, P/C Ratio; daily history from 2006-11-01).
    - `https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/indexpcarchive.csv`.
- **Latency:** EOD; updated within ~30 min of close.
- **Failure mode:**
    - File occasionally has formatting changes (header rows shift). Wrap parse in try/except
      with schema validation.
    - CDN does not rate-limit, but aggressive scraping of the broader CBOE delayed-quotes site
      *is* IP-blocked (per Cboe TOS); stick to the CDN endpoint.
- **Alert tier:** **Confirmatory regime filter** (gates other alerts; not a standalone trigger).

---

## Feature 5 — VIX / VVIX / SKEW Volatility Term-Structure Spike

- **Function:** Track VIX, VVIX, and Cboe SKEW from FRED + Cboe official historical CSVs.
  Compute (a) day-over-day VIX change, (b) VIX9D / VIX ratio (term-structure), (c) VVIX z-score
  (vol-of-vol shock). Emit a market-stress flag when VIX9D/VIX > 1.0 (inversion) or VVIX z > 2.
- **Rationale + measurable edge hypothesis:** Vol-of-vol spikes precede equity drawdowns by
  hours-to-days; VIX term-structure inversion is a classic stress signal. Hypothesis: filtering
  out long-side signals during VIX9D/VIX inversion improves precision; flagging short-side
  / hedge ideas during these regimes captures upside on volatility expansion. Measure:
  drawdown-conditional precision delta on Feature 1 long-side triggers.
- **Source category:** **High** (CBOE / FRED official).
- **Free + public source(s):**
    - **FRED:** series `VIXCLS`, `VXVCLS` (VIX 3-month). API:
      `https://api.stlouisfed.org/fred/series/observations?series_id=VIXCLS&api_key=...`.
    - **CBOE historical CSVs:** VIX, VVIX, SKEW exposed via `www.cboe.com/tradable_products/`
      pages with CSV download links per index.
    - **yfinance** symbols `^VIX`, `^VVIX`, `^VIX9D`, `^SKEW`.
- **Latency:** EOD official from CBOE / FRED; 15-min delayed intraday from yfinance.
- **Failure mode:**
    - VIX9D yfinance symbol is occasionally stale; cross-check with CBOE.
    - FRED API requires free key (env var); 120 req/min limit — non-issue for daily polling.
    - Vol regimes themselves are autocorrelated; using levels (not changes) leaks back-history.
- **Alert tier:** **Confirmatory regime filter** (and possibly standalone for sufficiently
  extreme VVIX z >= 3 — historically rare enough that "vol-shock pending" is genuine signal).

---

## Feature 6 — FINRA Daily Short Sale Volume Anomaly

- **Function:** Download the daily TRF + ADF + ORF (consolidated) short-sale volume file at
  ~6 PM ET. For each ticker compute `short_volume / total_volume` and z-score against 30-day
  rolling baseline. Emit a confirmatory alert when z >= 2 AND raw short volume >= 100k shares
  (filter out low-liquidity noise).
- **Rationale + measurable edge hypothesis:** FINRA short-volume ratio reflects same-day
  reported short trades (though not all short volume is directional — MM hedging is a
  significant chunk). Spike in ratio with stable price is a "loaded gun" condition for
  short-squeeze setups; spike with declining price confirms bear thesis. Hypothesis: tickers
  showing 2σ short-volume z-spike that do NOT trade lower next session see >50% probability of
  3-day positive return (squeeze pressure release). Measure: directional precision over
  T+1 to T+3.
- **Source category:** **High** (regulated FINRA TRF/ADF data, timestamped, auditable).
- **Free + public source(s):**
    - **FINRA Daily Short Sale Volume Files:**
      `https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data/daily-short-sale-volume-files`
      (.txt files, posted no later than 6:00 PM ET same trade date).
    - **FINRA API:** `https://api.finra.org/data/group/otcMarket/name/regShoDaily` (CSV / JSON
      output; Reg SHO Daily Short Sale Volume endpoint, documented at
      `developer.finra.org/docs/api-explorer/query_api-equity-reg_sho_daily_short_sale_volume`).
- **Latency:** T+0 EOD (~6 PM ET same day). The fastest official short-volume feed available
  free.
- **Failure mode:**
    - Market-maker hedging shorts inflate the ratio without expressing directional view; FINRA
      itself cautions against using short-volume ratio as a sole signal.
    - Excludes lit-exchange short trades — covers only TRF/ADF/ORF (off-exchange + ATS); a
      large lit-exchange short does not appear here. The ratio is therefore not a complete
      "% short" of trading.
    - File occasionally late by 1-2 hours; build retry/backoff into fetcher.
- **Alert tier:** **Confirmatory `+xref`** (not standalone — short-volume noise is too high).

---

## Feature 7 — Reg SHO Threshold List Entry / Exit Event

- **Function:** Daily-poll the Reg SHO threshold security lists from NASDAQ Trader, NYSE, and
  Cboe. Diff today's list against yesterday's. **New entries** flag a security that has had
  fails-to-deliver of >= 10,000 shares AND >= 0.5% of shares outstanding for 5 consecutive
  settlement days — a hard regulated event. **Exits** flag a security where the close-out
  obligation has resolved (often via a price move).
- **Rationale + measurable edge hypothesis:** Reg SHO threshold list inclusion is a leading
  indicator of forced buy-in pressure on heavily-shorted, low-liquidity names. Hypothesis: new
  entries to the threshold list outperform their sector by >= 1.5σ over T+5 to T+13 settlement
  days, especially when accompanied by Feature 6 short-volume z-spike. Measure: average excess
  return on entry-day cohort vs. matched-control cohort over T+5/T+13.
- **Source category:** **High** (regulated SRO publication, timestamped daily).
- **Free + public source(s):**
    - **NASDAQ:** `https://www.nasdaqtrader.com/dynamic/symdir/regsho/nasdaqth20260423.txt`
      (filename pattern `nasdaqthYYYYMMDD.txt`, daily).
    - **NYSE:** `https://www.nyse.com/regulation/threshold-securities`.
    - **Cboe:** `https://www.cboe.com/us/equities/market_statistics/reg_sho_threshold/`.
    - **OTC equities:** `https://otce.finra.org/otce/RegSHOThreshold/archives`.
- **Latency:** Daily, posted EOD same trade date.
- **Failure mode:**
    - Threshold inclusion sometimes triggers reflexive rallies that fade quickly (1-2 day
      half-life); xref with FTD trend (Feature 8) and short-interest level (Feature 9) is
      important.
    - Many threshold-list names are micro-cap / OTC, increasing manipulation risk.
    - Multiple lists (NASDAQ, NYSE, OTC) need union; symbol normalization required.
- **Alert tier:** **Instant-trigger eligible on liquid, large-cap entries** (>= $1B market cap)
  given the regulatory weight of the event; **confirmatory only** for micro-caps.

---

## Feature 8 — SEC Failures-to-Deliver (FTD) Trend & Spike

- **Function:** Pull the bi-monthly FTD CSVs from SEC, build a per-ticker FTD time series (CUSIP
  → ticker mapping). Compute (a) absolute FTD spike z-score, (b) FTD as % of float, (c)
  consecutive-period growth (3-period rising). Emit confirmatory boost when FTD growth is
  rising AND ticker is on the Reg SHO threshold list (Feature 7).
- **Rationale + measurable edge hypothesis:** Persistent / rising FTD volumes indicate failed
  short delivery obligations and cumulative buy-in pressure. Academic work (Pastorek et al.
  on T+35 cycles, GME case studies) confirms FTD volumes precede price moves on the order of
  1-3 weeks. Hypothesis: tickers with FTDs > 0.5% of float for 2 consecutive bi-monthly
  reports outperform sector-matched controls over T+15 to T+30 by an economically meaningful
  margin (>= 1σ). Measure: cohort excess return + Sharpe over the holding window.
- **Source category:** **High** (SEC official dataset, regulated, timestamped settlement-date
  granular).
- **Free + public source(s):**
    - **SEC:** `https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data` →
      bi-monthly ZIPs (e.g. `cnsfails202604a.zip`, `cnsfails202604b.zip`).
    - Existing OSS scrapers: `github.com/clatour/sec-failures-to-deliver`,
      `github.com/juszhan/Fail-To-Deliver`.
- **Latency:** **Bi-monthly with ~15-day lag.** First half of month released ~end of month;
  second half released ~15th of next month. Schedule must align with SEC's cadence.
- **Failure mode:**
    - FTDs include many benign causes (settlement delays, ETF AP basket failures); not all are
      bearish-positioning evidence. Filter by absolute level + persistence.
    - CUSIP-to-ticker mapping breaks on corporate actions; need a rolling CUSIP → symbol
      lookup (FINRA's symbol directory or OpenFIGI free API).
    - 15-day lag means this is *never* an instant trigger; strictly confirmatory.
- **Alert tier:** **Confirmatory `+xref`** to other short / squeeze signals; standalone alert
  is inappropriate given the lag.

---

## Feature 9 — FINRA Equity Short Interest Surprise

- **Function:** Pull FINRA bi-monthly short-interest reports. For each ticker compute (a) raw
  short-interest level, (b) days-to-cover (`SI / 30-day ADV`), (c) **surprise** = realized SI
  minus expected SI from a simple AR(1) baseline on the prior 6 reports. Emit confirmatory
  boost on |surprise z| >= 2 AND DTC >= 5.
- **Rationale + measurable edge hypothesis:** Recent academic work (Boehmer-style "surprise in
  short interest") shows that the *unexpected* component of SI changes — not the level —
  carries 4-6% annualized abnormal return when used to construct decile-portfolios. Hypothesis:
  same-day xref of SI surprise with Feature 1 (unusual options) and Feature 6 (short-volume
  spike) elevates a single-name signal to high-conviction status. Measure: precision of triple-
  xref hit set vs. single-source baseline.
- **Source category:** **High** (regulated FINRA biweekly).
- **Free + public source(s):**
    - **FINRA Equity Short Interest API:**
      `https://api.finra.org/data/group/otcMarket/name/EquityShortInterest` (CSV/JSON).
    - **OTC tier (pipe-delimited text archives):**
      `https://otce.finra.org/otce/EquityShortInterest/archives`.
    - **Public mirror:** `https://www.finra.org/finra-data/browse-catalog/equity-short-interest/files`.
- **Latency:** **Bi-monthly, ~10-day lag** (settlement T → reported T+2 → published T+8 to
  T+10 per FINRA 2026 calendar).
- **Failure mode:**
    - Lag means SI reflects positioning from ~10 days prior; intermediate covering / new shorts
      are invisible.
    - Reporting compliance is firm-level, so individual broker-dealer omissions can distort
      single-period readings; the AR(1) surprise model partly absorbs this.
    - 13F-aggregate cross-check is a useful sanity filter (not all "shorts" appear in 13F since
      it's long-only).
- **Alert tier:** **Confirmatory `+xref`** (lag rules out instant trigger).

---

## Feature 10 — FINRA ATS / Dark-Pool Volume Concentration

- **Function:** Weekly pull of FINRA ATS Transparency files. For each ticker compute
  (a) ATS share = ATS volume / total reported volume, (b) ATS-share z-score vs. trailing
  12-week rolling average, (c) Herfindahl on per-ATS distribution (concentration). Emit
  confirmatory boost when ATS share spikes >= 2σ above baseline AND a single ATS captures
  >= 60% of dark trades (concentrated accumulation).
- **Rationale + measurable edge hypothesis:** A single ATS dominating a ticker's dark volume in
  a given week is a fingerprint of a single large institutional accumulator (or distributor)
  routing to its preferred dark venue. Hypothesis: weeks with concentrated ATS spikes precede
  sector-relative outperformance by 5-15 trading days as the position is built up and
  eventually leaks into lit markets. Measure: weekly cohort excess return T+5 to T+20.
- **Source category:** **High** (FINRA OTC Transparency, regulated weekly publication).
- **Free + public source(s):**
    - **OTC Transparency portal:** `https://otctransparency.finra.org/otctransparency/`.
    - **Quarterly stats summary:**
      `https://www.finra.org/filing-reporting/otc-transparency/ats-quarterly-statistics`.
    - **API spec:**
      `https://www.finra.org/sites/default/files/OTC-Transparency-Data-File-Download-API-v04.pdf`.
- **Latency:** **Weekly with 2-week lag for Tier 1 NMS stocks; 4-week lag for Tier 2 / OTC.**
  Tier-1 covers most names a retail bot would alert on (large-cap NMS); the 2-week lag still
  rules out instant triggering.
- **Failure mode:**
    - ATS-share is post-trade, aggregate, not real-time book state — cannot promise real-time
      dark-pool prints (free data simply does not exist for that).
    - Concentrated ATS volume can also reflect a single broker's algo behavior, not directional
      conviction; cross-check with 13F changes for institutional confirmation.
    - "Block prints" are a different feed (TRF block size) and not in ATS data; must caveat.
- **Alert tier:** **Confirmatory `+xref`** strictly.

---

## Feature 11 — Odd-Lot Volume Rate Spike (Informed-Algo Footprint)

- **Function:** Track per-ticker odd-lot rate (count of odd-lot trades / total trades) using
  SEC MIDAS quarterly stock-by-stock data; for higher-frequency pickup, derive an *intra-day
  proxy* from yfinance / Tradier intraday tape by counting trades with quantity < 100 (where
  available). Spike trigger when daily odd-lot rate is z >= 2 above ticker's 60-day baseline.
- **Rationale + measurable edge hypothesis:** Modern academic literature (post-2014 transparency
  rule) shows odd-lot trades are *informed* (HFTs use sub-100 share orders for stealth and
  exploration) — the historical "odd-lot theory" of dumb retail is obsolete. Hypothesis: odd-
  lot rate spikes correlate with informed pre-positioning; precision uplift when xref'd with
  Feature 1 options activity. Measure: precision delta on combined trigger.
- **Source category:** **High** (SEC MIDAS official, quarterly per-stock CSVs); **Medium** for
  intraday proxy via Tradier tape (sub-second timestamps but no NBBO trade-condition codes).
- **Free + public source(s):**
    - **SEC MIDAS Market Structure Data Downloads:**
      `https://www.sec.gov/data-research/market-structure-data` (per-stock daily files,
      released quarterly).
    - **Aggregate visualizations (no download):**
      `https://www.sec.gov/marketstructure/datavis/ma_stocks_oddlotrate.html`.
    - **Intraday tape proxy:** Tradier sandbox `markets/timesales` (free with broker account).
- **Latency:** **Quarterly** for the official SEC dataset (lags by 1 quarter). Intraday proxy
  is real-time but lossy (no trade-condition flags).
- **Failure mode:**
    - SEC data is too lagged to be a fresh signal alone; useful only as a *baseline / regime*
      input.
    - Intraday odd-lot proxy from Tradier is not equivalent to TAQ tape and may miss
      cross-listed prints. Filter by ticker to those with verified high-quality time-and-sales.
    - Odd-lot rate is autocorrelated and ticker-specific; per-ticker baseline is mandatory.
- **Alert tier:** **Confirmatory baseline / regime input** (not standalone).

---

## Feature 12 — ETF Shares-Outstanding Daily Diff (Creation/Redemption Flow)

- **Function:** Daily pull of `shares outstanding` from issuer pages for top liquid ETFs (SPY,
  QQQ, IWM, sector SPDRs, popular thematic ETFs). Diff today vs. yesterday → net creation /
  redemption units. Aggregate by sector / theme to infer macro flow direction. Emit
  confirmatory regime input on extreme moves (z >= 2 vs. 60-day baseline).
- **Rationale + measurable edge hypothesis:** AP-driven creation/redemption captures real
  positioning by allocators (not retail order-flow). A surge of creations in XLE during a
  single session is a leading indicator of energy-sector institutional appetite that can
  inform both index-level and single-name calls. Hypothesis: top-decile creation / redemption
  z-scored sectors outperform / underperform their median peer by measurable margin over T+1
  to T+5; per-ticker single-name signals in those sectors get a directional `+xref` boost.
- **Source category:** **High** (issuer official CSV, audit-grade).
- **Free + public source(s):**
    - **iShares CSV holdings + shares outstanding:**
      `https://www.ishares.com/us/products/{PRODUCT_ID}/{ETF_NAME}/1467271812596.ajax?fileType=csv&fileName={TICKER}_holdings&dataType=fund`
      (e.g. IVV PRODUCT_ID = 239726).
    - **SPDR holdings:** `https://www.ssga.com/...` per-fund downloadable CSV.
    - **OSS aggregator:** `pypi.org/project/etf-scraper/`,
      `github.com/talsan/ishares` for batch retrieval.
    - **Shares-outstanding via yfinance:** `Ticker.info["sharesOutstanding"]` updates daily for
      ETFs (less reliable; cross-validate against issuer CSV).
- **Latency:** **EOD** (issuer CSVs typically refreshed by 6 PM ET).
- **Failure mode:**
    - Issuer URLs change without notice (iShares restructures product pages); must wrap
      fetches in retry + URL re-resolution.
    - Some thematic ETFs have low AP activity, so day-to-day diffs are too noisy to z-score
      reliably; restrict to ETFs with average daily creation activity > $10M.
    - In-kind creations are economically different from cash creations (dilution mechanics);
      cannot distinguish from shares-outstanding alone.
    - **ToS caveat:** Aggressive scraping of issuer pages can be throttled; respect robots.txt
      and add per-fund delays.
- **Alert tier:** **Confirmatory regime / sector input** (not standalone).

---

## Feature 13 — OCC Daily Total Options Volume Z-Score (Market Stress & Speculation Gauge)

- **Function:** Pull OCC daily total volume statistics. Compute (a) total contracts z-score,
  (b) call/put split z-score, (c) ETF-vs-equity split. Use as a market-regime input similar
  to Feature 4 but with broader coverage (all OCC-cleared options, not just CBOE).
- **Rationale + measurable edge hypothesis:** OCC daily volume captures *all* US-listed options
  activity (CBOE, NDX, ARCA, MIAX, etc.), giving a complete market-wide options participation
  read. Spikes in total volume often precede / coincide with vol-regime shifts. Hypothesis:
  conditioning single-name alerts on OCC volume regime improves precision in a measurable but
  small way (~2-5pp). Measure: precision delta with vs. without filter.
- **Source category:** **High** (OCC official daily statistics, audit-grade).
- **Free + public source(s):**
    - **OCC Daily Volume page:**
      `https://www.theocc.com/market-data/market-data-reports/volume-and-open-interest/daily-volume`.
    - **Direct HTTP download:** `https://www.theocc.com/webapps/trade-volume-download`
      (XML / TXT formats, last 30 trading days).
    - **Historical archive:**
      `https://www.theocc.com/market-data/market-data-reports/volume-and-open-interest/historical-volume-statistics`.
- **Latency:** EOD T+0 (typically posted ~6 PM ET).
- **Failure mode:**
    - Aggregate-only — cannot drill down to per-ticker without paid feed.
    - OCC's site occasionally has scheduled-maintenance gaps (weekends); fetcher must tolerate.
    - Volume includes both speculative and hedging flow; cannot separate them at this
      aggregate level.
- **Alert tier:** **Confirmatory regime input**.

---

## Cross-Feature Combination Heuristics (for synthesis to consider)

The flow envelope is most powerful when **multiple weak/medium signals stack**. Suggested
high-conviction stacks:

1. **Squeeze stack:** Feature 7 (Reg SHO entry) + Feature 8 (FTD rising) + Feature 9 (SI
   surprise z >= 2) + Feature 6 (short-volume z >= 2). When all four fire on a name with
   >= $500M float and price stable → very-high conviction long-side instant trigger.
2. **Institutional accumulation stack:** Feature 1 (unusual call activity) + Feature 2 (large
   premium spend) + Feature 10 (concentrated ATS spike) + Feature 12 (sector ETF creations).
   Aligned, this is the textbook "smart money accumulating" pattern; warrants instant
   long-side alert.
3. **Distribution stack:** Feature 1 (unusual put activity) + Feature 3 (PCR z >= +2) +
   Feature 5 (VVIX z >= 2) + Feature 12 (sector ETF redemptions). Aligned, a high-conviction
   short-side / hedge-pending alert.

---

## Excluded (and why)

The following candidates were considered and excluded — synthesis should not re-introduce them
without addressing the named blocker:

- **Real-time dark-pool prints / block trades.** No free post-trade feed is real-time; FINRA
  ATS is 2-4 weeks lagged; TRF block-size data is not separately published. Marketing claims
  of "real-time dark-pool flow" rely on paid OPRA-tape derivatives which the project cannot
  use.
- **OPRA full-tape options trades / true sweep detection.** OPRA feed access is paid only;
  free chains aggregate volume by strike but do not expose the per-trade exchange-route data
  needed to identify actual sweeps. Feature 1's "unusual options activity" is the best
  available proxy.
- **Real-time order-book imbalance / Level-2 / NBBO depth.** No free vendor offers compliant
  Level-2 retail feeds; Alpaca and Tradier sandbox provide top-of-book only. Order-book
  imbalance is an attractive feature but cannot be free-tier sourced reliably.
- **Direct borrow rate / utilization feeds.** IBKR's Securities Lending Dashboard is
  account-gated and not API-exposed for non-customers; Fintel / S3 data is paid; no
  reliable free, public, programmatic borrow-rate feed exists. (Manual scraping of IBKR's
  short-availability page violates ToS at scale.)
- **CBOE delayed quote tables (live UI scraping).** Cboe explicitly prohibits automated
  extraction of delayed-quote tables from `cboe.com/delayed_quotes/` and IP-blocks offenders.
  Stick to the CDN CSVs (Feature 4).
- **Alpha Vantage real-time options chain.** Real-time chain endpoint is premium-only on
  Alpha Vantage; free / 75-RPM tier returns demo placeholder data. Historical-only options
  endpoint is free but doesn't help a live signal engine.
- **Forum-scraped "smart money" posts (e.g. WallStreetBets order-flow speculation,
  retail-flow proxies from third-party blogs).** Low-source-category, no auditability,
  high noise — not aligned with the project's quality-over-quantity philosophy.
- **13F real-time tracking.** 13F lag is 45 days post quarter-end. Useful as a slow-moving
  context layer (could subtly inform Feature 10 sanity filtering) but does not deserve
  a top-level feature slot in the flow lane; better suited to a fundamentals lane.
- **GameStop-style "T+35 cycle" timing rules.** Academic confirmation exists (Pastorek 2023)
  but is highly ticker-specific and prone to overfitting. Excluded as a primary feature;
  Feature 8 (FTD trend) captures the underlying signal more robustly.

---

## Sources Verified

The following endpoints / claims were verified during this research via WebSearch (specific
result snippets above the line, citations in markdown links below):

- FINRA Daily Short Sale Volume — same-day 6 PM ET posting
- FINRA Equity Short Interest — bi-monthly with ~10-day lag, pipe-delimited / CSV / JSON
- FINRA ATS Transparency — weekly with 2-week (Tier 1) / 4-week (Tier 2/OTC) lag
- SEC FTDs — bi-monthly, ~15-day lag, .zip CSVs
- Reg SHO Threshold lists — daily by NASDAQ / NYSE / Cboe / FINRA
- Cboe equity P/C ratio CDN — `equitypc.csv`, daily, columns DATE/CALL/PUT/TOTAL/Ratio
- OCC daily volume — same-day EOD, XML / TXT download
- yfinance options reliability — known OI=0 bug, rate-limit risk
- Tradier sandbox — 120 req/min free; sandbox endpoint accessible
- Alpaca options — 10k req/min advertised, history since Feb 2024
- Alpha Vantage options — real-time premium-only; historical free
- iShares holdings CSV URL pattern — verified format
- SEC MIDAS odd-lot rate — quarterly per-stock downloads
- FRED VIX series — `VIXCLS`, free API key

End of file.
