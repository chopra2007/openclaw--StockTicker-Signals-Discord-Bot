"""Nitter RSS Poller — fetches tweets from self-hosted Nitter via RSS.

Polls all 49 configured analyst accounts concurrently every 60-90 seconds.
Deduplicates by tweet URL. New tweets are returned for parsing.
"""

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine import db

log = logging.getLogger("consensus_engine.scanner.nitter")


def parse_rss_feed(xml_text: str, analyst: str) -> list[dict]:
    """Parse a Nitter RSS feed XML string into tweet dicts.

    Returns list of {"url": str, "text": str, "analyst": str, "timestamp": float}.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        log.warning("Failed to parse RSS for @%s", analyst)
        return []

    items = []
    for item in root.iter("item"):
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        description = item.findtext("description", "")
        pub_date = item.findtext("pubDate", "")

        text = description or title
        if not text or not link:
            continue

        timestamp = time.time()
        if pub_date:
            try:
                dt = parsedate_to_datetime(pub_date)
                timestamp = dt.timestamp()
            except (ValueError, TypeError):
                pass

        items.append({
            "url": link,
            "text": text,
            "analyst": analyst,
            "timestamp": timestamp,
        })

    return items


def _is_market_hours() -> bool:
    """Check if current time is within US market hours (ET)."""
    from datetime import timezone, timedelta
    et = timezone(timedelta(hours=-5))
    now_et = datetime.now(et)
    open_hour = cfg.get("nitter.market_open_hour", 9)
    close_hour = cfg.get("nitter.market_close_hour", 16)
    if now_et.weekday() > 4:
        return False
    return open_hour <= now_et.hour < close_hour


class NitterPoller:
    """Polls Nitter RSS feeds for all configured accounts."""

    def __init__(self):
        self._base_url = cfg.get("nitter.base_url", "http://localhost:8585")
        self._accounts = cfg.get_twitter_accounts()

    async def health_check(self) -> bool:
        """Check if Nitter is reachable."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self._base_url,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    return resp.status == 200
        except Exception as e:
            log.error("Nitter health check failed: %s", e)
            return False

    async def _fetch_rss(self, session: aiohttp.ClientSession, handle: str) -> str:
        """Fetch RSS feed for a single account."""
        url = f"{self._base_url}/{handle}/rss"
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    log.debug("Nitter RSS %d for @%s", resp.status, handle)
                    return ""
                return await resp.text()
        except Exception as e:
            log.debug("Nitter RSS error for @%s: %s", handle, e)
            return ""

    async def poll_all(self) -> list[dict]:
        """Poll all accounts concurrently. Returns only new (unseen) tweets."""
        if not self._accounts:
            log.warning("No Twitter accounts configured")
            return []

        start = time.time()
        new_tweets = []

        async with aiohttp.ClientSession() as session:
            tasks = [self._fetch_rss(session, handle) for handle in self._accounts]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for handle, result in zip(self._accounts, results):
                if isinstance(result, Exception):
                    log.debug("RSS fetch error for @%s: %s", handle, result)
                    continue
                if not result:
                    continue

                items = parse_rss_feed(result, handle)
                for item in items:
                    if await db.is_new_tweet(item["url"]):
                        new_tweets.append(item)

        elapsed = time.time() - start
        if new_tweets:
            log.info("Nitter poll: %d new tweets from %d accounts in %.1fs",
                     len(new_tweets), len(self._accounts), elapsed)
        else:
            log.debug("Nitter poll: no new tweets (%.1fs)", elapsed)

        await db.record_metric("nitter_poll_seconds", elapsed)
        return new_tweets

    def get_poll_interval(self) -> int:
        """Return poll interval based on market hours."""
        if _is_market_hours():
            return cfg.get("nitter.poll_interval_market_hours", 60)
        return cfg.get("nitter.poll_interval_off_hours", 180)
