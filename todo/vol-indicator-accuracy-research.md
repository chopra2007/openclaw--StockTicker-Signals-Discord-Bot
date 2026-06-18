# Build an accurate market top/bottom detector — research how others did it

**Status:** OPEN
**Created:** 2026-06-17

## Goal
Detect US equity-index (SPY/QQQ) **tops and bottoms early — before the move — with few false
alarms.** Flag an intermediate top ahead of a ≥8% drop (within ~60 trading days) and a bottom ahead
of a ≥8% rally, firing during the turning window. Must have a **real, out-of-sample-validated edge
with a low false-positive rate**, not an in-sample curve fit. Free/affordable public data preferred.

## Where this stands (2026-06-17)
The **daily-price/volume/breadth approach is exhausted and ruled out with statistical rigor.** Phase 1
(single signals) and Phase 2 (the multi-signal confluence + a continuous score + a two-stage model)
both came back **NO-GO**. Next phase is a **research mission** (prompt embedded below) to find how
others actually achieve this — almost certainly with richer data inputs we don't yet have.

## What we built (committed code — recoverable)
Repo: `volatility_regime_reversal_indicator/` (part of the main workspace git repo).
- **Phase 1** (commits bf61ed0/fd809dc/a8a8f93/26fc837): honest single-signal backtest harness —
  point-in-time features, next-open entry, episode collapsing, regime-matched null, BH-FDR + max-stat
  reality check, 5-gate kill-gate. Result: FAIL (no single signal has edge). Report:
  `backtest/ABLATION-REPORT.md`. Frozen contract: `backtest/preregistration.yaml`.
- **Phase 2** (commits df3515f + 58398d3, 2026-06-17): the CONFLUENCE the kickoff asked for, CCG-vetted.
  - `src/data/fetch_breadth.py` — free broad-US advance/decline feed (thetrading.tools, 4139 rows
    2010-26) → store series `ABINYSE` (a broad-US ABI PROXY, not NYSE-only; self-normalizing ratio).
    NOTE: `data/store/` is gitignored → re-fetch on a fresh clone; append-only restatement guard.
  - `src/features/utils.py::rolling_ols_residual` — beta-adjusted VVIX-vs-VIX residual (look-ahead-tested).
  - `src/signals/conditions_phase2.py` — 11 frozen constructions + continuous Distribution-Stress
    Index (DSI) + eligibility masks. (Raw VVIX/VIX-slope leg dropped as a search artifact.)
  - `src/backtest/phase2.py` + `src/run_phase2.py` — the confirmatory battery; report:
    `backtest/PHASE2-REPORT.md`. Frozen contract: `backtest/preregistration_phase2.yaml`.
  - Tests: `tests/test_lookahead_phase2.py`, `tests/test_preregistration_phase2.py`. 68 pass.
- Discover run working notes (GITIGNORED, local only): `.claude/discover/vol-indicator-accuracy/`
  (pass-0/3/5 artifacts, ground-truth-episodes.md, ccg-bundle.md, gemini-review.txt, RESEARCH-MISSION.md).

## What held up (INCONCLUSIVE — do NOT treat as validated; tests weren't conclusive)
- The **breadth-narrowing gate** (`concentration_regime = pct_change(RSP/SPY,60) < 0`) beat the bare
  stack at matched alert count (G5 pass, bootstrap diff p05 +0.026). The one component with a hint of
  real information. Untested forward.
- The **DSI is a robust CALM detector** (predicts LOWER forward volatility, rank-IC −0.23 SPY / −0.25
  QQQ, transfers across assets). That's a real relationship — but it's a *different* product (a
  complacency gauge), NOT a top predictor.

## What did NOT work, and why
Results (all from the actual confirmatory run, `backtest/PHASE2-REPORT.md`):
- Single signals: no edge (Phase-1 kill-gate FAIL).
- Binary confluence: best top precision +12pp but opportunity-set null p≈0.13 (not significant). The
  earlier "+13pp/p=0.03" was inflated by an artifact leg (raw VVIX/VIX slope) + a too-easy all-days null.
