"""M6.4 replay and synthetic scenario contracts for `CRVOL_ORB5`.

Every number below is a synthetic fixture supplied by the caller. A replayed
scenario proves the offline contract only: it establishes no provider coverage,
no adopted `M03B_ORB5_V1` rule, no approved catalog or factor roster, no quality
cutoff, no alert, no backtest result, no edge and no permission to act.

The six named scenarios are the clean catalyst breakout, the low-RVOL fakeout,
the resistance attempt that never accepts, the too-wide opening range, the stale
mandatory input and the mirrored short breakout.
"""

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta
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
from consensus_engine.orb5_eligibility import (
    REQUIRED_ROLES, FeatureBinding, eligibility_rules,
)
from consensus_engine.orb5_replay import (
    ARMED, DATA_MODE, EXPIRED, Orb5ReplayStep, Orb5ReplayStrategy, REPLAY_VERSION,
    RULES_VERSION, STRATEGY_ID, CrossingInputs, orb5_replay_rules,
)
from consensus_engine.orb5_risk_confidence import READY, UNAVAILABLE
from consensus_engine.orb5_trigger import TAPE, trigger_rules
from consensus_engine.state_transitions import StateTransitionEngine, TransitionScope
from consensus_engine.strategy_interface import (
    RequiredData, Strategy, StrategyContext, StrategyState,
)
from consensus_engine.trade_alerts_models import RecordError
from consensus_engine.transition_store import SQLiteTransitionStore
from test_orb5_eligibility import (
    BINDINGS, CORE, DAY, OPENING, PARTICIPATION, catalyst, decision,
    policy as supplied_eligibility_policy, snapshot, status,
)
from test_orb5_risk_confidence import composed, confidence_policy
from test_orb5_trigger import (
    CROSS, PRICES, RANGE, TRIGGER, geometry as supplied_geometry, grid, intensity,
    minute_close, observation, trigger_policy,
)
from test_strategy_interface import session


VERSION = "M64_FIXTURE_ONLY_V1"
DEFINITION = "M64_SUPPLIED_FIXTURE_DEFINITION"
PREFIX = "m64-transition"
# One replay keeps one fixed feature-engine version, so every supplied snapshot
# in a scenario is produced by the same declared fixture version.
FEATURES = "M64_REPLAY_FIXTURE_FEATURES_V1"
ARMING = CROSS - timedelta(seconds=1)
LATE = CROSS + timedelta(seconds=31)
RESET_AT = CROSS + timedelta(seconds=40)
NAMES = ("clean", "low_rvol", "resistance", "wide_or", "stale", "short")
# Synthetic supplied replacements only; none of these is an adopted threshold.
LOW_RVOL = {"RVOL_OPEN5_MEAN20_V1": 1.2}
WIDE_RANGE = {"OPENING_RANGE_WIDTH_5M_V1": 1.5}


# --- supplied fixtures ------------------------------------------------------


def bindings():
    """The M6.1 roles bound to this replay's single fixture feature version."""
    return tuple(FeatureBinding(role, BINDINGS[role][0], FEATURES, BINDINGS[role][1][1],
                                BINDINGS[role][2])
                 for role in REQUIRED_ROLES)


def eligibility_policy(**changes):
    values = dict(bindings=bindings())
    values.update(changes)
    return supplied_eligibility_policy(**values)


def snapshots(direction, at, changed=None):
    """One supplied snapshot per producer, all under the fixed fixture version."""
    return tuple(
        snapshot("m64-%s-%s" % (kind, at.isoformat()), (FEATURES, producer[1]),
                 names, direction=direction, changed=changed, at=at)
        for kind, producer, names in (
            ("core", CORE, ("GAP_OPEN_V1", "DAILY_ATR_14_SMA_V1", "SESSION_VWAP_BAR_HLC3_V1")),
            ("participation", PARTICIPATION,
             ("DOLLAR_VOLUME_CLOSE_PROXY20_V1", "RVOL_OPEN5_MEAN20_V1", "PM_RVOL_MEAN20_V1")),
            ("opening", OPENING,
             ("OPENING_RANGE_WIDTH_5M_V1", "OPENING_RANGE_COMPLETE_5M_V1")),
        )
    )


