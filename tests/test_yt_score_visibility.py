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


# ---------------------------------------------------------------------------
# Wave 4 — YouTube score smarts (#9 direction-aware, #10 recency decay,
# #11 channel-reliability, #12 level-confluence).
#
# All four are flag-gated (features.youtube_score.*) and default OFF. They live
# on a SHARED scoring path (live alerts AND !all) and change which alerts fire,
# so flag-OFF MUST be byte-identical. The PIN tests below lock `breakdown.youtube`
# at BOTH consumption sites:
#   * score_ticker()      -> breakdown.youtube (line ~428)
#   * cross_reference()   -> result.breakdown.youtube (decorates score_ticker)
# Then per-flag ON tests prove each flag actually changes the boost.
# ---------------------------------------------------------------------------
import time
from consensus_engine.models import ParsedTweet, TweetType
from consensus_engine.cross_reference import cross_reference, _get_youtube_context


def _flag_cfg(**overrides):
    """Override ONLY the named features.youtube_score.* keys; everything else
    passes through to the real config (no consensus.yaml edit). Mirrors
    tests/test_cross_reference_skip_llm._flag_cfg."""
    import consensus_engine.cross_reference as xref
    real_get = xref.cfg.get

    def fake_get(key, default=None):
        if key in overrides:
            return overrides[key]
        return real_get(key, default)

    return patch("consensus_engine.cross_reference.cfg.get", side_effect=fake_get)


def _tweet():
    return ParsedTweet(
        tweet_url="https://x.com/a/1", analyst="TestAnalyst", raw_text="$NVDA long",
        tweet_type=TweetType.TICKER_CALLOUT, tickers=["NVDA"],
        direction=Direction("long"), options=None, conviction=Conviction("medium"),
        summary="NVDA long",
    )


async def _score_with_flags(**flag_overrides):
    """score_ticker() with _get_youtube_context mocked to a fixed +15 context,
    so breakdown.youtube reflects ONLY what score_ticker does (i.e. #12)."""
    stack = _patches() + [_flag_cfg(**flag_overrides)]
    for p in stack:
        p.start()
    try:
        return await score_ticker("NVDA")
    finally:
        for p in stack:
            p.stop()


async def _xref_with_flags(**flag_overrides):
    """cross_reference() (tweet path) with the same mocks + a no-op xref cache,
    so result.breakdown.youtube is the SECOND consumption site's value."""
    stack = _patches() + [
        _flag_cfg(**flag_overrides),
        patch("consensus_engine.cross_reference.get_cached_xref",
              new_callable=AsyncMock, return_value=None),
        patch("consensus_engine.cross_reference.cache_xref",
              new_callable=AsyncMock, return_value=None),
        patch("consensus_engine.cross_reference.db.get_signal_events_for_ticker",
              new_callable=AsyncMock, return_value=[]),
        patch("consensus_engine.cross_reference.db.record_metric",
              new_callable=AsyncMock, return_value=None),
    ]
    for p in stack:
        p.start()
    try:
        return await cross_reference("NVDA", _tweet())
    finally:
        for p in stack:
            p.stop()


# --- PIN TESTS: each flag DEFAULT-OFF -> breakdown.youtube byte-identical -----

@pytest.mark.asyncio
async def test_pin_score_ticker_youtube_unchanged_all_flags_off():
    """PIN (score_ticker path): with every Wave-4 flag explicitly OFF,
    breakdown.youtube is the unchanged positive boost (+15)."""
    result = await _score_with_flags(
        **{
            "features.youtube_score.direction_aware": False,
            "features.youtube_score.recency_decay": False,
            "features.youtube_score.channel_reliability": False,
            "features.youtube_score.level_confluence": False,
        }
    )
    assert result.breakdown.youtube == 15


