"""M9.1EL frozen one-shot held-out D-108 evaluation contracts."""

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

import consensus_engine.retained_stage3_d108_evaluation as subject
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
from consensus_engine.retained_stage3_held_out_input import bind_retained_stage3_held_out_inputs
from consensus_engine.retained_stage3_input import bind_retained_stage3_input
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


def _held_out_source():
    stage3 = _source_stage3()
    playbook = stage3.selected_winner.events[0].trade.playbook
    winner = next(
        row for row in stage3.source_training.source_input.winners
        if row.playbook == playbook
    )
    candidate = winner.measurement.measurement.candidate
    events = tuple(
        Stage2TrainingEvent(
            ResolvedTrainingTrade(
                playbook,
                candidate.candidate_id,
                ticker,
                "LONG",
                START + timedelta(weeks=offset, minutes=30),
                1.0,
                "D106_D107_COSTS_V1",
                True,
                tuple(axis for axis, _value in candidate.settings),
                (f"held-out:{ticker}",),
            ),
            START + timedelta(weeks=offset),
        )
        for offset, ticker in enumerate(HELD_OUT_TICKERS)
    )
    return bind_retained_stage3_held_out_inputs(
        stage3,
        events=events,
        evaluated_tickers=HELD_OUT_TICKERS,
    )


@pytest.fixture(scope="module")
def held_out_source():
    return _held_out_source()


