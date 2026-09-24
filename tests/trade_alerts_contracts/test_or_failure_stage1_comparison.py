"""M9.1CP contracts for the two-candidate OR-failure comparison."""

from dataclasses import replace
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

import consensus_engine.or_failure_stage1_comparison as subject
from consensus_engine.or_failure_stage1_run import OrFailureStage1Run
from consensus_engine.search_run_config import STAGE1_CANDIDATES, TRAINING_TICKERS, TrainingMeasurement
from consensus_engine.stage1_training_measurement import (
    POLICY_VERSION, Stage1TrainingMeasurement,
)
from consensus_engine.trade_alerts_models import RecordError


CANDIDATES = STAGE1_CANDIDATES[subject.PLAYBOOK]
SESSIONS = tuple((ticker, "2026-01-05") for ticker in TRAINING_TICKERS)
VERSIONS = tuple(subject._RUN_VERSIONS[row.candidate_id] for row in CANDIDATES)


def measurement(order, *, mean=None, win=0.5, recovery=1.0,
                disabled=("ORIGINAL_AVAILABILITY_GAP",)):
    candidate = CANDIDATES[order]
    ranking = TrainingMeasurement(
        candidate, float(2 - order if mean is None else mean), win, recovery)
    return Stage1TrainingMeasurement(
        POLICY_VERSION, subject.PLAYBOOK, ranking, -0.5, 3, 3,
        TRAINING_TICKERS, disabled)


def run(order, **changes):
    values = dict(
        version=VERSIONS[order], candidate_id=CANDIDATES[order].candidate_id,
        measurement=measurement(order), resolved=(),
        excluded=(f"excluded-{order}",), evaluated_sessions=SESSIONS,
    )
    values.update(changes)
    return OrFailureStage1Run(**values)


def test_two_accepted_runs_are_ranked_by_the_frozen_rule_in_catalog_order():
    result = subject.compare_or_failure_stage1((run(1), run(0)))

    assert result.version == subject.COMPARISON_VERSION
    assert result.status == "RANKED" and not result.blockers
    assert tuple(row.candidate_id for row in result.runs) == tuple(
        row.candidate_id for row in CANDIDATES)
    assert tuple(row.measurement.candidate.table_order for row in result.ranked) == (0, 1)
    assert result.winner == result.ranked[0]
    assert tuple(row.excluded for row in result.runs) == (
        ("excluded-0",), ("excluded-1",))


def test_all_frozen_ties_end_with_the_preregistered_candidate_order():
    tied = tuple(run(order, measurement=measurement(
        order, mean=1.0, win=0.5, recovery=2.0)) for order in range(2))

    result = subject.compare_or_failure_stage1(tied)

    assert tuple(row.measurement.candidate.table_order for row in result.ranked) == (0, 1)
    assert result.winner.measurement.candidate == CANDIDATES[0]


@pytest.mark.parametrize("case", ("missing_measurement", "coverage", "disabled_rules"))
def test_missing_or_incomparable_inputs_stay_visible_and_do_not_choose_a_winner(case):
    runs = [run(order) for order in range(2)]
    if case == "missing_measurement":
        runs[1] = replace(runs[1], measurement=None)
        expected = f"{CANDIDATES[1].candidate_id}:MEASUREMENT_UNAVAILABLE"
    elif case == "coverage":
        runs[1] = replace(runs[1], evaluated_sessions=SESSIONS[:-1])
        expected = f"{CANDIDATES[1].candidate_id}:EVALUATED_SESSION_COVERAGE_MISMATCH"
    else:
        runs[1] = replace(runs[1], measurement=measurement(
            1, disabled=("POINT_IN_TIME_MEMBERSHIP_GAP",)))
        expected = f"{CANDIDATES[1].candidate_id}:DISABLED_RULE_LABELS_MISMATCH"

    result = subject.compare_or_failure_stage1(runs)

    assert result.status == "NOT_RANKABLE"
    assert result.winner is None and not result.ranked
    assert expected in result.blockers
    assert tuple(row.excluded for row in result.runs) == (
        ("excluded-0",), ("excluded-1",))


@pytest.mark.parametrize("case", (
    "short", "duplicate", "unknown", "wrong_version", "measurement_drift",
))
def test_comparison_refuses_incomplete_or_forged_runner_identity(case):
    runs = [run(order) for order in range(2)]
    if case == "short":
        runs.pop()
    elif case == "duplicate":
        runs[1] = runs[0]
    elif case == "unknown":
        runs[1] = replace(runs[1], candidate_id="NOT_FROZEN")
    elif case == "wrong_version":
        runs[1] = replace(runs[1], version="FORGED")
    else:
        runs[1] = replace(runs[1], measurement=measurement(0))
    with pytest.raises(RecordError):
        subject.compare_or_failure_stage1(runs)
