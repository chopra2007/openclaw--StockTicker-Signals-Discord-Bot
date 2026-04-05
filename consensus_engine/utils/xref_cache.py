"""In-memory cross-reference result cache with TTL.

Prevents redundant API calls when multiple analysts tweet the same ticker
within a short window. Keyed by ticker, 5-minute TTL.
"""

from dataclasses import asdict
import json
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
        from consensus_engine.models import (
            CrossReferenceResult,
            OptionsResult,
            ScoreBreakdown,
            TechnicalFilter,
            TechnicalResult,
        )

        raw = await get_xref_from_db(ticker)
        if raw is not None:
            data = json.loads(raw)
            data["breakdown"] = ScoreBreakdown(**data["breakdown"])

            technical_data = data.get("technical")
            if technical_data:
                technical_data["filters"] = [
                    TechnicalFilter(**f) for f in technical_data.get("filters", [])
                ]
                data["technical"] = TechnicalResult(**technical_data)

            options_data = data.get("options")
            if options_data:
                data["options"] = OptionsResult(**options_data)

            result = CrossReferenceResult(**data)
            _cache.put(ticker, result)
            return result
    except Exception:
        pass
    return None


async def cache_xref(ticker: str, result: Any) -> None:
    _cache.put(ticker, result)
    try:
        from consensus_engine.db import set_xref_in_db
        await set_xref_in_db(ticker, json.dumps(asdict(result)))
    except Exception:
        pass


def clear_xref_cache() -> None:
    _cache._entries.clear()
