"""Tests for I7: sigmoid(log-odds) scaling of consensus_boost (consolidation.py).

Four scenarios:
  (a) flag ON + strong positive log_odds -> boost ≈ legacy (sigmoid -> 1)
  (b) flag ON + strongly negative log_odds -> boost ≈ count_floor_frac × legacy, never 0
  (c) flag ON + cold-start (no priors) -> consensus_boost == 0, identical to legacy
  (d) flag OFF -> byte-identical legacy boost (int(effective_n * pts_per_cluster))
"""
from __future__ import annotations

import math
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from consensus_engine import config as cfg
from consensus_engine.analysis.consolidation import consolidate_for_ticker


# ---------------------------------------------------------------------------
# Fixtures / helpers  (reuse pattern from test_source_consolidation.py)
# ---------------------------------------------------------------------------

def _make_mock_conn(signal_rows=None, perf_rows=None, insert_lastrowid=1):
    """Build a mock AsyncConnection for consolidate_for_ticker tests."""
    conn = AsyncMock()
    signal_rows = signal_rows or []
    perf_rows = perf_rows or {}  # source_type -> rolling_accuracy | None

    async def _execute(sql, params=()):
        cursor = AsyncMock()
        sql_lower = sql.strip().lower()

        if "from signal_events" in sql_lower:
            mock_rows = []
            for r in signal_rows:
                m = MagicMock()
                m.__getitem__ = lambda self, k, _r=r: _r[k]
                mock_rows.append(m)
            cursor.fetchall = AsyncMock(return_value=mock_rows)
            cursor.fetchone = AsyncMock(return_value=None)

        elif "from source_performance" in sql_lower:
            entity_id = params[0] if params else None
            acc = perf_rows.get(entity_id, None)
            if acc is None:
                cursor.fetchone = AsyncMock(return_value=None)
            else:
                row = MagicMock()
                row.__getitem__ = lambda self, k: acc if k == "rolling_accuracy" else None
                cursor.fetchone = AsyncMock(return_value=row)
            cursor.fetchall = AsyncMock(return_value=[])

        elif "insert or ignore into consolidated_events" in sql_lower:
            cursor.lastrowid = insert_lastrowid
            cursor.fetchone = AsyncMock(return_value=None)
            cursor.fetchall = AsyncMock(return_value=[])

        elif "from consolidated_events" in sql_lower:
            row = MagicMock()
            row.__getitem__ = lambda self, k: insert_lastrowid if k == "id" else None
            cursor.fetchone = AsyncMock(return_value=row)
            cursor.fetchall = AsyncMock(return_value=[])

        else:
            cursor.fetchone = AsyncMock(return_value=None)
            cursor.fetchall = AsyncMock(return_value=[])
            cursor.lastrowid = None

        return cursor

    conn.execute = _execute
    conn.commit = AsyncMock()
    return conn


def _signal_row(source_type: str):
    return {
        "id": 1,
        "source_type": source_type,
        "recorded_at": time.time(),
        "consumed_by_cluster_id": None,
    }


# ---------------------------------------------------------------------------
# (a) Flag ON + strong positive log_odds -> boost ≈ legacy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_i7_strong_positive_logodds_boost_near_legacy():
    """Strong positive log_odds (high accuracy sources) -> sigmoid -> 1, boost ≈ legacy."""
    cfg.load_config()
    # Two high-accuracy sources in different clusters
    rows = [_signal_row("twitter"), _signal_row("reddit")]
    # accuracy 0.95 -> log_odds per cluster ≈ log(0.95/0.05) ≈ 2.94 each, total ≈ 5.88
    conn = _make_mock_conn(
        signal_rows=rows,
        perf_rows={"twitter": 0.95, "reddit": 0.95},
    )
    pts_per_cluster = cfg.get("scoring.multipliers.additional_analyst", 20)
    count_floor_frac = 0.5  # matches config value

    with patch("consensus_engine.analysis.consolidation.db") as mock_db, \
         patch("consensus_engine.config.get") as mock_cfg_get:

        def cfg_side_effect(key, default=None):
            overrides = {
                "features.consensus_logodds.enabled": True,
                "features.consensus_logodds.count_floor_frac": count_floor_frac,
                "features.cross_source_consolidation.max_effective_clusters": 3,
                "features.cross_source_consolidation.window_minutes": 15,
                "scoring.multipliers.additional_analyst": pts_per_cluster,
            }
            return overrides.get(key, cfg._config_data and cfg.get.__wrapped__(key, default) if hasattr(cfg.get, "__wrapped__") else default)

        # Use real config but override just the I7 flags
        mock_db.get_db = AsyncMock(return_value=conn)

        # Patch at module level inside consolidation
        with patch("consensus_engine.analysis.consolidation.cfg") as mock_consolidation_cfg:
            mock_consolidation_cfg.get = lambda key, default=None: {
                "features.consensus_logodds.enabled": True,
                "features.consensus_logodds.count_floor_frac": count_floor_frac,
                "features.cross_source_consolidation.max_effective_clusters": 3,
                "features.cross_source_consolidation.window_minutes": 15,
                "scoring.multipliers.additional_analyst": pts_per_cluster,
            }.get(key, default)
            result = await consolidate_for_ticker("NVDA", window_minutes=15, shadow_only=False)

    legacy_boost = round(2 * pts_per_cluster)
    # sigmoid(5.88) is ~0.997, so scaled_boost should be very close to legacy
    assert result.consensus_boost > 0
    assert result.consensus_boost >= round(0.9 * legacy_boost), (
        f"Expected boost close to legacy={legacy_boost}, got {result.consensus_boost}"
    )


