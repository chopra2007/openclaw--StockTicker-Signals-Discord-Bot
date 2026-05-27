"""Unit tests for compute_direction_from_fields + compute_expected_move (Step 9)."""
from __future__ import annotations

import pytest

from consensus_engine.alerts.all_command.structured_fields import (
    compute_direction_from_fields,
    compute_expected_move,
)


# ---------------------------------------------------------------------------
# compute_direction_from_fields
# ---------------------------------------------------------------------------

def test_direction_long():
    fields = {"news_catalyst": 10, "technical": 5, "options_flow": 3}
    assert compute_direction_from_fields(fields) == "LONG"


def test_direction_short():
    fields = {"news_catalyst": -10, "technical": -5, "options_flow": -2}
    assert compute_direction_from_fields(fields) == "SHORT"


def test_direction_neutral_zero_net():
    fields = {"news_catalyst": 5, "technical": -5}
    assert compute_direction_from_fields(fields) == "NEUTRAL"


def test_direction_missing_fields():
    assert compute_direction_from_fields({}) == "NEUTRAL"


def test_direction_non_numeric_skipped():
    fields = {"news_catalyst": "bullish", "technical": 3}
    assert compute_direction_from_fields(fields) == "LONG"


# ---------------------------------------------------------------------------
# compute_expected_move
# ---------------------------------------------------------------------------

def test_expected_move_high_conviction_high_vol():
    result = compute_expected_move({}, "HIGH", 4.0)
    assert result == pytest.approx(6.0)


def test_expected_move_low_conviction_low_vol():
    result = compute_expected_move({}, "LOW", 2.0)
    assert result == pytest.approx(2.0)


def test_expected_move_missing_conviction_tier():
    # Non-HIGH tier uses 1.0 multiplier.
    result = compute_expected_move({}, None, 3.0)
    assert result == pytest.approx(3.0)


def test_expected_move_missing_recent_vol_zero():
    result = compute_expected_move({}, "HIGH", 0.0)
    assert result == 0.0


def test_expected_move_negative_vol_returns_zero():
    result = compute_expected_move({}, "HIGH", -1.5)
    assert result == 0.0


def test_expected_move_invalid_vol_type():
    result = compute_expected_move({}, "HIGH", "not-a-number")
    assert result == 0.0
