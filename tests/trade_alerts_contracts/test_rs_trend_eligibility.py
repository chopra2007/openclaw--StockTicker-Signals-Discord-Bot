"""M7.2 supplied-input RS and trend contracts; no approved threshold is adopted.

Every number below is a synthetic fixture supplied by the caller. Passing gates
prove the offline contract only: they establish no provider coverage, no adopted
`HOD_COMP_RS` rule, no trigger and no permission to act. The lookback, the
warm-up answer, the return basis and every cutoff stay the caller's.

The daily-ATR-percent and open-return roles have no producer of their own yet,
so they are bound to supplied fixture snapshots; the M7.1 reference and
compression flags and the M7.2 relative strength are built by their real modules
in the end-to-end case.
"""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine import db, rs_trend_eligibility
from consensus_engine.event_store import ResearchEventStore
from consensus_engine.historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from consensus_engine.hod_compression import CompressionPolicy, build_hod_compression_snapshot
from consensus_engine.quote_events import QuoteEventPolicy, QuoteEventStream
from consensus_engine.rs_trend_eligibility import (
    ARMED_GATES, DATA_MODE, ELIGIBILITY_VERSION, FeatureBinding, GateResult,
    HodCompRsEligibilityMachine, MandatoryStatus, REQUIRED_ROLES, RS_DATA_MODE,
    RS_FEATURE_NAMES, RS_FEATURE_VERSION, RULES_VERSION, RsTrendPolicy, RsTrendRequest,
    RsWindowPolicy, SETUP_GATES, STRATEGY_ID, WINDOW_GATE, build_rs_trend_snapshot,
    evaluate_rs_trend_eligibility, rs_trend_rules,
)
from consensus_engine.state_transitions import StateTransitionEngine, TransitionScope
from consensus_engine.strategy_interface import StrategyContext, StrategyState
from consensus_engine.trade_alerts_models import (
    Bar, FeatureSnapshot, FeatureValue, Quote, RecordError, SourceMetadata,
)
from consensus_engine.transition_store import SQLiteTransitionStore
from consensus_engine.utils.time_context import as_utc, session_bounds
from test_strategy_interface import session


PACIFIC = ZoneInfo("America/Los_Angeles")
DAY = "2026-07-06"
OPENED = datetime(2026, 7, 6, 6, 30, tzinfo=PACIFIC)
AT = datetime(2026, 7, 6, 6, 50, 10, tzinfo=PACIFIC)
VERSION = "M72_FIXTURE_ONLY_V1"
POLICY_VERSION = "M72_SUPPLIED_FIXTURE_POLICY_V1"
BENCHMARK = "SYNTHBENCH"

CONTEXT = ("M72_SUPPLIED_CONTEXT_V1", "SUPPLIED_CONTEXT_FIXTURE")
RS = (RS_FEATURE_VERSION, RS_DATA_MODE)
COMPRESSION = ("M71_HOD_COMPRESSION_V1", "SUPPLIED_BAR_HOD_COMPRESSION")
BINDINGS = {
    "MEDIAN_DOLLAR_VOLUME": ("DOLLAR_VOLUME_FIXTURE_V1", CONTEXT, "USD"),
    "RVOL": ("RVOL_FIXTURE_V1", CONTEXT, "RATIO"),
    "OPEN_RETURN": ("OPEN_RETURN_FIXTURE_V1", CONTEXT, "RATIO"),
    "DAILY_ATR_PCT": ("DAILY_ATR_PCT_FIXTURE_V1", CONTEXT, "RATIO"),
    "SESSION_VWAP": ("SESSION_VWAP_FIXTURE_V1", CONTEXT, "USD_PER_SHARE"),
    "RS": ("RS_LOOKBACK_V1", RS, "RATIO"),
    "RS_WARMUP_COMPLETE": ("RS_WARMUP_COMPLETE_V1", RS, "BOOLEAN"),
    "REFERENCE_EXTREME_COMPLETE": ("REFERENCE_EXTREME_COMPLETE_V1", COMPRESSION, "BOOLEAN"),
    "COMPRESSION_COMPLETE": ("COMPRESSION_COMPLETE_V1", COMPRESSION, "BOOLEAN"),
}
GROUPS = {
    CONTEXT: ("DOLLAR_VOLUME_FIXTURE_V1", "RVOL_FIXTURE_V1", "OPEN_RETURN_FIXTURE_V1",
              "DAILY_ATR_PCT_FIXTURE_V1", "SESSION_VWAP_FIXTURE_V1"),
    RS: ("RS_LOOKBACK_V1", "RS_WARMUP_COMPLETE_V1"),
    COMPRESSION: ("REFERENCE_EXTREME_COMPLETE_V1", "COMPRESSION_COMPLETE_V1"),
}
RECORDS = {CONTEXT: "m72-context", RS: "m72-rs", COMPRESSION: "m72-compression"}
# Synthetic supplied values only; every one of them is a fixture.
VALUES = {
    "DOLLAR_VOLUME_FIXTURE_V1": 50_000_000.0, "RVOL_FIXTURE_V1": 2.0,
    "OPEN_RETURN_FIXTURE_V1": 0.012, "DAILY_ATR_PCT_FIXTURE_V1": 0.02,
    "SESSION_VWAP_FIXTURE_V1": 100.5, "RS_LOOKBACK_V1": 0.004,
    "RS_WARMUP_COMPLETE_V1": 1.0, "REFERENCE_EXTREME_COMPLETE_V1": 1.0,
    "COMPRESSION_COMPLETE_V1": 1.0,
}
QUOTES = {"LONG": (101.02, 101.04, 101.03), "SHORT": (98.96, 98.98, 98.97)}


def mirror(value):
    return float(Decimal(200) - Decimal(str(value)))


def metadata(at=AT, **changes):
    values = dict(instrument_id="SYNTH", instrument_type="EQUITY", source="SYNTHETIC",
                  source_time=at, received_time=at, available_time=at, normalized_time=at,
                  session=DAY, data_mode="FIXTURE", quality="VALID")
    values.update(changes)
    return SourceMetadata(**values)


