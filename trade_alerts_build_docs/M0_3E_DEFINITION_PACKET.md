# M0.3E deterministic research definitions — `FIRST_PULLBACK_VWAP`

Version: `M03E_FIRST_PULLBACK_VWAP_V1`  
Status: **FROZEN FOR OFFLINE RESEARCH**  
Date: **2026-09-13 Pacific**

## 1. Scope and authority

The owner's 2026-09-13 research authorization delegates the remaining ordinary
research choices to the agent. This packet freezes one finite first research
version for `FIRST_PULLBACK_VWAP`. PLAYBOOKS and TESTING_AND_VALIDATION
incorporate it under their own authority. It does not approve a live alert, an
order, a replay result or a claim of profit.

Use exact values before display rounding. Every input must have event time,
available time, source identity, session identity and a compatible adjustment
basis. A missing mandatory input is `UNKNOWN` and cannot pass. Long and short
rules are exact mirrors unless a row below says otherwise.

## 2. Shared inputs, window and eligibility

Use `ATR_1M_20_SMA_V1`, `DAILY_ATR_14_SMA_V1`,
`DOLLAR_VOLUME_CLOSE_PROXY20_V1`, `RVOL_OPEN5_MEAN20_V1`,
`RS15_SPY_CLOSE_V1` and one explicitly named M0.3A session VWAP mode. Do not
mix bar and trade VWAP modes in one arm. AVWAP remains context only in V1 and
cannot satisfy a VWAP gate.

The impulse may start at or after 06:30 Pacific. The half-open setup and entry
window is 06:38 through, but excluding, 07:15 Pacific on a regular session.
Price must be at least $5, median daily dollar volume at least $50 million,
spread at most 25 basis points and RVOL at least 1.5. Absolute return from the
first eligible regular-session trade must be at least
`max(0.004, 0.20 * daily_ATR_pct)`, where
`daily_ATR_pct = DAILY_ATR_14_SMA_V1 / prior_regular_close`. A nonpositive
denominator is `UNKNOWN`.

A quote must be positive, two-sided, not crossed, not delayed and no more than
3 seconds old. The latest eligible trade must be no more than 3 seconds old.
Halt status, opposing-material-news status and required interval coverage must
be known. Equality passes every minimum or maximum in this packet unless the
rule expressly uses a strict comparison.

## 3. Impulse and swing confirmation

Feature `FIRST_PULLBACK_IMPULSE_2BAR_V1` uses final, available, contiguous,
traded one-minute bars. For the first structure, the run begins with the 06:30
regular-session bar; if that scheduled bar is not final, available and traded,
the structure is `UNKNOWN`. For a later structure, it begins with the
first bar whose start is at or after the prior structure's terminal instant.
That first bar's open is the origin. For a long, the extreme is the highest
later high; for a short, it is the lowest later low. The extreme must occur
after the origin. The directional distance
must be at least both `0.40 * frozen_ATR_1m` and `0.15 * frozen_daily_ATR`.
The extreme must also be at least `0.25 * frozen_ATR_1m` beyond the selected
VWAP in the impulse direction.

Confirm the extreme only after two consecutive final one-minute bars following
its bar do not make a stricter directional extreme. Equality is not a new
extreme. Each confirmation close must move toward VWAP from the preceding final
close: strictly lower for a long and strictly higher for a short. A later price
cannot move the confirmed
origin, extreme, ATR, VWAP or input IDs. If a new extreme prints before the
second confirmation bar is final, restart the two-bar count from that bar.

The first eligible confirmed impulse of a direction owns the first pullback.
After its pullback reaches a terminal state, a later impulse must begin after
that terminal instant and pass every impulse gate independently to own a second
pullback. Bars and extrema cannot be shared between structures.

Structure identity is `(session, symbol, direction, data_mode, impulse_origin_at,
impulse_extreme_at, impulse_input_ids)`. A correction creates a new as-of
version; it never silently rewrites a frozen event.

## 4. Pullback counting, depth and volume

