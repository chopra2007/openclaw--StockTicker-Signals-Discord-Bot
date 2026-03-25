"""Stage 2 — Social & Sentiment Scanner.

Hybrid strategy:
  - Reddit: Apify primary, Playwright fallback
  - StockTwits: Direct API (free, no scraping needed)
  - ApeWisdom: Direct API (free, no scraping needed)
  - Google Trends: Apify primary

Monitors Reddit, StockTwits, ApeWisdom, and Google Trends.
"""

import asyncio
import logging
import time
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.models import (
    TickerSignal, SourceType, Sentiment, SocialConsensus,
)
from consensus_engine.utils.tickers import extract_tickers
from consensus_engine.utils.browser import (
    create_stealth_browser, stealth_page, safe_goto, random_delay,
)
from consensus_engine.utils.rate_limiter import rate_limiter
from consensus_engine.utils.apify_client import apify

log = logging.getLogger("consensus_engine.scanner.social")


# ---------------------------------------------------------------------------
# Reddit — Apify primary, Playwright fallback
# ---------------------------------------------------------------------------

async def _scan_reddit_apify() -> list[TickerSignal]:
    """Scrape Reddit via Apify Reddit Scraper Lite."""
    if not apify.enabled:
        return []

    actor_id = cfg.get("apify.actors.reddit", "trudax/reddit-scraper-lite")
    subreddits = cfg.get("social.subreddits", [])
    if not subreddits:
        return []

    urls = [f"https://www.reddit.com/r/{sub}/new/" for sub in subreddits]

    input_data = {
        "startUrls": [{"url": u} for u in urls],
        "maxItems": cfg.get("apify.max_results", 50),
        "maxPostCount": 20,
        "maxComments": 0,
        "sort": "new",
        "proxy": {"useApifyProxy": True},
    }

    items = await apify.run_actor(actor_id, input_data, timeout_seconds=90)
    signals = []

    for item in items:
        title = item.get("title", "")
        body = item.get("body") or item.get("selftext") or item.get("text") or ""
        text = f"{title} {body}"
        subreddit = item.get("subreddit") or item.get("communityName") or "reddit"
        score = item.get("score") or item.get("upVotes") or 0

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

    log.info("Apify Reddit: %d signals from %d subreddits", len(signals), len(subreddits))
    return signals


async def _scan_reddit_playwright() -> list[TickerSignal]:
    """Scrape subreddits via Playwright stealth (fallback)."""
    subreddits = cfg.get("social.subreddits", [])
    if not subreddits:
        return []

    signals = []
    async with create_stealth_browser() as (browser, context):
        for sub in subreddits:
            sub_signals = await _scrape_subreddit_pw(context, sub)
            signals.extend(sub_signals)
            await random_delay(2.0, 5.0)

    log.info("Playwright Reddit: %d signals", len(signals))
    return signals


async def _scrape_subreddit_pw(context, subreddit: str) -> list[TickerSignal]:
    """Scrape a single subreddit via Playwright."""
    if not await rate_limiter.acquire("reddit"):
        return []

    signals = []
    page = await stealth_page(context)
    try:
        url = f"https://old.reddit.com/r/{subreddit}/new/"
        if not await safe_goto(page, url):
            rate_limiter.report_failure("reddit")
            return []

        posts = await page.query_selector_all("#siteTable .thing.link")
        for post in posts[:25]:
            try:
                title_el = await post.query_selector("a.title")
                if not title_el:
                    continue
                title = await title_el.inner_text()

                text = title
                expando = await post.query_selector(".expando .md")
                if expando:
                    text = title + " " + await expando.inner_text()

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
            except Exception:
                continue

        rate_limiter.report_success("reddit")
    except Exception as e:
        log.warning("Playwright error for r/%s: %s", subreddit, e)
        rate_limiter.report_failure("reddit")
    finally:
        await page.close()

    return signals


async def scan_reddit() -> list[TickerSignal]:
    """Scan Reddit — Apify primary, Playwright fallback."""
    signals = await _scan_reddit_apify()
    if not signals:
        log.info("Apify Reddit returned nothing, falling back to Playwright...")
        signals = await _scan_reddit_playwright()
    return signals


# ---------------------------------------------------------------------------
# StockTwits (Playwright stealth — API blocked by Cloudflare)
# ---------------------------------------------------------------------------

async def scan_stocktwits() -> list[TickerSignal]:
    """Fetch trending symbols from StockTwits via Playwright.

    StockTwits API is behind Cloudflare, so we scrape the trending page.
    """
    if not cfg.get("social.stocktwits_enabled", True):
        return []
    if not await rate_limiter.acquire("stocktwits"):
        return []

    signals = []
    try:
        async with create_stealth_browser() as (browser, context):
            page = await stealth_page(context)
            if not await safe_goto(page, "https://stocktwits.com/rankings/trending", wait_until="networkidle"):
                rate_limiter.report_failure("stocktwits")
                return []

            await asyncio.sleep(3)  # Let dynamic content load

            # Extract ticker symbols from the trending list
            rows = await page.query_selector_all('a[href*="/symbol/"]')
            seen = set()
            for row in rows[:30]:
                try:
                    href = await row.get_attribute("href") or ""
                    text = await row.inner_text()
                    # Extract ticker from /symbol/NVDA or text like "$NVDA"
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
# Google Trends — Apify primary
# ---------------------------------------------------------------------------