def snapshot(definition, *, direction="LONG", at=AT, changed=None, **changes):
    version, mode = definition
    changed = changed or {}
    features = []
    for name in GROUPS[definition]:
        value = changed[name] if name in changed else VALUES[name]
        unit = next(row[2] for row in BINDINGS.values() if row[0] == name)
        if direction == "SHORT" and value is not None:
            if name == "SESSION_VWAP_FIXTURE_V1":
                value = mirror(value)
            if name == "RS_LOOKBACK_V1":
                value = -value
        features.append(FeatureValue(name, value, unit,
                                     None if value is not None else "MISSING_INPUT",
                                     ("supplied-" + name,)))
    values = dict(record_id=RECORDS[definition], metadata=metadata(at, data_mode=mode),
                  evaluated_at=at, feature_version=version, features=tuple(features),
                  input_record_ids=tuple("supplied-" + name for name in GROUPS[definition]))
    values.update(changes)
    return FeatureSnapshot.from_json(FeatureSnapshot(**values).to_json())


def snapshots(direction="LONG", *, changed=None, at=AT):
    return tuple(snapshot(definition, direction=direction, changed=changed, at=at)
                 for definition in (CONTEXT, RS, COMPRESSION))


def quote_record(direction="LONG", *, at=AT, **changes):
    supplied_bid, supplied_ask, supplied_last = QUOTES[direction]
    values = dict(
        record_id="m72-quote-" + at.isoformat(), metadata=metadata(at),
        quote_time=at, trade_time=at, bid=supplied_bid, ask=supplied_ask,
        last=supplied_last, status="VALID", delayed=False,
    )
    values.update(changes)
    return Quote.from_json(Quote(**values).to_json())


def decision(direction="LONG", *, at=AT, age=0, **changes):
    """One supplied quote-stream decision; age moves the observation backward."""
    policy = QuoteEventPolicy(VERSION, 3, 3, 10)
    stream = QuoteEventStream(source="SYNTHETIC", instrument_id="SYNTH", instrument_type="EQUITY",
                              session=DAY, data_mode="FIXTURE", policy=policy)
    observed = at - timedelta(seconds=age)
    supplied = quote_record(direction, at=observed, **changes)
    stream.connect(observed)
    stream.consume(supplied, at=observed)
    stream.confirm_continuity(at=observed, epoch=stream.inspect(observed).epoch,
                              record_id=supplied.record_id,
                              evidence_reference="M72_SYNTHETIC_CONTINUITY")
    return stream.inspect(at)


def bindings():
    return tuple(FeatureBinding(role, BINDINGS[role][0], BINDINGS[role][1][0],
                                BINDINGS[role][1][1], BINDINGS[role][2])
                 for role in REQUIRED_ROLES)


def policy(**changes):
    values = dict(
        version=POLICY_VERSION, definition_reference="M72_SUPPLIED_FIXTURE_DEFINITION",
        window_start_minutes=5, window_end_minutes=45, min_price=5.0,
        min_median_dollar_volume=50_000_000.0, min_rvol=1.5, min_abs_open_return=0.005,
        open_return_atr_multiple=0.2, min_rs=0.003, rs_atr_multiple=0.15,
        max_spread_bps=20.0, max_quote_age_seconds=3.0, max_trade_age_seconds=3.0,
        max_feature_age_seconds=60.0, bindings=bindings(),
    )
    values.update(changes)
    return RsTrendPolicy(**values)


def status(**changes):
    values = dict(halted=False, macro_blackout_active=False, catalyst_coverage="COMPLETE",
                  definition_reference="M72_SUPPLIED_STATUS_DEFINITION",
                  evidence_reference="M72_SYNTHETIC_STATUS", available_at=AT)
    values.update(changes)
    return MandatoryStatus(**values)


def context(direction="LONG", **changes):
    values = dict(session=session(DAY), symbol="SYNTH", instrument_type="EQUITY",
                  direction=direction, evaluated_at=AT, features=snapshots(direction),
                  quote=decision(direction), catalysts=())
    values.update(changes)
    return StrategyContext(**values)


def eligibility(direction="LONG", **changes):
    values = dict(context=context(direction), policy=policy(), status=status())
    values.update(changes)
    return RsTrendRequest(**values)


def state_of(request):
    return evaluate_rs_trend_eligibility(request).state.state


def machine(direction="LONG", **changes):
    values = dict(session=session(DAY), symbol="SYNTH", instrument_type="EQUITY",
                  direction=direction, strategy_version=VERSION, policy=policy())
    values.update(changes)
    return HodCompRsEligibilityMachine(**values)


# --- supplied minute histories for the RS measurement -----------------------


LOOKBACK = RsWindowPolicy(version="M72_TEST_LOOKBACK_V1",
                          definition_reference="M72_SYNTHETIC_LOOKBACK_ONLY",
                          benchmark_symbol=BENCHMARK, lookback_bars=15,
                          return_basis="FIRST_BAR_OPEN")
PRIOR_CLOSE = replace(LOOKBACK, return_basis="PRIOR_BAR_CLOSE")


def conventions(**changes):
    values = dict(
        timestamp="START", session="REGULAR", adjustment_basis="SYNTHETIC_RAW",
        price="USD_PER_SHARE", volume="SHARES", coverage_basis="SYNTHETIC_COMPLETE",
        finality="SYNTHETIC_FINAL", publication="SYNTHETIC_RECEIPT",
        evidence_reference="M72_SYNTHETIC_ONLY",
    )
    values.update(changes)
    return HistoryConventions(**values)


def make_bar(number, interval, opened, close, *, symbol="SYNTH", no_trade=False, revision=0,
             is_final=True, instrument_type="EQUITY", prefix="rs"):
    high, low = max(opened, close) + 0.05, min(opened, close) - 0.05
    meta = SourceMetadata(
        instrument_id=symbol, instrument_type=instrument_type, source="SYNTHETIC",
        source_time=interval.start, received_time=interval.end, available_time=interval.end,
        normalized_time=interval.end, session=interval.session, revision=revision,
        data_mode="SYNTHETIC_HISTORY", quality="VALID",
    )
    return Bar(
        record_id=f"{prefix}-{symbol}-{number}-r{revision}", metadata=meta,
        start_time=interval.start, end_time=interval.end, is_final=is_final,
        open=None if no_trade else opened, high=None if no_trade else high,
        low=None if no_trade else low, close=None if no_trade else close,
        volume=0 if no_trade else 1000 + number,
        adjustment_basis="SYNTHETIC_RAW", price_convention="USD_PER_SHARE",
        volume_convention="SHARES", certified_no_trade=no_trade,
    )


def walk(first, step, count):
    """A straight synthetic path; each bar opens where the last one closed."""
    values = [float(Decimal(str(first)) + Decimal(str(step)) * number)
              for number in range(count + 1)]
    return list(zip(values, values[1:]))


