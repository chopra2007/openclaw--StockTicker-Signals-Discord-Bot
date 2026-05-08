"""15-min TTL cache for !all command results.

Wraps the PR3 namespaced xref_cache with `key_prefix="all"` and
`ttl_seconds=900` so the !all payload coexists with the regular
cross_reference cache rows without colliding.

The payload is a plain dict with shape::

    {"embed": <discord embed dict>, "vault_md": <str>, "cached_at": <float>}

It is JSON-serialized when written through to the DB, so the embed and
vault markdown round-trip cleanly through L1 (in-memory) and L2 (DB).
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

from consensus_engine.utils import xref_cache

log = logging.getLogger("consensus_engine.alerts.all_command.cache")

KEY_PREFIX = "all"
TTL_SECONDS = 900  # 15 minutes per locked decision D10


async def get_cached_all(ticker: str) -> Optional[dict]:
    """Read the !all payload for `ticker`. Returns None on miss/corrupt blob."""
    payload = await xref_cache.get_cached_xref(ticker, key_prefix=KEY_PREFIX)
    if payload is None:
        return None
    if not isinstance(payload, dict):
        log.warning(
            "cache.get_cached_all: unexpected payload type %s for %s; treating as miss",
            type(payload).__name__, ticker,
        )
        return None
    return payload


async def set_cached_all(ticker: str, payload: dict) -> None:
    """Write `payload` ({embed, vault_md, cached_at}) to the namespaced cache."""
    await xref_cache.cache_xref(
        ticker, payload, ttl_seconds=TTL_SECONDS, key_prefix=KEY_PREFIX,
    )


async def all_with_single_flight(
    ticker: str,
    compute_fn: Callable[[], Awaitable[dict]],
) -> dict:
    """Cache + single-flight wrapper for !all.

    Concurrent callers for the same ticker share one `compute_fn()`
    invocation via PR3's `single_flight_get`. On hit, returns the cached
    dict directly. On miss, runs compute_fn() under the per-ticker lock and
    caches the result for 15 min.
    """
    return await xref_cache.single_flight_get(
        ticker,
        compute_fn,
        key_prefix=KEY_PREFIX,
        ttl_seconds=TTL_SECONDS,
    )
