"""M8.6 replay and synthetic scenario contracts for `FIRST_PULLBACK_VWAP`.

Every number below is a synthetic fixture supplied by the caller. A replayed
scenario proves the offline contract only: it establishes no bar, tape or quote
coverage, no adopted `FIRST_PULLBACK_VWAP` rule, no approved catalog, no
quality cutoff, no alert, no backtest result, no edge and no permission to act.

The two named scenarios are the clean supplied pullback that triggers in one
evaluation and the missing-last-trade evaluation that only arms.
"""

from dataclasses import FrozenInstanceError
from datetime import date, timedelta
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine import db
from consensus_engine.event_store import ResearchEventStore
from consensus_engine.first_pullback_vwap import STRATEGY_ID, pullback_rules
from consensus_engine.first_pullback_vwap_replay import (
    DATA_MODE, FORMING, FirstPullbackVwapReplayStrategy, PullbackReplayStep, REPLAY_VERSION,
    first_pullback_vwap_replay_rules,
)
from consensus_engine.historical_replay import (
    HistoricalReplayRunner, RecordingReplaySink, ReplaySpec,
)
from consensus_engine.state_transitions import StateTransitionEngine, TransitionScope
from consensus_engine.strategy_interface import (
    RequiredData, Strategy, StrategyContext, StrategyState,
)
from consensus_engine.trade_alerts_models import FeatureSnapshot, FeatureValue, RecordError
from consensus_engine.transition_store import SQLiteTransitionStore
from test_first_pullback_vwap import (
    ATR, DAY, EVALUATED, FROZEN, STARTED, MEASURE_LONG, MEASURE_SHORT, confidence,
    confidence_policy, last_trade, measurement, policy as pullback_policy, relative_strength,
    structural, vwap_context,
)
from test_orb5_eligibility import decision, metadata
from test_strategy_interface import session


VERSION = "M86_FIRST_PULLBACK_VWAP_FIXTURE_ONLY_V1"
DEFINITION = "M86_FIRST_PULLBACK_VWAP_SUPPLIED_FIXTURE_DEFINITION"
FEATURES = "M86_REPLAY_FIXTURE_FEATURES_V1"
PREFIX = "m86-pullback-transition"
OTHER = EVALUATED + timedelta(seconds=1)
NAMES = ("triggered", "armed")
ARMED = StrategyState("ARMED")
TRIGGERED = StrategyState("ALERT_TRIGGERED")


def step_at(direction, at, **changes):
    """One supplied pullback evaluation of the real M8.3 measurement at this instant."""
    values = dict(
        evaluated_at=at, measurement=measurement(direction, evaluated=at), atr_1m=ATR,
        pullback_ordinal=1, vwap=vwap_context(direction, at_instant=at),
        relative_strength=relative_strength(direction, at_instant=at),
        last_trade=last_trade(direction, at_instant=at), quote=decision(direction, at=at),
        structural=structural(direction, at_instant=at),
        confidence=confidence(direction, at_instant=at,
                              supplied_policy=confidence_policy(strategy_version=VERSION)))
    values.update(changes)
    return PullbackReplayStep(**values)


def _referenced_ids(step):
    """Every supplied record ID a gate could reference for this step."""
    ids = set(step.measurement.input_record_ids)
    if step.vwap is not None:
        ids.add(step.vwap.record_id)
    if step.relative_strength is not None:
        ids.add(step.relative_strength.record_id)
    if step.last_trade is not None:
        ids.add(step.last_trade.record_id)
    if step.quote is not None and step.quote.quote is not None:
        ids.add(step.quote.quote.record_id)
    if step.structural is not None:
        ids.update(step.structural.record_ids)
    if step.confidence is not None:
        ids.update(row.record_id for row in step.confidence.request.context.features)
    return tuple(sorted(ids))


def context_at(direction, at, step):
    """A minimal M4.2 context whose one provenance snapshot covers this step's IDs."""
    ids = _referenced_ids(step)
    provenance = FeatureSnapshot(
        record_id="m86-pullback-inputs-" + at.isoformat(),
        metadata=metadata(at, data_mode=DATA_MODE), evaluated_at=at,
        features=(FeatureValue("FIRST_PULLBACK_VWAP_REPLAY_INPUTS_V1", 1.0, "BOOLEAN", None, ids),),
        feature_version=FEATURES, input_record_ids=ids)
    return StrategyContext(session(DAY), "SYNTH", "EQUITY", direction, at, (provenance,))


