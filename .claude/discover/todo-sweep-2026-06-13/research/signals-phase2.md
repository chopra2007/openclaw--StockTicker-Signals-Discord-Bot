# Signals Phase-2 (TODO #32) — backtest & flip-readiness sweep

**Date:** 2026-06-13
**Cluster:** signals-phase2 (the only item in TODO #32)
**Source spec:** `.claude/discover/signal-features-2026-06-09/final-plan.md` §2/§5/§6/§8.B
**Method:** Backtested every Phase-2 feature against the live `consensus.db` (read-only),
the systemd journal, and code-level synthetic probes — instead of waiting for the
14-30 day shadow windows.

---

## TL;DR — what is provable NOW

| Verdict | Features |
|---|---|
| **PROVEN ready to flip now** (backtest passes on real data) | **E1** (FINRA short-vol), **E2-VIX** (VIX-term leg), **I15** (weighted Wolf votes), **I3** (contradiction producer — math proven, low live-fire is correct behavior) |
| **Wired & inert — flip is harmless, no effect yet** | **I7** (log-odds), **I14-widening** (panic shift), **I10** (STRONG hard-evidence) |
| **Needs a DB-baseline wait (~11 more days)** | **I13** (ApeWisdom z-score) — backfill in progress, eligible ~2026-06-24 |
| **Unbuildable** | **E2-FRED leg** (no FRED key — config placeholder only, zero code) |
| **Already LIVE (Phase 1)** | **I1** (signed YouTube boost), **I9** (alert-floor knob, held at 0 by design) |

**The biggest finding:** the "shadow windows" the TODO assumed were accumulating data are
mostly **empty** — `[I3 shadow]`, `[I10 shadow]`, `[E2 shadow]`, `[I7 shadow]` lines = **0
across the entire journal since 2026-06-10**. The plan said they'd accumulate passively; they
don't, for structural reasons (below). So "wait for the shadow window" is NOT a valid path for
most of these. Backtesting is the only way to gate them — and it works for the ready ones.

---

## Per-feature table

| Feature | Bucket | Backtest-provable NOW? | Backtest result | Flip-ready? | Tuned placeholder |
|---|---|---|---|---|---|
| **I3** contradiction producer | 4 (off) | YES (synthetic + live) | Producer math correct: 2 opposing actors w/ +30 supp vs +25 opp → CI=0.455; single opposing actor → CI=0.333 but gated below ≥2-actor downgrade; balanced → 0.500; <2 signed legs → 0.0. Live: all 43 classifications since 6/10 had CI=0.00 (correct — <2 signed sources per ticker). Consumer LIVE (`evaluate_contradiction`+`apply_penalty`→WATCHLIST at engine.py:384). | **READY** (low blast radius: only acts when a real ≥2-actor contradiction exists, which is rare; caps at WATCHLIST, never kills) | none — `min_actors:2`, `downgrade_threshold:0.5` fine |
| **I10** STRONG hard-evidence | 4 (off) | PARTIAL | 0 `[I10 shadow]` lines since 6/10. Cause: shadow log keys off the **precision-engine `total_score`** in `_classify`, which capped at **56** in all 43 runs (all WATCHLIST) — below STRONG. Yet alert_history shows 714 alerts ≥75 (AMD 79, SMMT 75 on 6/12) via the **xref-total** path. The two score paths diverge — I10 instrumented the path that rarely reaches STRONG. | **NOT YET** — flip is harmless (no demotions will fire) but also proves nothing until I4-full unifies the scores OR I10 reads the xref path | `min_technical_filters:2` fine; `analyst_lb_threshold:0.65` fine |
| **I13** ApeWisdom z-score | 4 (off) | NO (data too thin) | `apewisdom_mentions`: 121,200 rows / 376 tickers, BUT span only **2026-06-10→06-12 = 3 distinct days**. 0 tickers have ≥14-day baseline (`min_baseline_days:14`). Term returns 0 until backfill completes. ApeWisdom API confirmed live (top: SPCX 728, SPY 258). | **NEEDS DATA — ~11 more days** (eligible ~2026-06-24). No public historical ApeWisdom backfill exists → must accumulate forward at ~1 day/day. | `z_threshold:2.0` fine (verify against distribution once baseline exists) |
| **I15** weighted Wolf votes | 4 (off) | YES (full live backtest) | 65 real theses scored weighted-OFF vs ON via the live gather. **2 tier changes, both DOWNWARD** (IGV bull critical→high), **0 upgrades to critical**. Demotions come from recency/size weighting, not lost sources (agree_count stays 3/3). Non-actor-for-critical guard intact. Primitives correct: decay 1h→0.996, 20d→0.20 (floor); size-norm caps $9231 options premium to 1.0 so it can't dominate. Live gather supplies `as_of`/`size`/`actor` per row (db.py:3701-3743). | **READY** (only ever demotes over-ranked theses; never manufactures a critical @-ping) | none — defaults fine |
| **I4-full** single score | 4 (off) | code-only | Wired (`main.py:1412-1425`, supersedes score_display_honesty when both ON). Resolves the I3/I10 dual-score divergence above. Not separately backtestable without flipping — it changes a display/decision number, not a producer. | **READY to flip** (low risk; falls back to xref total on budget-depressed runs per spec) | none |
| **I7** log-odds consensus_boost | 4 (off) | YES (proven inert) | Wired (`consolidation.py:180-193`). But `consolidated_events`: **all 1934 rows have effective_n_clusters=1, combined_log_odds=0.0, shadow_only=1**. The consolidation engine runs in its own shadow-only mode AND every event is single-cluster → sigmoid(0)=0.5 on a 0-boost base → nothing to scale. 0 `[I7 shadow]` lines. | **FLIP IS A NO-OP** today — harmless but pointless until consolidation exits shadow-only and multi-cluster events occur | `count_floor_frac:0.5` fine (untestable now) |
| **I14-widening** panic shift | 4 (off) | YES (proven inert) | Wired (`regime.py:36-62`, clamp present). But `regime_daily` is **EMPTY (0 rows)** → classifier permanently cold-starts → label never reaches "panic" → the z-scaled panic branch is never entered. Returns static `shifts.get(label,0)` regardless of flag. | **FLIP IS A NO-OP** today — needs `regime_daily` populated (252-day vol history) before panic can ever be assigned | `max_shift:15`, `cutoff_ceiling:90`, `slope:2.5` fine (untestable now) |
| **E1** FINRA short-volume | 4 (off) | YES (full z-backtest) | `finra_short_volume`: 4,740 rows / 314 tickers / **22 trading days (05-11→06-10)** — backfill COMPLETE (`min_baseline_days:20` met; 204 tickers qualify). z-distribution sane: min -3.19, median 0.09, max 3.85. **9 tickers (~4.4%) would fire today at z>2.0** (HD 3.85, ASTS 2.93, ABAT 2.85, AMAT, AVAV, GOOG, BRO, META, SF) — a sensible rate, not a flood. 13 near-misses (1.5<z≤2.0). Term +5 cap, long-only, confluence-only, daily timer keeps it fresh. | **READY** (backfill done, behaves correctly, capped & confluence-only) | none — `z_threshold:2.0`, `term_cap:5`, `min_baseline_days:20` fine |
| **E2-VIX** VIX-term multiplier | 4 (off) | YES (live fetch) | `_fetch_vix_ratio()` returns **live 0.862** (contango/calm) → multiplier **1.138** (mild confirm). Band correct & symmetric: ratio>1 (backwardation)→toward 0.85 veto, ratio<1→toward 1.15 confirm, clamped both ends. The "0.983 probe" in the note was a different market moment; leg is deterministic & functional. | **READY** (VIX leg works; flip turns on shadow logging too — see caveat) | `veto_floor:0.85`, `confirm_ceiling:1.15` fine |
| **E2-FRED** HY-credit leg | 1 (not built) | N/A | No FRED key exists. `cross_asset.py` header confirms: "There is NO code behind it here... config placeholder only." `fred_leg_enabled` flag has zero implementation. | **UNBUILDABLE** — leave `fred_leg_enabled:false` permanently until a FRED key is obtained | n/a |
| **E6** manufactured-agreement gate | 4 (off) | not separately tested | Built; reconciles with I3 in one pass. Lands after I3. Not backtested here (no coordinated-burst events in the sample to trigger it). | defer with I3 wave | n/a |
| **I1** signed YouTube boost (Phase 1) | LIVE | confirmed | Config shows the I1 keys live (`min_trusted_channels:2`, `min_channel_graded_n:10`, `bearish_cap:8`). Phase-1 block all `enabled:true`. | already on | n/a |
| **I9** alert-floor knob (Phase 1) | LIVE (held at 0) | confirmed | `min_base_score_for_alert: 0` with the comment "DIAL OFF (user 2026-06-09)". Connected but deliberately at 0 — **do NOT raise** (the conviction heuristic floors ~98% of real tentative analyst calls; raising deletes real signal). | leave at 0 | keep 0 |

---

## Recency-window synchronizer (cross-cutting prerequisite)

**Status: BUILT, LIVE, and actively used.** `consensus_engine/analysis/recency_window.py` exists
(`is_fresh`, `filter_fresh`, `SourceLeg` dataclass). Config: `recency_window: { enabled: true, ... }`.
The I3 producer already calls `filter_fresh` on its legs (proven in the code path). It is the one
piece of the Phase-2 stack that is genuinely on and working.

The per-source `max_age_min` caps are the placeholders the TODO flags for tuning:
`{ sec:120, tweet:120, options:90, youtube:1440, apewisdom:1440, finra_short_volume:1440, vix:1440 }`.
**These cannot be tuned from a shadow distribution because the shadow logs are empty.** They are
defensible as-is from first principles (tweets/SEC are minute-scale, FINRA/ApeWisdom/VIX are
daily/EOD = 1440 min). Note I15's Wolf-confluence path deliberately **bypasses** these minute-scale
caps and uses the 21-day window instead (a hard-won fix — the global caps deleted every Wolf vote in
the 2026-06-10 live test; see `wolf_confluence.py:341-358`). Leave the caps at defaults; revisit only
if a live false-drop appears.

---

## Why the shadow windows are empty (structural, not a bug to wait out)

- **I3** logs only when `computed_ci > 0` — requires ≥2 signed sources with opposing directions on
  one ticker. Real traffic rarely has options+SEC+YT+tweet all signed at once → CI=0 → no line.
  *Backtest, don't wait.*
- **I10** logs only when the **precision `total_score` ≥ STRONG cutoff** — but that score capped at 56
  in 43 runs. *Instrumented the wrong score path; waiting won't help until I4-full lands.*
- **E2 / I7** log only when their **own flag is ON** (cross_asset.py:566, consolidation.py:181). With
  the flag OFF, the fetch/scale code never runs → zero passive shadow data. *The "two weeks of shadow"
  the plan promised is impossible while flag-OFF.*

This means the documented "read the shadow distribution, then flip" plan is unworkable for I3/I10/E2/I7.
The replacement gate is the backtest evidence in this doc.

---

## Recommended activation order (with evidence)

**Tier 1 — flip now, backtest-proven, real effect:**
1. **E1 (FINRA short-volume)** — backfill complete (22 trading days, 204 tickers), z-score sane,
   9/204 fire today at a sensible 4.4% rate, +5 cap confluence-only. Lowest risk, clear value.
2. **I15 (weighted Wolf votes)** — live backtest on 65 theses: only demotes 2 over-ranked theses,
   0 spurious critical @-pings, guards intact. Touches only the Wolf #news brain (no per-ticker blast).
3. **E2-VIX** — VIX leg fetches live (ratio 0.862→mult 1.138), symmetric-capped 0.85-1.15, no-op on
   fetch failure. Flip the VIX leg; keep `fred_leg_enabled:false` forever (unbuildable). *Caveat: flip
   means you turn on the live multiplier and its shadow log simultaneously — there is no passive
   shadow-first option. Mitigation: the cap (0.85-1.15) bounds the worst case to ±15%.*
4. **I3 (contradiction producer)** — math proven correct, ≥2-actor gate defeats single-source denial,
   caps at WATCHLIST. Consumer already live, so flipping the producer flag activates the full path.
   Real contradictions are rare → small, surgical effect.

**Tier 2 — flip is harmless but does nothing yet (flip with Tier 1 for code-coherence, or hold):**
5. **I4-full (single score)** — flip alongside I3/I10 to unify the dual-score paths; this is what makes
   I10's shadow/demotion meaningful. Low risk (falls back to xref total on budget-depressed runs).
6. **I10 (STRONG hard-evidence)** — only useful after I4-full unifies scores (or after re-pointing its
   instrumentation at the xref path). Until then it never fires.
7. **I7 (log-odds)** — pure no-op until the consolidation engine leaves shadow-only mode AND
   multi-cluster events occur. Flip costs nothing; gains nothing today.
8. **I14-widening** — pure no-op until `regime_daily` is populated (needs 252-day vol history seeded).
   The empty `regime_daily` is a separate gap worth fixing independently.

**Tier 3 — wait for data:**
9. **I13 (ApeWisdom z-score)** — flip-eligible ~**2026-06-24** (needs ~11 more days for ≥14-day
   baselines). No historical backfill source exists; must accumulate forward. Re-run the z-distribution
   check then before flipping.

**Never:**
- **E2-FRED leg** — `fred_leg_enabled` stays false; no key, no code.
- **I9 raise** — `min_base_score_for_alert` stays 0 (raising deletes the 98% real tentative-analyst signal).

---

## Independent gaps surfaced (not Phase-2 features, but block Phase-2 value)

1. **`regime_daily` is empty (0 rows).** The regime classifier permanently cold-starts. This silently
   neuters I14-widening AND the regime-context line (I14-display, which IS live but always shows
   "warming up"/normal). Worth a separate seed task (compute 252-day realized-vol history).
2. **Consolidation engine is in shadow-only mode** (all 1934 events `shadow_only=1`, `consensus_boost=0`).
   This neuters I7. Whether that's intended is worth confirming with the user.
3. **Dual-score divergence** (precision `total_score` ~56 max vs xref/alert scores ≥75): I10's shadow
   log watches the path that rarely reaches STRONG. I4-full is the intended fix.
