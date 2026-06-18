# Phase-3 Detector — CONFIRMATORY Report (decomposed-surface tops / breadth-thrust bottoms)

- panel: 4145 rows, 2010-01-04..2026-06-17
- frozen contract: backtest/preregistration_phase3.yaml (builds on the Phase-2 NO-GO; hypotheses post-selected, disclosed)
- 8% top base rate (all days): 0.263 | bottom base: 0.602
- HONESTY: raw ratios lead; an opportunity-set null_p in [0.05,0.10] is SUGGESTIVE only; the
  watch-state top detector is effectively a ~2012+ tool (warmup) — pre-2012 tops are warmup-excluded.

## Per-construction precision vs OPPORTUNITY-SET null (the hard null)

| construction | side | role | episodes | TP | precision | elig-base | edge | oppset null_p | all-days base |
|---|---|---|---|---|---|---|---|---|---|
| T_watch_break[0.80,50] | top | primary | 35 | 10 | 0.286 | 0.221 | 0.065 | 0.435 | 0.263 |
| T_watch_break[0.85,50] | top | variant | 29 | 9 | 0.310 | 0.221 | 0.090 | 0.384 | 0.263 |
| T_watch_break[0.80,20] | top | variant | 48 | 11 | 0.229 | 0.221 | 0.008 | 0.755 | 0.263 |
| B_thrust[-0.08,0.90] | bottom | primary | 13 | 10 | 0.769 | 0.923 | -0.154 | 0.970 | 0.602 |
| B_thrust[-0.05,0.80] | bottom | variant | 19 | 12 | 0.632 | 0.923 | -0.292 | 1.000 | 0.602 |
| B_thrust_canonical | bottom | variant | 3 | 2 | 0.667 | 0.923 | -0.257 | 0.976 | 0.602 |
| ctl_zbt_only | bottom | control | 42 | 25 | 0.595 | 0.923 | -0.328 | 1.000 | 0.602 |
| ctl_washout_only | bottom | control | 23 | 22 | 0.957 | 0.923 | 0.033 | 0.293 | 0.602 |
| bench_top_200 | top | benchmark | 23 | 11 | 0.478 | 0.221 | 0.258 | 0.022 | 0.263 |
| bench_bot_200 | bottom | benchmark | 24 | 18 | 0.750 | 0.923 | -0.173 | 1.000 | 0.602 |

## Recall over the 12 enumerated tops (raw counts — the honest headline)

| construction | caught (all/12) | caught organic (/10) | caught distribution (/7) |
|---|---|---|---|
| T_watch_break[0.80,50] | 5/12 | 4/10 | 3/7 |
| T_watch_break[0.85,50] | 4/12 | 4/10 | 3/7 |
| T_watch_break[0.80,20] | 5/12 | 4/10 | 3/7 |
| bench_top_200 | 1/12 | 0/10 | 0/7 |

## Best top construction: **T_watch_break[0.85,50]**  (best of 3 by opportunity-set edge)

- precision 0.310 vs eligible-base 0.221 = edge 0.090 pp; opportunity-set null_p = **0.384**
- raw: 9 of 29 alerts preceded a >=8% top; caught 4/10 organic tops
- TEMPORAL hold-out — discover(2010-21) edge 0.111 (p 0.431, n=22) | CONFIRM(2022-26) edge 0.109 (p 0.360, n=8)
- CROSS-ASSET transfer to QQQ — edge 0.024, null_p 0.522, n=32
- LEAVE-ONE-EPISODE-OUT — full precision 0.310, base 0.263, max single-episode precision drop -0.023, no-single-collapse=True

## Best bottom construction: **B_thrust[-0.08,0.90]**  (best of 3 by opportunity-set edge)

- precision 0.769 vs eligible-base 0.923 = edge -0.154 pp; opportunity-set null_p = **0.970**; raw 10/13
- TEMPORAL hold-out — discover edge -0.165 (p 0.946, n=8) | CONFIRM edge -0.139 (p 0.968, n=5)
- CROSS-ASSET transfer to QQQ — edge 0.050, null_p 0.753, n=14
- G5 stack-beats-parts (matched count): vs ctl_zbt_only diff_p05 0.000 beats=False | vs ctl_washout_only diff_p05 -0.231 beats=False

## Confirmatory MULTIPLE-TESTING reality check

- max-stat reality_p across 6 frozen cells (opportunity-set null): **0.350** (V_obs=0.090)

## Benchmark battle (G6) — detector vs the late-but-robust 200-day trend baseline, matched count

- TOP: T_watch_break[0.85,50] precision 0.310 (n=29) vs bench_top_200 0.478 (n=23); diff_p05 -0.342 -> beats=False
- BOTTOM: B_thrust[-0.08,0.90] precision 0.769 (n=13) vs bench_bot_200 0.750 (n=24); diff_p05 -0.154 -> beats=False

## Alert budget (G7) — collapsed episodes/year vs the pre-registered cap

- TOP: 1.76/yr (cap 4, min 2) within_cap=True above_min=False
- BOTTOM: 0.85/yr (cap 3, min 1) within_cap=True above_min=False

## KILL-GATE (Phase-3, per side)

- **TOP VERDICT: NO-GO**  |  **BOTTOM VERDICT: NO-GO**  |  overall: NO-GO
- G1 precision floor (>= base+20pp AND oppset p<0.05): top=False (edge 0.090, p 0.384) | bottom=False (edge -0.154, p 0.970)
- G2 confirmatory MTC (reality_p<0.05): False (reality_p 0.350)
- G3 out-of-sample (confirm>0 AND QQQ beats null [AND top LOEO no-collapse]): top=False | bottom=False
- G4 recall floor (top only, >= 4/10 organic): True (4/10)
- G5 stack beats parts (bottom gated > both controls, matched): False
- G6 benchmark battle (beats 200-day baseline): top=False | bottom=False
- G7 alert budget (within cap): top=True | bottom=True

> NO-GO (both sides) = **no demonstrably-validated edge**. Ship DESCRIPTIVE-ONLY (display where the fragility watch-state / VRP / breadth thrust stand today; no predictive-confidence claim, no live alert). This is the honest, successful outcome the pre-registration anticipated. The Track-B forward-collection (CBOE put/call, true NYSE up/down volume) continues regardless and is what sets up the next, stronger test.