def history(symbol="SYNTH", *, first=100.00, step=0.10, minutes=15, path=None, changed=None,
            supplied_conventions=None, day=DAY, **request_changes):
    opened = as_utc(session_bounds(datetime.fromisoformat(day).date())[0])
    path = path or walk(first, step, minutes)
    values = dict(symbol=symbol, start=opened, end=opened + timedelta(minutes=len(path)))
    values.update(request_changes)
    request = HistoryRequest(**values)
    bars = [make_bar(number, interval, path[number][0], path[number][1],
                     symbol=request.symbol)
            for number, interval in enumerate(request.expected_intervals())]
    if changed:
        bars = changed(bars)
    return HistoryBatch(request, "SYNTHETIC", supplied_conventions or conventions(), tuple(bars))


def rs_snapshot(stock=None, benchmark=None, *, evaluated=None, supplied=LOOKBACK, **changes):
    values = dict(
        record_id="m72-rs-measured", evaluated_at=evaluated or AT, symbol="SYNTH",
        instrument_type="EQUITY",
        minute_history=history() if stock is None else stock,
        benchmark_history=history(BENCHMARK, first=400.00, step=0.08)
        if benchmark is None else benchmark,
        policy=supplied,
    )
    values.update(changes)
    return build_rs_trend_snapshot(**values)


def measured(output):
    return {item.name: item for item in output.features}


def numbers(output, *names):
    return [measured(output)[name].value for name in names]


def missing(output, *names):
    return [measured(output)[name].missing_reason for name in names]


# --- one relative-strength measurement --------------------------------------


def test_rs_is_the_difference_between_the_two_supplied_returns():
    output = rs_snapshot()
    assert numbers(output, "STOCK_RETURN_LOOKBACK_V1", "BENCHMARK_RETURN_LOOKBACK_V1",
                   "RS_LOOKBACK_V1") == [0.015, 0.003, 0.012]
    assert numbers(output, "RS_LOOKBACK_BARS_V1", "RS_WARMUP_COMPLETE_V1") == [15, 1]
    assert output.feature_version == RS_FEATURE_VERSION
    assert output.metadata.data_mode == RS_DATA_MODE
    assert len(measured(output)["STOCK_RETURN_LOOKBACK_V1"].input_record_ids) == 15
    assert len(output.input_record_ids) == 30


def test_the_two_supplied_return_bases_measure_different_returns():
    """The same bars, two supplied answers, two returns; the module picks neither."""
    # One gap between the first close and the next open separates the answers.
    gapped = history(path=[(99.00, 99.50)] + walk(100.00, 0.10, 15))
    first = rs_snapshot(gapped)
    prior = rs_snapshot(gapped, supplied=PRIOR_CLOSE)
    assert numbers(first, "STOCK_RETURN_LOOKBACK_V1") == [0.015]
    assert numbers(prior, "STOCK_RETURN_LOOKBACK_V1") == [pytest.approx(2.00 / 99.50)]
    assert LOOKBACK.required_bars == 15 and PRIOR_CLOSE.required_bars == 16
    assert len(measured(prior)["STOCK_RETURN_LOOKBACK_V1"].input_record_ids) == 16


def test_the_lookback_never_shortens_itself_before_warm_up():
    early = datetime(2026, 7, 6, 6, 40, tzinfo=PACIFIC)
    output = rs_snapshot(evaluated=early)
    assert numbers(output, "RS_WARMUP_COMPLETE_V1") == [0]
    assert missing(output, "STOCK_RETURN_LOOKBACK_V1", "RS_LOOKBACK_V1") == [
        "RS_WARMUP_INCOMPLETE"] * 2
    assert missing(output, "BENCHMARK_RETURN_LOOKBACK_V1") == ["BENCHMARK_RS_WARMUP_INCOMPLETE"]
    # The fifteenth supplied minute ends exactly at 06:45; nothing measures before it.
    warm = rs_snapshot(evaluated=datetime(2026, 7, 6, 6, 45, tzinfo=PACIFIC))
    assert numbers(warm, "RS_WARMUP_COMPLETE_V1") == [1]
    assert numbers(warm, "STOCK_RETURN_LOOKBACK_V1") == [0.015]


@pytest.mark.parametrize("change,reason", (
    ("missing", "RS_WINDOW_MISSING"),
    ("provisional", "RS_WINDOW_PROVISIONAL"),
    ("quiet", "NO_TRADED_RS_INTERVAL"),
    ("overlapping", "UNEXPECTED_OVERLAPPING_RECORD"),
    ("foreign", "INCOMPATIBLE_INSTRUMENT_TYPE"),
))
def test_a_broken_lookback_is_refused_by_name(change, reason):
    def apply(bars):
        if change == "missing":
            return [row for index, row in enumerate(bars) if index != 10]
        if change == "provisional":
            return [replace(row, is_final=False) if index == 10 else row
                    for index, row in enumerate(bars)]
        if change == "quiet":
            return [replace(row, open=None, high=None, low=None, close=None, volume=0,
                            certified_no_trade=True) if index == 10 else row
                    for index, row in enumerate(bars)]
        if change == "foreign":
            return [replace(row, metadata=replace(row.metadata, instrument_type="ETF"))
                    if index == 10 else row for index, row in enumerate(bars)]
        start = bars[10].start_time + timedelta(seconds=30)
        end = bars[10].end_time + timedelta(seconds=30)
        meta = replace(bars[10].metadata, source_time=start, received_time=end,
                       available_time=end, normalized_time=end)
        return [*bars, replace(bars[10], record_id="rs-overlap", metadata=meta,
                               start_time=start, end_time=end)]

    output = rs_snapshot(history(changed=apply))
    assert missing(output, "STOCK_RETURN_LOOKBACK_V1", "RS_LOOKBACK_V1") == [reason] * 2
    # The benchmark keeps its own fate; only the stock side is broken here.
    assert numbers(output, "BENCHMARK_RETURN_LOOKBACK_V1") == [0.003]


def test_a_history_shorter_than_the_lookback_is_incomplete_not_shortened():
    output = rs_snapshot(history(minutes=10))
    assert numbers(output, "RS_WARMUP_COMPLETE_V1") == [1]
    assert missing(output, "STOCK_RETURN_LOOKBACK_V1") == ["INCOMPLETE_RS_WINDOW"]


