# M0.3C deterministic research definitions — `HOD_COMP_RS`

Version: `M03C_HOD_COMP_RS_V1`  
Status: **FROZEN FOR OFFLINE RESEARCH**  
Date: **2026-09-13 Pacific**

## 1. Scope and authority

The owner's 2026-09-13 research authorization delegates the remaining ordinary
research choices to the agent. This packet freezes one finite first research
version for `HOD_COMP_RS`. PLAYBOOKS and TESTING_AND_VALIDATION incorporate it
under their own authority. It does not approve a live alert, an order, a replay
result or a claim of profit.

Use exact values before display rounding. Every input must have event time,
available time, source identity, session identity and a compatible adjustment
basis. A missing mandatory input is `UNKNOWN` and cannot pass. Long and short
rules are exact mirrors unless a row below says otherwise.

## 2. Shared inputs and evaluation window

Use `ATR_1M_20_SMA_V1`, `DAILY_ATR_14_SMA_V1`,
`DOLLAR_VOLUME_CLOSE_PROXY20_V1` and one explicitly named session VWAP mode from
M0.3A. Use `RVOL_OPEN5_MEAN20_V1` for the unqualified RVOL gate. Do not mix the
bar and trade VWAP modes in one arm.

The half-open setup and entry window is 06:40 through, but excluding, 07:15
Pacific on a regular session. A pending structure expires at 07:15. Price must
be at least $5, median daily dollar volume at least $50 million, spread at most
20 basis points, RVOL at least 1.5, and absolute return from the first eligible
regular-session trade at least
`max(0.005, 0.20 * DAILY_ATR_14_SMA_V1 / prior_regular_close)`.

A quote must be positive, two-sided, not crossed, not delayed and no more than
3 seconds old. The last trade must be no more than 3 seconds old. Halt status
and required interval coverage must be known. Equality passes every minimum or
maximum in this packet unless the rule expressly uses a strict comparison.

## 3. Relative strength and trend

Feature `RS15_SPY_CLOSE_V1` uses exactly the first 15 completed regular-session
one-minute bars of the current session for both the stock and SPY. It freezes
when the fifteenth bar is final and available. For each instrument:

`return15 = fifteenth_bar_close / first_bar_open - 1`

`RS15 = stock_return15 - SPY_return15`

Before both complete 15-bar windows are available, RS15 is `UNKNOWN`; no shorter
warm-up is allowed. A missing or revised required bar makes the affected as-of
version `UNKNOWN`. SPY is the benchmark for equities and ETFs in V1; sector
relative strength is recorded as context only.

Long requires price strictly above the chosen session VWAP and
`RS15 >= max(0.003, 0.15 * daily_ATR_pct)`. Short requires price strictly below
VWAP and `RS15 <= -max(0.003, 0.15 * daily_ATR_pct)`. Here
`daily_ATR_pct = DAILY_ATR_14_SMA_V1 / prior_regular_close`; a nonpositive or
missing prior close is `UNKNOWN`.

## 4. Compression seed and frozen reference

Feature `HOD_COMP_RS_COMPRESSION_3X7_V1` uses final, available, traded regular-
session one-minute bars. Certified no-trade minutes and unexplained missing
minutes break contiguity; they are never skipped.

At each completed-minute endpoint, the recent window is the last three bars.
The prior window is the seven bars immediately before those three. The windows
do not overlap. A seed exists when all ten bars are contiguous and:

`recent_range / prior_range <= 0.60`

where each range is `max(high) - min(low)`. A zero prior range makes the ratio
`UNKNOWN`. The compression begins at the start of the oldest recent bar. The
reference HOD and LOD are the extrema of all final, available traded regular-
session bars from the session open through the last bar ending at or before that
start. Their values and input IDs are frozen at that start; later session highs
or lows never rewrite them.

The seeded three-bar compression may extend through five more contiguous bars,
for a maximum of eight. Each extension must keep the full compression range no
wider than the seed's three-bar range and must remain on the permitted side of
the frozen reference: compression high at or below frozen HOD for long, or
compression low at or above frozen LOD for short. A wider bar, a bar beyond the
reference, a missing interval, the eighth bar, or session-window expiry closes
the structure. A crossing may occur after the three-bar seed is known and no
later than the end of the eighth bar. The structure cannot be redrawn around a
breakout bar.

