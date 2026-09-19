"""M7.5 replay and synthetic scenario contracts for `HOD_COMP_RS`.

Every number below is a synthetic fixture supplied by the caller. A replayed
scenario proves the offline contract only: it establishes no provider coverage,
no adopted `HOD_COMP_RS` rule, no approved stop, target or factor roster, no
quality cutoff, no alert, no backtest result, no edge and no permission to act.

The five named scenarios are the clean compression break, its mirrored short
twin, the failed break that never accepts, the RS-weak case that never arms and
the stale extension that already ran too far.
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
from consensus_engine.hod_comp_rs_replay import (
    ARMED, CrossingInputs, DATA_MODE, EXPIRED, HodCompRsReplayStep, HodCompRsReplayStrategy,
    NOTICED, REPLAY_VERSION, RULES_VERSION, STRATEGY_ID, StructureInputs,
    hod_comp_rs_replay_rules,
)
from consensus_engine.hod_comp_rs_risk_confidence import READY, REJECTED
from consensus_engine.hod_comp_rs_trigger import HEADS_UP, TAPE, trigger_rules
from consensus_engine.rs_trend_eligibility import (
    REQUIRED_ROLES, FeatureBinding, rs_trend_rules,
)
from consensus_engine.state_transitions import StateTransitionEngine, TransitionScope
from consensus_engine.strategy_interface import (
    RequiredData, Strategy, StrategyContext, StrategyState,
)
from consensus_engine.trade_alerts_models import RecordError
from consensus_engine.transition_store import SQLiteTransitionStore
from test_hod_comp_rs_risk_confidence import (
    confidence_policy, composed, history, structural, suppression_policy,
)
from test_hod_comp_rs_trigger import (
    ATR, BOUNDARY, COMPRESSION as COIL, CROSS, EARLY, PRICES, REFERENCE, SEVEN, SIX, TRIGGER,
    distance, extension, flip, grid, intensity, minute_close, observation, trigger_policy,
)
from test_rs_trend_eligibility import (
    BINDINGS, COMPRESSION as COMPRESSION_GROUP, CONTEXT as CONTEXT_GROUP, DAY,
    RS as RS_GROUP, decision, policy as supplied_eligibility_policy, snapshot, status,
)
from test_strategy_interface import session


VERSION = "M75_FIXTURE_ONLY_V1"
DEFINITION = "M75_SUPPLIED_FIXTURE_DEFINITION"
PREFIX = "m75-transition"
# One replay keeps one fixed feature-engine version, so every supplied snapshot
# in a scenario is produced by the same declared fixture version.
FEATURES = "M75_REPLAY_FIXTURE_FEATURES_V1"
ARMING = CROSS - timedelta(minutes=2)
LATE = CROSS + timedelta(seconds=31)
RESET_AT = CROSS + timedelta(seconds=40)
NAMES = ("clean", "short", "failed_break", "rs_weak", "stale_extension")
# Synthetic supplied replacements only; neither is an adopted threshold.
WEAK_RS = {"RS_LOOKBACK_V1": 0.001}
FAR_TRADE = 101.25


# --- supplied fixtures ------------------------------------------------------


def bindings():
    """The M7.2 roles bound to this replay's single fixture feature version."""
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
        snapshot(group, direction=direction, changed=changed, at=at,
                 record_id="m75-%s-%s" % (kind, at.isoformat()), feature_version=FEATURES)
        for kind, group in (("context", CONTEXT_GROUP), ("rs", RS_GROUP),
                            ("compression", COMPRESSION_GROUP))
    )


def context_at(direction, at, *, changed=None):
    return StrategyContext(session(DAY), "SYNTH", "EQUITY", direction, at,
                           snapshots(direction, at, changed), decision(direction, at=at), ())


def confidence_at(direction, at):
    return composed(direction, at=at,
                    supplied_policy=confidence_policy(strategy_version=VERSION))


