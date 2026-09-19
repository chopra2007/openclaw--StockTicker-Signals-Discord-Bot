# PLAYBOOKS.md

## 1. Purpose

This document is the canonical behavioral specification for the eight approved trading strategies. It defines how each strategy is detected, how it progresses through states, what makes an alert actionable, how it invalidates, how risk/targets are derived, what human checks remain, and which questions require validation.

If implementation code conflicts with this document on trading behavior, this document governs unless a later explicitly approved decision has been synchronized into a new version.

## 2. Shared Strategy Conventions

### Common states

```text
NOT_ELIGIBLE
WATCHING
SETUP_FORMING
ARMED
ALERT_TRIGGERED
INVALIDATED
EXPIRED
```

Strategies may define additional substates.

### Heads-up vs actionable

`HEADS_UP` means setup formation is sufficiently advanced to prepare the human.

`ACTIONABLE` means the deterministic trigger has occurred and all mandatory machine checks currently pass.

### Structural risk

```text
R = abs(entry_reference - hard_stop)
```

Targets are structural prices plus R multiples.

### Acceptance

Where sub-minute data exists:

```text
acceptance_ratio = observations beyond/inside required level / total observations in window
```

Typical provisional threshold is ~0.70. If sub-minute data is unavailable, use the approved bar/quote proxy and mark data mode.

### Confidence

Confidence is relative setup quality, not win probability.

Common decomposition:

```text
FinalConfidence =
weight_setup * SetupScore
+ weight_context * ContextScore
+ weight_execution * ExecutionScore
```

Persist components.

### Options

Underlying setup validity is independent of option quality. General priors:
- 0–7 DTE universe
- 1–5 DTE for many stock setups
- 0–3 DTE for liquid SPY/QQQ
- 1–7 DTE for catalyst setups
- abs(delta) ~0.50–0.70, commonly near 0.60
- reject poor spread/liquidity/IV/Greek fit
- valid result: `STOCK SETUP VALID — OPTIONS QUALITY POOR`

### Human review

Human review should focus on chart/tape/catalyst/exhaustion/nearby-structure nuances that are difficult to encode reliably. Mechanical validity remains separate from human `ACCEPTED` / `REJECTED` / `NO_DECISION`.

### Staleness

A setup is stale when price has already moved too far from the intended structural entry or most available reward is consumed. Each strategy defines its own threshold.

### Deduplication

Strategies emit independently; portfolio orchestration merges overlapping opportunities into primary strategy + confluence.

---

# 3. Strategy 1 — `CRVOL_ORB5`

**Name:** Catalyst / Relative-Volume 5-Minute Opening Range Breakout  
**Direction:** Long and short  
**Window:** ~06:35–07:15 Pacific  
**Options suitability:** High

## Thesis

The opening is genuine price discovery. ORB becomes more credible when the stock is clearly in play because of fresh information and/or abnormal participation. Generic low-participation opening-range breaks are intentionally filtered.

## Eligibility

Initial filters:
- price >= $5
- median 20-day daily dollar volume >= $50M
- spread <= 20 bps preferred
- 5m RVOL >= 2.0
- OR width / daily ATR ~0.08–0.65

`stock_in_play` if any:
- confirmed catalyst
- PM RVOL >= 2.5 and abs(gap) >= 1%
- 5m RVOL >= 3.0

Kill/suppress:
- halt
- spread > ~25 bps
- stale quote > ~3s
- OR > ~0.65 daily ATR
- next obstacle < 1R
- imminent macro event

## State

```text
NOT_ELIGIBLE → WATCHING → SETUP_FORMING → ARMED → ALERT_TRIGGERED
```

## Long trigger

```text
buffer = max(0.01, 0.05 * ATR_1m_20)

ARMED
AND rvol_5m >= 2.0
AND last > VWAP
AND spread <= 20 bps
AND no halt
AND last >= ORH + buffer
AND acceptance_10s >= 0.70
AND trade_intensity_15s >= 1.50
```

If tape unavailable, fallback may use projected current 1m volume ratio >= ~1.5 plus L1/bar acceptance. Store degraded mode.

Short symmetric around ORL.

## Heads-up

Typically ~30 seconds to several minutes before actionable. Emit as price approaches OR boundary with valid in-play/RVOL/context and viable R:R.

## Entry

Preferred:
- B: 10–30s acceptance beyond OR
- A: first break in strongest clean conditions
- C: retest/hold

Stale if > ~0.35R extended or resistance destroys ~1.5R potential.

## Stop

Long:

```text
relevant breakout/retest swing low - 0.05 * ATR_1m
```

Short symmetric.

## Targets

- T1 >= ~1.5R
- T2 ideally >= ~2.5R
- PMH/PML, PDH/PDL, OR measured move, ATR, AVWAP/profile/structure

## Suppression

Initial prior:
- one heads-up per direction/structure
- one actionable initially
- ~10-minute cooldown
- max ~2 independent structures per ticker/direction/session

## Confidence

```text
50% Setup
30% Context
20% Execution
```

## Options

Current frozen research policy: `CRVOL_ORB5_OPTION_POLICY_V1` in §23 and
M4_7_DEFINITION_PACKET §§1–3. Ordinary DTE is 1–5, absolute delta is 0.50–0.70
with target 0.60 and OptionScore is at least 65. The strict 0DTE membership,
quote, liquidity and score gates are exact in that packet. Earlier approximate
wording is historical for this research version.

