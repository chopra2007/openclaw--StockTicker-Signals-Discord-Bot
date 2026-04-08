"""Tests for HTTP adapters with mocked responses."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from consensus_engine.api_adapters import (
    BraveAdapter,
    ExaAdapter,
    FinnhubAdapter,
    FirecrawlAdapter,
    SerpApiAdapter,
)
from consensus_engine.adapter_protocols import FinnhubContext, SearchHit, FirecrawlPage


def _mock_session():
    """Create a MagicMock session whose .get/.post return async context managers."""
    session = MagicMock()
    return session


def _ctx_manager(status=200, json_data=None):
    """Return an object usable as `async with session.get(...) as resp:`."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# FinnhubAdapter
# ---------------------------------------------------------------------------

class TestFinnhubAdapter:
    async def test_get_context_success(self):
        session = _mock_session()
        quote_cm = _ctx_manager(json_data={"c": 150.0, "pc": 145.0, "v": 50000})
        news_cm = _ctx_manager(json_data=[
            {"headline": "NVDA beats earnings", "source": "Reuters"},
            {"headline": "AI chip demand surges", "source": "CNBC"},
        ])
        session.get.side_effect = [quote_cm, news_cm]

        adapter = FinnhubAdapter(session, api_key="test-key")
        ctx = await adapter.get_context("NVDA")

        assert isinstance(ctx, FinnhubContext)
        assert ctx.price == 150.0
        assert ctx.prev_close == 145.0
        assert abs(ctx.change_pct - 3.448) < 0.01
        assert ctx.market_ok is True
        assert len(ctx.news_headlines) == 2

    async def test_get_context_no_key(self):
        session = _mock_session()
        adapter = FinnhubAdapter(session, api_key="")
        # Patch cfg so fallback also returns empty
        with patch("consensus_engine.api_adapters.cfg") as mock_cfg:
            mock_cfg.get_api_key.return_value = ""
            adapter = FinnhubAdapter(session, api_key="")
        ctx = await adapter.get_context("NVDA")
        assert ctx.price == 0.0
        session.get.assert_not_called()

    async def test_get_context_api_error(self):
        session = _mock_session()
        quote_cm = _ctx_manager(status=429)
        news_cm = _ctx_manager(status=429)
        session.get.side_effect = [quote_cm, news_cm]

        adapter = FinnhubAdapter(session, api_key="test-key")
        ctx = await adapter.get_context("NVDA")
        assert ctx.price == 0.0
        assert ctx.market_ok is False


# ---------------------------------------------------------------------------
# BraveAdapter
# ---------------------------------------------------------------------------

class TestBraveAdapter:
    async def test_search_success(self):
        session = _mock_session()
        cm = _ctx_manager(json_data={
            "web": {
                "results": [
                    {"title": "NVDA surges", "url": "https://cnbc.com/nvda", "description": "Chip stock up",
                     "meta_url": {"hostname": "cnbc.com"}},
                    {"title": "Market rally", "url": "https://reuters.com/rally", "description": "Broad rally",
                     "meta_url": {"hostname": "reuters.com"}},
                ]
            }
        })
        session.get.return_value = cm

        adapter = BraveAdapter(session, api_key="test-key")
        hits = await adapter.search("NVDA stock news")

        assert len(hits) == 2
        assert hits[0].source == "cnbc.com"
        assert hits[1].title == "Market rally"

    async def test_search_no_key(self):
        session = _mock_session()
        with patch("consensus_engine.api_adapters.cfg") as mock_cfg:
            mock_cfg.get_api_key.return_value = ""
            adapter = BraveAdapter(session, api_key="")
        hits = await adapter.search("test")
        assert hits == []

    async def test_search_api_error(self):
        session = _mock_session()
        cm = _ctx_manager(status=500)
        session.get.return_value = cm
        adapter = BraveAdapter(session, api_key="test-key")
        hits = await adapter.search("test")
        assert hits == []


