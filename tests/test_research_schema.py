import pytest
from consensus_engine import db


async def test_research_tables_exist(tmp_path, monkeypatch):
    monkeypatch.setattr("consensus_engine.db.DB_PATH", str(tmp_path / "t.db"), raising=False)
    # Force re-init
    import consensus_engine.db as dbmod
    dbmod._db = None
    await dbmod.init_db()
    conn = await dbmod.get_db()
    cur = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('research_jobs','research_sections','briefing_runs')"
    )
    rows = await cur.fetchall()
    names = sorted(r["name"] for r in rows)
    assert names == ["briefing_runs", "research_jobs", "research_sections"]
