import hashlib
import json
from pathlib import Path

import pytest
import numpy as np

from scripts.research import trading_edge_e2 as E


def test_registers_exactly_nine_uncombined_variants():
    assert len(E.VARIANTS) == 9
    assert len({row["id"] for row in E.VARIANTS}) == 9
    assert {row["exit_rule"] for row in E.VARIANTS} == set(E.EXIT_RULES)
    assert {row["population"] for row in E.VARIANTS} == set(E.POPULATIONS)


def test_population_boundaries_are_strict_and_missing_gap_is_excluded():
    assert E.population_allows("EARLY_1H", 59, None)
    assert not E.population_allows("EARLY_1H", 60, None)
    assert E.population_allows("ABS_GAP_LT2", 60, 199.999)
    assert not E.population_allows("ABS_GAP_LT2", 60, 200.0)
    assert not E.population_allows("ABS_GAP_LT2", 60, None)
    assert E.population_allows("UNFILTERED", 60, None)


def test_short_bracket_gap_and_same_minute_rules():
    gap_stop = E.bracket_short(100, [111], [112], [109], 110, 110, 90)
    assert gap_stop["exit_price"] == 111
    assert gap_stop["reason"] == "GAP_STOP"
    gap_target = E.bracket_short(100, [89], [91], [88], 90, 110, 90)
    assert gap_target["exit_price"] == 90
    assert gap_target["reason"] == "GAP_TARGET_CAPPED"
    stop_first = E.bracket_short(100, [100], [111], [89], 100, 110, 90)
    target_first = E.bracket_short(100, [100], [111], [89], 100, 110, 90, same_minute="target_first")
    assert stop_first["exit_price"] == 110
    assert target_first["exit_price"] == 90


def test_short_bracket_missing_path_is_unresolved():
    result = E.bracket_short(100, [100], [float("nan")], [99], 100, 110, 90)
    assert result == {"status": "unresolved", "reason": "MISSING_PATH"}


def test_cost_floor_and_two_sided_spread_math():
    buckets = [
        {"start": 0, "median_displayed_spread_bps": 10.0},
        {"start": 30, "median_displayed_spread_bps": 6.0},
        {"start": 60, "median_displayed_spread_bps": 4.0},
    ]
    assert E.round_trip_cost_bps(10, 40, buckets, "median_displayed_spread_bps") == 8.0
    assert E.round_trip_cost_bps(70, 80, buckets, "median_displayed_spread_bps") == 5.0


def test_common_coverage_requires_complete_h30_path():
    class Panel:
        lengths = [390]
        o = __import__("numpy").ones((1, 1, 40))
        h = __import__("numpy").ones((1, 1, 40))
        l = __import__("numpy").ones((1, 1, 40))
        c = __import__("numpy").ones((1, 1, 40))

    assert E._common_h30_coverage(Panel, 0, 0, 1, 30)
    Panel.h[0, 0, 20] = float("nan")
    assert not E._common_h30_coverage(Panel, 0, 0, 1, 30)


def test_delayed_h15_keeps_the_registered_exit_clock():
    class Panel:
        lengths = [390]
        o = np.full((1, 1, 40), 100.0)
        h = np.full((1, 1, 40), 101.0)
        l = np.full((1, 1, 40), 99.0)
        c = np.arange(40, dtype=float).reshape(1, 1, 40) + 100.0

    result = E._path_result(Panel, 0, 0, 2, 30, 15, "FIXED_H15", "stop_first")
    assert result["exit_price"] == 115.0
    assert result["exit_index"] == 13


def test_rolling_folds_are_expanding_and_stop_before_test_block():
    assert E.FOLDS == (
        ("F1", ("B1",), "B2"),
        ("F2", ("B1", "B2"), "B3"),
        ("F3", ("B1", "B2", "B3"), "B4"),
        ("F4", ("B1", "B2", "B3", "B4"), "B5"),
    )


