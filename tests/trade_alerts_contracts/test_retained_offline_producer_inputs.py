"""M9.1DQ retained offline producer-input contracts."""

from dataclasses import replace
from datetime import timedelta
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.core_price_features import build_core_price_snapshot
from consensus_engine.historical_bars import HistoryBatch, HistoryRequest
import consensus_engine.retained_offline_producer_inputs as offline_inputs
from consensus_engine.retained_candidate_events import CandidateEventInput
from consensus_engine.retained_decision_moments import plan_decision_moments
from consensus_engine.retained_history_batches import SessionHistory
from consensus_engine.retained_offline_producer_inputs import (
    ALWAYS_UNKNOWN,
    RUN_VERSION,
    build_retained_offline_producer_inputs,
)
from consensus_engine.trade_alerts_models import Bar, RecordError
from test_retained_candidate_events import CONVENTIONS, MOMENT, OPEN, SESSION, _market, _retained


def _input(*, quotes=True):
    retained = _retained(("NVDA",))
    item = next(row for row in plan_decision_moments(retained)
                if row.playbook == "CRVOL_ORB5")
    records = _market()
    trades = tuple(row.quote for row in records if row.schema == "trades")
    bbo = tuple(row.quote for row in records if row.schema == "bbo-1m") if quotes else ()
    source_ids = tuple(
        [bar.record_id for bar in item.history.batch.bars]
        + [row.record_id for row in trades + bbo]
    )
    return CandidateEventInput(
        item.playbook, item.ticker, item.session, item.moments, item.history,
        trades, bbo, source_ids,
    )


def _features(row):
    return {value.name: value for value in row.measurement.features}


def test_connects_retained_bars_and_quotes_without_filling_unknown_facts():
    value = _input()
    rows = build_retained_offline_producer_inputs(value)

    assert tuple(row.evaluated_at for row in rows) == value.decision_moments
    assert all(row.version == RUN_VERSION for row in rows)
    assert all(row.status.halted is None for row in rows)
    assert all(row.status.macro_blackout_active is None for row in rows)
    assert all(row.status.catalyst_coverage == "UNKNOWN" for row in rows)
    selected = next(row for row in rows if row.evaluated_at == MOMENT)
    assert selected.quote_decision is not None
    assert selected.quote_decision.quote.record_id == value.quotes[0].record_id
    assert not selected.quote_decision.usable
    assert "MISSING_POLICY" in selected.quote_decision.reasons
    assert "SOURCE_QUALITY_UNKNOWN" in selected.quote_decision.reasons
    combined = selected.quote_trade_combination
    assert combined.quote_record_id == value.quotes[0].record_id
    assert combined.trade_record_id == value.trades[0].record_id
    assert combined.last_trade == value.trades[0]
    assert combined.input_record_ids == (
        value.quotes[0].record_id, value.trades[0].record_id,
    )
    assert not combined.usable
    assert {
        "QUOTE_MISSING_POLICY",
        "QUOTE_SOURCE_QUALITY_UNKNOWN",
        "QUOTE_MISSING_POSITIVE_LAST",
        "QUOTE_CONTINUITY_LOST",
        "TRADE_SOURCE_QUALITY_UNKNOWN",
        "TRADE_DELAY_UNKNOWN",
    }.issubset(combined.reasons)
    assert selected.missing_required_inputs == (
        *ALWAYS_UNKNOWN, "ATR_1M_UNAVAILABLE", "VWAP_UNAVAILABLE",
        "QUOTE_DECISION_UNAVAILABLE", "QUOTE_TRADE_COMBINATION_UNAVAILABLE",
    )


def test_missing_quote_stays_an_explicit_gap():
    rows = build_retained_offline_producer_inputs(_input(quotes=False))
    assert all(row.quote_decision is None for row in rows)
    assert all(row.quote_trade_combination.quote_record_id is None for row in rows)
    assert all(row.quote_trade_combination.trade_record_id is not None for row in rows)
    assert all(row.missing_required_inputs[-2:] == (
        "QUOTE_DECISION_UNAVAILABLE", "QUOTE_TRADE_COMBINATION_UNAVAILABLE",
    ) for row in rows)


def test_quote_trade_combination_uses_only_records_available_at_each_moment():
    value = _input()
    later = MOMENT + timedelta(minutes=1)
    later_trade = replace(
        value.trades[0],
        record_id="later-trade",
        trade_time=later,
        metadata=replace(
            value.trades[0].metadata,
            source_time=later,
            received_time=later,
            available_time=later,
            normalized_time=later,
        ),
    )
    supplied = replace(value, decision_moments=(MOMENT, later),
                       trades=(later_trade, value.trades[0]))
    rows = build_retained_offline_producer_inputs(supplied)
    assert rows[0].quote_trade_combination.trade_record_id == value.trades[0].record_id
    assert rows[1].quote_trade_combination.trade_record_id == later_trade.record_id


