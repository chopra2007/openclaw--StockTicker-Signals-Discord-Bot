"""Tests for Nitter RSS poller."""
import time
import pytest
from unittest.mock import AsyncMock, patch
from consensus_engine.scanners.nitter import parse_rss_feed, NitterPoller


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>@unusual_whales / Twitter</title>
    <item>
      <title>$NVDA unusual call activity detected. Large block at 950 strike.</title>
      <link>https://x.com/unusual_whales/status/111111</link>
      <pubDate>Wed, 26 Mar 2026 14:30:00 GMT</pubDate>
      <description>$NVDA unusual call activity detected. Large block at 950 strike.</description>
    </item>
    <item>
      <title>Market looking choppy today, be careful out there</title>
      <link>https://x.com/unusual_whales/status/222222</link>
      <pubDate>Wed, 26 Mar 2026 14:00:00 GMT</pubDate>
      <description>Market looking choppy today, be careful out there</description>
    </item>
  </channel>
</rss>"""

EMPTY_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>@nobody</title></channel></rss>"""

MALFORMED_RSS = """<not valid xml at all"""


def test_parse_rss_feed_extracts_items():
    items = parse_rss_feed(SAMPLE_RSS, "unusual_whales")
    assert len(items) == 2
    assert items[0]["url"] == "https://x.com/unusual_whales/status/111111"
    assert items[0]["analyst"] == "unusual_whales"
    assert "$NVDA" in items[0]["text"]


def test_parse_rss_feed_empty():
    items = parse_rss_feed(EMPTY_RSS, "nobody")
    assert items == []


def test_parse_rss_feed_malformed():
    items = parse_rss_feed(MALFORMED_RSS, "broken")
    assert items == []


def test_parse_rss_feed_timestamp():
    items = parse_rss_feed(SAMPLE_RSS, "unusual_whales")
    assert isinstance(items[0]["timestamp"], float)
    assert items[0]["timestamp"] > 0


@pytest.mark.asyncio
async def test_poller_deduplication(tmp_path):
    """Poller should skip tweets it has already seen."""
    from consensus_engine import db, config as cfg
    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "test.db"), "signal_ttl_hours": 2}
    await db.init_db()

    await db.mark_tweet_seen("https://x.com/unusual_whales/status/111111", "unusual_whales")

    poller = NitterPoller()
    items = parse_rss_feed(SAMPLE_RSS, "unusual_whales")

    new_items = []
    for item in items:
        if await db.is_new_tweet(item["url"]):
            new_items.append(item)

    assert len(new_items) == 1
    assert "222222" in new_items[0]["url"]

    await db.close_db()