def test_checkpoint_rejects_wrong_context_and_recovers_from_partial_file(tmp_path):
    path = tmp_path / "checkpoint.json"
    record = {"version": 1, "context_sha256": "right", "variant_id": "v", "block": "B1", "summary": {}, "daily_rows": [], "audit_rows": [], "unresolved_rows": []}
    E.write_checkpoint(path, record)
    assert E.load_checkpoint(path, "right", "v", "B1") == record
    assert E.load_checkpoint(path, "wrong", "v", "B1") is None
    path.write_text("{")
    assert E.load_checkpoint(path, "right", "v", "B1") is None


def test_checkpoint_recovers_if_interrupted_after_atomic_json_rename(tmp_path, monkeypatch):
    path = tmp_path / "checkpoint.json"
    record = {"version": 1, "context_sha256": "ctx", "variant_id": "v", "block": "B1", "summary": {}, "daily_rows": [], "audit_rows": [], "unresolved_rows": []}
    original = E._write_sidecar

    def interrupt(_path, _digest):
        raise RuntimeError("injected interruption")

    monkeypatch.setattr(E, "_write_sidecar", interrupt)
    with pytest.raises(RuntimeError, match="injected"):
        E.write_checkpoint(path, record)
    assert path.exists()
    assert not path.with_name("checkpoint.json.sha256").exists()
    monkeypatch.setattr(E, "_write_sidecar", original)
    assert E.load_checkpoint(path, "ctx", "v", "B1") == record
    assert path.with_name("checkpoint.json.sha256").exists()


def test_checkpoint_repairs_stale_sidecar_and_skips_completed_compute(tmp_path):
    path = tmp_path / "checkpoint.json"
    record = {"version": 1, "context_sha256": "ctx", "variant_id": "v", "block": "B1", "summary": {}, "daily_rows": [], "audit_rows": [], "unresolved_rows": []}
    E.write_checkpoint(path, record)
    path.with_name("checkpoint.json.sha256").write_text("stale\n")
    called = False

    def compute():
        nonlocal called
        called = True
        return []

    saved, reused = E.checkpointed_block(path, "ctx", "v", "B1", compute)
    assert saved == record
    assert reused is True
    assert called is False
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert path.with_name("checkpoint.json.sha256").read_text() == f"{digest}  checkpoint.json\n"


def test_checkpoint_rejects_valid_json_with_wrong_embedded_checksum(tmp_path):
    path = tmp_path / "checkpoint.json"
    record = {"version": 1, "context_sha256": "ctx", "variant_id": "v", "block": "B1", "summary": {}, "daily_rows": [], "audit_rows": [], "unresolved_rows": []}
    E.write_checkpoint(path, record)
    envelope = json.loads(path.read_text())
    envelope["checkpoint"]["daily_rows"] = [{"id": "tampered"}]
    path.write_text(json.dumps(envelope))
    assert E.load_checkpoint(path, "ctx", "v", "B1") is None


def test_atomic_output_has_matching_sidecar(tmp_path):
    path = tmp_path / "result.json"
    E.write_json(path, {"b": 2, "a": 1})
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert path.with_name("result.json.sha256").read_text() == f"{digest}  result.json\n"
    assert json.loads(path.read_text()) == {"a": 1, "b": 2}


def test_date_first_summary_does_not_weight_trade_count():
    rows = [
        {"date": "2024-01-02", "week": "2024-W01", "event_count": 10,
         "net_excess_base": 0.01, "net_excess_base_target_first": 0.01,
         "raw_event_gross": 0.011, "raw_event_net_base": 0.01, "net_excess_p90": 0.01,
         "net_excess_twice_floor": 0.01, "net_excess_20bps": 0.01},
        {"date": "2024-01-03", "week": "2024-W01", "event_count": 1,
         "net_excess_base": -0.01, "net_excess_base_target_first": -0.01,
         "raw_event_gross": -0.009, "raw_event_net_base": -0.01, "net_excess_p90": -0.01,
         "net_excess_twice_floor": -0.01, "net_excess_20bps": -0.01},
    ]
    assert E._summarize(rows, "v", "B1")["mean_net_excess_base"] == pytest.approx(0.0)


