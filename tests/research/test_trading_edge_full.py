import importlib.util
from pathlib import Path

import numpy as np
import pytest


REPO = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO / "scripts/research"


def _load(name):
    import sys
    sys.path.insert(0, str(SCRIPT_DIR))
    path = SCRIPT_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


F = _load("trading_edge_full")


def _panel(symbols=("CRM", "ORCL"), days=21):
    shape = (len(symbols), days, F.MAX_MINUTES)
    arrays = [np.full(shape, np.nan, dtype=np.float32) for _ in range(5)]
    panel = F.DensePanel(
        tuple(symbols), [f"2023-04-{day:02d}" for day in range(1, days + 1)],
        np.full(days, 390, dtype=np.int16), np.full(days, 960, dtype=np.int16),
        *arrays,
    )
    return panel


def test_dense_rvol_never_skips_a_missing_prior_window():
    panel = _panel()
    panel.v[:, :, :5] = 100
    panel.v[0, 4, 2] = np.nan
    values, status = F._rolling_rvol(panel, 5)
    assert np.isnan(values[0, 20])
    assert status[0, 20] == "one_or_more_exact_prior_windows_missing"
    assert values[1, 20] == pytest.approx(1.0)
    assert status[1, 20] == "available"


def test_compact_control_sums_reproduce_expanded_daily_mean(tmp_path):
    panel = _panel(days=2)
    panel.dates = ["2023-04-03", "2023-04-04"]
    panel.o[0, :, :15] = 100
    panel.c[0, :, 4:19] = 101
    loo = {5: np.full((2, 2, 386), np.nan, dtype=np.float32)}
    group = "CRM|B1|5|regular|BIN00"
    responses = [{"control_group_id": group}]
    sink = F.JsonlSink(tmp_path / "controls.jsonl")
    stats, daily = F._control_daily(panel, responses, loo, sink)
    count, _ = sink.close()
    rows = [F.json.loads(line) for line in (tmp_path / "controls.jsonl").read_text().splitlines()]
    assert count == 2
    expanded_daily = [row["sum_raw_return"] / row["opportunity_count"] for row in rows]
    assert stats[group]["raw"] == pytest.approx(sum(expanded_daily) / len(expanded_daily))
    assert [item[1] for item in daily[group]] == pytest.approx(expanded_daily)


def test_exact_minute_sensitivity_is_computed_without_repeating_daily_ledger(tmp_path):
    panel = _panel(days=2)
    panel.dates = ["2023-04-03", "2023-04-04"]
    panel.o[0, :, 2] = 100
    panel.c[0, :, 6] = 101
    loo = {5: np.full((2, 2, 386), np.nan, dtype=np.float32)}
    group = "CRM|B1|5|regular|MIN002"
    sink = F.JsonlSink(tmp_path / "controls.jsonl")
    stats, daily = F._control_daily(panel, [{"exact_control_group_id": group}], loo, sink)
    count, _ = sink.close()
    assert count == 0
    assert stats[group]["raw"] == pytest.approx(0.01)
    assert len(daily[group]) == 2


def test_market_loo_requires_every_frozen_constituent_path():
    panel = _panel(days=2)
    panel.o[:, 1, 0] = 100
    panel.c[:, 1, 4] = [101, 102]
    panel.c[:, 0, 0] = 100  # both names are known before day two
    values = F._market_loo(panel, {5})[5]
    assert values[0, 1, 0] == pytest.approx(0.02)
    assert values[1, 1, 0] == pytest.approx(0.01)
    panel.c[1, 1, 4] = np.nan
    values = F._market_loo(panel, {5})[5]
    assert np.isnan(values[:, 1, 0]).all()


def test_registered_full_output_names_are_stable():
    names = {
        "full-pre-return-audit.json",
        "full-events.jsonl", "full-responses.jsonl", "full-censors.jsonl",
        "full-control-daily.jsonl", "full-cell-summaries.jsonl",
        "full-daily-responses.jsonl",
        "full-effective-variants.json", "full-power-table.json",
        "full-ranked-discovery.csv", "full-trial-ledger.json", "full-summary.json",
    }
    assert len(names) == 12


def test_pre_return_audit_writes_numpy_scalars_as_strict_json(tmp_path):
    path = tmp_path / "full-pre-return-audit.json"
    audit_record = {
        "exclude": np.bool_(True),
        "raw_row_count": np.int64(390),
        "overnight_gap_bps": np.float32(12.5),
    }

    digest = F._write_json(path, audit_record)

    assert digest == F.R.sha256_file(path)
    assert F.json.loads(path.read_text()) == {
        "exclude": True,
        "raw_row_count": 390,
        "overnight_gap_bps": 12.5,
    }
    with pytest.raises(ValueError, match="Out of range float values"):
        F._write_json(tmp_path / "invalid.json", {"value": np.float32(np.nan)})


