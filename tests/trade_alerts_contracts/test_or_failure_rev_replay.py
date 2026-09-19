"""M8.6 replay and synthetic scenario contracts for `OR_FAILURE_REV`.

Every number below is a synthetic fixture supplied by the caller. A replayed
scenario proves the offline contract only: it establishes no provider coverage,
no adopted `OR_FAILURE_REV` rule, no approved catalog, no quality cutoff, no
alert, no backtest result, no edge and no permission to act.

The two named scenarios are the clean supplied reversal that triggers in one
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
from consensus_engine.historical_replay import (
    HistoricalReplayRunner, RecordingReplaySink, ReplaySpec,
)
from consensus_engine.or_failure_handoff import STRATEGY_ID, mirror_direction
from consensus_engine.or_failure_rev import reversal_rules
from consensus_engine.or_failure_rev_replay import (
    DATA_MODE, FORMING, OrFailureRevReplayStep, OrFailureRevReplayStrategy, REPLAY_VERSION,
    or_failure_rev_replay_rules,
)
from consensus_engine.state_transitions import StateTransitionEngine, TransitionScope
from consensus_engine.strategy_interface import (
    RequiredData, Strategy, StrategyContext, StrategyState,
)
from consensus_engine.trade_alerts_models import FeatureSnapshot, FeatureValue, RecordError
from consensus_engine.transition_store import SQLiteTransitionStore
from test_or_failure_handoff import ENDED_AT, EXTREME
from test_or_failure_rev import (
    acceptance, confidence, confidence_policy, failure_bar, handoff, last_trade,
    minute_close as confirmation_close, policy as reversal_policy, structural,
)
from test_orb5_eligibility import decision, metadata
from test_orb5_trigger import DAY
from test_strategy_interface import session


VERSION = "M86_OR_FAILURE_REV_FIXTURE_ONLY_V1"
DEFINITION = "M86_OR_FAILURE_REV_SUPPLIED_FIXTURE_DEFINITION"
FEATURES = "M86_REPLAY_FIXTURE_FEATURES_V1"
PREFIX = "m86-rev-transition"
OTHER = ENDED_AT + timedelta(seconds=1)
NAMES = ("triggered", "armed")
ARMED = StrategyState("ARMED")
TRIGGERED = StrategyState("ALERT_TRIGGERED")


def step_at(break_direction, at, **changes):
    """One supplied reversal evaluation of the real M8.1 handoff at this instant."""
    values = dict(
        evaluated_at=at, handoff=handoff(break_direction, at=at),
        breakout_extreme_price=EXTREME[break_direction],
        last_trade=last_trade(break_direction, at=at),
        confirmation_close=confirmation_close(break_direction, at=at),
        failure_bar=failure_bar(break_direction, at=at), acceptance=acceptance(at=at),
        quote=decision(at=at),
        structural=structural(break_direction, at=at),
        confidence=confidence(break_direction, at=at,
                              supplied_policy=confidence_policy(strategy_version=VERSION)))
    values.update(changes)
    return OrFailureRevReplayStep(**values)


def _referenced_ids(step):
    """Every supplied record ID a gate could reference for this step."""
    ids = {value for row in step.handoff.gates for value in row.input_record_ids}
    if step.last_trade is not None:
        ids.add(step.last_trade.record_id)
    if step.confirmation_close is not None:
        ids.add(step.confirmation_close.record_id)
    if step.failure_bar is not None:
        ids.add(step.failure_bar.record_id)
    if step.acceptance is not None:
        ids.add(step.acceptance.record_id)
    if step.quote is not None and step.quote.quote is not None:
        ids.add(step.quote.quote.record_id)
    if step.structural is not None:
        ids.update(step.structural.record_ids)
    if step.confidence is not None:
        ids.update(row.record_id for row in step.confidence.request.context.features)
    return tuple(sorted(ids))


def context_at(reversal_direction, at, step):
    """A minimal M4.2 context whose one provenance snapshot covers this step's IDs."""
    ids = _referenced_ids(step)
    provenance = FeatureSnapshot(
        record_id="m86-rev-inputs-" + at.isoformat(), metadata=metadata(at, data_mode=DATA_MODE),
        evaluated_at=at,
        features=(FeatureValue("OR_FAILURE_REV_REPLAY_INPUTS_V1", 1.0, "BOOLEAN", None, ids),),
        feature_version=FEATURES, input_record_ids=ids)
    return StrategyContext(session(DAY), "SYNTH", "EQUITY", reversal_direction, at, (provenance,))


def strategy(break_direction="LONG", *, steps, **changes):
    values = dict(session=session(DAY), symbol="SYNTH", instrument_type="EQUITY",
                  direction=mirror_direction(break_direction), strategy_version=VERSION,
                  definition_reference=DEFINITION, policy=reversal_policy(), steps=steps,
                  record_prefix=PREFIX)
    values.update(changes)
    return OrFailureRevReplayStrategy(**values)


