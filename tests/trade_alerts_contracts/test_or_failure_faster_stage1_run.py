"""M9.1CF contracts for the research-only FASTER OR-failure stage-1 run."""

from datetime import datetime, timezone
from types import SimpleNamespace
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

import consensus_engine.or_failure_faster_stage1_run as subject
from consensus_engine.fill_cost_model import FillCostPolicy, POLICY_VERSION
from consensus_engine.or_failure_handoff import (
    ENDED_GATE, EXCURSION_GATE, OWNERSHIP_GATE, RANGE_GATE, REACCEPTANCE_GATE,
)
from consensus_engine.or_failure_rev import (
    CONFIRMATION_GATE, HANDOFF_GATE, PASS, REVERSAL_GATES,
)
from consensus_engine.or_failure_stage1_run import (
    OrFailureTrainingEvent, SessionWithoutEvent,
)
from consensus_engine.retained_history_batches import RetainedHistoryBatches
from consensus_engine.search_run_config import STAGE1_CANDIDATES, TRAINING_TICKERS
from consensus_engine.trade_alerts_models import Quote, RecordError, SourceMetadata


AT = datetime(2026, 1, 5, 21, tzinfo=timezone.utc)


class GateSet(SimpleNamespace):
    def gate(self, name):
        return self.by_name[name]


def gate(name, status=PASS, reason=None):
    return SimpleNamespace(name=name, status=status, reason=reason)


def handoff(**changes):
    statuses = {
        ENDED_GATE: gate(ENDED_GATE), OWNERSHIP_GATE: gate(OWNERSHIP_GATE),
        RANGE_GATE: gate(RANGE_GATE), EXCURSION_GATE: gate(EXCURSION_GATE),
        REACCEPTANCE_GATE: gate(REACCEPTANCE_GATE, "UNKNOWN", "NO_FINAL_CLOSE"),
    }
    statuses.update(changes)
    return GateSet(by_name=statuses)


def request(**changes):
    values = dict(confirmation_close=None, failure_bar=None, handoff=handoff())
    values.update(changes)
    return SimpleNamespace(**values)


def assessment(**changes):
    statuses = {name: gate(name) for name in REVERSAL_GATES}
    statuses[HANDOFF_GATE] = gate(HANDOFF_GATE, "FAIL", "HANDOFF_NOT_FAILURE_FORMING")
    statuses[CONFIRMATION_GATE] = gate(CONFIRMATION_GATE, "UNKNOWN", "MISSING_CONFIRMATION_CLOSE")
    values = dict(
        by_name=statuses, direction="SHORT", risk=object(), targets=(object(),),
        evaluated_at=AT, structural_input_ids=("structure",),
    )
    values.update(changes)
    return GateSet(**values)


def retained(tickers=TRAINING_TICKERS):
    return RetainedHistoryBatches(tuple(
        SimpleNamespace(
            ticker=ticker, session="2026-01-05",
            batch=SimpleNamespace(request=SimpleNamespace(symbol=ticker, end=AT)),
        ) for ticker in tickers
    ), (), ())


def event(ticker="NVDA", **changes):
    values = dict(
        ticker=ticker, session="2026-01-05", request=request(), trades=(), quotes=(),
    )
    values.update(changes)
    return OrFailureTrainingEvent(**values)


def complete_events(*first):
    covered = {row.ticker for row in first}
    return first + tuple(event(ticker) for ticker in TRAINING_TICKERS if ticker not in covered)


def market_record(kind, *, ticker="NVDA", session="2026-01-05"):
    return Quote(
        record_id=kind, metadata=SourceMetadata(
            instrument_id=ticker, session=session, source="SYNTHETIC",
            source_time=AT, received_time=AT, available_time=AT, normalized_time=AT,
        ),
        trade_time=AT if kind == "trade" else None,
        quote_time=AT if kind == "quote" else None,
        last=100.0 if kind == "trade" else None,
        bid=99.9 if kind == "quote" else None,
        ask=100.1 if kind == "quote" else None, status="VALID",
    )


def outcome(resolved_r=0.5, reason="RESOLVED"):
    return SimpleNamespace(
        resolved_r=resolved_r, status_reason=reason,
        outcome=SimpleNamespace(input_record_ids=("bar", "trade", "quote")),
        fill=SimpleNamespace(status="FILLED", total_cost_per_share=0.02),
        unit_exits=(SimpleNamespace(at=AT),),
    )


def policy():
    return FillCostPolicy(POLICY_VERSION, 10.0, 0.0)


def test_faster_runner_uses_break_reject_and_acceptance_without_a_close(monkeypatch):
    first = event(
        trades=(market_record("trade"),), quotes=(market_record("quote"),))
    events = complete_events(first)
    assessed = []

    def assess(value):
        assessed.append(value)
        if value is first.request:
            return assessment()
        failed = assessment()
        failed.by_name["LAST_BACK_INSIDE_RANGE"] = gate(
            "LAST_BACK_INSIDE_RANGE", "FAIL", "LAST_NOT_BACK_INSIDE_RANGE")
        return failed

    monkeypatch.setattr(subject, "evaluate_or_failure_rev", assess)
    monkeypatch.setattr(subject, "evaluate_playbook_outcome", lambda **_kwargs: outcome())

    result = subject.run_faster_or_failure_stage1(
        retained=retained(), candidate=subject.FASTER_CANDIDATE,
        events=events, fill_policy=policy(),
        disabled_rules=("ORIGINAL_AVAILABILITY_GAP",),
    )

    assert result.version == subject.RUN_VERSION
    assert result.candidate_id == "FASTER"
    assert result.measurement.trade_count == 1
    assert result.measurement.disabled_rules == ("ORIGINAL_AVAILABILITY_GAP",)
    assert result.resolved[0].tested_axes == ("D-052",)
    assert result.resolved[0].cost_model_version == POLICY_VERSION
    assert result.resolved[0].input_record_ids == ("structure", "bar", "trade", "quote")
    assert assessed == [row.request for row in events]
    assert all(row.reason.startswith("LAST_BACK_INSIDE_RANGE:FAIL")
               for row in result.excluded)


