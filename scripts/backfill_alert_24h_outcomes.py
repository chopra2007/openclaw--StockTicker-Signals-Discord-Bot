"""#73: one-off backfill of `alert_history.price_24h_later` for aged-out rows.

Every Friday's alerts used to lose their 24h outcome permanently: the live fill
only works 24-48h after the alert, and the engine sleeps through that window
each weekend (Fri 3pm → Sun 3pm PDT). Measured damage: 4% of Friday rows ever
resolved vs ~100% Mon-Wed. The engine-side fix (_fill_alert_24h_catchup) stops
the bleeding going forward; THIS script recovers the back-catalogue from
historical daily bars, grading each lost row at the next TRADING day's close
(a Friday alert grades at Monday's close).

Mirrors backfill_alert_5d_outcomes.py: batched yfinance downloads (one per
ticker-set chunk, not one per row), the same tested trading-day indexing, and
the same three writes as the live 24h path — alert_history, the linked
decision_snapshot, and the shadow-prediction label. Idempotent: only NULL
cells are written.

Bars end YESTERDAY while the market is open (before 4pm ET): today's daily bar
is the live session still forming, and grading with it would record a spot
price as a "close". After 4pm ET today's final bar is included.

    python3 scripts/backfill_alert_24h_outcomes.py --count
    python3 scripts/backfill_alert_24h_outcomes.py
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from consensus_engine import db  # noqa: E402

# Reuse the batch price fetch + trading-day indexing already proven by #57's grader.
_SPEC = importlib.util.spec_from_file_location(
    "grade_options_flow", _ROOT / "scripts" / "grade_options_flow.py")
_grader = importlib.util.module_from_spec(_SPEC)
sys.modules["grade_options_flow"] = _grader
_SPEC.loader.exec_module(_grader)

log = logging.getLogger("backfill_alert_24h")

N_TRADING_DAYS = 1
# Only rows the live-spot fill can no longer reach (its window closes at 48h).
MIN_AGE_DAYS = 2


def _market_date(ts: float) -> str:
    """The US trading date an alert fired on (UTC-5 lands every session on its day)."""
    return datetime.fromtimestamp(ts - 5 * 3600, tz=timezone.utc).strftime("%Y-%m-%d")


def _bars_end_date() -> date:
    """Last bar date it is safe to grade with: yesterday until 4pm ET, then today."""
    now_et = datetime.now(ZoneInfo("America/New_York"))
    return now_et.date() if now_et.hour >= 16 else now_et.date() - timedelta(days=1)


async def _eligible() -> list[dict]:
    conn = await db.get_db()
    cutoff = datetime.now(timezone.utc).timestamp() - MIN_AGE_DAYS * 86400
    cur = await conn.execute(
        """SELECT id, ticker, alerted_at, price_at_alert FROM alert_history
           WHERE price_24h_later IS NULL AND alerted_at <= ?
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
        end = _bars_end_date()
        log.info("backfilling %d alerts across %d tickers (%s → %s)",
                 len(rows), len(tickers), first, end)

        bars_by_ticker = _grader.fetch_daily_closes(tickers, start, end, use_cache=use_cache)

        filled = no_price = 0
        for r in rows:
            bars = bars_by_ticker.get(r["ticker"])
            close = _grader.close_n_trading_days_later(
                bars, _market_date(r["alerted_at"]), N_TRADING_DAYS) if bars else None
            if close and close > 0:
                await db.update_alert_price(r["id"], "price_24h_later", float(close))
                snapshot_id = await db.get_snapshot_id_for_alert(r["id"])
                if snapshot_id is not None:
                    await db.update_snapshot_outcomes(
                        snapshot_id, outcome_price_24h=float(close))
                entry = float(r.get("price_at_alert") or 0.0)
                if entry > 0:
                    await db.label_shadow_predictions_for_alert_id(
                        alert_history_id=r["id"], horizon="24h",
                        entry_price=entry, exit_price=float(close),
                    )
                filled += 1
            else:
                no_price += 1
        return {"eligible": len(rows), "filled": filled, "no_price": no_price}
    finally:
        await db.close_db()


def main() -> int:
    p = argparse.ArgumentParser(description="Backfill alert_history.price_24h_later (#73).")
    p.add_argument("--count", action="store_true", help="report eligibility, write nothing")
    p.add_argument("--no-cache", action="store_true", help="ignore the price cache")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    out = asyncio.run(run(args.count, use_cache=not args.no_cache))
    if args.count:
        print(f"Eligible alerts (NULL price_24h_later, >= {MIN_AGE_DAYS}d old): {out['eligible']}")
    else:
        print(f"eligible={out['eligible']} filled={out['filled']} no_price={out['no_price']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
