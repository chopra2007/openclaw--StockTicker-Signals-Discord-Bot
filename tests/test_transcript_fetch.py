"""Tests for multi-tier transcript fetch cascade."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from consensus_engine.utils.transcript_fetch import (
    _vtt_to_text,
    fetch_transcript_cascade,
    parse_video_id,
)


# ---------------------------------------------------------------------------
# parse_video_id
# ---------------------------------------------------------------------------

class TestParseVideoId:
    def test_watch_url(self):
        assert parse_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_url(self):
        assert parse_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_url_with_params(self):
        assert parse_video_id("https://youtu.be/dQw4w9WgXcQ?si=xyz") == "dQw4w9WgXcQ"

    def test_shorts_url(self):
        assert parse_video_id("https://youtube.com/shorts/6UMKh-kmRWw?si=test") == "6UMKh-kmRWw"

    def test_embed_url(self):
        assert parse_video_id("https://youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_invalid_url(self):
        assert parse_video_id("https://example.com/page") is None

    def test_empty_watch(self):
        assert parse_video_id("https://youtube.com/watch") is None


# ---------------------------------------------------------------------------
# _vtt_to_text
# ---------------------------------------------------------------------------

class TestVttToText:
    def test_basic_vtt(self):
        vtt = (
            "WEBVTT\n\n"
            "1\n"
            "00:00:01.000 --> 00:00:03.000\n"
            "Hello world\n\n"
            "2\n"
            "00:00:03.000 --> 00:00:05.000\n"
            "Testing here\n"
        )
        assert _vtt_to_text(vtt) == "Hello world Testing here"

    def test_deduplication(self):
        vtt = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "Hello world\n\n"
            "00:00:02.000 --> 00:00:03.000\n"
            "Hello world\n\n"
            "00:00:03.000 --> 00:00:04.000\n"
            "New line\n"
        )
        assert _vtt_to_text(vtt) == "Hello world New line"

    def test_strips_vtt_tags(self):
        vtt = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:03.000\n"
            "<c>Hello</c> <00:00:02.000>world\n"
        )
        assert _vtt_to_text(vtt) == "Hello world"

    def test_empty_vtt(self):
        assert _vtt_to_text("WEBVTT\n\n") == ""


# ---------------------------------------------------------------------------
# Cascade logic
# ---------------------------------------------------------------------------

class TestFetchTranscriptCascade:
    # The cascade is Supadata-only now — the Invidious-captions and
    # youtube-transcript-api tiers were removed 2026-06-09 (dead on this VPS's
    # blacklisted IP). Only Supadata fetches via its own residential network.
    @pytest.fixture(autouse=True)
    def _patch_tiers(self):
        base = "consensus_engine.utils.transcript_fetch"
        with patch(f"{base}._fetch_via_supadata") as self.mock_supadata:
            self.mock_supadata.return_value = None  # default: fail
            yield

    async def test_supadata_wins(self):
        self.mock_supadata.return_value = ("hello world", "en", True)
        text, lang, auto = await fetch_transcript_cascade("abc123")
        assert text == "hello world"
        assert lang == "en"

    async def test_supadata_none_raises(self):
        # Supadata is the only tier; None → total failure.
        with pytest.raises(ValueError, match="All transcript sources failed"):
            await fetch_transcript_cascade("abc123")

    async def test_supadata_exception_raises(self):
        # An exception in the only tier is swallowed → still raises (no fallback left).
        self.mock_supadata.side_effect = RuntimeError("boom")
        with pytest.raises(ValueError, match="All transcript sources failed"):
            await fetch_transcript_cascade("abc123")


# ---------------------------------------------------------------------------
# Supadata multi-key rotation
# ---------------------------------------------------------------------------

def _supadata_ctx(status=200, content="hello"):
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value={"content": content, "lang": "en"})
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


class TestSupadataKeyRotation:
    @pytest.fixture(autouse=True)
    def _three_keys(self, monkeypatch):
        import consensus_engine.utils.transcript_fetch as T
        monkeypatch.setenv("SUPADATA_API_KEY", "S1")
        monkeypatch.setenv("SUPADATA_API_KEY2", "S2")
        monkeypatch.setenv("SUPADATA_API_KEY3", "S3")
        T._supadata_rotation_idx = 0

    async def test_round_robin_across_three_keys(self):
        import consensus_engine.utils.transcript_fetch as T
        used = []
        for _ in range(4):
            session = MagicMock()
            session.get.return_value = _supadata_ctx()
            with patch.object(T, "get_session", AsyncMock(return_value=session)):
                await T._fetch_via_supadata("vid")
            used.append(session.get.call_args.kwargs["headers"]["x-api-key"])
        assert used == ["S1", "S2", "S3", "S1"]

    async def test_fails_over_on_429(self):
        import consensus_engine.utils.transcript_fetch as T
        session = MagicMock()
        session.get.side_effect = [_supadata_ctx(status=429), _supadata_ctx(content="ok")]
        with patch.object(T, "get_session", AsyncMock(return_value=session)):
            result = await T._fetch_via_supadata("vid")
        assert result is not None
        assert result[0] == "ok"
        assert session.get.call_count == 2
