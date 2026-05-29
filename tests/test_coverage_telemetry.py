"""C1 (coverage counter) + C2 (Gemini why-it-stopped telemetry).

Both persist new columns on youtube_analysis_runs and surface chart-read
coverage / failure category as queryable telemetry.
"""
import tempfile, os
import pytest

from consensus_engine import db
from consensus_engine.scanners import youtube as yt


@pytest.fixture
async def tmp_db():
    prev = db.DB_PATH
    db._db = None
    db.DB_PATH = tempfile.mktemp(suffix=".db")
    await db.init_db()
    yield
    await db.close_db()
    try:
        os.unlink(db.DB_PATH)
    except OSError:
        pass
    db.DB_PATH = prev
    db._db = None


async def test_coverage_counts_and_failure_category(tmp_db):
    r1 = await db.create_analysis_run("vidGEM", "p/v1")
    await db.update_analysis_run_metrics(run_id=r1, span_count=26, chain_winner="gemini/v2")
    r2 = await db.create_analysis_run("vidCAP", "p/v1")
    await db.update_analysis_run_metrics(
        run_id=r2, span_count=10, chain_winner="ytdlp-captions/v1", f2_failure_category="quota")

    counts = await db.get_youtube_coverage_counts(hours=24)
    assert counts.get("gemini/v2") == 1
    assert counts.get("ytdlp-captions/v1") == 1

    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT f2_failure_category FROM youtube_analysis_runs WHERE video_id='vidCAP'")
    assert (await cur.fetchone())["f2_failure_category"] == "quota"


async def test_daily_coverage_emits_once_per_day(tmp_db, monkeypatch, caplog):
    r1 = await db.create_analysis_run("v1", "p/v1")
    await db.update_analysis_run_metrics(run_id=r1, chain_winner="gemini/v2")

    yt._LAST_COVERAGE_DAY = None
    import logging
    with caplog.at_level(logging.INFO, logger="consensus_engine.scanner.youtube"):
        await yt._emit_daily_coverage()
        first = [r for r in caplog.records if "coverage (24h)" in r.message]
        await yt._emit_daily_coverage()  # same day -> no second emit
        second = [r for r in caplog.records if "coverage (24h)" in r.message]
    assert len(first) == 1
    assert len(second) == 1  # unchanged — gated to once per UTC day
