from datetime import date

from consensus_engine.utils import time_context as tc


def test_session_dates_repeat_calls_reuse_calendar_and_stay_unchanged():
    tc._session_dates_cached.cache_clear()
    first = tc.session_dates(date(2026, 9, 1), date(2026, 9, 8))
    assert first == [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3), date(2026, 9, 4), date(2026, 9, 8)]
    first.append(date(2030, 1, 1))
    assert tc.session_dates(date(2026, 9, 1), date(2026, 9, 8)) == first[:-1]
    assert tc._session_dates_cached.cache_info().hits == 1
    assert tc.session_dates(date(2026, 9, 8), date(2026, 9, 1)) == []
    assert tc.session_dates(date(2026, 9, 5), date(2026, 9, 6)) == []


def test_session_bounds_cached_values_match_holiday_and_early_close():
    assert tc.session_bounds(date(2026, 9, 7)) is None
    assert tc.session_bounds(date(2026, 9, 7)) is None
    opened, closed = tc.session_bounds(date(2026, 11, 27))
    assert closed.hour == 13
    assert tc.session_bounds(date(2026, 11, 27)) == (opened, closed)
