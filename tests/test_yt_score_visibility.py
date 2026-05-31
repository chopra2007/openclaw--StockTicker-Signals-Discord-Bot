"""Regression tests for #19 — YouTube score visibility (`yt=N` footer term).

The change splits the YouTube conviction boost out of `llm_boost` into its own
`ScoreBreakdown.youtube` field. It MUST be display-only:
  * `total` identical to the old `llm_boost += youtube_pts` merge,
  * `compute_direction` identical (youtube added to _BULLISH_BIASED_FIELDS),
  * the split actually happened (llm_boost no longer includes the YT points),
  * the footer shows `yt=N` only when youtube > 0.
"""
import pytest
from unittest.mock import patch, AsyncMock

from consensus_engine.models import (
    ScoreBreakdown, YouTubeContext, Direction, Conviction, CatalystResult,
)
from consensus_engine.cross_reference import score_ticker, ScoreTickerResult
from consensus_engine.alerts.all_command.structured_fields import compute_direction
from consensus_engine.alerts.all_command.embed import _build_breakdown_inline


def _yt_context(score_boost=15):
    return YouTubeContext(
        mention_count=2,
        direction=Direction("long"),
        top_conviction=Conviction("high"),
        channels=["TestChannel"],
        levels=[],
        score_boost=score_boost,
        videos=[],
    )


def _patches(yt_boost=15):
    """Mirror tests/test_pr2_score_ticker._patches; YouTube returns a real
    high-conviction context instead of None so youtube_pts > 0."""
    mock_catalyst = CatalystResult(
        ticker="NVDA", catalyst_summary="NVDA earnings beat",
        catalyst_type="Earnings Beat", news_sources=["reuters.com"],
        source_urls=["https://reuters.com/nvda"], confidence=0.8,
    )
    return [
        patch("consensus_engine.cross_reference._run_news_cascade",
              new_callable=AsyncMock, return_value=mock_catalyst),
        patch("consensus_engine.cross_reference._run_sec_check",
              new_callable=AsyncMock, return_value=(False, "")),
        patch("consensus_engine.cross_reference._run_social_check",
              new_callable=AsyncMock, return_value={"apewisdom": 3}),
        patch("consensus_engine.cross_reference._run_technical",
              new_callable=AsyncMock, return_value=None),
        patch("consensus_engine.cross_reference._run_other_analysts",
              new_callable=AsyncMock, return_value=["CheddarFlow"]),
        patch("consensus_engine.cross_reference._run_llm_score",
              new_callable=AsyncMock, return_value=(75.0, "Strong setup")),
        patch("consensus_engine.cross_reference._run_options_check",
              new_callable=AsyncMock, return_value=None),
        patch("consensus_engine.cross_reference._get_youtube_context",
              new_callable=AsyncMock, return_value=_yt_context(yt_boost)),
    ]


async def _score():
    stack = _patches()
    for p in stack:
        p.start()
    try:
        return await score_ticker("NVDA")
    finally:
        for p in stack:
            p.stop()


@pytest.mark.asyncio
async def test_youtube_points_split_into_own_field():
    """YT boost lands in `youtube`, NOT inside `llm_boost`."""
    result = await _score()
    assert isinstance(result, ScoreTickerResult)
    # llm_score 75 * llm_max 15 / 100 = 11 — this is the LLM-only contribution.
    assert result.breakdown.llm_boost == 11, "llm_boost must NOT include the YT boost"
    assert result.breakdown.youtube == 15, "YT conviction boost (high=15) lives in its own field"


@pytest.mark.asyncio
async def test_total_unchanged_vs_old_merge():
    """`total` must equal the old `llm_boost += youtube_pts` behavior."""
    result = await _score()
    bd = result.breakdown
    # Reconstruct the OLD-style breakdown: YT folded into llm_boost, youtube=0.
    old_style = ScoreBreakdown(
        base=bd.base, additional_analysts=bd.additional_analysts,
        news_catalyst=bd.news_catalyst, sec_filing=bd.sec_filing,
        social_apewisdom=bd.social_apewisdom, social_stocktwits=bd.social_stocktwits,
        social_reddit=bd.social_reddit, google_trends=bd.google_trends,
        technical=bd.technical,
        llm_boost=bd.llm_boost + bd.youtube, youtube=0,
        options_flow=bd.options_flow, consensus_boost=bd.consensus_boost,
    )
    assert bd.total == old_style.total


@pytest.mark.asyncio
async def test_direction_unchanged_vs_old_merge():
    """compute_direction must be identical whether YT is its own field or in llm."""
    result = await _score()
    bd = result.breakdown
    old_style = ScoreBreakdown(
        base=bd.base, additional_analysts=bd.additional_analysts,
        news_catalyst=bd.news_catalyst, sec_filing=bd.sec_filing,
        social_apewisdom=bd.social_apewisdom, social_stocktwits=bd.social_stocktwits,
        social_reddit=bd.social_reddit, google_trends=bd.google_trends,
        technical=bd.technical,
        llm_boost=bd.llm_boost + bd.youtube, youtube=0,
        options_flow=bd.options_flow, consensus_boost=bd.consensus_boost,
    )
    assert compute_direction(bd) == compute_direction(old_style)


def test_footer_shows_yt_term_only_when_positive():
    with_yt = ScoreBreakdown(base=20, news_catalyst=15, llm_boost=4, youtube=10)
    line = _build_breakdown_inline(with_yt)
    assert "yt=10" in line
    assert "llm=4" in line

    no_yt = ScoreBreakdown(base=20, news_catalyst=15, llm_boost=4, youtube=0)
    assert "yt=" not in _build_breakdown_inline(no_yt)
