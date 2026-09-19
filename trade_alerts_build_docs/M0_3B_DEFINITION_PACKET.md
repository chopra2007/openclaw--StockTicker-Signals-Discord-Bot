# M0_3B_DEFINITION_PACKET.md

## Current research authority — 2026-09-13 Pacific

**REOPENED FOR AGENT-OWNED RESEARCH REVISION.** The owner explicitly delegated the remaining entry, stop/target, filter, option-selection and validation choices for research and implementation. See [RESEARCH_AUTHORIZATION_20260913.md](./RESEARCH_AUTHORIZATION_20260913.md). This removes the requirement to ask the owner to approve each research parameter. It does **not** adopt the unseen `M03B_ORB5_V1` packet verbatim or establish profitable/live rules.

The current required opening-range research scope is **5-minute and 15-minute ranges × immediate, confirmed and retest entries × long and short directions**: twelve separately reported base combinations. No entry style, range duration or direction may be excluded before evidence. Compare after-cost expectancy, win rate, payoff ratio, drawdown and frequency; do not force one winner. Common fixed 1:3 risk/reward is a required research candidate, not the sole exit policy.

Keep D-090 and `M03A_ORB5_V1` immutable as a historical research arm. Create new explicit versions for changed rules, including the 15-minute range; do not relabel the old five-minute evidence. The agent must freeze exact variants, source requirements, cost/fill assumptions and untouched final-validation dates in the governing PLAYBOOKS and TESTING_AND_VALIDATION files before inspecting corresponding results. Incorporation and deterministic boundary examples remain unfinished M0.3B work. Source coverage, historical evidence, forward/shadow evidence and live-activation gates remain required.

The original preparation below is retained as historical proposed material. Its requests for further owner review and adoption are superseded **only for research/implementation choices** by the current delegation. Its unvalidated numbers may be selected as named research arms, revised before results, or compared with reasonable alternatives; they are not approved operational thresholds. All other seven playbooks remain required. The current incremental-spend limit is **$0**; D-091's earlier allowance remains historical and does not authorize new spending.

## Agent-selected preregistration — `M03B_OR_RESEARCH_V2`

Status: **FROZEN FOR OFFLINE RESEARCH / DATA MANIFEST BLOCKED**, 2026-09-13 Pacific. The owner delegation permits these research choices. It does not authorize live use. No strategy result was inspected while selecting them. D-090 and every `M03A_ORB5_V1` record remain unchanged as a separately reported historical arm.

### Opening ranges and common rules

`OR5_V2` uses the five scheduled one-minute regular-session slots beginning at 06:30 Pacific. `OR15_V2` uses the fifteen slots beginning at 06:30 Pacific. Every slot must be final and available. A certified no-trade slot adds zero volume and no invented high or low. An unexplained gap makes the range `UNKNOWN`. At least one traded slot is required. The range high is the greatest raw high, the range low is the least raw low, and width is high minus low. OR5 becomes available no earlier than 06:35; OR15 no earlier than 06:45. Each entry window starts when its own range is available and ends at 07:15, half-open.

Both durations keep the existing common gates so range duration is the changed dimension: price at least $5; 20-session median daily dollar volume at least $50 million; `RVOL_OPEN5 >= 2.0`; range width divided by frozen daily ATR from 0.08 through 0.65 inclusive; known nonhalted state; spread at most 20 basis points; quote and last-trade ages each at most three seconds; no active or unknown mandatory macro blackout; `stock_in_play` true under the existing three-branch rule; directional completed-bar VWAP alignment; complete structure catalog; nearest obstacle at least 1R; and the existing `<=0.35R` extension rule. Missing mandatory facts block the candidate. The 15-minute arm still uses the five-minute RVOL fact so it does not gain a different participation filter.

For duration `d`, long boundary `B=ORH+max($0.01,0.05*ATR_1m)` and short boundary `B=ORL-max($0.01,0.05*ATR_1m)`. Freeze the range, boundary, daily ATR, one-minute ATR, direction, source mode and attempt identity at the first eligible crossing. Prices and ratios are compared before display rounding. Long/short logic uses direction sign `s`, where long is `+1` and short is `-1`; crossing means the prior eligible trade is strictly behind B and the current trade is at or beyond B in direction `s`. A future or missing event time is unavailable. Maximum attempts, reset, cooldown, expiry, heads-up identity and recovery use D-090 unchanged.

### Twelve base combinations

Each row below is a separate tape-data arm and must be reported even when it loses or has no usable data. `IMM` uses the historical proposal's §2.7 exact ten pre-cross one-second samples and requires at least 7 of 10 in the approach band. `CNF` uses D-090 B's exact crossing and post-cross evaluation from 10 through 30 seconds, with ten fixed one-second samples and at least 7 of 10 at or beyond B. `RTS` first obtains that same confirmation and then uses §2.8's first retest, two-left/two-right plateau confirmation, ten-minute deadline, `max(valid_tick,0.10*ATR_1m)` band and final 7-of-10 acceptance. The duration token changes only the frozen range and start time. The direction token applies the exact mirrored comparisons.

| Base ID | Range | Entry | Direction |
|---|---:|---|---|
| `OR5_IMM_L_V2` | 5 minutes | immediate | long |
| `OR5_IMM_S_V2` | 5 minutes | immediate | short |
| `OR5_CNF_L_V2` | 5 minutes | confirmed | long |
| `OR5_CNF_S_V2` | 5 minutes | confirmed | short |
| `OR5_RTS_L_V2` | 5 minutes | retest | long |
| `OR5_RTS_S_V2` | 5 minutes | retest | short |
| `OR15_IMM_L_V2` | 15 minutes | immediate | long |
| `OR15_IMM_S_V2` | 15 minutes | immediate | short |
| `OR15_CNF_L_V2` | 15 minutes | confirmed | long |
| `OR15_CNF_S_V2` | 15 minutes | confirmed | short |
| `OR15_RTS_L_V2` | 15 minutes | retest | long |
| `OR15_RTS_S_V2` | 15 minutes | retest | short |

### Frozen stop and exit candidates

Each base row is crossed with both stops and all three exits. There is one common filter policy and one tape source mode. The preregistered family therefore has exactly `12 * 2 * 3 = 72` result arms. No arm may be removed, added, tuned or renamed after a return is read.

`STOP_ENTRY_STRUCTURE_V2` uses the entry-specific anchor. IMM and CNF use the completed-bar/path anchor and `0.05*frozen_ATR` buffer from D-090. RTS uses the confirmed retest extreme and the same buffer. Long subtracts the buffer and rounds down to the valid price increment. Short adds it and rounds up. `STOP_FAR_OR_EDGE_V2` uses `ORL-0.05*frozen_ATR` for long and `ORH+0.05*frozen_ATR` for short, with the same outward rounding. A stop must remain strictly adverse to entry and produce positive R or that arm is invalid.

`EXIT_FIXED_2R_V2` closes both units at the first eligible 2R touch. `EXIT_FIXED_3R_V2` closes both at the first eligible 3R touch. `EXIT_D090_STRUCTURE_V2` preserves D-090's two-unit 50/50 T1/T2 selector and same-session remainder rule. Fixed targets are calculated from the actual delayed entry and frozen stop: long `E+kR`, short `E-kR`. Exact event order controls with tape/quotes. Equal provider and availability times resolve adversely: stop before target. The separate one-minute bar estimate also resolves a bar touching stop and target as stop first. At regular-session close, use the first valid exit quote at or after close and available within three seconds; otherwise the open unit is unresolved. No overnight fill is invented.

The historical stock result uses a mechanical 60-second delay and the historical proposal's `SHARE_QUOTE_PRIMARY_V1`; 0/5/15/30 seconds and low/harsh costs are sensitivities. Forward evidence uses confirmed-delivery 30 seconds as primary and 60 seconds as sensitivity. Exact quote sides already include spread and must not be charged twice. The bar-only estimate remains `BAR_PROXY / MODELED_COST_ONLY`. Short executable results require point-in-time borrow availability and cost; missing borrow leaves only a labeled directional study. Option results remain separate and use the frozen §3 `CRVOL_ORB5_OPTION_POLICY_V1`, `OPTION_SCORE_INTRADAY_LONG_PREMIUM_V1`, exact contract identity, ask entry, bid exit and $0.45 per contract per transaction. Missing option bid/ask, size, contract or fee evidence blocks only the option claim.

The historical proposal's complete structure catalog (§2.2–§2.6), catalyst/macro facts (§2.5–§2.6), quality formula (§3), option selection (§3), missingness, cost models (§4.3), uncertainty method (§4.5–§4.6), score calibration (§4.8) and release gates (§4.9) are selected unchanged for `M03B_OR_RESEARCH_V2`. Their old `PROPOSED` labels describe `M03B_ORB5_V1`; this paragraph freezes the named content only for offline V2 research under the 2026-09-13 delegation.

### Comparison and reporting contract

Report every one of the 72 arms by after-cost expectancy, win rate, payoff ratio, maximum drawdown and candidate frequency. Keep counts and denominators. Report range duration, entry style, direction, stop and exit separately; do not pool them to hide a losing slice. Report the D-090 arm separately and never use it as one of the 72 V2 arms.

The confirmatory family uses one-sided family allocation `0.05/72 = 1/1440` per V2 arm. Apply the §4 circular 10-session moving-block bootstrap with nearest-rank quantile `q=1/1440`; 10,000 draws and frozen seeds remain unchanged. This accounts for the 72 planned comparisons but does not prove exact family-error control. Descriptive pairwise strengths and weaknesses do not select a winner. A production choice would need a later decision and untouched forward evidence.

Market regime is fixed from the point-in-time SPY regular-session open versus its prior regular close: `DOWN` at or below -0.50%, `FLAT` strictly between -0.50% and +0.50%, and `UP` at or above +0.50%. Unknown compatible SPY prices make regime `UNKNOWN`; the candidate remains in its main arm and is excluded only from regime-specific figures. Report each arm by these labels without creating more confirmatory tests.

### Coverage audit and held-out reservation gate

The coverage-only audit in DATA_REQUIREMENTS §§44–48 was read before any result. It found no manifest that proves the required tape, event/availability, correction, complete one-minute/reference, borrow and historical option coverage. The latest dated collector sample also contains no stock bars or option files. Daily JSON files are not a substitute for the required intraday tape. Therefore no qualifying covered-session list exists from which exact development, calibration and final dates can honestly be frozen.

