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
from consensus_engine.utils.http import get_session
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
# Reddit (public JSON API — no auth needed)
# ---------------------------------------------------------------------------

async def scan_reddit() -> list[TickerSignal]:
    """Fetch subreddit posts via Reddit's public JSON API."""
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
            try:
                url = f"https://www.reddit.com/r/{sub}/new.json?limit=25"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        log.warning("Reddit JSON r/%s returned %d", sub, resp.status)
                        rate_limiter.report_failure("reddit")
                        continue
                    data = await resp.json()
                sub_signals = _parse_reddit_json(data, sub)
                signals.extend(sub_signals)
                rate_limiter.report_success("reddit")
            except Exception as e:
                log.warning("Reddit JSON error for r/%s: %s", sub, e)
                rate_limiter.report_failure("reddit")
            await asyncio.sleep(2)

    log.info("Reddit: %d signals from %d subreddits", len(signals), len(subreddits))
    return signals


def _parse_reddit_json(data: dict, subreddit: str) -> list[TickerSignal]:
    """Parse Reddit JSON API response into TickerSignal list."""
    children = data.get("data", {}).get("children", [])
    signals = []
    for child in children[:25]:
        post = child.get("data", {})
        title = post.get("title", "")
        selftext = post.get("selftext", "")
        text = (title + " " + selftext).strip()

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
# Google Trends (Pytrends - Free, runs as background task)
# ---------------------------------------------------------------------------

# Track Pytrends failures for auto-disable
_pytrends_failure_window: list[float] = []  # Timestamps of recent failures


async def scan_google_trends_pytrends(tickers: list[str]) -> dict[str, float]:
    """Check Google Trends for ticker search volume spikes via Pytrends (free).

    Runs blocking pytrends calls in a thread executor to avoid blocking the
    event loop. Sleeps 60s between each ticker (Google rate-limit threshold).
    Auto-disables after 3 failures in 24 hours — Exa AI takes over as fallback.

    Returns dict of ticker -> trend delta (positive = rising interest).
    """
    global _pytrends_failure_window

    if not cfg.get("social.google_trends_enabled", True):
        return {}
    if not tickers:
        return {}
    if not cfg.get("social.pytrends_enabled", False):
        return {}

    # Auto-disable after 3 failures in 24 hours
    now = time.time()
    one_day_ago = now - 86400
    _pytrends_failure_window = [ts for ts in _pytrends_failure_window if ts > one_day_ago]

    if len(_pytrends_failure_window) >= 3:
        log.warning("Pytrends auto-disabled: 3+ failures in 24h — Exa AI fallback will be used.")
        cfg.config["social"]["pytrends_enabled"] = False
        return {}

    try:
        from pytrends.request import TrendReq
        import pandas as pd
    except ImportError:
        log.debug("Pytrends not installed, skipping")
        return {}

    results = {}
    loop = asyncio.get_event_loop()
    pytrends = TrendReq(hl='en-US', tz=360)
    batch = tickers[:5]

    for i, ticker in enumerate(batch):
        # Sleep 60s between requests (not before first, not after last)
        if i > 0:
            await asyncio.sleep(60)

        try:
            kw = f"{ticker} stock"

            # Run blocking calls in thread executor so event loop stays free
            await loop.run_in_executor(
                None,
                lambda: pytrends.build_payload([kw], cat=0, timeframe='now 1-d', geo='US'),
            )
            interest = await loop.run_in_executor(None, pytrends.interest_over_time)

            if interest is None or len(interest) < 2 or kw not in interest.columns:
                continue

            recent = interest.iloc[-1][kw]
            earlier = interest.iloc[0][kw]

            # Skip rows with NaN (no data for period — avoids false -100%)
            if pd.isna(recent) or pd.isna(earlier):
                continue

            recent, earlier = float(recent), float(earlier)

            if earlier > 0:
                results[ticker] = ((recent - earlier) / earlier) * 100
            elif recent > 0:
                results[ticker] = 100.0
            # both zero → skip (no meaningful signal)

        except Exception as e:
            log.warning("Pytrends error for %s: %s", ticker, e)
            _pytrends_failure_window.append(now)

    log.info("Google Trends (Pytrends): %d/%d tickers with data", len(results), len(batch))
    return results


# ---------------------------------------------------------------------------
# Google Trends (Exa AI - Fallback when Pytrends is rate-limited/disabled)
# ---------------------------------------------------------------------------

async def scan_google_trends_exa(tickers: list[str]) -> dict[str, float]:
    """Proxy Google Trends interest via Exa AI recent article count (fallback).

    Searches Exa for "{ticker} stock" limited to the last 24h.
    Result count is a reliable proxy for trending interest:
      10+ articles → strong spike (75.0)
       5+ articles → moderate spike (40.0)
       1+ articles → weak signal  (15.0)

    Returns dict of ticker -> trend score.
    """
    if not tickers:
        return {}

    api_key = cfg.get_api_key("exa")
    if not api_key:
        log.debug("Exa AI: no API key configured, skipping trends fallback")
        return {}

    from datetime import datetime, timedelta, timezone
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    results = {}
    async with aiohttp.ClientSession() as session:
        for ticker in tickers[:10]:
            if not await rate_limiter.acquire("exa"):
                break
            try:
                payload = {
                    "query": f"{ticker} stock",
                    "numResults": 10,
                    "startPublishedDate": yesterday,
                    "useAutoprompt": False,
                }
                async with session.post(
                    "https://api.exa.ai/search",
                    json=payload,
                    headers={"x-api-key": api_key, "Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        rate_limiter.report_failure("exa")
                        continue
                    data = await resp.json()

                count = len(data.get("results", []))
                if count >= 10:
                    results[ticker] = 75.0
                elif count >= 5:
                    results[ticker] = 40.0
                elif count >= 1:
                    results[ticker] = 15.0

                rate_limiter.report_success("exa")
            except Exception as e:
                log.debug("Exa trends error for %s: %s", ticker, e)
                rate_limiter.report_failure("exa")

            await asyncio.sleep(0.5)

    log.info("Google Trends (Exa fallback): %d/%d tickers with data", len(results), len(tickers))
    return results


# ---------------------------------------------------------------------------
# Google Trends (Combined - Pytrends primary, Exa fallback, SerpAPI via cron)
# ---------------------------------------------------------------------------

async def scan_google_trends_combined(tickers: list[str]) -> dict[str, float]:
    """Run Google Trends using the best available source.

    Priority:
      1. Pytrends (free, runs as non-blocking background task every 300s)
      2. Exa AI (fallback when Pytrends is auto-disabled after 3 failures/24h)
      3. SerpAPI (cron only — once/day at 5:50am via jobs.json, never called here)
    """
    if cfg.get("social.pytrends_enabled", False):
        results = await scan_google_trends_pytrends(tickers)
        if results:
            return results

    # Pytrends disabled or returned nothing — use Exa AI
    return await scan_google_trends_exa(tickers)


async def scan_google_trends_serpapi(tickers: list[str]) -> dict[str, float]:
    """Run SerpAPI Google Trends. Called only by cron at 5:50am (jobs.json)."""
    return await scan_google_trends(tickers)


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
