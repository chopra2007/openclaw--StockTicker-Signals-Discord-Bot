import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest


REPO = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "scripts/research/trading_edge_quote_cost_report.py"
SPEC = importlib.util.spec_from_file_location("trading_edge_quote_cost_report", MODULE_PATH)
Q = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = Q
SPEC.loader.exec_module(Q)


def _write_quotes(path: Path) -> None:
    rows = [
        {"market_date": "2026-09-01", "captured_at_utc": "2026-09-01T13:30:10+00:00", "ticker": "CRM", "bid": 99.9, "ask": 100.1, "quote_time": 1788269400},
        {"market_date": "2026-09-01", "captured_at_utc": "2026-09-01T13:59:50+00:00", "ticker": "NOW", "bid": 199.8, "ask": 200.2, "quote_time": 1788271180},
        {"market_date": "2026-09-01", "captured_at_utc": "2026-09-01T14:30:00+00:00", "ticker": "ORCL", "bid": 49.9, "ask": 50.1, "quote_time": 1788273005},
        {"market_date": "2026-09-01", "captured_at_utc": "2026-09-01T15:00:00+00:00", "ticker": "CRM", "bid": 101.0, "ask": 100.0, "quote_time": 1788274800},
        {"market_date": "2026-09-01", "captured_at_utc": "2026-09-01T15:30:00+00:00", "ticker": "SPY", "bid": 500.0, "ask": 500.1, "quote_time": 1788276600},
    ]
    pq.write_table(pa.Table.from_pylist(rows), path)


def test_reads_only_three_symbols_at_parquet_read_time(tmp_path, monkeypatch):
    source = tmp_path / "quotes"
    source.mkdir()
    path = source / "2026-09-01.parquet"
    _write_quotes(path)
    pq.write_table(pa.Table.from_pylist([{"ticker": "SPY"}]), source / "2026-09-26.parquet")
    calls = []
    original = Q.pq.read_table

    def recording_read_table(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(Q.pq, "read_table", recording_read_table)
    files = Q.source_files(source)
    quotes, fingerprints = Q.read_selected_quotes(files)

    assert [item.name for item in files] == ["2026-09-01.parquet"]
    assert calls == [{"columns": list(Q.SOURCE_COLUMNS), "filters": [("ticker", "in", list(Q.SYMBOLS))]}]
    assert sorted(quotes["ticker"].unique()) == ["CRM", "NOW", "ORCL"]
    assert fingerprints[0]["selected_rows"] == 4


def test_report_uses_pacific_capture_buckets_valid_quotes_and_lag_window(tmp_path):
    source = tmp_path / "quotes"
    source.mkdir()
    _write_quotes(source / "2026-09-01.parquet")
    quotes, fingerprints = Q.read_selected_quotes(Q.source_files(source))
    report = Q.build_report(quotes, fingerprints)

    overall = report["results"]["regular_session_overall"]
    first_hour = report["results"]["first_regular_session_hour"]
    assert overall["row_count"] == 3
    assert first_hour["row_count"] == 2
    assert overall["median_displayed_spread_bps"] == pytest.approx(20.0)
    assert first_hour["median_displayed_spread_bps"] == pytest.approx(20.0)
    assert [item["bucket_start_pacific"] for item in report["results"]["thirty_minute_buckets"]] == ["06:30", "07:30"]
    assert report["completeness"]["crossed_quote_rows"] == 1
    assert report["scope"]["provider_quote_time_unit_detected"] == "s"
    assert report["completeness"]["missing_session_dates"] == [
        day for day in Q.expected_session_dates() if day != "2026-09-01"
    ]


def test_lag_boundaries_are_inclusive_and_outside_rows_are_counted():
    base = {
        "market_date": "2026-09-01", "ticker": "CRM", "bid": 99.0, "ask": 101.0,
        "_source_file": "2026-09-01.parquet",
    }
    quotes = pd.DataFrame([
        {**base, "captured_at_utc": "2026-09-01T14:00:00+00:00", "quote_time": 1788271215},
        {**base, "captured_at_utc": "2026-09-01T14:01:00+00:00", "quote_time": 1788271200},
        {**base, "captured_at_utc": "2026-09-01T14:02:00+00:00", "quote_time": 1788271259},
        {**base, "captured_at_utc": "not-a-time", "quote_time": 1788271259},
    ])
    report = Q.build_report(quotes, [{"file": "2026-09-01.parquet", "bytes": 1, "sha256": "x", "selected_rows": 4}])
    assert report["results"]["regular_session_overall"]["row_count"] == 2
    assert report["completeness"]["regular_session_rows_outside_lag_window"] == 1
    assert report["completeness"]["invalid_timestamp_rows"] == 1


def test_json_and_sidecar_are_deterministic(tmp_path):
    output = tmp_path / "report.json"
    report = {"z": 2, "a": [1, 3]}
    Q.write_report(report, output)
    first = output.read_bytes()
    Q.write_report(report, output)
    assert output.read_bytes() == first
    expected = hashlib.sha256(first).hexdigest()
    assert output.with_name("report.json.sha256").read_text() == f"{expected}  report.json\n"
    assert json.loads(first) == report
