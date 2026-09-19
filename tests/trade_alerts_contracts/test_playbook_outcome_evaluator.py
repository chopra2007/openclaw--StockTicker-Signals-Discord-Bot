"""M9.1C contracts for the shared D-106/D-107 playbook outcome evaluator."""

from dataclasses import replace
from datetime import date, timedelta
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.fill_cost_model import POLICY_VERSION as FILL_POLICY_VERSION, FillCostPolicy
from consensus_engine.historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from consensus_engine.playbook_outcome_evaluator import (
    POLICY_VERSION, SUPPORTED_STRATEGIES, evaluate_playbook_outcome,
)
from consensus_engine.trade_alerts_models import (
    Bar, Quote, RecordError, RiskLevel, SourceMetadata, TargetLevel,
)
from consensus_engine.utils.time_context import as_utc, session_bounds


SESSION = date(2026, 7, 6)
OPENED, CLOSED = (as_utc(value) for value in session_bounds(SESSION))
ALERT = OPENED


def _bar_metadata(interval, **changes):
    values = {
        "instrument_id": "SYNTH", "instrument_type": "EQUITY", "source": "SYNTHETIC",
        "source_time": interval.start, "received_time": interval.end,
        "available_time": interval.end, "normalized_time": interval.end,
        "session": interval.session, "data_mode": "M91C_FIXTURE", "quality": "VALID",
    }
    values.update(changes)
    return SourceMetadata(**values)


def _history(changes=None):
    request = HistoryRequest("SYNTH", OPENED, CLOSED, "1m", "REGULAR")
    changes = changes or {}
    bars = []
    for number, interval in enumerate(request.expected_intervals()):
        values = {"open": 100.1, "high": 100.1, "low": 100.1, "close": 100.1}
        values.update(changes.get(number, {}))
        bars.append(Bar(
            record_id=f"m91c-bar-{number}", metadata=_bar_metadata(interval),
            start_time=interval.start, end_time=interval.end, is_final=True,
            volume=1000, adjustment_basis="RAW", price_convention="OHLC",
            volume_convention="SHARES", **values,
        ))
    return HistoryBatch(
        request=request, source="SYNTHETIC",
        conventions=HistoryConventions(
            timestamp="START", session="REGULAR", adjustment_basis="RAW",
            price="OHLC", volume="SHARES", coverage_basis="SUPPLIED_FIXTURE",
            finality="FINAL", publication="BAR_END", evidence_reference="M9.1C_FIXTURE",
        ), bars=tuple(bars),
    )


def _quote_metadata(seconds_after_alert):
    at = ALERT + timedelta(seconds=seconds_after_alert)
    return SourceMetadata(
        instrument_id="SYNTH", instrument_type="EQUITY", source="SYNTHETIC",
        source_time=at, received_time=CLOSED, available_time=CLOSED, normalized_time=CLOSED,
        session=SESSION.isoformat(), data_mode="M91C_FIXTURE", quality="VALID",
    )


def _trade(record_id, *, seconds_after_alert, price):
    return Quote(
        record_id=record_id, metadata=_quote_metadata(seconds_after_alert),
        quote_time=None, trade_time=ALERT + timedelta(seconds=seconds_after_alert),
        bid=None, ask=None, last=price, last_size=100, bid_size=None, ask_size=None,
        status="VALID",
    )


def _quote(record_id, *, seconds_after_alert, bid, ask):
    return Quote(
        record_id=record_id, metadata=_quote_metadata(seconds_after_alert),
        quote_time=ALERT + timedelta(seconds=seconds_after_alert), trade_time=None,
        bid=bid, ask=ask, last=None, last_size=None, bid_size=100, ask_size=100,
        status="VALID",
    )


def _policy():
    return FillCostPolicy(version=FILL_POLICY_VERSION, slippage_bps=0.0, commission_per_share=0.0)


def _risk(direction, entry=100.1, stop=99.0):
    if direction == "SHORT":
        entry, stop = 200 - entry, 200 - stop
    return RiskLevel(entry_reference=entry, hard_stop=stop,
                     risk_per_share=abs(entry - stop), rationale="FIXTURE", source="FIXTURE")


def _target(direction, name, price, r_multiple):
    if direction == "SHORT":
        price = 200 - price
    return TargetLevel(name=name, price=price, r_multiple=r_multiple, source="FIXTURE")


