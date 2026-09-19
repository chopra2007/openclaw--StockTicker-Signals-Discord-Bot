# M0.3H deterministic research definitions — `CAT_FIRST_CONSOL`

Version: `M03H_CAT_FIRST_CONSOL_V1`  
Status: **FROZEN FOR OFFLINE RESEARCH**  
Date: **2026-09-13 Pacific**

## 1. Scope and authority

The owner's 2026-09-13 research authorization delegates the remaining ordinary
research choices to the agent. This packet freezes one finite first research
version for `CAT_FIRST_CONSOL`. PLAYBOOKS and TESTING_AND_VALIDATION incorporate
it under their own authority. It does not approve a live alert, an order, a
replay result or a claim of profit.

Use exact values before display rounding. Every input must have event time,
available time, source identity, session identity and a compatible adjustment
basis. A missing mandatory input is `UNKNOWN` and cannot pass. Long and short
setups are exact mirrors under the direction sign defined below.

## 2. Point-in-time catalyst classification — `CATALYST_EVENT_M03H_V1`

Let `s = +1` for a long setup and `s = -1` for a short setup. Use only a
catalyst record whose original publication time and first receive time are
known, whose first receive time is no later than evaluation, and whose issuer,
source, source-event identifier, classification version and direction were
available then. Later edits, summaries or classifications create new as-of
records and cannot rewrite an earlier decision.

The event must first publish after the prior regular-session close and before
07:15 Pacific. For an intraday event, evaluation must occur no more than 30
minutes after first receipt. Equality at 30 minutes passes. An older event is
retained but cannot start V1. Proven complete coverage with no qualifying event
is `NO_QUALIFYING_CATALYST`, not class C. Missing coverage is `UNKNOWN`.

Freeze these classes from information available at evaluation:

- A: a named hard event that directly changes, or can reasonably change, the
  issuer's earnings, cash flows, capital structure or legal ability to operate:
  earnings or guidance, merger/acquisition, FDA or other binding regulator
  action, a signed material contract, bankruptcy, financing, restructuring or
  a filed material corporate action.
- B: a sourced and issuer-specific analyst action, investor-day disclosure,
  product launch/result, industry event or corporate update with a stated fact
  that can reasonably affect revenue, costs, demand, valuation or operations,
  but that does not meet A.
- C: a sourced secondary event with a concrete issuer link that does not meet A
  or B, such as a nonbinding mention, minor product item or sympathy connection.
- D: rumor, unsourced claim, material ambiguity about issuer/event identity, or
  facts whose direction cannot be classified from the available record.

Direction is `LONG`, `SHORT`, `NEUTRAL` or `AMBIGUOUS`. LONG requires the known
facts to support higher value or demand; SHORT requires lower value or demand;
NEUTRAL means the known facts have no directional claim; AMBIGUOUS means
credible available facts conflict or are insufficient. D and AMBIGUOUS suppress
V1. A/B/C must match `s`; NEUTRAL does not match.

`CONTRADICTORY_NEWS_M03H_V1` exists when a separate A or B record for the same
issuer, first received by evaluation and not a duplicate or later summary of the
qualifying event, has the direction opposite `s`. Equality of receive and
evaluation times counts as known. Contradictory news suppresses the structure.
A C event never cancels a known opposing A/B event. Unknown news coverage makes
this gate `UNKNOWN`, not false.

The preserved A/B-only trigger is the primary arm. Class C never becomes an
actionable V1 trigger. It enters only `C_ABNORMAL_DIAGNOSTIC_V1` when both
`RVOL_OPEN5_MEAN20_V1 >= 3.0` and either `abs(gap_ATR) >= 0.30` or the regular-
session impulse is at least `0.30 * DAILY_ATR_14_SMA_V1`. Equality passes. This
resolves the old “C only with abnormality” prior without weakening the A/B
trigger. Keep A, B and C-diagnostic results separate.

