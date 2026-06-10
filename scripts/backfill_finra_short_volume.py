"""One-shot backfill: fetch the last 30 trading days of FINRA CNMS short-volume
data for all active tracked tickers and seed the ``finra_short_volume`` table.

E1 (signal-features-2026-06-09): the z-score confluence scorer requires a
30-day baseline before it can contribute any points.  This script provides that
baseline so the ``features.finra_short_volume.enabled`` flag can be activated.

Usage:
    python3 scripts/backfill_finra_short_volume.py --dry-run      # list dates, no DB writes
    python3 scripts/backfill_finra_short_volume.py                 # real backfill
    python3 scripts/backfill_finra_short_volume.py --days 14       # shorter window
    python3 scripts/backfill_finra_short_volume.py --ticker NVDA   # single ticker only

Idempotent/re-runnable: upsert on (ticker, trade_date) — safe to run multiple
times.  Weekends and holidays return 404 — skipped gracefully.

Polite delay: a small sleep between file fetches to avoid hammering FINRA's CDN.
"""

import argparse
import asyncio
import logging
import sys
import time
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consensus_engine import db
from consensus_engine.scanners.finra_short_volume import (
    fetch_finra_short_volume,
    ingest_finra_day,
)

log = logging.getLogger("backfill_finra")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Polite delay between file fetches (seconds)
_FETCH_DELAY_SEC = 1.0
# Max calendar days to look back (we skip weekends/holidays automatically)
_DEFAULT_LOOKBACK_CALENDAR_DAYS = 45  # ~30 trading days within 45 calendar days


def _trading_day_candidates(lookback_calendar_days: int = _DEFAULT_LOOKBACK_CALENDAR_DAYS) -> list[date]:
    """Return calendar dates from today-1 back `lookback_calendar_days` days,
    excluding weekends.  We always start from yesterday (T-1) since today's
    file is not yet published until after market close.
    """
    today = date.today()
    candidates = []
    for offset in range(1, lookback_calendar_days + 1):
        d = today - timedelta(days=offset)
        if d.weekday() < 5:  # Mon-Fri only (holidays return 404 — handled gracefully)
            candidates.append(d)
    return sorted(candidates)


async def run_backfill(
    tickers: set[str] | None,
    lookback_days: int,
    dry_run: bool,
) -> None:
    """Main backfill logic."""
    await db.init_db()

    if tickers is None:
        tickers_list = await db.get_active_tickers(min_signals=1)
        tickers = set(tickers_list)

    if not tickers:
        log.warning("No active tickers found in DB — nothing to backfill.")
        log.info("Tip: run the engine for one poll cycle first to populate ticker_signals,")
        log.info("     or specify --ticker NVDA to test with a specific ticker.")
        await db.close_db()
        return

    log.info("Backfilling FINRA short-volume for %d tracked tickers: %s",
             len(tickers), sorted(tickers)[:10])

    candidates = _trading_day_candidates(lookback_calendar_days=lookback_days)
    log.info("Date range: %s → %s (%d candidate trading days)",
             candidates[0], candidates[-1], len(candidates))

    if dry_run:
        log.info("[DRY RUN] Would fetch %d dates for %d tickers",
                 len(candidates), len(tickers))
        await db.close_db()
        return

    total_rows = 0
    days_with_data = 0
    days_404 = 0

    for trade_date in candidates:
        rows = await fetch_finra_short_volume(trade_date, tickers=tickers)
        if not rows:
            log.debug("  %s: no data (404/weekend/holiday)", trade_date)
            days_404 += 1
            await asyncio.sleep(_FETCH_DELAY_SEC)
            continue

        inserted = 0
        # Historical rows must carry a HISTORICAL publication time, not "now" —
        # FINRA publishes the daily file after the close (~6pm ET), so stamp
        # trade_date 22:00 UTC. Stamping time.time() would make month-old rows
        # look freshly published to the recency-window gate.
        _dt = datetime.combine(trade_date, dt_time(hour=22), tzinfo=timezone.utc)
        pub_at = _dt.timestamp()
        for row in rows:
            try:
                await db.upsert_finra_short_volume(
                    ticker=row["symbol"],
                    trade_date=row["trade_date"],
                    total_volume=row["total_volume"],
                    short_volume=row["short_volume"],
                    short_exempt_volume=row["short_exempt_volume"],
                    short_pct=row["short_pct"],
                    finra_published_at=pub_at,
                )
                inserted += 1
            except Exception as exc:
                log.warning("  DB write failed for %s %s: %s",
                             row["symbol"], trade_date, exc)

        log.info("  %s: %d rows inserted", trade_date, inserted)
        total_rows += inserted
        if inserted:
            days_with_data += 1

        await asyncio.sleep(_FETCH_DELAY_SEC)

    log.info(
        "Backfill complete: %d rows inserted across %d trading days "
        "(%d dates returned 404/holiday).",
        total_rows, days_with_data, days_404,
    )
    covered = await db.get_db()
    cur = await covered.execute("SELECT COUNT(DISTINCT ticker) FROM finra_short_volume")
    n_covered = (await cur.fetchone())[0]
    log.info("Tickers covered: %d of %d requested", n_covered, len(tickers))

    # Summary: show per-ticker sample counts
    if total_rows:
        log.info("Sample counts per ticker (up to 10):")
        for tkr in sorted(tickers)[:10]:
            bl = await db.get_finra_short_volume_baseline(tkr)
            log.info("  %s: %d days, mean_short_pct=%.3f std=%.3f",
                     tkr, bl["sample_days"], bl["mean"], bl["std"])

    await db.close_db()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill FINRA short-volume baseline (E1).")
    parser.add_argument("--days", type=int, default=_DEFAULT_LOOKBACK_CALENDAR_DAYS,
                        help="Calendar days to look back (default: %(default)s ~ 30 trading days)")
    parser.add_argument("--ticker", type=str, default=None,
                        help="Comma-separated list of specific tickers (default: all active)")
    parser.add_argument("--dry-run", action="store_true",
                        help="List dates and ticker set, no DB writes")
    args = parser.parse_args()

    tickers: set[str] | None = None
    if args.ticker:
        tickers = {t.strip().upper() for t in args.ticker.split(",")}

    asyncio.run(run_backfill(tickers=tickers, lookback_days=args.days, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