- **Cross-asset transfer to QQQ = NEGATIVE edge** → strongest sign the S&P result was overfit.
- **Continuous DSI → forward drawdown rank-IC = −0.09 across 3,815 days (p≈0.85)** → essentially zero
  WITH full statistical power, so "too few examples" is NOT the cause.
- Two-stage watch→break: +8–10pp on S&P but not significant and no QQQ transfer.
- Bottom detector's high precision was an artifact: once already 5%+ down, an 8% bounce within 60 days
  happens ~92% of the time anyway (the eligible base rate) → no real edge.
- VVIX/VIX (both slope and residual encodings) and the low-ABI breadth leg added no validated edge.

**Why (our hypotheses — the research mission must verify/refute):**
1. "Compression/churn near the highs precedes a top" is, in this data, mostly a **calm-market
   signature that precedes more calm**, not distribution before a drop. Genuine tops are too rare
   (~7–10 in 16 years) to separate from the many benign calm stretches.
2. The institutional-distribution fingerprint the thesis describes (smart-money tail-hedging, selling
   into strength) is likely **not visible in daily price/volume/breadth** — it needs richer inputs we
   don't have: **options positioning / dealer gamma, tick-level or true-exchange breadth, order flow.**
   We're measuring the phenomenon with too blunt an instrument.

