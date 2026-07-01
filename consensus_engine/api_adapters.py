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
from consensus_engine.utils.http import get_session
from consensus_engine.utils.rate_limiter import rate_limiter
from consensus_engine.adapter_protocols import (
    FinnhubContext,
    FirecrawlPage,
    SearchHit,
)

log = logging.getLogger("consensus_engine.api_adapters")

_TIMEOUT = aiohttp.ClientTimeout(total=10)

# C14: the precision-engine adapters share source names with the polling tiers
# ("finnhub", "finnhub_news", "brave_search", "exa", ...). They never reported
# failures, so a dead source was retried every call and the error stayed at
# debug. Feed the SHARED rate_limiter so a failing source actually backs off,
# and surface a repeat at WARNING. Flag-gated (adapters.report_failure, default
# OFF) — it changes WHEN those sources back off, so it ships dark.
_adapter_fail_counts: dict[str, int] = {}


def _report_adapter_failure(source: str, detail: str = "") -> None:
    if not cfg.get("adapters.report_failure", False):
        return
    rate_limiter.report_failure(source)
    _adapter_fail_counts[source] = _adapter_fail_counts.get(source, 0) + 1
    if _adapter_fail_counts[source] >= 2:
        log.warning("adapter source '%s' repeated failure (%dx): %s",
                    source, _adapter_fail_counts[source], detail)


def _report_adapter_success(source: str) -> None:
    if not cfg.get("adapters.report_failure", False):
        return
    rate_limiter.report_success(source)
    _adapter_fail_counts.pop(source, None)


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
                    _report_adapter_failure("finnhub", f"quote HTTP {resp.status}")
                    return None
                _report_adapter_success("finnhub")
                return await resp.json()
        except Exception as e:
            log.debug("Finnhub quote failed for %s: %s", ticker, e)
            _report_adapter_failure("finnhub", f"quote {e}")
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
                    _report_adapter_failure("finnhub_news", f"news HTTP {resp.status}")
                    return None
                _report_adapter_success("finnhub_news")
                return await resp.json()
        except Exception as e:
            log.debug("Finnhub news failed for %s: %s", ticker, e)
            _report_adapter_failure("finnhub_news", f"news {e}")
            return None


# ---------------------------------------------------------------------------
# Brave Search Adapter
# ---------------------------------------------------------------------------

# Round-robin pointer shared across BraveAdapter instances so that, over many
# calls, traffic is spread evenly across every configured Brave subscription
# token (lets monthly free-tier quota be split across keys).
_brave_rotation_idx = 0


def _collect_brave_keys() -> list[str]:
    """Every configured non-empty Brave key, in slot order, de-duplicated."""
    keys: list[str] = []
    for slot in ("brave_search", "brave_search_2"):
        k = cfg.get_api_key(slot)
        if k and k not in keys:
            keys.append(k)
    return keys


class BraveAdapter:
    def __init__(self, session: aiohttp.ClientSession, api_key: str = ""):
        self._session = session
        # Explicit key (used by tests/callers) wins; otherwise rotate all keys.
        self._keys = [api_key] if api_key else _collect_brave_keys()

    async def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        if not self._keys:
            return []
        global _brave_rotation_idx
        n = len(self._keys)
        start = _brave_rotation_idx % n
        _brave_rotation_idx += 1
        # Try the round-robin key first, then fail over to the rest on
        # error/quota so a single benched key doesn't drop the query.
        for offset in range(n):
            api_key = self._keys[(start + offset) % n]
            try:
                async with self._session.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
                    params={"q": query, "count": max_results, "freshness": "pd"},
                    timeout=_TIMEOUT,
                ) as resp:
                    if resp.status != 200:
                        log.debug("Brave search %d for %s (key %d/%d)", resp.status, query, start + offset + 1, n)
                        continue
                    data = await resp.json()
            except Exception as e:
                log.debug("Brave search error: %s", e)
                continue

            hits = []
            for r in (data.get("web", {}).get("results") or [])[:max_results]:
                hits.append(SearchHit(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    source=r.get("meta_url", {}).get("hostname", ""),
                    snippet=r.get("description", ""),
                ))
            _report_adapter_success("brave_search")
            return hits
        _report_adapter_failure("brave_search", "all keys failed")  # C14
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
                    _report_adapter_failure("exa", f"HTTP {resp.status}")
                    return []
                data = await resp.json()
                _report_adapter_success("exa")

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
            _report_adapter_failure("exa", str(e))
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
                    _report_adapter_failure("serpapi", f"HTTP {resp.status}")
                    return []
                data = await resp.json()
                _report_adapter_success("serpapi")

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
            _report_adapter_failure("serpapi", str(e))
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
                    _report_adapter_failure("firecrawl", f"HTTP {resp.status}")
                    return FirecrawlPage(url=url)
                data = await resp.json()
                _report_adapter_success("firecrawl")

            fc_data = data.get("data", {})
            return FirecrawlPage(
                url=url,
                title=fc_data.get("metadata", {}).get("title", ""),
                text=(fc_data.get("markdown") or "")[:5000],
                success=data.get("success", False),
            )
        except Exception as e:
            log.debug("Firecrawl scrape failed for %s: %s", url, e)
            _report_adapter_failure("firecrawl", str(e))
            return FirecrawlPage(url=url)


