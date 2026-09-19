"""M9.1M: `FIRST_PULLBACK_VWAP`'s first bar-native input, from real, `PROVISIONAL`-usable bars.

Every bar below is a synthetic fixture. Passing a case proves only the offline
contract described in `impulse_pullback_research_adapter.py`: it establishes no
provider coverage, no adopted `FIRST_PULLBACK_VWAP` rule and no permission to
act.
"""

from dataclasses import replace
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
from consensus_engine.impulse_pullback import DATA_MODE, FEATURE_VERSION, PullbackPolicy
from consensus_engine.impulse_pullback_research_adapter import (
    RESEARCH_IMPULSE_PULLBACK_DATA_MODE, RESEARCH_IMPULSE_PULLBACK_FEATURE_VERSION,
    build_impulse_pullback_snapshot_from_research,
)
from consensus_engine.trade_alerts_models import Bar, FeatureSnapshot, RecordError, SourceMetadata
from consensus_engine.utils.time_context import as_utc, session_bounds


PACIFIC = ZoneInfo("America/Los_Angeles")
DAY = "2026-07-06"
# One synthetic session: five rising minutes, a quieter drift back, then a new high.
PLAN = (
    (100.00, 99.00, 900), (101.00, 99.50, 1000), (102.00, 100.50, 1200),
    (103.00, 101.50, 1400), (104.00, 103.00, 1500),
    (103.50, 102.50, 900), (103.00, 102.00, 700), (102.60, 102.00, 600),
    (103.20, 102.40, 800), (104.50, 103.00, 1100),
)
LONG = PullbackPolicy(
    version="M91M_TEST_LEGS_V1", definition_reference="M91M_SYNTHETIC_LEGS_ONLY",
    direction="LONG", min_pullback_bars=1, measure_from_close=False,
)


def at(clock, day=DAY):
    return datetime.fromisoformat(day + "T" + clock).replace(tzinfo=PACIFIC)


def conventions(**changes):
    values = dict(
        timestamp="START", session="REGULAR", adjustment_basis="SYNTHETIC_RAW",
        price="USD_PER_SHARE", volume="SHARES", coverage_basis="SYNTHETIC_COMPLETE",
        finality="SYNTHETIC_FINAL", publication="SYNTHETIC_RECEIPT",
        evidence_reference="M91M_SYNTHETIC_ONLY",
    )
    values.update(changes)
    return HistoryConventions(**values)


def make_bar(number, interval, prices, *, no_trade=False, revision=0, quality="VALID",
             is_final=True, instrument_type="EQUITY", data_mode="SYNTHETIC_HISTORY",
             symbol="SYNTH"):
    high, low, volume = prices
    middle = round((high + low) / 2, 2)
    meta = SourceMetadata(
        instrument_id=symbol, instrument_type=instrument_type, source="SYNTHETIC",
        source_time=interval.start, received_time=interval.end, available_time=interval.end,
        normalized_time=interval.end, session=interval.session, revision=revision,
        data_mode=data_mode, quality=quality,
    )
    empty = no_trade or quality == "UNAVAILABLE"
    return Bar(
        record_id=f"legs-{number}-r{revision}", metadata=meta,
        start_time=interval.start, end_time=interval.end, is_final=is_final,
        open=None if empty else middle, high=None if empty else high,
        low=None if empty else low, close=None if empty else middle,
        volume=(0 if no_trade else None) if empty else volume,
        adjustment_basis="SYNTHETIC_RAW", price_convention="USD_PER_SHARE",
        volume_convention="SHARES", certified_no_trade=no_trade,
    )


def history(day=DAY, *, plan=PLAN, changed=None, supplied_conventions=None, is_final=True,
            **request_changes):
    opened = as_utc(session_bounds(datetime.fromisoformat(day).date())[0])
    values = dict(symbol="SYNTH", start=opened, end=opened + timedelta(minutes=len(plan)))
    values.update(request_changes)
    request = HistoryRequest(**values)
    bars = [make_bar(number, interval, plan[number], symbol=request.symbol, is_final=is_final)
            for number, interval in enumerate(request.expected_intervals())]
    if changed:
        bars = changed(bars)
    return HistoryBatch(request, "SYNTHETIC", supplied_conventions or conventions(), tuple(bars))


