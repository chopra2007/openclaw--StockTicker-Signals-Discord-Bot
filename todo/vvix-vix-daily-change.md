# Add day-over-day % change to the VVIX fear-of-fear gauge

**Status:** OPEN
**Created:** 2026-08-16

## What the user wants

Right now the `!market` VVIX fear-of-fear gauge (`features.vvix_residual.enabled`, TODO #67 switch 10)
shows the *level* of VVIX and VIX (e.g. "VVIX 87.5 vs VIX 14.2") and where today's reading ranks over
the past year. The user wants the **daily percent change** of each shown too — e.g. "VVIX +4%, VIX +2%
today" — because if VVIX is rising *faster* than VIX, that's an early signal that volatility itself is
about to pick up (fear-of-fear leading fear).

## What already exists

The daily history needed for this is already being collected and stored — no new data source needed.
`vol_of_vol_daily` (`consensus_engine/db.py:1268`) has one row per date with `vvix` and `vix` closes,
written daily by the market_daily writer. Confirmed real data on 2026-08-16:

| date_utc | vvix | vix |
|---|---|---|
| 2026-08-14 | 87.48 | 14.25 |
| 2026-08-13 | 89.42 | 14.63 |
| 2026-08-12 | 88.50 | 14.55 |
| 2026-08-11 | 90.90 | 15.28 |
| 2026-08-10 | 92.51 | 15.46 |

Day-over-day change is a simple two-row read from a table that already exists — this is a display-only
addition, not a new signal or scoring change.

## The job

1. In the `!market` handler (`consensus_engine/alerts/commands.py`, around line 2513-2521 where
   `vvix_row` is built), also fetch the previous day's row from `vol_of_vol_daily` and compute
   `(today - yesterday) / yesterday` for both `vvix` and `vix`.
2. Render both changes next to the existing level line, e.g.:
   `VVIX 87.5 (−2.2% today) vs VIX 14.2 (−2.6% today)`
3. Optional: add a one-line interpretive note when VVIX's % change outpaces VIX's by some threshold —
   "fear-of-fear rising faster than fear itself" — as a plain-language flag, still descriptive-only
   (never feeds the score, per the table's own comment: "DESCRIPTIVE ONLY: never a term in
   score_ticker, never an alert gate").
4. Build under the normal rules: flag stays under the existing `features.vvix_residual.enabled` switch
   (no new flag needed — it's the same feature, more detail), test on real data, no regression.

## Files / code involved

- `consensus_engine/db.py:1268` — `vol_of_vol_daily` table (existing, has what's needed)
- `consensus_engine/alerts/commands.py:2513-2521` — where `vvix_row` is fetched for `!market`
- `consensus_engine/alerts/commands.py` — market embed builder that renders the VVIX line

## Open questions

- Threshold for the "rising faster" interpretive note — needs a reasonable default (e.g. VVIX change
  minus VIX change > some vol-points gap), not user-specified yet.

## Related

- [[feature-menu-ledger.md]] — T1-b, the original VVIX gauge build (2026-07-14)
- TODO #67 — the switch ledger; `features.vvix_residual.enabled` is switch 10 there, still pending go-live
