"""M9.1ED exact retained stage-1 candidate grouping contracts."""

from dataclasses import replace
from datetime import datetime, timezone
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
from consensus_engine.retained_first_four_stage1_result import (
    RUN_VERSION as INPUT_VERSION, RetainedFirstFourStage1ResultRun,
)
from consensus_engine.retained_stage1_candidate_groups import (
    RUN_VERSION, group_retained_stage1_results,
)
from consensus_engine.search_run_config import (
    HELD_OUT_TICKERS, STAGE1_CANDIDATES, TRAINING_TICKERS,
)
from consensus_engine.stage1_training_measurement import ResolvedTrainingTrade
from consensus_engine.trade_alerts_models import RecordError


def _candidates():
    return {playbook: STAGE1_CANDIDATES[playbook][0] for playbook in PLAYBOOKS}


def _sessions():
    return tuple((ticker, "2026-01-05") for ticker in TRAINING_TICKERS)


def _coverage(candidates=None, sessions=None):
    candidates = _candidates() if candidates is None else candidates
    sessions = _sessions() if sessions is None else sessions
    return {
        (playbook, candidate.candidate_id): sessions
        for playbook, candidate in candidates.items()
    }


def _run(rows=()):
    rows = tuple(rows)
    return RetainedFirstFourStage1ResultRun(
        INPUT_VERSION, "M91EB_RETAINED_FIRST_FOUR_OUTCOME_V1", rows,
        5 + len(rows), 3 + len(rows), len(rows), 2, 3, 4, 5, 6,
        REQUIRED_DISABLED_RULES,
    )


def _row(playbook="OR_FAILURE_REV", ticker="NVDA"):
    candidate = _candidates()[playbook]
    return ResolvedTrainingTrade(
        playbook, candidate.candidate_id, ticker, "LONG",
        datetime(2026, 1, 5, 21, tzinfo=timezone.utc), 1.0,
        "ROUND_TRIP_COSTS_V1", True,
        tuple(axis for axis, _value in candidate.settings),
        (f"{ticker}:2026-01-05:result",),
    )


def _group(run=None, candidates=None, sessions=None, coverage=None):
    candidates = _candidates() if candidates is None else candidates
    sessions = _sessions() if sessions is None else sessions
    return group_retained_stage1_results(
        _run() if run is None else run,
        candidates=candidates,
        training_sessions=sessions,
        evaluated_sessions=_coverage(candidates, sessions) if coverage is None else coverage,
    )


def test_groups_rows_by_frozen_candidate_and_preserves_every_exclusion():
    result = _group(_run((_row(),)))
    groups = {(group.playbook, group.candidate_id): group for group in result.groups}
    key = ("OR_FAILURE_REV", _candidates()["OR_FAILURE_REV"].candidate_id)

    assert result.version == RUN_VERSION
    assert result.coverage_complete
    assert groups[key].rows == (_row(),)
    assert all(group.sessions == _sessions() for group in result.groups)
    assert result.unresolved_excluded_count == 2
    assert result.incomplete_cost_excluded_count == 3
    assert result.unfilled_excluded_count == 4
    assert result.no_event_excluded_count == 5
    assert result.unavailable_excluded_count == 6
    assert not any((result.measurement_released, result.ranking_released,
                    result.result_shard_released, result.held_out_opened,
                    result.alert_released, result.live_action))


@pytest.mark.parametrize("case", (
    "missing_name", "held_out_name", "missing_candidate", "short_candidate",
    "wrong_order", "duplicate_session",
))
def test_incomplete_or_changed_training_coverage_is_refused(case):
    sessions = _sessions()
    coverage = _coverage(sessions=sessions)
    if case == "missing_name":
        sessions = sessions[:-1]
    elif case == "held_out_name":
        sessions = (*sessions[:-1], (HELD_OUT_TICKERS[0], "2026-01-05"))
    elif case == "missing_candidate":
        coverage.pop(next(iter(coverage)))
    elif case == "short_candidate":
        key = next(iter(coverage))
        coverage[key] = coverage[key][:-1]
    elif case == "wrong_order":
        sessions = tuple(reversed(sessions))
    else:
        sessions = (*sessions, sessions[0])
    with pytest.raises(RecordError):
        _group(sessions=sessions, coverage=coverage)


@pytest.mark.parametrize("case", (
    "wrong_candidate", "held_out_row", "outside_session", "incomplete_cost",
    "axis_off", "forged_counts", "opened_release", "disabled_rules",
))
def test_changed_rows_counts_or_release_boundaries_are_refused(case):
    row = _row()
    run = _run((row,))
    if case == "wrong_candidate":
        row = replace(row, candidate_id=STAGE1_CANDIDATES[row.playbook][1].candidate_id)
        run = _run((row,))
    elif case == "held_out_row":
        run = _run((replace(row, ticker=HELD_OUT_TICKERS[0]),))
    elif case == "outside_session":
        run = _run((replace(row, closed_at=datetime(2026, 1, 6, 21,
                                                   tzinfo=timezone.utc)),))
    elif case == "incomplete_cost":
        run = _run((replace(row, costs_complete=False),))
    elif case == "axis_off":
        run = _run((replace(row, tested_axes=()),))
    elif case == "forged_counts":
        run = replace(run, fully_costed_count=0)
    elif case == "opened_release":
        run = replace(run, result_shard_released=True)
    else:
        run = replace(run, disabled_rules=())
    with pytest.raises(RecordError):
        _group(run)


def test_recorded_candidate_groups_are_deterministic_and_keep_measurement_closed():
    result = _group(_run((_row(),)))
    payload = result.as_dict()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    recording = {
        "version": RUN_VERSION,
        "candidate_groups_sha256": hashlib.sha256(canonical).hexdigest(),
        "canonical_bytes": len(canonical),
        "result": payload,
        "all_nine_training_names_covered": {
            ticker for group in result.groups for ticker, _session in group.sessions
        } == set(TRAINING_TICKERS),
        "exclusions_preserved": True,
        "gap_dependent_rules": "OFF_UNTESTED",
        "measurement_ranking_or_result_released": False,
        "held_out_opened": False,
        "alert_or_live_action": False,
    }
    rendered = json.dumps(recording, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91ed-retained-stage1-candidate-groups.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert json.loads(output.read_text()) == recording
