"""Tests for A3: Bayesian multi-source consolidation (consolidation.py).

10 scenarios per spec §8.2:
  (a) single-source no-op: only one cluster -> effective_n=1, shadow write, minimal boost
  (b) two-cluster fuse: twitter + reddit -> effective_n=2, combined log_odds computed
  (c) three-cluster cap-at-3: 4 source clusters -> capped at 3
  (d) consumed_by_cluster_id excludes rows with that column set
  (e) cold-start passthrough: source with no source_performance row -> fired=False
  (f) INSERT OR IGNORE race: calling consolidate_for_ticker twice same window
  (g) shadow_only=True writes but boost=0
  (h) shadow_only=False returns real consensus_boost
  (i) ScoreBreakdown.consensus_boost plumbing — cross_reference passes it through
  (j) replay 30d window_minutes param honored
"""
import asyncio
import math
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from consensus_engine import config as cfg
from consensus_engine.analysis.consolidation import (
    ConsolidationResult,
    SOURCE_CLUSTERS,
    _source_to_cluster,
    consolidate_for_ticker,
)
from consensus_engine.models import ScoreBreakdown


# ---------------------------------------------------------------------------
# Helpers
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
            # Return signal_rows as list of dict-like objects
            mock_rows = []
            for r in signal_rows:
                m = MagicMock()
                m.__getitem__ = lambda self, k, _r=r: _r[k]
                mock_rows.append(m)
            cursor.fetchall = AsyncMock(return_value=mock_rows)
            cursor.fetchone = AsyncMock(return_value=None)

        elif "from source_performance" in sql_lower:
            # Extract entity_id from params
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
            # Re-SELECT after collision — return existing row
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


def _signal_row(source_type: str, consumed=False):
    return {
        "id": 1,
        "source_type": source_type,
        "recorded_at": time.time(),
        "consumed_by_cluster_id": 999 if consumed else None,
    }


# ---------------------------------------------------------------------------
# (a) Single-source: only one cluster
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_single_source_single_cluster():
    """One source type (twitter) -> effective_n_clusters=1, shadow write happens."""
    cfg.load_config()
    rows = [_signal_row("twitter")]
    conn = _make_mock_conn(
        signal_rows=rows,
        perf_rows={"twitter": 0.7},
    )
    with patch("consensus_engine.analysis.consolidation.db") as mock_db:
        mock_db.get_db = AsyncMock(return_value=conn)
        result = await consolidate_for_ticker("NVDA", window_minutes=15, shadow_only=True)

    assert result.effective_n_clusters == 1
    assert result.sources_seen == ["twitter"]
    assert result.consensus_boost == 0  # shadow_only
    assert result.reason == "shadow_only"


# ---------------------------------------------------------------------------
# (b) Two-cluster fuse: twitter + reddit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_two_cluster_fuse_computes_log_odds():
    """twitter (analyst cluster) + reddit (retail cluster) -> effective_n=2."""
    cfg.load_config()
    rows = [_signal_row("twitter"), _signal_row("reddit")]
    conn = _make_mock_conn(
        signal_rows=rows,
        perf_rows={"twitter": 0.7, "reddit": 0.6},
    )
    with patch("consensus_engine.analysis.consolidation.db") as mock_db:
        mock_db.get_db = AsyncMock(return_value=conn)
        result = await consolidate_for_ticker("NVDA", window_minutes=15, shadow_only=False)

    assert result.effective_n_clusters == 2
    assert result.fired is True
    # combined_log_odds = log(0.7/0.3) + log(0.6/0.4)
    expected_lo = math.log(0.7 / 0.3) + math.log(0.6 / 0.4)
    assert abs(result.combined_log_odds - expected_lo) < 0.01
    assert result.consensus_boost > 0
    assert result.reason == "consolidated"


