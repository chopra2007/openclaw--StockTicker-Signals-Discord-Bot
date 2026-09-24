"""M9.1CE contracts for the confirmed OR-failure stage-1 connection."""

from datetime import datetime, timezone
from types import SimpleNamespace
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

import consensus_engine.or_failure_stage1_run as subject
from consensus_engine.fill_cost_model import FillCostPolicy, POLICY_VERSION
from consensus_engine.retained_history_batches import RetainedHistoryBatches
from consensus_engine.search_run_config import STAGE1_CANDIDATES, TRAINING_TICKERS
from consensus_engine.trade_alerts_models import Quote, RecordError, SourceMetadata


AT = datetime(2026, 1, 5, 21, tzinfo=timezone.utc)


def retained(tickers=TRAINING_TICKERS):
    histories = tuple(
        SimpleNamespace(
            ticker=ticker, session="2026-01-05",
            batch=SimpleNamespace(request=SimpleNamespace(symbol=ticker, end=AT)),
        )
        for ticker in tickers
    )
    return RetainedHistoryBatches(histories, (), ())


def request(confirmation="MINUTE_CLOSE"):
    return SimpleNamespace(policy=SimpleNamespace(confirmation=confirmation))


def event(**changes):
    values = dict(
        ticker="NVDA", session="2026-01-05", request=request(), trades=(), quotes=(),
    )
    values.update(changes)
    return subject.OrFailureTrainingEvent(**values)


def complete_events(*first):
    """Every other name has an explicit request that the runner must assess."""
    covered = {row.ticker for row in first}
    return first + tuple(event(ticker=ticker) for ticker in TRAINING_TICKERS
                         if ticker not in covered)


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


def assessment(*, state="ALERT_TRIGGERED", reasons=()):
    return SimpleNamespace(
        state=SimpleNamespace(state=state), direction="SHORT", reasons=reasons,
        risk=object(), targets=(object(),), evaluated_at=AT,
        structural_input_ids=("structure",),
    )


def outcome(*, resolved_r=0.5, reason="RESOLVED"):
    return SimpleNamespace(
        resolved_r=resolved_r, status_reason=reason,
        outcome=SimpleNamespace(input_record_ids=("bar", "trade", "quote")),
        fill=SimpleNamespace(status="FILLED", total_cost_per_share=0.02),
        unit_exits=(SimpleNamespace(at=AT),),
    )


def policy():
    return FillCostPolicy(POLICY_VERSION, 10.0, 0.0)


def test_confirmed_runner_feeds_resolved_modeled_cost_row_to_strict_measurement(monkeypatch):
    events = complete_events(event(trades=(market_record("trade"),),
                                   quotes=(market_record("quote"),)))
    assessed = []

    def assess(value):
        assessed.append(value)
        return (assessment() if value is events[0].request
                else assessment(state="ARMED", reasons=("NO_TRIGGER",)))

    def evaluate(**kwargs):
        assert kwargs["trades"] == events[0].trades
        assert kwargs["quotes"] == events[0].quotes
        assert kwargs["history"].request.symbol == "NVDA"
        return outcome()

    monkeypatch.setattr(subject, "evaluate_or_failure_rev", assess)
    monkeypatch.setattr(subject, "evaluate_playbook_outcome", evaluate)

    result = subject.run_confirmed_or_failure_stage1(
        retained=retained(), candidate=subject.CONFIRMED_CANDIDATE,
        events=events, fill_policy=policy(),
        disabled_rules=("ORIGINAL_AVAILABILITY_GAP",),
    )

    assert result.version == subject.RUN_VERSION
    assert result.measurement.trade_count == 1
    assert result.measurement.evaluated_tickers == TRAINING_TICKERS
    assert result.measurement.disabled_rules == ("ORIGINAL_AVAILABILITY_GAP",)
    assert result.resolved[0].tested_axes == ("D-052",)
    assert result.resolved[0].cost_model_version == POLICY_VERSION
    assert result.resolved[0].input_record_ids == ("structure", "bar", "trade", "quote")
    assert assessed == [row.request for row in events]
    assert result.evaluated_sessions == tuple(sorted(
        (ticker, "2026-01-05") for ticker in TRAINING_TICKERS))
    assert tuple(row.ticker for row in result.excluded) == TRAINING_TICKERS[1:]
    assert all(row.reason == "NO_TRIGGER" for row in result.excluded)


