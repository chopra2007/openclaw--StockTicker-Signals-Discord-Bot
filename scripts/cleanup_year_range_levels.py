"""One-time cleanup: mark historical youtube_levels offenders as suppressed.

W1 A-T0 closes the year-as-price leak at insert time, but rows inserted
*before* the filter shipped still survive (state.json row 201 MSFT $2024
class). This script re-applies the calendar filter against the existing
table and marks offenders `suppressed=1, suppression_reason='backfill_year_range'`.

Mirror of v2's `cleanup_corrupt_youtube_levels.py` (referenced in
v2-quality-rebuild PR5 history). Idempotent: re-running over already-suppressed
rows is a no-op.

Usage:
    python3 -m scripts.cleanup_year_range_levels [--db PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

# Repo-relative import — keep this script runnable from any cwd.
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from consensus_engine.analysis.calendar_filter import is_calendar_year_in_context

DEFAULT_DB = _REPO / "consensus.db"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cleanup_year_range_levels")


def cleanup(db_path: Path, dry_run: bool) -> int:
    """Mark year-range-in-calendar-context rows suppressed. Returns affected row count."""
    if not db_path.exists():
        log.error("db not found: %s", db_path)
        return 0

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, ticker, price, source_snippet, suppressed "
            "FROM youtube_levels WHERE price BETWEEN 1900 AND 2100"
        ).fetchall()
        log.info("scanning %d candidate rows in year window", len(rows))

        offenders: list[tuple[int, str, float]] = []
        for r in rows:
            if r["suppressed"]:
                continue
            if is_calendar_year_in_context(r["price"], r["source_snippet"], r["ticker"] or ""):
                offenders.append((r["id"], r["ticker"] or "", float(r["price"])))

        log.info("found %d offenders to suppress", len(offenders))
        for row_id, ticker, price in offenders:
            log.info("  id=%d %s @ $%.2f", row_id, ticker, price)

        if dry_run:
            log.info("dry-run: no writes")
            return len(offenders)

        if offenders:
            conn.executemany(
                "UPDATE youtube_levels "
                "SET suppressed = 1, suppression_reason = 'backfill_year_range' "
                "WHERE id = ?",
                [(row_id,) for row_id, _, _ in offenders],
            )
            conn.commit()
            log.info("suppressed %d rows", len(offenders))
        return len(offenders)
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    count = cleanup(args.db, args.dry_run)
    return 0 if count >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
