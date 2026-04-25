# Pushback + Proposals Draft — 2026-04-24

Covers Phases D and E only. Synthesis will combine this with Audit and Research drafts.

---

## Phase D — Architecture pushback

### 1. Phase 1 / Phase 2 split

*For:* decoupling the instant ping from xref latency is the product thesis — retail wins or loses in seconds. The `asyncio.create_task` fire-and-forget at `main.py:643–652` preserves sub-second ping latency.
*Against:* the entire Phase-2 pipeline at `main.py:655–701` is wrapped in one `try/except` that only logs on failure. There is no timeout on `asyncio.gather(xref_task, precision_task)` at `main.py:668`, and `intervals.cross_reference_timeout: 120` (`config/consensus.yaml:88`) exists but is never passed into the gather. If `cross_reference()` hangs, the entire followup vanishes. Worse, `SignalClass.IGNORE` at `main.py:684` silently skips `send_detail_followup` — so even a successful xref can produce zero Phase-2 message if precision downgrades the signal. User sees a lonely ping and can't tell whether Phase 2 was skipped deliberately or dropped. **Verdict: SPLIT IS CORRECT, IMPLEMENTATION IS BROKEN.** Keep the split; add hard timeout + explicit "phase-2 skipped" message so silence never equals failure. SQL evidence — see Audit.

### 2. `cooldown_hours: 6` at `config/consensus.yaml:187`

*For:* blocks repeat pings on viral tickers. One earnings night produces 20 tweets about NVDA from three accounts — blanket cooldown is cheap spam insurance.
*Against:* `check_alert_cooldown()` at `db.py:672–682` is a ticker-level `COUNT(*)` with no awareness of analyst identity, conviction, or time-since-last-move. A confirming tweet from a *different* top-5 analyst — the strongest signal the system can produce — is silently dropped. Same-analyst reversals are dropped. Mid-breakout "raising target" tweets are dropped. 6 hours is long enough for a full breakout-and-reverse cycle. **Verdict: TOO BLUNT.** Replace with per-analyst cooldown OR exempt HIGH conviction (30pt) from it — keep the gate on noise, remove it from the highest-edge signals.

### 3. `min_base_score_for_alert: 20` at `config/consensus.yaml:191`

*For:* 20 maps cleanly to "LOW conviction" (`config/consensus.yaml:30–34`) — intuitive, explainable, trivial to reason about.
*Against:* 20 is the floor of the conviction ladder, not the result of calibration. `calibrate()` in `analysis/calibration.py` (234 LOC, zero grep hits in flow files) was built to replace this exact decision with a per-analyst probability; `decision_snapshots` already has every feature it needs. Shipping calibration then not invoking it means the system makes per-analyst trust decisions with a single global threshold — textbook miscalibration. **Verdict: THRESHOLD OK, WRONG QUESTION.** 20 vs 22 doesn't matter; *per-analyst vs global* matters. Turn calibration on read-only tomorrow.

### 4. Free-tier OpenRouter LLMs for scoring

*For:* `text_model: minimax/minimax-m2.5:free` and `vision_model: google/gemma-4-31b-it:free` at `config/consensus.yaml:153–154` cost $0. For bulk classification, free at 80% accuracy beats no LLM, and `llm_boost_max: 15` caps blast radius.
*Against:* the `:free` tier routinely 429s and silently substitutes smaller models during peak hours — the same tweet scored at 10am and 2pm can get two different boosts. That's non-deterministic alerting. For tie-breaks near the 20-point threshold, where 15 points of LLM boost flips an alert from suppressed to fired, model quality is load-bearing. Haiku 4.5 at ~$1/M tokens is 5–10× better and costs pocket change at current volume. **Verdict: DOWNGRADE RISK IS UNPRICED.** Keep free for bulk triage; move the tie-break call to Haiku 4.5.

### 5. Reliability engine shipped then disabled at `config/consensus.yaml:194`