def test_a_broken_benchmark_keeps_the_stock_return_and_names_its_own_side():
    output = rs_snapshot(benchmark_history=None)
    assert numbers(output, "STOCK_RETURN_LOOKBACK_V1") == [0.015]
    assert missing(output, "BENCHMARK_RETURN_LOOKBACK_V1", "RS_LOOKBACK_V1") == [
        "BENCHMARK_MISSING_MINUTE_HISTORY"] * 2


@pytest.mark.parametrize("supplied,reason", (
    (None, "MISSING_MINUTE_HISTORY"),
    ("symbol", "INCOMPATIBLE_SYMBOL"),
    ("interval", "INCOMPATIBLE_HISTORY_INTERVAL"),
    ("price", "INCOMPATIBLE_PRICE_UNIT"),
    ("volume", "INCOMPATIBLE_VOLUME_UNIT"),
    ("basis", "UNKNOWN_SOURCE_OR_VENUE_BASIS"),
))
def test_incompatible_or_absent_stock_history_is_named_for_every_return(supplied, reason):
    bounds = session_bounds(datetime.fromisoformat(DAY).date())
    cases = {
        None: None,
        "symbol": history(symbol="OTHER"),
        "interval": HistoryBatch(HistoryRequest("SYNTH", as_utc(bounds[0]), as_utc(bounds[1]),
                                                "1d"), "SYNTHETIC", conventions(), ()),
        "price": history(supplied_conventions=conventions(price="USD_PER_CONTRACT")),
        "volume": history(supplied_conventions=conventions(volume="CONTRACTS")),
        "basis": history(supplied_conventions=conventions(coverage_basis="UNKNOWN")),
    }
    output = rs_snapshot(minute_history=cases[supplied])
    assert missing(output, "STOCK_RETURN_LOOKBACK_V1", "RS_LOOKBACK_V1") == [reason] * 2
    assert measured(output)["STOCK_RETURN_LOOKBACK_V1"].input_record_ids == ()


def test_a_closed_day_refuses_both_returns():
    holiday = datetime(2026, 7, 3, 6, 50, 10, tzinfo=PACIFIC)
    output = rs_snapshot(evaluated=holiday, minute_history=None, benchmark_history=None)
    assert missing(output, "STOCK_RETURN_LOOKBACK_V1", "BENCHMARK_RETURN_LOOKBACK_V1",
                   "RS_LOOKBACK_V1") == ["NO_REGULAR_SESSION"] * 3
    assert numbers(output, "RS_WARMUP_COMPLETE_V1") == [0]


@pytest.mark.parametrize("changes", (
    {"version": " "}, {"definition_reference": "UNKNOWN"}, {"benchmark_symbol": ""},
    {"lookback_bars": 0}, {"lookback_bars": 15.0}, {"lookback_bars": True},
    {"return_basis": "PREVIOUS_CLOSE"},
))
def test_the_supplied_lookback_must_be_explicit_and_supported(changes):
    with pytest.raises(RecordError):
        replace(LOOKBACK, **changes)


def test_rs_public_scope_is_checked_before_any_measurement():
    with pytest.raises(RecordError, match="symbol is required"):
        rs_snapshot(symbol="")
    with pytest.raises(RecordError, match="instrument type"):
        rs_snapshot(instrument_type="OPTION")
    with pytest.raises(RecordError, match="RsWindowPolicy"):
        rs_snapshot(supplied="M72")
    with pytest.raises(RecordError, match="benchmark must differ"):
        rs_snapshot(supplied=replace(LOOKBACK, benchmark_symbol="SYNTH"))
    with pytest.raises(RecordError, match="evaluated_at"):
        rs_snapshot(evaluated=datetime.fromisoformat(DAY + "T06:50:10"))
    with pytest.raises(FrozenInstanceError):
        LOOKBACK.lookback_bars = 5


def test_the_module_adopts_no_rule_number_of_its_own():
    source = inspect.getsource(rs_trend_eligibility)
    for token in ("0.60", "0.35", "0.003", "0.15", "1.40", "0.70", "50_000_000", "rs_15m"):
        assert token not in source
    output = rs_snapshot()
    assert sorted(RS_FEATURE_NAMES) == sorted(item.name for item in output.features)
    assert FeatureSnapshot.from_json(output.to_json()) == output


# --- supplied policy, bindings and request contracts ------------------------


@pytest.mark.parametrize("changes", (
    {"version": " "}, {"version": "UNKNOWN"}, {"definition_reference": "UNSPECIFIED"},
    {"window_start_minutes": 45}, {"window_start_minutes": 46}, {"window_start_minutes": 5.0},
    {"window_end_minutes": True}, {"min_price": -1}, {"min_price": float("nan")},
    {"min_price": float("inf")}, {"min_price": "5"}, {"min_price": True},
    {"min_rs": -0.001}, {"rs_atr_multiple": "0.15"}, {"max_quote_age_seconds": -0.5},
    {"bindings": ()}, {"bindings": ("RVOL",)},
))
def test_policy_requires_explicit_supplied_values(changes):
    with pytest.raises(RecordError):
        policy(**changes)


def test_policy_requires_every_role_exactly_once():
    rows = bindings()
    with pytest.raises(RecordError):
        policy(bindings=rows[:-1])
    with pytest.raises(RecordError):
        policy(bindings=rows + (rows[0],))
    assert sorted(row.role for row in policy().bindings) == sorted(REQUIRED_ROLES)


@pytest.mark.parametrize("changes", (
    {"role": "PRICE"}, {"role": "rs"}, {"feature_name": ""},
    {"feature_version": "UNKNOWN"}, {"data_mode": " "}, {"unit": "UNSPECIFIED"},
))
def test_feature_binding_requires_an_explicit_definition(changes):
    values = dict(role="RS", feature_name="RS_LOOKBACK_V1", feature_version=RS[0],
                  data_mode=RS[1], unit="RATIO")
    values.update(changes)
    with pytest.raises(RecordError):
        FeatureBinding(**values)


def test_request_requires_canonical_supplied_parts():
    for changes in ({"context": None}, {"policy": None}, {"status": None}):
        with pytest.raises(RecordError):
            eligibility(**changes)


# --- the supplied path through ARMED ----------------------------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_supplied_gates_reach_armed(direction):
    result = evaluate_rs_trend_eligibility(eligibility(direction))
    assert result.state == StrategyState("ARMED") and result.reasons == ()
    assert all(result.gate(name).status == "PASS" for name in ARMED_GATES)
    assert result.gate(WINDOW_GATE).status == "PASS"
    assert result.gate("RS_TREND").observed == 0.004
    assert result.gate("RS_TREND").threshold == 0.003
    assert result.policy_version == POLICY_VERSION


