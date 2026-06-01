"""Unit tests for Ship 2 narrator constraints + quality_bar structural gate."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from consensus_engine.alerts.all_command import narrator, quality_bar
from consensus_engine.alerts.all_command.structured_fields import StructuredFields


# ---------------------------------------------------------------------------
# CONSTRAINTS block — Ship 2 markers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("swing_v2", [True, False])
def test_constraints_block_contains_tldr_marker(swing_v2):
    block = narrator._build_constraints_block(swing_v2)
    assert "**TL;DR:**" in block


@pytest.mark.parametrize("swing_v2", [True, False])
def test_constraints_block_has_single_merged_risk_section(swing_v2):
    # all-risk-section: the 3 overlapping risk sections were merged into ONE
    # `## Risk Considerations`, and the old headings are explicitly banned.
    block = narrator._build_constraints_block(swing_v2)
    assert "## Risk Considerations" in block
    assert "do NOT emit those headings" in block


@pytest.mark.parametrize("swing_v2", [True, False])
def test_constraints_block_bans_price_and_generic_risks(swing_v2):
    block = narrator._build_constraints_block(swing_v2)
    assert "NO PRICE LEVELS" in block   # no stop-loss restatement
    assert "BANNED" in block            # generic-risk ban list
    assert "[evidence:N]" in block      # per-bullet citation still required


@pytest.mark.parametrize("swing_v2", [True, False])
def test_constraints_block_contains_variant_perception_pattern(swing_v2):
    block = narrator._build_constraints_block(swing_v2)
    assert "Market view:" in block
    assert "Our view:" in block
    assert "Catalyst:" in block


@pytest.mark.parametrize("swing_v2", [True, False])
def test_constraints_block_contains_contradiction_clause(swing_v2):
    block = narrator._build_constraints_block(swing_v2)
    # M2 (a) — Bear Case must acknowledge COMPUTED SIGNAL direction.
    assert "INVALIDATE" in block.upper() or "invalidate" in block.lower()
    assert "acknowledge" in block.lower()


@pytest.mark.parametrize("swing_v2", [True, False])
def test_constraints_block_contains_evidence_clause(swing_v2):
    block = narrator._build_constraints_block(swing_v2)
    # M2 (b) — Bear Case sentences must carry [evidence:N] marker.
    assert "[evidence:N]" in block


@pytest.mark.parametrize("swing_v2", [True, False])
def test_constraints_block_includes_swing_risk_buckets(swing_v2):
    # all-risk-section: merged risk section draws from evidence-conditional
    # swing-trade buckets instead of the old generic Bear Case / mitigants.
    block = narrator._build_constraints_block(swing_v2)
    assert "Macro / regulatory" in block
    assert "Event / binary" in block
    assert "Positioning / crowding" in block


# ---------------------------------------------------------------------------
# quality_bar.has_required_sections
# ---------------------------------------------------------------------------

# all-risk-section: merged-section fixture. ONE `## Risk Considerations`, no
# old headings, and NO price level inside the risk section (so the Feature-B
# stop-price gate stays clean).
_FULL_NARRATIVE = (
    "**TL;DR:** Long $NVDA above $920, target $980.\n"
    "Body opening with **Market view:** consensus / **Our view:** ours / "
    "**Catalyst:** the diff.\n"
    "## Catalysts\n"
    "* item\n"
    "## Risk Considerations\n"
    "* China export curbs cut ~17% of revenue [evidence:1].\n"
    "* Short interest 4.2% of float → unwind risk [evidence:2].\n"
    "## Trade Plan\n"
    "| Parameter | Level | Rationale |\n"
)


def test_has_required_sections_true_for_full_narrative():
    assert quality_bar.has_required_sections(_FULL_NARRATIVE)


def test_has_required_sections_false_missing_tldr():
    n = _FULL_NARRATIVE.replace("**TL;DR:**", "**Summary:**")
    assert not quality_bar.has_required_sections(n)


def test_has_required_sections_false_missing_risk_considerations():
    n = _FULL_NARRATIVE.replace("## Risk Considerations", "## Other")
    assert not quality_bar.has_required_sections(n)


def test_has_required_sections_false_empty():
    assert not quality_bar.has_required_sections("")
    assert not quality_bar.has_required_sections(None)


def test_missing_required_sections_lists_only_missing():
    n = "**TL;DR:** present.\n only TL;DR section."
    missing = quality_bar.missing_required_sections(n)
    assert "**TL;DR:**" not in missing
    assert "## Risk Considerations" in missing


# ---------------------------------------------------------------------------
# all-risk-section Feature B — risk_section_violations hard gate
# ---------------------------------------------------------------------------

def test_risk_section_violations_flags_stop_price():
    narrative = (
        "**TL;DR:** Long.\n## Risk Considerations\n"
        "* A break below $196.19 ends it.\n## Trade Plan\n| x |\n"
    )
    v = quality_bar.risk_section_violations(narrative, 196.19)
    assert v and "196.19" in v[0]


def test_risk_section_violations_clean_when_no_price():
    narrative = (
        "**TL;DR:** Long.\n## Risk Considerations\n"
        "* China export curbs cut revenue [evidence:1].\n## Trade Plan\n| x |\n"
    )
    assert quality_bar.risk_section_violations(narrative, 196.19) == []


def test_risk_section_violations_only_scans_risk_section():
    # the stop price in TL;DR and Trade Plan (outside the risk section) is fine
    narrative = (
        "**TL;DR:** stop $196.19.\n## Risk Considerations\n"
        "* China export curbs [evidence:1].\n## Trade Plan\n| SL | $196.19 |\n"
    )
    assert quality_bar.risk_section_violations(narrative, 196.19) == []


def test_risk_section_violations_none_stop_price():
    narrative = "## Risk Considerations\n* something specific [evidence:1]\n"
    assert quality_bar.risk_section_violations(narrative, None) == []


# ---------------------------------------------------------------------------
# synthesize_narrative retries on missing-sections (M2 quality gate)
# ---------------------------------------------------------------------------

class _S:
    direction = "BULLISH"
    confidence_label = "HIGH"
    current_price = 180.0
    buy_zone_low = 178.0
    buy_zone_high = 180.0
    sl = 175.0
    tp1 = 190.0
    tp2 = 200.0
    tp3 = 210.0
    earnings_date = None
    breakout_timeframe = "TBD"
    magnitude_label = "TBD"
    next_catalyst_days = None
    swing_horizon_days = None
    swing_horizon_band = None
    expected_move_typical = None
    expected_move_high_vol = None
    magnitude_band_label = None


class _BD:
    total = 70


@pytest.mark.asyncio
async def test_synthesize_retries_when_sections_missing():
    """Narrator should call the LLM twice when the first response is missing markers."""
    bad_first = "Just a body, no headers."
    good_second = _FULL_NARRATIVE
    calls = []

    async def fake_invoke(messages, deadline):
        calls.append(messages)
        return bad_first if len(calls) == 1 else good_second

    with patch.object(narrator, "_invoke_synthesis", side_effect=fake_invoke):
        text, status = await narrator.synthesize_narrative(
            ticker="NVDA",
            structured=_S(),
            score_breakdown=_BD(),
            sanitized_searxng=[],
            sanitized_chat=[],
            sanitized_brief=[],
            vault_summary="",
            structured_data_json="{}",
            deadline_seconds=30.0,
        )

    assert len(calls) == 2, "should retry once on missing required sections"
    # The second call's user prompt must list the missing sections.
    assert any("MISSING SECTIONS" in m.get("content", "") for m in calls[1])
    assert "TL;DR" in text
    assert status == "ok"


@pytest.mark.asyncio
async def test_synthesize_no_retry_when_sections_present():
    """If the first response already has all sections, no retry happens."""
    calls = []

    async def fake_invoke(messages, deadline):
        calls.append(messages)
        return _FULL_NARRATIVE

    with patch.object(narrator, "_invoke_synthesis", side_effect=fake_invoke):
        text, status = await narrator.synthesize_narrative(
            ticker="NVDA",
            structured=_S(),
            score_breakdown=_BD(),
            sanitized_searxng=[],
            sanitized_chat=[],
            sanitized_brief=[],
            vault_summary="",
            structured_data_json="{}",
            deadline_seconds=30.0,
        )

    assert len(calls) == 1
    assert status == "ok"
    assert "TL;DR" in text


@pytest.mark.asyncio
async def test_synthesize_retries_when_stop_price_in_risk_section():
    """Feature B gate: re-prompt once when the stop price ($175) leaks into the
    `## Risk Considerations` section (prompt-only bans proved unreliable)."""
    bad_first = (
        "**TL;DR:** Long.\n## Risk Considerations\n"
        "* A break below $175 invalidates it.\n## Trade Plan\n| x |\n"
    )
    good_second = _FULL_NARRATIVE  # clean risk section, no price level
    calls = []

    async def fake_invoke(messages, deadline):
        calls.append(messages)
        return bad_first if len(calls) == 1 else good_second

    with patch.object(narrator, "_invoke_synthesis", side_effect=fake_invoke):
        text, status = await narrator.synthesize_narrative(
            ticker="NVDA",
            structured=_S(),  # _S.sl == 175.0
            score_breakdown=_BD(),
            sanitized_searxng=[],
            sanitized_chat=[],
            sanitized_brief=[],
            vault_summary="",
            structured_data_json="{}",
            deadline_seconds=30.0,
        )

    assert len(calls) == 2, "should retry once when stop price is in risk section"
    assert any("RISK SECTION FIX" in m.get("content", "") for m in calls[1])
    assert status == "ok"


# ---------------------------------------------------------------------------
# TODO #11 — anti-influencer prose: pre-formatters + constraint clause
# ---------------------------------------------------------------------------

def test_format_yt_signals_strips_analyst_name():
    items = [{"analyst_name": "Wicked Stocks", "price_level": 220.0,
              "direction": "long"}]
    out = narrator._format_yt_signals(items)
    assert "analyst_name" not in out[0]
    assert "Wicked Stocks" not in str(out)
    assert out[0]["price_level"] == 220.0
    assert out[0]["direction"] == "long"


def test_format_yt_signals_strips_channel_name_and_adds_source_type():
    items = [{"channel_name": "CheddarFlow", "price_level": 215.0}]
    out = narrator._format_yt_signals(items)
    assert "channel_name" not in out[0]
    assert "CheddarFlow" not in str(out)
    assert out[0]["source_type"] == "youtube"


def test_format_yt_signals_collapses_trust_score_to_curated_tier():
    items = [{"creator_name": "X", "trust_score": 0.85, "price_level": 220.0}]
    out = narrator._format_yt_signals(items)
    assert out[0]["source_type"] == "youtube_curated"
    assert "trust_score" not in out[0]
    assert "X" not in str(out)


def test_format_yt_signals_low_trust_score_yields_general_tier():
    items = [{"handle": "@randomtrader", "trust_score": 0.3, "price_level": 100.0}]
    out = narrator._format_yt_signals(items)
    assert out[0]["source_type"] == "youtube_general"
    assert "@randomtrader" not in str(out)


def test_format_yt_signals_passthrough_for_non_list():
    assert narrator._format_yt_signals(None) is None
    assert narrator._format_yt_signals("not a list") == "not a list"


def test_format_yt_evidence_strips_names_same_as_signals():
    items = [{"author": "Lottery Stocks", "speaker_name": "Joe",
              "price_level": 200.0}]
    out = narrator._format_yt_evidence(items)
    assert "Lottery Stocks" not in str(out)
    assert "Joe" not in str(out)
    assert out[0]["price_level"] == 200.0


@pytest.mark.parametrize("swing_v2", [True, False])
def test_constraints_block_rejects_named_analysts(swing_v2):
    """TODO #11 — anti-influencer rule in CONSTRAINTS."""
    block = narrator._build_constraints_block(swing_v2)
    assert "provenance is not proof" in block.lower()
    assert "rejected" in block.lower()
    assert "analysts are calling" in block.lower()


@pytest.mark.parametrize("swing_v2", [True, False])
def test_constraints_block_does_not_instruct_naming_cheddarflow(swing_v2):
    """The pre-fix instruction explicitly told LLM to cite 'CheddarFlow'."""
    block = narrator._build_constraints_block(swing_v2)
    assert "CheddarFlow" not in block
    assert "name them in the" not in block
