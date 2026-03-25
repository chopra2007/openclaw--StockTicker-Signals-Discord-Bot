"""Stage 1 — X/Twitter Scanner.

Hybrid strategy:
  1. Apify tweet-scraper (cloud, reliable when credits available)
  2. Playwright stealth (local fallback)

Monitors the configured analyst accounts, extracts ticker mentions,
and tracks mention velocity across a rolling window.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Optional

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.models import TickerSignal, SourceType, Sentiment, TwitterConsensus
from consensus_engine.utils.tickers import extract_tickers
from consensus_engine.utils.browser import (
    create_stealth_browser, stealth_page, safe_goto, random_delay,
)
from consensus_engine.utils.rate_limiter import rate_limiter
from consensus_engine.utils.apify_client import apify

log = logging.getLogger("consensus_engine.scanner.twitter")


# ---------------------------------------------------------------------------
# Apify-based Twitter scraping (primary)
# ---------------------------------------------------------------------------

async def _scan_via_apify(accounts: list[str]) -> list[TickerSignal]:
    """Scan Twitter accounts using Apify tweet-scraper.

    Uses search queries like 'from:handle' to get recent tweets.
    Batches accounts into groups to minimize actor runs and cost.
    """
    if not apify.enabled:
        return []

    actor_id = cfg.get("apify.actors.twitter", "apidojo/tweet-scraper")
    signals = []

    # Batch accounts into groups of 10 for search queries
    # "from:handle1 OR from:handle2 ..." is valid Twitter search syntax
    batch_size = 10
    for i in range(0, len(accounts), batch_size):
        batch = accounts[i:i + batch_size]
        # Build combined search query
        query = " OR ".join(f"from:{h}" for h in batch)

        input_data = {
            "searchTerms": [query],
            "maxItems": cfg.get("apify.max_results", 50),
            "sort": "Latest",
        }

        items = await apify.run_actor(actor_id, input_data, timeout_seconds=90)

        for item in items:
            text = item.get("text") or item.get("full_text") or item.get("tweet") or ""
            if not text:
                # Try nested structures common in tweet scrapers
                text = item.get("content", "")

            author = (
                item.get("author", {}).get("userName", "")
                or item.get("user", {}).get("screen_name", "")
                or item.get("username", "")
                or item.get("handle", "")
                or ""
            ).lower()

            # Parse timestamp
            ts = time.time()
            for ts_field in ("createdAt", "created_at", "timestamp", "date"):
                raw_ts = item.get(ts_field)
                if raw_ts:
                    try:
                        if isinstance(raw_ts, str):
                            ts = datetime.fromisoformat(
                                raw_ts.replace("Z", "+00:00")
                            ).timestamp()
                        elif isinstance(raw_ts, (int, float)):
                            ts = float(raw_ts) if raw_ts > 1e9 else float(raw_ts) * 1000
                        break
                    except (ValueError, TypeError):
                        continue

            tickers = extract_tickers(text)
            # Match author to our tracked accounts
            matched_handle = author
            for acct in accounts:
                if acct.lower() == author:
                    matched_handle = acct
                    break

            for ticker in tickers:
                signals.append(TickerSignal(
                    ticker=ticker,
                    source_type=SourceType.TWITTER,
                    source_detail=matched_handle,
                    raw_text=text[:500],
                    sentiment=Sentiment.NEUTRAL,
                    detected_at=ts,
                ))

    log.info("Apify Twitter: %d signals from %d accounts", len(signals), len(accounts))
    return signals


# ---------------------------------------------------------------------------
# Playwright-based Twitter scraping (fallback)
# ---------------------------------------------------------------------------

async def _scrape_account_tweets(context, handle: str) -> list[dict]:
    """Scrape recent tweets from a single X/Twitter account via Playwright."""
    if not await rate_limiter.acquire("twitter"):
        return []

    page = await stealth_page(context)
    tweets = []
    try:
        url = f"https://x.com/{handle}"
        if not await safe_goto(page, url, wait_until="networkidle"):
            rate_limiter.report_failure("twitter")
            return []

        try:
            await page.wait_for_selector('article[data-testid="tweet"]', timeout=15000)
        except Exception:
            log.debug("No tweets rendered for @%s", handle)
            rate_limiter.report_failure("twitter")
            return []

        tweet_elements = await page.query_selector_all('article[data-testid="tweet"]')
        for el in tweet_elements[:10]:
            try:
                text_el = await el.query_selector('[data-testid="tweetText"]')
                if text_el:
                    text = await text_el.inner_text()
                    time_el = await el.query_selector("time")
                    timestamp = None
                    if time_el:
                        dt_attr = await time_el.get_attribute("datetime")
                        if dt_attr:
                            try:
                                timestamp = datetime.fromisoformat(
                                    dt_attr.replace("Z", "+00:00")
                                ).timestamp()
                            except ValueError:
                                pass

                    tweets.append({
                        "text": text,
                        "timestamp": timestamp or time.time(),
                        "handle": handle,
                    })
            except Exception:
                continue

        rate_limiter.report_success("twitter")
        log.debug("Playwright: %d tweets from @%s", len(tweets), handle)

    except Exception as e:
        log.warning("Playwright error for @%s: %s", handle, e)
        rate_limiter.report_failure("twitter")
    finally:
        await page.close()

    return tweets


async def _scan_via_playwright(accounts: list[str]) -> list[TickerSignal]:
    """Scan Twitter accounts using Playwright stealth."""
    signals = []

    async with create_stealth_browser() as (browser, context):
        batch_size = 5
        for i in range(0, len(accounts), batch_size):
            batch = accounts[i:i + batch_size]

            for handle in batch:
                tweets = await _scrape_account_tweets(context, handle)
                for tweet in tweets:
                    tickers = extract_tickers(tweet["text"])
                    for ticker in tickers:
                        signals.append(TickerSignal(
                            ticker=ticker,
                            source_type=SourceType.TWITTER,
                            source_detail=handle,
                            raw_text=tweet["text"][:500],
                            sentiment=Sentiment.NEUTRAL,
                            detected_at=tweet["timestamp"],
                        ))

                await random_delay(1.0, 3.0)

            if i + batch_size < len(accounts):
                await random_delay(5.0, 10.0)

    log.info("Playwright Twitter: %d signals from %d accounts", len(signals), len(accounts))
    return signals


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def scan_twitter_accounts() -> list[TickerSignal]:
    """Scan all configured Twitter accounts.

    Strategy: Try Apify first, fall back to Playwright if no results.
    """
    accounts = cfg.get_twitter_accounts()
    if not accounts:
        log.warning("No Twitter accounts configured")
        return []

    log.info("Scanning %d Twitter accounts...", len(accounts))
    start = time.time()

    # Primary: Apify
    signals = await _scan_via_apify(accounts)

    # Fallback: Playwright if Apify returned nothing
    if not signals:
        log.info("Apify returned no Twitter signals, falling back to Playwright...")
        signals = await _scan_via_playwright(accounts)

    elapsed = time.time() - start
    log.info("Twitter scan complete: %d signals from %d accounts in %.1fs",
             len(signals), len(accounts), elapsed)
    await db.record_metric("twitter_scan_seconds", elapsed)
    return signals


async def evaluate_twitter_consensus(ticker: str) -> Optional[TwitterConsensus]:
    """Evaluate whether a ticker meets the Twitter consensus threshold.

    Requires min_analysts unique analysts mentioning the ticker
    within the rolling_window_minutes.
    """
    window_minutes = cfg.get("twitter.rolling_window_minutes", 30)
    min_analysts = cfg.get("twitter.min_analysts", 3)
    window_seconds = window_minutes * 60

    rows = await db.get_twitter_signals(ticker, window_seconds)
    if not rows:
        return None

    # Deduplicate by analyst handle
    analyst_map: dict[str, dict] = {}
    for row in rows:
        handle = row["source_detail"]
        if handle not in analyst_map:
            analyst_map[handle] = row

    if len(analyst_map) < min_analysts:
        log.debug("Twitter: %s has %d/%d analysts (need %d)",
                   ticker, len(analyst_map), min_analysts, min_analysts)
        return None

    analysts = list(analyst_map.keys())
    timestamps = [analyst_map[h]["detected_at"] for h in analysts]
    raw_texts = [analyst_map[h]["raw_text"] for h in analysts]

    if timestamps:
        window_span = (max(timestamps) - min(timestamps)) / 60.0
    else:
        window_span = 0.0

    consensus = TwitterConsensus(
        ticker=ticker,
        analysts=analysts,
        timestamps=timestamps,
        raw_texts=raw_texts,
        window_minutes=window_span,
    )

    if consensus.passed:
        log.info("Twitter CONSENSUS for %s: %d analysts in %.1f min",
                 ticker, consensus.count, window_span)
    else:
        log.debug("Twitter: %s has %d analysts but window is %.1f min (need ≤%d)",
                   ticker, consensus.count, window_span, window_minutes)

    return consensus