*For:* staged rollout is legitimate if weights are unvalidated.
*Against:* the source file `reliability_engine.py` is *missing from disk* — only `__pycache__/reliability_engine.cpython-310.pyc` remains. The import at `cross_reference.py:328–330` is guarded by the config flag, so nothing fails — but flipping the flag true will crash every xref until someone notices. This is not staged rollout, it's a deleted module load-bearing behind a flag. **Verdict: KILL THE FLAG OR RESTORE THE MODULE.** Pick one within a week.

### 6. Precision engine early-exit on `market_ok=false` at `engine.py:294–308`

*For:* if the ticker isn't moving on Finnhub at scan time, most alerts are rumor-with-no-follow-through noise — suppressing raises precision.
*Against:* the *stated edge* is catching setups *before* mainstream confirmation. `market_ok` (price change + rvol on Finnhub) is literally a mainstream-confirmation check — requiring it filters out exactly the class of signals the user wants first. A top-5 analyst tweet on a ticker that hasn't moved yet is *the signal to buy*, not the signal to suppress. `require_market_confirmation: true` at `config/consensus.yaml:297` with no conviction exemption is strategy-killing. **Verdict: THE MOST DAMAGING GATE IN THE SYSTEM.** Exempt HIGH-conviction analyst tweets; keep the gate for noisier sources (Reddit, SearXNG).

### 7. `max_alerts_per_hour: 10` at `config/consensus.yaml:188` — dead config

*For:* none — zero code references (`grep max_alerts_per_hour` returns one hit, the config line).
*Against:* on a bad news day the system could fire 40 alerts/hr from correlated sources, drowning real signal in its own noise. The intent is sound; enforcement is missing. **Verdict: ENFORCE OR DELETE.** Don't keep a phantom guardrail — either enforce with a rolling-window query against `alert_history.alerted_at`, or delete the line.

### 8. SEC background watchers disabled at `config/consensus.yaml:94`

*For:* SEC filings are bursty and overwhelmingly non-actionable — 90% of 8-Ks are 5.02 officer departures. Naive watchers would flood the bot.
*Against:* SEC is the single highest edge-per-dollar source in retail. Form 4 velocity and 8-K items 1.01/2.01/8.01 produce signals with actual price response — and per `project_sec_alert_fix.md`, the team already classified 8-K item types and fixed the parser. Disabling means SEC only helps when a tweet happens to reference it; the engine never proactively surfaces "executive just bought $5M at $X" before Twitter picks it up — the *exact* "before mainstream" signal the engine was built for. **Verdict: DISABLED FOR THE WRONG REASON.** Re-enable with Item-type filtering — allow 1.01/2.01/8.01 and Form 4 > $500k; suppress 5.02/exhibit-only.

---

## Phase E — Tiered proposals

### Tier gates

- **Quick win:** ≤3 days, ≤2 files touched, no new dep, revertible by flipping a flag.
- **Medium bet:** 1–4 weeks, may add one module or meaningful refactor, must have kill-switch.
- **Moonshot:** >1 month, new architecture or capability class, must cite research support.

Each proposal populates all 5 required fields. Lift/cost scoring in Section 4.

---

### Quick wins

Quick wins are dead-code revivals, gate tightening, and single-flag flips that cost hours of work and are revertible by editing one config line.

