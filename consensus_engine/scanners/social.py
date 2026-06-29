"""Social & Sentiment Scanner.

Scanners for cross-reference scoring:
  - Reddit: Public JSON API (no browser needed)
  - StockTwits: Playwright stealth (API blocked by Cloudflare)
  - ApeWisdom: Direct REST API (free)
  - Google Trends: SerpAPI
"""

import asyncio
import logging
import os
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
from consensus_engine.utils.circuit_breaker import circuit_breaker  # C5



async def _has_market_cap(ticker: str) -> bool:
    """Check if ticker has any market cap - skip if not a real stock."""
    try:
        from consensus_engine.utils.tickers import validate_ticker_market_cap
        return await validate_ticker_market_cap(ticker)
    except Exception as e:
        # C19: fail CLOSED. validate_ticker_market_cap (Finnhub) already fails
        # closed, so a bare exception here must not let an unvalidated ticker
        # through; treat it as not-a-real-stock and skip.
        log.warning("market-cap validation errored for %s (%s); treating as invalid", ticker, e)
        return False

log = logging.getLogger("consensus_engine.scanner.social")


# ---------------------------------------------------------------------------
# Reddit (public JSON API — no auth needed)
# ---------------------------------------------------------------------------

async def scan_reddit() -> list[TickerSignal]:
    """Fetch subreddit posts via OAuth API (credentials) or RSS fallback."""
    subreddits = cfg.get("social.subreddits", [])
    if not subreddits:
        return []

    from consensus_engine.utils.reddit import fetch_subreddit_posts

    signals = []
    session = await get_session()
    for sub in subreddits:
        if not await rate_limiter.acquire("reddit"):
            break
        try:
            posts = await fetch_subreddit_posts(session, sub, limit=100)
            sub_signals = _parse_reddit_posts(posts, sub)
            signals.extend(sub_signals)
            rate_limiter.report_success("reddit")
        except Exception as e:
            log.warning("Reddit error for r/%s: %s", sub, e)
            rate_limiter.report_failure("reddit")
        await asyncio.sleep(2)

    log.info("Reddit: %d signals from %d subreddits", len(signals), len(subreddits))
    return signals


def _parse_reddit_json(response: dict, subreddit: str) -> list[TickerSignal]:
    """Parse a raw Reddit JSON API response (with data.children) into TickerSignals."""
    children = response.get("data", {}).get("children", [])
    posts = [c.get("data", {}) for c in children if isinstance(c, dict)]
    return _parse_reddit_posts(posts, subreddit)


def _parse_reddit_posts(posts: list[dict], subreddit: str) -> list[TickerSignal]:
    """Parse flat post list into TickerSignals."""
    signals = []
    for post in posts:
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
        session = await get_session()
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
                mentions_24h_ago = item.get("mentions_24h_ago")
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
                # I13 (signal-features-2026-06-09): persist numeric mention count
                # for the z-score baseline. Never raise on DB error — write is
                # additive and a failure must not break the scan.
                try:
                    await db.upsert_apewisdom_mentions(
                        ticker=ticker,
                        mentions=int(mentions),
                        rank=int(rank),
                        mentions_24h_ago=int(mentions_24h_ago) if mentions_24h_ago is not None else None,
                    )
                except Exception as _db_exc:
                    log.warning("ApeWisdom: failed to persist mention count for %s: %s", ticker, _db_exc)
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

# In-memory SerpAPI key rotation. Advances permanently when a key is rate-limited.
_serpapi_key_index = 0


def _get_serpapi_keys() -> list[str]:
    return [
        k for k in [
            cfg.get_api_key("serpapi"),
            os.environ.get("SERPAPI2_API_KEY", ""),
            os.environ.get("SERPAPI3_API_KEY", ""),
        ]
        if k
    ]