def _evaluate(direction="LONG", targets=None, changes=None, trades=None, quotes=None,
              strategy_id="HOD_COMP_RS"):
    history = _history(changes)
    if targets is None:
        targets = (_target(direction, "T1", 105.0, 1.0),)
    if trades is None:
        trades = [_trade("trade-1", seconds_after_alert=5, price=100.0
                         if direction == "LONG" else 100.0)]
    if quotes is None:
        quotes = [_quote("quote-1", seconds_after_alert=4, bid=99.9, ask=100.1)]
    return evaluate_playbook_outcome(
        record_id="m91c-outcome", candidate_id="m91c-candidate", strategy_id=strategy_id,
        direction=direction, risk=_risk(direction), targets=targets, alert_time=ALERT,
        evaluated_at=CLOSED, trades=trades, quotes=quotes, policy=_policy(), history=history,
    )


def test_policy_version_is_explicit():
    assert POLICY_VERSION == "M91C_SHARED_D106_D107_OUTCOME_V1"
    assert SUPPORTED_STRATEGIES == {"HOD_COMP_RS", "OR_FAILURE_REV", "FIRST_PULLBACK_VWAP"}


def test_rejects_unsupported_strategy():
    with pytest.raises(RecordError):
        _evaluate(strategy_id="CRVOL_ORB5")


def test_no_trade_in_window_stays_unfilled_not_approximated():
    result = _evaluate(trades=[], quotes=[])
    assert result.fill.status == "NO_TRADE_IN_WINDOW"
    assert result.outcome.result == "UNKNOWN"
    assert result.outcome.data_quality == "UNAVAILABLE"
    assert result.outcome.modeled_entry_price is None


def test_entry_geometry_invalid_when_fill_already_through_stop():
    trades = [_trade("trade-1", seconds_after_alert=5, price=98.0)]
    quotes = [_quote("quote-1", seconds_after_alert=4, bid=97.9, ask=98.1)]
    result = _evaluate(trades=trades, quotes=quotes)
    assert result.status_reason == "ENTRY_GEOMETRY_INVALID"
    assert result.outcome.result == "UNFILLED"


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_single_target_resolves_at_horizon_when_never_touched(direction):
    result = _evaluate(direction=direction)
    assert result.outcome.result == "RESOLVED"
    assert result.unit_exits[0].reason == "HORIZON"
    assert result.outcome.target_outcomes[0].hit is False
    assert result.outcome.policy_version == POLICY_VERSION


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_single_target_hit_in_range_before_horizon(direction):
    changes = {5: {"high": 106.0, "low": 100.1, "open": 100.1, "close": 100.1}}
    if direction == "SHORT":
        changes = {5: {"low": 200 - 106.0, "high": 200 - 100.1, "open": 200 - 100.1,
                       "close": 200 - 100.1}}
    result = _evaluate(direction=direction, targets=(_target(direction, "T1", 105.0, 1.0),),
                       changes=changes)
    assert result.outcome.result == "RESOLVED"
    assert result.unit_exits[0].reason == "TARGET"
    assert result.outcome.target_outcomes[0].hit is True


def test_same_bar_stop_and_target_resolve_stop_first_and_flag_ambiguous():
    changes = {0: {"open": 100.1, "high": 106.0, "low": 98.0, "close": 100.1}}
    result = _evaluate(targets=(_target("LONG", "T1", 105.0, 1.0),), changes=changes)
    assert result.same_bar_ambiguous is True
    assert result.outcome.result == "AMBIGUOUS"
    assert result.unit_exits[0].reason == "STOP"
    assert result.unit_exits[0].price == pytest.approx(99.0)


def test_two_targets_split_units_and_average_the_exit():
    targets = (_target("LONG", "T1", 101.0, 1.0), _target("LONG", "T2", 103.0, 3.0))
    changes = {3: {"open": 100.1, "high": 101.5, "low": 100.1, "close": 101.0}}
    result = _evaluate(targets=targets, changes=changes)
    assert [row.reason for row in result.unit_exits] == ["TARGET", "HORIZON"]
    assert result.outcome.target_outcomes[0].hit is True
    assert result.outcome.target_outcomes[1].hit is False


def test_incomplete_coverage_is_censored_not_approximated():
    request = HistoryRequest("SYNTH", OPENED, CLOSED, "1m", "REGULAR")
    intervals = request.expected_intervals()
    history = _history()
    truncated = replace(history, bars=tuple(
        bar for bar in history.bars if bar.start_time != intervals[3].start))
    result = evaluate_playbook_outcome(
        record_id="m91c-outcome", candidate_id="m91c-candidate", strategy_id="OR_FAILURE_REV",
        direction="LONG", risk=_risk("LONG"), targets=(_target("LONG", "T1", 105.0, 1.0),),
        alert_time=ALERT, evaluated_at=CLOSED,
        trades=[_trade("trade-1", seconds_after_alert=5, price=100.0)],
        quotes=[_quote("quote-1", seconds_after_alert=4, bid=99.9, ask=100.1)],
        policy=_policy(), history=truncated,
    )
    assert result.outcome.result == "CENSORED"
    assert result.outcome.data_quality == "INVALID"
