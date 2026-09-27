import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/research/momentum_saved_summary_audit.py"
SPEC = importlib.util.spec_from_file_location("momentum_saved_summary_audit", MODULE_PATH)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def test_report_verifies_units_costs_freeze_and_parks_promotion():
    report = M.build_report()

    assert all(report["saved_summary_checks"].values())
    assert report["verified_facts"]["unit"]["combined_trade_count"] == 1700
    assert report["verified_facts"]["cohorts"]["hold_months"]["status"] == "VERIFIED"
    assert report["verified_facts"]["cohorts"]["groups_overlap"]["value"] is True
    assert report["verified_facts"]["costs"]["spread_bps_per_side"] == 5.0
    assert report["verified_facts"]["costs"]["displayed_round_trip_cost_usd_at_flat_price"] == 22.0
    assert report["verified_facts"]["costs"]["saved_round_trip_percent_field"]["status"] == \
        "INCOMPLETE_IF_READ_AS_TOTAL_COST"
    assert report["verified_facts"]["freeze_and_repair"]["initial_rule_frozen_before_outcomes"]
    assert report["verified_facts"]["freeze_and_repair"]["post_freeze_repair"]["effect"]
    assert report["verified_facts"]["freeze_and_repair"]["cost_change_after_development_was_harsher"]["status"] == \
        "VERIFIED_FROM_TWO_NAMED_JSON_RECORDS"
    assert report["decision"]["primary_ledger_promotion"] == "PARK"
    assert report["decision"]["blocked"] is True


def test_output_is_deterministic_and_sidecar_matches(tmp_path):
    first = M._json_bytes(M.build_report())
    second = M._json_bytes(M.build_report())
    assert first == second

    output, sidecar = M.write_report(tmp_path / "audit.json")
    expected = hashlib.sha256(output.read_bytes()).hexdigest()
    assert sidecar.read_text() == f"{expected}  audit.json\n"
    assert json.loads(output.read_text())["audit_version"] == "MOMENTUM_SAVED_SUMMARY_AUDIT_V1"


def test_safe_input_allowlist_contains_no_trade_or_membership_csv():
    assert all(Path(name).suffix == ".json" for name in M.SUMMARY_FILES.values())
    assert M.FORMULA_SOURCE.suffix == ".py"
    excluded = M.build_report()["scope"]["excluded"]
    assert "trade CSV rows" in excluded
    assert "membership CSV rows" in excluded


def _loaded_evidence():
    paths = {key: M.SOURCE_DIR / name for key, name in M.SUMMARY_FILES.items()}
    docs = {key: M._load_json(path) for key, path in paths.items()}
    return docs, M._formula_facts(M.FORMULA_SOURCE)


def test_contradictory_cost_record_is_rejected():
    docs, formula = _loaded_evidence()
    docs = deepcopy(docs)
    docs["cost"]["perSideCharges"]["spreadBps"] = 4
    try:
        M._validate_named_evidence(docs, formula)
    except ValueError as error:
        assert "cost_json_matches_code_constants" in str(error)
    else:
        raise AssertionError("contradictory cost evidence was accepted")


def test_contradictory_holding_formula_is_rejected():
    docs, formula = _loaded_evidence()
    formula = deepcopy(formula)
    formula["expressions"]["exit_month"] = "month_end[month_shift(month, -2)]"
    try:
        M._validate_named_evidence(docs, formula)
    except ValueError as error:
        assert "three_month_exit_is_in_code" in str(error)
    else:
        raise AssertionError("contradictory holding-period evidence was accepted")


def test_missing_post_development_cost_evidence_is_rejected():
    docs, formula = _loaded_evidence()
    docs = deepcopy(docs)
    docs["freeze"]["onlyPostHocChangeWasHarsher"] = ""
    try:
        M._validate_named_evidence(docs, formula)
    except ValueError as error:
        assert "post_development_harsher_cost_change" in str(error)
    else:
        raise AssertionError("unsupported cost-change chronology was accepted")
