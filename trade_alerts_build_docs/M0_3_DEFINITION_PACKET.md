# M0_3_DEFINITION_PACKET.md

Navigation note, 2026-09-05 Pacific: next-work labels in this approved packet
describe its approval-time handoff. Use ROADMAP §31 for current progress: M1.2
is complete and M1.3 is next. The approved packet body below is unchanged.

## 1. Status and decision scope

Date: 2026-09-05 Pacific. Packet: `M03A_ORB5_V1`. Status: **APPROVED FOR WRITTEN RESEARCH RULES — D-090**. Approved by the owner on 2026-09-05 Pacific after reviewing this packet. Formula and example content is unchanged by this approval update.

This is a supporting decision packet for M0.3, not a new canonical specification. [PLAYBOOKS.md](./PLAYBOOKS.md), [DATA_REQUIREMENTS.md](./DATA_REQUIREMENTS.md) and [TESTING_AND_VALIDATION.md](./TESTING_AND_VALIDATION.md) retain their authority. P-01–P-03 in [DECISIONS_AND_OPEN_QUESTIONS.md](./DECISIONS_AND_OPEN_QUESTIONS.md) govern approval. The owner explicitly approved the presented packet. D-090 records that later approval for F-01, F-02, F-03, B-01, B-02 and O-01. The earlier request to continue drafting was not treated as approval.

**Approved research choices:** use fixed, complete historical windows; start the first ORB variant with the documented 10–30 second acceptance entry B; use a known completed bar plus the breakout path for its stop; keep tape and quote/volume estimates separately named; measure two equal research units with fixed exits. These are explicit choices, not evidence that the strategy is profitable.

This packet closes the bounded definition-and-decision step **M0.3A**, covering common arithmetic and the first strategy's B-entry, stop and outcome rules. M0.3 remains IN PROGRESS. Entry A/C, the full structural-level producer, scoring, options ranking and statistical/release criteria remain required, with precise owners in §9. This approval alone does not complete Strategy #1 or permit an actionable alert, application implementation or live activation. The separate Databento testing-credit authorization is D-091; it is not a strategy-readiness decision.

D-090 approves all six rows below for written research rules only. Canonical incorporation is recorded in PLAYBOOKS §14, DATA_REQUIREMENTS §34 and TESTING_AND_VALIDATION §51. A change to these frozen rules requires a new proposed version and scoped decision; do not edit this approved version silently. Unfinished dependencies in §9 remain open.

| Approved scope | Research choice | Tradeoff / alternative not selected |
|---|---|---|
| F-01, under P-01 | Fixed-window arithmetic ATR: 20 regular-session minutes; 14 completed daily true ranges. | Unlike Wilder smoothing, older observations drop out at a fixed boundary. Wilder needs an explicit historical seed and remains a distinct alternative. |
| F-02, under P-01/P-02 | RVOL uses all 20 immediately prior sessions and their arithmetic mean; fixed premarket window; close-times-volume daily dollar-volume estimate. | Missing any required reference blocks the feature. A 10-session warm-up, median denominator, or skipped missing sessions would change selection. |
| F-03, under P-02 | Completed-bar HLC3 session VWAP is a named estimate; full trade VWAP stays separately required. | Bar prices cannot reproduce the actual distribution of traded volume. Never pool the two modes. |
| B-01, under P-01 | B-entry with explicit crossing, 10–30 second window, one-second acceptance samples, completed-bar/path stop, exact boundary treatment and reset. | A first-break and C retest entry remain required separate variants; neither is implicitly implemented by B. |
| B-02, under P-02 | Projected current-minute volume plus quote-mid acceptance, requiring at least 10 elapsed seconds of the current minute. | Delays some signals, especially around minute boundaries; does not supply tape intensity or trade acceptance. |
| O-01, under P-03 | Separate mechanical/delivery delay clocks, 60-second entry search, two-unit 50/50 exits, same-session horizon, conservative ambiguous-bar treatment. | Partial exits differ from all-out-at-T1 results. Exact quotes, bar estimates and missing execution costs remain separate. |

## 2. Clarifications already implied by the governing rules

These clarify existing requirements. The additional choices below are now approved within D-090's written-research scope.