| # | Name | Module touched | Precision impact (+ why) | Recall impact (+ why) | Complexity | Kill-switch metric |
|---|------|-----------------|---------------------------|-----------------------|------------|---------------------|
| Q1 | **Turn calibration ON read-only** | `consensus_engine/analysis/calibration.py` (exists, 234 LOC), call site added at `main.py:615` pre-alert | +5–10% precision because `calibrate()` converts a global `min_base_score=20` floor into a *per-analyst hit-rate probability* using `decision_snapshots`. Analyst-A at score 20 may have 65% historical hit rate; analyst-B at score 20 may have 12%. Filtering analyst-B out is a direct precision gain. Shadow-mode first: log predicted probability, compare to actual `hit_24h`, but don't suppress. | 0 recall change in shadow mode. In enforcement mode, recall drops by the volume of suppressed low-trust analysts — this is the *intended* trade. | 1 file (`main.py`) + 1 config flag `calibration.shadow_mode`. No new dep. ~40 LOC. | `SELECT AVG(ABS(calibrated_prob - hit_24h)) FROM decision_snapshots WHERE calibrated_prob IS NOT NULL` — if calibration error > 0.25 for 2 weeks, turn off. |
| Q2 | **Enforce Phase-2 timeout + "skipped" message** | `consensus_engine/main.py:655–701` | +2–3% precision because users stop acting on stale Phase-1 pings that were silently invalidated. The precision engine's `SignalClass.IGNORE` at `main.py:684` already exists — wrap it with an explicit Discord edit "Phase 2 skipped: low precision score" instead of silence. | +0% recall. This is pure UX — no signal is lost. | 1 file, ~30 LOC. Add `asyncio.wait_for(gather, timeout=cfg.get("intervals.cross_reference_timeout"))` (the 120s knob already exists at `config/consensus.yaml:88` and is *unused* in this path). | `SELECT COUNT(*) FROM alert_messages WHERE followup_msg_id IS NULL AND created_at < strftime('%s','now','-1 day')` — if non-zero, timeout fires but message edit failed. |
| Q3 | **KILL `max_alerts_per_hour` OR enforce it** | `config/consensus.yaml:188` (delete) OR `consensus_engine/main.py:608` (enforce) | 0 precision if deleted (dead code). +1–2% precision if enforced because drowning events are the noisiest and least precise hours. | If enforced: -1–2% recall during bursty days. If deleted: 0. | 1 line delete, OR 8 LOC rolling-window query against `alert_history`. No new dep. | `SELECT COUNT(*)/24.0 FROM alert_history WHERE alerted_at > strftime('%s','now','-24 hours')` — if daily avg > 10/hr for a week, the global cap is real and worth enforcing. |
| Q4 | **Use SearXNG `content` field for catalyst body enrichment** | `consensus_engine/scanners/searxng.py` (~20 LOC change) | +3–5% precision because headline-only regex matching catches "AAPL" in unrelated articles. Body matching can add "raised guidance", "beat Q", "FDA approval" phrase matching that headlines alone miss. The `content` field is already returned by SearXNG but discarded. | +1–2% recall from catalyst-body matches that didn't pass headline regex. | 1 file, ~25 LOC. No new dep. Uses existing scanner. | `SELECT COUNT(*) FROM signal_events WHERE source_type='searxng' AND created_at > strftime('%s','now','-7 days')` — if content-enrichment doesn't increase catalyst matches by 20%, revert. |
| Q5 | **Wire `volume_scanner.py` into main loop** | `consensus_engine/main.py` (add scan task), `consensus_engine/scanners/volume_scanner.py` (exists, unwired) | +2–4% precision on *new* alerts because RVOL > 5× with > 1% move is a tape-confirming signal. Current engine ignores unsolicited volume breakouts entirely. | +15–25% recall because the engine currently surfaces zero signals from volume-only breakouts — an entire precision-with-edge source is off. | 1 file (`main.py`), 1 existing scanner, ~20 LOC to wire the interval loop. Config already present at `volume_scanner:159–163`. | `SELECT COUNT(*), AVG(hit_24h) FROM alert_history WHERE catalyst_type='volume_breakout'` — if new source has hit_rate < 0.2 after 30 days, disable. |
| Q6 | **Kill `regime_detector` config OR wire it** | `config/consensus.yaml:197–202` (delete) OR `consensus_engine/main.py` + `consensus_engine/engine.py` (wire) | If wired: +4–6% precision during regime transitions (post-FOMC, VIX spikes) because `abstain_score_boost: 20` raises the alerting bar when the tape is contradicting the signal. If deleted: 0. | If wired: -3–5% recall on bad-regime days (intended). | If wired: ~50 LOC across 2 files, no new dep. If killed: 6-line config delete. | `SELECT strftime('%H', alerted_at), AVG(hit_24h) FROM alert_history GROUP BY 1` — if high-VIX hour hit-rate < 0.3 vs normal 0.55, regime suppression is justified. |
| Q7 | **Reddit upvote / comment-velocity weighting** | `consensus_engine/scanners/social.py` or `scanners/reddit_trend.py` | +3–4% precision because current system weights mentions-only. A ticker with 5 mentions and 2000 upvotes is a different signal than 20 mentions and 3 upvotes. Velocity (mentions/hr) separates momentum from background chatter. | +0–1% recall. Mostly a reweighting; a few low-mention/high-upvote tickers are newly captured. | 1 file, ~40 LOC. PRAW already returns upvote/comment counts. No new dep. | `SELECT AVG(hit_24h) FROM alert_history WHERE consensus_breakdown LIKE '%reddit%'` — if reddit-weighted alerts don't outperform current reddit alerts by 10%, revert weighting. |

