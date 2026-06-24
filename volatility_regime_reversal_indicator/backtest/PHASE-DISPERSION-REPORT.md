# Phase-DISPERSION Detector — CONFIRMATORY Report

## Cross-Sectional Return Dispersion as a TOP Precursor (Maio & Saffi 2016)

- panel: 5158 rows, 2006-01-03..2026-06-24
- SP500_DISP valid rows: 5158/5158 (100%)
- frozen contract: backtest/preregistration_dispersion.yaml
- in-window enumerated tops scored: 12 of 12
- 8% top base rate (all days): 0.286
- SURVIVORSHIP CAVEAT: SP500_DISP uses today's membership applied backward.
  Historical dispersion is UNDERSTATED near stress events. Precision is an UPPER BOUND.
- HONESTY: raw ratios lead; null_p in [0.05,0.10] is SUGGESTIVE only.
  The make-or-break test is the QQQ cross-asset transfer (same threshold applied to
  NDX_DISP with NO re-tuning). Failure here = the SPY edge is index-specific noise.

## Per-construction precision vs OPPORTUNITY-SET null (the hard null)

| construction | side | role | episodes | TP | precision | elig-base | edge | oppset null_p | all-days base |
|---|---|---|---|---|---|---|---|---|---|
| D_high_disp_near_high[0.80,252] | top | primary | 127 | 34 | 0.268 | 0.225 | 0.043 | 0.306 | 0.286 |
| D_high_disp_near_high[0.80,126] | top | variant | 136 | 30 | 0.221 | 0.225 | -0.005 | 0.754 | 0.286 |
| D_high_disp_near_high[0.80,60] | top | variant | 143 | 36 | 0.252 | 0.225 | 0.027 | 0.297 | 0.286 |
| D_high_down_disp_near_high[0.80,252] | top | variant | 131 | 29 | 0.221 | 0.225 | -0.004 | 0.805 | 0.286 |
| ctl_disp_only[0.80,252] | top | control | 178 | 63 | 0.354 | 0.225 | 0.129 | 0.011 | 0.286 |
| bench_top_200 | top | benchmark | 30 | 15 | 0.500 | 0.225 | 0.275 | 0.039 | 0.286 |

## Recall over the enumerated tops (raw counts — the honest headline)

| construction | caught (all/12 in-window) | caught organic | caught distribution |
|---|---|---|---|
| D_high_disp_near_high[0.80,252] | 12/12 | 11 | 7 |
| D_high_disp_near_high[0.80,126] | 10/12 | 9 | 6 |
| D_high_disp_near_high[0.80,60] | 12/12 | 11 | 7 |
| D_high_down_disp_near_high[0.80,252] | 11/12 | 10 | 6 |
| ctl_disp_only[0.80,252] | 12/12 | 11 | 7 |
| bench_top_200 | 1/12 | 0 | 0 |

## Best top construction: **D_high_disp_near_high[0.80,252]**  (best of 4 by opportunity-set edge)

- precision 0.268 vs eligible-base 0.225 = edge 0.043 pp; opportunity-set null_p = **0.306**
- raw: 34 of 127 alerts preceded a >=8% top; caught 11 organic tops
- TEMPORAL hold-out — discover(2006-2021) edge 0.053 (p 0.296, n=97) | CONFIRM(2022-2026) edge 0.000 (p 0.544, n=30)
- **CROSS-ASSET transfer to QQQ (THE BINDING CONSTRAINT) — edge 0.010, null_p 0.474, n=130**
- LEAVE-ONE-EPISODE-OUT — full precision 0.268, base 0.286, max single-episode precision drop 0.030, no-single-collapse=False

## Controls / stack-beats-parts (G5) — does the near-high gate matter, matched count?

- TOP gated vs ctl_disp_only: detector prec 0.268 (n=127) vs control 0.354 (n=178); diff_p05 -0.126 -> beats=False

## Confirmatory MULTIPLE-TESTING reality check

- max-stat reality_p across 4 frozen cells (opportunity-set null): **0.393** (V_obs=0.043)

## Benchmark battle (G6 analogue) — detector vs 200-day trend baseline, matched count

- TOP: D_high_disp_near_high[0.80,252] precision 0.268 (n=127) vs bench_top_200 0.500 (n=30); diff_p05 -0.366 -> beats=False

## Alert budget — collapsed episodes/year vs pre-registered cap

- TOP: 6.35/yr (cap 6.0, min 1.0) within_cap=False above_min=True

## KILL-GATE (Phase-DISPERSION)

- **VERDICT: NO-GO**
- G1 precision floor (>= base+8pp AND oppset p<0.05): False (edge 0.043, p 0.306)
- G2 confirmatory MTC (reality_p<0.05): False (reality_p 0.393)
- G3 out-of-sample (confirm>0 AND QQQ beats null AND LOEO no-collapse): False
  - QQQ-transfer detail: edge 0.010 p 0.474 n=130
  - LOEO no-single-collapse: False
- G4 recall floor (>= 4 organic in-window): True (11 organic)
- G5 stack beats parts (gated > disp-only at matched count): False (diff_p05 -0.126)

> NO-GO = **no demonstrably-validated edge**. Ship DESCRIPTIVE-ONLY:
> display the current S&P 500 cross-sectional dispersion percentile reading.
> No predictive-confidence claim. No live alert.
>
> Root causes for NO-GO (check which gates failed above):
>  - G1: precision edge 0.043 pp below 8pp floor, or null_p 0.306 >= 0.05
>  - G2: reality check p=0.393 >= 0.05 (no cell survives MTC)
>  - G3: OOS failure: QQQ transfer edge 0.010 p 0.474; LOEO: single episode collapses precision
>  - G5: near-high gate does not add precision over raw dispersion
>
> The survivorship bias in the constituent data likely inflated in-sample
> precision. A real-time implementation would see HIGHER dispersion in
> stress (more losers included); the signal would be noisier and less
> precise than these results suggest.
