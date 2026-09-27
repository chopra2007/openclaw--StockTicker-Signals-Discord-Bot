import importlib.util
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "scripts/research/trading_edge_analysis.py"
SPEC = importlib.util.spec_from_file_location("trading_edge_analysis", MODULE_PATH)
A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)


def _event(day, symbol, value, control="K", block="B1", panel=0.0, cell="CELL"):
    return {
        "cell_id": cell, "setting_id": cell, "family": "family",
        "symbol": symbol, "date": day, "block": block, "direction": "long",
        "horizon_minutes": 30, "control_key": control,
        "signed_return": value, "signed_loo_panel_return": panel,
    }


def _control(day, value, control="K", panel=0.0):
    return {
        "control_key": control, "date": day, "signed_return": value,
        "signed_loo_panel_return": panel,
    }


def test_plain_excess_averages_control_minutes_within_date_then_dates_equally():
    events = [_event("2024-01-02", "AAA", 0.03)]
    controls = [
        _control("2024-01-02", 0.00),
        _control("2024-01-02", 0.02),
        _control("2024-01-03", 0.03),
    ]
    # Daily controls are 1% and 3%; their equal-date mean is 2%.
    result = A.date_first_plain_excess(events, controls)
    assert result[0]["plain_excess"] == pytest.approx(0.01)


def test_date_first_gives_busy_and_quiet_dates_equal_weight():
    controls = [_control("2024-01-01", 0.0)]
    events = [
        _event("2024-01-02", "AAA", 0.01),
        _event("2024-01-02", "BBB", 0.03),
        _event("2024-01-03", "AAA", -0.02),
    ]
    daily = A.date_first_plain_excess(events, controls)
    assert [row["plain_excess"] for row in daily] == pytest.approx([0.02, -0.02])
    assert sum(row["plain_excess"] for row in daily) / 2 == pytest.approx(0.0)


def test_market_adjusted_residual_uses_leave_one_stock_out_on_both_sides():
    events = [_event("2024-01-02", "AAA", 0.04, panel=0.01)]
    controls = [
        _control("2024-01-02", 0.03, panel=0.01),
        _control("2024-01-03", 0.01, panel=0.01),
    ]
    result = A.leave_one_stock_out_residual_excess(events, controls)
    # Event residual 3%; daily control residuals 2% and 0%, mean 1%.
    assert result[0]["market_adjusted_excess"] == pytest.approx(0.02)


def test_five_blocks_include_empty_blocks_and_report_sign():
    rows = [
        {"block": "B1", "date": "2023-04-03", "x": 0.01},
        {"block": "B2", "date": "2023-07-03", "x": -0.01},
    ]
    result = A.five_block_summaries(rows, "x")
    assert [row["block"] for row in result] == ["B1", "B2", "B3", "B4", "B5"]
    assert result[0]["positive"] is True
    assert result[1]["positive"] is False
    assert result[2]["mean"] is None


def test_five_blocks_do_not_mix_cells():
    rows = [
        {"cell_id": "A", "block": "B1", "date": "2023-04-03", "x": 0.01},
        {"cell_id": "B", "block": "B1", "date": "2023-04-03", "x": -0.01},
    ]
    result = A.five_block_summaries(rows, "x")
    assert len(result) == 10
    assert result[0]["cell_id"] == "A" and result[0]["mean"] == pytest.approx(0.01)
    assert result[5]["cell_id"] == "B" and result[5]["mean"] == pytest.approx(-0.01)


def test_remove_top_three_positive_symbol_days_is_deterministic():
    rows = [
        {"symbol": symbol, "date": "2024-01-02", "x": value}
        for symbol, value in zip("ABCDE", [0.05, 0.04, 0.03, 0.02, -0.01])
    ]
    result = A.remove_top_three_positive_symbol_days(rows, "x")
    assert [row["symbol"] for row in result["removed_symbol_days"]] == ["A", "B", "C"]
    assert result["remaining_mean"] == pytest.approx(0.005)
    assert result["remains_positive"] is True


def test_week_bootstrap_is_fixed_seed_and_recomputes_controls():
    events = [
        _event("2024-01-02", "AAA", 0.03),
        _event("2024-01-09", "AAA", 0.01),
        _event("2024-01-16", "AAA", 0.02),
    ]
    controls = [
        _control("2024-01-02", 0.01),
        _control("2024-01-09", 0.00),
        _control("2024-01-16", 0.01),
    ]
    first = A.week_cluster_bootstrap(events, controls, draws=200, seed=7)
    second = A.week_cluster_bootstrap(events, controls, draws=200, seed=7)
    assert first == second
    assert first["draws_resolved"] == 200
    assert first["lower_80"] <= first["median"] <= first["upper_80"]


