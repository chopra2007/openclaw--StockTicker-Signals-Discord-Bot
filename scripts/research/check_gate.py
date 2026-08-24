#!/usr/bin/env python3
"""Mechanical gate checker for the opening-auction-imbalance overnight run (TODO #93).

Run between every phase dispatch:
    python3 scripts/research/check_gate.py <phase>

Exit code 0 = gate passed, dispatch the next phase.
Exit code 1 = gate failed (missing/malformed file, missing keys, failed
assertion, or gate_pass:false). Do not dispatch the next phase.

The gate directory is fixed (per the approved plan, not a CLI arg):
    /home/openclaw/.openclaw/workspace/.omc/research/opening-auction-imbalance/

This script is the mechanical enforcement described in the plan's
"Orchestrator's job" section — it does not trust an agent's own `proceed`
value where the plan calls for independent recomputation (phase1c).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

GATE_DIR = Path("/home/openclaw/.openclaw/workspace/.omc/research/opening-auction-imbalance")

# phase -> required keys (presence + non-None check)
REQUIRED_KEYS = {
    "phase1": [
        "gate_pass", "proceed", "files_decoded", "record_counts",
        "degraded_dates_xnys", "degraded_dates_equs", "brk_alias_confirmed",
    ],
    "phase1b": [
        "gate_pass", "proceed", "information_cutoff_et", "auction_entry_cutoff_et",
        "entry_price_convention", "entry_price_source", "market_proxy_method",
        "halted_ticker_days_excluded", "xnys_0930_bar_missing_share",
    ],
    "phase1c": [
        "gate_pass", "proceed", "split_date", "decile_spread_bps_top",
        "decile_spread_bps_bottom", "fillable_entry_share",
    ],
    "phase2": [
        "gate_pass", "proceed", "hypothesis_count", "hypothesis_ids",
        "dev_events_path", "eval_events_path", "min_sample_floor",
        "target_trigger_rate", "min_effect_size_bps", "power_calc_n_required",
        "normalization_window_days", "holding_period_minutes",
        "entry_price_source", "signal_direction_convention",
    ],
    "phase3a": ["gate_pass", "proceed", "dates_used_source", "builder_read", "sample_size"],
    "phase3b": ["gate_pass", "proceed", "dates_used_source", "builder_read", "sample_size"],
    "phase3c": ["gate_pass", "proceed", "dates_used_source", "builder_read", "sample_size"],
    "phase4a": ["gate_pass", "audit_verdict", "defects_found"],
    "phase4b": ["gate_pass", "audit_verdict", "defects_found"],
    "phase4c": ["gate_pass", "audit_verdict", "defects_found"],
    "phase4-summary": ["gate_pass", "proceed", "hypotheses_advancing"],
    "phase5a": ["gate_pass", "hypotheses_run", "hypotheses_skipped", "per_event_csv_paths"],
    "phase5b": ["gate_pass", "final_verdict_per_hypothesis", "todo_updated"],
}


def load_gate(phase: str) -> dict:
    path = GATE_DIR / f"{phase}-gate.json"
    if not path.exists():
        print(f"FAIL: {path} does not exist")
        sys.exit(1)
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        print(f"FAIL: {path} is not valid JSON: {e}")
        sys.exit(1)
    if not isinstance(data, dict):
        print(f"FAIL: {path} top-level JSON is not an object")
        sys.exit(1)
    return data


def check_required_keys(phase: str, data: dict) -> None:
    required = REQUIRED_KEYS.get(phase)
    if required is None:
        print(f"FAIL: unknown phase '{phase}'")
        sys.exit(1)
    missing = [k for k in required if k not in data]
    if missing:
        print(f"FAIL: {phase}-gate.json missing required keys: {missing}")
        sys.exit(1)


def check_gate_pass(data: dict) -> None:
    if data.get("gate_pass") is not True:
        print(f"FAIL: gate_pass is not true (got {data.get('gate_pass')!r})")
        sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: check_gate.py <phase>")
        sys.exit(1)
    phase = sys.argv[1]
    data = load_gate(phase)
    check_required_keys(phase, data)

    # phase-specific extra assertions
    if phase == "phase1":
        check_gate_pass(data)
        files = data["files_decoded"]
        if not isinstance(files, list) or len(files) != 4:
            print(f"FAIL: files_decoded must have exactly 4 entries, got {files!r}")
            sys.exit(1)
        if data.get("brk_alias_confirmed") is not True:
            print("FAIL: brk_alias_confirmed is not true")
            sys.exit(1)

    elif phase == "phase1b":
        check_gate_pass(data)
        checks = {
            "information_cutoff_et": "09:30:00",
            "entry_price_convention": "close_of_0934_1min_bar_equs",
            "entry_price_source": "equs",
            "market_proxy_method": "beta_scaled_cross_sectional_60_names",
        }
        for key, expected in checks.items():
            if data.get(key) != expected:
                print(f"FAIL: {key} must equal {expected!r}, got {data.get(key)!r}")
                sys.exit(1)

    elif phase == "phase1c":
        # gate_pass must be true regardless of proceed outcome (proceed:false is a
        # valid terminal kill state, not a failure).
        check_gate_pass(data)
        try:
            top = float(data["decile_spread_bps_top"])
            bottom = float(data["decile_spread_bps_bottom"])
            fillable = float(data["fillable_entry_share"])
        except (TypeError, ValueError) as e:
            print(f"FAIL: decile/fillable fields are not numeric: {e}")
            sys.exit(1)
        expected_proceed = (top >= 15 or bottom <= -15) and (fillable >= 0.60)
        actual_proceed = data.get("proceed")
        if actual_proceed is not expected_proceed:
            print(
                f"FAIL: proceed mismatch — recomputed {expected_proceed} from "
                f"(decile_spread_bps_top={top}, decile_spread_bps_bottom={bottom}, "
                f"fillable_entry_share={fillable}) but gate file says proceed={actual_proceed!r}"
            )
            sys.exit(1)
        if actual_proceed is False:
            print("PASS (phase1c): gate_pass true, proceed correctly recomputed as False (kill). "
                  "Orchestrator must stop the run here per the plan.")
        else:
            print("PASS (phase1c): gate_pass true, proceed correctly recomputed as True.")

    elif phase == "phase2":
        check_gate_pass(data)
        if not (isinstance(data.get("min_sample_floor"), (int, float)) and data["min_sample_floor"] >= 20):
            print(f"FAIL: min_sample_floor must be >= 20, got {data.get('min_sample_floor')!r}")
            sys.exit(1)
        if data.get("holding_period_minutes") != 60:
            print(f"FAIL: holding_period_minutes must be 60, got {data.get('holding_period_minutes')!r}")
            sys.exit(1)
        if data.get("entry_price_source") != "equs":
            print(f"FAIL: entry_price_source must be 'equs', got {data.get('entry_price_source')!r}")
            sys.exit(1)
        hyp_path = GATE_DIR / "hypotheses-v1.md"
        if not hyp_path.exists():
            print(f"FAIL: {hyp_path} does not exist")
            sys.exit(1)
        text = hyp_path.read_text()
        if "TBD" in text:
            print("FAIL: hypotheses-v1.md contains the literal string 'TBD'")
            sys.exit(1)
        dev_path = Path(data["dev_events_path"])
        eval_path = Path(data["eval_events_path"])
        for p in (dev_path, eval_path):
            if not p.exists():
                print(f"FAIL: {p} does not exist")
                sys.exit(1)
        import csv as _csv

        def max_min_date(p: Path, colname_candidates=("date", "event_date", "trading_date")):
            with open(p, newline="") as f:
                reader = _csv.DictReader(f)
                col = None
                for c in colname_candidates:
                    if c in (reader.fieldnames or []):
                        col = c
                        break
                if col is None:
                    print(f"FAIL: no date-like column found in {p} (fieldnames={reader.fieldnames})")
                    sys.exit(1)
                dates = [row[col] for row in reader if row.get(col)]
                if not dates:
                    print(f"FAIL: {p} has no data rows")
                    sys.exit(1)
                return min(dates), max(dates)

        dev_min, dev_max = max_min_date(dev_path)
        eval_min, eval_max = max_min_date(eval_path)
        if not (dev_max < eval_min):
            print(f"FAIL: dev/eval date overlap — max(dev)={dev_max} not < min(eval)={eval_min}")
            sys.exit(1)

    elif phase in ("phase3a", "phase3b", "phase3c"):
        check_gate_pass(data)
        if data.get("dates_used_source") != "dev_events.csv":
            print(f"FAIL: dates_used_source must be 'dev_events.csv', got {data.get('dates_used_source')!r}")
            sys.exit(1)

    elif phase in ("phase4a", "phase4b", "phase4c"):
        # gate_pass here means "did the audit execute", not "did it advance" —
        # the plan's gate condition is just that the file exists with a
        # non-empty verdict, so we don't hard-require gate_pass True here,
        # but we do require it present (checked above) and a valid verdict.
        verdict = data.get("audit_verdict")
        if verdict not in ("advance", "reject", "insufficient"):
            print(f"FAIL: audit_verdict must be one of advance/reject/insufficient, got {verdict!r}")
            sys.exit(1)

    elif phase == "phase4-summary":
        check_gate_pass(data)
        if data.get("hypotheses_advancing") != []:
            print(f"FAIL: hypotheses_advancing must be [] for the all-reject summary, got {data.get('hypotheses_advancing')!r}")
            sys.exit(1)

    elif phase == "phase5a":
        check_gate_pass(data)
        for p in data["per_event_csv_paths"]:
            if not Path(p).exists():
                print(f"FAIL: per_event_csv_paths entry does not exist on disk: {p}")
                sys.exit(1)

    elif phase == "phase5b":
        check_gate_pass(data)
        if data.get("todo_updated") is not True:
            print(f"FAIL: todo_updated must be true, got {data.get('todo_updated')!r}")
            sys.exit(1)

    print(f"PASS: {phase}-gate.json")
    sys.exit(0)


if __name__ == "__main__":
    main()
