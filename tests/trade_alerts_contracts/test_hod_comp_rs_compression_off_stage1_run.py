"""M9.1CI contracts for the HOD-compression compression-off connection."""

from datetime import datetime, timezone
from types import SimpleNamespace
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

import consensus_engine.hod_comp_rs_compression_off_stage1_run as subject
from consensus_engine.fill_cost_model import FillCostPolicy, POLICY_VERSION
from consensus_engine.hod_comp_rs_stage1_run import HodCompRsTrainingEvent
from consensus_engine.retained_history_batches import RetainedHistoryBatches
from consensus_engine.rs_trend_eligibility import (
    ARMED_GATES, FAIL, PASS, UNKNOWN, GateResult, RsTrendAssessment,
)
from consensus_engine.search_run_config import STAGE1_CANDIDATES, TRAINING_TICKERS
from consensus_engine.strategy_interface import StrategyContext, StrategyState
from consensus_engine.trade_alerts_config import TradeAlertsConfig
from consensus_engine.trade_alerts_models import Quote, RecordError, SessionRecord, SourceMetadata


AT = datetime(2026, 1, 5, 21, tzinfo=timezone.utc)


def retained(tickers=TRAINING_TICKERS):
    histories = tuple(SimpleNamespace(
        ticker=ticker, session="2026-01-05",
        batch=SimpleNamespace(request=SimpleNamespace(symbol=ticker, end=AT)),
    ) for ticker in tickers)
    return RetainedHistoryBatches(histories, (), ())


def context(ticker="NVDA"):
    session = SessionRecord.from_config(
        record_id="session-" + ticker, session="2026-01-05",
        started_at=datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc),
        config=TradeAlertsConfig({"schema_version": 1}),
    )
    return StrategyContext(session, ticker, "EQUITY", "LONG", AT)


def event(ticker="NVDA"):
    return HodCompRsTrainingEvent(
        ticker, "2026-01-05", object(), (context(ticker),), (), ())


def complete_events():
    return tuple(event(ticker) for ticker in TRAINING_TICKERS)


def assessment(compression_status, *, other_failure=False):
    gates = [GateResult("EVALUATION_WINDOW", PASS)]
    for name in ARMED_GATES:
        if name == "COMPRESSION_MEASURED":
            observed = 1.0 if compression_status == PASS else (
                0.0 if compression_status == FAIL else None)
            reason = None if compression_status == PASS else (
                "COMPRESSION_NOT_MEASURED" if compression_status == FAIL
                else "VALUE_UNAVAILABLE")
            gates.append(GateResult(name, compression_status, observed, 1.0, reason,
                                    ("compression",)))
        elif name == "RVOL" and other_failure:
            gates.append(GateResult(name, FAIL, 1.0, 1.5, "BELOW_MIN_RVOL", ("rvol",)))
        else:
            gates.append(GateResult(name, PASS))
    reasons = tuple(
        f"{row.name}:{row.status}:{row.reason}" for row in gates if row.status != PASS)
    return RsTrendAssessment(
        AT, StrategyState("WATCHING"), tuple(gates), reasons,
        ("compression",), "policy", "definition")


@pytest.mark.parametrize("compression_status", (PASS, FAIL, UNKNOWN))
def test_compression_off_keeps_measurement_visible_but_never_uses_it_as_a_gate(
        monkeypatch, compression_status):
    supplied = assessment(compression_status)
    monkeypatch.setattr(subject, "evaluate_rs_trend_eligibility", lambda _request: supplied)

    result = subject._compression_off_assessment(object())

    assert result.state.state == "ARMED"
    assert result.gate("COMPRESSION_MEASURED") == supplied.gate("COMPRESSION_MEASURED")
    assert not result.reasons


def test_compression_off_does_not_relax_any_other_eligibility_gate(monkeypatch):
    supplied = assessment(FAIL, other_failure=True)
    monkeypatch.setattr(subject, "evaluate_rs_trend_eligibility", lambda _request: supplied)

    result = subject._compression_off_assessment(object())

    assert result.state.state == "WATCHING"
    assert result.reasons == ("RVOL:FAIL:BELOW_MIN_RVOL",)


def composed(status="READY", reasons=()):
    return SimpleNamespace(
        status=status, reasons=reasons, evaluated_at=AT,
        risk=object() if status == "READY" else None,
        targets=(object(),) if status == "READY" else (),
        structure=SimpleNamespace(input_record_ids=("compression", "rs")),
        structural_input_ids=("structure",),
        gates=(SimpleNamespace(input_record_ids=("eligibility",)),),
    )


def evaluated(resolved_r=0.5, reason="RESOLVED"):
    return SimpleNamespace(
        resolved_r=resolved_r, status_reason=reason,
        outcome=SimpleNamespace(input_record_ids=("bar", "trade", "quote")),
        fill=SimpleNamespace(status="FILLED", total_cost_per_share=0.02),
        unit_exits=(SimpleNamespace(at=AT),),
    )


