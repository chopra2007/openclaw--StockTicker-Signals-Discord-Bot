# tests/test_sessions.py
from datetime import datetime
from zoneinfo import ZoneInfo
from consensus_engine.research.sessions import current_et_session, is_market_holiday


def test_current_et_session_returns_key_and_bounds():
    # Monday 2026-04-20 at 09:00 ET
    ref = datetime(2026, 4, 20, 9, 0, tzinfo=ZoneInfo("America/New_York"))
    start, end, key = current_et_session(ref)
    assert key == "2026-04-20"
    assert end > start
    # ~24h window (slightly less due to 4pm boundaries)
    assert 18 * 3600 <= end - start <= 30 * 3600


def test_weekend_session_key_rolls_back_to_friday():
    # Saturday should surface Friday's key (tradeable session)
    sat = datetime(2026, 4, 25, 9, 0, tzinfo=ZoneInfo("America/New_York"))
    _, _, key = current_et_session(sat)
    assert key == "2026-04-24"  # Friday


def test_is_market_holiday_matches_config(monkeypatch):
    monkeypatch.setattr(
        "consensus_engine.research.sessions._holiday_list",
        lambda: ["2026-04-21"],
    )
    d = datetime(2026, 4, 21, tzinfo=ZoneInfo("America/New_York"))
    assert is_market_holiday(d) is True
    d = datetime(2026, 4, 22, tzinfo=ZoneInfo("America/New_York"))
    assert is_market_holiday(d) is False