def structure_inputs(direction, *, at=EARLY, **changes):
    """The caller's own frozen compression, reference extreme and ATR."""
    high, low = COIL[direction]
    values = dict(frozen_at=at, reference_extreme=REFERENCE[direction], compression_high=high,
                  compression_low=low, latest_atr=ATR, anchor_bar_id="m75-anchor-minute",
                  input_record_ids=("m75-compression-window", "m75-reference-freeze"))
    values.update(changes)
    return StructureInputs(**values)


def step_at(direction, at, **changes):
    """One supplied evaluation with only its mandatory status facts."""
    values = dict(evaluated_at=at, status=status(available_at=at))
    values.update(changes)
    return HodCompRsReplayStep(**values)


def notice_step(direction, *, at=EARLY, **changes):
    """One supplied pre-crossing evaluation of an approaching structure."""
    values = dict(structure=structure_inputs(direction, at=at), distance=distance(at=at),
                  last_trade=observation("m75-notice-trade", at,
                                         flip(PRICES["LONG"][0], direction)))
    values.update(changes)
    return step_at(direction, at, **values)


def crossing_inputs(direction, *, at=CROSS, previous=None, current=None, structure=None):
    inside, beyond = PRICES[direction][0], PRICES[direction][2]
    return CrossingInputs(
        current=observation("m75-cross-current", at, beyond if current is None else current),
        previous=observation("m75-cross-previous", at - timedelta(seconds=1),
                             inside if previous is None else previous),
        structure=structure_inputs(direction) if structure is None else structure)


def crossing_step(direction, *, at=CROSS, **changes):
    values = dict(crossing=crossing_inputs(direction, at=at))
    values.update(changes)
    return step_at(direction, at, **values)


def trigger_step(direction, *, at=TRIGGER, prices=SEVEN, last_price=None, **changes):
    """One supplied structure evaluation on the fixed one-second acceptance grid."""
    values = dict(
        observations=grid(direction, at=at, prices=prices, prefix="m75-sample"),
        intensity=intensity(),
        last_trade=observation("m75-last-trade", at,
                               PRICES[direction][2] if last_price is None
                               else flip(last_price, direction)),
        extension=extension(at=at), structural=structural(direction, at=at),
        confidence=confidence_at(direction, at), history=history(at=at))
    values.update(changes)
    return step_at(direction, at, **values)


def strategy(direction="LONG", *, steps, **changes):
    values = dict(session=session(DAY), symbol="SYNTH", instrument_type="EQUITY",
                  direction=direction, strategy_version=VERSION,
                  definition_reference=DEFINITION, eligibility_policy=eligibility_policy(),
                  trigger_policy=trigger_policy(TAPE),
                  suppression_policy=suppression_policy(), steps=steps, record_prefix=PREFIX)
    values.update(changes)
    return HodCompRsReplayStrategy(**values)


def scope(direction):
    return TransitionScope(session(DAY), "SYNTH", "EQUITY", direction, STRATEGY_ID, VERSION,
                           hod_comp_rs_replay_rules())


def spec(**changes):
    values = dict(
        dataset_id="M75_SUPPLIED_SCENARIO_V1", start_date=date(2026, 7, 6),
        end_date=date(2026, 7, 6), symbols=("SYNTH",),
        strategy_versions=((STRATEGY_ID, VERSION),), config_hash=session(DAY).config_hash,
        feature_engine_version=FEATURES, execution_model="CHRONOLOGICAL_SAME_RUNTIME",
        recorded_at=RESET_AT, code_revision="M75_SUPPLIED_TEST_REVISION")
    values.update(changes)
    return ReplaySpec(**values)


# --- the five supplied scenarios --------------------------------------------