## Example

```text
Entry 150.35
Stop 149.85
R 0.50
T1 151.15 = 1.60R
T2 152.10 = 3.50R
Possible 150C, 3 DTE, delta ~0.58
```

## Critical validation

Generic ORB vs stock-in-play/RVOL; catalyst increment; acceptance delay; OR width; reaction survival; tape/L2 increment.

---

# 4. Strategy 2 — `HOD_COMP_RS`

**Name:** HOD/LOD Compression Break + Relative Strength  
**Direction:** Long and short  
**Window:** ~06:40–07:15 Pacific  
**Options:** High

## Eligibility

- price >= $5
- median daily dollar volume >= $50M
- spread <= 20 bps
- RVOL >= 1.5
- abs(return open) >= max(0.50%, 0.20 * daily_ATR_pct)

Long:
- price > VWAP
- RS15 > 0

Freeze HOD/LOD point-in-time when compression begins. Never use final session HOD/LOD.

## Compression

- 3–8 one-minute bars
- last-3 range / prior-7 range <= 0.60
- distance to reference HOD <= ~0.35 ATR_1m

Armed long:
- compression <= 0.60
- last >= reference_HOD - 0.20 ATR_1m
- price > VWAP

```text
rs_15m = stock_return_15m - benchmark_return_15m
```

Initial threshold:

```text
rs_15m >= max(0.003, 0.15 * daily_atr_pct)
```

## Trigger

```text
buffer = max(0.01, 0.04 * ATR_1m)
last >= reference_HOD + buffer
acceptance >= 0.70
trade_intensity >= 1.40
```

Short symmetric at LOD.

Stale if > ~0.40R extended.

## Stop / targets

Long stop:

```text
compression_low - 0.05 * ATR_1m
```

T1 >= 1.5R; T2 >= 2.5R preferred.

Max ~2 independent HOD/LOD structures/session/direction.

## Options

Current frozen research policy: `HOD_COMP_RS_OPTION_ORDINARY_RESEARCH_V1` in
§23. It selects bought calls for long setups and bought puts for short setups,
ordinary 1–5 DTE, absolute delta 0.50–0.70 with target 0.60, and the shared
OptionScore minimum 65. It does not select 0DTE.

## Example

```text
HOD 150.00
Entry 150.08
Stop 149.62
R 0.46
T1 150.80 = 1.57R
T2 151.50 = 3.09R
Possible 150C, 3 DTE, delta ~0.62
```

## Critical validation

Generic HOD vs compression; compression threshold/duration; RS; volume contraction; exhaustion; later structures.

---

# 5. Strategy 3 — `OR_FAILURE_REV`

**Name:** Opening Range Failure Reversal  
**Direction:** Long/short  
**Window:** ~06:35–07:15 Pacific

## Thesis

A meaningful OR breakout attempt that quickly fails and is reaccepted inside the range may trap breakout participants and reverse. This is not generic mean reversion.

## Eligibility

- liquid stock/ETF
- completed OR
- price >= $5
- median daily dollar volume >= $50M
- spread <= 20 bps
- RVOL >= 1.5
- OR width / daily ATR ~0.08–0.65

Break buffer:

```text
max(0.01, 0.05 * ATR_1m)
```

Suppress strong catalyst + sustained acceptance.

## State

```text
WATCHING → BREAKOUT_ATTEMPT → FAILURE_FORMING → ARMED → ALERT_TRIGGERED
```

## Failed-upside short

- real break above ORH must occur
- price back inside within ~180s
- stronger: 1m close inside
- inside acceptance >= ~0.70

Actionable prior:

```text
last < ORH
AND close_1m < ORH
AND acceptance_inside >= 0.70
AND spread <= 20 bps
AND last <= ORH - 0.03 * ATR_1m
```

Stronger trigger: below failure-bar low.

Stale > ~0.40R from ORH.

## Stop / targets

Short stop:

```text
breakout_extreme + 0.05 * ATR_1m
```

Targets: OR midpoint, VWAP, opposite OR boundary; T1 >= ~1.5R.

A failed #1 ORB may transition into #3.

## Options

Current frozen research policy: `OR_FAILURE_REV_OPTION_ORDINARY_RESEARCH_V1` in
§23. It selects bought calls for long setups and bought puts for short setups,
ordinary 1–5 DTE, absolute delta 0.50–0.70 with target 0.60, and the shared
OptionScore minimum 65. It does not select 0DTE.

## Example

```text
Breakout extreme 150.55
Short 150.05
Stop 150.60
R 0.55
T1 149.20 = 1.55R
T2 148.60 = 2.64R
Possible 150P, 3 DTE
```

## Critical validation

Failure window; meaningful excursion; 1m-close confirmation vs faster entry; catalyst filter.

---

# 6. Strategy 4 — `FIRST_PULLBACK_VWAP`

**Name:** First Pullback to VWAP/AVWAP Continuation  
**Direction:** Long/short  
**Window:** ~06:38–07:15 Pacific  
**Options:** High

## Mandatory long context

- price > VWAP
- opening impulse >= max(0.40 ATR_1m, 0.15 daily ATR)
- positive VWAP slope
- RS15 > 0
- first valid pullback

Kill:
- VWAP crosses >= 4
- retracement > 0.70
- spread > 25 bps
- R:R < 1.5
- halt/opposing material news

