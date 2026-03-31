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


async def get_cached_xref(ticker: str) -> Optional[Any]:
    # L1: in-memory
    hit = _cache.get(ticker)
    if hit is not None:
        return hit
    # L2: DB
    try:
        from consensus_engine.db import get_xref_from_db
        import json
        raw = await get_xref_from_db(ticker)
        if raw is not None:
            from consensus_engine.models import CrossReferenceResult
            result = CrossReferenceResult(**json.loads(raw))
            _cache.put(ticker, result)
            return result
    except Exception:
        pass
    return None


async def cache_xref(ticker: str, result: Any) -> None:
    _cache.put(ticker, result)
    try:
        from consensus_engine.db import set_xref_in_db
        import json
        await set_xref_in_db(ticker, json.dumps(result.__dict__, default=str))
    except Exception:
        pass


def clear_xref_cache() -> None:
    _cache._entries.clear()