The pullback starts with the first final one-minute bar after the impulse extreme
whose low is below the preceding bar's low for a long, or whose high is above
the preceding bar's high for a short. It ends at trigger, invalidation or expiry.
Its ordinal is the count of independently confirmed directional impulse/pullback
structures in the same session: first and second are retained separately; a
third and later structure is recorded and suppressed.

For a long, pullback depth is `impulse_extreme - lowest_pullback_low`; for a
short it is `highest_pullback_high - impulse_extreme`. Retracement is depth
divided by impulse distance. A nonpositive impulse distance is `UNKNOWN`.
Actionable retracement is from 0.20 through 0.65. The 0.30 through 0.50 band is
recorded as preferred context, not a separate pass gate. A value above 0.65
through 0.70 is a known deep diagnostic refusal. A value strictly above 0.70
invalidates the structure. This resolves the old 0.65–0.70 conflict without
changing either documented boundary.

Feature `PULLBACK_VOLUME_PER_MINUTE_RATIO_V1` is:

`(pullback eligible shares / pullback covered seconds) /
 (impulse eligible shares / impulse covered seconds)`

Both legs use the same eligible-trade rules and all covered seconds from their
half-open windows. Certified no-trade time contributes zero shares and covered
seconds. An unexplained gap, nonpositive duration or nonpositive impulse rate is
`UNKNOWN`. The ratio must be at most 0.80. A raw total-volume ratio may be
reported but cannot satisfy this duration-normalized gate.

## 5. VWAP slope, crosses and support

Feature `VWAP_SLOPE_3M_ATR_V1` freezes the selected session VWAP at trigger and
subtracts its value exactly 180 seconds earlier, then divides by the frozen
minute ATR. Both values require complete same-mode input coverage and must have
been available by trigger. Long requires the value strictly above zero; short
requires it strictly below zero. Zero fails. A nonpositive ATR is `UNKNOWN`.

Feature `VWAP_CLOSE_CROSSES_V1` uses final one-minute closes from 06:30 through
the last completed bar before trigger. A cross occurs only when two consecutive
known closes are on strict opposite sides of VWAP measured for their own bar.
A close equal to VWAP is neutral: it creates no cross and breaks adjacency.
The count is directional-independent. Three crosses pass; four or more
invalidate. Missing coverage makes the count `UNKNOWN`.

At trigger, price must be strictly above VWAP for long and below it for short.
The pullback extreme must be within `0.15 * frozen_ATR_1m` of VWAP by absolute
distance and may not pass more than `0.10 * frozen_ATR_1m` through VWAP against
the trade direction. Thus a long low may equal `VWAP - 0.10 ATR`; the short
mirror may equal `VWAP + 0.10 ATR`.

## 6. Reversal bar, trigger and priority arms

The reversal bar is the first final, available, traded one-minute pullback bar
after retracement first reaches 0.20 that closes in the trade direction and
beyond the prior final bar's close. Long requires `close > open` and
`close > prior_close`; short requires `close < open` and `close < prior_close`.
Freeze its high, low, end time and input ID when it becomes available.

Freeze `buffer = max($0.01, 0.03 * frozen_ATR_1m)`. Long trigger is the first
eligible trade crossing the frozen `reversal_bar_high + buffer` with
`previous < boundary <= current`. Short uses
`reversal_bar_low - buffer` with `previous > boundary >= current`. A moving
boundary is not a crossing. The confirming trade cannot be its own fill.

At trigger, all context, retracement, volume, support, VWAP, relative-strength,
spread, halt and news gates must still pass. Long requires `RS15_SPY_CLOSE_V1`
strictly above zero; short requires it strictly below zero. Tape acceleration
over the prior 15 seconds is recorded when faithful tape exists, but the old
approximate 1.3 preference is not an actionable gate in V1.

Keep two priority arms separate. `FIRST_PULLBACK_ONLY_V1` admits ordinal one and
preserves the mandatory first-pullback prior. `FIRST_AND_SECOND_PULLBACK_V1`
admits ordinals one and two, labels ordinal two `LOWER_PRIORITY`, and reports
them separately. It cannot pool ordinal two with ordinal one or silently replace
the first-only prior. Ordinal three and later are suppressed in both arms.