## 3. Eligibility, shared inputs and time window

Use `ATR_1M_20_SMA_V1`, `DAILY_ATR_14_SMA_V1`,
`RVOL_OPEN5_MEAN20_V1`, `DOLLAR_VOLUME_CLOSE_PROXY20_V1` and exactly
`SESSION_VWAP_BAR_HLC3_V1` from M0.3A. Trade VWAP is not a V1 alternative or
fallback. Freeze the first eligible regular-session trade as `open_price` and
the prior regular-session adjusted close as `prior_close`.

Require price at least $5, 20-session median daily dollar volume at least $50
million and opening-five-minute RVOL at least 2.0. The latest positive two-sided
quote must not be crossed or delayed, must be no more than 3 seconds old and
must have spread at most 20 basis points. The latest eligible trade must be no
more than 3 seconds old. A spread over 30 basis points, a halt, an opposing A/B
event or an unknown halt/news gate suppresses evaluation. Premarket dollar
volume at least $10 million is preferred recorded context, not a V1 gate.

Abnormal repricing passes when at least one is true: `abs(gap_ATR) >= 0.30`,
`RVOL_OPEN5_MEAN20_V1 >= 2.5`, or a post-open move from the price at catalyst
receipt reaches `0.30 * DAILY_ATR_14_SMA_V1`. A nonpositive denominator or
missing branch input cannot make that branch pass. At least one fully known
branch must pass.

The trigger window begins at 06:35 Pacific and ends before 07:15 Pacific. A
catalyst received after the open can start observation at its first receive
time, but no bar or trade known earlier may be treated as a reaction to it. One
actionable event is allowed per `(session, symbol, source_event_id, direction)`.

## 4. Regular-session impulse — `CAT_IMPULSE_M03H_V1`

The impulse begins at the first eligible trade at or after
`max(06:30 Pacific, catalyst_first_receive_time)`. The starting price is that
trade. A long impulse tracks the highest eligible trade; a short impulse tracks
the lowest. Its directional distance is `s * (extreme - start_price)` and must
be at least `max(0.30 * ATR_1M_20_SMA_V1,
0.10 * DAILY_ATR_14_SMA_V1)`. Equality passes. The overnight gap is context and
cannot supply this regular-session distance.

After the threshold is first reached, freeze the impulse extreme when two
consecutive final, available, traded one-minute bars fail to make a new extreme
in direction `s`. A one-tick equal high or low is not a new extreme. The first
of those two bars starts the consolidation candidate; the second confirms that
the preceding extreme and candidate start were knowable. An unexplained missing
minute before confirmation makes the structure `UNKNOWN`. A correction creates
a new as-of structure rather than changing the frozen record.

Impulse volume is the eligible share volume from the impulse start through the
trade that sets the frozen extreme. Its duration is positive wall-clock seconds.
Zero duration, unknown trade eligibility or uncovered trade intervals make the
faithful volume comparison `UNKNOWN`.

## 5. First consolidation — `CAT_FIRST_CONSOL_M03H_V1`

The first consolidation is the first candidate after the qualifying impulse.
It starts with the first of the two non-extension bars in §4 and contains every
consecutive final, available, traded one-minute bar through the trigger or
invalidation. It is eligible only after at least two bars and at most eight
bars. A second candidate after a breakout, invalidation or completed first
candidate is retained as `LATER_CONSOLIDATION` and cannot trigger V1.

For a long, freeze the consolidation low and high from eligible trades in those
bars. For a short, use the same observed low/high and mirror all directional
tests. Let `impulse_size` be the positive directional distance in §4. Define:

`retrace = s * (impulse_extreme - adverse_extreme) / impulse_size`

`consolidation_range_ratio = (consolidation_high - consolidation_low) / impulse_size`

`volume_ratio = consolidation_eligible_shares / impulse_eligible_shares`