def context_at(direction, at, *, quote_age=0, changed=None, catalysts=True):
    return StrategyContext(
        session(DAY), "SYNTH", "EQUITY", direction, at, snapshots(direction, at, changed),
        decision(direction, at=at, age=quote_age),
        (catalyst("m64-catalyst-" + at.isoformat(), at=at),) if catalysts else ())


def confidence(direction, at):
    return composed(direction, at=at,
                    supplied_policy=confidence_policy(strategy_version=VERSION))


def step_at(direction, at, **changes):
    """One supplied evaluation with its own current preliminary geometry."""
    values = dict(evaluated_at=at, status=status(available_at=at),
                  preliminary=supplied_geometry(direction, crossed_at=at, at=at))
    values.update(changes)
    return Orb5ReplayStep(**values)


def crossing_inputs(direction, *, at=CROSS, previous=None, current=None):
    high, low = RANGE[direction]
    inside, beyond = PRICES[direction][0], PRICES[direction][2]
    return CrossingInputs(
        current=observation("m64-cross-current", at, beyond if current is None else current),
        previous=observation("m64-cross-previous", at - timedelta(seconds=1),
                             inside if previous is None else previous),
        opening_range_high=high, opening_range_low=low, latest_atr=0.4,
        anchor_bar_id="m64-anchor-minute")


def trigger_step(direction, *, at=TRIGGER, prices=None, **changes):
    """One supplied attempt evaluation on the fixed one-second acceptance grid."""
    supplied = supplied_geometry(direction, crossed_at=CROSS, at=at)
    values = dict(
        evaluated_at=at, status=status(available_at=at), preliminary=supplied,
        observations=grid(direction, at=at) if prices is None else grid(direction, at=at,
                                                                       prices=prices),
        participation=intensity(),
        last_trade=observation("m64-last-trade", at, PRICES[direction][2]),
        geometry=supplied, confidence=confidence(direction, at))
    values.update(changes)
    return Orb5ReplayStep(**values)


def strategy(direction="LONG", *, steps, **changes):
    values = dict(session=session(DAY), symbol="SYNTH", instrument_type="EQUITY",
                  direction=direction, strategy_version=VERSION,
                  definition_reference=DEFINITION, eligibility_policy=eligibility_policy(),
                  trigger_policy=trigger_policy(TAPE), steps=steps, record_prefix=PREFIX)
    values.update(changes)
    return Orb5ReplayStrategy(**values)


def scope(direction):
    return TransitionScope(session(DAY), "SYNTH", "EQUITY", direction, STRATEGY_ID, VERSION,
                           orb5_replay_rules())


def spec(**changes):
    values = dict(
        dataset_id="M64_SUPPLIED_SCENARIO_V1", start_date=date(2026, 7, 6),
        end_date=date(2026, 7, 6), symbols=("SYNTH",),
        strategy_versions=((STRATEGY_ID, VERSION),), config_hash=session(DAY).config_hash,
        feature_engine_version=FEATURES, execution_model="CHRONOLOGICAL_SAME_RUNTIME",
        recorded_at=RESET_AT, code_revision="M64_SUPPLIED_TEST_REVISION")
    values.update(changes)
    return ReplaySpec(**values)


# --- the six supplied scenarios ---------------------------------------------


