"""Unit tests for Ship 1 + Ship 2 helpers in consensus_engine/alerts/all_command/embed.py."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from consensus_engine.alerts.all_command import embed


# ---------------------------------------------------------------------------
# Ship 1 N1 — cashtag
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("NVDA", "$NVDA"),
        ("$AAPL", "$AAPL"),
        ("tsla", "$TSLA"),
        (" amd ", "$AMD"),
    ],
)
def test_fmt_cashtag_happy(raw, expected):
    assert embed._fmt_cashtag(raw) == expected


def test_fmt_cashtag_empty():
    assert embed._fmt_cashtag("") == ""


# ---------------------------------------------------------------------------
# Ship 1 N3 — compact money
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value,expected",
    [
        (2_400_000, "$2.4M"),
        (437_000, "$437K"),
        (1_200_000_000, "$1.2B"),
        (120, "$120"),
        (999, "$1K"),
        (12_345_678, "$12.3M"),
        (-2_400_000, "-$2.4M"),
    ],
)
def test_fmt_money_compact_happy(value, expected):
    assert embed._fmt_money_compact(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "—"),
        ("not-a-number", "—"),
        ([], "—"),
    ],
)
def test_fmt_money_compact_invalid(value, expected):
    assert embed._fmt_money_compact(value) == expected


def test_fmt_money_compact_fraction():
    assert embed._fmt_money_compact(120.50) == "$120.50"


# ---------------------------------------------------------------------------
# Ship 1 N4 — arrow for level
# ---------------------------------------------------------------------------

def test_arrow_for_level_above():
    assert embed._arrow_for_level(185.20, 180.00) == "↑"


def test_arrow_for_level_below():
    assert embed._arrow_for_level(178.50, 180.00) == "↓"


def test_arrow_for_level_within_tolerance():
    # 180.05 / 180 = within 0.1 %
    assert embed._arrow_for_level(180.05, 180.00) == "⇄"


def test_arrow_for_level_none_inputs():
    assert embed._arrow_for_level(None, 180.0) == ""
    assert embed._arrow_for_level(180.0, None) == ""


def test_arrow_for_level_zero_current():
    assert embed._arrow_for_level(10.0, 0.0) == ""


# ---------------------------------------------------------------------------
# Ship 1 N2 — direction emoji upgrade
# ---------------------------------------------------------------------------

def test_direction_emoji_bullish():
    assert embed._direction_emoji("BULLISH") == "🟢 BULLISH"


def test_direction_emoji_bearish():
    assert embed._direction_emoji("BEARISH") == "🔴 BEARISH"


def test_direction_emoji_neutral_and_unknown():
    assert embed._direction_emoji("NEUTRAL") == "⚪ NEUTRAL"
    assert embed._direction_emoji("") == "⚪ NEUTRAL"
    assert embed._direction_emoji("WAT") == "⚪ NEUTRAL"


# ---------------------------------------------------------------------------
# Ship 1 N5 — per-level italic one-liner
# ---------------------------------------------------------------------------

def test_level_oneliner_sl_bullish_mentions_exit():
    text = embed._level_oneliner("SL", 178.5, 180.0, "BULLISH")
    assert text.startswith("_") and text.endswith("_")
    assert "exit" in text.lower() or "invalidated" in text.lower()


def test_level_oneliner_tp1_present():
    assert embed._level_oneliner("TP1", 200.0, 180.0, "BULLISH") != ""


def test_level_oneliner_none_value_empty():
    assert embed._level_oneliner("SL", None, 180.0, "BULLISH") == ""


def test_level_oneliner_unknown_field():
    assert embed._level_oneliner("XYZ", 200.0, 180.0, "BULLISH") == ""


# ---------------------------------------------------------------------------
# Ship 1 N7 — relative date
# ---------------------------------------------------------------------------

def test_fmt_relative_date_today():
    today = date.today().isoformat()
    assert embed._fmt_relative_date(today) == "today"


def test_fmt_relative_date_one_session():
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert embed._fmt_relative_date(tomorrow) == "in 1 session"


def test_fmt_relative_date_n_sessions():
    in_three = (date.today() + timedelta(days=3)).isoformat()
    assert embed._fmt_relative_date(in_three) == "in 3 sessions"


def test_fmt_relative_date_days():
    in_thirty = (date.today() + timedelta(days=30)).isoformat()
    assert embed._fmt_relative_date(in_thirty) == "in 30 days"


def test_fmt_relative_date_past():
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    assert embed._fmt_relative_date(yesterday) == "1 day ago"
    last_week = (date.today() - timedelta(days=7)).isoformat()
    assert embed._fmt_relative_date(last_week) == "7 days ago"


def test_fmt_relative_date_invalid_returns_input():
    assert embed._fmt_relative_date("not-a-date") == "not-a-date"


def test_fmt_relative_date_empty_returns_empty():
    assert embed._fmt_relative_date("") == ""
    assert embed._fmt_relative_date(None) == ""


# ---------------------------------------------------------------------------
# Ship 2 M1 — TL;DR extraction
# ---------------------------------------------------------------------------

def test_extract_tldr_first_line():
    narrative = (
        "**TL;DR:** Long $NVDA above $920, target $980, stop $895.\n"
        "\nMore text here.\n"
        "## Catalysts\n"
        "* item one\n"
    )
    assert embed._extract_tldr(narrative).startswith("Long $NVDA")


def test_extract_tldr_case_insensitive():
    narrative = "**tl;dr:** lowercase header still matches."
    assert "lowercase header" in embed._extract_tldr(narrative)


def test_extract_tldr_missing_returns_empty():
    assert embed._extract_tldr("just a paragraph, no header.") == ""


def test_extract_tldr_none():
    assert embed._extract_tldr("") == ""


def test_strip_tldr_removes_line():
    narrative = (
        "**TL;DR:** Long $NVDA, target $980.\n"
        "Body content.\n"
    )
    stripped = embed._strip_tldr(narrative)
    assert "TL;DR" not in stripped
    assert "Body content" in stripped


# ---------------------------------------------------------------------------
# Integration: build_embed wires everything
# ---------------------------------------------------------------------------

class _FakeStructured:
    direction = "BULLISH"
    confidence_label = "HIGH"
    current_price = 180.00
    buy_zone_low = 178.00
    buy_zone_high = 180.00
    sl = 175.00
    tp1 = 190.00
    tp2 = 200.00
    tp3 = 210.00
    earnings_date = None
    breakout_timeframe = "TBD"
    magnitude_label = "TBD"
    next_catalyst_days = 3
    swing_horizon_days = 14
    swing_horizon_band = (10, 18)
    expected_move_typical = 5.0
    expected_move_high_vol = 8.0
    magnitude_band_label = "±$5–$8 / 2w"


class _FakeBreakdown:
    total = 82
    news_catalyst = 20
    social_apewisdom = 0
    social_stocktwits = 0
    social_reddit = 0
    google_trends = 0
    technical = 30
    llm_boost = 20
    options_flow = 0
    consensus_boost = 12


def test_build_embed_renders_cashtag_title():
    payload = embed.build_embed(
        ticker="NVDA",
        structured=_FakeStructured(),
        score_breakdown=_FakeBreakdown(),
        narrative="**TL;DR:** test thesis sentence.\nBody.",
        sources_used=["news", "twitter"],
        cache_age_seconds=None,
    )
    assert payload["title"] == "$NVDA — Full Analysis"


def test_build_embed_first_description_line_is_tldr():
    payload = embed.build_embed(
        ticker="NVDA",
        structured=_FakeStructured(),
        score_breakdown=_FakeBreakdown(),
        narrative="**TL;DR:** test thesis sentence.\nBody content.",
        sources_used=["news"],
        cache_age_seconds=None,
    )
    first_line = payload["description"].splitlines()[0]
    assert first_line.startswith("**TL;DR:** test thesis")


def test_build_embed_no_tldr_falls_back_to_direction_line():
    payload = embed.build_embed(
        ticker="NVDA",
        structured=_FakeStructured(),
        score_breakdown=_FakeBreakdown(),
        narrative="Just a paragraph without a header.",
        sources_used=["news"],
        cache_age_seconds=None,
    )
    first_line = payload["description"].splitlines()[0]
    assert first_line == "🟢 BULLISH"


def test_build_embed_only_three_inline_fields_post_dedupe():
    """Commit 16: embed shows ONLY Direction / Confidence / Price as
    inline fields. The trade-plan-duplicating fields (Buy Zone, SL,
    TP1-3, Horizon, Next Catalyst, Expected Move) were dropped because
    they duplicate the LLM-generated Trade Plan table per user feedback."""
    payload = embed.build_embed(
        ticker="NVDA",
        structured=_FakeStructured(),
        score_breakdown=_FakeBreakdown(),
        narrative="**TL;DR:** thesis.\nBody.",
        sources_used=["news"],
        cache_age_seconds=None,
    )
    names = [f["name"] for f in payload["fields"]]
    assert names == ["Direction", "Confidence", "Price"]
    # Dropped fields must NOT appear
    for dropped in ("Buy Zone", "SL", "TP1", "TP2", "TP3",
                    "Next Catalyst", "Horizon", "Expected Move",
                    "Timeframe", "Magnitude"):
        assert dropped not in names


def test_build_embed_direction_field_uses_new_emoji():
    payload = embed.build_embed(
        ticker="NVDA",
        structured=_FakeStructured(),
        score_breakdown=_FakeBreakdown(),
        narrative="",
        sources_used=[],
        cache_age_seconds=None,
    )
    direction_field = next(f["value"] for f in payload["fields"] if f["name"] == "Direction")
    assert direction_field == "🟢 BULLISH"