Negative retracement is recorded as zero; values above one are retained. The
consolidation requires `consolidation_range_ratio <= 0.50` and
`volume_ratio <= 0.80`; equality passes. An unexplained missing minute or trade-
coverage gap makes the corresponding value `UNKNOWN`.

The exact depth roles are:

- `PRIMARY_DEPTH`: `retrace <= 0.50`. A/B can arm the primary trigger.
- `DEEP_DIAGNOSTIC`: `0.50 < retrace <= 0.65`. It is recorded but cannot arm.
- `TOO_DEEP`: `retrace > 0.65`. It invalidates the structure; equality at 0.65
  stays diagnostic.

Thus 0.50 is the actionable ceiling and 0.65 is the final research-observation
ceiling. Neither is a preferred display-only hint.

## 6. Acceptance, trigger and state

Freeze `buffer = max($0.01, 0.03 * ATR_1M_20_SMA_V1)` when the second
consolidation bar becomes available. Long boundary is
`consolidation_high + buffer`; short boundary is
`consolidation_low - buffer`. Later bars may extend the consolidation toward
the trigger only while they remain inside the current boundary; update the
extreme and boundary in a new as-of record before arming. A triggering trade
cannot first redefine the boundary it crosses.

`CAT_ACCEPTANCE_10S_TRADE_V1` samples one covered eligible last trade at each of
the ten fixed one-second instants ending at evaluation. A long sample passes
when it is at or above the frozen boundary; a short sample passes when it is at
or below. At least seven of ten samples must pass, so acceptance is at least
0.70. Missing a sample makes faithful acceptance `UNKNOWN`. Multiple messages
inside one second count once. A final one-minute bar is only a separately
labeled proxy and cannot satisfy this arm.

The first later covered pair of eligible trades crossing the boundary sets the
trigger: long `previous <= boundary < current`; short
`previous >= boundary > current`. Equality at the boundary does not trigger.
The two trades must be correctly ordered and no more than 3 seconds apart. The
crossing trade sets trigger time but cannot be its own modeled fill.

Freeze that first crossing. Beginning with the first fixed one-second instant at
or after it, evaluate the trailing ten samples after each new covered second.
The first evaluation with seven passing samples is the alert decision. Store the
crossing trade's event time as mechanical trigger time and the later of its
receive time and the tenth sample's available time as decision available time.
Entry delay starts from decision available time, so acceptance cannot look ahead
into a modeled fill.

At trigger, A/B primary setups require `PRIMARY_DEPTH`, catalyst direction
matching `s`, no contradictory news, price strictly on the correct side of the
same-time VWAP, known passing liquidity/freshness/halt gates, acceptance at
least 0.70, range ratio at most 0.50 and volume ratio at most 0.80. Class C and
deep consolidations remain diagnostic regardless of their other values.

The exact path is `CATALYST_IDENTIFIED -> IMPULSE_DETECTED ->
CONSOLIDATION_FORMING -> ARMED -> ALERT_TRIGGERED`. The point-in-time event
creates `CATALYST_IDENTIFIED`; §4 threshold creates `IMPULSE_DETECTED`; the
first candidate creates `CONSOLIDATION_FORMING`; two through eight valid bars
plus all current A/B primary gates create `ARMED`; and the crossing plus
acceptance creates `ALERT_TRIGGERED`. Nine bars, too-deep retracement,
contradictory news, halt or 07:15 expiry ends an untriggered structure. Persist
every transition and reason.

The setup is stale when price moves more than `0.35R` beyond the frozen trigger
boundary before the modeled fill. Equality remains eligible; a value strictly
greater than 0.35R is stale.

## 7. Stop, targets and overlap ownership

For a long, raw stop is `consolidation_low - 0.05 * frozen_ATR_1m`. For a short,
it is `consolidation_high + 0.05 * frozen_ATR_1m`. Round outward to the known
valid price increment: down for long, up for short. `R = s * (entry - stop)`
must be positive.

