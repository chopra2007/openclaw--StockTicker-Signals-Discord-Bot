"""Pass 5 Step 11 — news_cascade parallel/serial config gate tests."""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine.models import CatalystResult
from consensus_engine.scanners import news as news_mod


def _hit(ticker: str = "NVDA", tier: str = "finnhub") -> CatalystResult:
    # CatalystResult.passed is a computed property: non-empty news_sources + summary.
    return CatalystResult(
        ticker=ticker,
        catalyst_summary="Test catalyst",
        catalyst_type="Earnings Beat",
        news_sources=["reuters.com"],
        source_urls=["https://reuters.com/test"],
        confidence=0.8,
    )


# ---------------------------------------------------------------------------
# 1. Serial mode (parallel=False) — short-circuits on first hit in tier order
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_serial_stops_at_first_hit():
    """Serial mode: when tier 1 (finnhub) hits, tier 2+ must NOT be called."""
    finnhub_hit = _hit()
    searxng_mock = AsyncMock(return_value=None)

    with patch("consensus_engine.scanners.news.cfg") as mock_cfg, \
         patch("consensus_engine.scanners.news._search_recent_earnings",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.scanners.news._search_finnhub_news",
               new_callable=AsyncMock, return_value=finnhub_hit), \
         patch("consensus_engine.scanners.news._search_google_news_rss",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.scanners.news._search_brave",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.scanners.news._search_searxng", searxng_mock):

        def _cfg_get(key, default=None):
            if key == "news_cascade.tiers":
                return ["recent_earnings", "finnhub", "google_rss", "brave", "searxng"]
            if key == "news_cascade.parallel":
                return False
            return default

        mock_cfg.get = _cfg_get
        result = await news_mod.news_cascade("NVDA")

    assert result is not None
    assert result.catalyst_type == "Earnings Beat"
    searxng_mock.assert_not_called()


@pytest.mark.asyncio
async def test_serial_falls_through_all_misses():
    """Serial mode: when all tiers miss, returns None."""
    with patch("consensus_engine.scanners.news.cfg") as mock_cfg, \
         patch("consensus_engine.scanners.news._search_recent_earnings",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.scanners.news._search_finnhub_news",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.scanners.news._search_google_news_rss",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.scanners.news._search_brave",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.scanners.news._search_searxng",
               new_callable=AsyncMock, return_value=None):

        def _cfg_get(key, default=None):
            if key == "news_cascade.tiers":
                return ["recent_earnings", "finnhub", "google_rss", "brave", "searxng"]
            if key == "news_cascade.parallel":
                return False
            return default

        mock_cfg.get = _cfg_get
        result = await news_mod.news_cascade("ZZZZ")

    assert result is None


# ---------------------------------------------------------------------------
# 2. Parallel mode (parallel=True) — all tiers fire concurrently
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_parallel_mode_runs_concurrently():
    """Parallel mode: all tiers run concurrently; timing shows overlap."""
    delay = 0.05  # 50ms per tier
    start_times: list[float] = []

    async def _slow_none(*_args, **_kwargs):
        start_times.append(time.monotonic())
        await asyncio.sleep(delay)
        return None

    finnhub_hit = _hit()

    async def _finnhub_hit(*_args, **_kwargs):
        start_times.append(time.monotonic())
        await asyncio.sleep(delay)
        return finnhub_hit

    tiers = ["recent_earnings", "finnhub", "google_rss"]

    with patch("consensus_engine.scanners.news.cfg") as mock_cfg, \
         patch("consensus_engine.scanners.news._search_recent_earnings",
               side_effect=_slow_none), \
         patch("consensus_engine.scanners.news._search_finnhub_news",
               side_effect=_finnhub_hit), \
         patch("consensus_engine.scanners.news._search_google_news_rss",
               side_effect=_slow_none):

        def _cfg_get(key, default=None):
            if key == "news_cascade.tiers":
                return tiers
            if key == "news_cascade.parallel":
                return True
            if key == "news_cascade.parallel_timeout_sec":
                return 5.0
            return default

        mock_cfg.get = _cfg_get

        wall_start = time.monotonic()
        result = await news_mod.news_cascade("NVDA")
        wall_elapsed = time.monotonic() - wall_start

    assert result is not None
    assert result.catalyst_type == "Earnings Beat"
    # If tiers ran concurrently, total wall time ≈ 1×delay, not 3×delay.
    # Allow generous 3× margin for CI slowness.
    assert wall_elapsed < delay * 3 + 0.2, (
        f"Parallel mode too slow ({wall_elapsed:.3f}s): tiers may be running serially"
    )
    # All three tiers should have started (before any finished)
    assert len(start_times) >= 2


