import csv
import hashlib
import importlib.util
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "scripts/research/verify_trading_edge_e1_result.py"
RESULT_DIR = REPO / ".omc/research/trading-edge-discovery"
SPEC = importlib.util.spec_from_file_location("verify_trading_edge_e1_result", MODULE_PATH)
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_proof_artifact_hashes_and_saved_checks_are_valid():
    result = VERIFY.verify_proof_artifacts(RESULT_DIR)
    assert result["sidecars_match"] is True
    assert result["reconstruction_all_checks_pass"] is True
    assert result["sample_checks_pass"] is True
    assert result["market_ranks_are_sequential"] is True


def test_fixed_raw_bar_sample_is_deterministic_and_reconstructed():
    report = json.loads((RESULT_DIR / "e1-independent-reconstruction.json").read_text())
    rows = report["raw_bar_reconstructions"]
    expected = sorted(
        rows,
        key=lambda row: (hashlib.sha256(row["id"].encode()).hexdigest(), row["id"]),
    )
    assert len(rows) == 10
    assert [row["id"] for row in rows] == [row["id"] for row in expected]
    assert all(row["all_checks_pass"] for row in rows)
    assert all(all(row["checks"].values()) for row in rows)


def test_independent_arithmetic_and_selection_are_within_tolerance():
    report = json.loads((RESULT_DIR / "e1-independent-reconstruction.json").read_text())
    candidate = report["candidate"]
    assert max(candidate["ledger_absolute_errors"].values()) <= VERIFY.TOLERANCE
    assert max(candidate["summary_absolute_errors"].values()) <= VERIFY.TOLERANCE
    assert candidate["all_eligibility_gates_pass"] is True
    assert report["selection"] == {
        "candidate_rank": 1,
        "eligible_cells": 1,
        "persisted_ranking_matches": True,
        "primary_cells": 32,
        "selected_cells": [VERIFY.CANDIDATE_ID],
    }


def test_market_adjusted_ranking_recomputes_exactly_and_deterministically():
    summaries = {
        row["cell_id"]: row
        for row in VERIFY.read_jsonl(RESULT_DIR / "full-cell-summaries.jsonl")
    }
    first = VERIFY.market_adjusted_ranking(summaries)
    second = VERIFY.market_adjusted_ranking(dict(reversed(list(summaries.items()))))
    with (RESULT_DIR / "full-market-adjusted-ranking.csv").open() as handle:
        saved = list(csv.DictReader(handle))
    assert first == second
    assert len(first) == len(saved) == 32
    assert [row["cell_id"] for row in first] == [row["cell_id"] for row in saved]
    assert [row["rank"] for row in first] == list(range(1, 33))
    for expected, actual in zip(first, saved):
        saved_lower = actual["market_adjusted_80pct_week_bootstrap_lower"]
        expected_lower = expected["market_adjusted_80pct_week_bootstrap_lower"]
        assert (None if saved_lower == "" else float(saved_lower)) == expected_lower
        assert int(actual["market_adjusted_count"]) == expected["market_adjusted_count"]
        assert float(actual["bh_q_value"]) == expected["bh_q_value"]


def test_writers_are_byte_deterministic_and_hash_the_exact_file(tmp_path):
    value = {"b": [2, 1], "a": {"z": 3}}
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    VERIFY.write_json(first, value)
    VERIFY.write_json(second, value)
    assert first.read_bytes() == second.read_bytes()
    for path in (first, second):
        sidecar = path.with_suffix(path.suffix + ".sha256").read_text().split()[0]
        assert sidecar == _sha256(path)


def test_owner_report_states_limits_and_no_live_authorization():
    text = (RESULT_DIR / "e1-owner-report.md").read_text()
    assert "exploratory result" in text
    assert "does not establish statistical significance" in text
    assert "244 days or 112 weeks" in text
    assert "does not authorize live alerts, live trading, order placement, or use of owner capital" in text
