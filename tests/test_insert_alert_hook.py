# tests/test_insert_alert_hook.py
import pytest
from consensus_engine import db


@pytest.fixture(autouse=True)
async def _isolated(tmp_path, monkeypatch):
    import consensus_engine.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    dbmod._db = None
    await dbmod.init_db()
    monkeypatch.setattr("consensus_engine.config.get",
                        lambda k, default=None: True if k == "atlas.enabled" else default)
    yield
    dbmod._db = None


async def test_insert_alert_enqueues_atlas_job():
    await db.insert_alert("NVDA", 80.0, "earnings beat", "news", "{}", "{}", "{}", 150.0)
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT ticker, reason FROM research_jobs WHERE ticker='NVDA'"
    )
    row = await cur.fetchone()
    assert row is not None
    assert row["reason"] == "alert"


async def test_insert_alert_respects_atlas_disabled(monkeypatch):
    monkeypatch.setattr("consensus_engine.config.get",
                        lambda k, default=None: False if k == "atlas.enabled" else default)
    await db.insert_alert("AAPL", 75.0, "x", "news", "{}", "{}", "{}", 200.0)
    conn = await db.get_db()
    cur = await conn.execute("SELECT COUNT(*) AS c FROM research_jobs")
    assert (await cur.fetchone())["c"] == 0