## 7. Stop, targets and staleness

Long raw stop is `pullback_low - 0.05 * frozen_ATR_1m`; short raw stop is
`pullback_high + 0.05 * frozen_ATR_1m`. Round outward to the known valid price
increment: down for long and up for short. An unknown increment makes risk
`UNKNOWN`. With direction sign `s` equal to +1 long and -1 short,
`R = s * (entry - stop)` must be positive.

Build one complete structural target catalog at trigger from the frozen impulse
extreme, regular-session HOD/LOD available at trigger, prior-day high/low and
close, and known whole-dollar and half-dollar levels between entry and the
furthest supplied structural level. Keep only levels ahead in the trade
direction, merge exact prices while retaining every label, and sort by
directional distance. T1 is the nearest level at least 1.5R away. T2 is the
nearest distinct later level from 2.5R through 4R. No T1 blocks action. A
complete catalog with no qualifying T2 records known absence; an incomplete
catalog is `UNKNOWN` and blocks action.

Keep three exit policies as separate result arms. `FIRST_PULLBACK_STRUCTURAL_V1`
uses T1 and T2 above. `FIRST_PULLBACK_FIXED_2R_V1` exits both research units at
2R. `FIRST_PULLBACK_FIXED_3R_V1` exits both at 3R. Both fixed policies still
require structural T1, so they compare exits rather than admit another setup.
No result selects a winner or changes the structural prior.

A structure expires at 07:15 Pacific. It also becomes stale before trigger if
price extends more than 0.40R beyond the reversal-bar boundary in the trade
direction; exactly 0.40R remains eligible. A triggered mechanical event is
immutable.

## 8. Research score

Score `FIRST_PULLBACK_VWAP_SCORE_V1` is frozen only at trigger. Define
`clamp(x)=min(100,max(0,x))`. Missing any factor makes the score `UNKNOWN`; do
not rescale.

- Setup, weight 50%: impulse strength
  `clamp(100*(impulse_ATR-0.40)/0.60)`; retracement quality
  `clamp(100*(0.65-abs(retracement-0.40))/0.65)`; volume contraction
  `clamp(100*(0.80-volume_ratio)/0.80)`. Average the three.
- Context, weight 30%: directional VWAP slope
  `clamp(100*abs(slope_ATR)/0.20)`; directional RS
  `clamp(100*abs(RS15)/0.01)`; VWAP support proximity
  `clamp(100*(0.15-support_distance_ATR)/0.15)`. Average the three.
- Execution, weight 20%: spread quality `100*(25-spread_bps)/25`; quote
  freshness `100*(3-quote_age_seconds)/3`; trade freshness
  `100*(3-trade_age_seconds)/3`; staleness headroom
  `100*(0.40-extension_R)/0.40`. Average the four.

`final_score = 0.50*setup + 0.30*context + 0.20*execution`. Keep every raw
factor. A final score at least 65 passes the score-threshold research arm. Also
retain all mechanical candidates with no score cutoff. The score is a research
rank, not a win probability or a live threshold.

## 9. Outcome and reporting rules

Measure the stock setup with two equal research units. Use the M0.3A O-01 entry
search, quote-side fills, delays of 0, 5, 15, 30 and 60 seconds, session-close
horizon, missingness and adverse ordering. At entry, the frozen stop and 0.40R
staleness rule must still pass.

The structural policy closes one unit at T1 and the second at T2 when present;
known absence of T2 makes the second unit a session-close runner. Each fixed
policy closes both units at its target. The original stop never moves and closes
every open unit. Long exits use bid and short exits use ask. Equal availability
times resolve adversely: stop before target. With only one-minute bars, enter at
the next bar open, check an opening gap first and resolve a bar touching stop and
target as stop first; label it `BAR_PROXY / MODELED_COST_ONLY`.