def test_week_bootstrap_preserves_repeated_week_weighting_for_both_metrics():
    events = []
    controls = []
    for day, value, control in (
        ("2024-01-02", 0.03, 0.01),
        ("2024-01-03", 0.01, 0.02),
        ("2024-01-09", 0.04, 0.015),
        ("2024-01-16", -0.01, 0.005),
    ):
        events.extend((
            _event(day, "AAA", value, panel=value / 2),
            _event(day, "BBB", value + 0.002, panel=value / 2 + 0.001),
        ))
        controls.append(_control(day, control, panel=control / 2))

    plain = A.week_cluster_bootstrap(events, controls, draws=37, seed=19)
    market = A.week_cluster_bootstrap(
        events, controls, metric="market_adjusted", draws=37, seed=19
    )

    assert plain["lower_80"] == pytest.approx(-0.00013333333333333182)
    assert plain["median"] == pytest.approx(0.006000000000000002)
    assert plain["upper_80"] == pytest.approx(0.012133333333333336)
    assert market["lower_80"] == pytest.approx(-0.00006666666666666591)
    assert market["median"] == pytest.approx(0.003000000000000001)
    assert market["upper_80"] == pytest.approx(0.006066666666666668)


def test_power_table_has_registered_effects_and_less_data_for_larger_effect():
    rows = [
        {"date": f"2024-01-{day:02d}", "x": value}
        for day, value in zip(range(2, 10), [0.01, 0.01, 0.01, 0.01, -0.01, -0.01, -0.01, -0.01])
    ]
    result = A.power_day_week_estimates(rows, "x")
    assert [row["effect_bps"] for row in result] == [3, 5, 8, 12]
    assert result[0]["required_days"] > result[-1]["required_days"]
    assert result[0]["required_weeks"] > result[-1]["required_weeks"]


def test_benjamini_hochberg_qvalues_are_monotone_by_p_value():
    result = A.benjamini_hochberg_qvalues([
        {"cell_id": "C", "p_value": 0.03},
        {"cell_id": "A", "p_value": 0.01},
        {"cell_id": "B", "p_value": 0.04},
    ])
    by_cell = {row["cell_id"]: row["bh_q_value"] for row in result}
    assert by_cell == pytest.approx({"A": 0.03, "B": 0.04, "C": 0.04})


def test_registered_cost_floor_and_stresses():
    assert A.registered_cost_floor_bps(570, 629, 570) == 8
    assert A.registered_cost_floor_bps(630, 660, 570) == 5
    assert A.registered_cost_stresses(8) == {
        "floor_bps": 8, "stress_20_bps": 20, "stress_twice_floor_bps": 16,
    }
    # Equal costs cancel in excess, while each raw ledger is charged once.
    assert A.actual_net_excess([0.01], [8], [0.005], [8]) == pytest.approx(0.005)


def test_effective_groups_join_identical_decisions_and_retain_labels():
    rows = []
    for setting in ("S1", "S2"):
        rows.append({
            "setting_id": setting, "symbol": "AAA", "date": "2024-01-02",
            "direction": "long", "signal_minute": 600,
        })
    rows.append({
        "setting_id": "S3", "symbol": "BBB", "date": "2024-01-02",
        "direction": "long", "signal_minute": 601,
    })
    groups = A.effective_variant_groups(rows)
    assert groups[0]["attempted_setting_ids"] == ["S1", "S2"]
    assert groups[1]["attempted_setting_ids"] == ["S3"]


def test_effective_groups_count_zero_decision_settings_once():
    groups = A.effective_variant_groups([], attempted_settings=["EMPTY_B", "EMPTY_A"])
    assert groups[0]["attempted_setting_ids"] == ["EMPTY_A", "EMPTY_B"]
    assert groups[0]["decision_count"] == 0


def test_top_five_obeys_family_and_decision_caps_with_stable_ties():
    candidates = [
        {"setting_id": "S1", "direction": "long", "family": "F1",
         "decision_group": "G1", "selection_lower_80": 0.06},
        {"setting_id": "S2", "direction": "long", "family": "F1",
         "decision_group": "G1", "selection_lower_80": 0.05},
        {"setting_id": "S3", "direction": "long", "family": "F1",
         "decision_group": "G3", "selection_lower_80": 0.04},
        {"setting_id": "S4", "direction": "long", "family": "F1",
         "decision_group": "G4", "selection_lower_80": 0.03},
        {"setting_id": "S5", "direction": "long", "family": "F2",
         "decision_group": "G5", "selection_lower_80": -0.01},
        {"setting_id": "S6", "direction": "long", "family": "F3",
         "decision_group": "G6", "selection_lower_80": -0.01},
        {"setting_id": "S7", "direction": "long", "family": "F4",
         "decision_group": "G7", "selection_lower_80": -0.02},
    ]
    selected = A.deterministic_top_five(candidates)
    assert [row["setting_id"] for row in selected] == ["S1", "S3", "S5", "S6", "S7"]
    assert [row["selection_rank"] for row in selected] == [1, 2, 3, 4, 5]
