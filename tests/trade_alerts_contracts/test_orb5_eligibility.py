"""M6.1 supplied-input eligibility contracts; no approved threshold is adopted.

Every number below is a synthetic fixture supplied by the caller. Passing gates
prove the offline contract only: they establish no provider coverage, no adopted
`M03B_ORB5_V1` rule, no trigger and no permission to act.
"""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine import db
from consensus_engine.core_price_features import build_core_price_snapshot
from consensus_engine.event_store import ResearchEventStore
from consensus_engine.historical_bars import HistoryRequest
from consensus_engine.opening_range_features import build_opening_range_snapshot
from consensus_engine.orb5_eligibility import (
    ARMED_GATES, DATA_MODE, ELIGIBILITY_VERSION, EligibilityAssessment, EligibilityPolicy,
    EligibilityRequest, FeatureBinding, GateResult, MandatoryStatus, Orb5EligibilityMachine,
    REQUIRED_ROLES, RULES_VERSION, SETUP_GATES, STRATEGY_ID, WINDOW_GATE, eligibility_rules,
    evaluate_orb5_eligibility,
)
from consensus_engine.participation_features import build_participation_snapshot
from consensus_engine.quote_events import QuoteEventPolicy, QuoteEventStream
from consensus_engine.state_transitions import StateTransitionEngine, TransitionScope
from consensus_engine.strategy_interface import StrategyContext, StrategyState
from consensus_engine.structural_risk import select_b_risk_targets
from consensus_engine.trade_alerts_models import (
    Bar, CatalystEvent, FeatureSnapshot, FeatureValue, Quote, RecordError, SourceMetadata,
)
from consensus_engine.transition_store import SQLiteTransitionStore
from test_core_price_features import bar, batch, daily_history, opening_trade
from test_participation_features import history as participation_history
from test_strategy_interface import session
from test_structural_risk import changed_value, request as risk_request


PACIFIC = ZoneInfo("America/Los_Angeles")
DAY = "2026-07-06"
OPENED = datetime(2026, 7, 6, 6, 30, tzinfo=PACIFIC)
AT = datetime(2026, 7, 6, 6, 50, 10, tzinfo=PACIFIC)
VERSION = "M61_FIXTURE_ONLY_V1"
POLICY_VERSION = "M61_SUPPLIED_FIXTURE_POLICY_V1"
CORE = ("D090_CORE_PRICE_FEATURES_V1", "BAR_HLC3_WITH_EXPLICIT_OPEN")
PARTICIPATION = ("D090_PARTICIPATION_FEATURES_V1",
                 "SUPPLIED_BAR_PARTICIPATION_WITH_CLOSE_DOLLAR_PROXY")
