"""Tests for 4-tier news cascade."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from consensus_engine.scanners.news import news_cascade, _search_finnhub_news, _search_google_news_rss
from consensus_engine.scanners.searxng import search_searxng
from consensus_engine.models import CatalystResult


@pytest.mark.asyncio
async def test_finnhub_news_returns_catalyst():
    """Tier 1 hit should stop the cascade."""
    mock_result = CatalystResult(
        ticker="NVDA",
        catalyst_summary="NVDA beats earnings estimates",
        catalyst_type="Earnings Beat",
        news_sources=["reuters.com"],
        source_urls=["https://reuters.com/nvda-earnings"],
        confidence=0.8,
    )
    with patch("consensus_engine.scanners.news._search_finnhub_news",
               new_callable=AsyncMock, return_value=mock_result):
        result = await news_cascade("NVDA")
        assert result is not None
        assert result.catalyst_type == "Earnings Beat"
        assert result.news_sources == ["reuters.com"]


@pytest.mark.asyncio
async def test_cascade_falls_through_to_google_rss():
    """If Finnhub returns nothing, try Google RSS."""
    mock_google = CatalystResult(
        ticker="TSLA",
        catalyst_summary="Tesla analyst upgrade",
        catalyst_type="Analyst Upgrade",
        news_sources=["cnbc.com"],
        source_urls=["https://cnbc.com/tsla"],
        confidence=0.7,
    )
    with patch("consensus_engine.scanners.news._search_finnhub_news",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.scanners.news._search_google_news_rss",
               new_callable=AsyncMock, return_value=mock_google):
        result = await news_cascade("TSLA")
        assert result is not None
        assert result.catalyst_type == "Analyst Upgrade"


@pytest.mark.asyncio
async def test_cascade_all_miss():
    """If all tiers miss, return None."""
    with patch("consensus_engine.scanners.news._search_finnhub_news",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.scanners.news._search_google_news_rss",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.scanners.news._search_brave",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.scanners.news._search_searxng",
               new_callable=AsyncMock, return_value=None):
        result = await news_cascade("ZZZZ")
        assert result is None


def test_searxng_parse_results():
    """SearXNG JSON response should be parseable."""
    from consensus_engine.scanners.searxng import _parse_searxng_results
    raw = {
        "results": [
            {"title": "NVDA earnings beat estimates", "url": "https://reuters.com/nvda", "content": "NVIDIA beat..."},
            {"title": "Random blog post", "url": "https://random.blog/nvda", "content": "My thoughts..."},
        ]
    }
    results = _parse_searxng_results(raw)
    assert len(results) == 2
    assert results[0]["title"] == "NVDA earnings beat estimates"
    assert results[0]["url"] == "https://reuters.com/nvda"
