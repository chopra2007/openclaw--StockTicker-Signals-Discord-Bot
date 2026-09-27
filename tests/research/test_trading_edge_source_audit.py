import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest


REPO = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "scripts/research/trading_edge_source_audit.py"
SPEC = importlib.util.spec_from_file_location("trading_edge_source_audit", MODULE_PATH)
S = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = S
SPEC.loader.exec_module(S)


def _bars(day1_close=100.0, day2_open=101.0):
    return pd.DataFrame([
        {"symbol": "ABC", "date": "2023-04-03", "minute": 570, "open": 99.0, "close": 99.5, "volume": 10},
        {"symbol": "ABC", "date": "2023-04-03", "minute": 571, "open": 99.5, "close": day1_close, "volume": 11},
        {"symbol": "ABC", "date": "2023-04-04", "minute": 570, "open": day2_open, "close": 101.5, "volume": 12},
        {"symbol": "ABC", "date": "2023-04-04", "minute": 571, "open": 101.5, "close": 102.0, "volume": 13},
    ])


SCHEDULE = {"2023-04-03": [570, 571], "2023-04-04": [570, 571]}


def test_known_unadjusted_action_is_recorded_excluded_and_resets_references():
    bars = _bars()
    original = bars.copy(deep=True)
    actions = pd.DataFrame([{
        "symbol": "ABC", "date": "2023-04-04", "action_type": "split",
        "value": 2.0, "source": "fixture-actions", "adjustment_compatible": False,
    }])
    result = S.audit_source_rows(bars, SCHEDULE, actions)
    day = result.symbol_days.set_index("date").loc["2023-04-04"]

    pd.testing.assert_frame_equal(bars, original)
    pd.testing.assert_frame_equal(
        result.rows[list(original.columns)], original, check_dtype=True
    )
    assert day["exclude"]
    assert day["reference_reset"]
    assert day["reference_epoch"] == 1
    assert day["reasons"] == ["KNOWN_CORPORATE_ACTION", "UNPROVEN_ACTION_ADJUSTMENT"]
    assert day["corporate_actions"][0]["source"] == "fixture-actions"
    assert S.excluded_symbol_days(result.mask_record) == {("ABC", "2023-04-04")}


def test_proven_compatible_action_is_audited_without_forcing_exclusion():
    actions = pd.DataFrame([{
        "symbol": "ABC", "date": "2023-04-04", "action_type": "dividend",
        "source": "fixture-actions", "adjustment_compatible": True,
    }])
    day = S.audit_source_rows(_bars(), SCHEDULE, actions).symbol_days.iloc[1]
    assert not day["exclude"]
    assert not day["reference_reset"]
    assert day["reasons"] == ["KNOWN_CORPORATE_ACTION"]


def test_blank_compatibility_is_not_treated_as_proof():
    actions = pd.DataFrame([{
        "symbol": "ABC", "date": "2023-04-04", "action_type": "split",
        "source": "fixture-actions", "adjustment_compatible": None,
    }])
    day = S.audit_source_rows(_bars(), SCHEDULE, actions).symbol_days.iloc[1]
    assert day["exclude"]
    assert day["reference_reset"]
    assert "UNPROVEN_ACTION_ADJUSTMENT" in day["reasons"]


def test_extreme_gap_is_bucketed_and_round_factor_is_conservatively_masked():
    result = S.audit_source_rows(_bars(day1_close=100.0, day2_open=50.0), SCHEDULE)
    day = result.symbol_days.iloc[1]
    assert day["overnight_gap_bps"] == pytest.approx(-5_000)
    assert day["overnight_gap_bucket"] == "GE_20PCT"
    assert day["extreme_overnight_gap"]
    assert day["suspected_split_factor"] == 2.0
    assert day["exclude"]
    assert day["reasons"] == ["EXTREME_OVERNIGHT_GAP", "SUSPECTED_SPLIT_DISCONTINUITY"]


def test_extreme_non_split_gap_is_tagged_but_not_removed_by_gap_alone():
    day = S.audit_source_rows(_bars(day1_close=100.0, day2_open=73.0), SCHEDULE).symbol_days.iloc[1]
    assert day["overnight_gap_bucket"] == "GE_20PCT"
    assert day["extreme_overnight_gap"]
    assert day["suspected_split_factor"] is None
    assert not day["exclude"]
    assert day["reasons"] == ["EXTREME_OVERNIGHT_GAP"]


def test_missing_and_duplicate_minutes_create_a_deterministic_governed_mask():
    bars = _bars().drop(index=3)
    bars = pd.concat([bars, bars.iloc[[2]]], ignore_index=True)
    first = S.audit_source_rows(bars, SCHEDULE)
    second = S.audit_source_rows(bars.sample(frac=1, random_state=7), SCHEDULE)
    day = first.symbol_days.iloc[1]

    assert day["missing_minutes"] == [571]
    assert day["duplicate_minutes"] == [570]
    assert day["coverage_ratio"] == pytest.approx(0.5)
    assert day["exclude"]
    assert day["reasons"] == ["DUPLICATE_SCHEDULED_MINUTES", "MISSING_SCHEDULED_MINUTES"]
    assert first.mask_record == second.mask_record
    assert json.dumps(first.mask_record, sort_keys=True, allow_nan=False)
    assert len(first.rows) == len(bars)


def test_schedule_helper_matches_dense_panel_clock_contract():
    schedule = S.schedule_from_lengths(
        ["2023-04-03", "2023-07-03"], [390, 210], open_minute=570
    )
    assert schedule["2023-04-03"] == tuple(range(570, 960))
    assert schedule["2023-07-03"] == tuple(range(570, 780))
    assert S.gap_bucket(1_999.9) == "10_TO_20PCT"
    assert S.gap_bucket(2_000.0) == "GE_20PCT"
