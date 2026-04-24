# 40a — Phase 4 Implementation Mechanics (Build Manifest)

**Date:** 2026-04-24
**Scope:** Sections 1–5 (System Overview, Component Architecture, Data Flow Pipeline, Data Structures, Integration Plan).
**Inputs:** `33-final-feature-set.md` (source of truth — 9 surviving features, 9 cross-cutting safeguards), `00-system-map.md` (P0 file:line citations).
**Sibling deliverable:** `40b-implementation-operations.md` covers sections 6–10 (failure handling, tests, rollout) — do not duplicate here.

---

## 1. System Overview

### 1.1 Narrative

The 9 surviving features (F1, F2, F3, F4, F5, F6, F8, F10, F11) plug into the existing pipeline split that P0 documented:

- **Phase-1 instant trigger** (`main.py:553–653` `process_tweet`) remains the SOLE place a tweet-driven alert begins. F1, F2, F8, F11 emit standalone Phase-1 alerts via the *same* `alerts/discord.py:316` `send_instant_ping` path — they enter from new background scanner loops wired alongside `sec_8k_watcher_loop` (`main.py:343–347`), not via TweetShift.
- **Cross-reference Phase-2** (`cross_reference.py:217–334`) gains two new consumption sites at `cross_reference.py:333` (immediately after the existing `signal_events` read on `:328–332`): (i) the correlation-decay penalty (S2) and (ii) `_get_macro_context` (S9). F3 and F4 only contribute via this consumption path; they are NOT instant triggers.
- **Score breakdown** (`models.py:240–260` `ScoreBreakdown`) gets one new field `macro_context_modifier: float` to carry the multiplicative regime adjustment from F3 + F4. F5, F6, F10 contribute via existing `breakdown.technical` / `breakdown.llm_boost` channels (no new fields).
- **Calendar resolver** (`analysis/catalyst_resolver.py:179–197`) is generalised by S4 into a multi-event calendar service (FOMC, earnings, Reg-SHO file-publish dates) consumed by F3 (FOMC), F5/F6 (earnings), and F11 (Reg-SHO publish dates).
- **Shared infrastructure**: every SEC HTTP call routes through S1's tightened semaphore (`utils/rate_limiter.py:29` `sec_edgar: 0.15`); every yfinance call routes through new S8 limiter (`yfinance: 1.0`); every macro/quant signal consults S5 freshness gate (`utils/freshness_gate.py`) before computing.

**Why preconditions ship first:** S1, S3, S5 are HARD preconditions because the surviving features assume their behaviour. S1 stops Cluster A (F1/F2/F8) plus the existing `cross_reference._run_sec_check` from co-bursting. S3 fixes the `kpak82` parallel-read race so two near-simultaneous spoofed signals can no longer both pass cooldown. S5 closes the `regime_detector.py` failure mode (write to `signal_events`, no consumer) by giving F3 and F4 a documented consumer.

### 1.2 Module map

```
consensus_engine/
├── scanners/
│   ├── insider_cluster.py             [NEW]    F1   ~250 LOC
│   ├── sec_ma_filings.py              [NEW]    F2   ~220 LOC
│   ├── fomc_drift.py                  [NEW]    F3   ~180 LOC
│   ├── credit_equity_divergence.py    [NEW]    F4   ~200 LOC
│   ├── sec_activist_13d.py            [NEW]    F8   ~280 LOC
│   ├── wikipedia_pageviews.py         [NEW]    F10  ~150 LOC
│   ├── reg_sho_threshold.py           [NEW]    F11  ~180 LOC
│   ├── earnings_calendar.py           [EXTEND] F6 / S4   +30 LOC
│   └── (existing untouched: sec_edgar, sec_watcher, news, social,
│        volume_scanner, options, youtube, discord_tweetshift, …)
│
├── analysis/
│   ├── breakout_atr.py                [NEW]    F5   ~200 LOC (analysis util,
│   │                                          callable from new scanner+xref)
│   ├── correlation_decay.py           [NEW]    S2   ~150 LOC
│   ├── catalyst_resolver.py           [EXTEND] F6 / S4    +120 LOC
│   └── (existing: technical, indicators, regime_detector,
│        calibration, video_classifier, gemini_video_parser …)
│
├── utils/
│   ├── freshness_gate.py              [NEW]    S5   ~50 LOC
│   ├── rate_limiter.py                [EXTEND] S1+S8 +15 LOC
│   └── http.py                        [EXTEND] S6   +20 LOC (GET-as-HEAD helper)
│
├── cross_reference.py                 [EXTEND] S2 + S9 hook at :333
│                                                       +60 LOC
├── db.py                              [EXTEND] S3 + S7 schema additions
│                                                       +180 LOC
├── models.py                          [EXTEND] new SourceTypes,
│                                               new dataclasses     +60 LOC
└── alerts/
    └── discord.py                     [EXTEND] new payload formatters +80 LOC

config/
├── consensus.yaml                     [EXTEND] feature flags + thresholds  +120 lines
├── fomc_calendar.yaml                 [NEW]    F3 weekly-refreshed  ~30 lines
└── activist_whitelist.yaml            [NEW]    F8 whitelist          ~20 lines

scripts/
├── backfill_activist_history.py       [NEW]    F8 one-time job      ~100 LOC
└── migrations/202604_phase2_features.sql [NEW] consolidated schema migration
                                                                     ~200 LOC
```

### 1.3 Dependency story

```
S1 (SEC semaphore tighten + audit) ─┬─► F1 (insider cluster)
                                    ├─► F2 (M&A filings)
                                    └─► F8 (13D activist)

S3 (cooldown M3 generalisation) ────┬─► F1, F2, F3, F5, F8, F11
                                    │   (all instant-trigger features)
                                    └─► (existing TweetShift path benefits)

S7 (schema migrations consolidated) ─► F1 (beneficial_owner_index),
                                        F4 (macro_signals),
                                        F8 (holder_intent),
                                        F10 (ticker_external_ids),
                                        ALL (new SourceType enum values)

S5 (freshness gate)               ──┬─► F3 (Finnhub /quote SPY/VIX)
                                    ├─► F4 (FRED HY OAS, yfinance)
                                    ├─► F5 (yfinance OHLCV)
                                    └─► F11 (NASDAQ/NYSE/Cboe daily files)

S8 (yfinance rate limit)          ──┬─► F3, F4, F5
                                    └─► (existing price_outcome_loop)

S2 (correlation decay at xref)    ──┬─► F1, F2, F5, F8, F10, F11 (defends X1–X5)

S4 (calendar resolver)            ──┬─► F3 (FOMC), F6 (earnings),
                                    └─► F5 (earnings sub-suppression),
                                        F11 (Reg-SHO publish window)

S9 (_get_macro_context consumption)─┬─► F3 (pre-FOMC long → cyclical 0.85×),
                                    └─► F4 (credit-equity bearish → +10pt threshold)

S6 (GET-as-HEAD convention)       ──► (preventative for future EFTS reintroduction)
```

The three preconditions for **Milestone-1**: `S1`, `S3`, `S7`. Without these, NONE of F1/F2/F8 can ship safely (S1 to avoid IP block; S3 to close cooldown race; S7 to land enum values + new tables). Everything else can sequence behind these three.

---

## 2. Component Architecture

Each subsection lists Purpose / Inputs / Outputs / Core logic / File path / Reuses / LOC. Citations against P0 use `module.py:line` form verbatim from `00-system-map.md`.

---

### F1 — Cluster Form 4 Open-Market Buys

**Purpose:** Detect ≥2 distinct insiders' open-market buys (`transactionCode == "P"`, `aff10b5One == false`) on a single ticker within a rolling 14-day window; emit standalone Phase-1 alert with rank-weighted size and z-scored insider history.

**Inputs:**
- SEC EDGAR `getcurrent` ATOM feed for type=4 (every 5 min) — adapter pattern of `sec_edgar.py:64–141`.
- SEC EDGAR Form-4 archive XML — already parsed by `sec_edgar.py:173–302` (`fetch_form4_details`), reuse verbatim.
- DB `beneficial_owner_index` (NEW per S7) for filer-to-CIK clustering.
- DB `alert_history` for retract logic.

**Outputs:**
- Standalone Phase-1 alert via `alerts/discord.py:316` (`send_instant_ping`) with `signal_type="INSIDER_CLUSTER"`.
- `signal_events` row at `db.py:602` with new SourceType `INSIDER_CLUSTER`.
- Optional `alert_history` retract message via `alerts/discord.py:366` (`edit_instant_ping`) when 4/A arrives within 5 days.

**Core logic:**
- Poll `getcurrent` ATOM for type=4 every 300 s (jittered to :00 of every minute per S1).
- For each new accession, `await rate_limiter.acquire("sec_edgar")` then `fetch_form4_details(accession)`.
- Persist parsed buys keyed `(issuer_cik, filer_cik, transaction_date, shares, price)`.
- Rolling-window query: ≥2 distinct *beneficial owners* (fuzzy-merged via `beneficial_owner_index`) with `transactionCode='P'` AND `aff10b5One=false` in trailing 14 days.
- Apply rank weights (CEO/CFO/Chair=3, COO/President=2, other officer=2, director=1, 10%=1); cluster qualifies at total weight ≥4.
- Apply USD floors: ≥$25k per insider AND ≥$100k aggregate.
- C-tweak gates: (i) reject if any constituent buy price equals (within $0.01) any `transactionCode='A'` grant on same issuer in trailing 30 days; (ii) require ≥2 *independent* beneficial owners (non-overlapping prior Form 3); (iii) cluster aggregate USD-volume ≥ median weekly open-market activity for issuer.
- Liquidity gate: market cap ≥ $300M (read via `utils/tickers.py` `validate_ticker_market_cap`).
- Z-score each buy against insider's trailing 2-year personal buy distribution; record bonus weight if z ≥ 2.
- 4/A retract loop runs every 600 s: query trailing 5 days for `4/A` rows; if share-count reduced > 50% on a buy that triggered an alert, edit the original Phase-1 message (`edit_instant_ping`) appending "RETRACTED — amended filing reduces shares".

**File path:** `consensus_engine/scanners/insider_cluster.py` (NEW).

**Reuses:**
- `consensus_engine/scanners/sec_edgar.py:39` (ticker map).
- `consensus_engine/scanners/sec_edgar.py:173–302` (Form-4 XML parser).
- `consensus_engine/utils/rate_limiter.py:29` (`sec_edgar` lane, S1).
- `consensus_engine/utils/tickers.py` `validate_ticker_market_cap` (P0 row 26).
- `consensus_engine/alerts/discord.py:316` (`send_instant_ping`).
- `consensus_engine/db.py:602` (signal_events insert).
- `consensus_engine/db.py:784–805` (`insert_alert`).

**LOC estimate:** ~250 LOC (significant new module per audit calibration: scanner loop ~80, cluster query ~70, beneficial-owner detector ~50, retract loop ~30, rank/weight scoring ~20).

---

### F2 — SEC S-4 / 425 Real-Time M&A

**Purpose:** Detect new S-4 / 425 filings; classify as fresh-deal announcement; emit Phase-1 alert ONLY when 2-source rule (Form 4 cluster within 14d OR major-wire ±15min OR target options >3σ) is satisfied.

**Inputs:**
- SEC EDGAR `getcurrent` ATOM feeds for type=425 and type=S-4.
- `submissions.json` for filer/target CIK age check (≥90 days).
- Body parser regex `merger agreement|definitive agreement|per share`.
- DB tables: `signal_events` (for prior Form 4 cluster lookup from F1), `news` xref data (existing `_run_news_cascade`), `options.py` `check_unusual_options` (P0 row 22) for target ticker.
- `macro_signals` table (S7 NEW) for VIX > 30 and FOMC-±48h check.

