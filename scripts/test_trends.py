#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from consensus_engine import config as cfg, db
import time

async def main():
    await db.init_db()
    tickers = ["SPY", "AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "META", "GOOGL", "AMD", "COIN"]
    print(f"Testing trends for: {tickers}")
    from consensus_engine.scanners import social
    trends = await social.scan_google_trends_serpapi(tickers)
    print(f"Trends results: {trends}")
    await db.close_db()

if __name__ == '__main__':
    asyncio.run(main())
