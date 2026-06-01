"""all-risk-section v2 — focused tests for the correctness-sensitive fixes.

Covers:
  - Fix #1: squeeze bullet is magnitude-guarded (low short interest is NOT fed
    into the prompt; elevated short interest IS).
  - Fix #2: overextension fields (wk52_high_pct / rsi / rvol) reach the prompt.
  - Fix #3: the risk-section retry is re-validated — a retry that STILL leaks the
    stop price is rejected and the original raw is kept.
  - Fix #5: output_filter strips internal pipeline tags from user-facing prose.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from consensus_engine.alerts.all_command import narrator, output_filter


# ---------------------------------------------------------------------------
# Shared structured-signal stub (mirrors test_narrator_pack._S, plus the v2
# snapshot / technical fields the new wiring reads).
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
    peer_strength = None
    snapshot = None  # overridden per-test


class _BD:
    total = 70


def _capture_computed_signal(calls):
    """Return a fake _invoke_synthesis that records the COMPUTED SIGNAL dict
    parsed out of each call's user prompt, then returns a clean full narrative."""
    good = (
        "**TL;DR:** Long $NVDA.\n"
        "Body with **Market view:** x **Our view:** y **Catalyst:** z.\n"
        "## Catalysts\n* item\n"
        "## Risk Considerations\n"
        "* China export curbs cut revenue [evidence:1].\n"
        "## Trade Plan\n| Parameter | Level | Rationale |\n"
    )

    async def fake_invoke(messages, deadline):
        for m in messages:
            content = m.get("content", "")
            if "COMPUTED SIGNAL:" in content:
                blob = content.split("COMPUTED SIGNAL:", 1)[1].strip()
                # the block is the first JSON object on the next line(s)
                start = blob.find("{")
                depth = 0
                end = start
                for i in range(start, len(blob)):
                    if blob[i] == "{":
                        depth += 1
                    elif blob[i] == "}":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                calls.append(json.loads(blob[start:end]))
                break
        return good

    return fake_invoke


async def _run(structured):
    calls: list[dict] = []
    with patch.object(narrator, "_invoke_synthesis", side_effect=_capture_computed_signal(calls)):
        await narrator.synthesize_narrative(
            ticker="NVDA",
            structured=structured,
            score_breakdown=_BD(),
            sanitized_searxng=[],
            sanitized_chat=[],
            sanitized_brief=[],
            vault_summary="",
            structured_data_json="{}",
            deadline_seconds=30.0,
            sanitized_technical_short={"price_change_pct": 12.4, "rsi": 71.0, "rvol": 1.8},
        )
    assert calls, "synthesis prompt should have been built"
    return calls[0]


# ---------------------------------------------------------------------------
# Fix #1 — magnitude-guard the squeeze bullet
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_low_short_interest_not_fed_to_prompt():
    """A trivial 1.3% short interest (and low days-to-cover) must NOT reach the
    prompt — no number for the model means no noise squeeze bullet."""
    class _LowShort(_S):
        snapshot = {"short_pct": 0.013, "short_days": 1.2}

    cs = await _run(_LowShort())
    assert "short_interest_pct" not in cs
    assert "short_days_to_cover" not in cs


@pytest.mark.asyncio
async def test_elevated_short_interest_is_fed():
    """Genuinely elevated short interest (>=8% of float) IS fed so the model can
    write a real squeeze/unwind bullet."""
    class _HighShort(_S):
        snapshot = {"short_pct": 0.12, "short_days": 3.0}

    cs = await _run(_HighShort())
    assert cs.get("short_interest_pct") == 12.0
    assert cs.get("short_days_to_cover") == 3.0


@pytest.mark.asyncio
async def test_high_days_to_cover_triggers_feed():
    """Days-to-cover >=5 alone is enough crowding to feed short interest even
    when the float percentage is modest."""
    class _HighDTC(_S):
        snapshot = {"short_pct": 0.04, "short_days": 6.0}

    cs = await _run(_HighDTC())
    assert cs.get("short_interest_pct") == 4.0
    assert cs.get("short_days_to_cover") == 6.0


# ---------------------------------------------------------------------------
# Fix #2 — overextension fields reach the prompt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_overextension_fields_fed_to_prompt():
    """wk52_high_pct (real distance-below-high) + rsi + rvol + recent_run_pct
    all reach the prompt so the model can write a grounded overextension bullet
    instead of a weak squeeze line."""
    class _Extended(_S):
        snapshot = {"short_pct": 0.013, "short_days": 1.0, "wk52_high_pct": -9.7}

    cs = await _run(_Extended())
    assert cs.get("wk52_high_pct") == -9.7
    assert cs.get("rsi") == 71.0
    assert cs.get("rvol") == 1.8
    assert cs.get("recent_run_pct") == 12.4
    # low short interest still suppressed alongside the overextension data
    assert "short_interest_pct" not in cs