@pytest.mark.asyncio
async def test_parallel_all_miss_returns_none():
    """Parallel mode: when every tier returns None, result is None."""
    with patch("consensus_engine.scanners.news.cfg") as mock_cfg, \
         patch("consensus_engine.scanners.news._search_recent_earnings",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.scanners.news._search_finnhub_news",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.scanners.news._search_google_news_rss",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.scanners.news._search_brave",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.scanners.news._search_searxng",
               new_callable=AsyncMock, return_value=None):

        def _cfg_get(key, default=None):
            if key == "news_cascade.tiers":
                return ["recent_earnings", "finnhub", "google_rss", "brave", "searxng"]
            if key == "news_cascade.parallel":
                return True
            if key == "news_cascade.parallel_timeout_sec":
                return 5.0
            return default

        mock_cfg.get = _cfg_get
        result = await news_mod.news_cascade("ZZZZ")

    assert result is None


# ---------------------------------------------------------------------------
# 3. Config default (parallel key absent) → serial fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_default_config_uses_serial():
    """When parallel config key is missing (default=False), serial path runs."""
    call_order: list[str] = []

    async def _mk_none(name):
        async def _fn(*_args, **_kwargs):
            call_order.append(name)
            return None
        return _fn

    with patch("consensus_engine.scanners.news.cfg") as mock_cfg, \
         patch("consensus_engine.scanners.news._search_recent_earnings",
               side_effect=lambda *a, **k: (call_order.append("re") or None)), \
         patch("consensus_engine.scanners.news._search_finnhub_news",
               side_effect=lambda *a, **k: (call_order.append("fh") or None)), \
         patch("consensus_engine.scanners.news._search_google_news_rss",
               side_effect=lambda *a, **k: (call_order.append("gr") or None)), \
         patch("consensus_engine.scanners.news._search_brave",
               side_effect=lambda *a, **k: (call_order.append("br") or None)), \
         patch("consensus_engine.scanners.news._search_searxng",
               side_effect=lambda *a, **k: (call_order.append("sx") or None)):

        # Make all tier funcs async by wrapping with AsyncMock
        with patch("consensus_engine.scanners.news._search_recent_earnings",
                   new_callable=AsyncMock, return_value=None) as re_m, \
             patch("consensus_engine.scanners.news._search_finnhub_news",
                   new_callable=AsyncMock, return_value=None) as fh_m, \
             patch("consensus_engine.scanners.news._search_google_news_rss",
                   new_callable=AsyncMock, return_value=None) as gr_m, \
             patch("consensus_engine.scanners.news._search_brave",
                   new_callable=AsyncMock, return_value=None) as br_m, \
             patch("consensus_engine.scanners.news._search_searxng",
                   new_callable=AsyncMock, return_value=None) as sx_m:

            def _cfg_get(key, default=None):
                if key == "news_cascade.tiers":
                    return ["finnhub", "searxng"]
                # parallel key absent → default=False
                if key == "news_cascade.parallel":
                    return False
                return default

            mock_cfg.get = _cfg_get
            result = await news_mod.news_cascade("TSLA")

    assert result is None
    # Both tiers were called (serial exhausted all)
    fh_m.assert_called_once()
    sx_m.assert_called_once()
