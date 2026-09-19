"""M3.3 frozen relative-strength calculations over supplied synthetic records."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from consensus_engine.relative_strength_features import (
    DATA_MODE, FEATURE_VERSION, EligibleTradeObservation, build_relative_strength_snapshot,
)
from consensus_engine.trade_alerts_models import Bar, FeatureSnapshot, RecordError, SourceMetadata
from consensus_engine.utils.time_context import as_utc, session_bounds


PACIFIC = ZoneInfo("America/Los_Angeles")
DAY = "2026-07-06"


def at(clock):
    return datetime.fromisoformat(f"{DAY}T{clock}").replace(tzinfo=PACIFIC)


def history(symbol, instrument_type, step, *, changed=None):
    opened = as_utc(session_bounds(at("00:00:00").date())[0])
    request = HistoryRequest(symbol, opened, opened + timedelta(minutes=30))
    bars = []
    for number, interval in enumerate(request.expected_intervals()):
        opened_price = 100.0
        close = opened_price + step * (number + 1)
        meta = SourceMetadata(
            instrument_id=symbol, instrument_type=instrument_type, source="SYNTHETIC",
            source_time=interval.start, received_time=interval.end,
            available_time=interval.end, normalized_time=interval.end, session=DAY,
            data_mode="SYNTHETIC_HISTORY", quality="VALID",
        )
        bars.append(Bar(
            record_id=f"{symbol}-{number}", metadata=meta,
            start_time=interval.start, end_time=interval.end, is_final=True,
            open=opened_price, high=max(opened_price, close), low=min(opened_price, close),
            close=close, volume=1000, adjustment_basis="SYNTHETIC_RAW",
            price_convention="USD_PER_SHARE", volume_convention="SHARES",
            certified_no_trade=False,
        ))
    if changed is not None:
        bars = changed(bars)
    conventions = HistoryConventions(
        "START", "REGULAR", "SYNTHETIC_RAW", "USD_PER_SHARE", "SHARES",
        "SYNTHETIC_COMPLETE", "SYNTHETIC_FINAL", "SYNTHETIC_RECEIPT", "M33_FIXTURE",
    )
    return HistoryBatch(request, "SYNTHETIC", conventions, tuple(bars))


def trade(symbol, price, clock, *, instrument_type="ETF", delay=1, **changes):
    happened = at(clock)
    values = dict(
        record_id=f"{symbol}-{clock}-{price}", symbol=symbol,
        instrument_type=instrument_type, session=DAY, trade_time=happened,
        available_time=happened + timedelta(seconds=delay), price=price,
        adjustment_basis="SYNTHETIC_RAW", price_convention="USD_PER_SHARE",
    )
    values.update(changes)
    return EligibleTradeObservation(**values)


def supplied_trades():
    return {
        "stock_open": trade("SYNTH", 100, "06:30:00", instrument_type="EQUITY"),
        "stock_current": trade("SYNTH", 102, "06:49:59", instrument_type="EQUITY"),
        "reference_opens": {
            "SPY": trade("SPY", 500, "06:30:00"),
            "QQQ": trade("QQQ", 400, "06:30:00"),
            "SECTOR": trade("XLK", 200, "06:30:00"),
        },
        "reference_currents": {
            "SPY": trade("SPY", 505, "06:49:58"),
            "QQQ": trade("QQQ", 408, "06:49:59"),
            "SECTOR": trade("XLK", 206, "06:49:57"),
        },
    }


def snapshot(**changes):
    values = dict(
        record_id="m33-rs", evaluated_at=at("06:50:00"), symbol="SYNTH",
        instrument_type="EQUITY", stock_history=history("SYNTH", "EQUITY", 0.1),
        spy_history=history("SPY", "ETF", 0.05),
        qqq_history=history("QQQ", "ETF", 0.08),
        sector_history=history("XLK", "ETF", 0.12), sector_symbol="XLK",
        **supplied_trades(),
    )
    values.update(changes)
    return build_relative_strength_snapshot(**values)


def features(output):
    return {row.name: row for row in output.features}


def test_frozen_rs15_and_all_from_open_references_are_calculated():
    output = snapshot()
    values = features(output)
    assert values["STOCK_RETURN_15M_OPEN_CLOSE_V1"].value == pytest.approx(0.015)
    assert values["SPY_RETURN_15M_OPEN_CLOSE_V1"].value == pytest.approx(0.0075)
    assert values["RS15_SPY_CLOSE_V1"].value == pytest.approx(0.0075)
    assert values["RS15_QQQ_CLOSE_V1"].value == pytest.approx(0.003)
    assert values["RS15_SECTOR_CLOSE_V1"].value == pytest.approx(-0.003)
    assert values["RS15_WARMUP_COMPLETE_V1"].value == 1
    assert values["STOCK_RETURN_OPEN_V1"].value == pytest.approx(0.02)
    assert values["RS_OPEN_SPY_V1"].value == pytest.approx(0.01)
    assert values["RS_OPEN_QQQ_V1"].value == pytest.approx(0.0)
    assert values["RS_OPEN_SECTOR_V1"].value == pytest.approx(-0.01)
    assert output.feature_version == FEATURE_VERSION
    assert output.metadata.data_mode == DATA_MODE


def test_rs15_freezes_the_first_fifteen_bars_after_warmup():
    first = snapshot(evaluated_at=at("06:45:00"), **{
        **supplied_trades(),
        "stock_current": trade("SYNTH", 102, "06:44:59", instrument_type="EQUITY"),
        "reference_currents": {
            "SPY": trade("SPY", 505, "06:44:59"),
            "QQQ": trade("QQQ", 408, "06:44:59"),
            "SECTOR": trade("XLK", 206, "06:44:59"),
        },
    })
    later = snapshot()
    assert features(first)["RS15_SPY_CLOSE_V1"] == features(later)["RS15_SPY_CLOSE_V1"]


def test_rs15_never_shortens_before_fifteen_complete_minutes():
    output = snapshot(evaluated_at=at("06:44:59"), **{
        **supplied_trades(),
        "stock_current": trade("SYNTH", 102, "06:44:58", instrument_type="EQUITY"),
        "reference_currents": {
            "SPY": trade("SPY", 505, "06:44:58"),
            "QQQ": trade("QQQ", 408, "06:44:58"),
            "SECTOR": trade("XLK", 206, "06:44:58"),
        },
    })
    values = features(output)
    assert values["RS15_SPY_CLOSE_V1"].missing_reason == "RS15_WARMUP_INCOMPLETE"
    assert values["RS15_WARMUP_COMPLETE_V1"].value == 0


@pytest.mark.parametrize("change,reason", (
    (lambda bars: bars[:8] + bars[9:], "RS15_WINDOW_MISSING"),
    (lambda bars: [replace(row, is_final=False) if i == 8 else row
                   for i, row in enumerate(bars)], "RS15_WINDOW_PROVISIONAL"),
    (lambda bars: [replace(row, open=None, high=None, low=None, close=None, volume=0,
                               certified_no_trade=True) if i == 8 else row
                   for i, row in enumerate(bars)], "RS15_WINDOW_NO_TRADE"),
))
def test_broken_required_rs15_minutes_stay_missing(change, reason):
    output = snapshot(stock_history=history("SYNTH", "EQUITY", 0.1, changed=change))
    assert features(output)["RS15_SPY_CLOSE_V1"].missing_reason == reason
    assert features(output)["RS15_WARMUP_COMPLETE_V1"].value == 0


def test_selected_revised_final_rs15_bar_stays_unavailable():
    def revised(symbol, instrument_type, step):
        batch = history(symbol, instrument_type, step)
        bars = list(batch.bars)
        bars[8] = replace(
            bars[8], metadata=replace(bars[8].metadata, revision=1))
        return replace(batch, bars=tuple(bars))

    cases = (
        ("stock_history", revised("SYNTH", "EQUITY", 0.1), "STOCK"),
        ("spy_history", revised("SPY", "ETF", 0.05), "SPY"),
        ("qqq_history", revised("QQQ", "ETF", 0.08), "QQQ"),
        ("sector_history", revised("XLK", "ETF", 0.12), "SECTOR"),
    )
    for argument, batch, role in cases:
        values = features(snapshot(**{argument: batch}))
        assert values[f"{role}_RETURN_15M_OPEN_CLOSE_V1"].missing_reason == (
            "RS15_REVISED_INPUT")
        reference = "SPY" if role == "STOCK" else role
        assert values[f"RS15_{reference}_CLOSE_V1"].missing_reason == (
            "RS15_REVISED_INPUT")
        if role == "STOCK":
            assert values["RS15_WARMUP_COMPLETE_V1"].value == 0


def test_wrong_rs15_units_stay_unavailable():
    def change_unit(bars):
        bars[8] = replace(bars[8], price_convention="INDEX_POINTS")
        return bars

    output = snapshot(stock_history=history(
        "SYNTH", "EQUITY", 0.1, changed=change_unit))
    assert features(output)["RS15_SPY_CLOSE_V1"].missing_reason == (
        "RS15_WINDOW_INCOMPATIBLE_CONVENTIONS")


def test_wrong_rs15_instrument_type_stays_unavailable():
    def change_type(bars):
        bars[8] = replace(
            bars[8], metadata=replace(bars[8].metadata, instrument_type="ETF"))
        return bars

    output = snapshot(stock_history=history(
        "SYNTH", "EQUITY", 0.1, changed=change_type))
    assert features(output)["RS15_SPY_CLOSE_V1"].missing_reason == (
        "INCOMPATIBLE_INSTRUMENT_TYPE")


def test_wrong_rs15_session_stays_unavailable():
    def change_session(bars):
        bars[8] = replace(
            bars[8], metadata=replace(bars[8].metadata, session="2026-07-07"))
        return bars

    output = snapshot(stock_history=history(
        "SYNTH", "EQUITY", 0.1, changed=change_session))
    assert features(output)["RS15_SPY_CLOSE_V1"].missing_reason == (
        "RS15_WINDOW_MISSING")


def test_incompatible_rs15_adjustment_bases_stay_unavailable():
    def change_basis(bars):
        return [replace(row, adjustment_basis="OTHER_BASIS") for row in bars]

    output = snapshot(spy_history=HistoryBatch(
        history("SPY", "ETF", 0.05).request,
        "SYNTHETIC",
        replace(history("SPY", "ETF", 0.05).conventions,
                adjustment_basis="OTHER_BASIS"),
        tuple(change_basis(list(history("SPY", "ETF", 0.05).bars))),
    ))
    assert features(output)["RS15_SPY_CLOSE_V1"].missing_reason == (
        "INCOMPATIBLE_ADJUSTMENT_BASIS")


def test_missing_spy_history_does_not_erase_the_stock_return():
    output = snapshot(spy_history=None)
    values = features(output)
    assert values["STOCK_RETURN_15M_OPEN_CLOSE_V1"].value == pytest.approx(0.015)
    assert values["SPY_RETURN_15M_OPEN_CLOSE_V1"].missing_reason == "MISSING_MINUTE_HISTORY"
    assert values["RS15_SPY_CLOSE_V1"].missing_reason == "MISSING_MINUTE_HISTORY"


@pytest.mark.parametrize("role", ("SPY", "QQQ", "SECTOR"))
def test_each_missing_current_reference_blocks_only_its_own_from_open_rs(role):
    current = supplied_trades()["reference_currents"]
    current[role] = None
    output = snapshot(reference_currents=current)
    values = features(output)
    assert values[f"RS_OPEN_{role}_V1"].missing_reason == "MISSING_OPEN_OR_CURRENT_TRADE"
    for other in set(("SPY", "QQQ", "SECTOR")) - {role}:
        assert values[f"RS_OPEN_{other}_V1"].value is not None


def test_unknown_sector_mapping_is_visible_without_hiding_spy_or_qqq():
    output = snapshot(sector_symbol=None)
    values = features(output)
    assert values["RS_OPEN_SECTOR_V1"].missing_reason == "SECTOR_MAPPING_UNAVAILABLE"
    assert values["RS_OPEN_SPY_V1"].value is not None
    assert values["RS_OPEN_QQQ_V1"].value is not None


def test_trade_staleness_and_original_open_capture_delay_are_separate():
    stale = snapshot(stock_current=trade("SYNTH", 102, "06:49:56", instrument_type="EQUITY"))
    assert features(stale)["STOCK_RETURN_OPEN_V1"].missing_reason == "STALE_CURRENT_TRADE"
    late_open = snapshot(stock_open=trade(
        "SYNTH", 100, "06:30:00", instrument_type="EQUITY", delay=4))
    assert features(late_open)["STOCK_RETURN_OPEN_V1"].missing_reason == "STALE_OPENING_TRADE_AT_CAPTURE"
    exact = snapshot(stock_current=trade("SYNTH", 102, "06:49:57", instrument_type="EQUITY"))
    assert features(exact)["STOCK_RETURN_OPEN_V1"].value == pytest.approx(0.02)


def test_incompatible_adjustment_basis_and_future_availability_do_not_pass():
    basis = snapshot(stock_current=trade(
        "SYNTH", 102, "06:49:59", instrument_type="EQUITY", adjustment_basis="OTHER"))
    assert features(basis)["RS_OPEN_SPY_V1"].missing_reason == "INCOMPATIBLE_ADJUSTMENT_BASIS"
    future = snapshot(stock_current=trade(
        "SYNTH", 102, "06:49:59", instrument_type="EQUITY", delay=2))
    assert features(future)["STOCK_RETURN_OPEN_V1"].missing_reason == "TRADE_NOT_YET_AVAILABLE"


def test_inputs_and_output_are_immutable_and_scope_is_explicit():
    output = snapshot()
    assert output.schema_version == 1
    assert output.record_id == "m33-rs"
    assert output.metadata.instrument_id == "SYNTH"
    assert output.evaluated_at == as_utc(at("06:50:00"))
    assert output.input_record_ids == tuple(sorted({
        record_id for row in output.features for record_id in row.input_record_ids
    }))
    restored = FeatureSnapshot.from_json(output.to_json())
    assert restored.to_json() == output.to_json()
    with pytest.raises(FrozenInstanceError):
        output.features = ()
    with pytest.raises(RecordError, match="instrument type"):
        snapshot(instrument_type="OPTION")
    with pytest.raises(RecordError, match="sector symbol"):
        snapshot(sector_symbol="SPY")
    with pytest.raises(RecordError, match="role"):
        snapshot(reference_opens={"OTHER": None})


def test_relative_strength_recording_end_to_end():
    outputs = [snapshot()]
    revised = history("SYNTH", "EQUITY", 0.1)
    revised_bars = list(revised.bars)
    revised_bars[8] = replace(
        revised_bars[8],
        metadata=replace(revised_bars[8].metadata, revision=1),
    )
    outputs.append(snapshot(stock_history=replace(revised, bars=tuple(revised_bars))))
    outputs.append(snapshot(sector_symbol=None))
    currents = supplied_trades()["reference_currents"]
    currents["QQQ"] = None
    outputs.append(snapshot(reference_currents=currents))
    outputs.append(snapshot(spy_history=None))
    payload = {
        "evidence": "SYNTHETIC_SOFTWARE_PROOF_ONLY",
        "feature_version": FEATURE_VERSION,
        "snapshots": [],
    }
    for output in outputs:
        restored = FeatureSnapshot.from_json(output.to_json())
        raw = restored.to_json().encode()
        payload["snapshots"].append({
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "features": [{"name": row.name, "value": row.value,
                          "missing_reason": row.missing_reason,
                          "input_count": len(row.input_record_ids)} for row in output.features],
        })
    rendered = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    assert len(rendered.encode()) < 100_000
    Path("/tmp/m33-relative-strength-proof.json").write_text(rendered)
