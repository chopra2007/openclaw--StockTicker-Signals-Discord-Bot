# 40b — Implementation Operations Playbook (Phase 4 part B)

**Date:** 2026-04-24
**Scope:** Operational / shipping portion of the 9-feature + 9-safeguard plan converged in `33-final-feature-set.md`. Sibling deliverable `40a-implementation-structure.md` covers structural / mechanical sections 1–5.

**Inputs of record:**
- `plans/discovery-2026-04-24/33-final-feature-set.md` (source of truth for hardening + kill criteria + instant-trigger eligibility)
- `plans/discovery-2026-04-24/00-system-map.md` (in-code constraints, ThreadPoolExecutor sites, semaphore counts, DEGRADED_MODE)
- `plans/AUDIT_RESEARCH_2026-04-24.md` (M3 cooldown race, 78.4% Phase-2 silent-drop, dead `regime_detector.py`, kpak82 26-min race)
- `plans/discovery-2026-04-24/30-critique-signal-quality.md` / `31-critique-feasibility.md` / `32-critique-adversarial.md` (regime stratifications, attack vectors)

**Spec scaffold:** `docs/superpowers/specs/discovery-2026-04-24-features.md` (created by this deliverable; carries canonical IDs, names, hardened descriptions, kill criteria, module paths).

---

## 6. Failure Handling

For every surviving feature and cross-cutting safeguard, the table below specifies behavior across seven failure axes. Common conventions:

- **Blocking-call hosting:** any sync HTTP call (yfinance, Playwright, blocking SDK) MUST run inside `loop.run_in_executor(executor, ...)` per `main.py:807–832` and `scanners/options.py:97–112`. New per-feature ThreadPoolExecutors are NOT permitted; reuse the existing 4-worker price-outcome pool, or a new `sec_executor` provisioned in `main.py` with explicit max_workers.
- **Rate-limit pattern:** all SEC endpoints `await rate_limiter.acquire("sec_edgar")`; yfinance callers `await rate_limiter.acquire("yfinance")` after CC-S4 ships; FRED callers `await rate_limiter.acquire("fred")`.
- **Retry budget:** bounded — 3 attempts with exponential 30s/60s/120s backoff, capped at 600s, per existing `RateLimiter.report_failure` (`utils/rate_limiter.py:73–79`). After 3 failures the source enters backoff; consumers must check `is_blocked` before issuing.
- **DEGRADED_MODE participation:** every new feature contributes to `_record_source_ok/_record_source_error` (`main.py:68–86`). When ≥2 critical sources unhealthy, the global `DEGRADED_MODE` flips True and `alerts.suppress_when_degraded` controls suppression of new feature emissions (default: keep firing, footer-flag).
- **Freshness gate:** every macro/quant feature MUST call `freshness_gate.is_fresh(source_id, max_age_seconds)` (CC-S5 / S5 module) before computing. `is_fresh == False` → no signal fires (fail-closed, no false positive).

### 6.1 Per-feature failure matrix

#### F1 — Cluster Form 4 (`consensus_engine/scanners/insider_cluster.py`)

| Axis | Behavior |
|------|----------|
| Missing data | EDGAR submissions.json returns 200 with empty `recent` filings → no-op cycle, `_record_source_ok` (the source IS healthy, just nothing to scan). Form-4 XML 404 (filing pulled mid-cycle) → log warning, skip filing, do not error the cycle. |
| Delayed data | Form-4 must be filed within 2 business days; cluster window is 14d, so 1–2-day delay is absorbed. If submissions.json `lastUpdate` >24h old → emit source-health warning, continue (filings are append-only; staleness is upstream not local). |
| Conflicting signals | Buyer cluster + simultaneous insider sell on same ticker (e.g., Form 4 P + Form 4 S within 14d) — emit cluster IF buy-weight ≥ 4 AND net-dollar-flow positive; else suppress and tag `signal_events` row with `INSIDER_MIXED` for xref consumption only. |
| Rate-limit backoff | Per-filing XML fetch routed through `rate_limiter.acquire("sec_edgar")` (CC-S1). On 429 / `is_blocked`, drop remaining filings in cycle; resume next cycle after backoff. NEVER retry inline. |
| Retry budget | 3 attempts per filing, exponential per existing helper. After 3 failures, mark filing `partial_parse` in `signal_events` and continue. |
| Blocking calls | Pure `aiohttp` (sec_edgar.py is already async). No executor needed. XML parse via `xml.etree.ElementTree` (sync but cheap, OK on event loop for ~50KB filings). |
| Degraded-mode | DEGRADED_MODE active → suppression governed by `alerts.suppress_when_degraded` (default False, footer-flag only). `sec_edgar` source marked unhealthy → `is_fresh("sec_edgar", 1800)` returns False → entire feature no-op until source recovers. |

#### F2 — SEC S-4/425 M&A (`consensus_engine/scanners/sec_ma_filings.py`)

| Axis | Behavior |
|------|----------|
| Missing data | ATOM feed empty (no recent S-4/425) → no-op. ATOM feed 5xx → backoff via rate_limiter. Body-fetch 404 (filing pulled) → log + skip; do not block other filings in feed. |
| Delayed data | ATOM cadence is ~1 min; if `lastBuildDate` >5 min stale → source-health warning. If FOMC calendar within 48h (per A3 hardening) → suppress standalone regardless of ATOM freshness. |
| Conflicting signals | Same target CIK has S-4 (acquirer A) + S-4 (acquirer B) within 30 days → emit BOTH as separate signals; do NOT collapse. Conflicting `termination|amendment` keywords on same accession_number (425 + 425/A) → run retract-message logic (C2). |
| Rate-limit backoff | ATOM and body fetch share `sec_edgar` semaphore (CC-S1) with jittered :20-of-minute start offset. |
| Retry budget | 3 attempts on body-fetch only (ATOM listing is single shot per cycle). |
| Blocking calls | None — `aiohttp` end to end. |
| Degraded-mode | If `sec_edgar` unhealthy or VIX>30 (per A3) → standalone suppressed, downgrade to xref-only via `signal_events` row. |

#### F3 — Pre-FOMC Drift (`consensus_engine/scanners/fomc_drift.py`)

| Axis | Behavior |
|------|----------|
| Missing data | FOMC YAML missing or last_refreshed > 7 days → fail-closed (per C1 hardening); emit operator alert via Discord ops channel. EFFR series 404 from FRED → fail-closed (kill-switch tripped: cannot verify rate stability). SPY/VIX `/quote` 5xx → fail-closed for that cycle. |
| Delayed data | FRED publishes T+1 → during 24h window pre-FOMC, EFFR may be missing for current day; treat as "kill-switch unknown" and suppress (fail-closed). 2yr Treasury (`DGS2`) similarly. |
| Conflicting signals | EFFR moved >5bps intraday but VIX still >18 + VIX-up + flat-prior — C2 EFFR kill-switch wins; suppress. Macro caution active from F4 — independent (F3 fires on calendar, F4 modulates downstream confidence). |
| Rate-limit backoff | FRED 1 req/s nominal (well within free 120 req/min); jittered start at :00 of T-1 14:00 ET. yfinance for VIX series via `yfinance` semaphore (CC-S4). |
| Retry budget | 3 attempts on FRED + Finnhub `/quote`. After 3 failures → fail-closed. |
| Blocking calls | yfinance `Ticker("^VIX").history()` is blocking → `loop.run_in_executor(price_outcome_executor, ...)`. FRED via `aiohttp` (async). |
| Degraded-mode | DEGRADED_MODE active OR finnhub/yfinance unhealthy → suppress (this signal NEEDS fresh quote data to pass guard checks). |

#### F4 — FRED Credit-Equity Divergence (`consensus_engine/scanners/credit_equity_divergence.py`)

| Axis | Behavior |
|------|----------|
| Missing data | FRED `BAMLH0A0HYM2` series 404 → graceful degradation to ETF-only (HYG/SPY/LQD via yfinance) per P2 fallback. yfinance HYG missing → fail-closed (HYG is the primary input, no substitute). Breadth lookup empty (S&P constituents universe missing) → suppress A1 broad-participation filter, log warning, continue with degraded confidence. |
| Delayed data | FRED HY OAS publishes T+1 (acceptable per design); use last-known value with timestamp annotation in `macro_signals` row. yfinance HYG OHLCV stale > 1 trading session → fail-closed. |
| Conflicting signals | Bearish divergence active + breadth filter (A1) shows < 60% of S&P 500 above 50d-SMA → DO NOT emit (broad-participation regime gate fails). Both F4 bearish and F11 stress-regime active → both write independent macro_signals rows; xref consumption combines via CC-S8. |
| Rate-limit backoff | FRED via `rate_limiter.acquire("fred")` 1 req/s. yfinance via CC-S4 semaphore. |
| Retry budget | 3 attempts; on terminal failure, last-known cached value held for max 24h then fail-closed. |
| Blocking calls | yfinance multi-ticker history blocking → ThreadPoolExecutor. |
| Degraded-mode | Macro feature; coverage drop in DEGRADED_MODE acceptable. CC-S8 consumer (`_get_macro_context`) reads `macro_signals` table; if no row present in last 24h, treat as "regime unknown" → no multiplier applied. |

