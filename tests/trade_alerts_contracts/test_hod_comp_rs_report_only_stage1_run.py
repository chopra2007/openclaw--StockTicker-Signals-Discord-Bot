"""M9.1CH contracts for the HOD-compression RS-report-only connection."""

from datetime import datetime, timezone
from types import SimpleNamespace
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

import consensus_engine.hod_comp_rs_report_only_stage1_run as subject
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


def assessment(rs_status, *, observed=0.001):
    gates = [GateResult("EVALUATION_WINDOW", PASS)]
    for name in ARMED_GATES:
        if name == "RS_TREND":
            reason = None if rs_status == PASS else (
                "RS_BELOW_DIRECTIONAL_MINIMUM" if rs_status == FAIL else "VALUE_UNAVAILABLE")
            gates.append(GateResult(name, rs_status, observed, 0.003, reason, ("rs",)))
        else:
            gates.append(GateResult(name, PASS))
    reasons = () if rs_status == PASS else (
        f"RS_TREND:{rs_status}:{gates[-5].reason}",)
    return RsTrendAssessment(
        AT, StrategyState("SETUP_FORMING"), tuple(gates), reasons, ("rs",),
        "policy", "definition")


@pytest.mark.parametrize(
    "rs_status,observed,expected_state",
    ((FAIL, 0.001, "ARMED"), (PASS, 0.004, "ARMED"), (UNKNOWN, None, "SETUP_FORMING")),
)
def test_report_only_keeps_rs_visible_but_only_a_measured_cutoff_failure_is_non_gating(
        monkeypatch, rs_status, observed, expected_state):
    supplied = assessment(rs_status, observed=observed)
    monkeypatch.setattr(subject, "evaluate_rs_trend_eligibility", lambda _request: supplied)

    result = subject._report_only_assessment(object())

    assert result.state.state == expected_state
    assert result.gate("RS_TREND") == supplied.gate("RS_TREND")
    assert (not result.reasons) if expected_state == "ARMED" else result.reasons


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


def test_report_only_candidate_feeds_resolved_costed_row_to_strict_measurement(monkeypatch):
    monkeypatch.setattr(subject, "HodCompRsReportOnlyReplayStrategy", object)
    outcomes = iter((composed(), *(composed("UNAVAILABLE", ("NO_EVENT",))
                                   for _ in TRAINING_TICKERS[1:])))
    monkeypatch.setattr(subject, "_evaluate_event", lambda _event: next(outcomes))
    monkeypatch.setattr(subject, "evaluate_playbook_outcome", lambda **_kwargs: evaluated())

    result = subject.run_report_only_hod_comp_rs_stage1(
        retained=retained(), candidate=subject.REPORT_ONLY_CANDIDATE,
        events=complete_events(), fill_policy=policy(),
        disabled_rules=("ORIGINAL_AVAILABILITY_GAP",))

    assert result.version == subject.RUN_VERSION
    assert result.measurement.trade_count == 1
    assert result.measurement.evaluated_tickers == TRAINING_TICKERS
    assert result.measurement.disabled_rules == ("ORIGINAL_AVAILABILITY_GAP",)
    assert result.resolved[0].candidate_id == "COMP_ON_060|RS_REPORT_ONLY"
    assert result.resolved[0].tested_axes == ("D-048", "D-049")
    assert result.resolved[0].cost_model_version == POLICY_VERSION
    assert result.resolved[0].input_record_ids == (
        "compression", "rs", "structure", "eligibility", "bar", "trade", "quote")


@pytest.mark.parametrize("case", ("held_out", "wrong_candidate", "wrong_owner", "incomplete"))
def test_runner_refuses_scope_candidate_owner_or_coverage_drift(monkeypatch, case):
    monkeypatch.setattr(subject, "_evaluate_event",
                        lambda _event: pytest.fail("invalid input must fail first"))
    monkeypatch.setattr(subject, "HodCompRsReportOnlyReplayStrategy", object)
    kwargs = dict(retained=retained(), candidate=subject.REPORT_ONLY_CANDIDATE,
                  events=complete_events(), fill_policy=policy())
    if case == "held_out":
        kwargs["retained"] = retained(TRAINING_TICKERS[:-1] + ("GOOGL",))
    elif case == "wrong_candidate":
        kwargs["candidate"] = STAGE1_CANDIDATES[subject.PLAYBOOK][0]
    elif case == "wrong_owner":
        monkeypatch.setattr(subject, "HodCompRsReportOnlyReplayStrategy", type(None))
    else:
        kwargs["events"] = (event(),)
    with pytest.raises(RecordError):
        subject.run_report_only_hod_comp_rs_stage1(**kwargs)


def test_missing_and_unresolved_inputs_stay_visible_not_filled(monkeypatch):
    monkeypatch.setattr(subject, "HodCompRsReportOnlyReplayStrategy", object)
    outcomes = iter((None, composed(), *(composed("UNAVAILABLE", ("RS_VALUE_MISSING",))
                                         for _ in TRAINING_TICKERS[2:])))
    monkeypatch.setattr(subject, "_evaluate_event", lambda _event: next(outcomes))
    monkeypatch.setattr(subject, "evaluate_playbook_outcome",
                        lambda **_kwargs: evaluated(resolved_r=None, reason="NO_QUOTE_AT_FILL"))

    result = subject.run_report_only_hod_comp_rs_stage1(
        retained=retained(), candidate=subject.REPORT_ONLY_CANDIDATE,
        events=complete_events(), fill_policy=policy())

    assert tuple(row.reason for row in result.excluded) == (
        "NO_COMPOSED_OUTCOME", "NO_QUOTE_AT_FILL",
        *("RS_VALUE_MISSING" for _ in TRAINING_TICKERS[2:]))
    assert result.measurement is None


def test_market_record_identity_is_checked_before_replay(monkeypatch):
    monkeypatch.setattr(subject, "HodCompRsReportOnlyReplayStrategy", object)
    bad = Quote(
        record_id="trade", metadata=SourceMetadata(
            instrument_id="MSFT", instrument_type="EQUITY", session="2026-01-05",
            source="SYNTHETIC", source_time=AT, received_time=AT,
            available_time=AT, normalized_time=AT),
        trade_time=AT, last=100.0, status="VALID")
    events = (HodCompRsTrainingEvent(
        "NVDA", "2026-01-05", object(), (context(),), (bad,), ()), *complete_events()[1:])
    with pytest.raises(RecordError, match="metadata does not match"):
        subject.run_report_only_hod_comp_rs_stage1(
            retained=retained(), candidate=subject.REPORT_ONLY_CANDIDATE,
            events=events, fill_policy=policy())
