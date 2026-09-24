"""M9.1EH retained stage-2 input binding contracts."""

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

import consensus_engine.retained_stage2_input as subject
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
from consensus_engine.search_run_config import HELD_OUT_TICKERS, STAGE1_CANDIDATES, TRAINING_TICKERS
from consensus_engine.stage1_training_measurement import (
    POLICY_VERSION,
    ResolvedTrainingTrade,
    measure_stage1_candidate,
)
from consensus_engine.stage2_training_comparison import Stage2TrainingEvent
from consensus_engine.trade_alerts_models import RecordError


START = datetime(2026, 1, 5, 15, tzinfo=timezone.utc)
SESSIONS = tuple((ticker, "2026-01-05") for ticker in TRAINING_TICKERS)


def _trade(playbook, candidate, resolved_r, ticker=None, costs_complete=True):
    return ResolvedTrainingTrade(
        playbook,
        candidate.candidate_id,
        ticker or TRAINING_TICKERS[0],
        "LONG",
        START + timedelta(minutes=30),
        resolved_r,
        "D106_D107_COSTS_V1",
        costs_complete,
        tuple(axis for axis, _value in candidate.settings),
        (f"source:{playbook}:{candidate.candidate_id}:{resolved_r}",),
    )


def _fixture():
    playbook_catalogs = []
    winner_events = OrderedDict()
    for playbook in PLAYBOOKS:
        entries = []
        for candidate in STAGE1_CANDIDATES[playbook]:
            resolved_r = 2.0 if candidate.table_order == 0 else 1.0
            trade = _trade(playbook, candidate, resolved_r)
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
        playbook_catalogs.append(RetainedStage1PlaybookCatalog(playbook, tuple(entries)))
    catalog = RetainedStage1MeasurementCatalogRun(
        CATALOG_VERSION,
        MEASUREMENT_RUN_VERSION,
        POLICY_VERSION,
        tuple(playbook_catalogs),
        SESSIONS,
    )
    return rank_retained_stage1_catalog(catalog), winner_events


def test_binds_every_retained_winner_and_preserves_the_complete_catalog():
    ranking, events = _fixture()
    result = subject.bind_retained_stage2_inputs(ranking, events_by_playbook=events)

    assert result.version == subject.RUN_VERSION
    assert result.source_ranking == ranking
    assert tuple(winner.playbook for winner in result.winners) == PLAYBOOKS
    assert tuple(len(winner.candidate_measurements) for winner in result.winners) == (18, 4, 2, 4)
    assert tuple(winner.events for winner in result.winners) == tuple(events.values())
    assert result.disabled_rules == REQUIRED_DISABLED_RULES
    assert result.input_complete
    assert not any((result.stage2_ranking_released, result.result_shard_released,
                    result.held_out_opened, result.alert_released, result.live_action))


@pytest.mark.parametrize("case", (
    "wrong_version", "missing_playbook", "wrong_candidate", "held_out",
    "incomplete_cost", "wrong_axes", "wrong_measurement", "duplicate",
    "changed_rules", "stage2_open",
))
def test_rejects_changed_ranking_or_nonmatching_winner_events(case):
    ranking, events = _fixture()
    events = OrderedDict(events)
    first = PLAYBOOKS[0]
    event = events[first][0]
    if case == "wrong_version":
        ranking = replace(ranking, version="FORGED")
    elif case == "missing_playbook":
        events.popitem()
    elif case == "wrong_candidate":
        events[first] = (replace(event, trade=replace(
            event.trade, candidate_id=STAGE1_CANDIDATES[first][1].candidate_id)),)
    elif case == "held_out":
        held_out_ticker = HELD_OUT_TICKERS[0]
        assert held_out_ticker not in TRAINING_TICKERS
        events[first] = (replace(event, trade=replace(event.trade, ticker=held_out_ticker)),)
    elif case == "incomplete_cost":
        events[first] = (replace(event, trade=replace(event.trade, costs_complete=False)),)
    elif case == "wrong_axes":
        events[first] = (replace(event, trade=replace(event.trade, tested_axes=())),)
    elif case == "wrong_measurement":
        events[first] = (replace(event, trade=replace(event.trade, resolved_r=99.0)),)
    elif case == "duplicate":
        events[first] = (event, event)
    elif case == "changed_rules":
        ranking = replace(ranking, disabled_rules=())
    else:
        ranking = replace(ranking, result_shard_released=True)
    with pytest.raises(RecordError):
        subject.bind_retained_stage2_inputs(ranking, events_by_playbook=events)


def test_recorded_retained_stage2_input_is_deterministic_and_keeps_stage2_closed():
    ranking, events = _fixture()
    result = subject.bind_retained_stage2_inputs(ranking, events_by_playbook=events)
    payload = result.as_dict()
    assert payload == subject.bind_retained_stage2_inputs(
        ranking, events_by_playbook=events).as_dict()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    recording = {
        "version": subject.RUN_VERSION,
        "input_sha256": hashlib.sha256(canonical).hexdigest(),
        "canonical_bytes": len(canonical),
        "result": payload,
        "candidate_measurements_preserved": [18, 4, 2, 4],
        "gap_dependent_rules": "OFF_UNTESTED",
        "stage2_ranked": False,
        "held_out_opened": False,
        "result_alert_or_live_released": False,
    }
    rendered = json.dumps(recording, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91eh-retained-stage2-input.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert json.loads(output.read_text()) == recording