- All user-facing times are Pacific; session boundaries come from the exchange calendar and are converted for display with `ZoneInfo("America/Los_Angeles")`. Scheduled holidays and early closes are data, not fixed assumptions.
- The opening range covers the five scheduled one-minute intervals beginning at the regular-session open. At the usual open, these start at 06:30 through 06:34. `ORH=max(high)`, `ORL=min(low)`, `OR_width=ORH-ORL`. Every interval must be known and final; certified no-trade intervals contribute volume zero and no invented high/low. At least one traded bar is needed for a range.
- A bar contributes only when `final=true`, `bar_end <= evaluation_time`, and `available_at <= evaluation_time`. A start-stamped minute ends 60 seconds after its start. Receipt after 06:35 delays opening-range availability. A revised bar cannot rewrite an earlier event.
- Price, range, ATR, VWAP, stops and targets use dollars per share. Volumes use shares. RVOL and range/ATR are ratios. One basis point is 0.0001 of price. `1%` is 0.01 internally. Preserve the original threshold values and inclusive/strict operators where specified.
- Use unrounded mathematical values for decisions; round only display copies. Positive-denominator comparisons may use cross-multiplication to avoid division rounding at boundaries. Canonical stored decimal values are authoritative; numerical type or binary-float representation must not change a boundary result. This does not approve a change to existing indicator helpers.
- UNKNOWN is distinct from zero and false. Missing prices, unexplained intervals, denominator zero, source changes or unproved adjustment compatibility cannot become a passing feature. Certified no-trade intervals must come from source evidence; absence alone is insufficient.
- Compute shared features once per immutable, versioned snapshot. Retain source/venue basis, reference intervals, revisions, availability and quality state. Strategies consume that snapshot; they do not independently fetch or recompute it.

## 3. Approved shared calculations F-01–F-03

The specified formulas in this section are **approved for research under D-090**; missing data and unfinished trade-eligibility rules remain blockers. References must be point-in-time, use one compatible source/venue/adjustment basis, and exclude information first available after evaluation. Corporate-action normalization must put prices and share volumes on the same as-of basis; otherwise the affected feature is UNKNOWN. A current-session early calculation must not depend on whether data later in that session turns out complete.

### F-01: volatility

`ATR_1M_20_SMA_V1`: select the latest 20 consecutive scheduled regular-session minute slots ending by evaluation time first; then require every selected slot to be final and available, including certified no-trade results. Do not skip a newer unavailable slot to use an older value. Use the prior session's tail when necessary at the open; overnight/non-session clock minutes are not slots. For each traded slot, `TR=max(H-L, abs(H-prev_close), abs(L-prev_close))`, where `prev_close` is the most recent known traded close in the same session. For the first traded slot of a session use `TR=H-L`, excluding the overnight gap from minute volatility. A certified no-trade slot has TR zero and does not invent a price or replace the last traded close. Any unexplained slot, including a missing needed previous-close reference, invalidates the window. ATR is `sum(TR)/20`; require all 20 TRs. Zero ATR cannot support an ATR-denominator gate.

`DAILY_ATR_14_SMA_V1`: use exactly the 15 immediately preceding completed regular sessions. For the newest 14, compute daily true range against the preceding daily close, including overnight gaps. Return `sum(TR)/14`. Missing a session or adjustment reference means UNKNOWN; do not substitute an older day. Today's partial daily bar is excluded. In this approved research #1 variant, the unqualified `ATR_1m` in the stop formula is the same 20-minute feature, frozen at crossing.

These are arithmetic averages, not the existing helper's continuing Wilder series. The helper's true-range arithmetic can be reused through an explicitly named extension; do not change old callers or let the amount fetched at startup select a different formula.

### F-02: participation, gap and session levels

Each historical comparison uses exactly the 20 immediately prior exchange sessions, including all required intervals in each. Do not skip a missing reference and reach farther back. Require a positive denominator; a certified zero-volume numerator may equal zero.