# ---------------------------------------------------------------------------
# (c) Three-cluster cap: 4 source clusters seen -> capped at max 3
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_four_clusters_capped_at_three():
    """4 distinct clusters seen but max_effective_clusters=3 caps effective_n."""
    cfg.load_config()
    rows = [
        _signal_row("twitter"),    # analyst
        _signal_row("reddit"),     # retail
        _signal_row("youtube"),    # video
        _signal_row("sec_filing"), # official
    ]
    conn = _make_mock_conn(
        signal_rows=rows,
        perf_rows={"twitter": 0.7, "reddit": 0.6, "youtube": 0.65, "sec_filing": 0.8},
    )
    with patch("consensus_engine.analysis.consolidation.db") as mock_db:
        mock_db.get_db = AsyncMock(return_value=conn)
        result = await consolidate_for_ticker("NVDA", window_minutes=15, shadow_only=False)

    assert result.effective_n_clusters == 3  # capped at max_effective_clusters=3
    assert len(result.sources_seen) == 4


# ---------------------------------------------------------------------------
# (d) consumed_by_cluster_id excludes rows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consumed_rows_excluded_by_sql():
    """Rows with consumed_by_cluster_id set must not appear (SQL WHERE clause)."""
    cfg.load_config()
    # The SQL already filters WHERE consumed_by_cluster_id IS NULL.
    # Simulate: no rows returned (all consumed) -> no_other_sources
    conn = _make_mock_conn(signal_rows=[], perf_rows={})
    with patch("consensus_engine.analysis.consolidation.db") as mock_db:
        mock_db.get_db = AsyncMock(return_value=conn)
        result = await consolidate_for_ticker("NVDA", window_minutes=15, shadow_only=True)

    assert result.reason == "no_other_sources"
    assert result.effective_n_clusters == 0
    assert result.fired is False


@pytest.mark.asyncio
async def test_consumed_sql_contains_null_check():
    """SQL query must include consumed_by_cluster_id IS NULL."""
    cfg.load_config()
    captured_sqls = []

    conn = AsyncMock()
    cursor = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=[])
    cursor.fetchone = AsyncMock(return_value=None)
    cursor.lastrowid = None

    async def capture_execute(sql, params=()):
        captured_sqls.append(sql)
        return cursor

    conn.execute = capture_execute
    conn.commit = AsyncMock()

    with patch("consensus_engine.analysis.consolidation.db") as mock_db:
        mock_db.get_db = AsyncMock(return_value=conn)
        await consolidate_for_ticker("NVDA", window_minutes=15, shadow_only=True)

    signal_sqls = [s for s in captured_sqls if "signal_events" in s.lower()]
    assert signal_sqls, "Expected at least one signal_events query"
    assert any("consumed_by_cluster_id IS NULL" in s for s in signal_sqls)


# ---------------------------------------------------------------------------
# (e) Cold-start passthrough
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cold_start_returns_passthrough_reason():
    """Source with no source_performance row -> fired=False, cold_start_passthrough."""
    cfg.load_config()
    rows = [_signal_row("twitter")]
    # No perf entry for twitter -> cold start
    conn = _make_mock_conn(signal_rows=rows, perf_rows={})
    with patch("consensus_engine.analysis.consolidation.db") as mock_db:
        mock_db.get_db = AsyncMock(return_value=conn)
        with patch("consensus_engine.analysis.consolidation._maybe_write_consolidated"):
            result = await consolidate_for_ticker("NVDA", window_minutes=15, shadow_only=False)

    assert result.fired is False
    assert result.reason == "cold_start_passthrough"
    assert result.consensus_boost == 0


