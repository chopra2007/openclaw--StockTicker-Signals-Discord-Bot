"""Fixed-input contracts for the canonical M1.1 market clock."""

import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from datetime import date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

from consensus_engine.utils.time_context import (
    as_utc,
    format_pacific,
    premarket_bounds,
    regular_session_window,
    session_date_at,
    session_phase,
)


UTC = timezone.utc
PACIFIC = ZoneInfo("America/Los_Angeles")
RESEARCH_PREMARKET_START = time(1, 0)


def test_as_utc_converts_absolute_instant_and_preserves_microseconds():
    source = datetime(
        2026, 7, 6, 19, 45, 12, 345678,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )

    result = as_utc(source)

    assert result == datetime(2026, 7, 6, 14, 15, 12, 345678, tzinfo=UTC)
    assert result.utcoffset() == timedelta(0)


class _NoOffset(tzinfo):
    def utcoffset(self, dt):
        return None


@pytest.mark.parametrize(
    "moment",
    [datetime(2026, 7, 6, 9, 30), datetime(2026, 7, 6, 9, 30, tzinfo=_NoOffset())],
)
def test_as_utc_rejects_datetimes_without_an_absolute_offset(moment):
    with pytest.raises(ValueError):
        as_utc(moment)


def test_fall_clock_repeat_maps_each_fold_to_its_distinct_absolute_instant():
    first = datetime(2026, 11, 1, 1, 30, 0, 111111, tzinfo=PACIFIC, fold=0)
    second = datetime(2026, 11, 1, 1, 30, 0, 222222, tzinfo=PACIFIC, fold=1)

    assert as_utc(first) == datetime(2026, 11, 1, 8, 30, 0, 111111, tzinfo=UTC)
    assert as_utc(second) == datetime(2026, 11, 1, 9, 30, 0, 222222, tzinfo=UTC)
    assert format_pacific(first) == "2026-11-01 01:30:00 AM PDT"
    assert format_pacific(second) == "2026-11-01 01:30:00 AM PST"


@pytest.mark.parametrize(
    "moment, expected",
    [
        (datetime(2026, 3, 9, 14, 0, tzinfo=UTC), "2026-03-09 07:00:00 AM PDT"),
        (datetime(2026, 11, 2, 14, 0, tzinfo=UTC), "2026-11-02 06:00:00 AM PST"),
    ],
)
def test_format_pacific_uses_the_seasonal_label(moment, expected):
    assert format_pacific(moment) == expected


def test_session_date_uses_the_exchange_calendar_date_after_source_date_rollover():
    instant = datetime(2026, 7, 6, 0, 30, tzinfo=UTC)
    source_views = [
        instant,
        instant.astimezone(PACIFIC),
        instant.astimezone(ZoneInfo("Asia/Tokyo")),
    ]

    assert {session_date_at(moment) for moment in source_views} == {date(2026, 7, 5)}


@pytest.mark.parametrize(
    "day, expected",
    [
        (
            date(2026, 3, 6),
            (
                datetime(2026, 3, 6, 9, 0, tzinfo=UTC),
                datetime(2026, 3, 6, 14, 30, tzinfo=UTC),
            ),
        ),
        (
            date(2026, 3, 9),
            (
                datetime(2026, 3, 9, 8, 0, tzinfo=UTC),
                datetime(2026, 3, 9, 13, 30, tzinfo=UTC),
            ),
        ),
        (
            date(2026, 10, 30),
            (
                datetime(2026, 10, 30, 8, 0, tzinfo=UTC),
                datetime(2026, 10, 30, 13, 30, tzinfo=UTC),
            ),
        ),
        (
            date(2026, 11, 2),
            (
                datetime(2026, 11, 2, 9, 0, tzinfo=UTC),
                datetime(2026, 11, 2, 14, 30, tzinfo=UTC),
            ),
        ),
        (
            date(2026, 11, 27),
            (
                datetime(2026, 11, 27, 9, 0, tzinfo=UTC),
                datetime(2026, 11, 27, 14, 30, tzinfo=UTC),
            ),
        ),
    ],
)
def test_premarket_bounds_have_hand_checked_absolute_times(day, expected):
    assert premarket_bounds(day, RESEARCH_PREMARKET_START) == expected


