"""Unit tests for the !all embed's Recent YouTube Coverage field.

Step 11b populated YT clickable links in the cross_reference (TweetShift)
embed path only. This file covers the parallel addition to the !all
embed builder so users see recent YT video coverage when invoking
`!all <ticker>` even without TweetShift social activity.

Filter contract (2026-05-26, after user feedback on !all MSFT):
A signal surfaces for `ticker` only if the parser captured at least
`all_command.youtube_links.min_evidence_spans` (default 1) row in
youtube_evidence_spans whose tickers_json explicitly tags the ticker.
That moves the bar from "the row exists" to "the parser has at least
one substantive quote tied to this ticker", eliminating incidental
over-tags from coarse-grained mention counting.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from consensus_engine.alerts.all_command.embed import (
    _build_youtube_links_field,
    _signal_is_primary_coverage,
    build_embed,
)
from consensus_engine.alerts.all_command.structured_fields import StructuredFields
from consensus_engine.models import ScoreBreakdown


# ---------------------------------------------------------------------------
# _build_youtube_links_field helper — direct contract tests
#
# When `ticker` is not passed (or is empty), the helper renders the rows it
# was given without filtering. The filter only engages when a ticker is
# provided. The handful of tests below exercise the rendering contract;
# the filter contract is exercised separately further down.
# ---------------------------------------------------------------------------


def _signal(video_id: str, title: str | None = None, channel_name: str | None = None,
            evidence_spans_for_ticker: int = 0) -> dict:
    return {
        "video_id": video_id,
        "video_title": title,
        "channel_name": channel_name,
        "evidence_spans_for_ticker": evidence_spans_for_ticker,
    }


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
    sigs = [
        _signal("aaa", title="First"),
        _signal("aaa", title="First again"),  # duplicate
        _signal("bbb", title="Second"),
    ]
    field = _build_youtube_links_field(sigs)
    assert field is not None
    assert field["value"].count("https://www.youtube.com") == 2


def test_field_caps_at_max_videos(monkeypatch):
    from consensus_engine import config as cfg
    monkeypatch.setattr(cfg, "get", lambda key, default=None: (
        2 if key == "all_command.youtube_links.max_videos"
        else True if key == "all_command.youtube_links.enabled"
        else 80 if key == "all_command.youtube_links.title_max_chars"
        else 1 if key == "all_command.youtube_links.min_evidence_spans"
        else default
    ))
    sigs = [_signal(f"v{i}", title=f"Video {i}") for i in range(5)]
    field = _build_youtube_links_field(sigs)
    assert field is not None
    assert field["value"].count("https://www.youtube.com") == 2


def test_field_returns_none_when_disabled(monkeypatch):
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
    assert "…" in field["value"]


def test_field_escapes_markdown_special_chars():
    field = _build_youtube_links_field([_signal("esc", title="Big [Bad] (Edge) \\ case")])
    assert field is not None
    assert r"\[Bad\]" in field["value"] or "\\[Bad\\]" in field["value"]


# ---------------------------------------------------------------------------
# _signal_is_primary_coverage — pure evidence-spans filter
# ---------------------------------------------------------------------------


def _sig(evidence_spans_for_ticker=0, video_id="v", title=None):
    return {
        "video_id": video_id,
        "video_title": title,
        "evidence_spans_for_ticker": evidence_spans_for_ticker,
    }


def test_primary_coverage_rejects_zero_evidence_spans():
    """A signal with no evidence spans tagging the ticker is rejected —
    the parser didn't capture any quote where this ticker is named, so
    treating it as primary coverage would be misleading."""
    assert _signal_is_primary_coverage(_sig(evidence_spans_for_ticker=0), "MSFT") is False


def test_primary_coverage_accepts_one_evidence_span():
    """Default threshold is 1 — a single evidence span tagging the ticker
    is enough."""
    assert _signal_is_primary_coverage(_sig(evidence_spans_for_ticker=1), "MSFT") is True


def test_primary_coverage_accepts_many_evidence_spans():
    """High evidence-span counts pass — the parser captured many quotes
    tagging the ticker."""
    assert _signal_is_primary_coverage(_sig(evidence_spans_for_ticker=16), "MSFT") is True


def test_primary_coverage_rejects_even_when_title_contains_ticker():
    """Title-match no longer rescues a signal. If the parser couldn't pin
    a single quote to the ticker, we don't surface it — even if the title
    suggests the video is about the ticker. The user picked evidence-only
    filtering knowing that some older signals would be dropped."""
    s = _sig(evidence_spans_for_ticker=0, title="NVDA Earnings Recap")
    assert _signal_is_primary_coverage(s, "NVDA") is False


def test_primary_coverage_respects_configured_threshold(monkeypatch):
    """`all_command.youtube_links.min_evidence_spans` raises the bar."""
    from consensus_engine import config as cfg
    monkeypatch.setattr(cfg, "get", lambda key, default=None: (
        3 if key == "all_command.youtube_links.min_evidence_spans" else default
    ))
    assert _signal_is_primary_coverage(_sig(evidence_spans_for_ticker=2), "MSFT") is False
    assert _signal_is_primary_coverage(_sig(evidence_spans_for_ticker=3), "MSFT") is True


# ---------------------------------------------------------------------------
# build_embed wiring — field appears or not based on signals + evidence
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


def test_build_embed_includes_yt_field_when_signals_have_evidence():
    embed = build_embed(
        ticker="NVDA",
        structured=_make_structured(),
        score_breakdown=ScoreBreakdown(),
        narrative="Test narrative",
        sources_used=["news"],
        cache_age_seconds=None,
        yt_signals=[_signal("vid1", title="Today's NVDA play",
                            evidence_spans_for_ticker=5)],
    )
    yt_fields = [f for f in embed["fields"] if f["name"] == "Recent YouTube Coverage"]
    assert len(yt_fields) == 1
    assert "[Today's NVDA play](https://www.youtube.com/watch?v=vid1)" in yt_fields[0]["value"]
    assert yt_fields[0]["inline"] is False


def test_build_embed_filters_zero_evidence_rows_even_with_great_titles():
    """Reproduces the scenario from production: the parser created
    signal rows for NVDA from videos whose titles look NVDA-relevant
    (Mag 7 + PLTR; This is BIG) but generated zero NVDA-tagged
    evidence spans. Pure evidence filtering correctly drops them."""
    yt_signals = [
        _signal("vid_real", title="$NVDA Levels Today",
                evidence_spans_for_ticker=4),
        _signal("vid_no_evidence", title="Mag 7 + PLTR",
                evidence_spans_for_ticker=0),
        _signal("vid_macro", title="This is BIG",
                evidence_spans_for_ticker=0),
    ]
    embed = build_embed(
        ticker="NVDA",
        structured=_make_structured(),
        score_breakdown=ScoreBreakdown(),
        narrative="Test narrative",
        sources_used=["news"],
        cache_age_seconds=None,
        yt_signals=yt_signals,
    )
    yt_field = next(f for f in embed["fields"] if f["name"] == "Recent YouTube Coverage")
    assert "vid_real" in yt_field["value"]
    assert "vid_no_evidence" not in yt_field["value"]
    assert "vid_macro" not in yt_field["value"]


def test_build_embed_omits_yt_field_when_no_signal_has_evidence():
    """Every signal has 0 evidence spans for the ticker — render nothing.
    Better to omit the field than show videos that don't genuinely cover
    the ticker."""
    yt_signals = [
        _signal("v1", title="Mag 7 + PLTR", evidence_spans_for_ticker=0),
        _signal("v2", title="Tesla Stock Analysis", evidence_spans_for_ticker=0),
    ]
    embed = build_embed(
        ticker="NVDA",
        structured=_make_structured(),
        score_breakdown=ScoreBreakdown(),
        narrative="Test narrative",
        sources_used=["news"],
        cache_age_seconds=None,
        yt_signals=yt_signals,
    )
    field_names = [f["name"] for f in embed["fields"]]
    assert "Recent YouTube Coverage" not in field_names


def test_build_embed_yt_field_after_inline_three():
    """When the YT field appears, the existing 3 inline fields stay first."""
    embed = build_embed(
        ticker="MSFT",
        structured=_make_structured(),
        score_breakdown=ScoreBreakdown(),
        narrative="Test narrative",
        sources_used=["news"],
        cache_age_seconds=None,
        yt_signals=[_signal("vid1", title="$SPY Pivot",
                            evidence_spans_for_ticker=16)],
    )
    fields = embed["fields"]
    assert len(fields) == 4
    assert all(f["inline"] is True for f in fields[:3])
    assert fields[3]["inline"] is False
    assert fields[3]["name"] == "Recent YouTube Coverage"