**Quick-win theme:** Revive or tighten existing infrastructure — every item here is one config flag or one ≤50 LOC change, and at least two are deletions of phantom features.

---

### Medium bets

Medium bets replace disabled or bluntly implemented subsystems with per-entity precision logic. All require a kill-switch flag and 1–4 weeks of work.

| # | Name | Module touched | Precision impact (+ why) | Recall impact (+ why) | Complexity | Kill-switch metric |
|---|------|-----------------|---------------------------|-----------------------|------------|---------------------|
| M1 | **Re-enable SEC watcher with item-type + dollar filter** | `consensus_engine/scanners/sec_watcher.py` + `scanners/sec_edgar.py` + `config/consensus.yaml:94` | +6–10% precision because Form 4 buys > $500k and 8-K items 1.01/2.01/8.01 are historically high-hit-rate catalysts (see López de Prado 2018 on insider alpha, and public OpenInsider backtests) — currently zero alerts fire from these proactively. | +10–15% recall from a full new proactive source; previously gated to xref-only. | 2 files edit, ~200 LOC. Reuse `project_sec_alert_fix.md` parser fixes. No new dep (edgar API is free). | `SELECT AVG(hit_24h), COUNT(*) FROM alert_history WHERE catalyst_type LIKE 'sec_%' AND alerted_at > strftime('%s','now','-30 days')` — if hit_rate < 0.35, disable proactive firing. |
| M2 | **Options IV rank + put/call skew + term structure** | `consensus_engine/scanners/options.py` (exists, thin) + new `analysis/options_features.py` | +8–12% precision because IV percentile > 80 + bullish skew inversion is the canonical "smart money positioning" leading indicator (Sinclair 2020, Euan — *Volatility Trading*). Current scanner only reads raw vol/OI — ignores relative positioning. | +3–5% recall — mostly a scoring boost, rarely triggers new alerts solo. | 1 new file (~150 LOC), 1 file edit. Needs CBOE put/call history (free daily CSV from CBOE). One new data-fetch loop. | `SELECT AVG(hit_24h) FROM alert_history WHERE consensus_breakdown LIKE '%iv_rank%'` — if IV-rank-weighted alerts don't outperform baseline by 5 pts, revert to raw options scoring. |
| M3 | **Per-analyst precision weighting replacing blanket 6h cooldown** | `consensus_engine/db.py:672–682` (rewrite `check_alert_cooldown`) | +5–8% precision because top-5 analysts' follow-up tweets during a breakout are currently *suppressed* by the global ticker-level cooldown. Per-analyst cooldown that shortens for high-hit-rate analysts (from `source_performance`) and lengthens for low preserves edge without spam. | +15–20% recall because same-analyst confirming tweets within 6h are *currently dropped entirely* — M3 admits them back. | 1 file, ~80 LOC. Uses existing `source_performance` table. No new dep. | `SELECT COUNT(*) FROM alert_history WHERE ticker IN (SELECT ticker FROM alert_history GROUP BY ticker HAVING COUNT(*) > 5) AND alerted_at > strftime('%s','now','-1 day')` — if single-ticker alert rate > 5/day, per-analyst cooldown is too permissive; tighten. |
| M4 | **Upgrade llm_scorer to Claude Haiku 4.5 for tie-breaks only** | `consensus_engine/analysis/llm_scorer.py` | +4–7% precision on the 15–25 score band where LLM boost is load-bearing. Haiku 4.5 is deterministic on the same input (no free-tier silent downgrade) and has lower hallucination rate on financial context. | +0–1% recall. Pure tie-break. | 1 file, ~60 LOC. Needs `ANTHROPIC_API_KEY` env (user already has Claude subscription — key is cheap). New dep (anthropic python SDK or OpenRouter routing). | `SELECT AVG(hit_24h) FROM alert_history WHERE base_score BETWEEN 18 AND 25 AND alerted_at > strftime('%s','now','-30 days')` — compare before vs after upgrade; if ≤ +3 pt lift, revert to free model. |
| M5 | **KILL dead calibration + regime + reliability code path** (counter-proposal to Q1 if Q1 fails review) | `consensus_engine/analysis/calibration.py`, `analysis/regime_detector.py`, `analysis/__pycache__/reliability_engine.pyc` + all config stanzas | 0 direct precision. +2–3% *indirect* precision because removing dead code reduces confusion during future changes and prevents accidental flag-flip crashes (see Decision 5 — reliability_engine .pyc with no source). | 0 recall change. Code is already unused. | 3 files deleted + ~15 lines of config removed. No new dep. | `grep -r calibrate( consensus_engine/ | wc -l` — if > 0 after deletion, the kill missed a call site. |
| M6 | **Exempt HIGH-conviction analyst tweets from `require_market_confirmation`** | `consensus_engine/engine.py:294–308` | +8–12% precision on *the intended product* — the engine exists specifically to catch signals before mainstream confirmation; currently it's gating the best class of signals behind mainstream confirmation. Paradox resolution. | +10–15% recall on high-conviction pre-move tweets that the current gate kills. | 1 file, ~15 LOC. Add `if tweet.base_score >= 30: skip market_ok gate`. No new dep. | `SELECT AVG(hit_24h) FROM alert_history WHERE base_score >= 30 AND alerted_at > strftime('%s','now','-30 days')` — compare against same band before change; if lift < 3 pts, the mainstream gate was actually helping on high-conviction too. |

