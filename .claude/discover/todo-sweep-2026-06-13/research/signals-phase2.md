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
| **Flip now** (lowest blast radius, after the alert-replay harness — see order below) | **E1** (FINRA short-vol), **I15** (weighted Wolf votes) |
| **HOLD until after I4-full + offline replay, then flip ONE AT A TIME** | **I3** (contradiction producer), **I10** (STRONG hard-evidence), **E2-VIX** (VIX-term leg — turns on a live ±15% scoring multiplier with no shadow-first mode; NOT a flip-now item per the codex pass) |
| **Wired & inert — flip only when it can act (NOT for "code-coherence")** | **I7** (log-odds), **I14-widening** (panic shift) |
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
| **I3** contradiction producer | 4 (off) | YES (synthetic + live) | Producer math correct: 2 opposing actors w/ +30 supp vs +25 opp → CI=0.455; single opposing actor → CI=0.333 but gated below ≥2-actor downgrade; balanced → 0.500; <2 signed legs → 0.0. Live: all 43 classifications since 6/10 had CI=0.00 (correct — <2 signed sources per ticker). Consumer LIVE (`evaluate_contradiction`+`apply_penalty`→WATCHLIST at engine.py:384). | **HOLD until after I4-full + offline replay** (math is fine, but flip it alone and watch — not bundled with Tier-1) | none — `min_actors:2`, `downgrade_threshold:0.5` fine |
| **I10** STRONG hard-evidence | 4 (off) | PARTIAL | 0 `[I10 shadow]` lines since 6/10. Cause: shadow log keys off the **precision-engine `total_score`** in `_classify`, which capped at **56** in all 43 runs (all WATCHLIST) — below STRONG. Yet alert_history shows 714 alerts ≥75 (AMD 79, SMMT 75 on 6/12) via the **xref-total** path. The two score paths diverge — I10 instrumented the path that rarely reaches STRONG. | **NOT YET** — flip is harmless (no demotions will fire) but also proves nothing until I4-full unifies the scores OR I10 reads the xref path | `min_technical_filters:2` fine; `analyst_lb_threshold:0.65` fine |
| **I13** ApeWisdom z-score | 4 (off) | NO (data too thin) | `apewisdom_mentions`: 121,200 rows / 376 tickers, BUT span only **2026-06-10→06-12 = 3 distinct days**. 0 tickers have ≥14-day baseline (`min_baseline_days:14`). Term returns 0 until backfill completes. ApeWisdom API confirmed live (top: SPCX 728, SPY 258). | **NEEDS DATA — ~11 more days** (eligible ~2026-06-24). No public historical ApeWisdom backfill exists → must accumulate forward at ~1 day/day. | `z_threshold:2.0` fine (verify against distribution once baseline exists) |
| **I15** weighted Wolf votes | 4 (off) | YES (full live backtest) | 65 real theses scored weighted-OFF vs ON via the live gather. **2 tier changes, both DOWNWARD** (IGV bull critical→high), **0 upgrades to critical**. Demotions come from recency/size weighting, not lost sources (agree_count stays 3/3). Non-actor-for-critical guard intact. Primitives correct: decay 1h→0.996, 20d→0.20 (floor); size-norm caps $9231 options premium to 1.0 so it can't dominate. Live gather supplies `as_of`/`size`/`actor` per row (db.py:3701-3743). | **READY** (only ever demotes over-ranked theses; never manufactures a critical @-ping) | none — defaults fine |
| **I4-full** single score | 4 (off) | code-only | Wired (`main.py:1412-1425`, supersedes score_display_honesty when both ON). Resolves the I3/I10 dual-score divergence above. Not separately backtestable without flipping — it changes a display/decision number, not a producer. | **READY to flip** (low risk; falls back to xref total on budget-depressed runs per spec) | none |
| **I7** log-odds consensus_boost | 4 (off) | YES (proven inert) | Wired (`consolidation.py:180-193`). But `consolidated_events`: **all 1934 rows have effective_n_clusters=1, combined_log_odds=0.0, shadow_only=1**. The consolidation engine runs in its own shadow-only mode AND every event is single-cluster → sigmoid(0)=0.5 on a 0-boost base → nothing to scale. 0 `[I7 shadow]` lines. | **FLIP IS A NO-OP** today — harmless but pointless until consolidation exits shadow-only and multi-cluster events occur | `count_floor_frac:0.5` fine (untestable now) |
| **I14-widening** panic shift | 4 (off) | YES (proven inert) | Wired (`regime.py:36-62`, clamp present). But `regime_daily` is **EMPTY (0 rows)** → classifier permanently cold-starts → label never reaches "panic" → the z-scaled panic branch is never entered. Returns static `shifts.get(label,0)` regardless of flag. | **FLIP IS A NO-OP** today — needs `regime_daily` populated (252-day vol history) before panic can ever be assigned | `max_shift:15`, `cutoff_ceiling:90`, `slope:2.5` fine (untestable now) |
| **E1** FINRA short-volume | 4 (off) | YES (full z-backtest) | `finra_short_volume`: 4,740 rows / 314 tickers / **22 trading days (05-11→06-10)** — backfill COMPLETE (`min_baseline_days:20` met; 204 tickers qualify). z-distribution sane: min -3.19, median 0.09, max 3.85. **9 tickers (~4.4%) would fire today at z>2.0** (HD 3.85, ASTS 2.93, ABAT 2.85, AMAT, AVAV, GOOG, BRO, META, SF) — a sensible rate, not a flood. 13 near-misses (1.5<z≤2.0). Term +5 cap, long-only, confluence-only, daily timer keeps it fresh. | **READY** (backfill done, behaves correctly, capped & confluence-only) | none — `z_threshold:2.0`, `term_cap:5`, `min_baseline_days:20` fine |
| **E2-VIX** VIX-term multiplier | 4 (off) | YES (live fetch) | `_fetch_vix_ratio()` returns **live 0.862** (contango/calm) → multiplier **1.138** (mild confirm). Band correct & symmetric: ratio>1 (backwardation)→toward 0.85 veto, ratio<1→toward 1.15 confirm, clamped both ends. The "0.983 probe" in the note was a different market moment; leg is deterministic & functional. | **DO NOT FLIP NOW** (codex: live ±15% multiplier + shadow log turn on together, no shadow-first; only 1 live point proven; ±15% can cross the ≥75 alert floor → live alert behavior, not harmless. Flip last, after I4-full + offline replay across calm AND backwardation regimes) | `veto_floor:0.85`, `confirm_ceiling:1.15` fine |
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

