import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from scripts.research import captured_population_probes as probes


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    mask_path = tmp_path / "masks.json"
    panel = ["PANEL"] + [f"P{i:02d}" for i in range(58)]
    mask_path.write_text(json.dumps({
        "development": {"permitted_symbols": panel},
        "sealed": {"d107_symbols_and_aliases": [
            "GOOGL", "AMZN", "META", "AVGO", "BRK.B", "IWM", "GLD", "VXX"
        ]},
    }))

    db_path = tmp_path / "probe.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE decision_snapshots (
            id INTEGER PRIMARY KEY, ticker TEXT, decision TEXT, final_score REAL,
            recorded_at REAL, outcome_price_at_alert REAL, outcome_price_1h REAL,
            outcome_price_24h REAL, outcome_price_5d REAL, outcome_price_20d REAL
        );
        CREATE TABLE options_flow (
            id INTEGER PRIMARY KEY, ticker TEXT, detected_at REAL, last_trade_ts REAL
        );
        CREATE TABLE options_flow_outcomes (
            flow_id INTEGER PRIMARY KEY, market_date TEXT, close_0d REAL,
            close_1d REAL, close_5d REAL, bench_close_0d REAL,
            bench_close_1d REAL, bench_close_5d REAL, graded_at REAL
        );
    """)
    decisions = [
        (1, "AAA", "ALERT", 80, 1_700_000_000, 100, 101, 102, 110, 120),
        (2, "BBB", "NO_ALERT", 79, 1_700_000_100, 100, 99, 98, 95, 90),
        (3, "PANEL", "ALERT", 99, 1_700_000_200, 1, 10, 10, 100, 100),
        (4, "BRK B", "ALERT", 99, 1_700_000_300, 1, 10, 10, 100, 100),
        (5, "CCC", "NO_ALERT", 60, 1_700_086_400, 100, None, None, None, None),
    ]
    conn.executemany("INSERT INTO decision_snapshots VALUES (?,?,?,?,?,?,?,?,?,?)", decisions)
    flow = [
        (1, "AAA", 1_000, 1_000),
        (2, "BBB", 1_060, 1_000),
        (3, "CCC", 1_061, 1_000),
        (4, "DDD", 999, 1_000),
        (5, "PANEL", 1_001, 1_000),
        (6, "BRK.B", 1_001, 1_000),
        (7, "EEE", 1_030, 1_000),
    ]
    outcomes = [
        (1, "2026-01-02", 100, 110, 120, 100, 101, 102, 2_000),
        (2, "2026-01-02", 100, 105, 106, 100, 101, 102, 2_000),
        (3, "2026-01-03", 100, 90, 80, 100, 101, 102, 2_000),
        (4, "2026-01-03", 100, 200, 200, 100, 100, 100, 2_000),
        (5, "2026-01-04", 1, 100, 100, 1, 1, 1, 2_000),
        (6, "2026-01-04", 1, 100, 100, 1, 1, 1, 2_000),
    ]
    conn.executemany("INSERT INTO options_flow VALUES (?,?,?,?)", flow)
    conn.executemany("INSERT INTO options_flow_outcomes VALUES (?,?,?,?,?,?,?,?,?)", outcomes)
    conn.commit()
    conn.close()
    return db_path, mask_path


def test_exclusions_are_selected_before_separate_id_only_outcome_queries():
    assert "outcome_price" not in probes.DECISION_ELIGIBLE_SQL
    assert "options_flow_outcomes" not in probes.OPTIONS_ELIGIBLE_SQL
    assert "NOT IN" in probes.DECISION_ELIGIBLE_SQL
    assert "NOT IN" in probes.OPTIONS_ELIGIBLE_SQL


def test_report_uses_fixed_rules_and_labels_stock_outcomes_honestly(tmp_path):
    db_path, mask_path = _fixture(tmp_path)
    report = probes.build_report(db_path, mask_path, seed=7, resamples=200)
    a, b = report["probes"]

    assert report["exclusion_count"] == 68  # 59 panel + 8 D-107 + the BRK B alias
    assert a["captured_rows_after_exclusions"] == 3
    assert a["matured_five_session_rows"] == 2
    assert a["usable_five_session_rows"] == 2
    assert a["groups"]["score_at_least_80"]["captured_count"] == 1
    assert a["groups"]["score_below_80"]["captured_count"] == 2
    assert a["groups"]["score_at_least_80"]["count"] == 1
    assert a["groups"]["score_at_least_80"]["mean"] == pytest.approx(0.10)
    assert a["groups"]["score_below_80"]["mean"] == pytest.approx(-0.05)
    assert "not direction-adjusted" in a["outcome_label"]
    assert any("model version" in item for item in a["limitations"])

    assert b["eligible_rows_after_exclusions"] == 5
    assert b["matched_outcome_rows"] == 4
    assert b["eligible_tickers"] == 5
    assert b["matched_outcome_market_dates"] == 2
    assert b["valid_timestamp_rows"] == 4
    assert b["invalid_or_negative_delay_rows_excluded"] == 1
    assert b["timestamp_group_counts_before_outcome_availability"] == {
        "later_than_60_seconds": 1,
        "timely_0_to_60_seconds": 3,
    }
    assert b["coverage_by_timing"]["timely_0_to_60_seconds"] == {
        "eligible_count": 3,
        "matched_outcome_count": 2,
        "outcome_coverage": pytest.approx(2 / 3),
        "usable_one_session_count": 2,
        "usable_one_session_coverage": pytest.approx(2 / 3),
        "usable_five_session_count": 2,
        "usable_five_session_coverage": pytest.approx(2 / 3),
    }
    assert b["horizons"]["one_session"]["groups"]["timely_0_to_60_seconds"]["count"] == 2
    assert b["horizons"]["one_session"]["groups"]["later_than_60_seconds"]["count"] == 1
    assert "not option profit or loss" in b["outcome_label"]
    assert any("selection bias" in item for item in b["limitations"])
    assert a["uncertainty"]["standard_error"] is not None
    assert a["uncertainty"]["two_standard_error_verdict"] in {"ADVANCE", "PARK"}
    parked = probes.date_clustered_mean_difference(
        [("d1", "test", 1.0), ("d1", "comparison", 0.0),
         ("d2", "test", -1.0), ("d2", "comparison", 0.0)],
        "test", "comparison", seed=3, resamples=200,
    )
    assert parked["mean_difference"] == 0.0
    assert parked["standard_error"] > 0
    assert parked["two_standard_error_verdict"] == "PARK"


def test_output_is_deterministic_and_sidecar_matches(tmp_path):
    db_path, mask_path = _fixture(tmp_path)
    first = probes.build_report(db_path, mask_path, seed=11, resamples=100)
    second = probes.build_report(db_path, mask_path, seed=11, resamples=100)
    assert first == second

    output = tmp_path / "report.json"
    _, sidecar = probes.write_report(first, output)
    payload = output.read_bytes()
    assert json.loads(payload) == first
    assert sidecar.read_text().split()[0] == hashlib.sha256(payload).hexdigest()


def test_both_probes_share_one_read_snapshot(tmp_path, monkeypatch):
    db_path, mask_path = _fixture(tmp_path)
    writer = sqlite3.connect(db_path)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.close()
    original = probes.build_decision_probe

    def write_between_probes(conn, exclusions, **kwargs):
        result = original(conn, exclusions, **kwargs)
        external = sqlite3.connect(db_path)
        external.execute("INSERT INTO options_flow VALUES (8, 'LATE', 1030, 1000)")
        external.execute(
            "INSERT INTO options_flow_outcomes VALUES (8, '2026-01-05', 100, 101, 102, 100, 100, 100, 2000)"
        )
        external.commit()
        external.close()
        return result

    monkeypatch.setattr(probes, "build_decision_probe", write_between_probes)
    report = probes.build_report(db_path, mask_path, seed=2, resamples=20)
    assert report["probes"][1]["eligible_rows_after_exclusions"] == 5
    assert report["input_identity"]["watermarks"]["options_flow"]["row_count"] == 7


def test_sqlite_deadline_interrupts_work(tmp_path):
    db_path, mask_path = _fixture(tmp_path)
    with probes.open_read_only(db_path) as conn:
        probes.install_deadline(conn, 0, progress_ops=1)
        with pytest.raises(sqlite3.OperationalError, match="interrupted"):
            conn.execute("SELECT COUNT(*) FROM options_flow").fetchone()
    with pytest.raises(sqlite3.OperationalError, match="interrupted"):
        probes.build_report(
            db_path,
            mask_path,
            seed=1,
            resamples=1,
            sqlite_deadline_seconds=0,
            sqlite_progress_ops=1,
        )
