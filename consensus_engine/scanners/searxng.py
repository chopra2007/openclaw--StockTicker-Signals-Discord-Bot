"""SearXNG JSON API client — tier 4 news search fallback.

Self-hosted SearXNG on localhost:8888 aggregates Google, Bing, DuckDuckGo.
"""

import logging
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.utils.rate_limiter import rate_limiter

log = logging.getLogger("consensus_engine.scanner.searxng")


def _parse_searxng_results(data: dict) -> list[dict]:
    """Parse SearXNG JSON response into a list of result dicts."""
    results = []
    for item in data.get("results", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": item.get("content", ""),
        })
    return results


async def search_searxng(query: str) -> list[dict]:
    """Search via self-hosted SearXNG. Returns list of {"title", "url", "content"}."""
    base_url = cfg.get("searxng.base_url", "http://localhost:8888")
    timeout = cfg.get("searxng.timeout", 10)

    if not await rate_limiter.acquire("searxng"):
        return []

    try:
        async with aiohttp.ClientSession() as session:
            params = {"q": query, "format": "json"}
            async with session.get(
                f"{base_url}/search",
                params=params,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    rate_limiter.report_failure("searxng")
                    log.warning("SearXNG returned %d for '%s'", resp.status, query)
                    return []
                data = await resp.json()
                rate_limiter.report_success("searxng")
                results = _parse_searxng_results(data)
                log.debug("SearXNG: %d results for '%s'", len(results), query)
                return results
    except Exception as e:
        log.warning("SearXNG error: %s", e)
        rate_limiter.report_failure("searxng")
        return []