def scope(reversal_direction):
    return TransitionScope(session(DAY), "SYNTH", "EQUITY", reversal_direction, STRATEGY_ID,
                           VERSION, or_failure_rev_replay_rules())


def spec(**changes):
    values = dict(
        dataset_id="M86_OR_FAILURE_REV_SCENARIO_V1", start_date=date(2026, 7, 6),
        end_date=date(2026, 7, 6), symbols=("SYNTH",),
        strategy_versions=((STRATEGY_ID, VERSION),), config_hash=session(DAY).config_hash,
        feature_engine_version=FEATURES, execution_model="CHRONOLOGICAL_SAME_RUNTIME",
        recorded_at=ENDED_AT, code_revision="M86_SUPPLIED_TEST_REVISION")
    values.update(changes)
    return ReplaySpec(**values)


def plan(name):
    """The supplied steps and contexts for one named synthetic scenario."""
    if name == "triggered":
        step = step_at("LONG", ENDED_AT)
        return "LONG", (step,), (context_at("SHORT", ENDED_AT, step),)
    if name == "armed":
        step = step_at("LONG", ENDED_AT, last_trade=None)
        return "LONG", (step,), (context_at("SHORT", ENDED_AT, step),)
    raise AssertionError("unknown supplied scenario")


EXPECTED = {
    "triggered": (("ARMED", None), ("ALERT_TRIGGERED", None)),
    "armed": (("ARMED", None),),
}