# ---------------------------------------------------------------------------
# (b) Flag ON + strongly negative log_odds -> boost ≈ floor, never 0
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_i7_strong_negative_logodds_boost_near_floor():
    """Strong negative log_odds (low accuracy sources) -> sigmoid -> 0, boost ≈ floor."""
    cfg.load_config()
    rows = [_signal_row("twitter"), _signal_row("reddit")]
    # accuracy 0.05 -> log_odds per cluster ≈ log(0.05/0.95) ≈ -2.94 each, total ≈ -5.88
    conn = _make_mock_conn(
        signal_rows=rows,
        perf_rows={"twitter": 0.05, "reddit": 0.05},
    )
    pts_per_cluster = cfg.get("scoring.multipliers.additional_analyst", 20)
    count_floor_frac = 0.5

    with patch("consensus_engine.analysis.consolidation.db") as mock_db, \
         patch("consensus_engine.analysis.consolidation.cfg") as mock_cfg:

        mock_cfg.get = lambda key, default=None: {
            "features.consensus_logodds.enabled": True,
            "features.consensus_logodds.count_floor_frac": count_floor_frac,
            "features.cross_source_consolidation.max_effective_clusters": 3,
            "features.cross_source_consolidation.window_minutes": 15,
            "scoring.multipliers.additional_analyst": pts_per_cluster,
        }.get(key, default)
        mock_db.get_db = AsyncMock(return_value=conn)
        result = await consolidate_for_ticker("NVDA", window_minutes=15, shadow_only=False)

    legacy_boost = round(2 * pts_per_cluster)
    expected_floor = round(count_floor_frac * legacy_boost)

    # boost must never be 0 when legacy > 0
    assert result.consensus_boost > 0, "boost must never be 0 when legacy > 0"
    # boost should be close to the floor (sigmoid≈0 so sigmoid_part≈0)
    # allow ±1 for rounding
    assert abs(result.consensus_boost - expected_floor) <= 1, (
        f"Expected boost near floor={expected_floor}, got {result.consensus_boost}"
    )


# ---------------------------------------------------------------------------
# (c) Flag ON + cold-start -> boost exactly 0, identical to legacy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_i7_cold_start_boost_exactly_zero():
    """Cold-start (no source_performance row) -> consensus_boost == 0 even with flag ON."""
    cfg.load_config()
    rows = [_signal_row("twitter")]
    # No perf entry -> cold start
    conn = _make_mock_conn(signal_rows=rows, perf_rows={})

    with patch("consensus_engine.analysis.consolidation.db") as mock_db, \
         patch("consensus_engine.analysis.consolidation.cfg") as mock_cfg, \
         patch("asyncio.ensure_future"):  # suppress background write

        mock_cfg.get = lambda key, default=None: {
            "features.consensus_logodds.enabled": True,
            "features.consensus_logodds.count_floor_frac": 0.5,
            "features.cross_source_consolidation.max_effective_clusters": 3,
            "features.cross_source_consolidation.window_minutes": 15,
            "scoring.multipliers.additional_analyst": 20,
        }.get(key, default)
        mock_db.get_db = AsyncMock(return_value=conn)
        result = await consolidate_for_ticker("NVDA", window_minutes=15, shadow_only=False)

    # Cold-start path is hit before sigmoid logic -> must still be 0
    assert result.consensus_boost == 0
    assert result.reason == "cold_start_passthrough"
    assert result.fired is False


# ---------------------------------------------------------------------------
# (d) Flag OFF -> byte-identical legacy boost
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_i7_flag_off_byte_identical_to_legacy():
    """Flag OFF -> boost == round(effective_n * pts_per_cluster), unchanged."""
    cfg.load_config()
    rows = [_signal_row("twitter"), _signal_row("reddit")]
    conn = _make_mock_conn(
        signal_rows=rows,
        perf_rows={"twitter": 0.7, "reddit": 0.6},
    )
    pts_per_cluster = cfg.get("scoring.multipliers.additional_analyst", 20)

    with patch("consensus_engine.analysis.consolidation.db") as mock_db, \
         patch("consensus_engine.analysis.consolidation.cfg") as mock_cfg:

        mock_cfg.get = lambda key, default=None: {
            "features.consensus_logodds.enabled": False,  # FLAG OFF
            "features.consensus_logodds.count_floor_frac": 0.5,
            "features.cross_source_consolidation.max_effective_clusters": 3,
            "features.cross_source_consolidation.window_minutes": 15,
            "scoring.multipliers.additional_analyst": pts_per_cluster,
        }.get(key, default)
        mock_db.get_db = AsyncMock(return_value=conn)
        result = await consolidate_for_ticker("NVDA", window_minutes=15, shadow_only=False)

    legacy_boost = round(2 * pts_per_cluster)
    assert result.consensus_boost == legacy_boost, (
        f"Flag OFF must produce byte-identical legacy={legacy_boost}, got {result.consensus_boost}"
    )