- `RVOL_OPEN5_MEAN20_V1`: sum the current opening five minutes' share volume, divided by the arithmetic mean of the same five opening minutes from those 20 sessions. Freeze the numerator when all five current intervals become available; this is opening-five-minute RVOL, not a rolling five-minute ratio.
- `PM_RVOL_MEAN20_V1`: total share volume from 01:00 Pacific up to, but excluding, the scheduled regular open, divided by the mean of those same complete windows from the 20 references. Freeze the current window at the regular open, but make it usable only when its coverage is known. A pending final premarket interval delays availability.
- `DOLLAR_VOLUME_CLOSE_PROXY20_V1`: for each of the 20 prior regular sessions compute `regular_close * regular_share_volume`. Sort the 20 values and average the tenth and eleventh for the median. This is a daily dollar-volume estimate; exact traded-dollar volume, if available, is a separate named mode and cannot be silently substituted.
- `GAP_OPEN_V1=(first regular-session trade - prior regular-session close)/prior regular-session close`. The opening trade must be known as an opening observation, not inferred from a later still-incomplete bar. Zero/missing prior close means UNKNOWN. Use its absolute value only where #1 requires `abs(gap)`.
- `PMH/PML`: extrema of traded prices/bars in the complete current premarket window, frozen at the open. `PDH/PDL`: prior completed regular-session extrema. No trades means unavailable levels, not zero. Missing expected coverage means UNKNOWN. All extrema use the same approved basis as current prices.

F-02 does not establish that the existing providers deliver these complete histories. Source/coverage proof remains M0.2 work.

### F-03: VWAP modes

`SESSION_VWAP_BAR_HLC3_V1 = sum(((H+L+C)/3)*volume)/sum(volume)`, selecting all scheduled regular-session one-minute intervals from the open through the latest interval ending by evaluation time first, then requiring every selected interval to be final and available. Do not drop unavailable intervals from the selected window. Reset at each regular open. Certified no-trade intervals contribute zero weight. An unexplained gap or zero total volume means UNKNOWN. This is a bar estimate and must be labeled in every snapshot/event/result.

`SESSION_VWAP_TRADES_V1 = sum(trade_price*trade_shares)/sum(trade_shares)`, over eligible regular-session trades known at evaluation. It requires complete coverage plus a frozen treatment of trade conditions, duplicates, cancels and corrections under M0.2/M0.3B. It remains required and BLOCKED until those inputs/rules are verified. A polling last price is not a complete tape.

## 4. Approved first research variant: B-01

Variant names: `CRVOL_ORB5_B_TAPE_V1` and `CRVOL_ORB5_B_QUOTE_PROJECTED_V1`. Both are approved written research definitions under D-090; neither is implemented or activated. Crossing, acceptance, participation and stop-path evidence differ as defined in §§5–6. VWAP mode is a separate recorded feature-version dimension. Configure one mode per live strategy instance. Research runs each mode as an isolated arm with its own state/quota, so enabling tape cannot change the quote arm. Do not automatically switch modes during an attempt or combine results across modes. A live failover/hybrid and its priority rules require a separate explicit definition; none is selected here.

### Hard gates and approved research treatment of approximate boundaries

Use the half-open evaluation window from scheduled open + 5 minutes through, but excluding, scheduled open + 45 minutes (normally 06:35–07:15 Pacific). Opening range must already be available. Price means the latest valid regular-session trade: price >= $5; median daily dollar-volume estimate >= $50M; opening RVOL >= 2.0; and `0.08 <= OR_width/daily_ATR <= 0.65`.

`stock_in_play = confirmed_catalyst OR (PM_RVOL >= 2.5 AND abs(gap) >= 0.01) OR (RVOL_OPEN5 >= 3.0)`. Use three-valued logic: a known true branch makes the OR true; no true branch plus an unknown branch is UNKNOWN. This does not waive separately mandatory premarket/structural coverage. Catalyst and macro facts must have versioned classification and availability; this packet does not invent their classifiers. Unknown mandatory halt/macro/structure status suppresses action.

Require a non-delayed, non-crossed, positive bid/ask with `spread_bps=10000*(ask-bid)/((ask+bid)/2) <= 20`. Require both quote age and last-trade age <= 3 seconds, measured from their separate event times at evaluation; future timestamps are invalid. At exactly 20 bps the action gate passes; above 20 it fails. The original >25 bps severe-spread suppression is retained; exactly 25 still fails the action gate. Halt=true, mandatory halt status unknown, or an active/unknown mandatory macro blackout prevents action. Defining the macro blackout interval remains M0.3B.

Long requires latest trade > chosen VWAP; short requires latest trade < chosen VWAP. Preserve the next-obstacle <1R veto, >=1.5R T1 room and >0.35R stale rule. Section 6 defines the approved research geometry; unavailable mandatory target/obstacle coverage blocks action.