> **[codex revision 2026-06-13 — AUTHORITATIVE ORDER]** The Codex adversarial pass flagged a
> BLOCKER: an earlier version of this section listed **E2-VIX** and **I3** under "flip now",
> which CONTRADICTS the revised `final-plan.md` §3. The order below is now the single source of
> truth and matches final-plan. **E2-VIX and I3/I10 are NOT flip-now items** — see why inline.
> Two hard prerequisites Codex added, before ANY scoring flag is flipped in production:
>   1. **Build an offline alert-pipeline replay harness.** Every "ready" claim below (E1's "9/204
>      fire at 4.4%", I4-full's score change) proves *term/score* behavior, NOT *user-visible alert*
>      behavior. The replay must report: how many Discord alerts change tier, how many new @-pings
>      fire, which tickers get upgraded, with concrete before/after examples. Flip nothing until the
>      replay shows the alert delta.
>   2. **No "flip the inert ones for code-coherence" — ever.** I3/I10/I7/I14/E2-VIX must each be
>      flipped *individually, after* I4-full, each watched in isolation. If several are already ON
>      when I4-full unifies the scores, they all activate at once = an alert storm with no way to
>      isolate the culprit.

**Step 1 — flip now (lowest blast radius), but ONLY after the alert-replay harness confirms the delta:**
1. **E1 (FINRA short-volume)** — backfill complete (22 trading days, 204 tickers), z-score sane,
   9/204 fire today at a sensible 4.4% rate, +5 cap confluence-only. Lowest risk. **[codex revision]
   "9/204 fire" is the *term* fire rate, not the alert delta — run the replay first to confirm how
   many actual alerts cross thresholds after the +5.**
2. **I15 (weighted Wolf votes)** — live backtest on 65 theses: only demotes 2 over-ranked theses,
   0 spurious critical @-pings, guards intact. Touches only the Wolf #news brain (no per-ticker blast).
   Safe to flip first; no alert-tier interaction.

**Step 2 — build + ship I4-full (with replay), THEN re-evaluate I3/I10/E2-VIX one at a time:**
3. **I4-full (single score)** — unifies the dual-score paths; this is what makes I10's demotion
   meaningful and what I3/I10/E2-VIX assume. **[codex revision] I4-full changes the decision/display
   score — it is exactly the kind of change to SIMULATE OFFLINE first. The note "not separately
   backtestable without flipping" is not a license to flip blind: build the replay (old score vs new
   score vs alert tier vs user-visible text) and review the delta before flipping.** Falls back to
   xref total on budget-depressed runs.