@pytest.mark.parametrize("field, changed_value", (
    ("source", "OTHER_SOURCE"),
    ("instrument_id", "MSFT"),
))
def test_refuses_trade_scope_drift(field, changed_value):
    value = _input()
    wrong = replace(
        value.trades[0],
        metadata=replace(value.trades[0].metadata, **{field: changed_value}),
    )
    with pytest.raises(RecordError, match="retained trades must share"):
        build_retained_offline_producer_inputs(replace(value, trades=(wrong,)))


def test_computes_point_in_time_minute_atr_and_vwap_from_twenty_ended_bars():
    value = _input(quotes=False)
    bars = []
    for index in range(20):
        start = OPEN + timedelta(minutes=index)
        end = start + timedelta(minutes=1)
        template = value.history.batch.bars[0]
        metadata = replace(
            template.metadata,
            source_time=start,
            received_time=end,
            available_time=end,
            normalized_time=end,
            data_mode="SYNTHETIC_TEST",
            # The shared retained template intentionally has UNKNOWN quality.
            quality="VALID",
        )
        bars.append(Bar(
            record_id=f"bar:NVDA:{index}", metadata=metadata,
            start_time=start, end_time=end, is_final=True,
            open=100.0 + index, high=101.0 + index, low=99.0 + index,
            close=100.5 + index, volume=1000.0,
            adjustment_basis=template.adjustment_basis,
            price_convention=template.price_convention,
            volume_convention=template.volume_convention,
        ))
    moment = OPEN + timedelta(minutes=20)
    request = HistoryRequest("NVDA", OPEN, moment)
    history = SessionHistory(
        ticker=value.ticker,
        session=value.session,
        batch=HistoryBatch(
            request, "EQUS.MINI", replace(CONVENTIONS, finality="SYNTHETIC_TEST"), tuple(bars),
        ),
        prior_batch=None,
    )
    supplied = replace(
        value,
        decision_moments=(moment,),
        history=history,
        source_record_ids=tuple(bar.record_id for bar in bars),
    )

    coverage = history.batch.coverage_at(moment)
    assert tuple(item.status for item in coverage.intervals) == ("FINAL",) * 20
    row = build_retained_offline_producer_inputs(supplied)[0]
    features = _features(row)
    assert features["ATR_1M_20_SMA_V1"].value == pytest.approx(2.0)
    assert features["SESSION_VWAP_BAR_HLC3_V1"].value == pytest.approx(109 + 2 / 3)
    assert "ATR_1M_UNAVAILABLE" not in row.missing_required_inputs
    assert "VWAP_UNAVAILABLE" not in row.missing_required_inputs
    assert "DAILY_ATR_UNAVAILABLE" in row.missing_required_inputs

    # An ended synthetic bar with unknown quality must still block both features.
    unknown_bar = replace(bars[-1], metadata=replace(bars[-1].metadata, quality="UNKNOWN"))
    unknown_history = replace(
        history, batch=replace(history.batch, bars=(*bars[:-1], unknown_bar)),
    )
    unknown_row = build_retained_offline_producer_inputs(
        replace(supplied, history=unknown_history),
    )[0]
    unknown_features = _features(unknown_row)
    assert unknown_features["ATR_1M_20_SMA_V1"].value is None
    assert unknown_features["SESSION_VWAP_BAR_HLC3_V1"].value is None
    assert "ATR_1M_UNAVAILABLE" in unknown_row.missing_required_inputs
    assert "VWAP_UNAVAILABLE" in unknown_row.missing_required_inputs


def test_refuses_quote_scope_drift():
    value = _input()
    wrong = replace(
        value.quotes[0],
        metadata=replace(value.quotes[0].metadata, instrument_id="MSFT"),
    )
    with pytest.raises(RecordError, match="share the candidate history scope"):
        build_retained_offline_producer_inputs(replace(value, quotes=(wrong,)))


def _cache_input():
    value = _input(quotes=False)
    moment = OPEN + timedelta(minutes=1)
    bar = value.history.batch.bars[0]
    bar = replace(bar, is_final=True, metadata=replace(
        bar.metadata, quality="VALID", data_mode="SYNTHETIC_TEST",
        received_time=moment, available_time=moment, normalized_time=moment,
    ))
    history = SessionHistory(
        value.ticker, value.session,
        HistoryBatch(
            HistoryRequest(value.ticker, OPEN, OPEN + timedelta(minutes=2)),
            "EQUS.MINI", replace(CONVENTIONS, finality="SYNTHETIC_TEST"), (bar,),
        ), None,
    )
    # These checks vary only bar history; market scope has its own rejection tests.
    return replace(value, history=history, decision_moments=(moment,), trades=(),
                   source_record_ids=(bar.record_id,))


def _assert_direct_measurement(value):
    rows = build_retained_offline_producer_inputs(value)
    for row in rows:
        direct = build_core_price_snapshot(
            record_id=row.measurement.record_id, evaluated_at=row.evaluated_at,
            minute_history=value.history.batch, daily_history=None, premarket_history=None,
        )
        assert row.measurement.to_json() == direct.to_json()
    return rows