### Crossing, state and heads-up

Before a crossing, compute `buffer=max(0.01,0.05*latest_ATR_1M_20)`, and candidate boundary B=`ORH+buffer` long or `ORL-buffer` short. At each eligible observation, compare both the preceding and current price with this SAME candidate B. Crossing requires `previous < B <= current` long or `previous > B >= current` short. Both prices must come from the chosen mode, be consecutive covered observations in that mode, and be fresh at the crossing. The first observation after a gap cannot establish a crossing. A decrease in ATR with flat price is not a breakout. Freeze OR, B, ATR, mode and anchor-bar identity at crossing time t0; later calculations cannot move these references within the attempt.

Before the OR is ready use WATCHING. With the OR ready and non-price eligibility satisfied use SETUP_FORMING. When required live gates and preliminary risk/target checks pass, use ARMED, allowing a fresh crossing even if no heads-up was emitted. Heads-up is emitted at most once for the pending direction/structure when an otherwise eligible long price lies in `[ORH-buffer,ORH]`, or short price in `[ORL,ORL+buffer]`, and preliminary R:R is valid. Calculate preliminary stop from the latest completed traded minute using the stop buffer; entry is B. Recompute/freeze actual geometry at trigger. The typical 30-second warning is not a minimum delivery guarantee, and a price jump may trigger without prior heads-up.

From t0+10 through t0+30 seconds inclusive, evaluate once per second. At each evaluation t=t0+k, acceptance uses exactly ten samples at `t-9,...,t` seconds. Thus the first window samples t0+1 through t0+10, spanning ten elapsed seconds after crossing. Use only observations already available at each sampling instant; later arrivals cannot repair that sample. All ten samples must be known; at least seven must lie at/beyond frozen B in the chosen direction. A burst of messages still supplies only one sample per instant.

At the first passing window, if intensity/projection and every current mandatory gate also pass, freeze entry/stop/targets/scores and record ALERT_TRIGGERED once. Missing score/target definitions cannot be treated as passing checks. The last trade must still be at/beyond B even in quote-proxy mode. If none passes by t0+30, enter WAITING_FOR_RESET. A final one-minute close strictly back inside the unbuffered OR boundary invalidates the current attempt immediately; it is also the required reset before another fresh crossing. A halt, unexplained coverage loss or unknown mandatory input invalidates the attempt and requires reset; do not resume a partially observed window. The one exception is a just-ended bar awaiting its final version: hold action while that bar-dependent feature is UNKNOWN, continue collecting covered sub-minute samples, and keep the original t0+30 deadline. This does not permit skipping the pending bar; confirmed missing coverage still invalidates. Expire pending attempts at the evaluation-window end.

Approved research structure identity is `(session, symbol, direction, mode, attempt_number)` plus frozen input references. Before crossing, reserve `pending_attempt_number=started_attempt_count+1` for the heads-up and persist its configured mode. A crossing with no heads-up allocates that same next number; increment started_attempt_count once on crossing. A pre-crossing heads-up that loses eligibility retains its reserved number and dedup record until crossing or session expiry. Start a new attempt number only on a fresh crossing after the required reset, not on every quote recross. Permit at most two such attempts per direction/session, including failed attempts; this is an explicit interpretation of the approximate two-structure prior. Only the configured live mode can emit for that strategy instance; mode changes do not authorize a fresh production quota. Independent research arms have independent quotas and cannot send alerts. One heads-up and one mechanical action per structure. Following a mechanical action, a new attempt also requires at least 10 minutes elapsed from that mechanical event; equality passes. Delivery time does not reset the cooldown. Freeze/recover all identity, reset and quota facts across restart.

## 5. Approved research acceptance and participation definitions

**Tape mode (B-01):** crossing/sample price is the most recent eligible regular-session trade. At every sample its age must be <=3 seconds and trade coverage must be known; otherwise the sample is UNKNOWN. Repeated use of one still-fresh trade on the fixed grid is allowed, but repeated delivery of that trade cannot increase volume. `INTENSITY_15S_MEAN20_V1` is total eligible executed shares with event times in `(t-15s,t]`, known by t, divided by the mean of the identical session-relative 15-second intervals in the 20 immediately prior sessions. Require complete numerator/reference coverage, the same trade/venue eligibility, and a positive mean. `>=1.50` passes. Historical one-minute bars cannot establish this value. Late trades or missing coverage do not justify claiming a complete 15-second interval.