def strategy(direction="LONG", *, steps, **changes):
    values = dict(
        session=session(DAY), symbol="SYNTH", instrument_type="EQUITY", strategy_version=VERSION,
        definition_reference=DEFINITION, policy=pullback_policy(direction),
        measurement_policy=MEASURE_LONG if direction == "LONG" else MEASURE_SHORT,
        impulse_started_at=STARTED, impulse_frozen_at=FROZEN, steps=steps, record_prefix=PREFIX)
    values.update(changes)
    return FirstPullbackVwapReplayStrategy(**values)


def scope(direction):
    return TransitionScope(session(DAY), "SYNTH", "EQUITY", direction, STRATEGY_ID, VERSION,
                           first_pullback_vwap_replay_rules())


def spec(**changes):
    values = dict(
        dataset_id="M86_FIRST_PULLBACK_VWAP_SCENARIO_V1", start_date=date(2026, 7, 6),
        end_date=date(2026, 7, 6), symbols=("SYNTH",),
        strategy_versions=((STRATEGY_ID, VERSION),), config_hash=session(DAY).config_hash,
        feature_engine_version=FEATURES,
        execution_model="CHRONOLOGICAL_SAME_RUNTIME", recorded_at=EVALUATED,
        code_revision="M86_SUPPLIED_TEST_REVISION")
    values.update(changes)
    return ReplaySpec(**values)


def plan(name):
    """The supplied steps and contexts for one named synthetic scenario."""
    if name == "triggered":
        step = step_at("LONG", EVALUATED)
        return "LONG", (step,), (context_at("LONG", EVALUATED, step),)
    if name == "armed":
        step = step_at("LONG", EVALUATED, last_trade=None)
        return "LONG", (step,), (context_at("LONG", EVALUATED, step),)
    raise AssertionError("unknown supplied scenario")


EXPECTED = {
    "triggered": (("ARMED", None), ("ALERT_TRIGGERED", None)),
    "armed": (("ARMED", None),),
}


async def replay(name, *, database=None):
    """Run one supplied scenario through the M5.3 runner in this process."""
    direction, steps, contexts = plan(name)
    if database is not None:
        await db.close_db()
        db.DB_PATH = str(database)
    connection = await db.init_db()
    owner = strategy(direction, steps=steps)
    sink = RecordingReplaySink()
    runner = HistoricalReplayRunner(
        spec=spec(), strategy=owner,
        transitions=StateTransitionEngine(scope(direction), SQLiteTransitionStore(connection)),
        store=ResearchEventStore(connection), sink=sink)
    result = await runner.run(contexts)
    owner.confirm_recorded()
    return owner, result, sink


def recorded_states(result):
    return tuple((row["transition"]["to_state"], row["transition"]["to_substate"])
                 for item in result.observations for row in item.as_dict()["transitions"])


@pytest.mark.parametrize("name", NAMES)
async def test_each_supplied_scenario_replays_its_own_recorded_states(name):
    owner, result, sink = await replay(name)
    assert recorded_states(result) == EXPECTED[name]
    assert tuple(sink.observations) == result.observations
    assert len(result.observations) == len(plan(name)[2])
    if name == "triggered":
        assert owner.current_state() == TRIGGERED
        assert owner.outcome().state == TRIGGERED
    else:
        assert owner.current_state() == ARMED
        assert owner.outcome().state == ARMED
    assert owner.heads_up() is None and owner.actionable() is None


async def test_a_clean_supplied_pullback_reports_its_supplied_geometry():
    owner, _, _ = await replay("triggered")
    result = owner.outcome()
    assert result.state == TRIGGERED and result.reasons == ()
    assert owner.stop() == result.risk and owner.targets() == result.targets
    assert owner.confidence() == result.confidence
    assert "CONFIDENCE_FLOOR_UNDEFINED" in result.unavailable
    assert owner.last_assessment().state == TRIGGERED


