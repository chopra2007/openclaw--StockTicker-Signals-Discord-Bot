"""News Cascade — 4-tier news source for catalyst detection.

Tiers (tried in order, stops on first catalyst found):
  1. Finnhub /company-news
  2. Google News RSS
  3. Brave Search
  4. SearXNG (self-hosted)
"""

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.models import CatalystResult, TickerSignal, SourceType, Sentiment
from consensus_engine.utils.rate_limiter import rate_limiter
from consensus_engine.scanners.searxng import search_searxng

log = logging.getLogger("consensus_engine.scanner.news")

_CATALYST_PATTERNS = [
    (["short squeeze", "squeeze", "short interest"], "Short Squeeze"),
    (["acquisition", "merger", "acquire", "buyout", "m&a"], "M&A"),
    (["upgrade", "price target raised", "outperform"], "Analyst Upgrade"),
    (["downgrade", "price target cut", "underperform"], "Analyst Downgrade"),
    (["earnings beat", "beat estimates", "revenue beat", "eps beat"], "Earnings Beat"),
    (["earnings miss", "missed estimates", "revenue miss", "eps miss"], "Earnings Miss"),
    (["fda approv", "fda clear", "drug approv"], "FDA Approval"),
    (["fda reject", "fda deny", "clinical fail"], "FDA Rejection"),
    (["government contract", "defense contract", "military contract"], "Government Contract"),
    (["partnership", "collaboration", "joint venture", "deal with"], "Partnership"),
    (["ipo", "public offering", "going public"], "IPO"),
    (["stock split", "reverse split"], "Stock Split"),
    (["dividend", "special dividend", "dividend increase"], "Dividend"),
    (["insider buy", "insider purchas"], "Insider Buying"),
    (["insider sell", "insider sold"], "Insider Selling"),
    (["sec filing", "13f", "13d", "sec investigat"], "SEC Filing"),
    (["patent", "intellectual property"], "Patent"),
    (["product launch", "new product", "announced", "unveil"], "Product Launch"),
    (["revenue guidance", "raised guidance", "lowered guidance"], "Guidance Update"),
    (["breaking", "just announced", "just reported"], "Breaking News"),
]


def _classify_catalyst(text: str) -> Optional[str]:
    """Classify catalyst type from text."""
    lower = text.lower()
    for patterns, label in _CATALYST_PATTERNS:
        if any(p in lower for p in patterns):
            return label
    return None


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    parts = url.split("/")
    return parts[2] if len(parts) > 2 else "unknown"


def _is_trusted_source(url: str) -> bool:
    """Check if URL is from a trusted news source."""
    trusted = cfg.get("news.trusted_sources", [])
    url_lower = url.lower()
    return any(source in url_lower for source in trusted)


async def _get_search_query(ticker: str) -> str:
    """Build a better search query using company name if available."""
    meta = await db.get_ticker_metadata(ticker, max_age_days=30)
    if meta and meta.get("name"):
        return f'"{meta["name"]}" OR "${ticker}" stock'
    return f"${ticker} stock"


def _headline_relevant(headline: str, ticker: str, company_name: str = "") -> bool:
    """Check if a headline actually mentions the ticker or company."""
    upper = headline.upper()
    if ticker in upper:
        return True
    if company_name and company_name.lower() in headline.lower():
        return True
    return False


async def _get_company_name(ticker: str) -> str:
    """Get cached company name for relevance checking."""
    meta = await db.get_ticker_metadata(ticker, max_age_days=30)
    if meta and meta.get("name"):
        return meta["name"]
    return ""


def _build_catalyst(ticker: str, title: str, url: str, catalyst_type: str) -> CatalystResult:
    """Build a CatalystResult from a single news hit."""
    return CatalystResult(
        ticker=ticker,
        catalyst_summary=title[:200],
        catalyst_type=catalyst_type,
        news_sources=[_extract_domain(url)],
        source_urls=[url],
        confidence=0.8 if catalyst_type != "Market Movement" else 0.5,
    )


