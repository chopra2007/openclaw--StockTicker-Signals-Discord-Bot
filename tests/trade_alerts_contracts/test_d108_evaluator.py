"""M9.1U contracts for the frozen D-108 success-bar evaluator."""

from datetime import datetime, timedelta, timezone
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.d108_evaluator import (
    DRAWDOWN_RECOVERY_WINNING_WEEKS, LOWER_BOUND_Q, POLICY_VERSION, PRIMARY_BLOCK_LENGTH,
    RESAMPLES, SENSITIVITY_BLOCK_LENGTHS, WINNING_WEEK_FRACTION_REQUIRED, TradeResult,
    evaluate_d108,
)
from consensus_engine.trade_alerts_models import RecordError


UTC = timezone.utc
MONDAY = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)  # ISO week 2026-W02


def _week(offset_weeks, *, day_offset=0, hour=14):
    return MONDAY + timedelta(weeks=offset_weeks, days=day_offset, hours=hour - 14)


def _trades(rows):
    """rows: sequence of (week_offset, resolved_r)."""
    return [TradeResult(resolved_r=r, closed_at=_week(w)) for w, r in rows]


def test_rejects_empty_trades():
    with pytest.raises(RecordError):
        evaluate_d108("CANDIDATE", [])


def test_rejects_blank_candidate_id():
    with pytest.raises(RecordError):
        evaluate_d108("  ", _trades([(0, 1.0)]))


def test_rejects_non_finite_resolved_r():
    with pytest.raises(RecordError):
        TradeResult(resolved_r=float("nan"), closed_at=MONDAY)


def test_strong_winning_pattern_passes_all_three():
    # 8 held-out weeks, each with 5 trades, mostly winners at consistent size.
    rows = []
    for week in range(8):
        for trade in range(5):
            rows.append((week, 0.6 if trade < 4 else -1.0))  # 4 wins of 0.6R, 1 loss of 1R
    result = evaluate_d108("STRONG", _trades(rows))

    assert result.policy_version == POLICY_VERSION
    assert result.trade_count == 40
    assert result.consistency.week_count == 8
    assert result.consistency.winning_week_fraction == pytest.approx(1.0)
    assert result.consistency.passed is True
    assert result.profit.mean_r == pytest.approx((4 * 0.6 - 1.0) / 5)
    assert result.profit.primary.passed is True
    assert result.survivability.passed is True
    assert result.passed is True


def test_losing_pattern_fails_all_three():
    rows = []
    for week in range(8):
        for trade in range(5):
            rows.append((week, -0.6 if trade < 4 else 1.0))
    result = evaluate_d108("WEAK", _trades(rows))

    assert result.consistency.winning_week_fraction == pytest.approx(0.0)
    assert result.consistency.passed is False
    assert result.profit.mean_r < 0
    assert result.profit.primary.passed is False
    assert result.passed is False


def test_consistency_boundary_is_inclusive():
    # 5 of 8 weeks winning = 62.5% >= 60%.
    winning = [(week, 1.0) for week in range(5)]
    losing = [(week, -0.5) for week in range(5, 8)]
    result = evaluate_d108("BOUNDARY", _trades(winning + losing))
    assert result.consistency.winning_week_fraction == pytest.approx(5 / 8)
    assert result.consistency.passed is True

    winning_fewer = [(week, 1.0) for week in range(4)]
    losing_more = [(week, -0.5) for week in range(4, 8)]
    result2 = evaluate_d108("BELOW_BOUNDARY", _trades(winning_fewer + losing_more))
    assert result2.consistency.winning_week_fraction == pytest.approx(0.5)
    assert result2.consistency.passed is False


def test_survivability_recoverable_drawdown_passes():
    # One bad week losing 3R, then 6 good weeks each winning 1R (drawdown of 3R
    # recoverable within 6 winning weeks at 1R/week -> weeks_to_recover == 6).
    rows = [(0, -3.0)] + [(week, 1.0) for week in range(1, 7)]
    result = evaluate_d108("RECOVERABLE", _trades(rows))
    assert result.survivability.worst_drawdown_r == pytest.approx(3.0)
    assert result.survivability.average_winning_week_r == pytest.approx(1.0)
    assert result.survivability.weeks_to_recover == pytest.approx(3.0)
    assert result.survivability.passed is True
    assert result.survivability.worst_losing_streak == 1


def test_survivability_unrecoverable_drawdown_fails():
    # A 20R drawdown against a typical 1R winning week needs 20 winning weeks,
    # far past the ~6 week bar.
    rows = [(0, -20.0)] + [(week, 1.0) for week in range(1, 3)]
    result = evaluate_d108("UNRECOVERABLE", _trades(rows))
    assert result.survivability.weeks_to_recover == pytest.approx(20.0)
    assert result.survivability.weeks_to_recover > DRAWDOWN_RECOVERY_WINNING_WEEKS
    assert result.survivability.passed is False


