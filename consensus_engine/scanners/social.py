"""Social & Sentiment Scanner.

Scanners for cross-reference scoring:
  - Reddit: Playwright stealth scraping
  - StockTwits: Playwright stealth (API blocked by Cloudflare)
  - ApeWisdom: Direct REST API (free)
  - Google Trends: Playwright stealth
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
# Reddit (Playwright stealth)
# ---------------------------------------------------------------------------

async def scan_reddit() -> list[TickerSignal]:
    """Scrape subreddits via Playwright stealth."""
    subreddits = cfg.get("social.subreddits", [])
    if not subreddits:
        return []

    signals = []
    async with create_stealth_browser() as (browser, context):
        for sub in subreddits:
            sub_signals = await _scrape_subreddit_pw(context, sub)
            signals.extend(sub_signals)
            await random_delay(2.0, 5.0)

    log.info("Reddit: %d signals", len(signals))
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
                if not await safe_goto(page, "https://stocktwits.com/rankings/trending", wait_until="networkidle"):
                    rate_limiter.report_failure("stocktwits")
                    return []

                await asyncio.sleep(3)

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
# Google Trends (Playwright stealth)
# ---------------------------------------------------------------------------

async def scan_google_trends(tickers: list[str]) -> dict[str, float]:
    """Check Google Trends for ticker search volume spikes.

    Returns dict of ticker -> trend delta (positive = rising interest).
    """
    if not cfg.get("social.google_trends_enabled", True):
        return {}
    if not tickers:
        return {}

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
                log.debug("Google Trends error for %s: %s", ticker, e)
                rate_limiter.report_failure("google_trends")
            finally:
                await page.close()
                await random_delay(3.0, 6.0)

    log.info("Google Trends: %d/%d tickers with data", len(results), len(tickers))
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
