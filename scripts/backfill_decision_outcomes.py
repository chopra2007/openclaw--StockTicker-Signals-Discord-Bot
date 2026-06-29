"""Backfill script: fill outcome_price_5d / outcome_price_20d on EXISTING
decision_snapshots whose 5/20-trading-day window has already elapsed.

The live price_outcome_loop only fills these going forward (and only revisits
snapshots up to ~20 trading days old). This one-off pass fills the back-catalogue:
for every snapshot older than its horizon, it fetches the HISTORICAL close on the
exact Nth trading day after the alert (the prices already exist) via yfinance — the
same source the engine already uses, no new dependency.

Idempotent: only NULL columns are touched (the loop's own
get_snapshots_needing_outcome filter on `field IS NULL` is reused), so it is safe
to run repeatedly. Existing 1h/24h columns and all other data are never modified.

Usage:
    python3 scripts/backfill_decision_outcomes.py            # fill all eligible rows
    python3 scripts/backfill_decision_outcomes.py --max-rows 200   # cap per horizon
    python3 scripts/backfill_decision_outcomes.py --count    # report only, no writes

WARNING: do NOT run against the live consensus.db while the consensus-engine
service is also writing (the price_outcome_loop fills the same columns). For a
one-time historical fill, run it during a maintenance window or accept that the
loop and this script both COALESCE-fill NULLs (no row is double-counted because
each only writes when the column is still NULL).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure the project root is on sys.path so consensus_engine imports resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consensus_engine import db
from consensus_engine.main import backfill_decision_outcomes, _SLOW_OUTCOME_HORIZONS

log = logging.getLogger("backfill_decision_outcomes")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


async def _count_eligible() -> dict:
    """Report how many rows each horizon WOULD fill, without fetching/writing."""
    await db.init_db()
    out = {}
    for field, _n_td, min_age_days, _max in _SLOW_OUTCOME_HORIZONS:
        rows = await db.get_snapshots_needing_outcome(
            field, min_age_days=min_age_days, max_age_days=None, limit=1_000_000,
        )
        out[field] = len(rows)
    await db.close_db()
    return out


async def _run(max_rows: int | None) -> dict:
    await db.init_db()
    try:
        return await backfill_decision_outcomes(max_rows=max_rows)
    finally:
        await db.close_db()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill 5d/20d trading-day outcome prices on decision_snapshots."
    )
    parser.add_argument(
        "--max-rows", type=int, default=None, metavar="N",
        help="Cap rows scanned per horizon (default: all eligible rows).",
    )
    parser.add_argument(
        "--count", action="store_true",
        help="Report how many rows are eligible; do NOT fetch or write.",
    )
    args = parser.parse_args()

    if args.count:
        counts = asyncio.run(_count_eligible())
        print("Eligible (NULL + window elapsed) decision_snapshots:")
        for field, n in counts.items():
            print(f"  {field}: {n}")
        return 0

    log.info("Backfilling 5d/20d outcomes (max_rows=%s) …", args.max_rows)
    filled = asyncio.run(_run(args.max_rows))
    print("Filled:")
    for field, n in filled.items():
        print(f"  {field}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
