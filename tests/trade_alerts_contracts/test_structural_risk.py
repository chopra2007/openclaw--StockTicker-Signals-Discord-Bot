"""D-090 supplied geometry, never a trading strategy or real catalog proof."""

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

from consensus_engine.core_price_features import build_core_price_snapshot
from consensus_engine.historical_bars import HistoryRequest
from consensus_engine.opening_range_features import build_opening_range_snapshot
from consensus_engine.structural_risk import (
    FamilyCoverage, PriceInput, REQUIRED_FAMILIES, RiskTargetRequest, SELECTOR_VERSION,
    StructuralCatalog, StructuralLevel, VARIANTS, select_b_risk_targets,
)
from consensus_engine.trade_alerts_models import (
    AlertCandidate, Bar, ConfidenceBreakdown, ConfidenceComponent, FeatureSnapshot,
    FeatureValue, RecordError, RiskLevel, SourceMetadata, TargetLevel,
)
from test_core_price_features import bar, batch
from test_strategy_interface import session


PACIFIC = ZoneInfo("America/Los_Angeles")
CROSS = datetime(2026, 7, 6, 6, 50, tzinfo=PACIFIC)
TRIGGER = CROSS + timedelta(seconds=10)
BASIS = "SYNTHETIC_SOURCE_VENUE_RAW_V1"


def metadata(at=TRIGGER, **changes):
    fields = dict(instrument_id="SYNTH", instrument_type="EQUITY", source="SYNTHETIC",
                  source_time=at, received_time=at, available_time=at, normalized_time=at,
                  session="2026-07-06", data_mode="SUPPLIED_FEATURES", quality="VALID")
    fields.update(changes)
    return SourceMetadata(**fields)


def price(name, value, *, at=TRIGGER, mode="SUPPLIED_FEATURES", **changes):
    fields = dict(record_id=name, metadata=metadata(at, data_mode=mode), evaluated_at=at,
                  feature_version="M43_FIXTURE_ONLY_V1",
                  features=(FeatureValue(name, value, "USD_PER_SHARE",
                                         "MISSING_INPUT" if value is None else None,
                                         ("supplied-" + name,)),),
                  input_record_ids=("supplied-" + name,))
    fields.update(changes)
    snap = FeatureSnapshot(**fields)
    return PriceInput(FeatureSnapshot.from_json(snap.to_json()), name, BASIS)


def level(value, name="RESISTANCE", *, family="OTHER_STRUCTURE", target=True, obstacle=True):
    return StructuralLevel(price(name, value), family, name, target, obstacle)


def request(direction="LONG", *, variant=VARIANTS[0], levels=None):
    long = direction == "LONG"
    mode = "ELIGIBLE_TRADE_PATH" if variant == VARIANTS[0] else "QUOTE_LAST_TRADE_PATH_ESTIMATE"
    rows = levels if levels is not None else (
        level(101.50 if long else 49.50, "FIRST_LEVEL"),
        level(102.00 if long else 49.00, "SECOND_LEVEL"),
    )
    catalog = StructuralCatalog(
        "M43_SUPPLIED_CATALOG_ONLY_V1", metadata(), BASIS,
        tuple(FamilyCoverage(family, "COMPLETE", TRIGGER, TRIGGER, "SYNTHETIC_ONLY")
              for family in REQUIRED_FAMILIES), tuple(rows),
    )
    return RiskTargetRequest(
        variant, direction, CROSS, TRIGGER,
        price("PATH_ANCHOR", 100.80 if long else 50.20, mode=mode),
        price("ATR_1M_20_SMA_V1", 0.4, at=CROSS),
        price("PRICE_INCREMENT", 0.01, at=CROSS),
        price("CROSSING_BOUNDARY", 101.02 if long else 49.98, at=CROSS),
        price("ELIGIBLE_LATEST_TRADE", 101.03 if long else 49.97, mode=mode),
        True, "SUPPLIED_PATH_ONLY", catalog,
    )


