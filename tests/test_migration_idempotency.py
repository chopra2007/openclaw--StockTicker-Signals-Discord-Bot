"""Test that init_db is idempotent (schema_version unchanged on second call)."""
import pytest


async def test_init_db_twice_is_idempotent(tmp_path):
    import consensus_engine.db as db_module
    db_module.DB_PATH = str(tmp_path / "test.db")
    db_module._db = None

    conn = await db_module.init_db()
    cur = await conn.execute("SELECT MAX(version) as v FROM schema_version")
    row = await cur.fetchone()
    version_after_first = row["v"]

    cur = await conn.execute("PRAGMA user_version")
    row = await cur.fetchone()

    # Run init_db a second time (simulates restart)
    await db_module.close_db()
    db_module._db = None
    conn2 = await db_module.init_db()
    cur2 = await conn2.execute("SELECT MAX(version) as v FROM schema_version")
    row2 = await cur2.fetchone()
    version_after_second = row2["v"]

    assert version_after_first == version_after_second, "schema_version changed on second init_db call"
    assert version_after_first is not None

    await db_module.close_db()
    db_module._db = None
    db_module.DB_PATH = None