`M03B_OR_RESEARCH_V2` keeps the chronological 60%/20%/remainder split rule in §4.4, but replay is blocked until M0.2 supplies a qualifying, immutable source manifest. Before any candidate or return is generated, a coverage-only session must publish: every covered date and symbol; expected/observed intervals; source, venue and adjustment basis; event and availability times; correction rules; gaps; source-file SHA-256 values; one canonical manifest SHA-256; and the resulting exact three date lists. The last list is the untouched final validation set. Opening it before all rules and calibration choices are frozen invalidates it and requires newly arriving dates. The current audit record is `M0_3B_COVERAGE_AUDIT.json`; its null manifest hash is a blocker, not a wildcard.

### Deterministic boundary examples

- `OR15`: final bars through 06:44 are present but the 06:44 bar is not available until 06:45:02. OR15 is unavailable at 06:45:01 and becomes available at 06:45:02. A missing 06:37 slot makes it `UNKNOWN`.
- `IMM`: long B is 100.02. Seven samples from 99.98 through below 100.02 and a trade `100.01 -> 100.02` pass the 0.70 boundary. Six samples fail. A sample exactly at B is outside the pre-cross band.
- `CNF`: seven of ten samples exactly at or above long B pass at `t0+10`; six fail. The mirror requires short samples at or below B.
- `RTS`: a confirmation at 06:50 sets a 07:00 deadline. A valid trigger at 06:59:59 passes; one at exactly 07:00 expires.
- `STOP_ENTRY_STRUCTURE_V2`: long entry 100.00, anchor 99.80, ATR 0.40 and tick 0.01 give raw and rounded stop 99.78, so R is 0.22. The short mirror at entry 100.00 and anchor 100.20 gives stop 100.22 and the same R.
- `STOP_FAR_OR_EDGE_V2`: long ORL 99.50 and ATR 0.40 give 99.48. Short ORH 100.50 gives 100.52. Unknown tick makes both unavailable.
- Fixed exits with long E 100.00 and stop 99.50 produce 2R at 101.00 and 3R at 101.50. A one-minute bar with low 99.50 and high 101.50 records the stop, never the 3R win.
- A $100 SPY prior close and opens of 99.50, 100.00 and 100.50 label `DOWN`, `FLAT` and `UP` respectively. Missing prior close labels the regime `UNKNOWN`.
- A missing short borrow record leaves the short directional row reportable but blocks executable short expectancy. A missing option exit bid leaves that option result unresolved and cannot alter the stock result.

## Historical `M03B_ORB5_V1` proposal retained below

## 1. Status, owner choices and build boundary

Prepared **2026-09-05 Pacific**. Packet `M03B_ORB5_V1`. Status: **PREPARATION COMPLETE / PROPOSED FOR OWNER DECISION**. The proposal has not been adopted as a trading rule. The owner's instruction to prepare the packet is not approval of previously unseen choices. D-090's six approved M0.3A rows and D-091's cumulative $25 testing allowance remain unchanged.

This is supporting material under the existing nine-document authority hierarchy. It does not independently override PLAYBOOKS, DATA_REQUIREMENTS or TESTING_AND_VALIDATION. Explicit adoption must name this version, record the owner decision, and incorporate the relevant sections into those governing files. Do not silently activate the proposal or request the unchanged D-090/D-091 approvals again.

The proposed choices are grouped for one reviewable owner decision:

- **B-STRUCTURE / B-ENTRY, §2:** complete named bar-based target catalog; 63-session confirmed daily swings, daily-bar anchored averages, prior-day profile estimates and prior-close ±1 daily ATR; a five-minute-before/ten-minute-after macro pause; exact catalyst evidence; A's explicit pre-cross pressure exception; C's retest/hold timing. True trade profile remains a separately tracked required mode.
- **B-SCORE / B-OPTIONS, §3:** exact 50/30/20 stock-quality factors with no generic stock-score cutoff; exact contract score with minimum 65, stricter same-day minimum 75, and the proposed $500 billion mega-cap membership threshold. Stock validity and option quality remain separate.
- **B-EVIDENCE, §4:** frozen cost/delay assumptions, dates reserved before results, uncertainty checks, conservative treatment of missing outcomes, and separate stock/option evidence gates. All new numeric release rules here apply to CRVOL only and are unvalidated proposals.

The recommendation is to freeze this as a first **research** version before looking at its results. It is not a claim that these choices are optimal or profitable. A/B/C retain separate scores, observations and results; B is the proposed primary research arm. Full Strategy #1 completion still includes A and C.

**You can start the independent first build now:** M0.4's exact scope is in [FIRST_BUILD_SESSION.md](./FIRST_BUILD_SESSION.md). It tests existing interfaces using fake records, a temporary database and blocked external connections. No new target, entry, score, contract filter or profit gate is coded during that milestone. M0.3B adoption and M0.2 source proof block their dependent strategy work only. No provider request, credential read, application code or live change was made to prepare this packet; Databento usage under D-091 remains $0.

All eight playbooks remain required: `CRVOL_ORB5`, `HOD_COMP_RS`, `OR_FAILURE_REV`, `FIRST_PULLBACK_VWAP`, `INDEX_OPEN_DRIVE_BREADTH`, `GAP_FADE_FAILED_OPEN`, `CAT_FIRST_CONSOL`, and `VP_ACCEPT_LVN`. The other seven definition rows remain in PLAYBOOKS §13 before their dependent milestones. Missing full-data modes, actual source coverage, classifier fidelity and unseen forward evidence are not solved by writing formulas.

## 2. Proposed structure, event facts and A/C entries

### 1. Status and scope

Status: **PROPOSED FOR OWNER REVIEW**. Suggested packet/version: `M03B_ORB5_STRUCTURE_AC_V1`.

This draft supplies proposed written research definitions for:

- the full selected structural-level and obstacle catalog for `CRVOL_ORB5`;
- company catalyst classification for the `stock_in_play` branch;
- scheduled macro-event suppression;
- A first-break entry; and
- C retest/hold entry.

Every new formula, number, time window, family rule, and entry rule below is a proposal. None is self-approved. The fact that DATA_REQUIREMENTS already permits a labeled one-minute approximate profile does not preapprove the numeric binning method proposed here.

D-090 and `M03A_ORB5_V1` remain unchanged. In particular, the B crossing, B 10-30 second acceptance window, 0.70 ratio, tape/projected-volume rules, B stop/path rule, target selector, attempts, reset, cooldown, expiry, and O-01 outcome policy are not rewritten by this draft.

### 2. Noncircular ownership and data modes

Build `ORB5_STRUCTURE_BAR_V1` as a small shared producer under M3.5/M4.3 before M6. It provides Strategy #1 with a complete named level catalog without waiting for Strategy #8.

The selected Strategy #1 profile mode is `PRIOR_SESSION_BAR_PROFILE_V1`, a proposed numeric method using the already allowed one-minute approximate-profile data mode. `TRUE_TRADE_PROFILE` remains a separate, unselected fidelity mode tracked through M13. Missing true-profile data does not block `ORB5_STRUCTURE_BAR_V1`; missing required bar-profile input does block it. The two modes must never be pooled or presented as equivalent.

The early shared producer does not implement Strategy #8's LVN/HVN stability, refill, or state machine. It only supplies POC and value-area edges needed by Strategy #1's required profile family.

### 3. Common level record and family states

Each level record contains:

- raw decimal price in dollars per share;
- family and feature version;
- every retained label;
- source and venue basis;
- adjustment basis;
- source/event time;
- `available_at` time;
- coverage state; and
- profile fidelity mode where applicable.

Every required family or subfamily reports exactly one state:

- `PRESENT`: complete input produced one or more levels;
- `KNOWN_EMPTY`: complete input proves the rule produced no level;
- `NOT_SELECTED`: an explicitly named alternate fidelity mode is outside this catalog version; or
- `UNKNOWN`: required input is missing, late, inconsistent, or not proved complete.

The selected catalog is complete only when every selected family/subfamily is `PRESENT` or `KNOWN_EMPTY`. `UNKNOWN` blocks action and cannot mean no obstacle. `NOT_SELECTED` is allowed only for an explicitly alternate mode such as `TRUE_TRADE_PROFILE`; it does not excuse a missing selected family.

All calculations use the exchange calendar and records available by the evaluation time. A later correction creates a later version and never rewrites an earlier catalog. Decisions use unrounded values. Exact equal raw prices merge into one level while retaining every family label. Near prices do not merge.

At mechanical trigger, D-090 remains the selector: use only levels ahead of entry `E` in the trade direction; sort by directional distance; suppress an obstacle below 1R; require T1 at or above 1.5R; and use a distinct T2 at or above 2.5R when available.

### 4. Required selected level families

#### 4.1 Approved families used unchanged

- `PMH/PML` and `PDH/PDL` use F-02 exactly.
- Long OR measured move is `ORH + OR_width`.
- Short OR measured move is `ORL - OR_width`.

#### 4.2 Proposed ATR projection

Feature: `PRIOR_CLOSE_DAILY_ATR_LEVELS_V1`.

- Upper level: `prior_regular_close + DAILY_ATR_14_SMA_V1`.
- Lower level: `prior_regular_close - DAILY_ATR_14_SMA_V1`.

Require the approved daily ATR and prior close on the same adjustment basis. A level already behind entry is excluded by D-090; it is not moved forward.

Tradeoff: prior-close anchoring counts the overnight gap against the normal daily range and is conservative after a large gap. An open-anchored alternative would claim more remaining room after the overnight move.

#### 4.3 Proposed confirmed daily swings

Feature: `DAILY_SWING_PLATEAU_2X2_V1`.

Use exactly the 63 immediately preceding completed regular sessions. Do not splice daily bars with minute bars. A missing required session or incompatible adjustment makes this daily family `UNKNOWN`.

For highs, a plateau is the maximal contiguous run of bars with exactly equal canonical high price `H`. If the run is indices `[i,j]`, it is a confirmed swing high only when:

- `i >= 2` and `j + 2 < N`; and
- the highs at `i-2`, `i-1`, `j+1`, and `j+2` are all strictly below `H`.

For lows, use the maximal contiguous run with exactly equal low `L`. It is confirmed only when the lows of those four outside neighbors are all strictly above `L`.

The swing becomes available only when the second right-side neighbor is final and available. Record the full plateau span and use the last plateau bar as its anchor time. A plateau touching either series edge is unconfirmed, not missing. Emit every confirmed daily swing price. Complete history with no confirmed swing is `KNOWN_EMPTY`.

#### 4.4 Proposed confirmed minute swings

Features:

- `PREMARKET_SWING_PLATEAU_2X2_V1`; and
- `REGULAR_SWING_PLATEAU_2X2_V1`.

