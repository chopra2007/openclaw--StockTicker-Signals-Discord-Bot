# Phase-GAMMA Detector — CONFIRMATORY Report (dealer-gamma tops / dark-pool-dix bottoms)

- panel: 3811 rows, 2011-05-02..2026-06-18
- frozen contract: backtest/preregistration_gamma.yaml (builds on the Phase-3 NO-GO; round canonical thresholds, NOT re-tuned)
- in-window enumerated tops scored: 10 of 12 (SQZ starts 2011-05-02 — pre-2011-05 tops not covered)
- 8% top base rate (all days): 0.262 | bottom base: 0.593
- HONESTY: raw ratios lead; an opportunity-set null_p in [0.05,0.10] is SUGGESTIVE only.
  Dealer gamma (gex) is the ONE genuinely-new, NON-VIX-derived free input; the make-or-break
  test is the QQQ cross-asset transfer — the constraint that killed Phases 2 and 3.

## Per-construction precision vs OPPORTUNITY-SET null (the hard null)

| construction | side | role | episodes | TP | precision | elig-base | edge | oppset null_p | all-days base |
|---|---|---|---|---|---|---|---|---|---|
| G_neg_gamma_break[50] | top | primary | 49 | 17 | 0.347 | 0.219 | 0.128 | 0.092 | 0.262 |
| G_low_gex_break[0.20,50] | top | variant | 66 | 21 | 0.318 | 0.219 | 0.099 | 0.200 | 0.262 |
| G_neg_gamma_ma_break[20,50] | top | variant | 10 | 6 | 0.600 | 0.219 | 0.381 | 0.016 | 0.262 |
| G_dix_capitulation[-0.08,0.90] | bottom | primary | 23 | 21 | 0.913 | 0.917 | -0.004 | 0.583 | 0.593 |
| G_neg_gamma_capitulation[-0.08,0.90] | bottom | variant | 22 | 19 | 0.864 | 0.917 | -0.053 | 0.769 | 0.593 |
| ctl_neg_gamma_only | top | control | 52 | 18 | 0.346 | 0.219 | 0.127 | 0.073 | 0.262 |
| ctl_dix_only | bottom | control | 78 | 45 | 0.577 | 0.917 | -0.340 | 1.000 | 0.593 |
| bench_top_200 | top | benchmark | 20 | 9 | 0.450 | 0.219 | 0.231 | 0.046 | 0.262 |
| bench_bot_200 | bottom | benchmark | 22 | 16 | 0.727 | 0.917 | -0.190 | 1.000 | 0.593 |

## Recall over the enumerated tops (raw counts — the honest headline)

| construction | caught (all/10 in-window) | caught organic | caught distribution |
|---|---|---|---|
| G_neg_gamma_break[50] | 4/10 | 3 | 2 |
| G_low_gex_break[0.20,50] | 7/10 | 6 | 4 |
| G_neg_gamma_ma_break[20,50] | 0/10 | 0 | 0 |
| ctl_neg_gamma_only | 5/10 | 4 | 2 |
| bench_top_200 | 1/10 | 0 | 0 |

## Best top construction: **G_neg_gamma_ma_break[20,50]**  (best of 3 by opportunity-set edge)

- precision 0.600 vs eligible-base 0.219 = edge 0.381 pp; opportunity-set null_p = **0.016**
- raw: 6 of 10 alerts preceded a >=8% top; caught 0 organic tops
- TEMPORAL hold-out — discover(2011-21) edge 0.297 (p 0.170, n=6) | CONFIRM(2022-26) edge 0.484 (p 0.050, n=4)
- **CROSS-ASSET transfer to QQQ (THE BINDING CONSTRAINT) — edge 0.268, null_p 0.064, n=10**
- LEAVE-ONE-EPISODE-OUT — full precision 0.600, base 0.262, max single-episode precision drop -0.338, no-single-collapse=True

## Best bottom construction: **G_dix_capitulation[-0.08,0.90]**  (best of 2 by opportunity-set edge)

- precision 0.913 vs eligible-base 0.917 = edge -0.004 pp; opportunity-set null_p = **0.583**; raw 21/23
- TEMPORAL hold-out — discover edge 0.015 (p 0.494, n=12) | CONFIRM edge -0.030 (p 0.856, n=11)
- **CROSS-ASSET transfer to QQQ — edge 0.011, null_p 0.833, n=25**

## Controls / stack-beats-parts (G5) — does the trigger/sequence matter, matched count?

- TOP gated vs ctl_neg_gamma_only: detector prec 0.600 (n=10) vs control 0.346 (n=52); diff_p05 0.000 -> beats=False
- BOTTOM gated vs ctl_dix_only: detector prec 0.913 (n=23) vs control 0.577 (n=78); diff_p05 0.217 -> beats=True

## Confirmatory MULTIPLE-TESTING reality check

- max-stat reality_p across 5 frozen cells (opportunity-set null): **0.010** (V_obs=0.381)

## Benchmark battle (G6) — detector vs the late-but-robust 200-day trend baseline, matched count

- TOP: G_neg_gamma_ma_break[20,50] precision 0.600 (n=10) vs bench_top_200 0.450 (n=20); diff_p05 0.000 -> beats=False
- BOTTOM: G_dix_capitulation[-0.08,0.90] precision 0.913 (n=23) vs bench_bot_200 0.727 (n=22); diff_p05 0.049 -> beats=True

## Alert budget (G7) — collapsed episodes/year vs the pre-registered cap

- TOP: 0.66/yr (cap 4, min 2) within_cap=True above_min=False
- BOTTOM: 1.59/yr (cap 3, min 1) within_cap=True above_min=True

## KILL-GATE (Phase-GAMMA, per side)

- **TOP VERDICT: NO-GO**  |  **BOTTOM VERDICT: NO-GO**  |  overall: NO-GO
- G1 precision floor (>= base+20pp AND oppset p<0.05): top=True (edge 0.381, p 0.016) | bottom=False (edge -0.004, p 0.583)
- G2 confirmatory MTC (reality_p<0.05): True (reality_p 0.010)
- G3 out-of-sample (confirm>0 AND QQQ beats null [AND top LOEO no-collapse]): top=False | bottom=False
  - QQQ-transfer detail: top edge 0.268 p 0.064 | bottom edge 0.011 p 0.833
- G4 recall floor (top only, >= 4 organic in-window): False (0 organic)
- G5 stack beats parts (matched): top vs neg_gamma_only=False | bottom vs dix_only=True
- G6 benchmark battle (beats 200-day baseline): top=False | bottom=True
- G7 alert budget (within cap): top=True | bottom=True

> NO-GO (both sides) = **no demonstrably-validated edge**. Ship DESCRIPTIVE-ONLY (display where dealer gamma / dark-pool dix stand today; no predictive-confidence claim, no live alert). This is the honest outcome the pre-registration anticipated: dealer gamma was the last free, non-VIX lever — if it does not transfer to QQQ or beat the regime-matched base, the free-data search for a validated TOP/BOTTOM detector is exhausted, and the next attempt needs paid decomposed-surface data.
