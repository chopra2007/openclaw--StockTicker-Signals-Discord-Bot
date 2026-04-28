"""Tests for YouTube RSS description extraction (yt-description-fetch spec section b)."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from consensus_engine.scanners.youtube import fetch_channel_videos_rss

_RSS_WITH_DESC = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/">
  <entry>
    <yt:videoId>vid001</yt:videoId>
    <title>Top 5 Stocks NOW</title>
    <published>2026-04-28T10:00:00+00:00</published>
    <media:group>
      <media:description>Stocks discussed: $AAPL, $MSFT, $TSLA. Don't miss this one!</media:description>
    </media:group>
  </entry>
  <entry>
    <yt:videoId>vid002</yt:videoId>
    <title>No Description Entry</title>
    <published>2026-04-27T10:00:00+00:00</published>
  </entry>
</feed>"""


def _make_session(body: str, status: int = 200):
    resp = AsyncMock()
    resp.status = status
    resp.text = AsyncMock(return_value=body)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get = MagicMock(return_value=resp)
    return session


@pytest.mark.asyncio
async def test_rss_description_extracted():
    """feed entry with media:group/media:description populates the 'description' key."""
    videos = await fetch_channel_videos_rss(_make_session(_RSS_WITH_DESC), "UCtest", limit=5)
    assert len(videos) == 2
    assert videos[0]["description"] == "Stocks discussed: $AAPL, $MSFT, $TSLA. Don't miss this one!"


@pytest.mark.asyncio
async def test_rss_description_empty_when_absent():
    """Entry without media:group yields empty string for 'description', not KeyError."""
    videos = await fetch_channel_videos_rss(_make_session(_RSS_WITH_DESC), "UCtest", limit=5)
    assert videos[1]["description"] == ""
