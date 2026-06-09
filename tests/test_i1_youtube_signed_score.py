"""I1 (signal-features-2026-06-09) — sign the YouTube boost.

VERIFIED wrong-sign bug: a bearish (short) YouTube consensus currently RAISES a
long score via the unsigned `youtube.score_boost`. The signed path already
exists in `_get_youtube_context` (flag-gated, byte-identical when off). This
suite asserts the NEW Pass-3 safeguards that fire when the flags are ON:

  (1) min-2-trusted-channel FLOOR before any bearish subtraction — below the
      floor a bearish consensus contributes 0, NEVER a positive add (the bug).
  (2) a channel's trust counts toward the floor only if it has channel-age
      (`channel_age_days`) AND >= min_channel_graded_n graded outcomes
      (`graded_n`).
  (3) the bearish (negative) magnitude is capped at bearish_cap (-8) while the
      bullish boost stays up to +15.
  (4) a null/missing `extracted_at` is treated as STALE (down-weighted to the
      recency floor), never fresh; the divide is guarded.

Per the I1 plan the dedicated test forces direction_aware + recency_decay +
channel_reliability ON together (channel_reliability is NOT deferred).

Flag-OFF byte-identical legacy behavior (the same bearish rows keep the unsigned
POSITIVE boost) is locked here and in tests/test_yt_score_visibility.py.
"""
import time
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine.cross_reference import _get_youtube_context, _count_trusted_channels


# --- helpers ---------------------------------------------------------------

def _flag_cfg(**overrides):
    """Override only the named features.youtube_score.* keys; everything else
    passes through to the real config (mirrors test_yt_score_visibility)."""
    import consensus_engine.cross_reference as xref
    real_get = xref.cfg.get

    def fake_get(key, default=None):
        if key in overrides:
            return overrides[key]
        return real_get(key, default)

    return patch("consensus_engine.cross_reference.cfg.get", side_effect=fake_get)


def _rows(direction, *, channels, conviction="high", age_days=0.0,
          trust=1.0, graded_n=20, channel_age_days=400.0, has_timestamp=True):
    """Fabricate get_youtube_signals_for_ticker rows, one per channel name.

    `channels` is a list of channel_name strings (distinct names => distinct
    channels for the trusted-floor count). `graded_n` / `channel_age_days` drive
    the I1 trusted-channel eligibility; set either to None to make a channel NOT
    count toward the floor. `has_timestamp=False` drops extracted_at (-> stale).
    """
    now = time.time()
    rows = []
    for i, ch in enumerate(channels):
        rows.append({
            "video_id": f"vid{i}", "channel_name": ch, "ticker": "NVDA",
            "direction": direction, "conviction": conviction, "mention_count": 1,
            "macro_thesis": "", "parsed_at": now, "published_at": now,
            "extracted_at": (now - age_days * 86400.0) if has_timestamp else None,
            "video_title": "t", "trust_score": trust,
            "evidence_spans_for_ticker": 1,
            "graded_n": graded_n, "channel_age_days": channel_age_days,
        })
    return rows


def _yt_patches(rows, evidence=None):
    return [
        patch("consensus_engine.cross_reference.db.get_youtube_signals_for_ticker",
              new_callable=AsyncMock, return_value=rows),
        patch("consensus_engine.cross_reference.db.get_youtube_evidence_for_ticker",
              new_callable=AsyncMock, return_value=evidence or []),
    ]


async def _run(rows, **flag_overrides):
    stack = _yt_patches(rows) + [_flag_cfg(**flag_overrides)]
    for p in stack:
        p.start()
    try:
        return await _get_youtube_context("NVDA")
    finally:
        for p in stack:
            p.stop()


# Force all three I1 flags ON together (channel_reliability NOT deferred). Use
# a fresh recency (age_days=0) and trust=1.0 so the decay/trust multipliers are
# no-ops and the assertion isolates the sign/floor/cap behavior.
_ALL_ON = {
    "features.youtube_score.direction_aware": True,
    "features.youtube_score.recency_decay": True,
    "features.youtube_score.channel_reliability": True,
    "features.youtube_score.min_trusted_channels": 2,
    "features.youtube_score.min_channel_graded_n": 10,
    "features.youtube_score.bearish_cap": 8,
}


# --- (1)+(3) bearish multi-trusted-channel -> NEGATIVE, capped at -8 ---------

@pytest.mark.asyncio
async def test_bearish_multi_trusted_channel_is_negative_capped():
    """A bearish consensus across 2 trusted channels (each graded_n>=10, aged)
    -> NEGATIVE youtube_pts, magnitude capped at bearish_cap (-8) even though the
    raw high-conviction boost is 15."""
    rows = _rows("short", channels=["AlphaTrader", "BetaDesk"])
    ctx = await _run(rows, **_ALL_ON)
    assert ctx.score_boost == -8  # -min(15, 8)


# --- (1) single-channel bearish -> 0 (floor), NEVER positive -----------------

