"""Tests for Section 2P: YouTube clickable video links in Social field.

Covers:
- _escape_md_link_text unit tests
- _build_social_summary link rendering (title present, title NULL, escape, cap, truncation, kill-switch)
- _get_youtube_context video deduplication
"""
import pytest
from unittest.mock import AsyncMock, patch

from consensus_engine.alerts._markdown import _escape_md_link_text


# ---------------------------------------------------------------------------
# _escape_md_link_text unit tests
# ---------------------------------------------------------------------------

def test_escape_plain_title():
    assert _escape_md_link_text("NVDA Breakout Setup") == "NVDA Breakout Setup"


def test_escape_closing_bracket():
    result = _escape_md_link_text("Title with ] bracket")
    assert "\\]" in result
    assert "]" not in result.replace("\\]", "")


def test_escape_backslash():
    result = _escape_md_link_text("C:\\path\\to\\video")
    assert "\\\\" in result


def test_escape_empty_string():
    assert _escape_md_link_text("") == ""


def test_escape_newlines_collapsed():
    result = _escape_md_link_text("Line one\nLine two\r\nLine three")
    assert "\n" not in result
    assert "\r" not in result
    assert "Line one Line two Line three" == result


def test_escape_complex_title():
    """Title containing ] [ \\ ( ) and backtick all escaped."""
    raw = "]B(C)\\`backtick"
    result = _escape_md_link_text(raw)
    # Must not break Discord markdown link parsing — none of the raw specials remain unescaped
    for ch in ("]", "[", "(", ")", "`"):
        # Every occurrence should be preceded by a backslash
        idx = 0
        while True:
            pos = result.find(ch, idx)
            if pos == -1:
                break
            assert pos > 0 and result[pos - 1] == "\\", f"Unescaped {ch!r} at pos {pos} in {result!r}"
            idx = pos + 1


# ---------------------------------------------------------------------------
# _build_social_summary rendering tests
# ---------------------------------------------------------------------------

def _make_yt_context(videos):
    """Build a minimal YouTubeContext for rendering tests."""
    from consensus_engine.models import YouTubeContext, Direction, Conviction
    return YouTubeContext(
        mention_count=len(videos),
        direction=Direction("long"),
        top_conviction=Conviction("high"),
        channels=["TestChannel"],
        levels=[],
        score_boost=15,
        videos=videos,
    )


def _build(youtube_ctx, extra_cfg=None):
    """Call _build_social_summary with optional config overrides."""
    from consensus_engine.cross_reference import _build_social_summary
    cfg_overrides = {"all_command.youtube_links.enabled": True,
                     "all_command.youtube_links.max_videos": 3,
                     "all_command.youtube_links.title_max_chars": 80,
                     **(extra_cfg or {})}

    def fake_get(key, default=None):
        return cfg_overrides.get(key, default)

    with patch("consensus_engine.cross_reference.cfg.get", side_effect=fake_get):
        return _build_social_summary({}, youtube_ctx)


def test_link_rendered_with_title():
    ctx = _make_yt_context([{"video_id": "abc123", "title": "Bull Run Setup", "channel_name": "Chan"}])
    result = _build(ctx)
    assert "[Bull Run Setup](https://www.youtube.com/watch?v=abc123)" in result
    assert result.startswith("YouTube")


def test_link_rendered_without_title_uses_channel():
    ctx = _make_yt_context([{"video_id": "abc123", "title": None, "channel_name": "MyChan"}])
    result = _build(ctx)
    assert "[Video by MyChan](https://www.youtube.com/watch?v=abc123)" in result


def test_title_escaped_in_link():
    ctx = _make_yt_context([{"video_id": "vid1", "title": "Title ]B(C)\\`weird", "channel_name": "C"}])
    result = _build(ctx)
    # The rendered link line must contain \\] and \\( etc — raw ] would break Discord markdown
    assert "\\]" in result


def test_title_truncated_with_ellipsis():
    long_title = "A" * 90
    ctx = _make_yt_context([{"video_id": "v1", "title": long_title, "channel_name": "C"}])
    result = _build(ctx, {"all_command.youtube_links.title_max_chars": 80})
    assert "…" in result
    # The link text portion should not exceed 80+1 (ellipsis) chars
    import re
    m = re.search(r"\[([^\]]+)\]", result.split("\n", 1)[1])
    assert m and len(m.group(1)) <= 81


def test_cap_at_max_videos():
    videos = [{"video_id": f"v{i}", "title": f"Title {i}", "channel_name": "C"} for i in range(10)]
    ctx = _make_yt_context(videos)
    result = _build(ctx, {"all_command.youtube_links.max_videos": 3})
    # Count bullet lines
    link_lines = [l for l in result.split("\n") if l.startswith("•")]
    assert len(link_lines) == 3


def test_kill_switch_disabled():
    ctx = _make_yt_context([{"video_id": "v1", "title": "Some video", "channel_name": "C"}])
    result = _build(ctx, {"all_command.youtube_links.enabled": False})
    assert "•" not in result
    assert "youtube.com" not in result


# ---------------------------------------------------------------------------
# _get_youtube_context deduplication test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_youtube_context_deduplicates_video_ids():
    """3 signal rows across 2 unique video_ids → videos list has 2 entries."""
    from consensus_engine.cross_reference import _get_youtube_context

    fake_mentions = [
        {"video_id": "vid1", "channel_name": "Chan", "direction": "long",
         "conviction": "high", "video_title": "Title 1", "evidence_spans_for_ticker": 1},
        {"video_id": "vid2", "channel_name": "Chan", "direction": "long",
         "conviction": "medium", "video_title": "Title 2", "evidence_spans_for_ticker": 1},
        {"video_id": "vid1", "channel_name": "Chan", "direction": "long",
         "conviction": "low", "video_title": "Title 1", "evidence_spans_for_ticker": 1},  # duplicate
    ]
    fake_evidence = []

    def fake_cfg_get(key, default=None):
        if key == "all_command.youtube_links.max_videos":
            return 10
        return default

    with patch("consensus_engine.cross_reference.db.get_youtube_signals_for_ticker",
               new=AsyncMock(return_value=fake_mentions)), \
         patch("consensus_engine.cross_reference.db.get_youtube_evidence_for_ticker",
               new=AsyncMock(return_value=fake_evidence)), \
         patch("consensus_engine.cross_reference.cfg.get", side_effect=fake_cfg_get):
        ctx = await _get_youtube_context("NVDA")

    assert ctx is not None
    assert len(ctx.videos) == 2
    video_ids = [v["video_id"] for v in ctx.videos]
    assert "vid1" in video_ids
    assert "vid2" in video_ids
