# M0.3F deterministic research definitions — `INDEX_OPEN_DRIVE_BREADTH`

Version: `M03F_INDEX_OPEN_DRIVE_BREADTH_V2`
Status: **FROZEN FOR OFFLINE RESEARCH**
Date: **2026-09-13 Pacific**

V2 repairs the reviewed V1 gaps before any results: it selects one exact VWAP
mode and fixes the Up Volume observation sequence and share attribution. V1's
protected proof remains historical; V2 protected verification passed; independent acceptance remains pending.

## 1. Scope and authority

The owner's 2026-09-13 research authorization delegates the remaining ordinary
research choices to the agent. This packet freezes one finite first research
version for `INDEX_OPEN_DRIVE_BREADTH`. PLAYBOOKS and TESTING_AND_VALIDATION
incorporate it under their own authority. It does not approve a live alert, an
order, a replay result or a claim of profit.

Use exact values before display rounding. Every input must have event time,
available time, source identity, session identity and a compatible adjustment
basis. A missing mandatory input is `UNKNOWN` and cannot pass. Long and short
rules are exact mirrors unless a row below says otherwise.

## 2. Instruments, window and shared inputs

The primary research instruments are SPY and QQQ. IWM and DIA are separate
secondary rows and cannot be pooled with them. The half-open observation and
entry window is 06:32 through, but excluding, 07:15 Pacific on a regular
session. Drive detection cannot occur before 120 seconds after the first
eligible regular-session trade.

Use `ATR_1M_20_SMA_V1`, `DAILY_ATR_14_SMA_V1` and exactly
`SESSION_VWAP_BAR_HLC3_V1` from M0.3A F-03 for every instrument and breadth
member in every V2 arm. This volume-weighted average uses `(high+low+close)/3`
for each completed one-minute bar, weighted by that bar's share volume. Select
all regular-session minute intervals from the open through the latest interval
ending by evaluation, then require each to be final and available. Reset at
the regular open. Certified no-trade intervals have zero weight; a gap or zero
total volume is `UNKNOWN`. Label this bar estimate in every record. The trade
VWAP mode `SESSION_VWAP_TRADES_V1` is not a V2 alternative or fallback; its
separate source gate stays open. This selection leaves D-090 unchanged.

Use this same bar mode for `VWAP_SLOPE_3M_ATR_V1`: subtract its value at exactly
180 seconds before evaluation from its value at evaluation, and divide by the
positive frozen minute ATR. Each value uses the minute intervals ending by its
own reference time and available by evaluation, as in M0.3E §5. No earlier
regular-session value, incomplete coverage or nonpositive ATR means `UNKNOWN`.
Thus the 120-second drive minimum alone does not satisfy slope warm-up. Use the
same bar mode for VWAP side, consolidation and close-cross checks as well.

The latest positive two-sided quote and eligible trade must
each be no more than 3 seconds old. The quote must not be crossed or delayed.
Spread must be at most 20 basis points. Halt status and the next scheduled
market-wide macro event must be known. An event due in 300 seconds or less
suppresses the setup; an event 301 seconds away does not.

## 3. Point-in-time breadth universes and coverage

Freeze every universe at the evaluation instant. Membership means the set and
weights published for that instant, not today's membership copied backward.
A member is covered only when its regular-session open, current eligible price,
current session VWAP, complete eligible-trade sequence from the regular open
through evaluation as defined in §4.1, and sector label were available by
evaluation. Certified no-trade intervals contribute zero volume; unexplained
gaps are missing. A first trade without a predecessor is a defined neutral
observation, not a missing prior price.

`FULL_CONSTITUENT` uses the complete point-in-time constituent universe of the
traded index for all four components. It requires at least 95% of members and
95% of frozen index weight covered. Every sector represented in the frozen
membership must have at least one covered member. The sector component is the
equal-weight share of those represented sectors whose covered members have a
directional weighted-advance ratio of at least 0.50. Preserve the represented-
sector count; do not pretend an absent index sector is missing data.

`SECTOR_PROXY` uses exactly XLK, XLF, XLY, XLC, XLI, XLV, XLP, XLE, XLU, XLRE
and XLB for all four components. All 11 must be covered. Each ETF has equal
weight for count components. This mode keeps the original 35/30/20/15 weights;
it does not rescale the available parts or claim constituent breadth.

`HYBRID` uses the full point-in-time constituent universe for Advance, Above
VWAP and Up Volume, with the same 95% member and weight coverage. It uses the
11 covered sector ETFs for Sector. All 11 ETFs are required. A record that
meets neither exact mode is `UNKNOWN`; the system may not silently switch modes.

## 4. Breadth components and mirrored direction

Let direction sign `s` be +1 for long and -1 for short. A positive directional
move means `s * (current_price - reference_price) > 0`. Equality is neutral.