@pytest.mark.asyncio
async def test_pin_cross_reference_youtube_unchanged_all_flags_off():
    """PIN (tweet cross_reference path): with every Wave-4 flag OFF,
    result.breakdown.youtube is the unchanged positive boost (+15)."""
    result = await _xref_with_flags(
        **{
            "features.youtube_score.direction_aware": False,
            "features.youtube_score.recency_decay": False,
            "features.youtube_score.channel_reliability": False,
            "features.youtube_score.level_confluence": False,
        }
    )
    assert result.breakdown.youtube == 15


@pytest.mark.asyncio
async def test_pin_default_config_matches_explicit_off_both_sites():
    """PIN: production DEFAULT config (no overrides) gives the SAME
    breakdown.youtube as explicit-all-OFF, at BOTH consumption sites."""
    # No flag overrides at all -> reads real consensus.yaml (all default OFF).
    st_default = await _score_with_flags()
    xr_default = await _xref_with_flags()
    assert st_default.breakdown.youtube == 15
    assert xr_default.breakdown.youtube == 15


# --- #9 direction-aware -------------------------------------------------------

def _signal_rows(direction, conviction="high", n=2, age_days=0.0, trust=1.0):
    """Fabricate get_youtube_signals_for_ticker rows. age_days drives
    extracted_at; trust drives the channel-reliability join column."""
    now = time.time()
    return [
        {
            "video_id": f"vid{i}", "channel_name": "TestChannel", "ticker": "NVDA",
            "direction": direction, "conviction": conviction, "mention_count": 1,
            "macro_thesis": "", "parsed_at": now, "published_at": now,
            "extracted_at": now - age_days * 86400.0, "video_title": "t",
            "trust_score": trust, "evidence_spans_for_ticker": 1,
        }
        for i in range(n)
    ]


def _yt_context_patches(rows, evidence=None):
    """Patch the two DB reads _get_youtube_context makes."""
    return [
        patch("consensus_engine.cross_reference.db.get_youtube_signals_for_ticker",
              new_callable=AsyncMock, return_value=rows),
        patch("consensus_engine.cross_reference.db.get_youtube_evidence_for_ticker",
              new_callable=AsyncMock, return_value=evidence or []),
    ]


async def _run_yt_context(rows, evidence=None, **flag_overrides):
    stack = _yt_context_patches(rows, evidence) + [_flag_cfg(**flag_overrides)]
    for p in stack:
        p.start()
    try:
        return await _get_youtube_context("NVDA")
    finally:
        for p in stack:
            p.stop()


@pytest.mark.asyncio
async def test_direction_aware_short_negative_when_on():
    """#9 ON: a short consensus signs the boost negative (injected rows — all
    live short rows are stale/out of window)."""
    rows = _signal_rows("short", conviction="high")
    ctx = await _run_yt_context(rows, **{"features.youtube_score.direction_aware": True})
    assert ctx.score_boost == -15


@pytest.mark.asyncio
async def test_direction_aware_short_positive_when_off():
    """#9 OFF: same short rows keep today's POSITIVE boost (byte-identical)."""
    rows = _signal_rows("short", conviction="high")
    ctx = await _run_yt_context(rows, **{"features.youtube_score.direction_aware": False})
    assert ctx.score_boost == 15


@pytest.mark.asyncio
async def test_direction_aware_neutral_keeps_positive_when_on():
    """#9 ON + neutral consensus -> KEEP positive (do NOT zero; per review)."""
    rows = _signal_rows("neutral", conviction="high")
    ctx = await _run_yt_context(rows, **{"features.youtube_score.direction_aware": True})
    assert ctx.score_boost == 15


@pytest.mark.asyncio
async def test_direction_aware_long_positive_when_on():
    """#9 ON + long consensus -> positive (unchanged sign)."""
    rows = _signal_rows("long", conviction="high")
    ctx = await _run_yt_context(rows, **{"features.youtube_score.direction_aware": True})
    assert ctx.score_boost == 15


# --- #10 recency decay --------------------------------------------------------

