# TODO #87 — daily SPY expected-move numbers checked against the 47 stored snapshots

The brief reuses `expected_move.compute_em("SPY", horizon="daily")` — the same function
`!em SPY` calls. So the question is whether the CURRENT formulas still agree with the numbers
stored by `scripts/iv_snapshot_daily.py` since 2026-06-29. Two independent checks:

## Check 1 — does the stored `iv_em_to_expiry` column still match the code's definition?

`calculate_expected_moves` defines `iv_em_to_expiration = spot * atm_iv * sqrt(T_252)`
(trading-day clock, deliberately frozen so old rows stay comparable). Solving each stored row
for the T it implies:

| implied T in trading days | rows |
|---|---|
| 1 | 46 |
| 2 | 1 |

Every one of the 47 rows lands on a whole number of trading days (1, or 2 over a
holiday-shortened gap). The stored column is exactly `spot * atm_iv * sqrt(T_252)`, so the
current code's definition has NOT drifted from the data it produced.

## Check 2 — is the stored straddle consistent with the stored quoted IV?

Independent of check 1: `implied_iv_from_straddle(straddle, spot, T_365)` backs the annualised
vol out of the straddle price on a CALENDAR clock. Compared against the chain's own quoted
`atm_iv` for the same row. A straddle and a quoted vol describe the same option, so these
should be in the same neighbourhood; they are not required to be identical (the straddle
carries the bid/ask spread and the 0.798-sigma conversion).

- rows compared: **47**
- ratio straddle-implied IV / quoted ATM IV: median **1.15**, min 0.94, max 1.88
- within a factor of 2 of the quoted vol: **47 of 47**

The two measures track each other across the whole sample — no row shows the straddle and the
quoted vol disagreeing by an order of magnitude, which is what a broken units conversion (the
trading-day vs calendar-day mix-up documented in `calculate_expected_moves`) would look like.

## What this does NOT prove — stated plainly

- These snapshots store one row per day per ticker at the NEAREST expiration. They are not a
  full option chain, so an old daily chart cannot be re-rendered from them; what is verified is
  that the numbers the chart is built from still follow the same formulas that produced the
  stored history.
- No weekly chains were ever snapshotted. A multi-date WEEKLY replay is therefore impossible,
  and none is claimed. The weekly chart is verified only against the same live chain `!emw`
  reads, at the time of the live test.
