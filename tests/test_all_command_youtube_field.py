"""Unit tests for the !all embed's Recent YouTube Coverage field.

Step 11b populated YT clickable links in the cross_reference (TweetShift)
embed path only. This file covers the parallel addition to the !all
embed builder so users see recent YT video coverage when invoking
`!all <ticker>` even without TweetShift social activity.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from consensus_engine.alerts.all_command.embed import (
    _build_youtube_links_field,
    build_embed,
)
from consensus_engine.alerts.all_command.structured_fields import StructuredFields
from consensus_engine.models import ScoreBreakdown


# ---------------------------------------------------------------------------
# _build_youtube_links_field helper — direct contract tests
# ---------------------------------------------------------------------------


def _signal(video_id: str, title: str | None = None, channel_name: str | None = None) -> dict:
    return {"video_id": video_id, "video_title": title, "channel_name": channel_name}


def test_field_none_when_yt_signals_empty():
    assert _build_youtube_links_field([]) is None


def test_field_renders_clickable_link_with_title():
    field = _build_youtube_links_field([_signal("abc123", title="NVDA Setup Today")])
    assert field is not None
    assert field["name"] == "Recent YouTube Coverage"
    assert field["inline"] is False
    assert "[NVDA Setup Today](https://www.youtube.com/watch?v=abc123)" in field["value"]


def test_field_falls_back_to_channel_when_title_null():
    field = _build_youtube_links_field([_signal("xyz789", title=None, channel_name="Figuring Out Money")])
    assert field is not None
    assert "[Video by Figuring Out Money](https://www.youtube.com/watch?v=xyz789)" in field["value"]


def test_field_deduplicates_by_video_id():
    # Same video_id appearing twice should produce one bullet line
    sigs = [
        _signal("aaa", title="First"),
        _signal("aaa", title="First again"),  # duplicate
        _signal("bbb", title="Second"),
    ]
    field = _build_youtube_links_field(sigs)
    assert field is not None
    assert field["value"].count("https://www.youtube.com") == 2


def test_field_caps_at_max_videos(monkeypatch):
    """max_videos config caps the number of bullet lines."""
    from consensus_engine import config as cfg
    monkeypatch.setattr(cfg, "get", lambda key, default=None: (
        2 if key == "all_command.youtube_links.max_videos"
        else True if key == "all_command.youtube_links.enabled"
        else 80 if key == "all_command.youtube_links.title_max_chars"
        else default
    ))
    sigs = [_signal(f"v{i}", title=f"Video {i}") for i in range(5)]
    field = _build_youtube_links_field(sigs)
    assert field is not None
    assert field["value"].count("https://www.youtube.com") == 2


def test_field_returns_none_when_disabled(monkeypatch):
    """Kill switch — when enabled=false the helper returns None."""
    from consensus_engine import config as cfg
    monkeypatch.setattr(cfg, "get", lambda key, default=None: (
        False if key == "all_command.youtube_links.enabled" else default
    ))
    sigs = [_signal("aaa", title="should not render")]
    assert _build_youtube_links_field(sigs) is None


def test_field_truncates_long_titles():
    long_title = "A" * 200
    field = _build_youtube_links_field([_signal("ttt", title=long_title)])
    assert field is not None
    # Default title_max_chars=80 + ellipsis
    assert "…" in field["value"]


def test_field_escapes_markdown_special_chars():
    """Square brackets, parens, backslashes in titles get escaped so the link
    parser doesn't choke on user-supplied video titles."""
    field = _build_youtube_links_field([_signal("esc", title="Big [Bad] (Edge) \\ case")])
    assert field is not None
    # The escape helper inserts backslashes before special markdown chars
    assert r"\[Bad\]" in field["value"] or "\\[Bad\\]" in field["value"]


# ---------------------------------------------------------------------------
# build_embed wiring — field appears or not, depending on yt_signals
# ---------------------------------------------------------------------------


def _make_structured() -> StructuredFields:
    return StructuredFields(
        direction="BULLISH",
        confidence_label="MEDIUM",
        current_price=214.86,
    )


def test_build_embed_omits_yt_field_when_no_signals():
    embed = build_embed(
        ticker="NVDA",
        structured=_make_structured(),
        score_breakdown=ScoreBreakdown(),
        narrative="Test narrative",
        sources_used=["news"],
        cache_age_seconds=None,
    )
    field_names = [f["name"] for f in embed["fields"]]
    assert "Recent YouTube Coverage" not in field_names


def test_build_embed_includes_yt_field_when_signals_present():
    embed = build_embed(
        ticker="NVDA",
        structured=_make_structured(),
        score_breakdown=ScoreBreakdown(),
        narrative="Test narrative",
        sources_used=["news"],
        cache_age_seconds=None,
        yt_signals=[_signal("vid1", title="Today's NVDA play")],
    )
    yt_fields = [f for f in embed["fields"] if f["name"] == "Recent YouTube Coverage"]
    assert len(yt_fields) == 1
    assert "[Today's NVDA play](https://www.youtube.com/watch?v=vid1)" in yt_fields[0]["value"]
    assert yt_fields[0]["inline"] is False


def test_build_embed_yt_field_appears_after_inline_three():
    """The new field should not disrupt the existing 3 inline fields."""
    embed = build_embed(
        ticker="NVDA",
        structured=_make_structured(),
        score_breakdown=ScoreBreakdown(),
        narrative="Test narrative",
        sources_used=["news"],
        cache_age_seconds=None,
        yt_signals=[_signal("vid1", title="A")],
    )
    fields = embed["fields"]
    assert len(fields) == 4
    # First three remain inline
    assert all(f["inline"] is True for f in fields[:3])
    # The new YT field is non-inline
    assert fields[3]["inline"] is False
    assert fields[3]["name"] == "Recent YouTube Coverage"
