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
            "finnhub_news": 1.0,  # 60/min on free tier
            "google_news_rss": 0.5,  # No rate limit, but be polite
            "searxng": 0.5,       # Local, but don't hammer it
            "sec_edgar": 0.2,     # SEC asks for max 10 req/s
            "gemini": 6.0,        # ≤10 RPM free tier — pace at 6s/request to avoid per-minute 429s
            "openrouter": 1.0,    # 60/min process-level cap (D17 / S6)
            "groq": 2.0,          # Groq free tier ~30 req/min
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

            # Reserve the slot now (before releasing lock).
            # Use `now` captured above, not a fresh time.time(): under
            # contention the lock-held time itself drifts the slot reservation.
            self._last_request[source] = now + wait_time

        # Sleep outside the lock so other sources aren't blocked
        if wait_time > 0:
            await asyncio.sleep(wait_time)

        return True

    def report_success(self, source: str):
        """Reset failure count on success."""
        self._failure_counts[source] = 0

    def report_failure(self, source: str, retry_after: float | None = None):
        """Increment failure count and potentially trigger backoff.

        C3: when a server supplies an explicit Retry-After (seconds), honor it
        immediately (capped at 600s) instead of the count-based exponential
        schedule — rate_limiter stays the single backoff authority, now informed
        by the server hint. Existing callers omit ``retry_after`` and are
        unaffected.
        """
        self._failure_counts[source] += 1
        count = self._failure_counts[source]

        if retry_after and retry_after > 0:
            block = min(float(retry_after), 600.0)
            self._blocked_until[source] = time.time() + block
            log.warning("Source '%s' backing off %.0fs (server Retry-After)", source, block)
            return

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
