# M9_1T_PARAMETER_GRID_PREREGISTRATION.md

## Status and authority

**FROZEN FOR OFFLINE RESEARCH**, 2026-09-18 Pacific. Agent-selected under the
2026-09-13 [RESEARCH_AUTHORIZATION](./RESEARCH_AUTHORIZATION_20260913.md)
delegation and owner decision D-107/D-108 (2026-09-16, see
[DECISIONS_AND_OPEN_QUESTIONS.md](./DECISIONS_AND_OPEN_QUESTIONS.md) sections
56-57). This is build-scope item (c) from the 2026-09-17 M9.1 inventory: the
frozen parameter grid over the eight open settings (D-043, D-044, D-045,
D-048, D-049, D-052, D-054, D-055), the playbook-combination candidates, and
confirmation of the D-107 9-train/8-held-out split. **No search has run, no
signal has been generated and no return has been read while writing this
record.** This packet freezes the grid; it does not evaluate it. Items (d) the
D-108 evaluator and (e) the search run itself remain separate, unstarted work.

## 1. Confirmed split (unchanged, reproduced from D-107 for this record)

- **Training (9):** NVDA, MSFT, AAPL, TSLA, LLY, SPY, QQQ, XLV, USO
- **Held out (8):** GOOGL, AMZN, META, AVGO, BRK.B, IWM, GLD, VXX

All parameter selection in stage 1 below (per-playbook winning configuration)
and stage 2 (playbook-combination selection) uses only the training nine. The
held-out eight are not inspected, plotted, counted or used for any tuning
decision until both stages are final and this record is unchanged. The D-108
pass/fail bar is evaluated only on the held-out eight, after both stages are
frozen.

## 2. Per-strategy setting axes

Each axis below lists the current `PLAYBOOKS.md` default (kept as one named
candidate, not privileged) plus reasonable finite alternatives. Two or three
candidates per axis, matching `TESTING_AND_VALIDATION.md`'s "keep parameter
grids small" instruction. No axis may be added, removed or renamed after a
result is read.

### `CRVOL_ORB5` (#1) — D-043, D-044, D-045

**D-043 — opening-range duration.** Reuses the already-frozen `OR5_V2`/
`OR15_V2` definitions from `M0_3B_DEFINITION_PACKET.md`'s
`M03B_OR_RESEARCH_V2` preregistration (same slot construction, availability
time and common gates); this axis only selects which duration feeds
`CRVOL_ORB5`'s eligibility/trigger for this D-107 search. Candidates:

| ID | Value |
|---|---|
| `OR5` (current default) | 5-minute range |
| `OR15` | 15-minute range |

**D-044 — 5m RVOL participation threshold** (`min_open5_rvol` /
`stock_in_play_min_open5_rvol` gate). Candidates:

| ID | Value |
|---|---|
| `RVOL_1_5` | >= 1.5 |
| `RVOL_2_0` (current default) | >= 2.0 |
| `RVOL_2_5` | >= 2.5 |

**D-045 — acceptance window/prior** (`acceptance_10s >= 0.70` trigger gate).
Window and prior are preregistered as three paired named candidates rather
than a free cross, to keep the axis finite and small:

| ID | Window | Prior |
|---|---|---|
| `ACC_10S_060` | 10s | >= 0.60 |
| `ACC_10S_070` (current default) | 10s | >= 0.70 |
| `ACC_30S_070` | 30s | >= 0.70 |

`CRVOL_ORB5` per-strategy grid size: `2 * 3 * 3 = 18` configurations.

### `HOD_COMP_RS` (#2) — D-048, D-049

**D-048 — compression filter.** Candidates:

| ID | Value |
|---|---|
| `COMP_ON_060` (current default) | require last-3/prior-7 range ratio <= 0.60 before arming |
| `COMP_OFF` | drop the compression prerequisite; arm on the existing RVOL/VWAP/RS gates alone against the frozen point-in-time HOD/LOD reference |

**D-049 — relative-strength gate.** Candidates:

| ID | Value |
|---|---|
| `RS_MANDATORY` (current default) | `rs_15m >= max(0.003, 0.15 * daily_atr_pct)` required to arm |
| `RS_REPORT_ONLY` | `rs_15m` computed and reported per trade but not required to arm |

`HOD_COMP_RS` per-strategy grid size: `2 * 2 = 4` configurations.

### `OR_FAILURE_REV` (#3) — D-052

**D-052 — confirmation vs faster entry.** Candidates:

| ID | Value |
|---|---|
| `CONFIRMED` (current default) | require the 1-minute close back inside `ORH`/`ORL` before the failure state is `ARMED` |
| `FASTER` | arm on the real break-and-reject (last back inside, `acceptance_inside` gate) without waiting for a completed 1-minute close |

