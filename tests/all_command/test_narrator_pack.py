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
def test_constraints_block_contains_bear_case_marker(swing_v2):
    block = narrator._build_constraints_block(swing_v2)
    assert "**What could go wrong:**" in block


@pytest.mark.parametrize("swing_v2", [True, False])
def test_constraints_block_contains_risks_marker(swing_v2):
    block = narrator._build_constraints_block(swing_v2)
    assert "**Risks & mitigants:**" in block


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
def test_constraints_block_includes_arrow_mitigant_examples(swing_v2):
    block = narrator._build_constraints_block(swing_v2)
    # M6 — risk → mitigant form with concrete trade-plan features.
    assert "→ Trim half at TP1" in block
    assert "→ Stop at" in block


# ---------------------------------------------------------------------------
# quality_bar.has_required_sections
# ---------------------------------------------------------------------------

_FULL_NARRATIVE = (
    "**TL;DR:** Long $NVDA above $920, target $980.\n"
    "Body opening with **Market view:** consensus / **Our view:** ours / "
    "**Catalyst:** the diff.\n"
    "## Catalysts\n"
    "* item\n"
    "## Risk Considerations\n"
    "* risk one\n"
    "**What could go wrong:** Daily close below $895 invalidates [evidence:1].\n"
    "**Risks & mitigants:**\n"
    "- thesis break → Stop at $895\n"
    "- vol spike → Trim half at TP1\n"
    "## Trade Plan\n"
    "| Parameter | Level | Rationale |\n"
)


def test_has_required_sections_true_for_full_narrative():
    assert quality_bar.has_required_sections(_FULL_NARRATIVE)


def test_has_required_sections_false_missing_tldr():
    n = _FULL_NARRATIVE.replace("**TL;DR:**", "**Summary:**")
    assert not quality_bar.has_required_sections(n)


def test_has_required_sections_false_missing_bear_case():
    n = _FULL_NARRATIVE.replace("**What could go wrong:**", "Maybe trouble:")
    assert not quality_bar.has_required_sections(n)


def test_has_required_sections_false_missing_risks():
    n = _FULL_NARRATIVE.replace("**Risks & mitigants:**", "**Risks (no mit):**")
    assert not quality_bar.has_required_sections(n)


def test_has_required_sections_false_empty():
    assert not quality_bar.has_required_sections("")
    assert not quality_bar.has_required_sections(None)


def test_missing_required_sections_lists_only_missing():
    n = "**TL;DR:** present.\n only TL;DR section."
    missing = quality_bar.missing_required_sections(n)
    assert "**TL;DR:**" not in missing
    assert "**What could go wrong:**" in missing
    assert "**Risks & mitigants:**" in missing


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