def changed_value(row, value, *, unit="USD_PER_SHARE"):
    old = row.snapshot.features[0]
    feature = replace(old, value=value, unit=unit,
                      missing_reason="MISSING_INPUT" if value is None else None)
    return replace(row, snapshot=replace(row.snapshot, features=(feature,)))


def geometry(direction="LONG", *, targets=(11.5, 12.5), entry=10, boundary=10, anchor=9.05):
    """Exactly 1 dollar risk; short is the price mirror around 10."""
    supplied = request(direction)
    mirror = (lambda p: p) if direction == "LONG" else (lambda p: float(Decimal(20) - Decimal(str(p))))
    return replace(supplied,
                   anchor=changed_value(supplied.anchor, mirror(anchor)),
                   frozen_atr=changed_value(supplied.frozen_atr, 1),
                   entry=changed_value(supplied.entry, mirror(entry)),
                   boundary=changed_value(supplied.boundary, mirror(boundary)),
                   catalog=replace(supplied.catalog, levels=tuple(
                       level(mirror(p), f"level-{n}") for n, p in enumerate(targets))))


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("variant", VARIANTS)
def test_d090_fx08_fx09_and_canonical_geometry(direction, variant):
    result = select_b_risk_targets(request(direction, variant=variant))
    assert result.status == "READY" and result.reasons == ()
    assert result.raw_stop == (100.78 if direction == "LONG" else 50.22)
    assert result.risk == RiskLevel(101.03 if direction == "LONG" else 49.97,
                                   result.raw_stop, .25, result.risk.rationale, "PATH_ANCHOR")
    assert result.extension_r == .04
    assert [(t.name, t.price, t.r_multiple) for t in result.targets] == [
        ("T1", 101.5 if direction == "LONG" else 49.5, 1.88),
        ("T2", 102 if direction == "LONG" else 49, 3.88)]
    assert result.unavailable == ("SOFT_INVALIDATION_UNDEFINED", "RUNNER_UNDEFINED")
    assert result.request.variant == variant


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("tick,expected", ((.01, 8.98), (.05, 8.95), (.001, 8.989)))
def test_outward_tick_rounding_preserves_raw_stop_and_unrounded_boundary(direction, tick, expected):
    supplied = geometry(direction, targets=(12, 13), anchor=9.039, boundary=9.8135)
    supplied = replace(supplied, price_increment=changed_value(supplied.price_increment, tick))
    result = select_b_risk_targets(supplied)
    assert result.status == "READY"
    assert result.raw_stop == pytest.approx(8.989 if direction == "LONG" else 11.011)
    assert result.risk.hard_stop == pytest.approx(expected if direction == "LONG" else 20 - expected)
    assert result.request.boundary.snapshot.features[0].value == (9.8135 if direction == "LONG" else 20 - 9.8135)


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("boundary,status", ((9.650000001, "READY"), (9.65, "READY"), (9.649999999, "REJECTED")))
def test_extension_compares_exactly_before_display_rounding(direction, boundary, status):
    result = select_b_risk_targets(geometry(direction, boundary=boundary))
    assert result.status == status
    assert result.reasons == (() if status == "READY" else ("STALE_EXTENSION",))
    if boundary == 9.65:
        assert result.extension_r == .35


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("obstacle,reason", ((10.999999999, "OBSTACLE_BELOW_1R"), (11, "INSUFFICIENT_RR"),
                                           (11.499999999, "INSUFFICIENT_RR"), (11.5, None)))
