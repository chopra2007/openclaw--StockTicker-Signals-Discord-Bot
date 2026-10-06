"""Backup discovery must preserve channel ownership, dates, and feed cooldowns."""
import json
from unittest.mock import AsyncMock, MagicMock
import pytest
from consensus_engine import config as cfg, db
from consensus_engine.scanners import youtube as yt

def response(status=200, body="", data=None, headers=None):
    r = AsyncMock()
    r.status = status
    r.headers = headers or {}
    r.text = AsyncMock(return_value=body)
    r.json = AsyncMock(return_value=data)
    r.__aenter__.return_value = r
    r.__aexit__.return_value = False
    return r

def page(kind, content):
    data = {"contents": {"twoColumnBrowseResultsRenderer": {"tabs": [
        {"tabRenderer": {"selected": True, "endpoint": {"commandMetadata": {
            "webCommandMetadata": {"url": "/channel/UCtest/" + kind}}},
            "content": {"richGridRenderer": {"contents": [
                {"richItemRenderer": {"content": content}}
            ]}}}}
    ]}}}
    return "var ytInitialData = " + json.dumps(data) + ";"

@pytest.fixture(autouse=True)
def setup(monkeypatch):
    cfg.load_config()
    monkeypatch.setattr(yt.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(db, "has_video_been_processed", AsyncMock(return_value=False))
    monkeypatch.setattr(db, "get_youtube_video", AsyncMock(return_value=None))
    yt._rss_block_until = 0
    yt._backup_metadata_cache.clear()
    yt._backup_block_until = 0
    yt._backup_metadata_key_until.clear()
    yield
    yt._rss_block_until = 0

@pytest.mark.asyncio
async def test_backup_reads_three_categories_and_preserves_metadata(monkeypatch):
    monkeypatch.setenv("SUPADATA_API_KEY", "test")
    monkeypatch.delenv("SUPADATA_API_KEY2", raising=False)
    monkeypatch.delenv("SUPADATA_API_KEY3", raising=False)
    items = [
        page("videos", {"lockupViewModel": {"contentId": "regular0001", "contentType": "LOCKUP_CONTENT_TYPE_VIDEO"}}),
        page("shorts", {"shortsLockupViewModel": {"onTap": {"innertubeCommand": {"reelWatchEndpoint": {"videoId": "shorts00001"}}}}}),
        page("streams", {"videoRenderer": {"videoId": "streams0001"}}),
    ]
    meta = lambda v: {"id": v, "title": v, "description": "source description",
                     "createdAt": "2026-10-01T00:00:00Z",
                     "additionalData": {"channelId": "UCtest"}}
    session = MagicMock()
    session.get.side_effect = [response(body=p) for p in items] + [
        response(data=meta(v)) for v in ("regular0001", "shorts00001", "streams0001")]
    videos, ok, detail = await yt._fetch_channel_videos_backup(session, "UCtest", 3)
    assert ok, detail
    assert {v["video_id"] for v in videos} == {"regular0001", "shorts00001", "streams0001"}
    assert all(v["published_at"] == "2026-10-01T00:00:00Z" for v in videos)
    assert all(v["description"] == "source description" for v in videos)
    assert session.get.call_count == 6

@pytest.mark.asyncio
async def test_backup_does_not_fetch_metadata_for_processed_videos(monkeypatch):
    monkeypatch.setattr(db, "has_video_been_processed", AsyncMock(return_value=True))
    session = MagicMock()
    session.get.return_value = response(body=page("videos", {"videoRenderer": {"videoId": "regular0001"}}))
    videos, ok, _ = await yt._fetch_channel_videos_backup(session, "UCtest", 3)
    assert ok and videos == []
    assert session.get.call_count == 3

@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [
    {"id": "regular0001", "createdAt": "2026-10-01T00:00:00Z", "additionalData": {"channelId": "UCother"}},
    {"id": "regular0001", "additionalData": {"channelId": "UCtest"}},
])
async def test_backup_rejects_wrong_channel_or_missing_date(monkeypatch, metadata):
    monkeypatch.setenv("SUPADATA_API_KEY", "test")
    session = MagicMock()
    session.get.side_effect = [response(body=page("videos", {"videoRenderer": {"videoId": "regular0001"}}))] * 3 + [response(data=metadata)]
    videos, ok, _ = await yt._fetch_channel_videos_backup(session, "UCtest", 3)
    assert not ok and videos == []

@pytest.mark.asyncio
async def test_429_stops_immediately_and_respects_retry_after():
    session = MagicMock()
    session.get.return_value = response(429, headers={"Retry-After": "3600"})
    before = yt.time.monotonic()
    _, ok, _ = await yt._fetch_channel_videos_rss_result(session, "UCtest")
    assert not ok
    assert session.get.call_count == 1
    assert yt._rss_block_until >= before + 3600

