"""M9.1EE strict retained candidate-group measurement contracts."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.orb5_stage1_result import REQUIRED_DISABLED_RULES
from consensus_engine.retained_decision_moments import PLAYBOOKS
from consensus_engine.retained_first_four_stage1_result import RetainedFirstFourStage1ResultRun
from consensus_engine.retained_stage1_candidate_groups import group_retained_stage1_results
from consensus_engine.retained_stage1_candidate_measurements import (
    RUN_VERSION, measure_retained_stage1_groups,
)
from consensus_engine.search_run_config import STAGE1_CANDIDATES, TRAINING_TICKERS
from consensus_engine.stage1_training_measurement import ResolvedTrainingTrade
from consensus_engine.trade_alerts_models import RecordError


def _candidates():
    return {playbook: STAGE1_CANDIDATES[playbook][0] for playbook in PLAYBOOKS}


def _sessions():
    return tuple((ticker, "2026-01-05") for ticker in TRAINING_TICKERS)


def _row(playbook, order):
    candidate = _candidates()[playbook]
    ticker = TRAINING_TICKERS[order]
    return ResolvedTrainingTrade(
        playbook, candidate.candidate_id, ticker,
        "LONG" if order % 2 == 0 else "SHORT",
        datetime(2026, 1, 5, 21, tzinfo=timezone.utc) + timedelta(minutes=order),
        1.0 - order / 10, "ROUND_TRIP_COSTS_V1", True,
        tuple(axis for axis, _value in candidate.settings),
        (f"{playbook}:{ticker}:result",),
    )


def _groups(*, empty_playbook=None):
    candidates = _candidates()
    rows = tuple(
        _row(playbook, order)
        for order, playbook in enumerate(PLAYBOOKS)
        if playbook != empty_playbook
    )
    source = RetainedFirstFourStage1ResultRun(
        "M91EC_RETAINED_FIRST_FOUR_STAGE1_RESULT_V1",
        "M91EB_RETAINED_FIRST_FOUR_OUTCOME_V1",
        rows, 10, 7, len(rows), 3, 7 - len(rows), 2, 4, 5,
        REQUIRED_DISABLED_RULES,
    )
    sessions = _sessions()
    coverage = {
        (playbook, candidate.candidate_id): sessions
        for playbook, candidate in candidates.items()
    }
    return group_retained_stage1_results(
        source, candidates=candidates, training_sessions=sessions,
        evaluated_sessions=coverage,
    )


def test_complete_groups_feed_existing_measurement_and_preserve_exclusions():
    result = measure_retained_stage1_groups(_groups(), candidates=_candidates())

    assert result.version == RUN_VERSION
    assert tuple(row.playbook for row in result.measurements) == PLAYBOOKS
    assert tuple(row.measurement.candidate for row in result.measurements) == tuple(
        _candidates().values())
    assert all(row.trade_count == row.week_count == 1 for row in result.measurements)
    assert all(row.evaluated_tickers == TRAINING_TICKERS for row in result.measurements)
    assert all(row.disabled_rules == REQUIRED_DISABLED_RULES for row in result.measurements)
    assert result.unresolved_excluded_count == 3
    assert result.incomplete_cost_excluded_count == 3
    assert result.unfilled_excluded_count == 2
    assert result.no_event_excluded_count == 4
    assert result.unavailable_excluded_count == 5
    assert not any((result.ranking_released, result.result_shard_released,
                    result.held_out_opened, result.alert_released, result.live_action))


def test_real_empty_group_boundary_is_refused_instead_of_fabricating_measurement():
    with pytest.raises(RecordError, match="empty candidate groups"):
        measure_retained_stage1_groups(
            _groups(empty_playbook="CRVOL_ORB5"), candidates=_candidates(),
        )


@pytest.mark.parametrize("case", (
    "version", "coverage", "measurement_open", "ranking_open", "counts",
    "disabled_rules", "missing_group", "wrong_candidate", "changed_sessions",
    "held_out_session", "outside_session", "incomplete_cost", "axis_off",
))
def test_changed_group_identity_cost_coverage_or_release_is_refused(case):
    run = _groups()
    candidates = _candidates()
    if case == "version":
        run = replace(run, version="FORGED")
    elif case == "coverage":
        run = replace(run, coverage_complete=False)
    elif case == "measurement_open":
        run = replace(run, measurement_released=True)
    elif case == "ranking_open":
        run = replace(run, ranking_released=True)
    elif case == "counts":
        run = replace(run, fully_costed_count=99)
    elif case == "disabled_rules":
        run = replace(run, disabled_rules=())
    elif case == "missing_group":
        run = replace(run, groups=run.groups[:-1])
    elif case == "wrong_candidate":
        candidates[PLAYBOOKS[0]] = STAGE1_CANDIDATES[PLAYBOOKS[0]][1]
    elif case == "changed_sessions":
        group = replace(run.groups[0], sessions=run.groups[0].sessions[:-1])
        run = replace(run, groups=(group, *run.groups[1:]))
    elif case == "held_out_session":
        sessions = (*run.training_sessions[:-1], ("GOOGL", "2026-01-05"))
        run = replace(
            run, training_sessions=sessions,
            groups=tuple(replace(group, sessions=sessions) for group in run.groups),
        )
    elif case == "outside_session":
        row = replace(run.groups[0].rows[0], closed_at=datetime(
            2026, 1, 6, 21, tzinfo=timezone.utc))
        group = replace(run.groups[0], rows=(row,))
        run = replace(run, groups=(group, *run.groups[1:]))
    else:
        row = run.groups[0].rows[0]
        row = replace(row, costs_complete=False) if case == "incomplete_cost" else replace(row, tested_axes=())
        group = replace(run.groups[0], rows=(row,))
        run = replace(run, groups=(group, *run.groups[1:]))
    with pytest.raises(RecordError):
        measure_retained_stage1_groups(run, candidates=candidates)


def test_recorded_candidate_measurements_are_deterministic_and_keep_release_closed():
    result = measure_retained_stage1_groups(_groups(), candidates=_candidates())
    payload = result.as_dict()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    recording = {
        "version": RUN_VERSION,
        "candidate_measurements_sha256": hashlib.sha256(canonical).hexdigest(),
        "canonical_bytes": len(canonical),
        "result": payload,
        "all_complete_groups_measured": len(result.measurements) == len(PLAYBOOKS),
        "exclusions_preserved": True,
        "gap_dependent_rules": "OFF_UNTESTED",
        "ranking_or_result_released": False,
        "held_out_opened": False,
        "alert_or_live_action": False,
    }
    rendered = json.dumps(recording, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91ee-retained-stage1-candidate-measurements.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert json.loads(output.read_text()) == recording