@pytest.mark.parametrize("clock,expected,reason", (
    ("06:34:59", "NOT_ELIGIBLE", "BEFORE_EVALUATION_WINDOW"),
    ("06:35:00", "SETUP_FORMING", None),
    ("07:14:59", "SETUP_FORMING", None),
    ("07:15:00", "EXPIRED", "AFTER_EVALUATION_WINDOW"),
))
def test_half_open_evaluation_window(clock, expected, reason):
    """Identical supplied inputs; only the instant moves across both edges."""
    at = datetime.fromisoformat(DAY + "T" + clock).replace(tzinfo=PACIFIC)
    # The status stays unavailable, so no row can pass every ARMED gate.
    supplied = context(features=snapshots(at=at), quote=decision(at=at), evaluated_at=at)
    result = evaluate_rs_trend_eligibility(eligibility(
        context=supplied, status=status(halted=None, available_at=at)))
    assert result.gate(WINDOW_GATE).reason == reason
    assert result.state.state == expected
    assert all(result.gate(name).status == "PASS" for name in SETUP_GATES)


def test_window_uses_the_supplied_minutes_not_a_fixed_clock():
    assert state_of(eligibility(policy=policy(window_start_minutes=25,
                                              window_end_minutes=45))) == "NOT_ELIGIBLE"
    assert state_of(eligibility(policy=policy(window_start_minutes=0,
                                              window_end_minutes=15))) == "EXPIRED"


# --- the M7.1 flags and the RS warm-up --------------------------------------


@pytest.mark.parametrize("name,gate,reason,expected", (
    ("REFERENCE_EXTREME_COMPLETE_V1", "REFERENCE_FROZEN", "REFERENCE_NOT_FROZEN", "WATCHING"),
    ("COMPRESSION_COMPLETE_V1", "COMPRESSION_MEASURED", "COMPRESSION_NOT_MEASURED", "WATCHING"),
    ("RS_WARMUP_COMPLETE_V1", "RS_WARMUP", "RS_WARMUP_INCOMPLETE", "SETUP_FORMING"),
))
def test_an_unset_supplied_flag_fails_its_own_gate(name, gate, reason, expected):
    result = evaluate_rs_trend_eligibility(eligibility(
        context=context(features=snapshots(changed={name: 0.0}))))
    assert result.gate(gate).status == "FAIL" and result.gate(gate).reason == reason
    assert result.state.state == expected


@pytest.mark.parametrize("name,gate,reason", (
    ("REFERENCE_EXTREME_COMPLETE_V1", "REFERENCE_FROZEN", "REFERENCE_FLAG_NOT_BOOLEAN"),
    ("COMPRESSION_COMPLETE_V1", "COMPRESSION_MEASURED", "COMPRESSION_FLAG_NOT_BOOLEAN"),
    ("RS_WARMUP_COMPLETE_V1", "RS_WARMUP", "RS_WARMUP_FLAG_NOT_BOOLEAN"),
))
def test_a_flag_that_is_not_boolean_is_unknown_not_read_as_true(name, gate, reason):
    result = evaluate_rs_trend_eligibility(eligibility(
        context=context(features=snapshots(changed={name: 0.5}))))
    assert result.gate(gate).status == "UNKNOWN" and result.gate(gate).reason == reason
    assert result.state.state != "ARMED"


def test_an_unmeasured_rs_keeps_the_trend_gate_unknown():
    supplied = context(features=snapshots(changed={"RS_LOOKBACK_V1": None}))
    result = evaluate_rs_trend_eligibility(eligibility(context=supplied))
    assert result.gate("RS_TREND").status == "UNKNOWN"
    assert result.gate("RS_TREND").reason == "MISSING_INPUT"
    assert result.state.state == "SETUP_FORMING"


# --- missing, stale, ambiguous and mislabeled inputs ------------------------


@pytest.mark.parametrize("role", REQUIRED_ROLES)
def test_a_missing_mandatory_value_is_never_read_as_passing(role):
    name = BINDINGS[role][0]
    result = evaluate_rs_trend_eligibility(eligibility(
        context=context(features=snapshots(changed={name: None}))))
    assert result.state.state != "ARMED"
    assert any(row.status == "UNKNOWN" for row in result.gates)


@pytest.mark.parametrize("role", REQUIRED_ROLES)
def test_an_absent_snapshot_is_reported_not_assumed(role):
    binding = policy().binding(role)
    kept = tuple(row for row in snapshots() if row.feature_version != binding.feature_version)
    result = evaluate_rs_trend_eligibility(eligibility(context=context(features=kept)))
    assert result.state.state != "ARMED"
    assert any("FEATURE_ABSENT" in reason for reason in result.reasons)


@pytest.mark.parametrize("changes,reason", (
    ({"feature_version": "OTHER_PRODUCER_V1"}, "FEATURE_ABSENT"),
    ({"metadata": metadata(data_mode="OTHER_MODE")}, "FEATURE_ABSENT"),
    ({"metadata": metadata(instrument_id="OTHER", data_mode=RS[1])}, "FEATURE_ABSENT"),
    ({"metadata": metadata(instrument_type="ETF", data_mode=RS[1])}, "FEATURE_ABSENT"),
    ({"metadata": metadata(quality="DEGRADED_PROXY", data_mode=RS[1])},
     "FEATURE_QUALITY_UNAVAILABLE"),
    ({"metadata": metadata(source_time=None, data_mode=RS[1])}, "INVALID_SOURCE_TIME"),
))
def test_another_definition_or_instrument_cannot_substitute(changes, reason):
    rows = list(snapshots())
    values = dict(record_id=rows[1].record_id, metadata=rows[1].metadata, evaluated_at=AT,
                  feature_version=rows[1].feature_version, features=rows[1].features,
                  input_record_ids=rows[1].input_record_ids)
    values.update(changes)
    rows[1] = FeatureSnapshot(**values)
    result = evaluate_rs_trend_eligibility(eligibility(context=context(features=tuple(rows))))
    assert result.state.state != "ARMED"
    assert any(reason in row for row in result.reasons)


def test_a_wrong_unit_cannot_be_read_as_the_bound_value():
    supplied = policy(bindings=tuple(replace(row, unit="USD") if row.role == "RS" else row
                                     for row in bindings()))
    result = evaluate_rs_trend_eligibility(eligibility(policy=supplied))
    assert result.gate("RS_TREND").reason == "WRONG_UNIT"
    assert result.state.state == "SETUP_FORMING"


