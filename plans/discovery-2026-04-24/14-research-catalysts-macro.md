# Phase 1 Discovery — Catalysts & Macro Features

**Author:** catalysts/macro researcher (Phase 1)
**Date:** 2026-04-24
**Scope:** Free, public catalyst & macro feature candidates for the `consensus_engine` retail trade-idea bot. Synthesis will dedup against social, technical, options, and microstructure tracks.

---

## Framing notes (read first — these constrain every feature)

1. **Catalysts almost always confirm; they rarely instant-trigger.** A scheduled event (earnings date, PDUFA date, FOMC meeting) is in everyone's calendar. The edge is in *interpretation* of the print, *positioning* into the print, or *cross-confirmation* of an unscheduled signal (e.g., a tweet) by an upcoming catalyst. Every feature below is framed as "what we do AT, AROUND, or AS-A-CROSS-CHECK-OF a catalyst," not "alert that a catalyst exists."
2. **8-K is never a standalone alert** (per `CLAUDE.md`). 8-K may *score* an existing thesis or feed the LLM thesis generator, never the opposite. Same for Form 4 (already +15 score per project rules).
3. **PEAD has decayed in large-cap.** Decades-old anomaly, gone in non-microcaps by ~2006 per Alpha Architect / UCLA Anderson reviews. Where we use it, we restrict to microcap or to the surprise-magnitude tails, and we measure lift honestly.
4. **Free + public only.** No Benzinga Pro, no TradeTheNews, no paid PDUFA aggregator subscription. We use SEC EDGAR (full-text + EFTS), openFDA (240 req/min, no key), ClinicalTrials.gov v2 (no key, ~10 req/s), FRED (free key, generous), BLS (500/day registered), Fed press-release pages (RSS), Yahoo/Nasdaq earnings calendars (unofficial JSON), CBOE delayed EOD options, yfinance options chains.
5. **2+ independent source rule.** Catalyst features are *typically* the second source confirming a primary signal. Where they instant-trigger (large insider cluster, AdCom disaster, surprise CRL), the feature must call out the exception.

---

## Feature catalogue

Twelve candidates ordered roughly by expected coverage × edge density. Synthesis will cut.

### C1. Earnings-Window Risk Gate

- **Function:** For every ticker that surfaces from any other engine (tweet, technical, social), the resolver looks up the next earnings date and tags the signal with one of `pre_earnings_T-N`, `into_earnings`, `post_earnings_T+N`, or `clear` so downstream scoring and alert text reflect event-driven risk.
- **Rationale + edge:** Pre-earnings signals from social media have a fundamentally different prior than mid-quarter signals — implied vols are elevated, dealer hedging is asymmetric, and the *information* content of unusual flow is qualitatively different. Treating "AAPL bullish tweet" identically 1 day before earnings vs 30 days before is a known precision leak. Measurable lift: precision delta between gated vs ungated cohorts on the same upstream signal class. Aim for +10–20% precision on social signals fired in the T-3 to T+1 window.
- **Source category:** Medium (Yahoo/Nasdaq earnings calendars).
- **Free/public sources:**
  - `yfinance.Ticker(symbol).calendar` returns next earnings date.
  - Nasdaq public JSON: `https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD`.
  - Yahoo public earnings calendar page: `https://finance.yahoo.com/calendar/earnings`.
  - `s-kerin/finance_calendars` PyPI wrapper around Nasdaq's public endpoint.
- **Latency:** Daily (refreshed once at session open is sufficient for a T-N gate).
- **Failure mode:** Unofficial Yahoo/Nasdaq endpoints can return stale or wrong dates for small-caps (especially when companies pre-announce or shift). Robustness: cross-check Yahoo vs Nasdaq vs whatever sec_edgar returns from 8-K item 2.02 history. If mismatch ≥ 2 days, treat as "uncertain" rather than "clear."
- **Measurement methodology:** Backtest by replaying the prior 6 months of fired alerts; bucket by `days_to_earnings`; compute precision per bucket. Threshold-tune the gate (probably suppress T-1/T+0/T+1 default-ON, T-2/T+2 conditional). Report bucketed precision and alert-volume delta.
- **Alert-text contribution:** "Reports earnings in 4 sessions (post-mkt 2026-05-01)" appended to alert body when bucket ≠ `clear`. No emojis.
- **Implementation effort:** Low. ~1 day. Uses existing `scanners/earnings_calendar.py` (already in repo) plus a thin tagger called from the resolver.

---

### C2. Earnings Surprise Decomposition (revenue-beat vs cost-beat vs guidance)

