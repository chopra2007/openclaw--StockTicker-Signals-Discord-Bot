# Phase-1 Ablation & Kill-Gate Report — SPY

- panel: 4145 rows, 2010-01-04..2026-06-17
- grid cells tested: 320 (reality-check max-stat p = 0.0675)
- coverage buckets (days): {'high': 4145, 'low': 0, 'mid': 0}
- primary horizon = 20d; primary tier = 8%

## Per-condition ablation (primary = 20d forward-return edge, sign-adjusted)

| condition | family | side | N ep | edge(20d) | null_p | BH | stable(folds) | hit8 edge pp | hit8 p |
|---|---|---|---|---|---|---|---|---|---|
| overextended_top[dist_pct=0.95,rsi_thresh=75.0] | trend_extension | top | 4 | 0.0290 | 0.083 | · | ·(0+/0-) | 48.7 | 0.044 |
| vix_capitulation[pct=0.95] | vix_level | bottom | 36 | 0.0161 | 0.133 | · | Y(5+/2-) | 19.8 | 0.179 |
| oversold_bottom[dist_pct=0.05,rsi_thresh=25.0] | trend_extension | bottom | 7 | 0.0146 | 0.327 | · | ·(0+/0-) | 39.8 | 0.099 |
| rsi_recovering_bottom[low=35.0] | mean_reversion | bottom | 43 | 0.0117 | 0.111 | · | Y(6+/0-) | 21.2 | 0.020 |
| rsi_recovering_bottom[low=30.0] | mean_reversion | bottom | 18 | 0.0063 | 0.459 | · | Y(3+/0-) | 28.0 | 0.066 |
| breadth_break_top[ratio_drop=-0.01,near_high=0.98] | breadth | top | 59 | 0.0061 | 0.157 | · | Y(5+/2-) | 5.3 | 0.125 |
| oversold_bottom[dist_pct=0.1,rsi_thresh=30.0] | trend_extension | bottom | 17 | 0.0056 | 0.457 | · | Y(3+/0-) | 33.6 | 0.015 |
| skew_extreme[pct=0.95] | skew | top | 68 | 0.0050 | 0.163 | · | Y(5+/3-) | -5.4 | 0.829 |
| breadth_break_top[ratio_drop=-0.02,near_high=0.97] | breadth | top | 24 | 0.0044 | 0.332 | · | Y(2+/1-) | 19.2 | 0.021 |
| overextended_top[dist_pct=0.9,rsi_thresh=70.0] | trend_extension | top | 26 | 0.0044 | 0.343 | · | ·(3+/3-) | -1.3 | 0.439 |
| vix_complacency[pct=0.1] | vix_level | top | 70 | 0.0042 | 0.277 | · | Y(6+/2-) | -13.4 | 0.929 |
| vix_term_falling[pct_thresh=-0.05] | vix_term_structure | vol_contraction | 136 | 0.0029 | 0.129 | · | Y(5+/3-) | -0.9 | 0.495 |
| vix_capitulation[pct=0.9] | vix_level | bottom | 51 | 0.0024 | 0.701 | · | ·(4+/4-) | 11.8 | 0.561 |
| vix_complacency[pct=0.2] | vix_level | top | 94 | 0.0021 | 0.509 | · | Y(5+/3-) | -9.2 | 0.683 |
| skew_extreme[pct=0.9] | skew | top | 82 | 0.0014 | 0.394 | · | Y(5+/3-) | -5.3 | 0.840 |
| accumulation_bottom[near_low=1.03,ud_ratio=1.0] | distribution_accumulation | bottom | 14 | 0.0013 | 0.555 | · | ·(1+/1-) | 18.4 | 0.208 |
| distribution_top[near_high=0.97,width_pct=0.3] | distribution_accumulation | top | 69 | 0.0008 | 0.463 | · | ·(4+/4-) | -4.5 | 0.861 |
| credit_stress_rising[z_thresh=1.0] | credit | top | 44 | 0.0003 | 0.315 | · | ·(2+/4-) | 16.9 | 0.079 |
| distribution_top[near_high=0.98,width_pct=0.2] | distribution_accumulation | top | 55 | -0.0004 | 0.558 | · | ·(3+/5-) | -6.3 | 0.868 |
| rvol_compression[pct=0.2] | realized_vol | vol_contraction | 74 | -0.0005 | 0.393 | · | ·(2+/5-) | -11.5 | 0.937 |
| rvol_spike[pct=0.9] | realized_vol | vol_expansion | 30 | -0.0006 | 0.290 | · | ·(2+/4-) | 18.6 | 0.174 |
| rvol_compression[pct=0.1] | realized_vol | vol_contraction | 55 | -0.0017 | 0.481 | · | ·(2+/5-) | -11.1 | 0.849 |
| tlt_safe_haven[window=20,thresh=0.02] | safe_haven | top | 91 | -0.0020 | 0.514 | · | ·(3+/5-) | 3.7 | 0.557 |
| vvix_elevated[pct=0.8] | vol_of_vol | vol_expansion | 100 | -0.0022 | 0.399 | · | ·(4+/4-) | 3.7 | 0.722 |
| rvol_spike[pct=0.8] | realized_vol | vol_expansion | 41 | -0.0027 | 0.361 | · | ·(3+/3-) | 18.7 | 0.113 |
| tlt_safe_haven[window=20,thresh=0.04] | safe_haven | top | 73 | -0.0041 | 0.605 | · | ·(2+/6-) | 8.5 | 0.279 |
| vix_term_falling[pct_thresh=-0.1] | vix_term_structure | vol_contraction | 78 | -0.0046 | 0.807 | · | ·(3+/5-) | -8.2 | 0.917 |
| vvix_elevated[pct=0.9] | vol_of_vol | vol_expansion | 76 | -0.0048 | 0.581 | · | ·(3+/5-) | 2.7 | 0.825 |
| vix_backwardation[thresh=1.0] | vix_term_structure | vol_expansion | 60 | -0.0052 | 0.488 | · | ·(3+/5-) | 7.6 | 0.627 |
| vix_backwardation[thresh=1.05] | vix_term_structure | vol_expansion | 23 | -0.0059 | 0.514 | · | Y(3+/2-) | 4.2 | 0.746 |
| credit_stress_rising[z_thresh=1.5] | credit | top | 33 | -0.0078 | 0.680 | · | ·(0+/6-) | 19.2 | 0.096 |
| accumulation_bottom[near_low=1.02,ud_ratio=1.2] | distribution_accumulation | bottom | 0 | nan | nan | · | ·(0+/0-) | nan | nan |