These are two separate series and are never spliced with each other or with daily bars.

The premarket series contains only scheduled premarket minute slots from 01:00 Pacific up to, but excluding, the regular open. The regular series begins at the scheduled regular open. Select all scheduled slots ending by evaluation first, then require them to be final and available; never skip a just-ended unavailable slot to use an older cutoff.

A certified no-trade slot has no invented high/low and breaks a contiguous traded-bar run; it cannot serve as a neighbor or be skipped to join two runs. It is known coverage, not UNKNOWN. Apply the same rule to certified no-trade daily sessions. Use the same maximal contiguous equal-extreme plateau and two-strict-neighbors-on-each-side rule as the daily feature. Premarket bars cannot serve as left neighbors for a regular-session swing. Regular bars cannot serve as right neighbors for a premarket swing. A missing or unexplained slot inside either selected series makes only that series `UNKNOWN`. A complete series too short to confirm a swing, or with no qualifying plateau, is `KNOWN_EMPTY`.

#### 4.5 Proposed daily-bar AVWAPs

Feature: `DAILY_SWING_AVWAP_HLC3_V1`.

Use the most recent confirmed daily swing-high plateau and the most recent confirmed daily swing-low plateau as two independent anchors. Starting with the last bar of each anchor plateau and ending with the immediately prior completed regular session:

`AVWAP = sum(((H+L+C)/3) * regular_share_volume) / sum(regular_share_volume)`.

Require every scheduled session from the anchor through the prior session on one source/venue/adjustment basis and positive total volume. A certified zero-volume session contributes zero weight. Missing volume is never replaced by weight 1. Each subfamily is independently `PRESENT`, `KNOWN_EMPTY`, or `UNKNOWN`.

These are labeled daily-bar AVWAP estimates. They are not exact trade VWAPs and are not mixed with the approved regular-session VWAP feature.

#### 4.6 Proposed prior-session one-minute bar profile

Feature: `PRIOR_SESSION_BAR_PROFILE_V1`. Fidelity: `BAR_APPROX_PROFILE`.

Require every scheduled one-minute slot in the immediately prior regular session. Certified no-trade slots contribute zero. An unexplained slot makes the profile `UNKNOWN`. Require at least one positive-volume traded bar, a known valid price increment `tick`, and compatible price/volume adjustments.

The ATR used for bin width is `DAILY_ATR_14_SMA_V1` as of the prior session's close. It uses exactly the 15 sessions ending with that prior session and becomes available at that close. This profile is built for the next session; it must never be exposed as if that closing ATR had been available earlier within the profile session.

Proposed bins:

- `ticks_per_bin = max(1, ceil((0.01 * prior_session_close_daily_ATR) / tick))`;
- `bin_width = ticks_per_bin * tick`;
- `origin = floor(prior_session_low / bin_width) * bin_width`;
- `bin_count=max(1,ceil((prior_session_high-origin)/bin_width))`; k runs from 0 through bin_count-1;
- bins are `[origin + k*bin_width, origin + (k+1)*bin_width)`; the last bin includes its upper edge. A flat bar exactly on that final edge belongs to the last bin; other shared edges belong to the bin on their right.

For a bar with `H > L`, allocate its volume uniformly across price and give each overlapped bin `bar_volume * overlap_width / (H-L)`. For `H=L`, put all volume in the containing bin. Allocation must conserve each bar's volume.

POC is the bin with greatest allocated volume. Tie order:

1. midpoint closest to the prior regular close;
2. lower midpoint.

Build the 70% value area from POC. Add one adjacent bin per step. Choose the side with more allocated volume. If equal, choose the candidate midpoint closer to the prior close; if still equal, choose the lower-price bin. Stop after cumulative included volume is at least 70% of total.

Emit:

- POC at the POC bin midpoint;
- VAL at the lower outer edge of the lowest included bin; and
- VAH at the upper outer edge of the highest included bin.

If two emitted prices are exactly equal, merge their labels. POC/VAL/VAH are raw estimate prices and are not rounded for decisions.

`TRUE_TRADE_PROFILE` is `NOT_SELECTED` in this version. Its later use requires complete eligible trade prints, trade-condition/correction rules, and separate versioned parity evidence. Proposed HVN/LVN production is also outside this early catalog and remains with M13.

#### 4.7 External asserted levels

YouTube, web, analyst, or manually asserted levels are `NOT_SELECTED` for `ORB5_STRUCTURE_BAR_V1`. They may be retained as display/context data. A future actionable mode must define point-in-time source, received time, expiry, verification, and conflict rules before admitting them.

### 5. Proposed company catalyst fact

Feature: `CATALYST_ORB5_V1`.

The qualifying event window is strictly after the prior regular-session close through evaluation time. Both the original event/publication time and local received/available time must be no later than evaluation. Consume an explicit versioned structured event type and source identity; do not ask free text to decide what counts as material at trigger time. An ambiguous type remains D_AMBIGUOUS/UNKNOWN. A faithful source-to-type producer and labeled disagreement tests remain M0.2/M6 prerequisites; these categories do not claim that an automatic classifier already exists.

Classes:

- `A_HARD`: earnings result or guidance; merger/acquisition; FDA or other regulatory decision; major contract; restructuring.
- `B_SIGNIFICANT`: analyst action, investor day, or a material product, industry, or company event directly tied to the symbol.
- `C_SECONDARY`: relevant but not demonstrably material.
- `D_AMBIGUOUS`: rumor, vague breaking-news label, unresolved contradiction, or unclear symbol/event.
- `NON_EVENT`.

`confirmed_catalyst=TRUE` only for class A/B with either:

- one primary issuer, regulator, exchange, or filed-source record; or
- two independent named reports describing the same underlying event.

Syndicated copies sharing one origin count once. A scheduled earnings date alone is not an earnings result. Catalyst direction is not required for Strategy #1; the price break supplies direction.

`confirmed_catalyst=FALSE` requires a configured source to certify complete symbol/window coverage and every known event to be nonqualifying. Otherwise the result is `UNKNOWN`. If a primary correction/retraction is available by evaluation, its latest available version governs. Conflicting reports without a primary resolution are `UNKNOWN`. Later corrections never rewrite earlier snapshots.

This remains only one branch of D-090's three-way `stock_in_play` rule. A known true price/volume branch can still make `stock_in_play` true while catalyst is unknown.

External gate: the current news result lacks original event and received times, and the news cascade stops at one passing hit. It cannot satisfy this mechanical fact without a compatible extension and coverage proof.

### 6. Proposed scheduled macro suppression

Feature: `MACRO_BLACKOUT_ORB5_V1`.

The event set is United States releases: the Federal Reserve decision/statement/chair conference, BLS CPI and employment report/PPI, BEA PCE and advance GDP, Census retail sales, and ISM manufacturing/services. Proposed freshness: an official-source or equivalent verified schedule snapshot received during the current Pacific date and no more than 24 hours old, with complete session coverage; a conflicting known revision makes it UNKNOWN. Historical publication/availability proof is mandatory, and a calendar downloaded today does not prove an older as-of state.

Covered scheduled event types:

- central-bank rate decision, statement, or chair press conference;
- CPI;
- employment report/payrolls;
- PCE;
- advance GDP;
- PPI;
- retail sales; and
- ISM manufacturing or services.

For scheduled event time `T`, suppress action during the half-open interval `[T-5 minutes, T+10 minutes)`. Exactly five minutes before is blocked. Exactly ten minutes after is clear.

`macro_blackout=FALSE` requires a schedule source to certify complete coverage for the session and no matching active interval. Missing schedule, missing event time, stale/unverified schedule, parse failure, or unresolved reschedule is `UNKNOWN` and blocks action. Use the latest schedule revision available by evaluation and retain its source and availability time.

External gate: the current static helper treats a missing or unreadable calendar as no blackout. Its parser shape may be reused behind a fail-closed adapter, but its current return value cannot satisfy this rule.

### 7. Proposed A first-break entry

Variant: `CRVOL_ORB5_A_TAPE_V1`. Tape only.

An immediate first break cannot also wait ten seconds beyond the break. Therefore A explicitly proposes one A-only interpretation: preserve the ten-second/0.70 number as pre-cross boundary pressure. D-090 B acceptance remains unchanged. Owner approval must cover this A-only distinction.

Let `t0` be the first covered eligible trade crossing frozen B after the required reset, using D-090's exact crossing comparison. Before that trade, sample the latest eligible trade once per second at `t0-10` through `t0-1`. All ten samples must be known, fresh under the D-090 trade-age rule, and covered.

- Long approach band: `[ORH-buffer, B)`.
- Short approach band: `(B, ORL+buffer]`.
- Equivalently, with direction sign `s`, a sample is in the band when `-2*buffer <= s*(price-B) < 0`. This is the same A pressure input used by eligibility and scoring; there is no second A pressure definition.
- `APPROACH_PRESSURE_10S = samples_in_band / 10`.
- Require `APPROACH_PRESSURE_10S >= 0.70`.
- No prior sample or eligible trade since reset may already be at/beyond B.

Proposed `strongest_clean` requires:

- every D-090 common gate is known and passing;
- at least two of the three existing `stock_in_play` branches are known true;
- tape mode and complete tape coverage;
- `INTENSITY_15S_MEAN20_V1 >= 1.50` at `t0`;
- complete `ORB5_STRUCTURE_BAR_V1`; and
- valid preliminary stop/target geometry under the D-090 selector.

At `t0`, calculate the stop with the same completed-bar/path anchor method, `0.05*frozen_ATR` buffer, and outward tick rounding used by D-090 B. Entry `E` is the crossing trade. Require positive R and extension `<=0.35R`; freeze stop, catalog, targets, and score inputs at `t0`.

If the first crossing has any false or unknown A-only gate, enter `WAITING_FOR_RESET`. A cannot qualify later on the same excursion. Heads-up uses D-090's approved zone and at most one message. Define its own evaluation instant h: compute candidate B/buffer from facts at h, sample exactly h-9 through h at 1 Hz, require all ten known/fresh and at least seven inside the same directional approach band, and evaluate the two-of-three in-play, intensity and other current gates at h. Use D-090 preliminary entry=B and its preliminary completed-bar stop/target geometry. No observed eligible trade since reset may already be at/beyond that candidate B. Never use future crossing time t0 or fill in a missed heads-up later. Trigger pressure remains the separate strictly pre-cross t0-10 through t0-1 window above. Attempt identity, maximum two attempts, reset, cooldown, restart recovery, and session expiry are exactly D-090.

