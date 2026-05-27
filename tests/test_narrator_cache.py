"""Pass 5 Step 11 — narrator synthesis cache: hit/miss/eviction/flush tests."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine.alerts.all_command import narrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_cache():
    narrator._synthesis_cache.clear()


def _make_key(ticker="NVDA", json_str="{}", direction_source="legacy"):
    return narrator._cache_key(ticker, json_str, direction_source)


# ---------------------------------------------------------------------------
# Unit: _cache_key is deterministic and includes all three inputs
# ---------------------------------------------------------------------------

def test_cache_key_deterministic():
    k1 = _make_key("NVDA", '{"a":1}', "legacy")
    k2 = _make_key("NVDA", '{"a":1}', "legacy")
    assert k1 == k2


def test_cache_key_differs_on_ticker():
    k1 = _make_key("NVDA", "{}", "legacy")
    k2 = _make_key("AMD", "{}", "legacy")
    assert k1 != k2


def test_cache_key_differs_on_direction_source():
    k1 = _make_key("NVDA", "{}", "legacy")
    k2 = _make_key("NVDA", "{}", "structured")
    assert k1 != k2


def test_cache_key_differs_on_json():
    k1 = _make_key("NVDA", '{"x":1}', "legacy")
    k2 = _make_key("NVDA", '{"x":2}', "legacy")
    assert k1 != k2


# ---------------------------------------------------------------------------
# Unit: cache miss returns None; put + get returns value
# ---------------------------------------------------------------------------

def test_cache_miss_returns_none():
    _reset_cache()
    assert narrator._cache_get("nonexistent_key") is None


def test_cache_put_then_get():
    _reset_cache()
    key = _make_key("TSLA")
    narrator._cache_put(key, ("narrative text", "ok"))
    result = narrator._cache_get(key)
    assert result == ("narrative text", "ok")


# ---------------------------------------------------------------------------
# Unit: TTL expiry — entry is a miss after TTL seconds
# ---------------------------------------------------------------------------

def test_cache_ttl_expiry():
    _reset_cache()
    key = _make_key("AAPL")
    # Inject entry with timestamp in the past (TTL + 1 seconds ago)
    past_ts = time.monotonic() - (narrator._CACHE_TTL + 1)
    narrator._synthesis_cache[key] = (past_ts, ("old text", "ok"))

    result = narrator._cache_get(key)
    assert result is None  # hard-expired
    assert key not in narrator._synthesis_cache  # also evicted


def test_cache_hit_within_ttl():
    _reset_cache()
    key = _make_key("MSFT")
    narrator._cache_put(key, ("fresh text", "ok"))
    # Should still be valid immediately
    result = narrator._cache_get(key)
    assert result is not None
    assert result[0] == "fresh text"


# ---------------------------------------------------------------------------
# Unit: LRU eviction at max 100 entries
# ---------------------------------------------------------------------------

def test_cache_lru_eviction():
    _reset_cache()
    # Fill to _CACHE_MAX
    for i in range(narrator._CACHE_MAX):
        k = _make_key(ticker=f"T{i:04d}")
        narrator._cache_put(k, (f"text_{i}", "ok"))

    assert len(narrator._synthesis_cache) == narrator._CACHE_MAX

    # Access the oldest entry (T0000) to promote it in LRU order
    k_first = _make_key(ticker="T0000")
    narrator._cache_get(k_first)  # moves T0000 to end

    # Insert one more entry — should evict the new LRU tail (T0001, not T0000)
    k_new = _make_key(ticker="TNEW")
    narrator._cache_put(k_new, ("new", "ok"))

    assert len(narrator._synthesis_cache) == narrator._CACHE_MAX
    # T0000 was promoted so it should still be present
    assert narrator._cache_get(k_first) is not None
    # k_new was just inserted so it should be present
    assert narrator._cache_get(k_new) is not None


# ---------------------------------------------------------------------------
# Unit: flush_synthesis_cache clears all entries
# ---------------------------------------------------------------------------

def test_flush_clears_cache():
    _reset_cache()
    for i in range(5):
        k = _make_key(ticker=f"F{i}")
        narrator._cache_put(k, ("x", "ok"))
    assert len(narrator._synthesis_cache) == 5

    narrator.flush_synthesis_cache()
    assert len(narrator._synthesis_cache) == 0


# ---------------------------------------------------------------------------
# Integration: synthesize_narrative returns cached value on second call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_synthesize_narrative_cache_hit():
    """Second identical call within TTL must not invoke the LLM."""
    _reset_cache()

    from consensus_engine.alerts.all_command.structured_fields import StructuredFields
    from consensus_engine.models import ScoreBreakdown

    sf = StructuredFields(
        direction="BULLISH",
        confidence_label="HIGH",
        current_price=950.0,
        sl=920.0,
        tp1=980.0,
        tp2=1010.0,
        tp3=1050.0,
    )
    sb = ScoreBreakdown(base=75)

    call_count = 0

    async def _fake_synthesis(messages, deadline):
        nonlocal call_count
        call_count += 1
        return "**TL;DR:** fake narrative"

    # The cache lookup calls `_cfg.get` inside synthesize_narrative via the
    # local import `from consensus_engine import config as _cfg`.  Patch at
    # the module level so both calls see the same mock.
    def _fake_get(key, default=None):
        if key == "all_command.cache.enabled":
            return True
        if key == "all_command.direction_source":
            return "legacy"
        if key == "all_command.swing_v2_enabled":
            return False
        return default

    with patch("consensus_engine.config.get", side_effect=_fake_get), \
         patch("consensus_engine.alerts.all_command.narrator._invoke_synthesis",
               side_effect=_fake_synthesis), \
         patch("consensus_engine.alerts.all_command.quality_bar.has_required_sections",
               return_value=True), \
         patch("consensus_engine.alerts.all_command.output_filter.sanitize_or_retry",
               new_callable=AsyncMock,
               return_value=("**TL;DR:** fake narrative", "ok")):

        # First call — cache miss, should invoke LLM
        r1, s1 = await narrator.synthesize_narrative(
            ticker="NVDA",
            structured=sf,
            score_breakdown=sb,
            sanitized_searxng=[],
            sanitized_chat=[],
            sanitized_brief=[],
            vault_summary="",
            structured_data_json="{}",
            deadline_seconds=30.0,
        )
        # Second identical call — cache hit, LLM must NOT be called again
        r2, s2 = await narrator.synthesize_narrative(
            ticker="NVDA",
            structured=sf,
            score_breakdown=sb,
            sanitized_searxng=[],
            sanitized_chat=[],
            sanitized_brief=[],
            vault_summary="",
            structured_data_json="{}",
            deadline_seconds=30.0,
        )

    assert s1 == "ok"
    assert s2 == "ok"
    assert r1 == r2
    assert call_count == 1, f"Expected 1 LLM call, got {call_count}"


@pytest.mark.asyncio
async def test_synthesize_narrative_cache_miss_after_ttl():
    """Call after TTL expiry must invoke the LLM again (cold path)."""
    _reset_cache()

    from consensus_engine.alerts.all_command.structured_fields import StructuredFields
    from consensus_engine.models import ScoreBreakdown

    sf = StructuredFields(direction="BULLISH", confidence_label="LOW",
                          current_price=100.0)
    sb = ScoreBreakdown(base=30)

    call_count = 0

    async def _fake_synthesis(messages, deadline):
        nonlocal call_count
        call_count += 1
        return "**TL;DR:** fresh narrative"

    def _fake_get(key, default=None):
        if key == "all_command.cache.enabled":
            return True
        if key == "all_command.direction_source":
            return "legacy"
        if key == "all_command.swing_v2_enabled":
            return False
        return default

    with patch("consensus_engine.config.get", side_effect=_fake_get), \
         patch("consensus_engine.alerts.all_command.narrator._invoke_synthesis",
               side_effect=_fake_synthesis), \
         patch("consensus_engine.alerts.all_command.quality_bar.has_required_sections",
               return_value=True), \
         patch("consensus_engine.alerts.all_command.output_filter.sanitize_or_retry",
               new_callable=AsyncMock,
               return_value=("**TL;DR:** fresh narrative", "ok")):

        await narrator.synthesize_narrative(
            ticker="AMD", structured=sf, score_breakdown=sb,
            sanitized_searxng=[], sanitized_chat=[], sanitized_brief=[],
            vault_summary="", structured_data_json="{}", deadline_seconds=30.0,
        )
        # Manually expire the cache entry
        for k in list(narrator._synthesis_cache.keys()):
            ts, val = narrator._synthesis_cache[k]
            narrator._synthesis_cache[k] = (ts - narrator._CACHE_TTL - 1, val)

        await narrator.synthesize_narrative(
            ticker="AMD", structured=sf, score_breakdown=sb,
            sanitized_searxng=[], sanitized_chat=[], sanitized_brief=[],
            vault_summary="", structured_data_json="{}", deadline_seconds=30.0,
        )

    assert call_count == 2, f"Expected 2 LLM calls (TTL expired), got {call_count}"
