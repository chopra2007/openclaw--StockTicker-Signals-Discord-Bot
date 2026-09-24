"""M9.1EJ retained closed stage-3 input contracts."""

from collections import OrderedDict
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

import consensus_engine.retained_stage3_input as subject
from consensus_engine.orb5_stage1_result import REQUIRED_DISABLED_RULES
from consensus_engine.retained_decision_moments import PLAYBOOKS
from consensus_engine.retained_stage1_candidate_measurements import RUN_VERSION as MEASUREMENT_RUN_VERSION
from consensus_engine.retained_stage1_measurement_catalog import (
    RUN_VERSION as CATALOG_VERSION,
    RetainedStage1CatalogEntry,
    RetainedStage1MeasurementCatalogRun,
    RetainedStage1PlaybookCatalog,
)
from consensus_engine.retained_stage1_ranking import rank_retained_stage1_catalog
from consensus_engine.retained_stage2_input import bind_retained_stage2_inputs
from consensus_engine.retained_stage2_training_run import run_retained_stage2_training
from consensus_engine.search_run_config import STAGE1_CANDIDATES, TRAINING_TICKERS
from consensus_engine.stage1_training_measurement import (
    POLICY_VERSION,
    ResolvedTrainingTrade,
    measure_stage1_candidate,
)
from consensus_engine.stage2_training_comparison import Stage2TrainingEvent
from consensus_engine.trade_alerts_models import RecordError


START = datetime(2026, 1, 5, 15, tzinfo=timezone.utc)
SESSIONS = tuple((ticker, "2026-01-05") for ticker in TRAINING_TICKERS)


def _source_training():
    catalogs = []
    winner_events = OrderedDict()
    for playbook_order, playbook in enumerate(PLAYBOOKS):
        entries = []
        for candidate in STAGE1_CANDIDATES[playbook]:
            resolved_r = float(playbook_order + 2) if candidate.table_order == 0 else 1.0
            trade = ResolvedTrainingTrade(
                playbook,
                candidate.candidate_id,
                TRAINING_TICKERS[playbook_order],
                "LONG",
                START + timedelta(minutes=30),
                resolved_r,
                "D106_D107_COSTS_V1",
                True,
                tuple(axis for axis, _value in candidate.settings),
                (f"source:{playbook}:{candidate.candidate_id}",),
            )
            measured = measure_stage1_candidate(
                playbook=playbook,
                candidate=candidate,
                trades=(trade,),
                evaluated_tickers=TRAINING_TICKERS,
                disabled_rules=REQUIRED_DISABLED_RULES,
            )
            entries.append(RetainedStage1CatalogEntry(
                playbook, candidate.candidate_id, measured,
                4, 4, 4, 0, 0, 0, 0, 0,
            ))
            if candidate.table_order == 0:
                winner_events[playbook] = (Stage2TrainingEvent(trade, START),)
        catalogs.append(RetainedStage1PlaybookCatalog(playbook, tuple(entries)))
    catalog = RetainedStage1MeasurementCatalogRun(
        CATALOG_VERSION,
        MEASUREMENT_RUN_VERSION,
        POLICY_VERSION,
        tuple(catalogs),
        SESSIONS,
    )
    ranking = rank_retained_stage1_catalog(catalog)
    stage2_input = bind_retained_stage2_inputs(
        ranking, events_by_playbook=winner_events,
    )
    return run_retained_stage2_training(stage2_input)


def test_binds_frozen_stage2_winner_and_keeps_stage3_closed():
    source = _source_training()
    result = subject.bind_retained_stage3_input(source)

    assert result.version == subject.RUN_VERSION
    assert result.source_training == source
    assert result.selected_winner == source.comparison.winner
    assert result.selected_winner.candidate.candidate_id == "SOLO_PULLBACK"
    assert tuple(len(row.entries) for row in (
        result.source_training.source_input.source_ranking.rankings
    )) == (18, 4, 2, 4)
    assert len(result.source_training.comparison.measured) == 5
    assert result.disabled_rules == REQUIRED_DISABLED_RULES
    assert result.input_complete
    assert not any((result.held_out_opened, result.d108_evaluation_run,
                    result.result_shard_released, result.alert_released,
                    result.live_action))


@pytest.mark.parametrize("case", (
    "wrong_version", "comparison_incomplete", "held_out_open",
    "changed_winner", "changed_measurement", "changed_rules",
))
def test_rejects_changed_or_open_stage2_training(case):
    source = _source_training()
    if case == "wrong_version":
        source = replace(source, version="FORGED")
    elif case == "comparison_incomplete":
        source = replace(source, comparison_complete=False)
    elif case == "held_out_open":
        source = replace(source, held_out_opened=True)
    elif case == "changed_winner":
        source = replace(source, comparison=replace(
            source.comparison, winner=source.comparison.measured[0]))
    elif case == "changed_measurement":
        measured = list(source.comparison.measured)
        measured[0] = replace(measured[0], trade_count=99)
        source = replace(source, comparison=replace(
            source.comparison, measured=tuple(measured)))
    else:
        source = replace(source, disabled_rules=())
    with pytest.raises(RecordError):
        subject.bind_retained_stage3_input(source)


def test_recorded_retained_stage3_input_is_deterministic_and_keeps_held_out_sealed():
    source = _source_training()
    payload = subject.bind_retained_stage3_input(source).as_dict()
    assert payload == subject.bind_retained_stage3_input(source).as_dict()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    recording = {
        "version": subject.RUN_VERSION,
        "input_sha256": hashlib.sha256(canonical).hexdigest(),
        "canonical_bytes": len(canonical),
        "result": payload,
        "stage1_candidate_measurements_preserved": [18, 4, 2, 4],
        "stage2_candidate_count": 5,
        "selected_candidate_id": payload["selected_winner"]["candidate_id"],
        "gap_dependent_rules": "OFF_UNTESTED",
        "held_out_opened": False,
        "d108_result_alert_or_live_released": False,
    }
    rendered = json.dumps(recording, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91ej-retained-stage3-input.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert json.loads(output.read_text()) == recording