async def scan_google_trends(tickers: list[str]) -> dict[str, float]:
    """Check Google Trends for ticker search volume spikes.

    Uses Apify Google Trends Scraper as primary.
    Returns dict of ticker → trend delta (positive = rising interest).
    """
    if not cfg.get("social.google_trends_enabled", True):
        return {}
    if not tickers:
        return {}

    # Try Apify first
    results = await _google_trends_apify(tickers)
    if results:
        return results

    # Fallback to Playwright
    return await _google_trends_playwright(tickers)


async def _google_trends_apify(tickers: list[str]) -> dict[str, float]:
    """Check Google Trends via Apify actor."""
    if not apify.enabled:
        return {}

    actor_id = cfg.get("apify.actors.google_trends", "apify/google-trends-scraper")
    results = {}

    # Google Trends supports up to 5 terms per comparison
    for i in range(0, min(len(tickers), 10), 5):
        batch = tickers[i:i + 5]
        search_terms = [f"{t} stock" for t in batch]

        input_data = {
            "searchTerms": search_terms,
            "timeRange": "now 1-d",
            "geo": "US",
            "isPublic": False,
        }

        items = await apify.run_actor(actor_id, input_data, timeout_seconds=60)

        for item in items:
            term = item.get("searchTerm", "") or item.get("term", "")
            # Extract ticker from "NVDA stock" → "NVDA"
            ticker = term.split()[0].upper() if term else ""
            if ticker not in tickers:
                continue

            # Different actors return different fields
            value = (
                item.get("interestOverTime", 0)
                or item.get("value", 0)
                or item.get("interest", 0)
            )
            if isinstance(value, list) and value:
                # Some actors return a time series — take the latest
                value = value[-1] if isinstance(value[-1], (int, float)) else 0

            if isinstance(value, (int, float)) and value > 0:
                results[ticker] = float(value)

    log.info("Apify Google Trends: %d/%d tickers with data", len(results), len(tickers))
    return results


async def _google_trends_playwright(tickers: list[str]) -> dict[str, float]:
    """Check Google Trends via Playwright stealth (fallback)."""
    results = {}
    async with create_stealth_browser() as (browser, context):
        for ticker in tickers[:10]:
            if not await rate_limiter.acquire("google_trends"):
                break

            page = await stealth_page(context)
            try:
                url = f"https://trends.google.com/trends/explore?q={ticker}+stock&date=now%201-d&geo=US"
                if not await safe_goto(page, url, wait_until="networkidle"):
                    rate_limiter.report_failure("google_trends")
                    continue

                await asyncio.sleep(3)
                trend_el = await page.query_selector('.summary-value-num')
                if trend_el:
                    trend_text = await trend_el.inner_text()
                    try:
                        if "%" in trend_text:
                            results[ticker] = float(
                                trend_text.replace("%", "").replace("+", "").replace(",", "")
                            )
                        else:
                            results[ticker] = float(trend_text.replace(",", ""))
                    except ValueError:
                        pass

                rate_limiter.report_success("google_trends")
            except Exception as e:
                log.debug("Google Trends Playwright error for %s: %s", ticker, e)
                rate_limiter.report_failure("google_trends")
            finally:
                await page.close()
                await random_delay(3.0, 6.0)

    log.info("Playwright Google Trends: %d/%d tickers with data", len(results), len(tickers))
    return results


# ---------------------------------------------------------------------------
# Social Consensus Evaluation
# ---------------------------------------------------------------------------

async def evaluate_social_consensus(ticker: str) -> Optional[SocialConsensus]:
    """Evaluate whether a ticker has social confirmation across platforms."""
    rows = await db.get_social_signals(ticker)
    if not rows:
        return None

    min_platforms = cfg.get("social.min_platforms_confirming", 1)

    platform_counts: dict[str, int] = {}
    for row in rows:
        src = row["source_type"]
        platform_counts[src] = platform_counts.get(src, 0) + 1

    reddit_mentions = platform_counts.get("reddit", 0)
    stocktwits_count = platform_counts.get("stocktwits", 0)
    apewisdom_count = platform_counts.get("apewisdom", 0)
    trends_count = platform_counts.get("google_trends", 0)

    platforms_confirming = sum(1 for c in [
        reddit_mentions >= 2,
        stocktwits_count >= 1,
        apewisdom_count >= 1,
        trends_count >= 1,
    ] if c)

    consensus = SocialConsensus(
        ticker=ticker,
        reddit_mentions=reddit_mentions,
        stocktwits_trending=stocktwits_count > 0,
        apewisdom_rank=None,
        google_trend_delta=None,
        platforms_confirming=platforms_confirming,
    )

    if consensus.passed:
        log.info("Social CONSENSUS for %s: %d platforms (reddit=%d, st=%d, ape=%d, trends=%d)",
                 ticker, platforms_confirming, reddit_mentions,
                 stocktwits_count, apewisdom_count, trends_count)
    else:
        log.debug("Social: %s only %d platforms (need %d)",
                   ticker, platforms_confirming, min_platforms)

    return consensus


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
