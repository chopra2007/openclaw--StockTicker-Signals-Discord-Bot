"""Async rate limiter with per-source tracking and exponential backoff."""

import asyncio
import logging
import time
from collections import defaultdict

log = logging.getLogger("consensus_engine.rate_limiter")


class RateLimiter:
    """Per-source async rate limiter with backoff on failures."""

    def __init__(self):
        self._last_request: dict[str, float] = defaultdict(float)
        self._min_intervals: dict[str, float] = {
            "twitter": 3.0,       # 3s between Twitter page loads
            "reddit": 2.0,        # 2s between Reddit pages
            "stocktwits": 1.0,    # 1s between StockTwits API calls
            "apewisdom": 1.0,     # 1s between ApeWisdom API calls
            "google_trends": 5.0, # 5s between Google Trends checks
            "brave_search": 0.5,  # Brave API is generous
            "finnhub": 1.0,       # 60/min = 1/s
            "news_scrape": 3.0,   # News site scraping
            "discord": 0.5,       # Discord API
        }
        self._failure_counts: dict[str, int] = defaultdict(int)
        self._blocked_until: dict[str, float] = defaultdict(float)
        self._lock = asyncio.Lock()

    async def acquire(self, source: str) -> bool:
        """Wait for rate limit clearance. Returns False if source is blocked."""
        wait_time = 0.0
        async with self._lock:
            now = time.time()

            # Check if source is temporarily blocked (backoff)
            if now < self._blocked_until.get(source, 0):
                remaining = self._blocked_until[source] - now
                log.warning("Source '%s' blocked for %.1fs (backoff)", source, remaining)
                return False

            # Enforce minimum interval
            min_interval = self._min_intervals.get(source, 1.0)
            elapsed = now - self._last_request.get(source, 0)
            if elapsed < min_interval:
                wait_time = min_interval - elapsed

            # Reserve the slot now (before releasing lock)
            self._last_request[source] = time.time() + wait_time

        # Sleep outside the lock so other sources aren't blocked
        if wait_time > 0:
            await asyncio.sleep(wait_time)

        return True

    def report_success(self, source: str):
        """Reset failure count on success."""
        self._failure_counts[source] = 0

    def report_failure(self, source: str):
        """Increment failure count and potentially trigger backoff."""
        self._failure_counts[source] += 1
        count = self._failure_counts[source]

        if count >= 3:
            # Exponential backoff: 30s, 60s, 120s, 240s, max 600s
            backoff = min(30 * (2 ** (count - 3)), 600)
            self._blocked_until[source] = time.time() + backoff
            log.warning(
                "Source '%s' backing off for %ds after %d failures",
                source, backoff, count,
            )

    def is_blocked(self, source: str) -> bool:
        return time.time() < self._blocked_until.get(source, 0)


# Global singleton
rate_limiter = RateLimiter()
