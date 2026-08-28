"""TODO #100 — the put-flow option-trade OBSERVER runner.

Two jobs, both Pacific time, both OBSERVE ONLY — nothing here places an order,
picks or rejects a stock, and a failure never touches the stock-pair path:

  --select-only  ~06:37 a.m.  For every position that was entered and already
                              has its 06:35 option-chain slice stored, pick the
                              one contract (or one two-leg spread) the frozen
                              rule points at and write its plan row. A morning
                              with nothing eligible is written as NO_OPTION_TRADE,
                              never dropped.
  --run          ~06:34 a.m.  Watch every open option leg: one batched Schwab
                              /quotes every 15 seconds until just after 13:00
                              Pacific, one stored row per contract per minute,
                              one immutable event the first time a position's
                              liquidation value touches its target or stop, or
                              at its frozen time-exit date.

`--dry-run` is structurally unable to write to the database — every insert is a
no-op. `--session YYYY-MM-DD` overrides today. `--once` does a single poll and
returns (for `--run`).

    python3 scripts/put_flow_option_monitor_job.py --select-only
    python3 scripts/put_flow_option_monitor_job.py --run
    python3 scripts/put_flow_option_monitor_job.py --run --once --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from consensus_engine import db  # noqa: E402
from consensus_engine.analysis import put_flow_option_monitor as mon  # noqa: E402

log = logging.getLogger("put_flow_option_monitor")


async def run(args) -> int:
    # The two halves have their own switches: selection can be on while the
    # session monitor is off, and vice versa. Check the one this mode needs.
    wanted = []
    if args.select_only and not mon.select_enabled():
        wanted.append(f"{mon._CFG}.select_enabled")
    if args.run and not mon.monitor_enabled():
        wanted.append(f"{mon._CFG}.monitor_enabled")
    if wanted and not args.force:
        # stdout is reserved for JSON — this note goes to stderr.
        print(" and ".join(wanted) + " is off — nothing done "
              "(use --force to run anyway)", file=sys.stderr)
        return 0
    await db.init_db()
    try:
        if args.select_only:
            out = await mon.select_open_positions(session=args.session,
                                                  dry_run=args.dry_run)
            sys.stdout.write(json.dumps(out, indent=2, default=str) + "\n")
        if args.run:
            out = await mon.run_session(session=args.session, dry_run=args.dry_run,
                                        once=args.once)
            sys.stdout.write(json.dumps(out, indent=2, default=str) + "\n")
    finally:
        await db.close_db()
        try:
            from consensus_engine.utils.http import close_session
            await close_session()
        except Exception:  # noqa: BLE001
            pass
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--select-only", action="store_true",
                   help="~06:37 a.m. pick the contract for every entered position")
    p.add_argument("--run", action="store_true",
                   help="~06:34 a.m. watch every open leg until just after 13:00 Pacific")
    p.add_argument("--once", action="store_true",
                   help="with --run: do a single poll and return")
    p.add_argument("--dry-run", action="store_true",
                   help="write nothing to the database")
    p.add_argument("--session", default=None, help="override today's Pacific session date")
    p.add_argument("--force", action="store_true", help="run even when the switch is off")
    args = p.parse_args()
    # All logging goes to stderr so stdout carries only the JSON result.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(message)s")
    if not (args.select_only or args.run):
        p.print_help()
        return 0
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