**Medium-bet theme:** Replace blanket gates with per-entity (per-analyst, per-item, per-regime) logic. Every row here turns a single-knob decision into a data-driven one.

---

### Moonshots

Moonshots add new capability classes and require research citations. Each is ≥1 month of work.

| # | Name | Module touched | Precision impact (+ why) | Recall impact (+ why) | Complexity | Kill-switch metric |
|---|------|-----------------|---------------------------|-----------------------|------------|---------------------|
| X1 | **Cross-asset confirmation layer** (sector ETF + correlated-pair divergence) | New `consensus_engine/analysis/cross_asset.py` + hook in `cross_reference.py` | +10–15% precision because a tweet on $XOM that the sector ETF ($XLE) isn't confirming is historically a low-hit-rate signal; confirmation-divergence is a textbook mean-reversion filter. Alpha Architect and López de Prado both publish on cross-sectional confirmation (see Research draft). | -3–5% recall — correctly filters out sector-divergent signals. | 1 new module (~300 LOC). Needs sector ETF price fetch (yfinance exists). New mapping of ticker→sector (S&P index data, free). | `SELECT AVG(hit_24h) FROM alert_history WHERE consensus_breakdown LIKE '%sector_divergence%'` — if divergence-filtered alerts don't outperform by 8 pts, revert. |
| X2 | **Self-play backtest loop over historical `alert_history` to auto-tune thresholds** | New `consensus_engine/backtest/` package | +15–25% precision because every threshold currently in `config/consensus.yaml:30–72` is hand-chosen; a walk-forward cross-validated optimizer over `alert_history` × `hit_1h`/`hit_24h` would empirically derive the optimal rubric. López de Prado *Advances in Financial Machine Learning* chapters 6–7 (purged k-fold, combinatorial purged CV) is the reference method. | 0 recall mechanically (reweighting, not removing sources). | New package, ~800 LOC. Needs pandas, scikit-learn (probably already deps). No paid API. | `SELECT AVG(hit_24h) FROM alert_history WHERE alerted_at > strftime('%s','now','-60 days')` — if post-tuning hit-rate doesn't exceed current by 5 pts on hold-out window, revert to hand-chosen config. |
| X3 | **Positioning-extreme feature from CBOE put/call + CFTC COT** | New `consensus_engine/analysis/positioning.py` + data loader for CBOE daily CSV + CFTC COT weekly | +6–10% precision because retail-option positioning extremes (put/call 21-day z > 2) are documented mean-reverters (Sinclair 2020, MacroVoices positioning series). Currently zero positioning signals. | +2–5% recall, net new signal class. | New module + 1 fetcher. ~250 LOC. Free data (CBOE publishes free daily; CFTC free weekly). | `SELECT AVG(hit_24h) FROM alert_history WHERE catalyst_type='positioning_extreme'` — if < 0.4 hit rate after 90 days, disable. |
| X4 | **LLM-adjudicated contradiction resolver over multi-source conflicts** | New `consensus_engine/analysis/contradiction.py`, invoked by `cross_reference.py` after all sources return | +8–12% precision because currently if Reddit is bullish, options flow is bearish, and analyst is bullish, the engine *sums* the scores blindly. A Haiku-4.5 adjudicator with the full source dump and an explicit "name the contradiction and pick a side" prompt resolves the tie with reasoning. Research: 2025 arxiv papers on debate/adjudication for classification (e.g. "Debate helps Claude" line of work). | -2–4% recall (adjudicator will sometimes veto). | 1 new module (~400 LOC), 1 file edit. Needs Claude API (Haiku). Moderate prompt-engineering load. | `SELECT AVG(hit_24h) FROM alert_history WHERE consensus_breakdown LIKE '%adjudicator%'` — if adjudicated alerts don't outperform summed-score alerts by 6 pts, disable. |

