#!/usr/bin/env python3
"""F9 (#76 menu) — daily SEC XBRL fundamentals fetch.

For each active watchlist ticker, pull the SEC company-facts XBRL feed, parse the
last few fiscal quarters, and upsert them into company_fundamentals. Display-only
(read by the !all card when features.sec_xbrl.enabled); never scored. Runs off the
!all hot path via sec-xbrl.timer, honoring SEC's 10 req/s ceiling.

Usage:
    python3 scripts/sec_xbrl_daily.py                       # active watchlist
    python3 scripts/sec_xbrl_daily.py --tickers NVDA,AAPL   # explicit
    python3 scripts/sec_xbrl_daily.py --db /tmp/probe.db --tickers NVDA
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

_WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _WORKSPACE)

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.scanners import sec_xbrl
from consensus_engine.utils.http import close_session

# SEC allows 10 req/s; one request per ticker with a safe margin.
_PER_TICKER_DELAY_S = 0.2


async def _run(tickers: list[str]) -> int:
    await db.init_db()
    written_total = 0
    try:
        for tk in tickers:
            data = await sec_xbrl.fetch_company_facts(tk)
            if not data:
                print(f"{tk}: no facts (no CIK / non-200) — skipped")
                await asyncio.sleep(_PER_TICKER_DELAY_S)
                continue
            rows, rev_tag = sec_xbrl.parse_fundamentals(data)
            if not rows:
                print(f"{tk}: facts fetched but no quarterly revenue parsed — skipped")
                await asyncio.sleep(_PER_TICKER_DELAY_S)
                continue
            cik = str(data.get("cik", "")).zfill(10) if data.get("cik") else None
            for r in rows:
                r["cik"] = cik
            n = await db.upsert_company_fundamentals(tk, rows)
            written_total += n
            latest = rows[0]
            print(f"{tk}: {n} quarter(s) [tag={rev_tag}] latest "
                  f"{latest['fiscal_period']} rev={latest['revenue']:,} "
                  f"yoy={latest['revenue_yoy']}")
            await asyncio.sleep(_PER_TICKER_DELAY_S)
    finally:
        await close_session()
        await db.close_db()
    return written_total


def main() -> int:
    ap = argparse.ArgumentParser(description="F9 daily SEC XBRL fundamentals fetch")
    ap.add_argument("--db", default=None, help="DB path override (default: live)")
    ap.add_argument("--tickers", default=None, help="comma-separated tickers (default: active watchlist)")
    args = ap.parse_args()

    if args.db:
        db.DB_PATH = args.db
        db._db = None

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        async def _tk():
            await db.init_db()
            active = await db.get_active_tickers(min_signals=1)
            core = cfg.get("options_flow.fixed_core", []) or []
            await db.close_db()
            return list(dict.fromkeys([*active, *core]))
        tickers = asyncio.run(_tk())

    if not tickers:
        print("no tickers to fetch")
        return 0

    written = asyncio.run(_run(tickers))
    print(f"\nWrote {written} fundamentals row(s) across {len(tickers)} ticker(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
