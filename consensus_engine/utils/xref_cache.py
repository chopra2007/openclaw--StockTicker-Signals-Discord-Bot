"""In-memory cross-reference result cache with TTL.

Prevents redundant API calls when multiple analysts tweet the same ticker
within a short window. Keyed by ticker, 5-minute TTL.
"""

import time
from typing import Any, Optional


class XRefCache:
    """Simple in-memory cache with per-entry TTL."""

    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        self._entries: dict[str, tuple[float, Any]] = {}

    def get(self, ticker: str) -> Optional[Any]:
        """Get cached result, or None if missing/expired."""
        entry = self._entries.get(ticker)
        if entry is None:
            return None
        timestamp, value = entry
        if time.time() - timestamp > self.ttl_seconds:
            del self._entries[ticker]
            return None
        return value

    def put(self, ticker: str, value: Any) -> None:
        """Cache a result for a ticker."""
        self._entries[ticker] = (time.time(), value)


# Module-level singleton
_cache = XRefCache(ttl_seconds=300)


def get_cached_xref(ticker: str) -> Optional[Any]:
    return _cache.get(ticker)


def cache_xref(ticker: str, result: Any) -> None:
    _cache.put(ticker, result)


def clear_xref_cache() -> None:
    _cache._entries.clear()