For the proposed scoring contract, A supplies `APPROACH_PRESSURE_10S` as its acceptance ratio. Participation, OR validity, stock-in-play, VWAP alignment, T1 room, T2 presence, spread, quote/trade ages, and extension are all taken at `t0`; none may use a later observation.

### 8. Proposed C retest/hold entries

Variants:

- `CRVOL_ORB5_C_TAPE_V1`; and
- `CRVOL_ORB5_C_QUOTE_PROJECTED_V1`.

#### 8.1 Initial breakout qualification

Use D-090's B crossing, frozen B/ATR/mode, 10-30 second acceptance, 0.70 threshold, selected participation rule, common gates, and preliminary B geometry. The first passing evaluation creates `BREAKOUT_CONFIRMED` in the C research arm; it does not create a B alert or change the B arm.

Let that confirmation time be `q`. Define `retest_deadline = min(q + 10 minutes, strategy_window_end)`. The C trigger must occur strictly before `retest_deadline`; at the deadline the attempt expires. The overall strategy end remains half-open as in D-090.

#### 8.2 Eligible post-confirmation bars

Only a minute bar with `bar_start >= q`, `bar_end > q`, `final=true`, and `available_at <= current_evaluation` may participate in the retest. A bar that started before `q` is excluded even if it ended or became available after `q`. It cannot create a retrospective retest from price action that occurred before breakout confirmation.

All selected post-`q` minute slots through the current bar must have known coverage. Missing coverage invalidates the attempt. Freeze OR, B, ATR, direction, mode, and attempt identity at the original crossing.

#### 8.3 Retest band and invalidation

Proposed `retest_band = max(valid_tick, 0.10 * frozen_ATR)`.

Long retest lows must lie within `[ORH-retest_band, B+retest_band]`. Every final participating bar must close `>=ORH`; a close strictly below ORH invokes the D-090 reset. A low below the band invalidates C as `RETEST_TOO_DEEP`.

Short retest highs must lie within `[B-retest_band, ORL+retest_band]`. Every final participating bar must close `<=ORL`; a close strictly above ORL invokes the D-090 reset. A high above the band invalidates C as `RETEST_TOO_DEEP`.

Use the first eligible post-`q` retest structure only. The first participating bar whose directional extreme enters the band starts it. It must already have two complete eligible left neighbors with strictly less extreme values; otherwise fail `RETEST_LEFT_CONTEXT_MISSING` and wait for reset. An equal next extreme extends its plateau. A more extreme in-band low/high before confirmation replaces the candidate and must satisfy the same two-left-neighbor rule; it cannot move the original deadline. Failure cannot skip forward to a later separate pullback without reset.

#### 8.4 Retest swing and hold confirmation

Within the eligible post-`q` bar series, use a maximal contiguous equal-extreme plateau.

For long, a plateau `[i,j]` has exactly equal low `L`. It confirms only when the two immediately preceding eligible bars and the two immediately following eligible bars all have lows strictly above `L`. Every plateau bar must close `>=ORH`; both right-side confirmation bars must close `>=B`.

For short, use exactly equal high `H`. It confirms only when the two immediately preceding and two immediately following eligible bars all have highs strictly below `H`. Every plateau bar must close `<=ORL`; both right-side confirmation bars must close `<=B`.

The swing becomes confirmed only when the second right-side bar is final and available. Confirmation time `tc` is that bar's `available_at`. The plateau must remain inside the retest band. If there are fewer than two complete left neighbors or two complete right neighbors before the deadline, no confirmed C swing exists.

#### 8.5 Final C acceptance and trigger

Evaluate once per second from `tc+10` through `tc+30` inclusive, but always strictly before `retest_deadline`. Each evaluation uses exactly the D-090 ten fixed samples at `t-9` through `t`, the 0.70 at/beyond-B threshold, and the selected tape or projected-volume rule. All ten samples and every current mandatory gate must be known.

The first passing evaluation strictly before the deadline triggers. If no evaluation passes by tc+30 or before the earlier retest deadline, expire the attempt. At confirmation tc, calculate the raw stop below and round it outward using D-090. From tc through the trigger evaluation inclusive, any eligible long-side trade <= that rounded stop, or short-side trade >= that rounded stop, invalidates C. Equality counts as a touch and invalidates; the raw unrounded stop is not the comparison boundary. A final close inside the OR also invalidates/reset as specified. Require known path coverage through this interval; do not use a swing already broken before entry. The deadline applies to retest detection, swing confirmation, acceptance, and final trigger.

Stop:

- long raw stop: `confirmed_retest_low - 0.05*frozen_ATR`;
- short raw stop: `confirmed_retest_high + 0.05*frozen_ATR`.

Apply D-090's outward valid-tick rounding. At trigger freeze current eligible trade `E`, positive R, extension, complete catalog, targets, and score inputs. The approved extension boundary remains `<=0.35R`.

C supplies the normal beyond-B ten-sample acceptance ratio to scoring. Participation, OR validity, stock-in-play, VWAP alignment, T1 room, T2 presence, spread, quote/trade ages, and extension all use facts available at the final trigger.

Heads-up, one-message rule, structure identity, attempt count, cooldown, reset, restart recovery, and session expiry remain D-090. Research A/B/C arms are isolated; no automatic mode switching or quota sharing is added.

### 9. Hand-worked boundary cases

#### SX-01: obstacle below 1R

`E=101.00`, stop `100.50`, so `R=0.50`. Nearest directional level is `101.40`. Distance is `0.80R`; suppress.

#### SX-02: exact target merge

PDH and VAH both equal raw `101.75`. Merge labels. With `E=101.00`, stop `100.50`, this is exactly `1.50R` and may be T1. A distinct `102.50` level is `3.00R` and may be T2.

#### SX-03: UNKNOWN versus KNOWN_EMPTY

One unexplained prior-session minute makes `PRIOR_SESSION_BAR_PROFILE_V1=UNKNOWN` and blocks. Complete 63-session daily history with no confirmed swing makes the affected swing and AVWAP subfamily `KNOWN_EMPTY` and does not block.

#### SX-04: daily plateau

Daily highs are `[99,100,105,105,104,103]` around a two-bar plateau. Both two left highs and both two right highs are strictly below 105, so one 105 swing high confirms when the second right bar becomes available. If either right high is also 105, the plateau extends and is not yet confirmed.

#### SX-05: no series splice

The last two premarket bars lie below a premarket high, while the first two regular bars also lie below it. The regular bars cannot confirm that premarket swing. Only premarket right neighbors may do so; if unavailable before the boundary, it remains unconfirmed.

#### SX-06: profile POC/value-area ties

Five adjacent bins have volumes `[10,30,30,20,10]`. Prior close is closest to the third midpoint, so the third bin wins the POC tie. Value area next adds the second bin, then the fourth, reaching 80%. VAL is the second bin's lower outer edge; VAH is the fourth bin's upper outer edge.

#### SX-07: prior-session ATR availability

The profile session closes at 13:00 Pacific. Its bin-width ATR becomes available only with that close and may build the next session's profile. A replay evaluation at 12:59 must not expose that profile or ATR.

#### SX-08: macro boundaries

An event at 07:00 Pacific blocks from 06:55 through 07:09:59.999. Exactly 07:10 is clear if schedule coverage is complete.

#### SX-09: catalyst proof

One issuer filing published and received before evaluation qualifies if class A/B. Two articles copied from one wire count once. A material headline with no received time is `UNKNOWN`, not confirmed.

#### SX-10: A long threshold

`ORH=100`, ATR `0.40`, buffer `0.02`, B `100.02`. Seven of ten prior samples lie in `[99.98,100.02)`, two `stock_in_play` branches are true, intensity is exactly `1.50`, and the eligible trade moves `100.01 -> 100.02`. A passes if all geometry/gates pass. Intensity `1.499` or only one true in-play branch fails A and requires reset.

#### SX-11: C rejects a straddling bar

Breakout confirms at 06:38:20. The 06:38:00-06:39:00 bar later prints a valid-looking retest low, but it began before confirmation and is excluded. The first eligible C bar begins at or after 06:39:00.

#### SX-12: C long plateau and deadline

With `ORH=100`, ATR `0.40`, B `100.02`, retest band is `0.04`. Eligible lows after two higher-left neighbors are `100.00,100.00`, followed by two bars with lows `100.01,100.02` and closes at/above B. The plateau confirms at `100.00` only when the second right bar is available. Raw stop is `99.98`. If the ten-sample trigger would first pass exactly at the retest deadline, the attempt expires; the trigger must be earlier.

#### SX-13: C short mirror

`ORL=50`, ATR `0.40`, B `49.98`. A qualifying equal-high plateau at `50.00`, with two strict lower highs on both sides and both right closes at/below B, confirms. Raw stop is `50.02`. At `E=49.96`, `R=0.06` and extension is `0.02/0.06=0.333...`, so the approved extension gate passes.

### 10. Repository reuse boundary

Reuse exchange session dates/bounds and existing Schwab bar/quote mapping behind M0.4 contracts.

Reuse only arithmetic ideas from the existing `_fractal_pivots`, `_avwap`, and profile allocation helpers. Do not reuse their outputs directly for this strategy. The existing pivot rule has no plateau contract or availability fields. Its AVWAP substitutes weight 1 when volume is missing. Its profile uses different dynamic bins. `_method_anchor` rounds price to cents before downstream use.

The current macro helper treats a missing/unreadable calendar as clear, which conflicts with the proposed mandatory fail-closed rule. The current news result lacks original event and received times, and the cascade returns its first passing hit. Both need compatible extensions before they can supply mechanical Strategy #1 facts.

### 11. Proposed choices requiring approval

The owner decision must explicitly accept or reject:

- prior-close plus/minus 1.0 daily ATR;
- the separate 63-session daily and same-session minute plateau swing rules;
- last-plateau-bar AVWAP anchoring;
- the prior-close-as-of ATR and 1% ATR price bins for the prior-session bar profile;
- 70% value area and all tie/edge rules;
- class A/B catalyst proof and since-prior-close window;
- the macro event list and five-minute-before/ten-minute-after window;
- A's explicit pre-cross ten-second/0.70 exception and two-of-three in-play rule;
- C's ten-minute deadline, 0.10 ATR retest band, post-confirmation whole-bar rule, two-by-two plateau confirmation, and final ten-second acceptance.

No provider access, implementation, live activation, alert delivery, or trading authority follows from approving these written research choices.

## 3. Proposed quality and contract selection

### Quality score — `CRVOL_ORB5_QUALITY_V1`

