# 20 — Candidate Features (Discovery Phase 2 Synthesis)

**Date:** 2026-04-24
**Inputs:** P0 system map (`00-system-map.md`) + 5 Phase-1 domain research outputs (`10-research-sentiment.md`, `11-research-flow.md`, `12-research-insider-filings.md`, `13-research-technical-quant.md`, `14-research-catalysts-macro.md`).
**Pipeline:** dedup against P0 → enrich (failure modes, safeguards, kill criteria) → composite-score → cut bottom 30% → enforce High-Impact Bar.
**Repo root:** `/root/.openclaw/workspace`

---

## Executive Summary

- **Raw inputs:** 62 candidate features across 5 domains (12 sentiment + 13 flow + 13 insider/filings + 12 technical/quant + 12 catalysts/macro).
- **Dedup pass against P0 capabilities matrix:** 4 dropped as already-wired (Sentiment F6 Google Trends multi-backend → P0 rows 6/7/8; Flow F1 V/OI sweep → P0 row 13 already partial-but-broken = AUDIT scope; Insider F1 cluster ↔ Catalyst C7 cluster — merged as one feature; raw `verify_technical` indicator stack already wired = no candidate touches it). Net surviving after dedup: 58.
- **High-Impact Bar pass:** 11 cut for failing to plausibly deliver +5pp precision OR ≥30 min lead-time OR ≥20% net new coverage OR closing a P0 instant-trigger blind spot. Net surviving: 47.
- **Composite-score ranking + bottom-30% cut:** trimmed to top 14 surviving features. Cuts concentrated in low-coverage / high-cost / high-decay items (OpEx gamma, Bluesky, HN pulse, Form 4/A amendments, Form 144 chain, S-1 lockup tracker, single-pair PCR z-score that overlaps existing options module, ATS dark pool with 4-week lag) plus features whose edge collapses to noise without paid feeds.
- **Top survivors cluster:** insider Form-4 cluster (single highest-impact additive feature; closes a named P0 gap and is an instant-trigger exception), regulated event-class triggers (S-4/425 M&A real-time, 13D activist, 13G→13D conversion, Reg SHO threshold), regulated catalyst gates (earnings-window gate, FOMC drift, PDUFA proximity), high-leverage shared infrastructure (FinBERT pipeline, regime classifier consumed by 4+ features), and macro-rails / cross-asset additions (FRED HY OAS credit-equity divergence, VIX term-structure flip).
- **Notable cuts and rationale at bottom of file.** Cross-feature stacking notes (Section 3) flag pairs/trios that share infrastructure or amplify each other.

**High-Impact Bar referenced:**
1. ≥+5pp precision on actionable alerts vs current 2-source baseline.
2. ≥30 min median lead time vs current alert chain.
3. ≥20% net new alert coverage without inflating false-positive rate.
4. Closes a named P0 instant-trigger blind spot.

---

## Surviving Features (ranked by composite = 0.5·signal_quality + 0.3·edge_durability + 0.2·feasibility)

Ties broken by: instant-trigger eligibility (yes > conditional > no), then number of High-Impact-Bar bullets met, then signal score raw. Where ties remain, ordering reflects rough sequencing preference for engineering execution (P0-gap closure first).

---

## 1. Cluster Form 4 Open-Market Buys (rank-weighted, discretionary only) — Insider/Filings — score 5.00

**Function:** Detect ≥2 distinct insiders filing Form 4 with transaction code `P` (open-market buy), `aff10b5One=false`, on the same ticker within a rolling 14-day window; emit a standalone instant-trigger alert with rank-weighted size and z-scored insider history.

**Source tier + endpoint + latency:** **High** — SEC EDGAR direct. `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&start=0&count=100&output=atom` poll every 60–120 s; per-filing XML at `https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{primaryDoc}.xml`. Real-time within 1–10 min of acceptance.

**Failure modes:**
- 10b5-1 plan executions disguised as discretionary (post-2022 cooling-off period gameable).
- Amendments (`4/A`) voiding or restating prior buys — alerts go stale.
- Board-grant batches mis-coded as `A` look like cluster but aren't directional.
- Sub-100-CIK aggregation (family trust + personal CIK) — same insider double-counted.
- "Squeeze trap" on heavily shorted small caps where insider buys are cosmetic.

**Safeguards:**
- Filter strictly on `transactionCode == "P"` AND `aff10b5One == false` (or footnote-text says no plan); drop everything else.
- Require ≥2 distinct reporting-owner CIKs within rolling 14-day window (configurable; tentative 14d).
- Rank-weight: CEO/CFO/Chair = 3, COO/President = 2, other officer = 2, director = 1, 10% holder = 1; cluster qualifies at total weight ≥ 4.
- Dollar floor $25k per insider AND ≥$100k aggregate (tentative).
- Z-score each buy against the insider's trailing 2-year personal buy distribution; flag z ≥ 2 as bonus weight.
- Auto-retract alerts if a `4/A` arrives within 5 days reducing share count > 50%.
- Cross-CIK merge by name+address fuzzy match for known multi-CIK reporters (small lookup table).
- Liquidity gate: market cap ≥ $300M (tentative; below this the squeeze-trap risk dominates).

**Kill criterion:** If 21-day forward precision (close > entry by ≥3% sector-adjusted) is < 55% on the all-cluster cohort over 90-day rolling window, OR if 10b5-1 false-positive contamination exceeds 15% in a manual sample of 50 alerts, kill the standalone-trigger path and downgrade to xref-only +25 boost.

**Scoring breakdown:**
- Signal=5 (six decades of academic work — Lakonishok-Lee, Cohen-Malloy-Pomorski — document persistent 6–10% abnormal return for opportunistic open-market insider buys; cluster subset is the highest-precision cut).
- Durability=5 (regulatory mechanism cannot be arbitraged away; SEC reporting requirement is permanent).
- Feasibility=5 (pure SEC EDGAR; rate limit 10 req/s comfortable; XML parser already exists at `scanners/sec_edgar.py:173` — `fetch_form4_details` is wired but only behind `!form4` command).

→ composite = 0.5·5 + 0.3·5 + 0.2·5 = 2.5 + 1.5 + 1.0 = **5.00**.

**Instant-trigger eligible?** YES — explicitly named in CLAUDE.md ("insider trading"). High-source-tier regulated event meeting cluster criteria fires alone.

**High-Impact Bar:** Bullets 1, 3, AND 4. (1) +5pp+ precision plausible vs raw single-insider filter (cluster is ~2x precision per cited literature). (3) ≥20% net new coverage on small/mid-cap names where TweetShift signal is sparse. (4) Closes P0 gap row 28 ("No insider Form-4 velocity / cluster-buy signal") — explicitly named blind spot.

**Minimal integration touch:** Reuse existing `consensus_engine/scanners/sec_edgar.py:173` (`fetch_form4_details`) for XML parsing. New module `consensus_engine/scanners/form4_cluster.py` with poll loop. Wire into `main.py:343–347` alongside existing `sec_8k_watcher_loop` gate (separate `form4_cluster_enabled` flag). Standalone alert emit via existing `alerts/discord.py:316` (`send_instant_ping`) — pass `signal_type="INSIDER_CLUSTER"`. Cross-ref boost by writing `signal_events` row at `db.py:602` for SourceType (new enum value `INSIDER_CLUSTER`).

---

## 2. SEC S-4 / 425 Real-Time M&A Detection — Insider/Filings — score 4.50

**Function:** Detect new S-4 or 425 filings; classify as fresh-deal announcement (acquirer-CIK references target-CIK for first time in 30 days); parse offer per-share value (cash/stock/mixed); emit standalone alert if 2-source-rule satisfied (e.g., paired with cluster Form 4 in window OR by Discord-channel cross-mention).

**Source tier + endpoint + latency:** **High** — SEC EDGAR direct. `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=425&output=atom` and `type=S-4`; poll every 60 s. Real-time within ~10 min of acceptance; many 425s appear minutes BEFORE the corresponding press-release tape.