Additional priors:
- RVOL >= 1.5
- open move >= max(0.004, 0.20 * daily_ATR_pct)
- impulse distance from VWAP >= ~0.25 ATR_1m

Freeze impulse origin/extreme.

## Pullback

- retracement 0.20–0.65; 0.30–0.50 preferred
- support within ~0.15 ATR
- pullback volume / impulse volume <= 0.80
- armed long low >= VWAP - 0.10 ATR

## Trigger

```text
last >= reversal_bar_high + max(0.01, 0.03 * ATR_1m)
AND price > VWAP
AND VWAP_slope > 0
AND retracement <= 0.65
AND pullback_volume_ratio <= 0.80
AND RS > 0
```

Prefer tape acceleration >= ~1.3 when available.

## Stop / targets

```text
pullback_low - 0.05 * ATR_1m
```

T1 >= 1.5R; T2 ~2.5–4R when structure supports.

First pullback normal priority; second lower; third suppress by default.

AVWAP is optional until ablation supports it.

## Options

Current frozen research policy:
`FIRST_PULLBACK_VWAP_OPTION_ORDINARY_RESEARCH_V1` in §23. It selects bought
calls for long setups and bought puts for short setups, ordinary 1–5 DTE,
absolute delta 0.50–0.70 with target 0.60, and the shared OptionScore minimum
65. It does not select 0DTE.

## Critical validation

Generic first pullback vs VWAP aligned; volume contraction; RS; AVWAP; second-pullback performance.

---

# 7. Strategy 5 — `INDEX_OPEN_DRIVE_BREADTH`

**Primary:** SPY, QQQ  
**Secondary:** IWM, DIA  
**Window:** ~06:32–07:15 Pacific  
**Options:** Very High

Current offline research definition: `M03F_INDEX_OPEN_DRIVE_BREADTH_V2` in §19.
Its exact rules supersede the approximate choices in this strategy summary for
that research version only. It selects bar HLC3 VWAP and session-to-evaluation
trade-by-trade directional share volume. Protected verification of the repair passed; independent acceptance
is pending. Full and hybrid source gates remain blocked.

## Thesis

A directional post-open index drive with efficient movement, VWAP alignment, and broad participation may continue. Breadth filters narrow leadership.

Distinguish overnight gap from post-open drive.

## Mandatory long

- regular session
- approved ETF
- post-open drive > 0
- price > VWAP
- VWAP slope > 0
- breadth/context minimum

Kill:
- macro due <= ~5m
- abnormal spread
- breadth divergence
- repeated VWAP crosses/chop

## BreadthScore

Initial:

```text
35% Advance
30% Above VWAP
20% Up Volume
15% Sector
```

Full breadth ideal; sector proxy/hybrid allowed. Store breadth mode.

## Drive

After >= ~120s:

```text
opening_return >= max(0.0015, 0.15 * daily_atr_pct)

drive_efficiency =
abs(last - open) / sum(abs(1m changes))
```

Initial:
- efficiency >= 0.55
- breadth >= 60
- price > VWAP
- 3m VWAP slope > 0

## State / trigger

```text
OPEN_OBSERVATION → DRIVE_DETECTED → DRIVE_CONFIRMED → ARMED → ALERT_TRIGGERED
```

Armed: 2–4 bar microconsolidation/shallow pullback, retrace <= ~35–40%, above VWAP.

Trigger:

```text
last >= consolidation_high + max(0.01, 0.03 * ATR_1m)
AND breadth >= 60
AND price > VWAP
AND VWAP_slope > 0
AND drive_efficiency >= 0.55
AND acceptance >= 0.70
```

Prefer breadth >= 70.

Narrow leadership warning: index up while advance_ratio < ~0.45. Divergence: price new high while breadth drops ~15. Suppress VWAP crosses >= 3. Reduce if move already > ~0.50 daily ATR.

Stale > ~0.35R.

## Stop / targets / options

Stop = microconsolidation/pullback low - 0.05 ATR.

T1 >= 1.5R; T2 >= 2.5R.

Confidence 45/35/20.

SPY/QQQ options:
- 0–3 DTE
- delta ~0.55–0.70
- 0DTE spread <= ~5%
- abs(delta) >= ~0.55
- OptionScore >= ~75

Full constituent breadth is `BLOCKED BY DATA` until verified. Sector ETF/major-constituent proxy approved.

---

# 8. Strategy 6 — `GAP_FADE_FAILED_OPEN`

**Name:** Gap Fade After Failed Open  
**Direction:** Long/short mean reversion  
**Window:** ~06:33–07:15 Pacific

Current offline research definition: `M03G_GAP_FADE_FAILED_OPEN_V1` in §20.

## Thesis

Do not fade a gap because it exists. Fade the market's failure to sustain the repricing after the open.

## Eligibility

```text
abs(gap) >= 1%
OR gap_ATR >= 0.25
```

Liquidity:
- price >= $5
- median daily dollar volume >= $50M
- spread <= 20 bps
- PM dollar volume >= ~$5M preferred

Catalyst classes:
- A major hard catalyst
- B significant sector/market/event
- C technical/no clear catalyst
- D unknown/ambiguous

Preference: `C > D > B >>> A`.

Unknown remains distinct from no catalyst.

## State

```text
GAP_IDENTIFIED → OPEN_TEST → EXTENSION_FAILED → FADE_FORMING → ARMED → ALERT_TRIGGERED
```

## Failed-extension short for gap-up