At evaluation, long distance is
`(frozen_HOD - compression_high) / frozen_ATR_1m`; short distance is
`(compression_low - frozen_LOD) / frozen_ATR_1m`. It must be from 0 through
0.35. Long must also have last trade at or above
`frozen_HOD - 0.20 * frozen_ATR_1m`; short must be at or below
`frozen_LOD + 0.20 * frozen_ATR_1m`. Freeze ATR at seed detection.

Structure identity is `(session, symbol, direction, mode, compression_start,
reference_input_ids)`. A bar belongs to at most one active structure per
direction. Permit two started structures per session and direction. A structure
that fails or expires still counts.

## 5. Heads-up, crossing, acceptance and participation

Freeze `buffer = max($0.01, 0.04 * frozen_ATR_1m)`. Long boundary is
`frozen_HOD + buffer`; short boundary is `frozen_LOD - buffer`. A long crossing
requires consecutive covered observations `previous < boundary <= current`.
Short uses `previous > boundary >= current`. A boundary moving because an input
changed is not a crossing.

Emit at most one heads-up per structure after all non-crossing gates pass when
the fresh last trade is from 0 through 0.20 ATR from the reference on its
compression side. A jump may cross without a heads-up.

At crossing time `t0`, freeze the structure, boundary, ATR and mode. Evaluate
once per second from `t0+10` through `t0+30`, inclusive. Each evaluation uses
exactly ten fixed-grid samples at `t-9` through `t`. All ten must be known and
at least seven must be at or beyond the frozen boundary. A message burst cannot
create extra samples. The fresh last trade must still be beyond the boundary at
trigger.

Two separate research modes are required:

- `HOD_COMP_RS_TAPE_V1` samples the latest eligible trade, no more than 3
  seconds old. `INTENSITY_15S_MEAN20_HOD_V1` is eligible executed shares in
  `(t-15s,t]` divided by the mean for the identical session-relative interval
  in the prior 20 sessions. Complete same-basis tape coverage and a positive
  denominator are required. A value at least 1.40 passes.
- `HOD_COMP_RS_QUOTE_PROJECTED_V1` samples a fresh quote midpoint and requires
  the fresh last trade beyond the boundary. It uses the M0.3A projected-current-
  minute formula, with at least 10 elapsed seconds, complete current-minute
  volume and the prior-20 corresponding-minute reference. A projected ratio at
  least 1.40 passes. This is quote acceptance and projected volume, not tape
  proof.

Do not switch modes inside a structure or pool their results. If no window
passes by `t0+30`, the structure fails. A final one-minute close strictly back
through the reference level, a halt, unknown mandatory coverage, or the eighth
compression bar without a trigger invalidates it. After any trigger, the same
direction needs ten minutes from the mechanical event before a new structure;
equality passes. One actionable event is allowed per structure.

## 6. Stop, targets, staleness and score

At trigger, long raw stop is
`compression_low - 0.05 * frozen_ATR_1m`; short raw stop is
`compression_high + 0.05 * frozen_ATR_1m`. Round outward to the known valid
price increment: down for long and up for short. Unknown increment makes risk
`UNKNOWN`. Entry `E` is the latest eligible trade at the mechanical trigger.
With direction sign `s` equal to +1 long and -1 short,
`R = s * (E - stop)` must be positive.

Fixed research targets are `T1 = E + s * 1.5R` and
`T2 = E + s * 2.5R`. They do not claim structural liquidity. A structure is
stale when `s * (E - boundary) / R > 0.40`; exactly 0.40 remains eligible.

Score `HOD_COMP_RS_SCORE_V1` is frozen only at trigger. Clamp every factor to
0–100. Missing any factor makes the score `UNKNOWN`; do not rescale.

- Setup, weight 50%: compression quality
  `100*(0.60-ratio)/0.60`; reference proximity
  `100*(0.35-distance)/0.35`; RS strength
  `100*(abs(RS15)-rs_min)/rs_min`. Average the three.
- Context, weight 30%: RVOL excess `100*(RVOL-1.5)/1.5`; open-move excess
  `100*(abs(open_return)-open_min)/open_min`. Average the two.
- Execution, weight 20%: acceptance excess
  `100*(acceptance-0.70)/0.30`; participation excess
  `100*(participation-1.40)/1.40`; spread quality
  `100*(20-spread_bps)/20`. Average the three.

