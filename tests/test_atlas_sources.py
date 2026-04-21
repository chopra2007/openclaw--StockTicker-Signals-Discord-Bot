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


async def test_news_section_queries_searxng_and_summarizes(monkeypatch):
    async def fake_searxng(query):
        assert "NVDA" in query
        return [
            {"title": "NVDA jumps on AI guidance", "url": "https://x.com/a", "content": "..."},
            {"title": "Nvidia beats estimates", "url": "https://x.com/b", "content": "..."},
        ]
    async def fake_llm(prompt):
        assert "NVDA jumps" in prompt
        return "- AI guidance drove pop\n- Estimates beat"
    monkeypatch.setattr("consensus_engine.scanners.searxng.search_searxng", fake_searxng)
    monkeypatch.setattr(sources, "_summarize_with_llm", fake_llm)

    out = await sources.fetch_news_section("NVDA")
    assert out is not None
    assert "AI guidance" in out


async def test_news_section_returns_none_when_empty(monkeypatch):
    async def empty(q): return []
    monkeypatch.setattr("consensus_engine.scanners.searxng.search_searxng", empty)
    out = await sources.fetch_news_section("ZZZZ")
    assert out is None


async def test_sec_section_fetches_recent_8k(monkeypatch):
    async def fake_filings(ticker, limit=5):
        return [
            {"form": "8-K", "filed": "2026-04-19", "accession": "0001-abc",
             "items": "Item 2.02", "summary": "Q4 earnings released"},
            {"form": "10-Q", "filed": "2026-03-10", "accession": "0002-def",
             "items": "", "summary": "Quarterly report"},
        ]
    async def fake_llm(prompt):
        assert "Q4 earnings" in prompt
        return "- Q4 beat, revenue $60B"
    monkeypatch.setattr(sources, "_recent_filings", fake_filings)
    monkeypatch.setattr(sources, "_summarize_with_llm", fake_llm)

    out = await sources.fetch_sec_section("NVDA")
    assert out is not None
    assert "Q4" in out


async def test_sec_section_returns_none_on_no_filings(monkeypatch):
    async def empty(ticker, limit=5): return []
    monkeypatch.setattr(sources, "_recent_filings", empty)
    out = await sources.fetch_sec_section("ZZZZ")
    assert out is None