## Per-tier hit-rate vs base-rate (false-alarm) — the user's target

Top conditions ranked by 8% (primary) tier edge:

| condition | event | N ep | tier | hit_rate | base_rate | edge pp | false-alarm | null_p |
|---|---|---|---|---|---|---|---|---|
| overextended_top[dist_pct=0.95,rsi_thresh=75.0] | top | 4 | 5% | 1.000 | 0.517 | 48.3 | 0.000 | 0.078 |
| overextended_top[dist_pct=0.95,rsi_thresh=75.0] | top | 4 | 8% | 0.750 | 0.263 | 48.7 | 0.250 | 0.056 |
| overextended_top[dist_pct=0.95,rsi_thresh=75.0] | top | 4 | 15% | 0.000 | 0.071 | -7.1 | 1.000 | 1.000 |
| overextended_top[dist_pct=0.95,rsi_thresh=75.0] | top | 4 | 20% | 0.000 | 0.016 | -1.6 | 1.000 | 1.000 |
| oversold_bottom[dist_pct=0.05,rsi_thresh=25.0] | bottom | 7 | 5% | 1.000 | 0.905 | 9.5 | 0.000 | 0.763 |
| oversold_bottom[dist_pct=0.05,rsi_thresh=25.0] | bottom | 7 | 8% | 1.000 | 0.602 | 39.8 | 0.000 | 0.095 |
| oversold_bottom[dist_pct=0.05,rsi_thresh=25.0] | bottom | 7 | 15% | 0.571 | 0.100 | 47.2 | 0.429 | 0.072 |
| oversold_bottom[dist_pct=0.05,rsi_thresh=25.0] | bottom | 7 | 20% | 0.429 | 0.027 | 40.2 | 0.571 | 0.014 |
| oversold_bottom[dist_pct=0.1,rsi_thresh=30.0] | bottom | 16 | 5% | 1.000 | 0.905 | 9.5 | 0.000 | 0.448 |
| oversold_bottom[dist_pct=0.1,rsi_thresh=30.0] | bottom | 16 | 8% | 0.938 | 0.602 | 33.6 | 0.062 | 0.023 |
| oversold_bottom[dist_pct=0.1,rsi_thresh=30.0] | bottom | 16 | 15% | 0.375 | 0.100 | 27.5 | 0.625 | 0.116 |
| oversold_bottom[dist_pct=0.1,rsi_thresh=30.0] | bottom | 16 | 20% | 0.250 | 0.027 | 22.3 | 0.750 | 0.016 |
| rsi_recovering_bottom[low=30.0] | bottom | 17 | 5% | 1.000 | 0.905 | 9.5 | 0.000 | 0.412 |
| rsi_recovering_bottom[low=30.0] | bottom | 17 | 8% | 0.882 | 0.602 | 28.0 | 0.118 | 0.058 |
| rsi_recovering_bottom[low=30.0] | bottom | 17 | 15% | 0.353 | 0.100 | 25.3 | 0.647 | 0.148 |
| rsi_recovering_bottom[low=30.0] | bottom | 17 | 20% | 0.176 | 0.027 | 15.0 | 0.824 | 0.074 |
| rsi_recovering_bottom[low=35.0] | bottom | 43 | 5% | 1.000 | 0.905 | 9.5 | 0.000 | 0.048 |
| rsi_recovering_bottom[low=35.0] | bottom | 43 | 8% | 0.814 | 0.602 | 21.2 | 0.186 | 0.016 |
| rsi_recovering_bottom[low=35.0] | bottom | 43 | 15% | 0.256 | 0.100 | 15.6 | 0.744 | 0.156 |
| rsi_recovering_bottom[low=35.0] | bottom | 43 | 20% | 0.070 | 0.027 | 4.3 | 0.930 | 0.376 |
| vix_capitulation[pct=0.95] | bottom | 35 | 5% | 1.000 | 0.905 | 9.5 | 0.000 | 0.283 |
| vix_capitulation[pct=0.95] | bottom | 35 | 8% | 0.800 | 0.602 | 19.8 | 0.200 | 0.175 |
| vix_capitulation[pct=0.95] | bottom | 35 | 15% | 0.229 | 0.100 | 12.9 | 0.771 | 0.725 |
| vix_capitulation[pct=0.95] | bottom | 35 | 20% | 0.114 | 0.027 | 8.8 | 0.886 | 0.244 |
| breadth_break_top[ratio_drop=-0.02,near_high=0.97] | top | 22 | 5% | 0.591 | 0.517 | 7.4 | 0.409 | 0.266 |
| breadth_break_top[ratio_drop=-0.02,near_high=0.97] | top | 22 | 8% | 0.455 | 0.263 | 19.2 | 0.545 | 0.025 |
| breadth_break_top[ratio_drop=-0.02,near_high=0.97] | top | 22 | 15% | 0.045 | 0.071 | -2.6 | 0.955 | 0.772 |
| breadth_break_top[ratio_drop=-0.02,near_high=0.97] | top | 22 | 20% | 0.000 | 0.016 | -1.6 | 1.000 | 1.000 |
| credit_stress_rising[z_thresh=1.5] | top | 33 | 5% | 0.606 | 0.517 | 8.9 | 0.394 | 0.377 |
| credit_stress_rising[z_thresh=1.5] | top | 33 | 8% | 0.455 | 0.263 | 19.2 | 0.545 | 0.114 |
| credit_stress_rising[z_thresh=1.5] | top | 33 | 15% | 0.152 | 0.071 | 8.0 | 0.848 | 0.242 |
| credit_stress_rising[z_thresh=1.5] | top | 33 | 20% | 0.030 | 0.016 | 1.5 | 0.970 | 0.449 |
| rvol_spike[pct=0.8] | top | 40 | 5% | 0.650 | 0.517 | 13.3 | 0.350 | 0.184 |
| rvol_spike[pct=0.8] | top | 40 | 8% | 0.450 | 0.263 | 18.7 | 0.550 | 0.104 |
| rvol_spike[pct=0.8] | top | 40 | 15% | 0.075 | 0.071 | 0.4 | 0.925 | 0.827 |
| rvol_spike[pct=0.8] | top | 40 | 20% | 0.025 | 0.016 | 0.9 | 0.975 | 0.533 |
| rvol_spike[pct=0.9] | top | 29 | 5% | 0.690 | 0.517 | 17.3 | 0.310 | 0.147 |
| rvol_spike[pct=0.9] | top | 29 | 8% | 0.448 | 0.263 | 18.6 | 0.552 | 0.183 |
| rvol_spike[pct=0.9] | top | 29 | 15% | 0.103 | 0.071 | 3.2 | 0.897 | 0.607 |
| rvol_spike[pct=0.9] | top | 29 | 20% | 0.034 | 0.016 | 1.9 | 0.966 | 0.416 |
| accumulation_bottom[near_low=1.03,ud_ratio=1.0] | bottom | 14 | 5% | 0.929 | 0.905 | 2.4 | 0.071 | 0.738 |
| accumulation_bottom[near_low=1.03,ud_ratio=1.0] | bottom | 14 | 8% | 0.786 | 0.602 | 18.4 | 0.214 | 0.213 |
| accumulation_bottom[near_low=1.03,ud_ratio=1.0] | bottom | 14 | 15% | 0.286 | 0.100 | 18.6 | 0.714 | 0.158 |
| accumulation_bottom[near_low=1.03,ud_ratio=1.0] | bottom | 14 | 20% | 0.071 | 0.027 | 4.5 | 0.929 | 0.479 |
| credit_stress_rising[z_thresh=1.0] | top | 44 | 5% | 0.659 | 0.517 | 14.2 | 0.341 | 0.090 |
| credit_stress_rising[z_thresh=1.0] | top | 44 | 8% | 0.432 | 0.263 | 16.9 | 0.568 | 0.084 |
| credit_stress_rising[z_thresh=1.0] | top | 44 | 15% | 0.114 | 0.071 | 4.2 | 0.886 | 0.418 |
| credit_stress_rising[z_thresh=1.0] | top | 44 | 20% | 0.023 | 0.016 | 0.7 | 0.977 | 0.527 |