#### F5 — Volume-Confirmed Breakout w/ ATR (`consensus_engine/analysis/breakout_atr.py`)

| Axis | Behavior |
|------|----------|
| Missing data | yfinance OHLCV missing for ticker → skip ticker, do not fail cycle. Universe scope (top-N from ApeWisdom + active TweetShift hits) returned 0 tickers → no-op cycle. Earnings calendar lookup (per A2 in-module suppression) missing → fail-closed for that ticker (cannot confirm "outside earnings window"). |
| Delayed data | yfinance OHLCV stale > 1 trading session → ticker skipped via freshness gate. C5 30-min post-close delay is by design — late fires on stale data are not an issue if freshness gate enforces session-current OHLCV. |
| Conflicting signals | Breakout fires + Reg SHO threshold list entry (F11) on same ticker within 24h → score boost via correlation-decay (CC-S2) flags as 2 active sources, applies penalty if both fire from low-trust paths. Earnings window detected (F6 returns `into_earnings`) → suppress per A2. |
| Rate-limit backoff | yfinance via CC-S4 semaphore. Universe size capped at top-50 tickers per cycle to bound per-cycle yfinance calls. |
| Retry budget | 3 attempts per ticker; failure marks ticker `partial_data`, skip. |
| Blocking calls | yfinance OHLCV pull blocking → ThreadPoolExecutor (reuse `price_outcome_executor`). ATR/BBwidth via existing `analysis/indicators.py` (numpy-based, CPU-bound but fast). |
| Degraded-mode | yfinance unhealthy → entire feature no-op (no signal source). Per-feature daily quota acts as additional cap (max 20 alerts/day for N=20). |

#### F6 — Earnings-Window Risk Gate (extends `scanners/earnings_calendar.py` + `analysis/catalyst_resolver.py`)

| Axis | Behavior |
|------|----------|
| Missing data | Finnhub `/calendar/earnings` 5xx → fall back to yfinance Ticker.calendar (per B1 — Nasdaq dropped). Both unavailable → tag signal `clear` (no gate applied) AND log freshness violation. (Soft modifier means even a "clear" tag does no harm if data is missing — non-fail-closed by design.) |
| Delayed data | Cached earnings date > 7-day TTL → re-pull on next access. 8-K Item 2.02 detected for ticker → invalidate cache immediately (per B2). |
| Conflicting signals | Finnhub-curated date vs self-disclosed pre-announce date → trust Finnhub (per C1). Cross-source mismatch ≥2 days → tag `uncertain` (fail-closed retained from P2). Tweet density spike >10x normal in gate window → C3 override, tag `multiple_events` and don't apply gate. |
| Rate-limit backoff | Finnhub 1 req/s shared with `finnhub` source; respects existing limits in `scanners/earnings_calendar.py:25–47`. |
| Retry budget | 3 attempts; after exhaust, gate defaults to `clear`. |
| Blocking calls | None — Finnhub is `aiohttp`. yfinance fallback blocking → ThreadPoolExecutor only when Finnhub fails. |
| Degraded-mode | Gate is contextualizer — absent gate means no multiplier, alert fires at base score. Acceptable graceful degradation. |

#### F8 — 13D Activist + 13G→13D (`consensus_engine/scanners/sec_activist_13d.py`)

| Axis | Behavior |
|------|----------|
| Missing data | EDGAR submissions.json empty for issuer → no-op. Item 4 text empty → invoke B2 LLM-classifier fallback only if filer ≥2 prior campaigns; else downgrade to xref-only. Holder_intent table missing prior history → treat as "unknown filer" → xref-only (per C5 whitelist requirement). |
| Delayed data | 13D must be filed within 10 days of crossing 5%; 13D/A amendments routine. Stale submissions.json > 24h → source-health warning, continue. Backfill job (B1) failures → standalone path disabled until backfill completes. |
| Conflicting signals | New 13D + same-day 13G filing on same target by different filers → C1 co-filing dedup applies. 13G→13D conversion + concurrent 13D from another filer → emit BOTH but apply CC-S2 correlation-decay (multiple SourceTypes simultaneously → penalty). |
| Rate-limit backoff | All EDGAR calls via `rate_limiter.acquire("sec_edgar")` with jittered :40-of-minute start. LLM classifier fallback (B2) shares `llm_scorer` budget — apply same `_sem_llm=2` semaphore from `cross_reference.py:29`. |
| Retry budget | 3 attempts per filing. Backfill job retry budget separate (per-CIK 3 attempts, then mark CIK `incomplete_history` and skip). |
| Blocking calls | None — `aiohttp` end to end. LLM classifier already async. |
| Degraded-mode | DEGRADED_MODE active → standalone suppressed if `alerts.suppress_when_degraded`, else footer-flagged. SEC unhealthy → no-op. |

#### F10 — Wikipedia Pageview Spike (`consensus_engine/scanners/wikipedia_pageviews.py`)

| Axis | Behavior |
|------|----------|
| Missing data | Wikipedia REST API 404 for article slug → mark ticker `no_wiki_match`, skip; do not retry. ticker_external_ids table missing entry → trigger one-time backfill (B1 OpenFIGI lookup) or skip if backfill incomplete. Google Trends co-confirmation (C1) missing → suppress (fail-closed by design — C1 is mandatory). |
| Delayed data | Wikipedia hourly pageviews API has ~2-hour lag → 28-day baseline cached (B3) so latency only affects current-hour z-score. Article-baseline cache TTL 28 days; recompute weekly. |
| Conflicting signals | Wikipedia spike + Google Trends spike same direction → annotation only (per A3 demote). Wikipedia spike + Google Trends NO spike → null-and-void per C1; do not emit `signal_events` row. |
| Rate-limit backoff | Wikipedia REST has no documented rate-limit but be polite — `rate_limiter.acquire("wikipedia")` at 0.5s. User-Agent per B4. |
| Retry budget | 3 attempts; failure → skip article. |
| Blocking calls | None — `aiohttp`. |
| Degraded-mode | F10 is annotation only (+0.05 cap); absence has near-zero impact. DEGRADED_MODE → continue (no harm, low value). |

#### F11 — Reg SHO Threshold List (`consensus_engine/scanners/reg_sho_threshold.py`)

| Axis | Behavior |
|------|----------|
| Missing data | NASDAQ daily file 404 (file not yet posted) → retry 30 min later (per B3); no error log spam. NYSE redirect to non-200 → backoff. Cboe missing → continue with available exchanges. VIX/HY OAS data missing for A2 regime gate → fail-closed (cannot determine regime). |
| Delayed data | Daily file publishes ~T+1 morning; cumulative-entry-day-count (B1) handles publication delay. If file > 48h stale → source-health warning, freshness gate triggers fail-closed. |
| Conflicting signals | Same ticker on entry list one day, exit next day → emit BOTH events as distinct `signal_events` rows; xref consumes both. F11 + F8 13D within 14d → stacked $3B floor (per X2 resolution); single-feature $2B/3B logic in scanner module. |
| Rate-limit backoff | NASDAQ/NYSE/Cboe each get own `rate_limiter` source string at 0.2s (5 req/s well below polite ceiling). Daily cadence so cumulative load is trivial. |
| Retry budget | 3 attempts per exchange daily file. After exhaust, log warning, skip that exchange's diff for the day. |
| Blocking calls | None — pure `aiohttp` text fetch + Python diff. |
| Degraded-mode | If regime data (VIX, HY OAS from F4) missing → A2 gate cannot evaluate → suppress standalone, downgrade to xref-only. |

### 6.2 Per-safeguard failure matrix