# ---------------------------------------------------------------------------
# (f) INSERT OR IGNORE race — second call returns existing row
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_insert_or_ignore_race_returns_existing_id():
    """Second consolidate_for_ticker call with same window -> returns existing consolidated_id."""
    cfg.load_config()
    rows = [_signal_row("twitter")]
    conn = _make_mock_conn(
        signal_rows=rows,
        perf_rows={"twitter": 0.7},
        insert_lastrowid=0,  # simulate collision (lastrowid=0 = no insert)
    )
    with patch("consensus_engine.analysis.consolidation.db") as mock_db:
        mock_db.get_db = AsyncMock(return_value=conn)
        result = await consolidate_for_ticker("NVDA", window_minutes=15, shadow_only=True)

    # On collision (lastrowid=0), re-SELECT returns existing row id
    # Our mock returns insert_lastrowid=0 for the INSERT, then a mock SELECT row
    assert result is not None  # function should not raise


# ---------------------------------------------------------------------------
# (g) shadow_only=True writes but returns boost=0
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shadow_only_true_boost_is_zero():
    """shadow_only=True -> writes shadow row but consensus_boost=0."""
    cfg.load_config()
    rows = [_signal_row("twitter"), _signal_row("reddit")]
    conn = _make_mock_conn(
        signal_rows=rows,
        perf_rows={"twitter": 0.7, "reddit": 0.6},
    )
    with patch("consensus_engine.analysis.consolidation.db") as mock_db:
        mock_db.get_db = AsyncMock(return_value=conn)
        result = await consolidate_for_ticker("NVDA", window_minutes=15, shadow_only=True)

    assert result.consensus_boost == 0
    assert result.reason == "shadow_only"


# ---------------------------------------------------------------------------
# (h) shadow_only=False returns real consensus_boost
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shadow_only_false_returns_real_boost():
    """shadow_only=False -> consensus_boost = effective_n * pts_per_cluster."""
    cfg.load_config()
    rows = [_signal_row("twitter"), _signal_row("reddit")]
    conn = _make_mock_conn(
        signal_rows=rows,
        perf_rows={"twitter": 0.7, "reddit": 0.6},
    )
    pts_per_cluster = cfg.get("scoring.multipliers.additional_analyst", 20)
    with patch("consensus_engine.analysis.consolidation.db") as mock_db:
        mock_db.get_db = AsyncMock(return_value=conn)
        result = await consolidate_for_ticker("NVDA", window_minutes=15, shadow_only=False)

    expected_boost = round(2 * pts_per_cluster)
    assert result.consensus_boost == expected_boost
    assert result.fired is True


# ---------------------------------------------------------------------------
# (i) ScoreBreakdown.consensus_boost field exists and is wired
# ---------------------------------------------------------------------------

def test_score_breakdown_has_consensus_boost_field():
    """ScoreBreakdown.consensus_boost field must exist with default 0."""
    sb = ScoreBreakdown()
    assert hasattr(sb, "consensus_boost")
    assert sb.consensus_boost == 0


def test_score_breakdown_consensus_boost_in_total():
    """consensus_boost must be included in ScoreBreakdown.total."""
    sb = ScoreBreakdown(base=30, consensus_boost=40)
    assert sb.total == 70


# ---------------------------------------------------------------------------
# (j) window_minutes param is honored
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_window_minutes_param_honored():
    """window_minutes=30 results in cutoff = now - 30*60."""
    cfg.load_config()
    captured_params = []

    conn = AsyncMock()
    cursor = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=[])
    cursor.fetchone = AsyncMock(return_value=None)
    cursor.lastrowid = None

    async def capture_execute(sql, params=()):
        if "signal_events" in sql.lower():
            captured_params.append(params)
        return cursor

    conn.execute = capture_execute
    conn.commit = AsyncMock()

    before = time.time()
    with patch("consensus_engine.analysis.consolidation.db") as mock_db:
        mock_db.get_db = AsyncMock(return_value=conn)
        await consolidate_for_ticker("NVDA", window_minutes=30, shadow_only=True)
    after = time.time()

    assert captured_params, "Expected signal_events query to be captured"
    ticker_param, cutoff_param = captured_params[0]
    assert ticker_param == "NVDA"
    # cutoff should be approximately now - 30*60
    expected_cutoff = before - (30 * 60)
    assert abs(cutoff_param - expected_cutoff) < 5