Build the point-in-time structural catalog from session HOD/LOD, premarket
high/low, prior-day high/low/close, current session VWAP, the first whole-dollar
level ahead of entry and the first half-dollar level ahead of entry. Keep only
levels ahead in direction `s`, merge equal prices while retaining labels, and
sort by directional distance from entry. T1 is the nearest level at least 1.5R
away. T2 is the nearest distinct later level at least 2.5R away. A complete
catalog with no T1 blocks action. A complete catalog with no T2 records known
absence and leaves a session-close runner. An incomplete catalog is `UNKNOWN`.

Keep `CAT_CONSOL_STRUCTURAL_V1`, `CAT_CONSOL_FIXED_2R_V1` and
`CAT_CONSOL_FIXED_3R_V1` as separate exits. Fixed arms still require a complete
catalog and qualifying structural T1, so they do not admit a different setup.

The first qualifying catalyst consolidation owns the event over a later
`HOD_COMP_RS` compression. If `HOD_COMP_RS` triggered earlier, it remains
primary and this strategy is confluence. If both trigger at the same available
time, `CAT_FIRST_CONSOL` is primary because its identified catalyst and first
consolidation are more specific. Neither record is deleted.

## 8. Research score

`CAT_FIRST_CONSOL_SCORE_V1` uses 40% Setup, 40% Catalyst Context and 20%
Execution. Define `clamp(x)=min(100,max(0,x))`. Missing any factor makes the
score `UNKNOWN`; do not rescale.

- Setup, 40%: average impulse strength
  `clamp(100*(impulse_size/impulse_threshold-1)/2)`, retracement quality
  `clamp(100*(0.65-retrace)/0.65)` and contraction
  `clamp(100*(0.80-volume_ratio)/0.80)`.
- Catalyst Context, 40%: average class value A=100, B=70, C=40;
  freshness `clamp(100*(1800-age_seconds)/1800)`; and abnormality
  `clamp(100*(max(abs(gap_ATR)/0.30,RVOL_5m/2.5)-1)/2)`.
- Execution, 20%: average `100*(20-spread_bps)/20`,
  `100*(3-quote_age_seconds)/3`, `100*(3-trade_age_seconds)/3` and
  `clamp(100*(acceptance-0.70)/0.30)`.

A score at least 65 passes the score-threshold research population. Retain all
raw factors. The score is a research rank, not a win probability or a live
threshold. D, ambiguous direction, unknown coverage and contradictory news are
suppressions and cannot be rescued by score.

## 9. Outcome and reporting rules

Measure two equal stock research units. Use the M0.3A O-01 quote-side entry
search, delays of 0, 5, 15, 30 and 60 seconds, session-close horizon,
missingness and adverse ordering. At fill, the frozen catalyst, depth, stop,
staleness, news and liquidity gates must still pass.

For `CAT_CONSOL_STRUCTURAL_V1`, T1 closes one unit and T2 closes the second when
it exists. Known T2 absence leaves a session-close runner. Fixed 2R and 3R exits
close both units at their target. The original stop never moves and closes all
open units. Long exits use bid and short exits use ask. Equal availability times
resolve stop before target.

With one-minute bars, enter at the next bar open, check an opening gap first and
resolve a bar touching stop and target as stop first. Label it
`BAR_PROXY / MODELED_COST_ONLY`; it cannot prove catalyst timing, the trade
crossing, ten-second acceptance or quote-side fills.

Keep gross and after-cost results separate. Quote sides already include spread,
so do not charge it twice. Report stock slippage at 0.5 basis points per side
and a 1.0 basis point per-side harsh sensitivity; stock commission is $0.
Executable shorts additionally require point-in-time borrow availability and
cost. Without it, retain only a labeled directional result. Options remain a
separate later arm and cannot change a stock result.