```text
last < open
AND max_opening_extension <= max(0.15 * abs(gap_dollars), 0.20 * ATR_1m)
```

Formation:
- 1m close < open
- price <= VWAP

Armed:
- failed reclaim
- relative strength from open < 0

Trigger preferred:

```text
ARMED
AND last < open
AND last < VWAP
AND VWAP_slope <= 0
AND no known major positive news
AND last < first_3m_low - max(0.01, 0.03 * ATR_1m)
```

Stale when ~35% of gap already filled.

## Stop / targets / options

Stop: failed-reclaim high + 0.05 ATR or opening high + 0.05 ATR for early setup.

T1 >= 1.5R, T2 >= 2.5R. Partial/full gap may be targets; never assume all gaps fill.

Options: 1–5 DTE, delta ~-0.55 to -0.70 for shorts, penalize IV overpricing.

Catalyst latency is the key weakness. `UNKNOWN` reduces confidence.

---

# 9. Strategy 7 — `CAT_FIRST_CONSOL`

**Name:** Catalyst First Consolidation Continuation  
**Window:** ~06:30–07:15 Pacific; ideal ~06:35–07:05  
**Options:** Very High  
**Data:** Blocked/degraded until reliable catalyst feed

Current offline research definition: `M03H_CAT_FIRST_CONSOL_V1` in §21.

## Thesis

Fresh material information causes abnormal repricing. After the initial impulse, the first controlled consolidation may offer continuation if the market continues accepting the new information and participation renews.

## Catalyst classes

A — hard material: earnings surprise, guidance, M&A, FDA, regulatory, major contract/restructuring.  
B — significant: analyst action, investor day, product/industry/corporate event.  
C — secondary.  
D — rumor/ambiguous.

Production prior: A/B; C only with abnormality; D suppress.

Fresh morning event should be since prior close. Intraday received <= ~30m preferred. Actual receive time required.

## Abnormal repricing

```text
abs(gap_ATR) >= 0.30
OR RVOL_5m >= 2.5
OR breaking-news move >= 0.30 daily ATR
```

Kill:
- D catalyst
- spread > 30 bps
- halt
- retrace > 0.65
- R:R < 1.5
- contradictory news

Liquidity:
- price >= $5
- median daily dollar volume >= $50M
- spread <= 20 bps preferred
- RVOL_5m >= 2.0
- PM dollar volume >= ~$10M preferred

## State

```text
CATALYST_IDENTIFIED → IMPULSE_DETECTED → CONSOLIDATION_FORMING → ARMED → ALERT_TRIGGERED
```

## Impulse

```text
>= max(0.30 * ATR_1m, 0.10 * daily_ATR)
```

Overnight gap itself is not the regular-session impulse.

## First consolidation

- 2–8 one-minute bars
- retrace <= 0.50 preferred; max 0.65
- consolidation range / impulse <= 0.50
- consolidation volume / impulse <= 0.80

Armed long: valid consolidation, last > VWAP, retrace <= 0.50, volume ratio <= 0.80.

## Trigger

```text
last >= consolidation_high + max(0.01, 0.03 * ATR_1m)
AND catalyst_class in {A, B}
AND price > VWAP
AND retracement <= 0.50
AND volume_ratio <= 0.80
AND acceptance >= 0.70
```

Prefer trade intensity >= ~1.5 or projected 1m volume >= ~1.5 reference.

Stale > ~0.35R.

## Stop / targets / confidence / options

Stop = consolidation low - 0.05 ATR.

T1 >= 1.5R; T2 >= 2.5R.

First catalyst consolidation is #7; later HOD compression may be #2.

Confidence 40% Setup / 40% Catalyst Context / 20% Execution.

Options 1–7 DTE, delta ~0.50–0.70, current post-announcement IV.

Faithful active implementation: `BLOCKED BY DATA` until source confirmed. Allowed interim: `SHADOW_DEGRADED` / `DISABLED`.

---

# 10. Strategy 8 — `VP_ACCEPT_LVN`

**Name:** Prior-Session Value Acceptance → LVN Expansion  
**Window:** ~06:35–07:15 Pacific  
**Options:** Medium–High  
**Research confidence:** Low–Medium / experimental

Current offline research definition: `M03I_VP_ACCEPT_LVN_V1` in §22.

## Thesis

Volume Profile is descriptive, not inherently predictive. Hypothesis: current-session acceptance outside prior value followed by movement into a nearby low-volume region may produce faster traversal toward the next accepted high-volume area.

## Profile

Prior regular session frozen before current session.

Ideal: trade-level volume-at-price. Fallback: deterministic 1m bar approximation labeled `BAR_APPROX_PROFILE`.

Initial bin width:

```text
max(min_tick, 0.0005 * prior_close)
```

Sensitivity: 0.75x / 1x / 1.25x.

Compute VPOC, VAH, VAL, HVN, LVN. Value area ~70%.

LVN initial prior:
- 3-bin smoothing
- contiguous <= 30th percentile
- bounded by >= 60th percentile shelves
- width >= max(3 bins, 0.05 daily ATR)

## Long eligibility

- price > prior VAH
- price > VWAP
- adjacent LVN above
- next HVN above
- next HVN >= 1.5R
- RVOL >= 1.3