def test_two_snapshots_at_one_instant_are_ambiguous_not_preferred():
    duplicate = replace(snapshots()[1], record_id="m72-rs-copy")
    result = evaluate_rs_trend_eligibility(eligibility(
        context=context(features=snapshots() + (duplicate,))))
    assert result.gate("RS_TREND").reason == "AMBIGUOUS_FEATURE_INPUT"
    assert result.state.state == "SETUP_FORMING"


@pytest.mark.parametrize("age,expected", ((60, "ARMED"), (61, "SETUP_FORMING")))
def test_a_feature_older_than_the_supplied_limit_is_stale(age, expected):
    older = snapshot(RS, at=AT - timedelta(seconds=age))
    rows = tuple(row for row in snapshots() if row.feature_version != RS[0])
    result = evaluate_rs_trend_eligibility(eligibility(context=context(features=rows + (older,))))
    assert result.state.state == expected
    if expected != "ARMED":
        assert result.gate("RS_TREND").reason == "STALE_FEATURE"


def test_a_newer_snapshot_replaces_an_older_one_of_the_same_definition():
    older = snapshot(RS, at=AT - timedelta(seconds=30), changed={"RS_LOOKBACK_V1": 0.0001},
                     record_id="m72-rs-older")
    result = evaluate_rs_trend_eligibility(eligibility(
        context=context(features=snapshots() + (older,))))
    assert result.gate("RS_TREND").observed == 0.004 and result.state.state == "ARMED"


# --- numeric boundaries -----------------------------------------------------


@pytest.mark.parametrize("value,expected", ((50_000_000.0, "PASS"), (49_999_999.99, "FAIL")))
def test_median_dollar_volume_boundary(value, expected):
    result = evaluate_rs_trend_eligibility(eligibility(context=context(
        features=snapshots(changed={"DOLLAR_VOLUME_FIXTURE_V1": value}))))
    assert result.gate("MEDIAN_DOLLAR_VOLUME").status == expected


@pytest.mark.parametrize("value,expected", ((1.5, "PASS"), (1.49, "FAIL")))
def test_relative_volume_boundary(value, expected):
    result = evaluate_rs_trend_eligibility(eligibility(context=context(
        features=snapshots(changed={"RVOL_FIXTURE_V1": value}))))
    assert result.gate("RVOL").status == expected


@pytest.mark.parametrize("last,expected", ((5.0, "PASS"), (4.99, "FAIL")))
def test_minimum_price_boundary(last, expected):
    supplied = context(quote=decision(last=last),
                       features=snapshots(changed={"SESSION_VWAP_FIXTURE_V1": 1.0}))
    result = evaluate_rs_trend_eligibility(eligibility(context=supplied))
    gate = result.gate("MIN_PRICE")
    assert gate.status == expected and gate.observed == last


@pytest.mark.parametrize("atr,value,expected,limit", (
    (0.02, 0.005, "PASS", 0.005),   # the supplied floor is the higher of the two
    (0.02, 0.0049, "FAIL", 0.005),
    (0.10, 0.02, "PASS", 0.02),     # the supplied volatility part now dominates
    (0.10, 0.0199, "FAIL", 0.02),
    (0.10, -0.02, "PASS", 0.02),    # the open move is measured in either direction
))
def test_open_return_uses_the_higher_of_both_supplied_parts(atr, value, expected, limit):
    result = evaluate_rs_trend_eligibility(eligibility(context=context(features=snapshots(
        changed={"DAILY_ATR_PCT_FIXTURE_V1": atr, "OPEN_RETURN_FIXTURE_V1": value}))))
    gate = result.gate("OPEN_RETURN")
    assert gate.status == expected and gate.threshold == limit
    assert gate.observed == abs(value)


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("atr,value,expected,limit", (
    (0.02, 0.003, "PASS", 0.003),
    (0.02, 0.0029, "FAIL", 0.003),
    (0.10, 0.015, "PASS", 0.015),
    (0.10, 0.0149, "FAIL", 0.015),
    (0.02, -0.004, "FAIL", 0.003),  # strength against the benchmark, not for it
))
def test_the_trend_gate_mirrors_the_supplied_strength_for_a_short(direction, atr, value,
                                                                 expected, limit):
    result = evaluate_rs_trend_eligibility(eligibility(direction, context=context(
        direction, features=snapshots(direction, changed={
            "DAILY_ATR_PCT_FIXTURE_V1": atr, "RS_LOOKBACK_V1": value}))))
    gate = result.gate("RS_TREND")
    assert gate.status == expected and gate.threshold == limit
    assert gate.observed == value


def test_an_unavailable_daily_atr_leaves_both_composite_gates_unknown():
    result = evaluate_rs_trend_eligibility(eligibility(context=context(
        features=snapshots(changed={"DAILY_ATR_PCT_FIXTURE_V1": None}))))
    for name in ("OPEN_RETURN", "RS_TREND"):
        assert result.gate(name).status == "UNKNOWN"
        assert result.gate(name).reason == "MISSING_INPUT"
        assert result.gate(name).threshold is None
    assert result.state.state == "WATCHING"


@pytest.mark.parametrize("bid,ask,expected", (
    (100.0, 100.2, "PASS"), (100.0, 100.20040081, "FAIL"), (100.0, 100.0, "PASS")))
def test_spread_boundary_in_basis_points(bid, ask, expected):
    supplied = context(quote=decision(bid=bid, ask=ask, last=ask),
                       features=snapshots(changed={"SESSION_VWAP_FIXTURE_V1": 1.0}))
    result = evaluate_rs_trend_eligibility(eligibility(context=supplied))
    assert result.gate("SPREAD_BPS").status == expected


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_price_on_the_wrong_vwap_side_fails(direction):
    # The fixture mirrors a short VWAP, so 199.0 becomes 1.0 below the last trade.
    value = 200.0 if direction == "LONG" else 199.0
    supplied = context(direction, features=snapshots(
        direction, changed={"SESSION_VWAP_FIXTURE_V1": value}))
    result = evaluate_rs_trend_eligibility(eligibility(direction, context=supplied))
    assert result.gate("VWAP_SIDE").reason == "PRICE_ON_WRONG_VWAP_SIDE"
    assert result.state.state == "SETUP_FORMING"


# --- quote and mandatory-status gates ---------------------------------------