async def replay(name, *, database=None):
    """Run one supplied scenario through the M5.3 runner in this process."""
    break_direction, steps, contexts = plan(name)
    if database is not None:
        await db.close_db()
        db.DB_PATH = str(database)
    connection = await db.init_db()
    owner = strategy(break_direction, steps=steps)
    sink = RecordingReplaySink()
    runner = HistoricalReplayRunner(
        spec=spec(), strategy=owner,
        transitions=StateTransitionEngine(scope(mirror_direction(break_direction)),
                                          SQLiteTransitionStore(connection)),
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


async def test_a_clean_supplied_reversal_reports_its_supplied_geometry():
    owner, _, _ = await replay("triggered")
    result = owner.outcome()
    assert result.state == TRIGGERED and result.reasons == ()
    assert owner.stop() == result.risk and owner.targets() == result.targets
    assert owner.confidence() == result.confidence
    assert "CONFIDENCE_FLOOR_UNDEFINED" in result.unavailable
    assert owner.last_assessment().state == TRIGGERED


async def test_a_missing_last_trade_only_arms_the_reversal():
    owner, result, _ = await replay("armed")
    assert owner.current_state() == ARMED
    assert owner.notes() == ()
    assert owner.outcome().gate("LAST_BACK_INSIDE_RANGE").status == "UNKNOWN"


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
    (Path(os.environ["TMPDIR"]) / "m8_6_or_failure_rev_scenarios.json").write_text(rendered + "\n")


# --- supplied rules, records and boundaries ---------------------------------


def test_the_replay_rules_are_exactly_the_m82_rules():
    rules = or_failure_rev_replay_rules()
    reference = reversal_rules()
    assert rules.version == reference.version
    assert rules.initial_state == reference.initial_state == FORMING
    assert rules.allowed == reference.allowed


def test_the_module_defines_no_number_of_its_own():
    from consensus_engine import or_failure_rev_replay

    numbers = {name: value for name, value in vars(or_failure_rev_replay).items()
               if not name.startswith("_") and isinstance(value, (int, float))
               and not isinstance(value, bool)}
    assert numbers == {}


@pytest.mark.parametrize("changes", (
    {"evaluated_at": "2026-07-06T06:50:10"}, {"evaluated_at": None}, {"handoff": None},
    {"handoff": "M81"}, {"breakout_extreme_price": "101.30"}, {"last_trade": "m86-last-trade"},
    {"confirmation_close": 100.5}, {"failure_bar": "m86-failure-bar"},
    {"acceptance": "m86-acceptance"}, {"quote": "m86-quote"}, {"structural": "m86-structural"},
    {"confidence": "m86-confidence"},
))
def test_a_supplied_step_requires_canonical_records(changes):
    with pytest.raises(RecordError):
        step_at("LONG", OTHER, **changes)


def test_supplied_steps_are_immutable():
    step = step_at("LONG", ENDED_AT)
    with pytest.raises(FrozenInstanceError):
        step.evaluated_at = OTHER


@pytest.mark.parametrize("changes", (
    {"instrument_type": "OPTION"}, {"direction": "FLAT"}, {"strategy_version": " "},
    {"strategy_version": "UNKNOWN"}, {"definition_reference": "UNSPECIFIED"},
    {"record_prefix": ""}, {"symbol": "UNKNOWN"}, {"policy": "M82_POLICY"},
    {"session": "2026-07-06"}, {"steps": ()},
    {"steps": [step_at("LONG", ENDED_AT)]}, {"steps": ("TRIGGERED",)},
))
def test_the_replay_owner_requires_complete_supplied_scope(changes):
    values = dict(steps=(step_at("LONG", ENDED_AT),))
    values.update(changes)
    with pytest.raises(RecordError):
        strategy(**values)


def test_supplied_steps_must_be_chronological_and_distinct():
    with pytest.raises(RecordError):
        strategy(steps=(step_at("LONG", ENDED_AT), step_at("LONG", ENDED_AT)))


def test_the_owner_implements_the_shared_strategy_interface():
    owner = strategy(steps=(step_at("LONG", ENDED_AT),))
    assert isinstance(owner, Strategy)
    assert owner.strategy_id == STRATEGY_ID and owner.strategy_version == VERSION
    declared = owner.required_data()
    assert all(isinstance(row, RequiredData) for row in declared)
    assert {row.data_mode for row in declared} == {DATA_MODE}
    assert owner.current_state() == FORMING
    assert owner.stop() is None and owner.targets() == () and owner.confidence() is None


async def test_an_evaluation_outside_this_owner_is_refused():
    step = step_at("LONG", ENDED_AT)
    owner = strategy(steps=(step,))
    for supplied in (context_at("LONG", ENDED_AT, step), "SHORT", None):
        with pytest.raises(RecordError):
            owner.update(supplied)


async def test_an_instant_without_a_supplied_step_is_refused():
    step = step_at("LONG", ENDED_AT)
    owner = strategy(steps=(step,))
    with pytest.raises(RecordError, match="no supplied replay step"):
        owner.update(context_at("SHORT", OTHER, step))


async def test_evaluation_time_cannot_move_backward():
    early, late = step_at("LONG", ENDED_AT), step_at("LONG", OTHER)
    owner = strategy(steps=(early, late))
    owner.update(context_at("SHORT", OTHER, late))
    with pytest.raises(RecordError, match="backward"):
        owner.update(context_at("SHORT", ENDED_AT, early))


async def test_a_caller_cannot_assert_an_invalidation():
    step = step_at("LONG", ENDED_AT)
    owner = strategy(steps=(step,))
    with pytest.raises(RecordError, match="supplied reversal evidence"):
        owner.invalidate(context_at("SHORT", ENDED_AT, step), reason="CALLER_SAYS_SO")


async def test_state_advances_only_after_the_transition_was_recorded():
    step = step_at("LONG", ENDED_AT)
    owner = strategy(steps=(step,))
    changes = owner.update(context_at("SHORT", ENDED_AT, step))
    assert len(changes) == 2
    assert (changes[0].record_id, changes[1].record_id) == (PREFIX + "-001", PREFIX + "-002")
    assert owner.current_state() == FORMING
    assert owner.confirm_recorded() == TRIGGERED


async def test_an_armed_owner_can_be_expired_at_the_supplied_instant():
    step = step_at("LONG", ENDED_AT, last_trade=None)
    owner = strategy(steps=(step,))
    owner.update(context_at("SHORT", ENDED_AT, step))
    assert owner.confirm_recorded() == ARMED
    changes = owner.expire(context_at("SHORT", ENDED_AT, step), reason="EVALUATION_WINDOW_CLOSED")
    assert changes[0].to_state == "EXPIRED"
    assert owner.confirm_recorded() == StrategyState("EXPIRED")
    assert owner.update(context_at("SHORT", ENDED_AT, step)) == ()
    assert owner.notes() == ("SESSION_EXPIRED",)


async def test_a_reset_owner_starts_the_supplied_session_again():
    step = step_at("LONG", ENDED_AT)
    owner = strategy(steps=(step,))
    owner.update(context_at("SHORT", ENDED_AT, step))
    owner.confirm_recorded()
    owner.reset(session(DAY))
    assert owner.current_state() == FORMING
    assert owner.outcome() is None and owner.notes() == ()
    assert owner.update(context_at("SHORT", ENDED_AT, step))[0].record_id == PREFIX + "-001"


async def test_every_replayed_input_and_transition_is_stored_once():
    connection = await db.init_db()
    break_direction, steps, contexts = plan("triggered")
    owner = strategy(break_direction, steps=steps)
    store = ResearchEventStore(connection)
    runner = HistoricalReplayRunner(
        spec=spec(), strategy=owner,
        transitions=StateTransitionEngine(scope(mirror_direction(break_direction)),
                                          SQLiteTransitionStore(connection)),
        store=store, sink=RecordingReplaySink())
    await runner.run(contexts)
    rows = await store.read_all()
    identifiers = [row["record_id"] for row in rows]
    assert len(identifiers) == len(set(identifiers))
    assert {PREFIX + "-001", PREFIX + "-002"} <= set(identifiers)