def plan(name):
    """The supplied steps and contexts for one named synthetic scenario."""
    direction = "SHORT" if name == "short" else "LONG"
    opening = (step_at(direction, ARMING),
               step_at(direction, CROSS, crossing=crossing_inputs(direction)))
    if name in ("clean", "short"):
        return direction, opening + (trigger_step(direction),), tuple(
            context_at(direction, at) for at in (ARMING, CROSS, TRIGGER))
    if name in ("low_rvol", "wide_or"):
        changed = LOW_RVOL if name == "low_rvol" else WIDE_RANGE
        return direction, opening + (trigger_step(direction),), tuple(
            context_at(direction, at, changed=changed) for at in (ARMING, CROSS, TRIGGER))
    if name == "resistance":
        # Six of ten samples accept, so the supplied acceptance minimum of seven
        # is never met and the attempt runs out its own deadline instead.
        prices = (PRICES["LONG"][2],) * 6 + (PRICES["LONG"][0],) * 4
        steps = opening + (
            trigger_step(direction, prices=prices),
            trigger_step(direction, at=LATE, prices=prices),
            step_at(direction, RESET_AT, reset_close=minute_close(at=RESET_AT, close=100.5)))
        return direction, steps, tuple(context_at(direction, at)
                                       for at in (ARMING, CROSS, TRIGGER, LATE, RESET_AT))
    if name == "stale":
        return direction, opening + (trigger_step(direction),), (
            context_at(direction, ARMING), context_at(direction, CROSS),
            context_at(direction, TRIGGER, quote_age=5))
    raise AssertionError("unknown supplied scenario")