**Projected quote mode (B-02):** crossing/sample price is midpoint of the latest two-sided positive non-crossed quote known at that instant, age <=3 seconds. Ten fixed-grid midpoint samples and the 0.70 threshold are retained, but label them quote acceptance. Require the fresh last trade also beyond B at trigger. This does not claim trade acceptance.

At evaluation t let m be the current scheduled one-minute interval and e the seconds since its start, `0 <= e < 60`. Require `e >= 10`. `V_m(t)` is the eligible share volume actually observed from m's start through t, not the day's cumulative volume. A cumulative counter may supply it only with a verified minute-start baseline, complete same-basis coverage and no unknown reset/correction. `REF_m` is the arithmetic mean of the complete corresponding one-minute volumes in the 20 immediately prior sessions. Then `PROJECTED_RATIO=(60/e)*V_m(t)/REF_m`; require `>=1.50`. Missing baseline, negative delta, unexplained gap, mixed venues or denominator zero means UNKNOWN.

Recompute using the minute that contains t, including its own reference. Never carry a previous minute's numerator into the next. During the first ten seconds of a new minute this mode cannot pass; it may wait within the existing t0+30 limit. At e>=10 its trailing ten acceptance samples are all in the current minute. Finalized one-minute bars alone cannot recreate this projected path. A completed-bar alternative would require a separate proposal; it is not silently substituted here.

Persist each sample/time/age, first-cross reference, chosen mode, coverage flags, raw and projected volumes, elapsed seconds and historical numerator/reference inputs. Keep both full and degraded requirements tracked when data is unavailable.

## 6. Approved B-entry risk and target selector contract

At t0 freeze the latest completed traded one-minute bar whose end and availability are <=t0, including its ID/high/low. Require complete interval coverage between that bar and t0. Long anchor is the minimum of its low and the eligible traded prices observed from t0 through the trigger; short anchor is the corresponding maximum. In quote mode use a covered stream of timestamped last trades from the quote source, explicitly an observed-path estimate. Missing path coverage invalidates the attempt. Do not use a still-forming bar's eventual high/low or later-confirmed swing.

Apply long raw stop=`anchor_low-0.05*frozen_ATR`; short raw stop=`anchor_high+0.05*frozen_ATR`. The approved research stop rounding is outward to the instrument's known valid price increment: floor for long, ceiling for short. Unknown increment blocks an actionable stop. Keep raw and rounded values. Trigger B stays unrounded. D-090 approves this outward rounding for the named research variants; other strategies and existing callers remain unchanged.

At mechanical trigger let E be the latest eligible trade, not B and not a modeled fill. Let s=+1 long or -1 short. Require `R=s*(E-stop)>0`. Directional extension is `s*(E-B)/R`; exactly 0.35 passes, greater fails. Freeze E, stop and R. Preliminary heads-up geometry is not the final risk reference.

The selector consumes a versioned, complete-as-required catalog of known structural levels and obstacles. Each carries price, kind, availability and coverage. Full required families remain PMH/PML, PDH/PDL, OR measured move, ATR, AVWAP, profile and other confirmed structure. Current formulas in this packet cover only PM/prior-day/OR levels: long measured move=`ORH+OR_width`; short=`ORL-OR_width`. Missing an upstream family is not proof that no obstacle exists. Completing the remaining level producers and their applicability/priority rules is an M0.3B prerequisite to action.

Within a complete catalog, consider levels with `s*(level-E)>0`; sort by directional distance, merge equal prices and retain all labels. The closest obstacle <1R suppresses; one at 1R through less than 1.5R also leaves insufficient T1 room and suppresses. Select T1 as the closest admitted structural target >=1.5R, provided no nearer blocking obstacle exists. Select T2 as the next distinct admitted target >=2.5R beyond T1. If no T1 exists, suppress; if no T2 exists, keep it explicitly unavailable because the governing rule says ideally. An outcome variant may place a second unit only where T2 exists, or use the specified horizon for that unit; do not invent a structural target. New ATR multiples/AVWAP anchors/profile calculations are not approved by this selector.