def result(supplied=None, *, evaluated=None, started=None, frozen=None, policy=LONG,
           atr_1m=0.10, vwap=101.50, day=DAY, **changes):
    if supplied is None and "minute_history" not in changes:
        supplied = history(day)
    values = dict(
        record_id="m91m-impulse-pullback", evaluated_at=evaluated or at("06:39:00", day),
        symbol="SYNTH", instrument_type="EQUITY", minute_history=supplied, policy=policy,
        impulse_started_at=started or at("06:30:00", day),
        impulse_frozen_at=frozen or at("06:35:00", day), atr_1m=atr_1m, vwap=vwap,
    )
    values.update(changes)
    return build_impulse_pullback_snapshot_from_research(**values)


def values(output):
    return {item.name: item for item in output.snapshot.features}


def numbers(output, *names):
    return [values(output)[name].value for name in names]


def reasons(output, *names):
    return [values(output)[name].missing_reason for name in names]


def test_provisional_bars_are_usable_here_unlike_the_live_function():
    output = result(history(is_final=False))
    assert numbers(output, "IMPULSE_ORIGIN_V1", "IMPULSE_EXTREME_V1", "IMPULSE_DISTANCE_V1",
                   "IMPULSE_BAR_COUNT_V1", "IMPULSE_VOLUME_V1") == [99.00, 104.00, 5.00, 5, 6000]
    assert numbers(output, "PULLBACK_EXTREME_V1", "PULLBACK_RETRACEMENT_V1",
                   "PULLBACK_VOLUME_RATIO_V1", "PULLBACK_COMPLETE_V1") == [102.00, 0.4, 0.5, 1]
    assert output.snapshot.feature_version == RESEARCH_IMPULSE_PULLBACK_FEATURE_VERSION
    assert output.snapshot.metadata.data_mode == RESEARCH_IMPULSE_PULLBACK_DATA_MODE
    assert output.snapshot.feature_version != FEATURE_VERSION
    assert output.snapshot.metadata.data_mode != DATA_MODE


def test_labels_name_d110_and_the_provisional_count():
    output = result(history(is_final=False))
    assert output.label["decision"] == "D-110"
    assert output.label["finality"] == "RESEARCH_PROVISIONAL_PERMITTED"
    assert output.label["provisional_intervals"] == 9
    assert output.label["final_intervals"] == 0


def test_already_final_bars_measure_the_same_leg_as_provisional_ones():
    finalized = result()
    provisional = result(history(is_final=False))
    assert numbers(finalized, "IMPULSE_DISTANCE_V1", "PULLBACK_RETRACEMENT_V1") == numbers(
        provisional, "IMPULSE_DISTANCE_V1", "PULLBACK_RETRACEMENT_V1")
    assert finalized.label["final_intervals"] == 9
    assert finalized.label["provisional_intervals"] == 0


def test_a_later_high_never_moves_the_frozen_impulse():
    later = result(history(is_final=False), evaluated=at("06:40:00"))
    assert numbers(later, "IMPULSE_EXTREME_V1") == [104.00]
    assert numbers(later, "PULLBACK_BAR_COUNT_V1", "REVERSAL_BAR_HIGH_V1") == [5, 104.50]


def test_an_unready_untraded_or_contradicted_impulse_minute_is_still_refused():
    def quiet(bars):
        return [replace(bar, open=None, high=None, low=None, close=None, volume=0,
                        certified_no_trade=True, is_final=True) if index == 2 else bar
                for index, bar in enumerate(bars)]

    output = result(history(changed=quiet, is_final=False))
    assert reasons(output, "IMPULSE_ORIGIN_V1") == ["NO_TRADED_IMPULSE_INTERVAL"]

    def foreign(bars):
        return [replace(bar, metadata=replace(bar.metadata, instrument_type="ETF"))
                if index == 4 else bar for index, bar in enumerate(bars)]

    assert reasons(result(history(changed=foreign, is_final=False)), "IMPULSE_ORIGIN_V1") == [
        "INCOMPATIBLE_INSTRUMENT_TYPE"]

    def missing_bar(bars):
        return [bar for index, bar in enumerate(bars) if index != 3]

    assert reasons(result(history(changed=missing_bar, is_final=False)), "IMPULSE_ORIGIN_V1") == [
        "IMPULSE_MISSING"]


def test_a_missing_pullback_interval_is_still_incomplete_not_shortened():
    def drop(bars):
        return [bar for index, bar in enumerate(bars) if index != 6]

    output = result(history(changed=drop, is_final=False))
    assert reasons(output, "PULLBACK_EXTREME_V1") == ["PULLBACK_MISSING"]


