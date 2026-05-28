"""SearXNG JSON API client — tier 4 news search fallback.

Self-hosted SearXNG on localhost:8888 aggregates Google, Bing, DuckDuckGo.
When SearXNG fails or returns nothing, falls back to Tavily then Firecrawl
so the three callers keep getting results without any change on their side.
"""

import logging
import os
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.utils.http import get_session
from consensus_engine.utils.rate_limiter import rate_limiter

log = logging.getLogger("consensus_engine.scanner.searxng")

# Per-provider HTTP timeout (seconds). Kept at 6s each because gap_fill wraps
# the whole search_searxng() call in an 8s asyncio.wait_for budget.
_FALLBACK_TIMEOUT = 6


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
    """Search via self-hosted SearXNG. Returns list of {"title", "url", "content"}.

    When SearXNG is rate-limited, errors, returns a non-200, or returns zero
    results, falls back to Tavily then Firecrawl. A healthy SearXNG response
    with at least one result never triggers the fallback.
    """
    base_url = cfg.get("searxng.base_url", "http://localhost:8888")
    timeout = cfg.get("searxng.timeout", 10)

    if not await rate_limiter.acquire("searxng"):
        return await _search_fallback(query)

    try:
        session = await get_session()
        params = {"q": query, "format": "json"}
        async with session.get(
            f"{base_url}/search",
            params=params,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status != 200:
                rate_limiter.report_failure("searxng")
                log.warning("SearXNG returned %d for '%s'", resp.status, query)
                return await _search_fallback(query)
            data = await resp.json()
            rate_limiter.report_success("searxng")
            results = _parse_searxng_results(data)
            log.debug("SearXNG: %d results for '%s'", len(results), query)
            if results:
                return results
            return await _search_fallback(query)
    except Exception as e:
        log.warning("SearXNG error: %s", e)
        rate_limiter.report_failure("searxng")
        return await _search_fallback(query)


async def _search_fallback(query: str) -> list[dict]:
    """SearXNG unavailable/empty — try Tavily, then Firecrawl. Returns []
    only if both miss or have no API key configured."""
    results = await _tavily_search(query)
    if results:
        log.warning("SearXNG empty/failed; Tavily fallback returned %d for '%.60s'",
                    len(results), query)
        return results
    results = await _firecrawl_search(query)
    if results:
        log.warning("SearXNG+Tavily empty; Firecrawl fallback returned %d for '%.60s'",
                    len(results), query)
        return results
    return []


async def _tavily_search(query: str) -> list[dict]:
    """Tavily search. Returns [] if no key or on any failure."""
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return []
    try:
        session = await get_session()
        payload = {"api_key": key, "query": query, "max_results": 5}
        async with session.post(
            "https://api.tavily.com/search",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=_FALLBACK_TIMEOUT),
        ) as resp:
            if resp.status != 200:
                log.warning("Tavily returned %d for '%.60s'", resp.status, query)
                return []
            data = await resp.json()
    except Exception as e:
        log.warning("Tavily error: %s", e)
        return []

    out: list[dict] = []
    for r in data.get("results", []):
        out.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
        })
    return out


async def _firecrawl_search(query: str) -> list[dict]:
    """Firecrawl search. Returns [] if no key or on any failure."""
    key = os.environ.get("FIRECRAWL_API_KEY")
    if not key:
        return []
    try:
        session = await get_session()
        headers = {"Authorization": f"Bearer {key}"}
        payload = {"query": query, "limit": 5}
        async with session.post(
            "https://api.firecrawl.dev/v1/search",
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=_FALLBACK_TIMEOUT),
        ) as resp:
            if resp.status != 200:
                log.warning("Firecrawl returned %d for '%.60s'", resp.status, query)
                return []
            data = await resp.json()
    except Exception as e:
        log.warning("Firecrawl error: %s", e)
        return []

    out: list[dict] = []
    for r in data.get("data", []):
        out.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("description") or r.get("markdown") or "",
        })
    return out