def plan(name):
    """The supplied steps and contexts for one named synthetic scenario."""
    direction = "SHORT" if name == "short" else "LONG"
    opening = (step_at(direction, ARMING), notice_step(direction),
               crossing_step(direction))
    instants = [ARMING, EARLY, CROSS]
    if name in ("clean", "short"):
        steps = opening + (trigger_step(direction),)
        instants.append(TRIGGER)
    elif name == "failed_break":
        # Six of ten samples accept, so the supplied share is never met and the
        # structure runs out its own deadline before a supplied close resets it.
        steps = opening + (
            trigger_step(direction, prices=SIX),
            trigger_step(direction, at=LATE, prices=SIX),
            step_at(direction, RESET_AT,
                    reset_close=minute_close(at=RESET_AT, close=100.80)))
        instants += [TRIGGER, LATE, RESET_AT]
    elif name == "rs_weak":
        steps = opening
    elif name == "stale_extension":
        steps = opening + (trigger_step(direction, last_price=FAR_TRADE),)
        instants.append(TRIGGER)
    else:
        raise AssertionError("unknown supplied scenario")
    changed = WEAK_RS if name == "rs_weak" else None
    return direction, steps, tuple(context_at(direction, at, changed=changed)
                                   for at in instants)


EXPECTED = {
    "clean": ((("ARMED", None), ("ARMED", HEADS_UP), ("ARMED", "CROSSING_OBSERVED"),
               ("ALERT_TRIGGERED", None)), READY),
    "short": ((("ARMED", None), ("ARMED", HEADS_UP), ("ARMED", "CROSSING_OBSERVED"),
               ("ALERT_TRIGGERED", None)), READY),
    "failed_break": ((("ARMED", None), ("ARMED", HEADS_UP), ("ARMED", "CROSSING_OBSERVED"),
                      ("ARMED", "WAITING_FOR_RESET"), ("ARMED", None)), None),
    # Every supplied setup gate still passes, so the coil is forming; only the
    # supplied relative strength keeps it short of ARMED.
    "rs_weak": ((("SETUP_FORMING", None),), None),
    "stale_extension": ((("ARMED", None), ("ARMED", HEADS_UP),
                         ("ARMED", "CROSSING_OBSERVED")), REJECTED),
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
async def test_a_clean_compression_break_reports_its_supplied_geometry(name):
    owner, _, _ = await replay(name)
    direction = "SHORT" if name == "short" else "LONG"
    sign = 1 if direction == "LONG" else -1
    result = owner.outcome()
    assert result.status == READY and result.reasons == ()
    assert owner.current_state() == StrategyState("ALERT_TRIGGERED")
    assert owner.stop() == result.risk and owner.targets() == result.targets
    assert owner.confidence() == result.confidence
    assert result.suppression_reasons == ()
    assert sign * (result.risk.entry_reference - result.risk.hard_stop) > 0
    assert all(sign * (row.price - result.risk.entry_reference) > 0 for row in result.targets)
    assert "CONFIDENCE_FLOOR_UNDEFINED" in result.unavailable
    assert owner.last_trigger().state == StrategyState("ALERT_TRIGGERED")
    assert result.structure.boundary == BOUNDARY[direction]


@pytest.mark.parametrize("name", ("clean", "short"))
async def test_the_supplied_notice_precedes_the_crossing_it_describes(name):
    """The heads-up is a notice about one approaching structure, not a trigger."""
    direction, steps, contexts = plan(name)
    owner = strategy(direction, steps=steps)
    owner.update(contexts[0])
    assert owner.confirm_recorded() == ARMED
    changes = owner.update(contexts[1])
    assert changes[0].to_substate == HEADS_UP
    assert changes[0].metadata.data_mode.endswith("TRIGGER_INPUTS")
    assert owner.last_notice().state == NOTICED
    assert owner.last_notice().gate("HEADS_UP_BEFORE_BOUNDARY").status == "PASS"
    assert owner.confirm_recorded() == NOTICED
    assert owner.outcome() is None and owner.last_trigger() is None
    # The frozen structure the notice described is the one the crossing opens.
    owner.update(contexts[2])
    owner.confirm_recorded()
    assert owner.current_state() == StrategyState("ARMED", "CROSSING_OBSERVED")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("changes", ({"reference_extreme": 101.05}, {"latest_atr": ATR * 2}))
async def test_a_changed_crossing_structure_after_a_heads_up_is_refused(direction, changes):
    """A noticed boundary cannot be walked by a later changed price or ATR."""
    supplied = dict(changes)
    if "reference_extreme" in supplied:
        supplied["reference_extreme"] = flip(supplied["reference_extreme"], direction)
    changed = structure_inputs(direction, **supplied)
    steps = (step_at(direction, ARMING), notice_step(direction),
             crossing_step(direction, crossing=crossing_inputs(direction, structure=changed)))
    owner = strategy(direction, steps=steps)
    owner.update(context_at(direction, ARMING))
    owner.confirm_recorded()
    owner.update(context_at(direction, EARLY))
    assert owner.confirm_recorded() == NOTICED
    noticed = owner.noticed_structure()
    assert noticed.boundary == BOUNDARY[direction]
    with pytest.raises(RecordError, match="noticed frozen structure cannot change"):
        owner.update(context_at(direction, CROSS))
    # The notice still stands on exactly the structure it described.
    assert owner.current_state() == NOTICED
    assert owner.noticed_structure() == noticed


@pytest.mark.parametrize("name", ("clean", "short"))
async def test_the_noticed_structure_is_kept_only_while_the_notice_stands(name):
    direction, steps, contexts = plan(name)
    owner = strategy(direction, steps=steps)
    owner.update(contexts[0])
    assert owner.confirm_recorded() == ARMED
    assert owner.noticed_structure() is None
    owner.update(contexts[1])
    assert owner.confirm_recorded() == NOTICED
    assert owner.noticed_structure().boundary == BOUNDARY[direction]
    # The crossing opens that same structure, and the M7.3 owner holds it after.
    owner.update(contexts[2])
    owner.confirm_recorded()
    assert owner.current_state() == StrategyState("ARMED", "CROSSING_OBSERVED")
    assert owner.noticed_structure() is None


async def test_a_failed_break_waits_for_its_reset_before_arming_again():
    owner, result, _ = await replay("failed_break")
    assert recorded_states(result)[-2:] == (("ARMED", "WAITING_FOR_RESET"), ("ARMED", None))
    assert owner.current_state() == ARMED
    # The acceptance window never reached the supplied minimum.
    observed = [item.as_dict() for item in result.observations]
    assert observed[3]["transitions"] == []
    assert owner.outcome() is None


async def test_a_supplied_rs_value_below_its_band_never_arms_or_crosses():
    owner, result, _ = await replay("rs_weak")
    assert owner.current_state() == StrategyState("SETUP_FORMING")
    assert owner.last_eligibility().gate("RS_TREND").status == "FAIL"
    assert owner.last_eligibility().gate("RS_TREND").reason == "RS_BELOW_DIRECTIONAL_MINIMUM"
    assert owner.notes() == ("NOT_ARMED:SETUP_FORMING",)
    # The supplied structure and crossing are present and still open nothing.
    assert plan("rs_weak")[1][1].structure is not None
    assert plan("rs_weak")[1][2].crossing is not None
    assert owner.last_notice() is None and owner.last_trigger() is None
    assert len(recorded_states(result)) == 1


async def test_a_stale_extension_refuses_the_composed_outcome():
    owner, result, _ = await replay("stale_extension")
    assert owner.current_state() == StrategyState("ARMED", "CROSSING_OBSERVED")
    assert owner.last_trigger().gate("EXTENSION_NOT_STALE").status == "FAIL"
    assert owner.last_trigger().gate("EXTENSION_NOT_STALE").reason == "EXTENSION_ABOVE_LIMIT"
    result_outcome = owner.outcome()
    assert result_outcome.status == REJECTED
    assert result_outcome.gate("TRIGGER_ACTIONABLE").reason == (
        "TRIGGER_NOT_ACTIONABLE_EXTENSION_NOT_STALE")
    # The supplied stop and confidence are still reported beside the refusal.
    assert result_outcome.risk is not None and result_outcome.confidence is not None
    assert owner.notes() == ("NO_STATE_CHANGE:ARMED",)
    assert recorded_states(result)[-1] == ("ARMED", "CROSSING_OBSERVED")


@pytest.mark.parametrize("name", NAMES)
async def test_the_same_supplied_scenario_replays_byte_identically(name, tmp_path):
    _, first, _ = await replay(name)
    _, second, _ = await replay(name, database=tmp_path / (name + "-second.db"))
    assert first.to_json() == second.to_json()
    assert first.fingerprint == second.fingerprint


async def test_the_five_scenarios_record_one_deterministic_proof(tmp_path):
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
            "suppression_reasons": [] if outcome is None else list(outcome.suppression_reasons),
            "notes": list(owner.notes()),
        }
    rendered = json.dumps(proof, sort_keys=True, separators=(",", ":"))
    assert len(rendered.encode()) < 100000
    assert len({row["fingerprint"] for row in proof["scenarios"].values()}) == len(NAMES)
    (Path(os.environ["TMPDIR"]) / "m7_5_hod_comp_rs_scenarios.json").write_text(rendered + "\n")


