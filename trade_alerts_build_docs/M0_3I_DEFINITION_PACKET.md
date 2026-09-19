# M0.3I deterministic research definitions — `VP_ACCEPT_LVN`

Version: `M03I_VP_ACCEPT_LVN_V1`  
Status: **FROZEN FOR OFFLINE RESEARCH**  
Date: **2026-09-13 Pacific**

## 1. Scope and authority

The owner's 2026-09-13 research authorization delegates the remaining ordinary
research choices to the agent. This packet freezes one finite first research
version for `VP_ACCEPT_LVN`. PLAYBOOKS and TESTING_AND_VALIDATION incorporate it
under their own authority. It does not approve a live alert, an order, a replay
result or a claim of profit.

Use exact decimal values before display rounding. Every input has event time,
available time, source identity, session identity and one compatible split and
price basis. A missing mandatory input is `UNKNOWN` and cannot pass. Let `s=+1`
for long and `s=-1` for short; directional rules below mirror under `s`.

## 2. Prior-session profiles — `PROFILE_M03I_V1`

Use only the immediately prior regular session, frozen before the current
session. Premarket, after-hours and current-session observations are excluded.
The primary approximate mode is `BAR_APPROX_PROFILE_M03I_V1`; the separate
full-fidelity mode is `TRUE_TRADE_PROFILE_M03I_V1`. Never pool their results.

For each of the `0.75`, `1.00` and `1.25` width multipliers, compute
`raw_width = multiplier * max(valid_tick, 0.0005 * prior_close)` and round it up
to the next whole valid tick. The result is at least one tick. Bins use the zero
price origin and half-open intervals `[i*width, (i+1)*width)`. A price exactly on
an upper boundary belongs to the next bin. Negative prices and a nonpositive or
unknown prior close, tick or width make the profile `UNKNOWN`.

In true mode, assign each eligible prior-session trade's full eligible share
volume to the bin containing its price. Corrections and cancels replace the
affected as-of trade before the freeze. Unknown trade eligibility or an
unexplained coverage gap makes true mode unavailable.

In approximate mode, each final, available, traded one-minute bar allocates its
reported volume equally across every bin whose interval contains its low, its
high or any price between them. The low and high bins are both included. A
zero-range bar allocates all volume to its one price bin. Fractional allocated
shares are retained exactly; no remainder is rounded into a preferred bin. A
certified no-trade minute contributes zero. An unexplained missing minute,
unknown bar volume or invalid high/low makes approximate mode `UNKNOWN`.

Create every bin from the bin containing the prior-session low through the bin
containing the prior-session high, including zero-volume bins. Raw total volume
must equal source total volume exactly. Smooth with a centered three-bin mean;
the missing neighbor beyond either profile edge contributes zero. Keep raw and
smoothed values. VPOC and value area use raw volume; LVN/HVN classification uses
smoothed volume.

## 3. VPOC, value area, shelves and LVNs

`VPOC_M03I_V1` is the raw-volume maximum. A tie goes first to the bin whose
midpoint is closest to prior close, then to the lower-price bin. Starting with
VPOC, build one contiguous value area. At each step compare the raw volume in
the next lower and next higher bin and add the larger. A tie goes to the side
whose candidate midpoint is closer to prior close, then to the lower side.
Stop after the first addition that makes cumulative raw volume at least 70% of
the prior-session total. `VAL` is the lower boundary and `VAH` the upper
boundary of the selected bins. Equality at 70% passes. Zero total prior volume
makes VPOC, value area and every dependent path `UNKNOWN`.

For percentiles, sort all smoothed bin volumes from low to high and use the
nearest-rank value at rank `ceil(p*n)`, with ranks starting at one. An LVN is a
maximal contiguous run at or below the 30th percentile, bounded immediately on
both sides by bins at or above the 60th percentile. It must span at least three
bins and price width at least `0.05 * DAILY_ATR_14_SMA_V1`; equality passes.
The two bounding shelf bins are not part of the LVN. An HVN is a maximal
contiguous run at or above the 60th percentile.

For long, the adjacent LVN is the first qualifying LVN whose near edge is at or
above VAH; for short it is the first whose near edge is at or below VAL when
searching downward. There can be no other qualifying LVN between the value edge
and this region. The next HVN is the first qualifying HVN wholly beyond the far
edge in direction `s`. Equality between a value edge and LVN near edge is
allowed. Missing either the adjacent LVN or next HVN blocks the LVN arm but is
retained for the matched accepted-value control.

## 4. Stability and current-session refill

