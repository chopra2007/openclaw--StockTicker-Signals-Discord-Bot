import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "scripts/research/trading_edge_registration.py"
SPEC = importlib.util.spec_from_file_location("trading_edge_registration", MODULE_PATH)
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def test_exact_registered_dimensions_and_universe():
    assert len(R.PERMITTED_SYMBOLS) == 59
    assert len(set(R.PERMITTED_SYMBOLS)) == 59
    assert "BRK.B" not in R.PERMITTED_SYMBOLS
    assert not set(R.PERMITTED_SYMBOLS) & set(R.D107_SYMBOLS)
    assert len(R.BLOCKS) == 5
    assert len(R.SETTINGS) == 16
    assert len(R.CELLS) == 126
    assert len({cell["id"] for cell in R.CELLS}) == 126


def test_cell_math_is_exact():
    regular = [item for item in R.SETTINGS if item["id"] != "LATE_CONTINUATION"]
    late = [item for item in R.SETTINGS if item["id"] == "LATE_CONTINUATION"]
    assert len(regular) == 15
    assert all(item["horizons_minutes"] == [5, 15, 30, 60] for item in regular)
    assert late[0]["horizons_minutes"] == [5, 15, 25]
    assert len(regular) * 2 * 4 + len(late) * 2 * 3 == 126


@pytest.mark.parametrize("alias", ["BRK.B", "BRK B", "BRK/B", "brk-b"])
def test_d107_aliases_are_rejected_before_reader_creation(alias, monkeypatch):
    called = False

    def fail_if_reader_is_created(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("reader was constructed")

    import pyarrow.dataset

    monkeypatch.setattr(pyarrow.dataset, "dataset", fail_if_reader_is_created)
    with pytest.raises(PermissionError, match="D-107"):
        list(R.guarded_parquet_batches(
            R.PRIMARY_SOURCE, [alias], "2024-01-02", "2024-01-03", ["close"]
        ))
    assert called is False


@pytest.mark.parametrize(
    "start,end",
    [
        ("2023-03-27", "2023-03-28"),
        ("2025-03-31", "2025-04-01"),
        ("2025-07-01", "2025-07-02"),
        ("2026-08-22", "2026-08-22"),
    ],
)
def test_any_date_outside_safe_prefix_is_rejected(start, end):
    with pytest.raises(PermissionError, match="restricted"):
        R.assert_permitted_row_request(["TSM"], start, end)


def test_masks_freeze_legacy_reserved_and_prospective_seals():
    instant = "2026-09-26T08:15:00-07:00"
    masks = R.build_masks(instant)
    sealed = masks["sealed"]
    assert sealed["legacy_time_window"] == {
        "first_date": "2025-07-01", "last_date_exclusive": "2026-08-22"
    }
    assert sealed["older_panel_profit_window"] == {
        "first_date": "2025-12-01", "last_date": "2026-08-21"
    }
    assert len(sealed["m9_1er_reserved_dates"]) == 16
    assert sealed["exposure_ambiguity_exclusion"] == {
        "first_date": "2026-08-22", "last_instant": instant
    }
    assert sealed["prospective_confirmation_epoch"]["first_instant"] == instant


def test_json_serialization_is_deterministic():
    value = {"z": [2, 1], "a": {"d": 4, "c": 3}}
    first = R._json_bytes(value)
    second = R._json_bytes(json.loads(first))
    assert first == second
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()
