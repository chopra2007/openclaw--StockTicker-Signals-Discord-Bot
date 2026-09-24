"""M9.1EG retained per-playbook stage-1 ranking contracts."""

from collections import OrderedDict
from dataclasses import replace
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
from consensus_engine.retained_stage1_candidate_measurements import (
    RUN_VERSION as INPUT_VERSION,
    RetainedStage1CandidateMeasurementRun,
)
from consensus_engine.retained_stage1_measurement_catalog import (
    RUN_VERSION as CATALOG_VERSION,
    assemble_retained_stage1_measurement_catalog,
)
from consensus_engine.retained_stage1_ranking import (
    RUN_VERSION, rank_retained_stage1_catalog,
)
from consensus_engine.search_run_config import STAGE1_CANDIDATES, TRAINING_TICKERS, TrainingMeasurement
from consensus_engine.stage1_training_measurement import POLICY_VERSION, Stage1TrainingMeasurement
from consensus_engine.trade_alerts_models import RecordError


def _sessions():
    return tuple((ticker, "2026-01-05") for ticker in TRAINING_TICKERS)


def _measurement(playbook, candidate, profit, win_rate, recovery):
    return Stage1TrainingMeasurement(
        POLICY_VERSION, playbook,
        TrainingMeasurement(candidate, profit, win_rate, recovery),
        profit - .1, 1, 1, TRAINING_TICKERS, REQUIRED_DISABLED_RULES,
    )


def _run(selected_playbook, selected_candidate, profit, win_rate, recovery,
         trade_counts=(1, 1, 1, 1)):
    rows = []
    for playbook, trade_count in zip(PLAYBOOKS, trade_counts):
        candidate = selected_candidate if playbook == selected_playbook else STAGE1_CANDIDATES[playbook][0]
        rows.append(replace(
            _measurement(playbook, candidate, profit, win_rate, recovery),
            trade_count=trade_count,
        ))
    fully_costed = sum(trade_counts)
    return RetainedStage1CandidateMeasurementRun(
        INPUT_VERSION, "M91ED_RETAINED_STAGE1_CANDIDATE_GROUPS_V1", POLICY_VERSION,
        tuple(rows), _sessions(), fully_costed + 5, fully_costed + 3,
        fully_costed, 2, 3, 5, 6, 7, REQUIRED_DISABLED_RULES,
    )


def _catalog(trade_counts=(1, 1, 1, 1)):
    runs = OrderedDict()
    for playbook in PLAYBOOKS:
        candidates = STAGE1_CANDIDATES[playbook]
        for candidate in candidates:
            order = candidate.table_order
            runs[(playbook, candidate.candidate_id)] = _run(
                playbook, candidate, float(order % 3), float((order % 2) / 2), float(order % 4),
                trade_counts,
            )
    return assemble_retained_stage1_measurement_catalog(runs)


def test_each_playbook_uses_frozen_rank_and_preserves_every_catalog_entry():
    catalog = _catalog()
    result = rank_retained_stage1_catalog(catalog)

    assert result.version == RUN_VERSION
    assert result.catalog_version == CATALOG_VERSION
    assert tuple(row.playbook for row in result.rankings) == PLAYBOOKS
    assert tuple(len(row.entries) for row in result.rankings) == (18, 4, 2, 4)
    assert tuple(row.winner_candidate_id for row in result.rankings) == (
        STAGE1_CANDIDATES["CRVOL_ORB5"][5].candidate_id,
        STAGE1_CANDIDATES["HOD_COMP_RS"][2].candidate_id,
        STAGE1_CANDIDATES["OR_FAILURE_REV"][1].candidate_id,
        STAGE1_CANDIDATES["FIRST_PULLBACK_VWAP"][2].candidate_id,
    )
    assert tuple(row.entries for row in result.rankings) == tuple(
        group.entries for group in catalog.playbooks
    )
    assert result.disabled_rules == REQUIRED_DISABLED_RULES
    assert result.ranking_complete
    assert not any((result.result_shard_released, result.held_out_opened,
                    result.alert_released, result.live_action))


@pytest.mark.parametrize("trade_counts", ((1, 2, 3, 4), (4, 1, 1, 1)))
def test_source_run_totals_are_preserved_separately_from_each_playbook(trade_counts):
    catalog = _catalog(trade_counts)
    result = rank_retained_stage1_catalog(catalog)
    for ranking, group, trade_count in zip(result.rankings, catalog.playbooks, trade_counts):
        assert ranking.entries == group.entries
        for entry in ranking.entries:
            assert entry.measurement.trade_count == trade_count
            assert entry.fully_costed_count == sum(trade_counts)
            assert entry.outcome_count == sum(trade_counts) + 5
            assert entry.resolved_outcome_count == sum(trade_counts) + 3
            assert (entry.unresolved_excluded_count, entry.incomplete_cost_excluded_count,
                    entry.unfilled_excluded_count, entry.no_event_excluded_count,
                    entry.unavailable_excluded_count) == (2, 3, 5, 6, 7)