def test_nearest_obstacle_and_exact_t1_room(direction, obstacle, reason):
    result = select_b_risk_targets(geometry(direction, targets=(obstacle, 11.5, 12.5)))
    assert result.status == ("REJECTED" if reason else "READY")
    assert result.reasons == ((reason,) if reason else ())


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_non_target_obstacle_before_t1_blocks_even_above_minimum_room(direction):
    supplied = geometry(direction, targets=(12, 13))
    near = level(11.6 if direction == "LONG" else 8.4, "BLOCK_ONLY", target=False)
    supplied = replace(supplied, catalog=replace(supplied.catalog, levels=(near, *supplied.catalog.levels)))
    result = select_b_risk_targets(supplied)
    assert result.status == "REJECTED" and result.reasons == ("INSUFFICIENT_RR",)


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("targets,expected", (((11.5, 12.499999999), (1.5,)), ((11.5, 12.5), (1.5, 2.5)),
                                            ((13, 13), (3,)), ((13, 14), (3, 4))))
def test_t2_is_next_distinct_admitted_level_and_never_fabricated(direction, targets, expected):
    result = select_b_risk_targets(geometry(direction, targets=targets))
    assert result.status == "READY"
    assert tuple(t.r_multiple for t in result.targets) == expected
    assert ("T2_UNAVAILABLE" in result.unavailable) == (len(expected) == 1)


def test_equal_prices_keep_every_label_reference_and_are_order_independent():
    supplied = geometry(targets=())
    levels = (level(11.5, "PMH", family="PREMARKET"), level(11.5, "PDH", family="PRIOR_DAY"),
              level(12.5, "FAR"), level(11.5, "OBSTACLE", target=False))
    supplied = replace(supplied, catalog=replace(supplied.catalog, levels=levels))
    result = select_b_risk_targets(supplied)
    reversed_result = select_b_risk_targets(replace(supplied, catalog=replace(supplied.catalog, levels=levels[::-1])))
    assert result.status == "READY" and len(result.targets) == 2
    assert result.target_labels[0] == ("OBSTACLE", "PDH", "PMH")
    assert result.target_input_ids[0] == ("OBSTACLE", "PDH", "PMH")
    assert (result.targets, result.target_labels, result.target_input_ids) == (
        reversed_result.targets, reversed_result.target_labels, reversed_result.target_input_ids)


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("targets", ((), (8, 9, 10), (11,)))
def test_no_admitted_directional_t1_rejects_without_an_arbitrary_multiple(direction, targets):
    supplied = geometry(direction, targets=targets)
    supplied = replace(supplied, catalog=replace(supplied.catalog, levels=tuple(
        replace(l, blocking_obstacle=False) for l in supplied.catalog.levels)))
    result = select_b_risk_targets(supplied)
    assert result.status == "REJECTED" and result.reasons == ("INSUFFICIENT_RR",)
    assert result.targets == ()


@pytest.mark.parametrize("field", ("anchor", "frozen_atr", "price_increment", "boundary", "entry"))
def test_missing_each_risk_input_stays_unavailable(field):
    supplied = request()
    supplied = replace(supplied, **{field: changed_value(getattr(supplied, field), None)})
    result = select_b_risk_targets(supplied)
    assert result.status == "UNAVAILABLE" and result.risk is None
    assert any(r.startswith(field.upper() + ":") for r in result.reasons)


@pytest.mark.parametrize("family", REQUIRED_FAMILIES)
def test_every_required_family_must_have_complete_coverage(family):
    supplied = request()
    supplied = replace(supplied, catalog=replace(supplied.catalog, coverage=tuple(
        row for row in supplied.catalog.coverage if row.family != family)))
    result = select_b_risk_targets(supplied)
    assert result.status == "UNAVAILABLE" and result.targets == ()
    assert "CATALOG_INCOMPLETE:" + family in result.reasons


@pytest.mark.parametrize("change", (
    {"status": "UNKNOWN"}, {"status": "UNAVAILABLE"}, {"evidence_reference": " Unknown "},
    {"evidence_reference": " unspecified "}, {"available_at": TRIGGER + timedelta(seconds=1)},
    {"covered_through": TRIGGER - timedelta(seconds=1)},
))
def test_catalog_labels_late_or_old_coverage_cannot_certify_clear_room(change):
    supplied = request()
    coverage = (replace(supplied.catalog.coverage[0], **change), *supplied.catalog.coverage[1:])
    result = select_b_risk_targets(replace(supplied, catalog=replace(supplied.catalog, coverage=coverage)))
    assert result.status == "UNAVAILABLE"
    assert result.reasons == ("CATALOG_INCOMPLETE:PREMARKET",)