# ---------------------------------------------------------------------------
# ExaAdapter
# ---------------------------------------------------------------------------

class TestExaAdapter:
    async def test_search_success(self):
        session = _mock_session()
        cm = _ctx_manager(json_data={
            "results": [
                {"title": "NVDA analysis", "url": "https://seekingalpha.com/nvda", "text": "Detailed analysis..."},
            ]
        })
        session.post.return_value = cm

        adapter = ExaAdapter(session, api_key="test-key")
        hits = await adapter.search("NVDA catalyst")

        assert len(hits) == 1
        assert hits[0].source == "seekingalpha.com"

    async def test_search_no_key(self):
        session = _mock_session()
        with patch("consensus_engine.api_adapters.cfg") as mock_cfg:
            mock_cfg.get.return_value = ""
            mock_cfg.get_api_key.return_value = ""
            adapter = ExaAdapter(session, api_key="")
        hits = await adapter.search("test")
        assert hits == []


# ---------------------------------------------------------------------------
# SerpApiAdapter
# ---------------------------------------------------------------------------

class TestSerpApiAdapter:
    async def test_search_success(self):
        session = _mock_session()
        cm = _ctx_manager(json_data={
            "news_results": [
                {"title": "NVDA earnings beat", "link": "https://wsj.com/nvda",
                 "source": "Wall Street Journal", "snippet": "Nvidia reported..."},
            ]
        })
        session.get.return_value = cm

        adapter = SerpApiAdapter(session, api_key="test-key")
        hits = await adapter.search("NVDA stock news")

        assert len(hits) == 1
        assert hits[0].source == "Wall Street Journal"

    async def test_search_no_key(self):
        session = _mock_session()
        with patch("consensus_engine.api_adapters.cfg") as mock_cfg:
            mock_cfg.get.return_value = ""
            mock_cfg.get_api_key.return_value = ""
            adapter = SerpApiAdapter(session, api_key="")
        hits = await adapter.search("test")
        assert hits == []


# ---------------------------------------------------------------------------
# FirecrawlAdapter
# ---------------------------------------------------------------------------

class TestFirecrawlAdapter:
    async def test_extract_success(self):
        session = _mock_session()
        cm = _ctx_manager(json_data={
            "success": True,
            "data": {
                "markdown": "# NVDA Surges\nNvidia stock jumped 5% on earnings...",
                "metadata": {"title": "NVDA Surges on Earnings"},
            },
        })
        session.post.return_value = cm

        adapter = FirecrawlAdapter(session, api_key="test-key")
        pages = await adapter.extract(["https://example.com/article"])

        assert len(pages) == 1
        assert pages[0].success is True
        assert "NVDA" in pages[0].text

    async def test_extract_no_key(self):
        session = _mock_session()
        with patch("consensus_engine.api_adapters.cfg") as mock_cfg:
            mock_cfg.get.return_value = ""
            mock_cfg.get_api_key.return_value = ""
            adapter = FirecrawlAdapter(session, api_key="")
        pages = await adapter.extract(["https://example.com"])
        assert pages == []

    async def test_extract_empty_urls(self):
        session = _mock_session()
        adapter = FirecrawlAdapter(session, api_key="test-key")
        pages = await adapter.extract([])
        assert pages == []

    async def test_extract_api_error(self):
        session = _mock_session()
        cm = _ctx_manager(status=500)
        session.post.return_value = cm

        adapter = FirecrawlAdapter(session, api_key="test-key")
        pages = await adapter.extract(["https://example.com"])

        assert len(pages) == 1
        assert pages[0].success is False

    async def test_extract_parallel(self):
        """Multiple URLs are scraped in parallel."""
        session = _mock_session()
        cm = _ctx_manager(json_data={
            "success": True,
            "data": {"markdown": "content", "metadata": {"title": "test"}},
        })
        session.post.return_value = cm

        adapter = FirecrawlAdapter(session, api_key="test-key")
        pages = await adapter.extract(["https://a.com", "https://b.com"])
        assert len(pages) == 2