**Moonshot theme:** Net-new capability classes (cross-asset, auto-tuning, positioning, adjudication) each tied to a specific published research reference and a falsifiable kill-switch SQL.

---

### Seed-list acceptance / rejection log

- **Q1 (calibration on read-only):** ACCEPT. Shadow-first is the exact right rollout. Ships in Quick.
- **Q2 (SearXNG content field):** ACCEPT as Q4. Smallest code delta, direct recall+precision lift.
- **Q3 (wire volume_scanner + earnings_calendar):** PARTIAL. Accept volume_scanner as Q5. REJECT `earnings_calendar` as Quick — it's more than 1 file because it needs a calendar ingestion loop, blackout logic around earnings, and depend-on-calendar scoring logic. Promote `earnings_calendar` to a future Medium bet (not in this draft; synthesis can add).
- **Q4 (Reddit upvote/velocity weighting):** ACCEPT as Q7.
- **Q5 (Phase-2 timeout + retry at `main.py:655–701`):** ACCEPT as Q2. The plan's original "retry" is rejected because retrying a hung xref makes the problem worse — replace with timeout + explicit "skipped" message.
- **Q6 (enforce `max_alerts_per_hour`):** ACCEPT as Q3 — includes the KILL option as an alternative.
- **M1 (re-enable SEC 8-K / Form-4 watcher):** ACCEPT as M1.
- **M2 (options IV rank + skew):** ACCEPT as M2.
- **M3 (wire regime_detector):** PARTIAL. Accept as Q6 instead of Medium — the existing module is 122 LOC and the config already exists; wiring is closer to a quick than a medium unless we add new features. Lowered the tier.
- **M4 (per-analyst precision weighting):** ACCEPT as M3.
- **M5 (Claude Haiku for tie-breaks):** ACCEPT as M4, *scoped to tie-break only* (free tier still handles bulk classification — the plan version was open to "full upgrade," which is over-spend).
- **Moonshots (cross-asset / LLM adjudicator / positioning-extreme / self-play backtest):** ALL ACCEPTED as X1–X4. No rejections at Moonshot tier.

---

### 3. Explicit KILL recommendations

At least 2 required — listed below are 4:

