# M0.3D deterministic research definitions — `OR_FAILURE_REV`

Version: `M03D_OR_FAILURE_REV_V1`  
Status: **FROZEN FOR OFFLINE RESEARCH**  
Date: **2026-09-13 Pacific**

## 1. Scope and authority

The owner's 2026-09-13 research authorization delegates the remaining ordinary
research choices to the agent. This packet freezes one finite first research
version for `OR_FAILURE_REV`. PLAYBOOKS and TESTING_AND_VALIDATION incorporate
it under their own authority. It does not approve a live alert, an order, a
replay result or a claim of profit.

Use exact values before display rounding. Every input must have event time,
available time, source identity, session identity and a compatible adjustment
basis. A missing mandatory input is `UNKNOWN` and cannot pass. Long and short
rules are exact mirrors unless a row below says otherwise.

## 2. Shared inputs, range and eligibility

Use `ATR_1M_20_SMA_V1`, `DAILY_ATR_14_SMA_V1`,
`DOLLAR_VOLUME_CLOSE_PROXY20_V1`, `RVOL_OPEN5_MEAN20_V1`, the five-minute
opening range from M0.3A and one explicitly named M0.3A session VWAP mode. Do
not mix bar and trade VWAP modes in one arm.

The half-open setup and entry window is 06:35 through, but excluding, 07:15
Pacific on a regular session. The opening range must be final and available.
Price must be at least $5, median daily dollar volume at least $50 million,
spread at most 20 basis points, RVOL at least 1.5, and opening-range width divided
by daily ATR from 0.08 through 0.65. A nonpositive denominator is `UNKNOWN`.

A quote must be positive, two-sided, not crossed, not delayed and no more than
3 seconds old. The latest eligible trade must be no more than 3 seconds old.
Halt status and required interval coverage must be known. Equality passes every
minimum or maximum in this packet unless the rule expressly uses a strict
comparison.

The break buffer is frozen at the crossing:

`buffer = max($0.01, 0.05 * ATR_1M_20_SMA_V1)`

For an upside break the boundary is `ORH + buffer`; for a downside break it is
`ORL - buffer`. A crossing requires consecutive covered observations
`previous < boundary <= current` upside or `previous > boundary >= current`
downside. A moving boundary is not a crossing.

## 3. Meaningful excursion, timer and failure ownership

Feature `OR_FAILURE_EXCURSION_10ATR_V1` uses the furthest eligible trade after
the frozen crossing. An upside break is meaningful only when its high is at
least `ORH + 0.10 * frozen_ATR_1m` and remains beyond the buffered boundary. A
downside break is meaningful only when its low is at most
`ORL - 0.10 * frozen_ATR_1m` and remains beyond the buffered boundary. Thus one
tick beyond an edge or a buffered crossing below 0.10 ATR is not enough.

The failure timer starts at the first crossing of the frozen buffered boundary,
not at the opening-range edge, the excursion extreme, a later bar open or the
first trade back inside. The deadline is `crossed_at + 180 seconds`; equality
passes. A qualifying confirmation event and its required records must be
available by that deadline and before 07:15 Pacific. A later failure is recorded
as a diagnostic but cannot enter this V1 arm.

Structure identity is `(session, symbol, break_direction, opening_range_id,
crossed_at, mode)`. A failed upside break creates a short reversal; a failed
downside break creates a long reversal. One actionable reversal is allowed per
structure.

If the same structure belonged to `CRVOL_ORB5`, that owner releases it to
`OR_FAILURE_REV` only after the final one-minute close described in §4 makes the
breakout invalid. This applies even if the ORB had already produced an immutable
mechanical event. The old event is never deleted or rewritten; the reversal
stores its parent event ID. `OR_FAILURE_REV` becomes the sole primary owner only
at its own trigger. Before that instant the ORB remains primary. This is the
explicit reversal exception to ordinary opposite-direction suppression. A
generic later fade with no matching frozen break structure has no ownership.

## 4. Reacceptance, failure bar and two confirmation arms

The reacceptance bar is the first final, available, traded one-minute bar ending
after the crossing whose close is strictly inside the unbuffered opening range.
Its end and availability must satisfy the §3 deadline. A close exactly at ORH or
ORL is not inside. An unexplained missing minute makes confirmation `UNKNOWN`.

That same reacceptance bar is the failure bar. Freeze its high, low, close and
input ID when it becomes available. Compare two confirmation arms; neither may
replace or pool results from the other:

- `OR_FAILURE_CLOSE_V1`: the final reacceptance close is the confirmation event.
- `OR_FAILURE_BAR_BREAK_V1`: after that bar is available, the first eligible
  trade strictly below its low confirms a short, or strictly above its high
  confirms a long. Equality does not break the failure bar. This event must also
  meet the §3 deadline.

