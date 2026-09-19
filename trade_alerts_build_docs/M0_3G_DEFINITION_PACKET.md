# M0.3G deterministic research definitions — `GAP_FADE_FAILED_OPEN`

Version: `M03G_GAP_FADE_FAILED_OPEN_V1`  
Status: **FROZEN FOR OFFLINE RESEARCH**  
Date: **2026-09-13 Pacific**

## 1. Scope and authority

The owner's 2026-09-13 research authorization delegates the remaining ordinary
research choices to the agent. This packet freezes one finite first research
version for `GAP_FADE_FAILED_OPEN`. PLAYBOOKS and TESTING_AND_VALIDATION
incorporate it under their own authority. It does not approve a live alert, an
order, a replay result or a claim of profit.

Use exact values before display rounding. Every input must have event time,
available time, source identity, session identity and a compatible adjustment
basis. A missing mandatory input is `UNKNOWN` and cannot pass. Gap-up fades and
gap-down fades are exact mirrors under the direction sign defined below.

## 2. Shared inputs, gap and liquidity

Use `ATR_1M_20_SMA_V1`, `DAILY_ATR_14_SMA_V1`,
`DOLLAR_VOLUME_CLOSE_PROXY20_V1` and exactly `SESSION_VWAP_BAR_HLC3_V1` from
M0.3A. Trade VWAP is not a V1 alternative or fallback. Use
`RS_OPEN_SPY_V1` from §5 and the point-in-time catalyst class in §6.

Let `g` be +1 for a gap up and -1 for a gap down. Let fade direction `s = -g`.
Freeze the first eligible regular-session trade as `open_price` and the prior
regular-session adjusted close as `prior_close`.

`gap_dollars = open_price - prior_close`

`gap_pct = abs(gap_dollars) / prior_close`

`gap_ATR = abs(gap_dollars) / DAILY_ATR_14_SMA_V1`

A positive gap needs `gap_dollars > 0`; a negative gap needs
`gap_dollars < 0`. Equality is not a gap. Require `gap_pct >= 0.01` or
`gap_ATR >= 0.25`. A nonpositive price or ATR is `UNKNOWN`.

Price must be at least $5 and 20-session median daily dollar volume at least
$50 million. The latest positive two-sided quote must not be crossed or delayed,
must be no more than 3 seconds old and must have spread at most 20 basis points.
The latest eligible trade must be no more than 3 seconds old. Premarket dollar
volume of at least $5 million is preferred recorded context, not a V1 gate.
Halt status and the valid price increment must be known.

The setup can first be evaluated at 06:33 Pacific and expires at 07:15 Pacific.
The entry window is half-open: 06:33 through, but excluding, 07:15. One
actionable event is allowed per `(session, symbol, gap_direction, open_price)`.

## 3. Exact opening extension — `GAP_OPEN_EXTENSION_3M_V1`

The opening-extension window is the half-open interval from 06:30 through, but
excluding, 06:33 Pacific. It contains exactly the three scheduled one-minute
intervals beginning at 06:30, 06:31 and 06:32. All three must be final and
available before the extension is decided. A certified no-trade minute adds no
extreme; an unexplained missing minute makes the feature `UNKNOWN`. At least one
eligible trade is required.

For a gap up, freeze `opening_extreme` as the highest eligible trade in the
window and set `opening_extension = opening_extreme - open_price`. For a gap
down, freeze the lowest eligible trade and set
`opening_extension = open_price - opening_extreme`. Values below zero become
zero because movement toward the prior close is not continuation extension.

Freeze `extension_limit = max(0.15 * abs(gap_dollars),
0.20 * ATR_1M_20_SMA_V1)` at 06:33. `EXTENSION_FAILED` requires
`opening_extension <= extension_limit`; equality passes. A later session high
or low cannot rewrite the frozen opening extreme or extension result.

## 4. Loss of open and failed reclaim — `GAP_FAILED_RECLAIM_V1`

After `EXTENSION_FAILED`, the loss-of-open bar is the first final, available,
traded one-minute bar whose close is strictly in the fade direction from the
open and is on or beyond its same-time bar VWAP in the fade direction. In sign
form it requires `s * (close - open_price) > 0` and
`s * (close - vwap) >= 0`. A close equal to the open does not qualify. Equality
to VWAP passes. Freeze that bar and its available time.

A reclaim attempt must occur after the loss-of-open bar. It begins with the
first later final, available, traded one-minute bar whose range reaches the open
from the fade side: high at least the open after a gap up, or low at most the
open after a gap down. A temporary move that never reaches the open is not a
reclaim attempt.