@pytest.mark.parametrize("change", ({"path_complete": False}, {"path_evidence_reference": "UNKNOWN"}))
def test_anchor_path_is_not_invented(change):
    result = select_b_risk_targets(replace(request(), **change))
    assert result.status == "UNAVAILABLE" and "ANCHOR_PATH_INCOMPLETE" in result.reasons


@pytest.mark.parametrize("mutation,expected", (
    ("unit", "WRONG_UNIT"), ("basis", "PRICE_BASIS_MISMATCH"), ("definition", "DEFINITION_UNAVAILABLE"),
    ("symbol", "IDENTITY_MISMATCH"), ("instrument", "IDENTITY_MISMATCH"), ("session", "IDENTITY_MISMATCH"),
    ("source", "SOURCE_UNAVAILABLE"), ("mode", "QUALITY_UNAVAILABLE"), ("quality", "QUALITY_UNAVAILABLE"),
    ("source_time", "INVALID_SOURCE_TIME"), ("late", "NOT_YET_AVAILABLE"), ("missing_name", "VALUE_UNAVAILABLE"),
))
def test_bad_selected_feature_attribution_remains_unavailable(mutation, expected):
    supplied = request()
    row = supplied.frozen_atr
    if mutation == "unit":
        row = changed_value(row, .4, unit="RATIO")
    elif mutation == "basis":
        row = replace(row, price_basis="OTHER_SOURCE_ADJUSTMENT")
    elif mutation == "definition":
        row = replace(row, snapshot=replace(row.snapshot, feature_version="UNSPECIFIED"))
    elif mutation == "missing_name":
        row = replace(row, snapshot=replace(row.snapshot, features=()))
    else:
        changes = {"symbol": {"instrument_id": "OTHER"}, "instrument": {"instrument_type": "OPTION"},
                   "session": {"session": "2026-07-07"}, "source": {"source": "UNKNOWN"},
                   "mode": {"data_mode": "UNKNOWN"}, "quality": {"quality": "STALE"},
                   "source_time": {"source_time": CROSS + timedelta(seconds=1)},
                   "late": {"available_time": CROSS + timedelta(seconds=1)}}[mutation]
        meta = replace(row.snapshot.metadata, **changes)
        row = replace(row, snapshot=replace(row.snapshot, metadata=meta,
                                            evaluated_at=max(meta.available_time, row.snapshot.evaluated_at)))
    result = select_b_risk_targets(replace(supplied, frozen_atr=row))
    assert result.status == "UNAVAILABLE" and "FROZEN_ATR:" + expected in result.reasons


@pytest.mark.parametrize("field", ("anchor", "entry"))
def test_stale_trigger_snapshot_cannot_be_refreshed_by_request_time(field):
    supplied = request()
    row = getattr(supplied, field)
    row = replace(row, snapshot=replace(row.snapshot, metadata=metadata(CROSS, data_mode="ELIGIBLE_TRADE_PATH"),
                                       evaluated_at=CROSS))
    result = select_b_risk_targets(replace(supplied, **{field: row}))
    assert result.status == "UNAVAILABLE" and "TRIGGER_INPUT_NOT_CURRENT" in result.reasons


@pytest.mark.parametrize("field", ("anchor", "entry"))
def test_tape_and_quote_path_modes_cannot_be_mixed(field):
    supplied = request()
    row = getattr(supplied, field)
    row = replace(row, snapshot=replace(row.snapshot, metadata=replace(
        row.snapshot.metadata, data_mode="QUOTE_LAST_TRADE_PATH_ESTIMATE")))
    result = select_b_risk_targets(replace(supplied, **{field: row}))
    assert result.status == "UNAVAILABLE" and "PATH_MODE_MISMATCH" in result.reasons


