# Final Implementation Plan — signal-features-2026-06-09 (Pass 4)

**Feature set = EXACTLY §B of `pass-3-stress-tested.md`.** 14 BUILD (Waves 1–4), 1 DEFER (I18), 3 dropped/deferred (I8, E3, I11), 1 prior drop (E5). No features added or removed. Every item carries its Pass-3 required change as an explicit build step.

**House rule (non-negotiable, applies to every item):** lands **flag-OFF by default · shadow-first · kill-switch wired · regression-gate clean.** Live activation is a **separate user-sign-off gate** (see §7), NOT part of this build.

**Build-now scope:** Phase 1 = Wave 1 + Wave 2 (I9, I12, I16, I14-display, I4-display-honesty, I1, I2, I5, I6). Phase 2 = Wave 3 + Wave 4 (I3, I10, E6, I13, I15, I4-full, I7, I14-widening, E2, E1), fully specified here, built after Phase 1 verifies. **Phase-1 verification checklist (§8.A) is the build-now Definition of Done.**

All file:line anchors below were re-verified against live source during this pass.

---

## 1. System Overview

The bot has three independent brains, all preserved by this plan:

- **Phase-1 instant alert** (`main.py::process_tweet` :1094): cheap gates → instant Discord ping → spawns Phase-2 task. The hardcoded quality gate is `main.py:1066` (`quality_score >= 20`). **I9** reconnects the documented `alerts.min_base_score_for_alert` knob here.
- **Phase-2 scoring** (`main.py::_run_cross_reference_and_followup` :1211): runs `cross_reference.score_ticker` (:451, additive sum) and `engine.analyze_signal` (precision escalation) in parallel, then renders the follow-up (`discord.py`). **Most features touch this lane.** The additive sum is built at `cross_reference.py:483-577` (analyst/news/sec/technical/social/options/youtube/consensus terms). The precision class is decided by `engine._classify` (:228-277). The render contract is `main.py:1255-1293` + `discord.py:447` headline.
- **Wolf #news brain** (`analysis/wolf_*` + `alerts/wolf_*`): read-only on the live tables via `db.get_confluence_stances` (:3354). **I15** (confluence votes) and **I16** (outcome benchmark) touch this brain only — no live per-ticker scoring blast radius.

The plan's edge: it **stops the bot scoring against itself** (bearish YouTube raising a long — I1; put-walls adding points — I6; track-record-blind analysts — I2; crowd-only STRONGs — I10; a displayed number that does not gate — I4), **surfaces contradiction/freshness context** (I3, and deferred I18), and adds **free confirm/veto layers** (I13, I15, E1, E2) that raise precision without new standalone alert noise. It does NOT add a new alert generator and does NOT manufacture a proprietary-data edge from free feeds.

The single cross-cutting risk threaded through I3/I13/I15/E1/E2 is **time-basis skew → "phantom confluence"** (mixing near-instant SEC/tweets with EOD/daily-lag FINRA/YouTube/ApeWisdom). §3 defines the **common-recency-window synchronizer** that every multi-source computation must call.

---

## 2. Component Architecture

Per module: purpose · inputs · outputs · core logic · the exact Pass-3 safeguard. New modules are marked **[NEW]**.

### Wave 1

