"""Tests for the SearXNG in-process fallback chain (TODO #10).

SearXNG healthy -> use SearXNG, no fallback.
SearXNG empty   -> Tavily.
SearXNG+Tavily empty -> Firecrawl.
All three empty -> [].
Plus per-provider normalization to {"title","url","content"}.

No live network: the aiohttp session and the provider helpers are mocked.
"""

from unittest.mock import AsyncMock, patch

import pytest

import consensus_engine.scanners.searxng as sx


class _FakeResp:
    """Async-context-manager aiohttp response stub."""

    def __init__(self, status=200, payload=None):
        self.status = status
        self._payload = payload or {}

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _GetSession:
    """Session stub whose .get() returns a preset response."""

    def __init__(self, resp):
        self._resp = resp
        self.get_calls = 0

    def get(self, *a, **kw):
        self.get_calls += 1
        return self._resp


class _PostSession:
    """Session stub whose .post() returns a preset response."""

    def __init__(self, resp):
        self._resp = resp
        self.post_calls = 0

    def post(self, *a, **kw):
        self.post_calls += 1
        return self._resp


# --------------------------------------------------------------------------
# Fallback chain (helpers mocked)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_healthy_searxng_skips_fallback(monkeypatch):
    """SearXNG returns results -> they are returned and NO fallback fires."""
    sx_results = [{"title": "t", "url": "u", "content": "c"}]
    resp = _FakeResp(status=200, payload={
        "results": [{"title": "t", "url": "u", "content": "c"}]
    })
    session = _GetSession(resp)

    monkeypatch.setattr(sx.rate_limiter, "acquire", AsyncMock(return_value=True))
    monkeypatch.setattr(sx.rate_limiter, "report_success", lambda *a: None)
    monkeypatch.setattr(sx, "get_session", AsyncMock(return_value=session))

    with patch.object(sx, "_search_fallback", new_callable=AsyncMock) as fb:
        out = await sx.search_searxng("nvda news")

    assert out == sx_results
    fb.assert_not_called()


@pytest.mark.asyncio
async def test_searxng_empty_falls_to_tavily(monkeypatch):
    """SearXNG returns zero results -> Tavily hit is returned."""
    resp = _FakeResp(status=200, payload={"results": []})
    session = _GetSession(resp)

    tavily_hit = [{"title": "tav", "url": "tu", "content": "tc"}]
    monkeypatch.setattr(sx.rate_limiter, "acquire", AsyncMock(return_value=True))
    monkeypatch.setattr(sx.rate_limiter, "report_success", lambda *a: None)
    monkeypatch.setattr(sx, "get_session", AsyncMock(return_value=session))
    monkeypatch.setattr(sx, "_tavily_search",
                        AsyncMock(return_value=tavily_hit))
    fc = AsyncMock(return_value=[])
    monkeypatch.setattr(sx, "_firecrawl_search", fc)

    out = await sx.search_searxng("nvda news")

    assert out == tavily_hit
    fc.assert_not_called()


@pytest.mark.asyncio
async def test_searxng_and_tavily_empty_falls_to_firecrawl(monkeypatch):
    """SearXNG empty + Tavily empty -> Firecrawl hit is returned."""
    resp = _FakeResp(status=200, payload={"results": []})
    session = _GetSession(resp)

    firecrawl_hit = [{"title": "fc", "url": "fu", "content": "fcc"}]
    monkeypatch.setattr(sx.rate_limiter, "acquire", AsyncMock(return_value=True))
    monkeypatch.setattr(sx.rate_limiter, "report_success", lambda *a: None)
    monkeypatch.setattr(sx, "get_session", AsyncMock(return_value=session))
    monkeypatch.setattr(sx, "_tavily_search", AsyncMock(return_value=[]))
    monkeypatch.setattr(sx, "_firecrawl_search",
                        AsyncMock(return_value=firecrawl_hit))

    out = await sx.search_searxng("nvda news")

    assert out == firecrawl_hit


@pytest.mark.asyncio
async def test_all_three_empty_returns_empty(monkeypatch):
    """SearXNG + Tavily + Firecrawl all empty -> []."""
    resp = _FakeResp(status=200, payload={"results": []})
    session = _GetSession(resp)

    monkeypatch.setattr(sx.rate_limiter, "acquire", AsyncMock(return_value=True))
    monkeypatch.setattr(sx.rate_limiter, "report_success", lambda *a: None)
    monkeypatch.setattr(sx, "get_session", AsyncMock(return_value=session))
    monkeypatch.setattr(sx, "_tavily_search", AsyncMock(return_value=[]))
    monkeypatch.setattr(sx, "_firecrawl_search", AsyncMock(return_value=[]))

    out = await sx.search_searxng("nvda news")

    assert out == []


