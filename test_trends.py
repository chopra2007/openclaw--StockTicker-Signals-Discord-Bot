#!/usr/bin/env python3
import asyncio
import sys
sys.path.insert(0, '.')
from consensus_engine import config as cfg, db
import time

async def main():
    await db.init_db()
    # Use volume watchlist from config as fallback
    watchlist = cfg.get('volume_scanner.watchlist', [])
    print(f"Volume watchlist length: {len(watchlist)}")
    # Take first 10
    tickers = watchlist[:10]
    print(f"Testing trends for: {tickers}")
    from consensus_engine.scanners import social
    trends = await social.scan_google_trends_serpapi(tickers)
    print(f"Trends results: {trends}")
    await db.close_db()

if __name__ == '__main__':
    asyncio.run(main())