def policy():
    return FillCostPolicy(POLICY_VERSION, 10.0, 0.0)


def test_compression_off_candidate_feeds_resolved_costed_row_to_strict_measurement(monkeypatch):
    monkeypatch.setattr(subject, "HodCompRsCompressionOffReplayStrategy", object)
    outcomes = iter((composed(), *(composed("UNAVAILABLE", ("NO_EVENT",))
                                   for _ in TRAINING_TICKERS[1:])))
    monkeypatch.setattr(subject, "_evaluate_event", lambda _event: next(outcomes))
    monkeypatch.setattr(subject, "evaluate_playbook_outcome", lambda **_kwargs: evaluated())

    result = subject.run_compression_off_hod_comp_rs_stage1(
        retained=retained(), candidate=subject.COMPRESSION_OFF_CANDIDATE,
        events=complete_events(), fill_policy=policy(),
        disabled_rules=("ORIGINAL_AVAILABILITY_GAP",))

    assert result.version == subject.RUN_VERSION
    assert result.measurement.trade_count == 1
    assert result.measurement.evaluated_tickers == TRAINING_TICKERS
    assert result.measurement.disabled_rules == ("ORIGINAL_AVAILABILITY_GAP",)
    assert result.resolved[0].candidate_id == "COMP_OFF|RS_MANDATORY"
    assert result.resolved[0].tested_axes == ("D-048", "D-049")
    assert result.resolved[0].cost_model_version == POLICY_VERSION
    assert result.resolved[0].input_record_ids == (
        "compression", "rs", "structure", "eligibility", "bar", "trade", "quote")


@pytest.mark.parametrize("case", ("held_out", "wrong_candidate", "wrong_owner", "incomplete"))
def test_runner_refuses_scope_candidate_owner_or_coverage_drift(monkeypatch, case):
    monkeypatch.setattr(subject, "_evaluate_event",
                        lambda _event: pytest.fail("invalid input must fail first"))
    monkeypatch.setattr(subject, "HodCompRsCompressionOffReplayStrategy", object)
    kwargs = dict(retained=retained(), candidate=subject.COMPRESSION_OFF_CANDIDATE,
                  events=complete_events(), fill_policy=policy())
    if case == "held_out":
        kwargs["retained"] = retained(TRAINING_TICKERS[:-1] + ("GOOGL",))
    elif case == "wrong_candidate":
        kwargs["candidate"] = STAGE1_CANDIDATES[subject.PLAYBOOK][0]
    elif case == "wrong_owner":
        monkeypatch.setattr(subject, "HodCompRsCompressionOffReplayStrategy", type(None))
    else:
        kwargs["events"] = (event(),)
    with pytest.raises(RecordError):
        subject.run_compression_off_hod_comp_rs_stage1(**kwargs)


def test_missing_and_unresolved_inputs_stay_visible_not_filled(monkeypatch):
    monkeypatch.setattr(subject, "HodCompRsCompressionOffReplayStrategy", object)
    outcomes = iter((None, composed(), *(composed("UNAVAILABLE", ("RS_VALUE_MISSING",))
                                         for _ in TRAINING_TICKERS[2:])))
    monkeypatch.setattr(subject, "_evaluate_event", lambda _event: next(outcomes))
    monkeypatch.setattr(subject, "evaluate_playbook_outcome",
                        lambda **_kwargs: evaluated(resolved_r=None, reason="NO_QUOTE_AT_FILL"))

    result = subject.run_compression_off_hod_comp_rs_stage1(
        retained=retained(), candidate=subject.COMPRESSION_OFF_CANDIDATE,
        events=complete_events(), fill_policy=policy())

    assert tuple(row.reason for row in result.excluded) == (
        "NO_COMPOSED_OUTCOME", "NO_QUOTE_AT_FILL",
        *("RS_VALUE_MISSING" for _ in TRAINING_TICKERS[2:]))
    assert result.measurement is None


def test_market_record_identity_is_checked_before_replay(monkeypatch):
    monkeypatch.setattr(subject, "HodCompRsCompressionOffReplayStrategy", object)
    bad = Quote(
        record_id="trade", metadata=SourceMetadata(
            instrument_id="MSFT", instrument_type="EQUITY", session="2026-01-05",
            source="SYNTHETIC", source_time=AT, received_time=AT,
            available_time=AT, normalized_time=AT),
        trade_time=AT, last=100.0, status="VALID")
    events = (HodCompRsTrainingEvent(
        "NVDA", "2026-01-05", object(), (context(),), (bad,), ()), *complete_events()[1:])
    with pytest.raises(RecordError, match="metadata does not match"):
        subject.run_compression_off_hod_comp_rs_stage1(
            retained=retained(), candidate=subject.COMPRESSION_OFF_CANDIDATE,
            events=events, fill_policy=policy())
