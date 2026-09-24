"""M9.1CK contracts for the default first-pullback stage-1 connection."""

from datetime import datetime, timezone
from types import SimpleNamespace
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

import consensus_engine.first_pullback_vwap_stage1_run as subject
from consensus_engine.fill_cost_model import FillCostPolicy, POLICY_VERSION
from consensus_engine.retained_history_batches import RetainedHistoryBatches
from consensus_engine.search_run_config import STAGE1_CANDIDATES, TRAINING_TICKERS
from consensus_engine.strategy_interface import StrategyContext
from consensus_engine.trade_alerts_config import TradeAlertsConfig
from consensus_engine.trade_alerts_models import Quote, RecordError, SessionRecord, SourceMetadata


AT = datetime(2026, 1, 5, 21, tzinfo=timezone.utc)


def retained(tickers=TRAINING_TICKERS):
    histories = tuple(SimpleNamespace(
        ticker=ticker, session="2026-01-05",
        batch=SimpleNamespace(request=SimpleNamespace(symbol=ticker, end=AT)),
    ) for ticker in tickers)
    return RetainedHistoryBatches(histories, (), ())


def context(ticker="NVDA", direction="LONG", at=AT):
    session = SessionRecord.from_config(
        record_id="session-" + ticker, session="2026-01-05",
        started_at=datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc),
        config=TradeAlertsConfig({"schema_version": 1}),
    )
    return StrategyContext(session, ticker, "EQUITY", direction, at)


def event(**changes):
    ticker = changes.get("ticker", "NVDA")
    values = dict(ticker=ticker, session="2026-01-05", strategy=object(),
                  contexts=(context(ticker),), trades=(), quotes=())
    values.update(changes)
    return subject.FirstPullbackTrainingEvent(**values)


def complete_events(*first):
    covered = {row.ticker for row in first}
    return first + tuple(event(ticker=ticker) for ticker in TRAINING_TICKERS
                         if ticker not in covered)


def market_record(kind, *, ticker="NVDA", session="2026-01-05"):
    return Quote(
        record_id=kind, metadata=SourceMetadata(
            instrument_id=ticker, instrument_type="EQUITY", session=session,
            source="SYNTHETIC", source_time=AT, received_time=AT,
            available_time=AT, normalized_time=AT,
        ),
        trade_time=AT if kind == "trade" else None,
        quote_time=AT if kind == "quote" else None,
        last=100.0 if kind == "trade" else None,
        bid=99.9 if kind == "quote" else None,
        ask=100.1 if kind == "quote" else None, status="VALID",
    )


def assessment(*, state="ALERT_TRIGGERED", reasons=()):
    return SimpleNamespace(
        state=SimpleNamespace(state=state), reasons=reasons, evaluated_at=AT,
        direction="LONG", risk=object() if state == "ALERT_TRIGGERED" else None,
        targets=(object(),) if state == "ALERT_TRIGGERED" else (),
        measurement_record_id="measurement", structural_input_ids=("structure",),
        gates=(SimpleNamespace(input_record_ids=("vwap",)),),
    )


def evaluated(*, resolved_r=0.5, reason="RESOLVED"):
    return SimpleNamespace(
        resolved_r=resolved_r, status_reason=reason,
        outcome=SimpleNamespace(input_record_ids=("bar", "trade", "quote")),
        fill=SimpleNamespace(status="FILLED", total_cost_per_share=0.02),
        unit_exits=(SimpleNamespace(at=AT),),
    )


def policy():
    return FillCostPolicy(POLICY_VERSION, 10.0, 0.0)


def test_default_candidate_feeds_resolved_costed_row_to_strict_measurement(monkeypatch):
    events = complete_events(event(trades=(market_record("trade"),),
                                   quotes=(market_record("quote"),)))
    outcomes = iter((assessment(), *(assessment(state="ARMED", reasons=("NO_EVENT",))
                                     for _ in TRAINING_TICKERS[1:])))
    monkeypatch.setattr(subject, "_evaluate_event", lambda _event: next(outcomes))
    monkeypatch.setattr(subject, "evaluate_playbook_outcome", lambda **_kwargs: evaluated())

    result = subject.run_default_first_pullback_stage1(
        retained=retained(), candidate=subject.DEFAULT_CANDIDATE,
        events=events, fill_policy=policy(),
        disabled_rules=("ORIGINAL_AVAILABILITY_GAP",),
    )

    assert subject.DEFAULT_CANDIDATE.candidate_id.endswith("VWAP_MANDATORY|AVWAP_OFF")
    assert result.version == subject.RUN_VERSION
    assert result.measurement.trade_count == 1
    assert result.measurement.evaluated_tickers == TRAINING_TICKERS
    assert result.measurement.disabled_rules == ("ORIGINAL_AVAILABILITY_GAP",)
    assert result.resolved[0].tested_axes == ("D-054", "D-055")
    assert result.resolved[0].cost_model_version == POLICY_VERSION
    assert result.resolved[0].input_record_ids == (
        "measurement", "structure", "vwap", "bar", "trade", "quote")
    assert tuple(row.reason for row in result.excluded) == tuple(
        "NO_EVENT" for _ in TRAINING_TICKERS[1:])


