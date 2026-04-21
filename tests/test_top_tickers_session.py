import time
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


async def test_top_tickers_by_count_in_window():
    now = time.time()
    conn = await db.get_db()
    rows = [
        ("NVDA", "twitter", "a", "x", "neutral", now - 100, now + 3600),
        ("NVDA", "twitter", "a", "y", "neutral", now - 200, now + 3600),
        ("NVDA", "twitter", "a", "z", "neutral", now - 300, now + 3600),
        ("AAPL", "twitter", "b", "x", "neutral", now - 100, now + 3600),
        ("AAPL", "twitter", "b", "y", "neutral", now - 150, now + 3600),
        ("TSLA", "twitter", "c", "x", "neutral", now - 100, now + 3600),
        # outside window — should be excluded
        ("MSFT", "twitter", "d", "x", "neutral", now - 100000, now + 3600),
    ]
    for r in rows:
        await conn.execute(
            "INSERT INTO ticker_signals (ticker, source_type, source_detail, raw_text, sentiment, detected_at, expires_at) "
            "VALUES (?,?,?,?,?,?,?)", r,
        )
    await conn.commit()

    top = await db.get_top_tickers_session(now - 3600, now, limit=10)
    # Order: NVDA (3) > AAPL (2) > TSLA (1); MSFT excluded
    assert top[:3] == ["NVDA", "AAPL", "TSLA"]
    assert "MSFT" not in top