@pytest.mark.parametrize("changes,reason", (
    ({"age": 4}, "STALE_LAST_TRADE"),
    ({"delayed": True}, "QUOTE_NOT_VALID_REALTIME"),
    ({"last": None}, "LAST_TRADE_UNAVAILABLE"),
))
def test_an_unusable_last_trade_keeps_price_gates_unknown(changes, reason):
    result = evaluate_rs_trend_eligibility(eligibility(
        context=context(quote=decision(**changes))))
    assert result.gate("MIN_PRICE").reason == reason
    assert result.state.state == "WATCHING"


@pytest.mark.parametrize("changes", (
    {"bid": None}, {"ask": None}, {"bid": 0.0}, {"age": 4}, {"status": "CROSSED"},
))
def test_an_unusable_quote_keeps_action_gates_unknown(changes):
    result = evaluate_rs_trend_eligibility(eligibility(
        context=context(quote=decision(**changes))))
    gate = result.gate("QUOTE_ACTIONABLE")
    assert gate.status == "UNKNOWN" and gate.reason.startswith("QUOTE")
    assert result.gate("SPREAD_BPS").status == "UNKNOWN"
    assert result.state.state != "ARMED"


def test_a_missing_quote_decision_is_reported_not_assumed():
    result = evaluate_rs_trend_eligibility(eligibility(context=context(quote=None)))
    assert result.gate("QUOTE_ACTIONABLE").reason == "QUOTE_DECISION_ABSENT"
    assert result.gate("MIN_PRICE").reason == "QUOTE_DECISION_ABSENT"
    assert result.state.state == "WATCHING"


@pytest.mark.parametrize("changes,expected,reason", (
    ({}, "PASS", None),
    ({"halted": None}, "UNKNOWN", "HALT_STATUS_UNKNOWN"),
    ({"halted": True}, "FAIL", "HALTED"),
    ({"macro_blackout_active": None}, "UNKNOWN", "MACRO_BLACKOUT_UNKNOWN"),
    ({"macro_blackout_active": True}, "FAIL", "MACRO_BLACKOUT_ACTIVE"),
    ({"available_at": AT + timedelta(seconds=1)}, "UNKNOWN", "STATUS_NOT_YET_AVAILABLE"),
))
def test_mandatory_status_gate(changes, expected, reason):
    result = evaluate_rs_trend_eligibility(eligibility(status=status(**changes)))
    assert result.gate("MANDATORY_STATUS").status == expected
    assert result.gate("MANDATORY_STATUS").reason == reason
    assert result.state.state == ("ARMED" if expected == "PASS" else "SETUP_FORMING")


# --- machine, rules and immutability ----------------------------------------


def test_supplied_rules_cover_only_the_m72_states():
    rules = rs_trend_rules()
    assert rules.version == RULES_VERSION
    assert rules.initial_state == StrategyState("NOT_ELIGIBLE")
    states = {state.state for pair in rules.allowed for state in pair}
    assert states == {"NOT_ELIGIBLE", "WATCHING", "SETUP_FORMING", "ARMED", "EXPIRED"}
    assert not any(old.state == "EXPIRED" for old, _ in rules.allowed)
    assert not any(state.state == "ALERT_TRIGGERED" for pair in rules.allowed for state in pair)


def test_machine_proposes_but_never_advances_itself():
    subject = machine()
    assessment, changes = subject.propose(eligibility(), record_id="m72-change-1")
    assert assessment.state == StrategyState("ARMED") and len(changes) == 1
    assert subject.current_state() == StrategyState("NOT_ELIGIBLE")
    assert changes[0].from_state == "NOT_ELIGIBLE" and changes[0].to_state == "ARMED"
    assert changes[0].metadata.data_mode == DATA_MODE
    assert changes[0].strategy_id == STRATEGY_ID
    assert changes[0].feature_snapshot_id == "m72-rs"
    assert set(changes[0].input_record_ids) <= {
        "m72-context", "m72-rs", "m72-compression", "m72-quote-" + AT.isoformat()}
    assert subject.confirm(changes[0]) == StrategyState("ARMED")
    assert subject.current_state() == StrategyState("ARMED")


def test_only_the_pending_transition_can_advance_the_machine():
    subject = machine()
    _, changes = subject.propose(eligibility(), record_id="m72-change-1")
    with pytest.raises(RecordError):
        subject.confirm(replace(changes[0], record_id="m72-other"))
    subject.confirm(changes[0])
    with pytest.raises(RecordError):
        subject.confirm(changes[0])


def test_an_unchanged_state_proposes_no_transition():
    subject = machine()
    _, changes = subject.propose(eligibility(), record_id="m72-change-1")
    subject.confirm(changes[0])
    assessment, repeated = subject.propose(eligibility(), record_id="m72-change-2")
    assert assessment.state == StrategyState("ARMED") and repeated == ()


@pytest.mark.parametrize("changes", (
    {"symbol": "OTHER"}, {"direction": "SHORT"}, {"session": session("2026-07-07")},
))
def test_machine_refuses_a_foreign_evaluation(changes):
    subject = machine(**changes)
    with pytest.raises(RecordError):
        subject.evaluate(eligibility())


def test_machine_refuses_a_changed_policy_or_backward_time():
    subject = machine()
    subject.evaluate(eligibility())
    with pytest.raises(RecordError):
        subject.evaluate(eligibility(policy=policy(min_price=6.0)))
    before = AT - timedelta(seconds=5)
    earlier = context(evaluated_at=before, features=snapshots(at=before),
                      quote=decision(at=before))
    with pytest.raises(RecordError):
        subject.evaluate(eligibility(context=earlier))


def test_restore_requires_an_unused_owner_and_a_supported_state():
    subject = machine()
    assert subject.restore(StrategyState("SETUP_FORMING")) == StrategyState("SETUP_FORMING")
    with pytest.raises(RecordError):
        subject.restore(StrategyState("ALERT_TRIGGERED"))
    used = machine()
    used.evaluate(eligibility())
    with pytest.raises(RecordError):
        used.restore(StrategyState("WATCHING"))


def test_machine_construction_rejects_an_unsupported_owner():
    for changes in ({"instrument_type": "OPTION"}, {"direction": "FLAT"}, {"symbol": " "},
                    {"strategy_version": "UNKNOWN"}, {"policy": None}, {"session": None}):
        with pytest.raises(RecordError):
            machine(**changes)