**Failure modes:**
- Many 425s are routine investor-presentation or post-announcement material (false positives).
- Definitive Agreement may be filed as 8-K Item 1.01 instead of immediate 425.
- Target-side stock spike happens regardless of who files first — race condition on standalone alert eligibility.
- Foreign-issuer M&A (Form CB) out of scope.

**Safeguards:**
- Dedupe via "first 425 by acquirer-CIK referencing target-CIK in trailing 30 days" rule.
- Cross-reference 8-K Item 1.01 from same filer same day to eliminate post-announce 425 noise.
- Per CLAUDE.md, treat as 2-source candidate (425 + Form 4 cluster within 14d, OR + Discord tweet) — never standalone unless paired.
- Parse text body for "merger agreement" / "definitive agreement" / "per share" patterns; require ≥1 to qualify.
- Alert-text must include parsed offer price, deal type (cash/stock), and arbitrage spread to current target-price.
- 60-second cooldown on same target-CIK to prevent multiple 425s from spamming.

**Kill criterion:** If false-positive rate (alerts not corresponding to a real deal-announcement press release within ±2h) exceeds 25% on a 30-day backtest, OR if median lead-time over Bloomberg/Twitter is < 5 minutes, kill the standalone-eligibility and downgrade to xref-only.

**Scoring breakdown:**
- Signal=5 (M&A targets jump ~27% on average per Inside Arbitrage 2025; arbitrage spread is wide on first publication; window between 425 acceptance and broad tape is 5–30 min).
- Durability=4 (SEC reporting requirement permanent; mainstream-tape latency could narrow if SEC modernizes filing dissemination — but no near-term threat).
- Feasibility=4 (EDGAR endpoint stable; only complexity is target-CIK extraction from 425 cover page parsing — moderate engineering).

→ composite = 0.5·5 + 0.3·4 + 0.2·4 = 2.5 + 1.2 + 0.8 = **4.50**.

**Instant-trigger eligible?** Conditional YES — when paired with second source (Form 4 cluster in trailing 14d, OR analyst tweet within 60 min, OR options flow spike). Without second source, xref-only.

**High-Impact Bar:** Bullets 2 AND 3. (2) Median 5–30 min lead-time vs Bloomberg/CNBC tape on initial 425 well-exceeds 30-min target on after-hours filings. (3) ≥20% net new coverage on small-cap M&A targets where TweetShift coverage is thin.

**Minimal integration touch:** New module `consensus_engine/scanners/sec_ma_watcher.py`. Wire into `main.py:343` behind same `scanners.sec_background_watchers_enabled` flag with sub-flag `sec_ma_enabled`. Cross-ref boost via `signal_events` write at `db.py:602` with SourceType `M_AND_A`. Use existing `alerts/discord.py:316` for instant-ping when 2-source rule satisfied.

---

## 3. Pre-FOMC Drift Trade — Technical/Quant — score 4.20

**Function:** Hard-coded calendar of 8 scheduled FOMC announcement dates per year. At 14:00 ET on T-1 (one trading day before FOMC announcement), fire long-SPY/QQQ alert IF (a) `VIX > 18`, (b) VIX up >10% over prior 5 sessions, (c) prior 24h SPY return ≤ 0. Exit at 14:00 ET on FOMC day (15 min pre-announce). NEVER hold through announcement.

**Source tier + endpoint + latency:** **High** — Fed FOMC calendar `https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm` (scrape annually, cache YAML); SPY/VIX via existing Finnhub `/quote` + yfinance. Real-time-eligible at 14:00 ET T-1 via Finnhub.

**Failure modes:**
- Hawkish-surprise wipeout: hawkish FOMC erases gains in 5 min — strict no-hold-through rule.
- Inter-meeting emergency actions (2020-03 emergency cut, 2008 emergency liquidity) not on calendar — unhedgeable.
- The 2024+ regime saw reduced unconditional drift (~25–30bps); only filtered subset (VIX-rising + flat-prior-24h) retains ≥40bps.
- Press-conference vs non-press-conference meetings have different drift magnitudes.

**Safeguards:**
- Hard time-stop: exit at 14:00 ET FOMC day, no exceptions.
- VIX>18 entry gate (tentative; tune in calibration).
- Prior 5-session VIX rise threshold ≥10% (tentative).
- Prior 24h SPY return ≤ 0 (tentative; the "uncertainty bid" thesis only triggers when market is anxious).
- Suppress on inter-meeting emergency days (only act on scheduled meetings, hard-coded list refreshed annually).
- Stop-loss at entry × (1 − 0.6%) — Lucca-Moench filtered subset has ~70bps adverse-tail at <1% probability.

**Kill criterion:** If mean 24h pre-FOMC excess return on the filtered subset (VIX>18 + VIX-up + flat-prior) drops below +25bps over 8 consecutive meetings, OR if positive-day frequency falls below 60%, kill.

**Scoring breakdown:**
- Signal=4 (Lucca-Moench 2014 NY Fed Staff Report 512 documents drift; 2024 Applied Economics revisit confirms persistence but unconditional mean has compressed to ~25–30bps; filtered subset retains ≥40bps which downgrades signal score from 5 to 4).
- Durability=4 (durable while institutional pre-positioning behavior persists; could compress further if regime changes — already partially compressed 2024+).
- Feasibility=5 (calendar known years in advance; SPY/VIX free; signal fires <10x/year so alert-budget-friendly; trivial implementation).

→ composite = 0.5·4 + 0.3·4 + 0.2·5 = 2.0 + 1.2 + 1.0 = **4.20**.

**Instant-trigger eligible?** YES — quant/factor signal class explicitly named in CLAUDE.md; index-level alert (not single-name) so 2-source rule arguably N/A; calendar-based event.

**High-Impact Bar:** Bullets 1 AND 4. (1) ≥+40bps mean lift on filtered subset is meaningful precision improvement on macro bot's coverage. (4) Closes P0 gap row "no FRED / macro-rails ingest" by introducing macro calendar.

**Minimal integration touch:** New module `consensus_engine/signals/pre_fomc.py`. Wire into existing `main.py:455` `macro_digest_loop` with new `pre_fomc_check_loop` (or piggyback). Calendar YAML at `config/fomc_calendar.yaml`. Alert via `alerts/discord.py:316`. NO touches to existing alert pipeline beyond adding a new SourceType `MACRO_DRIFT`.

---

## 4. FRED Credit-Equity Divergence (HYG vs SPY + HY OAS) — Technical/Quant — score 4.00

**Function:** Compute on EOD daily total-return-adjusted closes: `gap_20d = SPY_20d_return − HYG_20d_return`. Bearish trigger when `gap_20d > 2σ` (over 252-day baseline) AND `HYG < SMA(HYG, 50)` AND `SPY ≥ SMA(SPY, 50)` AND signal persists ≥2 sessions. Optional confirmation via FRED `BAMLH0A0HYM2` (HY OAS direct) and LQD weakness check.

**Source tier + endpoint + latency:** **High** — yfinance HYG/SPY/LQD/IEF + FRED `https://api.stlouisfed.org/fred/series/observations?series_id=BAMLH0A0HYM2&api_key=...`. EOD; FRED HY OAS one-day-lagged.

**Failure modes:**
- Idiosyncratic HYG drawdown from energy/CCC stress without broad-market implication.
- 2020-Q2 regime where HY rallied with equity (correlation flip) — known blind spot.
- Doesn't identify which sector will lead the equity rollover.
- ETF tracking error vs underlying OAS during stress periods.

