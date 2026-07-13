"""#62: one-off backfill of `alert_history.price_5d_later` across the back-catalogue.

The live `price_outcome_loop` fills this going forward, one row at a time, which is
fine at a few rows per cycle. Filling ~4,000 historical rows that way means ~4,000
separate yfinance calls, and yfinance starts refusing long before the end — a first
attempt filled 73 of 550 analyst-bearing rows.

So this does what `grade_options_flow.py` does: download each ticker's daily bars
ONCE for the whole span, then index every alert into them locally. ~15 network calls
instead of ~4,000, and the trading-day arithmetic is the same tested helper.

Idempotent: only NULL `price_5d_later` cells are written.

    python3 scripts/backfill_alert_5d_outcomes.py --count
    python3 scripts/backfill_alert_5d_outcomes.py
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from consensus_engine import db  # noqa: E402

# Reuse the batch price fetch + trading-day indexing already proven by #57's grader.
_SPEC = importlib.util.spec_from_file_location(
    "grade_options_flow", _ROOT / "scripts" / "grade_options_flow.py")
_grader = importlib.util.module_from_spec(_SPEC)
sys.modules["grade_options_flow"] = _grader
_SPEC.loader.exec_module(_grader)

log = logging.getLogger("backfill_alert_5d")

N_TRADING_DAYS = 5
# The alert's own session is bar 0; we need bar 5 to exist. Pad in calendar days.
MIN_AGE_DAYS = 7


def _market_date(ts: float) -> str:
    """The US trading date an alert fired on (UTC-5 lands every session on its day)."""
    return datetime.fromtimestamp(ts - 5 * 3600, tz=timezone.utc).strftime("%Y-%m-%d")


async def _eligible() -> list[dict]:
    conn = await db.get_db()
    cutoff = datetime.now(timezone.utc).timestamp() - MIN_AGE_DAYS * 86400
    cur = await conn.execute(
        """SELECT id, ticker, alerted_at FROM alert_history
           WHERE price_5d_later IS NULL AND alerted_at <= ?
             AND ticker IS NOT NULL AND ticker != ''
           ORDER BY alerted_at DESC""",
        (cutoff,),
    )
    return [dict(r) for r in await cur.fetchall()]


async def run(count_only: bool, use_cache: bool) -> dict:
    await db.init_db()
    try:
        rows = await _eligible()
        if count_only or not rows:
            return {"eligible": len(rows), "filled": 0, "no_price": 0}

        tickers = sorted({r["ticker"] for r in rows})
        first = min(_market_date(r["alerted_at"]) for r in rows)
        start = date.fromisoformat(first) - timedelta(days=5)
        end = datetime.now(timezone.utc).date()
        log.info("backfilling %d alerts across %d tickers (%s → %s)",
                 len(rows), len(tickers), first, end)

        bars_by_ticker = _grader.fetch_daily_closes(tickers, start, end, use_cache=use_cache)

        filled = no_price = 0
        for r in rows:
            bars = bars_by_ticker.get(r["ticker"])
            close = _grader.close_n_trading_days_later(
                bars, _market_date(r["alerted_at"]), N_TRADING_DAYS) if bars else None
            if close and close > 0:
                await db.update_alert_price(r["id"], "price_5d_later", float(close))
                filled += 1
            else:
                no_price += 1
        return {"eligible": len(rows), "filled": filled, "no_price": no_price}
    finally:
        await db.close_db()


def main() -> int:
    p = argparse.ArgumentParser(description="Backfill alert_history.price_5d_later (#62).")
    p.add_argument("--count", action="store_true", help="report eligibility, write nothing")
    p.add_argument("--no-cache", action="store_true", help="ignore the price cache")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    out = asyncio.run(run(args.count, use_cache=not args.no_cache))
    if args.count:
        print(f"Eligible alerts (NULL price_5d_later, >= {MIN_AGE_DAYS}d old): {out['eligible']}")
    else:
        print(f"eligible={out['eligible']} filled={out['filled']} no_price={out['no_price']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