def test_assessment_and_gates_are_immutable_and_stable():
    result = evaluate_rs_trend_eligibility(eligibility())
    with pytest.raises(FrozenInstanceError):
        result.gates[0].__setattr__("status", "PASS")
    with pytest.raises(FrozenInstanceError):
        result.__setattr__("state", StrategyState("WATCHING"))
    assert result.to_json() == evaluate_rs_trend_eligibility(eligibility()).to_json()
    assert json.loads(result.to_json())["eligibility_version"] == ELIGIBILITY_VERSION
    with pytest.raises(RecordError):
        evaluate_rs_trend_eligibility("M72")


@pytest.mark.parametrize("changes", (
    {"name": "NOT_A_GATE"}, {"status": "MAYBE"}, {"status": "FAIL", "reason": None},
    {"reason": "UNKNOWN"}, {"input_record_ids": ["a"]}, {"input_record_ids": (" ",)},
))
def test_gate_results_require_supported_facts(changes):
    values = dict(name="MIN_PRICE", status="FAIL", observed=1.0, threshold=5.0,
                  reason="BELOW_MIN_PRICE", input_record_ids=())
    values.update(changes)
    with pytest.raises(RecordError):
        GateResult(**values)


# --- measured M7.1 and M7.2 inputs, the M4.2 engine and M5.1 storage --------


def measured_features(direction):
    """The real M7.1 and M7.2 producers over one supplied synthetic session."""
    stock = history(first=100.00, step=0.10 if direction == "LONG" else -0.10)
    benchmark = history(BENCHMARK, first=400.00, step=0.08)
    relative = build_rs_trend_snapshot(
        record_id="m72-measured-rs", evaluated_at=AT, symbol="SYNTH",
        instrument_type="EQUITY", minute_history=stock, benchmark_history=benchmark,
        policy=LOOKBACK)
    compression = build_hod_compression_snapshot(
        record_id="m72-measured-compression", evaluated_at=AT, symbol="SYNTH",
        instrument_type="EQUITY", minute_history=stock,
        policy=CompressionPolicy(version="M72_TEST_WINDOW_V1",
                                 definition_reference="M72_SYNTHETIC_WINDOW_ONLY",
                                 recent_bars=3, prior_bars=7, prior_includes_recent=True),
        reference_frozen_at=datetime(2026, 7, 6, 6, 40, tzinfo=PACIFIC), atr_1m=0.10)
    rows = tuple(FeatureSnapshot.from_json(row.to_json()) for row in (relative, compression))
    return stock, benchmark, rows


def measured_request(direction):
    stock, benchmark, rows = measured_features(direction)
    fixture = snapshot(CONTEXT, direction=direction)
    supplied = context(direction, features=(fixture,) + rows,
                       quote=decision(direction))
    return stock, benchmark, rows, RsTrendRequest(supplied, policy(), status())


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_the_measured_rs_and_compression_inputs_reach_armed(direction):
    _, _, rows, request = measured_request(direction)
    values = {item.name: item.value for row in rows for item in row.features}
    assert values["RS_LOOKBACK_V1"] == (0.012 if direction == "LONG" else -0.018)
    assert values["RS_WARMUP_COMPLETE_V1"] == 1
    assert values["REFERENCE_EXTREME_COMPLETE_V1"] == 1
    assert values["COMPRESSION_COMPLETE_V1"] == 1
    result = evaluate_rs_trend_eligibility(request)
    assert result.state == StrategyState("ARMED") and result.reasons == ()
    assert result.gate("RS_TREND").observed == (0.012 if direction == "LONG" else 0.018)


async def test_measured_inputs_through_the_m42_engine_and_m51_store():
    proofs = []
    connection = await db.init_db()
    for direction in ("LONG", "SHORT"):
        stock, benchmark, rows, request = measured_request(direction)
        subject = machine(direction)
        assessment, changes = subject.propose(request, record_id="m72-measured-" + direction)
        assert assessment.state == StrategyState("ARMED") and assessment.reasons == ()

        engine = StateTransitionEngine(TransitionScope(
            session(DAY), "SYNTH", "EQUITY", direction, STRATEGY_ID, VERSION,
            rs_trend_rules()), SQLiteTransitionStore(connection))
        entry = await engine.apply(changes[0], context=request.context)
        assert engine.current_state() == StrategyState("ARMED")
        assert subject.confirm(changes[0]) == StrategyState("ARMED")
        store = ResearchEventStore(connection)
        stored = await store.append(changes[0], session=DAY, recorded_at=AT)
        assert stored["kind"] == "STATE_TRANSITION"
        assert await store.append(changes[0], session=DAY, recorded_at=AT) == stored

        repeated = evaluate_rs_trend_eligibility(request)
        assert repeated.to_json() == assessment.to_json()
        proofs.append({
            "synthetic_only": True, "direction": direction,
            "bars": len(stock.bars) + len(benchmark.bars),
            "bar_sha256": hashlib.sha256("".join(
                row.to_json() for row in (*stock.bars, *benchmark.bars)).encode()).hexdigest(),
            "measured_feature_values": {item.name: item.value for row in rows
                                        for item in row.features},
            "assessment": assessment.as_dict(), "transition": changes[0].as_dict(),
            "stored_position": entry.position, "stored_fingerprint": stored["fingerprint"],
            "repeated_assessment_identical": True,
        })
    await db.close_db()
    payload = {"evidence": "SYNTHETIC_SOFTWARE_PROOF_ONLY",
               "eligibility_version": ELIGIBILITY_VERSION,
               "rs_feature_version": RS_FEATURE_VERSION, "runs": proofs}
    rendered = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    assert len(rendered.encode()) < 100_000
    (Path(os.environ["TMPDIR"]) / "m7_2_rs_trend_proof.json").write_text(rendered)


async def test_a_refused_recording_leaves_the_machine_below_armed():
    class Refusing:
        async def append(self, entry):
            raise RecordError("synthetic storage refusal")

    subject = machine()
    supplied = eligibility()
    _, changes = subject.propose(supplied, record_id="m72-refused")
    engine = StateTransitionEngine(TransitionScope(
        session(DAY), "SYNTH", "EQUITY", "LONG", STRATEGY_ID, VERSION,
        rs_trend_rules()), Refusing())
    with pytest.raises(RecordError):
        await engine.apply(changes[0], context=supplied.context)
    assert engine.current_state() == StrategyState("NOT_ELIGIBLE")
    assert subject.current_state() == StrategyState("NOT_ELIGIBLE")