- Advance is 100 times the covered-universe weight whose current price has a
  positive directional move from its regular-session open, divided by total
  covered weight. `SECTOR_PROXY` uses equal ETF weights.
- Above VWAP is 100 times covered weight strictly on the directional side of
  the member's same-mode session VWAP, divided by total covered weight.
- Up Volume is the session-to-evaluation directional share-volume percentage
  defined in §4.1. Attribute each trade's own shares using its immediately
  preceding eligible trade price; never classify an entire member's volume
  using only its latest price. For short, use the exact down-volume mirror.
- Sector is the percentage of the frozen sector groups defined for the mode
  that pass their directional advance test. In `SECTOR_PROXY` and `HYBRID`, a
  sector passes when its ETF has a positive directional return from open. In
  `FULL_CONSTITUENT`, use the represented index sectors defined in §3.

`BreadthScore = 0.35*Advance + 0.30*AboveVWAP + 0.20*UpVolume + 0.15*Sector`.
Keep every component, numerator, denominator, member count, covered weight,
universe identity and mode. Missing one component makes the score `UNKNOWN`;
do not rescale. A score of 60 passes. A score of 70 is preferred context only.

### 4.1. Exact Up Volume sequence — `SESSION_DIRECTIONAL_TRADE_VOLUME_V1`

At evaluation time `t`, for each covered member select eligible regular-session
trades with event time in the closed interval `[regular_open, t]` and
availability time at or before `t`. Exclude premarket and prior-session trades.
Use the M0.2 source's frozen trade-condition eligibility mapping; an absent or
unverified mapping blocks this input. A quote or polled last is not a trade
sequence. Each trade needs a unique source trade ID, event time, availability
time, positive price, positive share size and source ordering information.

Deduplicate repeated deliveries of the same trade ID. Apply only cancellations
and corrections available by `t`: remove cancelled trades and use the latest
known corrected version of each surviving trade. Order surviving trades by
event time, then the source's unique sequence order for equal event times.
Conflicting duplicates, unresolved correction references or ambiguous ordering
make the member uncovered. Do not invent a tie order from arrival or price.
Rebuild this as-of sequence for each evaluation, retaining earlier recorded
evaluations unchanged; later information cannot rewrite an earlier result.

Write the ordered prices and share sizes as `(p_i, q_i)`, starting at `i=1`.
For `i>1`, "prior eligible price" means exactly `p_(i-1)` in this member's
sequence, even across a certified no-trade interval. It never means the prior
minute close, prior day's close, first price, or previous different price.
The first trade and all equal-price trades are neutral: their shares enter
the denominator only. Do not carry a previous uptick or downtick across a tie.
For each member `m`, define:

`V_m = sum(q_i for all i)`

`D_m(s) = sum(q_i for i>1 where s*(p_i-p_(i-1)) > 0)`

`UpVolume(s) = 100 * sum(D_m(s)) / sum(V_m)` over the same covered members
used by that mode's Advance and Above VWAP. Use raw shares, without index
weight or dollar-price weighting, including for the 11 sector ETFs. A trade
contributes its own size once; no rolling window, minute-volume substitution,
cumulative-volume snapshot or cross-member price comparison is allowed.
Certified empty intervals add no observation and no shares. Unknown gaps make
the member uncovered under §3; they are never bridged as known empty time.
A zero aggregate denominator is `UNKNOWN`. Preserve each member's numerator,
denominator and sequence/coverage identity with the aggregate.

## 5. Opening drive and efficiency

Freeze the first eligible regular-session trade as `open_price`. Overnight gap
is stored separately and never added to the post-open drive. At evaluation,
`opening_return = s * (last - open_price) / open_price`. It must be at least
`max(0.0015, 0.15 * daily_ATR_pct)`, where
`daily_ATR_pct = DAILY_ATR_14_SMA_V1 / prior_regular_close`. A nonpositive price
or prior close is `UNKNOWN`.

Build the chronological path from `open_price`, each final and available
one-minute close after it, and the current eligible last price. Do not duplicate
the last point when it equals the latest included close. The denominator is the
sum of the absolute change between every adjacent path point.

`drive_efficiency = abs(last - open_price) / path_absolute_change_sum`.

A zero denominator is `UNKNOWN`, including a flat path; it never becomes zero
or one by convention. Efficiency must be at least 0.55. At evaluation, price
must be strictly on the directional side of VWAP and `VWAP_SLOPE_3M_ATR_V1`
must be strictly positive in the trade direction. Zero slope fails.

## 6. Consolidation, retracement and trigger

