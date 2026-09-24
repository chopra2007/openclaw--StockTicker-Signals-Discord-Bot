"""M9.1CM contracts for the AVWAP-on first-pullback connection."""

import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

import consensus_engine.first_pullback_vwap_avwap_stage1_run as subject
from consensus_engine.first_pullback_vwap import SUPPORT_GATE
from consensus_engine.search_run_config import STAGE1_CANDIDATES, TRAINING_TICKERS
from consensus_engine.trade_alerts_models import RecordError
from test_first_pullback_vwap import (
    EVALUATED, STARTED, measurement, mirror, request,
)
from test_first_pullback_vwap_replay import (
    context_at, step_at, strategy as default_strategy,
)
from test_first_pullback_vwap_stage1_run import (
    assessment, complete_events, evaluated, event, policy, retained,
)


def support(direction="LONG", **changes):
    values = dict(
        record_id="m91cm-avwap", definition_reference="M91CM_IMPULSE_ORIGIN_AVWAP_V1",
        symbol="SYNTH", direction=direction, anchor_at=STARTED,
        evaluated_at=EVALUATED, available_at=EVALUATED, coverage_complete=True,
        support_from_avwap_atr=-0.05, input_record_ids=("avwap-bars",),
    )
    values.update(changes)
    return subject.AnchoredVwapSupport(**values)


def avwap_strategy(direction="LONG", *, step, supplied=None):
    base = default_strategy(direction, steps=(step,))
    reading = support(direction) if supplied is None else supplied
    return subject.AvwapFirstPullbackReplayStrategy(
        session=base._session, symbol=base._symbol, instrument_type=base._instrument_type,
        strategy_version=base._version, definition_reference=base._definition,
        policy=base._policy, measurement_policy=base._measurement_policy,
        impulse_started_at=base._impulse_started_at,
        impulse_frozen_at=base._impulse_frozen_at, steps=(step,), record_prefix="m91cm",
        avwap_supports=(reading,))


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_impulse_origin_avwap_can_supply_support_for_either_direction(direction):
    wrong_session_vwap = mirror(102.20, direction)
    step = step_at(direction, EVALUATED,
                   measurement=measurement(direction, vwap=wrong_session_vwap))
    owner = avwap_strategy(direction, step=step)
    changes = owner.update(context_at(direction, EVALUATED, step))
    owner.confirm_recorded()

    result = owner.outcome()
    gate = result.gate(SUPPORT_GATE)
    assert result.state.state == owner.current_state().state == "ALERT_TRIGGERED"
    assert gate.status == "PASS" and gate.observed == -0.05
    assert gate.input_record_ids == ("m91cm-avwap", "avwap-bars")
    assert "AVWAP_QUESTION_UNDEFINED" not in result.unavailable
    assert tuple(row.to_state for row in changes) == ("ARMED", "ALERT_TRIGGERED")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("missing", ("absent", "incomplete", "value"))
def test_session_vwap_support_still_passes_when_avwap_is_unavailable(direction, missing):
    reason = {"absent": "AVWAP_SUPPORT_UNAVAILABLE", "incomplete": "AVWAP_BAR_GAP",
              "value": "AVWAP_VALUE_UNAVAILABLE"}[missing]
    supplied = None if missing == "absent" else support(
        direction, coverage_complete=missing != "incomplete",
        support_from_avwap_atr=None, missing_reason=reason)
    given = request(direction)
    original = subject.evaluate_first_pullback_vwap(given)
    result = subject._avwap_assessment(given, supplied)

    assert result.state.state == "ALERT_TRIGGERED"
    assert result.gate(SUPPORT_GATE) == original.gate(SUPPORT_GATE)
    assert result.gate(SUPPORT_GATE).status == "PASS"
    assert result.unavailable == tuple(
        row for row in original.unavailable if row != "AVWAP_QUESTION_UNDEFINED") + (reason,)
    assert reason in result.as_dict()["unavailable"]
    assert reason in result.to_json()

    if supplied is not None:
        step = step_at(direction, EVALUATED)
        owner = avwap_strategy(direction, step=step, supplied=supplied)
        owner.update(context_at(direction, EVALUATED, step))
        owner.confirm_recorded()
        assert owner.current_state().state == "ALERT_TRIGGERED"
        assert reason in owner.outcome().as_dict()["unavailable"]