Report two directions, three catalyst populations (A, B and C diagnostic), two
depth populations and three exit policies as 36 separate cells before delay,
score and cost slices. Cross them with five delays, two score populations and
two stock-slippage assumptions for 720 primary comparisons. Cells that cannot
arm remain labeled diagnostic rather than silently removed. Use the 10-session
circular moving-block bootstrap and preregistered family threshold
`0.05 / 720 = 1 / 14400`. Report after-cost expectancy, win rate, payoff ratio,
maximum drawdown and candidate frequency with counts and denominators. Do not
pool A, B and C or primary and deep depth to choose a winner.

Preserve losing, suppressed, stale, later-consolidation, unknown, unfilled,
unresolved and short-borrow-blocked rows. Reserve exact chronological
development, calibration and untouched final dates from a qualifying coverage-
only source manifest before opening results.

## 10. Required boundary examples

These examples check definitions. They are not profit evidence.

1. An event received at 06:45 can use no 06:44 price as its reaction start. At
   07:15 it is exactly 30 minutes old and passes freshness; one microsecond
   later fails.
2. Proven complete coverage with no event is `NO_QUALIFYING_CATALYST`. Missing
   coverage is `UNKNOWN`; neither is class C.
3. A sourced minor issuer mention is C. It enters the diagnostic only with RVOL
   exactly 3.0 and either gap ATR exactly 0.30 or impulse exactly 0.30 daily ATR.
   It never enters the A/B primary trigger.
4. A long A earnings event and a separately sourced B guidance cut known by
   evaluation are contradictory and suppress. If the cut arrives one
   microsecond later, it cannot rewrite the earlier as-of result.
5. Minute ATR 1 and daily ATR 4 give impulse thresholds 0.30 and 0.40, so 0.40
   controls. A move of exactly 0.40 passes; 0.399 fails.
6. One bar fails to extend an impulse and the next also fails. The first starts
   the candidate, but the structure is knowable only when the second is final
   and available. An equal high is not a new long extreme.
7. A later second consolidation is labeled `LATER_CONSOLIDATION` even if it is
   tighter than the first. It cannot trigger V1.
8. Impulse 2.00 and adverse pullback 1.00 give retrace 0.50 and primary depth.
   Pullback 1.0002 gives 0.5001 and deep diagnostic. Retrace exactly 0.65 remains
   diagnostic; any greater value invalidates.
9. Consolidation range ratio exactly 0.50 and volume ratio exactly 0.80 pass.
   A value one exact unit above either boundary fails.
10. Seven of ten fixed one-second samples at or beyond the boundary pass 0.70.
    Six fail. Ten messages in one second count as one sample.
11. With long consolidation high 100 and ATR 0.50, buffer is 0.015 and boundary
    100.015. A move from 100.015 to 100.016 crosses; a trade equal to 100.015
    does not. The short case mirrors it.
12. A long fill delayed exactly 0.35R beyond the boundary remains eligible;
    0.3501R is stale.
13. Long consolidation low 99.50 and ATR 0.40 give raw stop 99.48, rounded down
    to the valid increment. The short case rounds upward.
14. A complete target catalog with no level at least 1.5R blocks action. A known
    T1 and no T2 leaves a runner. Missing one required catalog source is
    `UNKNOWN`, not proof of open space.
15. A bar touching a long stop and target records the stop first. Missing short
    borrow blocks executable short expectancy but leaves the directional row.
    Missing option quotes do not alter the stock row.

## 11. Open evidence gates

Faithful replay remains blocked until M0.2 supplies complete point-in-time
catalyst history and coverage, original publication/receipt times, corrected
versions, bars, eligible trades, quotes, VWAP, RVOL, halts and structural levels
with availability times. Executable short evidence also needs dated borrow
facts; option evidence needs exact contract and quote facts. Replay requires a
qualifying source manifest and frozen chronological development, calibration
and untouched final-validation dates. Written definitions and synthetic checks
do not validate an edge or authorize live use. All switches stay off.