| ID | Module | Missing data | Delayed data | Conflicting | Rate-limit | Retry | Blocking | Degraded |
|----|--------|--------------|--------------|-------------|------------|-------|----------|----------|
| S1 | `utils/rate_limiter.py` (sec_edgar tightened to 0.15s) | n/a (in-process) | n/a | Multiple features queued at minute boundary → semaphore queues fairly via FIFO; jittered offsets prevent thundering herd | Self-rate-limiting; 3-failure threshold flips source to backoff per `report_failure` | Bounded by existing impl | n/a | If sec_edgar enters backoff, all SEC features no-op until clear |
| S2 | `analysis/correlation_decay.py` + `cross_reference.py:333` | If `signal_events` window read returns empty, penalty = 0 (default no-op) | Window is 24h trailing; stale signal_events tolerated | Penalty itself has no failure mode — pure compute over xref aggregation | n/a | n/a | n/a (numpy compute) | Continues unchanged in DEGRADED_MODE |
| S3 | `db.py:672` (`check_alert_cooldown` rewrite) | `source_performance` empty for analyst → fall back to blanket cooldown (per audit M3 spec, <5 samples) | Stale rolling_accuracy → use last value | Race condition in parallel-read fix: serialize via `BEGIN IMMEDIATE` SQLite transaction (audit M3 prescription) | n/a | n/a | n/a | Cooldown still enforced; no relaxation in DEGRADED_MODE |
| S4 | `analysis/catalyst_resolver.py` ext | Calendar source missing → fail-closed for time-sensitive features (F3, F6) | Daily-cadence staleness check; > 7 days → operator alert | FOMC vs earnings on same day → both surface in resolver output | Finnhub respects existing limits; FOMC YAML local | n/a (local YAML) + Finnhub 3 attempts | None (Finnhub async) | If Finnhub unhealthy, calendar resolver returns last-cached values |
| S5 | `utils/freshness_gate.py` (NEW) | n/a — gate IS the missing-data detector | Each source has max_age_seconds config | Multiple sources stale simultaneously → all dependent features fail-closed independently | n/a | n/a | n/a | DEGRADED_MODE multiplies max_age by `degraded_freshness_multiplier=5` per existing pattern in `main.py:74` |
| S6 | `utils/http.py` ext (HEAD-vs-GET helper) | If health-check returns 5xx → mark source unhealthy via existing `_record_source_error` | Probe interval 60s per `source_health.poll_interval` | n/a | Probes share `rate_limiter` for the source | Bounded by existing | None | Probes themselves suppressed when DEGRADED_MODE to avoid hammering unhealthy sources |
| S7 | `db.py` schema migration | If migration fails mid-run → atomic rollback via SQLite transaction wrapping all DDL | n/a (one-shot) | If migration runs concurrently with live engine → flock at `/tmp/consensus_engine.lock` prevents (per `main.py:861`) | n/a | n/a | n/a | Engine refuses to start if migration version mismatch |
| S8 | `utils/rate_limiter.py` ext (yfinance string) | n/a | n/a | yfinance shared by F3, F4, F5, price_outcome_loop → FIFO queueing via existing rate_limiter | Self-rate-limiting at 1 req/s | Existing | n/a | Yfinance unhealthy → all dependent features no-op |
| S9 | `cross_reference.py` ext (`_get_macro_context`) | Missing `macro_signals` row → no multiplier applied (default no-op) | Window is 24h trailing | F3 active + F4 bearish → both multipliers compose multiplicatively (capped 0.5–1.5) | n/a | n/a | n/a (DB read) | Continues; macro context becomes "neutral" if all macro_signals stale |

### 6.3 Cross-feature conflict resolution

| Trigger | Resolution |
|---------|-----------|
| F1 cluster + F2 S-4 same ticker within 14d (Attack X1) | CC-S2 correlation-decay applies. n_active_sources=2, same-direction-in-<12h trips +0.30 factor, penalty = max(0, 2-2) × 0.30 = 0 (correctly no penalty for two legitimate filings); but if a 3rd feature joins, penalty kicks in. Score still emits, with breakdown annotation. |
| F8 13D + F11 Reg SHO same ticker within 14d (Attack X2) | Stacked $3B floor (per F11 X2 resolution). If single ticker fails $3B floor, stack does not amplify; F11 demoted to xref-only for stacked case. CC-S2 penalty applies if 3rd source joins. |
| F3 pre-FOMC active + F2 S-4 same window | F2 A3 hardening: VIX>30 OR FOMC<48h → F2 standalone suppressed; F2 downgrades to xref-only. F3 fires independently (index-level). |
| F4 macro-caution + F5 breakout | F4 writes `macro_signals` row with regime label; CC-S8 consumer raises confidence threshold +10pts on cyclicals/small-caps. F5 still fires if cleared threshold. No suppression. |
| F6 earnings into-earnings + F5 breakout | F5 A2 in-module suppression: standalone fire suppressed if `next_earnings_in_days <= 1 OR last_earnings_in_days <= 2`. F6 also applies 0.6× multiplier to any other signal in same window. Belt-and-suspenders by design. |
| F1 cluster + sock-puppet activist 13D (Attack X4) | F8 C5 whitelist: non-whitelisted activists demoted to xref-only. F1 still fires standalone but CC-S2 penalty if F8 joins from low-trust path. |
| F10 Wikipedia + tweet brigade + news velocity (Attack X5) | C1 mandatory Google Trends co-confirmation. C2 sustained 3h spike. C3 +0.05 cap. CC-S2 penalty trips at n_active_sources>=3 with low-trust-tier accumulator. |

---

## 7. Test Plan

**Conventions:**
- Project test command: `python3 -m pytest tests/ -v` (full); per CLAUDE.md, integration suite: `python3 -m pytest tests/integration/ -v --tb=short 2>&1 | tail -20`.
- `pytest.ini` has `asyncio_mode = auto` → all `async def test_*` functions run on event loop without explicit decoration.
- Blocking-call tests use `loop.run_in_executor(executor, ...)` per `main.py:809–832` precedent. ThreadPoolExecutor injection via fixture (`@pytest.fixture` returning `ThreadPoolExecutor(max_workers=2)`).
- Fixtures for SEC EDGAR / FRED / Wikipedia / yfinance use `aiohttp_responses` mock or `aiohttp.test_utils.TestClient`; for blocking yfinance, `unittest.mock.patch("yfinance.Ticker")` or recorded fixtures under `tests/fixtures/`.
- Each test file MUST include the kill-criterion regime test naming the regime explicitly (e.g., `test_F1_kill_regime_low_volatility_silence`).
- Coverage target: 90%+ on each new module before flag flip; integration suite must pass before stage-3 production enable.

### 7.1 Per-feature test plans

#### F1 — Cluster Form 4 — `tests/unit/scanners/test_insider_cluster.py` + `tests/integration/test_F1_integration.py`

| Test | Description |
|------|-------------|
| Golden path | 3 distinct insiders (CEO, CFO, director — total weight 7) buy ticker XYZ within 10d, each ≥$30k, aggregate ≥$200k, all `transactionCode=='P'`, `aff10b5One==False`. Expect: standalone alert emitted with SourceType `INSIDER_CLUSTER`, signal_events row written, beneficial_owner check passes (3 distinct CIKs with non-overlapping Form 3 history). |
| Edge-case 1: missing data | `submissions.json` returns 200 with `recent.filings == []`. Verify: no-op cycle, no exceptions, `_record_source_ok` called once, no signal_events row written. |
| Edge-case 2: rate-limit hit | Mock `rate_limiter.acquire("sec_edgar")` to return False mid-cycle (sec_edgar in backoff). Verify: cycle exits gracefully without partial emission; remaining filings deferred to next cycle. |
| Edge-case 3: kill-regime test | **Regime: 10b5-1 contamination >15%.** Inject 50 cluster events where 8 contain Form 4 with `aff10b5One==True` (not filtered properly). Verify: feature emits but kill-criterion monitor (60-day rolling check from CC-S3 generalization) flags 16% contamination → auto-disables flag and posts Discord ops notice. |
| Manipulation test (C-tweak) | Inject Form 4 buy at exactly $42.00 alongside Form 4 grant at $42.00 (same day, same issuer). Verify: cluster trigger rejected per C-tweak (i) "reject cluster trigger if any constituent buy is at exactly the same price as a recent grant". |
| Beneficial-owner dedup | Inject 4 CIKs where 3 share overlapping Form 3 history (same trust). Verify: counted as 2 independent beneficial owners, not 4 — cluster fails ≥2 independent test. |
| Liquidity floor | $250M market-cap ticker — verify suppressed (under $300M floor). |

#### F2 — SEC S-4/425 M&A — `tests/unit/scanners/test_sec_ma_filings.py` + `tests/integration/test_F2_integration.py`

| Test | Description |
|------|-------------|
| Golden path | New 425 filing, acquirer-CIK references target-CIK first time in 30 days, body contains "definitive agreement" + "per share", paired with target options vol >3σ within 15 min. Expect: standalone alert emitted, SourceType `M_AND_A`, both filer AND target on filing per C1. |
| Edge-case 1: missing data | ATOM feed returns empty. Verify: no-op, no exceptions. |
| Edge-case 2: rate-limit hit | sec_edgar backoff active. Verify: ATOM cycle skipped, body-fetch deferred. |
| Edge-case 3: kill-regime test | **Regime: deal-termination cascade in rate-shock.** Inject 425 filing while VIX==35 (>30 threshold). Verify: A3 hardening suppresses standalone, downgrades to xref-only via signal_events row. |
| Re-cut filter (A2) | Same acquirer files 425 referencing same target 7 days after prior. Verify: suppressed (no prior 425 from same acquirer in trailing 14 days requirement fails). |
| Termination keyword (A1) | 425 body contains "termination" → downgraded to xref-only. |
| C1 dual requirement | 425 references target only in body text (not in SUBJECT-COMPANY field) → suppressed. |
| C3 CIK age | Filer CIK first registered 30 days ago → suppressed. |

#### F3 — Pre-FOMC Drift — `tests/unit/signals/test_fomc_drift.py` + `tests/integration/test_F3_integration.py`