After drive detection, the first run of two through four contiguous final,
available and traded one-minute bars that stays on the directional side of VWAP
is the microconsolidation. Freeze the drive extreme known immediately before its
first bar. Long pullback depth is that extreme minus the lowest consolidation
low; short depth is the highest consolidation high minus that extreme. Divide
by the absolute drive distance from open to the frozen extreme. A nonpositive
drive distance is `UNKNOWN`.

Retracement from zero through 0.35 is actionable. A value strictly above 0.35
through 0.40 is retained as a shallow-range diagnostic refusal. A value above
0.40 invalidates. This selects 0.35 as the exact action boundary while retaining
the documented 0.40 alternative as a separate recorded comparison boundary.

Freeze `buffer = max($0.01, 0.03 * frozen_ATR_1m)`. Long trigger boundary is
`consolidation_high + buffer`; short is `consolidation_low - buffer`. The first
eligible trade must cross the frozen boundary from the non-triggered side.

Acceptance uses ten fixed one-second samples starting with the crossing second.
The sampled eligible trade must be at or beyond the boundary in the trade
direction for at least seven samples. Every second needs known coverage; bursts
do not create extra samples. The mechanical trigger time is the availability
time of the tenth sample when the test passes; the crossing trade cannot be its
own fill. A bar-only replay may use a separately labeled next-bar proxy, but
cannot satisfy faithful acceptance.

At trigger, BreadthScore, drive efficiency, VWAP side, slope, spread, halt and
macro gates must still pass. The setup expires at 07:15 Pacific. It also becomes
stale before trigger when price extends more than 0.35R beyond the frozen trigger
boundary; exactly 0.35R remains eligible.

## 7. Warning, reduction and suppression

These words have fixed research meanings and never place or resize an order.

- `WARN_NARROW_LEADERSHIP`: the index has a positive directional drive while
  Advance is below 45. The candidate may continue only if BreadthScore is at
  least 60. The warning stays on its record.
- `REDUCED_PRIORITY`: directional distance from open is strictly above
  `0.50 * frozen_daily_ATR`. The mechanical candidate is retained, but excluded
  from the primary arm. A separate inclusive comparison arm keeps it. Equality
  remains in the primary arm.
- `SUPPRESSED_BREADTH_DIVERGENCE`: price makes a strict new directional drive
  extreme while current BreadthScore is at least 15 points below the highest
  prior score frozen during this drive. Equality at a 15-point drop suppresses.
- `SUPPRESSED_VWAP_CHOP`: three or more strict close-side changes around each
  bar's same-mode VWAP from 06:30 through the last completed bar before trigger.
  A close equal to VWAP is neutral, creates no cross and breaks adjacency.

Macro proximity, abnormal spread, halt, unknown mandatory data and a failure of
any trigger gate also suppress action with their own reason. Every suppressed
or reduced event remains in research records.

## 8. Stop, targets and score

Long raw stop is `consolidation_low - 0.05 * frozen_ATR_1m`; short raw stop is
`consolidation_high + 0.05 * frozen_ATR_1m`. Round outward to the known valid
price increment. With sign `s`, `R = s * (entry - stop)` must be positive.

Build the same complete point-in-time structural catalog used by the frozen
research packets: current session HOD/LOD, prior-day high/low and close, and
valid whole-dollar and half-dollar levels. T1 is the nearest level at least
1.5R away. T2 is the nearest distinct later level from 2.5R through 4R. Missing
T1 blocks action. Keep structural, fixed 2R and fixed 3R exits as separate arms;
the fixed arms still require structural T1.

`INDEX_OPEN_DRIVE_SCORE_V1` uses the preserved 45/35/20 weights. Missing a
factor makes the score `UNKNOWN`; do not rescale. Define
`clamp(x)=min(100,max(0,x))`.

`breadth_drop_points` is the nonnegative difference between the highest prior
BreadthScore frozen during this drive and the current score. At the first valid
score it is zero. A missing prior score in a later observation is `UNKNOWN`.

- Drive, 45%: average `clamp(100*(opening_return/required_return-1)/2)`,
  `clamp(100*(efficiency-0.55)/0.45)` and BreadthScore.
- Context, 35%: average BreadthScore,
  `clamp(100*abs(vwap_slope_ATR)/0.20)` and
  `clamp(100*(15-breadth_drop_points)/15)`.
- Execution, 20%: average `100*(20-spread_bps)/20`,
  `100*(3-quote_age_seconds)/3`, `100*(3-trade_age_seconds)/3` and
  `100*(0.35-extension_R)/0.35`.

The final score is the weighted sum. A score at least 65 passes the score arm.
Also retain all mechanical candidates with no score cutoff. This score is a
research rank, not a win probability or a live threshold.

## 9. Outcome and reporting rules