@pytest.mark.asyncio
async def test_single_trusted_channel_bearish_is_zero_not_positive():
    """A bearish consensus from ONE trusted channel is below the min-2 floor ->
    0 contribution. NOT negative (unsafe) and NOT the legacy +15 (the bug)."""
    rows = _rows("short", channels=["AlphaTrader"])
    ctx = await _run(rows, **_ALL_ON)
    assert ctx.score_boost == 0


# --- (2) untracked channels do NOT count toward the floor --------------------

@pytest.mark.asyncio
async def test_two_channels_without_track_record_below_floor_is_zero():
    """Two distinct channels but NEITHER has the graded-outcome track record
    (graded_n=None) -> 0 trusted channels -> below floor -> 0, never positive."""
    rows = _rows("short", channels=["NewChan1", "NewChan2"], graded_n=None)
    ctx = await _run(rows, **_ALL_ON)
    assert ctx.score_boost == 0


@pytest.mark.asyncio
async def test_thin_graded_n_below_floor_is_zero():
    """Two channels but each has only graded_n=5 (< min 10) -> not trusted ->
    below floor -> 0."""
    rows = _rows("short", channels=["AlphaTrader", "BetaDesk"], graded_n=5)
    ctx = await _run(rows, **_ALL_ON)
    assert ctx.score_boost == 0


@pytest.mark.asyncio
async def test_count_trusted_channels_helper():
    """_count_trusted_channels: requires channel-age AND graded_n>=min, counts
    DISTINCT names, ignores missing fields (the production case -> 0)."""
    rows = _rows("short", channels=["A", "B"])
    assert _count_trusted_channels(rows, 10) == 2
    # Missing both fields (production rows today) -> 0 trusted.
    rows_prod = _rows("short", channels=["A", "B"], graded_n=None, channel_age_days=None)
    assert _count_trusted_channels(rows_prod, 10) == 0
    # Same channel name twice -> 1 distinct channel.
    rows_dup = _rows("short", channels=["A", "A"])
    assert _count_trusted_channels(rows_dup, 10) == 1


# --- (3) bullish stays uncapped at +15 ---------------------------------------

@pytest.mark.asyncio
async def test_bullish_stays_positive_uncapped():
    """A bullish (long) high-conviction consensus keeps the full +15 — the cap
    is bearish-only; the floor does not gate the positive add."""
    rows = _rows("long", channels=["AlphaTrader"])
    ctx = await _run(rows, **_ALL_ON)
    assert ctx.score_boost == 15


# --- (4) null timestamp -> STALE, down-weighted, never fresh -----------------

@pytest.mark.asyncio
async def test_null_timestamp_treated_as_stale_bullish():
    """A bullish consensus whose only mention has NO extracted_at is treated as
    STALE: down-weighted to the recency floor (0.3), not left fresh. 15*0.3=4.5
    -> round 4. (Bullish so the floor/cap don't apply.)"""
    rows = _rows("long", channels=["AlphaTrader"], has_timestamp=False)
    ctx = await _run(
        rows,
        **{
            "features.youtube_score.direction_aware": True,
            "features.youtube_score.recency_decay": True,
            "features.youtube_score.channel_reliability": True,
            "features.youtube_score.recency_half_life_days": 3,
            "features.youtube_score.recency_floor": 0.3,
            "features.youtube_score.min_trusted_channels": 2,
            "features.youtube_score.min_channel_graded_n": 10,
            "features.youtube_score.bearish_cap": 8,
        },
    )
    assert ctx.score_boost == 4  # round(15 * 0.3)


@pytest.mark.asyncio
async def test_one_missing_timestamp_caps_decay_at_floor():
    """If ONE leg is fresh but ANOTHER has a null timestamp, the consensus
    cannot be treated as fresh: decay is capped at the stale floor (0.3)."""
    rows = _rows("long", channels=["AlphaTrader", "BetaDesk"])
    rows[1]["extracted_at"] = None  # one stale leg
    ctx = await _run(
        rows,
        **{
            "features.youtube_score.direction_aware": True,
            "features.youtube_score.recency_decay": True,
            "features.youtube_score.channel_reliability": True,
            "features.youtube_score.recency_half_life_days": 3,
            "features.youtube_score.recency_floor": 0.3,
            "features.youtube_score.min_trusted_channels": 2,
            "features.youtube_score.min_channel_graded_n": 10,
            "features.youtube_score.bearish_cap": 8,
        },
    )
    assert ctx.score_boost == 4  # round(15 * 0.3) — fresh leg can't lift it


# --- flag-OFF: original unsigned POSITIVE boost (byte-identical) -------------

@pytest.mark.asyncio
async def test_flag_off_bearish_keeps_unsigned_positive():
    """Flags OFF: the SAME bearish multi-channel rows keep the legacy unsigned
    POSITIVE +15 (the pre-I1 behavior). This is the byte-identical proof."""
    rows = _rows("short", channels=["AlphaTrader", "BetaDesk"])
    ctx = await _run(
        rows,
        **{
            "features.youtube_score.direction_aware": False,
            "features.youtube_score.recency_decay": False,
            "features.youtube_score.channel_reliability": False,
        },
    )
    assert ctx.score_boost == 15
