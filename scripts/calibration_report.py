#!/usr/bin/env python3
"""Weekly calibration report -> #errors (F6, #76 menu).

The eval maths already exists (`python -m consensus_engine.eval`), but it is
manual-only: nobody ever sees "how well-calibrated was the bot?" unless a human
runs the CLI by hand. This script runs weekly via calibration-report.timer, asks
`consensus_engine.eval.report.run()` for the numbers (READ-ONLY), formats a short
plain-English summary, and posts it to the #errors channel.

Failure handling (per the build plan): if report.run() itself raises, we log the
full traceback, post NOTHING, and exit NON-ZERO so systemd marks the unit failed
and its OnFailure=alert@%n.service path fires — a swallowed exception would make
the weekly report silently vanish with no journal signal.

Flag: features.calibration_report.enabled (default false). When OFF the script
exits 0 without posting. --dry-run always prints the message and never posts, so
the report can be probed before the flag is flipped.
"""
import argparse
import asyncio
import os
import sys
import traceback

_WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _WORKSPACE)

from consensus_engine import config as cfg
from consensus_engine.eval import report
from consensus_engine.eval import loaders


def _build_message(db_path: str, out_path: str | None) -> str:
    """Run the eval and format it. Raises on eval failure (caller handles)."""
    result = report.run(db_path=db_path, out_path=out_path)
    return report.format_discord(result["sections"])


async def _post(message: str) -> None:
    from consensus_engine.alerts.discord import send_message
    from consensus_engine.alerts.ops_alert import errors_channel_id

    channel = errors_channel_id()
    if not channel:
        # No sink configured -> fail loudly rather than silently drop the report.
        raise RuntimeError("no #errors channel id configured (discord.errors_channel_id)")
    await send_message(channel, message)


def main() -> int:
    parser = argparse.ArgumentParser(description="Weekly calibration report -> #errors (F6)")
    parser.add_argument("--db", default=loaders.DEFAULT_DB,
                        help="path to the consensus DB (read-only)")
    parser.add_argument("--out", default=None,
                        help="optional path to also write the full markdown report")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the message, never post to Discord (works regardless of flag)")
    args = parser.parse_args()

    # Build the report first; a report-build failure must exit non-zero (systemd OnFailure).
    try:
        message = _build_message(args.db, args.out)
    except Exception:
        traceback.print_exc()
        print("calibration_report: eval.report.run() failed — posting nothing", file=sys.stderr)
        return 1

    if args.dry_run:
        print("[DRY RUN] would post to #errors:\n" + message)
        return 0

    if not cfg.get("features.calibration_report.enabled", False):
        print("calibration_report: features.calibration_report.enabled is OFF — not posting")
        return 0

    try:
        asyncio.run(_post(message))
    except Exception:
        traceback.print_exc()
        print("calibration_report: Discord post failed", file=sys.stderr)
        return 1

    print("calibration_report: posted weekly report to #errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
