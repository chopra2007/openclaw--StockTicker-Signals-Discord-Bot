import time
import pytest
from consensus_engine import db
from consensus_engine.briefing import alfred


@pytest.fixture(autouse=True)
async def _isolated(tmp_path, monkeypatch):
    import consensus_engine.db as dbmod
    from consensus_engine import config as cfg
    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "t.db"), "signal_ttl_hours": 2, "alert_history_days": 90}
    dbmod._db = None
    await dbmod.init_db()
    yield
    dbmod._db = None


async def test_build_briefing_data_bundles_all_sections():
    conn = await db.get_db()
    now = time.time()
    # seed an alert in window
    await db.insert_alert("NVDA", 80.0, "earnings", "news", "{}", "{}", "{}", 150.0)
    # seed a ticker signal so top-tickers has something
    await conn.execute(
        "INSERT INTO ticker_signals (ticker, source_type, source_detail, raw_text, sentiment, detected_at, expires_at) VALUES (?,?,?,?,?,?,?)",
        ("NVDA", "twitter", "a", "x", "bullish", now - 100, now + 3600),
    )
    # seed a research_sections last-good
    await db.upsert_research_section("NVDA", "analyst", "summary text", "ok")
    await conn.commit()

    data = await alfred.build_briefing_data(now - 3600, now + 3600)
    assert "alerts" in data and len(data["alerts"]) == 1
    assert data["alerts"][0]["ticker"] == "NVDA"
    assert "top_tickers" in data and "NVDA" in [t["ticker"] for t in data["top_tickers"]]
    assert data["top_tickers"][0]["sections"]["analyst"]["content"] == "summary text"