Keep gross and after-cost results separate. Quote sides already include spread,
so do not charge it twice. Report 0.5 basis points per side plus a 1.0 basis
point per-side harsh sensitivity for stock slippage; stock commission is $0.
Executable short results additionally require point-in-time borrow availability
and cost. Without it, retain only a labeled directional result. Option outcomes
remain separate and require exact contract, multiplier, bid/ask, size, expiry
and fee evidence.

Report two directions, two priority policies and three exit policies separately:
12 policy arms. The comparison policy's first and second ordinals stay separate,
so the result table has 18 direction/priority/ordinal/exit cells before other
slices. Cross those cells with five delays, two score populations (all mechanical
and score at least 65) and two stock-slippage assumptions (0.5 and 1.0 basis
points per side). This freezes exactly 360 primary comparisons. Use the existing
10-session circular moving-block bootstrap and a family threshold of
`0.05 / 360 = 1 / 7200`; show unadjusted intervals too, but do not promote from
them. Regime and tape-acceleration slices are descriptive and cannot create a
winner.

Each cell reports after-cost expectancy, win rate, payoff ratio, maximum
drawdown and candidate frequency with counts and denominators. Preserve losing,
unknown, unfilled, halted, unresolved and suppressed rows. Reserve exact
chronological development, calibration and untouched final dates from a
coverage-only source manifest before opening results.

## 10. Required boundary examples

These examples check definitions. They are not profit evidence.

1. With minute ATR 1.00 and daily ATR 4.00, the impulse must be at least 0.60.
   A 0.60 move passes; 0.599 fails. A new equal high does not restart swing
   confirmation, while a high one valid price increment above it does.
2. A long extreme at 101.00 from origin 100.00 and pullback low 100.35 gives
   retracement 0.65 and passes. Low 100.349 gives more than 0.65 and is a deep
   refusal; low 100.30 gives 0.70 and remains refused; below 100.30 invalidates.
   The short case mirrors these prices.
3. Impulse volume 6,000 shares over 300 covered seconds and pullback volume
   2,400 over 150 seconds give rates of 20 and 16 shares per second and a ratio
   of 0.80, which passes. Using
   raw totals would give 0.40 and is not permitted.
4. VWAP 100.20 now and 100.10 exactly 180 seconds earlier with ATR 0.50 gives
   long slope 0.20 ATR and passes. Equal VWAP values fail. A missing intervening
   mode record makes slope `UNKNOWN`.
5. Closes above, below, equal, above VWAP produce no cross across the equal
   close. Three strict side changes pass; the fourth invalidates.
6. VWAP 100.00 and ATR 0.50 allow a long pullback low at 99.95. A low at 99.949
   fails the armed-side gate. A low at 100.075 is exactly 0.15 ATR from VWAP and
   passes the support-distance gate.
7. A long reversal high of 100.50 and ATR 0.50 give buffer 0.015 and boundary
   100.515. A move from 100.514 to 100.515 crosses; equality on the previous
   observation does not create a new crossing. The short mirror uses the low.
8. Ordinal one passes both priority arms. Ordinal two is refused by
   `FIRST_PULLBACK_ONLY_V1` and retained as `LOWER_PRIORITY` by the comparison
   arm. Ordinal three is suppressed by both.
9. Long entry 100.60, pullback low 100.00 and ATR 0.50 give raw stop 99.975.
   With a $0.01 increment the outward stop is 99.97. Fixed targets are 101.86
   at 2R and 102.49 at 3R after using the rounded stop.
10. One missing quote, bar, VWAP, RS, news, borrow or target-catalog fact stays
    unavailable. It never becomes a favorable input or a win.

## 11. Open evidence gates

The definitions are frozen, but replay remains blocked until M0.2 publishes a
qualifying point-in-time source manifest and exact chronological development,
calibration and untouched final-validation dates. Faithful trigger evidence
requires sub-minute trades and quotes; bar data proves only its labeled proxy.
Borrow and option facts block only their executable arms. All switches stay off.
