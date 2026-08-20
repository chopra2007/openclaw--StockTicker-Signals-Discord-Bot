"""TODO #89: YouTube's nightly per-IP feed block — retry it, then stop hammering it.

Every RSS 404 in 15 days of journal logs fell between 19:00 and 23:59 PDT and
cleared at midnight Pacific, while the same feeds returned 200 outside that
window. So a 404 is transient, and a cycle where half the feeds fail means we
are blocked — not that half the channels vanished.
"""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from consensus_engine import config as cfg, db
import consensus_engine.scanners.youtube as youtube_mod

VALID_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <entry><yt:videoId>vid001</yt:videoId><title>T</title>
  <published>2026-08-20T10:00:00+00:00</published></entry>
</feed>"""


def _resp(status, body=""):
    r = AsyncMock()
    r.status = status
    r.text = AsyncMock(return_value=body)
    r.__aenter__ = AsyncMock(return_value=r)
    r.__aexit__ = AsyncMock(return_value=False)
    return r


@pytest.fixture(autouse=True)
def _reset_breaker():
    youtube_mod._rss_block_until = 0.0
    youtube_mod._rss_block_streak = 0
    yield
    youtube_mod._rss_block_until = 0.0
    youtube_mod._rss_block_streak = 0


@pytest.mark.asyncio
async def test_404_is_retried_and_recovers(monkeypatch):
    """A 404 must not end the attempt — the next try often returns the feed."""
    session = MagicMock()
    session.get = MagicMock(side_effect=[_resp(404), _resp(200, VALID_RSS)])
    monkeypatch.setattr(youtube_mod.asyncio, "sleep", AsyncMock())

    videos, ok, _ = await youtube_mod._fetch_channel_videos_rss_result(session, "UC1", 5)

    assert ok is True
    assert len(videos) == 1
    assert session.get.call_count == 2


@pytest.mark.asyncio
async def test_404_every_time_still_gives_up(monkeypatch):
    """Retrying is bounded — a feed that only ever 404s stops at _RSS_ATTEMPTS."""
    session = MagicMock()
    session.get = MagicMock(side_effect=[_resp(404) for _ in range(10)])
    monkeypatch.setattr(youtube_mod.asyncio, "sleep", AsyncMock())

    videos, ok, detail = await youtube_mod._fetch_channel_videos_rss_result(session, "UC1", 5)

    assert (videos, ok) == ([], False)
    assert detail == "HTTP 404"
    assert session.get.call_count == youtube_mod._RSS_ATTEMPTS


def _setup_scan(monkeypatch, channels, results):
    if cfg._config is None:
        cfg.load_config()
    monkeypatch.setitem(cfg._config["youtube"], "channel_ids", channels)
    monkeypatch.setitem(cfg._config["youtube"], "rss_pace_seconds", 0)
    monkeypatch.setattr(db, "get_approved_youtube_channels", AsyncMock(return_value=[]))
    monkeypatch.setattr(db, "downgrade_stale_quota_blocked", AsyncMock(return_value=0))
    monkeypatch.setattr(db, "get_retryable_youtube_videos", AsyncMock(return_value=[]))
    monkeypatch.setattr(db, "has_video_been_processed", AsyncMock(return_value=True))
    monkeypatch.setattr(youtube_mod, "get_session", AsyncMock(return_value=MagicMock()))
    fetch = AsyncMock(side_effect=results)
    monkeypatch.setattr(youtube_mod, "_fetch_channel_videos_rss_result", fetch)
    report = AsyncMock()
    monkeypatch.setattr("consensus_engine.alerts.ops_alert.report_ops_state", report)
    return fetch, report


@pytest.mark.asyncio
async def test_majority_failure_abandons_the_cycle(monkeypatch):
    """Once half the feeds are refused, the rest of the cycle is not attempted."""
    channels = [f"UC{i}" for i in range(8)]
    fetch, report = _setup_scan(monkeypatch, channels, [([], False, "HTTP 404")] * 8)

    await youtube_mod._youtube_scan_once_locked()

    # Threshold is 4 of 8 — it stops there rather than burning all 8.
    assert fetch.await_count == 4
    assert report.await_args.kwargs["down"] is True
    assert "4 of the 4" in report.await_args.kwargs["detail"]
    assert youtube_mod._rss_block_until > 0


@pytest.mark.asyncio
async def test_blocked_cycle_skips_the_next_poll_entirely(monkeypatch):
    """While the backoff runs, no feed request is made at all."""
    channels = [f"UC{i}" for i in range(8)]
    fetch, report = _setup_scan(monkeypatch, channels, [([], False, "HTTP 404")] * 8)
    await youtube_mod._youtube_scan_once_locked()
    fetch.reset_mock()
    report.reset_mock()

    await youtube_mod._youtube_scan_once_locked()

    assert fetch.await_count == 0
    report.assert_not_awaited()      # no repeat alert, state stays down


@pytest.mark.asyncio
async def test_backoff_doubles_then_resets_on_a_clean_cycle(monkeypatch):
    """A backoff that never resets pins at the ceiling — a good cycle must clear it."""
    channels = [f"UC{i}" for i in range(8)]
    _setup_scan(monkeypatch, channels, [([], False, "HTTP 404")] * 8)
    await youtube_mod._youtube_scan_once_locked()
    assert youtube_mod._rss_block_streak == 1
    first = youtube_mod._rss_block_until - youtube_mod.time.monotonic()

    youtube_mod._rss_block_until = 0.0        # simulate the pause expiring
    _setup_scan(monkeypatch, channels, [([], False, "HTTP 404")] * 8)
    await youtube_mod._youtube_scan_once_locked()
    second = youtube_mod._rss_block_until - youtube_mod.time.monotonic()
    assert youtube_mod._rss_block_streak == 2
    assert second > first * 1.9

    youtube_mod._rss_block_until = 0.0
    _, report = _setup_scan(monkeypatch, channels, [([{"video_id": "v"}], True, "")] * 8)
    await youtube_mod._youtube_scan_once_locked()

    assert youtube_mod._rss_block_streak == 0
    assert youtube_mod._rss_block_until == 0.0
    assert report.await_args.kwargs["down"] is False


@pytest.mark.asyncio
async def test_isolated_failure_does_not_blame_the_daily_limit(monkeypatch):
    """One stray failure is not evidence of a block — don't tell the user it is."""
    channels = [f"UC{i}" for i in range(8)]
    results = [([], False, "TimeoutError")] + [([{"video_id": "v"}], True, "")] * 7
    _, report = _setup_scan(monkeypatch, channels, results)

    await youtube_mod._youtube_scan_once_locked()

    detail = report.await_args.kwargs["detail"]
    assert report.await_args.kwargs["down"] is True
    assert "1 of the 8" in detail
    assert "midnight" not in detail
    assert youtube_mod._rss_block_until == 0.0
