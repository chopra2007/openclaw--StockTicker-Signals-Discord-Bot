"""Tests for #6 A3 — Risk/Reward ratio of the computed trade plan."""
from consensus_engine.alerts.all_command.structured_fields import (
    compute_risk_reward, StructuredFields,
)
from consensus_engine.alerts.all_command import embed


def test_bullish_happy_path():
    # spot 100, SL 90 (risk 10), TP1 124 (reward 24) -> 2.4
    assert compute_risk_reward(100.0, 90.0, 124.0, "BULLISH") == 2.4


def test_bearish_happy_path():
    # short: spot 100, SL 110 (risk 10), TP1 76 (reward 24) -> 2.4
    assert compute_risk_reward(100.0, 110.0, 76.0, "BEARISH") == 2.4


def test_neutral_returns_none():
    assert compute_risk_reward(100.0, 90.0, 124.0, "NEUTRAL") is None


def test_low_confidence_plan_omitted():
    # ATR-fallback plans (confidence == "low") would yield a synthetic ratio.
    assert compute_risk_reward(100.0, 90.0, 124.0, "BULLISH", "low") is None
    # any other confidence is fine
    assert compute_risk_reward(100.0, 90.0, 124.0, "BULLISH", "high") == 2.4


def test_missing_levels_return_none():
    assert compute_risk_reward(None, 90.0, 124.0, "BULLISH") is None
    assert compute_risk_reward(100.0, None, 124.0, "BULLISH") is None
    assert compute_risk_reward(100.0, 90.0, None, "BULLISH") is None


def test_zero_or_negative_risk_reward_returns_none():
    assert compute_risk_reward(100.0, 100.0, 124.0, "BULLISH") is None   # spot==sl -> risk 0
    assert compute_risk_reward(100.0, 90.0, 100.0, "BULLISH") is None    # reward 0
    assert compute_risk_reward(100.0, 90.0, 99.0, "BULLISH") is None     # TP1 below spot -> reward<0


def test_low_but_valid_ratio_kept():
    # risk 10, reward 1 -> 0.1 (a poor but real setup; still informative)
    assert compute_risk_reward(100.0, 90.0, 101.0, "BULLISH") == 0.1


def test_absurd_ratio_omitted():
    # SL ~ at spot -> tiny risk -> huge ratio -> omit
    assert compute_risk_reward(100.0, 99.99, 200.0, "BULLISH") is None


def test_structured_fields_carries_risk_reward():
    sf = StructuredFields(direction="BULLISH", confidence_label="HIGH", risk_reward=2.4)
    assert sf.risk_reward == 2.4
    # default is None when not set (field omitted in embed)
    assert StructuredFields(direction="NEUTRAL", confidence_label="LOW").risk_reward is None