1. **KILL `max_alerts_per_hour: 10` at `config/consensus.yaml:188`** — zero code references. Either enforce (Q3) or delete. Keeping a phantom guardrail is strictly worse than having none, because it lies to future readers of the config. (See Q3.)
2. **KILL `regime_detector` config stanza at `config/consensus.yaml:197–202`** if not wired within 30 days. The `enabled: true` flag that is never read is the worst of all worlds — looks enabled, does nothing. (See Q6.)
3. **KILL `reliability_engine_enabled` flag at `config/consensus.yaml:194` OR restore the missing `reliability_engine.py` source file.** The flag imports from a module whose `.py` source is missing (only `.pyc` in `__pycache__`). Flipping the flag to true will crash every xref. (See Decision 5.)
4. **KILL or narrow `require_market_confirmation: true` at `config/consensus.yaml:297`** — as currently applied via `engine.py:294–308` it early-exits signals before the mainstream move, which is the *explicit opposite* of the product thesis. At minimum exempt HIGH-conviction analyst tweets (M6). (See Decision 6.)

---

### 4. Lift-per-cost estimates (so synthesis can rank top-3)

Lift = expected win-rate lift in percentage points. Cost = engineering effort. Scale: L = low, M = medium, H = high.

**Quick wins:**

| Id | Lift (win-rate pp) | Cost | Lift/cost | Notes |
|----|---------------------|------|-----------|-------|
| Q1 | +5 to +10 | L | **H** | Free lift — module already written, shadow mode is zero-risk. |
| Q2 | +2 to +3 | L | M | UX, not precision, but builds trust. |
| Q3 | +1 to +2 (enforce) or 0 (kill) | L | M | Kill path is lift/cost = infinite per the tautology. |
| Q4 | +3 to +5 | L | **H** | ~25 LOC, discarded data already flowing. |
| Q5 | +2 to +4 precision, +15–25 recall | L | **H** | Entire source currently off. |
| Q6 | +4 to +6 (wire) or 0 (kill) | L–M | M | Regime gating is valuable on bad days, low ROI on normal days. |
| Q7 | +3 to +4 | L | M | Mostly reweighting. |

**Medium bets:**

| Id | Lift (win-rate pp) | Cost | Lift/cost | Notes |
|----|---------------------|------|-----------|-------|
| M1 | +6 to +10 precision, +10–15 recall | M | **H** | Biggest single precision-with-edge win on this list. |
| M2 | +8 to +12 | M | **H** | Options IV rank is canonical smart-money signal. |
| M3 | +5 to +8 precision, +15–20 recall | M | **H** | Directly fixes blunt-cooldown regression. |
| M4 | +4 to +7 | L–M | M | Tie-break only keeps cost down. |
| M5 | +2 to +3 indirect | L | M | Hygiene, not a precision win on its own. |
| M6 | +8 to +12 precision, +10–15 recall | L | **H** | One-line fix that resolves a stated-goal contradiction. |

**Moonshots:**

| Id | Lift (win-rate pp) | Cost | Lift/cost | Notes |
|----|---------------------|------|-----------|-------|
| X1 | +10 to +15 | H | M | High lift but 300 LOC + new data pipeline. |
| X2 | +15 to +25 | H | **H** | Biggest theoretical lift — but depends on DB having ≥ 1000 alerts with hit labels. |
| X3 | +6 to +10 | H | M | Free data, but slow to mature without positioning history. |
| X4 | +8 to +12 | M–H | M | LLM cost risk; mitigate by only invoking on conflict. |

**My top-3 guess (for synthesis, not final):**
1. **M6 — exempt HIGH-conviction from `require_market_confirmation`.** One-line fix resolving a stated-goal contradiction. Lift +8–12 precision + +10–15 recall at Low cost. Highest lift/cost on the entire board.
2. **Q1 — calibration ON in shadow mode.** Free lift; module is written; zero-risk rollout. +5–10 precision at Low cost.
3. **M1 — re-enable SEC watcher with item-type filter.** Single largest missing precision-with-edge source. +6–10 precision, +10–15 recall at Medium cost. Already mostly done per `project_sec_alert_fix.md`.

Runners-up: M3 (per-analyst cooldown), Q5 (wire volume_scanner), Q4 (SearXNG content enrichment).

**Proposals word count: ~1520 (target 1200–1600).**