def _fingerprint(source):
    return hashlib.sha256(json.dumps(
        source.as_dict(), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def frozen_input_sha256(held_out_source):
    # Retain separately, before any test changes the handed-off input.
    return _fingerprint(held_out_source)


def test_runs_frozen_d108_once_and_publishes_every_measure(
    monkeypatch, held_out_source, frozen_input_sha256,
):
    source = held_out_source
    original = subject.evaluate_d108
    calls = []

    def counted(candidate_id, rows):
        calls.append((candidate_id, tuple(rows)))
        return original(candidate_id, rows)

    monkeypatch.setattr(subject, "evaluate_d108", counted)
    result = subject.run_retained_stage3_d108_evaluation(
        source, frozen_input_sha256=frozen_input_sha256,
    )

    assert len(calls) == 1
    assert result.version == subject.RUN_VERSION
    assert result.source_held_out == source
    assert result.frozen_input_sha256 == frozen_input_sha256
    assert result.evaluation.candidate_id == source.selected_candidate_id
    assert result.evaluation.trade_count == len(HELD_OUT_TICKERS)
    assert result.evaluation.profit.mean_r == pytest.approx(1.0)
    assert result.evaluation.profit.primary.lower_bound == pytest.approx(1.0)
    assert result.evaluation.consistency.winning_week_fraction == pytest.approx(1.0)
    assert result.evaluation.survivability.weeks_to_recover == pytest.approx(0.0)
    assert result.evaluation.passed is True
    assert result.disabled_rules == REQUIRED_DISABLED_RULES
    assert result.evaluation_complete and result.d108_evaluation_run
    assert not any((result.result_shard_released, result.alert_released, result.live_action))


@pytest.mark.parametrize("case", (
    "wrong_version", "wrong_rules", "incomplete", "unbound", "already_run",
    "result_released", "alert_released", "live_action", "forged_nested_source",
    "forged_held_out_event", "changed_close", "changed_record_id",
    "removed_event", "reordered_events",
))
def test_rejects_changed_evidence_or_an_open_later_boundary(
    case, held_out_source, frozen_input_sha256, monkeypatch,
):
    def must_not_evaluate(*args, **kwargs):
        pytest.fail("changed evidence reached D-108")

    monkeypatch.setattr(subject, "evaluate_d108", must_not_evaluate)
    source = held_out_source
    if case == "wrong_version":
        source = replace(source, version="FORGED")
    elif case == "wrong_rules":
        source = replace(source, disabled_rules=())
    elif case == "incomplete":
        source = replace(source, input_complete=False)
    elif case == "unbound":
        source = replace(source, held_out_bound=False)
    elif case == "already_run":
        source = replace(source, d108_evaluation_run=True)
    elif case == "result_released":
        source = replace(source, result_shard_released=True)
    elif case == "alert_released":
        source = replace(source, alert_released=True)
    elif case == "live_action":
        source = replace(source, live_action=True)
    elif case == "forged_nested_source":
        source = replace(
            source,
            source_stage3=replace(source.source_stage3, selected_winner=replace(
                source.source_stage3.selected_winner,
                trade_count=source.source_stage3.selected_winner.trade_count + 1,
            )),
        )
    elif case == "removed_event":
        source = replace(source, held_out_events=source.held_out_events[1:])
    elif case == "reordered_events":
        source = replace(source, held_out_events=tuple(reversed(source.held_out_events)))
    else:
        events = list(source.held_out_events)
        changes = {
            "forged_held_out_event": {"resolved_r": 99.0},
            "changed_close": {"closed_at": events[0].trade.closed_at + timedelta(minutes=1)},
            "changed_record_id": {"input_record_ids": ("changed-evidence",)},
        }
        events[0] = replace(events[0], trade=replace(events[0].trade, **changes[case]))
        source = replace(source, held_out_events=tuple(events))
    with pytest.raises(RecordError):
        subject.run_retained_stage3_d108_evaluation(
            source, frozen_input_sha256=frozen_input_sha256,
        )


@pytest.mark.parametrize("fingerprint", (None, "", "0" * 64, "not-a-digest"))
def test_rejects_unavailable_or_wrong_frozen_fingerprint(held_out_source, fingerprint, monkeypatch):
    def must_not_evaluate(*args, **kwargs):
        pytest.fail("unmatched evidence reached D-108")

    monkeypatch.setattr(subject, "evaluate_d108", must_not_evaluate)
    with pytest.raises(RecordError, match="independently frozen fingerprint"):
        subject.run_retained_stage3_d108_evaluation(
            held_out_source, frozen_input_sha256=fingerprint,
        )


def test_reconstruction_still_rejects_forged_training_with_matching_fingerprint(held_out_source):
    source = replace(
        held_out_source,
        source_stage3=replace(held_out_source.source_stage3, selected_winner=replace(
            held_out_source.source_stage3.selected_winner,
            trade_count=held_out_source.source_stage3.selected_winner.trade_count + 1,
        )),
    )
    with pytest.raises(RecordError, match="full training evidence"):
        subject.run_retained_stage3_d108_evaluation(
            source, frozen_input_sha256=_fingerprint(source),
        )


def test_large_return_is_valid_when_it_was_in_the_frozen_input(held_out_source):
    events = list(held_out_source.held_out_events)
    events[0] = replace(events[0], trade=replace(events[0].trade, resolved_r=99.0))
    source = bind_retained_stage3_held_out_inputs(
        held_out_source.source_stage3, events=events, evaluated_tickers=HELD_OUT_TICKERS,
    )
    frozen_input_sha256 = _fingerprint(source)
    result = subject.run_retained_stage3_d108_evaluation(
        source, frozen_input_sha256=frozen_input_sha256,
    )
    assert result.evaluation.profit.mean_r == pytest.approx(
        sum(event.trade.resolved_r for event in events) / len(events)
    )
    assert result.frozen_input_sha256 == frozen_input_sha256


def test_recorded_d108_evaluation_is_deterministic_and_keeps_release_closed(
    held_out_source, frozen_input_sha256,
):
    source = held_out_source
    payload = subject.run_retained_stage3_d108_evaluation(
        source, frozen_input_sha256=frozen_input_sha256,
    ).as_dict()
    assert payload == subject.run_retained_stage3_d108_evaluation(
        source, frozen_input_sha256=frozen_input_sha256,
    ).as_dict()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    recording = {
        "version": subject.RUN_VERSION,
        "input_sha256": frozen_input_sha256,
        "result_sha256": hashlib.sha256(canonical).hexdigest(),
        "canonical_bytes": len(canonical),
        "result": payload,
        "held_out_tickers": list(HELD_OUT_TICKERS),
        "d108_evaluation_run": True,
        "d108_passed": payload["evaluation"]["passed"],
        "gap_dependent_rules": "OFF_UNTESTED",
        "result_alert_or_live_released": False,
    }
    rendered = json.dumps(recording, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91el-retained-stage3-d108-evaluation.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert json.loads(output.read_text()) == recording