- **Function:** When a ticker reports earnings, parse the 8-K Item 2.02 exhibit (press release) to decompose the beat into (a) revenue surprise, (b) EPS surprise driven by margin/cost, (c) forward-guidance delta vs prior consensus. Score the *type* of beat, not the headline.
- **Rationale + edge:** Cost-driven beats are demonstrably less rewarded than revenue-driven beats; guidance changes dominate the short-term tape (multiple academic and practitioner sources). Headline EPS beats with guide-downs frequently sell off — "beat & lower" is a known pattern. A bot that distinguishes the *kind* of beat catches asymmetric setups that headline-beat scrapers miss. Measurable lift: directional precision on T+0 to T+3 returns conditional on each category.
- **Source category:** High (SEC EDGAR primary; LLM thesis only per `CLAUDE.md`'s "8-K → LLM thesis" rule, not an instant alert).
- **Free/public sources:**
  - SEC EDGAR EFTS full-text search (`https://efts.sec.gov/LATEST/search-index?q=&dateRange=custom&forms=8-K`) — 10 req/sec, no key, requires User-Agent.
  - SEC submissions feed `https://data.sec.gov/submissions/CIK{cik}.json`.
  - Cross-ref against Yahoo/Nasdaq consensus EPS for surprise sign.
- **Latency:** Event-driven (within minutes of 8-K hitting EDGAR). Critical that we treat this as a *thesis-builder*, not a standalone alert.
- **Failure mode:** 8-K text parsing is fragile (every issuer formats differently; non-GAAP vs GAAP confusion is rampant). Mitigate by treating extracted numbers as *probabilistic* — if confidence < threshold, fall back to cached consensus delta only and do not score the guide component.
- **Measurement methodology:** For the most recent 4 earnings seasons, label each report by category (rev-beat / cost-beat / guide-up / guide-down / mixed). Compute mean T+0, T+1, T+3 returns per category vs SPY-beta-adjusted benchmark. Validate that the rank ordering matches literature (rev-beat-with-guide-up >> cost-beat-with-guide-down etc.).
- **Alert-text contribution:** Embedded in LLM thesis paragraph only — never raw structured numbers in the alert. Example thesis seed: "Beat driven primarily by SG&A reduction; guide for next quarter trimmed at midpoint."
- **Implementation effort:** Medium-high. ~3–5 days. 8-K parser + LLM prompt-engineering + non-GAAP detection. Largest risk: parsing reliability across issuer formats.

---

### C3. PDUFA / AdCom Proximity & Polarity Tag

- **Function:** Maintain a rolling 90-day window of upcoming PDUFA decision dates and AdCom advisory committee meetings keyed to ticker. When the bot considers a biotech ticker, attach `next_pdufa_in_days`, `next_adcom_in_days`, and a `historical_adcom_polarity` based on prior FDA AdCom vote outcomes for the sponsor (openFDA Drugs@FDA).
- **Rationale + edge:** Pre-PDUFA volatility is well-documented. Most bots either ignore the catalyst or treat it as a binary alert — neither is useful. The edge is in *positioning context*: a bullish flow signal on a small-cap biotech 5 trading days before a PDUFA reads completely differently from the same signal 60 days out. We don't try to *predict* approval; we use the calendar to discount or amplify other engines' confidence. For AdCom, the briefing-document release (typically T-2 trading days before the meeting) is a known mini-catalyst.
- **Source category:** High for the calendar (FDA Federal Register postings, openFDA, ClinicalTrials.gov v2). Medium for PDUFA dates specifically (FDA does not always pre-announce PDUFA dates publicly — sponsor 10-Q/10-K disclosure is the canonical source).
- **Free/public sources:**
  - FDA Advisory Committee Calendar HTML page `https://www.fda.gov/advisory-committees/advisory-committee-calendar` — scraped daily; FDA must announce ≥15 days in Federal Register so this is sufficient.
  - openFDA Drugs@FDA endpoint: `https://api.fda.gov/drug/drugsfda.json?search=...` — 240 req/min, no key.
  - ClinicalTrials.gov v2 API: `https://clinicaltrials.gov/api/v2/studies?query.cond=...&filter.overallStatus=COMPLETED` — for primary completion dates as a proxy for upcoming readouts. ~10 req/sec.
  - SEC EDGAR 10-Q/10-K full-text search for "PDUFA" mentions — backfill for sponsor-disclosed dates.
- **Latency:** Daily for the calendar; event-driven for AdCom briefing-doc posts.
- **Failure mode:** PDUFA dates routinely slip (extension to the review cycle, mid-cycle communications, RTF refusal-to-file). Calendar staleness is the #1 problem. Mitigation: never trigger an *alert* off the date; only use it to *contextualize* other signals. Also: AdCom briefing docs sometimes appear at unpredictable hours — race condition with social-media leakage.
- **Measurement methodology:** Construct ground-truth set from past 24 months of FDA approvals/CRLs (openFDA Drugs@FDA approval-date deltas vs sponsor 10-Q-disclosed PDUFA dates). Measure (a) tag-coverage (how many tickers got tagged ahead of the event) and (b) precision delta on cross-confirmed signals during T-30 to T-0 window.
- **Alert-text contribution:** "PDUFA decision expected within 12 trading days for [drug name] (per 10-Q disclosure 2026-02-14)" or "AdCom briefing docs publish in ~2 sessions."
- **Implementation effort:** Medium. ~3 days for calendar harvester + sponsor→ticker mapper + AdCom polarity feature. ClinicalTrials.gov v2 integration may be deferred to C12.

---

### C4. Macro-Print Window Suppressor

- **Function:** Treat the 30-min window before and 30-min after CPI / PCE / NFP / GDP releases (and the 14:00 ET ± 60-min window on FOMC days) as *signal suppression zones* for everything except explicit macro-themed alerts. Most retail-relevant single-name signals fired inside these windows are noise from beta-driven sweeps, not idiosyncratic information.
- **Rationale + edge:** Single-name signals during macro shocks have low precision because correlations spike to ~1. A 5% move in NVDA at 8:31 ET on NFP day is ~0% information about NVDA and ~100% about the dollar/yields. Suppressing during these windows is a *precision* improvement (fewer false positives) at the cost of small *coverage* loss. Measurable lift: false-positive rate inside vs outside window on prior 6 months of alerts.
- **Source category:** High (BLS, BEA, Fed press-release schedules — all canonical).
- **Free/public sources:**
  - BLS schedule page: `https://www.bls.gov/schedule/news_release/` (CPI, PPI, Employment Situation a.k.a. NFP, JOLTS).
  - BLS API v2 (registered, 500 queries/day): `https://api.bls.gov/publicAPI/v2/timeseries/data/`.
  - BEA press-release schedule: `https://www.bea.gov/news/schedule` (PCE, GDP).
  - FOMC calendar: `https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm` (RSS subscribe option exists).
  - FRED for the actual prints with vintages: `fredapi` Python wrapper, free key from `https://fredaccount.stlouisfed.org/apikeys`.
- **Latency:** Scheduled-release; the *suppression* is real-time (clock-driven, not data-driven, so latency is irrelevant).
- **Failure mode:** Over-suppression in regimes where macro is the dominant driver (you mute legit ideas). Mitigation: keep the window short (30+30 not 120+120), and exempt explicitly macro-tagged signals.
- **Measurement methodology:** Replay 6 months of alerts; bucket by `time_to_next_macro_print` and `time_since_last_macro_print`. Compute false-positive-rate and 1-day-realized-return-correlation-to-SPY per bucket. Justify suppression windows where FPR rises ≥1.5× baseline.
- **Alert-text contribution:** None (suppressed alerts are simply not sent; logged for review).
- **Implementation effort:** Low. ~1 day. Schedule loader + clock-based gate.

---

### C5. Macro Surprise → Sector Bias Vector

- **Function:** Within ~15 min of a CPI/NFP/PCE/GDP release, compute `surprise = actual - consensus`, then publish a *sector-bias vector* (e.g., hot CPI → financials +, rate-sensitive REITs −, high-multiple tech −) that biases scoring of any ticker by sector for the next ~4 trading hours. Not an alert by itself — it's a multiplier on existing signals.
- **Rationale + edge:** Asymmetric S&P reactions to CPI surprises in high-inflation regimes are documented (e.g., 2026 *Applied Economics Letters* event-study showing CARs > 1% on cool surprises with significantly larger magnitudes than hot-side). Banks reliably outperform broader market on hot CPI by ~14.5 bp per 1σ surprise. We don't trade the macro print directly — we use the surprise as a *contextual prior* for everything else. Measurable lift: precision of single-name signals fired in the 4-hour post-print window when the sector-bias multiplier is consistent with the signal direction vs when it's opposite.
- **Source category:** High (BLS/BEA primary). Medium for consensus (free public consensus is harder; Investing.com / Trading Economics scraping or Finnhub free `economic-calendar`).
- **Free/public sources:**
  - Actuals: BLS API (CPI series CUUR0000SA0, employment LNS14000000), BEA NIPA tables, FRED for everything else.
  - Consensus estimates: Finnhub free `/calendar/economic` (rate-limited, but adequate); Trading Economics public widget; investing.com calendar (scraped). Document the cleanest provider; have a fallback chain.
- **Latency:** Real-time on actuals (8:30 ET releases); seconds-latency on consensus comparison.
- **Failure mode:** Consensus-estimate aggregators disagree (Reuters consensus ≠ Bloomberg consensus ≠ Finnhub aggregated). Use one canonical source, document it, and accept the noise. Second failure: regime shifts — the high-inflation asymmetry of 2021–2025 will not necessarily hold in disinflationary regimes. Mitigation: store the bias vector as a *learned* mapping the calibrator can update, not a hardcoded constant.
- **Measurement methodology:** Build sector-bias vector from regression of XLF/XLK/XLE/XLU/XLP/XLY/XLI/XLV/XLB/XLRE/XLC 1-hour-post-release returns on sign-and-magnitude of CPI/NFP/PCE/GDP surprises across last 24 months. Validate with hold-out window. Recompute quarterly.
- **Alert-text contribution:** "Macro context: hot CPI surprise +0.2pp; financials biased +, long-duration tech biased −" prepended to alerts in the post-print window.
- **Implementation effort:** Medium. ~3 days. Surprise-computation harness + sector-bias regression + multiplier integration into scoring.

---

### C6. FOMC Statement / Press-Conference Polarity Score

- **Function:** Within minutes of the 14:00 ET FOMC statement and again after the 14:30 ET press conference, score the statement language on a hawk/dove axis (LLM scorer), publish the score, and bias every rate-sensitive signal (banks, REITs, homebuilders, high-duration tech) for the next 24 hours.
- **Rationale + edge:** Press-conference language is at least as market-moving as the statement itself (FRBSF working paper 2025-30; NBER Digest Sep 2018). Most retail tools key off the *headline rate change* (already priced); the durable edge is in *language drift* between consecutive statements (insertions of "patience," removals of "any," changes to "balance of risks"). On dot-plot meetings (Mar/Jun/Sep/Dec) we additionally compute median dot vs market-implied path delta. Measurable lift: directional precision of rate-sensitive single-name signals fired in T+1 to T+3 windows post-FOMC.
- **Source category:** High (Fed primary).
- **Free/public sources:**
  - Statement: `https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm` plus the dated press-release URLs (e.g., `fomcpresconf20260318.htm`). RSS feed available on the calendar page.
  - SEP / dot-plot PDFs: `https://www.federalreserve.gov/monetarypolicy/files/fomcprojtabl{YYYYMMDD}.pdf`.
  - Minutes: released ~3 weeks after each meeting; same RSS feed.
  - Market-implied rate path: CME FedWatch tool (HTML-scraped) or compute from SOFR futures via FRED.
- **Latency:** Event-driven, ~minutes from statement; ~30–60 min after press conf for full transcript.
- **Failure mode:** Markets react during the press conf in real time, so by the time we have the full transcript the move has often happened. Counter: the *durable* effect (T+1 to T+3) is what we care about, not the 30-second reaction. Second failure: language scoring is noisy on small statement changes — false hawkishness flags. Mitigation: only score *deltas* vs prior statement, not absolute scores.
- **Measurement methodology:** Score every FOMC statement since Jan 2022 on hawk/dove axis using diff-vs-prior approach. Regress sector returns (XLF, XLK, XLU, XLRE, XLI) at T+1, T+3, T+5 against statement-delta score and dot-plot-vs-implied-path delta. Document R² and per-sector beta.
- **Alert-text contribution:** "FOMC statement net-hawkish vs prior (delta +0.4); rate-sensitive longs face headwind for next 3 sessions" embedded in scoring rationale.
- **Implementation effort:** Medium. ~2–4 days. Statement diff-and-score logic + LLM-based language scorer + dot-plot PDF parser.

---

### C7. Insider-Cluster Cross-Confirmation (Form 4)

- **Function:** Ingest Form 4 filings continuously from EDGAR. When ≥3 distinct insiders (CEO/CFO/director-level) at the same issuer execute *open-market purchases* totaling > $25k each within a rolling 10-day window, mark the ticker as "insider cluster active" for the next 30 days. This *adds +15 to score* per existing CLAUDE.md rule, but also unlocks a new condition: an otherwise-marginal social/technical signal on a cluster-active ticker passes the alert threshold.
- **Rationale + edge:** Insider-cluster detection has documented 6-month alpha of ~5.2% in academic and practitioner work (MarketTriage, Polo-Chau insider trading study, OpenInsider data). The signal is much stronger than single-insider buys and has *historically* been a precision filter for medium-horizon ideas. The novel use here is as a *secondary threshold relaxer*, not a primary signal — consistent with "Form 4 stored for cross-ref, +15 to scoring" in CLAUDE.md. Measurable lift: precision delta on tier-2 signals when cross-confirmed by an active cluster vs not.
- **Source category:** High (SEC EDGAR primary).
- **Free/public sources:**
  - SEC EDGAR full-feed RSS: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&output=atom`.
  - Per-CIK submissions: `https://data.sec.gov/submissions/CIK{cik}.json`.
  - OpenInsider as a secondary cross-check (`http://openinsider.com/`) — note it's scraped, treat as soft validation.
- **Latency:** Event-driven within ~1 hour of Form 4 filing (insiders have 2 business days to file; the tape effect is largely on day-1 of disclosure).
- **Failure mode:** 10b5-1 plan transactions look like fresh purchases but aren't (planned in advance). Form 4 has a checkbox for 10b5-1 — must filter on that. Second: forced exercises of options at-the-money are not directional signals. Filter on transaction code (P = open-market purchase, not A = grant or M = option-exercise).
- **Measurement methodology:** Identify cluster events on past 24 months (≥3 unique insiders, P-code, non-10b5-1, ≥$25k each, 10-day rolling window). Compute T+1, T+5, T+30 returns vs sector ETF benchmark. Independently compute precision of *tier-2* alerts cross-confirmed by an active cluster vs not.
- **Alert-text contribution:** "Three insiders (CEO + 2 directors) bought $230k open-market in the last 7 sessions" in alert body.
- **Implementation effort:** Medium. ~2–3 days. Form 4 RSS poller + transaction-code filter + cluster window state.

---

### C8. Russell / S&P Index-Inclusion Anticipation Window

- **Function:** Maintain the Russell US Indexes reconstitution calendar (now semi-annual from 2026: June and December). On preliminary-list publication days (May 22, May 29, Jun 5, Jun 12, Jun 18 in 2026; and the December cycle), tag affected tickers with `russell_addition_pending` or `russell_deletion_pending` from prelim publication through Lock-Down (Jun 8) and Reconstitution Day (Jun 29). Bias scoring on affected tickers during the addition-anticipation phase.
- **Rationale + edge:** Index-inclusion alpha is heavily arb'd by professionals, but the *timing window* of the preliminary-list announcements is asymmetric for retail-oriented bots: small/microcap additions to Russell 2000 still see meaningful flow demand. Critically, the 2026 shift to semi-annual reconstitution doubles the events per year and is *new* (most strategies are calibrated to annual). The edge is in catching small-cap additions early in the prelim window. Measurable lift: directional precision T-7 through T-0 on Russell-2000 additions vs deletions (paired comparison).
- **Source category:** High (FTSE Russell primary).
- **Free/public sources:**
  - FTSE Russell announcement page: `https://www.lseg.com/en/ftse-russell/russell-reconstitution`.
  - Index-notice download endpoints (research.ftserussell.com).
  - For S&P 500 changes: S&P Dow Jones Indices press releases (no clean API; HTML scrape weekly).
- **Latency:** Event-driven on the prelim list days (after 6pm ET); daily polling in the lock-down window.
- **Failure mode:** Moves are often pre-positioned by the Friday-after-Rank-Day list — by Monday open, much of the alpha is gone. The bot needs to catch the after-hours print on prelim-publication day. Second: list revisions across the four publication weeks introduce churn (a ticker gets added, removed in the next revision). Mitigation: only act on ticker-state *transitions*, not list-membership snapshots.
- **Measurement methodology:** Construct ground-truth from 2024 + 2025 Russell prelim-list publications (one-shot, since semi-annual is new for 2026). For each addition/deletion, measure CAR from prelim-publication T+0 close to reconstitution T+0 close. Validate that small-cap additions have positive CAR and deletions have negative CAR before committing to the feature.
- **Alert-text contribution:** "Russell 2000 preliminary addition (5/22 list); rebalance window through 6/29" — usable as standalone alert in this rare case (instant-trigger exception, given small-cap discoverability).
- **Implementation effort:** Low-medium. ~1–2 days. List-diff harvester + transition state machine.

---

### C9. Buyback / Tender / Spin-off Announcement (8-K Item 8.01) → Thesis Generator

- **Function:** Continuously parse 8-K Item 8.01 ("Other Events") and Item 7.01 ("Reg FD Disclosure") for material capital-allocation announcements: open-market buyback authorizations, accelerated share repurchase agreements (ASRs), tender offers, special dividends, spin-off announcements. Feed parsed event into the LLM thesis generator (per CLAUDE.md: "All SEC data feeds LLM thesis generation only"). Never instant-alert.
- **Rationale + edge:** Buyback-announcement abnormal returns are well-documented (TwoSigma white paper; Manconi/Peyer/Vermaelen ECGI 2018). Short-term announcement-day CARs are statistically significant; longer-term effects are mixed. We use these as *thesis confirmers* attached to other-engine signals. ASRs in particular signal management's belief that current price is below intrinsic value. Spin-off announcements have the strongest event-day move and frequently set up multi-week drift. Measurable lift: precision and lead-time on cross-confirmed alerts where a recent (≤30 day) buyback/spin announcement exists for the ticker.
- **Source category:** High (SEC EDGAR EFTS).
- **Free/public sources:**
  - SEC EFTS full-text search filtered to forms 8-K, item 8.01: `https://efts.sec.gov/LATEST/search-index?forms=8-K&q=%22share+repurchase%22`. Same 10 req/sec, User-Agent required.
  - Live filing feed RSS: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent`.
- **Latency:** Event-driven within minutes of 8-K filing.
- **Failure mode:** Authorizations ≠ executions. A "$10B repurchase authorization" can sit unused for years. Tender offers and ASRs are the highest-confidence subset because they imply near-term execution; rank them above generic open-market authorizations.
- **Measurement methodology:** Backtest event-day and T+5 returns from past 18 months of 8-K Item 8.01 buyback / ASR / tender / spin-off filings (segmented by category). Compare each category's CAR distribution to baseline; rank categories by stat-significance and use rank to weight thesis input.
- **Alert-text contribution:** Embedded in LLM thesis as catalyst-side evidence. Example seed: "$2B accelerated share repurchase announced 2026-04-22; ASR ≠ open-market authorization (implies near-term execution)."
- **Implementation effort:** Medium. ~3 days. Builds on the same 8-K parser as C2; categorize by item code + keyword.

---

### C10. M&A-Tape Cross-Confirmation (sector-cluster pattern)

- **Function:** Keep a rolling 60-day count of announced acquisitions per sector (especially small/mid-cap biotech, software, oil & gas E&P). When sector M&A frequency exceeds a sector-specific threshold (e.g., ≥3 small-cap biotech buyouts in 30 days), publish a `sector_ma_active` flag. Tickers in those sectors that are cheap on multiples or have public takeout-target chatter get a probability bump on existing signals.
- **Rationale + edge:** Biotech takeover premiums average 87.5% post-2020 vs 41.7% market-wide (industry deal databases). M&A clustering within sub-sectors is a documented pattern (driven by big-pharma patent cliffs, energy oil-price regimes, etc.). The bot doesn't predict *which* small-cap is next; it amplifies signals on candidates that already match the typical-target profile (small-cap, profitable franchise, single asset late-stage in biotech) when the sector is in a deal-making mode. Measurable lift: precision of small-cap signals during sector-M&A-active windows vs quiet windows.
- **Source category:** High (SEC EDGAR for the actual deal announcements via 8-K Item 1.01 / SC TO-T / 425). Medium for sector-tagging (free SIC/NAICS codes from EDGAR).
- **Free/public sources:**
  - SEC EFTS for SC TO-T (tender offer) and 8-K Item 1.01 (Entry into Material Definitive Agreement) filings.
  - SEC company-facts JSON for SIC codes: `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json`.
- **Latency:** Event-driven on individual deal filings; the *sector-aggregate* signal updates daily.
- **Failure mode:** "Buyout speculation" rumors that don't materialize (Twitter pump scenarios). The mitigation here is that this feature *amplifies* other signals rather than firing alone — and the sector-cluster logic is an aggregate count, not a single-rumor trigger. Second: false-positive sectors due to one outlier mega-deal skewing the count. Use median deal size, not mean.
- **Measurement methodology:** Quantify "deal-frequency regime" per sector by SIC code on rolling 60-day windows from past 36 months. Compute precision of small-cap signals during top-quartile deal-frequency windows vs bottom-quartile, controlled for market regime. Threshold tuned at ≥3 sub-sector deals/30 days.
- **Alert-text contribution:** "Sector M&A active: 4 small-cap biotech buyouts in last 30 days at avg 78% premium" appended to the alert when active.
- **Implementation effort:** Medium. ~3 days. SIC-tagged deal counter + state machine. Reuses the EFTS pipeline.

---

### C11. OpEx-Week / Quad-Witching Volatility Profile

- **Function:** On the third Friday of each month (OpEx) and especially on the four quarterly quad-witching days (3rd Fri of Mar/Jun/Sep/Dec), compute the *current* dealer gamma exposure profile from CBOE EOD options data (1-day delayed) and yfinance live options chains for the largest names (SPY/QQQ/AAPL/NVDA/TSLA). Publish: (a) gamma-flip price level for index, (b) per-ticker net dealer gamma, (c) days-to-expiry-weighted exposure. Bias single-name signals during OpEx week — high positive gamma → expect compression, low/negative gamma → expect amplification.
- **Rationale + edge:** Dealer-gamma dynamics around OpEx are well-documented in retail/quant literature (SpotGamma, GEX-Metrix, FlashAlpha). The free-tier latency (15-min CBOE delay; yfinance chains updated every few minutes) is *not* sufficient for intraday gamma trading, but is sufficient for *positioning bias* on overnight/multi-day signals: "this signal fires on a high-gamma day, expect mean-reversion; on a low-gamma day, expect continuation." Measurable lift: directional precision of T+1 to T+3 returns on signals fired during high-positive-gamma vs negative-gamma OpEx weeks.
- **Source category:** Medium (CBOE delayed EOD; yfinance unofficial chain). The signal quality is honestly capped by the latency.
- **Free/public sources:**
  - yfinance: `yf.Ticker("SPY").option_chain(expiry)` returns calls and puts.
  - CBOE delayed quotes: `https://www.cboe.com/delayed_quotes/`.
  - GEX-Metrix free SPX dashboard demo `https://www.gexmetrix.com/demo` (read-only, but illustrates the calculation methodology — implement our own from yfinance).
  - `Matteo-Ferrara/gex-tracker` GitHub reference implementation.
- **Latency:** Daily (EOD CBOE) is the realistic floor; intraday yfinance refreshes every few minutes but is rate-limited.
- **Failure mode:** Free options data is delayed and noisy. We *will not* be competitive with paid GEX providers (SpotGamma, SqueezeMetrics) on intraday turning points. Frame the feature honestly as "weekly-horizon positioning context," not "intraday gamma-flip alert." Second: assumption that all market-maker inventory is mechanically delta-hedged is a simplification — real flow has discretionary overrides.
- **Measurement methodology:** Compute SPY net dealer gamma EOD for the past 12 OpEx weeks. Bucket into positive vs negative. Compare T+1 to T+3 returns of single-name signals fired during each bucket against benchmark. Accept the feature only if directional precision delta exceeds 5pp and is not driven by one outlier week.
- **Alert-text contribution:** "OpEx context: net dealer gamma negative; expect amplified moves through Friday close" prepended during OpEx weeks.
- **Implementation effort:** High. ~5–7 days. Options-chain harvester (rate-limit-safe), gamma calc, daily EOD pipeline. Highest-cost feature; pre-cleared for cut by synthesis if budget tight.

---

### C12. ClinicalTrials.gov "Primary Completion Imminent" Watcher (small-cap biotech)

- **Function:** Daily-poll ClinicalTrials.gov v2 for studies whose `primaryCompletionDate` falls in the next 30 days, where the sponsor is a public small/mid-cap biotech (cross-ref against `data.sec.gov` company-facts SIC ~2836). Tag affected tickers with `near_term_readout_in_days`. Cross-confirm any social/technical signal on those tickers with elevated weight; do *not* alert on calendar entry alone.
- **Rationale + edge:** Sponsor 8-K disclosure of trial readouts is reactive — by the time the 8-K hits, the readout has happened and the move is largely done. The *anticipation* window (T-30 to T-1) is when retail social chatter and bullish/bearish technical setups appear, and this is exactly when a calendar-driven cross-check makes the difference between alerting and not. Most retail bots ignore this dataset entirely. Measurable lift: coverage delta — how many small-cap biotech ideas does this surface that we currently miss? And precision delta on signals cross-confirmed by an upcoming readout.
- **Source category:** High (ClinicalTrials.gov is the canonical primary source).
- **Free/public sources:**
  - ClinicalTrials.gov v2 API: `https://clinicaltrials.gov/api/v2/studies?query.lead=...&fields=NCTId,LeadSponsorName,PrimaryCompletionDate,Phase,OverallStatus`. ~10 req/sec, no key.
  - Cross-ref sponsor → ticker via SEC EDGAR company-search (`https://efts.sec.gov/LATEST/search-index?q={sponsor_name}&forms=10-K`).
- **Latency:** Daily.
- **Failure mode:** "Primary completion date" is the date the last patient completes the protocol, NOT the date the data is read out — readout typically lags by 3–6 months. Mitigation: this tag should *broaden* the cross-ref window (T-180 from completion is more realistic than T-30); document the lag explicitly. Second: sponsor-to-ticker mapping for small private-subsidiary trials is messy (a parent ticker may not appear as the sponsor name).
- **Measurement methodology:** Pull all small/mid-cap biotech tickers (SEC SIC 2836, mkt-cap < $5B). For trials whose `primaryCompletionDate` falls in 2025-Q1..2025-Q4, identify when the sponsor's first 8-K disclosing readout outcome occurred, and the resulting price move. Validate that adding the cross-ref tag in the T-180 window improves precision of social/technical signals on these names.
- **Alert-text contribution:** "Phase 3 trial primary completion 2026-06-12 per ClinicalTrials.gov NCT0xxxxxx; readout typically 3–6 months later" in alert body.
- **Implementation effort:** Medium-high. ~4 days. CT.gov v2 client + sponsor→ticker fuzzy mapping + biotech-only filter. Map quality is the bottleneck.

---

## Priority + cost summary

| ID  | Feature                                       | Coverage gain | Edge confidence | Effort   | Standalone-alert eligible? |
| --- | --------------------------------------------- | ------------- | --------------- | -------- | -------------------------- |
| C1  | Earnings-Window Risk Gate                     | High          | High            | Low      | No (gate / contextualizer) |
| C2  | Earnings Surprise Decomp                      | Medium        | Medium-high     | Med-high | No (LLM thesis only)       |
| C3  | PDUFA / AdCom Proximity                       | Medium        | Medium-high     | Medium   | No (contextualizer)        |
| C4  | Macro-Print Suppressor                        | Negative*     | High            | Low      | No (suppressor)            |
| C5  | Macro Surprise → Sector Bias                  | Medium        | Medium          | Medium   | No (multiplier)            |
| C6  | FOMC Polarity Score                           | Low-medium    | Medium          | Medium   | No (multiplier)            |
| C7  | Insider-Cluster Cross-Confirmation            | Medium        | High             | Medium   | Edge: yes if magnitude large |
| C8  | Russell Index-Inclusion Window                | Low-medium    | Medium-high     | Low-med  | Yes (instant-trigger exception, small-cap discoverability) |
| C9  | Buyback / Tender / Spin-off → Thesis          | Medium        | Medium          | Medium   | No (LLM thesis only)       |
| C10 | M&A-Tape Cross-Confirmation                   | Medium        | Medium          | Medium   | No (multiplier)            |
| C11 | OpEx Gamma Profile                            | Low           | Low-medium      | High     | No (multiplier)            |
| C12 | ClinicalTrials.gov Imminent-Readout Watcher   | High (small-cap biotech segment) | Medium | Med-high | No (cross-ref) |

*C4 is intentionally a precision-improving filter; coverage decreases by design.

Recommended cut-priority for synthesis if engineering budget is constrained: C11 first (highest cost, weakest free-data quality), then C6 (high effort relative to small-cap idea-bot's actual rate-sensitive exposure).

Recommended build-first set if budget is tight: C1, C4, C7, C8, C12 — these are the four highest-leverage features per engineering hour and span the calendar/insider/index/biotech axes. C2 and C9 are coupled via the shared 8-K parser and should be evaluated as a pair.

---

## Cross-engine integration notes (for synthesis)

- C1 (Earnings-Window Risk Gate) and C3 (PDUFA Proximity) are essentially *the same kind of feature*: a calendar-driven contextualizer that modifies scoring on signals from other engines. They should share infrastructure (a unified "upcoming catalyst resolver" service that returns a list of tagged catalysts per ticker).
- C2 (Earnings Surprise Decomp) and C9 (8-K Item 8.01) share the SEC EDGAR EFTS pipeline and 8-K parser. Build once, score multiple event types.
- C4 (Macro-Print Suppressor), C5 (Sector Bias), C6 (FOMC Polarity) form a single "macro context" subsystem with shared schedule infrastructure.
- C7 (Insider Cluster) already has a ground rule (+15 score) — confirm with synthesis whether the threshold-relaxer dimension is novel or already implicit.
- C11 (OpEx) and C12 (ClinicalTrials.gov) are the most *novel* relative to typical retail-bot architectures and should be evaluated for coverage gain specifically.
- All features are framed to satisfy the 2+ independent-source rule by definition — they amplify or contextualize existing primary signals (tweets, technicals, options flow). The exception is C7 cluster + C8 Russell prelim publication, which on edge can be standalone if the magnitude is large enough; mark those clearly in the synthesis.

---

## Open questions for synthesis

1. Is a unified "calendar resolver" service (C1 + C3 + C8 + C12) already planned? If so, this work folds into that.
2. Is there appetite for a paid economic-consensus feed, or do we hard-commit to free Finnhub-tier consensus?
3. Does the LLM thesis generator already accept arbitrary structured event payloads (for C2 and C9), or do we need to extend its schema?
4. The OpEx feature (C11) is honestly the lowest-confidence and most labor-intensive of the twelve. Synthesis should consider cutting it if engineering bandwidth is constrained.

---

## Risk register

- **R1 — Free-data fragility.** Yahoo and Nasdaq earnings calendars are unofficial endpoints. Layer redundancy (yfinance + Nasdaq + SEC 8-K backfill) so any one source going dark degrades but does not kill the gate.
- **R2 — Calendar staleness.** PDUFA, AdCom, and trial-readout dates slip frequently. Always carry a "last refresh" timestamp on each calendar entry; expire entries older than 7 days; never alert off the calendar in isolation.
- **R3 — Regime-shift on macro mappings.** Sector-bias regressions (C5) and FOMC polarity weights (C6) are calibrated on the most recent regime. Recompute quarterly; flag the calibrator if hit-rate falls > 1σ below trailing baseline.
- **R4 — Parsing reliability.** 8-K parsing (C2, C9) is the largest engineering risk. Plan a confidence-score output channel; below threshold, fall through to "thesis-only, no scoring" mode.
- **R5 — Form 4 noise.** Without 10b5-1 filtering, cluster-detection precision craters. Filtering is not optional.
- **R6 — Sponsor→ticker mapping (C12).** Phase 3 trials by subsidiaries, partnerships, and CROs muddy ownership. Allow per-trial manual overrides.
- **R7 — Compliance / ToS.** None of the listed sources require login/scraping behind walls; we stick to their published HTTP interfaces and respect User-Agent + rate-limit conventions per SEC, openFDA, BLS, FRED, and ClinicalTrials.gov terms.

---

## Implementation sequencing recommendation (advisory only)

1. **Week 1–2:** Build shared infrastructure — calendar resolver service, 8-K EFTS parser harness, FRED/BLS schedule loader. These power C1, C2, C3, C4, C7, C9, C12 simultaneously. Without this, every feature reinvents data plumbing.
2. **Week 3:** Ship C1 (earnings gate) and C4 (macro suppressor) — both are low-effort precision-improvers and validate the infrastructure under load.
3. **Week 4:** Ship C7 (insider cluster) and C12 (CT.gov readout watcher). Both leverage the calendar resolver.
4. **Week 5:** Ship C8 (Russell window) ahead of the May 22 prelim publication — this gives one full Russell cycle of empirical data.
5. **Week 6+:** Evaluate C2/C9 (8-K parsing pair), C3/C5/C6/C10 based on Week 1–5 telemetry. Defer or cut C11 unless OpEx weeks show clear unmet need in the live alert mix.

---

## Excluded (and why)

- **Whisper-number scraping (EarningsWhispers).** Site is gated behind a free *account* and prone to scraping fragility. Bullish/Bears review confirms much of the value is paywalled. Even when accessible, recent academic work (ScienceDirect 2010 study; bullishbears.com 2026 review) shows whisper-vs-consensus accuracy delta has narrowed. Marginal coverage gain not worth ToS risk.
- **Standalone 8-K instant alerts.** Explicitly forbidden by `CLAUDE.md`. We use 8-K only as thesis input (features C2, C9). No exception.
- **Form 4 instant alerts.** Project rule already specifies "+15 to scoring" — no separate alert. Feature C7 respects this.
- **Paid PDUFA/AdCom aggregator subscriptions** (BiopharmaWatch paid tier, BPIQ paid, BioPharmCatalyst paid). Free tiers are sufficient when combined with FDA Federal Register and openFDA Drugs@FDA. Skipping the paid layer.
- **CME FedWatch as a primary source.** It's an HTML widget without a stable API; we'd be scraping. We can compute equivalent rate-path implied probabilities directly from SOFR futures via FRED (preferred). CME FedWatch only as a sanity-check display.
- **Earnings-revision momentum on consensus EPS.** Powerful signal in academic literature, but free public estimate-revision data (Refinitiv/IBES proxies) has gone increasingly paywalled. Yahoo's analyst page exposes some of this, but it's brittle scraping. Park this for a Phase-2 evaluation when budget for a paid feed (FMP / EODHD) is on the table.
- **Detailed central-bank-minutes language drift.** Discussed under C6, but the FOMC minutes (3-week-lagged) are usually a weaker market mover than the same-day statement + presser. Not a separate feature.
- **ECB / BoJ / BoE event windows.** Out of scope: this is a US-focused retail bot, and cross-currency signal handling adds complexity disproportionate to expected coverage. If we expand internationally, revisit.
- **Pre-FOMC drift trade.** NY Fed staff report SR512 documents a real ~50bp pre-FOMC drift, but it's an *index-level* phenomenon, not a single-name signal. Doesn't fit the bot's idea-level alert format.
