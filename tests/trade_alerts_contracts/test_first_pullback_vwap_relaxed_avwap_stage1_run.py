"""M9.1CN contracts for the relaxed-VWAP plus AVWAP connection."""

from dataclasses import replace
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

import consensus_engine.first_pullback_vwap_relaxed_avwap_stage1_run as subject
from consensus_engine.first_pullback_vwap import (
    SUPPORT_GATE, VWAP_SIDE_GATE, VWAP_SLOPE_GATE,
)
from consensus_engine.first_pullback_vwap_avwap_stage1_run import AnchoredVwapSupport
from consensus_engine.first_pullback_vwap_stage1_run import FirstPullbackTrainingEvent
from consensus_engine.search_run_config import STAGE1_CANDIDATES, TRAINING_TICKERS
from consensus_engine.trade_alerts_models import RecordError
from test_first_pullback_vwap import EVALUATED, STARTED, measurement, mirror, request, vwap_context
from test_first_pullback_vwap_replay import context_at, step_at, strategy as default_strategy
from test_first_pullback_vwap_stage1_run import (
    assessment, complete_events, evaluated, event, policy, retained,
)


def support(direction="LONG", **changes):
    values = dict(
        record_id="m91cn-avwap", definition_reference="M91CN_IMPULSE_ORIGIN_AVWAP_V1",
        symbol="SYNTH", direction=direction, anchor_at=STARTED,
        evaluated_at=EVALUATED, available_at=EVALUATED, coverage_complete=True,
        support_from_avwap_atr=-0.05, input_record_ids=("avwap-bars",),
    )
    values.update(changes)
    return AnchoredVwapSupport(**values)


def combined_strategy(direction="LONG", *, step, supplied=None):
    base = default_strategy(direction, steps=(step,))
    reading = support(direction) if supplied is None else supplied
    return subject.RelaxedAvwapFirstPullbackReplayStrategy(
        session=base._session, symbol=base._symbol, instrument_type=base._instrument_type,
        strategy_version=base._version, definition_reference=base._definition,
        policy=base._policy, measurement_policy=base._measurement_policy,
        impulse_started_at=base._impulse_started_at,
        impulse_frozen_at=base._impulse_frozen_at, steps=(step,), record_prefix="m91cn",
        avwap_supports=(reading,))


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_relaxed_vwap_and_avwap_support_work_together(direction):
    wrong_slope = -0.02 if direction == "LONG" else 0.02
    step = step_at(
        direction, EVALUATED,
        measurement=measurement(direction, vwap=mirror(102.20, direction)),
        vwap=vwap_context(direction, slope=wrong_slope),
    )
    owner = combined_strategy(direction, step=step)
    changes = owner.update(context_at(direction, EVALUATED, step))
    owner.confirm_recorded()

    result = owner.outcome()
    assert result.state.state == owner.current_state().state == "ALERT_TRIGGERED"
    assert result.gate(SUPPORT_GATE).status == "PASS"
    assert result.gate(SUPPORT_GATE).input_record_ids == ("m91cn-avwap", "avwap-bars")
    assert result.gate(VWAP_SLOPE_GATE).status == "FAIL"
    assert not any(reason.startswith((VWAP_SIDE_GATE, VWAP_SLOPE_GATE))
                   for reason in result.reasons)
    assert tuple(row.to_state for row in changes) == ("ARMED", "ALERT_TRIGGERED")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_missing_avwap_stays_visible_when_session_support_passes(direction):
    reading = support(
        direction, coverage_complete=False, support_from_avwap_atr=None,
        missing_reason="AVWAP_BAR_GAP")
    step = step_at(direction, EVALUATED)
    owner = combined_strategy(direction, step=step, supplied=reading)
    owner.update(context_at(direction, EVALUATED, step))
    owner.confirm_recorded()

    result = owner.outcome()
    assert result.state.state == "ALERT_TRIGGERED"
    assert result.gate(SUPPORT_GATE).status == "PASS"
    assert "AVWAP_BAR_GAP" in result.unavailable
    assert "AVWAP_BAR_GAP" in result.to_json()


