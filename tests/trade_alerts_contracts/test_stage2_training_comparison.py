"""M9.1CT contracts for the frozen five-candidate stage-2 boundary."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

import consensus_engine.stage2_training_comparison as subject
from consensus_engine.search_run_config import (
    HELD_OUT_TICKERS, PLAYBOOKS, STAGE1_CANDIDATES, STAGE2_CANDIDATES,
    TRAINING_TICKERS, TrainingMeasurement,
)
from consensus_engine.stage1_training_measurement import (
    POLICY_VERSION, ResolvedTrainingTrade, Stage1TrainingMeasurement,
)
from consensus_engine.trade_alerts_models import RecordError


START = datetime(2026, 1, 5, 15, tzinfo=timezone.utc)


def accepted(playbook, order, *, ticker=None, direction="LONG", alert_offset=0,
             close_offset=60, resolved_r=None, disabled=("ORIGINAL_AVAILABILITY_GAP",)):
    candidate = STAGE1_CANDIDATES[playbook][0]
    ranking = TrainingMeasurement(candidate, 1.0, 1.0, 0.0)
    measurement = Stage1TrainingMeasurement(
        POLICY_VERSION, playbook, ranking, 0.1, 1, 1, TRAINING_TICKERS, disabled)
    candidate_measurements = (measurement,) + tuple(
        Stage1TrainingMeasurement(
            POLICY_VERSION, playbook,
            TrainingMeasurement(other, 0.0, 0.0, 1.0),
            -0.1, 1, 1, TRAINING_TICKERS, disabled,
        )
        for other in STAGE1_CANDIDATES[playbook][1:]
    )
    ticker = ticker or TRAINING_TICKERS[order]
    trade = ResolvedTrainingTrade(
        playbook, candidate.candidate_id, ticker, direction,
        START + timedelta(seconds=close_offset),
        float(order + 1 if resolved_r is None else resolved_r), "D106_D107_COSTS_V1",
        True, tuple(name for name, _value in candidate.settings),
        (f"{playbook}:{ticker}:{direction}:{order}",),
    )
    event = subject.Stage2TrainingEvent(trade, START + timedelta(seconds=alert_offset))
    return subject.AcceptedStage1Winner(
        playbook, measurement, candidate_measurements, (event,))


def winners(**changes):
    rows = [accepted(playbook, order) for order, playbook in enumerate(PLAYBOOKS)]
    for order, replacement in changes.items():
        rows[int(order)] = replacement
    return tuple(rows)


def test_four_winners_build_and_rank_the_five_frozen_candidates():
    result = subject.compare_stage2_training(tuple(reversed(winners())))

    assert result.version == subject.COMPARISON_VERSION
    assert result.status == "RANKED" and not result.blockers
    assert tuple(row.playbook for row in result.winners) == PLAYBOOKS
    assert tuple(row.candidate for row in result.measured) == STAGE2_CANDIDATES
    assert result.winner.candidate.candidate_id == "SOLO_PULLBACK"
    assert result.winner.measurement.mean_profit_r == 4.0


def test_all_four_clusters_to_the_earliest_alert_without_reading_returns():
    rows = list(winners())
    rows[0] = accepted(PLAYBOOKS[0], 0, ticker="NVDA", alert_offset=20, resolved_r=99.0)
    rows[1] = accepted(PLAYBOOKS[1], 1, ticker="NVDA", alert_offset=10, resolved_r=-2.0)

    result = subject.compare_stage2_training(rows)
    combined = result.measured[-1]

    assert combined.candidate.candidate_id == "ALL_FOUR"
    assert combined.trade_count == 3
    # The other tickers alert first; NVDA's winning event is last in time order.
    assert combined.events == (
        rows[2].events[0], rows[3].events[0], rows[1].events[0],
    )
    assert combined.measurement.mean_profit_r == pytest.approx((-2.0 + 3.0 + 4.0) / 3)


def test_equal_alert_time_uses_frozen_playbook_order():
    rows = list(winners())
    rows[0] = accepted(PLAYBOOKS[0], 0, ticker="NVDA", resolved_r=-1.0)
    rows[1] = accepted(PLAYBOOKS[1], 1, ticker="NVDA", resolved_r=50.0)

    combined = subject.compare_stage2_training(rows).measured[-1]

    # Frozen playbook order breaks ties within NVDA's cluster, not across tickers.
    nvda_events = tuple(event for event in combined.events if event.trade.ticker == "NVDA")
    assert nvda_events == rows[0].events
    assert nvda_events[0].trade.resolved_r == -1.0


def test_disabled_rule_labels_are_preserved_per_included_playbook():
    rows = list(winners())
    rows[2] = accepted(PLAYBOOKS[2], 2, disabled=("POINT_IN_TIME_MEMBERSHIP_GAP",))

    result = subject.compare_stage2_training(rows)

    assert result.measured[2].disabled_rules_by_playbook == (
        (PLAYBOOKS[2], ("POINT_IN_TIME_MEMBERSHIP_GAP",)),
    )
    assert result.measured[-1].disabled_rules_by_playbook[2] == (
        PLAYBOOKS[2], ("POINT_IN_TIME_MEMBERSHIP_GAP",),
    )


@pytest.mark.parametrize("case", (
    "missing", "duplicate", "wrong_playbook", "catalog_drift", "scope",
    "held_out", "incomplete_cost", "event_candidate", "empty_events",
    "duplicate_cluster", "late_alert", "not_winner", "incomplete_grid",
    "disabled_drift",
))
def test_invalid_or_incomplete_winner_inputs_fail_closed(case):
    rows = list(winners())
    if case == "missing":
        rows.pop()
    elif case == "duplicate":
        rows[3] = rows[0]
    elif case == "wrong_playbook":
        rows[0] = replace(rows[0], playbook=PLAYBOOKS[1])
    elif case == "catalog_drift":
        drifted = replace(rows[0].measurement.measurement.candidate, table_order=99)
        rows[0] = replace(rows[0], measurement=replace(
            rows[0].measurement,
            measurement=replace(rows[0].measurement.measurement, candidate=drifted),
        ))
    elif case == "scope":
        rows[0] = replace(rows[0], measurement=replace(
            rows[0].measurement,
            evaluated_tickers=TRAINING_TICKERS[:-1] + (HELD_OUT_TICKERS[0],),
        ))
    elif case == "held_out":
        rows[0] = accepted(PLAYBOOKS[0], 0, ticker=HELD_OUT_TICKERS[0])
    elif case == "incomplete_cost":
        event = rows[0].events[0]
        rows[0] = replace(rows[0], events=(replace(
            event, trade=replace(event.trade, costs_complete=False)),))
    elif case == "event_candidate":
        event = rows[0].events[0]
        rows[0] = replace(rows[0], events=(replace(
            event, trade=replace(event.trade, candidate_id="FORGED")),))
    elif case == "empty_events":
        rows[0] = replace(rows[0], events=())
    elif case == "duplicate_cluster":
        rows[0] = replace(rows[0], events=(rows[0].events[0], rows[0].events[0]))
    elif case == "not_winner":
        losing = rows[0].candidate_measurements[1]
        rows[0] = replace(rows[0], measurement=losing)
    elif case == "incomplete_grid":
        rows[0] = replace(rows[0], candidate_measurements=rows[0].candidate_measurements[:-1])
    elif case == "disabled_drift":
        candidate_rows = list(rows[0].candidate_measurements)
        candidate_rows[-1] = replace(
            candidate_rows[-1], disabled_rules=("POINT_IN_TIME_MEMBERSHIP_GAP",))
        rows[0] = replace(rows[0], candidate_measurements=tuple(candidate_rows))
    else:
        event = rows[0].events[0]
        with pytest.raises(RecordError, match="alert time cannot be after"):
            replace(event, alerted_at=event.trade.closed_at + timedelta(seconds=1))
        return
    with pytest.raises(RecordError):
        subject.compare_stage2_training(rows)


def test_stage2_does_not_mutate_or_open_held_out_results():
    result = subject.compare_stage2_training(winners())
    assert all(
        event.trade.ticker in TRAINING_TICKERS
        for row in result.measured for event in row.events
    )
    assert set(HELD_OUT_TICKERS).isdisjoint(
        event.trade.ticker for row in result.measured for event in row.events
    )
