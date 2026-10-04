"""Video-reader symbols must be real, quotable symbols (TODO #116)."""
import pytest
from consensus_engine import db, config as cfg
from consensus_engine.analysis.ticker_grounding import resolve_video_ticker


@pytest.fixture(autouse=True)
def setup_config():
    cfg.load_config()


@pytest.fixture
async def tmp_db(tmp_path):
    cfg._config["database"] = {"path": str(tmp_path / "t.db"), "signal_ttl_hours": 2, "alert_history_days": 90}
    conn = await db.init_db()
    yield conn
    await db.close_db()


@pytest.mark.parametrize("raw,want", [
    ("NVIDIA", "NVDA"), ("Nebius", "NBIS"), ("$nvda", "NVDA"), ("NVDA", "NVDA"), ("META", "META"),
])
def test_resolves_names_and_keeps_real_symbols(raw, want):
    assert resolve_video_ticker(raw) == (want, None)


@pytest.mark.parametrize("raw", ["NASDAQ", "SPXW", "SPIRIT", "USDJPY", "BTCUSD"])
def test_flags_non_shares(raw):
    assert resolve_video_ticker(raw) == (raw, "invalid_symbol")


@pytest.mark.parametrize("raw", ["SPY", "QQQ", "LOD.V", "AMD", "SUSD"])
def test_leaves_other_symbols_alone(raw):
    assert resolve_video_ticker(raw) == (raw, None)


async def _rows(table):
    conn = await db.get_db()
    cur = await conn.execute(f"SELECT ticker, suppressed, suppression_reason FROM {table}")
    return [tuple(r) for r in await cur.fetchall()]


@pytest.mark.asyncio
async def test_inserts_fix_or_suppress(tmp_db):
    await db.insert_youtube_signal("v1", "ch", "NVIDIA", "long", "high")
    await db.insert_youtube_signal("v1", "ch", "USDJPY", "long", "high")
    await db.insert_youtube_level("v1", "NVIDIA", "support", 100.0)
    await db.insert_youtube_level("v1", "SPXW", "support", 5000.0)
    run_id = await db.create_analysis_run("v1", "v2")
    await db.insert_youtube_catalyst(run_id, "v1", "NASDAQ", "earnings")
    assert await _rows("youtube_signals") == [("NVDA", 0, None), ("USDJPY", 1, "invalid_symbol")]
    assert await _rows("youtube_levels") == [("NVDA", 0, None), ("SPXW", 1, "invalid_symbol")]
    assert await _rows("youtube_catalysts") == [("NASDAQ", 1, "invalid_symbol")]
