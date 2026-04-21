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


async def test_upsert_creates_pending_then_transitions():
    await db.upsert_briefing_run(
        "2026-04-21",
        session_start_utc=1.0,
        session_end_utc=2.0,
        rendered_content="brief text",
        status="pending",
    )
    run = await db.get_briefing_run("2026-04-21")
    assert run["status"] == "pending"
    assert run["rendered_content"] == "brief text"

    await db.upsert_briefing_run(
        "2026-04-21",
        discord_message_id="msg123",
        status="posted",
    )
    run = await db.get_briefing_run("2026-04-21")
    assert run["status"] == "posted"
    assert run["discord_message_id"] == "msg123"
    assert run["posted_at"] is not None

    await db.upsert_briefing_run("2026-04-21", status="archived")
    run = await db.get_briefing_run("2026-04-21")
    assert run["status"] == "archived"
    assert run["archived_at"] is not None


async def test_get_missing_returns_none():
    run = await db.get_briefing_run("2099-01-01")
    assert run is None