def test_zero_atr_is_known_but_zero_tick_and_nonpositive_stop_are_not_usable():
    supplied = geometry(anchor=9)
    result = select_b_risk_targets(replace(supplied, frozen_atr=changed_value(supplied.frozen_atr, 0)))
    assert result.status == "READY" and result.risk.hard_stop == 9
    result = select_b_risk_targets(replace(supplied, price_increment=changed_value(supplied.price_increment, 0)))
    assert result.status == "UNAVAILABLE"
    supplied = replace(supplied, frozen_atr=changed_value(supplied.frozen_atr, 200))
    result = select_b_risk_targets(supplied)
    assert result.status == "REJECTED" and result.reasons == ("INVALID_STOP_GEOMETRY",)


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_zero_risk_wrong_anchor_and_entry_before_boundary(direction):
    supplied = geometry(direction, anchor=10)
    result = select_b_risk_targets(replace(supplied, frozen_atr=changed_value(supplied.frozen_atr, 0)))
    assert result.reasons == ("INVALID_STOP_GEOMETRY",)
    assert result.risk is None
    result = select_b_risk_targets(geometry(direction, anchor=10.01))
    assert result.reasons == ("ANCHOR_EXCLUDES_ENTRY",)
    result = select_b_risk_targets(geometry(direction, boundary=10.01))
    assert result.reasons == ("ENTRY_BEFORE_BOUNDARY",)


@pytest.mark.parametrize("change", ("missing", "future", "bad_basis", "stale", "wrong_unit"))
def test_unusable_catalog_level_cannot_disappear_even_on_wrong_side(change):
    supplied = request()
    row = level(1, "UNKNOWN_OBSTACLE")
    if change == "missing":
        row = replace(row, price=changed_value(row.price, None))
    elif change == "future":
        row = replace(row, price=price("UNKNOWN_OBSTACLE", 1, at=TRIGGER + timedelta(seconds=1)))
    elif change == "bad_basis":
        row = replace(row, price=replace(row.price, price_basis="UNKNOWN"))
    elif change == "stale":
        row = replace(row, price=replace(row.price, snapshot=replace(row.price.snapshot,
            metadata=replace(row.price.snapshot.metadata, quality="STALE"))))
    else:
        row = replace(row, price=changed_value(row.price, 1, unit="TICKS"))
    result = select_b_risk_targets(replace(supplied, catalog=replace(supplied.catalog,
                                               levels=(row, *supplied.catalog.levels))))
    assert result.status == "UNAVAILABLE" and result.targets == ()
    assert any(r.startswith("LEVEL:") for r in result.reasons)


def test_conflicting_ids_do_not_overwrite_original_facts():
    supplied = request()
    altered = replace(supplied.entry, snapshot=replace(supplied.entry.snapshot,
                                                       record_id=supplied.anchor.snapshot.record_id))
    result = select_b_risk_targets(replace(supplied, entry=altered))
    assert result.status == "UNAVAILABLE" and "CONFLICTING_INPUT_ID" in result.reasons


@pytest.mark.parametrize("case", ("variant", "direction", "naive", "backward", "next_session", "coverage_duplicate",
                                 "mutable_levels", "bad_role", "future_coverage"))
def test_invalid_contract_shape_raises_without_io(case):
    supplied = request()
    with pytest.raises(RecordError):
        if case == "variant":
            replace(supplied, variant="M03B_PROPOSAL")
        elif case == "direction":
            replace(supplied, direction="BULLISH")
        elif case == "naive":
            replace(supplied, crossed_at=CROSS.replace(tzinfo=None))
        elif case == "backward":
            replace(supplied, evaluated_at=CROSS - timedelta(seconds=1))
        elif case == "next_session":
            replace(supplied, evaluated_at=TRIGGER + timedelta(days=1))
        elif case == "coverage_duplicate":
            replace(supplied.catalog, coverage=(*supplied.catalog.coverage, supplied.catalog.coverage[0]))
        elif case == "mutable_levels":
            replace(supplied.catalog, levels=list(supplied.catalog.levels))
        elif case == "bad_role":
            replace(supplied.catalog.levels[0], admitted_target=1)
        else:
            replace(supplied.catalog.coverage[0], covered_through=TRIGGER + timedelta(seconds=1))


