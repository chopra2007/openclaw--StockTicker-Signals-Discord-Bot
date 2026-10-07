from datetime import datetime
from zoneinfo import ZoneInfo

from consensus_engine import hour_outcomes


def test_missed_hour_uses_target_minute_not_latest_price(monkeypatch):
    start = datetime(2026, 10, 5, 9, 0, 30, tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()
    target_minute = int((start + 3600) // 60) * 60
    calls = []
    def history(ticker, **kwargs):
        calls.append(kwargs)
        return {'candles': [{'datetime': (target_minute-60)*1000, 'close': 99},
                            {'datetime': target_minute*1000, 'close': 101},
                            {'datetime': (target_minute+3600)*1000, 'close': 150}]}
    monkeypatch.setattr(hour_outcomes, 'get_history', history)
    assert hour_outcomes.fetch_hour_price('AAA', start, now=start+86400) == 101
    assert calls[0]['interval'] == '1m' and calls[0]['extended_hours'] is False


def test_missing_target_or_unfinished_minute_never_uses_current_price(monkeypatch):
    start = datetime(2026, 10, 5, 9, 0, 30, tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()
    monkeypatch.setattr(hour_outcomes, 'get_history', lambda *a, **k: {'candles': []})
    assert hour_outcomes.fetch_hour_price('AAA', start, now=start+86400) == 0
    assert hour_outcomes.fetch_hour_price('AAA', start, now=start+3601) == 0


def test_closed_session_and_old_history_do_not_call_source(monkeypatch):
    start = datetime(2026, 10, 5, 12, 30, tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()
    def forbidden(*args, **kwargs): raise AssertionError('no request expected')
    monkeypatch.setattr(hour_outcomes, 'get_history', forbidden)
    assert hour_outcomes.fetch_hour_price('AAA', start, now=start+86400) == 0
    start -= 5*3600
    assert hour_outcomes.fetch_hour_price('AAA', start, now=start+31*86400) == 0
