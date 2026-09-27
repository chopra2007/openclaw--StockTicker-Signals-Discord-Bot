"""M9.1EP saved-market-data qualification contracts."""

import json
import os
from pathlib import Path
import sys

import pandas as pd
import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.saved_market_data_audit import GAP_DEPENDENT_RULES, audit_saved_market_data


def _write(path: Path, *, close_shift: float = 0.0, bad: bool = False) -> None:
    rows = []
    for date in ("2026-01-05", "2026-01-06"):
        for symbol in ("AAA", "BBB"):
            for minute in range(570, 960):
                close = 100.0 + close_shift + (minute - 570) / 100
                rows.append({
                    "date": date, "symbol": symbol, "minute": minute,
                    "open": close - 0.02, "high": close + 0.05,
                    "low": close - 0.05, "close": close, "volume": 100,
                })
    if bad:
        rows.pop()
        rows.append(dict(rows[-1]))
        rows[-1]["volume"] = -1
        rows[-1]["high"] = rows[-1]["low"] - 1
    pd.DataFrame(rows).to_parquet(path, index=False)


def test_audit_reports_coverage_defects_agreement_and_d104_gaps(tmp_path):
    left, right = tmp_path / "left.parquet", tmp_path / "right.parquet"
    _write(left, bad=True)
    _write(right, close_shift=0.01)

    result = audit_saved_market_data((left, right), sample_date_count=2)

    assert result["mode"] == "READ_ONLY_OFFLINE_INVENTORY"
    assert result["files"][0]["rows"] == 1560
    assert result["files"][0]["duplicate_keys"] == 1
    assert result["files"][0]["negative_volume_rows"] == 1
    assert result["files"][0]["invalid_ohlc_rows"] == 1
    assert result["files"][0]["incomplete_symbol_dates"] == 1
    assert result["files"][1]["complete_390_minute_symbol_dates"] == 4
    assert result["cross_dataset_agreement"]["overlapping_rows"] == 1560
    assert set(result["gaps"]) == set(GAP_DEPENDENT_RULES)
    assert all(row == {"status": "GAP", "dependent_rules": "OFF_UNTESTED"}
               for row in result["gaps"].values())
    assert not result["held_out_evaluation_run"]
    assert not result["promotion_or_live_release"]


def test_recorded_audit_is_deterministic_and_keeps_release_closed(tmp_path):
    left, right = tmp_path / "left.parquet", tmp_path / "right.parquet"
    _write(left)
    _write(right, close_shift=0.01)
    first = audit_saved_market_data((left, right), sample_date_count=2)
    second = audit_saved_market_data((left, right), sample_date_count=2)
    assert first == second

    rendered = json.dumps(first, indent=2, sort_keys=True) + "\n"
    output = Path(os.environ["TMPDIR"], "m91ep-saved-market-data-audit.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