OPENING = ("D090_OPENING_RANGE_5M_V1", "SUPPLIED_BAR_OPENING_RANGE")
BINDINGS = {
    "MEDIAN_DOLLAR_VOLUME": ("DOLLAR_VOLUME_CLOSE_PROXY20_V1", PARTICIPATION, "USD"),
    "OPEN5_RVOL": ("RVOL_OPEN5_MEAN20_V1", PARTICIPATION, "RATIO"),
    "PM_RVOL": ("PM_RVOL_MEAN20_V1", PARTICIPATION, "RATIO"),
    "GAP": ("GAP_OPEN_V1", CORE, "RATIO"),
    "DAILY_ATR": ("DAILY_ATR_14_SMA_V1", CORE, "USD_PER_SHARE"),
    "SESSION_VWAP": ("SESSION_VWAP_BAR_HLC3_V1", CORE, "USD_PER_SHARE"),
    "OPENING_RANGE_WIDTH": ("OPENING_RANGE_WIDTH_5M_V1", OPENING, "USD_PER_SHARE"),
    "OPENING_RANGE_COMPLETE": ("OPENING_RANGE_COMPLETE_5M_V1", OPENING, "BOOLEAN"),
}
# Synthetic supplied values only; the ratio 0.4/2.1 and the mirror are fixtures.
VALUES = {
    "DOLLAR_VOLUME_CLOSE_PROXY20_V1": 50_000_000.0, "RVOL_OPEN5_MEAN20_V1": 2.0,
    "PM_RVOL_MEAN20_V1": 2.75, "GAP_OPEN_V1": 0.012, "DAILY_ATR_14_SMA_V1": 2.1,
    "SESSION_VWAP_BAR_HLC3_V1": 100.5, "OPENING_RANGE_WIDTH_5M_V1": 1.05,
    "OPENING_RANGE_COMPLETE_5M_V1": 1.0,
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


def snapshot(record_id, definition, names, *, direction="LONG", at=AT, changed=None, **changes):
    version, mode = definition
    changed = changed or {}
    features = []
    for name in names:
        value = changed[name] if name in changed else VALUES[name]
        unit = next(row[2] for row in BINDINGS.values() if row[0] == name)
        if direction == "SHORT" and name == "SESSION_VWAP_BAR_HLC3_V1" and value is not None:
            value = mirror(value)
        features.append(FeatureValue(name, value, unit,
                                     None if value is not None else "MISSING_INPUT",
                                     ("supplied-" + name,)))
    values = dict(record_id=record_id, metadata=metadata(at, data_mode=mode), evaluated_at=at,
                  feature_version=version, features=tuple(features),
                  input_record_ids=tuple("supplied-" + name for name in names))
    values.update(changes)
    return FeatureSnapshot.from_json(FeatureSnapshot(**values).to_json())


def snapshots(direction="LONG", *, changed=None, at=AT):
    return (
        snapshot("m61-core", CORE, ("GAP_OPEN_V1", "DAILY_ATR_14_SMA_V1",
                                    "SESSION_VWAP_BAR_HLC3_V1"),
                 direction=direction, changed=changed, at=at),
        snapshot("m61-participation", PARTICIPATION,
                 ("DOLLAR_VOLUME_CLOSE_PROXY20_V1", "RVOL_OPEN5_MEAN20_V1", "PM_RVOL_MEAN20_V1"),
                 direction=direction, changed=changed, at=at),
        snapshot("m61-opening", OPENING,
                 ("OPENING_RANGE_WIDTH_5M_V1", "OPENING_RANGE_COMPLETE_5M_V1"),
                 direction=direction, changed=changed, at=at),
    )


def quote_record(direction="LONG", *, at=AT, **changes):
    supplied_bid, supplied_ask, supplied_last = QUOTES[direction]
    values = dict(
        record_id="m61-quote-" + at.isoformat(), metadata=metadata(at),
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
                              evidence_reference="M61_SYNTHETIC_CONTINUITY")
    return stream.inspect(at)


def catalyst(record_id="m61-catalyst", *, classification="CONFIRMED_CATALYST", at=AT,
             classified=True):
    return CatalystEvent(
        record_id=record_id, metadata=metadata(at, data_mode="SYNTHETIC_NEWS"),
        event_type="EARNINGS", headline="Synthetic fixture headline",
        occurred_time=at - timedelta(minutes=30), classification=classification,
        classified_at=at if classified else None,
    )


def bindings():
    return tuple(FeatureBinding(role, BINDINGS[role][0], BINDINGS[role][1][0],
                                BINDINGS[role][1][1], BINDINGS[role][2])
                 for role in REQUIRED_ROLES)


def policy(**changes):
    values = dict(
        version=POLICY_VERSION, definition_reference="M61_SUPPLIED_FIXTURE_DEFINITION",
        window_start_minutes=5, window_end_minutes=45, min_price=5.0,
        min_median_dollar_volume=50_000_000.0, min_open5_rvol=2.0,
        min_or_width_atr_ratio=0.08, max_or_width_atr_ratio=0.65,
        stock_in_play_min_pm_rvol=2.5, stock_in_play_min_abs_gap=0.01,
        stock_in_play_min_open5_rvol=3.0, max_spread_bps=20.0, max_quote_age_seconds=3.0,
        max_trade_age_seconds=3.0, max_feature_age_seconds=60.0,
        catalyst_classifications=("CONFIRMED_CATALYST",), bindings=bindings(),
    )
    values.update(changes)
    return EligibilityPolicy(**values)


def status(**changes):
    values = dict(halted=False, macro_blackout_active=False, catalyst_coverage="COMPLETE",
                  definition_reference="M61_SUPPLIED_STATUS_DEFINITION",
                  evidence_reference="M61_SYNTHETIC_STATUS", available_at=AT)
    values.update(changes)
    return MandatoryStatus(**values)


def preliminary(direction="LONG", *, outcome="READY"):
    supplied = risk_request(direction)
    if outcome == "UNAVAILABLE":
        supplied = replace(supplied, path_complete=False)
    if outcome == "REJECTED":
        supplied = replace(supplied, boundary=changed_value(
            supplied.boundary, 100.90 if direction == "LONG" else 50.10))
    result = select_b_risk_targets(supplied)
    assert result.status == outcome
    return result


def context(direction="LONG", **changes):
    values = dict(session=session(DAY), symbol="SYNTH", instrument_type="EQUITY",
                  direction=direction, evaluated_at=AT, features=snapshots(direction),
                  quote=decision(direction), catalysts=())
    values.update(changes)
    return StrategyContext(**values)


def eligibility(direction="LONG", **changes):
    values = dict(context=context(direction), policy=policy(), status=status(),
                  preliminary=preliminary(direction))
    values.update(changes)
    return EligibilityRequest(**values)


def state_of(request):
    return evaluate_orb5_eligibility(request).state.state


def machine(direction="LONG", **changes):
    values = dict(session=session(DAY), symbol="SYNTH", instrument_type="EQUITY",
                  direction=direction, strategy_version=VERSION, policy=policy())
    values.update(changes)
    return Orb5EligibilityMachine(**values)


# --- supplied policy, bindings and status contracts -------------------------


@pytest.mark.parametrize("changes", (
    {"version": " "}, {"version": "UNKNOWN"}, {"definition_reference": "UNSPECIFIED"},
    {"window_start_minutes": 45}, {"window_start_minutes": 46}, {"window_start_minutes": 5.0},
    {"window_end_minutes": True}, {"min_price": -1}, {"min_price": float("nan")},
    {"min_price": float("inf")}, {"min_price": "5"}, {"min_price": True},
    {"min_or_width_atr_ratio": 0.66}, {"max_quote_age_seconds": -0.5},
    {"catalyst_classifications": ()}, {"catalyst_classifications": ("A", "A")},
    {"catalyst_classifications": ("UNKNOWN",)}, {"catalyst_classifications": "A"},
    {"bindings": ()}, {"bindings": ("OPEN5_RVOL",)},
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
    {"role": "PRICE"}, {"role": "open5_rvol"}, {"feature_name": ""},
    {"feature_version": "UNKNOWN"}, {"data_mode": " "}, {"unit": "UNSPECIFIED"},
))
def test_feature_binding_requires_an_explicit_definition(changes):
    values = dict(role="OPEN5_RVOL", feature_name="RVOL_OPEN5_MEAN20_V1",
                  feature_version=PARTICIPATION[0], data_mode=PARTICIPATION[1], unit="RATIO")
    values.update(changes)
    with pytest.raises(RecordError):
        FeatureBinding(**values)


@pytest.mark.parametrize("changes", (
    {"halted": 1}, {"macro_blackout_active": "false"}, {"catalyst_coverage": "PARTIAL"},
    {"definition_reference": "UNKNOWN"}, {"evidence_reference": ""},
    {"available_at": "2026-07-06T06:50:10"},
    {"available_at": datetime(2026, 7, 6, 6, 50, 10)},
))
def test_mandatory_status_rejects_unsupported_values(changes):
    with pytest.raises(RecordError):
        status(**changes)


def test_request_requires_canonical_supplied_parts():
    for changes in ({"context": None}, {"policy": None}, {"status": None},
                    {"preliminary": "READY"}):
        with pytest.raises(RecordError):
            eligibility(**changes)
    assert isinstance(eligibility().preliminary.status, str)


# --- the supplied path through ARMED ----------------------------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_supplied_gates_reach_armed(direction):
    result = evaluate_orb5_eligibility(eligibility(direction))
    assert result.state == StrategyState("ARMED") and result.reasons == ()
    assert result.stock_in_play == "TRUE"
    assert all(result.gate(name).status == "PASS" for name in ARMED_GATES)
    assert result.gate(WINDOW_GATE).status == "PASS"
    assert result.gate("OR_WIDTH_ATR_RATIO").observed == 0.5
    assert result.policy_version == POLICY_VERSION


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_setup_forming_when_only_live_gates_are_unknown(direction):
    result = evaluate_orb5_eligibility(eligibility(direction, preliminary=None))
    assert result.state == StrategyState("SETUP_FORMING")
    assert result.gate("PRELIMINARY_RISK_TARGETS").status == "UNKNOWN"
    assert all(result.gate(name).status == "PASS" for name in SETUP_GATES)


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_watching_when_the_opening_range_is_incomplete(direction):
    supplied = context(direction, features=snapshots(
        direction, changed={"OPENING_RANGE_COMPLETE_5M_V1": 0.0,
                            "OPENING_RANGE_WIDTH_5M_V1": None}))
    result = evaluate_orb5_eligibility(eligibility(direction, context=supplied))
    assert result.state == StrategyState("WATCHING")
    assert result.gate("OPENING_RANGE_READY").reason == "OPENING_RANGE_INCOMPLETE"
    assert result.gate("OR_WIDTH_ATR_RATIO").status == "UNKNOWN"


@pytest.mark.parametrize("clock,expected,reason", (
    ("06:34:59", "NOT_ELIGIBLE", "BEFORE_EVALUATION_WINDOW"),
    ("06:35:00", "SETUP_FORMING", None),
    ("07:14:59", "SETUP_FORMING", None),
    ("07:15:00", "EXPIRED", "AFTER_EVALUATION_WINDOW"),
))
def test_half_open_evaluation_window(clock, expected, reason):
    """Identical supplied inputs; only the instant moves across both edges."""
    at = datetime.fromisoformat(DAY + "T" + clock).replace(tzinfo=PACIFIC)
    supplied = context(features=snapshots(at=at), quote=decision(at=at), evaluated_at=at)
    # Preliminary geometry is left unavailable, so no row can pass its ARMED gate.
    result = evaluate_orb5_eligibility(eligibility(context=supplied, preliminary=None))
    assert result.gate(WINDOW_GATE).reason == reason
    assert result.state.state == expected
    assert all(result.gate(name).status == "PASS" for name in SETUP_GATES)


def test_window_uses_the_supplied_minutes_not_a_fixed_clock():
    supplied = eligibility(policy=policy(window_start_minutes=25, window_end_minutes=45))
    assert state_of(supplied) == "NOT_ELIGIBLE"
    assert state_of(eligibility(policy=policy(window_start_minutes=0,
                                              window_end_minutes=15))) == "EXPIRED"


# --- three-valued stock-in-play ---------------------------------------------


@pytest.mark.parametrize("changed,catalysts,coverage,expected", (
    ({}, (), "COMPLETE", "TRUE"),
    ({"PM_RVOL_MEAN20_V1": 2.5, "GAP_OPEN_V1": 0.01}, (), "COMPLETE", "TRUE"),
    ({"PM_RVOL_MEAN20_V1": 2.49}, (), "COMPLETE", "FALSE"),
    ({"GAP_OPEN_V1": -0.02}, (), "COMPLETE", "TRUE"),
    ({"PM_RVOL_MEAN20_V1": 1.0, "RVOL_OPEN5_MEAN20_V1": 3.0}, (), "COMPLETE", "TRUE"),
    ({"PM_RVOL_MEAN20_V1": None}, (), "COMPLETE", "UNKNOWN"),
    ({"PM_RVOL_MEAN20_V1": None, "GAP_OPEN_V1": 0.001}, (), "COMPLETE", "FALSE"),
    ({"PM_RVOL_MEAN20_V1": 1.0}, (), "UNKNOWN", "UNKNOWN"),
    ({"PM_RVOL_MEAN20_V1": 1.0}, (catalyst(),), "UNKNOWN", "TRUE"),
    ({"PM_RVOL_MEAN20_V1": 1.0}, (catalyst(classification="UNRELATED"),), "COMPLETE", "FALSE"),
    ({"PM_RVOL_MEAN20_V1": 1.0}, (catalyst(classified=False),), "COMPLETE", "UNKNOWN"),
    ({"PM_RVOL_MEAN20_V1": 1.0}, (catalyst(classification="UNKNOWN"),), "COMPLETE", "UNKNOWN"),
))
def test_stock_in_play_is_three_valued(changed, catalysts, coverage, expected):
    supplied = context(features=snapshots(changed=changed), catalysts=catalysts)
    result = evaluate_orb5_eligibility(eligibility(
        context=supplied, status=status(catalyst_coverage=coverage)))
    assert result.stock_in_play == expected
    assert result.gate("STOCK_IN_PLAY").status == {
        "TRUE": "PASS", "FALSE": "FAIL", "UNKNOWN": "UNKNOWN"}[expected]
    assert result.state.state == ("ARMED" if expected == "TRUE" else "WATCHING")


def test_an_unclassified_catalyst_alone_cannot_confirm_stock_in_play():
    supplied = context(features=snapshots(changed={"PM_RVOL_MEAN20_V1": 1.0}),
                       catalysts=(catalyst(classified=False),))
    result = evaluate_orb5_eligibility(eligibility(context=supplied))
    assert result.gate("STOCK_IN_PLAY").reason == "STOCK_IN_PLAY_UNKNOWN"
    assert result.state.state == "WATCHING"


# --- missing, stale, ambiguous and mislabeled inputs -------------------------


@pytest.mark.parametrize("role", REQUIRED_ROLES)
def test_a_missing_mandatory_value_is_unknown_and_never_passes(role):
    name = BINDINGS[role][0]
    supplied = context(features=snapshots(changed={name: None}))
    result = evaluate_orb5_eligibility(eligibility(context=supplied))
    assert result.state.state in ("WATCHING", "SETUP_FORMING")
    assert result.state.state != "ARMED"
    assert any(row.status == "UNKNOWN" for row in result.gates)


@pytest.mark.parametrize("role", REQUIRED_ROLES)
def test_an_absent_snapshot_is_reported_not_assumed(role):
    binding = policy().binding(role)
    kept = tuple(row for row in snapshots()
                 if row.feature_version != binding.feature_version)
    result = evaluate_orb5_eligibility(eligibility(context=context(features=kept)))
    assert result.state.state != "ARMED"
    assert any("FEATURE_ABSENT" in reason for reason in result.reasons)


@pytest.mark.parametrize("changes,reason", (
    ({"feature_version": "OTHER_PRODUCER_V1"}, "FEATURE_ABSENT"),
    ({"metadata": metadata(data_mode="OTHER_MODE")}, "FEATURE_ABSENT"),
    ({"metadata": metadata(instrument_id="OTHER")}, "FEATURE_ABSENT"),
    ({"metadata": metadata(instrument_type="ETF")}, "FEATURE_ABSENT"),
    ({"metadata": metadata(quality="DEGRADED_PROXY")}, "FEATURE_QUALITY_UNAVAILABLE"),
    ({"metadata": metadata(source_time=None)}, "INVALID_SOURCE_TIME"),
))
def test_another_definition_or_instrument_cannot_substitute(changes, reason):
    rows = list(snapshots())
    values = dict(record_id="m61-participation", metadata=rows[1].metadata,
                  evaluated_at=AT, feature_version=rows[1].feature_version,
                  features=rows[1].features, input_record_ids=rows[1].input_record_ids)
    if "metadata" in changes:
        changes = {"metadata": replace(changes["metadata"], data_mode=changes["metadata"].data_mode
                                       if changes["metadata"].data_mode != "FIXTURE"
                                       else PARTICIPATION[1])}
    values.update(changes)
    rows[1] = FeatureSnapshot(**values)
    result = evaluate_orb5_eligibility(eligibility(context=context(features=tuple(rows))))
    assert result.state.state != "ARMED"
    assert any(reason in row for row in result.reasons)


def test_a_wrong_unit_cannot_be_read_as_the_bound_value():
    supplied = policy(bindings=tuple(
        replace(row, unit="SHARES") if row.role == "OPEN5_RVOL" else row
        for row in bindings()))
    result = evaluate_orb5_eligibility(eligibility(policy=supplied))
    assert result.gate("OPEN5_RVOL").reason == "WRONG_UNIT"
    assert result.state.state == "WATCHING"


def test_two_snapshots_at_one_instant_are_ambiguous_not_preferred():
    duplicate = replace(snapshots()[1], record_id="m61-participation-copy")
    result = evaluate_orb5_eligibility(eligibility(
        context=context(features=snapshots() + (duplicate,))))
    assert result.gate("OPEN5_RVOL").reason == "AMBIGUOUS_FEATURE_INPUT"
    assert result.state.state == "WATCHING"


@pytest.mark.parametrize("age,expected", ((60, "ARMED"), (61, "WATCHING")))
def test_a_feature_older_than_the_supplied_limit_is_stale(age, expected):
    older = snapshot("m61-participation", PARTICIPATION,
                     ("DOLLAR_VOLUME_CLOSE_PROXY20_V1", "RVOL_OPEN5_MEAN20_V1",
                      "PM_RVOL_MEAN20_V1"), at=AT - timedelta(seconds=age))
    rows = tuple(row for row in snapshots() if row.record_id != "m61-participation")
    result = evaluate_orb5_eligibility(eligibility(context=context(features=rows + (older,))))
    assert result.state.state == expected
    if expected == "WATCHING":
        assert result.gate("OPEN5_RVOL").reason == "STALE_FEATURE"


def test_a_newer_snapshot_replaces_an_older_one_of_the_same_definition():
    older = snapshot("m61-participation-older", PARTICIPATION,
                     ("DOLLAR_VOLUME_CLOSE_PROXY20_V1", "RVOL_OPEN5_MEAN20_V1",
                      "PM_RVOL_MEAN20_V1"), at=AT - timedelta(seconds=30),
                     changed={"RVOL_OPEN5_MEAN20_V1": 0.1})
    result = evaluate_orb5_eligibility(eligibility(
        context=context(features=snapshots() + (older,))))
    assert result.gate("OPEN5_RVOL").observed == 2.0 and result.state.state == "ARMED"


# --- numeric boundaries -----------------------------------------------------


@pytest.mark.parametrize("value,expected", ((50_000_000.0, "PASS"), (49_999_999.99, "FAIL")))
def test_median_dollar_volume_boundary(value, expected):
    supplied = context(features=snapshots(
        changed={"DOLLAR_VOLUME_CLOSE_PROXY20_V1": value}))
    result = evaluate_orb5_eligibility(eligibility(context=supplied))
    assert result.gate("MEDIAN_DOLLAR_VOLUME").status == expected


@pytest.mark.parametrize("last,expected", ((5.0, "PASS"), (4.99, "FAIL")))
def test_minimum_price_boundary(last, expected):
    supplied = context(quote=decision(last=last),
                       features=snapshots(changed={"SESSION_VWAP_BAR_HLC3_V1": 1.0}))
    result = evaluate_orb5_eligibility(eligibility(context=supplied))
    assert result.gate("MIN_PRICE").status == expected and result.gate("MIN_PRICE").observed == last


@pytest.mark.parametrize("width,expected", (
    (0.168, "PASS"), (1.365, "PASS"), (0.1679, "FAIL"), (1.3651, "FAIL")))
def test_or_width_band_boundaries(width, expected):
    supplied = context(features=snapshots(changed={"OPENING_RANGE_WIDTH_5M_V1": width}))
    result = evaluate_orb5_eligibility(eligibility(context=supplied))
    assert result.gate("OR_WIDTH_ATR_RATIO").status == expected


def test_a_zero_atr_denominator_cannot_produce_a_ratio():
    supplied = context(features=snapshots(changed={"DAILY_ATR_14_SMA_V1": 0.0}))
    result = evaluate_orb5_eligibility(eligibility(context=supplied))
    assert result.gate("OR_WIDTH_ATR_RATIO").reason == "ZERO_ATR_DENOMINATOR"
    assert result.state.state == "WATCHING"


@pytest.mark.parametrize("bid,ask,expected", (
    (100.0, 100.2, "PASS"), (100.0, 100.20040081, "FAIL"), (100.0, 100.0, "PASS")))
def test_spread_boundary_in_basis_points(bid, ask, expected):
    supplied = context(quote=decision(bid=bid, ask=ask, last=ask),
                       features=snapshots(changed={"SESSION_VWAP_BAR_HLC3_V1": 1.0}))
    result = evaluate_orb5_eligibility(eligibility(context=supplied))
    assert result.gate("SPREAD_BPS").status == expected


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_price_on_the_wrong_vwap_side_fails(direction):
    # The fixture mirrors a short VWAP, so 199.0 becomes 1.0 below the last trade.
    value = 200.0 if direction == "LONG" else 199.0
    supplied = context(direction, features=snapshots(
        direction, changed={"SESSION_VWAP_BAR_HLC3_V1": value}))
    result = evaluate_orb5_eligibility(eligibility(direction, context=supplied))
    assert result.gate("VWAP_SIDE").reason == "PRICE_ON_WRONG_VWAP_SIDE"
    assert result.state.state == "SETUP_FORMING"


# --- quote, status and preliminary-geometry gates ---------------------------


@pytest.mark.parametrize("changes,reason", (
    ({"age": 4}, "STALE_LAST_TRADE"),
    ({"delayed": True}, "QUOTE_NOT_VALID_REALTIME"),
    ({"delayed": None}, "QUOTE_NOT_VALID_REALTIME"),
    ({"last": None}, "LAST_TRADE_UNAVAILABLE"),
))
def test_an_unusable_last_trade_keeps_price_gates_unknown(changes, reason):
    result = evaluate_orb5_eligibility(eligibility(context=context(quote=decision(**changes))))
    assert result.gate("MIN_PRICE").reason == reason
    assert result.state.state == "WATCHING"


@pytest.mark.parametrize("changes", (
    {"bid": None}, {"ask": None}, {"bid": 0.0}, {"age": 4}, {"status": "CROSSED"},
))
def test_an_unusable_quote_keeps_action_gates_unknown(changes):
    result = evaluate_orb5_eligibility(eligibility(context=context(quote=decision(**changes))))
    gate = result.gate("QUOTE_ACTIONABLE")
    assert gate.status == "UNKNOWN" and gate.reason.startswith("QUOTE")
    assert result.gate("SPREAD_BPS").status == "UNKNOWN"
    assert result.state.state != "ARMED"


def test_a_missing_quote_decision_is_reported_not_assumed():
    result = evaluate_orb5_eligibility(eligibility(context=context(quote=None)))
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
    result = evaluate_orb5_eligibility(eligibility(status=status(**changes)))
    assert result.gate("MANDATORY_STATUS").status == expected
    assert result.gate("MANDATORY_STATUS").reason == reason
    assert result.state.state == ("ARMED" if expected == "PASS" else "SETUP_FORMING")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("outcome,expected", (
    ("READY", "PASS"), ("REJECTED", "FAIL"), ("UNAVAILABLE", "UNKNOWN")))
def test_preliminary_geometry_gate(direction, outcome, expected):
    result = evaluate_orb5_eligibility(eligibility(
        direction, preliminary=preliminary(direction, outcome=outcome)))
    assert result.gate("PRELIMINARY_RISK_TARGETS").status == expected
    assert result.state.state == ("ARMED" if expected == "PASS" else "SETUP_FORMING")


def test_preliminary_geometry_must_match_this_direction_and_instant():
    other = evaluate_orb5_eligibility(eligibility("LONG", preliminary=preliminary("SHORT")))
    assert other.gate("PRELIMINARY_RISK_TARGETS").reason == "PRELIMINARY_DIRECTION_MISMATCH"
    later = AT + timedelta(seconds=5)
    earlier = context(evaluated_at=later, features=snapshots(), quote=decision(at=later, age=1))
    stale = evaluate_orb5_eligibility(eligibility(context=earlier))
    assert stale.gate("PRELIMINARY_RISK_TARGETS").reason == "PRELIMINARY_NOT_CURRENT"
    assert (other.state.state, stale.state.state) == ("SETUP_FORMING", "SETUP_FORMING")


# --- machine, rules and immutability ----------------------------------------


def test_supplied_rules_cover_only_the_m61_states():
    rules = eligibility_rules()
    assert rules.version == RULES_VERSION
    assert rules.initial_state == StrategyState("NOT_ELIGIBLE")
    states = {state.state for pair in rules.allowed for state in pair}
    assert states == {"NOT_ELIGIBLE", "WATCHING", "SETUP_FORMING", "ARMED", "EXPIRED"}
    assert not any(old.state == "EXPIRED" for old, _ in rules.allowed)
    assert (StrategyState("NOT_ELIGIBLE"), StrategyState("ARMED")) in rules.allowed


def test_machine_proposes_but_never_advances_itself():
    subject = machine()
    assessment, changes = subject.propose(eligibility(), record_id="m61-change-1")
    assert assessment.state == StrategyState("ARMED") and len(changes) == 1
    assert subject.current_state() == StrategyState("NOT_ELIGIBLE")
    assert changes[0].from_state == "NOT_ELIGIBLE" and changes[0].to_state == "ARMED"
    assert changes[0].metadata.data_mode == DATA_MODE
    assert changes[0].strategy_id == STRATEGY_ID
    assert changes[0].feature_snapshot_id == "m61-opening"
    assert set(changes[0].input_record_ids) <= {
        "m61-core", "m61-participation", "m61-opening", "m61-quote-" + AT.isoformat()}
    assert subject.confirm(changes[0]) == StrategyState("ARMED")
    assert subject.current_state() == StrategyState("ARMED")


def test_only_the_pending_transition_can_advance_the_machine():
    subject = machine()
    _, changes = subject.propose(eligibility(), record_id="m61-change-1")
    with pytest.raises(RecordError):
        subject.confirm(replace(changes[0], record_id="m61-other"))
    subject.confirm(changes[0])
    with pytest.raises(RecordError):
        subject.confirm(changes[0])


def test_an_unchanged_state_proposes_no_transition():
    subject = machine()
    _, changes = subject.propose(eligibility(), record_id="m61-change-1")
    subject.confirm(changes[0])
    assessment, repeated = subject.propose(eligibility(), record_id="m61-change-2")
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
        subject.evaluate(eligibility(context=earlier, preliminary=None))


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
    result = evaluate_orb5_eligibility(eligibility())
    with pytest.raises(FrozenInstanceError):
        result.gates[0].__setattr__("status", "PASS")
    with pytest.raises(FrozenInstanceError):
        result.__setattr__("state", StrategyState("WATCHING"))
    assert result.to_json() == evaluate_orb5_eligibility(eligibility()).to_json()
    assert json.loads(result.to_json())["eligibility_version"] == ELIGIBILITY_VERSION


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


# --- shared features, M4.2 engine and M5.1 storage --------------------------


def minute_bars(direction):
    """Twenty supplied regular minutes; the first five form the opening range."""
    request = HistoryRequest("SYNTH", OPENED, OPENED + timedelta(minutes=20))
    convert = (lambda value: value) if direction == "LONG" else mirror
    bars = []
    for number, interval in enumerate(request.expected_intervals()):
        low, high = (100.6, 101.0) if number < 5 else (100.8, 101.2)
        prices = sorted((convert(low), convert(high)))
        row = bar(f"m61-minute-{number}", interval.start, interval.end,
                  high=prices[1], low=prices[0], close=convert((low + high) / 2))
        bars.append(Bar.from_json(row.to_json()))
    return batch(request, bars)


def shared_features(direction):
    history = minute_bars(direction)
    core = build_core_price_snapshot(
        record_id="m61-shared-core", evaluated_at=AT, minute_history=history,
        daily_history=daily_history(), premarket_history=None,
        opening_trade=opening_trade(price=103.224))
    opening = build_opening_range_snapshot(
        record_id="m61-shared-opening", evaluated_at=AT, symbol="SYNTH",
        instrument_type="EQUITY", minute_history=history)
    participation = build_participation_snapshot(
        record_id="m61-shared-participation", evaluated_at=AT, symbol="SYNTH",
        instrument_type="EQUITY", opening_history=participation_history("opening"),
        premarket_history=participation_history("premarket"),
        daily_history=participation_history("daily"))
    rows = tuple(FeatureSnapshot.from_json(row.to_json())
                 for row in (core, opening, participation))
    return history, rows


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
async def test_shared_features_through_the_m42_engine_and_m51_store(direction):
    history, rows = shared_features(direction)
    values = {item.name: item.value for row in rows for item in row.features}
    assert values["DAILY_ATR_14_SMA_V1"] == 2.1 and values["GAP_OPEN_V1"] == 0.012
    assert values["OPENING_RANGE_COMPLETE_5M_V1"] == 1.0
    assert values["RVOL_OPEN5_MEAN20_V1"] == 2.0
    assert values["DOLLAR_VOLUME_CLOSE_PROXY20_V1"] == 50_000_000.0
    vwap = values["SESSION_VWAP_BAR_HLC3_V1"]
    last = round(vwap + (1 if direction == "LONG" else -1), 2)
    supplied = context(direction, features=rows, catalysts=(catalyst(),),
                       quote=decision(direction, bid=round(last - 0.01, 2),
                                      ask=round(last + 0.01, 2), last=last))
    request = EligibilityRequest(supplied, policy(), status(), preliminary(direction))
    subject = machine(direction)
    assessment, changes = subject.propose(request, record_id="m61-shared-" + direction)
    assert assessment.state == StrategyState("ARMED") and assessment.reasons == ()
    assert assessment.stock_in_play == "TRUE"

    connection = await db.init_db()
    engine = StateTransitionEngine(TransitionScope(
        session(DAY), "SYNTH", "EQUITY", direction, STRATEGY_ID, VERSION,
        eligibility_rules()), SQLiteTransitionStore(connection))
    entry = await engine.apply(changes[0], context=supplied)
    assert engine.current_state() == StrategyState("ARMED")
    assert subject.confirm(changes[0]) == StrategyState("ARMED")
    store = ResearchEventStore(connection)
    stored = await store.append(changes[0], session=DAY, recorded_at=AT)
    assert stored["kind"] == "STATE_TRANSITION"
    assert await store.append(changes[0], session=DAY, recorded_at=AT) == stored

    proof = {
        "synthetic_only": True, "direction": direction, "bars": len(history.bars),
        "bar_sha256": hashlib.sha256(
            "".join(row.to_json() for row in history.bars).encode()).hexdigest(),
        "shared_feature_values": {name: values[name] for name in sorted(values)},
        "assessment": assessment.as_dict(), "transition": changes[0].as_dict(),
        "stored_position": entry.position, "stored_fingerprint": stored["fingerprint"],
        "repeated_assessment_identical":
            evaluate_orb5_eligibility(request).to_json() == assessment.to_json(),
    }
    assert proof["repeated_assessment_identical"]
    rendered = json.dumps(proof, sort_keys=True, separators=(",", ":"))
    assert len(rendered.encode()) < 100000
    Path(f"/tmp/m61-orb5-eligibility-{direction.lower()}-proof.json").write_text(rendered)
    await db.close_db()


async def test_a_refused_recording_leaves_the_machine_below_armed():
    class Refusing:
        async def append(self, entry):
            raise RecordError("synthetic storage refusal")

    subject = machine()
    supplied = eligibility()
    _, changes = subject.propose(supplied, record_id="m61-refused")
    engine = StateTransitionEngine(TransitionScope(
        session(DAY), "SYNTH", "EQUITY", "LONG", STRATEGY_ID, VERSION,
        eligibility_rules()), Refusing())
    with pytest.raises(RecordError):
        await engine.apply(changes[0], context=supplied.context)
    assert engine.current_state() == StrategyState("NOT_ELIGIBLE")
    assert subject.current_state() == StrategyState("NOT_ELIGIBLE")
