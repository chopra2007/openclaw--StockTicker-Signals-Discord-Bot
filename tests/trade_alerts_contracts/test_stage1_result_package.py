"""M9.1CW contracts for the durable first-four stage-1 result package."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

import consensus_engine.first_pullback_stage1_comparison as pullback_comparison
import consensus_engine.hod_comp_rs_stage1_comparison as hod_comparison
import consensus_engine.or_failure_stage1_comparison as failure_comparison
import consensus_engine.orb5_stage1_result as orb5_result
import consensus_engine.stage1_result_package as subject
from consensus_engine.first_pullback_vwap_stage1_run import FirstPullbackStage1Run
from consensus_engine.hod_comp_rs_stage1_run import HodCompRsStage1Run
from consensus_engine.or_failure_stage1_run import OrFailureStage1Run
from consensus_engine.search_run_config import PLAYBOOKS, STAGE1_CANDIDATES, TRAINING_TICKERS
from consensus_engine.stage1_training_measurement import (
    POLICY_VERSION, ResolvedTrainingTrade, Stage1TrainingMeasurement,
)
from consensus_engine.stage2_training_comparison import AcceptedStage1Winner, Stage2TrainingEvent
from consensus_engine.trade_alerts_models import RecordError


START = datetime(2026, 1, 5, 15, tzinfo=timezone.utc)
SESSIONS = tuple((ticker, "2026-01-05") for ticker in TRAINING_TICKERS)
DISABLED = ("ORIGINAL_AVAILABILITY_GAP", "CORRECTIONS_FINALITY_GAP",
            "POINT_IN_TIME_MEMBERSHIP_GAP")


def _trade(playbook, candidate, order):
    return ResolvedTrainingTrade(
        playbook, candidate.candidate_id, TRAINING_TICKERS[order % len(TRAINING_TICKERS)],
        "LONG", START + timedelta(minutes=5 + order), float(20 - order),
        "D106_D107_COSTS_V1", True,
        tuple(name for name, _value in candidate.settings),
        (f"source:{playbook}:{candidate.candidate_id}",),
    )


def _measurement(playbook, candidate, order):
    from consensus_engine.search_run_config import TrainingMeasurement
    return Stage1TrainingMeasurement(
        POLICY_VERSION, playbook,
        TrainingMeasurement(candidate, float(20 - order), .75, float(order + 1)),
        -.25, 1, 1, TRAINING_TICKERS, DISABLED,
    )


def _orb5():
    candidates = STAGE1_CANDIDATES["CRVOL_ORB5"]
    runs = []
    for order, candidate in enumerate(candidates):
        trade = _trade("CRVOL_ORB5", candidate, order)
        event = orb5_result.Orb5Stage1Event("2026-01-05", START, trade)
        runs.append(orb5_result.run_orb5_candidate_stage1(
            candidate=candidate, events=(event,), evaluated_sessions=SESSIONS,
            disabled_rules=DISABLED, exclusions=(f"excluded:{order}",),
        ))
    comparison = orb5_result.compare_orb5_stage1(runs)
    return comparison, comparison.accepted_winner


def _comparison(playbook, module, run_type):
    candidates = STAGE1_CANDIDATES[playbook]
    runs = []
    for order, candidate in enumerate(candidates):
        runs.append(run_type(
            version=module._RUN_VERSIONS[candidate.candidate_id],
            candidate_id=candidate.candidate_id,
            measurement=_measurement(playbook, candidate, order),
            resolved=(_trade(playbook, candidate, order),),
            excluded=(f"excluded:{playbook}:{order}",),
            evaluated_sessions=SESSIONS,
        ))
    compare = {
        "HOD_COMP_RS": hod_comparison.compare_hod_comp_rs_stage1,
        "OR_FAILURE_REV": failure_comparison.compare_or_failure_stage1,
        "FIRST_PULLBACK_VWAP": pullback_comparison.compare_first_pullback_stage1,
    }[playbook]
    comparison = compare(runs)
    winner_run = next(run for run in comparison.runs
                      if run.candidate_id == comparison.winner.measurement.candidate.candidate_id)
    winner = AcceptedStage1Winner(
        playbook, comparison.winner,
        tuple(run.measurement for run in comparison.runs),
        (Stage2TrainingEvent(winner_run.resolved[0], START),),
    )
    return comparison, winner


def _inputs():
    pairs = (
        _orb5(),
        _comparison("HOD_COMP_RS", hod_comparison, HodCompRsStage1Run),
        _comparison("OR_FAILURE_REV", failure_comparison, OrFailureStage1Run),
        _comparison("FIRST_PULLBACK_VWAP", pullback_comparison, FirstPullbackStage1Run),
    )
    return tuple(pair[0] for pair in pairs), tuple(pair[1] for pair in pairs)


def test_package_preserves_all_comparisons_measurements_events_and_sources():
    comparisons, winners = _inputs()
    package = subject.build_stage1_result_package(comparisons, winners)
    record = package.as_dict()

    assert record["package_version"] == subject.PACKAGE_VERSION
    assert tuple(row["playbook"] for row in record["playbooks"]) == PLAYBOOKS
    assert tuple(len(row["candidates"]) for row in record["playbooks"]) == (18, 4, 2, 4)
    for row, comparison, winner in zip(record["playbooks"], comparisons, winners):
        assert row["comparison_version"] == comparison.version
        assert row["winner_candidate_id"] == winner.measurement.measurement.candidate.candidate_id
        coverage = row["candidates"][0]["retained_session_coverage"]
        assert coverage == [list(x) for x in comparison.runs[0].evaluated_sessions]
        assert {tuple(x) for x in coverage} == set(SESSIONS)
        assert row["candidates"][0]["measurement"]["disabled_rules"] == list(DISABLED)
        assert row["candidates"][0]["exclusions"]
        assert row["resolved_alert_time_events"][0]["alerted_at"] == "2026-01-05T15:00:00Z"
        assert row["source_record_identities"]
    assert len(record["source_record_identities"]) == 4


@pytest.mark.parametrize("case", ("not_ranked", "wrong_events", "wrong_order", "short"))
def test_package_refuses_incomplete_or_mismatched_accepted_inputs(case):
    comparisons, winners = _inputs()
    comparisons, winners = list(comparisons), list(winners)
    if case == "not_ranked":
        comparisons[1] = replace(comparisons[1], status="NOT_RANKABLE")
    elif case == "wrong_events":
        wrong = comparisons[1].runs[1].resolved[0]
        winners[1] = replace(winners[1], events=(Stage2TrainingEvent(wrong, START),))
    elif case == "wrong_order":
        comparisons[0], comparisons[1] = comparisons[1], comparisons[0]
    else:
        comparisons.pop()
    with pytest.raises(RecordError):
        subject.build_stage1_result_package(comparisons, winners)


def test_reopen_rejects_tampering_and_immutable_path_conflicts(tmp_path):
    package = subject.build_stage1_result_package(*_inputs())
    path = tmp_path / "stage1.json"
    subject.write_stage1_result_package(path, package)
    wrapper = json.loads(path.read_text())
    wrapper["record"]["playbooks"][0]["comparison_status"] = "FORGED"
    path.write_text(json.dumps(wrapper))
    with pytest.raises(RecordError):
        subject.read_stage1_result_package(path)
    with pytest.raises(RecordError, match="immutable"):
        subject.write_stage1_result_package(path, package)


def test_recorded_package_proof_is_deterministic_and_reopen_equal(tmp_path):
    package = subject.build_stage1_result_package(*_inputs())
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    subject.write_stage1_result_package(first, package)
    subject.write_stage1_result_package(second, package)
    reopened = subject.read_stage1_result_package(first)

    assert first.read_bytes() == second.read_bytes()
    assert reopened == package
    proof = Path(os.environ["TMPDIR"], "m91cw-stage1-result-package-proof.json")
    proof.write_bytes(first.read_bytes())
    assert subject.read_stage1_result_package(proof) == package
