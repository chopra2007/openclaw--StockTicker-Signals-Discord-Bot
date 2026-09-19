"""M9.1B contracts for the shared D-106/D-107 fill and cost model."""

from datetime import datetime, timedelta, timezone
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.fill_cost_model import (
    POLICY_VERSION, WINDOW_SECONDS, FillCostPolicy, model_fill,
)
from consensus_engine.trade_alerts_models import Quote, RecordError, SourceMetadata


UTC = timezone.utc
ALERT = datetime(2026, 7, 6, 13, 31, tzinfo=UTC)


_LATE = ALERT + timedelta(seconds=WINDOW_SECONDS + 5)


def _metadata(**changes):
    values = {
        "instrument_id": "SYNTH", "instrument_type": "EQUITY", "source": "SYNTHETIC",
        "source_time": ALERT, "received_time": ALERT, "available_time": _LATE,
        "normalized_time": _LATE, "session": "2026-07-06", "data_mode": "FIXTURE",
        "quality": "VALID",
    }
    values.update(changes)
    return SourceMetadata(**values)


def _trade(record_id, *, seconds_after_alert, price, quality="VALID"):
    return Quote(
        record_id=record_id, metadata=_metadata(quality=quality),
        quote_time=None, trade_time=ALERT + timedelta(seconds=seconds_after_alert),
        bid=None, ask=None, last=price, last_size=100, bid_size=None, ask_size=None,
        status="VALID",
    )


def _quote(record_id, *, seconds_after_alert, bid, ask, quality="VALID"):
    return Quote(
        record_id=record_id, metadata=_metadata(quality=quality),
        quote_time=ALERT + timedelta(seconds=seconds_after_alert), trade_time=None,
        bid=bid, ask=ask, last=None, last_size=None, bid_size=100, ask_size=100,
        status="VALID",
    )


def _policy(slippage_bps=0.0, commission_per_share=0.0):
    return FillCostPolicy(
        version=POLICY_VERSION, slippage_bps=slippage_bps,
        commission_per_share=commission_per_share,
    )


def test_window_is_fixed_at_thirty_seconds():
    assert WINDOW_SECONDS == 30.0


def test_long_fill_uses_first_print_and_pays_half_spread():
    trades = [_trade("t1", seconds_after_alert=5, price=100.0),
              _trade("t2", seconds_after_alert=10, price=101.0)]
    quotes = [_quote("q1", seconds_after_alert=4, bid=99.9, ask=100.1)]
    result = model_fill(alert_time=ALERT, direction="LONG", trades=trades, quotes=quotes,
                         policy=_policy())
    assert result.status == "FILLED"
    assert result.trade_print_price == 100.0
    assert result.trade_print_time == ALERT + timedelta(seconds=5)
    assert result.spread_cost_per_share == pytest.approx(0.1)
    assert result.modeled_price == pytest.approx(100.1)
    assert set(result.input_record_ids) == {"t1", "t2", "q1"}


def test_short_fill_subtracts_costs_instead_of_adding():
    trades = [_trade("t1", seconds_after_alert=5, price=100.0)]
    quotes = [_quote("q1", seconds_after_alert=4, bid=99.9, ask=100.1)]
    result = model_fill(alert_time=ALERT, direction="SHORT", trades=trades, quotes=quotes,
                         policy=_policy())
    assert result.modeled_price == pytest.approx(99.9)


def test_slippage_and_commission_add_to_total_cost():
    trades = [_trade("t1", seconds_after_alert=5, price=100.0)]
    quotes = [_quote("q1", seconds_after_alert=4, bid=99.9, ask=100.1)]
    result = model_fill(alert_time=ALERT, direction="LONG", trades=trades, quotes=quotes,
                         policy=_policy(slippage_bps=10.0, commission_per_share=0.01))
    assert result.slippage_cost_per_share == pytest.approx(0.1)
    assert result.commission_per_share == pytest.approx(0.01)
    assert result.total_cost_per_share == pytest.approx(0.1 + 0.1 + 0.01)
    assert result.modeled_price == pytest.approx(100.0 + 0.1 + 0.1 + 0.01)


