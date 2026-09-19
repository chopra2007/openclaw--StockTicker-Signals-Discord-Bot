"""M5.2 supplied-bar outcome proof for adopted D-090 O-01."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from functools import lru_cache
import json
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine import db
from consensus_engine.event_store import ResearchEventStore
from consensus_engine.historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from consensus_engine.outcome_evaluator import POLICY_VERSION, evaluate_bar_outcome
from consensus_engine.trade_alerts_models import (
    Bar, OutcomeRecord, RecordError, SourceMetadata, TargetLevel,
)
from consensus_engine.utils.time_context import as_utc, session_bounds
from test_alert_delivery import candidate
from test_strategy_interface import PACIFIC, START


@lru_cache(maxsize=1)
def _base_history():
    close = as_utc(session_bounds(START.date())[1])
    opened = as_utc(session_bounds(START.date())[0])
    request = HistoryRequest("SYNTH", opened, close, "1m", "REGULAR")
    bars = []
    for number, interval in enumerate(request.expected_intervals()):
        values = {"open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0}
        metadata = SourceMetadata(
            instrument_id="SYNTH", instrument_type="EQUITY", source="SYNTHETIC",
            source_time=interval.start, received_time=interval.end,
            available_time=interval.end, normalized_time=interval.end,
            session=interval.session, data_mode="BAR_ONLY_ORB5_O1_PROXY", quality="VALID",
        )
        bars.append(Bar(
            record_id=f"outcome-bar-{number}", metadata=metadata,
            start_time=interval.start, end_time=interval.end, is_final=True,
            volume=1000, adjustment_basis="RAW", price_convention="OHLC",
            volume_convention="SHARES", **values,
        ))
    return HistoryBatch(
        request=request, source="SYNTHETIC",
        conventions=HistoryConventions(
            timestamp="START", session="REGULAR", adjustment_basis="RAW",
            price="OHLC", volume="SHARES", coverage_basis="SUPPLIED_FIXTURE",
            finality="FINAL", publication="BAR_END", evidence_reference="M5.2_FIXTURE",
        ), bars=tuple(bars),
    )


def supplied_history(changes=None, omit=()):
    # Immutable common Bars can be reused without rebuilding 390 per case.
    history = _base_history()
    changes = changes or {}
    return replace(history, bars=tuple(
        replace(bar, **changes[number]) if number in changes else bar
        for number, bar in enumerate(history.bars) if number not in omit
    ))


def no_trade_bar(number):
    bar = _base_history().bars[number]
    metadata = replace(
        bar.metadata,
        source_time=bar.start_time,
        received_time=bar.end_time,
        available_time=bar.end_time,
        normalized_time=bar.end_time,
        quality="VALID",
    )
    return replace(
        bar, metadata=metadata, open=None, high=None, low=None, close=None,
        volume=0, certified_no_trade=True,
    )


def evaluate(direction="LONG", changes=None, omit=(), two_targets=False, reference_time=START,
             target_price=None):
    row, _ = candidate(direction)
    if target_price is not None:
        target_r = abs(target_price - row.risk.entry_reference) / row.risk.risk_per_share
        row = replace(row, targets=(replace(row.targets[0], price=target_price,
                                           r_multiple=target_r),))
    if two_targets:
        row = replace(row, targets=(*row.targets, TargetLevel(
            "T2", 103 if direction == "LONG" else 97, 3, "FIXTURE_LEVEL")))
    if direction == "SHORT":
        mirrored = {}
        for key, values in (changes or {}).items():
            converted = {}
            for name, value in values.items():
                converted[{"high": "low", "low": "high"}.get(name, name)] = 200 - value
            mirrored[key] = converted
        changes = mirrored
    history = supplied_history(changes, omit)
    return evaluate_bar_outcome(
        record_id="m52-" + direction, candidate=row, history=history,
        reference_time=reference_time, evaluated_at=history.request.end,
    ), row, history


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_t1_then_horizon_is_two_equal_units_and_mirrors(direction):
    result, _, _ = evaluate(direction, {7: {"high": 102, "close": 101}})
    assert result.entry_at == as_utc(START + timedelta(minutes=1))
    assert [row.reason for row in result.unit_exits] == ["T1", "HORIZON"]
    assert result.resolved_r == pytest.approx(1.0)
    assert result.original_resolved_r == pytest.approx(1.0)
    assert result.outcome.result == "RESOLVED"
    assert result.outcome.target_outcomes[0].hit is True
    assert result.outcome.policy_version == POLICY_VERSION


def test_same_bar_stop_and_target_is_stop_first_and_explicitly_ambiguous():
    result, _, _ = evaluate(changes={7: {"high": 102, "low": 99, "close": 100}})
    assert result.same_bar_ambiguous
    assert result.ambiguous_sensitivity == "UNRESOLVED"
    assert result.outcome.result == "AMBIGUOUS"
    assert result.status_reason == "STOP_FIRST_CONSERVATIVE"
    assert result.outcome.stop_hit is True
    assert result.outcome.target_outcomes[0].hit is False
    assert result.resolved_r == -1
    assert [row.reason for row in result.unit_exits] == ["STOP", "STOP"]


def test_target_on_earlier_bar_then_stop_only_closes_second_unit():
    result, _, _ = evaluate(changes={
        7: {"high": 102, "low": 99.9, "close": 101},
        8: {"open": 100.5, "high": 100.6, "low": 99, "close": 99},
    })
    assert [row.reason for row in result.unit_exits] == ["T1", "STOP"]
    assert result.resolved_r == pytest.approx(0.5)
    assert result.outcome.stop_hit is True


def test_distinct_t1_and_t2_close_one_unit_each_at_frozen_prices():
    row, _ = candidate()
    row = replace(row, targets=(*row.targets, TargetLevel("T2", 103, 3, "FIXTURE_LEVEL")))
    history = supplied_history({
        7: {"high": 102, "close": 101},
        8: {"open": 101, "high": 103, "low": 100.8, "close": 102},
    })
    result = evaluate_bar_outcome(
        record_id="m52-two-targets", candidate=row, history=history,
        reference_time=START, evaluated_at=history.request.end,
    )
    assert [(exit.reason, exit.price) for exit in result.unit_exits] == [("T1", 102), ("T2", 103)]
    assert [target.hit for target in result.outcome.target_outcomes] == [True, True]
    assert result.resolved_r == pytest.approx(2.5)


def test_stop_gap_uses_open_and_favorable_target_gap_uses_frozen_target():
    stopped, _, _ = evaluate(changes={7: {"open": 98.5, "high": 99, "low": 98, "close": 98.8}})
    assert [row.price for row in stopped.unit_exits] == [98.5, 98.5]
    target, _, _ = evaluate(changes={7: {"open": 103, "high": 103, "low": 102.5, "close": 102.8}})
    assert target.unit_exits[0].reason == "T1" and target.unit_exits[0].price == 102


def test_missing_path_stays_partial_and_does_not_invent_non_hits_or_horizon_exit():
    result, _, _ = evaluate(omit=(100,))
    assert result.outcome.coverage_status == "PARTIAL"
    assert result.outcome.result == "CENSORED"
    assert result.outcome.stop_hit is None
    assert result.outcome.target_outcomes[0].hit is None
    assert result.outcome.outcome_price is None and result.resolved_r is None


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
async def test_trailing_no_trade_minutes_leave_remaining_units_unresolved(direction, tmp_path):
    history = supplied_history({7: {"high": 102, "close": 101}})
    bars = list(history.bars)
    bars[-1] = no_trade_bar(len(bars) - 1)
    if direction == "SHORT":
        mirrored = []
        for bar in bars:
            if bar.certified_no_trade:
                mirrored.append(bar)
                continue
            mirrored.append(replace(
                bar, open=200 - bar.open, high=200 - bar.low,
                low=200 - bar.high, close=200 - bar.close,
            ))
        bars = mirrored
    history = replace(history, bars=tuple(bars))
    row, _ = candidate(direction)
    result = evaluate_bar_outcome(
        record_id="m52-no-trade-" + direction, candidate=row, history=history,
        reference_time=START, evaluated_at=history.request.end,
    )
    assert history.coverage_at(history.request.end).complete
    assert [row.reason for row in result.unit_exits] == ["T1"]
    assert result.outcome.result == "CENSORED"
    assert result.status_reason == "PATH_COVERAGE_INCOMPLETE"
    assert result.outcome.outcome_price is None
    assert result.resolved_r is None and result.original_resolved_r is None

    db.DB_PATH = str(tmp_path / ("m52-no-trade-" + direction + ".db"))
    db._db = None
    store = ResearchEventStore(await db.init_db())
    await store.append(row, session=row.metadata.session, recorded_at=row.created_at)
    await store.store_history(history, record_id="m52-history", session=row.metadata.session,
                              recorded_at=history.request.end)
    await store.store_outcome(result, session=row.metadata.session)
    before = await store.read_all()
    await db.close_db()
    db._db = None
    reopened = ResearchEventStore(await db.init_db())
    assert await reopened.read_all() == before
    saved = await reopened.read("m52:evaluation:" + result.outcome.record_id)
    assert json.loads(saved["record_json"])["outcome"]["result"] == "CENSORED"
    await db.close_db()


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
async def test_original_r_return_differs_from_actual_entry_r_and_survives_reopen(
        direction, tmp_path):
    result, row, history = evaluate(
        direction, {6: {"open": 100.2, "high": 100.2},
                    7: {"high": 102, "close": 101}})
    assert result.actual_risk == pytest.approx(1.2)
    assert result.original_risk == pytest.approx(1.0)
    assert result.resolved_r == pytest.approx(2 / 3)
    assert result.original_resolved_r == pytest.approx(1.0)

    db.DB_PATH = str(tmp_path / ("m52-original-r-" + direction + ".db"))
    db._db = None
    store = ResearchEventStore(await db.init_db())
    await store.append(row, session=row.metadata.session, recorded_at=row.created_at)
    await store.store_history(history, record_id="m52-history", session=row.metadata.session,
                              recorded_at=history.request.end)
    await store.store_outcome(result, session=row.metadata.session)
    before = await store.read_all()
    await db.close_db()
    db._db = None
    reopened = ResearchEventStore(await db.init_db())
    assert await reopened.read_all() == before
    saved = await reopened.read("m52:evaluation:" + result.outcome.record_id)
    facts = json.loads(saved["record_json"])
    assert facts["resolved_r"] == pytest.approx(2 / 3)
    assert facts["original_resolved_r"] == pytest.approx(1.0)
    await db.close_db()


def test_missing_entry_window_stays_unresolved_without_prices():
    result, _, _ = evaluate(omit=(6,))
    assert result.outcome.coverage_status == "UNRESOLVED"
    assert result.outcome.result == "UNKNOWN"
    assert result.entry_at is None and result.outcome.modeled_entry_price is None


@pytest.mark.parametrize("open_price", (99.0, 100.4))
def test_known_bad_entry_geometry_is_unfilled(open_price):
    result, _, _ = evaluate(changes={6: {"open": open_price, "high": open_price,
                                               "low": open_price, "close": open_price}})
    assert result.outcome.result == "UNFILLED"
    assert result.outcome.modeled_entry_price is None
    assert result.unit_exits == ()


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("extension,filled", ((0.35, True), (0.3500001, False)))
def test_entry_extension_boundary_is_exact_in_both_directions(direction, extension, filled):
    sign = 1 if direction == "LONG" else -1
    exact_extension = Decimal(str(extension))
    entry = Decimal("100") + sign * exact_extension
    stop = Decimal("99") if direction == "LONG" else Decimal("101")
    actual_risk = sign * (entry - stop)
    target = float(entry + sign * Decimal("1.5") * actual_risk)
    source_entry = float(Decimal("100") + exact_extension)
    result, _, _ = evaluate(
        direction,
        {6: {"open": source_entry, "high": source_entry,
             "low": source_entry, "close": source_entry}},
        target_price=target,
    )
    assert (result.outcome.result != "UNFILLED") is filled
    assert (result.outcome.modeled_entry_price is not None) is filled


def test_excursions_and_hit_times_are_point_in_time_bar_facts():
    result, _, _ = evaluate(changes={
        7: {"open": 100, "high": 101.5, "low": 99.5, "close": 101},
        8: {"open": 101, "high": 102, "low": 100.8, "close": 101.5},
    })
    assert result.outcome.mfe == 2 and result.outcome.mae == pytest.approx(0.5)
    assert result.outcome.max_r == 2
    assert result.outcome.target_outcomes[0].hit_at == supplied_history().bars[8].end_time


def test_wrong_candidate_or_history_contract_is_rejected():
    row, _ = candidate()
    history = supplied_history()
    with pytest.raises(RecordError, match="CRVOL_ORB5"):
        evaluate_bar_outcome(record_id="bad", candidate=replace(row, strategy_id="HOD_COMP_RS"),
                             history=history, reference_time=START, evaluated_at=history.request.end)
    with pytest.raises(RecordError, match="full regular session"):
        evaluate_bar_outcome(record_id="bad", candidate=row,
                             history=replace(history, request=replace(history.request,
                                             end=history.request.end - timedelta(minutes=1))),
                             reference_time=START, evaluated_at=history.request.end)


async def test_outcome_is_canonical_append_only_and_linked_to_inputs(tmp_path):
    result, row, history = evaluate(changes={7: {"high": 102, "close": 101}})
    db.DB_PATH = str(tmp_path / "m52.db")
    db._db = None
    store = ResearchEventStore(await db.init_db())
    await store.append(row, session=row.metadata.session, recorded_at=row.created_at)
    await store.store_history(history, record_id="m52-history", session=row.metadata.session,
                              recorded_at=history.request.end)
    await store.store_outcome(result, session=row.metadata.session)
    saved = await store.read(result.outcome.record_id)
    assert saved["kind"] == "OUTCOME"
    assert OutcomeRecord.from_json(saved["record_json"]) == result.outcome
    links = await store.links(result.outcome.record_id)
    assert links[0] == {"record_id": row.record_id, "role": "CANDIDATELINK",
                        "status": "RESOLVED", "kind": "CANDIDATE"}
    assert all(item["status"] == "RESOLVED" for item in links)
    before = await store.read_all()
    await store.store_outcome(result, session=row.metadata.session)
    assert await store.read_all() == before
    with pytest.raises(RecordError, match="conflicts"):
        await store.store_outcome(replace(result, status_reason="CHANGED"), session=row.metadata.session)
    assert await store.read_all() == before
    await db.close_db()
    db._db = None
    reopened = ResearchEventStore(await db.init_db())
    assert await reopened.read_all() == before
    await db.close_db()


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("at_open", (False, True))
@pytest.mark.parametrize("later_stop", (False, True))
def test_all_targets_in_one_bar_are_processed_before_advancing(direction, at_open, later_stop):
    values = {"open": 103 if at_open else 100, "high": 103,
              "low": 99 if later_stop else 99.9, "close": 100}
    result, _, history = evaluate(direction, {7: values}, two_targets=True)
    if later_stop and not at_open:
        assert result.outcome.result == "AMBIGUOUS"
        assert [row.reason for row in result.unit_exits] == ["STOP", "STOP"]
        assert result.resolved_r == -1
    else:
        assert result.outcome.result == "RESOLVED"
        assert not result.same_bar_ambiguous
        assert result.ambiguous_sensitivity == "NOT_APPLICABLE"
        assert [row.reason for row in result.unit_exits] == ["T1", "T2"]
        assert [row.price for row in result.unit_exits] == ([102, 103] if direction == "LONG" else [98, 97])
        expected_at = history.bars[7].start_time if at_open else history.bars[7].end_time
        assert all(row.at == expected_at for row in result.unit_exits)
        assert result.resolved_r == 2.5
        assert [row.hit for row in result.outcome.target_outcomes] == [True, True]


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_t1_at_open_precedes_ambiguous_t2_and_stop_range(direction):
    result, _, _ = evaluate(direction, {7: {"open": 102, "high": 103, "low": 99}},
                            two_targets=True)
    assert [row.reason for row in result.unit_exits] == ["T1", "STOP"]
    assert result.outcome.result == "AMBIGUOUS"
    assert result.ambiguous_sensitivity == "UNRESOLVED"
    assert result.resolved_r == 0.5


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("reference_minutes,filled", ((37, True), (38, False), (39, False), (40, False)))
def test_entry_and_availability_are_strictly_before_0715(direction, reference_minutes, filled):
    # START is 06:35 Pacific. The 07:14 open becomes available at 07:15.
    result, _, _ = evaluate(direction, reference_time=START + timedelta(minutes=reference_minutes))
    if filled:
        assert result.entry_at.astimezone(PACIFIC).strftime("%H:%M") == "07:13"
    else:
        assert result.outcome.result == "UNKNOWN"
        assert result.status_reason == "ENTRY_WINDOW_UNRESOLVED"
        assert result.entry_at is None
        assert result.unit_exits == () and result.resolved_r is None


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("earlier_t1", (False, True))
@pytest.mark.parametrize("later_exit", ("target", "stop"))
def test_gap_keeps_exposed_units_uncertain_despite_later_exits(direction, earlier_t1, later_exit):
    changes = {9: {"high": 103} if later_exit == "target" else {"low": 99}}
    if earlier_t1:
        changes[7] = {"high": 102}
    result, _, _ = evaluate(direction, changes, omit=(8,), two_targets=True)
    assert result.outcome.result == "CENSORED"
    assert result.status_reason == "PATH_COVERAGE_INCOMPLETE"
    assert result.outcome.outcome_price is None and result.resolved_r is None
    assert result.outcome.stop_hit is None
    assert [row.reason for row in result.unit_exits] == (["T1"] if earlier_t1 else [])
    assert [row.hit for row in result.outcome.target_outcomes] == ([True, None] if earlier_t1 else [None, None])


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
async def test_compact_end_to_end_recording(direction, tmp_path):
    result, _, _ = evaluate(direction, {7: {"high": 102, "close": 101}})
    payload = {
        "direction": direction, "outcome": result.outcome.as_dict(),
        "status_reason": result.status_reason,
        "entry_at": result.entry_at.isoformat(), "actual_risk": result.actual_risk,
        "original_risk": result.original_risk,
        "same_bar_ambiguous": result.same_bar_ambiguous,
        "ambiguous_sensitivity": result.ambiguous_sensitivity,
        "unit_exits": [row.__dict__ for row in result.unit_exits],
        "resolved_r": result.resolved_r,
        "original_resolved_r": result.original_resolved_r,
    }
    payload["durable_cases"] = {}
    for name, changes, omit in (
        ("resolved", {7: {"open": 103, "high": 103, "low": 99}}, ()),
        ("ambiguous", {7: {"high": 103, "low": 99}}, ()),
        ("partial", {7: {"high": 102}, 9: {"high": 103}}, (8,)),
    ):
        evaluation, row, history = evaluate(direction, changes, omit, two_targets=True)
        db.DB_PATH = str(tmp_path / (name + ".db"))
        db._db = None
        store = ResearchEventStore(await db.init_db())
        await store.append(row, session=row.metadata.session, recorded_at=row.created_at)
        await store.store_history(history, record_id="m52-history", session=row.metadata.session,
                                  recorded_at=history.request.end)
        await store.store_outcome(evaluation, session=row.metadata.session)
        before = await store.read_all()
        await db.close_db()
        db._db = None
        store = ResearchEventStore(await db.init_db())
        assert await store.read_all() == before
        saved = await store.read("m52:evaluation:" + evaluation.outcome.record_id)
        facts = json.loads(saved["record_json"])
        assert facts == {"store_version": "M51_V1", **evaluation.as_dict()}
        assert facts["outcome"]["result"] == name.upper().replace("PARTIAL", "CENSORED")
        canonical = await store.read(evaluation.outcome.record_id)
        assert OutcomeRecord.from_json(canonical["record_json"]) == evaluation.outcome
        await store.store_outcome(evaluation, session=row.metadata.session)
        assert await store.read_all() == before
        payload["durable_cases"][name] = {"evaluation": facts, "reopen_equal": True}
        await db.close_db()
    range_result, _, _ = evaluate(direction, {7: {"high": 103}}, two_targets=True)
    boundary, _, _ = evaluate(direction, reference_time=START + timedelta(minutes=39))
    gap, _, _ = evaluate(direction, {9: {"high": 103}}, omit=(8,), two_targets=True)
    assert [row.reason for row in range_result.unit_exits] == ["T1", "T2"]
    assert boundary.entry_at is None and boundary.status_reason == "ENTRY_WINDOW_UNRESOLVED"
    assert gap.unit_exits == () and gap.resolved_r is None
    payload["other_repair_paths"] = {
        "both_range_targets": [row.reason for row in range_result.unit_exits],
        "range_result_r": range_result.resolved_r,
        "entry_at_0715": boundary.status_reason,
        "gap_before_targets": gap.status_reason,
        "gap_exits": [], "gap_resolved_r": gap.resolved_r,
    }
    path = Path(f"/tmp/m52-outcome-{direction.lower()}-proof.json")
    path.write_text(json.dumps(payload, sort_keys=True, default=str, indent=2) + "\n")
    assert path.stat().st_size < 100_000