The failed-reclaim bar is the first final, available, traded bar at or after the
attempt begins that closes strictly back in the fade direction from both the
open and its same-time bar VWAP. In sign form,
`s * (close - open_price) > 0` and
`s * (close - vwap) > 0`. It must end and be available no later than 180 seconds
after the loss-of-open bar's end; equality passes. A later bar is retained as a
diagnostic but cannot arm V1. An unexplained missing scheduled minute between
the two bars makes the result `UNKNOWN`.

Freeze the adverse reclaim extreme from the first eligible trade after the
loss-of-open bar through the failed-reclaim bar: the highest trade for a gap-up
short and the lowest trade for a gap-down long. The failed-reclaim bar, window,
VWAP values and source IDs cannot be revised in place by later data.

## 5. From-open relative strength and trigger

`RS_OPEN_SPY_V1` uses the stock and SPY first eligible regular-session trades
and their latest eligible trades at the same evaluation instant:

`stock_return = stock_last / stock_open - 1`

`spy_return = spy_last / spy_open - 1`

`rs_from_open = stock_return - spy_return`

Both opens and current trades must be positive, no more than 3 seconds stale at
their own use, and available by evaluation. They must share the session and a
compatible adjustment basis. Missing SPY or stock input makes RS `UNKNOWN`.
For a gap-up short, require `rs_from_open < 0`. For a gap-down long, require
`rs_from_open > 0`. Zero fails both directions.

`VWAP_SLOPE_3M_ATR_V1` uses the selected bar VWAP at evaluation minus its value
at exactly 180 seconds earlier, divided by the positive frozen minute ATR. Each
VWAP uses all final regular-session minute intervals ending by its own reference
time and available by evaluation. A missing interval, zero total volume, absent
earlier value or nonpositive ATR makes slope `UNKNOWN`.

Freeze the three-minute opening extreme on the fade side: the first-three-minute
low for a gap-up short and first-three-minute high for a gap-down long. Freeze
`buffer = max($0.01, 0.03 * ATR_1M_20_SMA_V1)` when the failed reclaim is
confirmed. Short boundary is `first_3m_low - buffer`; long boundary is
`first_3m_high + buffer`.

The first later covered pair of eligible trades that crosses the frozen
boundary from the non-triggered side sets the trigger. Short crossing is
`previous >= boundary > current`; long crossing is
`previous <= boundary < current`. Equality at the boundary is not beyond it and
does not trigger. The previous and current trades must be covered, correctly
ordered and no more than 3 seconds apart. The crossing trade sets the mechanical
trigger time but cannot be its own modeled fill.

At trigger, price must remain strictly in the fade direction from the open and
VWAP, `VWAP_SLOPE_3M_ATR_V1` must be nonpositive for a short or nonnegative for
a long, RS must pass, spread must be at most 20 basis points, and halt and
catalyst gates must be known. Zero VWAP slope passes the preserved `<= 0` short
rule and its exact long mirror `>= 0`.

The exact state path is `GAP_IDENTIFIED -> OPEN_TEST -> EXTENSION_FAILED ->
FADE_FORMING -> ARMED -> ALERT_TRIGGERED`. The eligible gap creates
`GAP_IDENTIFIED`; the first-three-minute window creates `OPEN_TEST`; §3 advances
to `EXTENSION_FAILED`; loss of open advances to `FADE_FORMING`; failed reclaim
plus passing current RS and catalyst gates advances to `ARMED`; and the crossing
advances to `ALERT_TRIGGERED`. The 180-second reclaim deadline, 0.35 gap-fill
staleness or 07:15 expiry ends an untriggered structure. A continuation-aligned
class A event invalidates it. A temporary spread, freshness or RS failure blocks
that evaluation without erasing the frozen structure before expiry. Persist
each transition and reason; later corrections create a new as-of record rather
than rewriting an earlier state.

## 6. Catalyst classes and exact unknown penalty

Use the latest point-in-time catalyst class whose event time, original receive
time, source and classification version were available by trigger. Later news
cannot rewrite an earlier candidate. Keep A, B, C and D results separate.

Use the preserved playbook classes. A is a known major hard catalyst. B is a
known significant sector, market or company event. C requires proven source
coverage and either no qualifying event or a known technical-only explanation.
D requires proven coverage but leaves an observed event or its direction
ambiguous.

The catalyst must also say whether known news supports continuation in the gap
direction, opposes it or is directionally neutral. Class A continuation-aligned
news suppresses the fade. When complete source coverage is proven but the known
facts remain ambiguous, the class or direction is D. It is never changed to C
or treated as proof that no catalyst exists. Missing source coverage is
`UNKNOWN`, not D.

The preserved preference `C > D > B >>> A` has these exact V1 meanings:

- C has no catalyst penalty and remains in the primary mechanical arm.
- D remains mechanically eligible but subtracts 15 points from the final
  research score after the weighted score is calculated. The floor is zero.
