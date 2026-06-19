# Phase-4 BOTTOM Detector — CONFIRMATORY Report (capitulation -> rare breadth THRUST, Lowry 90/90)

- panel: 13867 rows, 1965-03-01..2020-02-10 (54.9 years)
- breadth: NYSE_UDVOL (true NYSE advancing-vs-declining share VOLUME) | price: GSPC (^GSPC)
- frozen contract: backtest/preregistration_phase4.yaml (builds on the Phase-3 NO-GO; bottom-only)
- 8% rally base rate (ALL days): 0.483 | 15% rally base (all days): 0.095
- # of 90% DOWN days: 261 | # of 90% UP days: 155 | equally-distressed eligible days (>=5% DD): 3652
- HONESTY: raw ratios lead; the OPPORTUNITY-SET null (random timing among equally-distressed
  days) is the make-or-break test, NOT the all-days base. A null_p in [0.05,0.10] is SUGGESTIVE only.
- LIMITATION: data ends 2020-02-10 (no COVID-2020 / 2022 / 2025 bottoms); no QQQ transfer (NYSE-index feed, QQQ starts 1999).

## Per-construction precision vs the OPPORTUNITY-SET null (equally-distressed days)

| construction | role | episodes | TP | precision | elig-base (>=5% DD) | edge | oppset null_p | all-days base |
|---|---|---|---|---|---|---|---|---|
| lowry_90_90[w10] | primary | 49 | 35 | 0.714 | 0.704 | 0.011 | 0.538 | 0.483 |
| lowry_90_90[w5] | variant | 37 | 27 | 0.730 | 0.704 | 0.026 | 0.469 | 0.483 |
| lowry_90_90[w25] | variant | 63 | 45 | 0.714 | 0.704 | 0.011 | 0.521 | 0.483 |
| lowry_90_90_two[w10] | variant | 19 | 13 | 0.684 | 0.704 | -0.020 | 0.736 | 0.483 |
| zbt_volume_after_capit | variant | 43 | 29 | 0.674 | 0.704 | -0.029 | 0.755 | 0.483 |
| ctl_thrust_only | control | 99 | 63 | 0.636 | 0.704 | -0.067 | 0.944 | 0.483 |
| ctl_capitulation_only | control | 143 | 97 | 0.678 | 0.704 | -0.025 | 0.702 | 0.483 |
| bench_bot_200 | benchmark | 96 | 54 | 0.562 | 0.704 | -0.141 | 0.998 | 0.483 |

## Best bottom construction: **lowry_90_90[w5]**  (best of 5 cells by opportunity-set edge)

- raw ratio: **27 of 37** thrust episodes preceded a >=8% rally within 60 days
- precision 0.730 vs equally-distressed base 0.704 = **edge 0.026** pp; OPPORTUNITY-SET null_p = **0.469**  <- the make-or-break number
- vs ALL-days base 0.483 = +0.247 (the base-rate trap — reported, NOT the gate)
- ALT eligibility (within 25d of a 90% down day): precision 0.730 vs base 0.658 = edge 0.071 (null_p 0.291, n=37)
- 15% deeper-rally tier: precision 0.270 vs base 0.246 = edge 0.025 (null_p 0.440, n=37)

## OPPORTUNITY-SET NULL block (the make-or-break test, restated)

- 90/90 thrust precision = 0.730; among equally-distressed days the SAME-COUNT
  random-timing precision averages ~0.704 (the eligible base).
- edge over equally-distressed = **0.026 pp**, null_p = **0.469**.
- VERDICT on the crux: the 90/90 thrust does NOT clear the equally-distressed base at p<0.05 -> the apparent edge is (mostly) the distressed base rate, not the sequence.

## Temporal hold-out (55-year split: discover 1965-1994 / confirm 1995-2020)

- DISCOVER edge -0.094 (null_p 0.851, n=11) | CONFIRM edge 0.017 (null_p 0.548, n=26)

## CONTROLS — the SEQUENCE must beat both pieces (load-bearing)

- ctl_thrust_only       (90% UP, no capitulation): precision 0.636 edge -0.067 null_p 0.944 (n=99)
- ctl_capitulation_only (ANY 90% DOWN = base-rate trap): precision 0.678 edge -0.025 null_p 0.702 (n=143)
- G5 stack-beats-parts (matched count): vs thrust_only diff_p05 0.000 beats=False | vs capitulation_only diff_p05 -0.054 beats=False
- READ: if the controls are about as strong as the sequence, the capitulation->thrust pairing adds nothing.

## Leave-one-episode-out (pooled precision)

- full precision 0.730, eligible base 0.704, min precision after dropping any one episode 0.722, no-single-collapse=True (n_ep=37)

## Confirmatory MULTIPLE-TESTING reality check

- max-stat reality_p across 5 frozen cells (opportunity-set null): **0.943** (V_obs=0.026)

## Benchmark battle (G6) vs bench_bot_200 (GSPC reclaims its 200-day MA), matched count

- lowry_90_90[w5] precision 0.730 (n=37) vs bench_bot_200 0.562 (n=96); diff_p05 0.054 -> beats=True

## Alert budget (G7) — collapsed episodes/year vs the recalibrated cap

- 0.67/yr (cap 1.5, min 0.3) within_cap=True above_min=True

## KILL-GATE (Phase-4, bottom side)

- **BOTTOM VERDICT: NO-GO**
- G1 precision floor (>= base+20pp AND oppset p<0.05): False (edge 0.026, p 0.469)
- G2 confirmatory MTC (reality_p<0.05): False (reality_p 0.943)
- G3 out-of-sample (BOTH halves edge>0): False (discover -0.094, confirm 0.017)
- G4 leave-one-episode-out (no single episode carries the edge): True
- G5 stack beats parts (sequence > both controls, matched): False
- G6 benchmark battle (beats 200-day MA reclaim): True
- G7 alert budget (within cap 1.5/yr): True

> BOTTOM NO-GO = **no demonstrable edge over equally-distressed days**. Ship DESCRIPTIVE-ONLY (display where the 90/90 breadth-thrust state stands today; no predictive-confidence claim, no live alert). This is the honest, expected-possible outcome the pre-registration anticipated. The 55-year window finally gave the test real power — and the SEQUENCE still has to beat the fact that distressed days bounce anyway.
