"""Tests for the YouTube RSS scanner."""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from consensus_engine import db, config as cfg
from consensus_engine.scanners.youtube import (
    fetch_channel_videos_rss,
    process_video,
)


@pytest.fixture(autouse=True)
def setup_config():
    cfg.load_config()


@pytest.fixture
async def test_db(tmp_path):
    db_path = str(tmp_path / "yt_scanner.db")
    cfg._config["database"] = {"path": db_path, "signal_ttl_hours": 2, "alert_history_days": 90}
    conn = await db.init_db()
    yield conn
    await db.close_db()


VALID_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <entry>
    <yt:videoId>abc123</yt:videoId>
    <title>First Video</title>
    <published>2026-04-06T10:00:00+00:00</published>
  </entry>
  <entry>
    <yt:videoId>def456</yt:videoId>
    <title>Second Video</title>
    <published>2026-04-05T10:00:00+00:00</published>
  </entry>
</feed>"""

MALFORMED_RSS = "<<this is not xml>>"


@pytest.mark.asyncio
async def test_rss_parse_success():
    import aiohttp
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value=VALID_RSS)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)

    videos = await fetch_channel_videos_rss(mock_session, "UCtest", limit=5)
    assert len(videos) == 2
    assert videos[0]["video_id"] == "abc123"
    assert videos[0]["title"] == "First Video"
    assert videos[1]["video_id"] == "def456"


@pytest.mark.asyncio
async def test_rss_parse_limit():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value=VALID_RSS)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)

    videos = await fetch_channel_videos_rss(mock_session, "UCtest", limit=1)
    assert len(videos) == 1
    assert videos[0]["video_id"] == "abc123"


@pytest.mark.asyncio
async def test_rss_malformed_returns_empty():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value=MALFORMED_RSS)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)

    videos = await fetch_channel_videos_rss(mock_session, "UCtest", limit=5)
    assert videos == []


@pytest.mark.asyncio
async def test_rss_http_error_returns_empty():
    mock_resp = AsyncMock()
    mock_resp.status = 503
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)

    videos = await fetch_channel_videos_rss(mock_session, "UCtest", limit=5)
    assert videos == []


@pytest.mark.asyncio
async def test_process_video_dedup(test_db, tmp_path):
    """Second call for same video_id after save should be a no-op."""
    semaphore = asyncio.Semaphore(1)
    video = {"video_id": "vidX", "channel_id": "UCX", "title": "T", "published_at": "2026-04-06T00:00:00Z"}

    with patch("consensus_engine.scanners.youtube.fetch_transcript",
               new=AsyncMock(return_value=("Some transcript text", "en", True))):
        await process_video(video, semaphore, ["en"], str(tmp_path))
        # second call — fetch_transcript should NOT be called again (video now processed)
        with patch("consensus_engine.scanners.youtube.fetch_transcript",
                   new=AsyncMock(side_effect=AssertionError("should not be called"))) as mock_ft2:
            await process_video(video, semaphore, ["en"], str(tmp_path))


@pytest.mark.asyncio
async def test_process_video_missing_captions(test_db, tmp_path):
    """Caption-unavailable error sets status to 'missing', does not raise."""
    semaphore = asyncio.Semaphore(1)
    video = {"video_id": "vidY", "channel_id": "UCY", "title": "No Caps", "published_at": "2026-04-06T00:00:00Z"}

    with patch("consensus_engine.scanners.youtube.fetch_transcript",
               new=AsyncMock(side_effect=Exception("no caption tracks for vidY"))):
        await process_video(video, semaphore, ["en"], str(tmp_path))

    conn = await db.get_db()
    cursor = await conn.execute("SELECT transcript_status FROM youtube_videos WHERE video_id='vidY'")
    row = await cursor.fetchone()
    assert row["transcript_status"] == "missing"
