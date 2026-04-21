import time
import pytest
from consensus_engine import db


@pytest.fixture(autouse=True)
async def _isolated_db(tmp_path, monkeypatch):
    import consensus_engine.db as dbmod
    from consensus_engine import config as cfg
    cfg.load_config()  # ensure _config is populated
    cfg._config["database"] = {"path": str(tmp_path / "t.db"), "signal_ttl_hours": 2, "alert_history_days": 90}
    dbmod._db = None
    await dbmod.init_db()
    yield
    dbmod._db = None


async def test_enqueue_creates_pending_job():
    job_id = await db.enqueue_atlas_job("NVDA", "sweep")
    assert job_id is not None
    conn = await db.get_db()
    cur = await conn.execute("SELECT * FROM research_jobs WHERE id=?", (job_id,))
    row = await cur.fetchone()
    assert row["ticker"] == "NVDA"
    assert row["status"] == "pending"
    assert row["reason"] == "sweep"


async def test_enqueue_coalesces_pending():
    first = await db.enqueue_atlas_job("NVDA", "sweep")
    second = await db.enqueue_atlas_job("NVDA", "alert")
    assert second is None  # coalesced
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT COUNT(*) AS c FROM research_jobs WHERE ticker='NVDA' AND status='pending'"
    )
    assert (await cur.fetchone())["c"] == 1


async def test_acquire_lease_returns_job_and_marks_running():
    await db.enqueue_atlas_job("AAPL", "sweep")
    job = await db.acquire_atlas_lease(1800)
    assert job is not None
    assert job["ticker"] == "AAPL"
    assert job["status"] == "running"
    # Second acquire gets nothing (lease held)
    job2 = await db.acquire_atlas_lease(1800)
    assert job2 is None


async def test_expired_lease_is_reacquirable():
    await db.enqueue_atlas_job("TSLA", "sweep")
    job = await db.acquire_atlas_lease(1800)
    # Manually expire the lease
    conn = await db.get_db()
    await conn.execute(
        "UPDATE research_jobs SET lease_expires_at=? WHERE id=?",
        (time.time() - 60, job["id"]),
    )
    await conn.commit()
    job2 = await db.acquire_atlas_lease(1800)
    assert job2 is not None
    assert job2["id"] == job["id"]


async def test_finish_atlas_job_sets_done():
    await db.enqueue_atlas_job("MSFT", "sweep")
    job = await db.acquire_atlas_lease(1800)
    await db.finish_atlas_job(job["id"], "done")
    conn = await db.get_db()
    cur = await conn.execute("SELECT status, finished_at FROM research_jobs WHERE id=?", (job["id"],))
    row = await cur.fetchone()
    assert row["status"] == "done"
    assert row["finished_at"] is not None