@pytest.mark.parametrize("day", [date(2026, 7, 3), date(2026, 7, 4)])
def test_premarket_bounds_are_absent_on_holiday_and_weekend(day):
    assert premarket_bounds(day, RESEARCH_PREMARKET_START) is None


def test_premarket_bounds_use_the_callers_local_pacific_start():
    assert premarket_bounds(date(2026, 3, 9), time(2, 0)) == (
        datetime(2026, 3, 9, 9, 0, tzinfo=UTC),
        datetime(2026, 3, 9, 13, 30, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    "premarket_start",
    [time(6, 30), time(7, 0), time(1, 0, tzinfo=UTC)],
)
def test_premarket_bounds_reject_invalid_local_start_times(premarket_start):
    with pytest.raises(ValueError):
        premarket_bounds(date(2026, 3, 9), premarket_start)


@pytest.mark.parametrize(
    "day, start, end, expected",
    [
        (
            date(2026, 3, 6),
            timedelta(minutes=5),
            timedelta(minutes=45),
            (
                datetime(2026, 3, 6, 14, 35, tzinfo=UTC),
                datetime(2026, 3, 6, 15, 15, tzinfo=UTC),
            ),
        ),
        (
            date(2026, 3, 9),
            timedelta(minutes=5),
            timedelta(minutes=45),
            (
                datetime(2026, 3, 9, 13, 35, tzinfo=UTC),
                datetime(2026, 3, 9, 14, 15, tzinfo=UTC),
            ),
        ),
        (
            date(2026, 10, 30),
            timedelta(minutes=5),
            timedelta(minutes=45),
            (
                datetime(2026, 10, 30, 13, 35, tzinfo=UTC),
                datetime(2026, 10, 30, 14, 15, tzinfo=UTC),
            ),
        ),
        (
            date(2026, 11, 2),
            timedelta(minutes=5),
            timedelta(minutes=45),
            (
                datetime(2026, 11, 2, 14, 35, tzinfo=UTC),
                datetime(2026, 11, 2, 15, 15, tzinfo=UTC),
            ),
        ),
        (
            date(2026, 3, 9),
            timedelta(0),
            timedelta(minutes=5),
            (
                datetime(2026, 3, 9, 13, 30, tzinfo=UTC),
                datetime(2026, 3, 9, 13, 35, tzinfo=UTC),
            ),
        ),
    ],
)
def test_regular_windows_use_open_relative_half_open_boundaries(day, start, end, expected):
    assert regular_session_window(day, start, end) == expected


def test_research_clock_windows_at_opening_and_expiry_edges():
    day = date(2026, 3, 9)
    opening = regular_session_window(day, timedelta(0), timedelta(minutes=5))
    evaluation = regular_session_window(day, timedelta(minutes=5), timedelta(minutes=45))

    for clock, in_opening, in_evaluation in [
        ("06:29:59", False, False),
        ("06:30:00", True, False),
        ("06:34:59", True, False),
        ("06:35:00", False, True),
        ("07:14:59", False, True),
        ("07:15:00", False, False),
    ]:
        moment = as_utc(datetime.combine(day, time.fromisoformat(clock), PACIFIC))
        assert (opening[0] <= moment < opening[1]) is in_opening
        assert (evaluation[0] <= moment < evaluation[1]) is in_evaluation
    # These are clock windows only. Final/available bars remain a separate gate.


def test_regular_window_clips_at_early_close_and_rejects_no_overlap():
    day = date(2026, 11, 27)

    assert regular_session_window(day, timedelta(hours=2), timedelta(hours=5)) == (
        datetime(2026, 11, 27, 16, 30, tzinfo=UTC),
        datetime(2026, 11, 27, 18, 0, tzinfo=UTC),
    )
    assert regular_session_window(day, timedelta(hours=4), timedelta(hours=5)) is None
    assert regular_session_window(
        date(2026, 7, 3), timedelta(minutes=5), timedelta(minutes=45)
    ) is None


@pytest.mark.parametrize(
    "start, end",
    [
        (timedelta(microseconds=-1), timedelta(minutes=5)),
        (timedelta(minutes=5), timedelta(minutes=5)),
        (timedelta(minutes=6), timedelta(minutes=5)),
    ],
)
def test_regular_window_rejects_invalid_offsets(start, end):
    with pytest.raises(ValueError):
        regular_session_window(date(2026, 3, 9), start, end)


@pytest.mark.parametrize(
    "moment, expected",
    [
        (datetime(2026, 3, 9, 7, 59, 59, 999999, tzinfo=UTC), "CLOSED"),
        (datetime(2026, 3, 9, 8, 0, tzinfo=UTC), "PREMARKET"),
        (datetime(2026, 3, 9, 13, 29, 59, 999999, tzinfo=UTC), "PREMARKET"),
        (datetime(2026, 3, 9, 13, 30, tzinfo=UTC), "REGULAR"),
        (datetime(2026, 3, 9, 19, 59, 59, 999999, tzinfo=UTC), "REGULAR"),
        (datetime(2026, 3, 9, 20, 0, tzinfo=UTC), "CLOSED"),
        (datetime(2026, 3, 9, 21, 0, tzinfo=UTC), "CLOSED"),
    ],
)
def test_session_phase_uses_exact_half_open_edges(moment, expected):
    assert session_phase(moment, RESEARCH_PREMARKET_START) == expected


def test_session_phase_honors_early_close_and_non_session_days():
    assert session_phase(
        datetime(2026, 11, 27, 17, 59, 59, 999999, tzinfo=UTC),
        RESEARCH_PREMARKET_START,
    ) == "REGULAR"
    assert session_phase(
        datetime(2026, 11, 27, 18, 0, tzinfo=UTC), RESEARCH_PREMARKET_START
    ) == "CLOSED"
    assert session_phase(
        datetime(2026, 7, 3, 15, 0, tzinfo=UTC), RESEARCH_PREMARKET_START
    ) == "CLOSED"
    assert session_phase(
        datetime(2026, 7, 4, 15, 0, tzinfo=UTC), RESEARCH_PREMARKET_START
    ) == "CLOSED"


def test_session_phase_normalizes_equivalent_source_zones():
    # The Tokyo view is already on the next date, while this session is open.
    instant = datetime(2026, 3, 9, 19, 0, tzinfo=UTC)

    assert (
        session_phase(instant.astimezone(PACIFIC), RESEARCH_PREMARKET_START)
        == "REGULAR"
    )
    assert session_phase(
        instant.astimezone(ZoneInfo("Asia/Tokyo")), RESEARCH_PREMARKET_START
    ) == "REGULAR"


def test_session_phase_uses_the_callers_premarket_start():
    instant = datetime(2026, 3, 9, 8, 30, tzinfo=UTC)

    assert session_phase(instant, time(1, 0)) == "PREMARKET"
    assert session_phase(instant, time(2, 0)) == "CLOSED"


@pytest.mark.parametrize("function", [format_pacific, session_date_at])
def test_single_argument_moment_helpers_reject_naive_datetimes(function):
    with pytest.raises(ValueError):
        function(datetime(2026, 3, 9, 13, 30))


def test_session_phase_rejects_invalid_moment_or_local_start_time():
    with pytest.raises(ValueError):
        session_phase(datetime(2026, 3, 9, 13, 30), RESEARCH_PREMARKET_START)
    with pytest.raises(ValueError):
        session_phase(datetime(2026, 3, 9, 13, 30, tzinfo=UTC), time(1, 0, tzinfo=UTC))
    with pytest.raises(ValueError):
        session_phase(datetime(2026, 3, 9, 13, 30, tzinfo=UTC), time(6, 30))