Both arms require the same final close. The bar-break arm is the stronger,
later confirmation; it is not a faster substitute for the mandatory close.
Record candidates that pass the close arm but never pass the bar-break arm.

## 5. Inside acceptance and actionable trigger

At each eligible evaluation from the confirmation event through the deadline,
feature `OR_FAILURE_INSIDE_ACCEPTANCE_10S_V1` uses exactly ten fixed one-second
samples at `t-9` through `t`. All ten must be known. A sample is inside only when
it is strictly between ORL and ORH. At least seven samples must be inside, so
0.70 passes and 0.60 fails. A message burst cannot create extra samples.

Keep two data modes separate:

- `OR_FAILURE_TAPE_V1` samples the latest eligible trade at each grid instant,
  no more than 3 seconds old.
- `OR_FAILURE_QUOTE_V1` samples a fresh quote midpoint at each grid instant and
  separately requires a fresh eligible last trade inside the range at trigger.

No mode switching is allowed within a structure. A completed one-minute bar
cannot stand in for either ten-sample arm.

At the mechanical trigger, the last eligible trade must still be inside the
range and must have moved at least `0.03 * frozen_ATR_1m` from the failed edge in
the reversal direction. Spread must remain at most 20 basis points. Freeze the
entry `E`, excursion extreme, failure bar, acceptance samples, quote, ATR, range,
VWAP mode and all score inputs at that instant.

The catalyst-continuation suppression is deliberately conjunctive. Suppress
only when a point-in-time `CATALYST_ORB5_V1` class A/B event is known, and the
full ten-sample window immediately before the
reacceptance close has at least seven samples still beyond the failed buffered
boundary. Unknown catalyst status makes this suppression gate `UNKNOWN`; it is
not treated as no catalyst. A catalyst without sustained outside acceptance, or
outside acceptance without a confirmed catalyst, does not satisfy this
specific suppression rule. The failed price break supplies the direction; this
rule does not invent a directional catalyst field.

## 6. Stop, targets and staleness

At trigger, use the furthest eligible trade from crossing through trigger as the
breakout extreme. Short raw stop is
`upside_extreme + 0.05 * frozen_ATR_1m`; long raw stop is
`downside_extreme - 0.05 * frozen_ATR_1m`. Round outward to the known valid
price increment: up for short and down for long. An unknown increment makes
risk `UNKNOWN`.

With reversal sign `s` equal to +1 long and -1 short,
`R = s * (E - stop)` must be positive. A setup is stale when
`s * (E - failed_edge) / R > 0.40`; exactly 0.40 remains eligible.

Build one complete target catalog at trigger from the frozen opening-range
midpoint, the selected as-of session VWAP and the opposite opening-range edge.
Keep only levels ahead in the reversal direction, merge exactly equal prices
while retaining all labels, and sort by directional distance from entry. T1 is
the nearest level at least 1.5R away. T2 is the nearest distinct later level at
least 2.5R away. No T1 blocks action. A complete catalog with no T2 records T2
as known absent; an incomplete catalog is `UNKNOWN` and blocks action. Never
move a level or invent an R-multiple target.

Keep three exit policies as separate result arms. `OR_FAILURE_STRUCTURAL_V1`
uses T1 and T2 above and preserves the playbook prior. `OR_FAILURE_FIXED_2R_V1`
uses one fixed target at `E + s * 2R`; `OR_FAILURE_FIXED_3R_V1` uses one fixed
target at `E + s * 3R`. Both fixed policies still require the complete catalog
and qualifying structural T1, so they test exit treatment rather than admit a
different setup. No result selects a winner or changes the structural prior.

## 7. Research score

Score `OR_FAILURE_REV_SCORE_V1` is frozen only at trigger. Define
`clamp(x)=min(100,max(0,x))`. Missing any factor makes the score `UNKNOWN`; do
not rescale.

- Setup, weight 50%: excursion strength
  `clamp(100*(excursion_ATR-0.10)/0.20)`; failure speed
  `clamp(100*(180-failure_seconds)/180)`; inside acceptance
  `100*(acceptance-0.70)/0.30`. Average the three.
- Context, weight 30%: RVOL excess `clamp(100*(RVOL-1.5)/1.5)`; target room
  `clamp(100*(T1_R-1.5)/1.0)`; failed-break displacement
  `clamp(100*(inside_distance_ATR-0.03)/0.12)`. Average the three.
- Execution, weight 20%: spread quality `100*(20-spread_bps)/20`; quote
  freshness `100*(3-quote_age_seconds)/3`; trade freshness
  `100*(3-trade_age_seconds)/3`; staleness headroom
  `100*(0.40-extension_R)/0.40`. Average the four.