| Test | Description |
|------|-------------|
| Golden path | Day = T-1 of FOMC, time = 14:00 ET, VIX=22 (>18), VIX +12% over prior 5 sessions, prior 24h SPY return = -0.3%, 2yr Treasury Δ5d = +5bps (within ±20bps), EFFR stable. Expect: long-SPY alert emitted with hard time-stop = 14:00 ET FOMC day. |
| Edge-case 1: missing data | FRED EFFR series returns 404. Verify: fail-closed (suppress), source-health warning logged, no alert emitted. |
| Edge-case 2: rate-limit hit | yfinance backoff active for VIX history. Verify: fail-closed; cycle skipped. |
| Edge-case 3: kill-regime test | **Regime: rates-shock filtered out.** 2yr Treasury Δ5d = +35bps (exceeds ±20bps). Verify: A1 rates-regime kill switch suppresses. |
| Calendar staleness | YAML last_refreshed > 7 days ago → fail-closed per C1; operator alert emitted. |
| EFFR deviation | EFFR moved >5bps intraday → C2 kill-switch trips, suppress for 24h. |
| Randomization (C4) | Verify: alert send time has ±90s jitter around 14:00 ET (deterministic only via seeded RNG in test). |
| Consumption pattern | F3 active → `_get_macro_context` returns multiplier `0.85` for cyclicals/small-caps in xref. Verify wired and read. |

#### F4 — FRED Credit-Equity Divergence — `tests/unit/scanners/test_credit_equity_divergence.py` + `tests/integration/test_F4_integration.py`

| Test | Description |
|------|-------------|
| Golden path | gap_20d = 4.2% (> 2σ over 252d baseline), HYG below SMA50, SPY above SMA50, 60d cor(HYG, SPY) = 0.65 (<0.85), 60% S&P breadth above 50d-SMA. Expect: macro_signals row written with regime `credit_caution`, `_get_macro_context` returns +10pts threshold modifier on cyclicals. |
| Edge-case 1: missing data | FRED HY OAS 404 → graceful degradation to ETF-only path; signal still computes from yfinance. |
| Edge-case 2: rate-limit hit | yfinance backoff → fail-closed for cycle. |
| Edge-case 3: kill-regime test | **Regime: concentrated mega-cap leadership (2024 pattern).** Breadth = 32% above SMA50 (<60%). Verify: A1 breadth filter suppresses; no macro_signals row written. |
| Stratified backtest | Inject 24 months synthetic data where broad-participation sub-period precision = 65%, concentrated sub-period = 35%. Verify: kill-criterion check evaluates only on broad-participation sub-period. |
| Correlation suppress | cor(HYG, SPY) = 0.92 → P2 suppress active; no row written. |
| Persistence (≥2 sessions) | Single-session bearish trigger does not write row; second consecutive session does. |

#### F5 — Volume-Confirmed Breakout w/ ATR — `tests/unit/analysis/test_breakout_atr.py` + `tests/integration/test_F5_integration.py`

| Test | Description |
|------|-------------|
| Golden path | N=20 breakout: today_close > rolling_max(close,20), today_dollar_vol = $25M, $10M floor cleared, ADV ≥ 500k shares, market cap = $1.2B (>$500M), VIX=18 (<35), VWAP confirmation, BBwidth at 45th pct, ADX(14)=25 (>22), 30-min post-close delay applied. Expect: alert emitted with entry + target_1 + target_2 (NO stop per C4). |
| Edge-case 1: missing data | yfinance OHLCV missing → ticker skipped, cycle continues. |
| Edge-case 2: rate-limit hit | yfinance backoff → universe-wide skip. |
| Edge-case 3: kill-regime test | **Regime: VIXmageddon (VIX > 40).** Verify: feature suppressed entirely. |
| C1 dollar-volume z-score | Ticker has 5x volume z but only $4M dollar volume → suppressed (< $10M floor). |
| C2 cap floor | $400M market cap → suppressed (< $500M). |
| C3 late-session concentration | Last-hour-vs-first-5h ratio = 0.55 → suppressed. |
| A1 persistence (N=20) | Single-session breakout → suppressed; second consecutive → fires. |
| A2 earnings suppression | next_earnings_in_days = 1 → suppressed. |
| C4 no published stop | Verify alert payload contains `entry`, `target_1`, `target_2`, `time_stop` but NO `stop_loss` field. |
| Daily quota | After 20 N=20 alerts in same day → 21st suppressed. |

#### F6 — Earnings-Window Risk Gate — `tests/unit/analysis/test_earnings_gate.py` + `tests/integration/test_F6_integration.py`

| Test | Description |
|------|-------------|
| Golden path | Tweet alert fires for ticker XYZ; next earnings T-2; gate tags `pre_earnings_T-2`, applies 0.6× multiplier to confidence. Verify: alert still fires (soft modifier per C2), Phase-2 embed text includes "pre-earnings (T-2)". |
| Edge-case 1: missing data | Finnhub `/calendar/earnings` 5xx + yfinance fallback also fails → tag `clear`, log freshness violation, no exception. |
| Edge-case 2: rate-limit hit | finnhub source in backoff → Cache-only path; if cache miss, yfinance fallback. |
| Edge-case 3: kill-regime test | **Regime: 6-month backtest precision delta < 5pp.** Inject 6 months of synthetic alerts where T-3 to T+1 social signals show only 4pp precision lift. Verify: kill-criterion monitor flags and auto-disables. |
| C2 soft modifier | Verify gate is multiplier (0.6×), not hard-suppress. High-conviction signal (score=85) × 0.6 = 51 → still above min_base_score_for_alert=20 → fires. |
| C3 tweet-density override | Tweet volume 12x normal in T-2 window → gate overrides to "multiple_events" → no multiplier applied. |
| B2 8-K Item 2.02 invalidation | 8-K Item 2.02 detected → cache invalidated, re-pull on next access. |
| Cross-source mismatch | Finnhub date = 2026-05-15, yfinance date = 2026-05-12 (3-day mismatch) → tag `uncertain`. |

#### F8 — 13D Activist + 13G→13D — `tests/unit/scanners/test_sec_activist_13d.py` + `tests/integration/test_F8_integration.py`

| Test | Description |
|------|-------------|
| Golden path | Whitelisted filer (Elliott Management) files new 13D, Item 4 contains "intend to nominate two directors", 8% stake disclosed. Expect: standalone alert, SourceType `ACTIVIST_FILING`. |
| Edge-case 1: missing data | submissions.json empty → no-op. |
| Edge-case 2: rate-limit hit | sec_edgar backoff → cycle skipped. |
| Edge-case 3: kill-regime test | **Regime: whitelisted-activist 12-month precision <50%.** Inject 12 months of synthetic alerts where whitelisted activist events show 47% 21d precision. Verify: kill-criterion monitor disables standalone path. |
| C5 whitelist | Non-whitelisted filer with 2 prior campaigns → downgraded to xref-only (not standalone). |
| C2 specific verbiage | Item 4 contains only "engaging with management" (soft language) → downgraded to xref-only. |
| C1 co-filing dedup | 3 CIKs file 13D same day on same target → counted as 1 filer. |
| C3 13G→13D conversion | Conversion without concurrent action (no press release, no options >3σ) → xref-only. |
| B2 LLM fallback | Item 4 regex returns 0 hits + filer is whitelisted → invoke LLM classifier; if classifier yields "directors named" → fires. |

#### F10 — Wikipedia Pageview Spike — `tests/unit/scanners/test_wikipedia_pageviews.py` + `tests/integration/test_F10_integration.py`

| Test | Description |
|------|-------------|
| Golden path | Mid-cap ticker ($1.5B), Wikipedia pageviews z=2.8 sustained 4h, Google Trends spike same hour same direction. Expect: signal_events row written with SourceType `WIKIPEDIA_ATTENTION`, score boost capped at +0.05. |
| Edge-case 1: missing data | Wikipedia REST 404 for slug → mark ticker `no_wiki_match`, skip. |
| Edge-case 2: rate-limit hit | Wikipedia in backoff → cycle skipped for affected tickers. |
| Edge-case 3: kill-regime test | **Regime: 90-day precision delta < 1pp via +0.05 multiplier.** Inject 90d backtest where Wikipedia-confirmed alerts show only 0.5pp precision lift. Verify: kill-criterion fires (effectively unused at +0.05 cap). |
| A1 cap floor | NVDA-style $3T mega-cap → suppressed (outside $200M–$5B band). |
| C1 mandatory Google Trends | Wikipedia spike but Google Trends flat → null-and-void; no signal_events row. |
| C2 sustained-spike | Wikipedia z=3.0 single-hour only → suppressed (need ≥3 consecutive hours). |
| C3 cap | Wikipedia z=10 (extreme) → still capped at +0.05. |
| B2 infobox check | Article infobox lacks ticker symbol → article rejected (e.g., common-noun ticker). |

#### F11 — Reg SHO Threshold List — `tests/unit/scanners/test_reg_sho_threshold.py` + `tests/integration/test_F11_integration.py`