# --- supplied rules, records and boundaries ---------------------------------


def test_the_replay_rules_hold_exactly_the_two_milestones_pairs():
    rules = hod_comp_rs_replay_rules()
    eligibility, trigger = rs_trend_rules(), trigger_rules()
    assert rules.version == RULES_VERSION
    assert rules.initial_state == eligibility.initial_state
    assert set(rules.allowed) == set(eligibility.allowed) | set(trigger.allowed)
    assert len(rules.allowed) == len(set(rules.allowed))


def test_the_module_defaults_no_number_of_its_own():
    from consensus_engine import hod_comp_rs_replay

    numbers = {name: value for name, value in vars(hod_comp_rs_replay).items()
               if not name.startswith("_") and isinstance(value, (int, float))
               and not isinstance(value, bool)}
    assert numbers == {}


@pytest.mark.parametrize("changes", (
    {"evaluated_at": "2026-07-06T06:50:00"}, {"evaluated_at": datetime(2026, 7, 6, 6, 50)},
    {"status": None}, {"status": "COMPLETE"}, {"structure": "COIL"}, {"distance": 0.125},
    {"crossing": "CROSSED"}, {"observations": []}, {"observations": ("m75-sample",)},
    {"intensity": "TAPE"}, {"last_trade": "m75-last-trade"}, {"extension": 0.46},
    {"minute_close": 100.8}, {"reset_close": 100.8}, {"structural": "READY"},
    {"confidence": "READY"}, {"history": ()},
))
def test_a_supplied_step_requires_canonical_records(changes):
    with pytest.raises(RecordError):
        step_at("LONG", TRIGGER, **changes)