## Collinearity / VIF (top 12)

| condition | VIF |
|---|---|
| rvol_spike[pct=0.8] | 3.09 |
| credit_stress_rising[z_thresh=1.0] | 3.03 |
| rvol_spike[pct=0.9] | 3.02 |
| credit_stress_rising[z_thresh=1.5] | 2.99 |
| distribution_top[near_high=0.98,width_pct=0.2] | 2.88 |
| distribution_top[near_high=0.97,width_pct=0.3] | 2.88 |
| vix_capitulation[pct=0.9] | 2.86 |
| tlt_safe_haven[window=20,thresh=0.04] | 2.56 |
| vix_capitulation[pct=0.95] | 2.51 |
| vix_complacency[pct=0.2] | 2.50 |
| tlt_safe_haven[window=20,thresh=0.02] | 2.46 |
| rvol_compression[pct=0.2] | 2.32 |

## KILL-GATE

- **VERDICT: FAIL**
- gate 1 (>=3 independent families): False -> families=[]
- gate 2 (positive edge survives MTC): False (reality_p=0.0675, BH+ survivors=0)
- gate 3 (directional fold-stability): False (stable survivors=0)
- gate 4 (edge >= min effect size 1.0%): False
- gate 5 (combined beats best single): False -> {'applicable': False}
- final survivors: []

> FAIL = **no demonstrable edge**. This is a successful, honest research outcome (final-plan.md 2): it saves the Phase 2/3 weeks. Do NOT build a live tool on an unproven signal.