Kill:
- spread > 25 bps
- poor/unstable profile
- narrow LVN
- R:R < 1.5
- fourth total value-edge crossing (VAH long / VAL short), counting the first
  buffered break as crossing 1; later strict-side changes count once, and
  equality, same-side trades and duplicate observations add nothing (packet §5)

## State

```text
APPROACHING_VALUE_EDGE → VALUE_EDGE_BROKEN → ACCEPTANCE_FORMING → LVN_APPROACH → ARMED → ALERT_TRIGGERED
```

Approach <= 0.20 ATR_1m.

Break:

```text
last >= VAH + max(0.01, 0.03 * ATR_1m)
```

Acceptance ~90s >= 0.70 plus 1m close > VAH.

LVN approach <= 0.15 ATR.

Trigger: enters LVN beyond low edge + buffer, maintains acceptance, VWAP alignment, RVOL; prefer volume acceleration >= 1.30.

Stale if > ~35% of LVN traversed.

## Stop / targets

Stop: acceptance swing low - 0.05 ATR or VAH - 0.05 ATR. Failure = reacceptance into prior value.

Track:

```text
current_lvn_fill_ratio = current_session_volume_inside_lvn / prior_session_volume_inside_lvn
```

Heavy filling should penalize old LVN; threshold TBD.

Targets:
- T1 far side of LVN if >=1.5R
- T2 next HVN leading edge
- runner HVN center/VPOC

Profile stability IoU initial >= 0.60.

Confidence 45/30/25. Research confidence separate.

## Critical matched experiment

Compare accepted VAH + LVN versus accepted VAH without LVN, matched on RVOL/ATR/time/market/sector/gap/liquidity/break strength. If no incremental value, remove/reject #8.

True trade-level volume-at-price history: `BLOCKED BY DATA`. Build last.

---

# 11. Cross-Strategy Interaction Rules

- #1 → #3: failed ORB can transition to OR failure.
- #3 ↔ #6: a failed OR on a gap may support gap-fade thesis; choose one primary + confluence.
- #2 ↔ #7: first catalyst consolidation is #7; later HOD compression may be #2.
- #8 often acts as context unless independent value is validated.
- Same symbol/direction within ~3m and trigger/stop region within ~0.25 ATR → merge by default.
- Opposite-direction conflicts suppress lower-confidence thesis until primary invalidates, except explicit reversal transitions.

# 12. Strategy Implementation Standard

Each strategy must provide:
- required data
- versioned config
- eligibility
- explicit state machine
- heads-up
- actionable trigger
- invalidation
- expiry
- staleness
- structural stop
- structural targets
- confidence breakdown
- human checks
- options hook
- suppression/dedup metadata
- event persistence
- synthetic tests
- replay support
- unresolved research questions

Codex must not invent new thresholds or capabilities. Provisional values remain current rules until validated and explicitly approved.

# 13. Deterministic definition gate — original gap register

The numerical priors and trading rules above are preserved. A named feature or an approximate/range description is not enough to produce a unique implementation. Before coding the affected behavior, M0.3 must produce a versioned definition and hand-worked boundary examples under this document's authority. Single-valued priors remain binding; missing definitions and competing alternatives must not be filled in by intuition. See proposals P-01 and P-02 in DECISIONS_AND_OPEN_QUESTIONS.

Shared definitions must specify ATR smoothing/seed/session and lookback; VWAP price input/reset; each RVOL numerator, same-time reference population and denominator; benchmark/sector choice and warm-up; swing confirmation time; acceptance sample type, cadence, window endpoints and missing coverage; volume projection and reference; heads-up distance, expiry, and structure identity; score factors and missing-factor treatment; structural stop/target priority; and the exact long/short transformations. Higher-frequency observations arriving in bursts must not count as sustained acceptance merely because the message count is high. A completed one-minute bar cannot stand in for a ten-second acceptance window without an explicit, versioned proxy definition.

| Playbook | Definition or conflict that must be closed before the affected behavior is built |
|---|---|
| `CRVOL_ORB5` | Choose the documented A/B/C entry mode; define the breakout/retest swing, tape/projection reference and heads-up condition. Preserve the 10-second/0.70 trigger and all existing thresholds. Clarify stop construction when no retest swing yet exists. |
| `HOD_COMP_RS` | Define whether last-3/prior-7 windows overlap, how a 3–8 bar compression is seeded, which HOD is frozen, RS15 warm-up before 15 regular-session minutes, acceptance duration and tape fallback. |
| `OR_FAILURE_REV` | Define meaningful excursion versus a one-tick break, the failure timer origin, inside-acceptance window, mandatory close versus stronger failure-bar trigger, and reversal ownership after an ORB. |
| `FIRST_PULLBACK_VWAP` | Define impulse/reversal bars, swing confirmation, pullback counting, slope/cross convention, volume duration normalization, the 0.65–0.70 interval, and how the first-only context relates to second-pullback lower priority. |
| `INDEX_OPEN_DRIVE_BREADTH` | Define all breadth components and coverage by mode, directional treatment for shorts, drive-efficiency denominator/zero handling, the 35–40% retracement choice, and the meaning of reduce/warn/suppress. Do not silently renormalize full-breadth weights for a sector proxy. |
| `GAP_FADE_FAILED_OPEN` | Define the open-extension window, failed-reclaim confirmation, benchmark for relative strength from open, UNKNOWN penalty, and stop precedence. Define symmetric behavior for a failed gap-down. |
| `CAT_FIRST_CONSOL` | Resolve class C with abnormality in the production prior versus the explicit A/B-only trigger; define material/contradictory news and point-in-time classification, first consolidation, and 0.50 versus 0.65 roles. Preserve the A/B trigger while the conflict is open. |
| `VP_ACCEPT_LVN` | Define bar volume allocation, bin origin/tick rounding, value-area and VPOC tie-breaking, smoothing edges, LVN adjacency, stability intersection-over-union calculation, stop precedence, zero prior volume, and the TBD refill penalty. The approximate mode is approved; its missing formula is not approved by this review. |

