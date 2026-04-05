"""Tests for cross-reference result cache."""
import time

import pytest

from consensus_engine import config as cfg, db
from consensus_engine.models import (
    CrossReferenceResult,
    OptionsResult,
    ScoreBreakdown,
    TechnicalFilter,
    TechnicalResult,
)
from consensus_engine.utils.xref_cache import (
    XRefCache,
    cache_xref,
    clear_xref_cache,
    get_cached_xref,
)


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


@pytest.fixture
async def setup_db(tmp_path):
    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "test.db")}
    clear_xref_cache()
    await db.init_db()
    yield
    clear_xref_cache()
    await db.close_db()


@pytest.mark.asyncio
async def test_cache_db_round_trip_rehydrates_nested_models(setup_db):
    result = CrossReferenceResult(
        ticker="NVDA",
        breakdown=ScoreBreakdown(base=30, technical=4, options_flow=10),
        catalyst_summary="Strong earnings",
        catalyst_type="Earnings Beat",
        technical=TechnicalResult(
            ticker="NVDA",
            filters=[TechnicalFilter(name="RVOL", value=2.4, threshold="> 2.0x", passed=True)],
            price=123.45,
            volume=1000000,
            price_change_pct=3.2,
        ),
        other_analysts=["analyst2"],
        options=OptionsResult(
            ticker="NVDA",
            unusual_calls=True,
            max_call_ratio=4.5,
            top_contract="NVDA260417C00120000",
        ),
    )

    await cache_xref("NVDA", result)
    clear_xref_cache()

    cached = await get_cached_xref("NVDA")

    assert isinstance(cached, CrossReferenceResult)
    assert isinstance(cached.breakdown, ScoreBreakdown)
    assert cached.breakdown.options_flow == 10
    assert isinstance(cached.technical, TechnicalResult)
    assert isinstance(cached.technical.filters[0], TechnicalFilter)
    assert cached.technical.filters[0].name == "RVOL"
    assert isinstance(cached.options, OptionsResult)
    assert cached.options.unusual_calls is True