@pytest.mark.parametrize("changes", (
    {"anchor_bar_id": ""}, {"anchor_bar_id": "UNKNOWN"}, {"anchor_bar_id": None},
    {"input_record_ids": ["m75-compression-window"]}, {"input_record_ids": (" ",)},
    {"at": datetime(2026, 7, 6, 6, 49)},
))
def test_supplied_structure_inputs_require_explicit_facts(changes):
    with pytest.raises(RecordError):
        structure_inputs("LONG", **changes)


@pytest.mark.parametrize("changes", (
    {"current": None}, {"current": "m75-cross-current"}, {"previous": "m75-cross-previous"},
    {"structure": "COIL"}, {"structure": None},
))
def test_supplied_crossing_inputs_require_canonical_observations(changes):
    values = dict(current=observation("m75-cross-current", CROSS, PRICES["LONG"][2]),
                  previous=observation("m75-cross-previous", ARMING, PRICES["LONG"][0]),
                  structure=structure_inputs("LONG"))
    values.update(changes)
    with pytest.raises(RecordError):
        CrossingInputs(**values)


def test_supplied_steps_and_structures_are_immutable():
    step = trigger_step("LONG")
    with pytest.raises(FrozenInstanceError):
        step.evaluated_at = CROSS
    with pytest.raises(FrozenInstanceError):
        structure_inputs("LONG").latest_atr = 0.5
    with pytest.raises(FrozenInstanceError):
        crossing_inputs("LONG").current = None