Status: **PROPOSED / NEEDS OWNER DECISION**, uncalibrated. Define `clamp(x)=min(100,max(0,x))`. All factors are on 0–100. Use unrounded values for comparisons; round only display copies to one decimal, half up. Freeze every input at the named variant's mechanical trigger. A score is a quality rank, never a success probability. No generic minimum FinalScore is introduced for #1.

Setup is the arithmetic mean of four factors:

- RVOL margin: `clamp(100*(RVOL_OPEN5-2)/(3-2))`.
- Acceptance margin: `clamp(100*(variant_acceptance_ratio-0.70)/0.30)`.
- Participation margin: `clamp(100*(participation_ratio-1.50)/1.50)`; tape or named projected-volume ratio, without mixing modes. Saturation at 3.0 is a new proposal.
- OR width: 100 when the existing inclusive 0.08–0.65 gate passes; a failed gate invalidates the candidate rather than assigning it a score.

Context is the arithmetic mean of four factors:

- Known true stock-in-play gate: 100.
- Known passing directional VWAP alignment: 100.
- T1 room: `clamp(100*(T1_distance_R-1.50)/(2.50-1.50))`.
- T2: 100 for the selected distinct T2 at least 2.50R away; zero when a complete catalog proves no qualifying T2 exists.

Execution is the arithmetic mean of four factors:

- Spread headroom: `clamp(100*(20-spread_bps)/20)`.
- Quote freshness: `clamp(100*(3-quote_age_seconds)/3)`.
- Last-trade freshness: `clamp(100*(3-trade_age_seconds)/3)`.
- Extension headroom: `clamp(100*(0.35-directional_extension_R)/0.35)`.

`FinalScore = 0.50*Setup + 0.30*Context + 0.20*Execution`, preserving the original weights. Known boundary passes may score zero on their margin factor. A missing mandatory input is `QUALITY_UNAVAILABLE`, blocks action, and is never zero or a reason to renormalize weights. Optional, proven absent T2 is the only known-zero absence above. Invalid geometry/gates do not become low-scoring valid candidates.

The component acceptance input comes exclusively from the corresponding entry definition in this packet: A uses the proposed pre-cross pressure in `-2*buffer <= s*(price-B) < 0`; B uses unchanged D-090 post-cross acceptance; C uses proposed rolling post-confirmation acceptance. Persist variant, factor ID, source mode, samples and separate calibration identity. Do not pool or compare A, B and C quality scores as though their acceptance factors mean the same thing. Tape and projected modes also remain distinct research arms.

For #1 V1, record `benchmark_mapping=NONE_CRVOL_ORB5_V1`; the original #1 context has no frozen benchmark factor. This adds no benchmark/sector penalty. Other playbooks' benchmark and relative-strength requirements remain mandatory in their own definitions. Future additions to #1 require a new score version.

Within one strategy/variant/mode, deterministic ties use higher FinalScore, Setup, Context, Execution, then earlier mechanical-event availability and lexicographically smaller stable candidate fingerprint. Do not use this tuple to resolve cross-playbook confluence until M4.7/M15 freezes that separate policy. Research calibration gates control when score-based ordering may affect output; raw diagnostic scores may be stored before calibration.

#### Quality fixtures

- Boundary: RVOL 2, acceptance 0.70, participation 1.50, valid OR, true in-play/alignment, T1 1.50R, no T2, spread 20 bps, both ages 3 seconds, extension 0.35R. Setup=25, Context=50, Execution=0, Final=27.5. The candidate can remain mechanically valid; there is no invented score cutoff.
- Interior: RVOL 2.5, acceptance 0.90 (9/10), participation 2.25, valid OR; T1 2R and T2 present; spread 10 bps, both ages 1.5 seconds, extension 0.175R. Setup=200/3, Context=87.5, Execution=50, Final=835/12 (display 69.6). Acceptance ratios use actual counts out of ten, never an impossible 8.5 samples.
- A receives 7/10 from its pre-cross pressure samples, never ten seconds of future prices. C receives its first passing rolling post-confirmation window. Mirrored shorts with equal normalized inputs receive equal scores.
- Missing quote age is unavailable, not the boundary fixture's known age of 3 seconds.

### Option policy — `CRVOL_ORB5_OPTION_POLICY_V1`

Status: **PROPOSED / NEEDS OWNER DECISION**. This exact policy is for #1. The shared engine retains the original 0–7-day capability and per-playbook policy support; other strategies still need their own exact policies before their option paths can run. A failed or missing option recommendation does not invalidate a valid stock setup.

Long stock direction selects a bought call; short selects a bought put. Require a standard contract, multiplier exactly 100, known standardness, and no adjusted/nonstandard deliverable. A blank deliverable is acceptable only when independent explicit standardness/multiplier metadata proves a plain 100-share contract; absent metadata is unavailable. A nonblank deliverable must resolve exactly to 100 shares of the same underlying with no cash or other assets.

DTE is the integer difference between the provider-listed expiration date and the current Pacific calendar date. Verify actual listed expirations against the exchange calendar; do not manufacture an expiration from a weekday. Ordinary DTE is 1 through 5 inclusive. Same-week preference uses the same ISO Monday–Sunday week. Absolute delta is 0.50 through 0.70 inclusive, target 0.60. Calls require nonnegative signed delta; puts require nonpositive signed delta.

Use only nondelayed regular-session chain and underlying snapshots, all available as of evaluation. For each option and underlying quote require `provider_time <= availability_time <= evaluation_time`. Require nonnegative reported age; effective age is the maximum of evaluation-minus-provider time and separately reported age. Ordinary maximum age is 3 seconds for each quote, and absolute option/underlying provider-time separation is at most 3 seconds. Unknown or future times are unavailable; arrival time cannot disguise stale provider data.

Required ordinary row filters:

- finite positive bid and ask with ask >= bid; midpoint >= $0.20;
- spread ratio `(ask-bid)/midpoint <= 0.10`;
- open interest >=100 contracts; bid and ask displayed sizes each >=2 contracts;
- finite known nonnegative current-session volume (zero is allowed);
- finite positive IV as a fraction; gamma >=0; theta <=0; signed delta consistent with right;
- verified units: sizes/OI/volume in contracts, IV as annualized fraction, gamma as delta change per $1 underlying move, theta as option-price dollars per calendar day.

Greek and IV timestamp/as-of identity must match the known chain snapshot contract; an unproved calculation time cannot become current just because the row was received now. M0.2 must prove source field units, provenance, completeness and timestamp semantics. Merely exposing a field in an existing mapper is insufficient.

#### Strict same-day membership and filters

Proposed `CRVOL_ORB5_0DTE_MEMBERSHIP_V1(session)` includes SPY and QQQ, plus a known common-stock symbol whose prior official regular close multiplied by the latest shares-outstanding figure published and available by that prior close is at least **$500 billion**. Use only corporate actions effective by the alert session, with the price and shares on a compatible basis. Require an actually listed same-session standard expiration. Unknown type, shares, publication availability, adjustment or close makes same-day membership unavailable; ordinary 1–5 DTE may remain available.

This keeps both ETF and mega-cap capability. SPY/QQQ are V1's explicit ETF members; another ETF can be added only through a dated approved membership-policy version. The $500 billion boundary is a new uncalibrated choice, not a claim that market capitalization proves option liquidity.

Membership permits testing the stricter filters; it does not waive them. Same-day contracts require both quote ages and provider-time separation <=1 second, spread ratio <=0.05, OI >=1000, session volume >=1000, bid and ask sizes >=10, every ordinary filter, and OptionScore >=75. Known failure excludes that same-day row. If membership data is missing, the same-day branch is explicitly unavailable; rank a complete ordinary 1–5 DTE set only with the label `ORDINARY_DTE_ONLY / SAME_DAY_MEMBERSHIP_UNAVAILABLE`, never claim best across all 0–5 DTE. This cannot erase the required same-day capability from its milestone.

### Option score — `OPTION_SCORE_INTRADAY_LONG_PREMIUM_V1`

Calculate factors only after all known required filters pass:

- `SpreadFit = clamp(100*(0.10-spread_ratio)/0.10)`.
- `DeltaFit = clamp(100*(1-abs(abs(delta)-0.60)/0.10))`.
- `OIFit = clamp(100*(OI-100)/900)`.
- `VolumeFit = clamp(100*session_volume/1000)`.
- `SizeFit = clamp(100*(min(bid_size,ask_size)-2)/8)`.
- `LiquidityFit = 0.40*OIFit + 0.40*VolumeFit + 0.20*SizeFit`.
- `DTEFit = 100` for the same ISO week, otherwise 0.
- `IVFit = clamp(100*(1-abs(IV/median_IV-1)))`. Median is over every positive, finite-IV row for the same underlying, right and expiration in the inclusive absolute-delta band in that complete as-of snapshot; require known standard identity. Even counts use the arithmetic mean of the two middle values. Do not select a favorable median reference after other score filters.
- Let `x = 0.5*gamma*(0.01*underlying_midpoint)^2 / abs(theta)`. `GreekFit = 100*x/(1+x)`. If theta=0 and gamma>0 use 100; if both are zero use 0. All inputs must have the verified units above.

`OptionScore = 0.30*SpreadFit + 0.25*DeltaFit + 0.25*LiquidityFit + 0.10*DTEFit + 0.05*IVFit + 0.05*GreekFit`.

Ordinary minimum is exactly 65; same-day minimum exactly 75. Compare unrounded scores. The spread, liquidity, IV and Greek weights and saturation constants are uncalibrated new proposals; they are not profitability evidence.

Rank all passing rows by higher score, smaller absolute distance of absolute delta from 0.60, lower spread ratio, higher minimum displayed size, higher session volume, higher OI, same-week first, earlier expiration, then lexicographically smaller canonical contract ID. Freeze selected identity and source snapshot with the candidate. Revalidate that same contract at O-01 entry; do not switch contracts after observing later prices. Require entry ask size >=2, and exit bid size >=the number of contracts being closed. O-01's separate delayed entry and exit clocks remain unchanged.

#### Completeness and option outcomes

`FULL_ELIGIBLE_CHAIN_COMPLETE` requires proved coverage of the requested underlying/right and every listed expiration in the permitted DTE set, plus every strike that might satisfy the delta band. A requested strike/expiry cap is partial unless source completeness or deterministic expansion to exhaustion proves eligible rows cannot lie outside it. Every possibly eligible row needs known identity and delta; every in-band, policy-eligible row needs all filter/score fields and their as-of timestamps. Known excluded rows need not satisfy irrelevant later filters. Never fill fields from later snapshots.

