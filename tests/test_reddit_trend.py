"""Tests for the Reddit trend pipeline."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_parse_post_extracts_tickers():
    from consensus_engine.scanners.reddit_trend import _extract_tickers_from_text
    tickers = _extract_tickers_from_text("NVDA earnings beat, also watching TSLA calls")
    assert "NVDA" in tickers
    assert "TSLA" in tickers
    # Blacklisted words filtered
    assert "THE" not in tickers
    assert "ARE" not in tickers


@pytest.mark.asyncio
async def test_compute_trend_metrics_threshold():
    from consensus_engine.scanners.reddit_trend import _compute_metrics
    posts = [
        {"ticker": "NVDA", "author": "user1", "title": "NVDA buy", "created_utc": 1000000},
        {"ticker": "NVDA", "author": "user2", "title": "NVDA calls", "created_utc": 1000100},
        {"ticker": "NVDA", "author": "user3", "title": "NVDA breakout", "created_utc": 1000200},
        {"ticker": "NVDA", "author": "user1", "title": "NVDA again", "created_utc": 1000300},
        {"ticker": "NVDA", "author": "user4", "title": "NVDA up", "created_utc": 1000400},
        {"ticker": "NVDA", "author": "user5", "title": "NVDA moon", "created_utc": 1000500},
        {"ticker": "NVDA", "author": "user6", "title": "NVDA squeeze", "created_utc": 1000600},
        {"ticker": "NVDA", "author": "user7", "title": "NVDA nice", "created_utc": 1000700},
        {"ticker": "TSLA", "author": "user1", "title": "TSLA down", "created_utc": 1000000},
    ]
    metrics = _compute_metrics(posts)
    assert metrics["NVDA"]["mentions"] == 8
    assert metrics["NVDA"]["unique_authors"] == 7
    assert "TSLA" in metrics


@pytest.mark.asyncio
async def test_filter_trending_passes_threshold():
    from consensus_engine.scanners.reddit_trend import _filter_trending
    metrics = {
        "NVDA": {"mentions": 10, "unique_authors": 6, "momentum": 2.0},
        "TSLA": {"mentions": 5, "unique_authors": 3, "momentum": 1.2},
        "AAPL": {"mentions": 9, "unique_authors": 2, "momentum": 1.0},
    }
    # NVDA: passes (mentions >= 8 AND unique_authors >= 5)
    # TSLA: fails both conditions
    # AAPL: fails (unique_authors 2 < 5 AND momentum 1.0 not > 1.5)
    trending = _filter_trending(metrics)
    tickers = [t["ticker"] for t in trending]
    assert "NVDA" in tickers
    assert "TSLA" not in tickers
    assert "AAPL" not in tickers
