# tests/test_atlas_sweep.py
import time
import pytest
from consensus_engine import db
from consensus_engine.research import atlas


@pytest.fixture(autouse=True)
async def _isolated(tmp_path, monkeypatch):
    import consensus_engine.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    dbmod._db = None
    await dbmod.init_db()
    monkeypatch.setattr("consensus_engine.config.get",
                        lambda k, default=None: {
                            "atlas.max_tickers_sweep": 3,
                            "atlas.cache_days": 7,
                            "atlas.enabled": True,
                        }.get(k, default))
    yield
    dbmod._db = None


async def test_sweep_enqueues_top_tickers():
    # Seed signals in session window
    conn = await db.get_db()
    now = time.time()
    for t, n in [("NVDA", 5), ("AAPL", 3), ("TSLA", 2), ("MSFT", 1)]:
        for i in range(n):
            await conn.execute(
                "INSERT INTO ticker_signals (ticker, source_type, source_detail, raw_text, sentiment, detected_at, expires_at) VALUES (?,?,?,?,?,?,?)",
                (t, "twitter", "a", "x", "neutral", now - 3600, now + 3600),
            )
    await conn.commit()

    await atlas._sweep_once(now - 7200, now)

    cur = await conn.execute(
        "SELECT ticker FROM research_jobs WHERE status='pending' ORDER BY created_at"
    )
    rows = await cur.fetchall()
    assert [r["ticker"] for r in rows] == ["NVDA", "AAPL", "TSLA"]


async def test_sweep_skips_fresh_tickers():
    conn = await db.get_db()
    now = time.time()
    await conn.execute(
        "INSERT INTO ticker_signals (ticker, source_type, source_detail, raw_text, sentiment, detected_at, expires_at) VALUES (?,?,?,?,?,?,?)",
        ("NVDA", "twitter", "a", "x", "neutral", now - 100, now + 3600),
    )
    # Fresh section already exists
    await db.upsert_research_section("NVDA", "analyst", "recent", "ok")
    await conn.commit()

    await atlas._sweep_once(now - 7200, now)

    cur = await conn.execute("SELECT COUNT(*) AS c FROM research_jobs")
    assert (await cur.fetchone())["c"] == 0