def test_identical_history_is_reused_across_playbooks_with_distinct_record_ids(monkeypatch):
    value = _cache_input()
    offline_inputs._measurement.cache_clear()
    calls = []

    def counted(**kwargs):
        calls.append(kwargs)
        return build_core_price_snapshot(**kwargs)

    monkeypatch.setattr(offline_inputs, "build_core_price_snapshot", counted)
    rows = []
    for playbook in ("CRVOL_ORB5", "HOD_COMP_RS", "OR_FAILURE_REV", "FIRST_PULLBACK_VWAP"):
        rows.extend(_assert_direct_measurement(replace(value, playbook=playbook)))
    assert len(calls) == 1
    assert len({row.measurement.record_id for row in rows}) == 4
    assert _features(rows[0])["SESSION_VWAP_BAR_HLC3_V1"].value is not None
    offline_inputs._measurement.cache_clear()
    assert build_retained_offline_producer_inputs(value)[0].as_dict() == rows[0].as_dict()


@pytest.mark.parametrize("case", (
    "price", "identity", "revision", "availability", "quality", "finality",
    "conventions", "request", "source", "ticker", "moment", "future_revision",
))
def test_reused_measurement_never_hides_changed_history_or_time(case, monkeypatch):
    value = _cache_input()
    offline_inputs._measurement.cache_clear()
    original = _assert_direct_measurement(value)[0]
    batch = value.history.batch
    bar = batch.bars[0]
    moment = value.decision_moments[0]
    if case == "price":
        batch = replace(batch, bars=(replace(bar, close=100.75),))
    elif case == "identity":
        batch = replace(batch, bars=(replace(bar, record_id="different-bar"),))
    elif case in ("revision", "availability", "quality"):
        changes = {"revision": {"revision": 1},
                   "availability": {"available_time": moment + timedelta(seconds=1),
                                    "normalized_time": moment + timedelta(seconds=1)},
                   "quality": {"quality": "UNKNOWN"}}[case]
        batch = replace(batch, bars=(replace(bar, metadata=replace(bar.metadata, **changes)),))
    elif case == "finality":
        batch = replace(batch, bars=(replace(bar, is_final=False),))
    elif case == "conventions":
        batch = replace(batch, conventions=replace(batch.conventions, finality="UNKNOWN"))
    elif case == "request":
        batch = replace(batch, request=replace(batch.request, start=moment))
    elif case == "source":
        batch = replace(batch, source="OTHER_SOURCE", bars=(replace(
            bar, metadata=replace(bar.metadata, source="OTHER_SOURCE")),))
    elif case == "ticker":
        batch = replace(batch, request=replace(batch.request, symbol="MSFT"), bars=(replace(
            bar, metadata=replace(bar.metadata, instrument_id="MSFT")),))
        value = replace(value, ticker="MSFT")
    elif case == "moment":
        value = replace(value, decision_moments=(moment + timedelta(minutes=1),))
    else:
        later = moment + timedelta(seconds=1)
        revision = replace(bar, record_id="later-revision", is_final=False, metadata=replace(
            bar.metadata, revision=1, received_time=later, available_time=later,
            normalized_time=later,
        ))
        batch = replace(batch, bars=(*batch.bars, revision))
        value = replace(value, decision_moments=(moment, later))
    changed = replace(value, history=replace(value.history, batch=batch))
    calls = []

    def counted(**kwargs):
        calls.append(kwargs)
        return build_core_price_snapshot(**kwargs)

    monkeypatch.setattr(offline_inputs, "build_core_price_snapshot", counted)
    rows = _assert_direct_measurement(changed)
    assert len(calls) == len(changed.decision_moments)
    if case == "future_revision":
        assert rows[0].measurement.to_json() == original.measurement.to_json()
        assert _features(rows[1])["SESSION_VWAP_BAR_HLC3_V1"].value is None
    offline_inputs._measurement.cache_clear()
    assert [row.as_dict() for row in build_retained_offline_producer_inputs(changed)] == [
        row.as_dict() for row in rows
    ]


def test_reused_price_measurement_does_not_reuse_quote_state():
    value = replace(_input(), decision_moments=(MOMENT,))
    with_quote = build_retained_offline_producer_inputs(value)[0]
    without_quote = build_retained_offline_producer_inputs(replace(value, quotes=()))[0]
    assert with_quote.quote_decision is not None
    assert without_quote.quote_decision is None
    assert with_quote.measurement.to_json() == without_quote.measurement.to_json()


def test_recorded_offline_input_proof_is_deterministic():
    rendered = json.dumps(
        [row.as_dict() for row in build_retained_offline_producer_inputs(_input())],
        sort_keys=True,
        indent=2,
    ) + "\n"
    output = Path(os.environ["TMPDIR"], "m91dq-retained-offline-producer-inputs-proof.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
