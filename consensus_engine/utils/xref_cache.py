"""In-memory cross-reference result cache with TTL.

Prevents redundant API calls when multiple analysts tweet the same ticker
within a short window. Keyed by ticker, 5-minute TTL by default.

PR3 (all-command-rebuild): adds `key_prefix` namespacing so the !all command
can share the same cache table without colliding with the cross_reference
default callers, and adds a per-key asyncio.Lock single-flight to dedup
concurrent rebuilds for the same key.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, is_dataclass
import json
import time
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger(__name__)


def _make_key(ticker: str, key_prefix: str = "") -> str:
    """Build the namespaced cache key.

    Empty prefix → bare ticker (preserves rows written before PR3).
    """
    return f"{key_prefix}:{ticker}" if key_prefix else ticker


class XRefCache:
    """Simple in-memory cache with per-entry TTL and prefix namespacing.

    Storage layout for `_entries[key]` is `(timestamp, value)` (preserved from
    the pre-PR3 shape so external callers that poke the dict directly — e.g.
    `tests/test_xref_cache.py::test_cache_expired` — keep working).
    Per-entry TTL overrides live in a parallel dict.
    """

    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        self._entries: dict[str, tuple[float, Any]] = {}
        self._ttls: dict[str, int] = {}

    def _ttl_for(self, key: str) -> int:
        return self._ttls.get(key, self.ttl_seconds)

    def get(self, ticker: str, key_prefix: str = "") -> Optional[Any]:
        """Get cached result, or None if missing/expired."""
        key = _make_key(ticker, key_prefix)
        entry = self._entries.get(key)
        if entry is None:
            return None
        timestamp, value = entry
        if time.time() - timestamp > self._ttl_for(key):
            del self._entries[key]
            self._ttls.pop(key, None)
            return None
        return value

    def put(
        self,
        ticker: str,
        value: Any,
        ttl_seconds: int | None = None,
        key_prefix: str = "",
    ) -> None:
        """Cache a result for a ticker (optionally namespaced).

        If `ttl_seconds` is None, the cache's class-level default (set at
        construction) is used. This preserves the pre-PR3 contract where
        `XRefCache(ttl_seconds=1)` made all entries expire after 1 second.
        """
        key = _make_key(ticker, key_prefix)
        self._entries[key] = (time.time(), value)
        self._ttls[key] = ttl_seconds if ttl_seconds is not None else self.ttl_seconds


# Module-level singleton
_cache = XRefCache(ttl_seconds=300)

# Per-key single-flight locks. Created lazily inside an async context.
_inflight_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


def _rehydrate_xref_models(data: dict) -> Any:
    """Rebuild a CrossReferenceResult from a plain dict (DB shape).

    Lives here so the DB miss path mirrors the structure callers expect.
    Raises on schema drift; caller treats as miss.
    """
    from consensus_engine.models import (
        CrossReferenceResult,
        OptionsResult,
        ScoreBreakdown,
        TechnicalFilter,
        TechnicalResult,
    )

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

    return CrossReferenceResult(**data)


async def get_cached_xref(
    ticker: str,
    key_prefix: str = "",
) -> Optional[Any]:
    """Read from L1 (in-memory) then L2 (DB cache table).

    On any DB-side deserialization failure, log a warning and treat as miss
    (per plan §7 row 'Cache deserialization failure').
    """
    # L1: in-memory
    hit = _cache.get(ticker, key_prefix=key_prefix)
    if hit is not None:
        return hit
    # L2: DB
    try:
        from consensus_engine.db import get_xref_from_db

        raw = await get_xref_from_db(ticker, key_prefix=key_prefix)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            # Best-effort rehydration: if it's the legacy CrossReferenceResult
            # shape, rebuild nested models. Otherwise return the parsed dict
            # so namespaced payloads (e.g. all_command) round-trip as plain.
            if isinstance(data, dict) and "breakdown" in data:
                result = _rehydrate_xref_models(data)
            else:
                result = data
        except Exception as exc:  # noqa: BLE001 — corrupt blob is an expected miss
            log.warning(
                "xref_cache deserialization failed for %s (prefix=%r): %s; treating as miss",
                ticker,
                key_prefix,
                exc,
            )
            return None
        _cache.put(ticker, result, ttl_seconds=_cache.ttl_seconds, key_prefix=key_prefix)
        return result
    except Exception as exc:  # noqa: BLE001 — DB outage etc → miss, not crash
        log.debug("xref_cache DB read failed for %s: %s", ticker, exc)
        return None


async def cache_xref(
    ticker: str,
    result: Any,
    ttl_seconds: int = 300,
    key_prefix: str = "",
) -> None:
    """Write through to L1 + L2."""
    _cache.put(ticker, result, ttl_seconds=ttl_seconds, key_prefix=key_prefix)
    try:
        from consensus_engine.db import set_xref_in_db

        if is_dataclass(result):
            payload = json.dumps(asdict(result))
        else:
            payload = json.dumps(result)
        await set_xref_in_db(ticker, payload, key_prefix=key_prefix)
    except Exception as exc:  # noqa: BLE001
        log.debug("xref_cache DB write failed for %s: %s", ticker, exc)


def clear_xref_cache(
    ticker: Optional[str] = None,
    key_prefix: str = "",
) -> None:
    """Clear the L1 cache.

    - No args → wipe everything (existing behavior).
    - Ticker only → wipe just that ticker's bare-key entry.
    - Ticker + prefix → wipe the namespaced entry.
    - Prefix only → wipe every entry under that prefix.
    """
    if ticker is None and not key_prefix:
        _cache._entries.clear()
        _cache._ttls.clear()
        return
    if ticker is not None:
        key = _make_key(ticker, key_prefix)
        _cache._entries.pop(key, None)
        _cache._ttls.pop(key, None)
        return
    # Prefix-only sweep
    prefix = f"{key_prefix}:"
    for k in [k for k in _cache._entries if k.startswith(prefix)]:
        del _cache._entries[k]
        _cache._ttls.pop(k, None)


async def _get_inflight_lock(key: str) -> asyncio.Lock:
    """Return a process-wide asyncio.Lock for `key`, creating it on demand."""
    async with _locks_guard:
        lock = _inflight_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _inflight_locks[key] = lock
        return lock


async def single_flight_get(
    ticker: str,
    compute_fn: Callable[[], Awaitable[Any]],
    *,
    key_prefix: str = "",
    ttl_seconds: int = 300,
) -> Any:
    """Cache-aware single-flight wrapper.

    Concurrent callers for the same `(key_prefix, ticker)` share one
    `compute_fn()` invocation: the first acquires the lock and runs it,
    populating the cache; subsequent callers block on the lock and then
    return the now-cached value without recomputing. Per plan §7 row
    'H-STAMPEDE'.
    """
    key = _make_key(ticker, key_prefix)
    cached = await get_cached_xref(ticker, key_prefix=key_prefix)
    if cached is not None:
        return cached

    lock = await _get_inflight_lock(key)
    async with lock:
        # Re-check after acquiring lock — winner already cached the value.
        cached = await get_cached_xref(ticker, key_prefix=key_prefix)
        if cached is not None:
            return cached
        value = await compute_fn()
        if value is not None:
            await cache_xref(
                ticker,
                value,
                ttl_seconds=ttl_seconds,
                key_prefix=key_prefix,
            )
        return value