async def test_a_missing_last_trade_only_arms_the_pullback():
    owner, result, _ = await replay("armed")
    assert owner.current_state() == ARMED
    assert owner.notes() == ()
    assert owner.outcome().gate("PRICE_VS_VWAP").status == "UNKNOWN"


@pytest.mark.parametrize("name", NAMES)
async def test_the_same_supplied_scenario_replays_byte_identically(name, tmp_path):
    _, first, _ = await replay(name)
    _, second, _ = await replay(name, database=tmp_path / (name + "-second.db"))
    assert first.to_json() == second.to_json()
    assert first.fingerprint == second.fingerprint


async def test_the_two_scenarios_record_one_deterministic_proof(tmp_path):
    proof = {"synthetic_only": True, "replay_version": REPLAY_VERSION,
             "definition_reference": DEFINITION, "scenarios": {}}
    for name in NAMES:
        owner, result, _ = await replay(name, database=tmp_path / (name + "-proof.db"))
        outcome = owner.outcome()
        proof["scenarios"][name] = {
            "fingerprint": result.fingerprint,
            "states": [list(row) for row in recorded_states(result)],
            "final_state": [owner.current_state().state, owner.current_state().substate],
            "outcome_state": None if outcome is None else outcome.state.state,
            "outcome_reasons": [] if outcome is None else list(outcome.reasons),
            "notes": list(owner.notes()),
        }
    rendered = json.dumps(proof, sort_keys=True, separators=(",", ":"))
    assert len(rendered.encode()) < 100000
    assert len({row["fingerprint"] for row in proof["scenarios"].values()}) == len(NAMES)
    (Path(os.environ["TMPDIR"]) / "m8_6_first_pullback_vwap_scenarios.json").write_text(
        rendered + "\n")


# --- supplied rules, records and boundaries ---------------------------------


def test_the_replay_rules_are_exactly_the_m84_rules():
    rules = first_pullback_vwap_replay_rules()
    reference = pullback_rules()
    assert rules.version == reference.version
    assert rules.initial_state == reference.initial_state == FORMING
    assert rules.allowed == reference.allowed


def test_the_module_defines_no_number_of_its_own():
    from consensus_engine import first_pullback_vwap_replay

    numbers = {name: value for name, value in vars(first_pullback_vwap_replay).items()
               if not name.startswith("_") and isinstance(value, (int, float))
               and not isinstance(value, bool)}
    assert numbers == {}


@pytest.mark.parametrize("changes", (
    {"evaluated_at": "2026-07-06T06:39:00"}, {"evaluated_at": None}, {"measurement": None},
    {"measurement": "M84"}, {"atr_1m": "0.10"}, {"pullback_ordinal": 1.0},
    {"vwap": "m86-vwap"}, {"relative_strength": "m86-rs"}, {"last_trade": "m86-last-trade"},
    {"quote": "m86-quote"}, {"structural": "m86-structural"}, {"confidence": "m86-confidence"},
))
def test_a_supplied_step_requires_canonical_records(changes):
    with pytest.raises(RecordError):
        step_at("LONG", OTHER, **changes)


def test_supplied_steps_are_immutable():
    step = step_at("LONG", EVALUATED)
    with pytest.raises(FrozenInstanceError):
        step.evaluated_at = OTHER


@pytest.mark.parametrize("changes", (
    {"instrument_type": "OPTION"}, {"strategy_version": " "}, {"strategy_version": "UNKNOWN"},
    {"definition_reference": "UNSPECIFIED"}, {"record_prefix": ""}, {"symbol": "UNKNOWN"},
    {"policy": "M84_POLICY"}, {"measurement_policy": "M83_POLICY"},
    {"impulse_started_at": "2026-07-06"}, {"impulse_frozen_at": STARTED},
    {"session": "2026-07-06"}, {"steps": ()}, {"steps": [step_at("LONG", EVALUATED)]},
    {"steps": ("TRIGGERED",)},
))
def test_the_replay_owner_requires_complete_supplied_scope(changes):
    values = dict(steps=(step_at("LONG", EVALUATED),))
    values.update(changes)
    with pytest.raises(RecordError):
        strategy(**values)


def test_supplied_steps_must_be_chronological_and_distinct():
    with pytest.raises(RecordError):
        strategy(steps=(step_at("LONG", EVALUATED), step_at("LONG", EVALUATED)))