## 7. Approved research outcome policy O-01

This section defines the research policy approved under D-090, not trade execution or a profitability result. It does not authorize real or paper orders. Existing underlying, options, mechanical, delivered and human-decision records remain separate.

For each candidate test delays `0/5/15/30/60` seconds independently. Mechanical origin is recorded ALERT_TRIGGERED; delivery origin is confirmed receipt, when known. Unknown/failed delivery has no delivered-delay result. For origin plus delay d, entry search starts strictly after that instant. Availability may equal start+60 seconds, but must always be strictly before the strategy entry-window end (normally 07:15). Both conditions bound the search. Require both provider timestamp and availability strictly after the start; order observations by availability, then provider time and a stable source sequence. No confirming observation may also be the entry fill observation. Record requested delay, first eligible observation and actual delay.

For quote-mode shares, long entry is ask and short entry is bid. Require current quote freshness/coverage and all still-applicable halt, spread, macro, mode and data gates. Freeze the original stop/targets. Require actual entry on the correct side of stop, at/beyond B, extension from original E <=0.35 original R, and T1 remaining room >=1.5 actual-entry R. Here `actual_R=s*(actual_entry-stop)`, extension=`s*(actual_entry-E)/original_R`, and room=`s*(T1-actual_entry)/actual_R`. A known geometry invalidation ends the intent as UNFILLED; a missing observation may wait only within the window. Preserve reason and candidate count. Do not move stops/targets to repair a late entry.

Use two equal research units, solely a measurement convention: two shares, or two identical whole option contracts where exact quote coverage supports them. T1 closes one unit; T2 closes the second. If T2 is unavailable or unreached, close the second at the horizon. Keep the original stop unchanged after T1. A stop closes every remaining unit. At a stop, quote-mode long exits at observed bid and short at ask; a gap is not filled at a better fictional stop price. A target requires the exit-side quote to reach its frozen level, and uses that level without assuming favorable price improvement.

Horizon is the calendar's regular-session close on the alert date, including early closes. Quote-mode remainder uses the latest valid exit-side quote available by that close, with provider timestamp no earlier than close-3 seconds and no later than close, availability no later than close, and known coverage through close. Otherwise remainder is UNRESOLVED. This is a modeled quote exit, not evidence of a real fill. A halt spanning required execution, lost path coverage, damaged adjustments or data ending early leaves affected units UNRESOLVED; do not invent resumption or closing prices.

A separate `BAR_ONLY_ORB5_O1_PROXY` study may use the next observed one-minute bar open after a bar-supported reference event and the last regular bar's close for the horizon. It cannot establish B's sub-minute trigger, exact-quote returns, or 5/15/30-second delivery effects. Evaluate each bar's open before its range: stop gap exits at open; favorable target gaps fill at frozen targets. For remaining units, a bar touching both stop and next target uses STOP_FIRST_CONSERVATIVE and stores `same_bar_ambiguous=true`. Also report a sensitivity that leaves such outcomes unresolved. If T1 exited earlier, a later stop affects only the second unit. Bar estimates require separately frozen spread/slippage/cost assumptions before any after-cost expectancy claim.

Options require exact contract identity, multiplier, two-contract displayed liquidity, bid/ask timestamps and underlying alignment. Entry uses the first valid ask after the chosen underlying entry reference, with at most 60 seconds search inside the same entry window and surviving underlying geometry; record its own actual time. An underlying exit closes the corresponding contract at the first valid bid whose provider and availability times are both at/after that exit and whose availability is no later than exit+3 seconds; missing/halted coverage makes that leg unresolved. Do not invent option prices from stock returns or invent an option-price stop. If the underlying invalidates or any underlying unit exits at/before option entry, the two-contract option result is UNFILLED; do not enter after an exit it must reproduce. Two contracts with complete exits incur `4 * $0.45 = $1.80` in the reused fee convention; missing exits do not create a fabricated net result. Additional share fees, short borrow, option slippage/quote-size eligibility and non-fee costs still require the P-03 completion row in §9.