def test_untriggered_and_unresolved_events_stay_visible_not_filled(monkeypatch):
    calls = iter((
        assessment(state="ARMED", reasons=("QUOTE:UNKNOWN:NO_QUOTE",)),
        assessment(),
        assessment(),
        *(assessment(state="ARMED", reasons=("INPUT_UNAVAILABLE",))
          for _ in TRAINING_TICKERS[3:]),
    ))
    outcomes = iter((
        outcome(resolved_r=None, reason="NO_QUOTE_AT_FILL"),
        outcome(),
    ))
    monkeypatch.setattr(subject, "evaluate_or_failure_rev", lambda _request: next(calls))
    monkeypatch.setattr(
        subject, "evaluate_playbook_outcome", lambda **_kwargs: next(outcomes),
    )

    result = subject.run_confirmed_or_failure_stage1(
        retained=retained(), candidate=subject.CONFIRMED_CANDIDATE,
        events=complete_events(event(), event(ticker="MSFT"), event(ticker="AAPL")),
        fill_policy=policy(),
    )

    assert tuple(row.reason for row in result.excluded) == (
        "QUOTE:UNKNOWN:NO_QUOTE", "NO_QUOTE_AT_FILL",
        *("INPUT_UNAVAILABLE" for _ in TRAINING_TICKERS[3:]),
    )
    assert tuple(row.ticker for row in result.excluded) == (
        "NVDA", "MSFT", *TRAINING_TICKERS[3:])
    assert tuple(row.ticker for row in result.resolved) == ("AAPL",)


@pytest.mark.parametrize("case", ("held_out_scope", "faster_candidate", "faster_request"))
def test_runner_refuses_scope_or_candidate_drift(case):
    kwargs = dict(
        retained=retained(), candidate=subject.CONFIRMED_CANDIDATE,
        events=complete_events(event()), fill_policy=policy(),
    )
    if case == "held_out_scope":
        kwargs["retained"] = retained(TRAINING_TICKERS[:-1] + ("GOOGL",))
    elif case == "faster_candidate":
        kwargs["candidate"] = STAGE1_CANDIDATES[subject.PLAYBOOK][1]
    elif case == "faster_request":
        kwargs["events"] = complete_events(event(request=request("FAILURE_BAR")))
    with pytest.raises(RecordError):
        subject.run_confirmed_or_failure_stage1(**kwargs)


@pytest.mark.parametrize("events", ((event(),), (event(),) * len(TRAINING_TICKERS), ()))
def test_history_presence_and_repeated_events_do_not_prove_evaluation_coverage(monkeypatch, events):
    def forbidden(*args, **kwargs):
        pytest.fail("incomplete coverage must be refused before assessment or measurement")

    monkeypatch.setattr(subject, "evaluate_or_failure_rev", forbidden)
    monkeypatch.setattr(subject, "measure_stage1_candidate", forbidden)
    with pytest.raises(RecordError, match="evaluation coverage"):
        subject.run_confirmed_or_failure_stage1(
            retained=retained(), candidate=subject.CONFIRMED_CANDIDATE,
            events=events, fill_policy=policy())


def test_every_retained_session_requires_evaluation_even_when_all_names_are_present():
    histories = retained()
    extra = SimpleNamespace(
        ticker="NVDA", session="2026-01-06",
        batch=SimpleNamespace(request=SimpleNamespace(symbol="NVDA", end=AT)),
    )
    histories = RetainedHistoryBatches(histories.histories + (extra,), (), ())
    with pytest.raises(RecordError, match="NVDA.*2026-01-06"):
        subject.run_confirmed_or_failure_stage1(
            retained=histories, candidate=subject.CONFIRMED_CANDIDATE,
            events=complete_events(), fill_policy=policy())


@pytest.mark.parametrize("reason", ("NO_TRIGGER", "INPUT_UNAVAILABLE"))
def test_no_resolved_events_returns_visible_exclusions_without_measurement(monkeypatch, reason):
    monkeypatch.setattr(subject, "evaluate_or_failure_rev",
                        lambda _: assessment(state="ARMED", reasons=(reason,)))

    def forbidden(**kwargs):
        pytest.fail("no resolved events must not create a fill or measurement")

    monkeypatch.setattr(subject, "evaluate_playbook_outcome", forbidden)
    monkeypatch.setattr(subject, "measure_stage1_candidate", forbidden)
    result = subject.run_confirmed_or_failure_stage1(
        retained=retained(), candidate=subject.CONFIRMED_CANDIDATE,
        events=complete_events(), fill_policy=policy())
    assert result.measurement is None
    assert result.resolved == ()
    assert tuple(row.ticker for row in result.excluded) == TRAINING_TICKERS
    assert all(row.reason == reason for row in result.excluded)


@pytest.mark.parametrize("kind", ("trade", "quote"))
@pytest.mark.parametrize("changes", ({"ticker": "MSFT"}, {"ticker": "GOOGL"},
                                     {"session": "2026-01-06"}))
