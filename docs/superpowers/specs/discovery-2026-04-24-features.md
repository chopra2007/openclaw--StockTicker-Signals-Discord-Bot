# Discovery 2026-04-24 — Phase-2 Feature Spec

**Date:** 2026-04-24
**Status:** Approved (post-converge); awaiting Milestone-0 kickoff
**Source of truth:** `plans/discovery-2026-04-24/33-final-feature-set.md`
**Operations playbook:** `plans/discovery-2026-04-24/40b-implementation-operations.md`
**Companion:** `plans/discovery-2026-04-24/40a-implementation-structure.md` (sibling)

This spec is the canonical reference for Phase-2 features. Operations and implementation plans cite IDs (F1, F2, ...) rather than restating descriptions.

---

## Surviving Features

### F1 — Cluster Form 4 Open-Market Buys

- **Module path:** `consensus_engine/scanners/insider_cluster.py` (NEW)
- **Test path:** `tests/unit/scanners/test_insider_cluster.py`, `tests/integration/test_F1_integration.py`
- **Domain:** Insider/Filings · **Instant-trigger eligible:** YES
- **Hardened description:** Detect ≥2 distinct insiders filing Form 4 with `transactionCode == "P"` AND `aff10b5One == false` on the same ticker within a rolling 14-day window; emit a standalone instant-trigger alert with rank-weighted size and z-scored insider history. Rank weights: CEO/CFO/Chair=3, COO/President=2, other officer=2, director=1, 10% holder=1; cluster qualifies at total weight ≥ 4. Dollar floor $25k per insider AND ≥$100k aggregate. Z-score each buy against the insider's trailing 2-year personal buy distribution; flag z ≥ 2 as bonus weight. Auto-retract alerts if a `4/A` arrives within 5 days reducing share count > 50%. Fuzzy name+address match on filer registration to merge multi-CIK reporters; a beneficial-owner detector inspects Form 3 history — if multi-CIKs all appeared on the same Form 3, treat as one. Liquidity gate: market cap ≥ $300M. C-tweak hardenings: (i) reject cluster trigger if any constituent buy is at exactly the same price (within $0.01) as a recent grant (`transactionCode='A'`); (ii) require ≥2 *independent beneficial owners* (non-overlapping prior Form 3 disclosures); (iii) cluster aggregate USD-volume must equal ≥ median recent week's open-market activity. All per-filing XML fetches MUST go through `await rate_limiter.acquire("sec_edgar")`; per-cycle XML fetch budget capped at 30.
- **Kill criterion:** If 21-day forward precision (close > entry by ≥3% sector-adjusted) is < 55% on all-cluster cohort over 90-day rolling broad-participation regime sub-period, OR if 10b5-1 false-positive contamination > 15% in manual sample of 50 alerts, kill standalone-trigger and downgrade to xref-only +25 boost.

### F2 — SEC S-4 / 425 Real-Time M&A Detection

- **Module path:** `consensus_engine/scanners/sec_ma_filings.py` (NEW)
- **Test path:** `tests/unit/scanners/test_sec_ma_filings.py`, `tests/integration/test_F2_integration.py`
- **Domain:** Insider/Filings · **Instant-trigger eligible:** Conditional YES (requires C4 cross-validation)
- **Hardened description:** Detect new S-4 or 425 filings via `getcurrent` atom feed (`type=425&output=atom` and `type=S-4&output=atom`). Classify as fresh-deal announcement (acquirer-CIK references target-CIK for first time in 30 days). Parse offer per-share value (cash/stock/mixed). Emit standalone alert if 2-source-rule satisfied (paired with cluster Form 4 in window OR major-wire headline within ±15 min OR options activity >3σ vs 30d ADV in target). Body parser regex: `merger agreement|definitive agreement|per share`. Hardenings: (A1) regime-aware downgrade on `termination|amendment|withdrawn`, (A2) re-cut filter (no prior 425 from same acquirer in trailing 14 days referencing same target), (A3) `VIX > 30` OR FOMC announcement within 48h → downgrade to xref, (A4) antitrust regime tag, (B1) backfill validation, (B2) 60s same-target-CIK cooldown + dedup on `accession_number`, (C1) require both filer AND target on the 425, (C2) 425/A withdrawal monitor with retract message, (C3) penalty if filer CIK age < 90 days, (C4) cross-validate with target options >3σ OR major-wire ±15 min.
- **Kill criterion:** If false-positive rate (alerts not corresponding to a real deal-announcement press release within ±2h) > 25% on 30-day backtest, OR if median lead-time over Bloomberg/Twitter < 5 minutes, kill standalone-eligibility and downgrade to xref-only.