async def scan_google_trends(tickers: list[str]) -> dict[str, float]:
    """Check Google Trends for ticker search volume spikes via SerpAPI.

    Returns dict of ticker -> trend delta (positive = rising interest).
    Rotates through up to 3 SerpAPI keys on rate-limit, retrying the same
    ticker immediately with the next key so no data is missed.
    """
    global _serpapi_key_index

    if not cfg.get("precision_engine.serpapi_enabled", True):
        log.debug("Google Trends: SerpAPI disabled via config, skipping")
        return {}
    if not cfg.get("social.google_trends_enabled", True):
        return {}
    if not tickers:
        return {}

    keys = _get_serpapi_keys()
    if not keys:
        log.debug("Google Trends: no SerpAPI key configured, skipping")
        return {}

    # Filter to valid tickers with market cap
    valid_tickers = []
    for t in tickers[:10]:
        if await _has_market_cap(t):
            valid_tickers.append(t)
    if not valid_tickers:
        return {}

    results = {}
    session = await get_session()
    for ticker in valid_tickers:
        if not await rate_limiter.acquire("google_trends"):
            break

        # Inner loop: try each key starting from current active index.
        # On rate-limit, advance _serpapi_key_index and retry same ticker.
        for attempt in range(len(keys)):
            key = keys[_serpapi_key_index]
            try:
                params = {
                    "engine": "google_trends",
                    "q": f"{ticker} stock",
                    "date": "now 1-d",
                    "geo": "US",
                    "api_key": key,
                }
                async with session.get(
                    "https://serpapi.com/search.json",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status in (429, 401):
                        log.warning(
                            "SerpAPI key %d/%d rate limited (HTTP %d) for %s, rotating",
                            _serpapi_key_index + 1, len(keys), resp.status, ticker,
                        )
                        _serpapi_key_index = (_serpapi_key_index + 1) % len(keys)
                        continue  # retry same ticker with next key
                    if resp.status != 200:
                        log.warning("SerpAPI error (%d) for %s", resp.status, ticker)
                        rate_limiter.report_failure("google_trends")
                        break  # non-rate-limit error, skip ticker
                    data = await resp.json()

                # SerpAPI also returns rate-limit errors in the JSON body
                err = data.get("error", "")
                if err and any(w in err.lower() for w in ("run out", "limit", "quota")):
                    log.warning(
                        "SerpAPI key %d/%d exhausted (%s) for %s, rotating",
                        _serpapi_key_index + 1, len(keys), err, ticker,
                    )
                    _serpapi_key_index = (_serpapi_key_index + 1) % len(keys)
                    continue  # retry same ticker with next key

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
                break  # success
            except Exception as e:
                log.debug("Google Trends SerpAPI error for %s: %s", ticker, e)
                rate_limiter.report_failure("google_trends")
                break  # network/parse error, skip ticker
        else:
            log.error("All %d SerpAPI keys exhausted for %s — skipping ticker", len(keys), ticker)
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
        cfg._config["social"]["pytrends_enabled"] = False
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
            _pytrends_failure_window.append(time.time())
            if len(_pytrends_failure_window) >= 3:
                log.warning("Pytrends: 3+ failures this cycle, bailing — Exa AI fallback will be used.")
                cfg._config["social"]["pytrends_enabled"] = False
                break

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

    # Filter to valid tickers with market cap
    valid_tickers = []
    for t in tickers[:10]:
        if await _has_market_cap(t):
            valid_tickers.append(t)
    if not valid_tickers:
        return {}

    # C5: skip the whole Exa sweep when the breaker is open (the motivating
    # "0/10 tickers" silent-loop case) instead of hammering a dead source.
    if not circuit_breaker.allow("exa"):
        return {}

    results = {}
    session = await get_session()
    for ticker in valid_tickers:
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
                    await circuit_breaker.note_failure("exa", status=resp.status)  # C5
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
            await circuit_breaker.note_success("exa")  # C5
        except Exception as e:
            log.debug("Exa trends error for %s: %s", ticker, e)
            rate_limiter.report_failure("exa")
            await circuit_breaker.note_failure("exa", exc=e)  # C5

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
    """Run SerpAPI Google Trends. Called only by cron at 5:50am (jobs.json).
    
    Bypasses the precision_engine.serpapi_enabled config flag since this is
    the explicit cron entry point for SerpAPI scans.
    """
    global _serpapi_key_index

    if not cfg.get("social.google_trends_enabled", True):
        return {}
    if not tickers:
        return {}

    keys = _get_serpapi_keys()
    if not keys:
        log.debug("Google Trends (SerpAPI cron): no SerpAPI key configured, skipping")
        return {}

    # Filter to valid tickers with market cap
    valid_tickers = []
    for t in tickers[:10]:
        if await _has_market_cap(t):
            valid_tickers.append(t)
    if not valid_tickers:
        return {}

    results = {}
    session = await get_session()
    for ticker in valid_tickers:
        if not await rate_limiter.acquire("google_trends"):
            break

        # Inner loop: try each key starting from current active index.
        # On rate-limit, advance _serpapi_key_index and retry same ticker.
        for attempt in range(len(keys)):
            key = keys[_serpapi_key_index]
            try:
                params = {
                    "engine": "google_trends",
                    "q": f"{ticker} stock",
                    "date": "now 1-d",
                    "geo": "US",
                    "api_key": key,
                }
                async with session.get(
                    "https://serpapi.com/search.json",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status in (429, 401):
                        log.warning(
                            "SerpAPI key %d/%d rate limited (HTTP %d) for %s, rotating",
                            _serpapi_key_index + 1, len(keys), resp.status, ticker,
                        )
                        _serpapi_key_index = (_serpapi_key_index + 1) % len(keys)
                        continue  # retry same ticker with next key
                    if resp.status != 200:
                        log.warning("SerpAPI error (%d) for %s", resp.status, ticker)
                        rate_limiter.report_failure("google_trends")
                        break  # non-rate-limit error, skip ticker
                    data = await resp.json()

                # SerpAPI also returns rate-limit errors in the JSON body
                err = data.get("error", "")
                if err and any(w in err.lower() for w in ("run out", "limit", "quota")):
                    log.warning(
                        "SerpAPI key %d/%d exhausted (%s) for %s, rotating",
                        _serpapi_key_index + 1, len(keys), err, ticker,
                    )
                    _serpapi_key_index = (_serpapi_key_index + 1) % len(keys)
                    continue  # retry same ticker with next key

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
                break  # success
            except Exception as e:
                log.debug("Google Trends SerpAPI error for %s: %s", ticker, e)
                rate_limiter.report_failure("google_trends")
                break  # network/parse error, skip ticker
        else:
            log.error("All %d SerpAPI keys exhausted for %s — skipping ticker", len(keys), ticker)
            rate_limiter.report_failure("google_trends")

        await asyncio.sleep(1)

    log.info("Google Trends (SerpAPI cron): %d/%d tickers with data", len(results), len(tickers))
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
