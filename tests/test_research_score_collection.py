"""Bot adapter retains ordered, conditional reads around the shared score math."""
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_consecutive_optional_collection_failures_preserve_score(monkeypatch):
    from consensus_engine import cross_reference as xref
    from consensus_engine.analysis import consolidation
    from consensus_engine.models import TechnicalResult

    values = {
        '_run_news_cascade': None, '_run_sec_check': (False, ''),
        '_run_social_check': {}, '_run_technical': TechnicalResult('SPY'),
        '_run_other_analysts': {'aligned': [], 'opposing': []},
        '_run_options_check': None, '_get_youtube_context': None,
    }
    for name, value in values.items():
        monkeypatch.setattr(xref, name, AsyncMock(return_value=value))
    config = {
        'scoring.skip_llm_below_threshold': True,
        'features.finra_short_volume.enabled': True,
        'features.short_interest.enabled': True,
    }
    monkeypatch.setattr(xref.cfg, 'get', lambda key, default=None: config.get(key, default))
    order = []

    async def consolidated(*args, **kwargs):
        order.append('consolidation')
        return consolidation.ConsolidationResult(False, None, 0, 0, 0, [], 'synthetic')

    async def volume(*args, **kwargs):
        order.append('finra_volume')
        raise RuntimeError('synthetic volume failure')

    async def interest(*args, **kwargs):
        order.append('short_interest')
        raise RuntimeError('synthetic interest failure')

    llm = AsyncMock(side_effect=AssertionError('LLM should remain skipped'))
    monkeypatch.setattr(xref, '_run_llm_score', llm)
    monkeypatch.setattr(consolidation, 'consolidate_for_ticker', consolidated)
    monkeypatch.setattr(xref.db, 'get_latest_finra_short_volume', volume)
    monkeypatch.setattr(xref.db, 'get_latest_finra_short_interest', interest)
    result = await xref.score_ticker('SPY')
    assert result.final_score == 0
    assert order == ['consolidation', 'finra_volume', 'short_interest']
    assert llm.await_count == 0