### F3 — Pre-FOMC Drift Trade

- **Module path:** `consensus_engine/scanners/fomc_drift.py` (NEW)
- **Test path:** `tests/unit/signals/test_fomc_drift.py`, `tests/integration/test_F3_integration.py`
- **Domain:** Technical/Quant · **Instant-trigger eligible:** YES (quant/factor signal class)
- **Hardened description:** Hard-coded calendar of 8 scheduled FOMC announcement dates per year. At 14:00 ET on T-1, fire long-SPY/QQQ alert IF (a) `VIX > 18`, (b) VIX up >10% over prior 5 sessions, (c) prior 24h SPY return ≤ 0. Exit at 14:00 ET on FOMC day (15 min pre-announce). NEVER hold through announcement. Hard time-stop at 14:00 ET on FOMC day. Stop-loss at entry × (1 − 0.6%). Hardenings: (A1) Rates-regime kill switch — 2yr Treasury Δ5d > ±20bps suppresses, (A2) Rolling-3 kill — 3 prior negative cumulative excess pauses standalone, (A3) Calibration logging — gated-out count per quarter, (C1) Refresh FOMC calendar weekly with fail-closed on > 7 days stale, (C2) EFFR deviation kill-switch (intraday > 5bps), (C3) Front-running mitigation via auction-imbalance gate (10-min ADV ≥ 90th pct), (C4) ±90 sec randomization on alert send. Wired consumer: `cross_reference._get_macro_context` applies `confidence_threshold *= 0.85` on cyclicals/small-caps when active.
- **Kill criterion:** If mean 24h pre-FOMC excess return on filtered subset (VIX>18 + VIX-up + flat-prior + 2yr-stable + EFFR-stable) drops below +25bps over 8 consecutive meetings, OR positive-day frequency falls below 60%, kill. Use 5-year rolling window stratified by regime.

### F4 — FRED Credit-Equity Divergence (HYG vs SPY + HY OAS)

- **Module path:** `consensus_engine/scanners/credit_equity_divergence.py` (NEW)
- **Test path:** `tests/unit/scanners/test_credit_equity_divergence.py`, `tests/integration/test_F4_integration.py`
- **Domain:** Technical/Quant · **Instant-trigger eligible:** NO (regime/macro signal; multiplier only)
- **Hardened description:** EOD daily computation: `gap_20d = SPY_20d_return − HYG_20d_return`. Bearish trigger when `gap_20d > 2σ` (over 252-day baseline) AND `HYG < SMA(HYG, 50)` AND `SPY ≥ SMA(SPY, 50)` AND signal persists ≥2 sessions. Confirmation via FRED `BAMLH0A0HYM2` (HY OAS direct) and LQD weakness check. Suppress when `correlation(HYG, SPY, 60d) > +0.85`. 252d rolling baseline excludes the most-recent 20 days. Hardenings: (A1) Breadth filter — only fire when SPY 50d-SMA-above is ≥60% of S&P constituents, (A2) Stratified backtest — kill criterion stratified by broad-participation vs concentrated, (A3) Define explicit consumption — `_get_macro_context` raises required confidence threshold +10pts on cyclicals/small-caps during macro-caution, (B1) FRED_API_KEY in `/root/.openclaw/.env`, (B2) New `macro_signals` table.
- **Kill criterion:** If false-positive rate (no >3% SPY drawdown within 20 trading days) > 60% on 24-month backtest stratified by broad-participation regime only, kill. Alternative: if mean forward 20d SPY return conditional on signal ≥ unconditional baseline within broad-participation sub-period, kill.