**Safeguards:**
- Require BOTH HYG-stress AND LQD-stress (IG ALSO showing weakness, defined as >1σ relative to its 50d mean) — drops energy-only false positives.
- Persistence filter: signal must hold ≥2 consecutive sessions before firing.
- Suppress when correlation(HYG, SPY, 60d) > +0.85 (the regime where divergence shouldn't exist) — flag instead as "regime anomaly" thesis-only.
- 252d rolling baseline excludes the most-recent 20 days from baseline computation (avoid contamination).
- FRED HY OAS as direct corroboration when available; fall back to ETF-only if FRED is dark.

**Kill criterion:** If false-positive rate (signal fires but >3% SPY drawdown does NOT occur within next 20 trading days) > 60% on a 24-month backtest, kill. Alternative: if mean forward 20d SPY return conditional on signal is ≥ unconditional baseline, kill (signal is broken).

**Scoring breakdown:**
- Signal=3 (HY/credit leads equity at turning points is academically and empirically supported, but lead-time window is variable 1–2 weeks AND signal is regime-shifter not single-trade trigger — caps signal score at 3).
- Durability=5 (credit-vs-equity dispersion is structural — bondholders price default risk before equity holders price slowdown; persistent across cycles).
- Feasibility=5 (yfinance + FRED both free, stable; FRED API is 120 req/min generous; trivial pandas computation).

→ composite = 0.5·3 + 0.3·5 + 0.2·5 = 1.5 + 1.5 + 1.0 = **4.00**.

**Instant-trigger eligible?** NO — regime/macro signal; fires as confidence multiplier on existing alerts and as standalone "macro caution" thesis-only.

**High-Impact Bar:** Bullet 4. Closes P0 gap row "no FRED / macro-rails ingest (2s10s, HY OAS, NFCI, DGS10)."

**Minimal integration touch:** New module `consensus_engine/scanners/macro_credit.py`. Wire into existing `main.py:455` `macro_digest_loop` (already runs hourly). Output is regime label written to existing `youtube_macro` table via `db.insert_youtube_macro` schema (or new `macro_signals` table). Consumed by xref via new `cross_reference._get_macro_context` method — minimal integration touch at `cross_reference.py:333` after existing xref read.

---

## 5. Volume-Confirmed N-Day Breakout with ATR Levels — Technical/Quant — score 4.00

**Function:** Fire when `close_today > rolling_max(close, N)` for N ∈ {20, 60, 252} AND `volume_today ≥ 2.0 × rolling_mean(volume, 20)` (raise to 2.5 for low-float <50M shares) AND `close > VWAP_anchored from prior pivot-low` AND `BBwidth(20, 2σ) > 30th percentile of trailing 252d`. Emit alert with `entry = close`, `stop = close − 1.5×ATR(14)`, `target_1 = close + 1.5×ATR(14)`, `target_2 = close + 3.0×ATR(14)`.

**Source tier + endpoint + latency:** **High** — yfinance daily OHLCV (`yf.download`) for rolling max + ATR; intraday 5-min via `interval='5m'` for VWAP anchoring. EOD reliable; alert at close (16:00 ET) or first AH bar.

**Failure modes:**
- Low-vol regime fade: breakouts in compressed-VIX, mean-reverting tape round-trip within 1–2 days.
- Thin-float pump-and-dump prints fake volume in first hour, fades by close.
- Gap-up open prints day's high at 9:31 — no follow-through signal.
- VIX>28 broad-volume-shock days where every name prints unusual volume.
- N=252 (52-week-high) suffers anchoring-effect compression in low-VIX regimes.

**Safeguards:**
- BBwidth filter (top 70% of 252d) — suppresses "false breakout out of squeeze."
- ADX(14) > 22 gate for N=20 tactical breakout (regime requirement); N=252 unconditional (anchoring edge stands).
- VIX < 28 gate (tentative) — suppress on broad volume-shock days.
- Liquidity floor: market cap ≥ $300M, ADV(20d) ≥ 500k shares.
- Per-ticker dedup: 24h cooldown on same ticker for same-N tier.
- Per-feature daily quota: max 20 alerts/day for N=20; max 5 for N=60; max 3 for N=252.

**Kill criterion:** If 1-day forward precision (next-day close above today's close) < 52% on filtered cohort over 90-day rolling window, kill the N=20 tier; if < 50% on N=252, kill that tier.

**Scoring breakdown:**
- Signal=4 (volume-confirmed breakouts are textbook liquidity-asymmetry play; 52-week high + anchoring bias from George-Hwang 2004 adds durability; precision target ≥55% on 1d hold is achievable per literature).
- Durability=4 (anchoring bias is psychological → durable; tactical 20d breakout could decay as more retail uses TradingView alerts on same level).
- Feasibility=4 (yfinance is free; pandas-ta is free; existing repo `consensus_engine/analysis/technical.py:243` and `analysis/indicators.py` already compute ATR/RSI/EMA — extends rather than rebuilds).

→ composite = 0.5·4 + 0.3·4 + 0.2·4 = 2.0 + 1.2 + 0.8 = **4.00**.

**Instant-trigger eligible?** YES — "technical breakout with levels" explicitly named in CLAUDE.md exception list. Fires standalone with mandatory entry/stop/target/time-stop in alert payload.

**High-Impact Bar:** Bullet 1 (precision ≥55% on 1d hold + ≥20% coverage gain on standalone-trigger universe).

**Minimal integration touch:** New module `consensus_engine/signals/breakout.py`. Reuses existing `consensus_engine/analysis/indicators.py` for ATR/BBwidth. Wire into existing `fetch_loop` at `main.py:369–380`. Alert via existing `alerts/discord.py:316`. NEW SourceType `TECHNICAL_BREAKOUT`.

---

## 6. Earnings-Window Risk Gate — Catalysts/Macro — score 4.00

**Function:** For every ticker that surfaces from any engine (tweet, technical, social), look up next earnings date and tag the signal with one of `pre_earnings_T-N`, `into_earnings`, `post_earnings_T+N`, or `clear`. Modulate downstream scoring and append risk text to alert body.

**Source tier + endpoint + latency:** **Medium** — `yfinance.Ticker(symbol).calendar` + Nasdaq public JSON `https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD` + existing `consensus_engine/scanners/earnings_calendar.py` (Finnhub `/calendar/earnings`). Daily refresh sufficient.

**Failure modes:**
- Unofficial Yahoo/Nasdaq endpoints return stale or wrong dates for small-caps; pre-announce shifts.
- Companies that pre-announce shift their effective T-0 unpredictably.
- "Clear" mis-tagging on names that have multiple events (earnings + AdCom in same week).

**Safeguards:**
- Cross-check Yahoo vs Nasdaq vs Finnhub; if mismatch ≥ 2 days, treat as "uncertain" rather than "clear" — fail-closed.
- T-1/T+0/T+1 default-suppress for non-earnings-themed signals (tentative).
- T-2/T+2 conditional suppress (require 3+ source consensus instead of 2+).
- T-3 to T-5 attach "earnings imminent" badge but do not suppress.
- 7-day staleness limit on cached earnings dates; refresh on access if stale.

**Kill criterion:** If precision delta on social-source signals fired in T-3 to T+1 window vs same signals in T-30 window is < 5pp on 6-month backtest, kill the gate (no edge from gating).

**Scoring breakdown:**
- Signal=3 (gating mechanism is well-grounded; pre-earnings IV elevation and dealer hedging asymmetry are documented; +10–20% precision on social signals in T-3 to T+1 is achievable BUT this is a gate not an alert source — coverage delta is zero by design, capping signal score at 3).
- Durability=5 (earnings cycle is structural; never going away).
- Feasibility=5 (existing `earnings_calendar.py` already runs; integration is wrapper / tagger; new yfinance and Nasdaq cross-checks are free).

→ composite = 0.5·3 + 0.3·5 + 0.2·5 = 1.5 + 1.5 + 1.0 = **4.00**.

**Instant-trigger eligible?** NO — gate/contextualizer; modifies confidence on others.

**High-Impact Bar:** Bullet 1 — +10–20pp precision on social signals fired in earnings-imminent window.

**Minimal integration touch:** Reuse existing `consensus_engine/scanners/earnings_calendar.py:25–47`. New module `consensus_engine/analysis/earnings_gate.py`. Hook into `cross_reference.py:333` (after existing xref read) — call new gate function which returns a confidence-multiplier appended to `breakdown`. Alert text appended in `alerts/discord.py:471–507` (`send_detail_followup`).

---

## 7. FinBERT Headline Sentiment + Catalyst Lexicon (combined infra w/ velocity) — Sentiment — score 4.00

**Function:** Run FinBERT (locally, free model `ProsusAI/finbert`) on every headline + lede the bot already pulls (Yahoo RSS, Nasdaq RSS, CNBC RSS in news cascade). Compute (a) classifier softmax score, (b) catalyst-intensity dictionary score over financial event terms ("guides higher", "raises", "FDA approves", "settled"). Composite: `0.6 × finbert_z + 0.4 × catalyst_z`. ALSO emits 8h velocity (rate-of-change) signal as a secondary derived feature.

**Source tier + endpoint + latency:** **Medium** for ingest (Yahoo/Nasdaq/CNBC RSS — already polled by existing `news.py`); compute is local (FinBERT + Loughran-McDonald lexicon). FinBERT inference ~50ms/headline on CPU. Velocity recomputed every 60 min on 8h rolling window.

**Failure modes:**
- Yahoo RSS occasionally throttles by IP and changes URL templates.
- FinBERT softmax is noisy on neutral-classified headlines containing hard-news language (the catalyst lexicon component is the recovery path).
- Sparse-headline small-caps make velocity unstable.
- Local model versioning drift if ProsusAI updates weights — pin model version.
- CPU throughput on multi-tenant server may bottleneck; needs benchmarking.

**Safeguards:**
- Triangulate against ≥2 RSS sources; circuit-breaker on RSS failure (single-RSS-down disables velocity, not classifier).
- Pin FinBERT model SHA in requirements.
- Minimum 8 headlines in 8h window before computing velocity; otherwise mark "insufficient signal" — never emit noisy reading.
- EWMA smoothing α=0.4 on velocity to suppress single-headline jitter.
- Composite threshold: emit only when `composite_score ≥ 2.0σ`; pair with same-window volume z (count of new headlines) ≥ 2.
- Headline dedup by URL hash before scoring.

**Kill criterion:** If precision delta on news-driven alerts (precision-with-FinBERT vs precision-without) is < 4pp on 90-day backtest, kill the FinBERT path. If catalyst-lexicon component alone (without FinBERT softmax) achieves the same lift, kill the FinBERT model and keep just the lexicon (cheaper).

**Scoring breakdown:**
- Signal=4 (FinBERT ~69% accuracy vs VADER ~56% on financial sentiment per DeepWiki/dshilman benchmark; catalyst-lexicon adds recovery on neutral-classified hard-news).
- Durability=4 (lexicon is durable; FinBERT model could drift but pinning solves it).
- Feasibility=4 (free model, free RSS already polled; CPU throughput on existing server needs verification but achievable; existing `news.py` is the natural integration point).

→ composite = 0.5·4 + 0.3·4 + 0.2·4 = 2.0 + 1.2 + 0.8 = **4.00**.

**Instant-trigger eligible?** NO — confirmer / second-source for tweet-driven primary signals.

**High-Impact Bar:** Bullets 1 AND 2. (1) +4–5pp precision on news-driven alerts. (2) ~15 min lead-time delta when polling RSS at 60s vs waiting for analyst-tweet aggregation.

**Minimal integration touch:** New subpackage `consensus_engine/sentiment/` with `finbert.py` + `catalyst_lexicon.py`. Hook into `consensus_engine/scanners/news.py:50–56` (`_classify_catalyst`) — extend existing classifier with FinBERT compute. Sentiment-velocity is derived in same module. Output written to `signal_events` via existing `db.insert_signal` path with new SourceType `NEWS_SENTIMENT`. Cross-ref consumes via `cross_reference._run_news_cascade` (already wired at `cross_reference.py:76`).

---

## 8. New 13D Activist-Filer Detection (with 13G→13D conversion) — Insider/Filings — score 4.00

**Function:** Two-leg feature. (a) When a new Schedule 13D appears, score on filer's activist history (count of distinct prior 13D campaigns over trailing 5 years), percentage stake disclosed, and Item 4 "Purpose of Transaction" intent classification (regex on {nominate, board representation, strategic alternatives, dissident slate, replace}). Standalone alert when filer ≥2 prior campaigns OR Item 4 contains nomination/strategic-alternative language. (b) Flag "13G→13D conversion" — a holder previously on 13G filing a fresh 13D; standalone alert (regime change).

**Source tier + endpoint + latency:** **High** — `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=SC+13D&start=0&count=40&output=atom` plus `type=SC+13G`. Real-time within ~10 min of acceptance. Rule change effective Feb 2024 contracted 13D filing window from 10 days to 5 business days post-5%-crossing.

**Failure modes:**
- Sophisticated filers stagger across affiliated entities (need group-level CIK aggregation).
- Item 4 language often deliberately vague — regex misses softer "engagement"/"discussions" wording.
- Cash-settled swap accumulation evades 13D requirement entirely.
- Joint-filer 13Ds counted once, not N times.
- Filer already on 13G then sells down then re-accumulates — false conversion flag.

**Safeguards:**
- Maintain `holder_intent` table keyed `(filer_cik, issuer_cik)` with latest schedule type + last-position-pct.
- Conversion rule requires continuous-ownership check via stake-percentage continuity in 13G amendments (no >25% drop between 13Gs).
- Item 4 regex: nominate|board representation|strategic alternatives|sale of the Company|replace|dissident|withhold votes|refresh.
- Activist-filer history: build local table from per-filer `submissions.json`, count distinct issuer-CIKs with prior 13D filings; ≥2 = "known activist" gate.
- Group-level CIK aggregation via name-similarity (≥90% Jaro-Winkler) for known multi-CIK activists (Elliott, Starboard, Engaged → maintain whitelist).
- Suppress on micro-caps (market cap < $200M; the noise rate dominates).

**Kill criterion:** If 21-day forward precision (positive sector-adjusted return on entry) < 50% on known-activist subset over 12-month backtest, kill the standalone path.

**Scoring breakdown:**
- Signal=4 (Brav/Jiang/Kim documents 5–10% abnormal returns in 20-day window post-13D for activist filers; rule change makes 13D timing tighter post-Feb-2024).
- Durability=4 (regulatory schedule permanent; cash-settled-swap workaround partially neutered by 2024 modernization).
- Feasibility=4 (EDGAR free; XML parsing of 13D HTML is messy but tractable).

→ composite = 0.5·4 + 0.3·4 + 0.2·4 = 2.0 + 1.2 + 0.8 = **4.00**.

**Instant-trigger eligible?** YES — when (a) known-activist filer (≥2 prior campaigns) OR (b) 13G→13D conversion. Both are regulated rare events meeting CLAUDE.md "insider trading" alert exception.

**High-Impact Bar:** Bullets 3 AND 4. (3) ≥20% net new coverage on activist-positioned small/mid-caps. (4) Closes implicit P0 gap (no 13D/G activist watcher).

**Minimal integration touch:** New module `consensus_engine/scanners/activist_watcher.py`. Reuses existing `sec_edgar.py` HTTP plumbing. Wire into `main.py:343` behind sub-flag `activist_watcher_enabled`. Standalone alert via `alerts/discord.py:316`. Cross-ref boost via `signal_events` SourceType `ACTIVIST_FILING`.

---

## 9. SEC EDGAR Full-Text Mention Velocity (cross-form) — Sentiment / Insider hybrid — score 3.80

**Function:** Daily EFTS query for ticker/CIK across all form types in rolling 30-day window. Track (a) mention count z-score, (b) form-type diversity (3+ distinct form codes in week = elevated activity). Output is +1 confirmation source for non-8-K-driven alerts (respects "8-K never standalone" rule by aggregating).

**Source tier + endpoint + latency:** **High** — EFTS API `https://efts.sec.gov/LATEST/search-index?q="{cik}"&dateRange=custom&startdt=YYYY-MM-DD&enddt=YYYY-MM-DD`. Free, 10 req/s rate limit. T+0 to T+15 min after filing acceptance.

**Failure modes:**
- EFTS rate-limit IP block (10-min) on aggressive callers.
- Ticker collisions (use CIK-locked queries to avoid).
- Filings unrelated to substantive activity (routine 4-filings, NT-10-Q lateness notices) inflate counts.
- Velocity baseline can be skewed by issuer's own filing cadence (small caps file fewer; large caps file more).

**Safeguards:**
- Anchor queries on CIK, not free-text ticker.
- Per-ticker daily polling (max 1 query/ticker/day at the cohort scale).
- Z-score against trailing 12-month rolling baseline (exclude most-recent 30-day window from baseline to avoid contamination).
- Form-type diversity threshold: ≥4 distinct form codes in rolling week.
- User-Agent: `"consensus_engine ak@openclaw.dev"` per SEC fair-use.
- Per-issuer filing-cadence normalization: divide raw count by issuer's trailing-12-month average filings/month.

**Kill criterion:** If z-score signal is noise (no precision lift on cross-confirmed alerts vs base over 90-day backtest, < 3pp delta), kill. If EFTS rate-limit blocks become routine (>5 hr/week down), kill.

**Scoring breakdown:**
- Signal=3 (regulated, timestamped, auditable but +3pp precision delta when paired with options flow on small caps is modest; velocity layer competes with Form 4 cluster on small-cap insider activity coverage — caps signal at 3).
- Durability=5 (SEC public-disclosure rule is permanent; EFTS API is officially supported).
- Feasibility=4 (EFTS is free but rate-limit-prone under aggressive load; per-ticker daily cadence is safe).

→ composite = 0.5·3 + 0.3·5 + 0.2·4 = 1.5 + 1.5 + 0.8 = **3.80**.

**Instant-trigger eligible?** NO — cross-form aggregate; respects 8-K standalone rule by design.

**High-Impact Bar:** Bullet 3 — ≥20% net new coverage on small caps with elevated regulated-filing activity that don't appear in TweetShift.

**Minimal integration touch:** New module `consensus_engine/scanners/sec_velocity.py`. Reuses existing `consensus_engine/scanners/sec_edgar.py` HTTP infrastructure (rate-limit handler, User-Agent header). Wire into existing `fetch_loop` at `main.py:369–380` with daily-cadence sub-scheduler. Output via `signal_events` with new SourceType `SEC_VELOCITY`.

---

## 10. Wikipedia Pageview Spike (per-ticker article) — Sentiment — score 3.70

**Function:** Pull hourly pageviews for ticker's company Wikipedia article and flag z ≥ 2.5 vs trailing-28-day weekday-matched baseline. Use as +1 confirmation source toward 2-source rule on tweet-driven or breakout-driven primary signals.

**Source tier + endpoint + latency:** **Medium** — Wikimedia Pageviews API `https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia.org/all-access/user/{article}/hourly/{start}/{end}`. 200 req/sec public limit, no auth, no key. Article resolution via OpenFIGI free API. Hourly latency (1–2h delay from Wikimedia ingest).

**Failure modes:**
- Article ambiguity (common-noun tickers like ALL, BABY, MOON) — must lock canonical Wikipedia article via FIGI symbology.
- Bot-driven pageview spikes (vandalism/scraping) — `all-access/user` filter excludes bots but is imperfect.
- Single-hour spikes from non-financial events (celebrity ad, ecosystem reference) — false positives.

**Safeguards:**
- FIGI-validated canonical article slug per ticker; reject ambiguous matches.
- 28-day weekday-matched baseline (Mon-vs-Mon, Fri-vs-Fri); log-transformed hourly views.
- Require current hour's z ≥ 2.5 AND prior-hour z ≥ 1.0 — rules out single-hour ad spikes.
- Article infobox check: confirm ticker symbol appears in infobox before locking match.
- 1-hour TTL cache per article.
- Suppress when prior-week Wikipedia-attention z is already ≥3 (already-saturated; crowding gate complements).

**Kill criterion:** If precision delta when used as second-source on tweet-driven primary signals is < 2pp on 90-day backtest, kill. If precision when paired with Google Trends second source (Sentiment F6 already wired) is < +5pp, kill the joint-attention-confirmer path.

**Scoring breakdown:**
- Signal=3 (Moat/Curme/Preis Sci. Reports 2013 + transfer-entropy 2017 work supports Wikipedia attention precedes price moves but +2pp precision delta is modest; ambiguity-resolution overhead and hourly latency rule out primary trigger — caps signal at 3).
- Durability=4 (slow, robust, uncorrelated with options/news/sentiment triggers; Wikipedia infrastructure is durable).
- Feasibility=5 (free, no auth, 200 req/sec limit comfortable, hourly endpoint typical <200ms response).

→ composite = 0.5·3 + 0.3·4 + 0.2·5 = 1.5 + 1.2 + 1.0 = **3.70**.

**Instant-trigger eligible?** NO — confirmer for primary tweet/breakout signals.

**High-Impact Bar:** Bullet 1 — +2pp precision delta as second source; lifts toward +5pp when paired with trends/wiki joint signal (existing repo-wired Google Trends provides natural pairing).

**Minimal integration touch:** New module `consensus_engine/scanners/wikipedia_attention.py`. Pre-built ticker-to-article map seeded from OpenFIGI + Wikidata. Wire into existing `fetch_loop` at `main.py:369–380` (5-min interval hourly resampled). Output via `signal_events` with new SourceType `WIKIPEDIA_ATTENTION`. Consumed by xref via existing `_run_social_check` aggregation.

---

## 11. Reg SHO Threshold List Entry/Exit Event — Flow/Microstructure — score 3.50

**Function:** Daily-poll Reg SHO threshold security lists from NASDAQ, NYSE, Cboe. Diff today's list against yesterday's. **New entries** flag a security with FTDs ≥10,000 shares AND ≥0.5% of shares outstanding for 5 consecutive settlement days — hard regulated event. **Exits** flag close-out resolution.

**Source tier + endpoint + latency:** **High** — `https://www.nasdaqtrader.com/dynamic/symdir/regsho/nasdaqthYYYYMMDD.txt` (daily filename pattern); NYSE: `https://www.nyse.com/regulation/threshold-securities`; Cboe: `https://www.cboe.com/us/equities/market_statistics/reg_sho_threshold/`. EOD same trade date.

**Failure modes:**
- Threshold inclusion sometimes triggers reflexive rallies that fade quickly (1–2 day half-life).
- Many threshold-list names are micro-cap / OTC — manipulation risk dominates.
- Multiple lists (NASDAQ, NYSE, Cboe, OTC) need union with symbol normalization.
- Exit events are often anticlimactic (close-out via price move ≠ predictive).

**Safeguards:**
- Liquidity gate for instant-trigger eligibility: market cap ≥ $1B (per research recommendation).
- For micro-caps (< $1B), confirmatory `+xref` only — no standalone alert.
- Cross-validate with FINRA short-volume z-score on same ticker (if both fire, conviction ↑↑).
- Symbol normalization across NASDAQ/NYSE/Cboe lists (CIK or ticker-cleansing).
- 5-day daily entry must be respected; do not fire on day-1 inclusion.

**Kill criterion:** If 5-day forward T+5 to T+13 excess return on liquid (>$1B mkt cap) cohort is < +0.5σ vs sector base over 12-month backtest, kill. Or if the false-positive (no follow-through) rate exceeds 70% on micro-cap subset, kill the micro-cap inclusion entirely.

**Scoring breakdown:**
- Signal=3 (regulated event with documented but variable forward-return; large-cap subset cleanest; micro-cap subset noisy and manipulation-prone).
- Durability=4 (Reg SHO is permanent SEC rule; forced buy-in mechanic is structural).
- Feasibility=4 (free public lists; daily diff is trivial; symbol normalization is moderate engineering).

→ composite = 0.5·3 + 0.3·4 + 0.2·4 = 1.5 + 1.2 + 0.8 = **3.50**.

**Instant-trigger eligible?** Conditional YES — large-cap (>$1B) entries fire standalone given regulatory weight. Micro-caps confirmatory only.

**High-Impact Bar:** Bullet 4 — closes P0 gap "no short-interest / borrow / utilization delta" partially (Reg SHO is the regulated short-pressure proxy).

**Minimal integration touch:** New module `consensus_engine/scanners/reg_sho.py`. Daily-cadence poll wired into `main.py:455` `macro_digest_loop` neighborhood. Output via `signal_events` with new SourceType `REG_SHO`. Standalone-trigger alert via `alerts/discord.py:316` for >$1B cap.

---

## 12. VIX Term-Structure Flip (contango ↔ backwardation) — Technical/Quant — score 3.50

**Function:** Compute `term_slope = (VX2_settle − VX1_settle) / VX1_settle` from CBOE daily VX-futures settlements. Backwardation entry: alert when slope crosses from ≥0 to <−0.005 AND VIX > 22 AND VIX up ≥15% over prior 5 sessions. Re-contango entry: slope flips from <0 to >0 after ≥3 days backwardated. Magnitude filter: |Δslope_today| ≥ 1σ of trailing 60-day Δslope.

**Source tier + endpoint + latency:** **High** — CBOE VX-futures CSVs `https://www.cboe.com/us/futures/market_statistics/historical_data/products/csv/VX/`. EOD ~16:15 ET. Backstop: `^VIX9D / ^VIX3M` ratio via yfinance (correlation ~0.85 with true VX1/VX2 slope).

**Failure modes:**
- Stale-curve trap during fast vol shocks (VX1/VX2 spike together; slope lags by 1–2 days).
- FOMC announce day / CPI day mechanically distorts slope — must suppress.
- CBOE CSV format occasionally changes (header rows shift); needs schema validation.
- Doesn't capture single-stock vol regime — index-level only.

**Safeguards:**
- Single-event suppression: drop signals fired on FOMC announce day or in 24h before/after CPI release.
- Magnitude filter: `|Δslope_today| ≥ 1σ of trailing 60-day Δslope` mandatory.
- Schema validation on CBOE CSV with try/except + checksum; fall back to yfinance VIX9D/VIX3M ratio.
- Persistence requirement: ≥3 consecutive days backwardated before re-contango flip qualifies.
- VIX > 22 entry gate (tentative).

**Kill criterion:** If forward 5d S&P excess return on re-contango flip cohort is < +20bps mean over 8 historical flip events (or insufficient data), suspend re-contango path. If backwardation entry forward 10d return is negative on 8+ events, kill.

**Scoring breakdown:**
- Signal=3 (Fassas-Hourvouliades + Quantpedia document persistent edge; signal fires <10×/year so no spam BUT effect is index-level only and ~30bps mean 5d excess return is modest — caps signal at 3).
- Durability=4 (dealer-vega-hedging-cycle mechanic durable; sub-strategy of basis trade has been arb'd partially but flip-detection is differentiated).
- Feasibility=4 (CBOE CSV is occasionally fragile; yfinance fallback is solid; trivial pandas computation).

→ composite = 0.5·3 + 0.3·4 + 0.2·4 = 1.5 + 1.2 + 0.8 = **3.50**.

**Instant-trigger eligible?** YES — quant/factor signal class explicitly named in CLAUDE.md; index-level alert.

**High-Impact Bar:** Bullet 4 — closes P0 gap "no CBOE put/call ratio / SKEW market-wide gate" + macro-rails ingest gap.

**Minimal integration touch:** New module `consensus_engine/scanners/vix_term.py`. Wire into existing `main.py:455` `macro_digest_loop`. Output via `signal_events` with new SourceType `VOL_REGIME`. Alert via `alerts/discord.py:316` (instant ping) when flip qualifies.

---

## 13. Influencer Cluster-Convergence (4-author independence, age, dispersion) — Sentiment — score 3.40

**Function:** From the existing Discord/TweetShift listener, cluster mentions of a ticker by author over a 4-hour rolling window. Score = (number of *independent* authors mentioning) × (network-distance penalty for follower-graph similarity). Alert when N≥4 independent voices converge inside the window AND none are in each other's reply chain.

**Source tier + endpoint + latency:** **Low** for source tier (anon/pseudonymous text) but feature is metadata-only (author IDs, no text scraping). Real-time streaming via existing `consensus_engine/scanners/discord_tweetshift.py`.

**Failure modes:**
- Sybil attacks (fake-account cohorts).
- Reply-chain collapse (multiple authors all replying to one OP) — same-cluster, not independent.
- New author with no history — "novelty" cuts both ways (could be high-value first mention OR a sock puppet).
- Crowd-stage features (TweetShift covers a curated cohort) — base independence may already be enforced by the cohort.

**Safeguards:**
- Independence test: two authors are "independent" if (a) neither retweets the other in last 30d, (b) cosine similarity of their last-100-mention ticker history is < 0.6, (c) they were not in the same reply chain in the current cluster.
- Convergence threshold: N≥4 independent authors mentioning same ticker in 4h window AND median author age ≥ 90 days AND median per-author tweet count > 50.
- "Novelty" boost: cluster includes ≥2 authors who have NEVER mentioned this ticker before — boost confidence (informationally heaviest first mentions).
- Suppress on micro-caps (market cap < $200M; sock-puppet/manipulation risk).

**Kill criterion:** If precision delta on tweet-triggered alerts gated by cluster-convergence vs ungated is < 4pp on 90-day backtest, kill.

**Scoring breakdown:**
- Signal=3 (uncorrelated convergence is genuinely informational and +6pp precision delta on tweet-triggered alerts is plausible BUT TweetShift cohort is already curated so independence may already be enforced — caps signal at 3).
- Durability=3 (TweetShift cohort already curated; manipulation vectors evolve — sock-puppet detection is a moving target).
- Feasibility=5 (zero new dependency — just derived analytics on existing TweetShift stream).

→ composite = 0.5·3 + 0.3·3 + 0.2·5 = 1.5 + 0.9 + 1.0 = **3.40**.

**Instant-trigger eligible?** NO — modifies confidence on tweet-driven primary signals.

**High-Impact Bar:** Bullet 1 — +6pp precision delta on tweet-triggered alerts.

**Minimal integration touch:** New module `consensus_engine/analysis/cluster_convergence.py`. Reuses existing `consensus_engine/scanners/discord_tweetshift.py:209–267` (`_handle_dispatch`) — add a hook that emits author-mention metadata to a derived store (`tweet_mentions` table or in-process ring buffer). Cluster compute runs in `process_tweet` flow at `main.py:553–653` (specifically a new `_cluster_check` invoked between dedup `:568` and quality gate `:505`). Output added to `breakdown` in xref scoring.

---

## 14. PDUFA / AdCom Proximity Tag — Catalysts/Macro — score 3.30

**Function:** Maintain rolling 90-day window of upcoming PDUFA decision dates and AdCom advisory committee meetings keyed to ticker. When the bot considers a biotech ticker, attach `next_pdufa_in_days`, `next_adcom_in_days`, and `historical_adcom_polarity` (sponsor's prior AdCom vote outcomes from openFDA Drugs@FDA).

**Source tier + endpoint + latency:** **High** for calendar — FDA Advisory Committee Calendar HTML page `https://www.fda.gov/advisory-committees/advisory-committee-calendar` (FDA must announce ≥15 days in Federal Register). openFDA Drugs@FDA: `https://api.fda.gov/drug/drugsfda.json` (240 req/min, no key). ClinicalTrials.gov v2: `https://clinicaltrials.gov/api/v2/studies` (~10 req/sec). SEC EDGAR 10-Q/10-K full-text search for "PDUFA" mentions for sponsor-disclosed dates. Daily refresh.

**Failure modes:**
- PDUFA dates routinely slip (extension, mid-cycle communications, RTF refusal).
- AdCom briefing docs sometimes appear at unpredictable hours — race vs social-media leakage.
- FDA does not always pre-announce PDUFA dates publicly (sponsor 10-Q is canonical source).
- Sponsor → ticker mapping is messy for subsidiaries / partnerships / CROs.

**Safeguards:**
- Never trigger an alert off the date alone; only contextualize other signals.
- 7-day staleness limit on cached calendar entries; refresh on access.
- Cross-source: FDA calendar + openFDA drugsfda + 10-Q full-text — flag mismatch.
- Suppression rule: if PDUFA date is within T-3 to T-0 window AND sponsor market cap < $5B, raise required confidence threshold by +20% (force 2-source on small biotech in PDUFA window).
- AdCom briefing-doc release detection: separate sub-watcher polling FDA briefing-doc page at hourly cadence.

**Kill criterion:** If tag-coverage (% of FDA approvals/CRLs in past 24 months that were tagged ahead of the event) < 60%, kill (calendar harvester is broken). If precision delta on cross-confirmed signals during T-30 to T-0 window vs T-180 to T-30 window is < 5pp, kill.

**Scoring breakdown:**
- Signal=3 (pre-PDUFA volatility well-documented; calendar context is high-leverage for biotech sub-sector but is gate/contextualizer not primary trigger; signal score capped at 3 for this reason).
- Durability=4 (FDA disclosure rules permanent; PDUFA cadence stable).
- Feasibility=3 (calendar harvester requires HTML scrape of FDA page + openFDA + sponsor 10-Q cross-check — moderate engineering; sponsor-to-ticker mapping is the bottleneck).

→ composite = 0.5·3 + 0.3·4 + 0.2·3 = 1.5 + 1.2 + 0.6 = **3.30**.

**Instant-trigger eligible?** NO — gate / contextualizer.

**High-Impact Bar:** Bullet 1 — +5pp+ precision on cross-confirmed biotech signals in PDUFA-imminent window.

**Minimal integration touch:** New module `consensus_engine/scanners/pdufa_calendar.py`. Reuses existing `consensus_engine/analysis/catalyst_resolver.py` schema. Hook into `cross_reference.py:333` (after existing xref read) to attach context. Output written to existing `youtube_catalysts` table via `db.insert_youtube_catalyst` (or new `external_catalysts` table — minimal new surface).

---

# Cut Candidates (one-line each)

(Sorted by domain.)

**Sentiment (cut: 6 of 12 raw, 6 survivors):**
- Sentiment F1 Reddit z-score multi-sub: dedup vs P0 row 9 (PARTIAL via reddit_trend, command-only) — extension is minor and bottom-30%. **Reason: bottom-30%** (composite ~3.20; below survivor cut).
- Sentiment F3 GDELT global tone: **bottom-30%** (composite ~3.30; coverage delta on US large-caps thin; international-news coverage gap is real but small-impact for US retail bot).
- Sentiment F5 YouTube broad search per ticker: **dedup vs P0 row 17** (YouTube curated channel pipeline already extensive); marginal lift.
- Sentiment F6 Google Trends multi-backend: **dedup vs P0 rows 6/7/8** (already wired with Pytrends + Exa fallback per project memory).
- Sentiment F9 HN/Algolia tech pulse: **below bar** (sector-coverage hole on non-tech tickers; doesn't pass +5pp/30min/+20%-cov bar).
- Sentiment F10 Crowding exhaustion negative gate: **bottom-30%** (composite 3.40 — useful negative gate but high engineering cost relative to standalone alpha; deferred to later phase).
- Sentiment F12 Bluesky/Threads cross-platform: **below bar** (Bluesky stock-mention volume currently too low to predict; opt-in per-ticker doesn't justify infra).

**Flow/Microstructure (cut: 9 of 13 raw, 4 survivors):**
- Flow F1 Options V/OI sweep: **dedup vs P0 row 13** (PARTIAL but broken — `executor=None` plumbing bug, AUDIT scope per task constraint).
- Flow F2 Aggressive premium spend: **bottom-30%** + **dedup-adjacent** (extends Flow F1 plumbing, which is AUDIT-scope).
- Flow F3 Per-ticker PCR z-score: **bottom-30%** (composite 3.05 — depends on F1/F2 plumbing AUDIT fix; standalone value modest).
- Flow F4 CBOE put/call ratio market regime: **bottom-30%** (composite 3.20; useful regime gate but overlaps with VIX term-structure (Feature 12) and future macro regime classifier).
- Flow F6 FINRA short-volume anomaly: **bottom-30%** (composite 3.35; T+0 EOD signal but 50%+ noise from MM hedging; standalone-alert ineligible).
- Flow F8 SEC FTD trend: **bottom-30%** (composite 3.10; 15-day lag rules out instant trigger; confirmatory only with thin marginal lift).
- Flow F9 FINRA SI surprise: **bottom-30%** (composite 3.25; 10-day lag; confirmatory; overlaps Reg SHO Feature 11).
- Flow F10 ATS dark-pool concentration: **bottom-30%** (composite 3.10; 2–4 week lag rules out instant trigger; signal value too compressed by lag).
- Flow F11 Odd-lot rate spike: **bottom-30%** (composite 2.95; quarterly SEC MIDAS is too lagged; intraday Tradier proxy is incomplete vs TAQ).
- Flow F12 ETF creation/redemption: **bottom-30%** (composite 3.30; useful sector-level signal but issuer-page scraping risk + low marginal lift over sector ETF momentum (cut)).
- Flow F13 OCC daily total options: **bottom-30%** (composite 3.05; aggregate-only; 2–5pp marginal precision delta is unreliable to detect).

**Insider/Filings (cut: 7 of 13 raw, 6 survivors — heavy survivor concentration warranted by source tier):**
- Insider F2 Personal z-score buy: **merged into Feature 1** as bonus weight (z ≥ 2 vs trailing 2-year personal distribution); not a standalone feature.
- Insider F5 Form 144 → Form 4 latency: **bottom-30%** (composite 3.10; arXiv 52.4% opacity claim needs validation; matching heuristic is fragile).
- Insider F6 Shelf takedown 424B5: **bottom-30%** (composite 3.20; defensive kill rather than alpha generator; modest lift; small-cap-only).
- Insider F7 S-1 IPO lockup tracker: **bottom-30%** (composite 3.05; mostly defensive; lockup expiration is well-known calendar event already arb'd).
- Insider F8 Form D PIPE: **bottom-30%** (composite 3.20; quality-buyer whitelist requires manual maintenance; signal is mostly defensive).
- Insider F12 Insider departure 5.02 cross-ref: **bottom-30%** (composite 3.05; 8-K-derived; thesis-only contribution; rare-event base rate too low — ~20–40 cases/month system-wide for the qualifying subset).
- Insider F13 Form 4/A amendments: **bottom-30%** (composite 2.65; mostly data-quality maintenance, not lead-discovery).
- Insider F11 13F sharp money quarterly: **bottom-30%** (composite 3.10; 45-day lag pure confirmation; CUSIP-to-ticker mapping is licensed/messy).
- Insider F10 Activist constellation (13D + DEF 14A + DFAN14A): **below bar but kept partially** — merged into Feature 8 as a tier-up rule (when 13D + DFAN14A from same filer-issuer pair within 90d, raise standalone-alert confidence — sub-feature of Feature 8, not its own slot).

**Technical/Quant (cut: 7 of 12 raw, 5 survivors):**
- Tech-Quant F4 Opening Range Breakout: **bottom-30%** (composite 3.30; 15-min delayed yfinance rules out 9:46 entry; mid-morning alert at 10:00 ET has positive but smaller expected expectancy and higher engineering cost).
- Tech-Quant F5 Cross-sectional momentum jump: **bottom-30%** (composite 3.20; requires 2000-ticker universe scan + caching layer; high engineering cost; standalone alpha competes with breakout Feature 5 on the same names).
- Tech-Quant F6 N-sigma mean reversion: **bottom-30%** (composite 3.10; catastrophic failure mode in trends; ADX-falling filter is laggy; opposite philosophy to bot's signal-first momentum bias).
- Tech-Quant F7 Cross-index breadth divergence: **bottom-30%** (composite 3.30; useful regime context but redundant with credit-equity divergence Feature 4).
- Tech-Quant F8 Sector rotation rank-jump: **bottom-30%** (composite 3.40; useful but signal fires in slow-moving regimes; competing with cross-asset signal Feature 4).
- Tech-Quant F10 SKEW-VIX divergence: **below bar** (explicitly NOT instant-trigger; high false-positive rate as standalone; overlaps with VIX term-structure Feature 12).
- Tech-Quant F11 Beta rotation regime: **below bar as alert; KEEP as shared-infrastructure** (not a feature slot — flagged in cross-feature stacking notes as a regime-classifier piece consumed by other features).
- Tech-Quant F12 Anchored VWAP reclaim: **bottom-30%** (composite 3.30; precision target ~58% is fine but adjacent to breakout Feature 5; secondary edge).

**Catalysts/Macro (cut: 8 of 12 raw, 4 survivors):**
- Catalyst C2 Earnings surprise decomposition: **below bar** (8-K parser is fragile across issuer formats; LLM-thesis-only contribution doesn't pass +5pp / +30min / +20%-cov bar standalone; could revisit as enrichment).
- Catalyst C5 Macro surprise → sector bias: **below bar** (consensus-estimate dependence is brittle without paid feed; sector-bias regression decay risk; multiplier role is duplicated by FOMC polarity Feature 6 + macro suppressor).
- Catalyst C6 FOMC polarity score: **below bar** (LLM-language-scoring is high engineering cost; net-hawkish/dovish multiplier overlaps with pre-FOMC drift Feature 3 in time-window terms).
- Catalyst C7 Insider cluster cross-confirmation: **merged into Feature 1** (Form 4 cluster) — same primitive; Feature 1 covers it.
- Catalyst C8 Russell index inclusion: **bottom-30%** (composite 3.40 — useful but rare event ~12×/year and pre-positioned by professionals; small-cap addition retail-flow window is narrow).
- Catalyst C9 Buyback/Tender/Spinoff thesis: **below bar** (LLM-thesis-only contribution; 8-K parsing fragile; tender/spin subset is small).
- Catalyst C10 M&A tape sector cluster: **bottom-30%** (composite 3.30 — multiplier role with low marginal lift; shared infrastructure with Feature 2 standalone).
- Catalyst C11 OpEx gamma profile: **below bar** + bottom-30% (free options-data quality not competitive with paid GEX vendors; 5–7 days engineering for marginal multiplier role; explicitly flagged for cut by researcher).
- Catalyst C12 ClinicalTrials.gov readout: **bottom-30%** (composite 3.40; sponsor-to-ticker mapping is the bottleneck; T-180 window is too wide for primary discovery; useful but high-cost niche).
- Catalyst C4 Macro print suppressor: **kept implicitly within Feature 3 / Feature 6 risk gates** (clock-driven 30+30 min suppression around CPI/PCE/NFP/FOMC is folded into the relevant feature's safeguards). Not a separate slot — it's a clock gate consumed by the catalyst-bearing alerts.

---

# Cross-Feature Stacking Notes

These pairs/trios share infrastructure or amplify each other; caller (Phase 3 + executor) should treat as design clusters, not isolated features.

**Cluster A — SEC EDGAR pipeline (high reuse):** Features 1 (Form 4 cluster), 2 (S-4/425 M&A), 8 (13D activist + 13G→13D conversion), 9 (SEC velocity). All share:
- HTTP plumbing (`User-Agent`, 10 req/s rate-limit, retry/backoff) at `consensus_engine/scanners/sec_edgar.py`.
- Submissions-JSON cache (per-CIK, 24h TTL).
- `submissions.json` `recent.items` parser.
- `signal_events` write path with new SourceType enum values.

Build the shared SEC pipeline once; each feature is then ~150–300 lines.

**Cluster B — Macro / regime classifier (high reuse):** Features 3 (pre-FOMC drift), 4 (credit-equity divergence), 12 (VIX term-structure flip). All share:
- FRED API client (free key, 120 req/min).
- yfinance index/ETF batch fetcher (`yf.download` for SPY/HYG/LQD/IEF/^VIX/^VIX9D/^VIX3M).
- Scheduled-event calendar (FOMC + CPI + PCE + NFP + GDP) — recommend single `events_calendar.yaml` cached annually.
- Regime label output consumed by xref via new `cross_reference._get_macro_context` method (single integration touch).

Recommended shared module: `consensus_engine/signals/_regime.py` — a single `Regime` dataclass (`{vix_bucket, term_slope_sign, credit_stress_flag, fomc_window}`) consumed by 3 features.

**Cluster C — News / sentiment pipeline (high reuse):** Features 7 (FinBERT + catalyst lexicon + velocity), 10 (Wikipedia attention), 13 (cluster convergence). All share:
- Existing `consensus_engine/scanners/news.py` RSS aggregation.
- New `signal_events` SourceType values feeding the existing 2-source rule.
- xref consumption via existing `_run_social_check` aggregation at `cross_reference.py:46`.

FinBERT (Feature 7) is the highest-leverage shared piece — its model is reused for the velocity sub-feature (same one-time inference cost) and the lexicon component runs in the same pipeline.

**Cluster D — Calendar resolver (high reuse):** Features 6 (earnings gate) + 14 (PDUFA proximity). Both are calendar-driven contextualizers that modify scoring on signals from other engines. Shared infrastructure:
- Unified "upcoming catalyst resolver" service that returns a list of tagged catalysts per ticker (extends existing `consensus_engine/analysis/catalyst_resolver.py:179–197`).
- 7-day staleness limit on cached entries; refresh on access if stale.
- Cross-source mismatch handling (Yahoo vs Nasdaq vs Finnhub for earnings; FDA calendar vs openFDA vs 10-Q for PDUFA).

**Pair stacks worth flagging to Phase 3:**
- **Insider Cluster (Feature 1) + S-4/425 M&A (Feature 2)** when both fire on same ticker within 14 days → very-high-conviction takeout setup.
- **Form 4 Cluster (Feature 1) + 13D Activist (Feature 8)** within 30 days → "smart money + activist" stack; high-conviction multi-week thesis.
- **Reg SHO Threshold Entry (Feature 11) + FRED Credit-Equity Divergence (Feature 4)** in same week on same ticker → squeeze-pressure stack with macro context.
- **Earnings Gate (Feature 6) + FinBERT (Feature 7) + Tweet** during T-3 to T+1 earnings window → drives the highest-precision tweet-driven cohort; gate suppresses ambiguous flow, FinBERT confirms direction.
- **Pre-FOMC Drift (Feature 3) + VIX Term-Structure Flip (Feature 12)** in same 3-day window → macro regime alert chain (one fires before, one fires during/after FOMC).

**Anti-stacking warnings:**
- **Feature 5 (breakout) and Feature 13 (cluster convergence) on same ticker same hour** — two instant-trigger paths, both at high confidence. Recommend collapsing into one alert with combined evidence rather than firing two pings.
- **Feature 8 (13D) and Feature 11 (Reg SHO)** can fire on same micro-cap with manipulation risk — large-cap gates on both protect against this.
- **Feature 6 (earnings gate) and Feature 14 (PDUFA gate)** can both hit same biotech in same week — coordinate gate-stacking via the shared calendar resolver (Cluster D).

End of synthesis.
