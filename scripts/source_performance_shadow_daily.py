"""#55 Build C — daily analyst track-record SHADOW producer (isolated timer).

ONE cron entrypoint that grades analyst handles from labeled `alert_history` and
writes the result to `source_performance_shadow` by calling the FROZEN producer
`consensus_engine.analysis.source_performance.compute_source_performance_shadow`.
It does not re-implement the grading math.

SAFETY: the producer writes ONLY to `source_performance_shadow`, never to the
live `source_performance` table, so this run changes ZERO live alerts. It is NOT
wired into the live engine loop — it runs from its own daily timer.

Usage:
    python3 scripts/source_performance_shadow_daily.py            # grade + upsert shadow table
    python3 scripts/source_performance_shadow_daily.py --db /tmp/x.db   # target a NON-live db
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Project root on sys.path so consensus_engine imports resolve.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from consensus_engine import config as cfg

log = logging.getLogger("source_performance_shadow_daily")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


async def _run_async() -> dict:
    from consensus_engine import db as db_module
    from consensus_engine.analysis.source_performance import (
        compute_source_performance_shadow,
    )
    await db_module.init_db()
    try:
        return await compute_source_performance_shadow()
    finally:
        await db_module.close_db()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Daily analyst track-record SHADOW producer — grades "
                    "alert_history into source_performance_shadow (never live).")
    parser.add_argument("--db", type=str, default=None, metavar="PATH",
                        help="Target SQLite db (default: database.path from config).")
    args = parser.parse_args()

    import consensus_engine.db as db_module
    db_module.DB_PATH = args.db or cfg.get(
        "database.path", "/home/openclaw/.openclaw/workspace/consensus.db")
    db_module._db = None

    summary = asyncio.run(_run_async())
    print()
    print(f"source_performance_shadow updated: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