def test_response_exit_never_passes_close_minus_five_on_short_session():
    panel = _panel(symbols=("CRM",), days=2)
    panel.dates = ["2023-04-03", "2023-04-04"]
    panel.lengths[:] = 210
    panel.closes[:] = 780
    for array in (panel.o, panel.h, panel.l, panel.c):
        array[:, :, :210] = 100
    panel.v[:, :, :210] = 100
    _event, responses, censors = F._event_and_responses(
        panel, 0, 1, "OR5_VOL_OFF", "long", 175
    )
    assert responses
    assert all(row["exit_col"] <= 204 for row in responses)
    assert any(row["reason"] == "MISSING_OR_LATER_THAN_CLOSE_MINUS_FIVE" for row in censors)


def test_missing_bar_blocks_later_opening_range_first_event():
    panel = _panel(symbols=("CRM",), days=21)
    for array in (panel.o, panel.h, panel.l, panel.c):
        array[:, :, :390] = 100
    panel.v[:, :, :390] = 100
    # Missing close before a later apparent long cross makes first-event identity unknowable.
    panel.c[0, 20, 6] = np.nan
    panel.c[0, 20, 7] = 101
    found, reasons = F._scan_day(panel, 0, 20, 1.0, 1.0)
    assert ("OR5_VOL_OFF", "long") not in found
    assert reasons[("OR5_VOL_OFF", "long")] == "MISSING_BAR_BEFORE_FIRST_EVENT"


def test_split_and_degraded_reference_masks_are_governed():
    dates, lengths, closes = F._calendar("2024-06-03", "2025-03-31")
    panel = F.DensePanel(
        ("APH", "CRM"), dates, lengths, closes,
        *[np.zeros((2, len(dates), F.MAX_MINUTES), dtype=np.float32) for _ in range(5)],
    )
    values = np.ones((2, len(dates)), dtype=np.float32)
    status = np.full(values.shape, "available", dtype=object)
    F._apply_reference_masks(panel, values, status)
    split = dates.index("2024-06-12")
    degraded = dates.index("2025-03-24")
    assert np.isnan(values[0, split:split + 21]).all()
    assert status[0, split] == "split_reference_reset"
    assert np.isnan(values[:, degraded:]).all()
    assert status[1, degraded] == "degraded_reference_reset"


def test_source_audit_governs_known_split_before_returns():
    panel = _panel(symbols=("APH",), days=2)
    panel.dates = ["2024-06-11", "2024-06-12"]
    panel.row_counts = np.ones((1, 2, F.MAX_MINUTES), dtype=np.uint8)
    panel.o[:, :, :] = 100
    panel.c[:, :, :] = 100
    record, governed, gaps = F._audit_panel(panel)
    assert ("APH", "2024-06-12") in governed
    assert "UNPROVEN_ACTION_ADJUSTMENT" in governed[("APH", "2024-06-12")]
    assert gaps[("APH", "2024-06-12")]["reference_reset"] is True
    assert record["runner_sha256"] == F.R.sha256_file(Path(F.__file__).resolve())


def test_missing_minute_is_recorded_but_not_globally_future_masked():
    panel = _panel(symbols=("CRM",), days=2)
    panel.dates = ["2024-06-11", "2024-06-12"]
    panel.row_counts = np.ones((1, 2, F.MAX_MINUTES), dtype=np.uint8)
    panel.row_counts[0, 1, 200] = 0
    panel.o[:, :, :] = 100
    panel.c[:, :, :] = 100
    record, governed, _gaps = F._audit_panel(panel)
    row = next(item for item in record["symbol_days"] if item["date"] == "2024-06-12")
    assert row["exclude"] is True
    assert row["missing_minutes"] == [F.OPEN_MINUTE + 200]
    assert ("CRM", "2024-06-12") not in governed


def test_split_mask_reaches_signals_controls_market_and_pullback_history(tmp_path):
    dates, lengths, closes = F._calendar("2024-05-20", "2024-07-05")
    panel = F.DensePanel(
        ("APH", "CRM", "ORCL"), dates, lengths, closes,
        *[np.full((3, len(dates), F.MAX_MINUTES), 100.0, dtype=np.float32)
          for _ in range(5)],
    )
    panel.v[:] = 100
    split = dates.index("2024-06-12")
    panel.excluded_days = np.zeros((3, len(dates)), dtype=bool)
    panel.reference_reset_days = np.zeros((3, len(dates)), dtype=bool)
    panel.excluded_days[0, split] = True
    panel.reference_reset_days[0, split] = True

    found, reasons = F._scan_day(panel, 0, split, 1.0, 1.0)
    assert found == {}
    assert set(reasons.values()) == {"PRE_RETURN_MASK_GOVERNED_DAY"}

    group = "APH|B3|5|regular|MIN000"
    sink = F.JsonlSink(tmp_path / "controls.jsonl")
    stats, daily = F._control_daily(
        panel, [{"exact_control_group_id": group}], F._market_loo(panel, {5}), sink
    )
    sink.close()
    assert "2024-06-12" not in {row[0] for row in daily[group]}

    loo = F._market_loo(panel, {5})[5]
    assert np.isnan(loo[0, split]).all()
    assert np.isfinite(loo[1, split, 0])

    setting = next(item for item in F.R.SETTINGS if item["family"] == "first_pullback")
    assert F._first_pullback_dense(panel, 0, split + 15, setting, "long")[1] == (
        "FIRST_PULLBACK_REQUIRED_HISTORY_UNAVAILABLE"
    )
    assert F._reference_window_is_clean(panel, 0, split + 1, split + 16)
    assert F._overnight_gap(panel, 0, split + 1) == (None, "unavailable")