def test_mismatched_record_identity_is_refused_before_a_fill(monkeypatch, kind, changes):
    def forbidden(*args, **kwargs):
        pytest.fail("mismatched records must be refused before assessment or fill")

    monkeypatch.setattr(subject, "evaluate_or_failure_rev", forbidden)
    monkeypatch.setattr(subject, "evaluate_playbook_outcome", forbidden)
    # Even a later mismatched record may not be ignored in favor of an earlier match.
    records = (market_record(kind), market_record(kind, **changes))
    row = event(**{("trades" if kind == "trade" else "quotes"): records})
    with pytest.raises(RecordError, match="metadata does not match"):
        subject.run_confirmed_or_failure_stage1(
            retained=retained(), candidate=subject.CONFIRMED_CANDIDATE,
            events=complete_events(row), fill_policy=policy())


@pytest.mark.parametrize("status", ("NO_EVENT", "UNAVAILABLE"))
def test_explicit_session_scan_results_remain_visible_and_unavailable_blocks_ranking(monkeypatch, status):
    monkeypatch.setattr(subject, "evaluate_or_failure_rev", lambda _: assessment())
    monkeypatch.setattr(subject, "evaluate_playbook_outcome", lambda **kwargs: outcome())
    dispositions = tuple(subject.SessionWithoutEvent(
        ticker, "2026-01-05", status, "SUPPLIED_SCAN_RESULT")
        for ticker in TRAINING_TICKERS[1:])
    result = subject.run_confirmed_or_failure_stage1(
        retained=retained(), candidate=subject.CONFIRMED_CANDIDATE,
        events=(event(),), sessions_without_events=dispositions, fill_policy=policy())
    assert tuple(row.ticker for row in result.excluded) == TRAINING_TICKERS[1:]
    assert all(row.reason == f"{status}:SUPPLIED_SCAN_RESULT" for row in result.excluded)
    assert tuple(row.ticker for row in result.resolved) == ("NVDA",)
    if status == "NO_EVENT":
        assert result.measurement.evaluated_tickers == TRAINING_TICKERS
        assert result.measurement.trade_count == 1
        assert result.evaluated_sessions == tuple(sorted(
            (ticker, "2026-01-05") for ticker in TRAINING_TICKERS))
    else:
        assert result.measurement is None
        assert result.evaluated_sessions == (("NVDA", "2026-01-05"),)


def test_all_explicit_no_event_sessions_need_no_fabricated_reversal_request(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("explicit no-event scans must not fabricate assessments or trades")

    monkeypatch.setattr(subject, "evaluate_or_failure_rev", forbidden)
    monkeypatch.setattr(subject, "evaluate_playbook_outcome", forbidden)
    result = subject.run_confirmed_or_failure_stage1(
        retained=retained(), candidate=subject.CONFIRMED_CANDIDATE,
        events=(), fill_policy=policy(), sessions_without_events=tuple(
            subject.SessionWithoutEvent(ticker, "2026-01-05", "NO_EVENT", "NO_HANDOFF")
            for ticker in TRAINING_TICKERS))
    assert result.measurement is None
    assert result.resolved == ()
    assert tuple(row.ticker for row in result.excluded) == TRAINING_TICKERS
    assert all(row.reason == "NO_EVENT:NO_HANDOFF" for row in result.excluded)


@pytest.mark.parametrize("case", ("duplicate", "conflict", "held_out", "wrong_session", "omitted"))
def test_session_dispositions_cannot_forge_complete_coverage(case):
    rows = [subject.SessionWithoutEvent(ticker, "2026-01-05", "NO_EVENT", "NO_HANDOFF")
            for ticker in TRAINING_TICKERS[1:]]
    if case == "duplicate":
        rows.append(rows[0])
    elif case == "conflict":
        rows.append(subject.SessionWithoutEvent("NVDA", "2026-01-05", "NO_EVENT", "NO_HANDOFF"))
    elif case == "held_out":
        rows[-1] = subject.SessionWithoutEvent("GOOGL", "2026-01-05", "NO_EVENT", "NO_HANDOFF")
    elif case == "wrong_session":
        rows[-1] = subject.SessionWithoutEvent("USO", "2026-01-06", "NO_EVENT", "NO_HANDOFF")
    else:
        rows.pop()
    with pytest.raises(RecordError, match="session disposition|evaluation coverage"):
        subject.run_confirmed_or_failure_stage1(
            retained=retained(), candidate=subject.CONFIRMED_CANDIDATE,
            events=(event(),), fill_policy=policy(), sessions_without_events=rows)
