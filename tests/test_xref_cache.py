"""Tests for cross-reference result cache."""
import time
import pytest
from consensus_engine.utils.xref_cache import XRefCache


def test_cache_miss():
    cache = XRefCache(ttl_seconds=300)
    assert cache.get("NVDA") is None


def test_cache_hit():
    cache = XRefCache(ttl_seconds=300)
    cache.put("NVDA", {"score": 75})
    assert cache.get("NVDA") == {"score": 75}


def test_cache_expired():
    cache = XRefCache(ttl_seconds=1)
    cache.put("NVDA", {"score": 75})
    # Manually expire
    cache._entries["NVDA"] = (time.time() - 2, {"score": 75})
    assert cache.get("NVDA") is None


def test_cache_different_tickers():
    cache = XRefCache(ttl_seconds=300)
    cache.put("NVDA", {"score": 75})
    cache.put("TSLA", {"score": 50})
    assert cache.get("NVDA") == {"score": 75}
    assert cache.get("TSLA") == {"score": 50}