@pytest.mark.asyncio
async def test_successful_backup_clears_discovery_outage_during_rss_pause(monkeypatch):
    monkeypatch.setitem(cfg._config["youtube"], "channel_ids", ["UCtest"])
    monkeypatch.setattr(db, "get_approved_youtube_channels", AsyncMock(return_value=[]))
    monkeypatch.setattr(db, "get_retryable_youtube_videos", AsyncMock(return_value=[]))
    monkeypatch.setattr(db, "downgrade_stale_quota_blocked", AsyncMock(return_value=0))
    monkeypatch.setattr(yt, "get_session", AsyncMock(return_value=MagicMock()))
    rss = AsyncMock()
    monkeypatch.setattr(yt, "_fetch_channel_videos_rss_result", rss)
    backup = AsyncMock(return_value=([], True, ""))
    monkeypatch.setattr(yt, "_fetch_channel_videos_backup", backup)
    report = AsyncMock()
    monkeypatch.setattr("consensus_engine.alerts.ops_alert.report_ops_state", report)
    yt._rss_block_until = yt.time.monotonic() + 3600
    await yt._youtube_scan_once_locked()
    rss.assert_not_awaited()
    backup.assert_awaited_once()
    assert report.await_args.kwargs["down"] is False
@pytest.mark.asyncio
async def test_latest_processed_upload_does_not_promote_old_shorts(monkeypatch):
    monkeypatch.setenv("SUPADATA_API_KEY", "test")
    latest = {"video_id": "regular0001", "channel_id": "UCtest", "title": "Latest",
              "description": "", "published_at": "2026-10-04T00:00:00Z"}
    monkeypatch.setattr(db, "get_youtube_video", AsyncMock(side_effect=lambda vid: latest if vid == "regular0001" else None))
    session = MagicMock()
    session.get.side_effect = [
        response(body=page("videos", {"videoRenderer": {"videoId": "regular0001"}})),
        response(body=page("shorts", {"videoRenderer": {"videoId": "shorts00001"}})),
        response(body=page("streams", {})),
        response(data={"id": "shorts00001", "createdAt": "2025-01-01T00:00:00Z",
                       "additionalData": {"channelId": "UCtest"}}),
    ]
    videos, ok, detail = await yt._fetch_channel_videos_backup(session, "UCtest", 1)
    assert ok, detail
    assert videos[0]["video_id"] == "regular0001"
    # The old Short's metadata is retained so future checks spend no more credits.
    assert ("UCtest", "shorts00001") in yt._backup_metadata_cache

@pytest.mark.asyncio
async def test_backup_429_pauses_other_channels():
    session = MagicMock()
    session.get.return_value = response(429, headers={"Retry-After": "3600"})
    before = yt.time.monotonic()
    assert not (await yt._fetch_channel_videos_backup(session, "UC1", 3))[1]
    assert not (await yt._fetch_channel_videos_backup(session, "UC2", 3))[1]
    assert session.get.call_count == 1
    assert yt._backup_block_until >= before + 3600

@pytest.mark.asyncio
async def test_partial_metadata_failure_does_not_return_unsorted_old_uploads(monkeypatch):
    monkeypatch.setenv("SUPADATA_API_KEY", "test")
    monkeypatch.delenv("SUPADATA_API_KEY2", raising=False)
    monkeypatch.delenv("SUPADATA_API_KEY3", raising=False)
    saved = {"video_id": "regular0001", "channel_id": "UCtest", "title": "Old",
             "description": "", "published_at": "2025-01-01T00:00:00Z"}
    monkeypatch.setattr(db, "get_youtube_video", AsyncMock(side_effect=lambda vid: saved if vid == "regular0001" else None))
    session = MagicMock()
    session.get.side_effect = [
        response(body=page("videos", {"videoRenderer": {"videoId": "regular0001"}})),
        response(body=page("shorts", {"videoRenderer": {"videoId": "shorts00001"}})),
        response(body=page("streams", {})),
        response(500),
    ]
    videos, ok, _ = await yt._fetch_channel_videos_backup(session, "UCtest", 1)
    assert not ok and videos == []

@pytest.mark.asyncio
async def test_metadata_rate_limit_is_not_retried_for_every_channel(monkeypatch):
    monkeypatch.setenv("SUPADATA_API_KEY", "test")
    monkeypatch.delenv("SUPADATA_API_KEY2", raising=False)
    monkeypatch.delenv("SUPADATA_API_KEY3", raising=False)
    pages = [response(body=page("videos", {"videoRenderer": {"videoId": "regular0001"}}))] * 3
    session = MagicMock()
    session.get.side_effect = pages + [response(429, headers={"Retry-After": "3600"})] + pages
    before = yt.time.monotonic()
    assert not (await yt._fetch_channel_videos_backup(session, "UCtest", 1))[1]
    assert not (await yt._fetch_channel_videos_backup(session, "UCother", 1))[1]
    assert session.get.call_count == 7
    assert yt._backup_metadata_key_until["test"] >= before + 3600
