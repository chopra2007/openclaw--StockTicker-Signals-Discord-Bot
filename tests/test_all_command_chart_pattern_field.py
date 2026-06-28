"""#21 (full-audit-2026-06-06) — chart-pattern embed field.

The pattern detection + narrator wiring is covered by
tests/test_all_command_chart_pattern_wiring.py. This file covers the NEW
Discord-embed surfacing: the `Pattern` field built inside `build_embed`,
gated behind `all_command.chart_pattern_field_enabled` (default OFF).

Asserts:
  * flag OFF (default) → no Pattern field (byte-identical embed)
  * flag ON, confidence >= 0.5 → field rendered (name + key level + conf)
  * flag ON, confidence < 0.5 → field omitted
  * flag ON, chart_pattern None → field omitted
"""
from __future__ import annotations

from unittest.mock import patch

from consensus_engine import config as cfg
from consensus_engine.models import ScoreBreakdown
from consensus_engine.alerts.all_command.structured_fields import StructuredFields
from consensus_engine.alerts.all_command import embed


_SENTINEL = {"pattern": "bull_flag", "confidence": 0.72, "key_level": 130.50}


def _flag_cfg(enabled: bool):
    """Override only all_command.chart_pattern_field_enabled; pass-through rest."""
    real_get = cfg.get

    def fake_get(key, default=None):
        if key == "all_command.chart_pattern_field_enabled":
            return enabled
        return real_get(key, default)

    return patch("consensus_engine.config.get", side_effect=fake_get)


def _build(chart_pattern):
    sf = StructuredFields(
        direction="BULLISH", confidence_label="HIGH",
        sl=120.0, tp1=140.0, current_price=128.0,
    )
    bd = ScoreBreakdown(news_catalyst=15, technical=4, llm_boost=9, youtube=15)
    return embed.build_embed(
        ticker="NVDA", structured=sf, score_breakdown=bd,
        narrative="**TL;DR:** test.\n## Trade Plan\n| x |",
        sources_used=["news", "technical"], cache_age_seconds=None,
        chart_pattern=chart_pattern,
    )


def _pattern_fields(emb):
    return [f for f in emb.get("fields", []) if f.get("name") == "Pattern"]


def test_flag_off_no_pattern_field():
    """Default-OFF: no Pattern field even when a pattern is present."""
    with _flag_cfg(False):
        emb = _build(_SENTINEL)
    assert _pattern_fields(emb) == [], "Pattern field leaked while flag OFF"


def test_flag_off_byte_identical_with_and_without_pattern():
    """Flag OFF: passing a chart_pattern must not change the embed at all."""
    with _flag_cfg(False):
        with_pattern = _build(_SENTINEL)
        without_pattern = _build(None)
    assert with_pattern == without_pattern


def test_flag_on_renders_pattern_field():
    """Flag ON + confidence >= 0.5 → field with title-cased name + key + conf."""
    with _flag_cfg(True):
        emb = _build(_SENTINEL)
    fields = _pattern_fields(emb)
    assert fields, "Pattern field not rendered while flag ON"
    assert fields[0]["value"] == "Bull Flag — key $130.50 (72% confidence)"


def test_flag_on_low_confidence_omitted():
    """Flag ON but confidence < 0.5 → field omitted."""
    weak = {"pattern": "bull_flag", "confidence": 0.3, "key_level": 130.0}
    with _flag_cfg(True):
        emb = _build(weak)
    assert _pattern_fields(emb) == []


def test_flag_on_none_pattern_omitted():
    """Flag ON but no pattern → field omitted (no crash)."""
    with _flag_cfg(True):
        emb = _build(None)
    assert _pattern_fields(emb) == []


def test_flag_on_no_key_level_renders_without_level():
    """Flag ON, pattern present but key_level missing → name + conf only."""
    no_level = {"pattern": "double_bottom", "confidence": 0.6}
    with _flag_cfg(True):
        emb = _build(no_level)
    fields = _pattern_fields(emb)
    assert fields and fields[0]["value"] == "Double Bottom (60% confidence)"