These gaps block only the dependent rule or data mode. They do not delete a playbook or prevent independent engineering work. Existing numeric thresholds remain in their governing sections; no new strategy version or approval is created by this review.

Current status is recorded in the frozen research sections below. Sections
§§14–22 resolve all eight strategy rows for their named research versions.
Source and historical-data gates remain separate. The gap table above is
historical; §22 holds the current frozen research-definition status.


# 14. Approved M0.3A research definitions — D-090

For the first five-minute opening range, require every scheduled interval to be final and available before using its extrema. A start-stamped minute ends 60 seconds later; late receipt delays availability. An unexplained absent interval is UNKNOWN. A certified no-trade interval contributes zero volume and no invented high/low. At least one traded interval is required. Keep prices/ATR/range in dollars per share, volume in shares, and RVOL/range-to-ATR as ratios. Compare values before display rounding. These clarify existing timing, missing-data and unit requirements.

On 2026-09-05 Pacific the owner approved `M03A_ORB5_V1` under D-090 for written research rules. This section incorporates [M0_3_DEFINITION_PACKET.md](./M0_3_DEFINITION_PACKET.md) §§2–6 by exact version: F-01/F-02/F-03 supply the named shared features; B-01/B-02 supply the first ORB research variants' crossing, acceptance, state/reset, stop/rounding and target-selector contracts. Those definitions resolve the previously missing or approximate terms only for `CRVOL_ORB5_B_TAPE_V1` and `CRVOL_ORB5_B_QUOTE_PROJECTED_V1`. Unchanged single-valued priors and all other playbooks retain their original requirements. This is incorporation under PLAYBOOKS authority, not an independent overriding specification.

Historical status at the D-090 incorporation: the #1 weights remained 50/30/20; component formulas, full structural-level producers, A/C entries, option policies and the other seven rows in §13 remained M0.3B/later M0.3 work. Current research-definition status is in the later frozen research sections below. Missing mandatory target/obstacle coverage is not proof that no obstacle exists. Full and estimated data modes remain distinct. Approval of these written rules is not implementation, validation, actionable readiness or permission for live alerts/trades. Do not ask again for approval of the six unchanged D-090 rows.

# 15. M0.3B agent-selected offline research rules — `M03B_OR_RESEARCH_V2`

The owner's 2026-09-13 Pacific delegation authorizes the versioned offline research choices in [M0_3B_DEFINITION_PACKET.md](./M0_3B_DEFINITION_PACKET.md), section “Agent-selected preregistration.” Incorporate that section under this document's strategy authority. It freezes 5-minute and 15-minute ranges, immediate/confirmed/retest entries, long/short mirrors, one common eligibility policy, two stop constructions and three exit policies. The twelve base combinations and their 72 stop/exit result arms must all be reported. Fixed 2R, fixed 3R and D-090 structural exits are separate. No result may silently select a winner or change an operational rule.

For V2, the detailed structure, catalyst, macro, quality and option formulas selected by the new packet are the exact formulas in the historical packet §§2–3. Their old “proposed” labels remain historical for `M03B_ORB5_V1`; the new packet's incorporation freezes those named formulas only for offline V2 research. D-090's `M03A_ORB5_V1` remains unchanged and separately reported. Missing mandatory facts remain unavailable. Stock, short-stock and option claims remain separate.

The definitions are frozen, but the required exact date lists are not. DATA_REQUIREMENTS §§44–49 and `M0_3B_COVERAGE_AUDIT.json` show that no qualifying source manifest exists. V2 replay and any result remain blocked until a coverage-only session publishes the manifest hash and exact development, calibration and untouched final-validation dates. This research incorporation is not validation, live approval or evidence of profit. Current resolution status for the remaining playbook rows is in the later frozen research sections below, with source requirements still separate.

# 16. M0.3C frozen research rules — `M03C_HOD_COMP_RS_V1`

The owner's 2026-09-13 delegation authorizes the agent-selected offline rules in
[M0_3C_DEFINITION_PACKET.md](./M0_3C_DEFINITION_PACKET.md). Incorporate §§2–7
under this document's strategy authority. The packet fixes the 06:40–07:15
Pacific window, non-overlapping recent-three/prior-seven compression seed,
three-to-eight-bar structure, point-in-time HOD/LOD freeze, 15-bar SPY relative
strength warm-up, long/short mirrors, ten-second 0.70 acceptance, separate tape
and projected-volume modes, 1.40 participation minimum, stop, fixed 1.5R/2.5R
targets, 0.40R staleness, score and stock outcome rules.

This is one finite first research version. It does not alter D-090 or
`M03B_OR_RESEARCH_V2`, approve an operational rule, establish source coverage or
authorize replay or live use. Missing mandatory data stays unavailable. At the
M0.3C freeze, six unresolved playbook rows in §13 remained open. Later frozen
research sections below record the subsequent definition resolutions.

