"""Tests for YouTube DB schema and helper methods."""
import time
import pytest
from consensus_engine import db, config as cfg


@pytest.fixture(autouse=True)
def setup_config():
    cfg.load_config()


@pytest.fixture
async def test_db(tmp_path):
    db_path = str(tmp_path / "test_yt.db")
    cfg._config["database"] = {"path": db_path, "signal_ttl_hours": 2, "alert_history_days": 90}
    conn = await db.init_db()
    yield conn
    await db.close_db()


@pytest.mark.asyncio
async def test_tables_created(test_db):
    conn = await db.get_db()
    cursor = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('youtube_videos','youtube_transcripts')"
    )
    rows = await cursor.fetchall()
    names = {r["name"] for r in rows}
    assert "youtube_videos" in names
    assert "youtube_transcripts" in names


@pytest.mark.asyncio
async def test_has_video_been_processed_unknown(test_db):
    result = await db.has_video_been_processed("nonexistent_id")
    assert result is False


@pytest.mark.asyncio
async def test_upsert_and_has_processed(test_db):
    await db.upsert_youtube_video("vid1", "UC123", "Title", "2026-04-06T00:00:00Z", time.time())
    # still pending → not "processed"
    result = await db.has_video_been_processed("vid1")
    assert result is False

    await db.mark_youtube_video_status("vid1", "saved", language="en", is_auto_generated=True, export_path="/tmp/vid1.json")
    result = await db.has_video_been_processed("vid1")
    assert result is True


@pytest.mark.asyncio
async def test_upsert_idempotent(test_db):
    for _ in range(3):
        await db.upsert_youtube_video("vid2", "UC456", "Dupe Title", "2026-04-06T01:00:00Z", time.time())
    conn = await db.get_db()
    cursor = await conn.execute("SELECT COUNT(*) as cnt FROM youtube_videos WHERE video_id='vid2'")
    row = await cursor.fetchone()
    assert row["cnt"] == 1


@pytest.mark.asyncio
async def test_mark_status_missing(test_db):
    await db.upsert_youtube_video("vid3", "UC789", "No Captions", "2026-04-06T02:00:00Z", time.time())
    await db.mark_youtube_video_status("vid3", "missing")
    result = await db.has_video_been_processed("vid3")
    assert result is True
    conn = await db.get_db()
    cursor = await conn.execute("SELECT transcript_status FROM youtube_videos WHERE video_id='vid3'")
    row = await cursor.fetchone()
    assert row["transcript_status"] == "missing"


@pytest.mark.asyncio
async def test_save_transcript(test_db):
    await db.upsert_youtube_video("vid4", "UCabc", "Has Transcript", "2026-04-06T03:00:00Z", time.time())
    await db.save_youtube_transcript("vid4", "This is the transcript text.", "abc123hash")
    conn = await db.get_db()
    cursor = await conn.execute("SELECT transcript_text, transcript_hash FROM youtube_transcripts WHERE video_id='vid4'")
    row = await cursor.fetchone()
    assert row["transcript_text"] == "This is the transcript text."
    assert row["transcript_hash"] == "abc123hash"


@pytest.mark.asyncio
async def test_save_transcript_idempotent(test_db):
    await db.upsert_youtube_video("vid5", "UCdef", "Repeated Save", "2026-04-06T04:00:00Z", time.time())
    await db.save_youtube_transcript("vid5", "text v1", "hash1")
    await db.save_youtube_transcript("vid5", "text v2", "hash2")
    conn = await db.get_db()
    cursor = await conn.execute("SELECT transcript_text FROM youtube_transcripts WHERE video_id='vid5'")
    row = await cursor.fetchone()
    assert row["transcript_text"] == "text v2"
