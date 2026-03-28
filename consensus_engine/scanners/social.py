"""Social & Sentiment Scanner.

Scanners for cross-reference scoring:
  - Reddit: Public JSON API (no browser needed)
  - StockTwits: Playwright stealth (API blocked by Cloudflare)
  - ApeWisdom: Direct REST API (free)
  - Google Trends: SerpAPI
"""

import asyncio
import logging
import time
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.models import (
    TickerSignal, SourceType, Sentiment,
)
from consensus_engine.utils.tickers import extract_tickers
from consensus_engine.utils.browser import (
    create_stealth_browser, stealth_page, safe_goto, random_delay,
)
from consensus_engine.utils.rate_limiter import rate_limiter

log = logging.getLogger("consensus_engine.scanner.social")


# ---------------------------------------------------------------------------
# Reddit (public RSS feeds — no Playwright, no auth needed)
# ---------------------------------------------------------------------------

async def scan_reddit() -> list[TickerSignal]:
    """Fetch subreddit posts via Reddit's public RSS feeds."""
    subreddits = cfg.get("social.subreddits", [])
    if not subreddits:
        return []

    signals = []
    headers = {
        "User-Agent": "OpenClaw/1.0 (stock trend engine)",
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        for sub in subreddits:
            if not await rate_limiter.acquire("reddit"):
                break
            sub_signals = await _fetch_subreddit_rss(session, sub)
            signals.extend(sub_signals)
            await asyncio.sleep(2)

    log.info("Reddit: %d signals from %d subreddits", len(signals), len(subreddits))
    return signals


async def _fetch_subreddit_rss(session: aiohttp.ClientSession, subreddit: str) -> list[TickerSignal]:
    """Fetch a single subreddit via Reddit's public RSS feed."""
    import xml.etree.ElementTree as ET

    url = f"https://www.reddit.com/r/{subreddit}/new/.rss"
    signals = []
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                log.warning("Reddit RSS r/%s returned %d", subreddit, resp.status)
                rate_limiter.report_failure("reddit")
                return []
            xml_text = await resp.text()

        root = ET.fromstring(xml_text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)

        for entry in entries[:25]:
            title_el = entry.find("atom:title", ns)
            content_el = entry.find("atom:content", ns)
            title = title_el.text if title_el is not None and title_el.text else ""
            content = content_el.text if content_el is not None and content_el.text else ""
            text = (title + " " + content).strip()

            tickers = extract_tickers(text)
            for ticker in tickers:
                signals.append(TickerSignal(
                    ticker=ticker,
                    source_type=SourceType.REDDIT,
                    source_detail=f"r/{subreddit}",
                    raw_text=text[:500],
                    sentiment=_quick_sentiment(text),
                    detected_at=time.time(),
                ))

        rate_limiter.report_success("reddit")
    except Exception as e:
        log.warning("Reddit RSS error for r/%s: %s", subreddit, e)
        rate_limiter.report_failure("reddit")

    return signals


# ---------------------------------------------------------------------------
# StockTwits (Playwright stealth — API blocked by Cloudflare)
# ---------------------------------------------------------------------------

async def scan_stocktwits() -> list[TickerSignal]:
    """Fetch trending symbols from StockTwits via Playwright."""
    if not cfg.get("social.stocktwits_enabled", True):
        return []
    if not await rate_limiter.acquire("stocktwits"):
        return []

    signals = []
    try:
        async with create_stealth_browser() as (browser, context):
            page = await stealth_page(context)
            try:
                # StockTwits uses Cloudflare which may return 403 initially
                # while the JS challenge resolves, so ignore response status
                try:
                    await page.goto("https://stocktwits.com/rankings/trending",
                                    wait_until="domcontentloaded")
                except Exception as nav_err:
                    log.warning("StockTwits navigation error: %s", nav_err)
                    rate_limiter.report_failure("stocktwits")
                    return []

                # Wait for symbol links to appear after Cloudflare challenge
                try:
                    await page.wait_for_selector('a[href*="/symbol/"]', timeout=20000)
                except Exception:
                    log.warning("StockTwits: symbol links did not appear (Cloudflare block?)")
                    rate_limiter.report_failure("stocktwits")
                    return []

                rows = await page.query_selector_all('a[href*="/symbol/"]')
                seen = set()
                for row in rows[:30]:
                    try:
                        href = await row.get_attribute("href") or ""
                        text = await row.inner_text()
                        ticker = ""
                        if "/symbol/" in href:
                            ticker = href.split("/symbol/")[-1].split("/")[0].split("?")[0].upper()
                        if not ticker:
                            tickers_found = extract_tickers(text)
                            if tickers_found:
                                ticker = next(iter(tickers_found))
                        if ticker and ticker not in seen:
                            seen.add(ticker)
                            signals.append(TickerSignal(
                                ticker=ticker,
                                source_type=SourceType.STOCKTWITS,
                                source_detail=f"trending #{len(seen)}",
                                raw_text=f"${ticker} trending on StockTwits",
                                sentiment=Sentiment.BULLISH,
                                detected_at=time.time(),
                            ))
                    except Exception:
                        continue
            finally:
                await page.close()

        rate_limiter.report_success("stocktwits")
        log.info("StockTwits: %d trending symbols", len(signals))

    except Exception as e:
        log.warning("StockTwits error: %s", e)
        rate_limiter.report_failure("stocktwits")

    return signals


# ---------------------------------------------------------------------------
# ApeWisdom (direct API — free)
# ---------------------------------------------------------------------------

async def scan_apewisdom() -> list[TickerSignal]:
    """Fetch trending tickers from ApeWisdom API."""
    if not cfg.get("social.apewisdom_enabled", True):
        return []
    if not await rate_limiter.acquire("apewisdom"):
        return []

    signals = []
    try:
        async with aiohttp.ClientSession() as session:
            for page_num in range(1, 3):
                url = f"https://apewisdom.io/api/v1.0/filter/all-stocks/page/{page_num}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()

                results = data.get("results", [])
                for idx, item in enumerate(results):
                    ticker = item.get("ticker", "")
                    mentions = item.get("mentions", 0)
                    rank = item.get("rank", idx + 1)
                    if not ticker:
                        continue
                    signals.append(TickerSignal(
                        ticker=ticker,
                        source_type=SourceType.APEWISDOM,
                        source_detail=f"rank #{rank} ({mentions} mentions)",
                        raw_text=f"${ticker} trending on ApeWisdom with {mentions} mentions",
                        sentiment=Sentiment.NEUTRAL,
                        detected_at=time.time(),
                    ))
                await asyncio.sleep(1)

        rate_limiter.report_success("apewisdom")
        log.info("ApeWisdom: %d trending tickers", len(signals))

    except Exception as e:
        log.warning("ApeWisdom error: %s", e)
        rate_limiter.report_failure("apewisdom")

    return signals


# ---------------------------------------------------------------------------
# Google Trends (SerpAPI)
# ---------------------------------------------------------------------------

async def scan_google_trends(tickers: list[str]) -> dict[str, float]:
    """Check Google Trends for ticker search volume spikes via SerpAPI.

    Returns dict of ticker -> trend delta (positive = rising interest).
    """
    if not cfg.get("social.google_trends_enabled", True):
        return {}
    if not tickers:
        return {}

    api_key = cfg.get_api_key("serpapi")
    if not api_key:
        log.debug("Google Trends: no SerpAPI key configured, skipping")
        return {}

    results = {}
    async with aiohttp.ClientSession() as session:
        for ticker in tickers[:10]:
            if not await rate_limiter.acquire("google_trends"):
                break

            try:
                params = {
                    "engine": "google_trends",
                    "q": f"{ticker} stock",
                    "date": "now 1-d",
                    "geo": "US",
                    "api_key": api_key,
                }
                async with session.get(
                    "https://serpapi.com/search.json",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        log.warning("SerpAPI error (%d) for %s", resp.status, ticker)
                        rate_limiter.report_failure("google_trends")
                        continue
                    data = await resp.json()

                # Extract interest over time
                timeline = data.get("interest_over_time", {}).get("timeline_data", [])
                if len(timeline) >= 2:
                    recent = timeline[-1].get("values", [{}])[0].get("extracted_value", 0)
                    earlier = timeline[0].get("values", [{}])[0].get("extracted_value", 0)
                    if earlier > 0:
                        delta = ((recent - earlier) / earlier) * 100
                        results[ticker] = delta
                    elif recent > 0:
                        results[ticker] = 100.0

                rate_limiter.report_success("google_trends")
            except Exception as e:
                log.debug("Google Trends SerpAPI error for %s: %s", ticker, e)
                rate_limiter.report_failure("google_trends")

            await asyncio.sleep(1)

    log.info("Google Trends (SerpAPI): %d/%d tickers with data", len(results), len(tickers))
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BULL_WORDS = {"bull", "calls", "buy", "long", "undervalued", "beat", "breakout", "moon", "rocket", "squeeze"}
_BEAR_WORDS = {"bear", "puts", "sell", "short", "overvalued", "miss", "breakdown", "crash", "dump"}


def _quick_sentiment(text: str) -> Sentiment:
    """Fast keyword-based sentiment."""
    lower = text.lower()
    bull = sum(1 for w in _BULL_WORDS if w in lower)
    bear = sum(1 for w in _BEAR_WORDS if w in lower)
    if bull > bear:
        return Sentiment.BULLISH
    elif bear > bull:
        return Sentiment.BEARISH
    return Sentiment.NEUTRAL