- Missing/truncated chain, unknown expiration coverage, missing delta in a possibly eligible row, or any required field missing from an in-band eligible row produces `OPTIONS_UNAVAILABLE` with the exact reason. Do not quietly rank the remaining rows as best.
- A proven complete chain with no listed policy expiration, or all rows known and rejected, produces `STOCK SETUP VALID — OPTIONS QUALITY POOR` with reason counts.
- A complete permitted set with passing rows produces one immutable recommendation using the tie rule. The explicitly labeled ordinary-only membership exception above cannot claim a complete 0–5 DTE comparison.

Persist completeness proof/version, requested/returned bounds, total and in-band rows, missing fields, known rejections and selected rank. Keep unavailable data distinct from known poor contracts.

#### Option fixtures

- Ordinary exact boundary: bid 2.33, ask 2.47, midpoint 2.40, delta 0.60, OI 1000, volume 0, both sizes 2, same week, IV equal to the reference median, and x=1. Factors are SpreadFit=41.666…, DeltaFit=100, LiquidityFit=40, DTEFit=100, IVFit=100, GreekFit=50. Score=65 exactly; passes ordinary score.
- Same-day exact boundary: eligible SPY, bid 1.95, ask 2.05, delta 0.57, OI and volume 1000, both sizes 10, current ages/skew <=1 second, same week, IV equal to median, underlying midpoint 500, gamma 0.002 and theta -0.025. x=1 and score=75 exactly. Every separate same-day filter must also pass.
- Mega-cap threshold: known compatible prior close $100 and published shares 5 billion yield $500 billion, so membership passes exactly if a same-day expiration is listed. Missing shares publication time leaves same-day membership unavailable, even if a present-day company list names the stock.
- A possibly eligible row with missing delta makes an otherwise attractive chain incomplete. Missing size is unavailable; known size 1 is poor. A fresh arrival with a 4-second-old provider quote fails ordinary freshness.

### Existing-code reuse and remaining data proof

Reuse field normalization ideas from `consensus_engine/scanners/schwab_client.py` (`_chain_map_to_df`), `consensus_engine/trade_tracking.py`, and the standard-contract checks in the existing put-flow option monitor. Do not substitute the old ATM/leg picker or expected-move selection for this new ranker. Existing Batch 2 quote-age and spread tolerances describe a different consumer.

The existing full-chain collector stores many required fields, but actual units, as-of calculation times, complete expiry/strike coverage and mega-cap inputs are unproved. The narrower quote capture omits several size/IV/Greek fields. M0.2/M2/M4.7 own that proof and the new consumer's adapter; missing data blocks the affected recommendation instead of being fabricated. The other seven strategies' option policies, complete M14 research and full-fidelity data requirements remain required.

## 4. Proposed costs, research and release evidence

### 1. Status and scope

Packet: `M03B_CRVOL_RESEARCH_V1`. Status: **PROPOSED / NEEDS DECISION**.

This packet preserves D-090 and `M03A_ORB5_V1` O-01 exactly. It adds proposed research-cost, split, uncertainty, score-calibration, and release rules for `CRVOL_ORB5`. It does not approve an order, live activation, profitability claim, account fee, new production threshold, or change to any D-090 rule.

The eight-strategy research program remains in scope. The numeric evidence and release gates below apply only to `CRVOL_ORB5`. Each of the other seven strategies needs its own horizon, coverage, sample-diversity, delay, cost, and release rules before its dependent result. In particular, Strategy #5 must not inherit the CRVOL requirement for ten symbols because an index strategy may legitimately use fewer traded instruments.

All costs below are modeled research assumptions unless a dated account/provider record proves the actual charge. A result with any unknown real commission, regulatory fee, exchange fee, borrow charge, or other mandatory cost is `MODELED_COST_ONLY`; it cannot be described as fully costed, realized, or actual executable profit.

### 2. Primary CRVOL result tuple is fixed before any profit calculation

Freeze and hash the complete primary tuple before calculating any development, validation, or final-test profit:

```text
strategy_version
trigger_arm
feature/data versions
direction policy
outcome policy O-01
clock and requested delay
share/option instrument track
cost model
manifest and covered-session map
split map
bootstrap algorithm/version/seeds
confirmatory statistic and gates
```

Arm selection uses coverage facts only:

1. Use `CRVOL_ORB5_B_TAPE_V1` when M0.2 has already recorded PASS for every required tape field, reference window, event/availability timestamp, correction rule, and candidate-window coverage.
2. Otherwise use `CRVOL_ORB5_B_QUOTE_PROJECTED_V1` when its required quote, last-trade, current-minute volume, reference-volume, and availability coverage has already recorded PASS.
3. If neither arm passes before profit is calculated, the primary result is `INSUFFICIENT_DATA`.
4. If both pass, tape is primary because it is the higher-fidelity approved arm. Quote-projected remains a separately labeled sensitivity.

Coverage status is frozen before any P&L is read. Development or validation returns cannot switch the primary arm. A later arm change creates a new version and requires untouched future dates.

The proposed historical primary tuple is the frozen arm, underlying shares, mechanical 60-second delay, O-01 exits, and the exact-quote primary share-cost model below. The proposed forward primary tuple uses the same arm and costs with confirmed-delivery 30-second delay. Delivered 60-second results are the forward delay sensitivity. Zero/5/15/30-second historical results and mechanical zero-delay results are diagnostics. `BAR_ONLY_ORB5_O1_PROXY` remains a separate proxy and cannot replace the exact-quote primary tuple.

The B arm is the first CRVOL primary research version. A/C entries remain challenger versions. Validation cannot switch the primary tuple to A, C, another delay, another cost model, another direction subset, or another data mode. Such a change needs a new version and untouched future evidence.

Underlying results are evaluated before option results. Option profit is a separate claim and cannot rescue a failed underlying result.

### 3. Proposed cost models

#### 3.1 Exact share quotes

O-01's long ask entry/short bid entry and long bid exit/short ask exit already include the displayed spread. Record the spread against midpoint as a diagnostic, but do not subtract it again.

- `SHARE_QUOTE_LOW_V1`: O-01 quote sides plus 0 basis points of added slippage per filled transaction.
- `SHARE_QUOTE_PRIMARY_V1`: O-01 quote sides plus 10 basis points of adverse slippage per filled transaction.
- `SHARE_QUOTE_HARSH_V1`: O-01 quote sides plus 20 basis points of adverse slippage per filled transaction.

For each transaction, `slippage_dollars = abs(reference_price * quantity * slippage_bps / 10000)`. Deduct it as a separate cash cost without moving the frozen stop, target, trigger, hit time, or O-01 quote reference. Entry for two shares is one two-share transaction; each one-share exit is a separate transaction.

Modeled share commission is $0 per transaction in all three models. This mirrors the inspected Batch 2 convention but is not an account fact. Unknown real commissions or mandatory fees block a `FULLY_COSTED` label even when `SHARE_QUOTE_PRIMARY_V1` passes.

#### 3.2 One-minute bar proxy

Because a one-minute bar has no bid/ask spread, apply a separately labeled adverse cash adjustment to every entry and exit reference:

- `SHARE_BAR_LOW_V1`: 5 basis points per transaction, representing a modeled 5-basis-point half-spread and zero added slippage.
- `SHARE_BAR_PRIMARY_V1`: 20 basis points per transaction, representing a modeled 10-basis-point half-spread plus 10-basis-point slippage.
- `SHARE_BAR_HARSH_V1`: 30 basis points per transaction, representing a modeled 10-basis-point half-spread plus 20-basis-point slippage.

Modeled commission is $0. These assumptions do not prove any historical spread or fill. Every result remains `BAR_PROXY` and `MODELED_COST_ONLY`.

#### 3.3 Exact option quotes

- `OPTION_QUOTE_IDEALIZED_V1`: midpoint entry and midpoint exit plus the approved $0.45 per contract per transaction. This is diagnostic only and can never satisfy a promotion gate.
- `OPTION_QUOTE_PRIMARY_V1`: O-01 ask entry and bid exit plus the approved $0.45 per contract per transaction. Entry displayed ask size must cover two contracts. Each separate exit displayed bid size must cover the actual remaining unit quantity, normally one contract; a simultaneous two-contract exit requires bid size of at least two. No extra slippage is added.
- `OPTION_QUOTE_HARSH_V1`: primary quote sides and fees, plus adverse movement on each transaction equal to `max(one known valid price increment, 0.25 * quoted_spread)`, rounded outward to the valid increment. Add this amount to entry prices, subtract it from exit prices, and floor an exit at zero.

The ask/bid primary already includes the displayed spread; do not charge that spread again. Two contracts with two complete exits incur four approved transactions, or $1.80. For a partially resolved trade, retain only fees and cash flows that actually occurred; do not fabricate the missing exit or a full net result.

All additional option commission, exchange, regulatory, exercise, assignment, and account charges are modeled as $0 until supported by a dated record. Unknown mandatory charges block `FULLY_COSTED` and actual-profit language.

#### 3.4 Short-share borrow

An executable short result requires point-in-time borrow availability, check time no later than entry, quoted rate or exact charge, applicable notional, and evidence the borrow remained valid through the same-session close.

- Primary when only an annual rate exists: `borrow_cost = entry_notional * annual_rate / 360`, charging one full day.
- Harsh sensitivity: use twice the recorded annual rate in the same formula.
- When an exact account charge is recorded, retain it as a separate `ACTUAL_EVIDENCE` model; do not mix its day-count method with the modeled formula.

Missing borrow evidence permits a labeled gross directional study only. It is excluded from executable expectancy, option comparison, and promotion.

### 4. Fixed chronological split and walk-forward rules

Freeze and hash the source manifest and all covered regular-session dates before generating candidate outcomes. Sort covered dates ascending, including dates with zero candidates.

For `N` covered dates:

```text
development_count = floor(0.60 * N)
validation_count  = floor(0.20 * N)
final_count       = N - development_count - validation_count
```

The first block is development, the next validation, and the remainder the locked final test. Every candidate from one session stays in the same split. The split never moves because one block has too few candidates, sessions, symbols, directions, or regimes.

The primary tuple is already frozen before development P&L. Development may diagnose it. Validation may confirm or fail it, but cannot switch arms or tuple fields. The final split opens once against the frozen tuple. A failed or insufficient final split cannot be reused for tuning. A changed version waits for newly arriving dates.

Purge any training candidate whose outcome interval reaches or crosses the first timestamp of a later split. For O-01, a complete same-session outcome ends before the next covered session, so no purge is normally needed. For every other strategy, purge the minimum whole number of earlier sessions that removes all outcome overlap; record the calculated count from its approved horizon. Reference features may use earlier raw observations, but never later outcomes or calibration labels.