| Test | Description |
|------|-------------|
| Golden path | Ticker XYZ enters NASDAQ threshold list, $2.5B market cap, VIX=24 (>22), HY OAS=380bps (>350). Expect: standalone alert, SourceType `REG_SHO`. |
| Edge-case 1: missing data | NASDAQ 404 (file not posted) → retry 30 min later (B3); no error log spam, no signal emitted this cycle. |
| Edge-case 2: rate-limit hit | NASDAQ source in backoff → cycle skipped for that exchange; NYSE/Cboe still attempt. |
| Edge-case 3: kill-regime test | **Regime: low-vol ample-borrow.** VIX=14, HY OAS=280bps. Verify: A2 regime gate suppresses standalone, downgrades to xref-only. |
| A1 cap floor | $1.8B ticker → suppressed (under $2B floor for single-feature standalone). |
| Stacked-floor (X2) | F11 + F8 13D within 14d on $2.5B ticker → stacked $3B floor not met → demoted from amplified-stack score boost; F11 still fires single-feature standalone if regime cleared. |
| B1 cumulative-day-count | Ticker on list day 1, off day 2, on day 3 → tracked as cumulative entries; spurious yesterday-vs-today diff suppressed. |
| B2 NYSE redirect | NYSE returns 301 to `/regulation/regulation-sho` → follow redirect successfully. |
| C ticker normalization | "BRK.B" / "BRK B" / "BRK-B" all normalize to single ticker for diff. |

### 7.2 Per-safeguard test plans

#### S1 — Shared SEC EDGAR semaphore — `tests/unit/utils/test_rate_limiter_sec.py`

| Test | Description |
|------|-------------|
| Golden path | 3 concurrent calls to `rate_limiter.acquire("sec_edgar")` → enforced 0.15s spacing, all 3 eventually succeed. |
| Conflict-with-features | F1 + F2 + F8 all fire at minute :00 (no jitter) → expected throttle to 6.67 req/s aggregate; verify queue order is FIFO and no dropped requests. |
| Failure-mode | 3 consecutive 429 responses → `report_failure` flips `is_blocked=True`; subsequent `acquire` returns False; queueing does not crash or leak coroutines. |
| Jitter offset | F1 jittered to :00, F2 to :20, F8 to :40 — verify per-feature start offsets in test harness. |

#### S2 — Correlation-decay penalty — `tests/unit/analysis/test_correlation_decay.py`

| Test | Description |
|------|-------------|
| Golden path | n_active_sources=2, both high-trust (e.g., F1 + F8), no low-trust additions. Penalty = max(0, 2-2) × 0.30 = 0; score unchanged. |
| Conflict-with-other-features | n_active_sources=4 (TweetShift + Wikipedia + News velocity + low-trust 13D) all firing within 30 min same direction. Verify: penalty accumulates (`+0.30 same-direction +0.20×3 low-trust = 0.90`), `penalty = max(0,4-2) × 0.90 = 1.80` → clamp final score to 0.20 floor. |
| Failure-mode | `signal_events` window read returns DB error → penalty defaults to 0 (graceful degradation, no false suppression). |
| Bounds | Score never goes below 0.20 floor or above 1.00 ceiling. |
| Macro-feature exemption | F3, F4 only contribute to macro_signals, not signal_events single-name. Verify penalty is computed only on single-name xref aggregations. |

#### S3 — Per-analyst cooldown generalization — `tests/unit/db/test_check_alert_cooldown.py`

| Test | Description |
|------|-------------|
| Golden path | Analyst with rolling_accuracy=0.7 in source_performance → cooldown scaled to (cooldown_hours × 60) × (1 - 0.7) = 108 min (vs blanket 360). Verify scaled value used. |
| Conflict-with-other-features | Two near-simultaneous tweets from same analyst (the kpak82 race) — only first passes cooldown. Verify SQLite `BEGIN IMMEDIATE` serializes the read-check-write. |
| Failure-mode | source_performance has < 5 samples for analyst → fall back to blanket cooldown. |
| HIGH-conviction bypass | Score ≥ high_conviction_threshold=30 → bypass per existing logic. |
| Multi-feature applicability | F1, F2, F3, F5, F8, F11 all standalone-trigger features must respect this cooldown. Test injects synthetic alerts from each SourceType and verifies cooldown applied per `(ticker, source)` tuple. |

#### S4 — Calendar resolver consolidation — `tests/unit/analysis/test_catalyst_resolver_extension.py`

| Test | Description |
|------|-------------|
| Golden path | Query `events_calendar.next_event(ticker="AAPL", types=["earnings","fomc"])` → returns next earnings date from Finnhub + next FOMC from YAML. |
| Conflict-with-other-features | FOMC and earnings on same day for ticker → resolver returns both events sorted by date. |
| Failure-mode | YAML missing → log + fall back to last cached value if < 7 days old, else operator alert. |
| Staleness check | YAML last_refreshed > 7 days → emit source-health warning, fail-closed. |
| Source priority | Finnhub vs yfinance disagreement on earnings date → C1 trust Finnhub (per F6 hardening). |

#### S5 — Data freshness gate — `tests/unit/utils/test_freshness_gate.py`

| Test | Description |
|------|-------------|
| Golden path | `is_fresh("yfinance", 86400)` with last successful update 30 min ago → returns True. |
| Conflict-with-other-features | F3, F4, F5 all check freshness simultaneously for yfinance → all read same source_health table; no race. |
| Failure-mode | source_health table missing entry for source → return False (fail-closed). |
| DEGRADED_MODE multiplier | DEGRADED_MODE active → effective max_age = max_age × 5 (`degraded_freshness_multiplier`). |
| Per-source config | finnhub max_age=60s, yfinance=300s, fred=86400s — verify configurable per source. |

#### S6 — HEAD-vs-GET health check — `tests/unit/utils/test_http_health.py`

| Test | Description |
|------|-------------|
| Golden path | `health_check_get(url)` issues GET with `Range: bytes=0-0`, parses 200/206 as healthy. |
| Conflict-with-other-features | Health probe interval 60s does not interfere with normal feature traffic (separate from main rate-limiter). |
| Failure-mode | URL returns 5xx → `_record_source_error` called; subsequent probes wait for backoff. |
| HEAD asymmetry test | Mock endpoint that returns `MissingAuthenticationTokenException` on HEAD but 200 on GET — verify health check using GET passes. |

#### S7 — Schema migration consolidation — `tests/integration/test_migration_phase2.py`

| Test | Description |
|------|-------------|
| Golden path | Run migration on fresh DB → all 9 schema items created (`holder_intent`, `macro_signals`, `ticker_external_ids`, `beneficial_owner_index`, 6 new SourceType values). |
| Conflict-with-other-features | Migration partial — fails at item 5/9 — atomic rollback restores DB to pre-migration state. |
| Failure-mode | Engine startup version-mismatch → engine refuses to start, exits with operator-actionable message. |
| Idempotency | Running migration twice on already-migrated DB → no-op (uses `CREATE TABLE IF NOT EXISTS` + version check). |
| Concurrent-engine safety | Migration cannot run while live engine holds `/tmp/consensus_engine.lock`. |

#### S8 — Shared yfinance rate-limit — `tests/unit/utils/test_rate_limiter_yfinance.py`

| Test | Description |
|------|-------------|
| Golden path | 3 concurrent yfinance calls → enforced 1s spacing. |
| Conflict-with-other-features | F3 (VIX) + F4 (HYG/SPY/LQD) + F5 (OHLCV) + price_outcome_loop all queue → FIFO, no dropped calls. |
| Failure-mode | 3 consecutive yfinance failures → `is_blocked=True`, all dependent features no-op until clear. |
| Throughput cap | At 1 req/s ceiling, F4's 4-ticker batch (HYG, SPY, LQD, BAMLH0A0HYM2 fallback) takes ~4s — measured. |

#### S9 — Macro-context consumption — `tests/unit/analysis/test_get_macro_context.py`

