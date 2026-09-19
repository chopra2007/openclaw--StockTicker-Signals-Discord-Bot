"""M9.1L: the M8.1 handoff's own opening-range `FeatureSnapshot` from real bars.

Every bar below is a synthetic fixture. Passing a case proves only the offline
contract described in `or_failure_handoff_research_adapter.py`: it establishes
no provider coverage, no adopted `OR_FAILURE_REV` rule and no permission to
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
from consensus_engine.opening_range_features import FEATURE_VERSION as OPENING_RANGE_VERSION
from consensus_engine.or_failure_handoff import (
    RANGE_GATE, HandoffRequest, evaluate_or_failure_handoff,
)
from consensus_engine.or_failure_handoff_research_adapter import (
    RESEARCH_OR_FAILURE_HANDOFF_DATA_MODE,
    build_or_failure_handoff_opening_range_from_research,
)
from consensus_engine.or_failure_rev_research_adapter import (
    build_or_failure_rev_bar_inputs_from_research,
    build_or_failure_rev_extreme_inputs_from_research,
)
from consensus_engine.strategy_interface import StrategyState
from consensus_engine.trade_alerts_models import Bar, FeatureSnapshot, RecordError, SourceMetadata
from consensus_engine.utils.time_context import as_utc, session_bounds

from test_or_failure_handoff import (
    ENDED_AT, attempt as handoff_attempt, extreme as handoff_extreme,
    policy as handoff_policy, reacceptance as handoff_reacceptance,
)
from test_orb5_trigger import DAY as TRIGGER_DAY, RANGE as TRIGGER_RANGE


PACIFIC = ZoneInfo("America/Los_Angeles")
DAY = "2026-07-06"
NAMES = (
    "OPENING_RANGE_HIGH_5M_V1",
    "OPENING_RANGE_LOW_5M_V1",
    "OPENING_RANGE_MID_5M_V1",
    "OPENING_RANGE_WIDTH_5M_V1",
    "OPENING_RANGE_COMPLETE_5M_V1",
)


def at(clock, day=DAY):
    return datetime.fromisoformat(day + "T" + clock).replace(tzinfo=PACIFIC)


def opened_at(day=DAY):
    return as_utc(session_bounds(datetime.fromisoformat(day).date())[0])


def conventions(**changes):
    values = dict(
        timestamp="START", session="REGULAR", adjustment_basis="SYNTHETIC_RAW",
        price="USD_PER_SHARE", volume="SHARES", coverage_basis="SYNTHETIC_COMPLETE",
        finality="SYNTHETIC_FINAL", publication="SYNTHETIC_RECEIPT",
        evidence_reference="M91L_SYNTHETIC_ONLY",
    )
    values.update(changes)
    return HistoryConventions(**values)


def make_bar(number, interval, *, high=None, low=None, no_trade=False, available=None,
             revision=0, instrument_type="EQUITY", is_final=True, symbol="SYNTH"):
    available = available or interval.end
    record_id = f"m91l-{number}-r{revision}"
    meta = SourceMetadata(
        instrument_id=symbol, instrument_type=instrument_type, source="SYNTHETIC",
        source_time=interval.start, received_time=available, available_time=available,
        normalized_time=available, session=interval.session, revision=revision,
        data_mode="SYNTHETIC_HISTORY", quality="VALID",
    )
    high = 101 + number if high is None else high
    low = 99 - number if low is None else low
    return Bar(
        record_id=record_id, metadata=meta, start_time=interval.start, end_time=interval.end,
        is_final=is_final, open=None if no_trade else 100, high=None if no_trade else high,
        low=None if no_trade else low, close=None if no_trade else 100,
        volume=0 if no_trade else 100 + number, adjustment_basis="SYNTHETIC_RAW",
        price_convention="USD_PER_SHARE", volume_convention="SHARES",
        certified_no_trade=no_trade,
    )


def history(day=DAY, *, changed=None, broad=False, is_final=True, symbol="SYNTH"):
    opened, closed = map(as_utc, session_bounds(datetime.fromisoformat(day).date()))
    request = HistoryRequest(symbol, opened, closed if broad else opened + timedelta(minutes=5))
    intervals = request.expected_intervals()
    if broad:
        intervals = intervals[:5]
    bars = [make_bar(number, interval, is_final=is_final, symbol=symbol)
            for number, interval in enumerate(intervals)]
    if changed:
        bars = changed(bars)
    return HistoryBatch(request, "SYNTHETIC", conventions(), tuple(bars))


def result(supplied=None, *, evaluated=None, day=DAY, **changes):
    minute_history = changes.pop(
        "minute_history", history(day) if supplied is None and session_bounds(
            datetime.fromisoformat(day).date()) is not None else supplied
    )
    values = dict(
        record_id="m91l-opening-range", evaluated_at=evaluated or at("06:35:00", day),
        symbol="SYNTH", instrument_type="EQUITY", minute_history=minute_history,
    )
    values.update(changes)
    return build_or_failure_handoff_opening_range_from_research(**values)


def values(output):
    return {value.name: value for value in output.features}


def range_values(output):
    found = values(output)
    return [found[name].value for name in NAMES]


def test_final_bars_reach_the_live_feature_version_exactly():
    output = result().snapshot
    assert range_values(output) == [105, 95, 100, 10, 1]
    assert output.feature_version == OPENING_RANGE_VERSION
    assert output.metadata.data_mode == RESEARCH_OR_FAILURE_HANDOFF_DATA_MODE
    assert FeatureSnapshot.from_json(output.to_json()) == output


def test_provisional_bars_complete_here_unlike_the_live_five_minute_builder():
    supplied = history(is_final=False)
    output = result(supplied).snapshot
    assert range_values(output) == [105, 95, 100, 10, 1]
    label = result(supplied).label
    assert label["finality"] == "RESEARCH_PROVISIONAL_PERMITTED"
    assert label["decision"] == "D-110"
    assert label["provisional_intervals"] == 5
    assert label["final_intervals"] == 0


def test_already_final_bars_are_labelled_final_not_provisional():
    label = result(history(is_final=True)).label
    assert label["final_intervals"] == 5
    assert label["provisional_intervals"] == 0


def test_range_cannot_complete_before_fifth_interval_ends():
    output = result(evaluated=at("06:34:59")).snapshot
    found = values(output)
    assert found[NAMES[-1]].value == 0
    assert found[NAMES[0]].missing_reason == "OPENING_RANGE_NOT_ENDED"


def test_certified_no_trade_minute_adds_no_invented_extreme():
    supplied = history(changed=lambda bars: [
        replace(bars[0], open=None, high=None, low=None, close=None, volume=0,
                certified_no_trade=True), *bars[1:]
    ])
    assert range_values(result(supplied).snapshot) == [105, 95, 100, 10, 1]


def test_all_certified_no_trade_minutes_are_not_a_range():
    supplied = history(changed=lambda bars: [
        replace(bar, open=None, high=None, low=None, close=None, volume=0,
                certified_no_trade=True) for bar in bars
    ])
    output = result(supplied).snapshot
    assert range_values(output) == [None, None, None, None, 0]
    assert values(output)[NAMES[0]].missing_reason == "NO_TRADED_OPENING_RANGE_INTERVAL"


def test_conflicting_and_overlapping_records_block():
    original = history()
    conflict = replace(original.bars[0], record_id="conflict", high=999)
    combined = replace(original, bars=(*original.bars, conflict))
    output = result(combined).snapshot
    assert values(output)[NAMES[0]].missing_reason == "OPENING_RANGE_CONFLICT"


def test_missing_minute_history_and_wrong_symbol_stay_incomplete():
    output = result(None, minute_history=None).snapshot
    assert values(output)[NAMES[0]].missing_reason == "MISSING_MINUTE_HISTORY"
    assert result(None, minute_history=None).label is None
    output = result(symbol="OTHER").snapshot
    assert values(output)[NAMES[0]].missing_reason == "INCOMPATIBLE_SYMBOL"


def test_wrong_instrument_type_on_a_selected_bar_is_refused():
    original = history()
    wrong_type = replace(original.bars[0], metadata=replace(
        original.bars[0].metadata, instrument_type="ETF"))
    combined = replace(original, bars=(wrong_type, *original.bars[1:]))
    output = result(combined).snapshot
    assert values(output)[NAMES[0]].missing_reason == "INCOMPATIBLE_INSTRUMENT_TYPE"


def test_holiday_has_no_opening_range():
    output = result(None, day="2026-07-04", minute_history=None).snapshot
    assert values(output)[NAMES[0]].missing_reason == "NO_REGULAR_SESSION"
    assert result(None, day="2026-07-04", minute_history=None).label is None


def test_symbol_and_instrument_type_are_still_required_and_explicit():
    with pytest.raises(RecordError, match="symbol is required"):
        result(symbol="")
    with pytest.raises(RecordError, match="instrument type"):
        result(instrument_type="OPTION")


def test_the_produced_snapshot_binds_the_real_m81_range_gate_end_to_end():
    """A research-built snapshot drives the same `RANGE_GATE` PASS a live one would.

    Reuses the M8.1 fixture helpers unchanged (`attempt`/`policy`/`extreme`/
    `reacceptance` from `test_or_failure_handoff.py`) and only swaps their
    live `opening_range()` builder for this module's research one, forcing the
    five opening-range bars `PROVISIONAL` -- which the live builder could never
    admit -- to prove the swap changes nothing else about the outcome.
    """
    direction = "LONG"
    high, low = TRIGGER_RANGE[direction]

    def fixed(bars):
        return [replace(bar, high=high, low=low, open=low, close=high, is_final=False)
                for bar in bars]

    minute_history = history(TRIGGER_DAY, changed=fixed)
    built = result(minute_history, day=TRIGGER_DAY, evaluated=at("06:35:00", TRIGGER_DAY))
    assert built.label["finality"] == "RESEARCH_PROVISIONAL_PERMITTED"
    assert built.label["provisional_intervals"] == 5
    request = HandoffRequest(
        symbol="SYNTH", instrument_type="EQUITY", attempt=handoff_attempt(direction, at=ENDED_AT),
        policy=handoff_policy(), evaluated_at=ENDED_AT, opening_range=built.snapshot,
        breakout_extreme=handoff_extreme(direction),
        minute_close=handoff_reacceptance(direction, at=ENDED_AT), attempt_reached_alert=False,
    )
    assessment = evaluate_or_failure_handoff(request)
    assert assessment.gate(RANGE_GATE).status == "PASS"
    assert assessment.state == StrategyState("SETUP_FORMING", "FAILURE_FORMING")


def test_the_same_selected_bar_feeds_the_handoffs_extreme_and_close_reads():
    supplied = history(is_final=False)
    evaluated = at("06:34:00")
    snapshot = result(supplied, evaluated=evaluated).snapshot
    assert values(snapshot)[NAMES[-1]].value == 0  # range not yet closed at minute 4
    bar_inputs = build_or_failure_rev_bar_inputs_from_research(
        record_id_prefix="m91l-close", evaluated_at=evaluated, symbol="SYNTH",
        instrument_type="EQUITY", minute_history=supplied,
    )
    extreme_inputs = build_or_failure_rev_extreme_inputs_from_research(
        record_id_prefix="m91l-extreme", crossed_at=opened_at(), evaluated_at=evaluated,
        symbol="SYNTH", instrument_type="EQUITY", break_direction="LONG",
        minute_history=supplied,
    )
    assert bar_inputs.confirmation_close.close == 100
    assert extreme_inputs.breakout_extreme.price is not None
    assert bar_inputs.label["finality"] == "RESEARCH_PROVISIONAL_PERMITTED"
    assert extreme_inputs.label["finality"] == "RESEARCH_PROVISIONAL_PERMITTED"


def proof_summary(output):
    raw = output.snapshot.to_json().encode()
    return {
        "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
        "evaluated_at_pacific": output.snapshot.evaluated_at.astimezone(PACIFIC).isoformat(),
        "label": output.label,
        "features": [
            {"name": value.name, "value": value.value, "missing_reason": value.missing_reason,
             "input_count": len(value.input_record_ids)} for value in output.snapshot.features
        ],
    }


def test_bar_coverage_handoff_opening_range_recording_end_to_end():
    provisional = history(broad=True, is_final=False)
    outputs = [result(provisional, evaluated=at(clock)) for clock in (
        "06:34:59", "06:35:00", "06:35:01"
    )]
    assert [range_values(item.snapshot) for item in outputs] == [
        [None, None, None, None, 0], [105, 95, 100, 10, 1], [105, 95, 100, 10, 1]
    ]
    frozen = outputs[1].snapshot.to_json()
    final = history(broad=True, is_final=True)
    outputs.append(result(final, evaluated=at("06:35:00")))
    assert outputs[1].snapshot.to_json() == frozen
    assert outputs[-1].label["final_intervals"] == 5
    all_empty = replace(provisional, bars=tuple(
        replace(bar, open=None, high=None, low=None, close=None, volume=0,
                certified_no_trade=True, is_final=True) for bar in provisional.bars
    ))
    outputs.append(result(all_empty))
    assert values(outputs[-1].snapshot)[NAMES[0]].missing_reason == "NO_TRADED_OPENING_RANGE_INTERVAL"
    assert all(
        FeatureSnapshot.from_json(item.snapshot.to_json()) == item.snapshot for item in outputs
    )
    payload = {
        "evidence": "SYNTHETIC_SOFTWARE_PROOF_ONLY", "feature_version": OPENING_RANGE_VERSION,
        "data_mode": RESEARCH_OR_FAILURE_HANDOFF_DATA_MODE,
        "snapshots": [proof_summary(item) for item in outputs],
    }
    rendered = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    assert len(rendered.encode()) < 100_000
    Path("/tmp/m91l-or-failure-handoff-opening-range-proof.json").write_text(rendered)
