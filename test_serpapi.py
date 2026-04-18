#!/usr/bin/env python3
import asyncio
import logging
import aiohttp
from consensus_engine import config as cfg_module, db
from consensus_engine.scanners import social

logging.basicConfig(level=logging.DEBUG)
cfg_module.load_config()

# Direct test of SerpAPI call
async def test_serpapi():
    api_key = cfg_module.get_api_key("serpapi")
    print(f"API key present: {bool(api_key)}")
    print(f"API key: {api_key[:10]}..." if api_key else "No key")
    
    async with aiohttp.ClientSession() as session:
        params = {
            "engine": "google_trends",
            "q": "AAPL stock",
            "date": "now 1-d",
            "geo": "US",
            "api_key": api_key,
        }
        print(f"Calling SerpAPI with params: {params}")
        async with session.get(
            "https://serpapi.com/search.json",
            params=params,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            print(f"Status: {resp.status}")
            data = await resp.json()
            print(f"Response: {data}")
            return data

asyncio.run(test_serpapi())