async def _search_finnhub_news(ticker: str) -> Optional[CatalystResult]:
    """Search Finnhub company news endpoint."""
    api_key = cfg.get_api_key("finnhub")
    if not api_key:
        return None
    if not await rate_limiter.acquire("finnhub_news"):
        return None

    days_back = cfg.get("news_cascade.finnhub_news_days_back", 2)
    from datetime import datetime, timedelta
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    try:
        async with aiohttp.ClientSession() as session:
            url = "https://finnhub.io/api/v1/company-news"
            params = {"symbol": ticker, "from": from_date, "to": to_date, "token": api_key}
            async with session.get(url, params=params,
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    rate_limiter.report_failure("finnhub_news")
                    return None
                articles = await resp.json()
                rate_limiter.report_success("finnhub_news")

        if not isinstance(articles, list):
            return None

        for article in articles[:10]:
            headline = article.get("headline", "")
            source = article.get("source", "")
            article_url = article.get("url", "")
            full_text = f"{headline} {source}"
            catalyst_type = _classify_catalyst(full_text)

            if catalyst_type and _is_trusted_source(article_url):
                log.info("Finnhub news catalyst for %s: %s (%s)", ticker, catalyst_type, source)
                return _build_catalyst(ticker, headline, article_url, catalyst_type)

        return None
    except Exception as e:
        log.warning("Finnhub news error for %s: %s", ticker, e)
        rate_limiter.report_failure("finnhub_news")
        return None


async def _search_google_news_rss(ticker: str) -> Optional[CatalystResult]:
    """Search Google News via RSS feed (free, no auth)."""
    if not await rate_limiter.acquire("google_news_rss"):
        return None

    search_query = await _get_search_query(ticker)
    company_name = await _get_company_name(ticker)
    query = search_query.replace('"', '').replace(' ', '+')
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                rss_url,
                timeout=aiohttp.ClientTimeout(total=10),
                headers={"User-Agent": "Mozilla/5.0"},
            ) as resp:
                if resp.status != 200:
                    rate_limiter.report_failure("google_news_rss")
                    return None
                xml_text = await resp.text()
                rate_limiter.report_success("google_news_rss")

        root = ET.fromstring(xml_text)
        for item in root.iter("item"):
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            source_el = item.find("source")
            source_name = source_el.text if source_el is not None else ""

            if not _headline_relevant(title, ticker, company_name):
                continue

            catalyst_type = _classify_catalyst(title)
            is_trusted = _is_trusted_source(link) or any(
                s.lower() in source_name.lower()
                for s in cfg.get("news.trusted_sources", [])
            )

            if catalyst_type and is_trusted:
                log.info("Google RSS catalyst for %s: %s (%s)", ticker, catalyst_type, source_name)
                return _build_catalyst(ticker, title, link, catalyst_type)

        return None
    except Exception as e:
        log.warning("Google News RSS error for %s: %s", ticker, e)
        rate_limiter.report_failure("google_news_rss")
        return None


async def _search_brave(ticker: str) -> Optional[CatalystResult]:
    """Search Brave for news (quota-limited, tier 3)."""
    api_key = cfg.get_api_key("brave_search")
    if not api_key:
        return None
    if not await rate_limiter.acquire("brave_search"):
        return None

    search_query = await _get_search_query(ticker)
    company_name = await _get_company_name(ticker)

    try:
        async with aiohttp.ClientSession() as session:
            url = "https://api.search.brave.com/res/v1/web/search"
            headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
            params = {
                "q": f"{search_query} news today",
                "count": cfg.get("news.max_search_results", 10),
                "freshness": "pd",
            }
            async with session.get(url, headers=headers, params=params,
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    rate_limiter.report_failure("brave_search")
                    return None
                data = await resp.json()
                rate_limiter.report_success("brave_search")

        for r in data.get("web", {}).get("results", []):
            title = r.get("title", "")
            result_url = r.get("url", "")
            description = r.get("description", "")
            full_text = f"{title} {description}"

            if not _headline_relevant(full_text, ticker, company_name):
                continue

            catalyst_type = _classify_catalyst(full_text)

            if catalyst_type and _is_trusted_source(result_url):
                log.info("Brave catalyst for %s: %s", ticker, catalyst_type)
                return _build_catalyst(ticker, title, result_url, catalyst_type)

        return None
    except Exception as e:
        log.warning("Brave search error for %s: %s", ticker, e)
        rate_limiter.report_failure("brave_search")
        return None


async def _search_searxng(ticker: str) -> Optional[CatalystResult]:
    """Search SearXNG for news (self-hosted, unlimited)."""
    search_query = await _get_search_query(ticker)
    company_name = await _get_company_name(ticker)
    results = await search_searxng(f"{search_query} news")
    for r in results:
        title = r.get("title", "")
        url = r.get("url", "")
        content = r.get("content", "")
        full_text = f"{title} {content}"

        if not _headline_relevant(full_text, ticker, company_name):
            continue

        catalyst_type = _classify_catalyst(full_text)

        if catalyst_type and _is_trusted_source(url):
            log.info("SearXNG catalyst for %s: %s", ticker, catalyst_type)
            return _build_catalyst(ticker, title, url, catalyst_type)

    return None


async def news_cascade(ticker: str) -> Optional[CatalystResult]:
    """Run the 4-tier news cascade. Stops at first catalyst found.

    Order: Finnhub -> Google RSS -> Brave -> SearXNG
    """
    tiers = cfg.get("news_cascade.tiers", ["finnhub", "google_rss", "brave", "searxng"])

    tier_funcs = {
        "finnhub": _search_finnhub_news,
        "google_rss": _search_google_news_rss,
        "brave": _search_brave,
        "searxng": _search_searxng,
    }

    for tier_name in tiers:
        func = tier_funcs.get(tier_name)
        if not func:
            continue
        result = await func(ticker)
        if result and result.passed:
            log.info("News cascade hit at tier '%s' for %s", tier_name, ticker)
            return result

    log.debug("News cascade: no catalyst found for %s across all tiers", ticker)
    return None
