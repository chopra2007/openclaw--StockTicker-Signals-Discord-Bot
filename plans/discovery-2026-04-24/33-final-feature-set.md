# 33 — Final Feature Set (Discovery Phase 3 Converge)

**Date:** 2026-04-24
**Inputs reconciled:**
- `plans/discovery-2026-04-24/20-candidate-features.md` (14 ranked Phase-2 candidates)
- `plans/discovery-2026-04-24/30-critique-signal-quality.md` (Red-Team A — regime lens)
- `plans/discovery-2026-04-24/31-critique-feasibility.md` (Red-Team B — data/rate-limits/ToS lens)
- `plans/discovery-2026-04-24/32-critique-adversarial.md` (Red-Team C — manipulation lens)
- P0 system map `plans/discovery-2026-04-24/00-system-map.md`
- AUDIT history `plans/AUDIT_RESEARCH_2026-04-24.md` (78.4% silent-drop, kpak82 26-min cooldown race, dead `regime_detector.py`)

**Converge rules applied:**
1. ≥2 KILLs → drop, no appeal
2. Exactly 1 KILL → STRENGTHEN must address the killing lens AND not undermine the other two; if not constructible, drop
3. 0 KILLs → UNION of STRENGTHEN proposals; resolve conflicts explicitly

**Deliberation order:** mechanical roll-up first; then per-feature reconciliation; then cross-cutting safeguards; then realistic edge.

---

## 1. Executive Reconciliation

- **Surviving features: 9.** Dropped: 5. (Drops: F7 FinBERT, F9 EDGAR Velocity, F12 VIX Term-Structure, F13 Influencer Cluster, F14 PDUFA — see post-mortems.)
- **Dominant theme #1 — News-text family collapsed under the manipulation lens.** F7 (FinBERT) was killed by C because PR-wire placement at $300–$2,500 is a publicly-priced direct attack vector, and the salvage path collapses the feature to a lexicon-only second-source confirmer with no real FinBERT contribution. The collapse cascaded to cross-feature attacks X3 and X5.
- **Dominant theme #2 — SEC EDGAR Cluster A survived but gained a hard semaphore dependency.** F1, F2, F8 all survived but they share a fair-use 10 req/s aggregate ceiling on `data.sec.gov` / `www.sec.gov/cgi-bin` / `efts.sec.gov`. F9 was the marginal-value member that competed for the same budget — both A and B killed it. The surviving Cluster A members must share `rate_limiter.acquire("sec_edgar")` with jittered start offsets; this is a precondition before any of the three ships.
- **Dominant theme #3 — Macro/index features lost VIX Term-Structure (F12); the remaining macro coverage is narrower but better-defended.** F12 was killed by C on signal-redundancy + manipulation grounds (Features 3 and 4 already cover the macro/regime axis). F3 (pre-FOMC) and F4 (credit-equity) survive with explicit consumption-pattern requirements so they do not join the audit's dead `regime_detector.py`.
- **Dominant theme #4 — Calendar-driven gates survived in different ways.** F6 (earnings) survived; F14 (PDUFA) was dropped because B's Akamai-403 finding on the FDA calendar HTML page combined with three serial upstream failure modes left no constructible STRENGTHEN that all three lenses would accept.
- **Dominant theme #5 — Cross-cutting safeguards now precondition every surviving instant-trigger feature.** The audit's M3 cooldown fix, a new correlation-decay penalty at `cross_reference.py:333`, a shared SEC semaphore, a shared `yfinance` rate-limit string, and a generalized data-staleness gate must ship BEFORE the first surviving feature goes live. These are not optional hardenings; they are dependencies the surviving features assume.

---

## 2. Verdict Roll-Up Table

Re-derived directly from the three critique files. Counts confirm the preliminary hint was correct.

| # | Feature | A | B | C | KILLs | Rule applied | Outcome |
|---|---|---|---|---|---|---|---|
| 1 | Cluster Form 4 Open-Market Buys | KEEP | KEEP | KEEP* | 0 | Rule 3 (UNION) | **SURVIVE** |
| 2 | SEC S-4 / 425 Real-Time M&A | STRENGTHEN | STRENGTHEN | STRENGTHEN | 0 | Rule 3 (UNION) | **SURVIVE** |
| 3 | Pre-FOMC Drift Trade | STRENGTHEN | KEEP | STRENGTHEN | 0 | Rule 3 (UNION) | **SURVIVE** |
| 4 | FRED Credit-Equity Divergence | STRENGTHEN | STRENGTHEN | KEEP | 0 | Rule 3 (UNION) | **SURVIVE** |
| 5 | Volume-Confirmed Breakout + ATR | STRENGTHEN | KEEP | STRENGTHEN | 0 | Rule 3 (UNION) | **SURVIVE** |
| 6 | Earnings-Window Risk Gate | KEEP | STRENGTHEN | STRENGTHEN | 0 | Rule 3 (UNION) | **SURVIVE** |
| 7 | FinBERT + Catalyst Lexicon | STRENGTHEN | STRENGTHEN | **KILL** | 1 | Rule 2 (no acceptable STRENGTHEN) | **DROP** |
| 8 | 13D Activist + 13G→13D Conversion | KEEP | STRENGTHEN | STRENGTHEN | 0 | Rule 3 (UNION) | **SURVIVE** |
| 9 | SEC EDGAR Full-Text Mention Velocity | **KILL** | **KILL** | STRENGTHEN | 2 | Rule 1 (auto-drop) | **DROP** |
| 10 | Wikipedia Pageview Spike | STRENGTHEN | STRENGTHEN | STRENGTHEN | 0 | Rule 3 (UNION) | **SURVIVE** |
| 11 | Reg SHO Threshold List Entry/Exit | STRENGTHEN | STRENGTHEN | KEEP | 0 | Rule 3 (UNION) | **SURVIVE** |
| 12 | VIX Term-Structure Flip | STRENGTHEN | STRENGTHEN | **KILL** | 1 | Rule 2 (no acceptable STRENGTHEN) | **DROP** |
| 13 | Influencer Cluster-Convergence | **KILL** | KEEP | **KILL** | 2 | Rule 1 (auto-drop) | **DROP** |
| 14 | PDUFA / AdCom Proximity Tag | KEEP | **KILL** | STRENGTHEN | 1 | Rule 2 (no acceptable STRENGTHEN) | **DROP** |

\* C verdict on F1 was "KEEP with one minor tweak" — folded as additive STRENGTHEN.

**Counts:**
- Survivors: **9** (Features 1, 2, 3, 4, 5, 6, 8, 10, 11)
- Drops: **5** (Features 7, 9, 12, 13, 14)
- Auto-drops via Rule 1: 2 (Features 9, 13)
- Rule-2 drops (1 KILL with no acceptable STRENGTHEN): 3 (Features 7, 12, 14) — see post-mortems for why no all-three-lens STRENGTHEN was constructible

---

## 3. Surviving Features

Detail blocks in P2 ranked order. Each block reflects the UNION of accepted STRENGTHEN proposals; conflicts are surfaced and resolved.

---

### Feature 1 — Cluster Form 4 Open-Market Buys

**Domain:** Insider/Filings · **P2 composite:** 5.00 · **Verdict map:** A=KEEP, B=KEEP, C=KEEP-with-tweak

**Final hardened description:** Detect ≥2 distinct insiders filing Form 4 with `transactionCode == "P"` AND `aff10b5One == false` on the same ticker within a rolling 14-day window; emit a standalone instant-trigger alert with rank-weighted size and z-scored insider history. Rank weights: CEO/CFO/Chair=3, COO/President=2, other officer=2, director=1, 10% holder=1; cluster qualifies at total weight ≥ 4. Dollar floor $25k per insider AND ≥$100k aggregate. Z-score each buy against the insider's trailing 2-year personal buy distribution; flag z ≥ 2 as bonus weight. Auto-retract alerts if a `4/A` arrives within 5 days reducing share count > 50%. Fuzzy name+address match on filer registration to merge multi-CIK reporters; a beneficial-owner detector inspects Form 3 history — if multi-CIKs all appeared on the same Form 3, treat as one. Liquidity gate: market cap ≥ $300M. **NEW from C-tweak:** (i) reject cluster trigger if any constituent buy is at exactly the same price (within $0.01) as a recent grant (Form 4 with `transactionCode='A'`) — flags grant-disguise attacks; (ii) require ≥2 *independent beneficial owners* (defined by non-overlapping prior Form 3 disclosures), not just ≥2 CIKs; (iii) cluster aggregate USD-volume must equal at least the median recent week's open-market activity in the issuer (defends against tiny token buys for cosmetic effect). All per-filing XML fetches MUST go through `await rate_limiter.acquire("sec_edgar")`; per-cycle XML fetch budget capped at 30 to bound backlog burst.

**Failure modes (combined):**
- 10b5-1 plan executions disguised as discretionary (post-2022 cooling-off period gameable; checkbox-only filter is lossy).
- Amendments (`4/A`) voiding or restating prior buys — alerts go stale (handled by retract logic).
- Board-grant batches mis-coded as `P` — handled by C's price-match-to-grant check.
- Multi-CIK trust splitting — handled by beneficial-owner detector.
- Sub-300M-cap squeeze trap — handled by liquidity gate.
- Mar 2020-style stress regime: signal works (Lakonishok-Lee 6-month abnormal +14% on 2007-09 financials cohort) but path volatility is enormous — alert text must annotate "expect path volatility in stress regimes" (UX nit, not signal-quality concern).

