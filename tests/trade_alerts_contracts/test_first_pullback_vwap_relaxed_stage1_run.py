"""M9.1CL contracts for the relaxed-VWAP first-pullback connection."""

from dataclasses import replace

import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

import consensus_engine.first_pullback_vwap_relaxed_stage1_run as subject
from consensus_engine.first_pullback_vwap import VWAP_SIDE_GATE, VWAP_SLOPE_GATE
from consensus_engine.first_pullback_vwap_stage1_run import FirstPullbackTrainingEvent
from consensus_engine.search_run_config import STAGE1_CANDIDATES, TRAINING_TICKERS
from consensus_engine.strategy_interface import StrategyState
from consensus_engine.trade_alerts_models import RecordError
from test_first_pullback_vwap import EVALUATED, vwap_context
from test_first_pullback_vwap_replay import (
    context_at, step_at, strategy as default_strategy,
)
from test_first_pullback_vwap_stage1_run import (
    assessment, complete_events, evaluated, event, policy, retained,
)


def relaxed_strategy(direction="LONG", *, step):
    base = default_strategy(direction, steps=(step,))
    return subject.RelaxedVwapFirstPullbackReplayStrategy(
        session=base._session, symbol=base._symbol, instrument_type=base._instrument_type,
        strategy_version=base._version, definition_reference=base._definition,
        policy=base._policy, measurement_policy=base._measurement_policy,
        impulse_started_at=base._impulse_started_at,
        impulse_frozen_at=base._impulse_frozen_at, steps=(step,), record_prefix="m91cl")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_wrong_vwap_slope_stays_visible_but_does_not_gate(direction):
    wrong_slope = -0.02 if direction == "LONG" else 0.02
    step = step_at(direction, EVALUATED,
                   vwap=vwap_context(direction, slope=wrong_slope))
    owner = relaxed_strategy(direction, step=step)
    changes = owner.update(context_at(direction, EVALUATED, step))
    owner.confirm_recorded()

    result = owner.outcome()
    assert result.state.state == owner.current_state().state == "ALERT_TRIGGERED"
    assert result.gate(VWAP_SIDE_GATE).status == "PASS"
    assert result.gate(VWAP_SLOPE_GATE).status == "FAIL"
    assert not any(reason.startswith((VWAP_SIDE_GATE, VWAP_SLOPE_GATE))
                   for reason in result.reasons)
    assert tuple(row.to_state for row in changes) == ("ARMED", "ALERT_TRIGGERED")


def test_missing_vwap_slope_stays_visible_without_being_filled():
    step = step_at("LONG", EVALUATED, vwap=vwap_context(
        "LONG", slope=None, missing_reason="NO_SLOPE_COVERAGE"))
    owner = relaxed_strategy(step=step)
    owner.update(context_at("LONG", EVALUATED, step))
    owner.confirm_recorded()

    result = owner.outcome()
    slope = result.gate(VWAP_SLOPE_GATE)
    assert result.state.state == "ALERT_TRIGGERED"
    assert slope.status == "UNKNOWN" and slope.observed is None
    assert slope.reason == "NO_SLOPE_COVERAGE"


def test_failed_vwap_position_is_visible_but_not_a_veto(monkeypatch):
    step = step_at("LONG", EVALUATED)
    owner = default_strategy(steps=(step,))
    owner.update(context_at("LONG", EVALUATED, step))
    owner.confirm_recorded()
    strict = owner.outcome()
    gates = tuple(
        replace(row, status="FAIL", reason="LAST_ON_THE_WRONG_SIDE_OF_VWAP")
        if row.name == VWAP_SIDE_GATE else row
        for row in strict.gates
    )
    strict = replace(
        strict, state=StrategyState("ARMED"), gates=gates,
        reasons=("PRICE_VS_VWAP:FAIL:LAST_ON_THE_WRONG_SIDE_OF_VWAP",))
    monkeypatch.setattr(subject, "evaluate_first_pullback_vwap", lambda _request: strict)

    result = subject._relaxed_vwap_assessment(object())

    assert result.state.state == "ALERT_TRIGGERED"
    assert result.gate(VWAP_SIDE_GATE).status == "FAIL"
    assert result.reasons == ()


def test_relaxing_vwap_does_not_relax_the_trigger_structure():
    step = step_at("LONG", EVALUATED, last_trade=None)
    owner = relaxed_strategy(step=step)
    owner.update(context_at("LONG", EVALUATED, step))
    owner.confirm_recorded()

    result = owner.outcome()
    assert result.state.state == owner.current_state().state == "ARMED"
    assert result.gate(VWAP_SIDE_GATE).status == "UNKNOWN"
    assert result.gate("REVERSAL_BAR_BREAK").status == "UNKNOWN"


def test_relaxed_candidate_feeds_resolved_row_to_strict_measurement(monkeypatch):
    monkeypatch.setattr(subject, "RelaxedVwapFirstPullbackReplayStrategy", object)
    outcomes = iter((assessment(), *(assessment(state="ARMED", reasons=("NO_EVENT",))
                                     for _ in TRAINING_TICKERS[1:])))
    monkeypatch.setattr(subject, "_evaluate_event", lambda _event: next(outcomes))
    monkeypatch.setattr(subject, "evaluate_playbook_outcome", lambda **_kwargs: evaluated())

    result = subject.run_relaxed_vwap_first_pullback_stage1(
        retained=retained(), candidate=subject.RELAXED_CANDIDATE,
        events=complete_events(event()), fill_policy=policy(),
        disabled_rules=("ORIGINAL_AVAILABILITY_GAP",))

    assert subject.RELAXED_CANDIDATE.candidate_id == "VWAP_RELAXED|AVWAP_OFF"
    assert result.measurement.trade_count == 1
    assert result.measurement.evaluated_tickers == TRAINING_TICKERS
    assert result.measurement.disabled_rules == ("ORIGINAL_AVAILABILITY_GAP",)
    assert result.resolved[0].tested_axes == ("D-054", "D-055")


@pytest.mark.parametrize("case", ("default_candidate", "held_out_scope", "incomplete"))
def test_runner_refuses_candidate_scope_or_coverage_drift(monkeypatch, case):
    monkeypatch.setattr(subject, "RelaxedVwapFirstPullbackReplayStrategy", object)
    monkeypatch.setattr(subject, "_evaluate_event",
                        lambda _event: pytest.fail("invalid input must fail first"))
    kwargs = dict(retained=retained(), candidate=subject.RELAXED_CANDIDATE,
                  events=complete_events(event()), fill_policy=policy())
    if case == "default_candidate":
        kwargs["candidate"] = STAGE1_CANDIDATES[subject.PLAYBOOK][0]
    elif case == "held_out_scope":
        kwargs["retained"] = retained(TRAINING_TICKERS[:-1] + ("GOOGL",))
    else:
        kwargs["events"] = (event(),)
    with pytest.raises(RecordError):
        subject.run_relaxed_vwap_first_pullback_stage1(**kwargs)


def test_event_driver_requires_the_relaxed_replay_owner():
    supplied = FirstPullbackTrainingEvent(
        ticker="NVDA", session="2026-01-05", strategy=object(), contexts=(),
        trades=(), quotes=())
    with pytest.raises(RecordError, match="RelaxedVwapFirstPullbackReplayStrategy"):
        subject._evaluate_event(supplied)
