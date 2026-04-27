"""Contract tests for source_performance table schema."""
import pytest
import time


@pytest.fixture(autouse=True)
async def fresh_db(tmp_path):
    import consensus_engine.db as db_module
    db_module.DB_PATH = str(tmp_path / "test.db")
    db_module._db = None
    await db_module.init_db()
    yield
    await db_module.close_db()
    db_module._db = None
    db_module.DB_PATH = None


async def test_rolling_accuracy_is_in_0_1_range():
    """rolling_accuracy must be a value in [0.0, 1.0]."""
    import consensus_engine.db as db_module
    conn = await db_module.get_db()
    await conn.execute(
        "INSERT INTO source_performance (entity_id, horizon, rolling_accuracy, sample_count, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("@TestAnalyst", "1h", 0.75, 10, time.time()),
    )
    await conn.commit()
    cur = await conn.execute("SELECT rolling_accuracy FROM source_performance WHERE entity_id='@TestAnalyst'")
    row = await cur.fetchone()
    assert row is not None
    assert 0.0 <= row["rolling_accuracy"] <= 1.0


async def test_entity_id_is_non_null():
    """entity_id must be a non-null string."""
    import consensus_engine.db as db_module
    conn = await db_module.get_db()
    await conn.execute(
        "INSERT INTO source_performance (entity_id, horizon, rolling_accuracy, sample_count, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("@AnotherAnalyst", "24h", 0.6, 5, time.time()),
    )
    await conn.commit()
    cur = await conn.execute("SELECT entity_id FROM source_performance WHERE entity_id='@AnotherAnalyst'")
    row = await cur.fetchone()
    assert row is not None
    assert row["entity_id"] is not None
    assert row["entity_id"] == "@AnotherAnalyst"


async def test_horizon_enum_values_stable():
    """horizon column accepts expected values (1h, 24h, 7d)."""
    import consensus_engine.db as db_module
    conn = await db_module.get_db()
    for horizon in ("1h", "24h", "7d"):
        await conn.execute(
            "INSERT OR REPLACE INTO source_performance (entity_id, horizon, rolling_accuracy, sample_count, updated_at) VALUES (?, ?, ?, ?, ?)",
            (f"@Analyst_{horizon}", horizon, 0.5, 1, time.time()),
        )
    await conn.commit()
    cur = await conn.execute("SELECT horizon FROM source_performance WHERE entity_id LIKE '@Analyst_%'")
    rows = await cur.fetchall()
    horizons = {r["horizon"] for r in rows}
    assert horizons == {"1h", "24h", "7d"}
