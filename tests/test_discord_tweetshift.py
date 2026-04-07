"""Tests for the TweetShift Discord message parser."""

import pytest
from consensus_engine.scanners.discord_tweetshift import (
    _parse_tweetshift_message,
    _normalize_handle,
    _known_handles,
)


def _embed_msg(author_name="", author_url="", description="", embed_url="", msg_id="123"):
    return {
        "id": msg_id,
        "channel_id": "your-discord-feed-channel-id",
        "content": "",
        "embeds": [{
            "author": {"name": author_name, "url": author_url},
            "description": description,
            "url": embed_url,
            "timestamp": "2026-03-27T12:00:00Z",
        }],
    }


class TestNormalizeHandle:
    def test_strips_at(self):
        assert _normalize_handle("@NickTimiraos") == "nicktimiraos"

    def test_already_clean(self):
        assert _normalize_handle("WOWSTrade") == "wowstrade"

    def test_lowercases(self):
        assert _normalize_handle("@CheddarFlow") == "cheddarflow"


class TestKnownHandles:
    def test_builds_set(self):
        handles = _known_handles(["@NickTimiraos", "@WOWSTrade"])
        assert "nicktimiraos" in handles
        assert "wowstrade" in handles


class TestParseTweetShiftMessage:
    def test_embed_with_author_url(self):
        msg = _embed_msg(
            author_name="Nick Timiraos",
            author_url="https://twitter.com/NickTimiraos",
            description="Fed likely to hold rates in March.",
            embed_url="https://twitter.com/NickTimiraos/status/99999",
        )
        result = _parse_tweetshift_message(msg)
        assert result is not None
        assert result["analyst"] == "NickTimiraos"
        assert result["text"] == "Fed likely to hold rates in March."
        assert result["url"] == "https://twitter.com/NickTimiraos/status/99999"

    def test_embed_with_x_url(self):
        msg = _embed_msg(
            author_url="https://x.com/CheddarFlow",
            description="$NVDA calls printing.",
        )
        result = _parse_tweetshift_message(msg)
        assert result is not None
        assert result["analyst"] == "CheddarFlow"

    def test_embed_author_name_at_handle(self):
        msg = _embed_msg(
            author_name="@unusual_whales",
            description="Dark pool activity spiking in $SPY.",
        )
        result = _parse_tweetshift_message(msg)
        assert result is not None
        assert result["analyst"] == "unusual_whales"

    def test_embed_no_url_falls_back(self):
        msg = _embed_msg(
            author_name="@data168",
            description="Some tweet text.",
            embed_url="",
        )
        result = _parse_tweetshift_message(msg)
        assert result is not None
        assert "twitter.com/data168" in result["url"]

    def test_plain_text_format(self):
        msg = {
            "id": "456",
            "channel_id": "your-discord-feed-channel-id",
            "content": "@traderstewie: $TSLA breaking out, watching 280 level.",
            "embeds": [],
        }
        result = _parse_tweetshift_message(msg)
        assert result is not None
        assert result["analyst"] == "traderstewie"
        assert "$TSLA" in result["text"]

    def test_empty_message_returns_none(self):
        msg = {"id": "789", "channel_id": "x", "content": "", "embeds": []}
        assert _parse_tweetshift_message(msg) is None

    def test_embed_no_description_skipped(self):
        msg = _embed_msg(
            author_url="https://twitter.com/someone",
            description="",
        )
        assert _parse_tweetshift_message(msg) is None

    def test_embed_title_fallback_when_description_missing(self):
        msg = _embed_msg(
            author_url="https://twitter.com/someone",
            description="",
        )
        msg["embeds"][0]["title"] = "$NVDA breaking out on volume"
        result = _parse_tweetshift_message(msg)
        assert result is not None
        assert "NVDA" in result["text"]

    def test_strips_bold_markdown(self):
        msg = _embed_msg(
            author_url="https://twitter.com/ripster47",
            description="**$AAPL** bullish setup forming.",
        )
        result = _parse_tweetshift_message(msg)
        assert result is not None
        assert "**" not in result["text"]
