"""M9.1DD retained M0.3D parent-selection contracts."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.databento_minute_bars import DatabentoMinuteContext, normalize_databento_ohlcv_1m
from consensus_engine.historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from consensus_engine.retained_candidate_events import CandidateEventInput
from consensus_engine.retained_or_failure_parent_scan import (
    DEFINITION_REFERENCE, RUN_VERSION, TradeCoverage, scan_retained_or_failure_parents,
)
from consensus_engine.retained_remaining_producers import build_retained_remaining_request
from consensus_engine.trade_alerts_models import Bar, Quote, SourceMetadata


UTC = timezone.utc
DAY = "2026-01-05"
OPEN = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
CONVENTIONS = HistoryConventions(
    timestamp="END", session="REGULAR", adjustment_basis="SYNTHETIC_TEST",
    price="USD_PER_SHARE", volume="SHARES", coverage_basis="SYNTHETIC_TEST",
    finality="SYNTHETIC_FINAL", publication="SYNTHETIC_TEST", evidence_reference="synthetic-test",
)


def _metadata(at):
    return SourceMetadata(
        instrument_id="NVDA", instrument_type="EQUITY", source="EQUS.MINI",
        source_time=at, received_time=at, available_time=at, normalized_time=at,
        session=DAY, quality="VALID", data_mode="SYNTHETIC_TEST",
    )


def _bar(number, *, close=100.0):
    start = OPEN + timedelta(minutes=number)
    end = start + timedelta(minutes=1)
    return Bar(
        record_id=f"bar-{number}", metadata=_metadata(end), start_time=start, end_time=end,
        is_final=True, open=close, high=close + 0.10, low=close - 0.10,
        close=close, volume=1000.0, adjustment_basis="SYNTHETIC_TEST",
        price_convention="USD_PER_SHARE", volume_convention="SHARES",
    )


def _trade(name, at, price):
    return Quote(
        record_id=name, metadata=_metadata(at), trade_time=at, last=price,
        last_size=100, status="VALID", delayed=False,
    )


def _input(*, short_history=False, direction="LONG"):
    count = 5 if short_history else 30
    bars = [_bar(number) for number in range(count)]
    if not short_history:
        bars[26] = _bar(26, close=100.0)
    batch = HistoryBatch(
        HistoryRequest("NVDA", OPEN, OPEN + timedelta(minutes=count)),
        "EQUS.MINI", CONVENTIONS, tuple(bars),
    )
    history = SimpleNamespace(ticker="NVDA", session=DAY, batch=batch)
    prices = (100.00, 100.22, 100.25) if direction == "LONG" else (100.00, 99.78, 99.75)
    trades = () if short_history else tuple(
        _trade(name, OPEN + timedelta(minutes=25, seconds=seconds), price)
        for name, seconds, price in zip(("before-cross", "cross", "extreme"),
                                        (9, 10, 20), prices)
    )
    return CandidateEventInput(
        "OR_FAILURE_REV", "NVDA", DAY,
        (OPEN + timedelta(minutes=30),), history, trades, (),
        tuple([bar.record_id for bar in bars] + [trade.record_id for trade in trades]),
    )


@pytest.mark.parametrize("break_direction,reversal_direction", (
    ("LONG", "SHORT"), ("SHORT", "LONG"),
))
def test_synthetic_ended_orb_parent_builds_canonical_reversal_step(
    break_direction, reversal_direction,
):
    value = _input(direction=break_direction)
    result = scan_retained_or_failure_parents(value, trade_coverage=_coverage(value))
    assert result.version == RUN_VERSION
    assert len(result.handoff_requests) == len(result.reversal_steps) == 1
    request = result.handoff_requests[0]
    step = result.reversal_steps[0]
    assert request.policy.definition_reference == DEFINITION_REFERENCE
    assert request.attempt.gate("ATTEMPT_ACTIVE").reason == "INSIDE_OR_CLOSE_INVALIDATION"
    assert request.attempt.candidate.direction == break_direction
    assert step.handoff.direction == reversal_direction
    assert step.handoff.state.substate == "FAILURE_FORMING"
    assert step.confirmation_close.record_id == "bar-25"
    assert set(step.handoff.gate("REAL_BREAK_EXCURSION").input_record_ids) == {"extreme"}
    assert result.unavailable_reasons == ()
    connected = build_retained_remaining_request(value, trade_coverage=_coverage(value))
    assert connected.handoff_requests == result.handoff_requests
    assert connected.reversal_steps == result.reversal_steps
    assert connected.missing_required_inputs == (
        "QUOTE_DECISION_UNAVAILABLE", "CONFIDENCE_UNAVAILABLE")


def test_missing_coverage_stays_explicit_and_builds_no_parent():
    result = scan_retained_or_failure_parents(_input(short_history=True))
    assert result.handoff_requests == result.reversal_steps == ()
    assert result.unavailable_reasons == ("RETAINED_TRADES_UNAVAILABLE",)


def _with_bars(value, bars, *, conventions=None):
    batch = replace(value.history.batch, bars=tuple(bars),
                    conventions=conventions or value.history.batch.conventions)
    return replace(value, history=SimpleNamespace(ticker=value.ticker, session=value.session, batch=batch),
                   source_record_ids=tuple(row.record_id for row in (*bars, *value.trades, *value.quotes)))


def _with_trades(value, trades):
    return replace(value, trades=tuple(trades), source_record_ids=tuple(
        row.record_id for row in (*value.history.batch.bars, *trades, *value.quotes)))


def _coverage(value):
    # Explicit synthetic interval evidence, absent from retained source inputs.
    start = min(row.trade_time for row in value.trades)
    moments = {row.metadata.available_time for row in value.trades}
    moments.update(bar.metadata.available_time for bar in value.history.batch.bars
                   if bar.metadata.available_time >= start)
    return tuple(TradeCoverage(
        value.ticker, value.session, value.history.batch.source, start, at, at,
        tuple(row.record_id for row in value.trades if row.metadata.available_time <= at),
        True, False, "SYNTHETIC_TEST_ONLY",
    ) for at in sorted(moments))


def _assert_unavailable(value, reason, *, evidence=None):
    result = scan_retained_or_failure_parents(
        value, trade_coverage=_coverage(value) if evidence is None else evidence)
    assert result.handoff_requests == result.reversal_steps == ()
    assert reason in result.unavailable_reasons
    return result


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("case,reason", (
    ("provisional_open", "OPENING_RANGE_PROVISIONAL"),
    ("unknown_conventions", "OPENING_RANGE_UNKNOWN_CONVENTIONS"),
    ("unknown_quality", "OPENING_RANGE_QUALITY_UNKNOWN"),
    ("missing_open", "OPENING_RANGE_MISSING"),
    ("duplicate_interval", "OPENING_RANGE_CONFLICT"),
    ("revised_open", "OPENING_RANGE_REVISION_UNAVAILABLE"),
    ("late_open", "OPENING_RANGE_NOT_AVAILABLE_AT_CROSSING"),
    ("atr_gap", "ATR_1M_20_SMA_UNAVAILABLE"),
    ("atr_future", "ATR_1M_20_SMA_UNAVAILABLE"),
    ("pending_close", "REACCEPTANCE_PROVISIONAL"),
    ("unknown_close", "REACCEPTANCE_QUALITY_UNKNOWN"),
    ("missing_close", "REACCEPTANCE_MISSING"),
))
def test_final_available_complete_bar_evidence_is_required(direction, case, reason):
    value = _input(direction=direction)
    bars = list(value.history.batch.bars)
    conventions = CONVENTIONS
    if case == "provisional_open":
        bars[0] = replace(bars[0], is_final=False)
    elif case == "unknown_conventions":
        conventions = replace(CONVENTIONS, finality="UNKNOWN")
    elif case == "unknown_quality":
        bars[0] = replace(bars[0], metadata=replace(bars[0].metadata, quality="UNKNOWN"))
    elif case == "missing_open":
        del bars[0]
    elif case == "duplicate_interval":
        bars.append(replace(bars[0], record_id="conflict", high=101))
    elif case == "revised_open":
        bars[0] = replace(bars[0], metadata=replace(bars[0].metadata, revision=1))
    elif case in ("late_open", "atr_future"):
        index = 0 if case == "late_open" else 24
        bars[index] = replace(bars[index], metadata=replace(
            bars[index].metadata, available_time=OPEN + timedelta(minutes=26)))
    elif case == "atr_gap":
        del bars[10]
    elif case == "pending_close":
        bars[25] = replace(bars[25], is_final=False)
    elif case == "unknown_close":
        bars[25] = replace(bars[25], metadata=replace(bars[25].metadata, quality="UNKNOWN"))
    elif case == "missing_close":
        del bars[25]
    _assert_unavailable(_with_bars(value, bars, conventions=conventions), reason)


@pytest.mark.parametrize("index", (1, 2))
@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("case,reason", (
    ("quality", "TRADE_SOURCE_QUALITY_UNAVAILABLE"),
    ("status", "TRADE_SOURCE_QUALITY_UNAVAILABLE"),
    ("revision", "TRADE_SOURCE_QUALITY_UNAVAILABLE"),
    ("delayed", "TRADE_DELAY_STATUS_UNAVAILABLE"),
    ("delay_unknown", "TRADE_DELAY_STATUS_UNAVAILABLE"),
    ("stale", "TRADE_FRESHNESS_UNAVAILABLE"),
    ("time_mismatch", "TRADE_NOT_AVAILABLE_AT_OBSERVATION"),
    ("no_price", "TRADE_VALUE_UNAVAILABLE"),
))
def test_bad_trade_cannot_supply_a_crossing_or_extreme(direction, case, reason, index):
    value = _input(direction=direction)
    trades = list(value.trades)
    row = trades[index]
    if case == "quality":
        row = replace(row, metadata=replace(row.metadata, quality="UNKNOWN"))
    elif case == "status":
        row = replace(row, status="STALE")
    elif case == "revision":
        row = replace(row, metadata=replace(row.metadata, revision=1))
    elif case in ("delayed", "delay_unknown"):
        row = replace(row, delayed=True if case == "delayed" else None)
    elif case == "stale":
        row = replace(row, metadata=replace(row.metadata, available_time=row.trade_time + timedelta(seconds=4)))
    elif case == "time_mismatch":
        row = replace(row, metadata=replace(row.metadata, source_time=row.trade_time - timedelta(seconds=1)))
    elif case == "no_price":
        row = replace(row, last=None)
    trades[index] = row
    _assert_unavailable(_with_trades(value, trades), reason)


@pytest.mark.parametrize("case", ("absent", "partial", "late", "gap", "halt", "halt_unknown", "wrong_source", "missing_id"))
def test_tape_coverage_and_halt_are_never_inferred(case):
    value = _input()
    evidence = _coverage(value)
    if case == "absent":
        evidence = ()
    else:
        changes = {
            "partial": {"complete": False},
            "late": {"available_at": OPEN + timedelta(minutes=31)},
            "gap": {"start": value.trades[1].trade_time},
            "halt": {"halted": True}, "halt_unknown": {"halted": None},
            "wrong_source": {"source": "OTHER"}, "missing_id": {"input_record_ids": ()},
        }[case]
        evidence = tuple(replace(row, **changes) for row in evidence if row.end >= value.trades[1].trade_time)
    _assert_unavailable(value, "TRADE_COVERAGE_OR_HALT_UNAVAILABLE", evidence=evidence)


@pytest.mark.parametrize("field,value", (("instrument_id", "AAPL"), ("session", "2026-01-06"), ("source", "OTHER")))
def test_trade_source_scope_is_enforced(field, value):
    supplied = _input()
    trades = list(supplied.trades)
    trades[1] = replace(trades[1], metadata=replace(trades[1].metadata, **{field: value}))
    with pytest.raises(ValueError, match="match the producer"):
        scan_retained_or_failure_parents(_with_trades(supplied, trades))


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_first_failed_crossing_is_not_restarted(direction):
    value = _input(direction=direction)
    sign = 1 if direction == "LONG" else -1
    # First crossing clears the buffer but never reaches the meaningful excursion.
    prices = (100, 100 + sign * .115, 100, 100 + sign * .25)
    times = ((25, 9), (25, 10), (29, 9), (29, 10))
    trades = tuple(_trade(f"attempt-{i}", OPEN + timedelta(minutes=m, seconds=s), price)
                   for i, ((m, s), price) in enumerate(zip(times, prices)))
    value = _with_trades(value, trades)
    _assert_unavailable(value, "FIRST_CROSSING_EXCURSION_INSUFFICIENT")


@pytest.mark.parametrize("delay,accepted", ((0, True), (1, False)))
def test_original_180_second_deadline_includes_equality(delay, accepted):
    value = _input()
    # First crossing is 25:00; first inside close is 28:00.
    value = _with_trades(value, tuple(replace(row,
        trade_time=row.trade_time - timedelta(seconds=10),
        metadata=_metadata(row.trade_time - timedelta(seconds=10))) for row in value.trades))
    bars = list(value.history.batch.bars)
    bars[25], bars[26] = _bar(25, close=100.22), _bar(26, close=100.22)
    bars[27] = replace(bars[27], metadata=replace(
        bars[27].metadata, available_time=bars[27].end_time + timedelta(seconds=delay)))
    value = _with_bars(value, bars)
    result = scan_retained_or_failure_parents(value, trade_coverage=_coverage(value))
    assert bool(result.handoff_requests) is accepted
    if accepted:
        assert result.handoff_requests[0].minute_close.bar_end == OPEN + timedelta(minutes=28)
    else:
        assert result.unavailable_reasons == ("FIRST_CROSSING_REACCEPTANCE_UNAVAILABLE",)


def test_actual_availability_is_preserved_and_future_extreme_cannot_rescue_failure():
    value = _input()
    bars = list(value.history.batch.bars)
    bars[25] = replace(bars[25], metadata=replace(
        bars[25].metadata, available_time=bars[25].end_time + timedelta(seconds=1)))
    value = _with_bars(value, bars)
    result = scan_retained_or_failure_parents(value, trade_coverage=_coverage(value))
    request = result.handoff_requests[0]
    assert request.minute_close.available_at == OPEN + timedelta(minutes=26, seconds=1)
    assert request.evaluated_at == request.minute_close.available_at
    trades = list(value.trades)
    trades[1] = replace(trades[1], last=100.115)
    trades[2] = replace(trades[2], metadata=replace(
        trades[2].metadata, available_time=OPEN + timedelta(minutes=27)))
    # A future strong trade cannot change the first reacceptance's result.
    result = scan_retained_or_failure_parents(_with_trades(value, trades), trade_coverage=_coverage(value))
    assert result.handoff_requests == ()


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_expired_first_crossing_cannot_be_replaced_by_a_later_match(direction):
    value = _input(direction=direction)
    outside = 100.22 if direction == "LONG" else 99.78
    bars = list(value.history.batch.bars)
    for index in range(25, 29):
        bars[index] = _bar(index, close=outside)
    value = _with_bars(value, bars)
    later = (_trade("later-before", OPEN + timedelta(minutes=29, seconds=9), 100),
             _trade("later-cross", OPEN + timedelta(minutes=29, seconds=10), outside))
    value = _with_trades(value, (*value.trades, *later))
    _assert_unavailable(value, "FIRST_CROSSING_REACCEPTANCE_UNAVAILABLE")


def test_future_confirmation_is_not_visible_at_an_earlier_decision():
    value = replace(_input(), decision_moments=(OPEN + timedelta(minutes=25, seconds=30),))
    _assert_unavailable(value, "FIRST_CROSSING_REACCEPTANCE_UNAVAILABLE")


def test_setup_end_is_exclusive_even_when_deadline_has_time_left():
    value = _input()
    bars = [_bar(index) for index in range(45)]
    batch = replace(value.history.batch,
                    request=HistoryRequest("NVDA", OPEN, OPEN + timedelta(minutes=45)),
                    bars=tuple(bars))
    value = replace(value, history=SimpleNamespace(batch=batch),
                    decision_moments=(OPEN + timedelta(minutes=45),))
    trades = tuple(_trade(row.record_id, row.trade_time + timedelta(minutes=19), row.last)
                   for row in value.trades)
    value = _with_trades(value, trades)
    _assert_unavailable(value, "FIRST_CROSSING_REACCEPTANCE_UNAVAILABLE")


def test_unknown_finality_reason_reaches_the_remaining_producer():
    value = _input()
    bars = [replace(bar, is_final=False) for bar in value.history.batch.bars]
    value = _with_bars(value, bars, conventions=replace(CONVENTIONS, finality="UNKNOWN"))
    built = build_retained_remaining_request(value)
    assert built.handoff_requests == built.reversal_steps == ()
    assert "OPENING_RANGE_PROVISIONAL" in built.missing_required_inputs


def test_recorded_parent_scan_is_deterministic():
    # This records a source gap, not a real retained-session match. The protected
    # child has no raw retained files. The actual retained adapters preserve the
    # same unknown finality and quality; never replace those facts to get a pass.
    value = _input()
    converted = tuple(normalize_databento_ohlcv_1m({
        "publisher_id": 7, "instrument_id": 1,
        "ts_event": int(bar.start_time.timestamp()) * 1_000_000_000,
        "open": 100_000_000_000, "high": 100_100_000_000,
        "low": 99_900_000_000, "close": 100_000_000_000, "volume": 1000,
    }, record_id=f"synthetic-adapter:{index}", context=DatabentoMinuteContext(
        dataset="EQUS.MINI", raw_symbol="NVDA", instrument_id=1, session=DAY,
        received_time=bar.end_time, available_time=bar.end_time, normalized_time=bar.end_time,
        source_file_sha256="a" * 64, provider_condition="AVAILABLE", instrument_type="EQUITY",
    )) for index, bar in enumerate(value.history.batch.bars))
    value = _with_bars(value, [record.bar for record in converted],
                      conventions=replace(CONVENTIONS, finality="UNKNOWN"))
    result = scan_retained_or_failure_parents(value)
    assert result.unavailable_reasons == ("OPENING_RANGE_PROVISIONAL",)
    assert result.handoff_requests == result.reversal_steps == ()
    proof = {
        "version": result.version,
        "evidence_kind": "SYNTHETIC_CONTRACT_AND_RETAINED_FIELD_GAP_ASSESSMENT",
        "real_retained_session_match": False,
        "retained_files_opened": False,
        "source_contracts": ["consensus_engine/databento_minute_bars.py",
                             "consensus_engine/retained_quote_trade_reader.py"],
        "retained_required_fields": {
            "original_availability": converted[0].original_availability,
            "finality": converted[0].finality,
            "correction_state": converted[0].correction_state, "trade_interval_coverage": "UNAVAILABLE",
            "halt_status": "UNKNOWN", "trade_delayed_status": "UNKNOWN",
        },
        "dependent_rule": {"id": DEFINITION_REFERENCE, "status": "OFF_UNTESTED_ON_RETAINED_SOURCE"},
        "handoffs": [], "reversal_steps": [],
        "synthetic_source_record_ids": list(result.source_record_ids),
        "unavailable_reasons": list(result.unavailable_reasons),
        "held_out_opened": False,
        "fills_returns_or_packages_calculated": False,
    }
    rendered = json.dumps(proof, sort_keys=True, indent=2) + "\n"
    repeated = scan_retained_or_failure_parents(value)
    assert repeated == result
    output = Path(os.environ["TMPDIR"], "m91dd-retained-or-failure-parent-scan-proof.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