@pytest.mark.asyncio
async def test_no_wk52_when_absent():
    """Never fabricate a distance-from-high: omit wk52_high_pct when the
    snapshot doesn't carry it."""
    class _NoHigh(_S):
        snapshot = {"short_pct": 0.013}

    cs = await _run(_NoHigh())
    assert "wk52_high_pct" not in cs


# ---------------------------------------------------------------------------
# Fix #3 — the risk-section retry is re-validated before adoption
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_still_leaking_stop_price_is_rejected():
    """The gate's retry must be re-checked. A retry that STILL leaks the stop
    price ($175) is rejected and the ORIGINAL raw is kept (the bug was adopting
    the retry unconditionally)."""
    bad_first = (
        "**TL;DR:** Long.\n## Risk Considerations\n"
        "* A break below $175 invalidates it.\n## Trade Plan\n| x |\n"
    )
    bad_second = (  # stubborn model leaks the SAME stop price again
        "**TL;DR:** Long.\n## Risk Considerations\n"
        "* Still, a close under $175 ends the thesis.\n## Trade Plan\n| x |\n"
    )
    calls = []

    async def fake_invoke(messages, deadline):
        calls.append(messages)
        return bad_first if len(calls) == 1 else bad_second

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

    assert len(calls) == 2, "should retry once on the violation"
    # The retry still violated, so the ORIGINAL raw is kept (not the 2nd draft).
    # Either way the violation is still detectable downstream — the point is we
    # did NOT silently adopt a still-bad retry as if it were clean.
    assert "$175" in text, "original raw kept when retry still leaks the stop"
    # The text shown is the FIRST draft's wording, not the second draft's.
    assert "Still, a close under" not in text


@pytest.mark.asyncio
async def test_clean_retry_is_adopted():
    """When the retry actually fixes the violation, it IS adopted."""
    bad_first = (
        "**TL;DR:** Long.\n## Risk Considerations\n"
        "* A break below $175 invalidates it.\n## Trade Plan\n| x |\n"
    )
    good_second = (
        "**TL;DR:** Long $NVDA.\n"
        "Body with **Market view:** x **Our view:** y **Catalyst:** z.\n"
        "## Catalysts\n* item\n"
        "## Risk Considerations\n"
        "* China export curbs cut revenue [evidence:1].\n"
        "## Trade Plan\n| Parameter | Level | Rationale |\n"
    )
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

    assert len(calls) == 2
    assert status == "ok"
    assert "China export curbs" in text  # clean retry adopted
    assert "$175" not in text


# ---------------------------------------------------------------------------
# Fix #5 — output_filter strips internal pipeline tags
# ---------------------------------------------------------------------------

def test_scrub_macro_risk_tag():
    out = output_filter.sanitize_narrative(
        "China export curbs cut ~17% of revenue per [macro_risk] news."
    )
    assert "[macro_risk]" not in out
    assert "macro_risk" not in out
    assert "17% of revenue per news" in out


def test_scrub_computed_signal_phrase():
    out = output_filter.sanitize_narrative(
        "Risk as indicated by the COMPUTED SIGNAL direction is BULLISH."
    )
    assert "COMPUTED SIGNAL" not in out
    assert "the the" not in out  # no doubled article
    assert "the data" in out


def test_scrub_evidence_tags():
    out = output_filter.sanitize_narrative(
        "Short interest 12% of float [evidence:2] looks crowded."
    )
    assert "[evidence:2]" not in out
    assert "evidence:" not in out


def test_scrub_free_text_evidence_tag():
    # Live NVDA 2026-06-01 leaked a free-text evidence tag the numeric-only regex missed.
    out = output_filter.sanitize_narrative(
        "pullback risk if it unwinds [evidence: the data recent_run_pct and wk52_high_pct]."
    )
    assert "evidence" not in out
    assert "recent_run_pct" not in out
    assert out.strip() == "pullback risk if it unwinds."


def test_scrub_keeps_evidence_based_phrase():
    # The ':'-guard means a real bracketed phrase is NOT stripped.
    clean = "we used an [evidence-based approach] here."
    assert output_filter.sanitize_narrative(clean) == clean


def test_scrub_high_vol_apology_keeps_formula():
    out = output_filter.sanitize_narrative(
        "Expected move ±$5 / 5d (0.7×ATR×√5; high-vol data unavailable)."
    )
    assert "high-vol data unavailable" not in out
    assert "0.7×ATR×√5" in out  # legitimate Trade Plan citation kept


def test_scrub_leaves_clean_prose_untouched():
    clean = "NVDA is long above the base; China curbs are the main macro risk."
    assert output_filter.sanitize_narrative(clean) == clean
