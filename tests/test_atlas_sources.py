# tests/test_atlas_sources.py
import time
import pytest
from consensus_engine import db
from consensus_engine.research import sources


@pytest.fixture(autouse=True)
async def _isolated_db(tmp_path, monkeypatch):
    import consensus_engine.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    dbmod._db = None
    await dbmod.init_db()
    yield
    dbmod._db = None


async def test_analyst_section_queries_twitter_signals(monkeypatch):
    conn = await db.get_db()
    now = time.time()
    for i, txt in enumerate(["NVDA bullish", "NVDA target $150", "NVDA upgrade"]):
        await conn.execute(
            "INSERT INTO ticker_signals (ticker, source_type, source_detail, raw_text, sentiment, detected_at, expires_at) "
            "VALUES (?,?,?,?,?,?,?)",
            ("NVDA", "twitter", f"@analyst{i}", txt, "bullish", now - i * 100, now + 3600),
        )
    await conn.commit()

    captured = {}
    async def fake_llm(prompt: str) -> str:
        captured["prompt"] = prompt
        return "Three bullish NVDA calls in last 30 days."
    monkeypatch.setattr(sources, "_summarize_with_llm", fake_llm)

    summary = await sources.fetch_analyst_section("NVDA")
    assert summary.startswith("Three bullish")
    assert "NVDA bullish" in captured["prompt"]


async def test_analyst_section_returns_none_when_no_signals(monkeypatch):
    async def fake_llm(prompt: str) -> str:
        raise AssertionError("LLM should not be called when no signals")
    monkeypatch.setattr(sources, "_summarize_with_llm", fake_llm)
    out = await sources.fetch_analyst_section("ZZZZ")
    assert out is None