def test_original_results_and_nested_inputs_remain_immutable_and_detached():
    supplied = request()
    result = select_b_risk_targets(supplied)
    original = result.to_json()
    detached = result.as_dict()
    detached["risk"]["hard_stop"] = 1
    detached["request"]["catalog"]["levels"].clear()
    with pytest.raises(FrozenInstanceError):
        result.risk.hard_stop = 1
    newer = replace(supplied, catalog=replace(supplied.catalog, levels=(level(101.1, "LATER_OBSTACLE"),)))
    assert select_b_risk_targets(newer).status == "REJECTED"
    assert result.to_json() == original
    assert select_b_risk_targets(supplied).to_json() == original
    assert json.loads(original)["selector_version"] == SELECTOR_VERSION


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_supplied_bars_to_shared_features_risk_candidate_recording_end_to_end(direction):
    sign = 1 if direction == "LONG" else -1
    mirror = (lambda p: p) if sign == 1 else (lambda p: float(Decimal(151) - Decimal(str(p))))
    opened = CROSS - timedelta(minutes=20)
    history_request = HistoryRequest("SYNTH", opened, CROSS)
    bars = []
    for n, interval in enumerate(history_request.expected_intervals()):
        low, high = (100.6, 101) if n < 5 else (100.8, 101.2)
        prices = sorted((mirror(low), mirror(high)))
        row = bar(f"m43-minute-{n}", interval.start, interval.end,
                  high=prices[1], low=prices[0], close=mirror((low + high) / 2))
        bars.append(Bar.from_json(row.to_json()))
    history = batch(history_request, bars)
    core = build_core_price_snapshot(record_id="m43-core", evaluated_at=CROSS,
                                    minute_history=history, daily_history=None, premarket_history=None)
    opening = build_opening_range_snapshot(record_id="m43-opening", evaluated_at=CROSS,
                                           symbol="SYNTH", instrument_type="EQUITY", minute_history=history)
    core = FeatureSnapshot.from_json(core.to_json())
    opening = FeatureSnapshot.from_json(opening.to_json())
    atr = next(f for f in core.features if f.name == "ATR_1M_20_SMA_V1")
    assert atr.value == .4 and len(atr.input_record_ids) == 20
    extrema = {f.name: f.value for f in opening.features}
    boundary = (extrema["OPENING_RANGE_HIGH_5M_V1"] + .02 if sign == 1
                else extrema["OPENING_RANGE_LOW_5M_V1"] - .02)
    supplied = request(direction)
    anchor_value = bars[-1].low if sign == 1 else bars[-1].high
    supplied = replace(supplied, frozen_atr=PriceInput(core, atr.name, BASIS),
                       anchor=changed_value(supplied.anchor, anchor_value),
                       boundary=changed_value(supplied.boundary, boundary))
    result = select_b_risk_targets(supplied)
    assert result.status == "READY" and result.risk.risk_per_share == .25
    assert [t.r_multiple for t in result.targets] == [1.88, 3.88]
    saved_session = session()
    # Candidate assembly and score are fixture-only. No playbook is evaluated.
    candidate = AlertCandidate(
        record_id="m43-" + direction, metadata=metadata(), strategy_id="CRVOL_ORB5",
        strategy_version="M43_FIXTURE_ONLY_V1", direction=direction, alert_type="ACTIONABLE",
        setup_state="ALERT_TRIGGERED", strategy_lifecycle="DEVELOPMENT", evidence_stage="IMPLEMENTED",
        delivery_status="PENDING", structure_id="M43_FIXTURE_STRUCTURE", trigger_price=boundary,
        alert_price=result.risk.entry_reference, risk=result.risk, targets=result.targets,
        confidence=ConfidenceBreakdown(0, 0, 0, 0, (ConfidenceComponent("fixture", 0, "FIXTURE_ONLY"),)),
        feature_snapshot_id=core.record_id, input_record_ids=(core.record_id, opening.record_id),
        session_record_id=saved_session.record_id, config_version=saved_session.config_version,
        config_hash=saved_session.config_hash, created_at=TRIGGER,
        expires_at=TRIGGER + timedelta(seconds=1), data_quality="VALID", mechanically_valid=True,
    )
    assert AlertCandidate.from_json(candidate.to_json()) == candidate
    assert isinstance(candidate.risk, RiskLevel) and all(isinstance(t, TargetLevel) for t in candidate.targets)
    frozen = candidate.to_json()
    missing = select_b_risk_targets(replace(supplied, path_complete=False))
    incomplete = select_b_risk_targets(replace(supplied, catalog=replace(supplied.catalog, coverage=())))
    near = level(mirror(101.1), "LATER_OBSTACLE")
    later = select_b_risk_targets(replace(supplied, catalog=replace(supplied.catalog, levels=(near,))))
    assert (missing.status, incomplete.status, later.status) == ("UNAVAILABLE", "UNAVAILABLE", "REJECTED")
    assert candidate.to_json() == frozen
    proof = {
        "synthetic_only": True, "direction": direction,
        "bars": len(bars), "history_complete": history.coverage_at(CROSS).complete,
        "bar_sha256": hashlib.sha256("".join(b.to_json() for b in bars).encode()).hexdigest(),
        "atr": atr.value, "opening_values": extrema, "result": result.as_dict(),
        "candidate": candidate.as_dict(), "failure_reasons": [missing.reasons, incomplete.reasons, later.reasons],
        "repeated_result_identical": select_b_risk_targets(supplied).to_json() == result.to_json(),
        "original_candidate_unchanged": candidate.to_json() == frozen,
    }
    assert proof["history_complete"] and proof["repeated_result_identical"]
    rendered = json.dumps(proof, sort_keys=True, separators=(",", ":"))
    assert len(rendered.encode()) < 100000
    Path(f"/tmp/m43-structural-risk-{direction.lower()}-proof.json").write_text(rendered)