## Cross-model review conclusions (Codex gpt-5.5 + Gemini)
Both said the original design was a NO-GO but the goal is **buildable if restructured** (NOT impossible):
- Codex: two-stage watch→trigger; price-break confirmation; dual breadth; credit as a soft score;
  opportunity-set null. (We built + tested these; they didn't clear the bar.)
- Gemini: continuous score instead of binary thresholds; cross-asset validation; credit momentum;
  liquidity-filtered breadth. (Built + tested the continuous score — failed with full power.)

## Next steps (priority-ordered)
1. **RUN THE RESEARCH MISSION (below).** Fact-find how others actually do this (data + method +
   out-of-sample evidence + false-alarm rates), propose a plan, adversarially review it. This is the
   user's chosen next move ("don't reinvent the wheel"). Prompt is self-contained — can be handed to
   any deep-research tool, or launched in a fresh session reading `.claude/discover/vol-indicator-
   accuracy/RESEARCH-MISSION.md` (also embedded below for git-recoverability).
2. After research: likely **acquire/forward-collect richer inputs** (options positioning / dealer
   gamma via CBOE delayed quotes; true NYSE breadth via WSJ; put/call) — these can't be backfilled,
   so start collecting NOW to build forward history, judge in months.
3. **Forward-test the breadth-narrowing gate** live on fresh data (the only honest way to confirm a
   backward-looking lead).
4. (Optional pivot) Ship the **DSI calm/complacency gauge** as an honest context feature — it works
   and transfers, just a different product than a crash predictor.

## Open questions
- Which non-daily inputs actually carry the distribution signal, and which are free/affordable?
- Is there published evidence of any method with real out-of-sample top/bottom accuracy + low false
  positives, or is most of it in-sample/marketing?
- Can the target be reframed (predict a fragile regime, not a binary crash) into something validatable?
- Is true NYSE-only breadth (vs the broad-US proxy) materially better, and worth forward-collecting?

## How to pick this up cold
Read `backtest/PHASE3-REPORT.md` (latest verdict), then `backtest/PHASE2-REPORT.md`, then this file.
The harness + honesty machinery are reusable; any new method MUST plug into it (point-in-time,
opportunity-set null, cross-asset transfer, temporal hold-out, pre-registration).

---

## Phase 3 — RAN, honest NO-GO both sides (2026-06-18)
Built the research mission's free, buildable-now subset and judged it under the SAME honesty harness
plus a benchmark battle + a pre-registered alert budget (7-gate kill-gate). Report:
`backtest/PHASE3-REPORT.md`. Frozen contract: `backtest/preregistration_phase3.yaml`. Code:
`src/features/utils.py` (new `variance_risk_premium`, `zweig_breadth_thrust`),
`src/signals/conditions_phase3.py`, `src/backtest/phase3.py`, `src/run_phase3.py`. Tests:
`tests/test_lookahead_phase3.py`, `tests/test_preregistration_phase3.py`. Full suite 90 green.

**What we built (Track A):**
- TOP: a 4-leg WATCH-STATE composite (low variance-risk-premium = complacency; high VIX/VIX3M term
  stress; high VVIX-vs-VIX residual; breadth narrowing) → a 2-stage TRIGGER (watch-state in its own
  top quintile AND SPY closes below its 50-day average). The first time we've actually tested VRP.
- BOTTOM: capitulation washout → a RARE breadth thrust. Canonical NYSE Zweig (0.40→0.615) fires only
  ~6x in 16y / none post-2019 on our broad-US feed, so we used a self-normalizing percentile thrust
  (10-day adv-ratio EMA's trailing-252 percentile 0.10→0.90), gated by a washout within the prior 25d.

**Result — NO-GO both sides (the anticipated, honest outcome):**
- TOP (best T_watch_break): edge +0.090 (precision 0.310 vs eligible-base 0.221) but oppset null_p
  0.384 — NOT significant. 9 of 29 alerts preceded a ≥8% top; recall 4/10 organic (clears the floor).
  QQQ transfer edge +0.024 (p 0.522) — POSITIVE (Phase-2 was −0.028) but not significant. The dumb
  200-day-break baseline had HIGHER precision (0.478) but caught 0/10 tops early (precise-but-late) →
  detector loses the benchmark battle.
- BOTTOM (best B_thrust): edge NEGATIVE −0.154 (precision 0.769 vs eligible-base 0.923), null_p 0.970.
  The 92% base-rate trap CONFIRMED AGAIN: among −5% pullback days, 92.3% precede an 8% bounce within
  60d; the rare thrust did not beat that (even underperformed — it fires late, after the bounce starts).
  `washout_only` (0.957) beat the gated thrust (0.769) → the thrust requirement HURT.
- Ships DESCRIPTIVE-ONLY (a fragility/complacency gauge); NO live alert flipped on. Confirms the
  research's core finding: free VIX-derived data + broad-US breadth can't hit the exact ≥8% turn.

**What shipped LIVE (Track B — forward-collection, can't be backfilled):**
- `src/data/fetch_putcall.py` → `CBOE_PUTCALL` (total/equity/index/etp put-call ratios; free CBOE
  daily page, backfillable to ~2019-10-15).
- `src/data/fetch_nyse_breadth.py` → `NYSE_BREADTH` (true NYSE adv/dec ISSUES **and UP/DOWN VOLUME**
  — the volume our ABINYSE proxy lacks; unlocks a future Lowry 90/90). Snapshot-only source, no free
  history → forward-collected.
- `scripts/collect_daily.sh` + `vol-collect-daily.timer/.service` (daily 22:30 UTC, runs as root, the
  store is root-owned). Append-only + restatement guard. NOTE: `data/store/` is gitignored.

## Next steps (priority-ordered)
1. **JUDGE TRACK B IN A FEW MONTHS.** Once CBOE put/call + true NYSE up/down volume have built forward
   history, add them as new legs: a put/call leg in `top_watch_state` and a Lowry 90/90 up/down-volume
   confirmation in `b_thrust`. Each is a one-line append + a prereg cell + a look-ahead-test entry, then
   re-run `python3 -m src.run_phase3`. This is the real bet for a future GO.
2. **Acquire the richer paid inputs** the research endorses if budget allows (ORATS near-EOD SPX/QQQ
   options for decomposed tail/jump/skew measures; dealer-gamma reconstruction; Norgate point-in-time
   constituents). They plug into the same watch-state composite.
3. The DSI/watch-state can still ship as an honest descriptive complacency gauge (works, transfers; a
   different product than a crash predictor).

## APPENDIX — the research-mission prompt (self-contained; git-recoverable copy)

> You are a research analyst. Do NOT start coding. Your job is a fact-finding mission, then a plan,
> then an adversarial review of that plan. We do not want to reinvent the wheel — find how OTHERS
> have actually achieved this, then design a better path grounded in what demonstrably works.
>
> **GOAL:** detect SPY/QQQ tops and bottoms early (ahead of a ≥8% move within ~60 trading days) with
> few false alarms and a real out-of-sample edge. Free/affordable data preferred. No look-ahead.
>
> **LEADING HYPOTHESIS WE TESTED:** a real top (outside a news crash) is a multi-week distribution
> phase — range-compression/churn near the highs, breadth narrowing, up-volume drying up, a VVIX-vs-
> VIX shift as price rolls over — the combination + timing, not one sign. Bottoms = capitulation climax.
>
> **WHAT WE TRIED:** 16 single signals (VIX level/term, VVIX, realized vol, RSI/trend-extension, RSP/SPY
> & QQQE/QQQ breadth, BAA10Y credit, SKEW, TLT safe-haven, OBV/Bollinger distribution); the gated
> confluence; a two-stage watch→price-break model; a continuous composite score; a capitulation bottom.
>
> **DATA:** free daily 2010-2026 — SPY/QQQ/RSP/QQQE/HYG/LQD/TLT OHLCV, VIX/VIX3M/VVIX/VXN/SKEW, FRED
> BAA10Y, a free broad-US advance/decline feed.
>
> **HOW WE BACK-TESTED (any new plan must respect this):** point-in-time only (truncation test);
> next-open entry; episode collapsing; only **12 independent ≥8% tops exist 2010-2026** (~10 organic);
> edge = precision vs base rate AND vs a random-timing null; the decisive upgrades — an **opportunity-
> set null** (draw the null only from eligible "watch" days, not all days), a **temporal hold-out**
> (2010-21 discover / 2022-26 confirm), a **cross-asset transfer** to QQQ with no re-tuning, leave-one-
> episode-out, a multiple-testing reality check on a frozen grid, raw counts not just %, pre-registration.
>
> **WHAT DIDN'T WORK:** single signals — no edge; binary confluence — best top +12pp but p≈0.13;
> **cross-asset transfer to QQQ NEGATIVE** (overfit); continuous score — rank-IC −0.09 over 3,815 days
> (p≈0.85, near zero with full power); two-stage — +8-10pp on S&P, not significant, no transfer; bottom
> precision was a base-rate artifact (after 5%+ down, an 8% bounce within 60d happens ~92% anyway).
>
> **WHY WE BELIEVE IT DIDN'T WORK (verify or refute):** (1) compression-near-highs is mostly a calm-
> market signature that precedes more calm, not a top; tops are too rare to separate from benign calm.
> (2) the institutional-distribution fingerprint likely isn't in daily price/volume/breadth — it needs
> richer inputs we lack (options positioning / dealer gamma, tick-level/true-exchange breadth, order flow).
>
> **YOUR MISSION:** (1) **Fact-finding** — how do others actually do this with *demonstrated out-of-
> sample accuracy and low false positives* (not marketing)? Survey academia, practitioners, open-source,
> and commercial tools; for each, extract the data inputs (especially beyond daily OHLCV), the method,
> the evidence of real edge (sample size + false-alarm rate), and data cost/availability. Name which
> inputs carry signal and which are noise. (2) **Plan** — a concrete, testable plan (data + sources +
> cost, method, validation protocol that reuses our honesty machinery, expected false-positive control).
> (3) **Adversarial review** of your own plan, focused on **accuracy and limiting false positives** —
> where it overfits, where the null is too easy, where it won't transfer, the realistic false-alarm
> rate, survivorship/restatement/look-ahead hazards, and what would make it fail live; then state what
> survives and what must change. Be concrete, cite sources, prefer evidence over assertion. Assume the
> goal is achievable with the right inputs — find how.
