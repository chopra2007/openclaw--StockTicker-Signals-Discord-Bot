"""#55/#62 — daily analyst track-record producers (isolated timer).

ONE cron entrypoint that grades analyst handles from labeled `alert_history`:

- `compute_source_performance_shadow` -> `source_performance_shadow` at 1h/24h (#55)
- `compute_source_performance_live`   -> `source_performance` at 24h/5d (#62)

It does not re-implement the grading math; both producers live in
`consensus_engine.analysis.source_performance`.

SAFETY — why writing the LIVE table changes zero alerts today:
every live reader resolves its horizon through `db.analyst_horizon()`, which
returns '1h' until `scoring.analyst_accuracy_weight.enabled` is flipped. The live
producer never writes a '1h' row. So the table accumulates 24h/5d track records
while every reader keeps missing and staying cold-start. The auto-flip engine
flips that flag only once an analyst clears n>=90, Wilson-LB>0.50 and BH-FDR
q<=0.10 — that flip, not this producer, is what puts the data to work.

Usage:
    python3 scripts/source_performance_shadow_daily.py            # both producers
    python3 scripts/source_performance_shadow_daily.py --shadow-only
    python3 scripts/source_performance_shadow_daily.py --db /tmp/x.db   # NON-live db
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


async def _run_async(shadow_only: bool) -> dict:
    from consensus_engine import db as db_module
    from consensus_engine.analysis.source_performance import (
        compute_source_performance_live,
        compute_source_performance_shadow,
    )
    await db_module.init_db()
    try:
        out = {"shadow": await compute_source_performance_shadow()}
        if not shadow_only:
            out["live"] = await compute_source_performance_live()
            out["reader_horizon"] = db_module.analyst_horizon()
        return out
    finally:
        await db_module.close_db()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Daily analyst track-record producers — grade alert_history "
                    "into source_performance_shadow (1h/24h) and source_performance "
                    "(24h/5d).")
    parser.add_argument("--db", type=str, default=None, metavar="PATH",
                        help="Target SQLite db (default: database.path from config).")
    parser.add_argument("--shadow-only", action="store_true",
                        help="Skip the #62 live-table producer.")
    args = parser.parse_args()

    import consensus_engine.db as db_module
    db_module.DB_PATH = args.db or cfg.get(
        "database.path", "/home/openclaw/.openclaw/workspace/consensus.db")
    db_module._db = None

    summary = asyncio.run(_run_async(args.shadow_only))
    print()
    print(f"source_performance_shadow updated: {summary['shadow']}")
    if "live" in summary:
        print(f"source_performance (live)  updated: {summary['live']}")
        print(f"live readers currently consult horizon '{summary['reader_horizon']}' "
              f"({'COLD-START — alerts unchanged' if summary['reader_horizon'] == '1h' else 'ACTIVE'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