`LVN_STABILITY_IOU_M03I_V1` compares the 1.00-width LVN price interval with the
corresponding closest LVN interval from each sensitivity profile. Corresponding
means the overlapping LVN with the largest price-length intersection; ties use
the nearer midpoint, then lower price. For each pair,
`IoU = intersection_length / union_length`. No overlap gives zero. Stability is
the smaller of the 0.75 and 1.25 IoUs and must be at least 0.60. Equality passes.
An unavailable sensitivity profile makes stability `UNKNOWN`.

Freeze the selected LVN's prior raw volume. Through each evaluation time,
allocate current-session volume inside the same fixed price interval using the
same profile mode and allocation rule. Define
`refill_ratio = current_inside_volume / prior_inside_volume`. A zero prior
inside volume makes the ratio `UNKNOWN` and blocks the LVN arm; it is not
infinite or zero refill.

Refill at or below 0.25 has no penalty. A ratio above 0.25 through 0.50 subtracts
10 score points. A ratio above 0.50 through 1.00 subtracts 25 points. A ratio
above 1.00 suppresses the LVN arm. Equality stays in the lower-penalty band.
Store the ratio and unpenalized score so this rule can be ablated.

## 5. Eligibility, acceptance, trigger and state

Use `ATR_1M_20_SMA_V1`, `DAILY_ATR_14_SMA_V1`,
`RVOL_OPEN5_MEAN20_V1` and exactly `SESSION_VWAP_BAR_HLC3_V1`. Require price at
least $5, known opening-five-minute RVOL at least 1.30, a positive uncrossed
two-sided quote no more than 3 seconds old, an eligible trade no more than 3
seconds old, spread at most 25 basis points, no halt, stable profile and a
complete adjacent-LVN/next-HVN structure. The repeated-cross kill uses four
total crossings, including the first break as crossing 1, as counted below.
Unknown coverage or correction state blocks.

The trigger window begins at 06:35 Pacific and ends before 07:15 Pacific. An
approach starts when directional distance to VAH for long or VAL for short is at
most `0.20 * ATR_1M_20_SMA_V1` without already being beyond the buffered edge.
Freeze `edge_buffer=max($0.01, 0.03*ATR_1M_20_SMA_V1)`. The first correctly
ordered covered pair of eligible trades no more than 3 seconds apart crossing
the buffered edge establishes the break: long
`previous <= VAH+edge_buffer < current`; short
`previous >= VAL-edge_buffer > current`. Equality alone does not cross.

Set the candidate's crossing count to 1 at that first buffered break; do not
count it again. From that break onward, count each later change between strict
sides of the frozen, unbuffered value edge (VAH for long, VAL for short) once,
using correctly ordered covered eligible trades. A trade exactly at the edge
neither increments the count nor changes the last strict side. Same-side trades
and duplicate observations of the same trade do not increment it. Thus the
first return inside is crossing 2, the next move outside is crossing 3, and the
next return inside is crossing 4. Crossing 4 immediately ends the untriggered
candidate, before evaluating any LVN trigger at that event; it does not wait
for four additional crossings after the first break.

`VALUE_ACCEPTANCE_90S_TRADE_M03I_V1` samples one covered eligible last trade at
each of the 90 fixed one-second instants ending at evaluation. A long sample is
above VAH and a short sample is below VAL. At least 63 of 90 samples must pass,
and the latest final available one-minute bar must close strictly outside the
value edge. Missing any fixed sample makes faithful acceptance `UNKNOWN`.
Message bursts inside one second count once.

After accepted value, `LVN_APPROACH` begins when directional distance to the
LVN near edge is at most `0.15 * ATR_1M_20_SMA_V1`. Freeze
`lvn_buffer=max($0.01, 0.03*ATR_1M_20_SMA_V1)`. The actionable trigger is the
first later correctly ordered covered pair no more than 3 seconds apart crossing
the LVN boundary: long `previous <= near_edge+lvn_buffer < current`; short
`previous >= near_edge-lvn_buffer > current`. Value acceptance must remain at least
0.70, price must be strictly on the correct side of the same-time VWAP, RVOL and
all gates must still pass, and refill must not suppress. Volume acceleration at
least 1.30 is recorded as a
preferred context arm, not a primary gate.

The exact path is `APPROACHING_VALUE_EDGE -> VALUE_EDGE_BROKEN ->
ACCEPTANCE_FORMING -> LVN_APPROACH -> ARMED -> ALERT_TRIGGERED`. The approach,
cross, first complete 90-second window, LVN distance, all current gates and LVN
cross respectively create those states. Profile failure, fourth total edge
cross (including the first buffered break as crossing 1),
halt, refill above 1.00 or 07:15 expiry ends an untriggered structure. Persist
every transition and reason.

The setup is stale when the modeled fill is strictly more than 35% through the
frozen LVN interval in direction `s`. Equality at 35% remains eligible.

## 6. Stop, targets and matched control

