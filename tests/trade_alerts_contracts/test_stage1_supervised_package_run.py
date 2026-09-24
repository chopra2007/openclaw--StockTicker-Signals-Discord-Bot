"""M9.1CX contracts for the bounded supervised stage-1 package connection."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
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
import consensus_engine.stage1_supervised_package_run as subject
from consensus_engine.first_pullback_vwap_stage1_run import FirstPullbackStage1Run
from consensus_engine.hod_comp_rs_stage1_run import HodCompRsStage1Run
from consensus_engine.or_failure_stage1_run import OrFailureStage1Run
from consensus_engine.search_run_config import (
    HELD_OUT_TICKERS, PLAYBOOKS, STAGE1_CANDIDATES, TRAINING_TICKERS,
)
from consensus_engine.stage1_training_measurement import (
    POLICY_VERSION, ResolvedTrainingTrade, Stage1TrainingMeasurement,
)
from consensus_engine.stage2_training_comparison import Stage2TrainingEvent
from consensus_engine.trade_alerts_models import RecordError


START = datetime(2026, 1, 5, 15, tzinfo=timezone.utc)
SESSIONS = tuple((ticker, "2026-01-05") for ticker in TRAINING_TICKERS)
DISABLED = orb5_result.REQUIRED_DISABLED_RULES


def _trade(playbook, candidate, order):
    return ResolvedTrainingTrade(
        playbook, candidate.candidate_id,
        TRAINING_TICKERS[order % len(TRAINING_TICKERS)], "LONG",
        START + timedelta(minutes=order + 1), float(30 - order),
        "D106_D107_COSTS_V1", True,
        tuple(name for name, _value in candidate.settings),
        (f"source:{playbook}:{candidate.candidate_id}",),
    )


def _measurement(playbook, candidate, order):
    from consensus_engine.search_run_config import TrainingMeasurement
    return Stage1TrainingMeasurement(
        POLICY_VERSION, playbook,
        TrainingMeasurement(candidate, float(30 - order), .75, float(order + 1)),
        -.25, 1, 1, TRAINING_TICKERS, DISABLED,
    )


def _inputs():
    orb5_runs = []
    for order, candidate in enumerate(STAGE1_CANDIDATES[PLAYBOOKS[0]]):
        event = orb5_result.Orb5Stage1Event(
            "2026-01-05", START, _trade(PLAYBOOKS[0], candidate, order))
        orb5_runs.append(orb5_result.run_orb5_candidate_stage1(
            candidate=candidate, events=(event,), evaluated_sessions=SESSIONS,
            disabled_rules=DISABLED,
        ))

    specs = (
        (PLAYBOOKS[1], hod_comparison, HodCompRsStage1Run),
        (PLAYBOOKS[2], failure_comparison, OrFailureStage1Run),
        (PLAYBOOKS[3], pullback_comparison, FirstPullbackStage1Run),
    )
    all_runs = []
    event_rows = {}
    for playbook, module, run_type in specs:
        runs = []
        for order, candidate in enumerate(STAGE1_CANDIDATES[playbook]):
            runs.append(run_type(
                module._RUN_VERSIONS[candidate.candidate_id], candidate.candidate_id,
                _measurement(playbook, candidate, order),
                (_trade(playbook, candidate, order),), (), SESSIONS,
            ))
        all_runs.append(tuple(runs))
        event_rows[playbook] = (Stage2TrainingEvent(runs[0].resolved[0], START),)
    return tuple(orb5_runs), tuple(all_runs), event_rows


def _run(path, *, change=None):
    orb5_runs, runs, events = _inputs()
    if change:
        orb5_runs, runs, events = change(orb5_runs, runs, events)
    return subject.run_supervised_stage1_package(
        output_path=path, orb5_runs=orb5_runs,
        hod_comp_rs_runs=runs[0], or_failure_runs=runs[1],
        first_pullback_runs=runs[2], winner_events=events,
    )


def test_connection_writes_complete_reopenable_training_only_package(tmp_path):
    path = tmp_path / "stage1.json"
    package = _run(path)
    record = package.as_dict()

    assert path.exists()
    assert tuple(row["playbook"] for row in record["playbooks"]) == PLAYBOOKS
    assert tuple(len(row["candidates"]) for row in record["playbooks"]) == (18, 4, 2, 4)
    assert all(
        set(DISABLED).issubset(candidate["measurement"]["disabled_rules"])
        for row in record["playbooks"] for candidate in row["candidates"]
    )
    assert all("source:" in identity for identity in record["source_record_identities"])


@pytest.mark.parametrize("case", ("missing_events", "wrong_trade", "missing_gap", "held_out"))
def test_connection_refuses_unaccepted_or_out_of_scope_inputs(tmp_path, case):
    def change(orb5_runs, runs, events):
        if case == "missing_events":
            events.pop(PLAYBOOKS[2])
        elif case == "wrong_trade":
            event = events[PLAYBOOKS[1]][0]
            events[PLAYBOOKS[1]] = (replace(
                event, trade=replace(event.trade, resolved_r=-999.0)),)
        elif case == "missing_gap":
            rows = list(runs[0])
            rows[0] = replace(rows[0], measurement=replace(
                rows[0].measurement, disabled_rules=DISABLED[:-1]))
            runs = (tuple(rows), runs[1], runs[2])
        else:
            rows = list(runs[0])
            held_out = replace(rows[0].resolved[0], ticker=HELD_OUT_TICKERS[0])
            rows[0] = replace(rows[0], resolved=(held_out,))
            runs = (tuple(rows), runs[1], runs[2])
            event = events[PLAYBOOKS[1]][0]
            events[PLAYBOOKS[1]] = (replace(event, trade=held_out),)
        return orb5_runs, runs, events

    with pytest.raises(RecordError):
        _run(tmp_path / "stage1.json", change=change)


def test_recorded_supervised_package_is_deterministic_and_reopenable(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first_package = _run(first)
    second_package = _run(second)

    assert first.read_bytes() == second.read_bytes()
    assert first_package == second_package
    proof = Path(os.environ["TMPDIR"], "m91cx-supervised-stage1-package-proof.json")
    proof.write_bytes(first.read_bytes())
    assert proof.read_bytes() == second.read_bytes()