@pytest.mark.parametrize("changes", (
    {"instrument_type": "OPTION"}, {"direction": "FLAT"}, {"strategy_version": " "},
    {"strategy_version": "UNKNOWN"}, {"definition_reference": "UNSPECIFIED"},
    {"record_prefix": ""}, {"symbol": "UNKNOWN"}, {"eligibility_policy": "M72_POLICY"},
    {"trigger_policy": "M73_POLICY"}, {"suppression_policy": "M74_POLICY"},
    {"session": "2026-07-06"}, {"steps": ()}, {"steps": [step_at("LONG", TRIGGER)]},
    {"steps": ("TRIGGER",)},
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
    owner = strategy(steps=(step_at("LONG", ARMING), trigger_step("LONG")))
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
    with pytest.raises(RecordError, match="supplied structure evidence"):
        owner.invalidate(supplied, reason="CALLER_SAYS_SO")
    with pytest.raises(RecordError, match="supplied evaluation window"):
        owner.expire(supplied, reason="CALLER_SAYS_SO")


async def test_an_open_structure_can_be_expired_at_the_supplied_instant():
    direction, steps, contexts = plan("clean")
    owner = strategy(direction, steps=steps)
    for context in contexts[:3]:
        owner.update(context)
        owner.confirm_recorded()
    assert owner.current_state() == StrategyState("ARMED", "CROSSING_OBSERVED")
    changes = owner.expire(contexts[3], reason="EVALUATION_WINDOW_CLOSED")
    assert changes[0].to_state == "EXPIRED"
    assert owner.confirm_recorded() == EXPIRED
    assert owner.update(contexts[3]) == ()
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


async def test_a_crossing_that_is_not_fresh_opens_no_structure():
    direction = "LONG"
    steps = (step_at(direction, ARMING),
             crossing_step(direction, crossing=crossing_inputs(
                 direction, previous=PRICES[direction][2])))
    owner = strategy(direction, steps=steps)
    owner.update(context_at(direction, ARMING))
    owner.confirm_recorded()
    assert owner.update(context_at(direction, CROSS)) == ()
    assert owner.notes() == ("CROSSING:NOT_CROSSED:NO_FRESH_CROSSING",)
    assert owner.current_state() == ARMED


async def test_a_crossing_observed_at_another_instant_is_refused():
    direction = "LONG"
    steps = (step_at(direction, ARMING),
             crossing_step(direction, crossing=crossing_inputs(direction, at=LATE)))
    owner = strategy(direction, steps=steps)
    owner.update(context_at(direction, ARMING))
    owner.confirm_recorded()
    with pytest.raises(RecordError, match="this evaluation instant"):
        owner.update(context_at(direction, CROSS))


async def test_an_armed_instant_without_a_supplied_structure_proposes_nothing():
    owner = strategy(steps=(step_at("LONG", ARMING), step_at("LONG", CROSS)))
    owner.update(context_at("LONG", ARMING))
    owner.confirm_recorded()
    assert owner.update(context_at("LONG", CROSS)) == ()
    assert owner.notes() == ("NO_SUPPLIED_STRUCTURE",)


async def test_the_replay_runner_keeps_its_own_fixed_provenance():
    direction, steps, contexts = plan("clean")
    connection = await db.init_db()
    runner = HistoricalReplayRunner(
        spec=spec(strategy_versions=((STRATEGY_ID, "M75_OTHER_VERSION"),)),
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
    assert {PREFIX + "-00%d" % number for number in (1, 2, 3, 4)} <= set(identifiers)