@pytest.mark.asyncio
async def test_recency_decay_shrinks_old_boost_when_on():
    """#10 ON: a stale mention (6 days, half_life 3) decays 15 -> ~4 (0.25x)."""
    rows = _signal_rows("long", conviction="high", age_days=6.0)
    ctx = await _run_yt_context(
        rows,
        **{
            "features.youtube_score.recency_decay": True,
            "features.youtube_score.recency_half_life_days": 3,
            "features.youtube_score.recency_floor": 0.3,
        },
    )
    # 15 * 0.5**(6/3) = 15 * 0.25 = 3.75 -> floor 0.3 -> 15*0.3=4.5; max(3.75,4.5)=4.5 -> round 4
    assert ctx.score_boost == 4


@pytest.mark.asyncio
async def test_recency_decay_off_keeps_full_boost():
    """#10 OFF: the same stale mention keeps the full +15 (byte-identical)."""
    rows = _signal_rows("long", conviction="high", age_days=6.0)
    ctx = await _run_yt_context(rows, **{"features.youtube_score.recency_decay": False})
    assert ctx.score_boost == 15


@pytest.mark.asyncio
async def test_recency_decay_fresh_mention_near_full_when_on():
    """#10 ON: a fresh mention (age 0) keeps ~full boost (0.5**0 == 1.0)."""
    rows = _signal_rows("long", conviction="high", age_days=0.0)
    ctx = await _run_yt_context(rows, **{"features.youtube_score.recency_decay": True})
    assert ctx.score_boost == 15


# --- #11 channel-reliability --------------------------------------------------

@pytest.mark.asyncio
async def test_channel_reliability_scales_by_trust_when_on():
    """#11 ON: trust 0.5 halves the boost (15 -> 7.5 -> round 8)."""
    rows = _signal_rows("long", conviction="high", trust=0.5)
    ctx = await _run_yt_context(rows, **{"features.youtube_score.channel_reliability": True})
    assert ctx.score_boost == 8  # round(7.5)


@pytest.mark.asyncio
async def test_channel_reliability_trust_1_is_noop_when_on():
    """#11 ON: trust=1.0 (today's prod state for all 14 channels) is a no-op."""
    rows = _signal_rows("long", conviction="high", trust=1.0)
    ctx = await _run_yt_context(rows, **{"features.youtube_score.channel_reliability": True})
    assert ctx.score_boost == 15


@pytest.mark.asyncio
async def test_channel_reliability_null_trust_bootstraps_half_when_on():
    """#11 ON: NULL trust (unregistered channel) bootstraps to 0.5 (15 -> 8)."""
    rows = _signal_rows("long", conviction="high")
    for r in rows:
        r["trust_score"] = None
    ctx = await _run_yt_context(rows, **{"features.youtube_score.channel_reliability": True})
    assert ctx.score_boost == 8  # round(15 * 0.5)


@pytest.mark.asyncio
async def test_channel_reliability_off_ignores_trust():
    """#11 OFF: low trust is ignored -> full +15 (byte-identical)."""
    rows = _signal_rows("long", conviction="high", trust=0.5)
    ctx = await _run_yt_context(rows, **{"features.youtube_score.channel_reliability": False})
    assert ctx.score_boost == 15


# --- #12 level-confluence (inside score_ticker) -------------------------------

def _yt_context_with_levels(score_boost, levels):
    return YouTubeContext(
        mention_count=2, direction=Direction("long"), top_conviction=Conviction("high"),
        channels=["TestChannel"], levels=levels, score_boost=score_boost, videos=[],
    )