Freeze the acceptance swing extreme from eligible trades between the value-edge
break and acceptance decision. For long, raw stop is the lower of
`acceptance_swing_low - 0.05*ATR_1m` and `VAH - 0.05*ATR_1m`. For short, it is
the higher of `acceptance_swing_high + 0.05*ATR_1m` and
`VAL + 0.05*ATR_1m`. Thus the stop is beyond both structures. Round outward to
the valid tick. `R=s*(entry-stop)` must be positive.

For `VP_LVN_STRUCTURAL_V1`, T1 is the far edge of the LVN and must be at least
1.5R from entry. T2 is the leading edge of the next HVN and must be distinct and
beyond T1. The HVN center is the raw-volume-weighted mean of its member-bin
midpoints. The runner target is that center, or the prior VPOC-bin midpoint only
when it lies farther in direction `s`. Round every target toward entry to a
valid tick: down for long and up for short. Missing, zero-volume or nearer
targets block the structural LVN arm. Keep `VP_LVN_FIXED_2R_V1` and
`VP_LVN_FIXED_3R_V1` as separate exits; they still require a qualifying
structural T1.

The matched control is `VALUE_ACCEPT_CONTROL_M03I_V1`: the same accepted value
break and direction but no adjacent qualifying LVN. It uses the same stop
construction and fixed 2R/3R exits; no LVN structural target is invented. The
control is not a live setup.

Freeze these half-open matching buckets, with the final upper band unbounded:
five-minute decision-time bands starting 06:35 Pacific; RVOL bands
`[1.30,1.50)`, `[1.50,2.00)`, `[2.00,3.00)`, `[3.00,+infinity)`; minute ATR as
a fraction of prior close `[0,0.0025)`, `[0.0025,0.0050)`, `[0.0050,0.0100)`,
`[0.0100,+infinity)`; direction-signed same-instant SPY and sector returns from
the regular open in basis-point bands `(-infinity,-25)`, `[-25,25)`,
`[25,+infinity)`; spread bands `[0,10)`, `[10,20)`, `[20,25]` basis points;
20-session median dollar-volume bands `[$50M,$100M)`, `[$100M,$500M)`,
`[$500M,+infinity)`; direction-signed gap/daily-ATR bands
`(-infinity,-0.50)`, `[-0.50,0)`, `[0,0.50)`, `[0.50,1.00)`,
`[1.00,+infinity)`; and directional value-edge break distance/minute-ATR bands
`[0,0.05)`, `[0.05,0.10)`, `[0.10,+infinity)`. Exact upper bounds go to the
next band except the closed 25-basis-point spread ceiling.

Match without replacement inside the same development/calibration/final
partition and exact profile mode, width and every bucket above. When several
controls qualify, choose the nearest event time, then earlier event time, then
symbol sort order. An unmatched candidate remains visible.

## 7. Research score

`VP_ACCEPT_LVN_SCORE_V1` uses 45% Setup, 30% Context and 25% Execution. Define
`clamp(x)=min(100,max(0,x))`. Missing any factor makes the score `UNKNOWN`; do
not rescale.

- Setup: average acceptance `clamp(100*(acceptance-0.70)/0.30)`, stability
  `clamp(100*(stability-0.60)/0.40)` and remaining LVN traversal
  `clamp(100*(1-traversed_fraction))`.
- Context: average RVOL `clamp(100*(RVOL_5m/1.30-1)/2)`, VWAP distance in the
  setup direction `clamp(100*s*(price-VWAP)/ATR_1m)` and next-HVN room
  `clamp(100*((directional_HVN_distance/R)-1.5)/1.5)`.
- Execution: average `100*(25-spread_bps)/25`,
  `100*(3-quote_age_seconds)/3` and `100*(3-trade_age_seconds)/3`.

Subtract the refill penalty after weighting. A final score at least 65 enters
the score-threshold research population. Keep all raw factors. Score is a rank,
not a win probability, and cannot rescue a failed mandatory gate.

## 8. Outcome and finite comparison rules

Measure two equal stock research units. Use the M0.3A O-01 quote-side entry
search, delays of 0, 5, 15, 30 and 60 seconds, session-close horizon,
missingness and adverse ordering. At fill, frozen profile identity, acceptance,
stop, staleness, refill, liquidity and halt gates must still pass.

The structural exit closes one unit at T1 and one at T2; if T2 is filled, any
declared runner is diagnostic only. Fixed 2R and 3R exits close both units. The
original stop never moves and closes all open units. Long exits use bid and
short exits use ask. Equal availability times resolve stop before target.

With one-minute bars, enter at the next bar open, check an opening gap first and
resolve a bar touching stop and target as stop first. Label it
`BAR_PROXY / MODELED_COST_ONLY`; it cannot prove sub-minute acceptance, the LVN
cross or quote-side fills.