def test_missing_avwap_cannot_fill_failed_session_support():
    supplied = support(
        coverage_complete=False, support_from_avwap_atr=None,
        missing_reason="AVWAP_BAR_GAP")
    result = subject._avwap_assessment(
        request(measurement=measurement(vwap=102.20)), supplied)

    gate = result.gate(SUPPORT_GATE)
    assert result.state.state == "ARMED"
    assert gate.status == "UNKNOWN" and gate.observed is None
    assert gate.reason == "AVWAP_BAR_GAP"
    assert gate.input_record_ids[-1] == "avwap-bars"
    assert "AVWAP_BAR_GAP" in result.unavailable


@pytest.mark.parametrize("change", (
    {"anchor_at": EVALUATED},
    {"symbol": "OTHER"},
    {"direction": "SHORT"},
))
def test_avwap_identity_or_anchor_drift_is_refused(change):
    if change.get("anchor_at") == EVALUATED:
        with pytest.raises(RecordError, match="anchor must precede"):
            support(**change)
        return
    with pytest.raises(RecordError, match="does not match"):
        subject._avwap_assessment(request(), support(**change))


def test_avwap_candidate_feeds_resolved_row_to_strict_measurement(monkeypatch):
    monkeypatch.setattr(subject, "AvwapFirstPullbackReplayStrategy", object)
    outcomes = iter((assessment(), *(assessment(state="ARMED", reasons=("NO_EVENT",))
                                     for _ in TRAINING_TICKERS[1:])))
    monkeypatch.setattr(subject, "_evaluate_event", lambda _event: next(outcomes))
    monkeypatch.setattr(subject, "evaluate_playbook_outcome", lambda **_kwargs: evaluated())

    result = subject.run_avwap_first_pullback_stage1(
        retained=retained(), candidate=subject.AVWAP_CANDIDATE,
        events=complete_events(event()), fill_policy=policy(),
        disabled_rules=("ORIGINAL_AVAILABILITY_GAP",))

    assert subject.AVWAP_CANDIDATE.candidate_id == "VWAP_MANDATORY|AVWAP_ON"
    assert result.measurement.trade_count == 1
    assert result.measurement.evaluated_tickers == TRAINING_TICKERS
    assert result.measurement.disabled_rules == ("ORIGINAL_AVAILABILITY_GAP",)
    assert result.resolved[0].tested_axes == ("D-054", "D-055")


@pytest.mark.parametrize("case", ("default_candidate", "held_out_scope", "incomplete"))
def test_runner_refuses_candidate_scope_or_coverage_drift(monkeypatch, case):
    monkeypatch.setattr(subject, "AvwapFirstPullbackReplayStrategy", object)
    monkeypatch.setattr(subject, "_evaluate_event",
                        lambda _event: pytest.fail("invalid input must fail first"))
    kwargs = dict(retained=retained(), candidate=subject.AVWAP_CANDIDATE,
                  events=complete_events(event()), fill_policy=policy())
    if case == "default_candidate":
        kwargs["candidate"] = STAGE1_CANDIDATES[subject.PLAYBOOK][0]
    elif case == "held_out_scope":
        kwargs["retained"] = retained(TRAINING_TICKERS[:-1] + ("GOOGL",))
    else:
        kwargs["events"] = (event(),)
    with pytest.raises(RecordError):
        subject.run_avwap_first_pullback_stage1(**kwargs)


def test_avwap_record_rejects_nonfinite_or_unproved_values():
    with pytest.raises(RecordError, match="finite"):
        support(support_from_avwap_atr=float("nan"))
    with pytest.raises(RecordError, match="incomplete"):
        support(coverage_complete=False)