@pytest.mark.asyncio
async def test_searxng_non200_falls_back(monkeypatch):
    """A non-200 from SearXNG also routes through the fallback chain."""
    resp = _FakeResp(status=503, payload={})
    session = _GetSession(resp)

    tavily_hit = [{"title": "tav", "url": "tu", "content": "tc"}]
    monkeypatch.setattr(sx.rate_limiter, "acquire", AsyncMock(return_value=True))
    monkeypatch.setattr(sx.rate_limiter, "report_failure", lambda *a: None)
    monkeypatch.setattr(sx, "get_session", AsyncMock(return_value=session))
    monkeypatch.setattr(sx, "_tavily_search",
                        AsyncMock(return_value=tavily_hit))

    out = await sx.search_searxng("nvda news")

    assert out == tavily_hit


@pytest.mark.asyncio
async def test_rate_limit_block_falls_back(monkeypatch):
    """A rate-limiter block routes through the fallback chain (no HTTP call)."""
    tavily_hit = [{"title": "tav", "url": "tu", "content": "tc"}]
    monkeypatch.setattr(sx.rate_limiter, "acquire", AsyncMock(return_value=False))
    monkeypatch.setattr(sx, "_tavily_search",
                        AsyncMock(return_value=tavily_hit))

    out = await sx.search_searxng("nvda news")

    assert out == tavily_hit


# --------------------------------------------------------------------------
# Per-provider normalization (aiohttp session mocked)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tavily_normalization(monkeypatch):
    """Tavily raw response -> {"title","url","content"}."""
    payload = {"results": [
        {"title": "Headline", "url": "https://ex.com", "content": "body text"},
    ]}
    session = _PostSession(_FakeResp(status=200, payload=payload))
    monkeypatch.setenv("TAVILY_API_KEY", "fake-key")
    monkeypatch.setattr(sx, "get_session", AsyncMock(return_value=session))

    out = await sx._tavily_search("q")

    assert out == [{"title": "Headline", "url": "https://ex.com",
                    "content": "body text"}]


@pytest.mark.asyncio
async def test_tavily_no_key_returns_empty(monkeypatch):
    """Empty/missing Tavily key -> [] (provider skipped, no HTTP)."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    session = _PostSession(_FakeResp(status=200, payload={"results": []}))
    monkeypatch.setattr(sx, "get_session", AsyncMock(return_value=session))

    out = await sx._tavily_search("q")

    assert out == []
    assert session.post_calls == 0


@pytest.mark.asyncio
async def test_firecrawl_normalization_description(monkeypatch):
    """Firecrawl raw response with description -> content uses description."""
    payload = {"data": [
        {"title": "FC Headline", "url": "https://fc.com",
         "description": "desc text", "markdown": "md text"},
    ]}
    session = _PostSession(_FakeResp(status=200, payload=payload))
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fake-key")
    monkeypatch.setattr(sx, "get_session", AsyncMock(return_value=session))

    out = await sx._firecrawl_search("q")

    assert out == [{"title": "FC Headline", "url": "https://fc.com",
                    "content": "desc text"}]


@pytest.mark.asyncio
async def test_firecrawl_normalization_markdown_fallback(monkeypatch):
    """Firecrawl with no description -> content falls back to markdown."""
    payload = {"data": [
        {"title": "FC", "url": "https://fc.com", "markdown": "md only"},
    ]}
    session = _PostSession(_FakeResp(status=200, payload=payload))
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fake-key")
    monkeypatch.setattr(sx, "get_session", AsyncMock(return_value=session))

    out = await sx._firecrawl_search("q")

    assert out == [{"title": "FC", "url": "https://fc.com",
                    "content": "md only"}]


@pytest.mark.asyncio
async def test_firecrawl_no_key_returns_empty(monkeypatch):
    """Empty/missing Firecrawl key -> [] (provider skipped, no HTTP)."""
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    session = _PostSession(_FakeResp(status=200, payload={"data": []}))
    monkeypatch.setattr(sx, "get_session", AsyncMock(return_value=session))

    out = await sx._firecrawl_search("q")

    assert out == []
    assert session.post_calls == 0
