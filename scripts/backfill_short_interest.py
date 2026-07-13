"""One-shot backfill: fetch recent FINRA settlement short-interest history for all
active tracked tickers and seed the ``finra_short_interest`` table.

r12 (standalone-scanners): the days-to-cover confluence leg + the !short trend
render need a few prior settlements of history. This script pulls the recent
settlement window per ticker so the ``features.short_interest.enabled`` flag can
be activated with a populated baseline.

Usage:
    python3 scripts/backfill_short_interest.py --dry-run      # list tickers, no DB writes
    python3 scripts/backfill_short_interest.py                 # real backfill
    python3 scripts/backfill_short_interest.py --days 180      # wider window
    python3 scripts/backfill_short_interest.py --ticker NVDA   # single ticker only

Idempotent/re-runnable: upsert on (ticker, settlement_date). Each settlement is
stamped with a HISTORICAL published_at (settlement_date 22:00 UTC) so old rows are
not misread as freshly published by the recency-window gate.

Polite delay: a small sleep between per-ticker fetches to avoid hammering the
FINRA API.
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, time as dt_time, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consensus_engine import db
from consensus_engine.scanners.finra_short_interest import fetch_finra_short_interest

log = logging.getLogger("backfill_short_interest")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_FETCH_DELAY_SEC = 0.5
_DEFAULT_LOOKBACK_DAYS = 120


async def run_backfill(tickers: set[str] | None, lookback_days: int, dry_run: bool) -> None:
    await db.init_db()

    if tickers is None:
        tickers = set(await db.get_active_tickers(min_signals=1))

    if not tickers:
        log.warning("No active tickers found in DB — nothing to backfill.")
        log.info("Tip: run the engine for one poll cycle first, or pass --ticker NVDA.")
        await db.close_db()
        return

    log.info("Backfilling FINRA settlement short-interest for %d tickers: %s",
             len(tickers), sorted(tickers)[:10])

    if dry_run:
        log.info("[DRY RUN] Would fetch ~%d-day settlement history for %d tickers",
                 lookback_days, len(tickers))
        await db.close_db()
        return

    total_rows = 0
    tickers_with_data = 0
    for ticker in sorted(tickers):
        rows = await fetch_finra_short_interest(ticker, lookback_days=lookback_days)
        inserted = 0
        for row in rows:
            # Historical publication stamp: settlement_date 22:00 UTC, so a months-old
            # settlement does not look freshly published to the recency-window gate.
            try:
                _d = datetime.strptime(row["settlement_date"], "%Y-%m-%d")
                pub_at = datetime.combine(_d.date(), dt_time(hour=22), tzinfo=timezone.utc).timestamp()
            except ValueError:
                pub_at = None
            try:
                await db.upsert_finra_short_interest(
                    ticker=row["symbol"],
                    settlement_date=row["settlement_date"],
                    short_interest=row["short_interest"],
                    avg_daily_volume=row["avg_daily_volume"],
                    days_to_cover=row["days_to_cover"],
                    prev_short_interest=row["prev_short_interest"],
                    pct_change=row["pct_change"],
                    published_at=pub_at,
                )
                inserted += 1
            except Exception as exc:
                log.warning("  DB write failed for %s %s: %s",
                            row["symbol"], row["settlement_date"], exc)
        if inserted:
            tickers_with_data += 1
            total_rows += inserted
            log.info("  %s: %d settlements", ticker, inserted)
        await asyncio.sleep(_FETCH_DELAY_SEC)

    log.info("Backfill complete: %d settlement rows across %d/%d tickers.",
             total_rows, tickers_with_data, len(tickers))
    await db.close_db()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill FINRA settlement short-interest (r12).")
    parser.add_argument("--days", type=int, default=_DEFAULT_LOOKBACK_DAYS,
                        help="Calendar days of settlement history to pull (default: %(default)s)")
    parser.add_argument("--ticker", type=str, default=None,
                        help="Comma-separated list of specific tickers (default: all active)")
    parser.add_argument("--dry-run", action="store_true", help="List tickers, no DB writes")
    args = parser.parse_args()

    tickers: set[str] | None = None
    if args.ticker:
        tickers = {t.strip().upper() for t in args.ticker.split(",")}

    asyncio.run(run_backfill(tickers=tickers, lookback_days=args.days, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