def _patches_for_confluence(yt_boost, levels, tech_price, atr):
    """Like _patches but with a real TechnicalResult (price+atr) and a YouTube
    context carrying levels, so #12's proximity check can fire."""
    from consensus_engine.models import TechnicalResult, CatalystResult
    mock_catalyst = CatalystResult(
        ticker="NVDA", catalyst_summary="x", catalyst_type="Earnings Beat",
        news_sources=["reuters.com"], source_urls=["https://r/n"], confidence=0.8,
    )
    tech = TechnicalResult("NVDA")
    tech.price = tech_price
    tech.atr14 = atr
    return [
        patch("consensus_engine.cross_reference._run_news_cascade",
              new_callable=AsyncMock, return_value=mock_catalyst),
        patch("consensus_engine.cross_reference._run_sec_check",
              new_callable=AsyncMock, return_value=(False, "")),
        patch("consensus_engine.cross_reference._run_social_check",
              new_callable=AsyncMock, return_value={}),
        patch("consensus_engine.cross_reference._run_technical",
              new_callable=AsyncMock, return_value=tech),
        patch("consensus_engine.cross_reference._run_other_analysts",
              new_callable=AsyncMock, return_value=[]),
        patch("consensus_engine.cross_reference._run_llm_score",
              new_callable=AsyncMock, return_value=(0.0, "")),
        patch("consensus_engine.cross_reference._run_options_check",
              new_callable=AsyncMock, return_value=None),
        patch("consensus_engine.cross_reference._get_youtube_context",
              new_callable=AsyncMock,
              return_value=_yt_context_with_levels(yt_boost, levels)),
    ]


async def _score_confluence(yt_boost, levels, tech_price, atr, **flag_overrides):
    stack = _patches_for_confluence(yt_boost, levels, tech_price, atr) + [_flag_cfg(**flag_overrides)]
    for p in stack:
        p.start()
    try:
        return await score_ticker("NVDA")
    finally:
        for p in stack:
            p.stop()


@pytest.mark.asyncio
async def test_level_confluence_adds_bonus_when_on():
    """#12 ON: a YouTube level inside the ATR band of technical.price adds the
    capped bonus (+3) on top of the +15 boost."""
    result = await _score_confluence(
        yt_boost=15, levels=[{"type": "support", "price": 100.0, "confidence": 0.9}],
        tech_price=100.0, atr=2.0,
        **{"features.youtube_score.level_confluence": True},
    )
    assert result.breakdown.youtube == 18  # 15 + 3


@pytest.mark.asyncio
async def test_level_confluence_capped_when_on():
    """#12 ON: many confluent levels cap the bonus at confluence_cap (6)."""
    levels = [{"type": "support", "price": 100.0, "confidence": 0.9} for _ in range(10)]
    result = await _score_confluence(
        yt_boost=15, levels=levels, tech_price=100.0, atr=2.0,
        **{"features.youtube_score.level_confluence": True},
    )
    assert result.breakdown.youtube == 21  # 15 + min(10*3, 6) = 15 + 6


@pytest.mark.asyncio
async def test_level_confluence_far_level_no_bonus_when_on():
    """#12 ON: a level FAR outside the band adds nothing."""
    result = await _score_confluence(
        yt_boost=15, levels=[{"type": "support", "price": 50.0, "confidence": 0.9}],
        tech_price=100.0, atr=2.0,
        **{"features.youtube_score.level_confluence": True},
    )
    assert result.breakdown.youtube == 15


@pytest.mark.asyncio
async def test_level_confluence_signed_to_match_negative_boost_when_on():
    """#12 ON: when the boost is already negative (bearish), the bonus is
    subtracted (signed to match) so confluence never flips the direction."""
    result = await _score_confluence(
        yt_boost=-15, levels=[{"type": "support", "price": 100.0, "confidence": 0.9}],
        tech_price=100.0, atr=2.0,
        **{"features.youtube_score.level_confluence": True},
    )
    assert result.breakdown.youtube == -18  # -15 - 3


@pytest.mark.asyncio
async def test_level_confluence_off_no_bonus():
    """#12 OFF: a confluent level adds nothing (byte-identical)."""
    result = await _score_confluence(
        yt_boost=15, levels=[{"type": "support", "price": 100.0, "confidence": 0.9}],
        tech_price=100.0, atr=2.0,
        **{"features.youtube_score.level_confluence": False},
    )
    assert result.breakdown.youtube == 15
