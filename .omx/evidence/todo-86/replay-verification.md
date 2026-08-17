# TODO #86 — historical replay verification

**Run:** 2026-08-17 · **Code under test:** `consensus_engine/alerts/commands.py::compute_vvix_lead_streak`
**Data:** all 23 rows of `vol_of_vol_daily`, 2026-07-15 .. 2026-08-14

## 1. Replay against an independent recomputation

Every date was replayed by feeding the function the rows available up to that date (newest-first, exactly as `get_recent_rows` returns them) and comparing its output to the independently precomputed values in `precomputed-lead-streak.json`.

**Result: 22 dates checked, 0 mismatches.**

The raw daily percentage changes were also recomputed from the stored VVIX/VIX closes ((new-old)/old*100) and agree with the stored values on all 22 dates.

| date | day | VVIX chg | VIX chg | lead pts (code) | lead pts (independent) | direction | streak | |
|---|---|---|---|---|---|---|---|---|
| 2026-07-16 | Thu | +5.94% | +6.76% | -0.8200 | -0.8200 | — | 0 | match |
| 2026-07-17 | Fri | +7.77% | +12.19% | -4.4247 | -4.4247 | — | 0 | match |
| 2026-07-20 | Mon | -1.95% | -0.64% | -1.3155 | -1.3155 | down | 1 | match |
| 2026-07-21 | Tue | -6.30% | -8.58% | +2.2768 | +2.2768 | — | 0 | match |
| 2026-07-22 | Wed | -0.82% | -2.40% | +1.5847 | +1.5847 | — | 0 | match |
| 2026-07-23 | Thu | +6.93% | +12.38% | -5.4515 | -5.4515 | — | 0 | match |
| 2026-07-24 | Fri | -1.41% | -0.64% | -0.7677 | -0.7677 | down | 1 | match |
| 2026-07-27 | Mon | +0.18% | +0.48% | -0.3057 | -0.3057 | — | 0 | match |
| 2026-07-28 | Tue | -2.38% | -2.46% | +0.0855 | +0.0855 | — | 0 | match |
| 2026-07-29 | Wed | +11.13% | +13.45% | -2.3284 | -2.3284 | — | 0 | match |
| 2026-07-30 | Thu | -13.53% | -17.28% | +3.7509 | +3.7509 | — | 0 | match |
| 2026-07-31 | Fri | -3.19% | -6.44% | +3.2461 | +3.2461 | — | 0 | match |
| 2026-08-03 | Mon | -0.91% | -0.81% | -0.0927 | -0.0927 | down | 1 | match |
| 2026-08-04 | Tue | +1.94% | +4.04% | -2.0972 | -2.0972 | — | 0 | match |
| 2026-08-05 | Wed | -2.31% | -4.18% | +1.8701 | +1.8701 | — | 0 | match |
| 2026-08-06 | Thu | -1.89% | -4.17% | +2.2836 | +2.2836 | — | 0 | match |
| 2026-08-07 | Fri | +1.92% | -1.65% | +3.5663 | +3.5663 | — | 0 | match |
| 2026-08-10 | Mon | +2.31% | +3.76% | -1.4470 | -1.4470 | — | 0 | match |
| 2026-08-11 | Tue | -1.74% | -1.16% | -0.5761 | -0.5761 | down | 1 | match |
| 2026-08-12 | Wed | -2.64% | -4.78% | +2.1372 | +2.1372 | — | 0 | match |
| 2026-08-13 | Thu | +1.04% | +0.55% | +0.4897 | +0.4897 | up | 1 | match |
| 2026-08-14 | Fri | -2.17% | -2.60% | +0.4279 | +0.4279 | — | 0 | match |

## 2. Streaks actually present in the real data

- Days with NO same-direction lead: **17 of 22**
- Days with an upward lead: **1** — all of streak length 1
- Days with a downward lead: **4** — all of streak length 1
- **Three-day upward lead streaks: 0**
- **Two-day downward lead streaks: 0**

The longest same-direction lead streak anywhere in the 23 real market days is **one day**.

## 3. What VIX did next (raw counts only)

The owner specifically asked whether a three-day VVIX lead foreshadows higher volatility. It cannot be answered from this data: there are zero such streaks. For completeness, here is what VIX did after every single-day lead. These are raw counts, deliberately not percentages — the sample is far below the 10 resolved cases needed to claim any rate.

- After a upward lead day, next 1 session(s): VIX higher **0**, lower or flat **1**, out of **1** resolved case(s).
- After a upward lead day, next 5 session(s): VIX higher **0**, lower or flat **0**, out of **0** resolved case(s).
- After a downward lead day, next 1 session(s): VIX higher **2**, lower or flat **2**, out of **4** resolved case(s).
- After a downward lead day, next 5 session(s): VIX higher **1**, lower or flat **2**, out of **3** resolved case(s).

## 4. Conclusion

The calculation is correct: it reproduces an independent recomputation exactly on every date.

The predictive question is **unanswerable with the data that exists** — not answered and negative, but unanswerable, because no qualifying three-day streak has ever occurred in the stored history. The card therefore states the streak as a plain fact and contains no foreshadowing or predictive wording, which is what the owner decided.

A practical consequence worth knowing: with the current 23 days of history, the card will show 'No same-direction VVIX lead today' on 17 of 22 days and a one-day streak on the rest. A multi-day streak is possible but has not yet occurred.