4. **I3 (contradiction producer)** — math proven correct, ≥2-actor gate, caps at WATCHLIST. **HOLD
   until after I4-full.** Then flip alone and watch. Real contradictions are rare → small effect.
5. **I10 (STRONG hard-evidence)** — only meaningful after I4-full unifies scores. **HOLD until after
   I4-full**, then flip alone.
6. **E2-VIX** — **[codex revision] DO NOT FLIP NOW (downgraded from the old "flip now").** Reasons:
   (a) it turns on a LIVE scoring multiplier AND its shadow log *simultaneously* — there is no
   shadow-first mode, so the first time you see its effect is in production alerts; (b) only ONE live
   point is proven (ratio 0.862→mult 1.138) — no historical behavior, no per-alert threshold-crossing
   analysis, no fetch-failure-under-load test; (c) a ±15% multiplier turns a score of 66 into ~75.2
   (crosses the ≥75 alert floor) or 86 into ~73.1 (drops below it) — that IS live alert behavior, not
   harmless logging. **Correct path: flip E2-VIX last, after I4-full, after an offline replay across
   calm AND backwardation regimes shows the per-alert deltas. Better still, add a true shadow-only
   flag first.** Keep `fred_leg_enabled:false` forever (unbuildable).
7. **I7 (log-odds)** — pure no-op until the consolidation engine leaves shadow-only mode AND
   multi-cluster events occur. **Do not flip for "code-coherence"** — flip only when it can actually act.
8. **I14-widening** — pure no-op until `regime_daily` is populated (252-day vol history seeded).
   The empty `regime_daily` is a separate gap worth fixing independently. Flip only after it's populated.

**Step 3 — wait for data:**
9. **I13 (ApeWisdom z-score)** — flip-eligible ~**2026-06-24** (needs ~11 more days for ≥14-day
   baselines). No historical backfill source exists; must accumulate forward. Re-run the z-distribution
   check then before flipping.

**Never:**
- **E2-FRED leg** — `fred_leg_enabled` stays false; no key, no code.
- **I9 raise** — `min_base_score_for_alert` stays 0 (raising deletes the 98% real tentative-analyst signal).

---

## Plain-English answers to two user questions (2026-06-13)

**Why is there no ApeWisdom backfill data?** ApeWisdom's free API
(`https://apewisdom.io/api/v1.0/filter/all-stocks/page/N`, the call in `social.py:189`) is a **live
leaderboard, not an archive.** Each request returns *today's* trending tickers + their *current*
mention counts — there is no date parameter and no "give me the last 30 days" endpoint. The I13
feature needs a **14-day baseline per ticker** to compute "is today's mention count unusually high"
(a z-score). The only way to get those 14 days is to **save the snapshot once a day and accumulate
going forward** — the past isn't retrievable. We started recording ~3 days ago, so only 3 days exist,
and the missing 11 simply don't exist anywhere to backfill from. Eligible ~2026-06-24 once enough days
have piled up. (Contrast: FINRA short-volume DID backfill, because FINRA publishes a downloadable
historical file — ApeWisdom does not.)

**What key is "the one we don't have"?** A **FRED API key** — a *free* key from the U.S. Federal
Reserve's economic-data service (FRED, run by the St. Louis Fed). The E2-FRED leg would read
credit-market stress (high-yield bond spreads) to confirm or veto signals. We never signed up for the
key, and there is **zero code behind it** (`cross_asset.py` header: "There is NO code behind it
here… config placeholder only"). So it's not "broken" — it was never built, and building it needs us
to register for the free FRED key first. Leave `fred_leg_enabled:false` until/unless we get the key.

---

## Independent gaps surfaced (not Phase-2 features, but block Phase-2 value)

1. **`regime_daily` is empty (0 rows).** The regime classifier permanently cold-starts. This silently
   neuters I14-widening AND the regime-context line (I14-display, which IS live but always shows
   "warming up"/normal). Worth a separate seed task (compute 252-day realized-vol history).
2. **Consolidation engine is in shadow-only mode** (all 1934 events `shadow_only=1`, `consensus_boost=0`).
   This neuters I7. Whether that's intended is worth confirming with the user.
3. **Dual-score divergence** (precision `total_score` ~56 max vs xref/alert scores ≥75): I10's shadow
   log watches the path that rarely reaches STRONG. I4-full is the intended fix.