EXPECTED = {
    "clean": ((("ARMED", None), ("ARMED", "CROSSING_OBSERVED"), ("ALERT_TRIGGERED", None)),
              READY),
    "short": ((("ARMED", None), ("ARMED", "CROSSING_OBSERVED"), ("ALERT_TRIGGERED", None)),
              READY),
    "low_rvol": ((("WATCHING", None),), None),
    "wide_or": ((("WATCHING", None),), None),
    "resistance": ((("ARMED", None), ("ARMED", "CROSSING_OBSERVED"),
                    ("ARMED", "WAITING_FOR_RESET"), ("ARMED", None)), None),
    "stale": ((("ARMED", None), ("ARMED", "CROSSING_OBSERVED"), ("INVALIDATED", None)),
              UNAVAILABLE),
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
    expected, outcome = EXPECTED[name]
    assert recorded_states(result) == expected
    assert tuple(sink.observations) == result.observations
    assert len(result.observations) == len(plan(name)[2])
    if outcome is None:
        assert owner.outcome() is None or owner.outcome().status != READY
    else:
        assert owner.outcome() is not None and owner.outcome().status == outcome
    # No scenario assembles a candidate here; delivery keeps its own owner.
    assert owner.heads_up() is None and owner.actionable() is None


@pytest.mark.parametrize("name", ("clean", "short"))
async def test_a_clean_catalyst_breakout_reports_its_supplied_geometry(name):
    owner, _, _ = await replay(name)
    direction = "SHORT" if name == "short" else "LONG"
    sign = 1 if direction == "LONG" else -1
    result = owner.outcome()
    assert result.status == READY and result.reasons == ()
    assert owner.current_state() == StrategyState("ALERT_TRIGGERED")
    assert owner.stop() == result.risk and owner.targets() == result.targets
    assert owner.confidence() == result.confidence
    assert sign * (result.risk.entry_reference - result.risk.hard_stop) > 0
    assert all(sign * (row.price - result.risk.entry_reference) > 0 for row in result.targets)
    assert "CONFIDENCE_FLOOR_UNDEFINED" in result.unavailable
    assert owner.last_trigger().state == StrategyState("ALERT_TRIGGERED")


@pytest.mark.parametrize("name,gate", (("low_rvol", "OPEN5_RVOL"),
                                       ("wide_or", "OR_WIDTH_ATR_RATIO")))
async def test_a_supplied_gate_below_its_band_never_arms_or_crosses(name, gate):
    owner, result, _ = await replay(name)
    assert owner.current_state() == StrategyState("WATCHING")
    assert owner.last_eligibility().gate(gate).status == "FAIL"
    assert owner.notes() == ("NOT_ARMED:WATCHING",)
    # The supplied crossing observations are present and still open no attempt.
    assert plan(name)[1][1].crossing is not None
    assert owner.last_trigger() is None and owner.outcome() is None
    assert len(recorded_states(result)) == 1


async def test_a_resistance_attempt_waits_for_its_reset_before_arming_again():
    owner, result, _ = await replay("resistance")
    assert recorded_states(result)[-2:] == (("ARMED", "WAITING_FOR_RESET"), ("ARMED", None))
    assert owner.current_state() == ARMED
    # The acceptance window never reached the supplied minimum.
    accepting = [item.as_dict() for item in result.observations]
    assert accepting[2]["transitions"] == []
    assert owner.outcome() is None


async def test_a_stale_mandatory_input_invalidates_the_open_attempt():
    owner, result, _ = await replay("stale")
    assert owner.current_state() == StrategyState("INVALIDATED")
    assert owner.last_trigger().gate("ATTEMPT_ACTIVE").reason == "UNKNOWN_MANDATORY_INPUT"
    assert owner.last_eligibility().state == StrategyState("WATCHING")
    assert owner.outcome().status == UNAVAILABLE
    # The supplied geometry is still reported; an unknown input never passes.
    assert owner.outcome().gate("TRIGGER_ACTIONABLE").status == "UNKNOWN"
    assert owner.outcome().confidence is not None
    assert recorded_states(result)[-1] == ("INVALIDATED", None)


@pytest.mark.parametrize("name", NAMES)
async def test_the_same_supplied_scenario_replays_byte_identically(name, tmp_path):
    _, first, _ = await replay(name)
    _, second, _ = await replay(name, database=tmp_path / (name + "-second.db"))
    assert first.to_json() == second.to_json()
    assert first.fingerprint == second.fingerprint


async def test_the_six_scenarios_record_one_deterministic_proof(tmp_path):
    proof = {"synthetic_only": True, "replay_version": REPLAY_VERSION,
             "definition_reference": DEFINITION, "scenarios": {}}
    for name in NAMES:
        owner, result, _ = await replay(name, database=tmp_path / (name + "-proof.db"))
        outcome = owner.outcome()
        proof["scenarios"][name] = {
            "direction": plan(name)[0],
            "fingerprint": result.fingerprint,
            "states": [list(row) for row in recorded_states(result)],
            "final_state": [owner.current_state().state, owner.current_state().substate],
            "outcome_status": None if outcome is None else outcome.status,
            "outcome_reasons": [] if outcome is None else list(outcome.reasons),
            "notes": list(owner.notes()),
        }
    rendered = json.dumps(proof, sort_keys=True, separators=(",", ":"))
    assert len(rendered.encode()) < 100000
    assert len({row["fingerprint"] for row in proof["scenarios"].values()}) == len(NAMES)
    (Path(os.environ["TMPDIR"]) / "m6_4_orb5_scenarios.json").write_text(rendered + "\n")


# --- supplied rules, records and boundaries ---------------------------------


def test_the_replay_rules_hold_exactly_the_two_milestones_pairs():
    rules = orb5_replay_rules()
    eligibility, trigger = eligibility_rules(), trigger_rules()
    assert rules.version == RULES_VERSION
    assert rules.initial_state == eligibility.initial_state
    assert set(rules.allowed) == set(eligibility.allowed) | set(trigger.allowed)
    assert len(rules.allowed) == len(set(rules.allowed))


def test_the_module_defaults_no_number_of_its_own():
    from consensus_engine import orb5_replay

    numbers = {name: value for name, value in vars(orb5_replay).items()
               if not name.startswith("_") and isinstance(value, (int, float))
               and not isinstance(value, bool)}
    assert numbers == {}


@pytest.mark.parametrize("changes", (
    {"evaluated_at": "2026-07-06T06:50:00"}, {"evaluated_at": datetime(2026, 7, 6, 6, 50)},
    {"status": None}, {"status": "COMPLETE"}, {"preliminary": "READY"},
    {"crossing": "CROSSED"}, {"observations": []}, {"observations": ("m64-sample",)},
    {"participation": "TAPE"}, {"last_trade": "m64-last-trade"}, {"geometry": "READY"},
    {"confidence": "READY"}, {"minute_close": 100.5}, {"reset_close": 100.5},
))
def test_a_supplied_step_requires_canonical_records(changes):
    with pytest.raises(RecordError):
        step_at("LONG", TRIGGER, **changes)


@pytest.mark.parametrize("changes", (
    {"current": None}, {"current": "m64-cross-current"}, {"previous": "m64-cross-previous"},
    {"anchor_bar_id": ""}, {"anchor_bar_id": "UNKNOWN"}, {"anchor_bar_id": None},
))
def test_supplied_crossing_inputs_require_canonical_observations(changes):
    values = dict(current=observation("m64-cross-current", CROSS, PRICES["LONG"][2]),
                  previous=observation("m64-cross-previous", ARMING, PRICES["LONG"][0]),
                  opening_range_high=101.0, opening_range_low=100.0, latest_atr=0.4,
                  anchor_bar_id="m64-anchor-minute")
    values.update(changes)
    with pytest.raises(RecordError):
        CrossingInputs(**values)


def test_supplied_steps_and_crossings_are_immutable():
    step = step_at("LONG", TRIGGER)
    with pytest.raises(FrozenInstanceError):
        step.evaluated_at = CROSS
    with pytest.raises(FrozenInstanceError):
        crossing_inputs("LONG").latest_atr = 0.5


@pytest.mark.parametrize("changes", (
    {"instrument_type": "OPTION"}, {"direction": "FLAT"}, {"strategy_version": " "},
    {"strategy_version": "UNKNOWN"}, {"definition_reference": "UNSPECIFIED"},
    {"record_prefix": ""}, {"symbol": "UNKNOWN"}, {"eligibility_policy": "M61_POLICY"},
    {"trigger_policy": "M62_POLICY"}, {"session": "2026-07-06"}, {"steps": ()},
    {"steps": [step_at("LONG", TRIGGER)]}, {"steps": ("TRIGGER",)},
))
def test_the_replay_owner_requires_complete_supplied_scope(changes):
    values = dict(steps=(step_at("LONG", ARMING),))
    values.update(changes)
    with pytest.raises(RecordError):
        strategy(**values)


def test_supplied_steps_must_be_chronological_and_distinct():
    for steps in ((step_at("LONG", TRIGGER), step_at("LONG", ARMING)),
                  (step_at("LONG", ARMING), step_at("LONG", ARMING))):
        with pytest.raises(RecordError):
            strategy(steps=steps)


def test_the_owner_implements_the_shared_strategy_interface():
    owner = strategy(steps=(step_at("LONG", ARMING),))
    assert isinstance(owner, Strategy)
    assert owner.strategy_id == STRATEGY_ID and owner.strategy_version == VERSION
    declared = owner.required_data()
    assert all(isinstance(row, RequiredData) for row in declared)
    assert {row.name for row in declared} >= {BINDINGS[role][0] for role in REQUIRED_ROLES}
    assert {row.data_mode for row in declared} >= {DATA_MODE}
    assert owner.current_state() == StrategyState("NOT_ELIGIBLE")
    assert owner.stop() is None and owner.targets() == () and owner.confidence() is None


async def test_an_evaluation_outside_this_owner_is_refused():
    owner = strategy(steps=(step_at("LONG", ARMING),))
    for supplied in (context_at("SHORT", ARMING), "ARMING", None):
        with pytest.raises(RecordError):
            owner.update(supplied)


async def test_an_instant_without_a_supplied_step_is_refused():
    owner = strategy(steps=(step_at("LONG", ARMING),))
    with pytest.raises(RecordError, match="no supplied replay step"):
        owner.update(context_at("LONG", TRIGGER))


async def test_evaluation_time_cannot_move_backward():
    steps = (step_at("LONG", ARMING), trigger_step("LONG"))
    owner = strategy(steps=steps)
    owner.update(context_at("LONG", TRIGGER))
    with pytest.raises(RecordError, match="backward"):
        owner.update(context_at("LONG", ARMING))


async def test_state_advances_only_after_the_transition_was_recorded():
    owner = strategy(steps=(step_at("LONG", ARMING),))
    changes = owner.update(context_at("LONG", ARMING))
    assert len(changes) == 1 and changes[0].record_id == PREFIX + "-001"
    assert owner.current_state() == StrategyState("NOT_ELIGIBLE")
    assert owner.confirm_recorded() == ARMED


async def test_a_caller_cannot_assert_an_invalidation_or_an_expiry():
    owner = strategy(steps=(step_at("LONG", ARMING),))
    supplied = context_at("LONG", ARMING)
    with pytest.raises(RecordError, match="supplied attempt evidence"):
        owner.invalidate(supplied, reason="CALLER_SAYS_SO")
    with pytest.raises(RecordError, match="supplied evaluation window"):
        owner.expire(supplied, reason="CALLER_SAYS_SO")


async def test_an_open_attempt_can_be_expired_at_the_supplied_instant():
    direction, steps, contexts = plan("clean")
    owner = strategy(direction, steps=steps)
    owner.update(contexts[0])
    owner.update(contexts[1])
    assert owner.confirm_recorded() == StrategyState("ARMED", "CROSSING_OBSERVED")
    changes = owner.expire(contexts[2], reason="EVALUATION_WINDOW_CLOSED")
    assert changes[0].to_state == "EXPIRED"
    assert owner.confirm_recorded() == EXPIRED
    assert owner.update(contexts[2]) == ()
    assert owner.notes() == ("SESSION_EXPIRED",)


async def test_a_reset_owner_starts_the_supplied_session_again():
    direction, steps, contexts = plan("clean")
    owner = strategy(direction, steps=steps)
    owner.update(contexts[0])
    owner.confirm_recorded()
    owner.reset(session(DAY))
    assert owner.current_state() == StrategyState("NOT_ELIGIBLE")
    assert owner.outcome() is None and owner.notes() == ()
    assert owner.update(contexts[0])[0].record_id == PREFIX + "-001"


async def test_a_crossing_that_is_not_fresh_opens_no_attempt():
    direction = "LONG"
    steps = (step_at(direction, ARMING),
             step_at(direction, CROSS,
                     crossing=crossing_inputs(direction, previous=PRICES[direction][2])))
    owner = strategy(direction, steps=steps)
    owner.update(context_at(direction, ARMING))
    owner.confirm_recorded()
    assert owner.update(context_at(direction, CROSS)) == ()
    assert owner.notes() == ("CROSSING:NOT_CROSSED:NO_FRESH_CROSSING",)
    assert owner.current_state() == ARMED


async def test_a_crossing_observed_at_another_instant_is_refused():
    direction = "LONG"
    steps = (step_at(direction, ARMING),
             step_at(direction, CROSS, crossing=crossing_inputs(direction, at=LATE)))
    owner = strategy(direction, steps=steps)
    owner.update(context_at(direction, ARMING))
    owner.confirm_recorded()
    with pytest.raises(RecordError, match="this evaluation instant"):
        owner.update(context_at(direction, CROSS))


async def test_the_replay_runner_keeps_its_own_fixed_provenance():
    direction, steps, contexts = plan("clean")
    connection = await db.init_db()
    runner = HistoricalReplayRunner(
        spec=spec(strategy_versions=((STRATEGY_ID, "M64_OTHER_VERSION"),)),
        strategy=strategy(direction, steps=steps),
        transitions=StateTransitionEngine(scope(direction), SQLiteTransitionStore(connection)),
        store=ResearchEventStore(connection), sink=RecordingReplaySink())
    with pytest.raises(RecordError, match="strategy version"):
        await runner.run(contexts)


async def test_every_replayed_input_and_transition_is_stored_once():
    connection = await db.init_db()
    direction, steps, contexts = plan("clean")
    owner = strategy(direction, steps=steps)
    store = ResearchEventStore(connection)
    runner = HistoricalReplayRunner(
        spec=spec(), strategy=owner,
        transitions=StateTransitionEngine(scope(direction), SQLiteTransitionStore(connection)),
        store=store, sink=RecordingReplaySink())
    result = await runner.run(contexts)
    rows = await store.read_all()
    identifiers = [row["record_id"] for row in rows]
    assert len(identifiers) == len(set(identifiers))
    for observed in result.observations:
        assert set(observed.input_record_ids) <= set(identifiers)
    assert {PREFIX + "-00%d" % number for number in (1, 2, 3)} <= set(identifiers)
