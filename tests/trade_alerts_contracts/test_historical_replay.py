"""M5.3 supplied-record historical replay contract."""

from dataclasses import replace
from datetime import date, timedelta
import json
import os
from pathlib import Path
import sqlite3
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine import db
from consensus_engine.event_store import ResearchEventStore
from consensus_engine.historical_replay import (
    HistoricalReplayRunner, RecordingReplaySink, ReplaySpec,
)
from consensus_engine.state_transitions import StateTransitionEngine
from consensus_engine.strategy_interface import StrategyContext
from consensus_engine.trade_alerts_models import RecordError
from consensus_engine.transition_store import SQLiteTransitionStore
from test_state_transitions import scope
from test_strategy_interface import START, VERSION, FixtureStrategy, context, quote_decision


def spec(**changes):
    values = dict(
        dataset_id="M53_SUPPLIED_FIXTURE_V1",
        start_date=date(2026, 7, 6), end_date=date(2026, 7, 6),
        symbols=("SYNTH",), strategy_versions=(("CRVOL_ORB5", VERSION),),
        config_hash=context().session.config_hash,
        feature_engine_version=context().features[0].feature_version,
        execution_model="CHRONOLOGICAL_SAME_RUNTIME",
        recorded_at=START + timedelta(hours=7), code_revision="SUPPLIED_TEST_REVISION",
    )
    values.update(changes)
    return ReplaySpec(**values)


async def run_once(contexts):
    conn = await db.init_db()
    event_store = ResearchEventStore(conn)
    transition_store = SQLiteTransitionStore(conn)
    sink = RecordingReplaySink()
    runner = HistoricalReplayRunner(
        spec=spec(), strategy=FixtureStrategy(context().session, "LONG"),
        transitions=StateTransitionEngine(scope(), transition_store),
        store=event_store, sink=sink,
    )
    result = await runner.run(contexts)
    rows = await event_store.read_all()
    return result, sink, rows


async def test_chronological_same_runtime_replay_is_byte_deterministic(tmp_path):
    supplied = tuple(context(START + timedelta(seconds=offset),
                             quote=quote_decision(START + timedelta(seconds=offset),
                                                  stale=offset in (-1, 2)))
                     for offset in (-1, 0, 1, 2))
    first, first_sink, first_rows = await run_once(supplied)
    await db.close_db()
    db.DB_PATH = str(tmp_path / "second.db")
    second, second_sink, second_rows = await run_once(supplied)
    assert first.to_json() == second.to_json()
    assert first.fingerprint == second.fingerprint
    assert tuple(first_sink.observations) == first.observations
    assert tuple(second_sink.observations) == second.observations
    assert [row["to_state"] for row in (item.as_dict()["transitions"][0]["transition"]
                                        for item in first.observations)] == [
        "WATCHING", "SETUP_FORMING", "ALERT_TRIGGERED", "WATCHING"]
    assert [(row["record_id"], row["fingerprint"]) for row in first_rows] == [
        (row["record_id"], row["fingerprint"]) for row in second_rows]
    artifact = {
        "fingerprint": first.fingerprint,
        "ordered_output": first.as_dict()["observations"],
    }
    (Path(os.environ["TMPDIR"]) / "m5_3_replay_artifact.json").write_text(
        json.dumps(artifact, sort_keys=True, separators=(",", ":")) + "\n"
    )


async def test_equal_times_keep_supplied_order():
    at = START
    supplied = (context(at, quote=quote_decision(at, stale=True)), context(at))
    result, _, _ = await run_once(supplied)
    transitions = [row.as_dict()["transitions"][0]["transition"] for row in result.observations]
    assert [row["from_state"] for row in transitions] == ["NOT_ELIGIBLE", "WATCHING"]
    assert [row["to_state"] for row in transitions] == ["WATCHING", "SETUP_FORMING"]


@pytest.mark.parametrize("case", ["backward", "future_input", "config", "version", "range"])
async def test_replay_fails_closed_for_unfaithful_inputs(case):
    first = context(START)
    runner_spec = spec()
    strategy = FixtureStrategy(first.session, "LONG")
    contexts = (first, context(START - timedelta(seconds=1)))
    if case == "future_input":
        decision = quote_decision(START)
        future = replace(decision.quote.metadata, available_time=START + timedelta(seconds=1))
        with pytest.raises(RecordError, match="not yet available"):
            replace(first, quote=replace(decision, quote=replace(decision.quote, metadata=future)))
        return
    if case == "config":
        runner_spec = spec(config_hash="1" * 64)
        contexts = (first,)
    elif case == "version":
        runner_spec = spec(strategy_versions=(("CRVOL_ORB5", "OTHER_V1"),))
        contexts = (first,)
    elif case == "range":
        runner_spec = spec(start_date=date(2026, 7, 7), end_date=date(2026, 7, 7))
        contexts = (first,)
    conn = await db.init_db()
    runner = HistoricalReplayRunner(
        spec=runner_spec, strategy=strategy,
        transitions=StateTransitionEngine(scope(), SQLiteTransitionStore(conn)),
        store=ResearchEventStore(conn), sink=RecordingReplaySink())
    with pytest.raises(RecordError):
        await runner.run(contexts)


async def test_replay_rejects_feature_version_outside_fixed_provenance():
    supplied = context(START)
    wrong = replace(supplied.features[0], feature_version="OTHER_FEATURES_V1")
    with pytest.raises(RecordError, match="feature version"):
        await run_once((replace(supplied, features=(wrong,)),))


async def test_replay_rejects_non_recording_sink():
    class OtherSink:
        async def record(self, observation):
            raise AssertionError("must not be called")

    conn = await db.init_db()
    with pytest.raises(RecordError, match="recording-only sink"):
        HistoricalReplayRunner(
            spec=spec(), strategy=FixtureStrategy(context().session, "LONG"),
            transitions=StateTransitionEngine(scope(), SQLiteTransitionStore(conn)),
            store=ResearchEventStore(conn), sink=OtherSink())


async def test_replay_rejects_database_outside_temporary_storage(tmp_path, monkeypatch):
    conn = await db.init_db()
    monkeypatch.setenv("TMPDIR", str(tmp_path / "different-root"))
    runner = HistoricalReplayRunner(
        spec=spec(), strategy=FixtureStrategy(context().session, "LONG"),
        transitions=StateTransitionEngine(scope(), SQLiteTransitionStore(conn)),
        store=ResearchEventStore(conn), sink=RecordingReplaySink())
    with pytest.raises(RecordError, match="temporary storage"):
        await runner.run((context(START),))


async def test_replay_rejects_transition_store_on_different_database(tmp_path):
    event_connection = await db.init_db()
    transition_connection = db.AsyncConnection(
        sqlite3.connect(tmp_path / "state-changes.db"))
    runner = HistoricalReplayRunner(
        spec=spec(), strategy=FixtureStrategy(context().session, "LONG"),
        transitions=StateTransitionEngine(
            scope(), SQLiteTransitionStore(transition_connection)),
        store=ResearchEventStore(event_connection), sink=RecordingReplaySink())
    with pytest.raises(RecordError, match="same isolated database"):
        await runner.run((context(START),))


def test_replay_spec_requires_complete_fixed_attribution():
    for changes in ({"symbols": ()}, {"dataset_id": ""},
                    {"config_hash": "bad"},
                    {"strategy_versions": (("CRVOL_ORB5", VERSION),
                                             ("CRVOL_ORB5", "OTHER"))},
                    {"start_date": date(2026, 7, 7), "end_date": date(2026, 7, 6)}):
        with pytest.raises(RecordError):
            spec(**changes)