`final_score = 0.50*setup + 0.30*context + 0.20*execution`. Keep every raw
factor. A final score at least 65 passes the score-threshold research arm. Also
retain an all-mechanical-candidates diagnostic with no score cutoff. The score
is a quality rank, not a win probability or a live threshold.

## 8. Outcome rules

Measure the stock setup with two equal research units. Use the M0.3A O-01 entry
search, quote-side fills, delays of 0, 5, 15, 30 and 60 seconds, session-close
horizon, missingness and adverse ordering. The confirming observation cannot be
its own fill. At entry, the frozen stop, range and 0.40R staleness rule must
still pass.

For `OR_FAILURE_STRUCTURAL_V1`, T1 closes one unit and T2 closes the second when
T2 exists. When the complete catalog proves T2 absent, the second unit is a
session-close runner. For each fixed exit policy, its one fixed target closes
both units. The original stop never moves, and a stop closes every open unit.
Long exits use bid and short exits use ask. Equal availability times resolve
adversely: stop before target.
With only one-minute bars, enter at the next bar open, check an opening gap first
and resolve a bar touching stop and target as stop first; label the arm
`BAR_PROXY / MODELED_COST_ONLY`.

Keep gross and after-cost results separate. Quote sides already include spread,
so do not charge it twice. Report 0.5 basis points per side plus a 1.0 basis
point per-side harsh sensitivity for stock slippage; stock commission is $0.
Executable short results additionally require point-in-time borrow availability
and cost. Without it, retain only a labeled directional result.

Option outcomes are a separate later arm. Missing exact contract, multiplier,
bid/ask, size, expiry or fee evidence cannot change the stock result. Unknown,
unfilled, halted, partially resolved and ambiguous outcomes stay in counts and
denominators and never become wins.

## 9. Required reporting and boundary examples

Report the two directions, two confirmation arms, two data modes and three exit
policies separately: 24 result arms before delay, score and cost slices. For each report
after-cost expectancy, win rate, payoff ratio, maximum drawdown and candidate
frequency with counts and denominators. Preserve losing arms. Report the
score-threshold arm separately from all mechanical candidates. Reserve exact
chronological development, calibration and untouched final dates from a
coverage-only source manifest before opening results.

The following are definition checks, not profitability evidence:

1. ORH 100.00 and ATR 0.50 give boundary 100.025 and meaningful-excursion level
   100.05. A trade at 100.05 passes both; 100.049 fails meaningful excursion.
   One tick at 100.01 does not cross the boundary. The downside mirror uses ORL.
2. A buffered crossing at 06:36:00 gives a 06:39:00 deadline. A qualifying
   event at 06:39:00 passes; one microsecond later fails. The extreme time does
   not restart the clock.
3. With OR 99.00–100.00, a final close at 99.99 is inside; 100.00 and 99.00 are
   not. The first qualifying final bar is frozen as the failure bar.
4. A short failure bar low of 99.80 is broken by 99.799 but not by 99.80. A long
   failure bar high of 100.20 is broken by 100.201 but not by 100.20.
5. Seven of ten fixed-grid samples strictly inside pass at 0.70. Six fail. One
   unknown sample makes the window `UNKNOWN`. One hundred messages in one second
   still supply one sample.
6. ATR 0.50 requires 0.015 displacement. A failed-upside short at 99.985 from
   ORH 100.00 passes equality; 99.986 fails. The long mirror uses ORL.
7. Upside extreme 100.50 and ATR 0.40 give short raw stop 100.52. With a $0.01
   increment it remains 100.52. Entry 100.00 gives R 0.52. The long mirror with
   downside extreme 99.50 gives stop 99.48 and the same R from entry 100.00.
8. Short edge 100.00, entry 99.80 and R 0.50 give extension 0.40 and pass;
   99.799 is stale. The long mirror uses edge 100.00 and entry 100.20.
9. Short entry 100.00 with catalog levels 99.20 midpoint, 99.10 VWAP and 98.60
   opposite edge, and R 0.50, selects midpoint at 1.6R as T1 and opposite edge
   at 2.8R as T2. A complete catalog whose nearest level is below 1.5R has no T1.
10. A bar that touches a long stop and T1 records the stop first. Missing short
    borrow blocks executable short expectancy but leaves the directional row.
    Missing option quotes do not alter the stock row.
11. Long entry 100.00 and stop 99.50 give R 0.50. The fixed 2R target is 101.00
    and the fixed 3R target is 101.50. Short mirrors them at 99.00 and 98.50.
    These stay separate from the structural-target result.