Use the M0.3A O-01 quote-side entry search, delays of 0, 5, 15, 30 and 60
seconds, two equal research units, session-close horizon, missingness and adverse
ordering. The original stop never moves. Structural T1 closes one unit and T2
closes the second; known absence of T2 leaves a session-close runner. Fixed 2R
and 3R policies close both units at their target. Equal availability times
resolve stop before target. A one-minute replay enters at the next bar open and
resolves a bar touching stop and target as stop first; label it
`BAR_PROXY / MODELED_COST_ONLY`.

Report two directions, three breadth modes, two priority policies (primary and
inclusive reduced), and three exit policies as 36 separate cells. Cross these
with five delays, two score populations and two stock-slippage assumptions of
0.5 and 1.0 basis points per side. This freezes 720 primary comparisons. Use the
10-session circular moving-block bootstrap and family threshold
`0.05 / 720 = 1 / 14400`. Report after-cost expectancy, win rate, payoff ratio,
maximum drawdown and candidate frequency with counts and denominators. Keep
mode results separate; do not choose or pool a winner.

Preserve losing, warning, reduced, suppressed, unknown, unfilled, unresolved
and short-borrow-blocked rows. Full and hybrid cells remain unavailable until
their source gates pass. Stock, short-stock and option evidence remain separate.
Reserve exact chronological development, calibration and untouched final dates
from a coverage-only source manifest before opening results.

## 10. Required boundary examples

These examples check definitions. They are not profit evidence.

1. Component values 60, 70, 50 and 80 give BreadthScore 64.0. A score of 60
   passes; 59.999 fails. If Up Volume is missing, the score is `UNKNOWN`, not a
   rescaled value.
2. Covering 95% of members and 95% of weight passes full-mode coverage. Either
   value just below 95% fails. Ten of 11 sector ETFs never become proxy mode.
3. For short direction, a member below its open and below VWAP contributes to
   Advance and Above VWAP. A member equal to either reference is neutral.
4. Path 100.00, 100.20, 100.10, 100.30 has numerator 0.30 and denominator 0.50,
   so efficiency is 0.60 and passes. A flat path has a zero denominator and is
   `UNKNOWN`.
5. With open 100, prior close 100 and daily ATR 2, required opening return is
   0.003. A directional last of 100.30 passes; 100.299 fails before rounding.
6. A drive from 100 to 101 and long consolidation low 100.65 has retracement
   0.35 and passes. A low 100.649 is a diagnostic refusal; a low below 100.60
   invalidates. The short case mirrors the prices.
7. Seven of ten covered samples at or beyond the boundary pass. Six fail. A
   missing second makes faithful acceptance `UNKNOWN`.
8. A prior peak BreadthScore of 75 and current score 60 at a strict new price
   extreme suppresses. A current score 60.001 does not meet the 15-point drop.
9. Directional distance exactly 0.50 daily ATR remains primary. A value one
   valid increment above it is `REDUCED_PRIORITY` and appears only in the
   inclusive comparison arm.
10. One missing membership, weight, sector, bar, quote, VWAP, macro, borrow or
    target-catalog fact stays unavailable. It never becomes favorable evidence.
11. Two completed minute bars with `(H,L,C,shares)` of `(103,99,101,100)`
    and `(106,100,103,300)` have HLC3 values 101 and 103. Their selected
    bar VWAP is `(101*100+103*300)/400 = 102.5`. A partial third minute
    contributes nothing. If a selected completed minute is unavailable, VWAP
    is `UNKNOWN`; an available trade VWAP cannot replace it.
12. One covered member has ordered `(price,shares)` observations
    `(100,10), (101,20), (101,30), (100,40)` since the regular open. Total
    volume is 100 shares. Long Up Volume is 20%; short is 40%. The opening
    10 shares and equal-price 30 shares are neutral. The denominator is not
    just the 60 direction-classified shares, and the final downtick does not
    turn the entire 100 shares into down volume.
13. With `(100,10), (101,20), (100,40)` and the middle trade cancelled by
    evaluation, the surviving sequence is `(100,10), (100,40)`: total volume
    50, long and short numerators both zero. Before that cancellation is
    available, retain the three trades with total 70, long numerator 20 and
    short numerator 40. A known empty interval changes neither result; an
    unexplained gap or unresolved equal-time ordering makes the member
    uncovered. Trades exactly at evaluation are included only if available
    by evaluation; later trades never enter that recorded value.

## 11. Open evidence gates

Full and hybrid modes remain blocked until M0.2 supplies verified point-in-time
constituent membership, weights, minute history and complete coverage. The
sector proxy still requires all 11 ETFs with exact point-in-time inputs. Replay
requires a qualifying source manifest and frozen chronological development,
calibration and untouched final-validation dates. Written definitions and
synthetic boundary checks do not validate an edge or authorize live use. All
switches stay off.