def test_degraded_day_is_excluded_from_signals_controls_market_and_references(tmp_path):
    dates, lengths, closes = F._calendar("2025-02-24", "2025-03-31")
    panel = F.DensePanel(
        ("CRM", "ORCL"), dates, lengths, closes,
        *[np.full((2, len(dates), F.MAX_MINUTES), 100.0, dtype=np.float32)
          for _ in range(5)],
    )
    audit_record = {"symbol_days": [
        {"symbol": symbol, "date": day, "reference_reset": False}
        for symbol in panel.symbols for day in panel.dates
    ]}
    F._install_governed_masks(panel, audit_record, {})
    degraded = dates.index("2025-03-24")
    assert panel.excluded_days[:, degraded].all()
    assert panel.reference_reset_days[:, degraded].all()

    found, reasons = F._scan_day(panel, 1, degraded, 1.0, 1.0)
    assert found == {}
    assert set(reasons.values()) == {"PRE_RETURN_MASK_GOVERNED_DAY"}

    group = "ORCL|B5|5|regular|MIN000"
    loo = F._market_loo(panel, {5})
    sink = F.JsonlSink(tmp_path / "controls.jsonl")
    _stats, daily = F._control_daily(
        panel, [{"exact_control_group_id": group}], loo, sink
    )
    sink.close()
    assert "2025-03-24" not in {row[0] for row in daily[group]}
    assert np.isnan(loo[5][:, degraded]).all()

    values = np.ones((2, len(dates)), dtype=np.float32)
    status = np.full(values.shape, "available", dtype=object)
    F._apply_reference_masks(panel, values, status)
    assert np.isnan(values[:, degraded:]).all()
    assert not F._reference_window_is_clean(panel, 1, degraded, degraded + 1)
    assert F._overnight_gap(panel, 1, degraded + 1) == (None, "unavailable")


def test_bootstrap_checkpoint_round_trip_and_stale_rejection(tmp_path):
    path = tmp_path / "CELL.json"
    record = {
        "version": F.BOOTSTRAP_CHECKPOINT_VERSION,
        "context_sha256": "a" * 64,
        "cell_id": "CELL",
        "seed": 17,
        "draws": 1000,
        "plain_bootstrap": {"lower_80": 0.1},
        "score_bootstrap": {"lower_80": 0.2},
        "market_bootstrap": None,
    }
    F._write_bootstrap_checkpoint(path, record)
    assert F._load_bootstrap_checkpoint(
        path, "a" * 64, "CELL", 17, 1000
    ) == (
        record["plain_bootstrap"], record["score_bootstrap"], None
    )
    assert F._load_bootstrap_checkpoint(path, "b" * 64, "CELL", 17, 1000) is None
    assert F._load_bootstrap_checkpoint(path, "a" * 64, "OTHER", 17, 1000) is None
    assert F._load_bootstrap_checkpoint(path, "a" * 64, "CELL", 18, 1000) is None
    assert F._load_bootstrap_checkpoint(path, "a" * 64, "CELL", 17, 100) is None
    path.write_text("{truncated")
    assert F._load_bootstrap_checkpoint(path, "a" * 64, "CELL", 17, 1000) is None


def test_cell_bootstrap_reuses_complete_checkpoint_without_recomputing(
    tmp_path, monkeypatch
):
    cell_id = "CELL"
    draws = 1000
    seed = F.SEED + int(F.hashlib.sha256(cell_id.encode()).hexdigest()[:8], 16)
    expected = ({"lower_80": 0.1}, {"lower_80": 0.2}, {"lower_80": 0.3})
    F._write_bootstrap_checkpoint(tmp_path / f"{cell_id}.json", {
        "version": F.BOOTSTRAP_CHECKPOINT_VERSION,
        "context_sha256": "c" * 64,
        "cell_id": cell_id,
        "seed": seed,
        "draws": draws,
        "plain_bootstrap": expected[0],
        "score_bootstrap": expected[1],
        "market_bootstrap": expected[2],
    })

    def unexpected(*_args, **_kwargs):
        raise AssertionError("valid checkpoint should skip bootstrap work")

    monkeypatch.setattr(F.A, "week_cluster_bootstrap", unexpected)
    assert F._cell_bootstraps(
        cell_id, [], [], [], draws, tmp_path, "c" * 64
    ) == expected


def test_cell_bootstrap_does_not_save_partial_work(tmp_path, monkeypatch):
    calls = 0

    def fail_second(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected failure")
        return {"lower_80": 0.1}

    monkeypatch.setattr(F.A, "week_cluster_bootstrap", fail_second)
    with pytest.raises(RuntimeError, match="injected failure"):
        F._cell_bootstraps(
            "CELL", [{"date": "2024-01-02"}], [], [], 10,
            tmp_path, "d" * 64,
        )
    assert not (tmp_path / "CELL.json").exists()
    assert not (tmp_path / "CELL.json.tmp").exists()