**I9 — reconnect `min_base_score_for_alert`** (`main.py:1066`)
- Purpose: make the documented dead knob (Gap #4) live; value-neutral at default 20.
- Input: `tweet.base_score` (with the existing −5 neutral discount at :1064-1065). Output: bool pass/fail.
- Logic: replace literal `return quality_score >= 20` with `return quality_score >= cfg.get("alerts.min_base_score_for_alert", 20)`.
- **Safeguard:** ship at default 20 (truly inert until deliberately changed — needs no flag). Add a **shadow volume-preview log line** on each gate eval: `would_suppress_at_25 / _at_30` counts, so any future raise has a measured readout first. Keep the −5 neutral discount explicit; document the effective neutral floor (25).

**I12 — magnitude-scaled earnings beat/miss** (scoring site `cross_reference.py:484` `news_pts = _get_catalyst_score(...)`; the surprise number originates at `scanners/earnings_calendar.py:168` `surprisePercent`, is read in `scanners/news.py:162` `eps_surprise_pct = recap.get("eps_surprise_pct")`, and is **today only formatted into a display string** at `scanners/news.py:180-182` — it is NOT a numeric field on the catalyst object the scorer reads)
- Purpose: a +40% blowout beat and an in-line print currently score the same catalyst tier.
- **Wiring prerequisite (verified — must be done first):** the scoring site reads only `catalyst.catalyst_type` and `catalyst.passed`; `CatalystResult` (`models.py:82-90`) carries `catalyst_type` + `catalyst_body` (string) but **no numeric `eps_surprise_pct`**. So step 1 is to add `eps_surprise_pct: float | None = None` and `eps_estimate: float | None = None` to `CatalystResult`, populate them from the recap in `scanners/news.py` where `catalyst_body` is built (the recap dict already has `eps_actual`/`eps_estimate`/`eps_surprise_pct`), and confirm that same `CatalystResult` object reaches `cross_reference.py:484`. Only after the number is reachable at the scoring site can the bonus be added.
- Input: numeric `catalyst.eps_surprise_pct` (newly threaded) + `catalyst.eps_estimate` for the denominator guard. Output: a bonus added to `news_pts`, cap +15.
- Logic: when catalyst type is "Earnings Report"/"Earnings Beat" and a fresh recap carries a numeric `eps_surprise_pct`, add `+5 per 10% surprise, cap +15` on top of the existing tier (base tier stays the floor).
- **Safeguard:** **absolute-$ surprise floor + sane-denominator guard** (require `|eps_surprise_pct|` above `min_abs_eps` AND a non-trivial `eps_estimate` denominator, so a $0.01 beat on a $0.001 estimate can't manufacture +900%); **cap +15**; **freshness gate** — only apply when the recap is within the fresh post-print window (`fetch_recent_earnings_for_ticker` returns None / empty `period` outside it). Flag `features.earnings_magnitude.enabled`.

**I16 — benchmark-adjust Wolf outcomes** (`wolf_outcomes.py:83-88` `_classify` + :144-146 compute body)
- Purpose: a relative-strength call is credited "moved_with" if the proxy merely rose, even if it lagged SPY. Recap-only.
- Input: `_fetch_proxy_series` (:40) result + a new SPY series over the same window (SPY OHLCV already pulled by `regime.py`). Output: a benchmark-adjusted state alongside the raw state.
- Logic: compute `excess = proxy_pct − benchmark_pct`; credit "moved_with" only when `excess > band`. Scope-aware benchmark: single-name → SPY, sector scope → its sector ETF (reuse `wolf_scope` scope_type), and for inverse-proxy scopes flip the benchmark sign (reuse `wolf_scope` inverse-proxy flag).
- **Safeguard:** **scope-aware, sign-aware benchmark** (no naive SPY for sector/inverse); **surface BOTH raw and benchmark-adjusted** in the Sunday recap (never replace raw — honors thin-sample memory). Recap-only: no live alert touched; flag `wolf.outcomes.benchmark_adjusted`.

**I14-display — regime risk-context line** (`discord.py` Phase-2 embed; reads `regime.py` `RegimeContext` :24 — `label`, `z_score`, `cold_start`)
- Purpose: the bot's one macro-risk read never appears in the alert.
- Input: `RegimeContext`. Output: one embed field line, e.g. `Regime: elevated (z=0.8)`.
- Logic: render label + z. When `cold_start=True`, render **"regime: warming up"** (do NOT imply active protection).
- **Safeguard:** display-only, pure-additive; widening half deferred to Wave 4. Flag `features.regime_context_line.enabled`. Embed-snapshot tests updated deliberately.

**I4-display-honesty** (`main.py:1269-1293` + `discord.py:447` headline `Cross-Reference: ${ticker} | Score: {total}`)
- Purpose: the headline shows the inflated additive `xref.final_score`; the precision engine actually decides (`main.py:1271-1273` logs `precision=%s overrides xref_score`).
- Input: `xref.final_score`, `precision` dict (has `classification`, `score`), and a new **per-source skipped-for-budget flag** (build it first if absent — see §4). Output: the displayed headline number + an explicit degraded state.
- Logic: render the precision-gated number, not the raw sum. On a **budget-depressed** run (a paid source was skipped), render an explicit `confidence degraded: budget` state — **never silently revert to the higher number.** The deeper single-score merge is I4-full (Wave 4).
- **Safeguard:** flag `features.score_display_honesty.enabled`; with flag off the legacy headline is byte-identical. Shadow-log reconciled vs displayed for a week. Show class + a number that cannot contradict the class (never a STRONG with a sub-65 number).

### Wave 2

**I1 — sign the YouTube boost** (`config/consensus.yaml:744-748` flags; logic already at `cross_reference.py:383-413`, byte-identical when off; level-confluence path at :502-520 already present)
- Purpose: **verified wrong-sign bug** — a bearish YouTube consensus RAISES a long score (unsigned `youtube.score_boost` at :493).
- Input: `YouTubeContext` (consensus_dir, per-mention extracted_at, channel trust). Output: signed, decayed, trust-scaled `youtube_pts`.
- Logic: flip `direction_aware` + `recency_decay` + **`channel_reliability` (same change, do NOT defer)** ON.
- **Pass-3 safeguards (all mandatory):** min-2-trusted-channel floor before a bearish subtraction (below floor → 0 contribution, never a positive add); **channel-age & N≥10 graded-outcome requirement before a channel's trust counts**; **cap negative magnitude below positive** (bearish max −8 vs bullish +15); **null-timestamp → treated as stale** (down-weighted, never fresh; guard the divide); **add `features.youtube_score.*` to the conftest force-off fixture** (§5). Shadow-log signed vs unsigned `youtube_pts` for a week.

**I2 — weight analysts by `rolling_accuracy`** (`cross_reference.py:483`; reads `db.get_analyst_precision` :1077, which today floors at sample_count<5 → None)
- Purpose: the single largest non-boost term (`analyst_pts`, cap +60) is track-record-blind (flat ×20).
- Input: per-contributing-analyst rolling_accuracy + sample_count. Output: `analyst_pts = sum(20 × clamp(weight, 0.5, 1.5))`.
- Logic: replace flat `min(len, 3) × 20` with a per-analyst sum weighted by accuracy.
- **Pass-3 safeguards:** **Wilson lower-bound, not raw ratio** (kills the n=5 coin-flip swing) — this is a **genuinely new helper** `get_analyst_precision_lb(analyst, horizon, min_n=10)` (verified: no Wilson math and no `get_analyst_precision_lb` exists today; `db.py:1077` `get_analyst_precision` returns the raw `rolling_accuracy` and floors at `sample_count < 5`); **n≥10 sample floor** (raise from the documented 5; below floor → neutral 20); **0.5 discount floor, never 0**; **base-rate / per-call notional cap** vs accuracy-farming. Flag `features.analyst_accuracy_weight.enabled`; mock `rolling_accuracy` in the dedicated test so general scoring tests keep the flat-+20 baseline.
- **Recovery claim DROPPED (verified):** the "a down-weighted analyst is still graded and can recover" claim is **removed**. There is no writer to `source_performance` anywhere in the engine, and the only outcome-grading paths key on **alerted** artifacts (`update_snapshot_outcomes` → `decision_snapshots` linked by `alert_id`; `record_call_outcome` is Wolf-only on `wolf_call_outcomes`). UN-alerted signals are not graded into `source_performance`, so a down-weighted analyst cannot self-recover through this mechanism. The weight is a one-directional read of whatever `rolling_accuracy` already exists; building the un-alerted grading pipeline is out of scope for this run and noted here as a known limitation, not a quiet assumption.

**I5 — graduate SEC by role + open-market $** (`cross_reference.py:236` `_run_sec_check` + :485 `sec_pts`; reads `sec_edgar.py:253-332` role/dollars/tx_code; reuse `_MIN_PURCHASE_DOLLARS` from `sec_form4_cluster.py`)
- Purpose: a $10M CEO buy and a routine director award both score flat +15.
- Input: parsed max open-market BUY dollars + reporter role from `classify_filing_significance`. Output: graduated `sec_pts`.
- Logic: +8 any Form-4, +15 >$250k open-market buy, +20 C-suite buy.
- **Pass-3 safeguards:** **when the 10b5-1/plan flag is ABSENT → cap at +8** (no +20 tier, no negative branch — neutralizes the plan-trade false signal AND the false-bear); **net-selling withholds the buy credit but NEVER subtracts** (no bearish drag on the additive sum — a real bearish insider signal stays in the dedicated SEC path); **canonicalize role strings** (CEO/CFO/COO/President/PEO/PFO synonym map; unknown title → +8 baseline, never +20); **recency gate on the TRANSACTION date** (stale already-priced buy doesn't inflate a fresh alert). Keep `_run_sec_check`'s boolean as a compatibility return field; add dollars/role as new fields. Flag `features.sec_graduated_scoring.enabled`.

**I6 — scale options by premium, same-direction confluence ONLY** (`cross_reference.py:491` `options_pts`; reads `OptionsResult` :317 + the #18 flow watcher premium in `options.py:171-352`; E4 narrator constraint touches `narrator.py`)
- Purpose: a $5M sweep and a 3×-OI far-dated contract add the same +10; a put-wall on a long adds points.
- Input: premium notional + vol/OI ratio aligned with the tweet direction. Output: graduated, same-direction-only `options_pts` carrying an intraday/1–2-day horizon attribute.
- Logic: +6 unusual, +10 for >$250k single-strike premium ALIGNED with the tweet direction.
- **Pass-3 safeguards (E4 enforcement is mandatory):** **DROP the opposing/negative branch entirely** — public single-leg side inference is the refuted Pan-Poteshman fallacy; when side is ambiguous contribute 0, never a sign; **magnitude-cap the term low** (confluence nudge, never a driver, never solo-STRONG); **staleness gate** (reuse the #18 watcher's `max_staleness_min`; after-hours prior-session snapshots → 0); **narrator forbidden from "smart money" framing** for public flow — add a **regression assertion that the intraday/1–2-day horizon attribute is present** on the contribution. Add premium/side as new `OptionsResult` fields with defaults. Flag `features.options_graduated_scoring.enabled`.

### Wave 3

**I3 — live `contradiction_index` PRODUCER only** (set `contradiction_index` on the `ScoreTickerResult` returned by `cross_reference.score_ticker` at :579 — the only missing piece)
- **Consumer is already LIVE and tested (verified — do NOT rebuild it):** `engine._classify` (:228-277) already takes `contradiction_index`, computes a verdict via `evaluate_contradiction`, and fires the penalty (`if contradiction_verdict.apply_penalty: return SignalClass.WATCHLIST` at :267-268). Separately, `main.py:1276-1290` has a live "A1 post-process" that re-reads the real `xref.contradiction_index` and does the STRONG→WATCHLIST downgrade when `real_ci > 0.0`. The penalty path therefore **already runs the moment a non-zero index exists** — there is no dead consumer and nothing "lights up automatically" to wire.
- Purpose: Gap #1 — the index is always the `models.py:293` default 0.0, so the live penalty above never has a non-zero value to act on. This item supplies the value; it touches the PRODUCER only.
- **Scope of the new flag:** because the penalty fires whenever `contradiction_index > 0`, gate the *producer's writing of a non-zero value* behind `features.contradiction_index_live.enabled` (flag off → producer leaves the index at 0.0 → consumer is a verbatim no-op → existing tests unchanged). The flag exists to keep the producer dark during the shadow window, NOT to enable an already-live consumer.
- Input: each contributing source's signed direction (analyst/tweet, signed YT consensus_dir from I1, options dominant side from I6, SEC buy/sell from I5), weighted by points contributed, each tagged with its data-as-of timestamp. Output: `contradiction_index ∈ [0,1]` set on `ScoreTickerResult` before return at :579.
- Logic: `index = min(opposing_weight, supporting_weight) / total_weight` over **signed** sources only.
- **Pass-3 safeguards:** **count opposing sources by INDEPENDENT-ACTOR identity** (one actor appearing across twitter+options = one source); **require ≥2 distinct actors** before the ≥0.5 downgrade can fire (defeats single-injected-source denial-of-signal); **downgrade-not-veto, floored** (caps tier at WATCHLIST, never kills the alert — vocal-bear asymmetric setups are surfaced-with-caution); **abs-magnitude math, clamp [0,1], NaN/empty → 0**; **common-recency-window** (§3) — a stale leg does not count; **enforce I5+I6 dependency** — until I6 lands options contributes no sign, until I5 lands SEC contributes no sign; if <2 signed sources, index = 0 (no fabricated split). Flag `features.contradiction_index_live.enabled` (with flag off, index stays 0.0; existing tests unchanged). Add a dedicated test for the ≥0.5 downgrade branch (currently untested). Shadow-log the index for a week before it gates.

**I10 — require a hard-evidence component for STRONG** (`engine.py:261-269` `_classify`)
- Purpose: analysts(60)+social(35)+trends(5) overshoot 80 with zero hard catalyst on an uncalibrated sum.
- Input: ScoreBreakdown components (news_catalyst, sec_filing, technical, options_flow) + analyst track record (I2) + per-source skipped-for-budget flag. Output: STRONG vs capped-at-WATCHLIST.
- Logic: STRONG requires `score ≥ high AND (news_catalyst>0 OR sec_filing>0 OR technical≥2-filters OR options_flow>0)`.
- **Pass-3 safeguards:** **carve out the "before-mainstream" path on analyst TRACK RECORD (I2 Wilson-LB), NOT base_score≥30** — a single very-high-track-record analyst tweet counts as hard evidence so a genuine early call is not demoted; **distinguish absent vs unfetched** (do NOT demote when a confirming fetch was skipped for budget — only demote when the fetch ran and returned nothing); **technical must be ≥2 filters** to count (one RVOL fire is too porous). Flag `features.strong_requires_hard_evidence.enabled`. Shadow-log which STRONGs *would* demote for a week before gating.

**E6 — manufactured-agreement / coordinated-burst gate** (ingest path + `cross_reference.py`; reconcile with I3 in one pass)
- Purpose: catch *manufactured agreement* (distinct from I3's *disagreement*) without suppressing real breaking news.
- Input: account-diversity / near-simultaneous timing / templated wording across the source set; price corroboration. Output: a corroboration requirement on the crowd-agreement bonus (NOT a suppression of the signal).
- Logic: a detected near-duplicate burst does NOT down-weight the underlying signal; it **requires an independent non-burst source before the burst can add confluence points.**
- **Pass-3 safeguards:** **gate on ACCOUNT-DIVERSITY/coordination** (distinct origins, near-simultaneous timing, templated wording, no price corroboration), **NEVER suppress the underlying signal** — ingest stays "N posts → N signals"; **reconcile with I3 in one pass** (corroboration-before-contradiction precedence). Lands AFTER I3. Flag `features.manufactured_agreement_gate.enabled`.

**I13 — ApeWisdom mention-count z-score gate** (PRODUCER: `scanners/social.py:178-217` `scan_apewisdom` — persist the numeric `mentions` parsed at :198 into a new DB series; today it survives only inside the display strings at :205-206 and is dropped, `TickerSignal` carries no numeric mentions field. SCORER: `cross_reference.py:97` `_compute_social_breakdown` — the `social_apewisdom` term, which currently adds the flat `m.get("social_apewisdom", 10)` on mere presence `social_data.get("apewisdom",0) >= 1`. 30-day baseline read in `db.py`)
- **Anchor correction (verified):** `cross_reference.py:601` is `_build_social_summary`, a human-readable DISPLAY-string builder, NOT the scorer — editing it would change embed text, not the score. The score is set in `_compute_social_breakdown` (:97), called at :487 (`social_breakdown = _compute_social_breakdown(social_data)`). Point the z-gate at :97.
- Purpose: a ticker with 2 mentions and one with 2000 score identically (+10 on presence).
- Input: persisted mention count (from the new series) + 24h delta + ticker's own ≥14-day baseline. Output: +10 only on a corroborated z-surge.
- Logic: in `_compute_social_breakdown`, replace the presence-only `social_apewisdom` add with `+10` only when mentions are >2σ above the ticker's own baseline AND corroborated. This requires `social_data` (or a new sibling arg) to carry the numeric mention count and baseline, not just the boolean presence it carries today.
- **Pass-3 safeguards:** **confirm-only** — z-surge adds points ONLY when an **ACTOR-independent, preferably hard/non-manipulable** source (SEC/earnings/technical) already agrees on direction (a pure Reddit spike earns 0 — this is the pump-vector mitigation); **≥14-day baseline** before any z-credit (below that → 0, NOT the old presence +10 — closes the infinite-σ new-ticker degeneracy); **cap the term low**; **common-recency-window** (§3); **db tripwire** — new numeric column requires migrate + backfill the 30-day baseline + keep the term **flag-OFF returning 0 until backfill completes** (§4, §7). Flag `features.apewisdom_zscore.enabled`.

**I15 — recency + size weighting in Wolf confluence** (`wolf_confluence.py:146-163` `net_vote` + `score_confluence` :200-253; feeds the critical-tier @-ping `enable_critical_ping`)
- Purpose: a 20-day-old tweet and a fresh $5M sweep vote equally; this feeds a critical-tier user @-ping.
- Input: per-source rows with age + size (SEC insider $, options premium, YT n_channels) + actor identity. Output: age-decayed, size-scaled, capped votes; tiered result.
- Logic: replace each binary one-vote with an age-decayed, percentile-capped, size-scaled vote.
- **Pass-3 safeguards:** **critical @-ping "independent source" defined by ACTOR identity**; **require ≥1 non-actor-controllable source before size-weighting can escalate to critical** (no single manipulable public options print solo-pushes a user @-ping); **per-source percentile cap** (normalize every source to bounded 0–1, so a $5M sweep can't dominate n_channels); **reuse I5's 10b5-1 exclusion for the SEC-bear vote**; **age-decay-with-floor** (stale decays toward, not to, zero); **common-recency-window** (§3). Lands AFTER I5. Wolf confluence flags already force-off in conftest; the dedicated test forces them on.

### Wave 4

**I4-full — single-score reconciliation** (`main.py:1255-1293` + `engine.analyze_signal`)
- Purpose: collapse the two divorced scores into one coherent gated number. Lands AFTER I1/I2/I5/I6/I7 so the reconciled number reflects corrected components.
- Logic: feed the xref ScoreBreakdown components into `engine.analyze_signal` as features → one number rendered in both headline and decision. Minimal fallback path: `final = min(xref_total, precision_total)` but **avoid the bare min()** — when precision is budget-depressed, fall back to the xref total for display (closes the hollow-precision-cliff and the "STRONG, 58" contradiction). Flag `features.single_score.enabled`.

**I7 — scale `consensus_boost` by Bayesian log-odds** (`consolidation.py:142-163`; `combined_log_odds` already computed at :151, the boost is `int(effective_n × pts_per_cluster)` at :163)
- Purpose: the largest scoring term (cap 60) is the least calibrated. Lands AFTER I2.
- Logic: scale a portion of the boost by a sigmoid of `combined_log_odds`, retaining a count-based floor.
- **Pass-3 safeguards:** **reuse I2's hardened accuracy primitive** (Wilson LB, n≥10, 0.5 floor) for the priors — do NOT re-implement raw accuracy; **preserve the cold-start-zero contract verbatim** (the existing `consensus_boost=0` cold-start path at :101-121 stays — sigmoid applies only once real priors exist); **blend with a low count-floor** (saturation can't erase independent-cluster info). I7↔I8 de-correlation is MOOT (I8 dropped). Flag `features.consensus_logodds.enabled`; cold-start-zero tests pass unchanged.

**I14-widening — graduated panic STRONG-cutoff widening** (real mechanism, verified: the widening is `regime.threshold_shift`, NOT a hardcoded +10. `engine.py:249` reads `high = high + regime.threshold_shift`. That `threshold_shift` is populated in `analysis/regime.py` from a label→shift config map at :68-71 — `shifts = cfg.get("features.regime_classifier.regime_shifts", {"calm": -5, "elevated": 5, "panic": 10})` then `shift = shifts.get(label, 0)`. The `panic` label itself is assigned at `analysis/regime.py:138-143` when `z_smooth >= panic_z` (panic_z read at :135). There is no "flat +10" at engine.py:248-249 — the +10 is the *default panic entry* in that config map.)
- Logic: replace the static `shifts.get(label, 0)` lookup with a z-scaled formula **inside `analysis/regime.py`** (preferred — `engine.py` only reads `threshold_shift`, so keeping the math in regime.py means no engine.py change and the cap lives in one place). When `label == "panic"`, compute the shift as a function of how far `z_smooth` exceeds `panic_z` (e.g. `base_panic_shift + slope * (z_smooth - panic_z)`), instead of the flat `regime_shifts["panic"]`. Non-panic labels keep their static map values.
- **Pass-3 safeguards:** **cap the widening** (max +15, hard cutoff ceiling ~90 — never disable STRONG; clamp the z-scaled term in regime.py before returning `threshold_shift`); **exempt high-conviction longs from the extra widening** (the `bypass_market_confirmation` / high-conviction callers already known to `_classify`); **reconcile with E2 into ONE bounded cutoff adjustment** (don't stack two widenings — E2's cutoff annotation and this z-scaled shift fold into a single bounded number). Flag `features.regime_widening_graduated.enabled` (off → regime.py returns the existing static `shifts.get(label,0)`, behavior byte-identical).

**E2 — cross-asset regime confirm/veto multiplier** [NEW `analysis/cross_asset.py`] (feeds `regime_classifier`/`engine.py`)
- Purpose: VIX-term + HY-credit are HIGH-tier cited; a confirm/veto multiplier on already-triggered *bullish* alerts. NOT a new alert generator.
- Input: VIX/VIX3M term structure (yfinance `^VIX`/`^VIX3M`, verified path); optional HY-credit (HYG/LQD) + DXY behind its own flag. Output: a bounded confidence multiplier / cutoff annotation.
- **Pass-3 safeguards:** **use as a regime FLAG, not a directional predictor** (avoids the verified VIX-backwardation wrong-sign trap — backwardation often precedes a bounce); **symmetric caps** (veto ≥0.85 floor AND confirm ≤1.15 ceiling); **VIX-term leg (yfinance) shadow-first**; **FRED/HY-credit leg behind its OWN flag pending FRED-access verification** (never ship a dead data path — re-verify FRED before building that leg; hard-coded series IDs; FRED key via header not query-param); **common-recency-window** (§3); reconcile with I14-widening (one adjustment). Flags `features.cross_asset.enabled` + `features.cross_asset.fred_leg_enabled`.

**E1 — FINRA daily short-VOLUME confluence input** [NEW `scanners/finra_short_volume.py` + new db series] (small cross-reference confluence term)
- Purpose: a genuinely-absent free stream (short *volume* flow, distinct from the short *interest* snapshot already pulled).
- Input: daily FINRA consolidated short-volume file → short-%-of-total (net out `ShortExemptVolume`) + 30-day z-score per ticker, tagged with FINRA publication time. Output: a small confluence-only term.
- **Pass-3 safeguards:** **confluence-only, never standalone, never rendered as "directional short selling"** (fixed provenance label: **"short-volume %, MM-hedging-inflated proxy"** — a hard render rule); **net out `ShortExemptVolume`**; **EOD-staleness tag + common-recency-window** (§3) — never fed into a per-tweet score as if fresh; **db tripwire** (migrate + backfill + flag-OFF returning 0 until backfilled); **response-size cap + `allow_redirects=False` + domain re-validation + dtype-pinned parse** (the medium security items). Flag `features.finra_short_volume.enabled`.

### DEFER (documented, NOT built this run)

**I18 — reliability render block** (`discord.py:402-424` — the dead `if xref.reliability_decision:` block; would set `reliability_decision`/`reliability_weights`/drivers in `cross_reference.py`). DEFER until **I3 + I4 ship hardened AND pass an adversarial-input shadow window** (not just outcome-accuracy). A wrong authoritative verdict block is worse than a blank one. When revived: timestamp hygiene (UTC normalize; null `extracted_at` → "freshness unknown" never "0m fresh"); drivers by absolute magnitude, sign-labeled (e.g. "YouTube −8 (bearish)"); conservative verdict mapping (CAUTION on any non-trivial contradiction or stale top driver; CONFIRM only when agree+fresh+not-budget-depressed).

---

## 3. Data Flow Pipeline

New/changed components in **bold**.

```
Analyst tweet (TweetShift) → process_tweet (main.py:1094)
  → cheap gate (main.py:1066)  ── I9: read alerts.min_base_score_for_alert; shadow-log would_suppress_at_25/30
  → INSTANT ping (main.py:1178)        [unchanged — signal-first preserved]
  → spawn Phase-2 (main.py:1198)
       ├─ cross_reference.score_ticker (cross_reference.py:451) — parallel gather (:468-477)
       │     analyst_pts (:483)   ── I2: Wilson-LB accuracy weight
       │     news_pts (:484)      ── I12: +5/10% earnings surprise, cap +15
       │     sec_pts (:485)       ── I5: graduated by role/$ (via _run_sec_check :236)
       │     options_pts (:491)   ── I6: same-direction premium scale, no negative branch
       │     youtube_pts (:493)   ── I1: signed/decayed/trust-scaled (flags :744-748)
       │     social_apewisdom term (_compute_social_breakdown :97, called :487) ── I13: z-score gate, confirm-only (new db series; producer scan_apewisdom :198 persists numeric count)
       │     consensus_boost (:553) ── I7: sigmoid(log_odds) scale (consolidation.py:163)
       │     ┌─────────────────── COMMON-RECENCY-WINDOW SYNCHRONIZER ───────────────────┐
       │     │ NEW shared helper (analysis/recency_window.py): every multi-source compute │
       │     │ (I3, I13, I15, E1, E2) tags each leg with its data-as-of timestamp and     │
       │     │ drops/down-weights any leg older than that source's freshness cap. No leg   │
       │     │ from a different time base counts toward confluence/contradiction unless    │
       │     │ inside the common window. Generalizes per-source freshness_max_age to the   │
       │     │ cross-source layer. Prevents pairing a 12h-old short-volume spike with a    │
       │     │ 1-min-old SEC buy → "phantom confluence" for a move that already happened.  │
       │     └────────────────────────────────────────────────────────────────────────────┘
       │     contradiction_index (PRODUCER only — set on ScoreTickerResult before return :579) ── I3: actor-counted, recency-windowed
       │       (consumer already LIVE: engine._classify penalty :267-268 + main.py A1 post-process :1276-1290)
       │     E6: manufactured-agreement corroboration applied BEFORE I3 contradiction (one pass)
       │
       ├─ engine.analyze_signal → _classify (engine.py:228-277)
       │     I10: STRONG requires a hard-evidence component (+ I2-track-record carve-out)
       │     I14-widening: graduated panic shift (reconciled w/ E2 into ONE adjustment)
       │     E2: cross-asset multiplier (VIX-term leg; FRED leg own flag)
       │
       └─ render (main.py:1255-1293 + discord.py)
             I4-display-honesty: show precision-gated number; "confidence degraded: budget" state
             I4-full (Wave 4): single coherent score in headline + decision
             I14-display: regime risk-context line ("warming up" on cold-start)
             [DEFERRED I18: reliability verdict/freshness/drivers block discord.py:402-424]

Wolf #news brain (read-only on live tables; isolated):
  wolf_confluence.score_confluence (wolf_confluence.py:200) ── I15: age/size/actor-weighted votes
        (common-recency-window applied) → critical-tier @-ping (≥1 non-actor-controllable source)
  wolf_outcomes.compute_outcomes (wolf_outcomes.py:91) ── I16: benchmark-adjusted state (raw + adjusted)
```

---

## 4. Data Structures

### New / changed DB columns (db.py tripwire: migrate + backfill + flag-OFF-until-backfilled)

- **I13 — ApeWisdom count series.** New numeric column(s) so the count is queryable. Verified: the numeric `mentions` is parsed at `scanners/social.py:198` but only re-embedded in the `source_detail`/`raw_text` strings at :205-206 and then dropped — `TickerSignal` carries no numeric mentions field, so nothing persists the count today. Concretely: persist a per-ticker `apewisdom_mentions` time series (ticker, count, captured_at) from `scan_apewisdom`, supporting a 30-day baseline + 24h delta. **Tripwire:** migrate the new column/table, backfill ≥14–30 days of baseline, retest every reader of the affected tables, keep `features.apewisdom_zscore.enabled` OFF (term returns 0) until backfill completes.
- **E1 — FINRA short-volume series.** New per-ticker daily series: `(ticker, trade_date, total_volume, short_volume, short_exempt_volume, short_pct, z_score, finra_published_at)`. `short_pct` is computed net of `short_exempt_volume`. `finra_published_at` carries the EOD-staleness tag for the common-recency-window. **Tripwire:** migrate, backfill the 30-day baseline, keep `features.finra_short_volume.enabled` OFF (term returns 0) until backfill completes.

### Changed in-memory dataclasses (all new fields get defaults — keyword construction, no positional break)

- **`OptionsResult` (`models.py:317)`** — add I6 fields: `premium_notional: float = 0.0`, `dominant_side: str = ""`, `horizon: str = ""` (the intraday/1–2-day attribute the narrator regression asserts).
- **`ScoreTickerResult` / `CrossReferenceResult` (`models.py:276`)** — `contradiction_index` (:293), `reliability_decision` (:292), `reliability_weights` (:294) already exist; I3 populates `contradiction_index`. I18 (deferred) would populate the other two.
- **`_run_sec_check` return** — keep the `(bool, summary)` tuple as a compatibility field; add `max_buy_dollars: float`, `reporter_role: str`, `is_planned: bool` (10b5-1), `txn_date` as new return fields (I5).
- **No new ScoreBreakdown field is added** (I8, which needed one, is dropped). The youtube/consensus/social/sec/options/analyst terms already exist on `ScoreBreakdown` (:251).

### Per-source skipped-for-budget flag (I4-display-honesty / I10 prerequisite — build first)

A boolean per paid source indicating "fetch skipped for budget" (vs "fetched and empty"), surfaced on the precision dict so I4-display-honesty can render `confidence degraded: budget` and I10 can distinguish absent-vs-unfetched.

**Resolved (verified — this is BUILD-NEW, not read-existing):** `engine.BudgetManager` (:52-154) exposes only `consume` / `can_consume` / `pct_used` / `can_consume_gemini` — it records consumption but **does not track or expose which sources it skipped** on a given run. So the prerequisite is a new, small piece of state: when `consume`/`can_consume` returns False for a source on a run, record that source name in a per-run skipped-set, and surface that set on the precision result (e.g. `precision["skipped_sources"]`). This is a load-bearing prerequisite for I4-display-honesty (Wave 1/2) and I10 (Wave 3) — build it as the FIRST step of the I4-display-honesty task so both downstream items can read it. Scope: ~1 new set on the budget/precision result + populate-on-skip; no new schema.

---

## 5. Integration Plan — exact connection points

Every anchor below is re-verified against live source.

| Item | File · function · anchor | Change |
|---|---|---|
| I9 | `main.py:1066` (`_passes_quality_gate`-style gate) | replace literal 20 with `cfg.get("alerts.min_base_score_for_alert", 20)`; add would-suppress shadow log |
| I12 | scoring `cross_reference.py:484` (news_pts); FIRST add numeric `eps_surprise_pct`+`eps_estimate` to `CatalystResult` (`models.py:82-90`) and populate in `scanners/news.py:162-182` from the recap (number originates `scanners/earnings_calendar.py:168` `surprisePercent`) — today it's only a display string, not on the catalyst object | thread numeric field → magnitude bonus + floors + freshness gate |
| I16 | `wolf_outcomes.py:83-88` `_classify` + :144-146 compute | benchmark-adjusted state; new SPY/sector series via `_fetch_proxy_series` pattern |
| I14-display | `discord.py` Phase-2 embed builder ← `regime.py:24` `RegimeContext` | risk-context line |
| I4-display | `main.py:1269-1293` + `discord.py:447` headline + :395-399 precision field | show gated number; budget-degraded state |
| I1 | `config/consensus.yaml:745-747` flags; logic `cross_reference.py:383-413` + :502-520 | flip 3 flags ON; add min-channel floor + caps in the existing signed path |
| I2 | `cross_reference.py:483`; `db.py:1077` `get_analyst_precision` | per-analyst Wilson-LB weight; new/extended helper with `min_n=10` |
| I5 | `cross_reference.py:236` `_run_sec_check` + :485; `sec_edgar.py:253-332`; `sec_form4_cluster.py` `_MIN_PURCHASE_DOLLARS` | return role/$/plan-flag; graduate sec_pts |
| I6 | `cross_reference.py:491`; `options.py:171-352` flow premium; `models.py:317` `OptionsResult`; `narrator.py` (E4 framing ban) | graduate options_pts same-direction-only |
| I3 | PRODUCER only: set `contradiction_index` on `ScoreTickerResult` before return at `cross_reference.py:579`. Consumer already LIVE+tested: penalty `engine._classify:267-268`, post-process `main.py:1276-1290` | compute & set `contradiction_index`; do NOT touch the consumer |
| I10 | `engine.py:261-269` `_classify` | hard-evidence AND-clause + carve-out |
| E6 | ingest path (`scanners/discord_tweetshift.py:115` synthetic-id area) + `cross_reference.py` | account-diversity corroboration before I3 |
| I13 | PRODUCER `scanners/social.py:178-217` `scan_apewisdom` (persist numeric `mentions` parsed at :198 into new series; today dropped after :205-206 strings) + SCORER `cross_reference.py:97` `_compute_social_breakdown` (the `social_apewisdom` term, called :487) — NOT :601 (`_build_social_summary`, display only) + `db.py` baseline read | z-score gate, confirm-only |
| I15 | `wolf_confluence.py:146-163` `net_vote` + :200-253 `score_confluence` | age/size/actor-weighted votes |
| I4-full | `main.py:1255-1293` + `engine.analyze_signal` | single coherent score |
| I7 | `consolidation.py:163` (boost) using `:151` log_odds; cold-start path :101-121 | sigmoid-scale, preserve cold-start zero |
| I14-widening | `analysis/regime.py:68-71` (`regime_shifts` map → `threshold_shift`) — z-scale the `panic` branch using `panic_z` (:135) and the `z_smooth` label assign (:138-143), clamp before return; `engine.py:249` reads `threshold_shift` unchanged | graduated capped shift inside regime.py |
| E2 | NEW `analysis/cross_asset.py` → `engine.py` / `regime_classifier` | VIX-term leg; FRED leg own flag |
| E1 | NEW `scanners/finra_short_volume.py` + `db.py` series + `cross_reference.py` term | confluence-only, provenance-labeled |
| common-recency-window | NEW `analysis/recency_window.py`, called by I3/I13/I15/E1/E2 | per-leg data-as-of tag + freshness drop/down-weight |

### Config keys / flags to add — `config/consensus.yaml`

Add under the existing `features:` block (starts :691) unless noted. Every one defaults **false** (or value-neutral for I9):

```
alerts:
  min_base_score_for_alert: 20        # :363 — already present; I9 only adds the reader
features:
  earnings_magnitude: { enabled: false, per_10pct: 5, cap: 15, min_abs_eps: 0.02 }        # I12 — min_abs_eps shadow-derived (0.02 placeholder; tune from shadow window)
  regime_context_line: { enabled: false }                                                  # I14-display
  score_display_honesty: { enabled: false }                                                # I4-display
  youtube_score: { direction_aware: false, recency_decay: false, channel_reliability: false,  # I1 (flip in a sign-off, not this build)
                   min_trusted_channels: 2, min_channel_graded_n: 10, bearish_cap: 8 }
  analyst_accuracy_weight: { enabled: false, min_n: 10, discount_floor: 0.5, weight_cap: 1.5 } # I2
  sec_graduated_scoring: { enabled: false, csuite_pts: 20, large_buy_pts: 15, base_pts: 8, recency_days: 5 } # I5 — recency_days shadow-derived (5 placeholder; tune from shadow window)
  options_graduated_scoring: { enabled: false, aligned_pts: 10, unusual_pts: 6, horizon: "1-2d" }  # I6
  contradiction_index_live: { enabled: false, min_actors: 2, downgrade_threshold: 0.5 }    # I3
  strong_requires_hard_evidence: { enabled: false, min_technical_filters: 2 }              # I10
  manufactured_agreement_gate: { enabled: false }                                          # E6
  apewisdom_zscore: { enabled: false, min_baseline_days: 14, z_threshold: 2.0 }            # I13
  single_score: { enabled: false }                                                         # I4-full
  consensus_logodds: { enabled: false, count_floor_frac: 0.5 }                             # I7 — count_floor_frac shadow-derived (0.5 placeholder; tune from shadow window)
  regime_widening_graduated: { enabled: false, max_shift: 15, cutoff_ceiling: 90 }         # I14-widening
  cross_asset: { enabled: false, fred_leg_enabled: false, veto_floor: 0.85, confirm_ceiling: 1.15 } # E2
  finra_short_volume: { enabled: false }                                                   # E1
  recency_window: { enabled: true, max_age_min: { sec: 120, tweet: 120, options: 90, youtube: 1440, apewisdom: 1440, finra_short_volume: 1440, vix: 1440 } } # cross-cutting helper — per-source freshness caps shadow-derived (placeholders; tune from shadow window)
wolf:
  outcomes: { benchmark_adjusted: false }                                                  # I16
  confluence: { ... weighted_votes_enabled: false, require_nonactor_for_critical: true }   # I15 (under existing wolf.confluence :870)
```

**Tuning note (shadow-window-derived, NOT build-time):** the four numeric values previously left as `<tune>` — `earnings_magnitude.min_abs_eps`, `sec_graduated_scoring.recency_days`, `consensus_logodds.count_floor_frac`, and every `recency_window.max_age_min.*` per-source cap — ship as the placeholder starting values shown above so the code is complete and tests run, but they are **NOT final**. Because every feature lands flag-OFF + shadow-first, the correct value for each is read off the shadow-log distribution during the shadow window before the sign-off gate flips the flag. The executor does not need to "finalize" these at build time; they are explicitly deferred to the shadow-tuning pass, and the placeholder is inert until the flag is on.

### conftest force-off entries — `tests/conftest.py` `_audit_flags_default_off._off` dict (:42-51)

Add every new user-visible flag so the regression baseline stays green (the documented flag-default-off pattern; dedicated feature tests force their own flag in-body and win):

```
"features.earnings_magnitude.enabled": False,
"features.regime_context_line.enabled": False,
"features.score_display_honesty.enabled": False,
"features.youtube_score.direction_aware": False,
"features.youtube_score.recency_decay": False,
"features.youtube_score.channel_reliability": False,
"features.youtube_score.level_confluence": False,
"features.analyst_accuracy_weight.enabled": False,
"features.sec_graduated_scoring.enabled": False,
"features.options_graduated_scoring.enabled": False,
"features.contradiction_index_live.enabled": False,
"features.strong_requires_hard_evidence.enabled": False,
"features.manufactured_agreement_gate.enabled": False,
"features.apewisdom_zscore.enabled": False,
"features.single_score.enabled": False,
"features.consensus_logodds.enabled": False,
"features.regime_widening_graduated.enabled": False,
"features.cross_asset.enabled": False,
"features.cross_asset.fred_leg_enabled": False,
"features.finra_short_volume.enabled": False,
"wolf.outcomes.benchmark_adjusted": False,
"wolf.confluence.weighted_votes_enabled": False,
```

(`youtube_score.level_confluence` is already shipped OFF in config; add it to the dict too so the I1 batch is coherent.)

### Shared-file tripwire (CLAUDE.md DoD — retest EVERY feature using these, not just the changed line)

- `cross_reference.py` — I1, I2, I3, I5, I6, I7(reads), I10(reads), I12, I13, E1. Heaviest contention; change in coherent wave batches, run full cross-reference + `!all` + alert path after each batch.
- `config.py` + `config/consensus.yaml` — every flag above; conftest force-off is the regression defense.
- `db.py` — I2 (accuracy read / new helper), I13 + E1 (new columns). Schema change = migrate + backfill + retest every reader.
- `narrator.py` — I6 (forbid "smart money" framing). Retest `!all` narration.
- `aggregator.py` — I6 (options ratios reach `!all`). Retest the full `!all` ~28-source gather.

---

## 6. Failure Handling (per-feature behavior on missing / delayed / conflicting / budget-day / cold-start)

- **I9:** missing knob → default 20 (today's behavior). Future raise → shadow-preview log shows the volume hit first.
- **I12:** missing/None `eps_surprise_pct` → base tier only (no bonus). Near-zero denominator → guard blocks the bonus. Stale recap → freshness gate skips the bonus.
- **I16:** SPY/sector series fetch fails → fall back to the raw (current) classification; recap always shows raw. Inverse scope → sign-aware.
- **I14-display:** regime cold-start (<30 `regime_daily` rows) → "warming up" label, no implied protection.
- **I4-display:** budget-depressed run → explicit `confidence degraded: budget` state; never silently shows the higher number.
- **I1:** missing `extracted_at` → treated as stale (down-weighted, never fresh). <2 trusted channels → 0 contribution, never a positive add. Bearish magnitude capped below positive.
- **I2:** sample_count <10 → neutral 20. Wilson-LB keeps thin records near neutral. Discount floored at 0.5; down-weighted analysts still graded (or recovery claim dropped if grading path absent).
- **I5:** plan-flag absent → cap +8 (no +20, no negative). Net selling → withholds buy credit, never subtracts. Unknown role → +8. Stale transaction date → recency gate skips graduation.
- **I6:** ambiguous side → 0 (never a sign). Stale/after-hours snapshot → 0. Term magnitude-capped low.
- **I3:** <2 signed sources or <2 distinct actors → index 0 / no downgrade. NaN/empty → 0. Stale leg → excluded by common-recency-window. Downgrade caps at WATCHLIST, never kills.
- **I10:** confirming fetch skipped for budget → NOT demoted (absent-vs-unfetched). High-track-record analyst tweet → counts as hard evidence.
- **E6:** real breaking-news burst → still alerts (signal-first), just no extra crowd-agreement credit until an independent non-burst source corroborates.
- **I13:** <14-day baseline → 0 (not the old +10). No corroborator → 0. Backfill incomplete → flag OFF, term 0.
- **I15:** stale signal → decays toward (not to) zero. <1 non-actor-controllable source → cannot escalate to critical @-ping. Incommensurable units → per-source percentile cap.
- **I4-full:** budget-depressed precision → display falls back to xref total (no hollow-cliff / "STRONG, 58").
- **I7:** cold-start (no priors) → `consensus_boost = 0` (verbatim existing path). Count-floor preserved against sigmoid saturation.
- **I14-widening:** extreme z → capped at +15 / ceiling ~90 (never disables STRONG). High-conviction longs exempt from extra widening.
- **E2:** VIX data unavailable → multiplier 1.0 (no-op). FRED leg unverified → stays behind its own flag (no dead data path). Multiplier symmetric-capped 0.85–1.15.
- **E1:** FINRA file missing/late → term 0 (EOD-stale, never fed as fresh). Backfill incomplete → flag OFF. Always confluence-only, never standalone, always provenance-labeled.

---

## 7. Feature Activation Plan

**CRITICAL house rule (explicit):** everything in this build **LANDS flag-OFF + shadow-first.** This build delivers code + tests + shadow wiring only. **LIVE activation (flipping any flag to true) is a SEPARATE user-sign-off gate and is NOT part of this build.** No flag in §5 flips to true in this run — including the I1 YouTube flags and the I9 knob (I9 ships value-neutral at 20).

How the running engine picks up an activation, once the user signs off (future, separate step):
1. Edit the flag to `true` in `config/consensus.yaml`. Service reads `config/consensus.yaml` at startup.
2. `sudo systemctl restart consensus-engine.service`.
3. **Ownership trap (memory):** if `config/consensus.yaml` or `.env` was edited as root, `chown openclaw:openclaw` + correct perms first, or the engine crash-loops invisibly from a root session.
4. Verify after restart (per CLAUDE.md DoD): `consensus-engine.service` + `openclaw-gateway.service` both `active`; no `GATEWAY drift` / LLM-health alert; `/root/.openclaw` symlink intact.

**db-tripwire activation order (I13, E1):** migrate → backfill the baseline → confirm backfill complete → only then is the flag eligible for the sign-off gate. The term returns 0 until backfill completes regardless of the flag.

---

## 8. Verification Checklist (Pass 5)

### Always-on (every wave, every restart — CLAUDE.md DoD)
- `consensus-engine.service` + `openclaw-gateway.service` both `active`.
- No `GATEWAY drift` alert (check `$DISCORD_BRIEFING_CHANNEL_ID`, not #chat) and no LLM-health failure alert.
- `/root/.openclaw` still resolves to `/home/openclaw/.openclaw`.
- Regression baseline: `make test-baseline` was empty at plan start — **run `make test-baseline` BEFORE any code to capture the true baseline.** No passing test may start failing (set matters, not count). Each scoring-term change is flag-gated AND its dependent term mocked in general tests; the new behavior is asserted only in a dedicated feature test that forces its own flag.

### 8.A — Phase-1 verification (Wave 1 + Wave 2) — THIS is the build-now Definition of Done
For **each** of I9, I12, I16, I14-display, I4-display-honesty, I1, I2, I5, I6:
1. **Flag-ON dedicated feature test** proving the new behavior (e.g. I1: a bearish YT consensus produces *negative* youtube_pts; I5: a >$250k C-suite open-market buy scores +20, a director award +8, a plan-coded buy +8 with no negative branch; I6: an aligned >$250k sweep scores +10 and an opposing put-wall scores 0 — never negative; I12: a +40% surprise adds +15 capped, a $0.01/$0.001 near-zero beat adds 0; I2: a 3/5 record stays neutral 20, a 30/40 high record lifts, a 5/40 chronic loser floors at 0.5×; I9: raising the knob to 25 in a test config suppresses a base-22 tweet; I16: an inverse-proxy call is sign-aware and shows raw + adjusted; I14-display: cold-start renders "warming up"; I4-display: a budget-depressed run renders "confidence degraded: budget" and never the higher number).
2. **Flag-OFF regression test** proving byte-identical legacy behavior (the conftest force-off keeps the general suite on baseline).
3. **Shadow-log evidence**: confirm the shadow line is emitted (I9 would-suppress-at-25/30; I1 signed-vs-unsigned youtube_pts; I2 weighted-vs-flat analyst_pts; I4 reconciled-vs-displayed).
4. **End-to-end**: at least one real Phase-2 run (or `!all`) on a live ticker with each flag toggled ON in a throwaway config, inspecting the actual embed output (judge output against the goal, not code against spec).
5. **Shared-file retest**: after the `cross_reference.py` Wave-2 batch, run the full cross-reference + `!all` + alert path; after I6, retest `!all` narration (no "smart money" framing) + the full ~28-source `!all` gather.
6. **Separate-verifier baseline diff** (NOT the author): re-run the full suite, diff `.test-baseline`, confirm zero new failures, confirm services active + symlink intact.

### 8.B — Phase-2 verification (Wave 3 + Wave 4) — same contract, plus:
- **Common-recency-window**: a dedicated test that a stale leg (older than its source freshness cap) does NOT count toward I3/I13/I15/E1/E2 confluence/contradiction (no "phantom confluence").
- **I3**: the ≥0.5 downgrade branch test (currently untested); a single injected opposing actor does NOT trigger the downgrade (needs ≥2 distinct actors); index clamps [0,1], NaN→0.
- **I10**: a crowd-only stack (analysts+social+trends ≥80, no catalyst) caps at WATCHLIST; a high-track-record early analyst still reaches STRONG; a budget-skipped confirming fetch does NOT demote.
- **I13 / E1**: db migration applied, baseline backfilled, term returns 0 until backfill complete; readers retested.
- **I15**: no single manipulable public-options print escalates to a critical @-ping (≥1 non-actor-controllable source required).
- **E6**: ingest stays "N posts → N signals" (no signals dropped); only the crowd-agreement credit changes; reconciled with I3 in one pass.
- **I4-full**: headline and decision show ONE coherent number; budget-depressed → display falls back to xref total (no "STRONG, 58").
- **I7**: cold-start `consensus_boost = 0` unchanged; sigmoid scaling only with real priors; reuses I2's hardened primitive.
- **E2**: VIX leg shadow-logs the multiplier for two weeks before any gate; FRED leg stays behind its own flag until FRED access is verified; reconciled with I14-widening into ONE adjustment.
- Separate-verifier baseline diff at the very end of Phase 2.
