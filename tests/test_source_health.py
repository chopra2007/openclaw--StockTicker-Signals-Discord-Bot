"""Tests for source health DB helpers, updater loop, and !source-health command."""
import time
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from consensus_engine import db, config as cfg


@pytest.fixture(autouse=True)
def setup_config():
    cfg.load_config()


@pytest.fixture
async def test_db(tmp_path):
    db_path = str(tmp_path / "test_sh.db")
    cfg._config["database"] = {"path": db_path, "signal_ttl_hours": 2, "alert_history_days": 90}
    conn = await db.init_db()
    yield conn
    await db.close_db()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_and_get_source_health(test_db):
    """upsert_source_health writes a row; get_source_health retrieves it."""
    now = time.time()
    await db.upsert_source_health("finnhub", now, 0.05, 30.0)

    row = await db.get_source_health("finnhub")
    assert row is not None
    assert row["source_id"] == "finnhub"
    assert abs(row["last_heartbeat"] - now) < 1
    assert row["error_rate"] == pytest.approx(0.05)
    assert row["freshness_seconds"] == pytest.approx(30.0)


@pytest.mark.asyncio
async def test_upsert_source_health_replace(test_db):
    """Second upsert overwrites the first (INSERT OR REPLACE)."""
    t1 = time.time() - 100
    await db.upsert_source_health("nitter", t1, 0.1, 120.0)

    t2 = time.time()
    await db.upsert_source_health("nitter", t2, 0.0, 5.0)

    row = await db.get_source_health("nitter")
    assert row["error_rate"] == pytest.approx(0.0)
    assert row["freshness_seconds"] == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_get_all_source_health_ordered(test_db):
    """get_all_source_health returns rows alphabetically by source_id."""
    now = time.time()
    await db.upsert_source_health("yfinance", now, 0.0, 10.0)
    await db.upsert_source_health("apewisdom", now, 0.0, 60.0)
    await db.upsert_source_health("finnhub", now, 0.02, 25.0)

    rows = await db.get_all_source_health()
    ids = [r["source_id"] for r in rows]
    assert ids == sorted(ids)


@pytest.mark.asyncio
async def test_get_source_health_missing(test_db):
    """get_source_health returns None for unknown source."""
    result = await db.get_source_health("nonexistent_source")
    assert result is None


# ---------------------------------------------------------------------------
# source_health_updater_loop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_source_health_updater_writes_rows(test_db):
    """source_health_updater_loop flushes _source_stats to DB."""
    import asyncio
    from consensus_engine.main import source_health_updater_loop, _source_stats, _record_source_ok

    # Seed an in-process stat
    _record_source_ok("finnhub")

    stop = asyncio.Event()
    # Run one tick then stop
    stop.set()
    await source_health_updater_loop(stop)

    row = await db.get_source_health("finnhub")
    assert row is not None
    assert row["error_rate"] == pytest.approx(0.0)
    assert row["freshness_seconds"] < 5.0  # just updated


@pytest.mark.asyncio
async def test_record_source_error_affects_error_rate(test_db):
    """_record_source_error increments error count; updater writes non-zero error_rate."""
    import asyncio
    from consensus_engine.main import (
        source_health_updater_loop,
        _source_stats,
        _record_source_ok,
        _record_source_error,
    )

    # 1 success, 2 errors → error_rate = 2/3
    _source_stats["test_src"] = {"calls": 0, "errors": 0, "last_ok": 0.0}
    _record_source_ok("test_src")
    _record_source_error("test_src")
    _record_source_error("test_src")

    stop = asyncio.Event()
    stop.set()
    await source_health_updater_loop(stop)

    row = await db.get_source_health("test_src")
    assert row is not None
    assert row["error_rate"] == pytest.approx(2 / 3, abs=0.01)


# ---------------------------------------------------------------------------
# !source-health command
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_source_health_command_no_data():
    """!source-health with empty DB replies with 'no data' message."""
    from consensus_engine.alerts.commands import route_command

    with patch("consensus_engine.alerts.commands.send_command_reply", new_callable=AsyncMock) as mock_send, \
         patch("consensus_engine.db.get_all_source_health", new_callable=AsyncMock, return_value=[]):
        await route_command("source-health", [], "chan1", "msg1")
        content = mock_send.call_args[0][2]
        assert "no source health" in content.lower() or "must run" in content.lower()


@pytest.mark.asyncio
async def test_source_health_command_formats_table():
    """!source-health with data renders a markdown table with status labels."""
    from consensus_engine.alerts.commands import route_command

    now = time.time()
    fake_rows = [
        {"source_id": "finnhub",  "last_heartbeat": now,        "error_rate": 0.0,  "freshness_seconds": 10.0},
        {"source_id": "nitter",   "last_heartbeat": now - 1000, "error_rate": 0.5,  "freshness_seconds": 1000.0},
        {"source_id": "yfinance", "last_heartbeat": 0,          "error_rate": 0.0,  "freshness_seconds": 9999.0},
    ]

    with patch("consensus_engine.alerts.commands.send_command_reply", new_callable=AsyncMock) as mock_send, \
         patch("consensus_engine.db.get_all_source_health", new_callable=AsyncMock, return_value=fake_rows):
        await route_command("source-health", [], "chan1", "msg1")

        content = mock_send.call_args[0][2]
        assert "finnhub" in content
        assert "nitter" in content
        assert "yfinance" in content
        # nitter has 50% error rate and high freshness → should be DEGRADED or OFFLINE
        assert "DEGRADED" in content or "OFFLINE" in content
        # finnhub is fresh → OK
        assert "OK" in content


@pytest.mark.asyncio
async def test_source_health_command_shows_critical_flag():
    """Critical sources are marked with * in the output."""
    from consensus_engine.alerts.commands import route_command

    now = time.time()
    fake_rows = [
        {"source_id": "finnhub", "last_heartbeat": now, "error_rate": 0.0, "freshness_seconds": 10.0},
    ]

    with patch("consensus_engine.alerts.commands.send_command_reply", new_callable=AsyncMock) as mock_send, \
         patch("consensus_engine.db.get_all_source_health", new_callable=AsyncMock, return_value=fake_rows):
        await route_command("source-health", [], "chan1", "msg1")

        content = mock_send.call_args[0][2]
        # finnhub is a critical source — should have * marker
        assert "*finnhub" in content or "finnhub*" in content or "* = critical" in content.lower()