- B remains mechanically eligible but subtracts 30 points from the final score.
- A continuation-aligned with the gap is suppressed. Other A events remain
  recorded in a separate diagnostic row and do not enter the primary arm.

The all-mechanical-candidates diagnostic retains C, D and B without a score
cutoff, with the class and penalty stored. This does not turn unknown news into
favorable evidence. Missing point-in-time coverage or classification version
makes the catalyst gate `UNKNOWN` and blocks the faithful arm.

## 7. Staleness, stop precedence and targets

Define progress toward full gap fill at trigger:

`gap_fill_fraction = s * (last - open_price) / abs(gap_dollars)`

The setup is stale when `gap_fill_fraction >= 0.35`. Thus a value strictly below
0.35 remains eligible and equality is stale. A negative value is retained as
zero fill. A value over one remains stale and is not capped in the raw record.

The stop always protects beyond both the frozen opening extreme and the adverse
failed-reclaim extreme. For a gap-up short:

`raw_stop = max(opening_extreme, reclaim_extreme) + 0.05 * frozen_ATR_1m`

For a gap-down long:

`raw_stop = min(opening_extreme, reclaim_extreme) - 0.05 * frozen_ATR_1m`

Round outward to the known valid price increment: up for short and down for
long. This is the exact precedence rule. The opening extreme cannot be ignored
when the reclaim high or low is closer to entry, and the reclaim extreme cannot
be ignored when it is more adverse. V1 has no separate early-entry arm because
failed reclaim is mandatory.

With fade sign `s`, `R = s * (entry - stop)` must be positive. Build the target
catalog at trigger from the 25%, 50%, 75% and 100% gap-fill prices between the
open and prior close, plus the current session VWAP. Keep only levels ahead in
the fade direction, merge equal prices while retaining labels, and sort by
directional distance from entry. T1 is the nearest level at least 1.5R away.
T2 is the nearest distinct later level at least 2.5R away. A complete catalog
with no qualifying T1 blocks action. A complete catalog with no T2 records known
absence and leaves a session-close runner. An incomplete catalog is `UNKNOWN`.

Keep three exit policies separate. `GAP_FADE_STRUCTURAL_V1` uses T1/T2 and
preserves the playbook prior. `GAP_FADE_FIXED_2R_V1` closes both units at 2R.
`GAP_FADE_FIXED_3R_V1` closes both units at 3R. The fixed arms still require a
complete catalog and qualifying structural T1, so they compare exit treatment
without admitting a different setup.

## 8. Research score and interaction ownership

`GAP_FADE_FAILED_OPEN_SCORE_V1` uses 45% Setup, 35% Context and 20% Execution.
Define `clamp(x)=min(100,max(0,x))`. Missing any factor makes the score
`UNKNOWN`; do not rescale.

- Setup, 45%: average extension headroom
  `clamp(100*(extension_limit-opening_extension)/extension_limit)`, reclaim
  speed `clamp(100*(180-reclaim_seconds)/180)` and trigger-break distance
  `clamp(100*fade_distance_past_boundary/(0.10*frozen_ATR_1m))`.
- Context, 35%: average gap size
  `clamp(100*(max(gap_pct/0.01,gap_ATR/0.25)-1)/2)`, from-open RS strength
  `clamp(100*abs(rs_from_open)/0.01)` and target room
  `clamp(100*(T1_R-1.5)/1.0)`.
- Execution, 20%: average `100*(20-spread_bps)/20`,
  `100*(3-quote_age_seconds)/3`, `100*(3-trade_age_seconds)/3` and
  `100*(0.35-gap_fill_fraction)/0.35`.

After the weighted sum, apply the catalyst penalty from §6 and floor at zero.
A final score at least 65 passes the score-threshold research arm. Retain all
raw factors and the pre-penalty score. The score is a research rank, not a win
probability or a live threshold.

When a matching `OR_FAILURE_REV` event exists, use one primary owner and retain
the other strategy as confluence. An opening-range failure owns a reversal of a
frozen opening-range break. This strategy owns a failure of the overnight gap
after its exact three-minute extension and reclaim chain. If both trigger at the
same available time, `OR_FAILURE_REV` is primary and this strategy is
confluence. Otherwise the first triggered strategy remains primary until it
invalidates. Neither event is deleted or rewritten.

## 9. Outcome and reporting rules

Measure two equal stock research units. Use the M0.3A O-01 quote-side entry
search, delays of 0, 5, 15, 30 and 60 seconds, session-close horizon,
missingness and adverse ordering. At fill, the frozen stop and 0.35 gap-fill
staleness rule must still pass.