Walk-forward diagnostics use at least 60 earlier covered sessions for training and consecutive 20-session test blocks, advancing by 20 sessions. The last short block is omitted. If these fixed rules cannot form a fold, report `INSUFFICIENT_DATA`; do not choose a shorter window after seeing returns.

### 5. Exact dependence-aware resampling

The primary uncertainty calculation is a circular moving-block bootstrap over ordered covered sessions. It preserves all same-session dependence and retains sessions with zero candidates.

For a split with `N` covered sessions and block length `L`:

1. Number sessions `0..N-1` in chronological order.
2. Draw each block start uniformly from all integers `0..N-1` with replacement.
3. A block contains `L` consecutive session indexes, wrapping through zero after `N-1`.
4. Draw `ceil(N/L)` blocks, concatenate their session indexes, then truncate the sequence to exactly `N` sessions.
5. For each sampled session occurrence, append every eligible row from that session. A zero-candidate session contributes no rows but retains its place in the sampled session sequence.
6. Compute the requested statistic across all appended rows. Never average session means unless the metric explicitly says so.

Primary settings are 10,000 resamples and `L=10`. Repeat the complete calculation with `L=5` and `L=20` as dependence sensitivities. If either sensitivity changes the required expectancy sign, makes its required lower bound non-positive, or produces an undefined interval, mark the result `REVIEW_REQUIRED` and block `SHADOW_ELIGIBLE` and `ACTIVE_CANDIDATE`; do not average the three results or ignore the sensitivity. When both sensitivities preserve the required sign and lower-bound conclusion, `L=10` remains the reported primary. A different primary block length needs a new proposed version before results.

Construct each seed as the unsigned 64-bit integer represented by the first 16 hexadecimal characters of:

```text
SHA256(canonical_json({
  "policy_hash": ..., "manifest_hash": ..., "split": ...,
  "metric": ..., "block_length": ..., "resamples": 10000
}))
```

Canonical JSON uses UTF-8, sorted keys, no insignificant whitespace, and exact string identifiers. Use NumPy `Generator(PCG64(seed))`. Persist the full hash, integer seed, NumPy version, resample count, and block length.

Quantiles use the nearest-rank rule. For an ordinary finite-valued metric, sort the 10,000 statistics ascending. For probability `q`, select index `clamp(ceil(q * n) - 1, 0, n - 1)`. Two-sided 95% bounds use `q=0.025` and `q=0.975`. The proposed family-adjusted one-sided lower bound uses `q=0.00625`.

If any replication is undefined or non-finite for an ordinary metric, report its count and make that metric’s interval `UNDEFINED`; do not silently remove it. The finite-draw probability resolution is `1/10000 = 0.0001`. Expectancy remains the primary inferential metric.

Profit factor is `sum(positive_R) / abs(sum(negative_R))`:

- positive sum > 0 and negative sum = 0: `+INFINITY`;
- both sums = 0: `UNDEFINED`;
- positive sum = 0 and negative sum < 0: `0`.

Bootstrap PF bounds sort the ordered extended-real results, retaining `+INFINITY`. Any `UNDEFINED` replication makes the PF interval `UNDEFINED`; report its count. PF never substitutes for the expectancy gate.

Ten thousand bootstrap draws and the Bonferroni-style bound are deterministic approximations under the chosen dependence model. They are not mathematical proof of exact error control. Report Monte Carlo resolution, block-length sensitivities, and the dependence assumptions.

### 6. Primary statistics and denominators

The underlying-stock primary statistic is mean fully resolved after-model-cost R under the frozen primary tuple. For each two-share O-01 candidate, `stock_net_R = net_cash_dollars / (2 * actual_R_dollars_per_share)`. Retain original-R results separately.

The option statistic is separately named `net_premium_return = net_cash_dollars / (2 * 100 * entry_ask_dollars)` for two standard 100-multiplier contracts. Never divide option dollars by share R, label option return as underlying R, or combine stock R and option premium return in one expectancy or drawdown series. A non-standard multiplier remains outside this proposed performance gate until its denominator rule is separately frozen.

Report total candidates, suppressed, delivered, unfilled, filled, fully resolved, partially resolved, unresolved, halted, ambiguous, direction, sessions, symbols, MFE/MAE, target/stop rates, profit factor, drawdown, losing streak, and actual delay. Unfilled and unresolved rows remain visible. Never assign them zero profit or silently drop them.

Fully resolved rate is `fully_resolved / filled`. Entry rate is `filled / total_candidates`. Use explicit `UNDEFINED` when a denominator is zero.

A 95% resolved rate does not by itself protect against profit bias because the missing 5% may be the worst outcomes. Build a conservative lower-bound result for every filled candidate:

- fully resolved: use the actual modeled result;
- unresolved bought share: set exit value to zero, so `net_cash_lower = 0 - entry_cash - every known or harsh modeled cost` for each unresolved unit;
- unresolved bought-to-open option: set exit value to zero, so `net_cash_lower = 0 - paid_entry_premium - approved transaction fees that occurred - every known or harsh modeled cost` for each unresolved contract;
- partially resolved: retain completed cash flows and apply the relevant lower bound to each unresolved unit;
- unresolved short share: loss is unbounded unless a dated, enforceable maximum-loss fact exists. Without that fact its lower bound is `UNBOUNDED`, never zero, the stop price, or the last observed price.

Calculate conservative-bound expectancy across **all filled candidates**, not only resolved rows, and run the same circular bootstrap on those bound values. Any `UNBOUNDED`, missing row, or mandatory cost without a finite frozen conservative model makes the profit/promotion evidence `INSUFFICIENT_DATA`. An unknown actual account fee with an explicit modeled value remains `MODELED_COST_ONLY` and cannot support a fully costed claim. Promotion requires both the resolved-only primary result and the conservative all-filled lower-bound result to clear their stated expectancy bounds. Never drop a missing row or treat missingness as random without separate evidence.

Construct the underlying stock operational aggregate-R drawdown ledger from realized unit exits. Allocate one half of the two-unit entry costs to each unit. For each exit, calculate its net unit cash flow including allocated entry cost and its own exit cost, then divide by `2 * actual_R`. Order ledger events by exit availability time, then provider time and stable candidate/unit ID. Sum all contributions with the same exit availability time into one event before updating cumulative R. Maximum drawdown is the largest peak-to-later-trough decrease in that cumulative series.

Also construct a conservative-bound drawdown ledger by posting each unresolved unit's lower-bound contribution at the time the unresolved status becomes known. An `UNBOUNDED` contribution makes conservative drawdown unavailable and the promotion evidence `INSUFFICIENT_DATA`. Operational aggregate R is a normalized underlying-stock research ledger; it is not portfolio return, account return, margin return, or proof that overlapping positions were fundable.

Construct the option drawdown ledger separately from realized contract exits, using each candidate's `net_premium_return` contributions and the same exit-availability ordering and same-time aggregation. Express its drawdown in cumulative initial-premium-risk units. It never inherits the underlying 12R label or divides by share risk.

Keep every same-day candidate together in bootstrap samples. Merged duplicate structures count once in primary P&L; their component records remain available for research. Report the fraction of total positive R contributed by each session and symbol.

### 7. Eight-strategy family and neighboring-rule tests

Reserve one primary underlying claim for each of the eight original strategies. The proposed fixed allocation is one-sided `0.05 / 8 = 0.00625` per strategy. Operationally, a strategy's 10-session bootstrap lower expectancy bound at nearest-rank `q=0.00625` must exceed zero for the proposed family gate.

This allocation does not apply CRVOL's sample, symbol, cost, delay, or release rules to the other seven strategies. Each needs its own approved contract. Options form a separate eight-strategy family using the same proposed allocation and are evaluated only after the corresponding underlying claim passes.

For CRVOL, A/C entries, the non-primary trigger arm, other delays, direction slices, ablations, and cost models are secondary. They cannot replace the frozen primary tuple after returns are read.

RVOL 1.75 and 2.25 are explicitly named offline sensitivity versions around the approved 2.0 rule. They never change the production rule, candidate facts, or primary test. Their results are reported as robustness evidence only. Any proposal to deploy another value requires a new strategy version, decision, and untouched future test.

The 10,000-draw bootstrap plus `0.00625` bound is a conservative approximate research gate. Finite resampling, serial dependence, missing data, and model misspecification prevent a claim of exact family-error control.

### 8. Score calibration

Preserve raw Setup, Context, Execution, and Final scores. A score remains a quality rank, never a win probability.

Use unrounded-score intervals [0,60), [60,70), [70,80), [80,90), and [90,100]. Display labels may be 0–59, 60–69, 70–79, 80–89, and 90–100; a score of 59.5 belongs to the first interval. A bucket is analyzable only with at least 20 fully resolved candidates across at least 10 covered sessions and at least 3 symbols. Otherwise label it `SPARSE / INSUFFICIENT_DATA`; do not merge buckets after outcomes are known.

Spearman correlation assigns average ranks to tied scores and tied outcomes, then calculates ordinary Pearson correlation between those rank vectors. Fewer than two distinct score values, fewer than two distinct outcome values, or zero rank variance produces `UNDEFINED` and fails calibration.

Call CRVOL's score `CALIBRATED_FOR_RANKING` only when validation and final splits each have:

- at least three analyzable buckets;
- defined Spearman correlation greater than zero;
- higher mean R in the highest analyzable score bucket than the lowest analyzable bucket; and
- a 10-session bootstrap 95% lower bound above zero for that high-minus-low mean-R difference.

Score-calibration failure does not erase an underlying strategy edge. It blocks score-based ordering and confidence claims. Any fitted rescaling, changed factor, changed weight, quantile bucket, or score cutoff requires a new scorer version trained on development dates only and tested on untouched dates.

### 9. Proposed CRVOL evidence and release gates

All numeric thresholds in this section apply only to `CRVOL_ORB5`. The other seven strategies require their own approved gates.

#### 9.1 Data-collection shadow

A disabled, non-alerting `DATA_COLLECTION_ONLY` shadow may collect missing evidence once its independent safety, storage, recovery, and no-network test contracts pass. It does not require a positive strategy result and cannot be described as validation, delivery-tested, profitable, or promotion evidence.

#### 9.2 `SHADOW_ELIGIBLE`

Held-out here means the locked final split only, never pooled validation plus final. Initial cumulative value and running peak are zero for every drawdown ledger. All conditions are required:

- At least 100 fully resolved held-out primary candidates across at least 60 held-out covered sessions and at least 10 symbols.
- At least 95% of filled primary candidates are fully resolved.
- Every filled candidate has a finite conservative lower-bound result; no missing row or unbounded short loss remains.
- Conservative all-filled expectancy is above zero and its proposed `q=0.00625` 10-session bootstrap lower bound is above zero.
- Resolved-only primary after-model-cost expectancy is above zero and its proposed `q=0.00625` 10-session bootstrap lower bound is above zero.
- Primary PF is at least 1.10.
- Harsh-cost expectancy is above zero.
- Historical mechanical 60-second expectancy is above zero.
- Conservative-bound maximum held-out drawdown is available and no more than 12R.
- The first floor(N/2) and remaining final-test covered sessions both have positive point expectancy, counting every candidate within its own session. An empty half is insufficient; never split a session to balance candidate counts.
- Each enabled direction has non-negative point expectancy. Removing a direction requires a new approved version.
- No covered session contributes more than 20% and no symbol more than 25% of total positive R.
- Offline RVOL 1.75 and 2.25 sensitivity versions both have positive point expectancy.
- Look-ahead, reconstruction, data coverage, corporate action, ambiguity, and independent reproduction checks pass.

These counts are minimum evidence conditions, never sufficient evidence by themselves. If the locked final split has 100 candidates but only 20 covered sessions, the result is `INSUFFICIENT_DATA` for the 60-session gate. Do not move the split, borrow validation dates, or choose a new split. For example, a 100-date source manifest fixes 60 development, 20 validation, and 20 final dates; its final block cannot satisfy a 60-session gate regardless of candidate count.

Passing while actual mandatory account fees remain unknown earns `MODEL_COST_PASS`, not `FULLY_COSTED`, actual-profit, or executable-profit language.

#### 9.3 `ACTIVE_CANDIDATE`

All prior gates plus all of the following are required:

- At least 60 valid forward-shadow covered sessions and 100 fully resolved delivered 30-second primary candidates.
- Every filled forward candidate has a finite conservative lower-bound result; conservative all-filled expectancy and its 10-session bootstrap 95% lower bound are above zero.
- Resolved-only delivered 30-second primary expectancy and its 10-session bootstrap 95% lower bound are above zero.
- Delivered 60-second point expectancy is non-negative.
- Harsh-cost forward expectancy is above zero.
- Forward PF is at least 1.10 and conservative-bound maximum drawdown is available and no more than 12R.
- Historical and forward frequency, directions, MFE/MAE, delay, data mode, unresolved rate, symbol concentration, and session concentration are reported together.
- ROADMAP M17.4's data health, delivery/restart, load, security, deployed-version, kill-switch, and rollback controls pass.
- The owner records an explicit decision under D-083.

Unknown actual mandatory costs or any unbounded unresolved loss retain `MODEL_COST_PASS` or `INSUFFICIENT_DATA`, respectively, and block a fully costed profit claim even when the resolved subset looks favorable. No score, sample count, implementation status, or monitor promotes automatically.

#### 9.4 Separate CRVOL option evidence gate

Option evidence is evaluated only after the corresponding underlying CRVOL claim passes. It uses `net_premium_return`, not share R. Apply these gates separately to the locked historical final split with mechanical 60-second delay and to at least 60 valid forward sessions with delivered 30-second delay; never pool their samples. Forward delivered 60-second conservative all-filled mean premium return must also be non-negative. All conditions below are required in each block before any option promotion claim:

- At least 100 fully resolved primary option candidates across at least 60 covered sessions and at least 10 symbols.
- Every filled option candidate has a finite conservative lower-bound premium return; conservative all-filled mean premium return and its proposed `q=0.00625` 10-session bootstrap lower bound exceed zero.
- Resolved-only primary mean premium return and its proposed `q=0.00625` lower bound exceed zero.
- Option PF, calculated from signed net premium-return values, is at least 1.10.
- Harsh option mean premium return is above zero.
- Maximum conservative-bound cumulative option drawdown is no more than **12.0 initial-premium-risk units**, where each candidate's unit is its two-contract entry-premium denominator. This is an option metric, not 12 share R.
- The `L=5` and `L=20` sensitivity disposition, missing-cost restrictions, concentration checks, and explicit owner promotion decision also pass.

A missing exact quote, mandatory option fee without a finite frozen conservative model, non-standard multiplier, or unresolved denominator produces `INSUFFICIENT_DATA` for this gate. An unknown actual account fee with an explicit modeled value retains `MODELED_COST_ONLY` and blocks a fully costed option-profit claim. Underlying success does not imply option success.

#### 9.5 Failure, rejection, and demotion

- Final primary point expectancy at or below zero is `NO_EDGE_SHOWN`.
- A 10-session bootstrap 95% upper expectancy bound at or below zero supports `REJECTED`, subject to the recorded owner/research decision.
- A wide interval crossing zero is `INSUFFICIENT_EVIDENCE`, not a pass.
- Data corruption, stale mandatory inputs, restart inconsistency, unhandled delivery ambiguity, or deployed-version mismatch immediately disables actionable output and returns the version to shadow without changing research history.
- Review statistics every 20 valid covered sessions.
- On the latest 60 valid sessions with at least 30 fully resolved primary results, use conservative all-filled results for monitoring: point expectancy at or below zero or PF below 1.0 becomes `ORANGE / REVIEW`. Resolved-only figures remain diagnostic.
- On that same fixed all-filled window, a 10-session bootstrap 95% upper expectancy bound below zero becomes `RED / RETURN TO SHADOW`.
- Any missing result without a finite defensible lower bound, or an undefined required interval, forces `REVIEW_REQUIRED`; it cannot leave a healthy status based on resolved winners. Report missing counts even before the 30-resolved-result statistical minimum; mandatory data-health failures still disable action immediately.
- A losing streak alone does not demote, reject, or tune the strategy.

### 10. Worked fixtures

#### FX-R01 exact shares

Two long shares enter at ask $100. One exits at $101 and one at $100.50. Gross is $1.50. Primary 10-basis-point slippage costs:

```text
entry: 2 * 100.00 * 0.001 = 0.2000
exit 1: 1 * 101.00 * 0.001 = 0.1010
exit 2: 1 * 100.50 * 0.001 = 0.1005
total slippage = 0.4015
modeled net = 1.5000 - 0.4015 = 1.0985
```

If actual mandatory fees are unknown, label this `MODELED_COST_ONLY`.

#### FX-R02 bar proxy

Using the same gross references under `SHARE_BAR_PRIMARY_V1`:

```text
entry: 2 * 100.00 * 0.002 = 0.400
exit 1: 101.00 * 0.002 = 0.202
exit 2: 100.50 * 0.002 = 0.201
total modeled adjustment = 0.803
modeled net = 1.500 - 0.803 = 0.697
```

This remains a bar estimate, not executable evidence.

#### FX-R03 options

Two contracts enter at ask $2.00. One exits at bid $2.50 and one at $3.00, multiplier 100:

```text
gross = ((2.50 - 2.00) + (3.00 - 2.00)) * 100 = 150.00
fees = 4 * 0.45 = 1.80
primary modeled net = 148.20
```

With a 20-cent spread and one-cent valid increment, harsh adverse movement is `max(0.01, 0.25*0.20)=0.05` each transaction. Across two entries and two exits it removes another $20, leaving $128.20 after the approved fees and before unknown mandatory costs.

#### FX-R04 borrow

Two short shares at $100 have $200 entry notional. A recorded 36% annual borrow rate gives:

```text
primary = 200 * 0.36 / 360 = 0.20
harsh = 200 * 0.72 / 360 = 0.40
```

Without dated availability and rate evidence, neither number is an executable short-profit result.

#### FX-R05 locked split insufficiency

A manifest with 100 covered sessions creates 60 development, 20 validation, and 20 final sessions. Even if the final 20 sessions contain 100 candidates, it fails the 60-session `SHADOW_ELIGIBLE` minimum and is `INSUFFICIENT_DATA`. The dates remain locked.

#### FX-R06 circular bootstrap

For ordered sessions `[A,B,C,D,E]`, `L=3`, and sampled block starts `[4,1]`, the circular blocks are `[E,A,B]` and `[B,C,D]`. Concatenate and truncate to `N=5`: `[E,A,B,B,C]`. Aggregate all candidate rows each time its session appears. A zero-candidate sampled session contributes no rows but remains one of the five sampled session positions.

#### FX-R07 PF edge cases

- R values `[1.0, 0.5]`: PF is `+INFINITY` because losses are zero.
- R values `[0.0, 0.0]`: PF is `UNDEFINED`.
- R values `[-1.0, -0.5]`: PF is `0`.

#### FX-R08 unresolved lower bound and same-time drawdown

Two long shares enter at $100 with $1 actual R per share. One exits at $101 and the other has no exit evidence. Before added costs, the conservative net cash is `(101-100) + (0-100) = -99`, so the conservative candidate result is `-99 / (2*1) = -49.5R`. The missing unit cannot be dropped. The equivalent missing short-share exit is `UNBOUNDED` and makes promotion evidence `INSUFFICIENT_DATA`.

If two realized unit-exit contributions at the same availability time are `+0.8R` and `-1.0R`, aggregate them as one `-0.2R` ledger event before updating the drawdown curve. Do not create an ordering-dependent temporary peak.

### 11. Independent first build

[FIRST_BUILD_SESSION.md](./FIRST_BUILD_SESSION.md) defines the complete M0.4 scope: existing-interface compatibility tests under protection established before application import. It does not build new record models, strategy logic, research results or delivery recovery; those remain M1/M4/M5. New trading proposals stay excluded until the owner decision is recorded. No paid data is needed for these synthetic compatibility tests.

### 12. Evidence basis

- D-070–D-084 and D-090 in `DECISIONS_AND_OPEN_QUESTIONS.md`.
- Outcome, uncertainty, chronology, calibration, promotion, and frozen-contract requirements in `TESTING_AND_VALIDATION.md` §§18–30, 37, and 49–51.
- Data fidelity and historical limitation requirements in `DATA_REQUIREMENTS.md` §§23–27 and 31–33.
- Approved O-01 in `M0_3_DEFINITION_PACKET.md` §7.
- Existing reuse evidence: `trade_collector.py:_frozen_rules`, `trade_tracking.py:assess_share_quote`, `calculate_share_result`, and `calculate_option_result`.
- Inspected Batch 2 defaults in `config/consensus.yaml` include $0.45 option transaction fees, 10-basis-point share slippage, and $0 modeled share commission. They are implementation facts, not CRVOL approval or actual account facts.
