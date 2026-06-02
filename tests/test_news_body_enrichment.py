"""Tests for Q4: SearXNG / Brave / Finnhub body enrichment.

Body content was already used for relevance + classification but discarded
from the resulting CatalystResult. The downstream LLM scorer received only
the headline (200 chars). Adding `catalyst_body` field surfaces the article
body to the LLM for richer scoring.
"""
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine.models import CatalystResult


def test_catalyst_result_has_body_field():
    cr = CatalystResult(
        ticker="NVDA",
        catalyst_summary="NVDA Earnings Beat",
        catalyst_type="Earnings Beat",
        catalyst_body="NVDA reported Q3 EPS of $5.16 vs $4.42 estimate, driven by AI demand.",
    )
    assert cr.catalyst_body.startswith("NVDA reported Q3")


def test_catalyst_result_body_defaults_empty():
    cr = CatalystResult(
        ticker="X", catalyst_summary="t", catalyst_type="Earnings Beat",
    )
    assert cr.catalyst_body == ""


@pytest.mark.asyncio
async def test_searxng_search_passes_content_as_body():
    """The SearXNG path should populate catalyst_body from result content."""
    from consensus_engine.scanners import news as news_mod

    fake_results = [{
        "title": "NVDA Earnings Beat",
        "url": "https://reuters.com/nvda-earnings",
        "content": "NVDA reported Q3 EPS of $5.16 vs $4.42 estimate.",
    }]

    with patch("consensus_engine.scanners.news.search_searxng",
               new_callable=AsyncMock, return_value=fake_results), \
         patch("consensus_engine.scanners.news._get_search_query",
               new_callable=AsyncMock, return_value="NVDA stock"), \
         patch("consensus_engine.scanners.news._get_company_name",
               new_callable=AsyncMock, return_value="NVIDIA"), \
         patch("consensus_engine.scanners.news._is_trusted_source", return_value=True):
        result = await news_mod._search_searxng("NVDA")

    assert result is not None
    assert result.catalyst_body == "NVDA reported Q3 EPS of $5.16 vs $4.42 estimate."


@pytest.mark.asyncio
async def test_brave_search_passes_description_as_body():
    """Brave path should populate catalyst_body from result description."""
    from consensus_engine.scanners import news as news_mod

    class MockResp:
        status = 200

        async def json(self):
            return {"web": {"results": [{
                "title": "AMD Earnings Beat",
                "url": "https://reuters.com/amd",
                "description": "AMD beat Q3 estimates with $5B revenue, raised guidance for Q4.",
            }]}}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

    class MockSession:
        def get(self, *a, **kw):
            return MockResp()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

    with patch("consensus_engine.scanners.news.get_session", new_callable=AsyncMock, return_value=MockSession()), \
         patch("consensus_engine.scanners.news.cfg.get_api_key", return_value="fake-key"), \
         patch("consensus_engine.scanners.news.rate_limiter.acquire",
               new_callable=AsyncMock, return_value=True), \
         patch("consensus_engine.scanners.news._get_search_query",
               new_callable=AsyncMock, return_value="AMD stock"), \
         patch("consensus_engine.scanners.news._get_company_name",
               new_callable=AsyncMock, return_value="AMD"), \
         patch("consensus_engine.scanners.news._is_trusted_source", return_value=True), \
         patch("consensus_engine.scanners.news._brave_budget_ok", return_value=True), \
         patch("consensus_engine.scanners.news._brave_quota_exhausted", False):
        # _brave_budget_ok reads a PERSISTENT daily counter file that the live engine
        # writes; _brave_quota_exhausted is a process global a 402 can set. Patch both so
        # this test exercises _search_brave's logic deterministically, never the live quota.
        result = await news_mod._search_brave("AMD")

    assert result is not None
    assert "raised guidance" in result.catalyst_body
