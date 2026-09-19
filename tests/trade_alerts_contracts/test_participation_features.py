"""M3.2 supplied-Bar participation checks; protected launcher only."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, time, timedelta
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from consensus_engine.participation_features import FEATURE_VERSION, build_participation_snapshot
from consensus_engine.trade_alerts_models import Bar, FeatureSnapshot, RecordError, SourceMetadata
from consensus_engine.utils.time_context import as_utc, premarket_bounds, session_bounds, session_dates


PACIFIC = ZoneInfo("America/Los_Angeles")
NAMES = {"opening": "RVOL_OPEN5_MEAN20_V1", "premarket": "PM_RVOL_MEAN20_V1",
         "daily": "DOLLAR_VOLUME_CLOSE_PROXY20_V1"}
EXPECTED = {"opening": 2.0, "premarket": 2.75, "daily": 50_000_000.0}


class _FixtureHistoryRequest(HistoryRequest):
    """Reuse only calendar slots for identical frozen test requests."""

    @lru_cache(maxsize=64)
    def expected_intervals(self):
        return super().expected_intervals()


def at(clock, day="2026-07-06"):
    return datetime.fromisoformat(day + "T" + clock).replace(tzinfo=PACIFIC)


def make_bar(record_id, start, end, volume, *, no_trade=False, available=None):
    available = available or end
    meta = SourceMetadata(
        instrument_id="SYNTH", instrument_type="EQUITY", source="SYNTHETIC",
        source_time=start, received_time=available, available_time=available,
        normalized_time=available, session=start.astimezone(PACIFIC).date().isoformat(),
        data_mode="SYNTHETIC_SHARES", quality="VALID",
    )
    return Bar(record_id=record_id, metadata=meta, start_time=start, end_time=end,
               is_final=True, open=None if no_trade else 100,
               high=None if no_trade else 101, low=None if no_trade else 99,
               close=None if no_trade else 100, volume=0 if no_trade else volume,
               adjustment_basis="SYNTHETIC_SAME_ASOF", price_convention="USD_PER_SHARE",
               volume_convention="SHARES", certified_no_trade=no_trade)


@lru_cache(maxsize=12)
def history(kind, day="2026-07-06"):
    current = at("06:35:00", day).date()
    prior = session_dates(current - timedelta(days=60), current - timedelta(days=1))[-20:]
    days = prior if kind == "daily" else [*prior, current]
    bars = []
    first = last = None
    for index, date in enumerate(days):
        opened, closed = map(as_utc, session_bounds(date))
        if kind == "premarket":
            start, end = premarket_bounds(date, time(1))
            total = 1_100_000 if index == 20 else [300_000, 350_000, 400_000, 450_000, 500_000][index % 5]
        elif kind == "opening":
            start, end = opened, opened + timedelta(minutes=5)
            total = 100_000 if index == 20 else [40_000, 45_000, 50_000, 55_000, 60_000][index % 5]
        else:
            start, end = opened, closed
            total = [400_000, 450_000, 500_000, 550_000, 600_000][index % 5]
        first = first or start
        last = end
        cursor = start
        slot = 0
        while cursor < end:
            stop = end if kind == "daily" else cursor + timedelta(minutes=1)
            bars.append(make_bar(f"{kind}-{index}-{slot}", cursor, stop, total,
                                 no_trade=slot > 0))
            cursor = stop
            slot += 1
    scope = "PREMARKET" if kind == "premarket" else "REGULAR"
    request = _FixtureHistoryRequest("SYNTH", first, last, interval="1d" if kind == "daily" else "1m",
                             session_scope=scope, premarket_start=time(1) if kind == "premarket" else None)
    conventions = HistoryConventions(
        timestamp="START", session=scope, adjustment_basis="SYNTHETIC_SAME_ASOF",
        price="USD_PER_SHARE", volume="SHARES", coverage_basis="SYNTHETIC_COMPLETE_VENUES",
        finality="SYNTHETIC_FINAL", publication="SYNTHETIC_ORIGINAL_AVAILABILITY",
        evidence_reference="M32_SYNTHETIC_ONLY",
    )
    return HistoryBatch(request, "SYNTHETIC", conventions, tuple(bars))


def snapshot(kind=None, supplied=None, *, evaluated=at("06:35:00"), **overrides):
    inputs = {key + "_history": None for key in NAMES}
    if kind is not None:
        inputs[kind + "_history"] = supplied if supplied is not None else history(kind)
    inputs.update(overrides)
    return build_participation_snapshot(record_id="participation", evaluated_at=evaluated,
                                        symbol="SYNTH", instrument_type="EQUITY", **inputs)


def feature(output, kind):
    return next(value for value in output.features if value.name == NAMES[kind])


def revised(bar, *, available=at("06:36:00"), **changes):
    meta = replace(bar.metadata, revision=bar.metadata.revision + 1,
                   received_time=available, available_time=available, normalized_time=available)
    return replace(bar, record_id=bar.record_id + "-revision", metadata=meta, **changes)


@pytest.mark.parametrize("kind", NAMES)
def test_hand_computed_twenty_session_participation(kind):
    output = snapshot(kind)
    value = feature(output, kind)
    assert value.value == EXPECTED[kind]
    assert value.missing_reason is None
    assert value.unit == ("USD" if kind == "daily" else "RATIO")
    assert len(value.input_record_ids) == {"opening": 105, "premarket": 6930, "daily": 20}[kind]
    assert output.feature_version == FEATURE_VERSION
    assert FeatureSnapshot.from_json(output.to_json()) == output
    assert all(feature(output, other).value is None for other in NAMES if other != kind)


@pytest.mark.parametrize("kind", NAMES)
def test_missing_required_reference_cannot_borrow_an_older_session(kind):
    original = history(kind)
    first_day = original.request.start.astimezone(PACIFIC).date()
    older_day = session_dates(first_day - timedelta(days=10), first_day - timedelta(days=1))[-1]
    opened, closed = map(as_utc, session_bounds(older_day))
    if kind == "premarket":
        opened, closed = premarket_bounds(older_day, time(1))
    if kind == "opening":
        closed = opened + timedelta(minutes=1)
    older = make_bar("older-substitute", opened, closed, 999_999_999)
    # Every required reference still means the latest 20 calendar sessions.
    broken = replace(original, request=replace(original.request, start=opened),
                     bars=(older, *original.bars[1:]))
    value = feature(snapshot(kind, broken), kind)
    assert value.value is None
    assert value.missing_reason == "REFERENCE_WINDOW_MISSING"
    assert "older-substitute" not in value.input_record_ids


@pytest.mark.parametrize("kind", NAMES)
def test_truncated_history_does_not_shorten_the_required_window(kind):
    original = history(kind)
    # Exclude exactly the first required slot (a whole session for daily data).
    broken = replace(original, request=replace(original.request, start=original.bars[0].end_time))
    value = feature(snapshot(kind, broken), kind)
    assert value.value is None
    assert value.missing_reason == "REFERENCE_WINDOW_NOT_REQUESTED"


@pytest.mark.parametrize("kind,clock", [("opening", "06:35:00"), ("premarket", "06:30:00")])
def test_fixed_window_waits_for_end_and_late_final_availability(kind, clock):
    original = history(kind)
    end = at(clock)
    final = original.bars[-1]
    late = replace(final, metadata=replace(final.metadata, received_time=end + timedelta(seconds=2),
                   available_time=end + timedelta(seconds=2), normalized_time=end + timedelta(seconds=2)))
    supplied = replace(original, bars=(*original.bars[:-1], late))
    outputs = [snapshot(kind, supplied, evaluated=end + timedelta(seconds=seconds)) for seconds in (-1, 0, 1, 2)]
    assert [feature(output, kind).value for output in outputs] == [None, None, None, EXPECTED[kind]]
    assert feature(outputs[0], kind).missing_reason == "CURRENT_WINDOW_NOT_ENDED"
    assert feature(outputs[1], kind).missing_reason == "CURRENT_WINDOW_MISSING"


@pytest.mark.parametrize("kind", NAMES)
def test_duplicates_order_and_later_revision_do_not_change_earlier_snapshot(kind):
    original = history(kind)
    before = snapshot(kind, original)
    duplicate = replace(original.bars[0], record_id="repeat",
                        metadata=replace(original.bars[0].metadata, received_time=at("06:34:59"),
                                         available_time=at("06:34:59"), normalized_time=at("06:34:59")))
    correction = revised(original.bars[0], volume=80_000 if kind == "opening" else 1_000_000)
    supplied = replace(original, bars=(correction, duplicate, *reversed(original.bars)))
    assert snapshot(kind, supplied).to_json() == before.to_json()
    after = snapshot(kind, supplied, evaluated=at("06:36:00"))
    assert correction.record_id in feature(after, kind).input_record_ids
    assert original.bars[0].record_id not in feature(after, kind).input_record_ids
    assert feature(before, kind).value == EXPECTED[kind]
    assert FeatureSnapshot.from_json(before.to_json()) == before


@pytest.mark.parametrize("kind", NAMES)
def test_new_invalid_revision_blocks_instead_of_reusing_old_final(kind):
    original = history(kind)
    correction = revised(original.bars[0])
    correction = replace(correction, metadata=replace(correction.metadata, quality="INVALID"))
    supplied = replace(original, bars=(*original.bars, correction))
    assert feature(snapshot(kind, supplied), kind).value == EXPECTED[kind]
    value = feature(snapshot(kind, supplied, evaluated=at("06:36:00")), kind)
    assert value.value is None
    assert value.missing_reason == "REFERENCE_WINDOW_QUALITY_INVALID"


@pytest.mark.parametrize("kind", NAMES)
def test_future_identity_cannot_change_scope_and_available_mismatch_blocks(kind):
    original = history(kind)
    correction = revised(original.bars[0])
    correction = replace(correction, metadata=replace(correction.metadata, instrument_type="ETF"))
    for bars in ((correction, *original.bars), (*original.bars, correction)):
        supplied = replace(original, bars=bars)
        assert snapshot(kind, supplied).to_json() == snapshot(kind, original).to_json()
        assert feature(snapshot(kind, supplied, evaluated=at("06:36:00")), kind).missing_reason == "INCOMPATIBLE_INSTRUMENT_TYPE"


@pytest.mark.parametrize("kind", NAMES)
def test_conflict_and_malformed_overlap_block_the_required_slot(kind):
    original = history(kind)
    first = original.bars[0]
    conflict = replace(first, record_id="conflicting", volume=first.volume + 1)
    value = feature(snapshot(kind, replace(original, bars=(*original.bars, conflict))), kind)
    assert value.missing_reason == "REFERENCE_WINDOW_CONFLICT"
    start = first.start_time + timedelta(seconds=1)
    overlap = replace(first, record_id="malformed", start_time=start,
                      metadata=replace(first.metadata, source_time=start))
    value = feature(snapshot(kind, replace(original, bars=(*original.bars, overlap))), kind)
    assert value.missing_reason == "UNEXPECTED_OVERLAPPING_RECORD"
    assert "malformed" in value.input_record_ids


@pytest.mark.parametrize("kind", NAMES)
def test_wrong_units_unknown_source_basis_and_mixed_modes_remain_missing(kind):
    original = history(kind)
    wrong_units = replace(original, conventions=replace(original.conventions, volume="LOTS"))
    assert feature(snapshot(kind, wrong_units), kind).missing_reason == "INCOMPATIBLE_VOLUME_UNIT"
    unknown = replace(original, conventions=replace(original.conventions, evidence_reference=" unknown "))
    assert feature(snapshot(kind, unknown), kind).missing_reason == "REFERENCE_WINDOW_UNKNOWN_CONVENTIONS"
    wrong_basis = replace(original.bars[0], adjustment_basis="OTHER_ASOF")
    assert feature(snapshot(kind, replace(original, bars=(wrong_basis, *original.bars[1:]))), kind).missing_reason == "REFERENCE_WINDOW_INCOMPATIBLE_CONVENTIONS"
    mixed = replace(original.bars[0], metadata=replace(original.bars[0].metadata, data_mode="OTHER_MODE"))
    assert feature(snapshot(kind, replace(original, bars=(mixed, *original.bars[1:]))), kind).missing_reason == "REFERENCE_WINDOW_INCOMPATIBLE_MODE"


@pytest.mark.parametrize("kind", ["opening", "premarket"])
def test_certified_zero_numerator_is_zero_but_zero_reference_is_missing(kind):
    original = history(kind)
    current = [bar for bar in original.bars if bar.metadata.session == "2026-07-06"]
    empty = tuple(replace(bar, open=None, high=None, low=None, close=None, volume=0,
                          certified_no_trade=True) for bar in current)
    zero_current = replace(original, bars=tuple(bar for bar in original.bars
                           if bar.metadata.session != "2026-07-06") + empty)
    assert feature(snapshot(kind, zero_current), kind).value == 0
    zero_prior = replace(original, bars=tuple(
        replace(bar, open=None, high=None, low=None, close=None, volume=0, certified_no_trade=True)
        if bar.metadata.session != "2026-07-06" else bar for bar in original.bars))
    assert feature(snapshot(kind, zero_prior), kind).missing_reason == "ZERO_REFERENCE_VOLUME"


def test_daily_median_uses_tenth_and_eleventh_and_requires_close():
    original = history("daily")
    bars = tuple(replace(bar, volume=(index + 1) * 10_000) for index, bar in enumerate(original.bars))
    assert feature(snapshot("daily", replace(original, bars=bars)), "daily").value == 10_500_000
    zero = tuple(replace(bar, volume=0) for bar in original.bars)
    assert feature(snapshot("daily", replace(original, bars=zero)), "daily").value == 0
    no_trade = replace(original.bars[0], open=None, high=None, low=None, close=None,
                       volume=0, certified_no_trade=True)
    assert feature(snapshot("daily", replace(original, bars=(no_trade, *original.bars[1:]))), "daily").missing_reason == "MISSING_REGULAR_SESSION_CLOSE"
    wrong_price = replace(original, conventions=replace(original.conventions, price="CENTS_PER_SHARE"))
    assert feature(snapshot("daily", wrong_price), "daily").missing_reason == "INCOMPATIBLE_PRICE_UNIT"


def test_opening_ratio_keeps_unrounded_near_threshold_values():
    original = history("opening")
    for total, expected in ((99_999, 1.99998), (100_000, 2), (100_001, 2.00002)):
        first = replace(original.bars[-5], volume=total)
        changed = replace(original, bars=(*original.bars[:-5], first, *original.bars[-4:]))
        assert feature(snapshot("opening", changed), "opening").value == expected


def test_provisional_current_and_reference_records_never_count_as_final():
    original = history("opening")
    for index, role in ((0, "REFERENCE"), (-1, "CURRENT")):
        bars = list(original.bars)
        # A non-final observation cannot also certify a no-trade interval.
        target = bars[index]
        bars[index] = replace(make_bar(target.record_id, target.start_time,
                                        target.end_time, 100), is_final=False)
        result = snapshot("opening", replace(original, bars=tuple(bars)))
        assert feature(result, "opening").missing_reason == role + "_WINDOW_PROVISIONAL"


def test_all_missing_inputs_and_nonfinite_dollar_result_are_explicit():
    output = snapshot()
    assert [value.value for value in output.features] == [None, None, None]
    assert all(value.missing_reason.startswith("MISSING_") for value in output.features)
    original = history("daily")
    huge = tuple(replace(bar, open=1e200, high=1e200, low=1e200, close=1e200, volume=1e200)
                 for bar in original.bars)
    assert feature(snapshot("daily", replace(original, bars=huge)), "daily").missing_reason == "NONFINITE_RESULT"


def test_later_minutes_and_current_daily_volume_cannot_enter_fixed_windows():
    opening = history("opening")
    later = make_bar("later-minute", at("06:35:00"), at("06:36:00"), 1_000_000_000)
    later = replace(later, metadata=replace(later.metadata, data_mode="UNRELATED_MODE", instrument_type="ETF"))
    wide = replace(opening, request=replace(opening.request, end=at("07:00:00")), bars=(*opening.bars, later))
    output = snapshot("opening", wide, evaluated=at("07:00:00"))
    assert feature(output, "opening").value == 2
    assert "later-minute" not in output.input_record_ids
    daily = history("daily")
    opened, closed = map(as_utc, session_bounds(at("06:35:00").date()))
    today = make_bar("today-daily", opened, closed, 1_000_000_000)
    with_today = replace(daily, request=replace(daily.request, end=closed), bars=(*daily.bars, today))
    assert feature(snapshot("daily", with_today, evaluated=at("13:00:00")), "daily").value == 50_000_000


@pytest.mark.parametrize("kind", NAMES)
def test_wrong_request_interval_cannot_supply_participation(kind):
    other = history("daily" if kind != "daily" else "opening")
    assert feature(snapshot(kind, other), kind).missing_reason == "INCOMPATIBLE_HISTORY_INTERVAL"


def test_premarket_cannot_start_later_or_use_partial_same_time_window():
    original = history("premarket")
    wrong = replace(original, request=replace(original.request, premarket_start=time(1, 1)))
    assert feature(snapshot("premarket", wrong), "premarket").missing_reason == "INCOMPATIBLE_PREMARKET_START"
    # At 05:00 the feature is unavailable even though the synthetic traded
    # volume was all seen at 01:00. The full frozen window is still required.
    assert feature(snapshot("premarket", original, evaluated=at("05:00:00")), "premarket").missing_reason == "CURRENT_WINDOW_NOT_ENDED"


@pytest.mark.parametrize("kind", NAMES)
def test_unknown_and_wrong_instrument_or_symbol_do_not_pass(kind):
    original = history(kind)
    wrong = replace(original.bars[0], metadata=replace(original.bars[0].metadata, instrument_type="UNKNOWN"))
    assert feature(snapshot(kind, replace(original, bars=(wrong, *original.bars[1:]))), kind).missing_reason == "INCOMPATIBLE_INSTRUMENT_TYPE"
    other = replace(original, request=replace(original.request, symbol="OTHER"), bars=())
    assert feature(snapshot(kind, other), kind).missing_reason == "INCOMPATIBLE_SYMBOL"


@pytest.mark.parametrize("day", ["2026-03-09", "2026-11-27", "2026-11-30"])
def test_calendar_changes_and_shortened_session_keep_exact_reference_population(day):
    opening = history("opening", day)
    daily = history("daily", day)
    output = snapshot(evaluated=at("06:35:00", day), opening_history=opening, daily_history=daily)
    assert feature(output, "opening").value == 2
    assert feature(output, "daily").value == 50_000_000
    assert len({bar.metadata.session for bar in daily.bars}) == 20
    if day == "2026-11-27":
        closed = as_utc(session_bounds(at("06:35:00", day).date())[1])
        assert closed.astimezone(PACIFIC).hour == 10
    elif day == "2026-11-30":
        assert daily.bars[-1].metadata.session == "2026-11-27"
        assert daily.bars[-1].end_time - daily.bars[-1].start_time == timedelta(minutes=210)
    else:
        first = opening.bars[0].start_time
        last = opening.bars[-5].start_time
        assert first.astimezone(PACIFIC).utcoffset() != last.astimezone(PACIFIC).utcoffset()


def test_holiday_and_immutable_snapshot_and_legacy_relative_volume():
    output = snapshot("opening")
    assert "2026-07-03" not in {bar.metadata.session for bar in history("opening").bars}
    assert history("daily").bars[-1].metadata.session == "2026-07-02"
    holiday = snapshot("opening", evaluated=at("06:35:00", "2026-07-03"))
    assert feature(holiday, "opening").missing_reason == "NO_CURRENT_SESSION_OR_20_REFERENCE_SESSIONS"
    with pytest.raises(FrozenInstanceError):
        output.features = ()
    detached = output.as_dict()
    detached["features"][0]["value"] = -1
    assert feature(output, "opening").value == 2
    with pytest.raises(RecordError):
        build_participation_snapshot(record_id="bad", evaluated_at=at("06:35:00"),
                                     symbol="SYNTH", instrument_type="OPTION",
                                     opening_history=None, daily_history=None, premarket_history=None)
    from consensus_engine.analysis.indicators import relative_volume
    assert relative_volume(100_000, 50_000) == 2
    assert relative_volume(100_000, 0) == 0
    assert relative_volume(100_000, -1) == 0


def test_explicit_etf_scope_uses_only_matching_supplied_etf_records():
    original = history("opening")
    supplied = replace(original, bars=tuple(replace(bar, metadata=replace(
        bar.metadata, instrument_type="ETF")) for bar in original.bars))
    output = build_participation_snapshot(
        record_id="etf", evaluated_at=at("06:35:00"), symbol="SYNTH", instrument_type="ETF",
        opening_history=supplied, premarket_history=None, daily_history=None)
    assert feature(output, "opening").value == 2
    assert output.metadata.instrument_type == "ETF"


def proof_summary(output):
    raw = output.to_json().encode()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "evaluated_at_pacific": output.evaluated_at.astimezone(PACIFIC).isoformat(),
            "features": [{"name": value.name, "value": value.value, "unit": value.unit,
                          "missing_reason": value.missing_reason,
                          "input_count": len(value.input_record_ids)} for value in output.features]}


def test_bar_coverage_participation_recording_end_to_end():
    def uncached_history(original):
        scope = original.request
        # Exercise the ordinary uncached request through the complete proof path.
        request = HistoryRequest(scope.symbol, scope.start, scope.end, scope.interval,
                                 scope.session_scope, scope.premarket_start)
        return replace(original, request=request, bars=tuple(
            Bar.from_json(bar.to_json()) for bar in original.bars))

    supplied = {kind: uncached_history(history(kind)) for kind in NAMES}
    outputs = []
    for clock in ("06:29:59", "06:30:00", "06:34:59", "06:35:00"):
        output = snapshot(evaluated=at(clock), **{kind + "_history": batch for kind, batch in supplied.items()})
        assert FeatureSnapshot.from_json(output.to_json()).to_json() == output.to_json()
        outputs.append(output)
    assert [[feature(output, kind).value for kind in NAMES] for output in outputs] == [
        [None, None, 50_000_000], [None, 2.75, 50_000_000],
        [None, 2.75, 50_000_000], [2, 2.75, 50_000_000],
    ]
    frozen = outputs[-1].to_json()
    broken = replace(supplied["opening"], bars=supplied["opening"].bars[1:])
    outputs.append(snapshot("opening", broken))
    assert feature(outputs[-1], "opening").missing_reason == "REFERENCE_WINDOW_MISSING"
    invalid = revised(supplied["opening"].bars[0])
    invalid = replace(invalid, metadata=replace(invalid.metadata, quality="INVALID"))
    corrected = replace(supplied["opening"], bars=(*supplied["opening"].bars, invalid))
    outputs.append(snapshot("opening", corrected, evaluated=at("06:36:00")))
    assert feature(outputs[-1], "opening").missing_reason == "REFERENCE_WINDOW_QUALITY_INVALID"
    assert outputs[3].to_json() == frozen
    end = at("06:35:00")
    last = supplied["opening"].bars[-1]
    late = replace(last, metadata=replace(last.metadata, received_time=end + timedelta(seconds=2),
                   available_time=end + timedelta(seconds=2), normalized_time=end + timedelta(seconds=2)))
    late_history = replace(supplied["opening"], bars=(*supplied["opening"].bars[:-1], late))
    for seconds, expected in ((0, None), (2, 2)):
        outputs.append(snapshot("opening", late_history, evaluated=end + timedelta(seconds=seconds)))
        assert feature(outputs[-1], "opening").value == expected
    for current, expected in ((True, 0), (False, None)):
        zero = replace(supplied["opening"], bars=tuple(replace(
            bar, open=None, high=None, low=None, close=None, volume=0, certified_no_trade=True)
            if (bar.metadata.session == "2026-07-06") == current else bar
            for bar in supplied["opening"].bars))
        outputs.append(snapshot("opening", zero))
        assert feature(outputs[-1], "opening").value == expected
    assert feature(outputs[-1], "opening").missing_reason == "ZERO_REFERENCE_VOLUME"
    for day in ("2026-03-09", "2026-11-30"):
        outputs.append(snapshot(evaluated=at("06:35:00", day),
                                opening_history=uncached_history(history("opening", day)),
                                daily_history=uncached_history(history("daily", day))))
        assert feature(outputs[-1], "opening").value == 2
        assert feature(outputs[-1], "daily").value == 50_000_000
    coverage_counts = {}
    for kind, batch in supplied.items():
        coverage = batch.coverage_at(at("06:35:00"))
        statuses = {}
        for item in coverage.intervals:
            statuses[item.status] = statuses.get(item.status, 0) + 1
        coverage_counts[kind] = {"requested_intervals": len(coverage.intervals), "status_counts": statuses,
                                 "supplied_bars": len(batch.bars)}
    # The broad opening request has unneeded later minutes missing on prior
    # days. Only the required five-minute windows may supply this feature.
    assert coverage_counts["opening"]["status_counts"]["MISSING"] > 0
    payload = {"evidence": "SYNTHETIC_SOFTWARE_PROOF_ONLY", "feature_version": FEATURE_VERSION,
               "coverage": coverage_counts, "snapshots": [proof_summary(output) for output in outputs]}
    rendered = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    assert len(rendered.encode()) < 100_000
    Path("/tmp/m32-participation-features-proof.json").write_text(rendered)
