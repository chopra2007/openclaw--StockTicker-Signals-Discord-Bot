"""HTTP adapter implementations for the precision scoring engine.

Each adapter accepts a shared aiohttp.ClientSession (from utils/http.py)
instead of creating its own, to reuse connection pools.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.adapter_protocols import (
    FinnhubContext,
    FirecrawlPage,
    SearchHit,
)

log = logging.getLogger("consensus_engine.api_adapters")

_TIMEOUT = aiohttp.ClientTimeout(total=10)


# ---------------------------------------------------------------------------
# Finnhub Adapter  (consumes 2 API calls: /quote + /company-news)
# ---------------------------------------------------------------------------

class FinnhubAdapter:
    def __init__(self, session: aiohttp.ClientSession, api_key: str = ""):
        self._session = session
        self._api_key = api_key or cfg.get_api_key("finnhub")

    async def get_context(self, ticker: str) -> FinnhubContext:
        if not self._api_key:
            return FinnhubContext()

        quote_task = self._fetch_quote(ticker)
        news_task = self._fetch_news(ticker)
        quote, news = await asyncio.gather(quote_task, news_task, return_exceptions=True)

        ctx = FinnhubContext()
        if isinstance(quote, dict):
            ctx.price = float(quote.get("c") or 0)
            ctx.prev_close = float(quote.get("pc") or 0)
            ctx.volume = int(quote.get("v") or 0)
            if ctx.prev_close > 0:
                ctx.change_pct = ((ctx.price - ctx.prev_close) / ctx.prev_close) * 100
            ctx.market_ok = abs(ctx.change_pct) >= 0.5

        if isinstance(news, list):
            for article in news[:10]:
                ctx.news_headlines.append(article.get("headline", ""))
                ctx.news_sources.append(article.get("source", ""))

        return ctx

    async def _fetch_quote(self, ticker: str) -> Optional[dict]:
        try:
            async with self._session.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": ticker, "token": self._api_key},
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
        except Exception as e:
            log.debug("Finnhub quote failed for %s: %s", ticker, e)
            return None

    async def _fetch_news(self, ticker: str) -> Optional[list]:
        now = datetime.now(timezone.utc)
        date_from = (now - timedelta(days=2)).strftime("%Y-%m-%d")
        date_to = now.strftime("%Y-%m-%d")
        try:
            async with self._session.get(
                "https://finnhub.io/api/v1/company-news",
                params={
                    "symbol": ticker,
                    "from": date_from,
                    "to": date_to,
                    "token": self._api_key,
                },
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
        except Exception as e:
            log.debug("Finnhub news failed for %s: %s", ticker, e)
            return None


# ---------------------------------------------------------------------------
# Brave Search Adapter
# ---------------------------------------------------------------------------

class BraveAdapter:
    def __init__(self, session: aiohttp.ClientSession, api_key: str = ""):
        self._session = session
        self._api_key = api_key or cfg.get_api_key("brave_search")

    async def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        if not self._api_key:
            return []
        try:
            async with self._session.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"X-Subscription-Token": self._api_key, "Accept": "application/json"},
                params={"q": query, "count": max_results, "freshness": "pd"},
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status != 200:
                    log.debug("Brave search %d for %s", resp.status, query)
                    return []
                data = await resp.json()

            hits = []
            for r in (data.get("web", {}).get("results") or [])[:max_results]:
                hits.append(SearchHit(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    source=r.get("meta_url", {}).get("hostname", ""),
                    snippet=r.get("description", ""),
                ))
            return hits
        except Exception as e:
            log.debug("Brave search error: %s", e)
            return []


# ---------------------------------------------------------------------------
# Exa AI Adapter
# ---------------------------------------------------------------------------

class ExaAdapter:
    def __init__(self, session: aiohttp.ClientSession, api_key: str = ""):
        self._session = session
        self._api_key = api_key or cfg.get("precision_engine.api_keys.exa", "") or cfg.get_api_key("exa")

    async def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        if not self._api_key:
            return []
        try:
            async with self._session.post(
                "https://api.exa.ai/search",
                headers={"x-api-key": self._api_key, "Content-Type": "application/json"},
                json={
                    "query": query,
                    "numResults": max_results,
                    "useAutoprompt": True,
                    "type": "neural",
                },
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status != 200:
                    log.debug("Exa search %d for %s", resp.status, query)
                    return []
                data = await resp.json()

            hits = []
            for r in (data.get("results") or [])[:max_results]:
                url = r.get("url", "")
                domain = url.split("/")[2] if url.count("/") >= 2 else ""
                hits.append(SearchHit(
                    title=r.get("title", ""),
                    url=url,
                    source=domain,
                    snippet=r.get("text", "")[:300],
                ))
            return hits
        except Exception as e:
            log.debug("Exa search error: %s", e)
            return []


# ---------------------------------------------------------------------------
# SerpApi Adapter
# ---------------------------------------------------------------------------

class SerpApiAdapter:
    def __init__(self, session: aiohttp.ClientSession, api_key: str = ""):
        self._session = session
        self._api_key = api_key or cfg.get("precision_engine.api_keys.serpapi", "") or cfg.get_api_key("serpapi")

    async def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        if not self._api_key:
            return []
        try:
            async with self._session.get(
                "https://serpapi.com/search.json",
                params={
                    "q": query,
                    "api_key": self._api_key,
                    "engine": "google",
                    "num": max_results,
                    "tbm": "nws",
                },
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status != 200:
                    log.debug("SerpApi %d for %s", resp.status, query)
                    return []
                data = await resp.json()

            hits = []
            for r in (data.get("news_results") or [])[:max_results]:
                hits.append(SearchHit(
                    title=r.get("title", ""),
                    url=r.get("link", ""),
                    source=r.get("source", ""),
                    snippet=r.get("snippet", ""),
                ))
            return hits
        except Exception as e:
            log.debug("SerpApi error: %s", e)
            return []


# ---------------------------------------------------------------------------
# Firecrawl Adapter
# ---------------------------------------------------------------------------

class FirecrawlAdapter:
    def __init__(self, session: aiohttp.ClientSession, api_key: str = ""):
        self._session = session
        self._api_key = api_key or cfg.get("precision_engine.api_keys.firecrawl", "") or cfg.get_api_key("firecrawl")

    async def extract(self, urls: list[str]) -> list[FirecrawlPage]:
        if not self._api_key or not urls:
            return []

        tasks = [self._scrape_one(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        pages = []
        for r in results:
            if isinstance(r, FirecrawlPage):
                pages.append(r)
            elif isinstance(r, Exception):
                log.debug("Firecrawl error: %s", r)
        return pages

    async def _scrape_one(self, url: str) -> FirecrawlPage:
        try:
            async with self._session.post(
                "https://api.firecrawl.dev/v1/scrape",
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json={"url": url, "formats": ["markdown"]},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    return FirecrawlPage(url=url)
                data = await resp.json()

            fc_data = data.get("data", {})
            return FirecrawlPage(
                url=url,
                title=fc_data.get("metadata", {}).get("title", ""),
                text=(fc_data.get("markdown") or "")[:5000],
                success=data.get("success", False),
            )
        except Exception as e:
            log.debug("Firecrawl scrape failed for %s: %s", url, e)
            return FirecrawlPage(url=url)