def test_a_quiet_no_trade_pullback_minute_is_still_refused_by_name():
    def quiet(bars):
        return [replace(bar, open=None, high=None, low=None, close=None, volume=0,
                        certified_no_trade=True, is_final=True) if index == 7 else bar
                for index, bar in enumerate(bars)]

    output = result(history(changed=quiet, is_final=False))
    assert reasons(output, "PULLBACK_EXTREME_V1") == ["NO_TRADED_PULLBACK_INTERVAL"]


def test_incompatible_or_absent_history_is_still_named_for_every_feature():
    cases = {
        "MISSING_MINUTE_HISTORY": None,
        "INCOMPATIBLE_SYMBOL": history(symbol="OTHER"),
        "UNKNOWN_SOURCE_OR_VENUE_BASIS": history(
            supplied_conventions=conventions(coverage_basis="UNKNOWN")),
        "INCOMPATIBLE_PRICE_UNIT": history(
            supplied_conventions=conventions(price="USD_PER_CONTRACT")),
        "INCOMPATIBLE_VOLUME_UNIT": history(
            supplied_conventions=conventions(volume="CONTRACTS")),
    }
    for reason, supplied in cases.items():
        output = result(minute_history=supplied)
        assert reasons(output, "IMPULSE_ORIGIN_V1", "PULLBACK_EXTREME_V1",
                       "PULLBACK_RETRACEMENT_V1") == [reason] * 3
        assert numbers(output, "IMPULSE_COMPLETE_V1", "PULLBACK_COMPLETE_V1") == [0, 0]
        assert output.snapshot.input_record_ids == ()
        assert output.label is None


def test_daily_history_and_a_closed_day_are_refused_by_name():
    opened = as_utc(session_bounds(datetime.fromisoformat(DAY).date())[0])
    closed = as_utc(session_bounds(datetime.fromisoformat(DAY).date())[1])
    daily = HistoryBatch(HistoryRequest("SYNTH", opened, closed, "1d"), "SYNTHETIC",
                         conventions(), ())
    assert reasons(result(daily), "IMPULSE_ORIGIN_V1") == ["INCOMPATIBLE_HISTORY_INTERVAL"]
    holiday = result(None, minute_history=None, day="2026-07-03",
                     evaluated=at("06:39:00", "2026-07-03"),
                     started=at("06:30:00", "2026-07-03"),
                     frozen=at("06:35:00", "2026-07-03"))
    assert reasons(holiday, "IMPULSE_ORIGIN_V1", "PULLBACK_EXTREME_V1") == ["NO_REGULAR_SESSION"] * 2
    assert holiday.label is None


def test_the_symbol_and_instrument_type_are_still_required_and_explicit():
    with pytest.raises(RecordError, match="symbol is required"):
        result(symbol="")
    with pytest.raises(RecordError, match="instrument type"):
        result(instrument_type="OPTION")
    with pytest.raises(RecordError, match="PullbackPolicy"):
        result(policy="M91M")


def proof_summary(output):
    raw = output.snapshot.to_json().encode()
    return {
        "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
        "evaluated_at_pacific": output.snapshot.evaluated_at.astimezone(PACIFIC).isoformat(),
        "label": output.label,
        "features": [
            {"name": item.name, "value": item.value, "missing_reason": item.missing_reason,
             "input_count": len(item.input_record_ids)} for item in output.snapshot.features
        ],
    }


def test_impulse_pullback_research_recording_end_to_end():
    provisional = history(is_final=False)
    outputs = [result(provisional, evaluated=at(clock)) for clock in (
        "06:35:59", "06:36:00", "06:39:00", "06:40:00"
    )]
    assert [numbers(item, "PULLBACK_BAR_COUNT_V1", "PULLBACK_EXTREME_V1") for item in outputs] == [
        [None, None], [1, 102.50], [4, 102.00], [5, 102.00]]
    frozen = outputs[2].snapshot.to_json()
    final = history(is_final=True)
    outputs.append(result(final, evaluated=at("06:39:00")))
    assert outputs[2].snapshot.to_json() == frozen
    assert outputs[-1].label["final_intervals"] == 9
    assert all(
        FeatureSnapshot.from_json(item.snapshot.to_json()) == item.snapshot for item in outputs)
    payload = {
        "evidence": "SYNTHETIC_SOFTWARE_PROOF_ONLY",
        "feature_version": RESEARCH_IMPULSE_PULLBACK_FEATURE_VERSION,
        "data_mode": RESEARCH_IMPULSE_PULLBACK_DATA_MODE,
        "snapshots": [proof_summary(item) for item in outputs],
    }
    rendered = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    assert len(rendered.encode()) < 100_000
    Path("/tmp/m91m-impulse-pullback-research-proof.json").write_text(rendered)