**Outputs:**
- Phase-1 alert via `send_instant_ping` with `signal_type="M_AND_A"`, only when 2-source rule satisfied.
- `signal_events` row with SourceType `M_AND_A` (every detection, even if standalone gate fails — feeds xref).
- Antitrust regime tag appended in alert body.

**Core logic:**
- Poll the two ATOM feeds at jittered :20 of every minute (per S1's offset plan); 300 s cycle.
- For each new accession: `acquire("sec_edgar")`, fetch the 425/S-4 body, regex-classify.
- Re-cut filter: query DB for any prior `signal_events` with SourceType `M_AND_A`, same `acquirer_cik`, `target_cik` in trailing 14 days; if found, downgrade to xref-only.
- Termination filter: if body contains `termination|amendment|withdrawn`, downgrade to xref-only.
- C1 dual-party check: require target CIK to appear in `SUBJECT-COMPANY` field, not merely referenced in body.
- C3 CIK-age check: query `submissions.json` for filer; if first SEC filing < 90 days ago, downgrade.
- A1/A3 macro gates: read `macro_signals` table — if `vix > 30` OR `fomc_within_48h`, downgrade.
- A4 antitrust regime: read `sector_antitrust_history` (small manual table); append "antitrust regime: high" to alert body if applicable.
- C4 second-source check (gate for standalone): require ANY of (a) `signal_events` row with SourceType `INSIDER_CLUSTER` for target ticker in trailing 14 days, (b) `news_cascade` Tier-1/Tier-2 hit within ±15 min, (c) `check_unusual_options(target_ticker)` returns `has_unusual_activity == True`.
- 425/A withdrawal monitor (separate 600 s loop): if a 425/A rolls in within 7 days of a prior alerted accession, edit the Phase-1 message via `edit_instant_ping` to append "RETRACTED — amended filing".
- 60s same-target-CIK cooldown (per B2) plus dedup on `accession_number`.

**File path:** `consensus_engine/scanners/sec_ma_filings.py` (NEW).

**Reuses:**
- `scanners/sec_edgar.py:39, 64–141` (ticker map + recent-filings adapter).
- `scanners/sec_watcher.py:23–155` (ATOM parser pattern).
- `scanners/news.py:279–303` (`news_cascade` for ±15 min headline).
- `scanners/options.py:89` (`check_unusual_options`).
- `utils/rate_limiter.py:29` (S1).
- `alerts/discord.py:316, :366` (instant + edit).
- `db.py:602` (signal_events insert).

**LOC estimate:** ~220 LOC.

---

### F3 — Pre-FOMC Drift Trade

**Purpose:** Hard-coded calendar of 8 FOMC dates per year; at 14:00 ET on T-1, fire long-SPY/QQQ index-level alert IF VIX>18, VIX up >10% over 5 sessions, and prior 24h SPY return ≤0. Exit at 14:00 ET on FOMC day.

**Inputs:**
- `config/fomc_calendar.yaml` (NEW; weekly-refreshed via S4 calendar resolver).
- Finnhub `/quote` for SPY, VIX (free tier; existing adapter at `engine.FinnhubAdapter`).
- yfinance for 5-session VIX history (via S8 lane).
- FRED `EFFR` series (NEW key per S7).
- FRED `DGS2` (2yr Treasury) for A1 rates-regime kill switch.
- `macro_signals` table to publish own state (`pre_fomc_active=True`).

**Outputs:**
- Index-level Phase-1 alert via `send_instant_ping` (with `signal_type="MACRO_DRIFT"`, ticker=SPY).
- Row in `macro_signals` table consumed by `_get_macro_context` (S9).
- Optional exit-time edit via `edit_instant_ping` at 14:00 ET FOMC day with realised P/L.

**Core logic:**
- Calendar staleness check (via S4 resolver): if `fomc_calendar.yaml` last-modified > 7 days, fail-closed (no fire) and emit `source_health` alert.
- 60 s tick from inside `macro_digest_loop` (`main.py:455–476`); poll until next FOMC date is ≤ 1 day away.
- At T-1, 14:00 ET (±90 sec randomisation per C4): evaluate gates.
- Gate set:
  - VIX > 18 (`/quote`).
  - VIX up >10% over prior 5 sessions (yfinance via `yfinance` lane).
  - Prior 24h SPY return ≤ 0.
  - A1: |Δ DGS2 over 5 sessions| ≤ 20bps (FRED).
  - A2: rolling-3 kill — count last 3 filtered-FOMC outcomes; if all negative, suppress until 2 positives recover.
  - C2: realised EFFR move <5bps inside the day (FRED `EFFR`); else suppress 24h.
  - C3: SPY auction-imbalance trailing 10-min ADV ≥ 90th percentile (yfinance).
  - S5 freshness check on Finnhub `/quote` and FRED endpoints.
- If all pass, fire alert (`signal_type="MACRO_DRIFT"`, direction="long", ticker="SPY"); write `macro_signals` row with `signal_name="pre_fomc_long_active"`.
- A3: ALWAYS log gate-pass count to `pipeline_metrics` for `pre_fomc_gate_passed` and `pre_fomc_gate_blocked` keys, regardless of fire decision (calibration logging).
- Exit job (separate timer) at FOMC day 14:00 ET: edit prior alert with realised P/L; clear `macro_signals` row.

**File path:** `consensus_engine/scanners/fomc_drift.py` (NEW).

**Reuses:**
- `engine.FinnhubAdapter` (`engine.py:308` style for `/quote`).
- `analysis/indicators.py` (existing helpers used by `analysis/technical.py:243`).
- `utils/rate_limiter.py:29` (`finnhub` and new `yfinance` S8 lane).
- `utils/freshness_gate.py` (S5).
- `db.py` (`macro_signals` insert).
- `alerts/discord.py:316, :366`.
- `main.py:455–476` (`macro_digest_loop`).

**LOC estimate:** ~180 LOC.

---

### F4 — FRED Credit-Equity Divergence (HYG vs SPY + HY OAS)

**Purpose:** EOD daily computation: `gap_20d = SPY_20d_return − HYG_20d_return`. Bearish trigger when `gap_20d > 2σ` over 252-day baseline AND HYG < SMA(HYG, 50) AND SPY ≥ SMA(SPY, 50) for ≥2 sessions. Confirmation via FRED `BAMLH0A0HYM2` (HY OAS) and LQD weakness.

**Inputs:**
- FRED `BAMLH0A0HYM2` (HY OAS) — NEW key per S7.
- yfinance OHLCV for SPY, HYG, LQD (via S8).
- S&P 500 constituent membership for A1 breadth filter (one-time YAML / weekly refresh).
- Existing `analysis/indicators.py` for SMA / σ.
- `macro_signals` table (writes own state).

**Outputs:**
- Row in `macro_signals` table with `signal_name="credit_equity_bearish"`, consumed by `_get_macro_context` (S9).
- NO standalone alert (per `33-final-feature-set.md` Section 3 Feature 4: "Instant-trigger eligibility: NO — regime/macro signal").
- Optional thesis-only embed in Phase-2 followups when active.

**Core logic:**
- Run once per day at 16:30 ET (post-close) inside `macro_digest_loop`.
- S5 freshness gate: yfinance HYG/SPY/LQD must be ≤ 1 trading-session stale; FRED HY OAS likewise.
- Compute `gap_20d` = SPY 20d return − HYG 20d return.
- 252d rolling baseline excluding most-recent 20 days for σ.
- Trigger: `gap_20d > 2σ` AND HYG < SMA(HYG, 50) AND SPY ≥ SMA(SPY, 50) AND HY OAS rising.
- Suppress if `correlation(HYG, SPY, 60d) > +0.85`.
- A1 breadth filter: only fire when ≥60% of S&P 500 constituents trade above 50d-SMA.
- Persist to `macro_signals` with `signal_name="credit_equity_bearish"`, `started_at=now`, `regime_label`.
- A2 stratified-backtest hook: bucket fires into "broad-participation" vs "concentrated" via the same 60% breadth metric for kill-criterion analysis.
- FRED-dark fallback: if FRED key missing or stale, demote to ETF-only (HYG/SPY/LQD) and append `confidence_degraded=True` to row.

**File path:** `consensus_engine/scanners/credit_equity_divergence.py` (NEW).

**Reuses:**
- `analysis/indicators.py` (SMA, σ).
- `utils/rate_limiter.py:29` (S8 yfinance).
- `utils/freshness_gate.py` (S5).
- `db.py` (`macro_signals` insert).
- `main.py:455–476` (`macro_digest_loop`).

**LOC estimate:** ~200 LOC.

---

### F5 — Volume-Confirmed N-Day Breakout with ATR Levels (analysis util)

**Purpose:** Compute volume-confirmed breakout with ATR-based targets. Fire when `close > rolling_max(close, N)` for N ∈ {20, 60, 252} AND dollar-volume ≥ 2.0× 20d mean (2.5× for low-float) AND `close > VWAP_anchored from prior pivot-low` AND BBwidth(20, 2σ) > 30th percentile of trailing 252d.

**Inputs:**
- yfinance OHLCV for the ticker universe (via S8).
- Bounded universe per B's hardening: top-N from ApeWisdom + tickers with active TweetShift hits in last 24h.
- `analysis/indicators.py` for ATR(14), BBwidth, VWAP_anchored.
- Earnings calendar (via S4 / `earnings_calendar.py`) for A2 in-module suppression.
- VIX from F3's poll for the absolute-kill check (`VIX > 35`).

**Outputs:**
- Phase-1 alert via `send_instant_ping` with `signal_type="TECHNICAL_BREAKOUT"`, payload contains `entry`, `target_1`, `target_2` ONLY (NO stop per C4).
- `signal_events` row with SourceType `TECHNICAL_BREAKOUT`.
- Per-ticker, per-N-tier 24h cooldown.

**Core logic:**
- Run from inside `fetch_loop` (`main.py:369–380`) every 300 s.
- For each ticker in bounded universe:
  - S5 freshness check on yfinance OHLCV.
  - Compute `rolling_max(close, N)` for N in {20, 60, 252}.
  - For N=20: A1 require `close > rolling_max(close, 20)` for 2 consecutive sessions before firing.
  - Volume check: dollar-volume ≥ 2.0× 20d mean (raise to 2.5× if shares_out < 50M); C1 require dollar volume ≥ $10M absolute floor.
  - VWAP-anchored check: `close > VWAP_anchored` from prior pivot-low.
  - BBwidth check: BBwidth(20, 2σ) > 30th percentile of trailing 252d.
  - ADX(14) > 22 (for N=20 only).
  - C2 hard market-cap floor ≥ $500M.
  - C3 abnormal-late-session-volume check: prior 5 sessions' last-hour-vs-first-5h volume ratio < 0.45 each.
  - A2 earnings suppression: query S4 calendar — if `next_earnings_in_days <= 1 OR last_earnings_in_days <= 2`, suppress.
  - VIX gate: VIX < 35 (raised from 28 per A3); absolute kill when VIX ≥ 35.
- C5 30-min post-close delay: queue all qualifying breakouts with `eligible_at = market_close + 30min`; only fire after AH price corroborates the breakout (close + AH price still above `rolling_max`).
- Daily quotas: ≤20 alerts for N=20, ≤5 for N=60, ≤3 for N=252 (config-driven).
- Compute `target_1 = close + 1.5 × ATR(14)`, `target_2 = close + 3.0 × ATR(14)`.
- Per-ticker dedup: 24h cooldown on same ticker for same-N tier (uses S3 generalised cooldown).

**File path:** `consensus_engine/analysis/breakout_atr.py` (NEW; analysis util reusable across scanners).

**Reuses:**
- `analysis/indicators.py` (ATR, BBwidth, VWAP).
- `analysis/technical.py:243` (`verify_technical` shape — ADX hook already present).
- `utils/rate_limiter.py:29` (S8 yfinance).
- `utils/freshness_gate.py` (S5).
- `scanners/earnings_calendar.py:25–47` (A2 suppression).
- `alerts/discord.py:316`.
- `db.py:602` (signal_events).
- `main.py:369–380` (`fetch_loop`).

**LOC estimate:** ~200 LOC.

---

### F6 — Earnings-Window Risk Gate (extends `earnings_calendar.py` + `catalyst_resolver.py`)

**Purpose:** For every ticker that surfaces from any engine, look up next earnings date and tag the signal with one of `pre_earnings_T-N`, `into_earnings`, `post_earnings_T+N`, or `clear`. Apply 0.6× confidence multiplier in T-3 to T+1 window (NOT hard suppress).

**Inputs:**
- Finnhub `/calendar/earnings` (existing primary path).
- yfinance fallback (existing — secondary).
- 8-K Item 2.02 invalidation hook from any 8-K detection.
- Tweet density signal from `db.py.get_signal_counts_by_source`.

**Outputs:**
- New `breakdown.macro_context_modifier` field on `ScoreBreakdown` (via S9 path) — NOT a separate alert.
- Annotation in `send_detail_followup` (`alerts/discord.py:471–507`) showing gate status.
- Cached earnings dates with 7-day TTL.

**Core logic:**
- Extend `analysis/catalyst_resolver.py:142–172` (`_verify_earnings`) into `analysis/earnings_gate.py` companion:
  - B1: drop `api.nasdaq.com` from primary path; tertiary fallback only when Finnhub + yfinance disagree.
  - B2: 7-day TTL on cached dates; `8-K Item 2.02` hit on the ticker invalidates cache.
  - C1: Finnhub-curated date wins over self-disclosed pre-announce date.
  - C2: when ticker is in T-3 to T+1 window, multiplier = 0.6× (NOT hard suppress).
  - C3 tweet-density override: if tweet volume for ticker > 10× normal in window, treat as evidence of additional event (M&A, etc.); reset multiplier to 1.0.
  - Cross-source mismatch ≥ 2 days → label `uncertain` (multiplier = 0.7×, fail-closed direction).
- Hook into `cross_reference.py:333`: `earnings_gate.evaluate(ticker)` returns `(label, multiplier)`; multiplier added to `breakdown.macro_context_modifier` (combined multiplicatively with S9's macro context).
- Alert text: `send_detail_followup` appends "Earnings: T-2 (0.6× confidence applied)" line.

**File paths:**
- Extend: `consensus_engine/scanners/earnings_calendar.py` (+30 LOC for cache TTL + 8-K invalidation hook).
- Extend: `consensus_engine/analysis/catalyst_resolver.py:179–197` (S4 generalisation).
- New companion: `consensus_engine/analysis/earnings_gate.py` (~80 LOC). NOTE: deliberate split — S4 owns calendar plumbing, earnings_gate owns the modifier policy.

**Reuses:**
- `scanners/earnings_calendar.py:25–47` (`fetch_earnings_calendar`).
- `analysis/catalyst_resolver.py:142–172` (`_verify_earnings`).
- `cross_reference.py:333` (consumption hook).
- `alerts/discord.py:471–507` (`send_detail_followup`).
- `db.py.get_signal_counts_by_source` (tweet-density override).

**LOC estimate:** ~110 LOC across the three files (extend + new companion).

---

### F8 — New 13D Activist + 13G→13D Conversion

**Purpose:** Two-leg feature. (a) Standalone alert when new Schedule 13D appears AND filer is on `activist_whitelist.yaml` (≥2 prior outcome-weighted campaigns) AND Item 4 contains specific actionable language. (b) Flag 13G→13D conversion; standalone ONLY when paired with concurrent action (press release ±24h, options >3σ, OR known-activist tweet ±48h).

**Inputs:**
- SEC EDGAR `getcurrent` ATOM for type=SC 13D and type=SC 13G/A.
- `submissions.json` for filer history backfill (one-time via `scripts/backfill_activist_history.py`).
- `holder_intent` table (NEW per S7).
- `activist_whitelist.yaml` (NEW manual curation).
- `news_cascade` (`scanners/news.py:279`).
- `options.py:89` (`check_unusual_options`).
- TweetShift signals via `signal_events` for known-activist tweet detection.
- LLM scorer fallback `analysis/llm_scorer.py:102` for B2 regex-fallback intent classification.

**Outputs:**
- Phase-1 alert via `send_instant_ping` with `signal_type="ACTIVIST_FILING"` (only when whitelist + verbiage gates pass).
- `signal_events` row with SourceType `ACTIVIST_FILING`.
- `holder_intent` row updates filer-issuer relationship.

**Core logic:**
- Background loop polls `getcurrent` ATOM at jittered :40 of every minute (per S1) every 300 s.
- For each new 13D/13G accession: `acquire("sec_edgar")`, fetch filing.
- Item 4 regex match for: named director nominee, specific tender/proxy threat, named transaction-counterparty.
- C1 co-filer dedup: same-day multi-CIK filings on same target = one filer (key on `(filer_group, target_cik, filing_date)`).
- C5 whitelist check: `filer_cik` in `activist_whitelist.yaml`. Newcomers downgrade to xref-only.
- C2 verbiage check: regex hits required for standalone; soft-engagement-only verbiage → xref-only.
- C4 outcome-weighted history: query `holder_intent` for `filer_cik` campaigns; weight by `(settlement_or_vote_outcome ? 1.0 : 0.3)`. ≥2 weighted campaigns required for standalone.
- B2 regex fallback: when filer is whitelisted but regex returns 0 hits, call `llm_scorer.score_confidence()` for intent classification (consumes existing LLM budget).
- 13G→13D conversion path: query prior 13G by same filer-target; if found, downgrade to xref-only UNLESS one of: news ±24h, options >3σ, known-activist tweet ±48h.

**File path:** `consensus_engine/scanners/sec_activist_13d.py` (NEW).

**Reuses:**
- `scanners/sec_edgar.py:39, 64–141` (HTTP plumbing, ticker map).
- `scanners/sec_watcher.py` (ATOM parser pattern).
- `analysis/llm_scorer.py:102` (B2 fallback).
- `scanners/news.py:279`, `scanners/options.py:89` (concurrent-action checks).
- `utils/rate_limiter.py:29` (S1).
- `alerts/discord.py:316`.
- `db.py:602` (signal_events).

**LOC estimate:** ~280 LOC (significant new module: scanner loop ~80, item-4 classifier + LLM fallback ~70, whitelist check ~30, outcome-weighted history query ~50, 13G→13D conversion + concurrent-action gate ~50).

---

### F10 — Wikipedia Pageview Spike

**Purpose:** Pull hourly pageviews for ticker's Wikipedia article; flag z ≥ 2.5 vs 28-day weekday-matched baseline. Use as +0.05 max confidence-multiplier on tweet-driven or breakout-driven primary signals (annotation-only).

**Inputs:**
- Wikimedia REST API (`https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{lang}/{project}/all-access/{agent}/{article}/{granularity}/{start}/{end}`).
- `ticker_external_ids` table (NEW per S7) mapping ticker → Wikipedia article slug.
- OpenFIGI API (one-time backfill seed).
- `signal_events` for Google Trends (existing P0 row 7) co-confirmation read.

**Outputs:**
- `signal_events` row with SourceType `WIKIPEDIA_ATTENTION`.
- NO standalone alert (annotation-only, per `33-final-feature-set.md`: "Instant-trigger eligibility: NO").
- Annotation in `send_detail_followup` body when active for the ticker.

**Core logic:**
- One-time backfill (`scripts/backfill_wikipedia_articles.py`): for each ticker in `ticker_metadata`, query OpenFIGI + Wikidata to resolve canonical article slug; B2 verify infobox contains the ticker.
- Hourly poll (queued from inside `fetch_loop`'s 300s tick — every 12th tick triggers a Wikipedia pass).
- 1-hour TTL cache per article-slug.
- 28-day weekday-matched baseline cached per slug (recomputed daily, NOT every alert).
- Compute z-score: current_hour vs same-weekday-hour baseline mean.
- C2 sustained-spike requirement: z ≥ 2.5 must hold for ≥3 consecutive hours.
- A1 cap floor: only run for tickers with $200M ≤ market_cap ≤ $5B.
- A2 saturation penalty: if prior-week elevation z>2 (already-saturated), reduce contribution.
- C1 co-confirmation gate (MANDATORY for any boost): query `signal_events` for Google Trends signal in same hour AND same direction. If absent → write the spike row but contribute zero score boost.
- Cap contribution at +0.05 (5% of score) regardless of magnitude.
- User-Agent header: `consensus_engine/1.0 (+https://github.com/chopra2007/openclaw; ak@openclaw.dev)`.

**File path:** `consensus_engine/scanners/wikipedia_pageviews.py` (NEW).

**Reuses:**
- `utils/rate_limiter.py` (new lane `wikipedia: 1.0` if needed; modest traffic).
- `db.py:602` (signal_events).
- `db.py.get_signal_counts_by_source` (Google Trends co-confirmation).
- `alerts/discord.py:471–507` (annotation in followup).
- `main.py:369–380` (`fetch_loop`).

**LOC estimate:** ~150 LOC (backfill logic in separate ~100 LOC script).

---

### F11 — Reg SHO Threshold List Entry

**Purpose:** Daily-poll Reg SHO threshold security lists from NASDAQ, NYSE, Cboe. Diff today vs yesterday. Standalone Phase-1 alert ONLY for >$2B cap during stress regime (VIX>22 AND HY OAS>350bps); >$3B cap when stacked with F8 13D within 14 days.

**Inputs:**
- NASDAQ daily threshold file: `https://www.nasdaqtrader.com/dynamic/symdir/regsho/nasdaqthYYYYMMDD.txt`.
- NYSE redirect: `https://www.nyse.com/regulation/regulation-sho` (with B2 hard-coded redirect URL).
- Cboe equivalent.
- `macro_signals` table (S7) for A2 regime gate (VIX, HY OAS — written by F4 + F3 paths).
- DB `signal_events` to detect F8 stack within 14 days.

**Outputs:**
- Phase-1 alert via `send_instant_ping` with `signal_type="REG_SHO"` (only when regime + cap gates pass).
- `signal_events` row with SourceType `REG_SHO`.
- B1 cumulative-day-count metadata in row.

**Core logic:**
- Run from inside `macro_digest_loop` neighbourhood (`main.py:455–476`); daily cadence at 18:00 ET.
- For each list source: `acquire("sec_edgar")` or new `nasdaq_trader` lane (no auth); fetch with S5 freshness gate.
- HTTP 404 = "file not yet posted" → retry in 30 min, no error log spam (B3).
- B2 NYSE redirect: hard-code redirected URL; verify via S6 GET-as-HEAD.
- Ticker normalization (BRK.B / BRK B / BRK-B) via shared helper.
- B1 cumulative-entry-day-count: maintain `reg_sho_history` table — increment on each appearance, reset on absence.
- Diff today vs yesterday: new entries → candidate alerts.
- Liquidity gate: market cap ≥ $2B (from `ticker_metadata`).
- A2 regime gate: query `macro_signals` for `vix > 22 AND hy_oas > 350bps`. If false → `signal_events` only (xref-only).
- A3 stack rule: query `signal_events` for F8 `ACTIVIST_FILING` on same ticker within 14 days; if found, require market cap ≥ $3B.
- A3 alternate stack: F1 `INSIDER_CLUSTER` within 14 days qualifies as second source for the same gate.
- Alert dedup: per-ticker per-list 7-day cooldown (uses S3 generalised cooldown).

**File path:** `consensus_engine/scanners/reg_sho_threshold.py` (NEW).

**Reuses:**
- `utils/rate_limiter.py` (new `nasdaq_trader: 0.5` lane).
- `utils/http.py` (S6 GET-as-HEAD).
- `utils/freshness_gate.py` (S5).
- `db.py:602` (signal_events).
- `alerts/discord.py:316`.
- `main.py:455–476` (`macro_digest_loop`).

**LOC estimate:** ~180 LOC.

---

### S1 — Shared SEC EDGAR semaphore

**Purpose:** Aggregate fair-use 10 req/s ceiling across `data.sec.gov`, `www.sec.gov/cgi-bin`, `efts.sec.gov`. Without this, F1+F2+F8+existing `_run_sec_check` can co-burst at minute boundaries → 10-min IP block silences every SEC-touching path.

**Inputs:** Existing `utils/rate_limiter.py:29` (`sec_edgar: 0.2` = 5 req/s).

**Outputs:** Tighter `sec_edgar: 0.15` (≈6.67 req/s, leaves headroom). Audited compliance across all SEC-touching code paths. Per-feature jittered start offsets in poll loops (F1 :00, F2 :20, F8 :40 of every minute).

**Core logic:**
- Tighten `sec_edgar` interval from 0.2 to 0.15 in `_min_intervals` dict (`utils/rate_limiter.py:29`).
- Audit existing call sites: `scanners/sec_edgar.py:39, 64–141, 173–302`; `scanners/sec_watcher.py:38–155`. Confirm every HTTP request to `*.sec.gov` is preceded by `await rate_limiter.acquire("sec_edgar")`.
- Add jittered start offset helper: scanners/insider_cluster.py uses `loop.run_in_offset(seconds=0)`, sec_ma_filings.py at `seconds=20`, sec_activist_13d.py at `seconds=40`, computed from minute boundary.
- Document in `consensus_engine/scanners/CLAUDE.md` (NEW guidance file or extend existing project CLAUDE.md).

**File path:** `consensus_engine/utils/rate_limiter.py` (EXTEND — line 29 dict change).

**Reuses:** Existing `acquire()` machinery (`rate_limiter.py:36–61`).

**LOC estimate:** ~30 LOC (config tighten + audit assertions + jitter helper) + ~20 LOC across the three new scanner loops to consume the offset.

---

### S2 — Correlation-decay penalty at xref aggregation

**Purpose:** Defend against cross-feature noise-injection attacks (X1–X5 from `33-final-feature-set.md` Section 5). Composite scoring assumes approximate independence between SourceTypes; correlated noise across 2–3 features simultaneously is the lowest-cost adversarial path.

**Inputs:**
- `signal_events` rows in trailing 24h window (`db.py.get_signal_events_for_ticker`).
- Filer-CIK age + sock-puppet-account-age (read from filer registration / `holder_intent`).

**Outputs:** Multiplicative penalty applied to `breakdown.total` BEFORE LLM scoring, capped at `[0.20, 1.00]`. Logged in `pipeline_metrics` with key `xref_correlation_penalty`.

**Core logic:**
- New module function `compute_correlation_penalty(ticker, signal_events) -> float`.
- For each ticker-window (24h):
  - `n_active_sources` = count of distinct SourceTypes contributing in window.
  - `suspicious_correlation_factor` accumulates additively:
    - same-direction-in-<12h: +0.30 base.
    - low-trust-tier source after the first (e.g. `WIKIPEDIA_ATTENTION`, news-velocity proxies, TweetShift-cluster repeats): +0.20 per such source.
    - filer CIK age <90 days OR account age <90 days: +0.40 per such source.
  - `penalty = max(0, n_active_sources − 2) × suspicious_correlation_factor`.
  - `final_score *= max(0.20, 1.0 − penalty)`.
- Apply at xref aggregation: invoked from `cross_reference.py:333` immediately after `signal_events` read on `:328–332`, before the existing `cache_xref` call on `:320`.
- Skip when fewer than 2 active SourceTypes in window (no penalty when no correlation possible).
- Macro/index features (F3, F4) feed into `_get_macro_context` (S9) instead of the per-name aggregation, so they do not contribute to `n_active_sources` in S2's calculation.

**File path:**
- New: `consensus_engine/analysis/correlation_decay.py`.
- Hook: `consensus_engine/cross_reference.py:333` (call site immediately after the `signal_events` read).

**Reuses:**
- `db.py.get_signal_events_for_ticker` (`db.py:` `signal_events` read; called from `cross_reference.py:329`).
- `models.py.ScoreBreakdown` (the computed penalty multiplies `breakdown.total`).

**LOC estimate:** ~150 LOC (per C's estimate; ~80 module + ~30 hook + ~40 fixture-friendly accessors).

---

### S3 — Generalised per-analyst cooldown (audit M3)

**Purpose:** Close `kpak82` 26-min cooldown race at `db.py:672` (`check_alert_cooldown` parallel-read race, per audit). Generalise the existing per-analyst path to also gate per-source for the new instant-trigger features.

**Inputs:** `source_performance` table (existing); `alert_history` table (existing); the new SourceTypes from S7.

**Outputs:** Bug-fixed `check_alert_cooldown` callable from F1, F2, F3, F5, F8, F11.

**Core logic:**
- Audit M3 fix: replace the parallel-read sequence in `db.py:714–781` with a single transactional read using `BEGIN IMMEDIATE` + `WHERE NOT EXISTS` insert pattern. The race occurs because two coroutines both observe the same `cnt=0` and both pass cooldown.
- Generalise the analyst slot to a `(ticker, source_type, source_detail)` triple. For TWITTER signals, `source_detail` remains the analyst handle (preserves existing behaviour). For new SourceTypes, `source_detail` becomes filer_cik (F1, F2, F8), or "REG_SHO_LIST" (F11), etc.
- Continue to honour `floor_minutes`, `cooldown_hours`, and `high_conviction_bypass` flags.
- Continue to read `source_performance` for precision-scaled cooldown when sample_count ≥5.
- Add metric `cooldown_blocked_total{source_type}` to `pipeline_metrics`.

**File path:** `consensus_engine/db.py` EXTEND (lines 714–781). New helper `_atomic_cooldown_check` near the `check_alert_cooldown` body.

**Reuses:** `db.py.get_analyst_precision` (`:700`); existing `source_performance` queries.

**LOC estimate:** ~80 LOC (per audit calibration: M3 cooldown ~80 LOC).

---

### S4 — Calendar resolver consolidation

**Purpose:** Cluster D from P2 — consolidate FOMC, earnings, and Reg SHO publish-date calendars into a single resolver. Used by F3 (FOMC), F5/F6 (earnings), F11 (Reg SHO publish day-of-week).

**Inputs:**
- `config/fomc_calendar.yaml` (NEW; weekly-refreshed via S4's calendar-staleness loop).
- Finnhub `/calendar/earnings` (existing primary, per F6 B1).
- yfinance fallback (F6).
- Reg SHO publish cadence (B-D file daily; baked-in cadence rules).

**Outputs:**
- Generalised `events_calendar` interface; sub-implementations per event type.
- Daily-cadence calendar-staleness check: compare next-event date to "now". If next-event within 30 days but YAML last-refreshed >7 days ago for FOMC, emit `source_health` alert.

**Core logic:**
- Extend `analysis/catalyst_resolver.py:179–197` (`resolve_and_verify_catalysts`) into a multi-event interface:
  - `resolve(event_type: Literal["fomc", "earnings", "reg_sho_publish"], ticker: str | None = None)`.
- FOMC sub-impl: read `config/fomc_calendar.yaml`; weekly refresh via background job inside `macro_digest_loop`. Fail-closed if YAML age > 7 days for upcoming-week resolution.
- Earnings sub-impl: keep existing `_verify_earnings` (`catalyst_resolver.py:142–172`) but route through Finnhub-first hierarchy per F6 B1 (drop Nasdaq from primary path).
- Reg SHO sub-impl: known publish cadence (NASDAQ daily file at ~17:00 ET); next-publish prediction.
- Add `is_within_window(event_type, ticker, days_before, days_after) -> bool` predicate consumed by F5 + F6.
- Add `is_calendar_fresh(event_type) -> bool` predicate consumed by F3 fail-closed gate.

**File path:** `consensus_engine/analysis/catalyst_resolver.py` (EXTEND); `config/fomc_calendar.yaml` (NEW); `scanners/earnings_calendar.py` minor (+30 LOC).

**Reuses:** Existing date logic (`catalyst_resolver.py:88–127` `_resolve_relative_date`); `_verify_earnings` (`:142–172`).

**LOC estimate:** ~150 LOC new + ~50 LOC extend existing.

---

### S5 — Data freshness gate

**Purpose:** A's S4 systemic concern — five macro/quant features (F3, F4, F5, F11) all depend on free public endpoints that historically degrade or break under exactly the stress conditions where the signals matter (Feb 2018, Mar 2020, Aug 2024). Without a shared freshness gate, signals fire on stale data with no false-positive protection.

**Inputs:** `source_health` table (existing); per-source max-age config (existing `config/consensus.yaml:178–183`).

**Outputs:** `is_fresh(source_id, max_age_seconds) -> bool` predicate. Fail-closed: when `False`, no signal fires (no false positive).

**Core logic:**
- New module `consensus_engine/utils/freshness_gate.py`.
- Read `source_health.last_heartbeat` for the source_id; compare to `time.time()`.
- Config defaults: macro signals `max_age_seconds=86400` (1 trading session); intraday confirmation `max_age_seconds=3600`.
- Per-feature override via dotted-config path `freshness_gate.<source>.max_age_seconds`.
- Each macro/quant feature consults `is_fresh()` BEFORE computing its signal; on `False` → no signal, log to `pipeline_metrics` as `freshness_block_<source>`.

**File path:** `consensus_engine/utils/freshness_gate.py` (NEW).

**Reuses:** `db.py.upsert_source_health` (called from `main.py:764`); `source_health` table.

**LOC estimate:** ~50 LOC (per A's estimate).

---

### S6 — HEAD-vs-GET health-check convention

**Purpose:** B's live-spot-check found EFTS rejects HEAD with `MissingAuthenticationTokenException` while accepting GET (AWS-API-Gateway). Any future watchdog using HEAD for liveness mis-classifies the source as down. Preventative for future SEC-cluster expansion (F9 was dropped, but the same pattern exists on AWS-gatewayed endpoints).

**Inputs:** Existing `utils/http.py` shared session.

**Outputs:** `health_check_get(url, timeout=5) -> bool` helper that uses GET with HEAD-equivalent semantics (`Range: bytes=0-0` or short body read).

**Core logic:**
- Extend `utils/http.py` (current 46 LOC) with a single helper:
  - `async def health_check_get(url, timeout=5.0) -> bool` — issues GET with `Range: bytes=0-0` header; treats HTTP 200, 206 as healthy.
- Document the rule: "All liveness probes must use `health_check_get`, never aiohttp HEAD, on AWS-gatewayed endpoints."
- F11 NYSE redirect probe + any future EFTS reintroduction consume this.

**File path:** `consensus_engine/utils/http.py` (EXTEND).

**Reuses:** Existing `get_session()` (`http.py:27`).

**LOC estimate:** ~20 LOC.

---

### S7 — Schema migration consolidation + FRED API key provisioning

**Purpose:** Land 9 new schema items + 7 new SourceType enum values + FRED key as a single atomic migration. Avoids partial-state failure during rollout.

**Inputs:** Existing `db.py:75–457` `SCHEMA` constant + `_run_column_migrations` pattern (`db.py:460–500`).

**Outputs:**
- New tables: `holder_intent`, `macro_signals`, `beneficial_owner_index`, `reg_sho_history`, `sector_antitrust_history`.
- New columns: `ticker_metadata.wikipedia_article_slug`, `ticker_metadata.openfigi_id`.
- New SourceType enum values: `INSIDER_CLUSTER`, `M_AND_A`, `MACRO_DRIFT`, `TECHNICAL_BREAKOUT`, `ACTIVIST_FILING`, `WIKIPEDIA_ATTENTION`, `REG_SHO`.
- FRED key documented in `/root/.openclaw/.env` and `MEMORY.md` reference index.

**Core logic:**
- New file `scripts/migrations/202604_phase2_features.sql` containing all CREATE TABLE / ALTER TABLE statements (DDL idempotent: `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE … ADD COLUMN` guarded by `PRAGMA table_info` like existing pattern at `db.py:496–500`).
- Extend `db.py.SCHEMA` (`:75`) with the five new tables.
- Extend `_run_column_migrations` (`db.py:460–500`) with the two new ticker_metadata columns.
- Extend `models.py:9–17` (`SourceType` enum) with the seven new values.
- Atomic migration: open DB, run the SQL script in single `executescript`, verify all SourceType values map to valid enums.
- Document FRED key load in `config/consensus.yaml:8–22` block (`api_keys` section); update CLAUDE.md global memory `reference_apis.md` per `MEMORY.md` index.

**File paths:**
- New: `scripts/migrations/202604_phase2_features.sql`.
- Extend: `consensus_engine/db.py` (~80 LOC: SCHEMA + migration helpers).
- Extend: `consensus_engine/models.py` (~10 LOC: enum + dataclass additions).

**Reuses:**
- Existing migration pattern at `db.py:460–500`.
- Existing `init_db()` flow at `db.py:534`.
- `cfg.get_api_key("fred")` pattern (will require adding FRED key to existing `config.py` env loader).

**LOC estimate:** ~200 LOC migration SQL + ~80 LOC SCHEMA / model extensions + ~10 LOC FRED key load + ~20 lines memory file update.

---

### S8 — Shared `yfinance` rate-limit string

**Purpose:** Yahoo Finance has tightened scraper rate limits twice since 2023. Three new features (F3, F4, F5) plus existing `price_outcome_loop` (`main.py:807–832`) and `analysis/technical.py:54` hit yfinance. Without coordination, simultaneous degradation is invisible to operators.

**Inputs:** Existing `utils/rate_limiter.py:29` dict.

**Outputs:** New `yfinance: 1.0` lane (1 req/s). Audited compliance across all yfinance call sites.

**Core logic:**
- Add `"yfinance": 1.0` to `_min_intervals` dict (`utils/rate_limiter.py:16–31`).
- Audit existing call sites: `main.py:807–832` (`price_outcome_loop`); `analysis/technical.py:54` (Yahoo `/v8/finance/chart`); `scanners/options.py:97–112` (option chains); `scanners/volume_scanner.py:65–82`. Wrap each with `await rate_limiter.acquire("yfinance")` if not already.
- Apply same wrap in new modules `scanners/credit_equity_divergence.py`, `analysis/breakout_atr.py`, `scanners/fomc_drift.py`.

**File path:** `consensus_engine/utils/rate_limiter.py` (EXTEND).

**Reuses:** Existing `acquire()` machinery.

**LOC estimate:** ~30 LOC config + audit assertions.

---

### S9 — Macro-context consumption pattern (`_get_macro_context`)

**Purpose:** A's S2 systemic concern. Three macro features (F3, F4, dropped F12) write to `macro_signals` as regime tags but `cross_reference` has no consumption pattern. Without explicit consumption, these features become dead code (cf. `regime_detector.py` per audit, zero callers despite check-in).

**Inputs:**
- `macro_signals` table (S7).
- Ticker sector / market-cap (existing `ticker_metadata`).

**Outputs:**
- New method `cross_reference._get_macro_context(ticker) -> MacroContext` returns multiplier and threshold adjustment.
- Applied at `cross_reference.py:333` (after the existing `signal_events` read at `:328–332`).
- Stored in `breakdown.macro_context_modifier` (NEW field on `ScoreBreakdown`).

**Core logic:**
- Read `macro_signals` for active rows: `(signal_name, started_at, regime_label)`.
- F4 `credit_equity_bearish` active AND ticker is cyclical/small-cap → confidence threshold +10pts (multiplier ≈ 0.9× to alert pass-rate).
- F3 `pre_fomc_long_active` AND ticker is cyclical → multiplier 0.85× (suppressing per-name alerts during macro-driven regime).
- Multiple active regimes combine multiplicatively.
- Sector classification: lightweight YAML at `config/sector_map.yaml` mapping ticker → GICS sector (one-time backfill from existing data; ~500 tickers).
- Default cyclical/small-cap: market_cap < $5B and sector in {Energy, Materials, Industrials, ConsumerDiscretionary, Financials}.

**File path:** `consensus_engine/cross_reference.py` (EXTEND — new method + call site at `:333`).

**Reuses:**
- `db.py` `macro_signals` read.
- `db.py` `ticker_metadata` read.
- `cross_reference.py:333` hook point (immediately after existing `signal_events` read).

**LOC estimate:** ~80 LOC.

---

## 3. Data Flow Pipeline

For each surviving feature, trace input → ingestion → signal emission → cross-reference contribution → score contribution → alert payload, citing P0 file:line. S1, S5, S6 hook points called out explicitly.

### F1 — Cluster Form 4 Open-Market Buys

| Stage | File:line |
|---|---|
| Input | SEC EDGAR `getcurrent` ATOM (type=4) every 300s |
| Ingestion entry | `scanners/insider_cluster.py` poll loop (NEW) wired alongside `main.py:343–347` SEC watchers gate; jittered start :00/min |
| S1 wrap | `await rate_limiter.acquire("sec_edgar")` before every fetch (`utils/rate_limiter.py:29` after S1 tighten to 0.15) |
| Form-4 fetch | `scanners/sec_edgar.py:173–302` (`fetch_form4_details`, reused) |
| Cluster query | `db.py` new query against `beneficial_owner_index` (S7) and rolling-14-day window |
| Signal emission | `db.py:602` (`signal_events` insert with SourceType `INSIDER_CLUSTER`) |
| Xref contribution | `cross_reference.py:328–332` reads via `db.get_signal_events_for_ticker(ticker, 3600)`; S2 penalty applied at `:333` |
| Score contribution | `breakdown.macro_context_modifier` via S9 if relevant; cluster fires its own standalone alert independent of xref |
| Cooldown gate (S3) | `db.check_alert_cooldown(ticker, source_detail=cluster_id)` at `db.py:714–781` (post-fix) |
| Alert payload | `alerts/discord.py:316` (`send_instant_ping`) with `signal_type="INSIDER_CLUSTER"` |
| Retract path | `alerts/discord.py:366` (`edit_instant_ping`) on 4/A within 5 days |

### F2 — SEC S-4 / 425 M&A

| Stage | File:line |
|---|---|
| Input | EDGAR `getcurrent` ATOM (type=425, type=S-4) every 300s |
| Ingestion entry | `scanners/sec_ma_filings.py` (NEW); jittered start :20/min via S1 |
| S1 wrap | `await rate_limiter.acquire("sec_edgar")` |
| Body parse | New regex + `submissions.json` CIK-age check (existing `sec_edgar.py:64–141` adapter) |
| Macro gates | `db.py` reads `macro_signals` for VIX>30, FOMC±48h |
| Second-source check | `cross_reference._run_news_cascade(ticker)` (`scanners/news.py:279–303`) ±15min, OR `scanners/options.py:89` (`check_unusual_options`), OR `signal_events` row INSIDER_CLUSTER trailing 14d |
| Signal emission | `db.py:602` (SourceType `M_AND_A`) — even when standalone gate fails |
| Cooldown gate (S3) | `db.check_alert_cooldown(ticker, source_detail=acquirer_cik)` |
| Alert payload | `alerts/discord.py:316` only when 2-source rule satisfied; antitrust regime tag appended in body |
| Withdrawal path | `alerts/discord.py:366` on 425/A within 7 days |

### F3 — Pre-FOMC Drift Trade

| Stage | File:line |
|---|---|
| Input | `config/fomc_calendar.yaml` (S4-managed); FRED EFFR + DGS2; Finnhub `/quote` SPY/VIX |
| Ingestion entry | `scanners/fomc_drift.py` (NEW), driven from inside `main.py:455–476` `macro_digest_loop` 60s tick |
| S5 freshness | `freshness_gate.is_fresh("finnhub", 60)` AND `is_fresh("fred", 86400)` BEFORE evaluating gates |
| S8 yfinance | `await rate_limiter.acquire("yfinance")` for VIX 5-session history + SPY auction-imbalance |
| Calendar staleness (S4) | `catalyst_resolver.is_calendar_fresh("fomc")` — fail-closed if YAML age > 7d |
| Gate evaluation | T-1 14:00 ET ±90s (C4 jitter); A1 + A2 + A3 + C1 + C2 + C3 |
| Signal emission | `db.py` insert into `macro_signals` with `signal_name="pre_fomc_long_active"` |
| Macro consumption (S9) | `cross_reference._get_macro_context(ticker)` at `cross_reference.py:333` reads `macro_signals` and applies 0.85× multiplier on cyclicals |
| Cooldown gate (S3) | `db.check_alert_cooldown("SPY", source_detail="MACRO_DRIFT")` |
| Alert payload | `alerts/discord.py:316` index-level; `signal_type="MACRO_DRIFT"`, ticker=SPY |
| Exit path | `alerts/discord.py:366` at FOMC day 14:00 ET with realised P/L |

### F4 — FRED Credit-Equity Divergence

| Stage | File:line |
|---|---|
| Input | FRED `BAMLH0A0HYM2` + yfinance HYG/SPY/LQD daily |
| Ingestion entry | `scanners/credit_equity_divergence.py` (NEW), driven from `main.py:455–476` `macro_digest_loop` (16:30 ET daily) |
| S5 freshness | `is_fresh("fred", 86400)` AND `is_fresh("yfinance", 86400)` |
| S8 yfinance | `acquire("yfinance")` for SPY/HYG/LQD pulls |
| Compute | `analysis/indicators.py` for SMA / σ / correlation |
| A1 breadth filter | `config/sp500_constituents.yaml` (S9-shared) for >60% above 50d-SMA |
| Signal emission | `db.py` insert into `macro_signals` with `signal_name="credit_equity_bearish"` |
| Macro consumption (S9) | `cross_reference._get_macro_context(ticker)` at `cross_reference.py:333` applies +10pt threshold on cyclicals/small-caps |
| Alert payload | NONE standalone — annotation only in `alerts/discord.py:471–507` (`send_detail_followup`) when active |

### F5 — Volume-Confirmed Breakout + ATR

| Stage | File:line |
|---|---|
| Input | yfinance OHLCV for bounded universe (top-N ApeWisdom + active TweetShift in 24h) |
| Ingestion entry | `analysis/breakout_atr.py` (NEW) called from inside `main.py:369–380` `fetch_loop` every 300s |
| S5 freshness | `is_fresh("yfinance", 3600)` per ticker |
| S8 yfinance | `acquire("yfinance")` per ticker pull |
| Earnings suppression (S4) | `catalyst_resolver.is_within_window("earnings", ticker, days_before=1, days_after=2)` — suppress if true |
| Compute | ATR(14), BBwidth(20,2σ), VWAP-anchored, ADX(14) via `analysis/indicators.py` |
| Cap floor | `utils/tickers.validate_ticker_market_cap` ≥$500M |
| Post-close delay (C5) | Queue with `eligible_at = market_close + 30min`; verify AH price corroboration |
| Signal emission | `db.py:602` (SourceType `TECHNICAL_BREAKOUT`) |
| Xref + S2 | `cross_reference.py:328–332` reads; S2 correlation penalty at `:333` defends X3 stop-hunting cooperation |
| Score contribution | `breakdown.technical` extends to capture ATR target levels metadata; `final_score` flows through `breakdown.total` |
| Cooldown gate (S3) | `check_alert_cooldown(ticker, source_detail=f"BREAKOUT_N{N}")` |
| Alert payload | `alerts/discord.py:316`; embed contains entry + target_1 + target_2 ONLY (NO stop per C4) |

### F6 — Earnings-Window Risk Gate

| Stage | File:line |
|---|---|
| Input | Finnhub `/calendar/earnings` (existing `scanners/earnings_calendar.py:25–47`); yfinance fallback |
| Ingestion entry | `analysis/earnings_gate.py` (NEW companion); invoked from `cross_reference.py:333` for every ticker that surfaces |
| S4 calendar | `catalyst_resolver.resolve("earnings", ticker)` returns next earnings date |
| 8-K invalidation | Hook at `scanners/sec_watcher.py:38–155` parser — when 8-K Item 2.02 for ticker, call `earnings_gate.invalidate_cache(ticker)` |
| Window classification | Compute label (`pre_earnings_T-N`, `into_earnings`, `post_earnings_T+N`, `clear`, `uncertain`) |
| Tweet-density override (C3) | `db.get_signal_counts_by_source(ticker)` — if 10× normal in window, multiplier=1.0 |
| Score contribution | Returned multiplier added to `breakdown.macro_context_modifier` (combined multiplicatively with S9 macro multiplier) |
| Alert payload | `alerts/discord.py:471–507` (`send_detail_followup`) appends "Earnings: T-2 (0.6× confidence)" line |

### F8 — 13D Activist + 13G→13D Conversion

| Stage | File:line |
|---|---|
| Input | EDGAR `getcurrent` ATOM (type=SC 13D, type=SC 13G/A) every 300s |
| Ingestion entry | `scanners/sec_activist_13d.py` (NEW); jittered start :40/min via S1 |
| S1 wrap | `await rate_limiter.acquire("sec_edgar")` |
| Filing fetch | `scanners/sec_edgar.py:64–141` HTTP plumbing reused |
| Whitelist check | `config/activist_whitelist.yaml` (NEW) gate for standalone eligibility |
| Item-4 classifier | Regex first; LLM fallback via `analysis/llm_scorer.py:102` (`score_confidence`) for whitelisted filers when regex misses |
| Concurrent action | `scanners/news.py:279`, `scanners/options.py:89`, `signal_events` for known-activist tweet |
| Signal emission | `db.py:602` (SourceType `ACTIVIST_FILING`); `holder_intent` row update |
| Xref + S2 | `cross_reference.py:328–332`; S2 penalty at `:333` defends X4 sock-puppet activist |
| Cooldown gate (S3) | `check_alert_cooldown(ticker, source_detail=filer_cik)` |
| Alert payload | `alerts/discord.py:316` only when whitelist + verbiage gates pass |

### F10 — Wikipedia Pageview Spike

| Stage | File:line |
|---|---|
| Input | Wikimedia REST API hourly pageviews |
| Ingestion entry | `scanners/wikipedia_pageviews.py` (NEW) called from `main.py:369–380` `fetch_loop` every 12th tick (~hourly) |
| Article-slug map | `ticker_metadata.wikipedia_article_slug` column (S7) seeded by `scripts/backfill_wikipedia_articles.py` |
| Z-score compute | 28-day weekday-matched baseline cached daily |
| Sustained-spike (C2) | Require ≥3 consecutive hours at z ≥ 2.5 |
| Co-confirmation (C1) | Read `db.get_signal_counts_by_source(ticker)` for `google_trends > 0` in same hour |
| Signal emission | `db.py:602` (SourceType `WIKIPEDIA_ATTENTION`) — always; boost only when C1 satisfies |
| Xref + S2 | `cross_reference.py:328–332` reads; S2 penalty at `:333` defends X5 brigade attack |
| Score contribution | Capped at +0.05 applied through `breakdown.llm_boost` channel (matches existing YouTube boost pattern at `cross_reference.py:295`) |
| Alert payload | NONE standalone; annotation only in `alerts/discord.py:471–507` |

### F11 — Reg SHO Threshold List Entry

| Stage | File:line |
|---|---|
| Input | NASDAQ daily threshold file; NYSE redirect; Cboe |
| Ingestion entry | `scanners/reg_sho_threshold.py` (NEW), driven from `main.py:455–476` neighbourhood at 18:00 ET daily |
| S5 freshness | `is_fresh("nasdaq_trader", 86400)` |
| S6 health-check | `utils/http.health_check_get(NYSE_URL)` for the redirect probe |
| Cumulative day-count (B1) | `reg_sho_history` table (S7) — increment / reset |
| Macro regime check | `db.py` reads `macro_signals` for VIX>22 AND HY OAS>350bps |
| F8 stack check | `db.get_signal_events_for_ticker(ticker, 14*86400)` — if SourceType `ACTIVIST_FILING` present, require $3B floor |
| F1 stack check | Same query, SourceType `INSIDER_CLUSTER` — qualifies as 2-source confirmation |
| Signal emission | `db.py:602` (SourceType `REG_SHO`) |
| Xref + S2 | `cross_reference.py:328–332`; S2 penalty at `:333` defends X2 squeeze-pressure stack |
| Cooldown gate (S3) | `check_alert_cooldown(ticker, source_detail="REG_SHO")` 7-day window |
| Alert payload | `alerts/discord.py:316` only for >$2B (or >$3B stacked) during stress regime |

### S1 wrap — call sites (existing + new)

| Call site | File:line |
|---|---|
| `check_recent_filings` | `scanners/sec_edgar.py:64–141` (existing) |
| `fetch_form4_details` | `scanners/sec_edgar.py:173–302` (existing) |
| 8-K ATOM watcher | `scanners/sec_watcher.py:38–155` (existing) |
| Xref `_run_sec_check` | `cross_reference.py:80–88` (existing) |
| F1 cluster poll | `scanners/insider_cluster.py` (NEW) |
| F2 425/S-4 poll | `scanners/sec_ma_filings.py` (NEW) |
| F8 13D/13G poll | `scanners/sec_activist_13d.py` (NEW) |

### S5 freshness gate — consumers

| Consumer | File:line | Source |
|---|---|---|
| F3 SPY/VIX `/quote` | `scanners/fomc_drift.py` | `finnhub` |
| F3 EFFR + DGS2 | `scanners/fomc_drift.py` | `fred` |
| F4 FRED HY OAS | `scanners/credit_equity_divergence.py` | `fred` |
| F4 yfinance HYG/SPY/LQD | `scanners/credit_equity_divergence.py` | `yfinance` |
| F5 yfinance OHLCV | `analysis/breakout_atr.py` | `yfinance` |
| F11 NASDAQ daily file | `scanners/reg_sho_threshold.py` | `nasdaq_trader` |

### S6 GET-as-HEAD — consumers

| Consumer | File:line | URL family |
|---|---|---|
| F11 NYSE redirect probe | `scanners/reg_sho_threshold.py` | `nyse.com/regulation/regulation-sho` |
| (Future) EFTS reintroduction | `consensus_engine/utils/http.py` | `efts.sec.gov` |

---

## 4. Data Structures

### 4.1 New / extended dataclasses (`models.py`)

```python
# consensus_engine/models.py — additions

class SourceType(str, Enum):
    # existing values preserved
    TWITTER = "twitter"
    REDDIT = "reddit"
    STOCKTWITS = "stocktwits"
    APEWISDOM = "apewisdom"
    GOOGLE_TRENDS = "google_trends"
    NEWS = "news"
    SEC_FILING = "sec_filing"
    YOUTUBE = "youtube"
    # NEW (S7)
    INSIDER_CLUSTER = "insider_cluster"        # F1
    M_AND_A = "m_and_a"                        # F2
    MACRO_DRIFT = "macro_drift"                # F3
    TECHNICAL_BREAKOUT = "technical_breakout"  # F5
    ACTIVIST_FILING = "activist_filing"        # F8
    WIKIPEDIA_ATTENTION = "wikipedia_attention"  # F10
    REG_SHO = "reg_sho"                        # F11
```

```python
# consensus_engine/models.py — ScoreBreakdown extension (NEW field)

@dataclass
class ScoreBreakdown:
    base: int = 0
    additional_analysts: int = 0
    news_catalyst: int = 0
    sec_filing: int = 0
    social_apewisdom: int = 0
    social_stocktwits: int = 0
    social_reddit: int = 0
    google_trends: int = 0
    technical: int = 0
    llm_boost: int = 0
    options_flow: int = 0
    # NEW (S9 + F6)
    macro_context_modifier: float = 1.0  # multiplicative; 1.0 = no effect
    # NEW (S2)
    correlation_penalty: float = 1.0     # multiplicative; 1.0 = no penalty

    @property
    def total(self) -> int:
        raw = (self.base + self.additional_analysts + self.news_catalyst
               + self.sec_filing + self.social_apewisdom + self.social_stocktwits
               + self.social_reddit + self.google_trends + self.technical
               + self.llm_boost + self.options_flow)
        # Apply macro context, then correlation penalty; both bounded above 0.20.
        adjusted = raw * max(0.20, self.macro_context_modifier) \
                       * max(0.20, self.correlation_penalty)
        return int(adjusted)
```

How this merges with the existing scoring object: `ScoreBreakdown` is the one place all multipliers concentrate. The existing `breakdown.total` property at `models.py:255–260` is replaced with the multiplier-aware variant above. The two new fields are float-typed so the existing `int()` cast at `models.py:286` (`final_score`) preserves the int contract on the outer `CrossReferenceResult.final_score`.

```python
# consensus_engine/models.py — new dataclasses for the Phase-2 features

@dataclass
class InsiderClusterSignal:                      # F1
    ticker: str
    issuer_cik: str
    cluster_id: str                              # hash of (issuer_cik, window_start)
    insiders: list[str]                          # filer CIKs (deduped via beneficial_owner_index)
    total_dollars: float
    weighted_rank_score: float
    z_scores: list[float]                        # one per insider
    detected_at: float = field(default_factory=time.time)


@dataclass
class MAFilingSignal:                            # F2
    ticker: str
    target_cik: str
    acquirer_cik: str
    accession_number: str
    filing_type: str                             # "425" or "S-4"
    offer_per_share: Optional[float]
    deal_consideration: Optional[str]            # "cash" | "stock" | "mixed"
    standalone_eligible: bool                    # True iff 2-source rule satisfied
    detected_at: float = field(default_factory=time.time)


@dataclass
class MacroDriftSignal:                          # F3
    signal_name: str                             # "pre_fomc_long_active"
    direction: str                               # "long" | "short"
    underlying: str                              # "SPY" or "QQQ"
    started_at: float
    expires_at: float                            # FOMC day 14:00 ET
    gate_pass: dict[str, bool]                   # logged for calibration


@dataclass
class CreditEquitySignal:                        # F4
    signal_name: str                             # "credit_equity_bearish"
    gap_20d: float
    sigma: float
    hy_oas_bps: float
    breadth_pct: float                           # >0.60 required for fire
    correlation_60d: float                       # <0.85 required
    started_at: float
    confidence_degraded: bool = False            # FRED-dark fallback flag


@dataclass
class BreakoutSignal:                            # F5
    ticker: str
    n_window: int                                # 20, 60, or 252
    entry: float
    target_1: float                              # entry + 1.5 * ATR(14)
    target_2: float                              # entry + 3.0 * ATR(14)
    atr_14: float
    dollar_volume: float
    bb_width_pctile: float
    eligible_at: float                           # post-close + 30 min
    detected_at: float = field(default_factory=time.time)


@dataclass
class ActivistFilingSignal:                     # F8
    ticker: str
    filer_cik: str
    accession_number: str
    filing_type: str                             # "13D" or "13G/A_to_13D"
    pct_stake: Optional[float]
    item4_classification: str                    # "specific" | "engagement" | "ambiguous"
    whitelisted: bool
    standalone_eligible: bool
    detected_at: float = field(default_factory=time.time)


@dataclass
class WikipediaAttentionSignal:                  # F10
    ticker: str
    article_slug: str
    z_score: float
    sustained_hours: int                         # ≥3 to qualify
    google_trends_co_confirm: bool               # mandatory C1 gate
    detected_at: float = field(default_factory=time.time)


@dataclass
class RegSHOSignal:                              # F11
    ticker: str
    list_source: str                             # "NASDAQ" | "NYSE" | "Cboe"
    cumulative_day_count: int
    market_cap: float
    stress_regime_active: bool                   # VIX>22 AND HY_OAS>350
    f8_stack_present: bool                       # F8 within 14d
    f1_stack_present: bool                       # F1 within 14d
    detected_at: float = field(default_factory=time.time)
```

Each of the above is persisted into `signal_events` as the canonical scoring-time row (`db.py:602`); the dataclass instances live only in-process during the scanner cycle, then the salient fields are flattened into `signal_events.source_detail` (JSON). This matches the existing pattern where `ParsedTweet` lives in-process and only the relevant fields land in `ticker_signals` / `signal_events`.

### 4.2 DB schema additions

All schema additions ship as a single atomic migration `scripts/migrations/202604_phase2_features.sql`, run by extending `db.py:534` `init_db()` flow alongside the existing `_run_column_migrations` (`db.py:460–500`) pattern. Migration is idempotent — re-running on an already-migrated DB is a no-op.

```sql
-- F1: beneficial_owner_index — fuzzy multi-CIK merge for Form-4 filers
CREATE TABLE IF NOT EXISTS beneficial_owner_index (
    owner_id        TEXT PRIMARY KEY,           -- canonical hash of (name, address)
    name            TEXT NOT NULL,
    address_hash    TEXT,
    cik_list        TEXT NOT NULL,              -- JSON array of associated CIKs
    last_seen       REAL NOT NULL,
    sample_count    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_boi_name ON beneficial_owner_index(name);

-- Retention: NEVER prune (stable mapping; ~10k rows lifetime)

-- F4 + F3 + F11: macro_signals — regime tags consumed by S9
CREATE TABLE IF NOT EXISTS macro_signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_name     TEXT NOT NULL,              -- "pre_fomc_long_active" | "credit_equity_bearish" | …
    direction       TEXT,                       -- "long" | "short" | NULL for non-directional
    payload_json    TEXT NOT NULL,              -- feature-specific fields
    started_at      REAL NOT NULL,
    expires_at      REAL,                        -- NULL = explicit clear required
    cleared_at      REAL,
    confidence_degraded INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_macro_signals_name ON macro_signals(signal_name);
CREATE INDEX IF NOT EXISTS idx_macro_signals_started ON macro_signals(started_at);
CREATE INDEX IF NOT EXISTS idx_macro_signals_active ON macro_signals(signal_name, cleared_at);

-- Retention: keep 90 days; pruned in db.prune_expired (extend the existing pattern at db.py:808–817)

-- F8: holder_intent — activist filer history per (filer, target)
CREATE TABLE IF NOT EXISTS holder_intent (
    filer_cik       TEXT NOT NULL,
    issuer_cik      TEXT NOT NULL,
    first_filing_at REAL NOT NULL,
    last_filing_at  REAL NOT NULL,
    campaign_count  INTEGER NOT NULL DEFAULT 1,
    outcome_weight  REAL NOT NULL DEFAULT 0.3,  -- updated by manual curation
    last_outcome    TEXT,                       -- "settled" | "vote" | "withdrawn" | "ongoing"
    PRIMARY KEY (filer_cik, issuer_cik)
);
CREATE INDEX IF NOT EXISTS idx_holder_intent_filer ON holder_intent(filer_cik);

-- Retention: NEVER prune (durable history; ~1M row ceiling)

-- F11: reg_sho_history — cumulative day-count for B1 publication-delay handling
CREATE TABLE IF NOT EXISTS reg_sho_history (
    ticker          TEXT NOT NULL,
    list_source     TEXT NOT NULL,              -- "NASDAQ" | "NYSE" | "Cboe"
    cumulative_days INTEGER NOT NULL DEFAULT 0,
    last_seen_date  TEXT NOT NULL,              -- YYYY-MM-DD
    PRIMARY KEY (ticker, list_source)
);

-- Retention: 365 days; entries reset on absence

-- F2 (A4 antitrust regime tag): sector_antitrust_history
CREATE TABLE IF NOT EXISTS sector_antitrust_history (
    sector          TEXT PRIMARY KEY,           -- GICS sector
    blocks_18m      INTEGER NOT NULL DEFAULT 0,
    last_block_date TEXT,                       -- YYYY-MM-DD
    notes           TEXT
);

-- Retention: manually maintained YAML synced into table; ~11 sector rows

-- F10: ticker_metadata extension — Wikipedia article slug + OpenFIGI ID
ALTER TABLE ticker_metadata ADD COLUMN wikipedia_article_slug TEXT;
ALTER TABLE ticker_metadata ADD COLUMN openfigi_id TEXT;

-- (existing ticker_metadata has cache_ttl_days=7 per config/consensus.yaml:168;
--  these columns inherit that retention behaviour via the parent row.)
```

Migration path through `db.py`:
- Append the five new `CREATE TABLE IF NOT EXISTS` statements to the `SCHEMA` constant (`db.py:75–457`).
- Append the two `ALTER TABLE … ADD COLUMN` operations to the `migrations` list inside `_run_column_migrations` (`db.py:460–500`), guarded by the existing `PRAGMA table_info` check at `:496–500`.
- Update `models.py:9–17` `SourceType` enum with the seven new values.
- Add `prune_macro_signals()` to the existing `db.prune_expired()` call site (`db.py:808–817`), pruning rows older than 90 days.
- New helpers in `db.py`:
  - `insert_macro_signal(signal: MacroDriftSignal | CreditEquitySignal) -> int`
  - `get_active_macro_signals(now: float) -> list[dict]`
  - `clear_macro_signal(signal_id: int) -> None`
  - `upsert_beneficial_owner(owner_id, name, address_hash, cik) -> None`
  - `get_beneficial_owner_for_cik(cik: str) -> str | None`
  - `upsert_holder_intent(filer_cik, issuer_cik, outcome=None) -> None`
  - `query_outcome_weighted_campaigns(filer_cik) -> float`
  - `upsert_reg_sho_entry(ticker, list_source, today_date) -> int`  # returns cumulative_days

LOC contribution: ~80 LOC for SCHEMA additions in `db.py`, ~100 LOC for the new helper functions, ~10 LOC for SourceType enum changes in `models.py`, plus ~200 LOC standalone migration SQL file.

---

## 5. Integration Plan

### 5.1 Per-feature connection points

| ID | Scanner entry (file:line) | Scoring hook (file:line) | Alert formatter (file:line) | Xref read site (file:line) |
|---|---|---|---|---|
| F1 | `scanners/insider_cluster.py` (NEW) wired alongside `main.py:343–347` | `db.py:602` `signal_events` insert; consumed at `cross_reference.py:328–332` | `alerts/discord.py:316` `send_instant_ping` | `cross_reference.py:333` (S2 penalty applied) |
| F2 | `scanners/sec_ma_filings.py` (NEW) wired alongside `main.py:343–347` | `db.py:602`; consumed at `cross_reference.py:328–332` | `alerts/discord.py:316` (with antitrust tag) | `cross_reference.py:333` |
| F3 | `scanners/fomc_drift.py` (NEW) wired into `main.py:455–476` `macro_digest_loop` | `db.py` `macro_signals` insert; consumed at `cross_reference.py:333` via S9 | `alerts/discord.py:316` for SPY index alert | `cross_reference.py:333` (S9 reads macro_signals) |
| F4 | `scanners/credit_equity_divergence.py` (NEW) wired into `main.py:455–476` | `db.py` `macro_signals` insert; consumed at `cross_reference.py:333` via S9 | `alerts/discord.py:471–507` annotation only (no standalone) | `cross_reference.py:333` (S9 reads macro_signals) |
| F5 | `analysis/breakout_atr.py` (NEW) called from `main.py:369–380` `fetch_loop` | `db.py:602` SourceType `TECHNICAL_BREAKOUT`; `breakdown.technical` | `alerts/discord.py:316` (entry + targets, NO stop) | `cross_reference.py:328–332` |
| F6 | `analysis/earnings_gate.py` (NEW companion); reuses `scanners/earnings_calendar.py:25–47` | Hooks at `cross_reference.py:333`; writes `breakdown.macro_context_modifier` | `alerts/discord.py:471–507` `send_detail_followup` annotation | `cross_reference.py:333` (read-only consumption) |
| F8 | `scanners/sec_activist_13d.py` (NEW) wired alongside `main.py:343–347` | `db.py:602`; consumed at `cross_reference.py:328–332` | `alerts/discord.py:316` (whitelist + verbiage gated) | `cross_reference.py:333` (S2 penalty defends X4) |
| F10 | `scanners/wikipedia_pageviews.py` (NEW) called from `main.py:369–380` 12th-tick | `db.py:602`; cap +0.05 applied via `breakdown.llm_boost` channel like YouTube at `cross_reference.py:295` | `alerts/discord.py:471–507` annotation only | `cross_reference.py:328–332` |
| F11 | `scanners/reg_sho_threshold.py` (NEW) wired into `main.py:455–476` 18:00 ET | `db.py:602` SourceType `REG_SHO`; consumed at `cross_reference.py:328–332` | `alerts/discord.py:316` (regime + cap gated) | `cross_reference.py:333` (S2 penalty defends X2) |

### 5.2 `main.py` task wiring

Extend the existing task assembly in `main.py:336–352` (`run_live`) with the new loops:

```python
# main.py — additions to the existing run_live task list at :336–352

if cfg.get("scanners.insider_cluster_enabled", False):
    tasks.append(asyncio.create_task(insider_cluster_loop(combined_stop)))
if cfg.get("scanners.sec_ma_filings_enabled", False):
    tasks.append(asyncio.create_task(sec_ma_filings_loop(combined_stop)))
if cfg.get("scanners.fomc_drift_enabled", False):
    tasks.append(asyncio.create_task(fomc_drift_loop(combined_stop)))
if cfg.get("scanners.credit_equity_divergence_enabled", False):
    tasks.append(asyncio.create_task(credit_equity_loop(combined_stop)))
if cfg.get("scanners.sec_activist_13d_enabled", False):
    tasks.append(asyncio.create_task(activist_13d_loop(combined_stop)))
if cfg.get("scanners.wikipedia_pageviews_enabled", False):
    tasks.append(asyncio.create_task(wikipedia_pageviews_loop(combined_stop)))
if cfg.get("scanners.reg_sho_enabled", False):
    tasks.append(asyncio.create_task(reg_sho_loop(combined_stop)))

# F5 hooks into existing fetch_loop (no new task) at main.py:369–380
# F6 hooks into existing cross_reference (no new task) at cross_reference.py:333
```

### 5.3 Config keys to add to `config/consensus.yaml`

Defaults follow the rule: feature flags **OFF**; safe-fix safeguards (S1, S6, S7) **ON**; behaviour-change safeguards (S2, S3, S5) **ON behind a master flag**; unconditional improvements (S4, S8, S9) **ON**.

```yaml
# ============================================================================
# Phase 2 Discovery — Feature flags (ALL DEFAULT OFF)
# ============================================================================
scanners:
  # existing keys preserved …
  sec_background_watchers_enabled: false   # existing

  # NEW — Phase 2 features
  insider_cluster_enabled: false           # F1 — Cluster Form 4 open-market buys
  sec_ma_filings_enabled: false            # F2 — S-4/425 M&A
  fomc_drift_enabled: false                # F3 — Pre-FOMC drift
  credit_equity_divergence_enabled: false  # F4 — FRED credit-equity
  breakout_atr_enabled: false              # F5 — Volume breakout w/ ATR
  earnings_gate_enabled: false             # F6 — Earnings-window gate (off until S3 lands)
  sec_activist_13d_enabled: false          # F8 — 13D activist
  wikipedia_pageviews_enabled: false       # F10 — Wikipedia pageviews
  reg_sho_enabled: false                   # F11 — Reg SHO threshold list

# ============================================================================
# Phase 2 Discovery — Cross-cutting safeguards
# ============================================================================
safeguards:
  master_enabled: true                     # MASTER for behaviour-change safeguards
                                           # When false, S2/S3/S5 are disabled even if
                                           # individually configured ON below.

  # S1 — SEC EDGAR semaphore tighten (SAFE; default ON)
  sec_semaphore_strict: true               # tightens utils/rate_limiter sec_edgar 0.2 -> 0.15

  # S2 — Correlation-decay penalty (BEHAVIOUR; ON behind master)
  correlation_decay_enabled: true
  correlation_decay:
    window_seconds: 86400                  # 24h cross-source correlation window
    same_direction_factor: 0.30
    low_trust_factor: 0.20
    young_filer_factor: 0.40               # CIK age <90d OR account age <90d
    floor: 0.20                            # final score multiplier never below this
    low_trust_sources:                     # explicit list of "second-or-later" tax penalties
      - wikipedia_attention
      - news_velocity
      - tweetshift_repeat

  # S3 — Per-analyst cooldown M3 fix + generalisation (BEHAVIOUR; ON behind master)
  cooldown_m3_fix_enabled: true            # closes the parallel-read race per audit
  cooldown_per_source_enabled: true        # generalises analyst slot to (ticker, source_type, source_detail)

  # S4 — Calendar resolver consolidation (UNCONDITIONAL; default ON)
  calendar_resolver_enabled: true
  calendar_resolver:
    fomc_refresh_days: 7                   # weekly per Feature 3 conflict resolution
    fomc_staleness_alert_days: 7           # source_health alert if older
    earnings_primary: finnhub              # B1 — drop nasdaq from primary
    earnings_secondary: yfinance
    earnings_tertiary: nasdaq              # tertiary fallback only
    earnings_cache_ttl_days: 7

  # S5 — Data freshness gate (BEHAVIOUR; ON behind master)
  freshness_gate_enabled: true
  freshness_gate:
    macro_max_age_seconds: 86400           # 1 trading session
    intraday_max_age_seconds: 3600
    fail_closed: true                      # no signal fires when stale

  # S6 — HEAD-vs-GET convention (SAFE; default ON)
  health_check_via_get: true               # forces GET-as-HEAD for AWS-gateway endpoints

  # S7 — Schema migration consolidation (always-on once landed)
  schema_migration_v202604: true           # idempotent; no-op after first run

  # S8 — Shared yfinance rate-limit (UNCONDITIONAL; default ON)
  yfinance_rate_limit_enabled: true

  # S9 — Macro-context consumption pattern (UNCONDITIONAL; default ON)
  macro_context_consumption_enabled: true

# ============================================================================
# Phase 2 Discovery — Per-feature thresholds
# ============================================================================
features:
  # F1 — Insider cluster
  insider_cluster:
    poll_interval_sec: 300
    jitter_offset_sec: 0                   # :00/min
    rolling_window_days: 14
    min_cluster_weight: 4
    rank_weights:
      ceo_cfo_chair: 3
      coo_president: 2
      other_officer: 2
      director: 1
      ten_pct_holder: 1
    min_dollars_per_insider: 25000
    min_dollars_aggregate: 100000
    min_market_cap: 300000000              # $300M floor
    z_score_bonus_threshold: 2.0
    retract_window_days: 5
    grant_price_match_tolerance: 0.01
    min_independent_owners: 2
    fetch_budget_per_cycle: 30

  # F2 — SEC M&A filings
  sec_ma_filings:
    poll_interval_sec: 300
    jitter_offset_sec: 20
    re_cut_window_days: 14
    cik_age_floor_days: 90
    second_source_window_min: 15           # ±15 minute news / options window
    target_options_sigma: 3.0
    vix_suppress_threshold: 30
    fomc_suppress_window_hours: 48
    target_cik_cooldown_sec: 60
    withdrawal_monitor_window_days: 7

  # F3 — Pre-FOMC drift
  fomc_drift:
    underlying: SPY
    fire_time_et: "14:00"
    randomize_seconds: 90
    vix_min: 18
    vix_5d_pct_min: 10
    spy_24h_max: 0
    dgs2_5d_bps_max: 20
    effr_intraday_bps_max: 5
    spy_imbalance_pctile_min: 90
    rolling_negative_kill: 3
    calendar_path: config/fomc_calendar.yaml

  # F4 — Credit-equity divergence
  credit_equity_divergence:
    eod_run_time_et: "16:30"
    gap_sigma: 2.0
    baseline_days: 252
    baseline_excluded_days: 20
    correlation_60d_max: 0.85
    breadth_pct_min: 0.60
    persistence_sessions: 2
    fred_series_hy_oas: BAMLH0A0HYM2
    sector_map_path: config/sector_map.yaml
    sp500_constituents_path: config/sp500_constituents.yaml

  # F5 — Volume breakout + ATR
  breakout_atr:
    n_windows: [20, 60, 252]
    persistence_sessions_n20: 2
    volume_z_min: 2.0
    volume_z_min_lowfloat: 2.5
    lowfloat_shares_max: 50000000
    dollar_volume_floor: 10000000
    bb_width_pctile_min: 30
    adx_min_n20: 22
    market_cap_floor: 500000000
    abnormal_late_session_ratio_max: 0.45
    earnings_window_days_before: 1
    earnings_window_days_after: 2
    vix_max: 35
    post_close_delay_min: 30
    daily_quota_n20: 20
    daily_quota_n60: 5
    daily_quota_n252: 3
    universe_apewisdom_top_n: 200
    universe_tweetshift_window_hours: 24
    publish_stop: false                    # C4 — never publish stop

  # F6 — Earnings-window gate
  earnings_gate:
    pre_earnings_days: 3
    post_earnings_days: 1
    multiplier_in_window: 0.6
    multiplier_uncertain: 0.7
    tweet_density_override_multiplier: 10.0  # 10× normal triggers override
    cache_ttl_days: 7
    sources_priority: [finnhub, yfinance, nasdaq]

  # F8 — 13D activist
  sec_activist_13d:
    poll_interval_sec: 300
    jitter_offset_sec: 40
    whitelist_path: config/activist_whitelist.yaml
    min_outcome_weighted_campaigns: 2.0
    item4_regex_required: true
    llm_fallback_enabled: true
    co_filer_dedup_window_hours: 24
    conversion_concurrent_window_hours: 48

  # F10 — Wikipedia pageviews
  wikipedia_pageviews:
    poll_interval_min: 60
    z_threshold: 2.5
    sustained_hours_required: 3
    market_cap_min: 200000000
    market_cap_max: 5000000000
    saturation_z_threshold: 2.0
    contribution_cap: 0.05
    user_agent: "consensus_engine/1.0 (+https://github.com/chopra2007/openclaw; ak@openclaw.dev)"

  # F11 — Reg SHO
  reg_sho:
    fire_time_et: "18:00"
    nasdaq_url_template: "https://www.nasdaqtrader.com/dynamic/symdir/regsho/nasdaqth{date}.txt"
    nyse_url: "https://www.nyse.com/regulation/regulation-sho"
    cboe_url: "https://www.cboe.com/us/equities/market_statistics/short_sale/"
    market_cap_floor_single: 2000000000    # $2B
    market_cap_floor_stacked: 3000000000   # $3B
    vix_stress_min: 22
    hy_oas_stress_bps_min: 350
    cooldown_days: 7
    publish_404_retry_min: 30

# ============================================================================
# Phase 2 Discovery — API key provisioning
# ============================================================================
api_keys:
  # existing keys preserved …
  fred: ${FRED_API_KEY}                    # NEW; required by F3 (EFFR/DGS2) + F4 (HY OAS)
```

### 5.4 Cross-cutting safeguard — config flag mapping

| Safeguard | Master flag | Per-flag default | Rationale |
|---|---|---|---|
| S1 | `safeguards.sec_semaphore_strict` | **ON** | Safe fix; tightens existing `rate_limiter` to leave headroom |
| S2 | `safeguards.correlation_decay_enabled` | **ON** behind `safeguards.master_enabled` | Behaviour change but the right default once tested |
| S3 | `safeguards.cooldown_m3_fix_enabled` + `safeguards.cooldown_per_source_enabled` | **ON** behind `safeguards.master_enabled` | Closes audit-confirmed race; cannot ship instant-trigger features without it |
| S4 | `safeguards.calendar_resolver_enabled` | **ON** | Unconditional improvement; replaces ad-hoc calendar lookups |
| S5 | `safeguards.freshness_gate_enabled` | **ON** behind `safeguards.master_enabled` | Behaviour change; fail-closed means no false positives during outages |
| S6 | `safeguards.health_check_via_get` | **ON** | Safe fix; preventative for AWS-gateway endpoints |
| S7 | `safeguards.schema_migration_v202604` | **ON** | Always-on once landed; idempotent |
| S8 | `safeguards.yfinance_rate_limit_enabled` | **ON** | Unconditional improvement |
| S9 | `safeguards.macro_context_consumption_enabled` | **ON** | Unconditional improvement; closes dead-code failure mode |

The master flag `safeguards.master_enabled` exists as an emergency rollback for the three behaviour-change safeguards (S2, S3, S5). Operator can flip it false to revert to pre-Phase-2 cross-reference behaviour without touching the database. The unconditional safeguards (S1, S4, S6, S8, S9) and the schema migration (S7) remain effective regardless — they are operational hygiene, not behaviour change.

### 5.5 Per-feature dependency wiring

| Feature | Required ON | Required OFF | DB tables |
|---|---|---|---|
| F1 | S1, S3, S7 | — | `signal_events`, `beneficial_owner_index`, `alert_history` |
| F2 | S1, S3, S4, S7 | — | `signal_events`, `macro_signals` (read), `sector_antitrust_history` |
| F3 | S3, S4, S5, S7, S8, S9 | — | `macro_signals`, `signal_events` |
| F4 | S5, S7, S8, S9 | — | `macro_signals` |
| F5 | S3, S4, S5, S7, S8 | — | `signal_events`, `alert_history` |
| F6 | S4, S7 | — | (read-only consumer) |
| F8 | S1, S2, S3, S7 | — | `signal_events`, `holder_intent`, `alert_history` |
| F10 | S2, S7 | — | `signal_events`, `ticker_metadata` (extended) |
| F11 | S2, S3, S5, S6, S7 | — | `signal_events`, `reg_sho_history`, `macro_signals` (read) |

A feature MUST NOT be enabled until every safeguard in the "Required ON" column is enabled and verified in production. The Milestone-1 ship order is therefore S1 → S3 → S7 (all three together), then per-feature rollout in the order suggested by P2 ranking + feasibility.

---

End of Phase 4 Implementation Mechanics (Sections 1–5). Continue with `40b-implementation-operations.md` for failure handling, tests, and rollout.