def test_the_owner_implements_the_shared_strategy_interface():
    owner = strategy(steps=(step_at("LONG", EVALUATED),))
    assert isinstance(owner, Strategy)
    assert owner.strategy_id == STRATEGY_ID and owner.strategy_version == VERSION
    declared = owner.required_data()
    assert all(isinstance(row, RequiredData) for row in declared)
    assert {row.data_mode for row in declared} == {DATA_MODE}
    assert owner.current_state() == FORMING
    assert owner.stop() is None and owner.targets() == () and owner.confidence() is None


async def test_an_evaluation_outside_this_owner_is_refused():
    step = step_at("LONG", EVALUATED)
    owner = strategy(steps=(step,))
    for supplied in (context_at("SHORT", EVALUATED, step), "LONG", None):
        with pytest.raises(RecordError):
            owner.update(supplied)


async def test_an_instant_without_a_supplied_step_is_refused():
    step = step_at("LONG", EVALUATED)
    owner = strategy(steps=(step,))
    with pytest.raises(RecordError, match="no supplied replay step"):
        owner.update(context_at("LONG", OTHER, step))


async def test_evaluation_time_cannot_move_backward():
    early, late = step_at("LONG", EVALUATED), step_at("LONG", OTHER)
    owner = strategy(steps=(early, late))
    owner.update(context_at("LONG", OTHER, late))
    with pytest.raises(RecordError, match="backward"):
        owner.update(context_at("LONG", EVALUATED, early))


async def test_a_caller_cannot_assert_an_invalidation():
    step = step_at("LONG", EVALUATED)
    owner = strategy(steps=(step,))
    with pytest.raises(RecordError, match="supplied pullback evidence"):
        owner.invalidate(context_at("LONG", EVALUATED, step), reason="CALLER_SAYS_SO")


async def test_state_advances_only_after_the_transition_was_recorded():
    step = step_at("LONG", EVALUATED)
    owner = strategy(steps=(step,))
    changes = owner.update(context_at("LONG", EVALUATED, step))
    assert len(changes) == 2
    assert (changes[0].record_id, changes[1].record_id) == (PREFIX + "-001", PREFIX + "-002")
    assert owner.current_state() == FORMING
    assert owner.confirm_recorded() == TRIGGERED


async def test_an_armed_owner_can_be_expired_at_the_supplied_instant():
    step = step_at("LONG", EVALUATED, last_trade=None)
    owner = strategy(steps=(step,))
    owner.update(context_at("LONG", EVALUATED, step))
    assert owner.confirm_recorded() == ARMED
    changes = owner.expire(context_at("LONG", EVALUATED, step), reason="EVALUATION_WINDOW_CLOSED")
    assert changes[0].to_state == "EXPIRED"
    assert owner.confirm_recorded() == StrategyState("EXPIRED")
    assert owner.update(context_at("LONG", EVALUATED, step)) == ()
    assert owner.notes() == ("SESSION_EXPIRED",)


async def test_a_reset_owner_starts_the_supplied_session_again():
    step = step_at("LONG", EVALUATED)
    owner = strategy(steps=(step,))
    owner.update(context_at("LONG", EVALUATED, step))
    owner.confirm_recorded()
    owner.reset(session(DAY))
    assert owner.current_state() == FORMING
    assert owner.outcome() is None and owner.notes() == ()
    assert owner.update(context_at("LONG", EVALUATED, step))[0].record_id == PREFIX + "-001"


async def test_every_replayed_input_and_transition_is_stored_once():
    connection = await db.init_db()
    direction, steps, contexts = plan("triggered")
    owner = strategy(direction, steps=steps)
    store = ResearchEventStore(connection)
    runner = HistoricalReplayRunner(
        spec=spec(), strategy=owner,
        transitions=StateTransitionEngine(scope(direction), SQLiteTransitionStore(connection)),
        store=store, sink=RecordingReplaySink())
    await runner.run(contexts)
    rows = await store.read_all()
    identifiers = [row["record_id"] for row in rows]
    assert len(identifiers) == len(set(identifiers))
    assert {PREFIX + "-001", PREFIX + "-002"} <= set(identifiers)