# 17. M0.3D frozen research rules — `M03D_OR_FAILURE_REV_V1`

The owner's 2026-09-13 delegation authorizes the agent-selected offline rules in
[M0_3D_DEFINITION_PACKET.md](./M0_3D_DEFINITION_PACKET.md). Incorporate §§2–8
under this document's strategy authority. The packet fixes the five-minute
opening range, 06:35–07:15 Pacific window, 0.10 ATR meaningful excursion,
crossing-based inclusive 180-second timer, final one-minute reacceptance close,
separate close and stronger failure-bar-break arms, ten-second 0.70 inside
acceptance, tape and quote modes, explicit ORB reversal ownership, mirrored
stop, structural targets, 0.40R staleness, score and stock outcome rules.
Fixed 2R and fixed 3R exits remain separate comparison arms beside the preserved
structural-target policy; no result silently replaces that prior.

This is one finite first research version. It does not alter D-090, D-092 or
D-093, approve an operational rule, establish source coverage or authorize
replay or live use. Missing mandatory data stays unavailable. At the M0.3D
freeze, five unresolved playbook rows in §13 remained open. Later frozen
research sections below record the subsequent definition resolutions.

# 18. M0.3E frozen research rules — `M03E_FIRST_PULLBACK_VWAP_V1`

The owner's 2026-09-13 delegation authorizes the agent-selected offline rules in
[M0_3E_DEFINITION_PACKET.md](./M0_3E_DEFINITION_PACKET.md). Incorporate §§2–9
under this document's strategy authority. The packet fixes the 06:38–07:15
Pacific window, completed-minute impulse and two-bar swing confirmation,
independent pullback counting, duration-normalized volume, three-minute VWAP
slope, close-cross counting, the 0.65 actionable and 0.70 kill boundaries,
reversal-bar crossing, mirrored stop, structural targets, 0.40R staleness,
score and stock outcome rules.

The first-only prior remains the primary research arm. A separate comparison
arm retains the second pullback at lower priority; neither pools it with the
first, and the third remains suppressed. Structural, fixed 2R and fixed 3R exits
are separate comparison arms. AVWAP and tape acceleration remain recorded
context, not actionable gates in V1.

This is one finite first research version. It does not alter D-090, D-092,
D-093 or D-094, approve an operational rule, establish source coverage or
authorize replay or live use. Missing mandatory data stays unavailable. The
four unresolved playbook rows at the M0.3E freeze were historical. Section §19
records the current count after M0.3F.

# 19. M0.3F frozen research rules — `M03F_INDEX_OPEN_DRIVE_BREADTH_V2`

The owner's 2026-09-13 delegation authorizes the agent-selected offline rules in
[M0_3F_DEFINITION_PACKET.md](./M0_3F_DEFINITION_PACKET.md). Incorporate §§2–9
under this document's strategy authority. The packet fixes the 06:32–07:15
Pacific window, 120-second drive minimum, exact path-efficiency denominator and
zero handling, full-constituent, 11-sector-proxy and hybrid breadth modes,
coverage, all four 35/30/20/15 components and mirrored short treatment.

V2 repairs the reviewed V1 gaps: every VWAP use selects
`SESSION_VWAP_BAR_HLC3_V1`; Up Volume selects
`SESSION_DIRECTIONAL_TRADE_VOLUME_V1` in packet §4.1. Each eligible trade's own
shares are classified against its immediately preceding eligible trade since
the regular open. First and equal-price trades are neutral denominator volume.
The packet fixes as-of ordering, duplicates, corrections and missing coverage.
These written repairs passed protected verification and await independent
acceptance; the earlier V1 proof does not verify V2.

It also fixes the 0.35 actionable and 0.40 invalidation boundaries, ten-second
0.70 acceptance, warning, reduced-priority and suppression meanings, breadth
divergence, VWAP-chop counting, mirrored stop, structural targets, fixed 2R and
fixed 3R comparison exits, 45/35/20 score and stock outcome rules. No mode may
rescale a missing component or silently stand in for another mode.

This is one finite first research version. It does not alter D-090, D-092,
D-093, D-094 or D-095, approve an operational rule, establish source coverage
or authorize replay or live use. Full and hybrid breadth remain blocked by
point-in-time membership and coverage. Missing mandatory data stays
unavailable. At the M0.3F freeze, the three unresolved playbook rows in §13 were
`GAP_FADE_FAILED_OPEN`, `CAT_FIRST_CONSOL` and `VP_ACCEPT_LVN`. That count
is historical; §20 records the current count after M0.3G.

# 20. M0.3G frozen research rules — `M03G_GAP_FADE_FAILED_OPEN_V1`

The owner's 2026-09-13 delegation authorizes the agent-selected offline rules in
[M0_3G_DEFINITION_PACKET.md](./M0_3G_DEFINITION_PACKET.md). Incorporate §§2–9
under this document's strategy authority. The packet fixes the three scheduled
opening minutes from 06:30 through, but excluding, 06:33 Pacific; the exact
gap-up and gap-down extension mirrors; loss of open; a later, inclusive
180-second failed reclaim; and the half-open 06:33–07:15 entry window.

It selects `SESSION_VWAP_BAR_HLC3_V1` and `RS_OPEN_SPY_V1`, including exact
same-instant stock-minus-SPY returns, zero treatment and warm-up. It fixes the
first-three-minute extreme crossing, nonpositive/nonnegative mirrored VWAP
slope, 0.35 gap-fill staleness, stop priority beyond both the opening and reclaim
extremes, structural targets, fixed 2R and fixed 3R exits, score and outcomes.

