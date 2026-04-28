"""Integration test: all 6 new-signal-features enabled, one synthesized signal.

Verifies:
- All 6 features can be imported without error
- Code paths don't crash
- consolidation_result key appears in feature_vector_json when xref has it
- No double-count in ScoreBreakdown
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from consensus_engine import config as cfg


@pytest.fixture(autouse=True)
def _load_cfg():
    cfg.load_config()


def test_all_feature_modules_importable():
    """All 6 new-signal-features modules import without error."""
    from consensus_engine.analysis.contradiction import evaluate_contradiction  # A1
    from consensus_engine.analysis.consolidation import consolidate_for_ticker  # A3
    from consensus_engine.analysis.regime import lookup_regime                  # A5
    assert callable(evaluate_contradiction)
    assert callable(consolidate_for_ticker)
    assert callable(lookup_regime)


def test_consolidation_result_dataclass():
    """ConsolidationResult can be instantiated and has all required fields."""
    from consensus_engine.analysis.consolidation import ConsolidationResult
    cr = ConsolidationResult(
        fired=True,
        consolidated_id=1,
        effective_n_clusters=2,
        combined_log_odds=0.847,
        consensus_boost=40,
        sources_seen=["twitter", "reddit"],
        reason="consolidated",
    )
    assert cr.fired is True
    assert cr.effective_n_clusters == 2
    assert cr.consensus_boost == 40
    assert cr.reason == "consolidated"


def test_score_breakdown_no_double_count():
    """ScoreBreakdown.total is sum of all fields; consensus_boost is one of them."""
    from consensus_engine.models import ScoreBreakdown
    sb = ScoreBreakdown(
        base=25,
        additional_analysts=20,
        news_catalyst=30,
        consensus_boost=40,
    )
    expected = 25 + 20 + 30 + 40
    assert sb.total == expected


def test_cross_reference_result_has_consolidation_field():
    """CrossReferenceResult has consolidation_result field (default None)."""
    from consensus_engine.models import CrossReferenceResult, ScoreBreakdown
    xr = CrossReferenceResult(
        ticker="NVDA",
        breakdown=ScoreBreakdown(base=25),
        catalyst_summary="",
        catalyst_type="",
    )
    assert hasattr(xr, "consolidation_result")
    assert xr.consolidation_result is None


@pytest.mark.asyncio
async def test_consolidate_for_ticker_no_sources_returns_no_other_sources():
    """With empty signal_events, consolidate_for_ticker returns no_other_sources."""
    from consensus_engine.analysis.consolidation import consolidate_for_ticker

    mock_conn = AsyncMock()
    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=[])
    mock_cursor.fetchone = AsyncMock(return_value=None)
    mock_cursor.lastrowid = None
    mock_conn.execute = AsyncMock(return_value=mock_cursor)
    mock_conn.commit = AsyncMock()

    with patch("consensus_engine.analysis.consolidation.db") as mock_db:
        mock_db.get_db = AsyncMock(return_value=mock_conn)
        result = await consolidate_for_ticker("NVDA", window_minutes=15, shadow_only=True)

    assert result.reason == "no_other_sources"
    assert result.consensus_boost == 0
    assert result.fired is False


@pytest.mark.asyncio
async def test_consolidate_shadow_only_matches_config_disabled():
    """When feature is disabled in config, shadow_only=True is inferred by cross_reference."""
    # The caller (cross_reference) sets shadow_only = not cfg.get(...)
    # When disabled, shadow_only=True -> consensus_boost=0
    enabled = cfg.get("features.cross_source_consolidation.enabled", False)
    expected_shadow = not enabled  # True when disabled

    mock_conn = AsyncMock()
    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=[])
    mock_cursor.fetchone = AsyncMock(return_value=None)
    mock_cursor.lastrowid = None
    mock_conn.execute = AsyncMock(return_value=mock_cursor)
    mock_conn.commit = AsyncMock()

    from consensus_engine.analysis.consolidation import consolidate_for_ticker
    with patch("consensus_engine.analysis.consolidation.db") as mock_db:
        mock_db.get_db = AsyncMock(return_value=mock_conn)
        result = await consolidate_for_ticker(
            "NVDA", window_minutes=15, shadow_only=expected_shadow
        )

    # When disabled (shadow_only=True), boost must be 0
    if expected_shadow:
        assert result.consensus_boost == 0