`OR_FAILURE_REV` per-strategy grid size: `2` configurations.

### `FIRST_PULLBACK_VWAP` (#4) — D-054, D-055

**D-054 — VWAP mandatory vs relaxed.** Candidates:

| ID | Value |
|---|---|
| `VWAP_MANDATORY` (current default) | `price > VWAP` and `VWAP_slope > 0` both required to arm/trigger |
| `VWAP_RELAXED` | VWAP position/slope computed and reported but not required to arm; pullback/trigger structure gates still apply |

**D-055 — AVWAP.** Candidates:

| ID | Value |
|---|---|
| `AVWAP_OFF` (current default) | AVWAP not used; pullback support judged only against session VWAP and the `0.15 ATR` band |
| `AVWAP_ON` | pullback support additionally validated against the session anchored VWAP (impulse-origin anchor); armed only when either session-VWAP or AVWAP support holds |

`FIRST_PULLBACK_VWAP` per-strategy grid size: `2 * 2 = 4` configurations.

## 3. Two-stage search design

A single flat cross of every axis across all four playbooks
(`18 * 4 * 2 * 4 = 576` combined configurations before any playbook-combination
choice) is not a small grid and is not preregistered. Instead:

**Stage 1 — per-playbook winning configuration.** For each of the four
playbooks independently, evaluate its own finite candidate configurations
(18, 4, 2 and 4 respectively above) on the training nine only, using the same
three D-108 measures (per-trade mean profit with bootstrap lower bound,
weekly win rate, worst recoverable drawdown) as a training-set ranking, not a
pass/fail bar — D-108's pass/fail bar itself applies only to the held-out
eight in stage 3. The configuration with the highest training-set per-trade
mean profit after costs is that playbook's single winning configuration
going into stage 2. Ties are broken by weekly win rate, then by lower
drawdown; a tie surviving all three is broken by the lowest-ID candidate in
the tables above, fixed before any result is read.

**Stage 2 — playbook-combination selection.** With each playbook's winning
configuration now fixed, select which playbooks run together as the alert
portfolio from these five finite candidates, evaluated on the training nine
using the same training-set ranking rule as stage 1:

| ID | Playbooks included |
|---|---|
| `SOLO_ORB5` | `CRVOL_ORB5` only |
| `SOLO_HODCOMP` | `HOD_COMP_RS` only |
| `SOLO_ORFAIL` | `OR_FAILURE_REV` only |
| `SOLO_PULLBACK` | `FIRST_PULLBACK_VWAP` only |
| `ALL_FOUR` | all four combined, D-106 anti-fooling one-event-per-ticker-day-side clustering applied across the combined alert stream |

The combination with the highest training-set per-trade mean profit after
costs is the single winning combination going into stage 3. The same
tie-break order as stage 1 applies.

**Stage 3 — held-out D-108 evaluation.** The stage-1 winning per-playbook
configurations, combined per the stage-2 winning combination, are evaluated
exactly once against the frozen D-108 bar (profit + bootstrap lower bound,
>=60% winning weeks, drawdown recoverable within about six average winning
weeks) on the held-out eight. This is the only step that reads the held-out
eight, and it happens only after stages 1 and 2 are complete and unchanged.

No configuration, axis, candidate or tie-break rule in this document may be
added, removed, tuned or renamed once stage 1 begins reading training-set
results.

## 4. What this record does not do

- It does not run the search (item (e), unstarted).
- It does not implement the D-108 evaluator (item (d), unstarted); stages 1-3
  above describe what that evaluator must compute, not a working
  implementation.
- It does not compute, inspect or imply any return, win rate or profit figure
  for any candidate.
- It does not change `first_pullback_vwap.py`, `hod_compression.py`,
  `or_failure_rev.py`, `orb5_eligibility.py` or any other production module;
  the alternative candidates above (e.g. `COMP_OFF`, `RS_REPORT_ONLY`,
  `FASTER`, `VWAP_RELAXED`, `AVWAP_ON`) are research-only variants to be
  exercised through each strategy's existing caller-supplied
  `EligibilityRequest`/`TriggerRequest` fields once the M9.1 bar-to-replay
  adapters and outcome evaluators (items (a)/(b), already built in M9.1A-S)
  are driven by the search itself in a later sub-step.
- It does not close the D-104 original-availability/finality or point-in-time
  membership gaps, or the quote-decision/M4.4-confidence gap recorded in
  M9.1S. Those stay recorded gaps with dependent rules off; any stage-1/2/3
  result must say so.

No provider call, application run, alert, order or spend occurred while
writing this record.