Report total candidates, unfilled, filled, fully resolved, partially resolved, unresolved, ambiguous and delivered counts by data/version/delay mode. Fully resolved per-candidate R is `sum(s*(each_unit_exit-actual_entry))/(2*actual_R)` for the stock model; also retain original-R results separately. Keep partial observed cash flows without counting them as full resolved returns. MFE/MAE and T1/T2 hit indicators remain separate diagnostics. No short executable-profit claim without dated borrow eligibility/costs. No primary after-cost expectancy, promotion or win-probability claim until the remaining cost/statistical contract is frozen under P-03.

## 8. Hand-worked acceptance fixtures

These are synthetic arithmetic checks for the definitions approved under D-090. They do not test a running strategy or establish historical profitability. All times are Pacific. Require mirrored long/short cases during later implementation.

| ID | Input | Expected result |
|---|---|---|
| FX-01 | Fifth opening interval ends 06:35:00 but is available at 06:35:02. Evaluate 06:35:01, then 06:35:02. | First OR UNKNOWN; second available only if all other intervals are known/final. |
| FX-02 | Minute TRs: nineteen at 0.20 and one at 0.40. | ATR=0.21; buffer=max(0.01,0.0105)=0.0105. |
| FX-03 | Daily TRs: thirteen at 2.00 and one at 3.40; OR width 1.05. | Daily ATR=2.10; width/ATR=0.50. |
| FX-04 | Typical prices 100 and 102; volumes 1,000 and 500. | Bar VWAP=100.666666…; not 101 and not an exact trade VWAP. |
| FX-05 | Prior five-minute totals [40,45,50,55,60] thousand repeated four times; current total 100,000. | Mean 50,000; RVOL=2.0 passes. One missing reference makes UNKNOWN. |
| FX-06 | Premarket reference [300,350,400,450,500] thousand repeated four times; current 1,100,000. | Mean 400,000; PM RVOL=2.75. |
| FX-07 | ORH=100.8030, buffer=0.0105; compare 100.8134 and 100.8135. | Boundary=100.8135; first fails, second passes. Display rounding cannot change either result. |
| FX-08 | ORH=101, ORL=100, daily ATR=4, minute ATR=0.4, B=101.02; anchor low=100.80; tick=0.01; E=101.03. | Stop=100.78; R=0.25; extension=0.01/0.25=0.04. Assuming a complete externally versioned catalog admits targets 101.50 and 102.00: 1.88R and 3.88R. |
| FX-09 | Short ORH=51, ORL=50; minute ATR=0.4; B=49.98; anchor high=50.20; tick=0.01; E=49.97. | Stop=50.22; R=0.25; extension=0.04. Assuming a complete externally versioned catalog admits targets 49.50 and 49.00, they give 1.88R and 3.88R. |
| FX-10 | Ten eligible sample prices [101.01,101.02,101.03,101.01,101.02,101.01,101.02,101.03,101.02,101.03], B=101.02. | Seven of ten pass, ratio=0.70. One UNKNOWN sample prevents passing; 100 messages at one sample time add no observations. |
| FX-11 | Current minute elapsed=20s, observed volume=10,000; reference minute mean=20,000. | Projected ratio=(60/20)*10000/20000=1.50 passes. At elapsed=5s mode cannot pass. |
| FX-12 | Cross at 06:40:55; first B check at 06:41:05; assume the 06:40 final close causes no inside-OR reset and coverage stays valid. | Quote projection waits because new-minute elapsed=5s. Earliest possible new-minute check is 06:41:10, within t0+30; it uses only 06:41 numerator/reference. |
| FX-13 | Mechanical event 06:40:00; confirmed delivery 06:40:12; fresh quotes with provider and availability times both at :01,:16,:31,:46. | For 15s delay, mechanical observation=:16; delivered=:31. Unknown delivery yields no delivered result. |
| FX-14 | An existing position entered on an earlier bar at 150.35, stop=149.85; T1=151.15, T2=152.10; later bar open=150.50, high=151.30, low=149.70. | Stop and T1 touched: conservative bar result -1R, ambiguity recorded; sensitivity unresolved. |
| FX-15 | Same geometry; half exits T1, rest at horizon 150.60. | Average stock return=(0.80+0.25)/(2*0.50)=1.05R before costs. |
| FX-16 | Two identical options: entry ask=2.00; one exits bid=2.50, other=3.00; multiplier=100. | Gross=150.00; reused contract fees=1.80; 148.20 after those fees only, before any other unresolved costs. |
| FX-17 | E=150.35, stop=149.85, T1=151.15; delayed long ask=150.50. | Extension=0.30 original R passes; remaining room=0.65/0.65=1.00 actual R fails; UNFILLED. |
| FX-18 | Flat consecutive price=101.02; ATR decreases so candidate B falls from 101.03 to 101.01. | Both prices are already beyond the new B; no fresh crossing. |