def test_uses_earliest_actionable_print_not_the_best_price():
    trades = [_trade("t_worse", seconds_after_alert=3, price=101.0),
              _trade("t_better", seconds_after_alert=9, price=99.0)]
    quotes = [_quote("q1", seconds_after_alert=2, bid=100.9, ask=101.1)]
    result = model_fill(alert_time=ALERT, direction="LONG", trades=trades, quotes=quotes,
                         policy=_policy())
    assert result.trade_print_price == 101.0


def test_trade_before_alert_time_is_excluded():
    trades = [_trade("t_early", seconds_after_alert=-1, price=95.0),
              _trade("t_in_window", seconds_after_alert=1, price=100.0)]
    quotes = [_quote("q1", seconds_after_alert=0, bid=99.9, ask=100.1)]
    result = model_fill(alert_time=ALERT, direction="LONG", trades=trades, quotes=quotes,
                         policy=_policy())
    assert result.trade_print_price == 100.0


def test_trade_after_window_is_excluded():
    trades = [_trade("t_late", seconds_after_alert=WINDOW_SECONDS + 1, price=100.0)]
    quotes = [_quote("q1", seconds_after_alert=0, bid=99.9, ask=100.1)]
    result = model_fill(alert_time=ALERT, direction="LONG", trades=trades, quotes=quotes,
                         policy=_policy())
    assert result.status == "NO_TRADE_IN_WINDOW"
    assert result.modeled_price is None


def test_no_valid_trade_in_window_is_recorded_not_approximated():
    result = model_fill(alert_time=ALERT, direction="LONG", trades=[], quotes=[],
                         policy=_policy())
    assert result.status == "NO_TRADE_IN_WINDOW"
    assert result.modeled_price is None


def test_no_quote_at_fill_is_recorded_not_approximated():
    trades = [_trade("t1", seconds_after_alert=5, price=100.0)]
    result = model_fill(alert_time=ALERT, direction="LONG", trades=trades, quotes=[],
                         policy=_policy())
    assert result.status == "NO_QUOTE_AT_FILL"
    assert result.modeled_price is None


def test_falls_back_to_earliest_quote_in_window_when_none_precede_the_print():
    trades = [_trade("t1", seconds_after_alert=1, price=100.0)]
    quotes = [_quote("q_late", seconds_after_alert=5, bid=99.8, ask=100.2)]
    result = model_fill(alert_time=ALERT, direction="LONG", trades=trades, quotes=quotes,
                         policy=_policy())
    assert result.status == "FILLED"
    assert result.quote_time == ALERT + timedelta(seconds=5)


def test_degraded_quality_trade_is_ignored_not_used_as_a_fill():
    trades = [_trade("t_bad", seconds_after_alert=1, price=50.0, quality="DEGRADED_PROXY"),
              _trade("t_good", seconds_after_alert=5, price=100.0)]
    quotes = [_quote("q1", seconds_after_alert=4, bid=99.9, ask=100.1)]
    result = model_fill(alert_time=ALERT, direction="LONG", trades=trades, quotes=quotes,
                         policy=_policy())
    assert result.trade_print_price == 100.0


def test_invalid_direction_is_rejected():
    with pytest.raises(RecordError):
        model_fill(alert_time=ALERT, direction="FLAT", trades=[], quotes=[], policy=_policy())


def test_policy_rejects_unknown_version():
    with pytest.raises(RecordError):
        FillCostPolicy(version="OTHER", slippage_bps=0.0, commission_per_share=0.0)


def test_policy_rejects_negative_inputs():
    with pytest.raises(RecordError):
        FillCostPolicy(version=POLICY_VERSION, slippage_bps=-1.0, commission_per_share=0.0)


def test_model_fill_requires_a_policy_instance():
    with pytest.raises(RecordError):
        model_fill(alert_time=ALERT, direction="LONG", trades=[], quotes=[], policy=None)
