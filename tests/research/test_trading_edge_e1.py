import importlib.util
from pathlib import Path

import pandas as pd
import pytest


REPO = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "scripts/research/trading_edge_e1.py"
SPEC = importlib.util.spec_from_file_location("trading_edge_e1", MODULE_PATH)
E1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(E1)


def _frame(rows):
    return pd.DataFrame(rows).set_index("minute")


def test_pilot_dates_are_twenty_references_then_thirty_sessions():
    references, pilot, schedule = E1.pilot_sessions()
    assert len(references) == 20
    assert len(pilot) == 30
    assert references[0] == "2023-03-28"
    assert references[-1] == "2023-04-25"
    assert pilot[0] == "2023-04-26"
    assert pilot[-1] == "2023-06-07"
    assert list(schedule.index) == references + pilot


def test_exchange_calendar_handles_shortened_session():
    calendar = E1.xcals.get_calendar("XNYS")
    row = calendar.schedule.loc["2023-11-24"]
    assert len(E1._session_minutes(row)) == 210


def test_cross_requires_previous_close_on_other_side_or_equal():
    assert E1._crossed(10.0, 10.1, 10.0, "long")
    assert not E1._crossed(10.01, 10.1, 10.0, "long")
    assert E1._crossed(10.0, 9.9, 10.0, "short")
    assert not E1._crossed(9.99, 9.9, 10.0, "short")


def test_opening_range_keeps_only_first_completed_close_cross():
    minutes = list(range(570, 580))
    rows = []
    closes = [10.0, 10.0, 10.0, 10.0, 10.0, 10.2, 9.8, 10.3, 9.7, 10.4]
    for minute, close in zip(minutes, closes):
        rows.append({
            "minute": minute, "open": close, "high": 10.1 if minute < 575 else close,
            "low": 9.9 if minute < 575 else close, "close": close, "volume": 100,
        })
    setting = {
        "opening_minutes": 5, "opening_volume_gate": None,
    }
    found, _ = E1._opening_range_events(setting, _frame(rows), minutes, None)
    assert found == {"long": 575, "short": 576}


def test_late_signal_uses_actual_close_relative_minute():
    minutes = list(range(570, 960))
    rows = [{
        "minute": minute, "open": 101, "high": 101, "low": 101,
        "close": 101, "volume": 100,
    } for minute in minutes]
    signal, reason = E1._late_event(_frame(rows), minutes, 100.0, "long")
    assert reason == ""
    assert signal == 929
    assert signal + 1 == 930


def test_control_key_uses_bin_or_time_to_close():
    minutes = list(range(570, 960))
    ordinary = {"symbol": "CRM", "block": "B1", "direction": "long", "family": "opening_range"}
    late = dict(ordinary, family="late_continuation")
    assert E1._control_key(ordinary, "next_minute", 30, 600, minutes).endswith("BIN02")
    assert E1._control_key(late, "next_minute", 25, 930, minutes).endswith("TTC30")


def test_jsonl_output_is_deterministic(tmp_path):
    rows = [{"id": "b", "x": 2}, {"id": "a", "x": 1}]
    first_count, first_hash = E1._write_jsonl(tmp_path / "first.jsonl", rows)
    second_count, second_hash = E1._write_jsonl(tmp_path / "second.jsonl", reversed(rows))
    assert first_count == second_count == 2
    assert first_hash == second_hash
    assert (tmp_path / "first.jsonl").read_bytes() == (tmp_path / "second.jsonl").read_bytes()


def test_rvol_reports_exact_prior_window_missingness():
    minutes = list(range(570, 575))
    complete = _frame([
        {"minute": minute, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 100}
        for minute in minutes
    ])
    incomplete = complete.drop(index=572)
    prior_days = [f"2023-03-{day:02d}" for day in range(1, 21)]
    frames = {("CRM", day): complete for day in prior_days}
    frames[("CRM", prior_days[5])] = incomplete
    frames[("CRM", "2023-03-21")] = complete
    value, status = E1._rvol_status(frames, "CRM", "2023-03-21", prior_days, minutes)
    assert value is None
    assert status == "one_or_more_exact_prior_windows_missing"


def test_full_run_lock_rejects_a_duplicate_writer(tmp_path):
    with E1._exclusive_full_run(tmp_path):
        with pytest.raises(RuntimeError, match="another trading-edge E1"):
            with E1._exclusive_full_run(tmp_path):
                pass
