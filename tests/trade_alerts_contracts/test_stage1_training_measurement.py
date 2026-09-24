"""M9.1CD contracts for the offline stage-1 training measurement path."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import math
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.search_run_config import (
    HELD_OUT_TICKERS, STAGE1_CANDIDATES, TRAINING_TICKERS, rank_training_candidates,
)
from consensus_engine.stage1_training_measurement import (
    POLICY_VERSION, ResolvedTrainingTrade, measure_stage1_candidate,
)
from consensus_engine.trade_alerts_models import RecordError


START = datetime(2026, 1, 5, 20, tzinfo=timezone.utc)
PLAYBOOK = "OR_FAILURE_REV"
CANDIDATES = STAGE1_CANDIDATES[PLAYBOOK]


def trade(candidate_id="CONFIRMED", *, ticker="NVDA", direction="LONG",
          days=0, resolved_r=1.0, costs_complete=True,
          tested_axes=("D-052",)):
    return ResolvedTrainingTrade(
        playbook=PLAYBOOK, candidate_id=candidate_id, ticker=ticker,
        direction=direction, closed_at=START + timedelta(days=days),
        resolved_r=resolved_r, cost_model_version="D106_D107_COSTS_V1",
        costs_complete=costs_complete, tested_axes=tested_axes,
        input_record_ids=(f"{ticker}-{days}-{direction}",),
    )


def measure(candidate=CANDIDATES[0], trades=None, **changes):
    values = dict(
        playbook=PLAYBOOK, candidate=candidate,
        trades=(trade(candidate.candidate_id),) if trades is None else trades,
        evaluated_tickers=TRAINING_TICKERS,
        disabled_rules=("ORIGINAL_AVAILABILITY_GAP", "POINT_IN_TIME_MEMBERSHIP_GAP"),
    )
    values.update(changes)
    return measure_stage1_candidate(**values)


def test_resolved_runner_rows_produce_the_frozen_training_measurement():
    result = measure(trades=(
        trade(days=0, resolved_r=1.0),
        trade(ticker="MSFT", days=7, resolved_r=-0.5),
        trade(ticker="AAPL", days=14, resolved_r=2.0),
    ))
    assert result.policy_version == POLICY_VERSION
    assert result.measurement.candidate == CANDIDATES[0]
    assert result.measurement.mean_profit_r == pytest.approx(2.5 / 3)
    assert result.measurement.weekly_win_rate == pytest.approx(2 / 3)
    assert result.measurement.drawdown_recovery_weeks == pytest.approx(0.5 / 1.5)
    assert result.trade_count == 3
    assert result.week_count == 3
    assert result.bootstrap_lower_bound == pytest.approx(result.bootstrap_lower_bound)
    assert result.evaluated_tickers == TRAINING_TICKERS
    assert result.disabled_rules == (
        "ORIGINAL_AVAILABILITY_GAP", "POINT_IN_TIME_MEMBERSHIP_GAP",
    )


def test_measurements_feed_the_existing_frozen_ranking_rule():
    confirmed = measure(trades=(trade(resolved_r=0.2),))
    faster_candidate = CANDIDATES[1]
    faster = measure(
        candidate=faster_candidate,
        trades=(trade("FASTER", resolved_r=0.4),),
    )
    winner = rank_training_candidates((confirmed.measurement, faster.measurement))
    assert winner.candidate == faster_candidate


@pytest.mark.parametrize("case", [
    "held_out_scope", "held_out_trade", "incomplete_cost", "axis_off",
    "candidate_drift", "duplicate_cluster", "empty",
])
def test_training_measurement_fails_closed(case):
    kwargs = {}
    if case == "held_out_scope":
        kwargs["evaluated_tickers"] = TRAINING_TICKERS[:-1] + (HELD_OUT_TICKERS[0],)
    elif case == "held_out_trade":
        kwargs["trades"] = (trade(ticker=HELD_OUT_TICKERS[0]),)
    elif case == "incomplete_cost":
        kwargs["trades"] = (trade(costs_complete=False),)
    elif case == "axis_off":
        kwargs["trades"] = (trade(tested_axes=()),)
    elif case == "candidate_drift":
        kwargs["candidate"] = replace(CANDIDATES[0], table_order=99)
    elif case == "duplicate_cluster":
        kwargs["trades"] = (trade(), trade(resolved_r=-1.0))
    elif case == "empty":
        kwargs["trades"] = ()
    with pytest.raises(RecordError):
        measure(**kwargs)


@pytest.mark.parametrize("playbook,candidate,disabled_axis", [
    (playbook, candidates[0], axis)
    for playbook, candidates in STAGE1_CANDIDATES.items()
    for axis, _value in candidates[0].settings
])
def test_disabled_candidate_axis_is_rejected_even_when_claimed_tested(
    playbook, candidate, disabled_axis,
):
    row = replace(
        trade(), playbook=playbook, candidate_id=candidate.candidate_id,
        tested_axes=tuple(axis for axis, _value in candidate.settings),
    )
    with pytest.raises(RecordError, match="a frozen candidate axis cannot be disabled"):
        measure(
            playbook=playbook, candidate=candidate, trades=(row,),
            disabled_rules=(disabled_axis,),
        )


def test_no_winning_week_is_ranked_as_unrecoverable_not_as_a_pass():
    result = measure(trades=(trade(resolved_r=-1.0),))
    assert math.isinf(result.measurement.drawdown_recovery_weeks)