## 9. Remaining decisions and exact continuation

| Required work retained | Owner / closure condition |
|---|---|
| Decision on F-01–F-03, B-01/B-02 and O-01 | COMPLETE for written research rules: owner-approved D-090 on 2026-09-05 Pacific; canonical references synchronized. Unfinished dependencies below remain open. |
| Entry A first-break and C retest/hold | M0.3B / M6: exact strongest-clean conditions, swing confirmation, acceptance, state/reset and risk fixtures. B alone cannot complete #1. |
| Full structural-level/obstacle catalog and macro/catalyst facts | M0.3B / M3.4–M3.5 / M4.3 / M6: freeze applicability, ATR multiples, AVWAP anchors, profile/other structure confirmation, event blackout duration, news classification and availability. Missing mandatory inputs block action rather than silently disappearing. |
| Setup/Context/Execution scoring | M0.3B / M4.4 / M6: exact factors, normalization, missing-factor treatment, benchmark/sector mapping, ties and boundaries; retain #1 weights 50/30/20. No invented numeric component or uncalibrated win probability. |
| Options suitability/ranking including 0DTE | M0.3B / M4.7 / M14.1–M14.5: exact spread/liquidity/IV/Greek filters, expiry calendar, OptionScore factors/ties, stricter 0DTE rule and original ~65 threshold treatment; retain 1–5 DTE and abs(delta) 0.50–0.70 target ~0.60. Stock validity survives missing option quality, but required option capability remains incomplete. |
| Cost, historical design and promotion contract | P-03 / M0.3B / M5.2 / M16–M17: primary and sensitivity slippage/fee assumptions, borrow, exact time splits, overlap purge, uncertainty method and measurable promotion gates before results. O-01 does not approve these missing values. |
| Tape/quote/history fidelity and corporate actions | M0.2 / M2: prove time/receipt completeness, allowed trade conditions, corrections, size/venue compatibility, valid price increment and the exact consecutive history required above. No entitlement or full data access is established by formulas. |
| Other seven strategy definition rows | M0.3 / PLAYBOOKS §13 and M7–M13: all remain required with their existing thresholds and data modes. No implementation-order gate or full-fidelity obligation has been removed. |

**Exact next milestone: M0.3B**, starting the shared structural-level/obstacle and scoring definitions needed for `CRVOL_ORB5`, followed by A/C entries, options and the remaining P-03 terms. M0.3A approval is complete and must not be requested again. New behavior-changing choices remain proposals until their own scoped decision; independent documentation drafting can continue. M0.4 remains the first offline compatibility milestone after the selected contracts are actually closed and implementation is authorized.

## 10. Repository reuse evidence

These inspected integration facts support reuse. D-090 supplies research-rule approval; neither the inspection nor approval proves live data access.

- [Existing indicator helpers](../consensus_engine/analysis/indicators.py): `atr` (true range, arithmetic seed then Wilder smoothing), `vwap` (weighted supplied values), `relative_volume` (currently returns zero for an unusable denominator; a new path must preserve UNKNOWN without changing existing callers).
- [Calendar helpers](../consensus_engine/utils/time_context.py): reuse `session_dates` and `session_bounds`; keep the new visible clock Pacific.
- [History adapter](../consensus_engine/utils/prices.py): `fetch_history` can fall back between providers; its returned frame alone does not prove provenance, finality or availability. The new compatible boundary must carry those facts.
- [Schwab client](../consensus_engine/scanners/schwab_client.py): quote, history and chain mappings can be extended; quote time and last-trade time are distinct. Do not make a separate data client.
- [Existing measurement](../consensus_engine/trade_tracking.py): exact selected-contract identity, quote classification and ask/bid cash-flow arithmetic provide reuse points. Preserve old measurement behavior and its fee rule.

No application code was added or executed for this packet. Verification consists of independent definition review, synthetic arithmetic and document consistency checks; implementation, market-data coverage and profitability are untested.