Keep gross and after-cost results separate. Quote sides already include spread.
Report stock slippage at 0.5 basis points per side and a 1.0 basis point per-side
harsh sensitivity; stock commission is $0. Executable shorts additionally need
point-in-time borrow and cost. Options remain separate.

Report two directions, two profile modes, three bin widths, two cohorts (LVN and
matched accepted-value control) and three exit policies as 72 separate cells.
Cross them with five delays, two score populations and two stock-slippage
assumptions for 1,440 primary comparisons. The structural exit is unavailable
for the no-LVN control and stays an explicit unavailable cell. Use the
10-session circular moving-block bootstrap and preregistered family threshold
`0.05 / 1440 = 1 / 28800`. Report after-cost expectancy, win rate, payoff ratio,
maximum drawdown and candidate frequency with counts and denominators.

Compare every metric and state each arm's strengths and weaknesses. Do not force
a winner; an unavailable or inconclusive family remains unavailable or
inconclusive.

Report stability pass/fail/unknown, four refill bands and volume-acceleration
context as separate strata and ablations, not hidden filters or extra primary
searches. Preserve losing, suppressed, stale, unstable, zero-prior-volume,
unknown, unmatched, unfilled, unresolved and short-borrow-blocked rows. Freeze
exact chronological development, calibration and untouched final dates from a
qualifying coverage-only source manifest before opening results.

## 9. Required boundary examples

These examples check definitions. They are not profit evidence.

1. With tick $0.01 and prior close $100, base raw width is $0.05. Multipliers
   produce $0.04, $0.05 and $0.07 after upward tick rounding.
2. At width $0.05, price $100.00 belongs to `[100.00,100.05)`; exactly $100.05
   belongs to the next bin.
3. A bar spanning three bins with volume 90 assigns 30 to each. A zero-range bar
   assigns all volume to one bin. Total allocated volume still equals source.
4. Edge smoothing uses zero outside the profile. It does not copy the edge bin
   or divide by two.
5. Equal VPOC volumes choose the midpoint nearest prior close, then the lower
   bin. A value-area addition reaching exactly 70% ends expansion.
6. Three low bins exactly at the 30th percentile, bounded by shelves exactly at
   the 60th percentile, qualify when width is exactly 0.05 daily ATR. Two bins
   or one exact unit less in width fail.
7. IoUs of 0.60 and 0.75 yield stability 0.60 and pass. An absent overlap gives
   zero. A missing sensitivity profile gives `UNKNOWN`.
8. Prior LVN volume zero makes refill `UNKNOWN`. Ratios 0.25, 0.50 and 1.00 stay
   in the lower penalty band; values just above them move to the next band.
9. Sixty-three of 90 fixed samples pass acceptance. Sixty-two fail. Ninety
   messages in one second count as one sample, not ninety.
10. With VAH $100.00 and buffer $0.01, the first break from $99.99 to $100.02
    sets crossing count 1. Trades at $100.00 then $100.03 leave it at 1;
    equality and a return to the same side add nothing. Later trades at $99.99,
    $100.02 and $99.99 give counts 2, 3 and 4. Count 3 does not kill; count 4
    immediately kills the untriggered candidate. A duplicate observation of
    any trade adds nothing. The short mirror at VAL $100.00 starts $100.01 to
    $99.98 (count 1), then $100.01 (2), $99.98 (3), $100.01 (4, killed).
11. A long acceptance swing stop at 99.40 and VAH stop at 99.55 select 99.40;
    the short mirror selects the higher price. Outward tick rounding follows.
12. A fill exactly 35% through the LVN remains eligible; one exact unit farther
    is stale.
13. LVN far edge exactly 1.5R away qualifies as T1. A nearer far edge blocks the
    structural arm even when a fixed 2R price exists.
14. Missing trade coverage blocks true mode but does not rewrite a complete bar
    profile. Missing a minute blocks approximate mode but does not manufacture a
    true profile.
15. A bar touching a long stop and target records the stop first. Missing short
    borrow blocks executable short expectancy but leaves the directional row.

## 10. Open evidence gates

Approximate replay needs complete final prior/current one-minute bars, certified
no-trade intervals, corrections, ticks, corporate actions, adjustment basis,
RVOL, VWAP, quotes, trades, halts and structural levels with availability times.
True mode additionally needs complete eligible trade-level volume, conditions,
cancels and corrections. Executable shorts need dated borrow facts; options need
exact contract and quote facts.

Replay requires a qualifying immutable source manifest and frozen chronological
development, calibration and untouched final-validation dates. Written rules
and synthetic checks do not validate an edge or authorize live use. All switches
stay off.
