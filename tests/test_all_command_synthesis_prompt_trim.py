"""#15 (full-audit-2026-06-06) — trim the static synthesis constraints block.

The full constraints prose repeats the "cite verbatim / don't invent"
anti-fabrication rule ~4x. Item #15 collapses those repeats into ONE canonical
statement, referenced once, behind the flag `all_command.synthesis_prompt_trim`
(default OFF). Flag OFF keeps today's full prompt verbatim; flag ON uses the
trimmed prompt (~30-40% shorter constraints block) while preserving every
DISTINCT rule (forbidden-pattern keywords, expected-move clause, section
requirements).

Asserts:
  * flag OFF (default) → `_build_constraints_block` is byte-identical to the
    full builder, and the SYS+constraints total matches the audited baseline.
  * flag ON → shorter than full (30-40% off the constraints block) but still
    contains every distinct forbidden-pattern keyword and section requirement.
"""
from __future__ import annotations

from unittest.mock import patch

from consensus_engine import config as cfg
from consensus_engine.alerts.all_command import narrator


# Audited baseline: len(_SYS_INSTRUCTION) + len(_build_constraints_block(True))
# == 11725 chars (~2,931 tokens). Locks the flag-OFF path against regression.
_BASELINE_TOTAL = 11725

# Distinct forbidden-pattern keywords the trim MUST preserve (the auto-reject
# behavior is load-bearing — free models fabricate without it).
_FORBIDDEN_KEYWORDS = (
    "Projected",
    "Expected partnership",
    "industry chatter",
    "codenamed",
    "estimated",
)

# Distinct section / rule requirements the trim MUST preserve.
_DISTINCT_RULES = (
    "**TL;DR:**",
    "## Catalysts",
    "## Risk Considerations",
    "## Trade Plan",
    "NO PRICE LEVELS",
    "[evidence:N]",
    "BANNED",
    "Market view:",
    "Our view:",
    "VERBATIM",
)


def _flag_cfg(enabled: bool):
    """Override only all_command.synthesis_prompt_trim; pass-through rest."""
    real_get = cfg.get

    def fake_get(key, default=None):
        if key == "all_command.synthesis_prompt_trim":
            return enabled
        return real_get(key, default)

    return patch("consensus_engine.config.get", side_effect=fake_get)


def test_flag_off_byte_identical_to_full_builder():
    with _flag_cfg(False):
        for swing_v2 in (True, False):
            assert (
                narrator._build_constraints_block(swing_v2)
                == narrator._build_constraints_block_full(swing_v2)
            )


def test_flag_off_total_matches_audited_baseline():
    with _flag_cfg(False):
        total = (
            len(narrator._SYS_INSTRUCTION)
            + len(narrator._build_constraints_block(True))
        )
    assert total == _BASELINE_TOTAL


def test_flag_on_uses_trimmed_builder():
    with _flag_cfg(True):
        for swing_v2 in (True, False):
            assert (
                narrator._build_constraints_block(swing_v2)
                == narrator._build_constraints_block_trimmed(swing_v2)
            )


def test_flag_on_is_shorter_within_target_band():
    # 30-40% off the constraints block, both swing_v2 paths.
    for swing_v2 in (True, False):
        full = narrator._build_constraints_block_full(swing_v2)
        trimmed = narrator._build_constraints_block_trimmed(swing_v2)
        pct_off = (len(full) - len(trimmed)) / len(full)
        assert len(trimmed) < len(full)
        assert 0.30 <= pct_off <= 0.40, (
            f"swing_v2={swing_v2}: {pct_off:.1%} off the constraints block "
            "(target 30-40%)"
        )


def test_flag_on_preserves_every_forbidden_pattern_keyword():
    trimmed = narrator._build_constraints_block_trimmed(True)
    for kw in _FORBIDDEN_KEYWORDS:
        assert kw in trimmed, f"trim dropped forbidden-pattern keyword: {kw!r}"


def test_flag_on_preserves_every_distinct_rule():
    for swing_v2 in (True, False):
        trimmed = narrator._build_constraints_block_trimmed(swing_v2)
        for rule in _DISTINCT_RULES:
            assert rule in trimmed, (
                f"swing_v2={swing_v2}: trim dropped distinct rule: {rule!r}"
            )


def test_flag_on_keeps_expected_move_clause_for_swing_v2():
    # The expected-move anti-invent clause is swing_v2-only in both paths.
    trimmed_v2 = narrator._build_constraints_block_trimmed(True)
    trimmed_v0 = narrator._build_constraints_block_trimmed(False)
    assert "Expected Move" in trimmed_v2
    assert "Expected Move" not in trimmed_v0