### F5 — Volume-Confirmed N-Day Breakout with ATR Levels

- **Module path:** `consensus_engine/analysis/breakout_atr.py` (NEW analysis util)
- **Test path:** `tests/unit/analysis/test_breakout_atr.py`, `tests/integration/test_F5_integration.py`
- **Domain:** Technical/Quant · **Instant-trigger eligible:** YES ("technical breakout with levels")
- **Hardened description:** Fire when `close_today > rolling_max(close, N)` for N ∈ {20, 60, 252} AND `volume_today ≥ 2.0 × rolling_mean(volume, 20)` (raise to 2.5 for low-float <50M shares) AND `close > VWAP_anchored` from prior pivot-low AND `BBwidth(20, 2σ) > 30th percentile of trailing 252d`. Emit alert with `entry = close`, `target_1 = close + 1.5×ATR(14)`, `target_2 = close + 3.0×ATR(14)`. Hardenings: (A1) 2-session persistence for N=20, (A2) earnings-window suppression in module (T-1/T+2), (A3) VIX cap raised to 35, (C1) replace volume-z-score with dollar-volume z-score; require dollar volume ≥ $10M, (C2) hard market-cap floor $500M, (C3) reject if last-hour-vs-first-5h volume ratio < 0.45, (C4) **stop publishing stop-loss** in alert (publish entry + targets only), (C5) 30-min post-close delay. ADX(14) > 22 retained for N=20. Daily quotas: 20/N=20, 5/N=60, 3/N=252. Universe scope MUST be bounded (top-N from ApeWisdom + active TweetShift hits).
- **Kill criterion:** If 1-day forward precision (next-day close above today's close) < 52% on filtered cohort over 90-day rolling broad-participation regime, kill N=20 tier; if < 50% on N=252, kill that tier.

### F6 — Earnings-Window Risk Gate

- **Module path:** Extends `consensus_engine/scanners/earnings_calendar.py` + `consensus_engine/analysis/catalyst_resolver.py`; new `consensus_engine/analysis/earnings_gate.py`
- **Test path:** `tests/unit/analysis/test_earnings_gate.py`, `tests/integration/test_F6_integration.py`
- **Domain:** Catalysts/Macro · **Instant-trigger eligible:** NO (gate/contextualizer only)
- **Hardened description:** For every ticker that surfaces from any engine, look up next earnings date and tag the signal with one of `pre_earnings_T-N`, `into_earnings`, `post_earnings_T+N`, or `clear`. Hardenings: (B1) drop Nasdaq `api.nasdaq.com` as primary source — keep only as tertiary fallback after Finnhub + yfinance, (B2) 7-day TTL on cached earnings dates; invalidate on any `8-K Item 2.02`, (C1) trust Finnhub-curated date over self-disclosed pre-announce, (C2) **soft score modifier (0.6× confidence multiplier in T-3 to T+1)**, not hard-suppress, (C3) tweet-density override (10x normal in gate window → "multiple_events"), cross-source mismatch ≥2 days → "uncertain" fail-closed.
- **Kill criterion:** If precision delta on social-source signals fired in T-3 to T+1 vs same signals in T-30 < 5pp on 6-month backtest, kill the gate.

### F8 — New 13D Activist-Filer Detection (with 13G→13D conversion)

- **Module path:** `consensus_engine/scanners/sec_activist_13d.py` (NEW)
- **Test path:** `tests/unit/scanners/test_sec_activist_13d.py`, `tests/integration/test_F8_integration.py`
- **Domain:** Insider/Filings · **Instant-trigger eligible:** YES (narrowed to whitelisted-activist + specific verbiage)
- **Hardened description:** Two-leg feature. (a) When a new Schedule 13D appears, score on filer's activist history (count of distinct prior 13D campaigns over trailing 5 years), percentage stake disclosed, and Item 4 "Purpose of Transaction" intent. Standalone alert when filer ≥2 prior campaigns AND C-required-conditions OR Item 4 contains specific actionable nomination/strategic-alternative language. (b) Flag "13G→13D conversion" — a holder previously on 13G filing fresh 13D; standalone alert ONLY when paired with concurrent action. Hardenings: (B1) backfill activist-filer history one-time + weekly delta refresh, (B2) Item 4 LLM-classifier fallback for filers with ≥2 prior campaigns, (B3) `holder_intent` table indexed `(filer_cik, issuer_cik)`, (C1) co-filing same-day dedup, (C2) Item 4 must contain named nominee/specific tender or proxy threat/named counterparty, (C3) 13G→13D conversion downgraded to xref-only unless paired with press release in 24h OR options >3σ OR known-activist tweet ±48h, (C4) outcome-weighted activist-history (raw 13D count insufficient), (C5) **whitelist of confirmed activist filer-CIKs** at `config/activist_whitelist.yaml` — only whitelisted qualify for standalone-trigger.
- **Kill criterion:** If 21-day forward precision (positive sector-adjusted return) < 50% on whitelisted-activist subset over 12-month backtest, kill standalone path.

### F10 — Wikipedia Pageview Spike

- **Module path:** `consensus_engine/scanners/wikipedia_pageviews.py` (NEW)
- **Test path:** `tests/unit/scanners/test_wikipedia_pageviews.py`, `tests/integration/test_F10_integration.py`
- **Domain:** Sentiment · **Instant-trigger eligible:** NO (annotation only)
- **Hardened description:** Pull hourly pageviews for ticker's company Wikipedia article and flag z ≥ 2.5 vs trailing-28-day weekday-matched baseline. Use as +0.05 max confidence-multiplier (cap, per C3) on tweet-driven or breakout-driven primary signals. Hardenings: (A1) hard-gate to mid/small-caps only ($200M–$5B), (A2) continuous penalty when prior-week elevation z>2 (already-saturated), (A3) demote from confirmer to thesis-text-only annotation, (B1) ship ticker→Wikipedia-article map as one-time backfill, (B2) reject articles where infobox doesn't contain ticker symbol, (B3) 1-hour TTL cache per article-slug; 28-day baseline cached, (B4) User-Agent: `consensus_engine/1.0 (+https://github.com/chopra2007/openclaw; ak@openclaw.dev)`, (C1) **mandatory** Google Trends co-confirmation (same hour, same direction), (C2) sustained-spike requirement: z ≥ 2.5 for ≥3 consecutive hours, (C3) +0.05 hard cap on contribution.
- **Kill criterion:** If precision delta when used as +0.05 multiplier on tweet-driven primaries (gated by C1+C2) < 1pp on 90-day backtest, kill.

### F11 — Reg SHO Threshold List Entry/Exit Event

- **Module path:** `consensus_engine/scanners/reg_sho_threshold.py` (NEW)
- **Test path:** `tests/unit/scanners/test_reg_sho_threshold.py`, `tests/integration/test_F11_integration.py`
- **Domain:** Flow/Microstructure · **Instant-trigger eligible:** Conditional YES (large-cap >$2B during stress regime)
- **Hardened description:** Daily-poll Reg SHO threshold security lists from NASDAQ (`nasdaqthYYYYMMDD.txt`), NYSE (follow redirect to `/regulation/regulation-sho`), Cboe. Diff today's list against yesterday's. Hardenings: (A1) cap floor $2B for instant-trigger; X2 stack with F8 13D requires $3B, (A2) regime gate — only fire standalone when `VIX > 22` AND HY OAS > 350bps, (A3) drop FINRA short-volume cross-validation (since Flow F6 cut at P2); replace with (Reg SHO + Form 4 cluster within 14d) OR (Reg SHO + macro stress regime per A2), (B1) cumulative-entry-day-count per (ticker, list), (B2) follow NYSE redirect explicitly, (B3) 404 retry 30 min later (no log spam), C-confirm robust ticker normalization (BRK.B / BRK B / BRK-B).
- **Kill criterion:** If 5-day forward T+5 to T+13 excess return on >$2B mkt cap cohort during stress regime (VIX>22 AND HY OAS>350) < +0.5σ vs sector base over 12-month backtest, kill standalone path.

---

## Cross-Cutting Safeguards

### S1 — Shared SEC EDGAR semaphore
- **Module path:** Extends `consensus_engine/utils/rate_limiter.py:29`
- **Default:** ON · **Tightening:** `sec_edgar: 0.15` (was 0.2)
- **Description:** Aggregate SEC fair-use 10 req/s ceiling across `data.sec.gov` / `www.sec.gov/cgi-bin` / `efts.sec.gov`. All SEC-touching code MUST `await rate_limiter.acquire("sec_edgar")`. Per-feature jittered start offsets: F1 :00, F2 :20, F8 :40 of every minute.
- **Dependent features:** F1, F2, F8

### S2 — Correlation-decay penalty at xref aggregation
- **Module path:** `consensus_engine/analysis/correlation_decay.py` (NEW), hooked at `consensus_engine/cross_reference.py:333`
- **Default:** OFF (master `phase2_safeguards_enabled` ON; sub-flag dark-launch first)
- **Description:** For each ticker-window (24h), compute `n_active_sources`, accumulate `suspicious_correlation_factor` (same-direction-in-<12h: +0.30; low-trust-tier source after first: +0.20 per source; CIK age <90 days OR sock-puppet account <90d: +0.40 per such source). `penalty = max(0, n_active_sources − 2) × suspicious_correlation_factor`. Final score = `base_score × (1 − penalty)`, capped at [0.20, 1.00].
- **Dependent features:** F1, F2, F5, F8, F10, F11

### S3 — Generalized per-analyst cooldown (audit M3)
- **Module path:** Extends `consensus_engine/db.py:672` (`check_alert_cooldown`)
- **Default:** OFF (master ON; sub-flag enables after audit M3 lands)
- **Description:** Replace ticker-level cooldown with per-analyst/per-source precision-weighted cooldown using `source_performance` table. Fixes audit-confirmed `kpak82` 26-min cooldown race. Generalizes to every standalone-trigger feature.
- **Dependent features:** All standalone-trigger features (F1, F2, F3, F5, F8, F11)
- **Status:** Audit-prerequisite. MUST land before first surviving feature goes live.

### S4 — Calendar resolver consolidation
- **Module path:** Extends `consensus_engine/analysis/catalyst_resolver.py`
- **Default:** OFF (sub-flag)
- **Description:** Consolidate Features 3 (pre-FOMC) and 6 (earnings) calendar dependencies into one shared `events_calendar` interface. FOMC YAML at `config/fomc_calendar.yaml` weekly refresh. Daily-cadence staleness check; if next-event within 30 days but YAML last-refreshed >7 days ago, emit source-health alert.
- **Dependent features:** F3 (FOMC), F6 (earnings)

### S5 — Data freshness gate
- **Module path:** `consensus_engine/utils/freshness_gate.py` (NEW)
- **Default:** OFF (master ON; sub-flag for gate behavior)
- **Description:** Each macro/quant feature consults `is_fresh(source_id, max_age_seconds)` before computing signal. Fail-closed: `is_fresh == False` → no signal, no false positive.
- **Dependent features:** F3 (Finnhub /quote, FRED), F4 (FRED, yfinance), F5 (yfinance OHLCV), F11 (NASDAQ/NYSE/Cboe daily files)

### S6 — HEAD-vs-GET health-check
- **Module path:** Extends `consensus_engine/utils/http.py`
- **Default:** ON
- **Description:** Health-check helper that uses GET with HEAD-equivalent semantics (`Range: bytes=0-0` or short body read). Documents convention to prevent re-hitting B's `MissingAuthenticationTokenException` finding on EFTS.
- **Dependent features:** None directly; preventative for future EFTS re-introduction.

### S7 — Schema migration consolidation
- **Module path:** Extends `consensus_engine/db.py`; migration script `scripts/migrations/202604_phase2_features.sql`
- **Default:** ON (one-shot)
- **Description:** New tables: `holder_intent` (F8), `macro_signals` (F4), `ticker_external_ids` ext (F10), `beneficial_owner_index` (F1). New SourceType enum values: `INSIDER_CLUSTER`, `M_AND_A`, `MACRO_DRIFT`, `TECHNICAL_BREAKOUT`, `ACTIVIST_FILING`, `WIKIPEDIA_ATTENTION`, `REG_SHO`. FRED API key in `/root/.openclaw/.env`. Atomic rollback on partial failure. Engine refuses to start on version mismatch.
- **Dependent features:** F1, F4, F8, F10 (also F3 indirectly via FRED)

### S8 — Shared yfinance rate-limit
- **Module path:** Extends `consensus_engine/utils/rate_limiter.py`
- **Default:** ON (config addition)
- **Description:** New entry `yfinance: 1.0` (1 req/s). All yfinance callers route through `await rate_limiter.acquire("yfinance")` regardless of caller. Audit existing call sites in `main.py:807–832`, `analysis/technical.py:54`, `scanners/volume_scanner.py`, `scanners/options.py`.
- **Dependent features:** F3, F4, F5, existing `price_outcome_loop`

### S9 — Macro-context consumption pattern
- **Module path:** Extends `consensus_engine/cross_reference.py` — new method `_get_macro_context` at `:333`
- **Default:** OFF (sub-flag)
- **Description:** Applies regime-conditional confidence multipliers. F4 (credit-equity bearish) → +10pts threshold on cyclicals/small-caps. F3 (pre-FOMC long active) → confidence threshold ×0.85 on tweet-driven cyclicals. Prevents dead-code fate of `regime_detector.py`.
- **Dependent features:** F3, F4

---

## Dropped Features (post-mortem references)

For full post-mortems see `plans/discovery-2026-04-24/33-final-feature-set.md` Section 4.

| ID | Name | Verdict | Reason |
|----|------|---------|--------|
| F7 | FinBERT Headline Sentiment + Catalyst Lexicon | A=STR, B=STR, **C=KILL** | Adversarial-text inputs economically asymmetric ($300 PR-wire placement, $0 BERT tokenization attacks). |
| F9 | SEC EDGAR Full-Text Mention Velocity | **A=KILL**, **B=KILL**, C=STR | Already poisoned production 2026-03-31 → 2026-04-07; EFTS HEAD-vs-GET asymmetry; aggregates EDGAR noise that F1/F2/F8 cover at signal level. |
| F12 | VIX Term-Structure Flip | A=STR, B=STR, **C=KILL** | Signal-redundancy with F3+F4; low frequency (<10×/year); fold into F4's `macro_signals` if revived. |
| F13 | Influencer Cluster-Convergence | **A=KILL**, B=KEEP, **C=KILL** | TweetShift cohort already curated; convergence becomes lagging in macro events; CC-S3 (M3) achieves +6pp goal cheaper. |
| F14 | PDUFA / AdCom Proximity Tag | A=KEEP, **B=KILL**, C=STR | FDA AdCom calendar Akamai-walled; serial upstream failure modes; no constructible all-three-lens STRENGTHEN. |

---

## Implementation Sequencing (canonical)

| Milestone | Includes | Notes |
|-----------|----------|-------|
| **M0** | S1, S2 (dark), S3, S4, S5, S6, S7, S8, S9 | All preconditions; production-validate before any feature |
| **M1** | F1 | Lowest infra risk, highest-confidence; CC-S2 flips live alongside F1 production-enable |
| **M2** | F6, F8 | Cluster A high-signal (F8) + gate (F6); F6 dark-launch shorter |
| **M3** | F2, F3, F4 | Macro/regime cluster + Cluster A completion; F3 dark-launch ≥1 FOMC cycle |
| **M4** | F5, F10, F11 | Broader infrastructure footprint; F5 highest blast radius |

See `plans/discovery-2026-04-24/40b-implementation-operations.md` Section 8 for stage gates, kill switches, and feature-flag rollout semantics.
