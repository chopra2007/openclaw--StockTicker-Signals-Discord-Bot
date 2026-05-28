#!/usr/bin/env python3
"""SearXNG-shaped search proxy for the agent path (@mention / !ask web_search).

Listens on 127.0.0.1:8899 and answers GET /search?q=...&format=json with a
SearXNG-shaped body: {"results": [{"title", "url", "content", "engine"}]}.

Priority: real SearXNG (localhost:8888) first; if it returns nothing, fall
back to Tavily, then Firecrawl. Returns {"results": []} with HTTP 200 if
everything misses, so the caller never sees an error status.

Run: python3 scripts/searxng_proxy.py   (reads optional PORT env, default 8899)
Keys are read from os.environ (the systemd unit sources .env).
"""

import logging
import os

import aiohttp
from aiohttp import web

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("searxng_proxy")

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8888")
SEARXNG_TIMEOUT = 4
FALLBACK_TIMEOUT = 6


async def _searxng(session: aiohttp.ClientSession, query: str) -> list[dict]:
    try:
        params = {"q": query, "format": "json"}
        async with session.get(
            f"{SEARXNG_URL}/search",
            params=params,
            timeout=aiohttp.ClientTimeout(total=SEARXNG_TIMEOUT),
        ) as resp:
            if resp.status != 200:
                log.warning("SearXNG returned %d for '%.60s'", resp.status, query)
                return []
            data = await resp.json()
    except Exception as e:
        log.warning("SearXNG error: %s", e)
        return []

    out = []
    for r in data.get("results", []):
        out.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
            "engine": "searxng",
        })
    return out


async def _tavily(session: aiohttp.ClientSession, query: str) -> list[dict]:
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return []
    try:
        payload = {"api_key": key, "query": query, "max_results": 5}
        async with session.post(
            "https://api.tavily.com/search",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=FALLBACK_TIMEOUT),
        ) as resp:
            if resp.status != 200:
                log.warning("Tavily returned %d for '%.60s'", resp.status, query)
                return []
            data = await resp.json()
    except Exception as e:
        log.warning("Tavily error: %s", e)
        return []

    out = []
    for r in data.get("results", []):
        out.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
            "engine": "tavily",
        })
    return out


async def _firecrawl(session: aiohttp.ClientSession, query: str) -> list[dict]:
    key = os.environ.get("FIRECRAWL_API_KEY")
    if not key:
        return []
    try:
        headers = {"Authorization": f"Bearer {key}"}
        payload = {"query": query, "limit": 5}
        async with session.post(
            "https://api.firecrawl.dev/v1/search",
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=FALLBACK_TIMEOUT),
        ) as resp:
            if resp.status != 200:
                log.warning("Firecrawl returned %d for '%.60s'", resp.status, query)
                return []
            data = await resp.json()
    except Exception as e:
        log.warning("Firecrawl error: %s", e)
        return []

    out = []
    for r in data.get("data", []):
        out.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("description") or r.get("markdown") or "",
            "engine": "firecrawl",
        })
    return out


async def handle_search(request: web.Request) -> web.Response:
    query = request.query.get("q", "")
    if not query:
        return web.json_response({"results": []})

    session: aiohttp.ClientSession = request.app["session"]

    results = await _searxng(session, query)
    if results:
        return web.json_response({"results": results})

    results = await _tavily(session, query)
    if results:
        log.warning("SearXNG empty; Tavily served '%.60s' (%d results)",
                    query, len(results))
        return web.json_response({"results": results})

    results = await _firecrawl(session, query)
    if results:
        log.warning("SearXNG+Tavily empty; Firecrawl served '%.60s' (%d results)",
                    query, len(results))
        return web.json_response({"results": results})

    log.warning("All providers empty for '%.60s'", query)
    return web.json_response({"results": []})


async def handle_healthz(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def _on_startup(app: web.Application) -> None:
    app["session"] = aiohttp.ClientSession()


async def _on_cleanup(app: web.Application) -> None:
    await app["session"].close()


def main() -> None:
    port = int(os.environ.get("PORT", "8899"))
    app = web.Application()
    app.router.add_get("/search", handle_search)
    app.router.add_get("/healthz", handle_healthz)
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    web.run_app(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