**Kill criterion (final):** If 21-day forward precision (close > entry by ≥3% sector-adjusted) is < 55% on the all-cluster cohort over a 90-day rolling window evaluated on the broad-participation regime sub-period (per A's S3 stratification), OR if 10b5-1 false-positive contamination exceeds 15% in a manual sample of 50 alerts, kill the standalone-trigger path and downgrade to xref-only +25 boost.

**Instant-trigger eligibility (post-hardening):** YES. Explicitly named in CLAUDE.md ("insider trading"). The C-tweak hardening tightens manipulation defense without breaking instant-trigger eligibility — the attack-defense ratio favors the defender because A1/A2/A3 attacks all require real capital commitment.

**Minimum implementation touch:** Reuse existing `consensus_engine/scanners/sec_edgar.py:173` (`fetch_form4_details`). New module `consensus_engine/scanners/form4_cluster.py` with poll loop. Wire into `main.py:343–347` alongside existing `sec_8k_watcher_loop` gate (separate `form4_cluster_enabled` flag). Standalone alert via `alerts/discord.py:316` (`send_instant_ping`); pass `signal_type="INSIDER_CLUSTER"`. Cross-ref boost via `signal_events` row at `db.py:602` for new SourceType `INSIDER_CLUSTER`. Beneficial-owner detector requires new schema migration (`beneficial_owner_index` table — small, ~10k rows lifetime).

**Cross-cutting dependencies:**
- Shared SEC EDGAR semaphore (CC-S1) — must use `rate_limiter.acquire("sec_edgar")` with jittered offset (e.g., :00 of every minute).
- Audit M3 cooldown fix (CC-S3) — required precondition; the cooldown race lets a spoofed cluster fire twice within minutes.
- Correlation-decay penalty (CC-S2) at `cross_reference.py:333` — protects against Attack X1 (Form 4 + S-4/425 stack).
- Beneficial-owner-history table (new schema migration grouped under CC-S5).

---

### Feature 2 — SEC S-4 / 425 Real-Time M&A Detection

**Domain:** Insider/Filings · **P2 composite:** 4.50 · **Verdict map:** A=STRENGTHEN, B=STRENGTHEN, C=STRENGTHEN

**Final hardened description:** Detect new S-4 or 425 filings via `getcurrent` atom feed (`type=425&output=atom` and `type=S-4&output=atom`). Classify as fresh-deal announcement (acquirer-CIK references target-CIK for first time in 30 days). Parse offer per-share value (cash/stock/mixed). Emit standalone alert if 2-source-rule satisfied (paired with cluster Form 4 in window OR major-wire headline within ±15 min OR options activity >3σ vs 30d ADV in target). Body parser regex: `merger agreement|definitive agreement|per share`. **NEW union of STRENGTHENS:**
- (A1) Regime-aware downgrade: presence of `termination|amendment|withdrawn` keywords → xref-only, never standalone.
- (A2) Re-cut filter: no prior 425 from same acquirer in trailing 14 days referencing same target.
- (A3) `VIX > 30` OR FOMC announcement within 48h → suppress standalone (downgrade to xref) — credit-shock regimes presage terminations not deal pops.
- (A4) Antitrust-active-regime tag: when sector-CIK has had ≥2 deal blocks in trailing 18 months, append "antitrust regime: high" to alert; user decides.
- (B1) Backfill validation: `aff10b5One`/Item-1.01 cross-ref logic verified on 6-month historical replay before going live.
- (B2) 60s same-target-CIK cooldown PLUS dedup on `accession_number` for 425 amendments.
- (C1) Require both filer AND target to be on the 425 (target's CIK appears as co-filer or named party in SUBJECT-COMPANY field, not just referenced).
- (C2) 425/A withdrawal monitor with retract-message on prior alerts within 7 days.
- (C3) Penalty if filer has no prior SEC filing history (CIK age < 90 days or first 10-K never filed).
- (C4) Cross-validate with at least one of: target options activity >3σ vs 30d, OR major-wire headline within ±15 min — creates real second source vs sock-puppet Discord post.

**Conflict resolution:** None. A's "regime-aware filter" and C's "real second-source" are complementary; both shipped.

**Failure modes (combined):**
- Many 425s are routine investor-presentation or post-announcement material (handled by re-cut and termination filters).
- Definitive Agreement may be filed as 8-K Item 1.01 instead of immediate 425 (acceptable graceful degradation — alert won't fire prematurely).
- Sham-425 from sub-shell with target name mentioned (handled by C1 + C3).
- Deal-termination cascade in rate-shock regimes (handled by A1 + A3).
- Antitrust-blocked deal in sector with active scrutiny (handled by A4 — tagged, not suppressed).

**Kill criterion (final):** If false-positive rate (alerts not corresponding to a real deal-announcement press release within ±2h) exceeds 25% on a 30-day backtest, OR if median lead-time over Bloomberg/Twitter is < 5 minutes, kill the standalone-eligibility and downgrade to xref-only.

**Instant-trigger eligibility (post-hardening):** Conditional YES — when the new C4 cross-validation (target options >3σ OR major-wire ±15 min) AND the existing 2-source pairing (Form 4 cluster in 14d OR analyst tweet in 60 min) BOTH hold. The double-gate is necessary because A's antitrust regime can shift the prior, and C1 plus C4 together address X1 (Form 4 + 425 stack attack).

**Minimum implementation touch:** New module `consensus_engine/scanners/sec_ma_watcher.py`. Wire into `main.py:343` behind same `scanners.sec_background_watchers_enabled` flag with sub-flag `sec_ma_enabled`. Cross-ref boost via `signal_events` write at `db.py:602` with SourceType `M_AND_A`. Reuse existing `alerts/discord.py:316` for instant-ping when 2-source rule satisfied. Antitrust regime tag requires new `sector_antitrust_history` config table (manually maintained, small).

**Cross-cutting dependencies:**
- Shared SEC EDGAR semaphore (CC-S1).
- Correlation-decay penalty (CC-S2) — defends against Attack X1.
- Calendar resolver for FOMC suppression (CC-S6 — Cluster D from P2).
- Audit M3 cooldown fix (CC-S3).
- Per-CIK age check requires backfill from `submissions.json` (folded into Feature 8's backfill job to share infrastructure).

---

### Feature 3 — Pre-FOMC Drift Trade

**Domain:** Technical/Quant · **P2 composite:** 4.20 · **Verdict map:** A=STRENGTHEN, B=KEEP, C=STRENGTHEN

**Final hardened description:** Hard-coded calendar of 8 scheduled FOMC announcement dates per year. At 14:00 ET on T-1, fire long-SPY/QQQ alert IF (a) `VIX > 18`, (b) VIX up >10% over prior 5 sessions, (c) prior 24h SPY return ≤ 0. Exit at 14:00 ET on FOMC day (15 min pre-announce). NEVER hold through announcement. Hard time-stop at 14:00 ET on FOMC day. Stop-loss at entry × (1 − 0.6%). **NEW union of STRENGTHENS:**
- (A1) Rates-regime kill switch: if 2yr Treasury yield change over prior 5 sessions exceeds ±20bps, suppress.
- (A2) Rolling-3 kill: if the prior 3 FOMC meetings on the filtered subset returned negative cumulative excess, pause standalone fire and demote to thesis-only until 2 consecutive positive prints rebuild confidence.
- (A3) Calibration logging: count gated-out would-be-entries per quarter; if >75% of meetings are gated for a full year, the feature contributes no coverage — operator alert, not silent.
- (C1) Refresh FOMC calendar **weekly** (B's annual scrape is correct under normal conditions but C's emergency-meeting attack vector requires fresher cache); fail-closed flag if calendar is older than 7 days.
- (C2) EFFR (effective-funds-rate) deviation kill-switch: if realized fed-funds rate moves >5bps inside the day, suppress alert chain for 24h.
- (C3) Front-running mitigation: publish alert only when SPY auction-imbalance shows expected exit liquidity (trailing 10-min ADV ≥ 90th percentile).
- (C4) Slight randomization of alert send time (±90 sec around 14:00 ET) — adds noise to front-runner's expected pickoff window.
- (NEW shared) Define and wire the consumption pattern explicitly — per A's S2 systemic concern: cross_reference must use this signal, not just write to `signal_events`. Specifically: `cross_reference._get_macro_context` must apply `confidence_threshold *= 0.85` on cyclicals/small-caps when pre-FOMC long is active. Without explicit consumption, this is a measurement that nobody reads.

**Conflict resolution:** B argued "scrape annually — calendar is known years in advance" while C argued "refresh weekly — emergency meetings break the cache." C wins because (i) emergency meetings are real (Mar 2020), (ii) weekly refresh is one extra HTTP GET/week which is trivially within Fed's Cloudflare-cached endpoint budget, and (iii) the failure mode of stale cache is silent — operator never knows. Weekly refresh is strictly safer and B's concern (low API budget) is moot at this volume.

**Failure modes (combined):**
- Hawkish-surprise wipeout — handled by hard time-stop.
- Inter-meeting emergency cuts — handled by C1 weekly-refresh + C2 EFFR kill-switch (replaces P2's "hard-coded list refreshed annually").
- Sustained VIX-crush regime — A3's calibration logging surfaces the dormancy; feature self-suppresses for months at a time which is acknowledged behavior.
- Hawkish-pivot rates regime — handled by A1 + A2.
- Front-running by adversary listening to the public Discord — handled by C3 + C4 (soft mitigations, increase attacker slippage but cannot eliminate).
- Bond-market-dominated drift — handled by A1 (2yr move filter).

**Kill criterion (final):** If mean 24h pre-FOMC excess return on the filtered subset (VIX>18 + VIX-up + flat-prior + 2yr-stable + EFFR-stable) drops below +25bps over 8 consecutive meetings, OR if positive-day frequency falls below 60%, kill. Use 5-year rolling window per A's S3 (regime-stratify the kill, not the most recent 24 months).

**Instant-trigger eligibility (post-hardening):** YES — quant/factor signal class explicitly named in CLAUDE.md; index-level alert. Acknowledged low fire rate (<10×/year, often near 0 in VIX-crush regimes).

**Minimum implementation touch:** New module `consensus_engine/signals/pre_fomc.py`. Wire into existing `main.py:455` `macro_digest_loop` with new `pre_fomc_check_loop`. Calendar YAML at `config/fomc_calendar.yaml` (refreshed weekly via job in `main.py:455` neighborhood). Alert via `alerts/discord.py:316`. New SourceType `MACRO_DRIFT`. EFFR kill-switch needs FRED `EFFR` series subscription via FRED API (depends on FRED_API_KEY provisioning per CC-S5).

**Cross-cutting dependencies:**
- FRED API key provisioning (CC-S5) — required for EFFR kill-switch and 2yr Treasury filter.
- Calendar resolver (CC-S6) — Pre-FOMC + EFFR calendar entries.
- Data freshness gate (CC-S7) — fail-closed if Finnhub `/quote` for SPY/VIX is older than 1 trading session.
- `_get_macro_context` consumption pattern in `cross_reference.py:333` (CC-S8) — explicit consumer logic to avoid the dead `regime_detector.py` failure mode.

---

### Feature 4 — FRED Credit-Equity Divergence (HYG vs SPY + HY OAS)

**Domain:** Technical/Quant · **P2 composite:** 4.00 · **Verdict map:** A=STRENGTHEN, B=STRENGTHEN, C=KEEP

**Final hardened description:** EOD daily computation: `gap_20d = SPY_20d_return − HYG_20d_return`. Bearish trigger when `gap_20d > 2σ` (over 252-day baseline) AND `HYG < SMA(HYG, 50)` AND `SPY ≥ SMA(SPY, 50)` AND signal persists ≥2 sessions. Confirmation via FRED `BAMLH0A0HYM2` (HY OAS direct) and LQD weakness check. Suppress when `correlation(HYG, SPY, 60d) > +0.85`. 252d rolling baseline excludes the most-recent 20 days. **NEW union of STRENGTHENS:**
- (A1) Breadth filter: only fire when SPY 50d-SMA-above is 60%+ of S&P 500 constituents (broad-participation regime) — removes 2023–2024 mega-cap-carried false positives.
- (A2) Stratified backtest: kill criterion separates "broad-participation" (top-quartile breadth) vs "concentrated" (bottom-quartile breadth) periods. Signal works in former, not latter; require failure on BOTH before retirement (cf. S3).
- (A3) Define explicit consumption: `cross_reference._get_macro_context` raises required confidence threshold by +10pts on cyclicals/small-caps during macro-caution regime. Without explicit consumption, this becomes dead code (cf. dead `regime_detector.py` per audit).
- (B1) `FRED_API_KEY` provisioned in `/root/.openclaw/.env` (CC-S5). Add to project memory's "External API Keys" reference.
- (B2) New `macro_signals` table (CLEAN schema) rather than overloading `youtube_macro` (semantic mismatch). 0.5 day for migration design.
- (C — confirmed unattackable) FRED is US-government infrastructure; HYG/LQD coordinated tape-paint is economically irrational ($70M cost for $10k retail-flow alpha = 5,000:1 unfavorable).

**Conflict resolution:** None. A and B are additive; C confirms the underlying inputs cannot be moved.

**Failure modes (combined):**
- Concentrated mega-cap leadership regime — handled by A1 breadth filter.
- 2020-Q2 correlation flip — handled by P2's `cor>0.85` suppress AND A1's breadth filter as second line.
- Idiosyncratic HY shocks — partially handled by P2's LQD-stress co-requirement.
- 24-month rolling backtest dominated by 2024 false positives — handled by A2 stratified backtest.
- "Macro caution" without consumer — handled by A3 explicit consumption.
- FRED dark/key issue — fail back to ETF-only signal per P2 (graceful degradation).

**Kill criterion (final):** If false-positive rate (signal fires but >3% SPY drawdown does NOT occur within next 20 trading days) > 60% on a 24-month backtest **stratified by broad-participation regime only**, kill. Alternative: if mean forward 20d SPY return conditional on signal is ≥ unconditional baseline within the broad-participation sub-period, kill.

**Instant-trigger eligibility (post-hardening):** NO — regime/macro signal; fires as confidence multiplier on existing alerts and as standalone "macro caution" thesis-only embed (NOT a per-name instant trigger).

**Minimum implementation touch:** New module `consensus_engine/scanners/macro_credit.py`. Wire into existing `main.py:455` `macro_digest_loop` (already runs hourly). Output written to **new `macro_signals` table** (NOT `youtube_macro` — semantically wrong per B). Consumed by xref via new `cross_reference._get_macro_context` method at `cross_reference.py:333` (immediately after existing xref read).

**Cross-cutting dependencies:**
- FRED API key (CC-S5).
- Shared `yfinance` rate-limit string (CC-S4) — Feature 4, 5, and any future yfinance consumer must share.
- `_get_macro_context` consumption pattern (CC-S8).
- Schema migration consolidation (CC-S5 — `macro_signals` table is one of nine new schema items).

---

### Feature 5 — Volume-Confirmed N-Day Breakout with ATR Levels

**Domain:** Technical/Quant · **P2 composite:** 4.00 · **Verdict map:** A=STRENGTHEN, B=KEEP, C=STRENGTHEN

**Final hardened description:** Fire when `close_today > rolling_max(close, N)` for N ∈ {20, 60, 252} AND `volume_today ≥ 2.0 × rolling_mean(volume, 20)` (raise to 2.5 for low-float <50M shares) AND `close > VWAP_anchored from prior pivot-low` AND `BBwidth(20, 2σ) > 30th percentile of trailing 252d`. Emit alert with `entry = close`, `target_1 = close + 1.5×ATR(14)`, `target_2 = close + 3.0×ATR(14)`. **NEW union of STRENGTHENS:**
- (A1) Consecutive-bar persistence for N=20: require `close > rolling_max(close, 20)` for 2 consecutive sessions before firing — cuts 2017-style whipsaw count by ~35%.
- (A2) Earnings-window suppression explicit in this module (do not rely on Feature 6 gate which is a downstream contextualizer): if `next_earnings_in_days <= 1 OR last_earnings_in_days <= 2`, suppress standalone fire.
- (A3) Lift the VIX cap from 28 to 35 — breakout edge extends through 28–35 band per Quantpedia volatility regime decomposition; absolute kill is VIXmageddon (VIX>40).
- (C1) **Replace volume-z-score with dollar-volume z-score** AND require dollar volume ≥ $10M (filters $50M floats from gaming the rule).
- (C2) **Hard market-cap floor at $500M** (raised from $300M); manipulation economics for $300–500M names is too attractive — pump cost ~$200k–$500k vs $50k–$200k profit, 4:1 cost-to-alpha is viable for a coordinated group.
- (C3) Require the rolling-max breakout's prior 5 days to NOT show abnormal late-session volume concentration (last hour vs first 5h ratio < 0.45).
- (C4) **Stop publishing stop-loss in the alert** — publish entry + targets only; let user compute their own stop. The published stop is itself an attack surface (X3 stop-hunting cooperation).
- (C5) Delay alert send by 30 min post-close to require AH price corroboration; many manipulated breakouts fade post-close.
- ADX(14) > 22 gate for N=20 retained; per-feature daily quota retained (max 20 alerts/day for N=20; 5 for N=60; 3 for N=252).
- Liquidity floor adjusted upward: market cap ≥ $500M (was $300M), ADV(20d) ≥ 500k shares.
- Per-ticker dedup retained: 24h cooldown on same ticker for same-N tier.

**Conflict resolution:** A wanted VIX cap raised to 35; C said nothing about VIX cap (manipulation lens). A's lift is preserved. C wanted cap floor raised to $500M; A originally accepted $300M but did not object to a higher floor — C's tighter floor is preserved (strictly safer). The "publish stop-loss" change in C is counter-intuitive (less detail for the user) but is not regime-fragile, so A is not undermined.

**Failure modes (combined):**
- Low-vol VIX-crush whipsaw — handled by A1 persistence filter.
- Earnings-driven gap-up false signal — handled by A2 in-module suppression.
- VIX>35 broad-volume-shock day — retained suppression.
- Coordinated wash-trading at the close (X3-style) — handled by C1 + C2 + C3.
- Single-actor dual-print at low-float close — handled by C1 + C2 hard floors.
- Stop-hunting cooperation — handled by C4 (don't publish stops).
- Mega-cap concentrated leadership regime — partially mitigated by daily quota; remaining risk acknowledged but accepted.

**Kill criterion (final):** If 1-day forward precision (next-day close above today's close) < 52% on filtered cohort over 90-day rolling window in broad-participation regime, kill the N=20 tier; if < 50% on N=252, kill that tier.

**Instant-trigger eligibility (post-hardening):** YES — "technical breakout with levels" explicitly named in CLAUDE.md exception list. Fires standalone with mandatory entry/target_1/target_2 (NO stop in payload per C4) and time-stop in alert payload. C5's 30-min post-close delay narrows the lead-time advantage but increases precision.

**Minimum implementation touch:** New module `consensus_engine/signals/breakout.py`. Reuses existing `consensus_engine/analysis/indicators.py` for ATR/BBwidth (already at `analysis/technical.py:243`). Wire into existing `fetch_loop` at `main.py:369–380`. Alert via `alerts/discord.py:316`. New SourceType `TECHNICAL_BREAKOUT`. Universe scope MUST be bounded (top-N from ApeWisdom + tickers with active TweetShift hits in last 24h, NOT a 2000-name Russell scan) per B.

**Cross-cutting dependencies:**
- Shared `yfinance` rate-limit string (CC-S4).
- Audit M3 cooldown fix (CC-S3) — required precondition for any new instant-trigger.
- Correlation-decay penalty (CC-S2) — defends against Attack X3.
- Earnings calendar from Feature 6's calendar resolver (CC-S6) — for the in-module A2 suppression.

---

### Feature 6 — Earnings-Window Risk Gate

**Domain:** Catalysts/Macro · **P2 composite:** 4.00 · **Verdict map:** A=KEEP, B=STRENGTHEN, C=STRENGTHEN

**Final hardened description:** For every ticker that surfaces from any engine (tweet, technical, social), look up next earnings date and tag the signal with one of `pre_earnings_T-N`, `into_earnings`, `post_earnings_T+N`, or `clear`. **NEW union of STRENGTHENS:**
- (B1) **Drop Nasdaq `api.nasdaq.com` as a primary source** — keep only as tertiary fallback after Finnhub + yfinance disagree. ToS-grey exposure not worth marginal small-cap coverage.
- (B2) 7-day TTL on cached earnings dates; explicitly invalidate on any `8-K Item 2.02` hit for the ticker (earnings press-release form code triggers re-pull of next-quarter date).
- (C1) **Trust Finnhub-curated date over self-disclosed pre-announce dates.** Self-disclosed date moves are too easy to game.
- (C2) **Make the gate a soft *score modifier* (0.6× confidence multiplier in T-3 to T+1), not a hard-suppress.** Hard suppression is binary and gameable (attacker manufactures phantom pre-announce to suppress). A soft modifier still lets high-conviction signals fire.
- (C3) Add an "earnings-week tweet density" sanity check — if tweet volume on a ticker spikes 10x normal in the gate window, treat as evidence the event is not just earnings (e.g., simultaneous M&A) and override gate.
- Cross-source mismatch ≥2 days → "uncertain" rather than "clear" — fail-closed retained from P2.

**Conflict resolution:** A said KEEP (gate mechanism is regime-agnostic by design). C wants to soften from hard-suppress to score-modifier. The softening is consistent with A's verdict because A's reasoning ("never *fires* a wrong signal, only modulates") is preserved — modulation just becomes 0.6× rather than 0×. A's regime-survival argument is unchanged.

**Failure modes (combined):**
- Stale unofficial endpoint dates — handled by B1 dropping Nasdaq from primary path.
- Earnings-date confusion exploit (gameable hard-suppress) — handled by C2 soft modifier.
- Pre-announce timing manipulation — handled by C1 trusting Finnhub-curated.
- Multiple-events-same-week — handled by C3 tweet-density override.
- Stale cached dates — handled by B2 7-day TTL + 8-K Item 2.02 invalidation.

**Kill criterion (final):** If precision delta on social-source signals fired in T-3 to T+1 window vs same signals in T-30 window is < 5pp on 6-month backtest, kill the gate.

**Instant-trigger eligibility (post-hardening):** NO — gate/contextualizer. The C2 softening from hard-suppress to soft-modifier does NOT change instant-trigger eligibility — this feature has never been an alert source.

**Minimum implementation touch:** Reuse existing `consensus_engine/scanners/earnings_calendar.py:25–47`. New module `consensus_engine/analysis/earnings_gate.py`. Hook into `cross_reference.py:333` (after existing xref read) — call new gate function which returns a confidence-multiplier appended to `breakdown`. Alert text appended in `alerts/discord.py:471–507` (`send_detail_followup`).

**Cross-cutting dependencies:**
- Calendar resolver (CC-S6) — earnings calendar consolidates with FOMC/PDUFA-equivalent into Cluster D.
- Source-trust hierarchy as part of CC-S6 implementation.

---

### Feature 8 — New 13D Activist-Filer Detection (with 13G→13D conversion)

**Domain:** Insider/Filings · **P2 composite:** 4.00 · **Verdict map:** A=KEEP, B=STRENGTHEN, C=STRENGTHEN

**Final hardened description:** Two-leg feature. (a) When a new Schedule 13D appears, score on filer's activist history (count of distinct prior 13D campaigns over trailing 5 years), percentage stake disclosed, and Item 4 "Purpose of Transaction" intent classification. Standalone alert when filer ≥2 prior campaigns AND C-required-conditions OR Item 4 contains specific actionable nomination/strategic-alternative language. (b) Flag "13G→13D conversion" — a holder previously on 13G filing a fresh 13D; standalone alert ONLY when paired with concurrent action. **NEW union of STRENGTHENS:**
- (B1) **Backfill activist-filer history as a one-time migration job** (`scripts/backfill_activist_history.py`) — 10k filer-CIKs × 1 submissions.json call each × 200ms paced ≈ 30 min total. Cache permanently with weekly delta refresh.
- (B2) Item 4 regex tightly coupled to current SEC drafting conventions; add **LLM-classifier fallback** (existing `analysis/llm_scorer.py` infrastructure) for any 13D where regex returns 0 hits but the filing is from a known-activist filer (≥2 prior campaigns) — uses existing OpenRouter budget.
- (B3) `holder_intent` table: index on `(filer_cik, issuer_cik)`; expected lifetime <1M rows.
- (C1) **Co-filing same-day deduplication** — multiple CIKs filing 13D on same target same day count as one filer.
- (C2) Item 4 must contain at least one of: named director nominee, specific tender/proxy threat, or named transaction-counterparty. Soft "engagement" verbiage downgrades to xref-only (not standalone).
- (C3) **13G→13D conversion alert downgrades to xref-only unless** paired with one of: press release in same 24h, options flow ≥3σ, OR known-activist-account tweet within ±48h.
- (C4) **Activist-history weighting** discounts campaigns that did NOT reach a settlement or vote outcome — raw count of 13Ds is insufficient; outcome-weighted counts. (Requires manual tagging of historical campaigns; ~500 LOC + ongoing curation.)
- (C5) **Maintain whitelist of confirmed activist filer-CIKs** (Elliott, Starboard, Engaged, etc.); only those qualify for standalone-trigger. Newcomers downgrade to xref-only until outcome-weighted history accumulates.

**Conflict resolution:** None. A's KEEP reasoning rests on regime-stability (Brav-Jiang-Kim documents persistence through GFC, post-GFC); C's strengthening narrows the standalone-trigger eligibility but doesn't undermine the underlying signal. Restricted standalone universe (whitelist + outcome-weighted) is a stricter version of A's "known activist (≥2 prior campaigns)" gate, which A explicitly endorsed.

**Failure modes (combined):**
- Sub-shell sham-13D — handled by C2 specific verbiage requirement + C5 whitelist.
- Joint-filer cluster spam — handled by C1 co-filing dedup.
- 13G→13D conversion gaming — handled by C3 concurrent-action requirement.
- Activist-history fabrication (12-month sock-puppet activist) — handled by C4 outcome-weighting + C5 whitelist.
- Cash-settled-swap evasion — partial mitigation acknowledged (P2); fails gracefully (no false signal).
- Item 4 regex drift — handled by B2 LLM-classifier fallback.

**Kill criterion (final):** If 21-day forward precision (positive sector-adjusted return on entry) < 50% on **whitelisted-activist subset** over 12-month backtest, kill the standalone path. (Per C5, only the whitelisted subset is eligible for standalone alerts; non-whitelist remains xref-only with no kill criterion.)

**Instant-trigger eligibility (post-hardening):** YES, narrowed: only when (a) filer is on the C5 whitelist AND C2 specific verbiage is satisfied, OR (b) 13G→13D conversion paired with concurrent action per C3. Both meet CLAUDE.md "insider trading" exception.

**Minimum implementation touch:** New module `consensus_engine/scanners/activist_watcher.py`. Reuses existing `sec_edgar.py` HTTP plumbing. Wire into `main.py:343` behind sub-flag `activist_watcher_enabled`. Standalone alert via `alerts/discord.py:316`. Cross-ref boost via `signal_events` SourceType `ACTIVIST_FILING`. Whitelist YAML at `config/activist_whitelist.yaml` (manual curation). `holder_intent` table schema migration.

**Cross-cutting dependencies:**
- Shared SEC EDGAR semaphore (CC-S1).
- Audit M3 cooldown fix (CC-S3).
- Correlation-decay penalty (CC-S2) — defends against Attack X4 (aged sock-puppet activist constellation) and Attack X2 (13D + Reg SHO stack).
- Backfill job shares infrastructure with Feature 2's CIK-age check (CC-S5 schema migration consolidation).

---

### Feature 10 — Wikipedia Pageview Spike

**Domain:** Sentiment · **P2 composite:** 3.70 · **Verdict map:** A=STRENGTHEN, B=STRENGTHEN, C=STRENGTHEN

**Final hardened description:** Pull hourly pageviews for ticker's company Wikipedia article and flag z ≥ 2.5 vs trailing-28-day weekday-matched baseline. Use as +0.05 max confidence-multiplier (cap, per C3) on tweet-driven or breakout-driven primary signals. **NEW union of STRENGTHENS:**
- (A1) **Hard-gate to mid/small-caps only** (market cap $200M–$5B) — baseline is detectable in this range; chronic NVDA-mania-style elevation is excluded.
- (A2) Continuous penalty when prior-week elevation z>2 (already-saturated) — converts P2's binary "suppress when >3" to a continuous weight reduction.
- (A3) **Demote from confirmer to thesis-text-only annotation** — latency disqualifies from the 2-source rule; use only as "context: Wikipedia attention z=2.7" annotation in Phase-2 followup. (C also caps at +0.05 score so this aligns.)
- (B1) **Ship the ticker→Wikipedia-article map as a one-time backfill** + ongoing daily-incremental for new tickers. 5–10 min of OpenFIGI calls.
- (B2) Reject articles where the infobox doesn't contain the ticker symbol.
- (B3) 1-hour TTL cache per article-slug; 28-day baseline cached, NOT recomputed every alert.
- (B4) User-Agent: `consensus_engine/1.0 (+https://github.com/chopra2007/openclaw; ak@openclaw.dev)`.
- (C1) **MANDATORY co-confirmation with a second uncorrelated attention source** (Google Trends — already wired in P0 row 7 — in same hour AND same direction). If Google Trends shows no spike, Wikipedia spike is null-and-void.
- (C2) **Sustained-spike requirement:** z ≥ 2.5 must hold for ≥3 consecutive hours, not single-hour. Attacker click-brigade rarely sustains 3h.
- (C3) **Cap on contribution to alert score** — Wikipedia is at most +0.05 (5% of score) regardless of magnitude.

**Conflict resolution:** A's "demote to thesis-text-only" and C's "+0.05 max contribution" are functionally equivalent — both reduce Wikipedia from a 2-source confirmer to a near-decorative annotation. Both shipped (cap at +0.05 AND text annotation, no 2-source eligibility).

**Failure modes (combined):**
- Article ambiguity (common-noun tickers) — handled by B2 infobox check.
- Pageview brigade attacks (X5 leg) — handled by C2 sustained-spike + C1 mandatory co-confirmation.
- Wiki edit-and-revert spam — partial mitigation via C2 (single-hour spikes excluded).
- Sock-puppet click farm — handled by C3 cap (limits manipulation upside) + C1 + C2.
- Crisis-news regime generic spikes — handled by C1 (Google Trends would also spike; the *direction* match adds information).
- Latency vs use-case mismatch — handled by A3 / C3 demotion.
- Concentrated-attention chronic NVDA-style elevation — handled by A1 cap floor.

**Kill criterion (final):** If precision delta when used as +0.05 multiplier on tweet-driven primary signals (gated by C1 + C2) is < 1pp on 90-day backtest, kill (effectively unused at +0.05 cap).

**Instant-trigger eligibility (post-hardening):** NO — annotation only. Cannot serve as 2-source second leg.

**Minimum implementation touch:** New module `consensus_engine/scanners/wikipedia_attention.py`. Pre-built ticker-to-article map seeded from OpenFIGI + Wikidata (one-time backfill per B1). Wire into existing `fetch_loop` at `main.py:369–380` (5-min interval hourly resampled). Output via `signal_events` with new SourceType `WIKIPEDIA_ATTENTION`. Consumed by xref via existing `_run_social_check` aggregation but with the +0.05 hard cap enforced at consumption.

**Cross-cutting dependencies:**
- New `ticker_external_ids` table extension or `ticker_metadata` extension (CC-S5 schema migration consolidation).
- Correlation-decay penalty (CC-S2) — defends against Attack X5 (Wikipedia + TweetShift + News brigade).
- Google Trends already wired (P0 rows 6/7/8) — required for C1 mandatory co-confirmation; no new dependency, just enforcement.

---

### Feature 11 — Reg SHO Threshold List Entry/Exit Event

**Domain:** Flow/Microstructure · **P2 composite:** 3.50 · **Verdict map:** A=STRENGTHEN, B=STRENGTHEN, C=KEEP

**Final hardened description:** Daily-poll Reg SHO threshold security lists from NASDAQ (`nasdaqthYYYYMMDD.txt`), NYSE (follow redirect to `/regulation/regulation-sho`), Cboe. Diff today's list against yesterday's. **NEW union of STRENGTHENS:**
- (A1) **Tighten cap floor to $2B** for instant-trigger eligibility (P2 specified $1B; precision lift is meaningfully better above $2B). C originally said KEEP at $1B; A's tightening is strictly safer and does not contradict C — both raise the manipulation barrier. Combined with X2 attack analysis showing $1.2B is exploitable for $1.2–2.4M profit on $60M tied capital, the higher floor is the right choice.
- (A2) **Regime gate: only fire standalone when `VIX > 22` AND HY OAS > 350bps** — Reg SHO mechanic only bites in actual borrowing-stress regimes. In low-vol/ample-borrow regimes (Feb 2017, late 2024), demote to xref-only.
- (A3) **Drop the FINRA short-volume cross-validation** since FINRA short-volume isn't being built (Flow F6 was cut at P2 dedup) — replace with (Reg SHO + Form 4 cluster within 14d) OR (Reg SHO + macro stress regime per A2). Internal consistency fix.
- (B1) **Track cumulative-entry-day-count per (ticker, list)** rather than naive yesterday-vs-today diff — handles publication-delay false-positives.
- (B2) **Follow the NYSE redirect** explicitly; hard-code the redirected `/regulation/regulation-sho` URL.
- (B3) Daily file fetcher must handle "file not yet posted" = HTTP 404 → retry 30 min later, no error log spam.
- (C-confirm) Robust ticker normalization across NASDAQ/NYSE/Cboe (handles "BRK.B" vs "BRK B" vs "BRK-B"). ~50 LOC, cheap.
- (X2 raised cap to $3B) C raised this in the cross-feature attack section. Resolution: A's $2B is the per-feature standalone floor, but per Attack X2 ("squeeze-pressure stack" with 13D activist), when Reg SHO + Feature 8 13D fire on same ticker within 14 days, require $3B floor for the *stack-amplified score boost*. Single-feature $2B; stacked $3B.

**Conflict resolution:** P2 said $1B; A said $2B; C's X2 attack section said $3B for the stacked case. Resolution above (single $2B / stacked $3B) honors all three.

**Failure modes (combined):**
- Low-vol ample-borrow regime — handled by A2 regime gate.
- Meme-era inversion — handled by $2B floor + A2 stress regime requirement.
- Liquidity-stress regime artifacts — partial mitigation via A2; the regime gate fires *because* of stress so artifact risk is acceptable.
- FINRA short-volume cross-validation gap — handled by A3 replacement rules.
- Symbol normalization across lists — handled by C ticker normalization.
- Publication delay false-positives — handled by B1 cumulative-entry-day-count.
- NYSE URL redirect — handled by B2 hard-code redirected URL.
- Coordinated borrow-fail (X2 leg) — handled by $3B stacked floor + correlation-decay penalty (CC-S2).

**Kill criterion (final):** If 5-day forward T+5 to T+13 excess return on liquid (>$2B mkt cap) cohort during stress-regime sub-period (VIX>22 AND HY OAS>350) is < +0.5σ vs sector base over 12-month backtest, kill standalone path.

**Instant-trigger eligibility (post-hardening):** Conditional YES — large-cap (>$2B) entries during stress regime (A2) fire standalone given regulatory weight. Stacked with Feature 8 13D requires >$3B floor. Mid/micro-caps confirmatory only.

**Minimum implementation touch:** New module `consensus_engine/scanners/reg_sho.py`. Daily-cadence poll wired into `main.py:455` `macro_digest_loop` neighborhood. Output via `signal_events` with new SourceType `REG_SHO`. Standalone-trigger alert via `alerts/discord.py:316` for >$2B cap during stress regime.

**Cross-cutting dependencies:**
- Audit M3 cooldown fix (CC-S3).
- Correlation-decay penalty (CC-S2) — required for X2 stack defense.
- VIX + HY OAS reading shared with Feature 4 (`macro_signals` table from Feature 4's CC-S5 migration) — A2 regime gate consumes this data.

---

## 4. Dropped Features

### Feature 7 — FinBERT Headline Sentiment + Catalyst Lexicon — DROPPED

**P2 composite:** 4.00 · **Verdict map:** A=STRENGTHEN, B=STRENGTHEN, **C=KILL** (1 KILL → Rule 2)

**Drop rule invoked:** Rule 2 — exactly 1 KILL; no STRENGTHEN that satisfies all three lenses can be constructed.

**Why no constructible STRENGTHEN:** C's KILL rationale is that PR-wire placement at $300–$2,500 is a publicly-priced direct attack on the feature's primary input (`A1`), AND BERT adversarial-tokenizer attacks cost $0 (`A2`), AND velocity-hijacking via 8-headline burst at $2,400 (`A3`), AND long-game adversarial drip at ~$5–10k for monthly ROI (`A4`). C's salvage path requires options-flow corroboration AND ≥2 first-class news domains (Bloomberg/Reuters/WSJ, NOT wire-services) — at which point the FinBERT contribution is essentially eliminated and the feature is "first-class news + options flow," which doesn't justify the engineering cost (FinBERT model, 400 MB venv, CPU throughput risk per B). A's STRENGTHEN proposed sector-tuned model + meme-detection flag — but these don't address C's adversarial-text input vector. B's STRENGTHEN proposed loading FinBERT once at engine init and ThreadPoolExecutor inference — but these are operational, not adversarial defenses.

**Constructibility test:** For an all-three-lens-acceptable STRENGTHEN to exist, it would need to defend against $300 PR-wire placement AND $0 adversarial tokenization. The only known defense is "require first-class news source as second leg," which collapses the feature to no-FinBERT lexicon-only. At that point the feature delivers no marginal value (catalyst lexicon alone — which P2's own kill criterion explicitly invites — is sufficient). The compute-and-RAM cost is not justified.

**Post-mortem:** The fatal gap is that adversarial-text inputs are economically asymmetric. Defender's cost (per-token sanitization, syndication detection, model-shipping pipeline, ongoing fine-tune) grows unbounded; attacker's cost is bounded ($300 minimum, $0 for some classes). The feature is FinBERT's brand value attached to a sentiment proxy that the lexicon already provides cheaper. **Recommendation if revived:** ship lexicon-only as a confirmer with mandatory first-class news second source — but rename so it isn't called "FinBERT." Defer entirely if the audit's M3 + correlation-decay safeguards already deliver the precision lift via more-reliable means.

---

### Feature 9 — SEC EDGAR Full-Text Mention Velocity (cross-form) — DROPPED

**P2 composite:** 3.80 · **Verdict map:** **A=KILL**, **B=KILL**, C=STRENGTHEN (2 KILLs → Rule 1)

**Drop rule invoked:** Rule 1 — auto-drop, no appeal.

**Post-mortem:** This is the feature that already poisoned the production SEC pipeline 2026-03-31 → 2026-04-07 in the form documented in the audit (395 SEC-8K alerts with 97% `final_score=0`, watcher disabled by operator on 2026-04-07). A killed it on signal-quality grounds: regulated filings have radically different per-issuer cadences and the noise/signal ratio collapses during any earnings season (~30% of small-caps simultaneously file form-type-diverse paperwork that is administrative, not material). B killed it on feasibility grounds: EFTS endpoint rejects HEAD with `MissingAuthenticationTokenException` while accepting GET (verified live), and combined Cluster-A SEC budget at ~5/min steady-state with bursts on minute-boundaries pushes against the shared 10 req/s ceiling — a single 10-min IP block silences `_run_sec_check` for every other feature. The fatal gap is that the feature aggregates the *noise* portion of EDGAR while Features 1 (Form 4 cluster), 2 (S-4/425), and 8 (13D) already cover the *signal* portion. **B's reconsideration path** (piggyback on `submissions.json` recent-items already pulled by `check_recent_filings`, no new endpoint) could be revisited after Cluster A is in production for 30+ days with measured SEC-budget headroom — but as a *new* feature, dropped.

---

### Feature 12 — VIX Term-Structure Flip — DROPPED

**P2 composite:** 3.50 · **Verdict map:** A=STRENGTHEN, B=STRENGTHEN, **C=KILL** (1 KILL → Rule 2)

**Drop rule invoked:** Rule 2 — exactly 1 KILL; no STRENGTHEN that satisfies all three lenses can be constructed.

**Why no constructible STRENGTHEN:** C's KILL rationale is two-pronged: (i) signal-redundancy — Features 3 (FOMC drift) and 4 (HYG/LQD divergence) already cover the macro/regime axis with similar information, and (ii) low frequency — `<10×/year` per the spec, with `~30bps mean 5d excess return` which is too thin for an instant-trigger feature slot at the bot's alert budget. Manipulation surface is secondary (theoretical $50–100M scale to move VX-futures settlement, but the attacker's downstream alpha is small because the alert is index-level). A's STRENGTHEN proposed direction-disambiguation in alert payload + rates filter; B's proposed CBOE freshness check + yfinance fallback. These address regime and feasibility concerns but do not change the underlying signal redundancy that drove C's KILL — the feature's slot is contested by Features 3 and 4 which provide overlapping macro coverage.

**Constructibility test:** An all-three-lens STRENGTHEN would need to address C's signal-redundancy concern AND C's low-frequency concern. The redundancy with Features 3 and 4 is structural (all three are macro/index signals on SPY-equivalent paths). A and B's proposals don't reduce redundancy. The only honest path is to fold VIX-term-structure into Feature 4's `_get_macro_context` consumption as one input among several (effectively merging 12 into 4) — which is no longer Feature 12 as a standalone. Drop is the correct call.

**Post-mortem:** The fatal gap is that the bot's product thesis is single-name actionable intelligence (CLAUDE.md alert philosophy), and the surviving macro slots (3, 4) are already at the practical limit for index-level coverage. F12 fails the high-impact bar (it claims Bullet 4 — "closes P0 gap on CBOE put/call ratio + macro-rails" — but Feature 4's HY OAS plus Feature 3's FOMC calendar already partially close that gap). **Recommendation if revived:** fold the VIX term-structure reading into Feature 4's `macro_signals` table as an additional column (`vol_regime_label`) that cross_reference consumes via the same `_get_macro_context` method. No standalone feature slot.

---

### Feature 13 — Influencer Cluster-Convergence — DROPPED

**P2 composite:** 3.40 · **Verdict map:** **A=KILL**, B=KEEP, **C=KILL** (2 KILLs → Rule 1)

**Drop rule invoked:** Rule 1 — auto-drop, no appeal.

**Post-mortem:** A killed it because the TweetShift cohort is already curated (per P2's own description), so the "independence" measurement (cosine similarity of last-100-mention ticker history < 0.6) inverts during high-conviction macro events when every analyst converges on the same broadcast catalyst — convergence becomes lagging, not leading; the audit's M3 fix (per-analyst hit-rate cooldown) achieves the feature's stated +6pp precision goal with ~80 LOC vs estimated multi-hundred-LOC engineering cost. C killed it because a 90-day pre-aged sock-puppet cohort costs ~$15/spoofed alert with arbitrary scaling, while defense requires industrial-grade social-fraud detection outside this project's scope. B's KEEP was a *feasibility* verdict (zero new external dependencies), which doesn't override A and C's signal/manipulation kills. **The fatal gap is duplicate engineering: the audit's M3 (per-analyst cooldown weighted by historical precision) achieves the stated goal more cheaply, with better adversarial properties (it operates on observed precision, not metadata that can be aged).** Ship M3 as part of CC-S3; do not ship Feature 13.

---

### Feature 14 — PDUFA / AdCom Proximity Tag — DROPPED

**P2 composite:** 3.30 · **Verdict map:** A=KEEP, **B=KILL**, C=STRENGTHEN (1 KILL → Rule 2)

**Drop rule invoked:** Rule 2 — exactly 1 KILL; no STRENGTHEN that satisfies all three lenses can be constructed.

**Why no constructible STRENGTHEN:** B's KILL is grounded in three serial upstream failure modes: (i) FDA Advisory Committee Calendar HTML page returned 403 Akamai-bot-block to plain `aiohttp` GET (verified live); (ii) PDUFA dates routinely slip; (iii) sponsor → ticker mapping is messy. The required Playwright stealth fallback (already wired but expensive at ~300 MB RAM per browser) compounds with Akamai's revocation of fingerprint sessions, requiring ongoing maintenance. A's KEEP rests on the gate's mechanism being fail-safe by design — but this is conditional on the calendar harvester *working*. C's STRENGTHEN proposed hierarchical source-trust (FDA > openFDA > 10-Q) and soft-modifier behavior — but these don't fix B's underlying problem that the canonical FDA calendar page is Akamai-walled.

**Constructibility test:** For an all-three-lens STRENGTHEN to exist, B would need a reliable free-tier path to the FDA calendar that doesn't depend on Playwright stealth's ongoing maintenance burden. B's reconsideration path ("manual YAML refresh of known upcoming PDUFA dates for the small biotech subset the bot already covers, ~20-30 names") is a plausible drop-in but loses the automation value — at that point the feature is a manually-curated YAML, not a Phase-2 feature.

**Post-mortem:** The fatal gap is that three out of four upstream sources (FDA calendar Akamai-walled, openFDA works, ClinicalTrials.gov works, 10-Q full-text competes for SEC budget) have material failure modes; the fourth competes with already-stretched Cluster-A SEC budget. A 5–7 day engineering project for a feature whose composite (3.30) is the second-lowest in the surviving cohort is a poor allocation. **Recommendation if revived:** ship the manual-YAML version for the ~20–30 biotech names already covered. Reclassify as a Phase-3 manual-curation feature, not a Phase-2 automated harvester.

---

## 5. Cross-Cutting Safeguards

These are proposals that multiple red-teams raised AND that must be implemented as shared infrastructure BEFORE any surviving feature ships. Each is a dependency the surviving features assume — surviving features list them in their Cross-cutting dependencies field.

### CC-S1 — Shared SEC EDGAR semaphore (Cluster A)

**What it protects:** Aggregate SEC fair-use 10 req/s ceiling across `data.sec.gov` / `www.sec.gov/cgi-bin` / `efts.sec.gov`. Without this, Features 1, 2, 8 + existing `_run_sec_check` can burst together at minute-zero alignments and trigger a shared 10-min IP block, silently taking down xref `_run_sec_check` for every alert in flight.

**file:line:** Already exists at `consensus_engine/utils/rate_limiter.py:29` (`sec_edgar: 0.2` = 5 req/s per source string). Tighten to `0.15` (6.67 req/s) to leave headroom. All SEC-touching code MUST `await rate_limiter.acquire("sec_edgar")` regardless of which sub-endpoint is hit. Document in `consensus_engine/scanners/CLAUDE.md`.

**Approximate LOC:** ~30 LOC config + audit existing call sites in `scanners/sec_edgar.py:64–141`, `:173–302` for compliance. Plus jittered start offsets in each new feature's poll loop (Feature 1 at :00, Feature 2 at :20, Feature 8 at :40 of every minute) — ~20 LOC.

**Dependent features:** F1 (Form 4 cluster), F2 (S-4/425), F8 (13D activist).

---

### CC-S2 — Correlation-decay penalty at xref aggregation

**What it protects:** Cross-feature cheap-noise-injection attacks (X1 — Form 4 + S-4/425 stack, X2 — 13D + Reg SHO stack, X3 — FinBERT-pumped breakout, X4 — aged sock-puppet activist constellation, X5 — Wikipedia + TweetShift + News brigade). The composite scoring assumes approximate independence between SourceTypes; correlated noise across 2–3 features simultaneously is an attacker's path of least resistance.

**file:line:** New code at `cross_reference.py:333` (immediately after existing xref read on line 328–332 `db.get_signal_events_for_ticker`). Apply penalty to base_score before LLM scoring.

**Mechanism (per C's recommendation):** For each ticker-window (24h per ticker), compute:
- `n_active_sources` = count of distinct SourceTypes contributing to score in window.
- `suspicious_correlation_factor` accumulates: same-direction-in-<12h: +0.30; low-trust-tier source after first (TweetShift cluster, Wikipedia, news velocity): +0.20 per source; CIK age <90 days OR sock-puppet account <90d: +0.40 per such source.
- `penalty = max(0, n_active_sources − 2) × suspicious_correlation_factor`.
- Final score = `base_score × (1 − penalty)`, capped at `[0.20, 1.00]`.

**Approximate LOC:** ~150 LOC (per C's estimate).

**Dependent features:** F1, F2, F5, F8, F10, F11 (every surviving instant-trigger or boost-eligible feature). F3 and F4 are macro/index so the penalty applies only to single-name xref aggregation and is moot for them.

---

### CC-S3 — Generalized per-analyst cooldown from audit M3

**What it protects:** The audit-confirmed `kpak82` 26-min cooldown race at `db.py:672` (`check_alert_cooldown` parallel-read race) — this generalizes to every standalone-trigger feature in the Phase-2 batch. An adversary who can spoof a single feature gets two chances to fire because of the parallel-read bug. Without this fix, every new instant-trigger feature inherits the bug.

**file:line:** Already specified by audit M3 — `db.check_alert_cooldown` `:714–781`. Replace ticker-level cooldown with per-analyst/per-source precision-weighted cooldown using `source_performance` table.

**Approximate LOC:** ~80 LOC per the audit.

**Dependent features:** ALL surviving instant-trigger features — F1, F2, F3, F5, F8, F11. Generalization explicitly required by Phase 3 task spec.

**Status:** Audit-prerequisite. This MUST land BEFORE the first surviving feature goes live.

---

### CC-S4 — Shared `yfinance` rate-limit string

**What it protects:** Yahoo Finance has tightened scraper rate limits twice since 2023. Three surviving features (F4 macro credit, F5 breakout, F3 SPY/VIX `/quote` for confirmation) hit yfinance plus existing `price_outcome_loop` (`main.py:807–832`). If yfinance starts rate-limiting, all three degrade simultaneously without coordination.

**file:line:** New entry in `consensus_engine/utils/rate_limiter.py:29` (e.g., `yfinance: 1.0` = 1 req/s). All yfinance calls route through `await rate_limiter.acquire("yfinance")` regardless of caller.

**Approximate LOC:** ~30 LOC config + audit existing call sites in `main.py:807–832`, `analysis/technical.py:54`, `scanners/volume_scanner.py` for compliance.

**Dependent features:** F3, F4, F5 (and existing `price_outcome_loop`).

---

### CC-S5 — Schema migration consolidation + FRED API key provisioning

**What it protects:** Cluster A and Cluster C between them propose 9 new schema items: `holder_intent` table (F8), `tweet_mentions` table (F13 — DROPPED, scratch), `macro_signals` table (F4), `ticker_external_ids` extension (F10), `beneficial_owner_index` (F1 NEW), and 6 new SourceType enum values (`INSIDER_CLUSTER`, `M_AND_A`, `MACRO_DRIFT`, `TECHNICAL_BREAKOUT`, `ACTIVIST_FILING`, `WIKIPEDIA_ATTENTION`, `REG_SHO`) — plus FRED API key provisioning for Feature 4 (and Feature 3's EFFR kill-switch) which is not yet in `/root/.openclaw/.env`.

**file:line:** New migration script under `scripts/migrations/202604_phase2_features.sql` (or whatever migration framework the repo uses — check `db.py` for existing patterns). FRED key documentation in CLAUDE.md project memory's `reference_apis.md` (per `MEMORY.md` index).

**Approximate LOC:** ~200 LOC migration + ~10 LOC FRED key load + memory file update (~20 lines).

**Dependent features:** F1 (`beneficial_owner_index`), F4 (`macro_signals` + FRED key), F8 (`holder_intent`), F10 (`ticker_external_ids`), all features (new SourceType enum values). Plus F3 indirectly (FRED EFFR kill-switch).

**Note:** Run as a single atomic migration before any feature ships. Verify SourceType enum values are stable — adding 6 values to a heavily-referenced enum is a meaningful change for analytics queries downstream.

---

### CC-S6 — Calendar resolver consolidation (Cluster D from P2)

**What it protects:** Features 3 (pre-FOMC), 6 (earnings gate) all depend on calendar data. P2's Cluster D recommends consolidation into one shared calendar service. Without this, calendar drift (FOMC schedule changes mid-year, an earnings date shifts) causes silent mis-fires in all features simultaneously.

**file:line:** Extends existing `consensus_engine/analysis/catalyst_resolver.py:179–197`. New consolidated `events_calendar` interface; sub-implementations per event type (FOMC YAML at `config/fomc_calendar.yaml`, Finnhub-curated earnings at `scanners/earnings_calendar.py:25–47`).

**Approximate LOC:** ~150 LOC new + extends 50 LOC existing.

**Dependent features:** F3 (FOMC calendar — weekly refresh per C1), F6 (earnings calendar — Finnhub primary, yfinance secondary, Nasdaq dropped per B). Daily-cadence calendar-staleness check (compare next-event date to "now"; if next-event is within 30 days but YAML last-refreshed >7 days ago for FOMC, emit source-health alert).

---

### CC-S7 — Data freshness gate (per A's S4 systemic concern)

**What it protects:** Five macro/quant features (F3, F4, F5, F11, plus removed F12) all depend on free public endpoints (yfinance, FRED, NASDAQ daily file, NYSE redirect, Finnhub `/quote`) that historically degrade or break under exactly the stress conditions where the signals matter (Feb 2018 VIXmageddon, Mar 2020, Aug 2024 yen-carry unwind). Without a shared freshness gate, signals fire on stale data with no false-positive protection.

**file:line:** New module `consensus_engine/utils/data_freshness.py`. Each macro/quant feature consults `is_fresh(source_id, max_age_seconds)` before computing signal. Fail-closed: `is_fresh == False` → no signal fires, NO false positive.

**Approximate LOC:** ~50 LOC per A's estimate.

**Dependent features:** F3 (Finnhub `/quote` for SPY/VIX), F4 (FRED HY OAS, yfinance HYG/SPY/LQD), F5 (yfinance OHLCV), F11 (NASDAQ/NYSE/Cboe daily files).

**Note:** Default `max_age_seconds`: 1 trading session for macro signals, 1 hour for intraday confirmation. Configurable per-feature.

---

### CC-S8 — Macro context consumption pattern at xref

**What it protects:** A's S2 systemic concern — three macro features (F3, F4, removed F12) write to `signal_events` as regime tags, but cross_reference has no defined consumption pattern. Without explicit consumption, these features become dead code (cf. dead `regime_detector.py` per audit, which has zero callers despite being checked in).

**file:line:** New method `cross_reference._get_macro_context` at `cross_reference.py:333` (after the existing xref read on `:328–332`). Applies regime-conditional confidence multipliers:
- F4 (credit-equity bearish regime active) → confidence threshold +10pts on cyclicals/small-caps.
- F3 (pre-FOMC long active) → confidence threshold ×0.85 on tweet-driven cyclicals.
- (If F12 had survived and folded into F4: vol regime label as additional column.)

**Approximate LOC:** ~80 LOC.

**Dependent features:** F3, F4. Without this, F3 and F4 are decorative measurements that nobody reads.

---

### CC-S9 — Health-check pattern change (HEAD vs GET asymmetry — B's finding)

**What it protects:** B's live-spot-check found that EFTS `efts.sec.gov/LATEST/search-index` rejects HEAD with `MissingAuthenticationTokenException` while accepting GET (AWS-API-Gateway-fronted). Any future watchdog using HEAD for liveness will mis-classify the source as down. Note: F9 (which used EFTS) was dropped, so this is preventative for any future EFTS reintroduction or other AWS-gatewayed endpoints.

**file:line:** New convention in `consensus_engine/utils/http.py` — health-check helper that uses GET with HEAD-equivalent semantics (e.g., GET with `Range: bytes=0-0` or short body read). Document the rule.

**Approximate LOC:** ~20 LOC.

**Dependent features:** None directly (F9 dropped); preventative for future SEC-cluster expansion. Listed here so the next maintainer doesn't reintroduce the bug.

---

### Contested cross-cutting safeguard: weekly vs annual calendar refresh (CC-S6)

**Disagreement:** B argued FOMC calendar can be scraped *annually* (calendar known years in advance); C argued *weekly* refresh is required to handle emergency-meeting cache staleness.

**Resolution:** Weekly wins, per Section 3 Feature 3 conflict resolution. Reasoning recap: (i) emergency meetings are real (2020-03 emergency cut), (ii) weekly Cloudflare-cached request is trivially within budget, (iii) failure mode of stale annual cache is silent — operator never knows until after the fact.

**Status:** Documented as resolved; CC-S6 specifies weekly cadence with daily-cadence staleness check.

---

## 6. Realistic Edge Statement

Honest accounting of the surviving 9-feature delta after hardening and drops, with red-team-identified regime dampening accounted for.

**Precision delta vs current 2-source baseline:**
- F1 (Form 4 cluster): +5pp on insider-cluster cohort. Plausible per Lakonishok-Lee and Cohen-Malloy-Pomorski; safeguards keep precision in the 55–60% range on 21d sector-adjusted returns. **Confidence: HIGH.**
- F2 (S-4/425): +3–5pp on M&A target subset, narrowed by C's filer+target dual requirement. **Confidence: MEDIUM** (deal-termination cascade in rate-shock regimes inverts; antitrust regime tag is informational).
- F3 (pre-FOMC): +25–40bps mean lift on filtered subset (gate-conditional). Self-suppresses for months in VIX-crush regimes — coverage delta is regime-conditional. **Confidence: LOW-MEDIUM** (post-2024 the unconditional mean has compressed to ~25–30bps; rates-driven regimes invert).
- F4 (credit-equity): regime-classifier; +0pp standalone, +5–10pp via macro_context multiplier on cyclicals/small-caps in broad-participation regimes. **Confidence: MEDIUM** (depends on CC-S8 wiring).
- F5 (breakout + ATR): +3–5pp precision on 1-day forward direction in qualifying regime; reduced from P2's claimed +5–10pp due to C's hardening (no published stop, $500M cap floor, 30-min post-close delay). **Confidence: MEDIUM-HIGH.**
- F6 (earnings gate): +5–10pp precision delta on social signals fired in T-3 to T+1 window. C's softening to 0.6× modifier (vs hard suppress) preserves directional effect. **Confidence: HIGH** (gate mechanism is regime-agnostic).
- F8 (13D activist): +5–8pp precision on whitelisted-activist subset; standalone universe is narrower than P2 spec (C5 whitelist + C2 specific verbiage). **Confidence: HIGH on narrowed cohort.**
- F10 (Wikipedia): +0–1pp via +0.05 multiplier cap; effectively decorative. **Confidence: LOW.**
- F11 (Reg SHO): regime-gated standalone; +2–4pp in stress regime, 0pp in low-vol regime. **Confidence: MEDIUM** (regime-conditional fire).

**Aggregate precision delta:** **+3 to +5pp** on actionable alerts vs current 2-source baseline, weighted by feature fire-rate. Concentrated in F1, F6, and F8 (the three KEEP features and one HIGH-confidence STRENGTHEN). Macro/index features (F3, F4) contribute via consumption multiplier rather than direct delta.

**Lead-time delta:**
- F1: +30–60 min vs analyst-tweet aggregation on small/mid-cap insider cluster events.
- F2: +5–30 min vs Bloomberg/CNBC tape for after-hours 425 filings.
- F3: scheduled-fire (calendar-known); lead-time concept N/A.
- F5: NEGATIVE 30 min vs current (C5's post-close delay) — by design, trades lead-time for manipulation defense.
- F8: +10–60 min vs first-class news on 13D filings.
- F11: 0–24h depending on file publication delay.

**Aggregate lead-time delta:** **+10 to +20 min median** weighted by fire-rate. Modest improvement — primarily on regulated-event features (F1, F2, F8). F5's deliberate post-close delay nets against the gain.

**Coverage delta:**
- F1: +20% net new coverage on small/mid-cap insider activity not visible in TweetShift.
- F2: +15% net new on small-cap M&A targets.
- F3: ZERO standalone coverage gain (already-existing macro digest); index-level only.
- F4, F11: regime-conditional coverage (silent in low-vol regimes).
- F5: +10–15% net new on technical breakouts on bounded universe.
- F6, F10: gate/annotation; ZERO standalone coverage.
- F8: +10% net new on activist-positioned small/mid-caps.

**Aggregate coverage delta:** **+15 to +20% net new actionable alerts** in normal regimes; **+5 to +10%** in low-vol/concentrated-leadership regimes (where F3, F4, F11 go silent and F5 produces fewer fires).

**High-Impact Bar conditions (which the SURVIVING set collectively hits):**
- **Bullet 1 (+5pp precision):** **MARGINAL HIT.** Aggregate +3 to +5pp is at the low end. If F1, F6, F8 all deliver per literature, hit. If any underdelivers, miss.
- **Bullet 2 (≥30 min lead-time):** **PARTIAL HIT.** F1 hits on insider cluster cohort; F2 hits on M&A subset; F8 hits on 13D subset. Aggregate weighted median +10 to +20 min — does NOT hit the 30-min bar.
- **Bullet 3 (≥20% net new coverage):** **HIT** in normal regimes (+15 to +20%); **MARGINAL/MISS** in low-vol regimes (+5 to +10%).
- **Bullet 4 (closes instant-trigger blind spot):** **HIT.** F1 closes the explicit P0 gap "No insider Form-4 velocity / cluster-buy signal" (P0 row 28). F8 closes the implicit P0 gap "No SEC Schedule 13D/G activist filed alerter." F2 closes a smaller implicit gap on real-time M&A.

**Honest summary:** The surviving set is **MARGINALLY ABOVE the High-Impact Bar** in normal regimes, with strong contributions from F1 + F8 (regulated-filing edge that the literature documents persistently) and F6 (gate mechanism that is regime-agnostic). The macro features (F3, F4) contribute via consumption multiplier rather than direct delta. **In low-vol VIX-crush regimes (Feb–Nov 2017 / Sep 2024–Feb 2025 pattern), the surviving set delivers materially less** — F3, F4, F11 dampen or go silent, F5 reduces fire rate, and the aggregate becomes a +1 to +3pp precision lift with limited coverage gain. This is not a reason to unship — it's a reason to set operator expectations.

---

## 7. Explicit Limitations

1. **Sustained low-vol regime (VIX<15 for 3+ months) dampens 4 surviving features simultaneously.** F3 (gate-off), F4 (correlation regime), F5 (whipsaw + reduced ADX>22 fire rate), F11 (no borrow stress). The bot's 2026-Q1 calendar is forecast soft on rate volatility per multiple Fed-funds-futures readings — this is not hypothetical for the launch window. Operator must accept that ~30% of the Phase-2 feature mix may go dormant for quarters at a time. Surface explicit "feature is dormant" telemetry so silence reads as health, not failure.

2. **Free-tier data sources will go dark exactly when stakes rise.** Mar 2020 / Feb 2018 / Aug 2024 precedents: yfinance returned stale data 4–6 hours, CBOE infrastructure had 30+ min outages, FRED HY OAS publishes T+1 (moot in 2-day shocks), RSS feeds rate-limit IPs aggressively. CC-S7 mitigates by failing closed (no signal, no false positive) but the *coverage* during these windows is reduced.

3. **The audit's M3 cooldown fix and CC-S2 correlation-decay penalty are HARD preconditions.** These features assume Phase-2 silent-drop rate is <10% and per-analyst cooldown is precision-weighted. The audit currently documents 78.4% silent-drop and a parallel-read race that lets two near-simultaneous spoofed signals both pass cooldown. **Without M3 + CC-S2, every new instant-trigger feature inherits an exploitable surface.** Audit fixes are not optional.

4. **Concentrated mega-cap leadership regime (2023–2024 pattern) creates feature-fire redundancy.** F1, F5, F8 will all fire most often on same handful of names (NVDA, MSFT, META, etc., and a handful of activist targets); the 2-source rule will be trivially satisfied but additional sources report on the same underlying capital-flow phenomenon. CC-S2 correlation-decay penalty addresses cheap noise injection but does not address structural redundancy in this regime — net coverage gain shrinks toward 0 in extreme concentration phases.

5. **Adversarial-text input attacks have NO fully satisfying hardening.** Feature 7 (FinBERT) was killed because PR-wire placement at $300 + adversarial-tokenizer attacks at $0 are economically asymmetric — defender's cost grows unbounded. The remaining surviving sentiment surface (F10 Wikipedia at +0.05 cap) has known partial defenses (C1 mandatory Google Trends co-confirm, C2 sustained-spike, C3 cap) but cohort-style brigades sustained for 3+ hours remain a residual attack surface. **This vector is explicitly unresolved**; the +0.05 cap limits damage but does not eliminate the possibility of a coordinated brigade tipping a borderline alert across the threshold.

6. **TweetShift cohort is itself a long-game attack surface.** Attack X4 (12-month sock-puppet activist constellation) and the cohort-infiltration vector (Feature 13's A4 attack — gain credibility via aged content, then post spoofed cluster) are unresolved. The audit's M3 (per-analyst hit-rate cooldown) raises the bar but does not eliminate the possibility — a sock-puppet who maintains genuine pseudo-precision for 6+ months passes M3. Acceptable residual risk; not full defense.

7. **F3 (pre-FOMC) front-running is structural.** Any public alert is front-runnable by an adversary listening to the public Discord. C3 (auction-imbalance gate) and C4 (±90s randomization) are soft mitigations that increase attacker slippage but do not eliminate the front-running surface. This is acceptable but should be communicated to operator.

8. **Calendar resolver consolidation (CC-S6) is contested between A and B's resolution.** A wanted FOMC weekly refresh + EFFR kill-switch; B was content with annual scrape. Resolved in favor of weekly (strictly safer) but the consolidation shifts complexity into the calendar service — daily-cadence staleness check is required, and any drift in the staleness check itself silently mis-fires all dependent features. Single-point-of-failure risk acknowledged.

9. **Reg SHO (F11) regime gate is itself regime-dependent.** A2's regime gate (`VIX > 22 AND HY OAS > 350bps`) makes F11 silent in low-vol regimes by design — but this means F11 contributes ZERO coverage when most regimes the bot operates in are calm. Effective fire rate in normal markets: a few per quarter on $2B+ caps. Acceptable but operator should not expect F11 as a workhorse.

10. **The +5pp precision Bullet 1 of the High-Impact Bar is MARGINAL.** Aggregate is +3 to +5pp weighted by fire-rate. If any of F1, F6, F8 underdelivers on its claimed precision (e.g., post-2020 regime compression on insider literature, gate's social-signal lift is <5pp), the Bar is missed. The kill criteria per feature provide retirement triggers, but the aggregate target is not guaranteed by construction — it depends on three independent features hitting their claimed deltas simultaneously. **This is honest, not pessimistic: the literature supports it, but production data may differ.**

---

End of Phase 3 Converge final feature set.