def test_performance_reports_common_size_drawdown_streaks_and_turnover():
    rows = [
        {"date": "2024-01-02", "week": "2024-W01", "event_count": 2,
         "raw_event_gross": 0.011, "raw_event_net_base": 0.01},
        {"date": "2024-01-03", "week": "2024-W01", "event_count": 1,
         "raw_event_gross": -0.019, "raw_event_net_base": -0.02},
        {"date": "2024-01-04", "week": "2024-W01", "event_count": 1,
         "raw_event_gross": 0.006, "raw_event_net_base": 0.005},
    ]
    result = E._performance(rows, ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-08"])
    assert result["completed_trades"] == 4
    assert result["turnover_legs"] == 8
    assert result["max_additive_drawdown_percent"] == pytest.approx(-2.0)
    assert result["longest_losing_trade_day_streak"] == 1
    assert result["inactive_weeks"] == 1


def test_power_uses_rolling_excess_and_confirmation_sample_must_fit_cap():
    rows = []
    for index in range(100):
        rows.append({
            "date": f"2024-01-{(index % 28) + 1:02d}#{index}",
            "week": f"2024-W{index:03d}",
            "event_count": 2,
            "net_excess_base": 0.0001 if index % 2 else -0.0001,
        })
    result = E._power(rows, 0.001)
    assert result["target_bps"] == pytest.approx(5.0)
    assert result["finalist_count"] == 1
    assert "variant_correction" not in result
    assert result["development_trades"] == 200
    assert result["required_weeks_for_200_confirmation_trades"] == 100
    assert result["required_confirmation_weeks"] >= 100
    assert result["feasible_within_cap"] is False


def test_checkpoint_context_binds_imported_runner_modules(monkeypatch):
    seen = []

    def fake_sha(path):
        seen.append(Path(path).resolve())
        return "a" * 64

    monkeypatch.setattr(E, "sha256_file", fake_sha)
    E._checkpoint_context()
    assert Path(E.F.__file__).resolve() in seen
    assert Path(E.R.__file__).resolve() in seen


def test_event_audit_persists_exit_cost_and_matched_control_details():
    class Panel:
        symbols = ("CRM",)
        dates = ["2023-04-03", "2023-04-04"]
        lengths = np.array([390, 390])
        o = np.full((1, 2, 390), 100.0)
        h = np.full((1, 2, 390), 101.0)
        l = np.full((1, 2, 390), 99.0)
        c = np.full((1, 2, 390), 99.5)

        @staticmethod
        def session_type(_index):
            return "regular"

    event = {
        "id": "response-1", "event_id": "event-1", "symbol": "CRM",
        "date": "2023-04-03", "block": "B1", "entry_col": 16,
        "exit_col": 45, "event_session_type": "regular", "audit_overnight_gap_bps": 10.0,
    }
    buckets = [
        {"start": 0, "median_displayed_spread_bps": 8.0, "p90_displayed_spread_bps": 16.0},
        {"start": 30, "median_displayed_spread_bps": 6.0, "p90_displayed_spread_bps": 12.0},
    ]
    result = E._build_daily_rows(
        Panel, [event], {}, {},
        {"id": "FIXED_H30__UNFILTERED", "exit_rule": "FIXED_H30", "population": "UNFILTERED"},
        buckets,
    )
    audit = result["audit_rows"][0]
    assert audit["exit_reason"] == "H30"
    assert audit["exit_time_pacific"] == "07:15 Pacific"
    assert audit["cost_base_bps"] == 8.0
    assert audit["matched_control_dates"] == 2
    assert audit["matched_control_opportunities"] == 30
    assert result["unresolved_rows"] == []
