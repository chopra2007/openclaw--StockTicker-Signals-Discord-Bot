# tests/test_atlas_worker.py
import asyncio
import os
import pytest
from consensus_engine import db
from consensus_engine.research import atlas


@pytest.fixture(autouse=True)
async def _isolated(tmp_path, monkeypatch):
    import consensus_engine.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    dbmod._db = None
    await dbmod.init_db()
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake")
    monkeypatch.setattr("consensus_engine.config.get",
                        lambda k, default=None: {
                            "vault.path": str(tmp_path / "vault"),
                            "atlas.lease_ttl_seconds": 1800,
                            "atlas.cache_days": 7,
                            "atlas.sources": {"analyst": True, "sec": True, "news": True},
                            "alfred.market_holidays": [],
                            "llm.model": "x",
                            "llm.max_tokens": 512,
                        }.get(k, default))
    yield
    dbmod._db = None


async def test_process_job_writes_sections_and_vault(monkeypatch, tmp_path):
    from consensus_engine.research import sources
    async def ok_analyst(t): return "analyst md"
    async def ok_sec(t): return "sec md"
    async def ok_news(t): return "news md"
    monkeypatch.setattr(sources, "fetch_analyst_section", ok_analyst)
    monkeypatch.setattr(sources, "fetch_sec_section", ok_sec)
    monkeypatch.setattr(sources, "fetch_news_section", ok_news)

    job_id = await db.enqueue_atlas_job("NVDA", "sweep")
    job = await db.acquire_atlas_lease(1800)
    await atlas._process_job(job)

    secs = await db.get_research_sections("NVDA")
    assert secs["analyst"]["status"] == "ok"
    assert secs["sec"]["status"] == "ok"
    assert secs["news"]["status"] == "ok"
    vault_file = tmp_path / "vault" / "tickers" / "NVDA.md"
    assert vault_file.exists()
    assert "analyst md" in vault_file.read_text()


async def test_process_job_failed_source_preserves_last_good(monkeypatch, tmp_path):
    from consensus_engine.research import sources
    calls = {"analyst": 0}
    async def flaky_analyst(t):
        calls["analyst"] += 1
        if calls["analyst"] == 1:
            return "first success"
        raise RuntimeError("boom")
    async def ok(t): return "x"
    monkeypatch.setattr(sources, "fetch_analyst_section", flaky_analyst)
    monkeypatch.setattr(sources, "fetch_sec_section", ok)
    monkeypatch.setattr(sources, "fetch_news_section", ok)

    # First run succeeds
    await db.enqueue_atlas_job("NVDA", "sweep")
    job = await db.acquire_atlas_lease(1800)
    await atlas._process_job(job)
    # Second run: analyst raises, should preserve last_good
    await db.enqueue_atlas_job("NVDA", "alert")
    job = await db.acquire_atlas_lease(1800)
    await atlas._process_job(job)

    secs = await db.get_research_sections("NVDA")
    assert secs["analyst"]["status"] == "failed"
    assert secs["analyst"]["last_good_content"] == "first success"
