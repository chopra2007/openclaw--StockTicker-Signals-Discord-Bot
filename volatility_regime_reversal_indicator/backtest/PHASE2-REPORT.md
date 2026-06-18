# Phase-2 Confluence Detector — CONFIRMATORY Report (SPY tops / bottoms)

- panel: 4145 rows, 2010-01-04..2026-06-17
- frozen contract: backtest/preregistration_phase2.yaml (hypotheses post-selected, disclosed)
- 8% top base rate (all days): 0.263 | opportunity-set = near-high watch days only
- HONESTY: raw ratios lead; an opportunity-set null_p in [0.05,0.10] is SUGGESTIVE only.

## Per-construction precision vs OPPORTUNITY-SET null (the hard null)

| construction | side | role | episodes | TP | precision | elig-base | edge | oppset null_p | all-days base |
|---|---|---|---|---|---|---|---|---|---|
| T1_core_gated[0.97,0.30] | top | primary | 38 | 13 | 0.342 | 0.221 | 0.121 | 0.132 | 0.263 |
| T1_core_gated[0.98,0.25] | top | variant | 31 | 10 | 0.323 | 0.221 | 0.102 | 0.182 | 0.263 |
| T2_core_support | top | variant | 30 | 10 | 0.333 | 0.221 | 0.113 | 0.225 | 0.263 |
| T3_core_vvixres | top | variant | 11 | 2 | 0.182 | 0.221 | -0.039 | 0.785 | 0.263 |
| T4_core_abichurn | top | variant | 19 | 6 | 0.316 | 0.221 | 0.095 | 0.267 | 0.263 |
| B1_capitulation[-0.08,0.90] | bottom | primary | 11 | 10 | 0.909 | 0.923 | -0.014 | 0.682 | 0.602 |
| B1_capitulation[-0.06,0.80] | bottom | variant | 18 | 18 | 1.000 | 0.923 | 0.077 | 0.146 | 0.602 |
| B2_capit_vixrev | bottom | variant | 12 | 11 | 0.917 | 0.923 | -0.007 | 0.650 | 0.602 |
| leg_vvix_residual_high | top | leg | 72 | 13 | 0.181 | 0.221 | -0.040 | 0.878 | 0.263 |
| leg_abi_churn | top | leg | 84 | 16 | 0.190 | 0.221 | -0.030 | 0.722 | 0.263 |
| leg_support_loss | top | leg | 88 | 22 | 0.250 | 0.221 | 0.029 | 0.530 | 0.263 |

## Recall over the 12 enumerated tops (raw counts — the honest headline)

| construction | caught (all/12) | caught organic (/10) | caught distribution (/7) |
|---|---|---|---|
| T1_core_gated[0.97,0.30] | 5/12 | 5/10 | 5/7 |
| T1_core_gated[0.98,0.25] | 5/12 | 5/10 | 5/7 |
| T2_core_support | 5/12 | 5/10 | 5/7 |
| T3_core_vvixres | 0/12 | 0/10 | 0/7 |
| T4_core_abichurn | 3/12 | 3/10 | 3/7 |
| leg_vvix_residual_high | 6/12 | 6/10 | 4/7 |
| leg_abi_churn | 11/12 | 10/10 | 7/7 |
| leg_support_loss | 10/12 | 9/10 | 7/7 |

## Best top construction: **T1_core_gated[0.97,0.30]**  (best of 5 by opportunity-set edge)

- precision 0.342 vs eligible-base 0.221 = edge 0.121 pp; opportunity-set null_p = **0.132**
- raw: 13 of 38 alerts preceded a >=8% top; caught 5/10 organic tops
- TEMPORAL hold-out — discover(2010-21) edge 0.113 (p 0.242, n=25) | CONFIRM(2022-26) edge 0.118 (p 0.271, n=13)
- CROSS-ASSET transfer to QQQ — edge -0.028, null_p 0.724, n=34
- LEAVE-ONE-EPISODE-OUT — full precision 0.342, base 0.263, max single-episode precision drop -0.062, no-single-collapse=True

## Best bottom construction: **B1_capitulation[-0.06,0.80]**

- precision 1.000 vs eligible-base 0.923 = edge 0.077 pp; opportunity-set null_p = **0.146**; raw 18/18

## Confirmatory MULTIPLE-TESTING reality check

- max-stat reality_p across 8 frozen cells (opportunity-set null): **0.398** (V_obs=0.121)
- discloses: hypotheses were chosen from ~10+ exploratory combos, so even this understates the true search burden — the OOS battery is the real evidence.

## G5 stack-beats-parts (T1 gated vs ungated watch + legs, matched alert count)

- T1 precision 0.342 (n=38)
  - vs ungated_watch: comparator precision 0.246, diff p05 0.026, T1 beats = True
  - vs leg_vvix_residual_high: comparator precision 0.181, diff p05 0.079, T1 beats = True
  - vs leg_abi_churn: comparator precision 0.190, diff p05 0.079, T1 beats = True

## KILL-GATE (Phase-2)

- **VERDICT: NO-GO**
- G1 precision floor (>= base+20pp AND oppset p<0.05): False (edge 0.121, p 0.132)
- G2 confirmatory MTC (reality_p<0.05): False (reality_p 0.398)
- G3 out-of-sample (confirm>0 AND QQQ beats null AND no LOEO collapse): False
- G4 recall floor (>= 4/10 organic): True (5/10)
- G5 stack beats parts (T1 > ungated watch, matched): True

> NO-GO = **no demonstrably-validated confluence edge**. Ship DESCRIPTIVE-ONLY (show where breadth/vol/compression stand today; no predictive-confidence claim). This is the honest, successful outcome the pre-registration anticipated — it does NOT flip a live alerting feature ON. The best constructions are logged as candidates for a future, independent confirmatory test on fresh/forward data.
