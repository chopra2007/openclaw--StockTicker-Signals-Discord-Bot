"""Tests for PR4a !all command data layer modules.

Covers levels, gap_fill, structured_fields, output_filter, embed, narrator
(sanitize functions only). Synthesis is OUT OF SCOPE for PR4a — ships in PR4b.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine.alerts.all_command import (
    embed as embed_mod,
    gap_fill,
    levels,
    narrator,
    output_filter,
    structured_fields,
)
from consensus_engine.alerts.all_command.structured_fields import StructuredFields
from consensus_engine.models import OptionsResult, ScoreBreakdown


# ---------------------------------------------------------------------------
# levels.py
# ---------------------------------------------------------------------------

def test_levels_extract_from_youtube_rows():
    rows = [
        {"price": 100.0, "channel_name": "LunaTrades", "level_type": "support"},
        {"price": 0, "channel_name": "X"},          # rejected (price <= 0.01)
        {"price": "bad", "channel_name": "Y"},      # rejected (non-numeric)
    ]
    anchors = levels.extract_anchors_from_youtube_levels(rows)
    assert len(anchors) == 1
    assert anchors[0].price == 100.0
    assert anchors[0].source == "youtube:LunaTrades"
    assert anchors[0].source_type == "yt"


def test_levels_extract_swing_levels_finds_local_extrema():
    candles = [
        {"high": 100, "low": 95},
        {"high": 110, "low": 105},  # local max high
        {"high": 105, "low": 90},   # local min low (i=2 → next is i=3)
        {"high": 108, "low": 99},
    ]
    anchors = levels.extract_swing_levels(candles)
    prices = sorted(a.price for a in anchors)
    assert 110.0 in prices  # swing high at i=1
    assert 90.0 in prices   # swing low at i=2


def test_levels_extract_from_search_snippets_requires_trigger():
    # Has trigger word → kept
    s_good = "Analyst sees price target of $150 for Q3."
    # No trigger word → rejected
    s_no_trigger = "Company has $42 cash on the books."
    # Negative context (billion) → rejected
    s_neg = "Revenue of $5 billion was reported."
    out = levels.extract_anchors_from_search_snippets(
        [s_good, s_no_trigger, s_neg], current_price=100.0,
    )
    assert len(out) == 1
    assert out[0].price == 150.0


def test_levels_cluster_merges_within_threshold():
    a1 = levels.Anchor(price=100.0, source="A", source_type="yt", touches=2)
    a2 = levels.Anchor(price=100.3, source="B", source_type="web", touches=1)  # 0.3% away
    a3 = levels.Anchor(price=120.0, source="C", source_type="swing", touches=1)
    merged = levels.cluster_anchors([a1, a2, a3], threshold_pct=0.005)
    assert len(merged) == 2
    # the cluster of A+B picks max touches
    cluster_anchor = next(a for a in merged if abs(a.price - 100.15) < 0.5)
    assert cluster_anchor.source_count == 2
    assert cluster_anchor.touches == 2


def test_levels_rank_splits_supports_and_resistances():
    current = 100.0
    anchors = [
        levels.Anchor(price=95.0, source="s1", source_type="swing", touches=3),
        levels.Anchor(price=92.0, source="s2", source_type="yt", touches=1),
        levels.Anchor(price=105.0, source="r1", source_type="web", touches=2),
        levels.Anchor(price=108.0, source="r2", source_type="yt", touches=1),
    ]
    supports, resistances = levels.rank_anchors(anchors, current)
    assert all(a.price < current for a in supports)
    assert all(a.price > current for a in resistances)
    # Higher touches → higher score; supports[0] should be the touches=3 one
    assert supports[0].price == 95.0


def test_levels_select_trade_plan_suppresses_under_4():
    supports = [levels.Anchor(price=95.0, source="s", source_type="swing")]
    resistances = [levels.Anchor(price=105.0, source="r", source_type="web")]
    # Total = 2 → suppressed (PR3: returns dict-with-None + reason)
    plan = levels.select_trade_plan(supports, resistances)
    assert plan["sl"] is None
    assert plan["tp1"] is None
    assert plan["tp2"] is None
    assert plan["tp3"] is None
    assert "2 anchors" in plan["suppression_reason"]


def test_levels_select_trade_plan_returns_dict_when_enough():
    supports = [
        levels.Anchor(price=95.0, source="s1", source_type="swing", computed_score=10),
    ]
    resistances = [
        levels.Anchor(price=105.0, source="r1", source_type="web", computed_score=8),
        levels.Anchor(price=110.0, source="r2", source_type="yt", computed_score=6),
        levels.Anchor(price=115.0, source="r3", source_type="yt", computed_score=4),
    ]
    plan = levels.select_trade_plan(supports, resistances)
    assert plan["sl"] == 95.0
    assert plan["tp1"] == 105.0
    assert plan["tp2"] == 110.0
    assert plan["tp3"] == 115.0
    assert plan["suppression_reason"] is None


# ---------------------------------------------------------------------------
# gap_fill.py
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gap_fill_no_triggers_returns_empty():
    out = await gap_fill.run_gap_fill(
        ticker="NVDA",
        anchors_count=10,
        sec_filings=[],
        has_event_date=True,
        direction="bullish",
        deadline=asyncio.get_event_loop().time() + 30,
    )
    assert out == {
        "harvested_anchors_snippets": [],
        "eight_k_summary_snippets": [],
        "event_date_snippets": [],
        "catalyst_research_snippets": [],
    }


@pytest.mark.asyncio
async def test_gap_fill_anchor_trigger_calls_searxng():
    fake = [{"title": "t", "url": "u", "content": "price target $150 support"}]
    with patch.object(gap_fill.searxng, "search_searxng",
                      new=AsyncMock(return_value=fake)) as mock_s:
        out = await gap_fill.run_gap_fill(
            ticker="NVDA",
            anchors_count=2,           # < 4 → triggers anchors query
            sec_filings=[],
            has_event_date=True,
            direction="bullish",
            deadline=__import__("time").time() + 10,
        )
    assert mock_s.await_count == 1
    assert out["harvested_anchors_snippets"] == [
        "price target $150 support"
    ]
    assert out["eight_k_summary_snippets"] == []


@pytest.mark.asyncio
async def test_gap_fill_per_query_timeout_isolates_slow_query():
    async def slow(_q):
        await asyncio.sleep(20)  # simulates >8s SearXNG hang
        return [{"content": "should never see this"}]

    with patch.object(gap_fill.searxng, "search_searxng", new=slow):
        # patch the per-query cap down so the test is fast
        with patch.object(gap_fill, "_PER_QUERY_TIMEOUT", 0.1):
            out = await gap_fill.run_gap_fill(
                ticker="NVDA",
                anchors_count=0,
                sec_filings=[],
                has_event_date=True,
                direction="bullish",
                deadline=__import__("time").time() + 10,
            )
    assert out["harvested_anchors_snippets"] == []


@pytest.mark.asyncio
async def test_gap_fill_outer_deadline_aborts():
    async def slow(_q):
        await asyncio.sleep(2)
        return []

    with patch.object(gap_fill.searxng, "search_searxng", new=slow):
        out = await gap_fill.run_gap_fill(
            ticker="NVDA",
            anchors_count=0,
            sec_filings=[],
            has_event_date=True,
            direction="bullish",
            deadline=__import__("time").time() - 1,  # already past
        )
    # Outer deadline 0 → returns empty without calling SearXNG
    assert out["harvested_anchors_snippets"] == []


# ---------------------------------------------------------------------------
# structured_fields.py
# ---------------------------------------------------------------------------

def test_structured_compute_direction_bullish():
    sb = ScoreBreakdown(news_catalyst=10, technical=5, social_reddit=3)
    assert structured_fields.compute_direction(sb) == "BULLISH"


def test_structured_compute_direction_bearish():
    sb = ScoreBreakdown(news_catalyst=-15, technical=-5)
    assert structured_fields.compute_direction(sb) == "BEARISH"


def test_structured_compute_direction_neutral_when_zero():
    sb = ScoreBreakdown()
    assert structured_fields.compute_direction(sb) == "NEUTRAL"


def test_structured_confidence_label_uses_threshold():
    assert structured_fields.compute_confidence_label(85, threshold=80) == "HIGH"
    assert structured_fields.compute_confidence_label(70, threshold=80) == "LOW"


def test_structured_breakout_timeframe_prefers_earnings_within_30():
    from datetime import date, timedelta
    soon = (date.today() + timedelta(days=7)).isoformat()
    out = structured_fields.compute_breakout_timeframe("NVDA", soon, None)
    assert "earnings" in out and soon in out


def test_structured_breakout_timeframe_tbd_when_nothing_close():
    out = structured_fields.compute_breakout_timeframe("NVDA", None, None)
    assert out == "TBD"


def test_structured_magnitude_tbd_when_no_atr():
    assert structured_fields.compute_magnitude(None, 100.0) == "TBD"


def test_structured_magnitude_formats_2x_atr():
    out = structured_fields.compute_magnitude(2.5, 100.0)
    assert "5.00" in out and "ATR" in out


# ---------------------------------------------------------------------------
# output_filter.py
# ---------------------------------------------------------------------------

def test_output_filter_strips_markdown_links():
    out = output_filter.sanitize_narrative("See [the report](https://x.com).")
    assert "[the report](" not in out
    assert "the report (https://x.com)" in out


def test_output_filter_redacts_at_everyone():
    out = output_filter.sanitize_narrative("@everyone buy NVDA now @here!")
    assert "@everyone" not in out
    assert "@here" not in out
    assert "[mention removed]" in out


def test_output_filter_strips_control_chars():
    out = output_filter.sanitize_narrative("hello\x00world\x07")
    assert "\x00" not in out
    assert "\x07" not in out


def test_output_filter_detect_contradiction_bullish_with_bear_words():
    s = StructuredFields(direction="BULLISH", confidence_label="HIGH")
    # Post-iter3: detector requires explicit thesis-reversal phrasing,
    # not bare financial vocabulary like "sell signal" / "short interest".
    assert output_filter.detect_contradiction(
        "Our outlook is bearish despite the bullish setup.", s,
    )
    # Bare-word usage that legitimately appears in catalyst lists must NOT trip.
    assert not output_filter.detect_contradiction(
        "Short interest is climbing and sell-side analysts upgraded the name.", s,
    )


def test_output_filter_detect_contradiction_no_flag_on_neutral():
    s = StructuredFields(direction="NEUTRAL", confidence_label="LOW")
    assert not output_filter.detect_contradiction("Could be a sell or buy", s)


@pytest.mark.asyncio
async def test_output_filter_sanitize_or_retry_returns_ok_when_clean():
    s = StructuredFields(direction="BULLISH", confidence_label="HIGH")
    retry = AsyncMock(return_value="should not be called")
    text, status = await output_filter.sanitize_or_retry(
        "Strong upside ahead with a breakout setup.", s, retry,
    )
    assert status == "ok"
    assert "upside" in text
    retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_output_filter_sanitize_or_retry_falls_back_when_retry_still_contradicts():
    s = StructuredFields(direction="BULLISH", confidence_label="HIGH")
    retry = AsyncMock(return_value="Still a bearish thesis on this name.")
    text, status = await output_filter.sanitize_or_retry(
        "Bearish reversal is the dominant view here.", s, retry,
    )
    assert status == "fallback_data_only"
    assert text == ""


def test_output_filter_render_data_only_fallback_two_lines():
    s = StructuredFields(direction="BULLISH", confidence_label="HIGH")
    sb = ScoreBreakdown(news_catalyst=20, technical=10)
    out = output_filter.render_data_only_fallback(s, sb, sources=["a", "b"])
    assert out.count("\n") == 1
    assert "BULLISH" in out and "HIGH" in out


# ---------------------------------------------------------------------------
# embed.py
# ---------------------------------------------------------------------------

def test_embed_color_bullish_high_conf():
    s = StructuredFields(direction="BULLISH", confidence_label="HIGH")
    sb = ScoreBreakdown(news_catalyst=20)
    out = embed_mod.build_embed("NVDA", s, sb, "narrative", ["src"], None)
    assert out["color"] == 0x57F287


def test_embed_color_bearish_high_conf():
    s = StructuredFields(direction="BEARISH", confidence_label="HIGH")
    sb = ScoreBreakdown()
    out = embed_mod.build_embed("NVDA", s, sb, "narrative", [], None)
    assert out["color"] == 0xED4245


def test_embed_color_neutral_or_low_conf():
    s = StructuredFields(direction="BULLISH", confidence_label="LOW")
    sb = ScoreBreakdown()
    out = embed_mod.build_embed("NVDA", s, sb, "n", [], None)
    assert out["color"] == 0xFEE75C


def test_embed_field_count_exactly_3_inline():
    """Commit 16 cut the embed to 3 inline fields — Direction, Confidence,
    Price. Buy Zone / SL / TP / Horizon / Next Catalyst / Expected Move were
    dropped as visual duplication of the narrative Trade Plan table."""
    s = StructuredFields(
        direction="BULLISH", confidence_label="HIGH",
        sl=98.5, tp1=112, tp2=125, tp3=140,
        breakout_timeframe="earnings 2026-05-15",
        magnitude_label="±$8.20 (2× ATR)",
        current_price=110.0, buy_zone_low=105.0, buy_zone_high=110.0,
        next_catalyst_days=4,
        swing_horizon_days=10,
        swing_horizon_band=(8, 13),
        expected_move_typical=8.5,
        magnitude_band_label="±$8 / 10d",
    )
    sb = ScoreBreakdown(news_catalyst=20)
    out = embed_mod.build_embed("NVDA", s, sb, "n", ["a"], None)
    assert len(out["fields"]) == 3
    assert all(f.get("inline") for f in out["fields"])
    assert [f["name"] for f in out["fields"]] == ["Direction", "Confidence", "Price"]


def test_embed_truncates_long_narrative_keeps_score_line():
    s = StructuredFields(direction="BULLISH", confidence_label="HIGH")
    sb = ScoreBreakdown(news_catalyst=20)
    long_n = "A" * 6000
    out = embed_mod.build_embed("NVDA", s, sb, long_n, ["src"], None)
    desc = out["description"]
    assert len(desc) <= 4000
    assert "**Score:**" in desc  # score line ALWAYS stays
    assert "see vault for full" in desc


def test_embed_drops_sources_line_under_pressure_moves_to_footer():
    s = StructuredFields(direction="BULLISH", confidence_label="HIGH")
    sb = ScoreBreakdown(news_catalyst=20)
    # Long narrative + many sources → step 2 should fire
    out = embed_mod.build_embed(
        "NVDA", s, sb,
        "A" * 5000,
        sources_used=[f"site-{i}.example.com" for i in range(10)],
        cache_age_seconds=None,
    )
    desc = out["description"]
    assert len(desc) <= 4000
    # When sources line was dropped, the footer mentions "(see vault)"
    if "**Sources:**" not in desc:
        assert "see vault" in out["footer"]["text"]


# ---------------------------------------------------------------------------
# narrator.py (sanitize functions only — synthesis is PR4b)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_narrator_sanitize_hostile_text_makes_exactly_4_calls():
    """Total = 4 LLM calls regardless of snippet count (Pass 4 critic R1)."""
    fake_resp = "1. summary one\n2. summary two\n3. summary three"
    with patch("consensus_engine.alerts.all_command.narrator.call_with_fallback",
               new=AsyncMock(return_value=fake_resp)) as mock_llm:
        out = await narrator.sanitize_hostile_text(
            searxng_snippets=["a", "b", "c"],
            chat_msgs=["m1", "m2"],
            brief_msgs=["b1"],
            vault_text="prior research notes",
        )
    assert mock_llm.await_count == 4
    assert isinstance(out["searxng"], list)
    assert isinstance(out["chat"], list)
    assert isinstance(out["brief"], list)
    assert isinstance(out["vault"], str)


@pytest.mark.asyncio
async def test_narrator_sanitize_hostile_text_concurrent_via_gather():
    """All 4 batches dispatched concurrently — total time ~= max(individual)."""
    call_log: list[float] = []

    async def slow_llm(*_args, **_kwargs):
        loop = asyncio.get_event_loop()
        call_log.append(loop.time())
        await asyncio.sleep(0.1)
        return "1. ok"

    with patch("consensus_engine.alerts.all_command.narrator.call_with_fallback",
               new=slow_llm):
        loop = asyncio.get_event_loop()
        t0 = loop.time()
        await narrator.sanitize_hostile_text(
            ["a"], ["b"], ["c"], "d"
        )
        elapsed = loop.time() - t0
    # If sequential, would be ~0.4s. Concurrent should be ~0.1-0.2s.
    assert elapsed < 0.3
    assert len(call_log) == 4


@pytest.mark.asyncio
async def test_narrator_sanitize_text_helper_caps_at_300_chars():
    long = "x" * 1000
    out = narrator._sanitize_text(long)
    assert len(out) == 300