def test_survivability_with_no_winning_week_is_explicit_not_a_crash():
    rows = [(week, -1.0) for week in range(3)]
    result = evaluate_d108("ALL_LOSERS", _trades(rows))
    assert result.survivability.average_winning_week_r is None
    assert result.survivability.weeks_to_recover is None
    assert result.survivability.passed is False
    assert "no winning week" in result.survivability.reason


def test_no_drawdown_is_trivially_survivable():
    rows = [(week, 1.0) for week in range(3)]
    result = evaluate_d108("NO_DRAWDOWN", _trades(rows))
    assert result.survivability.worst_drawdown_r == 0.0
    assert result.survivability.weeks_to_recover == 0.0
    assert result.survivability.passed is True


def test_worst_losing_streak_is_reported_not_pass_fail():
    rows = [(0, 1.0), (0, -1.0), (0, -1.0), (0, -1.0), (0, 5.0)]
    result = evaluate_d108("STREAK", _trades(rows))
    assert result.survivability.worst_losing_streak == 3
    # A single week can never fail consistency's 60% bar on its own count
    # (one week, net positive), so this case isolates the streak figure.
    assert result.consistency.week_count == 1


def test_bootstrap_is_deterministic_across_repeated_calls():
    rows = []
    for week in range(8):
        for trade in range(5):
            rows.append((week, 0.6 if trade < 4 else -1.0))
    first = evaluate_d108("REPEAT", _trades(rows))
    second = evaluate_d108("REPEAT", _trades(rows))
    assert first.profit.primary.seed == second.profit.primary.seed
    assert first.profit.primary.seed_hash == second.profit.primary.seed_hash
    assert first.profit.primary.lower_bound == second.profit.primary.lower_bound
    for a, b in zip(first.profit.sensitivities, second.profit.sensitivities):
        assert a.lower_bound == b.lower_bound


def test_different_candidate_id_changes_the_seed():
    rows = [(week, 0.5) for week in range(8)]
    first = evaluate_d108("CANDIDATE_A", _trades(rows))
    second = evaluate_d108("CANDIDATE_B", _trades(rows))
    assert first.profit.primary.seed != second.profit.primary.seed


def test_profit_bootstrap_uses_configured_resample_and_block_settings():
    rows = [(week, 0.5) for week in range(8)]
    result = evaluate_d108("CONFIG", _trades(rows))
    assert result.profit.primary.resamples == RESAMPLES
    assert result.profit.primary.block_length == PRIMARY_BLOCK_LENGTH
    lengths = tuple(item.block_length for item in result.profit.sensitivities)
    assert lengths == tuple(SENSITIVITY_BLOCK_LENGTHS)


def test_review_required_when_sensitivity_flips_conclusion():
    # A marginal, small-n, high-variance sample where different block lengths
    # over-/under-represent the single losing week can flip the sign; assert
    # the module correctly reports whatever it computes rather than a fixed
    # expectation, and that review_required tracks passed disagreement.
    rows = [(0, 5.0), (1, -4.9), (2, 0.05), (3, 0.05), (4, 0.05), (5, 0.05)]
    result = evaluate_d108("MARGINAL", _trades(rows))
    disagreement = any(item.passed != result.profit.primary.passed
                       for item in result.profit.sensitivities)
    assert result.profit.review_required == disagreement
    if disagreement:
        assert result.profit.passed is False


def test_as_dict_round_trips_expected_shape():
    rows = [(week, 0.5) for week in range(8)]
    result = evaluate_d108("SHAPE", _trades(rows))
    payload = result.as_dict()
    assert payload["policy_version"] == POLICY_VERSION
    assert payload["candidate_id"] == "SHAPE"
    assert set(payload) == {
        "policy_version", "candidate_id", "trade_count", "profit", "consistency",
        "survivability", "passed",
    }
    assert set(payload["profit"]) == {
        "trade_count", "mean_r", "primary", "sensitivities", "review_required", "passed",
    }
    assert set(payload["survivability"]) == {
        "worst_drawdown_r", "average_winning_week_r", "weeks_to_recover", "passed", "reason",
        "worst_losing_streak",
    }


def test_lower_bound_quantile_constant_matches_ninety_five_percent_one_sided():
    assert LOWER_BOUND_Q == pytest.approx(0.05)


def test_winning_week_fraction_constant_matches_d108():
    assert WINNING_WEEK_FRACTION_REQUIRED == pytest.approx(0.60)
