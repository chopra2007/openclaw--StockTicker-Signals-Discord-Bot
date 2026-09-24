"""M9.1EF complete retained stage-1 measurement catalog contracts."""

from collections import OrderedDict
from dataclasses import replace
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.orb5_stage1_result import REQUIRED_DISABLED_RULES
from consensus_engine.retained_decision_moments import PLAYBOOKS
from consensus_engine.retained_stage1_candidate_measurements import (
    RUN_VERSION as INPUT_VERSION,
    RetainedStage1CandidateMeasurementRun,
)
from consensus_engine.retained_stage1_measurement_catalog import (
    RUN_VERSION, assemble_retained_stage1_measurement_catalog,
)
from consensus_engine.search_run_config import (
    STAGE1_CANDIDATES, STAGE1_GRID_SIZES, TRAINING_TICKERS, TrainingMeasurement,
)
from consensus_engine.stage1_training_measurement import (
    POLICY_VERSION, ResolvedTrainingTrade, Stage1TrainingMeasurement,
    measure_stage1_candidate,
)
from consensus_engine.trade_alerts_models import RecordError


def _sessions(day="2026-01-05"):
    return tuple((ticker, day) for ticker in TRAINING_TICKERS)


def _measurement(playbook, candidate, order):
    return Stage1TrainingMeasurement(
        POLICY_VERSION, playbook,
        TrainingMeasurement(candidate, float(40 - order), .75, float(order + 1)),
        -.25, 1, 1, TRAINING_TICKERS, REQUIRED_DISABLED_RULES,
    )


def _run(selected_playbook, selected_candidate, *, sessions=None):
    measurements = []
    for playbook_order, playbook in enumerate(PLAYBOOKS):
        candidate = (selected_candidate if playbook == selected_playbook
                     else STAGE1_CANDIDATES[playbook][0])
        measurements.append(_measurement(playbook, candidate, playbook_order))
    return RetainedStage1CandidateMeasurementRun(
        INPUT_VERSION, "M91ED_RETAINED_STAGE1_CANDIDATE_GROUPS_V1",
        POLICY_VERSION, tuple(measurements),
        _sessions() if sessions is None else sessions,
        9, 7, 4, 2, 3, 5, 6, 7, REQUIRED_DISABLED_RULES,
    )


def _runs():
    return OrderedDict(
        ((playbook, candidate.candidate_id), _run(playbook, candidate))
        for playbook in PLAYBOOKS
        for candidate in STAGE1_CANDIDATES[playbook]
    )


def test_full_catalog_preserves_frozen_order_coverage_exclusions_and_off_rules():
    result = assemble_retained_stage1_measurement_catalog(_runs())

    assert result.version == RUN_VERSION
    assert tuple(row.playbook for row in result.playbooks) == PLAYBOOKS
    assert tuple(len(row.entries) for row in result.playbooks) == (18, 4, 2, 4)
    for row in result.playbooks:
        assert tuple(entry.candidate_id for entry in row.entries) == tuple(
            candidate.candidate_id for candidate in STAGE1_CANDIDATES[row.playbook])
        assert all(entry.measurement.evaluated_tickers == TRAINING_TICKERS
                   for entry in row.entries)
        assert all(entry.unresolved_excluded_count == 2 for entry in row.entries)
        assert all(entry.incomplete_cost_excluded_count == 3 for entry in row.entries)
        assert all(entry.unfilled_excluded_count == 5 for entry in row.entries)
        assert all(entry.no_event_excluded_count == 6 for entry in row.entries)
        assert all(entry.unavailable_excluded_count == 7 for entry in row.entries)
    assert result.catalog_complete
    assert result.disabled_rules == REQUIRED_DISABLED_RULES
    assert not any((result.ranking_released, result.result_shard_released,
                    result.held_out_opened, result.alert_released, result.live_action))


@pytest.mark.parametrize("case", (
    "missing", "extra", "wrong_order", "wrong_version", "wrong_group_version",
    "changed_coverage", "held_out", "ranking_open", "counts", "disabled_rules",
    "missing_measurement", "wrong_candidate", "wrong_tickers",
))
def test_incomplete_changed_or_open_catalog_inputs_are_refused(case):
    runs = _runs()
    key = next(iter(runs))
    run = runs[key]
    if case == "missing":
        runs.pop(key)
    elif case == "extra":
        runs[("EXTRA", "EXTRA")] = run
    elif case == "wrong_order":
        runs.move_to_end(key)
    elif case == "wrong_version":
        runs[key] = replace(run, version="FORGED")
    elif case == "wrong_group_version":
        runs[key] = replace(run, group_version="FORGED")
    elif case == "changed_coverage":
        runs[key] = replace(run, training_sessions=_sessions("2026-01-06"))
    elif case == "held_out":
        sessions = (*run.training_sessions[:-1], ("GOOGL", "2026-01-05"))
        runs[key] = replace(run, training_sessions=sessions)
    elif case == "ranking_open":
        runs[key] = replace(run, ranking_released=True)
    elif case == "counts":
        runs[key] = replace(run, fully_costed_count=3)
    elif case == "disabled_rules":
        runs[key] = replace(run, disabled_rules=())
    elif case == "missing_measurement":
        runs[key] = replace(run, measurements=run.measurements[:-1])
    elif case == "wrong_candidate":
        rows = list(run.measurements)
        rows[0] = replace(rows[0], measurement=replace(
            rows[0].measurement, candidate=STAGE1_CANDIDATES[PLAYBOOKS[0]][1]))
        runs[key] = replace(run, measurements=tuple(rows))
    else:
        rows = list(run.measurements)
        rows[0] = replace(rows[0], evaluated_tickers=TRAINING_TICKERS[:-1])
        runs[key] = replace(run, measurements=tuple(rows))
    with pytest.raises(RecordError):
        assemble_retained_stage1_measurement_catalog(runs)