def test_missing_and_unresolved_inputs_stay_visible_not_filled(monkeypatch):
    outcomes = iter((None, assessment(), assessment(),
                     *(assessment(state="ARMED", reasons=("VWAP_CONTEXT:UNKNOWN:MISSING",))
                       for _ in TRAINING_TICKERS[3:])))
    evaluations = iter((evaluated(resolved_r=None, reason="NO_QUOTE_AT_FILL"), evaluated()))
    monkeypatch.setattr(subject, "_evaluate_event", lambda _event: next(outcomes))
    monkeypatch.setattr(subject, "evaluate_playbook_outcome",
                        lambda **_kwargs: next(evaluations))

    result = subject.run_default_first_pullback_stage1(
        retained=retained(), candidate=subject.DEFAULT_CANDIDATE,
        events=complete_events(event(), event(ticker="MSFT"), event(ticker="AAPL")),
        fill_policy=policy())

    assert tuple(row.reason for row in result.excluded) == (
        "NO_PULLBACK_ASSESSMENT", "NO_QUOTE_AT_FILL",
        *("VWAP_CONTEXT:UNKNOWN:MISSING" for _ in TRAINING_TICKERS[3:]))
    assert tuple(row.ticker for row in result.resolved) == ("AAPL",)


@pytest.mark.parametrize("case", ("held_out_scope", "other_candidate", "incomplete"))
def test_runner_refuses_scope_candidate_or_evaluation_drift(monkeypatch, case):
    monkeypatch.setattr(subject, "_evaluate_event",
                        lambda _event: pytest.fail("invalid scope must fail first"))
    kwargs = dict(retained=retained(), candidate=subject.DEFAULT_CANDIDATE,
                  events=complete_events(event()), fill_policy=policy())
    if case == "held_out_scope":
        kwargs["retained"] = retained(TRAINING_TICKERS[:-1] + ("GOOGL",))
    elif case == "other_candidate":
        kwargs["candidate"] = STAGE1_CANDIDATES[subject.PLAYBOOK][1]
    else:
        kwargs["events"] = (event(),)
    with pytest.raises(RecordError):
        subject.run_default_first_pullback_stage1(**kwargs)


@pytest.mark.parametrize("kind", ("trade", "quote"))
def test_mismatched_market_record_is_refused_before_strategy_evaluation(monkeypatch, kind):
    monkeypatch.setattr(subject, "_evaluate_event",
                        lambda _event: pytest.fail("bad identity must fail first"))
    row = event(**{("trades" if kind == "trade" else "quotes"):
                   (market_record(kind, ticker="MSFT"),)})
    with pytest.raises(RecordError, match="metadata does not match"):
        subject.run_default_first_pullback_stage1(
            retained=retained(), candidate=subject.DEFAULT_CANDIDATE,
            events=complete_events(row), fill_policy=policy())


@pytest.mark.parametrize("status", ("NO_EVENT", "UNAVAILABLE"))
def test_explicit_session_dispositions_remain_visible(monkeypatch, status):
    monkeypatch.setattr(subject, "_evaluate_event", lambda _event: assessment())
    monkeypatch.setattr(subject, "evaluate_playbook_outcome", lambda **_kwargs: evaluated())
    dispositions = tuple(subject.SessionWithoutEvent(
        ticker, "2026-01-05", status, "SUPPLIED_SCAN_RESULT")
        for ticker in TRAINING_TICKERS[1:])
    result = subject.run_default_first_pullback_stage1(
        retained=retained(), candidate=subject.DEFAULT_CANDIDATE,
        events=(event(),), sessions_without_events=dispositions, fill_policy=policy())
    assert all(row.reason == f"{status}:SUPPLIED_SCAN_RESULT" for row in result.excluded)
    assert result.measurement is not None if status == "NO_EVENT" else result.measurement is None


def test_event_driver_runs_every_context_in_order_and_confirms(monkeypatch):
    calls = []
    answer = assessment()

    class FakeStrategy:
        def update(self, supplied):
            calls.append(("update", supplied.evaluated_at))

        def confirm_recorded(self):
            calls.append(("confirm", None))

        def outcome(self):
            return answer

    monkeypatch.setattr(subject, "FirstPullbackVwapReplayStrategy", FakeStrategy)
    first = context(at=AT)
    second = context(at=AT.replace(minute=1))
    result = subject._evaluate_event(event(strategy=FakeStrategy(), contexts=(first, second)))
    assert result is answer
    assert calls == [
        ("update", first.evaluated_at), ("confirm", None),
        ("update", second.evaluated_at), ("confirm", None),
    ]