def test_missing_avwap_cannot_rescue_failed_session_support():
    reading = support(
        coverage_complete=False, support_from_avwap_atr=None,
        missing_reason="AVWAP_BAR_GAP")
    result = subject._relaxed_avwap_assessment(
        request(measurement=measurement(vwap=102.20)), reading)

    assert result.state.state == "ARMED"
    assert result.gate(SUPPORT_GATE).status == "UNKNOWN"
    assert result.gate(SUPPORT_GATE).reason == "AVWAP_BAR_GAP"
    assert "AVWAP_BAR_GAP" in result.unavailable


def test_relaxed_vwap_does_not_relax_trigger_structure():
    step = step_at("LONG", EVALUATED, last_trade=None)
    owner = combined_strategy(step=step)
    owner.update(context_at("LONG", EVALUATED, step))
    owner.confirm_recorded()

    result = owner.outcome()
    assert result.state.state == "ARMED"
    assert result.gate("REVERSAL_BAR_BREAK").status == "UNKNOWN"


def test_failed_vwap_position_stays_visible_without_veto(monkeypatch):
    strict = subject._avwap_assessment(request(), support())
    gates = tuple(
        replace(row, status="FAIL", reason="LAST_ON_THE_WRONG_SIDE_OF_VWAP")
        if row.name == VWAP_SIDE_GATE else row
        for row in strict.gates
    )
    strict = replace(
        strict, gates=gates,
        reasons=("PRICE_VS_VWAP:FAIL:LAST_ON_THE_WRONG_SIDE_OF_VWAP",))
    monkeypatch.setattr(subject, "_avwap_assessment", lambda _request, _support: strict)

    result = subject._relaxed_avwap_assessment(object(), None)

    assert result.state.state == "ALERT_TRIGGERED"
    assert result.gate(VWAP_SIDE_GATE).status == "FAIL"
    assert result.reasons == ()


def test_combined_candidate_feeds_resolved_row_to_strict_measurement(monkeypatch):
    monkeypatch.setattr(subject, "RelaxedAvwapFirstPullbackReplayStrategy", object)
    outcomes = iter((assessment(), *(assessment(state="ARMED", reasons=("NO_EVENT",))
                                     for _ in TRAINING_TICKERS[1:])))
    monkeypatch.setattr(subject, "_evaluate_event", lambda _event: next(outcomes))
    monkeypatch.setattr(subject, "evaluate_playbook_outcome", lambda **_kwargs: evaluated())

    result = subject.run_relaxed_avwap_first_pullback_stage1(
        retained=retained(), candidate=subject.RELAXED_AVWAP_CANDIDATE,
        events=complete_events(event()), fill_policy=policy(),
        disabled_rules=("ORIGINAL_AVAILABILITY_GAP",))

    assert subject.RELAXED_AVWAP_CANDIDATE.candidate_id == "VWAP_RELAXED|AVWAP_ON"
    assert result.measurement.trade_count == 1
    assert result.measurement.evaluated_tickers == TRAINING_TICKERS
    assert result.measurement.disabled_rules == ("ORIGINAL_AVAILABILITY_GAP",)
    assert result.resolved[0].tested_axes == ("D-054", "D-055")


@pytest.mark.parametrize("case", ("wrong_candidate", "held_out_scope", "incomplete"))
def test_runner_refuses_candidate_scope_or_coverage_drift(monkeypatch, case):
    monkeypatch.setattr(subject, "RelaxedAvwapFirstPullbackReplayStrategy", object)
    monkeypatch.setattr(subject, "_evaluate_event",
                        lambda _event: pytest.fail("invalid input must fail first"))
    kwargs = dict(retained=retained(), candidate=subject.RELAXED_AVWAP_CANDIDATE,
                  events=complete_events(event()), fill_policy=policy())
    if case == "wrong_candidate":
        kwargs["candidate"] = STAGE1_CANDIDATES[subject.PLAYBOOK][0]
    elif case == "held_out_scope":
        kwargs["retained"] = retained(TRAINING_TICKERS[:-1] + ("GOOGL",))
    else:
        kwargs["events"] = (event(),)
    with pytest.raises(RecordError):
        subject.run_relaxed_avwap_first_pullback_stage1(**kwargs)


def test_event_driver_requires_combined_replay_owner():
    supplied = FirstPullbackTrainingEvent(
        ticker="NVDA", session="2026-01-05", strategy=object(), contexts=(),
        trades=(), quotes=())
    with pytest.raises(RecordError, match="RelaxedAvwapFirstPullbackReplayStrategy"):
        subject._evaluate_event(supplied)