For `GAP_FADE_STRUCTURAL_V1`, T1 closes one unit and T2 closes the second when
it exists. Known T2 absence leaves a session-close runner. Fixed 2R and 3R
policies close both units at their target. The original stop never moves and a
stop closes all open units. Long exits use bid and short exits use ask. Equal
availability times resolve stop before target.

With one-minute bars, enter at the next bar open, check an opening gap first and
resolve a bar touching stop and target as stop first. Label it
`BAR_PROXY / MODELED_COST_ONLY`; it cannot prove the trade crossing, reclaim
ordering, point-in-time catalyst or quote-side fills.

Keep gross and after-cost results separate. Quote sides already include spread,
so do not charge it twice. Report stock slippage at 0.5 basis points per side
and a 1.0 basis point per-side harsh sensitivity; stock commission is $0.
Executable shorts additionally require point-in-time borrow availability and
cost. Without it, retain only a labeled directional result. Options remain a
separate later arm and cannot change a stock result.

Report two fade directions, four catalyst classes and three exit policies as 24
separate cells before delay, score and cost slices. Cross them with five delays,
two score populations and two stock-slippage assumptions for 480 primary
comparisons. Use the 10-session circular moving-block bootstrap and
preregistered family threshold `0.05 / 480 = 1 / 9600`. Report after-cost
expectancy, win rate, payoff ratio, maximum drawdown and candidate frequency
with counts and denominators. Keep every class and direction separate; do not
choose or pool a winner.

Preserve losing, suppressed, stale, unknown, unfilled, unresolved and
short-borrow-blocked rows. Reserve exact chronological development, calibration
and untouched final dates from a qualifying coverage-only source manifest
before opening results.

## 10. Required boundary examples

These examples check definitions. They are not profit evidence.

1. Prior close 100 and open 101 give a 1% gap and pass. Open 100.999 fails the
   percent branch. With daily ATR 4, a $1 gap has gap_ATR 0.25 and passes.
2. A $2 gap and minute ATR 1 give limits 0.30 and 0.20, so 0.30 controls. An
   opening extension of 0.30 passes; 0.301 fails. A later high cannot rewrite it.
3. The three scheduled minutes must all be final and available. One certified
   no-trade minute is allowed; one unexplained missing minute is `UNKNOWN`.
4. For a gap-up short, a loss bar closing 100.99 below open 101 and equal to
   VWAP passes. A close equal to the open fails. The gap-down long mirrors both.
5. A gap-up loss bar ends at 06:34. A later bar reaches open 101 and closes
   100.90 below both open and VWAP at 06:37:00; the inclusive 180-second boundary
   passes. A bar ending one microsecond later is diagnostic only.
6. A gap-up reclaim bar whose high is 100.99 never reaches open 101 and is only
   a temporary bounce. The mirror gap-down bar whose low stays above its open
   also fails.
7. Stock return -0.40% and SPY return -0.10% give RS -0.30%, which passes a
   gap-up short. Zero RS fails. A gap-down long requires the exact positive mirror.
8. With first-three-minute low 100, ATR 0.50 gives a 0.015 buffer and short
   boundary 99.985. A move from 99.99 to 99.984 crosses; a trade at 99.985 does
   not. The long mirror uses first-three-minute high plus the buffer.
9. Gap-up open 101 and prior close 100 give 35% fill at 100.65. That value is
   stale; 100.651 is still eligible. Gap-down open 99 and prior close 100 uses
   99.35 as the exact mirrored stale boundary.
10. A gap-up opening high 101.40, reclaim high 101.30 and ATR 0.40 give raw short
    stop 101.42; opening high wins. If reclaim high is 101.50, raw stop is
    101.52. The gap-down long uses the lower of opening and reclaim lows.
11. Class C has no penalty. D subtracts 15 points and B subtracts 30. A
    pre-penalty score of 75 becomes 60 for D and 45 for B. A continuation-aligned
    class A suppresses. Missing catalyst coverage is `UNKNOWN`, not class C.
12. The target catalog needs all five named inputs. Missing VWAP makes it
    incomplete. A complete catalog with no T1 blocks action; known T2 absence
    leaves a runner.
13. A bar touching a long stop and target records the stop first. Missing short
    borrow blocks executable short expectancy but leaves the directional row.
    Missing option quotes do not alter the stock row.

## 11. Open evidence gates

Faithful replay remains blocked until M0.2 supplies complete point-in-time bars,
trades, quotes, SPY, VWAP, catalyst and halt coverage with corrections and
availability times. Executable short evidence also needs dated borrow facts;
option evidence needs exact contract and quote facts. Replay requires a
qualifying source manifest and frozen chronological development, calibration
and untouched final-validation dates. Written definitions and synthetic checks
do not validate an edge or authorize live use. All switches stay off.