`final_score = 0.50*setup + 0.30*context + 0.20*execution`. Keep every raw
factor. A final score at least 65 passes this research arm. This cutoff is a
preregistered comparison rule, not a validated production threshold.

## 7. Outcome rules

Measure the stock setup with two equal research units. At the first eligible
entry observation after a requested delay, long enters at ask and short at bid.
The observation must remain inside the entry window and pass the frozen stop,
boundary and 0.40R staleness rules. Test mechanical delays 0, 5, 15, 30 and 60
seconds separately. Do not use one confirming observation as its own fill.

T1 closes one unit and T2 closes the other. The original stop never moves. A
stop closes every open unit. Long exits use bid and short exits use ask. Exact
quote event order controls. Equal availability times resolve adversely: stop
before target. If only one-minute bars exist, use the next bar open as entry,
evaluate an opening gap first, and resolve a bar touching stop and target as
stop first; label that arm `BAR_PROXY / MODELED_COST_ONLY`.

At the regular-session close, close a remaining stock unit with the first valid
exit-side quote at or after the close and available within three seconds. If it
does not exist, the unit is unresolved. Never carry the position overnight.
Keep gross and after-cost results separate. Quote sides already include spread,
so do not charge it twice. Report 0.5 basis points per side plus a 1.0 basis
point per-side harsh sensitivity for stock slippage; stock commission is $0.
Short executable results also require point-in-time borrow availability and
cost. Without it, retain only a labeled directional result.

Option outcomes are a separate later arm. Missing exact contract, multiplier,
bid/ask, size, expiry or fee evidence cannot change the stock result. Unknown,
unfilled, halted, partially resolved and ambiguous outcomes stay in counts and
denominators and never become wins.

## 8. Required reporting and boundary examples

Report each direction and data mode separately by after-cost expectancy, win
rate, payoff ratio, maximum drawdown and candidate frequency, with counts and
denominators. Report the score threshold arm and an all-mechanical-candidates
diagnostic separately. Preserve losing arms. Reserve chronological development,
calibration and untouched final dates from a coverage-only source manifest
before opening results. Missing source coverage blocks the affected evidence,
not these written definitions.

The following are definition checks, not profitability evidence:

1. Ten consecutive bars are required. Recent highs/lows 100.00/99.70 and prior
   highs/lows 100.20/99.70 give 0.30/0.50 = 0.60 and seed. A ratio above 0.60
   fails. The recent three are not part of the prior seven.
2. A seed begins at 06:40. The HOD known through 06:40 is 100.00. A later 100.30
   does not rewrite it. The short mirror freezes the then-known LOD.
3. With HOD 100.00 and ATR 0.50, long compression high 99.825 is exactly 0.35
   ATR away and passes. 99.824 fails. Short uses LOD 100.00 and compression low
   100.175; equality also passes.
4. Fifteen stock bars return 0.80%, SPY returns 0.20%, and daily ATR percent is
   2.00%. RS15 is 0.60%; the minimum is max(0.30%, 0.30%) = 0.30%, so long
   passes. Fourteen completed bars make RS15 `UNKNOWN`. Short mirrors signs.
5. ATR 0.50 gives buffer 0.02. HOD 100.00 gives long boundary 100.02. A move
   100.01 to 100.02 crosses; 100.02 to 100.03 does not create a fresh crossing.
   The short mirror uses 99.98.
6. Seven of ten fixed-grid samples at the boundary pass acceptance at 0.70. Six
   fail. One unknown sample makes the window unknown. One hundred messages in
   one second still supply one sample.
7. Participation 1.40 passes in both named modes; 1.399 fails. Tape evidence
   cannot fill a missing projected-volume arm or the reverse.
8. Long compression low 99.80 and ATR 0.40 give raw stop 99.78. With a $0.01
   increment the stop stays 99.78. Entry 100.00 gives R 0.22, T1 100.33 and T2
   100.55. Short entry 100.00 and compression high 100.20 give stop 100.22,
   T1 99.67 and T2 99.45.
9. Long boundary 100.00, entry 100.20 and R 0.50 give extension 0.40 and pass;
   entry 100.201 is stale. The short mirror uses boundary 100.00, entry 99.80
   and the same R.
10. A bar with long stop 99.50 and T2 101.25 that trades both records the stop
    first. Missing short borrow blocks executable short expectancy but leaves
    the directional row. Missing option quotes do not alter the stock row.