# ---------------------------------------------------------------------------
# Standalone quote accessors (used by price_sanity at alert time, and TODO #57
# Schwab-primary quotes). Schwab real-time feed first (flag-gated), Finnhub
# free-tier fallback so the bot never goes dark.
# ---------------------------------------------------------------------------

async def _fetch_finnhub_quote_dict(ticker: str) -> Optional[dict]:
    """The pre-existing Finnhub quote path, factored out for reuse as the
    fallback behind Schwab. Uses the shared aiohttp session/adapter pool."""
    api_key = cfg.get_api_key("finnhub")
    if not api_key:
        return None
    try:
        session = await get_session()
        adapter = FinnhubAdapter(session, api_key)
        return await adapter._fetch_quote(ticker)
    except Exception as e:
        log.debug("_fetch_finnhub_quote_dict: failed for %s: %s", ticker, e)
        return None


async def get_quote(symbol: str) -> Optional[dict]:
    """Current quote for `symbol`: {c,pc,dp,o,h,l,v,t}, or None on any error.

    Schwab real-time feed is tried first when features.schwab_quotes.enabled
    (default OFF); any Schwab failure/empty result falls through to the
    existing Finnhub path.
    """
    if cfg.get("features.schwab_quotes.enabled", False):
        try:
            from consensus_engine.scanners import schwab_client
            q = await asyncio.to_thread(schwab_client.get_quote, symbol)
            if q and q.get("c"):
                return q
        except Exception as e:
            log.debug("get_quote: schwab failed for %s, falling back to Finnhub: %s", symbol, e)
    return await _fetch_finnhub_quote_dict(symbol)


async def get_quotes(symbols: list[str]) -> dict[str, dict]:
    """Batch quotes for `symbols`. Schwab primary (flag-gated), per-symbol
    Finnhub fallback for any symbol Schwab didn't cover."""
    if not symbols:
        return {}
    out: dict[str, dict] = {}
    missing = list(symbols)
    if cfg.get("features.schwab_quotes.enabled", False):
        try:
            from consensus_engine.scanners import schwab_client
            batch = await asyncio.to_thread(schwab_client.get_quotes, symbols)
            for sym, q in (batch or {}).items():
                if q and q.get("c"):
                    out[sym] = q
            missing = [s for s in symbols if s not in out]
        except Exception as e:
            log.debug("get_quotes: schwab batch failed, falling back to Finnhub: %s", e)
    if missing:
        results = await asyncio.gather(
            *[_fetch_finnhub_quote_dict(s) for s in missing], return_exceptions=True
        )
        for sym, r in zip(missing, results):
            if isinstance(r, dict):
                out[sym] = r
    return out


async def get_live_quote_price(ticker: str) -> float | None:
    """Return current price (Schwab-primary, Finnhub-fallback), or None on
    any error, so callers can fail-open."""
    try:
        q = await get_quote(ticker)
        if not q:
            return None
        price = float(q.get("c") or 0)
        return price if price > 0 else None
    except Exception as e:
        log.debug("get_live_quote_price: failed for %s: %s", ticker, e)
        return None
