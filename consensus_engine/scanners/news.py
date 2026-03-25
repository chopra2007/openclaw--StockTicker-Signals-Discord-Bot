"""Stage 3 — News & Catalyst Finder.

Uses Brave Search API and Playwright scraping to find breaking news
and identify the catalyst behind a stock's movement.
"""

import asyncio
import logging
import time
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.models import (
    TickerSignal, SourceType, Sentiment, CatalystResult,
)
from consensus_engine.utils.tickers import extract_tickers
from consensus_engine.utils.rate_limiter import rate_limiter

log = logging.getLogger("consensus_engine.scanner.news")

# Catalyst classification patterns
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
    """Classify the catalyst type from article text."""
    lower = text.lower()
    for patterns, label in _CATALYST_PATTERNS:
        if any(p in lower for p in patterns):
            return label
    return None


def _is_trusted_source(url: str) -> bool:
    """Check if a URL is from a trusted news source."""
    trusted = cfg.get("news.trusted_sources", [])
    url_lower = url.lower()
    return any(source in url_lower for source in trusted)


async def search_brave(ticker: str) -> list[dict]:
    """Search for news about a ticker using Brave Search API."""
    api_key = cfg.get_api_key("brave_search")
    if not api_key:
        log.warning("Brave Search API key not configured")
        return []

    if not await rate_limiter.acquire("brave_search"):
        return []

    results = []
    queries = [
        f"{ticker} stock news today",
        f"${ticker} breaking news catalyst",
    ]

    async with aiohttp.ClientSession() as session:
        for query in queries:
            try:
                url = "https://api.search.brave.com/res/v1/web/search"
                headers = {
                    "Accept": "application/json",
                    "X-Subscription-Token": api_key,
                }
                params = {
                    "q": query,
                    "count": cfg.get("news.max_search_results", 10),
                    "freshness": "pd",  # Past day
                }

                async with session.get(url, headers=headers, params=params,
                                       timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        rate_limiter.report_failure("brave_search")
                        continue

                    data = await resp.json()
                    web_results = data.get("web", {}).get("results", [])

                    for r in web_results:
                        title = r.get("title", "")
                        result_url = r.get("url", "")
                        description = r.get("description", "")
                        full_text = f"{title} {description}"
                        catalyst_type = _classify_catalyst(full_text)

                        results.append({
                            "title": title[:200],
                            "url": result_url,
                            "description": description[:500],
                            "catalyst_type": catalyst_type,
                            "is_trusted": _is_trusted_source(result_url),
                        })

                rate_limiter.report_success("brave_search")
                await asyncio.sleep(0.5)

            except Exception as e:
                log.warning("Brave search error for '%s': %s", query, e)
                rate_limiter.report_failure("brave_search")

    return results


async def scan_news_for_tickers(tickers: list[str]) -> list[TickerSignal]:
    """Search for news on a list of candidate tickers.

    Only called for tickers that already have Twitter/social signals.
    """
    if not tickers:
        return []

    log.info("Searching news for %d tickers: %s", len(tickers), ", ".join(tickers))
    start = time.time()
    signals = []

    for ticker in tickers:
        results = await search_brave(ticker)

        for r in results:
            if r["is_trusted"] or r["catalyst_type"]:
                sentiment = Sentiment.NEUTRAL
                if r["catalyst_type"] in ("Earnings Beat", "Analyst Upgrade", "FDA Approval",
                                          "Government Contract", "Partnership", "Insider Buying",
                                          "Product Launch"):
                    sentiment = Sentiment.BULLISH
                elif r["catalyst_type"] in ("Earnings Miss", "Analyst Downgrade", "FDA Rejection",
                                            "Insider Selling"):
                    sentiment = Sentiment.BEARISH

                signals.append(TickerSignal(
                    ticker=ticker,
                    source_type=SourceType.NEWS,
                    source_detail=r["url"],
                    raw_text=f"{r['title']} — {r['description']}"[:500],
                    sentiment=sentiment,
                    detected_at=time.time(),
                ))

        await asyncio.sleep(0.5)

    elapsed = time.time() - start
    log.info("News scan complete: %d signals for %d tickers in %.1fs",
             len(signals), len(tickers), elapsed)
    await db.record_metric("news_scan_seconds", elapsed)
    return signals


async def evaluate_catalyst(ticker: str) -> Optional[CatalystResult]:
    """Evaluate whether a credible catalyst exists for a ticker."""
    rows = await db.get_news_signals(ticker)
    if not rows:
        # Try a fresh search
        search_results = await search_brave(ticker)
        trusted_with_catalyst = [
            r for r in search_results
            if r["is_trusted"] and r["catalyst_type"]
        ]
        trusted_any = [r for r in search_results if r["is_trusted"]]
        fallback = trusted_with_catalyst or trusted_any

        if not fallback:
            log.debug("Catalyst: No trusted news found for %s", ticker)
            return None

        best = fallback[0]
        return CatalystResult(
            ticker=ticker,
            catalyst_summary=best["title"],
            catalyst_type=best.get("catalyst_type") or "Market Movement",
            news_sources=[best["url"].split("/")[2] if "/" in best["url"] else "unknown"],
            source_urls=[best["url"]],
            confidence=0.8 if best.get("catalyst_type") else 0.5,
        )

    # Build catalyst from stored signals
    best_catalyst_type = "Market Movement"
    sources = []
    urls = []
    best_text = ""

    for row in rows:
        url = row["source_detail"]
        text = row["raw_text"]
        catalyst_type = _classify_catalyst(text)

        if _is_trusted_source(url):
            domain = url.split("/")[2] if "/" in url else "unknown"
            if domain not in sources:
                sources.append(domain)
            if url not in urls:
                urls.append(url)
            if catalyst_type and best_catalyst_type == "Market Movement":
                best_catalyst_type = catalyst_type
                best_text = text

    if not sources:
        return None

    if not best_text and rows:
        best_text = rows[0]["raw_text"]

    result = CatalystResult(
        ticker=ticker,
        catalyst_summary=best_text[:200],
        catalyst_type=best_catalyst_type,
        news_sources=sources[:5],
        source_urls=urls[:5],
        confidence=0.8 if best_catalyst_type != "Market Movement" else 0.5,
    )

    if result.passed:
        log.info("Catalyst FOUND for %s: %s (%s)", ticker, best_catalyst_type, ", ".join(sources[:3]))
    return result