@pytest.mark.parametrize("trade_count", (8, 10, 11))
def test_source_total_must_cover_this_playbook_and_nonempty_other_playbooks(trade_count):
    catalog = _catalog((1, 2, 3, 4))
    group = catalog.playbooks[0]
    entry = group.entries[0]
    entry = replace(entry, measurement=replace(entry.measurement, trade_count=trade_count))
    catalog = replace(catalog, playbooks=(
        replace(group, entries=(entry, *group.entries[1:])), *catalog.playbooks[1:],
    ))
    with pytest.raises(RecordError, match="ranking catalog exclusion counts do not match"):
        rank_retained_stage1_catalog(catalog)


def test_frozen_ties_use_win_rate_recovery_then_table_order():
    catalog = _catalog()
    group = catalog.playbooks[2]
    first, second = group.entries

    tied_profit = replace(second.measurement, measurement=replace(
        second.measurement.measurement,
        mean_profit_r=first.measurement.measurement.mean_profit_r,
        weekly_win_rate=1.0,
        drawdown_recovery_weeks=9.0,
    ))
    catalog = replace(catalog, playbooks=(
        *catalog.playbooks[:2], replace(group, entries=(first, replace(second, measurement=tied_profit))),
        catalog.playbooks[3],
    ))
    assert rank_retained_stage1_catalog(catalog).rankings[2].winner_candidate_id == second.candidate_id

    full_tie = replace(tied_profit, measurement=replace(
        tied_profit.measurement,
        weekly_win_rate=first.measurement.measurement.weekly_win_rate,
        drawdown_recovery_weeks=first.measurement.measurement.drawdown_recovery_weeks,
    ))
    group = replace(group, entries=(first, replace(second, measurement=full_tie)))
    catalog = replace(catalog, playbooks=(*catalog.playbooks[:2], group, catalog.playbooks[3]))
    assert rank_retained_stage1_catalog(catalog).rankings[2].winner_candidate_id == first.candidate_id


@pytest.mark.parametrize("case", (
    "wrong_version", "incomplete", "truthy_complete", "ranking_open", "held_out_open", "missing_playbook",
    "wrong_playbook", "missing_entry", "wrong_candidate", "bad_number", "bad_count",
    "changed_rules", "changed_sessions",
))
def test_changed_incomplete_or_already_open_catalog_is_refused(case):
    catalog = _catalog()
    group = catalog.playbooks[0]
    entry = group.entries[0]
    if case == "wrong_version":
        catalog = replace(catalog, version="FORGED")
    elif case == "incomplete":
        catalog = replace(catalog, catalog_complete=False)
    elif case == "truthy_complete":
        catalog = replace(catalog, catalog_complete=1)
    elif case == "ranking_open":
        catalog = replace(catalog, ranking_released=True)
    elif case == "held_out_open":
        catalog = replace(catalog, held_out_opened=True)
    elif case == "missing_playbook":
        catalog = replace(catalog, playbooks=catalog.playbooks[:-1])
    elif case == "wrong_playbook":
        catalog = replace(catalog, playbooks=(replace(group, playbook=PLAYBOOKS[1]), *catalog.playbooks[1:]))
    elif case == "missing_entry":
        catalog = replace(catalog, playbooks=(replace(group, entries=group.entries[:-1]), *catalog.playbooks[1:]))
    elif case == "wrong_candidate":
        entry = replace(entry, candidate_id=group.entries[1].candidate_id)
        catalog = replace(catalog, playbooks=(replace(group, entries=(entry, *group.entries[1:])), *catalog.playbooks[1:]))
    elif case == "bad_number":
        measurement = replace(entry.measurement, measurement=replace(entry.measurement.measurement, mean_profit_r=float("nan")))
        entry = replace(entry, measurement=measurement)
        catalog = replace(catalog, playbooks=(replace(group, entries=(entry, *group.entries[1:])), *catalog.playbooks[1:]))
    elif case == "bad_count":
        entry = replace(entry, fully_costed_count=99)
        catalog = replace(catalog, playbooks=(replace(group, entries=(entry, *group.entries[1:])), *catalog.playbooks[1:]))
    elif case == "changed_rules":
        catalog = replace(catalog, disabled_rules=())
    else:
        catalog = replace(catalog, training_sessions=catalog.training_sessions[:-1])
    with pytest.raises(RecordError):
        rank_retained_stage1_catalog(catalog)


def test_recorded_stage1_ranking_is_deterministic_and_keeps_later_release_closed():
    catalog = _catalog((1, 2, 3, 4))
    result = rank_retained_stage1_catalog(catalog)
    payload = result.as_dict()
    assert payload == rank_retained_stage1_catalog(catalog).as_dict()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    recording = {
        "version": RUN_VERSION,
        "ranking_sha256": hashlib.sha256(canonical).hexdigest(),
        "canonical_bytes": len(canonical),
        "result": payload,
        "all_candidate_measurements_preserved": tuple(
            len(row.entries) for row in result.rankings) == (18, 4, 2, 4),
        "gap_dependent_rules": "OFF_UNTESTED",
        "held_out_opened": False,
        "result_alert_or_live_released": False,
    }
    rendered = json.dumps(recording, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91eg-retained-stage1-ranking.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert json.loads(output.read_text()) == recording