| Test | Description |
|------|-------------|
| Golden path | F4 wrote `credit_caution` row → `_get_macro_context(ticker)` returns +10pts threshold modifier for cyclicals. |
| Conflict-with-other-features | F3 active (×0.85 cyclicals) + F4 active (+10pts cyclicals) → multipliers compose; threshold becomes `(base + 10) × 0.85`. |
| Failure-mode | macro_signals empty (no rows in 24h) → returns neutral multiplier (1.0); no exceptions. |
| Cap | Combined multiplier never exceeds [0.5, 1.5] bounds. |
| Wired-into-xref | Test verifies `cross_reference.cross_reference()` actually calls `_get_macro_context` (regression: don't repeat dead `regime_detector.py`). |

### 7.3 Cross-feature integration tests

`tests/integration/test_cross_feature_attacks.py`:

| Test | Description |
|------|-------------|
| Attack X1 (Form 4 + S-4 stack) | Inject simultaneous F1 cluster + F2 S-4 same ticker; verify both emit but CC-S2 penalty applied if 3rd source joins. |
| Attack X2 (13D + Reg SHO stack) | F8 + F11 same ticker within 14d on $2.5B (under $3B stacked floor); verify single-feature scoring only, no stack amplification. |
| Attack X3 (FinBERT-pumped breakout) | N/A — F7 dropped. |
| Attack X4 (sock-puppet activist) | Non-whitelisted filer with 2 fabricated 13D campaigns → demoted to xref-only per C5. |
| Attack X5 (Wikipedia + tweet brigade) | F10 + low-trust TweetShift + news velocity → CC-S2 penalty trips at n_active_sources>=3 with low-trust accumulator. |
| End-to-end golden | Live tweet → F1 cluster fires within 5min on same ticker → both emit with correlation-decay penalty=0 (legitimate). |

---

## 8. Rollout

### 8.1 Feature-flag table

All flags live in `config/consensus.yaml`. Default OFF for all 9 features (per hard rule). S1, S6, S7 default ON. S2, S3, S5 default ON behind master flag `phase2_safeguards_enabled` (master ON, sub-OFF until each is verified).

| Flag | Default | Owner section | Notes |
|------|---------|---------------|-------|
| `scanners.insider_cluster_enabled` | `false` | F1 | Sub-flag under existing `sec_background_watchers_enabled` |
| `scanners.insider_cluster_min_weight` | `4` | F1 | Cluster-qualifying total rank weight |
| `scanners.insider_cluster_dollar_floor_per_insider` | `25000` | F1 | $25k per insider |
| `scanners.insider_cluster_dollar_floor_aggregate` | `100000` | F1 | $100k aggregate |
| `scanners.insider_cluster_market_cap_floor` | `300000000` | F1 | $300M |
| `scanners.sec_ma_enabled` | `false` | F2 | Sub-flag under `sec_background_watchers_enabled` |
| `scanners.sec_ma_min_lead_minutes` | `5` | F2 | Kill-criterion lead-time threshold |
| `signals.pre_fomc_enabled` | `false` | F3 | Macro signal |
| `signals.pre_fomc_vix_min` | `18` | F3 | Hardening guard |
| `signals.pre_fomc_yaml_path` | `config/fomc_calendar.yaml` | F3 | Weekly refresh |
| `signals.pre_fomc_max_yaml_age_days` | `7` | F3 | Fail-closed beyond |
| `scanners.credit_equity_divergence_enabled` | `false` | F4 | Macro signal |
| `scanners.credit_equity_breadth_floor` | `0.6` | F4 | A1 breadth filter |
| `scanners.credit_equity_correlation_suppress` | `0.85` | F4 | P2 default |
| `analysis.breakout_atr_enabled` | `false` | F5 | Standalone trigger |
| `analysis.breakout_atr_market_cap_floor` | `500000000` | F5 | $500M (C2) |
| `analysis.breakout_atr_dollar_volume_floor` | `10000000` | F5 | $10M (C1) |
| `analysis.breakout_atr_post_close_delay_min` | `30` | F5 | C5 |
| `analysis.breakout_atr_publish_stop` | `false` | F5 | C4 — never publish stop |
| `analysis.breakout_atr_max_alerts_per_day_n20` | `20` | F5 | Quota |
| `analysis.breakout_atr_max_alerts_per_day_n60` | `5` | F5 | Quota |
| `analysis.breakout_atr_max_alerts_per_day_n252` | `3` | F5 | Quota |
| `analysis.earnings_gate_enabled` | `false` | F6 | Modifier |
| `analysis.earnings_gate_window_days_pre` | `3` | F6 | T-3 |
| `analysis.earnings_gate_window_days_post` | `1` | F6 | T+1 |
| `analysis.earnings_gate_multiplier` | `0.6` | F6 | C2 soft modifier |
| `analysis.earnings_gate_cache_ttl_days` | `7` | F6 | B2 |
| `scanners.activist_13d_enabled` | `false` | F8 | Sub-flag under `sec_background_watchers_enabled` |
| `scanners.activist_13d_whitelist_path` | `config/activist_whitelist.yaml` | F8 | C5 |
| `scanners.activist_13d_min_prior_campaigns` | `2` | F8 | Activist gate |
| `scanners.wikipedia_pageviews_enabled` | `false` | F10 | Annotation |
| `scanners.wikipedia_pageviews_market_cap_min` | `200000000` | F10 | A1 |
| `scanners.wikipedia_pageviews_market_cap_max` | `5000000000` | F10 | A1 |
| `scanners.wikipedia_pageviews_z_min` | `2.5` | F10 | C2 |
| `scanners.wikipedia_pageviews_min_consecutive_hours` | `3` | F10 | C2 |
| `scanners.wikipedia_pageviews_score_cap` | `0.05` | F10 | C3 |
| `scanners.reg_sho_enabled` | `false` | F11 | Standalone (regime-gated) |
| `scanners.reg_sho_market_cap_floor_single` | `2000000000` | F11 | $2B (A1) |
| `scanners.reg_sho_market_cap_floor_stacked` | `3000000000` | F11 | $3B (X2) |
| `scanners.reg_sho_vix_min` | `22` | F11 | A2 stress regime |
| `scanners.reg_sho_hy_oas_min_bps` | `350` | F11 | A2 stress regime |
| `phase2_safeguards_enabled` | `true` | Master | Master toggle for S2/S3/S5 |
| `safeguards.sec_edgar_min_interval` | `0.15` | S1 | Tightened from 0.2 |
| `safeguards.correlation_decay_enabled` | `false` | S2 | Sub-flag (dark-launch first) |
| `safeguards.cooldown_per_analyst_enabled` | `false` | S3 | Sub-flag (audit-prerequisite) |
| `safeguards.calendar_resolver_v2_enabled` | `false` | S4 | Sub-flag |
| `safeguards.freshness_gate_enabled` | `false` | S5 | Sub-flag (gate dark-launch) |
| `safeguards.health_check_use_get` | `true` | S6 | Default ON |
| `safeguards.schema_migration_version` | `1` | S7 | Bumped on each migration |
| `safeguards.yfinance_min_interval` | `1.0` | S8 | New entry |
| `safeguards.macro_context_consumption_enabled` | `false` | S9 | Sub-flag |

### 8.2 Dark-launch sequence

Every feature follows a 3-stage dark-launch via `python3 -m consensus_engine --dry-run --once` (existing entry per `main.py:852`).

**Stage 1 — Log emissions only.**
- Set feature flag = `true` AND set `--dry-run` mode.
- Engine runs the scanner, computes the signal, but `alerts/discord.py` returns logged-but-not-posted (existing behavior at `:325, :373, :402, :446, :473`).
- Capture: emission rate, latency, false-positive observation against manual labeling.
- Required duration: minimum 7 days, ideally over an active news week (covers earnings + at least one macro event).
- Exit criterion: emission rate within ±50% of estimated; no Python exceptions in scanner module logs over 24h.

**Stage 2 — Enable correlation-decay penalty (CC-S2) in dark mode.**
- After Stage 1 of feature, enable `safeguards.correlation_decay_enabled = true` in dry-run.
- Verify the feature's would-be alerts get correctly attenuated when correlated with other emissions; verify legitimate solo emissions pass through unchanged.
- Required duration: 7 days.
- Exit criterion: penalty distribution matches expectation (no all-zero, no everyone-clamped).

**Stage 3 — Production enable.**
- Flip feature flag to `true` AND remove `--dry-run`.
- Live alerts fire to Discord channel.
- 7-day shadow precision (from Stage 1 logs) must be ≥ kill-criterion threshold for the feature.
- After 14 days of live operation, evaluate against the feature's kill criterion.

### 8.3 Success metrics

**Definition: actionable alert.**
An alert is "actionable" if EITHER (a) the post-alert 1h price moved ≥ 0.5% in the alert direction, OR (b) the post-alert 24h price moved ≥ 1.5% in the alert direction. Measurement uses `alert_history.price_1h_later` / `alert_history.price_24h_later` (`db.py:784–805`). Comparison set: 60-day rolling window, computed nightly via the kill-switch loop (8.5).

**Targets.**

| Metric | Target | Computation |
|--------|--------|-------------|
| Precision delta (overall) | **+3 to +5pp** | Rolling 60d actionable-rate, with-Phase-2 vs without-Phase-2 (counterfactual: replay alerts with feature flags off). |
| Lead-time delta (overall) | **+10 to +20 min median** | Median time-to-mainstream-coverage of alerts where Phase-2 is the primary trigger. |
| Coverage delta (overall) | **+15 to +20% net new actionable** | New-feature emissions that produce actionable alerts NOT covered by baseline (TweetShift) signals. |
| **Regime-stratified targets** | | |
| Precision delta in low-vol regime (VIX < 15 sustained 30d+) | **+1 to +3pp** | Same calculation but only on days within stratum. |
| Coverage delta in low-vol regime | **+5 to +10%** | Same calculation but stratified. |

**Auto-disable on stratified miss.**
For each feature flag, the nightly kill-switch loop checks 14-day rolling precision *within the relevant stratum*. If precision < kill-criterion floor for 14 consecutive days within the regime, auto-disable the flag and post a Discord notice via existing alert path (`alerts/discord.py:316`).

### 8.4 Kill switches

For every feature, a programmatic nightly check runs in a new `kill_switch_loop` wired into `main.py:455` neighborhood (alongside `macro_digest_loop`, hourly check). The loop:

1. Reads 60-day rolling alerts for the feature from `alert_history`.
2. Computes precision per kill criterion.
3. If precision < threshold: sets feature flag to `false` in DB-backed override (overrides YAML), posts Discord ops alert via `alerts/discord.py:send_instant_ping` with `signal_type="OPS_KILL_SWITCH"`.

| Feature | Programmatic check (nightly) |
|---------|----------------------------|
| F1 | If 21d-forward sector-adjusted precision (close > entry by ≥ 3%) < 55% on broad-participation regime sub-period over 90d rolling → disable. Also: if 10b5-1 false-positive rate > 15% in random sample of 50 alerts → disable. |
| F2 | If false-positive rate (no real deal-announcement press release within ±2h) > 25% on 30d backtest → demote to xref-only. If median lead-time over Bloomberg/Twitter < 5 min → demote. |
| F3 | If mean 24h pre-FOMC excess return on filtered subset < +25bps over 8 consecutive meetings, OR positive-day frequency < 60% → disable. Use 5-year rolling window per A's S3. |
| F4 | If false-positive rate (no >3% SPY drawdown within 20 trading days) > 60% on 24-month backtest stratified by broad-participation regime → disable. |
| F5 | N=20: if 1d forward precision (next-day close > today close) < 52% on filtered cohort over 90d rolling → disable N=20 tier. N=252: same with 50% threshold. |
| F6 | If precision delta on social signals fired in T-3 to T+1 vs T-30 < 5pp on 6-month backtest → disable gate. |
| F8 | If 21d forward precision (positive sector-adjusted return) < 50% on whitelisted-activist subset over 12-month backtest → disable standalone path. |
| F10 | If precision delta when used as +0.05 multiplier on tweet-driven primaries (gated by C1+C2) < 1pp on 90d backtest → disable. |
| F11 | If 5d forward (T+5 to T+13) excess return on >$2B mkt cap cohort during stress regime (VIX>22 AND HY OAS>350) < +0.5σ vs sector base over 12-month backtest → disable standalone. |

Implementation: kill-switch state stored in new DB table `feature_flags_runtime` (key, value, reason, disabled_at). YAML defines defaults; runtime DB overrides. Operator can re-enable manually via `!enable_feature <flag>` Discord command (new command in `alerts/commands.py`).

### 8.5 Sequencing — milestone list (smallest-blast-radius first)

**Milestone 0 — Preconditions (MUST ship before ANY feature).**

These are dependencies the surviving features assume. Order within M0 matters: schema first, then locking primitives, then consumption-pattern hooks.

| Step | What | Why first |
|------|------|-----------|
| M0.1 | Audit M3 cooldown fix (CC-S3) — replace `db.check_alert_cooldown` `:714–781` with per-analyst precision-weighted | Audit-prerequisite. The kpak82 race lets a spoofed signal fire twice within minutes; every new instant-trigger inherits this bug. |
| M0.2 | Schema migration consolidation (CC-S5/S7) — `holder_intent`, `macro_signals`, `ticker_external_ids`, `beneficial_owner_index`, 6 new SourceType values, FRED API key in `/root/.openclaw/.env` | Required by F1/F4/F8/F10 modules' DB writes; FRED key required by F3+F4. |
| M0.3 | Shared SEC EDGAR semaphore (CC-S1) — tighten `sec_edgar` to 0.15 in `utils/rate_limiter.py:29`, audit existing call sites, document jittered offset convention | Required by F1, F2, F8 — without this they collide and trigger 10-min IP bans. |
| M0.4 | Shared yfinance rate-limit string (CC-S4/S8) — add `yfinance: 1.0` entry, audit existing call sites in `main.py:807–832`, `analysis/technical.py:54`, `scanners/volume_scanner.py` | Required by F3, F4, F5; existing `price_outcome_loop` traffic must respect new limit. |
| M0.5 | Data freshness gate (CC-S5/S7) — `utils/freshness_gate.py` NEW module | Required by F3, F4, F5, F11 (fail-closed semantics). |
| M0.6 | HEAD-vs-GET health check helper (CC-S6/S6) — `utils/http.py` extension | Preventative; documented in `consensus_engine/scanners/CLAUDE.md` for next maintainer. |
| M0.7 | Correlation-decay penalty (CC-S2) — `analysis/correlation_decay.py` NEW + `cross_reference.py:333` hook | Required for X1/X2/X3/X4/X5 attack defense. **Dark-launch only at this stage** (`safeguards.correlation_decay_enabled=false`); flip to true at start of M2. |
| M0.8 | Calendar resolver consolidation (CC-S4/S6) — extend `analysis/catalyst_resolver.py`, FOMC YAML at `config/fomc_calendar.yaml`, weekly-refresh job in `macro_digest_loop` neighborhood | Required by F3, F6. |
| M0.9 | Macro-context consumption pattern (CC-S8/S9) — `cross_reference._get_macro_context` at `:333` | Required by F3, F4 to avoid dead-code fate of `regime_detector.py`. |

**Exit criteria for M0:** all 9 safeguards land with green test suite, dark-launched (correlation-decay off, freshness-gate on, others on/off per matrix above), audit M3 cooldown fix verified by reproducing kpak82 race in test harness AND confirming new code prevents it. **Run `python3 -m pytest tests/integration/ -v --tb=short 2>&1 | tail -20` and confirm pass.** Production `--live` run for 7 days with M0 only enabled before M1 begins.

**Milestone 1 — Feature 1 (Cluster Form 4).**

Lowest infrastructure risk (reuses existing `sec_edgar.py` plumbing) and highest expected lift per converge ranking (P2 composite 5.00, A=KEEP/B=KEEP/C=KEEP). One feature; small blast radius.

- Ship `consensus_engine/scanners/insider_cluster.py` (NEW).
- Wire into `main.py:343–347` behind `scanners.insider_cluster_enabled`.
- Run dark-launch Stage 1 (7 days) → Stage 2 (7 days; flip `correlation_decay_enabled=true`) → Stage 3 production.
- After 14 days production, evaluate F1 kill criterion. If passes, proceed to M2.

**Milestone 2 — Features 6, 8 (Cluster A high-signal members + earnings gate).**

F8 shares Cluster A SEC infrastructure with F1; F6 is a contextualizer (no new alert source) that pairs with every other feature including F8. Both are HIGH-confidence per converge.

- Ship F8 (`consensus_engine/scanners/sec_activist_13d.py`) AND F6 (extends `scanners/earnings_calendar.py` + `analysis/earnings_gate.py` NEW).
- F6 is gate-only (no new emission), so dark-launch is shorter (3 days observation).
- F8 follows full 3-stage dark-launch.
- After 14 days production, evaluate kill criteria.

**Milestone 3 — Features 2, 3, 4 (M&A + macro/regime cluster).**

F2 completes Cluster A (SEC). F3 + F4 are macro/regime features that depend on FRED key and CC-S8 consumption. They are MEDIUM confidence per converge and feature-fire concentration shifts to macro context.

- Ship F2 (`scanners/sec_ma_filings.py`) and F3 (`scanners/fomc_drift.py`) and F4 (`scanners/credit_equity_divergence.py`).
- F3 is calendar-bound (T-1 of FOMC dates only) — dark-launch is 1 FOMC cycle minimum (≥ 6 weeks).
- F2 follows full 3-stage dark-launch.
- F4 dark-launch overlaps with F2/F3.

**Milestone 4 — Features 5, 10, 11 (broader infrastructure footprint).**

F5 is technical-breakout with the largest universe scope (top-N from ApeWisdom + active TweetShift hits). F10 is annotation-only with low risk. F11 is regime-gated (will be silent most months).

- Ship F5 (`analysis/breakout_atr.py`), F10 (`scanners/wikipedia_pageviews.py`), F11 (`scanners/reg_sho_threshold.py`).
- F5 has the highest blast radius (universe scope, dollar-volume threshold tuning) — dark-launch is 14 days minimum.
- F10 is annotation only; can ship after 7 days dark-launch.
- F11 will rarely fire; ship via 14-day dark-launch but expect few emissions.

**Milestone-ordering rationale (sanity check against converge ranking):**

Converge file orders by P2 composite + verdict-confidence:
1. F1 (5.00, all KEEP) — M1 ✓
2. F2 (4.50, all STRENGTHEN) — M3 (deferred to share Cluster A infra with F8)
3. F3 (4.20, A=STR B=KEEP C=STR) — M3
4. F4 (4.00, A=STR B=STR C=KEEP) — M3
5. F5 (4.00, A=STR B=KEEP C=STR) — M4
6. F6 (4.00, A=KEEP B=STR C=STR) — M2 ✓ (high confidence, gate, pairs broadly)
7. F8 (4.00, A=KEEP B=STR C=STR) — M2 ✓ (high confidence on whitelist subset)
8. F10 (3.70, all STRENGTHEN) — M4
9. F11 (3.50, A=STR B=STR C=KEEP) — M4

This ordering ships **highest-confidence first** (F1 → F6+F8 → F2+F3+F4 → F5+F10+F11), groups Cluster A members where SEC infrastructure is shared (F1 in M1, F2+F8 use M0.3 semaphore), and defers the macro features (F3, F4) until M0.9 macro-context consumption is verified live.

---

## 9. Risks & Open Questions

### 9.1 Risks specific to this plan

1. **Audit M3 (CC-S3) is upstream-dependent and not yet merged.** The audit recommends the per-analyst precision-weighted cooldown but the implementation has not landed in the repo (per `MEMORY.md`: "Signal engine audit (2026-04-24) — full deliverable at plans/AUDIT_RESEARCH_2026-04-24.md awaiting /ralplan --deliberate"). M0.1 inherits an unresolved spec dependency; if the audit's M3 spec changes (e.g., chooses a different weighting function), every standalone-trigger feature inherits the new contract. **Mitigation:** treat M0.1 as code-frozen-from-audit-spec at the moment work begins; do not let M3 re-spec mid-implementation.

2. **Audit also claims `signal_events` schema may be invisible to xref ("78.4% Phase-2 silent-drop").** If the audit's diagnosis is correct, F1, F2, F8 will emit `signal_events` rows that xref never reads. CC-S9 wires `_get_macro_context` for F3/F4, but this does NOT fix the underlying signal_events read path for single-name SourceTypes. **This is not addressed in M0** as currently scoped. **Open question 9.2.A below.**

3. **FRED API key provisioning blocks F3 and F4 simultaneously.** Both depend on FRED via M0.2. If key acquisition fails (FRED requires registration but is reliably available) or rate-limit class is unexpectedly low, both M3 features stall. **Mitigation:** provision key in M0 before any feature module work begins; verify 120 req/min in test cycle.

4. **Cluster A semaphore tightening from 0.2s to 0.15s** (CC-S1) means existing `_run_sec_check` in xref `cross_reference.py:80` traffic immediately competes with new feature traffic. Existing code does not yet `await rate_limiter.acquire("sec_edgar")` (verify per audit). The migration is not just additive — it requires a sweep of all existing SEC call sites. **Mitigation:** include audit step in M0.3 to grep for any direct `aiohttp.get()` against `sec.gov` domains and route through rate-limiter.

5. **Correlation-decay penalty (CC-S2) may over-penalize legitimate convergence.** When a real catalyst (e.g., an earnings beat) genuinely produces multi-source confirmation (TweetShift + News + Form 4 cluster all in 30 min), CC-S2 still penalizes. The 12h same-direction +0.30 factor was tuned by C against attack scenarios but not against legitimate-convergence baselines. **Mitigation:** dark-launch period in M0.7 must measure penalty distribution and tune factors before M2 production. If penalties on legitimate alerts exceed 30%, factors must be relaxed.

6. **F5 universe-scope creep risk.** F5 spec says "top-N from ApeWisdom + active TweetShift hits", but the bot's TweetShift cohort is curated and ApeWisdom universe rotates daily. Unclear how big "top-N" is in practice — could grow to 200+ tickers/cycle, blowing the yfinance budget. **Mitigation:** hard cap N=50 in F5 module config; any growth requires explicit operator approval.

7. **F8 LLM-classifier fallback (B2) shares OpenRouter budget with existing `llm_scorer`.** Existing `_sem_llm=2` at `cross_reference.py:29` is already saturated during alert bursts. F8 backfill (B1) might issue thousands of LLM calls in a one-time job. **Mitigation:** B1 backfill runs as a separate offline script (not in-engine), uses a dedicated batch-mode LLM call budget that doesn't compete with live `_run_llm_scorer`.

8. **Activist whitelist (F8 C5) is manually curated.** YAML at `config/activist_whitelist.yaml` requires operator maintenance; a missing newcomer (e.g., a new credible fund) means alpha is lost; a stale departed name means false-positive standalone alerts. **Mitigation:** quarterly review checklist documented in spec; tie to M3 evaluation cadence.

9. **Calendar-resolver weekly refresh (CC-S6) creates a single-point-of-failure.** If the FOMC YAML refresh job fails silently (e.g., HTTP 500 on Federal Reserve site for 8 consecutive days), F3 fail-closes. Operator does not know unless source-health alert fires. **Mitigation:** explicit Discord ops alert on staleness (already specified, must be tested).

10. **F11 regime gate makes the feature dormant in most regimes.** A2 requires VIX > 22 AND HY OAS > 350bps. In the current low-vol regime (2025–2026 forecast), F11 fires near-zero times per quarter. If F11 contributes ZERO coverage for the first 6 months of operation, operator may incorrectly conclude the feature is broken. **Mitigation:** explicit "F11 dormant" telemetry surfaced in `!status` output and in nightly precision report; document in operator runbook.

### 9.2 Open questions (must resolve before M0 starts)

**9.2.A. `signal_events` schema audit fix vs S9 workaround.**
The audit identifies that `signal_events` rows from non-TWITTER SourceTypes may not be visible to xref. The current S9 (macro context consumption) addresses macro features F3/F4 but NOT single-name features F1/F2/F8/F11 which write signal_events with SourceTypes `INSIDER_CLUSTER`, `M_AND_A`, `ACTIVIST_FILING`, `REG_SHO`. **Decision required:** (a) include schema fix in M0 (likely +200 LOC, audit-spec dependency), or (b) work around in S9 by extending `_get_macro_context`-equivalent reader for single-name SourceTypes. **Recommendation:** option (a) — fix the audit's bug at the schema layer in M0. Option (b) is a deeper bug-by-bypass that compounds.

**9.2.B. Precision-baseline measurement window.**
The success metrics (8.3) compare with-Phase-2 vs without-Phase-2 over 60d rolling. **Decision required:** does "without-Phase-2" mean (a) historical pre-launch baseline (frozen 2026-Q1), or (b) live counterfactual via flag-off replay nightly? **Recommendation:** (b) is more defensible because regime drifts; but requires DB to record both factual and counterfactual decision-snapshots.

**9.2.C. Calibration model retraining cadence.**
`config/consensus.yaml:202` has `retrain_enabled: false`. Per CC-S5 schema migration, 6 new SourceType values feed `decision_snapshots.feature_vector_json`. If retraining stays disabled, the calibration model never learns new SourceTypes. **Decision required:** enable retraining at M0 (weekly cadence) vs defer to post-M4 (lower risk but means uncalibrated for ~3 months). **Recommendation:** enable weekly retraining at M0, gated by minimum-sample threshold per SourceType.

**9.2.D. Whether to dark-launch CC-S2 correlation-decay before features depend on it.**
M0.7 ships CC-S2 dark; M2 (F8 ship) flips it on. **Decision required:** does dark-launch period need to extend through M1 (F1 production live without CC-S2 active) — meaning F1 ships unprotected against attacks X1/X4 for 14+ days — or do we flip CC-S2 to live alongside F1's production enable in M1 Stage 3? **Recommendation:** flip CC-S2 live at the same moment F1 enters Stage 3. Justification: F1 alone cannot attract X1/X4 attacks (those require ≥2 features active), so CC-S2 has no work to do while only F1 is live; flipping it on at F1 production-enable gives time to observe distribution before F8 ships in M2.

**9.2.E. Activist whitelist (F8 C5) initial seed list.**
**Decision required:** which filer-CIKs go on the v1 whitelist at M2 ship? Elliott Investment Management, Starboard Value LP, Engaged Capital LLC, Carl Icahn (Icahn Capital), Pershing Square Capital are obvious. Less obvious: Cevian Capital, ValueAct Capital, Trian Fund Management, JANA Partners. **Recommendation:** seed v1 with the top-12 activists by completed-campaign volume per Brav-Jiang-Kim historical dataset; quarterly review process documented in `config/activist_whitelist.yaml` as YAML comment.

---

## 10. Spec Scaffold

The canonical spec lives at:

**`docs/superpowers/specs/discovery-2026-04-24-features.md`** (created by this deliverable).

It carries:
- Canonical feature IDs F1–F11 (with F7, F9, F12, F13, F14 marked DROPPED with post-mortem references).
- Canonical names per the converge file's "Final hardened description" lead.
- Hardened description (1 paragraph each, copied verbatim from `33-final-feature-set.md` to keep specs and plans aligned).
- Kill criterion (final form) per feature.
- Module path manifest (matching the canonical path manifest in this deliverable's preamble).

Reference this spec in any future implementation planning by ID (e.g., "implementing F8 per spec discovery-2026-04-24-features.md") rather than re-stating the hardened description.