@pytest.mark.parametrize("field,value", (("version", "UNKNOWN"), ("price_basis", "UNSPECIFIED")))
def test_unknown_catalog_contract_cannot_be_ready(field, value):
    supplied = request()
    result = select_b_risk_targets(replace(supplied, catalog=replace(supplied.catalog, **{field: value})))
    assert result.status == "UNAVAILABLE" and result.targets == ()


def test_another_atr_feature_cannot_substitute_for_frozen_twenty_minute_atr():
    supplied = request()
    wrong = price("DAILY_ATR_14_SMA_V1", .4, at=CROSS)
    result = select_b_risk_targets(replace(supplied, frozen_atr=wrong))
    assert result.status == "UNAVAILABLE" and "FROZEN_ATR_WRONG_DEFINITION" in result.reasons


@pytest.mark.parametrize("value", (True, float("nan"), float("inf")))
def test_non_numeric_or_nonfinite_prices_are_rejected_by_canonical_records(value):
    with pytest.raises(RecordError):
        price("bad-price", value)


def test_later_atr_revision_cannot_change_frozen_crossing_geometry():
    supplied = request()
    original = select_b_risk_targets(supplied).to_json()
    revised = changed_value(supplied.frozen_atr, .8)
    revised = replace(revised, snapshot=replace(revised.snapshot, metadata=metadata(TRIGGER, revision=1),
                                               evaluated_at=TRIGGER))
    result = select_b_risk_targets(replace(supplied, frozen_atr=revised))
    assert result.status == "UNAVAILABLE" and "FROZEN_ATR:NOT_YET_AVAILABLE" in result.reasons
    assert select_b_risk_targets(supplied).to_json() == original
