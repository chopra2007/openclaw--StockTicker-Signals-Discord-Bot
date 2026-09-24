"""M9.1BA: adapter run over planned decision moments (offline, synthetic)."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import sys
from zoneinfo import ZoneInfo

import pytest


if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.retained_adapter_run import NOT_CALLED, run_adapters
from consensus_engine.retained_decision_moments import DecisionPlanItem
from consensus_engine.retained_history_batches import SessionHistory
from consensus_engine.trade_alerts_models import RecordError
from tests.trade_alerts_contracts.test_hod_comp_rs_research_adapter import history

MOMENTS = (datetime(2026, 8, 21, 13, 35, tzinfo=timezone.utc),
           datetime(2026, 8, 21, 13, 40, tzinfo=timezone.utc))


def _item(playbook):
    history = SessionHistory("XYZ", "2026-08-21", batch=None, prior_batch=None)
    return DecisionPlanItem(playbook, "XYZ", "2026-08-21", MOMENTS, history)


def test_absent_batch_counts_every_moment_not_ready_with_a_reason():
    result = run_adapters((_item("CRVOL_ORB5"), _item("HOD_COMP_RS"), _item("OR_FAILURE_REV"),
                           _item("FIRST_PULLBACK_VWAP")),
                          instrument_types={"XYZ": "EQUITY"})
    assert result.moments_called == 8
    assert result.ready == ()
    assert sum(row[-1] for row in result.not_ready) == 28  # 4 ORB + 18 HOD + 2 OR + 4 pullback
    assert all(row[2] for row in result.not_ready)
    assert run_adapters((_item("OR_FAILURE_REV"),), instrument_types={"XYZ": "EQUITY"}) == \
        run_adapters((_item("OR_FAILURE_REV"),), instrument_types={"XYZ": "EQUITY"})


def test_gaps_are_listed_and_missing_instrument_type_is_rejected():
    result = run_adapters((), instrument_types={})
    assert result.not_called == NOT_CALLED and "atr_1m" in NOT_CALLED
    assert "orb5_tape_intensity" in NOT_CALLED
    assert "orb5_quote_and_status_inputs" in NOT_CALLED
    assert "orb5_bar_finality" in NOT_CALLED
    assert "hod_comp_rs_policy_inputs" not in NOT_CALLED
    with pytest.raises(RecordError):
        run_adapters((_item("OR_FAILURE_REV"),), instrument_types={})


OPENED = datetime(2026, 7, 6, 6, 30, tzinfo=ZoneInfo("America/Los_Angeles"))


def _opening_plan(stock, spy, minutes=(14, 15, 20, 30)):
    moments = tuple(OPENED + timedelta(minutes=value) for value in minutes)
    return tuple(
        DecisionPlanItem("HOD_COMP_RS", symbol, "2026-07-06", selected,
                         SessionHistory(symbol, "2026-07-06", batch, None))
        for symbol, batch, selected in (("XYZ", stock, moments), ("SPY", spy, ()))
    )


def test_opening_rs_value_and_input_ids_stay_frozen_after_bar_fifteen(monkeypatch):
    from consensus_engine import retained_adapter_run as adapter

    outputs = []
    original = adapter.build_rs_trend_snapshot_from_research

    def capture(**kwargs):
        output = original(**kwargs)
        outputs.append(output.snapshot)
        return output

    monkeypatch.setattr(adapter, "build_rs_trend_snapshot_from_research", capture)
    # A rolling window after minute 15 would see the opposite stock direction.
    stock = history("XYZ", path=[(100, 101)] * 15 + [(101, 90)] * 15,
                    is_final=False)
    spy = history("SPY", first=400, step=0, minutes=30, is_final=False)
    result = run_adapters(_opening_plan(stock, spy),
                          instrument_types={"XYZ": "EQUITY", "SPY": "ETF"})
    values = [next(f for f in out.features if f.name == "RS_LOOKBACK_V1")
              for out in outputs]
    assert values[0].value is None
    assert values[0].missing_reason == "RS_WARMUP_INCOMPLETE"
    assert [value.value for value in values[1:]] == [0.01] * 3
    expected_ids = tuple(sorted(bar.record_id for batch in (stock, spy)
                                for bar in batch.bars[:15]))
    assert all(value.input_record_ids == expected_ids for value in values[1:])
    assert ("HOD_COMP_RS", "rs_15m", 3) in result.ready


@pytest.mark.parametrize("symbol", ["XYZ", "SPY"])
@pytest.mark.parametrize("minute", [5, 18])
@pytest.mark.parametrize("change", ["missing", "revised"])
def test_opening_rs_readiness_depends_only_on_required_bars(symbol, minute, change):
    def changed(bars):
        if change == "missing":
            return [bar for index, bar in enumerate(bars) if index != minute]
        bar = bars[minute]
        bars[minute] = replace(bar, metadata=replace(bar.metadata, revision=1))
        return bars

    batches = {
        name: history(name, minutes=30, is_final=False,
                      changed=changed if name == symbol else None)
        for name in ("XYZ", "SPY")
    }
    result = run_adapters(_opening_plan(batches["XYZ"], batches["SPY"]),
                          instrument_types={"XYZ": "EQUITY", "SPY": "ETF"})
    for name in ("rs_15m", "rs_warmup"):
        assert ("HOD_COMP_RS", name, "RS_WARMUP_INCOMPLETE", 1) in result.not_ready
        if minute >= 15:
            assert ("HOD_COMP_RS", name, 3) in result.ready
        else:
            reason = "RS_WINDOW_MISSING" if change == "missing" else "RS_WINDOW_REVISED"
            if symbol == "SPY":
                reason = "BENCHMARK_" + reason
            assert ("HOD_COMP_RS", name, reason, 3) in result.not_ready
            assert not any(row[:2] == ("HOD_COMP_RS", name) for row in result.ready)


@pytest.mark.parametrize("symbol", ["XYZ", "SPY"])
def test_opening_rs_late_required_revision_changes_only_its_available_as_of_version(symbol):
    def revised(bars):
        bar = bars[5]
        available = OPENED + timedelta(minutes=25)
        return [*bars, replace(bar, record_id=bar.record_id + "-later",
                               metadata=replace(bar.metadata, revision=1,
                                                received_time=available,
                                                available_time=available,
                                                normalized_time=available))]

    batches = {name: history(name, minutes=30, is_final=False,
                             changed=revised if name == symbol else None)
               for name in ("XYZ", "SPY")}
    result = run_adapters(_opening_plan(batches["XYZ"], batches["SPY"], (15, 20, 30)),
                          instrument_types={"XYZ": "EQUITY", "SPY": "ETF"})
    reason = "RS_WINDOW_REVISED" if symbol == "XYZ" else "BENCHMARK_RS_WINDOW_REVISED"
    for name in ("rs_15m", "rs_warmup"):
        assert ("HOD_COMP_RS", name, 2) in result.ready
        assert ("HOD_COMP_RS", name, reason, 1) in result.not_ready


def test_orb5_counts_opening_range_and_latest_bar_at_every_planned_moment():
    stock = history("XYZ", minutes=30, is_final=False)
    plan = (DecisionPlanItem(
        "CRVOL_ORB5", "XYZ", "2026-07-06",
        tuple(OPENED + timedelta(minutes=value) for value in (5, 10, 20)),
        SessionHistory("XYZ", "2026-07-06", stock, None)),)
    result = run_adapters(plan, instrument_types={"XYZ": "EQUITY"})
    assert result.moments_called == 3
    assert ("CRVOL_ORB5", "opening_range_5m", 3) in result.ready
    assert ("CRVOL_ORB5", "latest_bar_observation", 3) in result.ready


def test_orb5_missing_opening_bar_never_becomes_a_partial_range():
    stock = history("XYZ", minutes=30, is_final=False,
                    changed=lambda bars: [bar for index, bar in enumerate(bars) if index != 2])
    plan = (DecisionPlanItem(
        "CRVOL_ORB5", "XYZ", "2026-07-06",
        tuple(OPENED + timedelta(minutes=value) for value in (5, 10, 20)),
        SessionHistory("XYZ", "2026-07-06", stock, None)),)
    result = run_adapters(plan, instrument_types={"XYZ": "EQUITY"})
    assert ("CRVOL_ORB5", "opening_range_5m", "OPENING_RANGE_BAR_NOT_READY", 3) \
        in result.not_ready
    assert ("CRVOL_ORB5", "latest_bar_observation", 3) in result.ready