@pytest.mark.parametrize("container", (None, [], {}, "measurements"))
def test_invalid_measurement_container_is_refused(container):
    runs = _runs()
    key = next(iter(runs))
    runs[key] = replace(runs[key], measurements=container)
    with pytest.raises(RecordError):
        assemble_retained_stage1_measurement_catalog(runs)


@pytest.mark.parametrize("row_index", range(len(PLAYBOOKS)))
@pytest.mark.parametrize("case", (
    "missing_row", "mapping_row", "missing_nested", "mapping_nested",
    "missing_candidate", "mapping_candidate", "bool_trade_count",
    "string_trade_count", "bool_week_count", "too_many_weeks",
))
def test_malformed_measurement_rows_are_refused_before_field_access_or_sum(row_index, case):
    runs = _runs()
    key = next(iter(runs))
    run = runs[key]
    rows = list(run.measurements)
    row = rows[row_index]
    if case == "missing_row":
        row = None
    elif case == "mapping_row":
        row = {"playbook": row.playbook}
    elif case in ("missing_nested", "mapping_nested"):
        row = replace(row, measurement=None if case == "missing_nested" else {})
    elif case in ("missing_candidate", "mapping_candidate"):
        row = replace(row, measurement=replace(
            row.measurement, candidate=None if case == "missing_candidate" else {}))
    elif case == "bool_trade_count":
        row = replace(row, trade_count=True)
    elif case == "string_trade_count":
        row = replace(row, trade_count="1")
    elif case == "bool_week_count":
        row = replace(row, week_count=True)
    else:
        row = replace(row, week_count=row.trade_count + 1)
    rows[row_index] = row
    runs[key] = replace(run, measurements=tuple(rows))
    with pytest.raises(RecordError):
        assemble_retained_stage1_measurement_catalog(runs)


@pytest.mark.parametrize("row_index", range(len(PLAYBOOKS)))
@pytest.mark.parametrize("field,value", (
    *((field, value)
      for field in ("mean_profit_r", "weekly_win_rate", "bootstrap_lower_bound")
      for value in (float("nan"), float("inf"), -float("inf"), None, "0.5", True)),
    ("weekly_win_rate", -.01), ("weekly_win_rate", 1.01),
    *(("drawdown_recovery_weeks", value)
      for value in (float("nan"), -float("inf"), -1, None, "1", True)),
))
def test_invalid_nested_ranking_numbers_are_refused(row_index, field, value):
    runs = _runs()
    key = next(iter(runs))
    run = runs[key]
    rows = list(run.measurements)
    row = rows[row_index]
    if field == "bootstrap_lower_bound":
        row = replace(row, bootstrap_lower_bound=value)
    else:
        row = replace(row, measurement=replace(row.measurement, **{field: value}))
    rows[row_index] = row
    runs[key] = replace(run, measurements=tuple(rows))
    with pytest.raises(RecordError):
        assemble_retained_stage1_measurement_catalog(runs)


@pytest.mark.parametrize("resolved_r", (-1.0, 0.0, 1.0))
def test_real_producer_measurements_keep_valid_boundaries_and_unavailable_recovery(resolved_r):
    runs = _runs()
    key = next(iter(runs))
    run = runs[key]
    playbook, candidate_id = key
    candidate = STAGE1_CANDIDATES[playbook][0]
    measured = measure_stage1_candidate(
        playbook=playbook, candidate=candidate,
        trades=(ResolvedTrainingTrade(
            playbook, candidate_id, TRAINING_TICKERS[0], "LONG",
            datetime(2026, 1, 5, 8, tzinfo=ZoneInfo("America/Los_Angeles")),
            resolved_r, "SYNTHETIC_COST_V1", True,
            tuple(name for name, _ in candidate.settings), ("synthetic-trade",),
        ),),
        evaluated_tickers=TRAINING_TICKERS, disabled_rules=REQUIRED_DISABLED_RULES,
    )
    runs[key] = replace(run, measurements=(measured, *run.measurements[1:]))
    result = assemble_retained_stage1_measurement_catalog(runs)
    preserved = result.playbooks[0].entries[0].measurement
    assert preserved == measured
    assert preserved.measurement.mean_profit_r == resolved_r
    assert preserved.measurement.weekly_win_rate == (1.0 if resolved_r > 0 else 0.0)
    assert preserved.measurement.drawdown_recovery_weeks == (
        float("inf") if resolved_r < 0 else 0.0)
    assert result.catalog_complete
    assert not result.ranking_released


def test_recorded_full_candidate_catalog_is_deterministic_and_keeps_ranking_closed():
    result = assemble_retained_stage1_measurement_catalog(_runs())
    payload = result.as_dict()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    recording = {
        "version": RUN_VERSION,
        "measurement_catalog_sha256": hashlib.sha256(canonical).hexdigest(),
        "canonical_bytes": len(canonical),
        "result": payload,
        "catalog_sizes": {
            playbook: STAGE1_GRID_SIZES[playbook] for playbook in PLAYBOOKS
        },
        "exact_training_coverage": True,
        "exclusions_preserved": True,
        "gap_dependent_rules": "OFF_UNTESTED",
        "ranking_or_result_released": False,
        "held_out_opened": False,
        "alert_or_live_action": False,
    }
    rendered = json.dumps(recording, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91ef-retained-stage1-measurement-catalog.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert json.loads(output.read_text()) == recording
