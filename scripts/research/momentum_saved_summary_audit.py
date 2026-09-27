#!/usr/bin/env python3
"""Audit the saved three-month momentum summaries without opening trade rows.

This is intentionally a bounded audit.  It reads only named published JSON
summaries and the Python file containing the calculation.  It does not open
trade CSVs, membership CSVs, market payloads, sealed names, or the network.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / ".omc/research/todo-111-proven-trading-edge"
OUTPUT = ROOT / ".omc/research/trading-edge-discovery/momentum-saved-summary-audit.json"
FORMULA_SOURCE = ROOT / "scripts/research/todo_111_momentum_quarter.py"

SUMMARY_FILES = {
    "development": "development-result-c3-three-component.json",
    "untouched": "untouched-result-c3.json",
    "combined": "combined-result-c3.json",
    "proof": "final-proof-bundle.json",
    "cost": "realistic-cost-audit.json",
    "freeze": "frozen-gates.json",
    "point_in_time": "point-in-time-audit.json",
}

# These are the source-filtered membership inputs named by the calculation.
# Their absence is checked by path only; no substitute CSV is opened.
ORIGINAL_MEMBERSHIP_INPUTS = (
    Path("/root/.claude/jobs/5622c81c/tmp/formation.json"),
    Path("/root/.claude/jobs/5622c81c/tmp/calendar.json"),
    Path("/root/.claude/jobs/5622c81c/tmp/symbols"),
    Path("/root/.claude/jobs/5622c81c/tmp/formation_untouched.json"),
    Path("/root/.claude/jobs/5622c81c/tmp/calendar_full.json"),
    Path("/root/.claude/jobs/5622c81c/tmp/symbols_untouched"),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _formula_facts(path: Path) -> dict:
    """Inspect the saved calculation's constants and exact return expressions."""
    tree = ast.parse(path.read_text(), filename=str(path))
    constants: dict[str, object] = {}
    wanted = {
        "POSITION_USD", "COMMISSION_USD_PER_SIDE", "SPREAD_BPS_PER_SIDE",
        "SLIPPAGE_BPS_PER_SIDE", "TOP_N", "MIN_PRIOR_DAYS",
        "GAP_BOUNDARY_TRADING_DAYS", "SIGNAL_ENDPOINT_MAX_STALE_TRADING_DAYS",
    }
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in wanted:
                constants[target.id] = ast.literal_eval(node.value)

    build = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "build"
    )
    assignments = {
        node.targets[0].id: ast.unparse(node.value)
        for node in build.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    }
    returned = next(node.value for node in build.body if isinstance(node, ast.Return))
    if not isinstance(returned, ast.Dict):
        raise ValueError("momentum build function no longer returns a record")
    fields = {
        key.value: ast.unparse(value)
        for key, value in zip(returned.keys, returned.values)
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    expected = {
        "shares": "POSITION_USD / entry_price",
        "entry_cost": "POSITION_USD * (1 + rate) + COMMISSION_USD_PER_SIDE",
        "exit_value": "shares * xp * (1 - rate) - COMMISSION_USD_PER_SIDE",
        "net_return": "round((value - cost) / cost * 100, 6)",
        "gross_return": "round((shares * xp - POSITION_USD) / POSITION_USD * 100, 6)",
    }
    observed = {
        "shares": assignments.get("shares"),
        "entry_cost": assignments.get("cost"),
        "exit_value": assignments.get("value"),
        "net_return": fields.get("returnPct"),
        "gross_return": fields.get("grossReturnPct"),
        "exit_month": next(
            ast.unparse(node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "x_date"
        ),
        "formation_iteration": next(
            ast.unparse(node.iter)
            for node in ast.walk(tree)
            if isinstance(node, ast.For)
            and isinstance(node.target, ast.Name)
            and node.target.id == "month"
        ),
    }
    expected.update({
        "exit_month": "month_end[month_shift(month, -3)]",
        "formation_iteration": "sorted(formation)",
    })
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": _sha256(path),
        "constants": constants,
        "expressions": observed,
        "expressions_match_expected": observed == expected,
    }


def _near(left: float, right: float, places: int = 4) -> bool:
    return round(float(left), places) == round(float(right), places)


def _inclusive_months(period: str) -> int:
    prefix = "groups formed "
    if not period.startswith(prefix) or ".." not in period:
        raise ValueError(f"unrecognised saved period: {period}")
    first, last = period[len(prefix):].split("..", 1)
    fy, fm = (int(value) for value in first.split("-"))
    ly, lm = (int(value) for value in last.split("-"))
    return (ly * 12 + lm) - (fy * 12 + fm) + 1


def _validate_named_evidence(docs: dict, formula: dict) -> dict:
    """Tie narrative facts to structured JSON fields and inspected expressions."""
    dev, untouched = docs["development"], docs["untouched"]
    cost, freeze = docs["cost"], docs["freeze"]
    constants = formula["constants"]
    charges = cost.get("perSideCharges", {})
    validations = {
        "three_month_exit_is_in_code":
            formula["expressions"].get("exit_month")
            == "month_end[month_shift(month, -3)]",
        "one_group_is_built_for_each_formation_month":
            formula["expressions"].get("formation_iteration") == "sorted(formation)",
        "development_period_contains_one_group_per_calendar_month":
            dev["groups"] == _inclusive_months(dev["period"]),
        "untouched_period_contains_one_group_per_calendar_month":
            untouched["groups"] == _inclusive_months(untouched["period"]),
        "cost_json_matches_code_constants": (
            charges.get("commissionUsd") == constants["COMMISSION_USD_PER_SIDE"]
            and charges.get("spreadBps") == constants["SPREAD_BPS_PER_SIDE"]
            and charges.get("slippageBps") == constants["SLIPPAGE_BPS_PER_SIDE"]
            and set(cost.get("costComponentsApplied", []))
            == {"commission", "spread", "slippage"}
            and cost.get("returnsAreNetOfTheseCosts") is True
        ),
        "post_development_harsher_cost_change_is_named_in_freeze_json": (
            "After the development run" in freeze.get("onlyPostHocChangeWasHarsher", "")
            and "strictly more expensive" in freeze.get("onlyPostHocChangeWasHarsher", "")
        ),
        "cost_audit_names_five_to_ten_bps_change": any(
            "raised to 10 a side" in note and "frozen rule charged 5 basis points" in note
            for note in cost.get("notes", [])
        ),
    }
    failed = [name for name, passed in validations.items() if not passed]
    if failed:
        raise ValueError("named evidence contradiction: " + ", ".join(failed))
    return validations


def build_report() -> dict:
    paths = {key: SOURCE_DIR / name for key, name in SUMMARY_FILES.items()}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing published summary: " + ", ".join(missing))
    docs = {key: _load_json(path) for key, path in paths.items()}
    dev, untouched, combined = docs["development"], docs["untouched"], docs["combined"]
    formula = _formula_facts(FORMULA_SOURCE)
    evidence_validations = _validate_named_evidence(docs, formula)

    weighted_mean = (
        dev["avgReturnPctAfterCosts"] * dev["tradeCount"]
        + untouched["avgReturnPctAfterCosts"] * untouched["tradeCount"]
    ) / (dev["tradeCount"] + untouched["tradeCount"])
    absent_membership = [str(path) for path in ORIGINAL_MEMBERSHIP_INPUTS if not path.exists()]
    all_membership_absent = len(absent_membership) == len(ORIGINAL_MEMBERSHIP_INPUTS)

    checks = {
        "development_has_twenty_positions_per_group":
            dev["tradeCount"] == dev["groups"] * formula["constants"]["TOP_N"],
        "untouched_has_twenty_positions_per_group":
            untouched["tradeCount"] == untouched["groups"] * formula["constants"]["TOP_N"],
        "combined_counts_are_additive": (
            combined["tradeCount"] == dev["tradeCount"] + untouched["tradeCount"]
            and combined["groups"] == dev["groups"] + untouched["groups"]
        ),
        "combined_mean_is_trade_weighted":
            _near(weighted_mean, combined["avgReturnPctAfterCosts"]),
        "saved_cost_labels_agree": (
            dev["costModel"] == untouched["costModel"] == combined["costModel"]
            == "three-component"
        ),
        "formula_expressions_match_expected": formula["expressions_match_expected"],
        "named_evidence_is_consistent": all(evidence_validations.values()),
        "all_named_original_membership_inputs_are_absent": all_membership_absent,
    }
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise ValueError("saved-summary audit invariant failed: " + ", ".join(failed))

    constants = formula["constants"]
    rate = (constants["SPREAD_BPS_PER_SIDE"] + constants["SLIPPAGE_BPS_PER_SIDE"]) / 10_000
    displayed_round_trip_dollars = (
        constants["POSITION_USD"] * rate * 2
        + constants["COMMISSION_USD_PER_SIDE"] * 2
    )

    return {
        "audit_version": "MOMENTUM_SAVED_SUMMARY_AUDIT_V1",
        "scope": {
            "read": "named published JSON summaries and calculation source only",
            "excluded": [
                "trade CSV rows", "membership CSV rows", "market payloads",
                "sealed names and aliases", "network", "secrets",
            ],
        },
        "inputs": [
            {"role": key, "path": str(path.relative_to(ROOT)), "sha256": _sha256(path)}
            for key, path in paths.items()
        ],
        "formula_inspection": formula,
        "named_evidence_validations": evidence_validations,
        "saved_summary_checks": checks,
        "verified_facts": {
            "unit": {
                "instrument": combined["instrument"],
                "one_record": "one equal-dollar long share position in one monthly group",
                "position_usd": constants["POSITION_USD"],
                "return_unit": "percent of entry debit after entry and exit costs",
                "combined_trade_count": combined["tradeCount"],
                "combined_groups": combined["groups"],
            },
            "cohorts": {
                "positions_per_month": constants["TOP_N"],
                "hold_months": {
                    "value": 3,
                    "status": "VERIFIED",
                    "evidence": "formula_inspection.expressions.exit_month",
                },
                "groups_overlap": {
                    "value": True,
                    "status": "VERIFIED",
                    "evidence": [
                        "named_evidence_validations.three_month_exit_is_in_code",
                        "named_evidence_validations.development_period_contains_one_group_per_calendar_month",
                        "named_evidence_validations.untouched_period_contains_one_group_per_calendar_month",
                    ],
                },
                "development_groups": dev["groups"],
                "untouched_groups": untouched["groups"],
                "dependence_warning": (
                    "Monthly groups overlap for a three-month hold, so 1,700 trades are not "
                    "1,700 independent observations."
                ),
            },
            "costs": {
                "spread_bps_per_side": constants["SPREAD_BPS_PER_SIDE"],
                "slippage_bps_per_side": constants["SLIPPAGE_BPS_PER_SIDE"],
                "commission_usd_per_side": constants["COMMISSION_USD_PER_SIDE"],
                "displayed_round_trip_cost_usd_at_flat_price": displayed_round_trip_dollars,
                "entry_and_exit_formula_verified": True,
                "saved_round_trip_percent_field": {
                    "value": docs["cost"]["roundTripCostPctOfPosition"],
                    "status": "INCOMPLETE_IF_READ_AS_TOTAL_COST",
                    "reason": (
                        "The saved 0.2% field covers the percentage charges. The inspected formula also "
                        "charges $2 round trip commission, making the displayed flat-price charge $22, "
                        "or 0.22% of the $10,000 position."
                    ),
                },
            },
            "saved_results": {
                "development_net_mean_pct": dev["avgReturnPctAfterCosts"],
                "development_benchmark_mean_pct": dev["benchmarkEqualWeightAllEligibleAvgReturnPct"],
                "development_net_mean_excluding_2020_pct":
                    dev["avgReturnPctExcludingGroupYear2020"],
                "development_net_mean_excluding_top_five_tickers_pct":
                    dev["avgReturnPctExcludingTopFiveTickers"],
                "untouched_net_mean_pct": untouched["avgReturnPctAfterCosts"],
                "untouched_benchmark_mean_pct": untouched["benchmarkEqualWeightAllEligibleAvgReturnPct"],
                "combined_net_mean_pct": combined["avgReturnPctAfterCosts"],
                "combined_benchmark_mean_pct": combined["benchmarkEqualWeightAllEligibleAvgReturnPct"],
                "combined_best_trade_pct": combined["bestReturnPct"],
                "combined_median_trade_pct": combined["medianReturnPct"],
            },
            "freeze_and_repair": {
                "initial_rule_frozen_before_outcomes": docs["freeze"]["frozenBeforeOutcomesRead"],
                "initial_minimum_mean_pct": docs["freeze"]["frozenMinAvgReturnPct"],
                "initial_minimum_trade_count": docs["freeze"]["frozenMinTradeCount"],
                "cost_change_after_development_was_harsher": {
                    "value": True,
                    "status": "VERIFIED_FROM_TWO_NAMED_JSON_RECORDS",
                    "evidence": [
                        "frozen-gates.json.onlyPostHocChangeWasHarsher",
                        "realistic-cost-audit.json.notes",
                    ],
                },
                "post_freeze_repair": docs["proof"]["repairedAfterIndependentVerification"],
                "saved_number_sequence_reconciliation": {
                    "cost_change_statement": next(
                        note for note in docs["cost"]["notes"]
                        if note.startswith("Effect of the harsher model")
                    ),
                    "later_repair_statement":
                        docs["proof"]["repairedAfterIndependentVerification"]["effect"],
                    "current_development_net_mean_pct": dev["avgReturnPctAfterCosts"],
                    "status": "RECONCILED_AS_SUCCESSIVE_SAVED_VERSIONS_NOT_ROW_REPRODUCED",
                },
            },
        },
        "reproducibility_gaps": [
            {
                "id": "MISSING_SOURCE_FILTERED_MEMBERSHIP_INPUTS",
                "evidence": absent_membership,
                "effect": (
                    "The month-by-month eligible membership and selections cannot be rebuilt "
                    "from the saved summaries."
                ),
            },
            {
                "id": "NO_COHORT_LEDGER_IN_SAFE_INPUTS",
                "effect": (
                    "The summaries do not contain one return per monthly group, so dependence-aware "
                    "uncertainty and positive benchmark-relative performance outside 2020 cannot be reproduced."
                ),
            },
            {
                "id": "NO_PRIMARY_ROW_RECONCILIATION",
                "effect": (
                    "Aggregate summary claims, the post-freeze membership repair, and the saved cost-audit "
                    "wording cannot be reconciled row by row without opening an original source-filtered ledger."
                ),
            },
            {
                "id": "UNSEALED_LEGACY_SUMMARIES",
                "effect": (
                    "The legacy summary folder has no saved SHA sidecars; this audit fingerprints the files "
                    "as found but cannot prove their earlier state."
                ),
            },
        ],
        "decision": {
            "primary_ledger_promotion": "PARK",
            "blocked": True,
            "reason": (
                "The source-filtered original membership and cohort inputs are missing or not safely usable. "
                "Saved aggregate summaries verify reported units and arithmetic shape, but they cannot prove "
                "benchmark-relative performance outside 2020 with overlap-aware uncertainty."
            ),
            "family_status": "preserve as an owner-retained research option; do not kill the family",
            "unblock_requires": [
                "an intact source-filtered month-by-month membership ledger",
                "an intact cohort-level return and benchmark ledger",
                "hashes or equivalent provenance tying those ledgers to the saved summaries",
            ],
        },
    }


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def write_report(output: Path = OUTPUT) -> tuple[Path, Path]:
    payload = _json_bytes(build_report())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    sidecar = output.with_name(output.name + ".sha256")
    sidecar.write_text(f"{digest}  {output.name}\n")
    return output, sidecar


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    output, sidecar = write_report(args.output)
    print(output.relative_to(ROOT) if output.is_relative_to(ROOT) else output)
    print(sidecar.relative_to(ROOT) if sidecar.is_relative_to(ROOT) else sidecar)


if __name__ == "__main__":
    main()
