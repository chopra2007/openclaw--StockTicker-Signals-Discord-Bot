"""PR3 cache namespacing + single-flight tests.

Covers:
- key_prefix isolation (default vs prefixed)
- backward-compatible bare-ticker behavior
- corrupt-blob deserialization is treated as miss
- single_flight_get dedups concurrent computes for the same key
"""
from __future__ import annotations

import asyncio

import pytest

from consensus_engine import config as cfg, db
from consensus_engine.utils.xref_cache import (
    XRefCache,
    cache_xref,
    clear_xref_cache,
    get_cached_xref,
    single_flight_get,
)


@pytest.fixture
async def setup_db(tmp_path):
    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "test.db")}
    clear_xref_cache()
    await db.init_db()
    yield
    clear_xref_cache()
    await db.close_db()


# --- L1-only behavior --------------------------------------------------------

def test_xrefcache_class_prefix_isolation():
    """Bare and prefixed entries must not collide in the L1 dict."""
    cache = XRefCache(ttl_seconds=300)
    cache.put("NVDA", {"x": 1})
    cache.put("NVDA", {"y": 2}, key_prefix="all")
    assert cache.get("NVDA") == {"x": 1}
    assert cache.get("NVDA", key_prefix="all") == {"y": 2}


def test_xrefcache_class_per_entry_ttl_expiry():
    """put() honors per-entry ttl_seconds, independent of class default."""
    cache = XRefCache(ttl_seconds=300)
    cache.put("NVDA", {"x": 1}, ttl_seconds=1)
    # Force expiry without sleeping
    key = next(iter(cache._entries))
    ts, val = cache._entries[key]
    cache._entries[key] = (ts - 5, val)
    assert cache.get("NVDA") is None


# --- Module-level helpers (L1 + L2) -----------------------------------------

@pytest.mark.asyncio
async def test_cache_default_no_prefix(setup_db):
    """Existing API shape (no key_prefix) round-trips."""
    await cache_xref("NVDA", {"score": 75})
    got = await get_cached_xref("NVDA")
    assert got == {"score": 75}


@pytest.mark.asyncio
async def test_cache_prefix_isolation(setup_db):
    """Same ticker under two prefixes returns two distinct payloads."""
    await cache_xref("NVDA", {"a": 1})
    await cache_xref("NVDA", {"b": 2}, key_prefix="all")
    assert await get_cached_xref("NVDA") == {"a": 1}
    assert await get_cached_xref("NVDA", key_prefix="all") == {"b": 2}


@pytest.mark.asyncio
async def test_cache_prefix_does_not_collide_default(setup_db):
    """Writing under a prefix must not overwrite the bare-ticker entry."""
    await cache_xref("NVDA", {"a": 1})
    await cache_xref("NVDA", {"b": 2}, key_prefix="all")
    # Wipe L1 so we test L2 isolation explicitly
    clear_xref_cache()
    assert await get_cached_xref("NVDA") == {"a": 1}
    assert await get_cached_xref("NVDA", key_prefix="all") == {"b": 2}


@pytest.mark.asyncio
async def test_cache_corrupt_blob_returns_miss(setup_db, caplog):
    """A corrupt JSON blob in the DB must be treated as a cache miss."""
    import logging

    # Manually insert a non-JSON blob into the DB row for ('all:NVDA', ...)
    conn = await db.get_db()
    import time as _time

    await conn.execute(
        "INSERT OR REPLACE INTO xref_cache (ticker, result_json, cached_at) VALUES (?, ?, ?)",
        ("all:NVDA", "{not valid json", _time.time()),
    )
    await conn.commit()

    clear_xref_cache()  # ensure L1 doesn't shadow the read
    with caplog.at_level(logging.WARNING):
        got = await get_cached_xref("NVDA", key_prefix="all")
    assert got is None
    assert any(
        "deserialization failed" in rec.message for rec in caplog.records
    )


# --- Single-flight ----------------------------------------------------------

@pytest.mark.asyncio
async def test_single_flight_dedups_concurrent_calls(setup_db):
    """Two concurrent callers for the same key share one compute_fn invocation."""
    call_count = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_compute():
        nonlocal call_count
        call_count += 1
        started.set()
        # Hold the lock long enough for the second caller to block on it.
        await release.wait()
        return {"computed": call_count}

    async def caller():
        return await single_flight_get(
            "AAPL",
            slow_compute,
            key_prefix="sf-test",
            ttl_seconds=900,
        )

    task_a = asyncio.create_task(caller())
    # Wait until A is inside compute_fn so B is guaranteed to find a miss
    # (no L1 hit yet) and then block on the lock.
    await started.wait()
    task_b = asyncio.create_task(caller())
    # Give B a tick to reach the lock.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    release.set()

    result_a, result_b = await asyncio.gather(task_a, task_b)
    assert call_count == 1
    assert result_a == {"computed": 1}
    assert result_b == {"computed": 1}


@pytest.mark.asyncio
async def test_single_flight_cache_hit_short_circuits(setup_db):
    """If the value is already cached, compute_fn must not be called at all."""
    call_count = 0

    async def compute():
        nonlocal call_count
        call_count += 1
        return {"v": "computed"}

    await cache_xref("MSFT", {"v": "preseeded"}, ttl_seconds=900, key_prefix="sf-hit")
    got = await single_flight_get(
        "MSFT", compute, key_prefix="sf-hit", ttl_seconds=900,
    )
    assert call_count == 0
    assert got == {"v": "preseeded"}