Point-in-time catalyst class C has no penalty, D subtracts 15 score points, B
subtracts 30 and continuation-aligned A suppresses. Missing catalyst coverage
stays `UNKNOWN`; it is not no-news evidence. Gap direction, catalyst class and
exit policy remain separate in the frozen 480-comparison family.

This is one finite first research version. It does not alter D-090, D-092,
D-093, D-094, D-095 or D-096, approve an operational rule, establish source
coverage or authorize replay or live use. Missing mandatory data stays
unavailable. At the M0.3G freeze, the two unresolved playbook rows in §13 were
`CAT_FIRST_CONSOL` and `VP_ACCEPT_LVN`. That count is historical; §21 records
the current count after M0.3H.

# 21. M0.3H frozen research rules — `M03H_CAT_FIRST_CONSOL_V1`

The owner's 2026-09-13 delegation authorizes the agent-selected offline rules in
[M0_3H_DEFINITION_PACKET.md](./M0_3H_DEFINITION_PACKET.md). Incorporate §§2–9
under this document's strategy authority. The packet fixes point-in-time A/B/C/D
classification, material and contradictory news, the reaction start, regular-
session impulse, two-bar extreme confirmation, first consolidation, exact
0.50/0.65 depth roles, ten-second acceptance and mirrored long/short behavior.

The preserved A/B-only trigger is the primary arm. Class C remains non-actionable
and enters only a separately labeled abnormality diagnostic with exact RVOL and
gap-or-impulse requirements. Class D, ambiguous direction, unknown coverage and
known opposing A/B news suppress. A retracement at or below 0.50 can enter the
primary A/B arm; a value above 0.50 through 0.65 is diagnostic only; a value over
0.65 invalidates.

The version also freezes stop rounding, structural, fixed 2R and fixed 3R exits,
the 40/40/20 score, outcome rules and interaction ownership with `HOD_COMP_RS`.
Direction, catalyst population, depth and exit remain separate in the frozen
720-comparison family.

This is one finite first research version. It does not alter D-090, D-092,
D-093, D-094, D-095, D-096 or D-097, approve an operational rule, establish
source coverage or authorize replay or live use. Missing mandatory data stays
unavailable. At the M0.3H freeze, the one unresolved playbook row in §13 was
`VP_ACCEPT_LVN`. That count is historical; §22 records the current status.

# 22. M0.3I frozen research rules — `M03I_VP_ACCEPT_LVN_V1`

The owner's 2026-09-13 delegation authorizes the agent-selected offline rules in
[M0_3I_DEFINITION_PACKET.md](./M0_3I_DEFINITION_PACKET.md). Incorporate §§2–8
under this document's strategy authority. The packet fixes true-trade and
one-minute-bar allocation, zero-origin tick-rounded bins, three width
sensitivities, edge smoothing, VPOC and value-area ties, exact LVN/HVN shelves,
adjacency and LVN stability.

The version also freezes 90 one-second value-acceptance samples, mirrored value
and LVN crossings, the fourth-total-cross kill (first buffered break = crossing
1; later strict-side changes of the unbuffered value edge count once; equality,
same-side trades and duplicate observations add nothing, per packet §5),
current-session refill bands and
penalties, stop precedence beyond both the acceptance swing and value edge,
structural, fixed 2R and fixed 3R exits, the 45/30/25 score and matched
accepted-value control. Direction, profile mode, width, cohort and exit remain
separate in the frozen 1,440-comparison family.

This is one finite first research version. It does not alter D-090, D-092,
D-093, D-094, D-095, D-096, D-097 or D-098, approve an operational rule,
establish source coverage or authorize replay or live use. True trade-level
profile remains blocked by source evidence. Missing mandatory data stays
unavailable. This freeze resolves the last current PLAYBOOKS §13 strategy row;
separate source, historical replay and implementation gates remain open.

# 23. M4.7 frozen first-four options and portfolio rules

The owner's research delegation freezes `M47_FIRST4_RESEARCH_V1` in
[M4_7_DEFINITION_PACKET.md](./M4_7_DEFINITION_PACKET.md). Its sections 1–5
govern the minimum shared offline options and portfolio path for `CRVOL_ORB5`,
`HOD_COMP_RS`, `OR_FAILURE_REV` and `FIRST_PULLBACK_VWAP`.

The packet preserves `CRVOL_ORB5_OPTION_POLICY_V1`,
`OPTION_SCORE_INTRADAY_LONG_PREMIUM_V1`, all 72 ORB arms and each producer's
structure rules. It freezes the other three ordinary 1–5 DTE policies, exact
mandatory filters, score arithmetic, ties, strict #1 0DTE branch, complete-chain
missingness and separate recommended/poor/unavailable results. Stock validity
never depends on option availability or quality.

It also freezes `M47_CANDIDATE_KEY_V1` and
`M47_FIRST4_GROUP_RECORDING_V1`: literal UTF-8 stable identity, full offline
batch grouping, original-primary time/price anchors, uncalibrated opposite-side
conflict, exact ORB-to-failure release, producer cooldowns and intent-only
expiry. Grouping retains every independent candidate and never pools research
arms. Source, calibration, historical option, later-strategy, M14/M15, shadow
and live gates remain open.
