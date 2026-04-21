import pytest
from consensus_engine import db


@pytest.fixture(autouse=True)
async def _isolated_db(tmp_path, monkeypatch):
    import consensus_engine.db as dbmod
    from consensus_engine import config as cfg
    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "t.db"), "signal_ttl_hours": 2, "alert_history_days": 90}
    dbmod._db = None
    await dbmod.init_db()
    yield
    dbmod._db = None


async def test_upsert_ok_stores_content_and_last_good():
    await db.upsert_research_section("NVDA", "analyst", "signals summary", "ok")
    secs = await db.get_research_sections("NVDA")
    assert "analyst" in secs
    assert secs["analyst"]["content"] == "signals summary"
    assert secs["analyst"]["last_good_content"] == "signals summary"
    assert secs["analyst"]["status"] == "ok"
    assert secs["analyst"]["last_good_at"] is not None


async def test_upsert_failed_preserves_last_good():
    await db.upsert_research_section("NVDA", "news", "good content", "ok")
    await db.upsert_research_section("NVDA", "news", None, "failed")
    secs = await db.get_research_sections("NVDA")
    assert secs["news"]["status"] == "failed"
    assert secs["news"]["content"] is None
    assert secs["news"]["last_good_content"] == "good content"


async def test_get_research_sections_empty_ticker_returns_empty():
    secs = await db.get_research_sections("UNKNOWN")
    assert secs == {}