@pytest.mark.parametrize("field", ("confirmation_close", "failure_bar"))
def test_faster_runner_refuses_completed_close_or_failure_bar_substitution(field):
    with pytest.raises(RecordError, match="cannot use a completed-close"):
        subject.run_faster_or_failure_stage1(
            retained=retained(), candidate=subject.FASTER_CANDIDATE,
            events=complete_events(event(request=request(**{field: object()}))),
            fill_policy=policy())


def test_confirmed_handoff_cannot_be_relabelled_as_faster(monkeypatch):
    confirmed = handoff(**{
        REACCEPTANCE_GATE: gate(REACCEPTANCE_GATE),
    })
    monkeypatch.setattr(subject, "evaluate_or_failure_rev", lambda _request: assessment())
    with pytest.raises(RecordError, match="cannot substitute the confirmed handoff"):
        subject.run_faster_or_failure_stage1(
            retained=retained(), candidate=subject.FASTER_CANDIDATE,
            events=complete_events(event(request=request(handoff=confirmed))),
            fill_policy=policy())


@pytest.mark.parametrize("failed_gate", (EXCURSION_GATE, "INSIDE_ACCEPTANCE"))
def test_real_break_and_inside_acceptance_are_both_required(monkeypatch, failed_gate):
    if failed_gate == EXCURSION_GATE:
        bad_request = request(handoff=handoff(**{
            EXCURSION_GATE: gate(EXCURSION_GATE, "FAIL", "EXCURSION_TOO_SMALL"),
        }))
        shared = assessment()
    else:
        bad_request = request()
        shared = assessment()
        shared.by_name[failed_gate] = gate(failed_gate, "FAIL", "ACCEPTANCE_TOO_LOW")
    monkeypatch.setattr(subject, "evaluate_or_failure_rev", lambda _request: shared)
    monkeypatch.setattr(subject, "evaluate_playbook_outcome",
                        lambda **_kwargs: pytest.fail("a failed faster gate cannot create a fill"))
    result = subject.run_faster_or_failure_stage1(
        retained=retained(), candidate=subject.FASTER_CANDIDATE,
        events=tuple(event(ticker, request=bad_request) for ticker in TRAINING_TICKERS),
        fill_policy=policy())
    assert result.measurement is None
    assert result.resolved == ()
    assert tuple(row.ticker for row in result.excluded) == TRAINING_TICKERS
    assert all(row.reason.startswith(failed_gate + ":FAIL") for row in result.excluded)


def test_faster_runner_keeps_unavailable_sessions_visible_and_unranked(monkeypatch):
    monkeypatch.setattr(subject, "evaluate_or_failure_rev", lambda _request: assessment())
    monkeypatch.setattr(subject, "evaluate_playbook_outcome", lambda **_kwargs: outcome())
    unavailable = tuple(SessionWithoutEvent(
        ticker, "2026-01-05", "UNAVAILABLE", "QUOTE_INPUT_OFF")
        for ticker in TRAINING_TICKERS[1:])
    result = subject.run_faster_or_failure_stage1(
        retained=retained(), candidate=subject.FASTER_CANDIDATE,
        events=(event(),), sessions_without_events=unavailable, fill_policy=policy())
    assert result.measurement is None
    assert tuple(row.reason for row in result.excluded) == tuple(
        "UNAVAILABLE:QUOTE_INPUT_OFF" for _ in unavailable)


def test_missing_quote_or_cost_outcome_stays_excluded_not_filled(monkeypatch):
    monkeypatch.setattr(subject, "evaluate_or_failure_rev", lambda _request: assessment())
    monkeypatch.setattr(
        subject, "evaluate_playbook_outcome",
        lambda **_kwargs: outcome(None, "NO_QUOTE_AT_FILL"))
    result = subject.run_faster_or_failure_stage1(
        retained=retained(), candidate=subject.FASTER_CANDIDATE,
        events=complete_events(), fill_policy=policy())
    assert result.measurement is None
    assert result.resolved == ()
    assert tuple(row.reason for row in result.excluded) == tuple(
        "NO_QUOTE_AT_FILL" for _ in TRAINING_TICKERS)


@pytest.mark.parametrize("case", ("confirmed_candidate", "missing_session", "wrong_record"))
def test_faster_runner_refuses_candidate_coverage_or_record_identity_drift(case):
    kwargs = dict(
        retained=retained(), candidate=subject.FASTER_CANDIDATE,
        events=complete_events(), fill_policy=policy(),
    )
    if case == "confirmed_candidate":
        kwargs["candidate"] = STAGE1_CANDIDATES[subject.PLAYBOOK][0]
    elif case == "missing_session":
        kwargs["events"] = complete_events()[:-1]
    else:
        kwargs["events"] = complete_events(event(
            trades=(market_record("trade", ticker="MSFT"),)))
    with pytest.raises(RecordError):
        subject.run_faster_or_failure_stage1(**kwargs)
