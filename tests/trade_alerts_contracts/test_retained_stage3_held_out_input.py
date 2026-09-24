"""M9.1EK frozen held-out input contracts."""

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

import consensus_engine.retained_stage3_held_out_input as subject
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
from consensus_engine.retained_stage3_input import bind_retained_stage3_input
from consensus_engine.search_run_config import (
    HELD_OUT_TICKERS, STAGE1_CANDIDATES, TRAINING_TICKERS,
)
from consensus_engine.stage1_training_measurement import (
    POLICY_VERSION,
    ResolvedTrainingTrade,
    measure_stage1_candidate,
)
from consensus_engine.stage2_training_comparison import Stage2TrainingEvent
from consensus_engine.trade_alerts_models import RecordError


START = datetime(2026, 1, 5, 15, tzinfo=timezone.utc)
SESSIONS = tuple((ticker, "2026-01-05") for ticker in TRAINING_TICKERS)


def _source_stage3():
    catalogs = []
    winner_events = OrderedDict()
    for playbook_order, playbook in enumerate(PLAYBOOKS):
        entries = []
        for candidate in STAGE1_CANDIDATES[playbook]:
            resolved_r = float(playbook_order + 2) if candidate.table_order == 0 else 1.0
            trade = ResolvedTrainingTrade(
                playbook, candidate.candidate_id, TRAINING_TICKERS[playbook_order],
                "LONG", START + timedelta(minutes=30), resolved_r,
                "D106_D107_COSTS_V1", True,
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
    stage2_input = bind_retained_stage2_inputs(ranking, events_by_playbook=winner_events)
    return bind_retained_stage3_input(run_retained_stage2_training(stage2_input))


def _held_out_events(source):
    playbook = source.selected_winner.events[0].trade.playbook
    winner = next(
        row for row in source.source_training.source_input.winners
        if row.playbook == playbook
    )
    candidate = winner.measurement.measurement.candidate
    return tuple(
        Stage2TrainingEvent(
            ResolvedTrainingTrade(
                playbook,
                candidate.candidate_id,
                ticker,
                "LONG",
                START + timedelta(minutes=30),
                1.0,
                "D106_D107_COSTS_V1",
                True,
                tuple(axis for axis, _value in candidate.settings),
                (f"held-out:{ticker}",),
            ),
            START,
        )
        for ticker in HELD_OUT_TICKERS
    )


def test_binds_complete_cost_events_for_the_frozen_winner_only():
    source = _source_stage3()
    events = _held_out_events(source)
    result = subject.bind_retained_stage3_held_out_inputs(
        source, events=events, evaluated_tickers=HELD_OUT_TICKERS,
    )

    assert result.version == subject.RUN_VERSION
    assert result.source_stage3 == source
    assert result.selected_candidate_id == "SOLO_PULLBACK"
    assert result.selected_playbooks == ("FIRST_PULLBACK_VWAP",)
    assert result.held_out_events == events
    assert result.evaluated_tickers == HELD_OUT_TICKERS
    assert result.disabled_rules == REQUIRED_DISABLED_RULES
    assert result.input_complete and result.held_out_bound
    assert not any((result.d108_evaluation_run, result.result_shard_released,
                    result.alert_released, result.live_action))


@pytest.mark.parametrize("case", (
    "wrong_source_version", "opened_source", "wrong_scope", "training_ticker",
    "wrong_playbook", "wrong_candidate", "incomplete_cost", "wrong_axes",
    "duplicate_cluster",
))
def test_rejects_changed_training_evidence_or_nonmatching_held_out_events(case):
    source = _source_stage3()
    events = list(_held_out_events(source))
    scope = HELD_OUT_TICKERS
    if case == "wrong_source_version":
        source = replace(source, version="FORGED")
    elif case == "opened_source":
        source = replace(source, held_out_opened=True)
    elif case == "wrong_scope":
        scope = tuple(reversed(HELD_OUT_TICKERS))
    elif case == "training_ticker":
        events[0] = replace(events[0], trade=replace(events[0].trade, ticker="AAPL"))
    elif case == "wrong_playbook":
        events[0] = replace(events[0], trade=replace(events[0].trade, playbook="CRVOL_ORB5"))
    elif case == "wrong_candidate":
        events[0] = replace(events[0], trade=replace(events[0].trade, candidate_id="FORGED"))
    elif case == "incomplete_cost":
        events[0] = replace(events[0], trade=replace(events[0].trade, costs_complete=False))
    elif case == "wrong_axes":
        events[0] = replace(events[0], trade=replace(events[0].trade, tested_axes=()))
    else:
        events.append(events[0])
    with pytest.raises(RecordError):
        subject.bind_retained_stage3_held_out_inputs(
            source, events=events, evaluated_tickers=scope,
        )


def test_recorded_held_out_binding_is_deterministic_and_does_not_run_d108():
    source = _source_stage3()
    events = _held_out_events(source)
    payload = subject.bind_retained_stage3_held_out_inputs(
        source, events=events, evaluated_tickers=HELD_OUT_TICKERS,
    ).as_dict()
    assert payload == subject.bind_retained_stage3_held_out_inputs(
        source, events=events, evaluated_tickers=HELD_OUT_TICKERS,
    ).as_dict()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    recording = {
        "version": subject.RUN_VERSION,
        "input_sha256": hashlib.sha256(canonical).hexdigest(),
        "canonical_bytes": len(canonical),
        "result": payload,
        "held_out_tickers": list(HELD_OUT_TICKERS),
        "held_out_event_count": len(events),
        "selected_candidate_id": payload["selected_candidate_id"],
        "gap_dependent_rules": "OFF_UNTESTED",
        "d108_evaluation_run": False,
        "result_alert_or_live_released": False,
    }
    rendered = json.dumps(recording, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91ek-retained-stage3-held-out-input.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert json.loads(output.read_text()) == recording
