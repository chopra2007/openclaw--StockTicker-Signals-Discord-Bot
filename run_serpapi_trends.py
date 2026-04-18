#!/usr/bin/env python3
import asyncio
import logging
logging.basicConfig(level=logging.DEBUG)
from consensus_engine import config as cfg_module, db
from consensus_engine.scanners import social

cfg_module.load_config()
print('Config loaded')

async def run():
    active = await db.get_active_tickers(min_signals=2)
    print(f'Active tickers: {active[:10]}')
    
    trends = await social.scan_google_trends_serpapi(active[:10])
    print(f'Result: {trends}')
    return trends

asyncio.run(run())
