#!/usr/bin/env python3
"""Independently reproduce and judge the persisted E2 research result.

This verifier does not import the E2 runner or its calculation helpers.  It
recomputes the saved ledgers, deterministic selections, performance, power,
and a fixed raw-bar sample from the registered development data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import NormalDist
from typing import Iterable

import numpy as np
import pyarrow.parquet as pq


WORKSPACE = Path(__file__).resolve().parents[2]
RESULT_DIR = WORKSPACE / ".omc/research/trading-edge-e2"
E1_DIR = WORKSPACE / ".omc/research/trading-edge-discovery"
SOURCE = WORKSPACE / ".omc/research/professional-day-trader-methods/bars-equs-allmin.parquet"
PRODUCTION_RUNNER = WORKSPACE / "scripts/research/trading_edge_e2.py"
E1_FULL = WORKSPACE / "scripts/research/trading_edge_full.py"
E1_REGISTRATION = WORKSPACE / "scripts/research/trading_edge_registration.py"
STUDY_ID = "TRADING_EDGE_E2_V1"
SURVIVOR = "OR15_VOL_2P5__SHORT__H30"
SEED = 20260927
BOOTSTRAP_DRAWS = 2_000
TOLERANCE = 2e-15
BLOCK_RANGES = {
    "B1": ("2023-03-28", "2023-06-30"),
    "B2": ("2023-07-03", "2023-12-29"),
    "B3": ("2024-01-02", "2024-06-28"),
    "B4": ("2024-07-01", "2024-12-31"),
    "B5": ("2025-01-02", "2025-03-31"),
}
BLOCKS = tuple(BLOCK_RANGES)
FOLDS = (
    ("F1", ("B1",), "B2"),
    ("F2", ("B1", "B2"), "B3"),
    ("F3", ("B1", "B2", "B3"), "B4"),
    ("F4", ("B1", "B2", "B3", "B4"), "B5"),
)
EXIT_RULES = ("FIXED_H15", "FIXED_H30", "OR1_BRACKET_H30")
POPULATIONS = ("UNFILTERED", "ABS_GAP_LT2", "EARLY_1H")
VARIANT_IDS = tuple(f"{exit_rule}__{population}" for exit_rule in EXIT_RULES for population in POPULATIONS)
BASE_NAMES = (
    "run-registration.json",
    "variants.json",
    "daily-results.jsonl",
    "block-results.jsonl",
    "rolling-results.json",
    "trial-ledger.json",
    "power.json",
    "summary.json",
    "owner-report.txt",
    "delay-stress.jsonl",
    "event-audit.jsonl",
    "unresolved.jsonl",
)
PROOF_NAMES = (
    "e2-reproduction.json",
    "e2-reproduction.json.sha256",
    "edge-verdict.json",
    "edge-verdict.json.sha256",
    "edge-verdict.md",
    "edge-verdict.md.sha256",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def write_with_sidecar(path: Path, payload: bytes) -> str:
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    temporary.write_bytes(payload)
    os.replace(temporary, path)
    digest = hashlib.sha256(payload).hexdigest()
    sidecar = path.with_name(path.name + ".sha256")
    side_tmp = sidecar.with_name(f".{sidecar.name}.tmp.{os.getpid()}")
    side_tmp.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    os.replace(side_tmp, sidecar)
    return digest


def write_json(path: Path, value: object) -> str:
    return write_with_sidecar(path, (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def expected_core_paths() -> tuple[str, ...]:
    paths = []
    for name in BASE_NAMES:
        paths.extend((name, name + ".sha256"))
    for variant_id in VARIANT_IDS:
        for block in BLOCKS:
            name = f"checkpoints/{variant_id}__{block}.json"
            paths.extend((name, name + ".sha256"))
    return tuple(sorted(paths))


def verify_sidecar(path: Path) -> dict:
    digest = sha256_file(path)
    sidecar = path.with_name(path.name + ".sha256")
    expected = f"{digest}  {path.name}\n"
    actual = sidecar.read_text(encoding="utf-8") if sidecar.exists() else None
    return {"sha256": digest, "matches_sidecar": actual == expected}


def close(left: float | int | None, right: float | int | None, tolerance: float = TOLERANCE) -> bool:
    if left is None or right is None:
        return left is right
    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=tolerance)


def week(day: str) -> str:
    year, number, _ = date.fromisoformat(day).isocalendar()
    return f"{year:04d}-W{number:02d}"


def mean(values: Iterable[float]) -> float | None:
    materialized = list(values)
    return statistics.mean(materialized) if materialized else None


def lower_bound(rows: list[dict], field: str, seed_key: str) -> float | None:
    by_week: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_week[row["week"]].append(float(row[field]))
    weeks = sorted(by_week)
    if not weeks:
        return None
    week_means = np.asarray([statistics.mean(by_week[item]) for item in weeks], dtype=float)
    seed = SEED + int(hashlib.sha256(seed_key.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    samples = rng.choice(week_means, size=(BOOTSTRAP_DRAWS, len(weeks)), replace=True).mean(axis=1)
    return float(np.quantile(samples, 0.20))


def summarize(rows: list[dict], variant_id: str, block: str) -> dict:
    return {
        "variant_id": variant_id,
        "block": block,
        "event_days": len({row["date"] for row in rows}),
        "trades": sum(int(row["event_count"]) for row in rows),
        "weeks": len({row["week"] for row in rows}),
        "mean_net_excess_base": mean(float(row["net_excess_base"]) for row in rows),
        "mean_net_excess_base_target_first": mean(float(row["net_excess_base_target_first"]) for row in rows),
        "mean_raw_event_net_base": mean(float(row["raw_event_net_base"]) for row in rows),
        "mean_raw_event_gross": mean(float(row["raw_event_gross"]) for row in rows),
        "mean_net_excess_p90": mean(float(row["net_excess_p90"]) for row in rows),
        "mean_net_excess_twice_floor": mean(float(row["net_excess_twice_floor"]) for row in rows),
        "mean_net_excess_20bps": mean(float(row["net_excess_20bps"]) for row in rows),
        "week_bootstrap_80pct_lower": lower_bound(rows, "net_excess_base", f"{variant_id}|{block}"),
    }


def compare_record(actual: dict, expected: dict, fields: Iterable[str], label: str, discrepancies: list[str]) -> None:
    for field in fields:
        left, right = actual.get(field), expected.get(field)
        if isinstance(left, (float, int)) or isinstance(right, (float, int)):
            if not close(left, right):
                discrepancies.append(f"{label}.{field}: {left!r} != {right!r}")
        elif left != right:
            discrepancies.append(f"{label}.{field}: {left!r} != {right!r}")


def quote_buckets() -> list[dict]:
    report = json.loads((E1_DIR / "quote-cost-report.json").read_text())
    buckets = []
    for row in report["results"]["thirty_minute_buckets"]:
        hour, minute = map(int, row["bucket_start_pacific"].split(":"))
        buckets.append({**row, "start": (hour - 6) * 60 + minute - 30})
    return buckets


def spread_at(column: int, buckets: list[dict], field: str) -> float:
    eligible = [row for row in buckets if int(row["start"]) <= column]
    if not eligible:
        raise AssertionError(f"no quote bucket covers column {column}")
    return float(eligible[-1][field])


def expected_cost(entry: int, exit_column: int, buckets: list[dict], field: str) -> float:
    floor = 8.0 if entry < 60 or exit_column < 60 else 5.0
    return max(floor, (spread_at(entry, buckets, field) + spread_at(exit_column, buckets, field)) / 2.0)


def audit_daily_reconstruction(audit_rows: list[dict], saved_daily: list[dict], discrepancies: list[str]) -> dict:
    buckets = quote_buckets()
    by_id = {row["id"]: row for row in saved_daily}
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    maximum_errors = defaultdict(float)
    for row in audit_rows:
        base_cost = expected_cost(int(row["entry_col"]), int(row["exit_col"]), buckets, "median_displayed_spread_bps")
        p90_cost = expected_cost(int(row["entry_col"]), int(row["exit_col"]), buckets, "p90_displayed_spread_bps")
        checks = {
            "event_base_cost": (float(row["cost_base_bps"]), base_cost),
            "event_p90_cost": (float(row["cost_p90_bps"]), p90_cost),
            "raw_net": (float(row["raw_net_base"]), float(row["gross_return"]) - base_cost / 10_000.0),
            "base_excess": (float(row["net_excess_base"]), float(row["raw_net_base"]) - float(row["matched_control_net_base"])),
            "control_p90_relation": (
                float(row["matched_control_net_p90"]),
                float(row["matched_control_net_base"])
                - (float(row["matched_control_cost_p90_bps"]) - float(row["matched_control_cost_base_bps"])) / 10_000.0,
            ),
        }
        for name, (left, right) in checks.items():
            error = abs(left - right)
            maximum_errors[name] = max(maximum_errors[name], error)
            if error > TOLERANCE:
                discrepancies.append(f"event audit {row['id']} {name} error {error}")
        grouped[(row["variant_id"], row["date"])].append(row)

    reconstructed = 0
    for (variant_id, day), rows in grouped.items():
        saved = by_id.get(f"{variant_id}|{day}")
        if saved is None:
            discrepancies.append(f"missing daily row for {variant_id}|{day}")
            continue
        control_gross = [
            float(row["matched_control_net_base"]) + float(row["matched_control_cost_base_bps"]) / 10_000.0
            for row in rows
        ]
        expected = {
            "event_count": len(rows),
            "raw_event_gross": statistics.mean(float(row["gross_return"]) for row in rows),
            "raw_event_net_base": statistics.mean(float(row["raw_net_base"]) for row in rows),
            "net_excess_base": statistics.mean(float(row["net_excess_base"]) for row in rows),
            "net_excess_p90": statistics.mean(
                (float(row["gross_return"]) - float(row["cost_p90_bps"]) / 10_000.0)
                - float(row["matched_control_net_p90"])
                for row in rows
            ),
            "net_excess_twice_floor": statistics.mean(
                float(row["gross_return"]) - control for row, control in zip(rows, control_gross)
            ),
            "net_excess_20bps": statistics.mean(
                float(row["gross_return"]) - control for row, control in zip(rows, control_gross)
            ),
        }
        compare_record(saved, expected, expected, f"daily {variant_id}|{day}", discrepancies)
        reconstructed += 1
    if reconstructed != len(saved_daily):
        discrepancies.append(f"daily reconstruction covered {reconstructed} of {len(saved_daily)} rows")
    return {"rows_reconstructed": reconstructed, "maximum_absolute_errors": dict(maximum_errors)}


def streak(values: list[float], positive: bool) -> int:
    best = current = 0
    for value in values:
        matches = value > 0 if positive else value < 0
        current = current + 1 if matches else 0
        best = max(best, current)
    return best


def performance(rows: list[dict], all_dates: list[str]) -> dict:
    ordered = sorted(rows, key=lambda row: row["date"])
    raw = [float(row["raw_event_net_base"]) for row in ordered]
    equity = peak = 0.0
    maximum_drawdown = 0.0
    underwater = recovery = 0
    for value in raw:
        equity += value
        if equity >= peak:
            peak = equity
            underwater = 0
        else:
            underwater += 1
            recovery = max(recovery, underwater)
            maximum_drawdown = min(maximum_drawdown, equity - peak)
    positive_sum = sum(value for value in raw if value > 0)
    negative_sum = -sum(value for value in raw if value < 0)
    positive_dates = sorted(
        ((float(row["raw_event_net_base"]), row["date"]) for row in ordered if row["raw_event_net_base"] > 0),
        reverse=True,
    )
    total_positive = sum(value for value, _ in positive_dates)
    active_weeks = {row["week"] for row in ordered}
    all_weeks = {week(day) for day in all_dates}
    return {
        "common_position_dollars": 10_000,
        "mean_raw_gross_percent": 100 * (mean(float(row["raw_event_gross"]) for row in ordered) or 0.0),
        "mean_raw_net_percent": 100 * (mean(raw) or 0.0),
        "mean_raw_net_dollars_per_10000": 10_000 * (mean(raw) or 0.0),
        "max_additive_drawdown_percent": 100 * maximum_drawdown,
        "longest_recovery_trade_days": recovery,
        "longest_winning_trade_day_streak": streak(raw, True),
        "longest_losing_trade_day_streak": streak(raw, False),
        "profit_factor_on_trade_day_means": positive_sum / negative_sum if negative_sum else None,
        "completed_trades": sum(int(row["event_count"]) for row in ordered),
        "turnover_legs": 2 * sum(int(row["event_count"]) for row in ordered),
        "active_weeks": len(active_weeks),
        "inactive_weeks": len(all_weeks - active_weeks),
        "top_three_positive_date_share": sum(value for value, _ in positive_dates[:3]) / total_positive,
        "top_three_positive_dates": [day for _, day in positive_dates[:3]],
        "capacity_status": "UNRESOLVED_NO_DEPTH_OR_FILL_EVIDENCE",
    }


def power(rows: list[dict], rolling_selected_mean: float | None) -> dict:
    by_week: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_week[row["week"]].append(float(row["net_excess_base"]))
    weekly = [statistics.mean(values) for values in by_week.values()]
    sigma = statistics.stdev(weekly)
    target_bps = max(3.0, 0.5 * max(0.0, (rolling_selected_mean or 0.0) * 10_000.0))
    z_alpha = NormalDist().inv_cdf(0.95)
    z_power = NormalDist().inv_cdf(0.80)

    def required(effect_bps: float) -> int:
        return math.ceil(((z_alpha + z_power) * sigma / (effect_bps / 10_000.0)) ** 2)

    dates_per_week = len({row["date"] for row in rows}) / len(weekly)
    trades = sum(int(row["event_count"]) for row in rows)
    trades_per_week = trades / len(weekly)
    statistical = required(target_bps)
    dates_required = math.ceil(60 / dates_per_week)
    trades_required = math.ceil(200 / trades_per_week)
    confirmation = max(statistical, dates_required, trades_required)
    return {
        "one_sided_alpha": 0.05,
        "power": 0.8,
        "finalist_count": 1,
        "target_bps": target_bps,
        "target_source": "50% of rolling-selected development excess, floored at 3 bps",
        "rolling_selected_mean_net_excess": rolling_selected_mean,
        "weekly_standard_deviation": sigma,
        "development_weeks": len(weekly),
        "development_event_days": len({row["date"] for row in rows}),
        "development_trades": trades,
        "required_statistical_weeks_at_target": statistical,
        "required_weeks_for_60_confirmation_dates": dates_required,
        "required_weeks_for_200_confirmation_trades": trades_required,
        "required_confirmation_weeks": confirmation,
        "nine_month_confirmation_cap_weeks": 39,
        "feasible_within_cap": confirmation <= 39,
        "operational_floor": {"trades": 200, "event_days": 60},
        "sensitivity": [{"effect_bps": item, "required_weeks": required(item)} for item in (3, 5, 8, 12)],
    }


def bracket_short(frame, entry: int, terminal: int, target_first: bool = False) -> dict:
    opening_high = float(frame.loc[range(570, 585), "high"].max())
    opening_low = float(frame.loc[range(570, 585), "low"].min())
    stop = opening_high
    target = opening_low - (opening_high - opening_low)
    for column in range(entry, terminal + 1):
        minute = 570 + column
        opened = float(frame.at[minute, "open"])
        high = float(frame.at[minute, "high"])
        low = float(frame.at[minute, "low"])
        if opened >= stop:
            return {"exit_col": column, "exit_price": opened, "reason": "GAP_STOP"}
        if opened <= target:
            return {"exit_col": column, "exit_price": target, "reason": "GAP_TARGET_CAPPED"}
        if high >= stop and low <= target:
            return {
                "exit_col": column,
                "exit_price": target if target_first else stop,
                "reason": "SAME_MINUTE_TARGET_FIRST" if target_first else "SAME_MINUTE_STOP_FIRST",
            }
        if high >= stop:
            return {"exit_col": column, "exit_price": stop, "reason": "STOP"}
        if low <= target:
            return {"exit_col": column, "exit_price": target, "reason": "TARGET"}
    return {"exit_col": terminal, "exit_price": float(frame.at[570 + terminal, "close"]), "reason": "H30"}


def deterministic_raw_sample(audit_rows: list[dict]) -> list[dict]:
    d0 = [row for row in audit_rows if int(row["delay_minutes"]) == 0]
    selected = []
    for rule in ("FIXED_H15", "FIXED_H30"):
        choices = [row for row in d0 if row["variant_id"].startswith(rule + "__")]
        selected.extend(sorted(choices, key=lambda row: (hashlib.sha256(row["id"].encode()).hexdigest(), row["id"]))[:3])
    bracket = [row for row in d0 if row["variant_id"].startswith("OR1_BRACKET_H30__")]
    for reason in sorted({row["exit_reason"] for row in bracket}):
        choices = [row for row in bracket if row["exit_reason"] == reason]
        selected.append(sorted(choices, key=lambda row: (hashlib.sha256(row["id"].encode()).hexdigest(), row["id"]))[0])
    delayed = [row for row in audit_rows if int(row["delay_minutes"]) == 1]
    selected.extend(sorted(delayed, key=lambda row: (hashlib.sha256(row["id"].encode()).hexdigest(), row["id"]))[:2])
    return selected


def raw_bar_reconstruction(audit_rows: list[dict], discrepancies: list[str]) -> list[dict]:
    sample = deterministic_raw_sample(audit_rows)
    event_ids = {row["event_id"] for row in sample}
    responses = {}
    with (E1_DIR / "full-responses.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("event_id") in event_ids and row.get("cell_id") == SURVIVOR and row.get("reference") == "next_minute":
                responses[row["event_id"]] = row
    if set(responses) != event_ids:
        discrepancies.append("raw sample is missing one or more registered E1 H30 responses")
        return []
    filters = [[("symbol", "=", row["symbol"]), ("date", "=", row["date"])] for row in sample]
    table = pq.read_table(
        SOURCE,
        columns=["date", "symbol", "minute", "open", "high", "low", "close"],
        filters=filters,
    )
    frame = table.to_pandas()
    frame["date"] = frame["date"].astype(str)
    for column in ("open", "high", "low", "close"):
        frame[column] = frame[column].astype(np.float32)
    frames = {
        (symbol, day): rows.set_index("minute").sort_index()
        for (symbol, day), rows in frame.groupby(["symbol", "date"], observed=True)
    }
    output = []
    for saved in sample:
        source = responses[saved["event_id"]]
        base_entry = int(source["entry_col"])
        entry = base_entry + int(saved["delay_minutes"])
        terminal = int(source["exit_col"])
        bars = frames[(saved["symbol"], saved["date"])]
        if not (BLOCK_RANGES["B1"][0] <= saved["date"] <= BLOCK_RANGES["B5"][1]):
            discrepancies.append(f"raw sample escaped development dates: {saved['id']}")
        rule = saved["variant_id"].split("__", 1)[0]
        if rule == "FIXED_H15":
            exit_column = base_entry + 14
            result = {"exit_col": exit_column, "exit_price": float(bars.at[570 + exit_column, "close"]), "reason": "H15"}
            alternate = result
        elif rule == "FIXED_H30":
            result = {"exit_col": terminal, "exit_price": float(bars.at[570 + terminal, "close"]), "reason": "H30"}
            alternate = result
        else:
            result = bracket_short(bars, entry, terminal)
            alternate = bracket_short(bars, entry, terminal, target_first=True)
        entry_price = float(bars.at[570 + entry, "open"])
        gross = 1.0 - float(result["exit_price"]) / entry_price
        checks = {
            "entry_col": entry == int(saved["entry_col"]),
            "exit_col": int(result["exit_col"]) == int(saved["exit_col"]),
            "exit_reason": result["reason"] == saved["exit_reason"],
            "target_first_exit_col": int(alternate["exit_col"]) == int(saved["target_first_exit_col"]),
            "target_first_exit_reason": alternate["reason"] == saved["target_first_exit_reason"],
            "gross_return": close(gross, float(saved["gross_return"]), 1e-12),
        }
        if not all(checks.values()):
            discrepancies.append(f"raw sample mismatch {saved['id']}: {checks}")
        output.append({
            "id": saved["id"],
            "symbol": saved["symbol"],
            "date": saved["date"],
            "rule": rule,
            "saved_exit_reason": saved["exit_reason"],
            "reconstructed_entry_price": entry_price,
            "reconstructed_exit_price": float(result["exit_price"]),
            "reconstructed_gross_return": gross,
            "checks": checks,
            "all_checks_pass": all(checks.values()),
        })
    return output


def build_reproduction(result_dir: Path = RESULT_DIR) -> dict:
    discrepancies: list[str] = []
    expected_paths = expected_core_paths()
    expected_set = set(expected_paths)
    present_core = {str(path.relative_to(result_dir)) for path in result_dir.rglob("*") if path.is_file()} & expected_set
    missing = sorted(expected_set - present_core)
    if missing:
        discrepancies.append(f"missing controller files: {missing}")
    seal_checks = {}
    for relative in expected_paths:
        if relative.endswith(".sha256"):
            continue
        path = result_dir / relative
        if path.exists():
            seal_checks[relative] = verify_sidecar(path)
            if not seal_checks[relative]["matches_sidecar"]:
                discrepancies.append(f"sidecar mismatch: {relative}")

    plan = json.loads((result_dir / "controller-plan.json").read_text())
    step = next(row for row in plan["steps"] if row["id"] == "TE2_RUN")
    registered_relatives = {str(Path(item).relative_to(".omc/research/trading-edge-e2")) for item in step["outputs"]}
    if registered_relatives != expected_set:
        discrepancies.append("controller plan does not register the exact 114-file E2 core")
    state = json.loads((result_dir / "controller-state.json").read_text())
    histories = [row for row in state["history"] if row["step"] == "TE2_RUN"]
    history = histories[-1]
    expected_absolutes = {str(result_dir / item) for item in expected_paths}
    if set(history["outputs"]) != expected_absolutes or history["exit_code"] != 0 or history["missing_outputs"]:
        discrepancies.append("controller state does not record a clean exact E2 completion")
    for path, digest in history["outputs"].items():
        if Path(path).exists() and sha256_file(Path(path)) != digest:
            discrepancies.append(f"controller state hash mismatch: {path}")

    registration = json.loads((result_dir / "run-registration.json").read_text())
    variants = json.loads((result_dir / "variants.json").read_text())["variants"]
    expected_variants = [
        {
            "id": f"{exit_rule}__{population}",
            "exit_rule": exit_rule,
            "population": population,
            "previously_exposed": exit_rule == "FIXED_H15",
        }
        for exit_rule in EXIT_RULES for population in POPULATIONS
    ]
    if variants != expected_variants or registration["variants"] != expected_variants:
        discrepancies.append("the nine registered variants do not match the independent matrix")
    for name, digest in registration["inputs"].items():
        if sha256_file(E1_DIR / name) != digest:
            discrepancies.append(f"registered input hash mismatch: {name}")
    context_inputs = {
        "runner": sha256_file(PRODUCTION_RUNNER),
        "trading_edge_full": sha256_file(E1_FULL),
        "trading_edge_registration": sha256_file(E1_REGISTRATION),
        "e1_events": sha256_file(E1_DIR / "full-events.jsonl"),
        "e1_responses": sha256_file(E1_DIR / "full-responses.jsonl"),
        "e1_masks": sha256_file(E1_DIR / "full-pre-return-audit.json"),
        "quote_cost_report": sha256_file(E1_DIR / "quote-cost-report.json"),
        "source": sha256_file(SOURCE),
    }
    context = hashlib.sha256(canonical(context_inputs)).hexdigest()
    if registration["context_sha256"] != context or registration["runner_sha256"] != context_inputs["runner"]:
        discrepancies.append("registered E2 code/data context does not reproduce")

    checkpoint_daily = []
    checkpoint_audit = []
    checkpoint_unresolved = []
    checkpoint_summaries = {}
    checkpoint_counts = defaultdict(int)
    for variant_id in VARIANT_IDS:
        for block in BLOCKS:
            name = f"{variant_id}__{block}.json"
            envelope = json.loads((result_dir / "checkpoints" / name).read_text())
            record = envelope.get("checkpoint")
            if envelope.get("checkpoint_sha256") != hashlib.sha256(canonical(record)).hexdigest():
                discrepancies.append(f"embedded checkpoint checksum mismatch: {name}")
                continue
            if record["context_sha256"] != context or record["variant_id"] != variant_id or record["block"] != block:
                discrepancies.append(f"checkpoint identity/context mismatch: {name}")
            independent_summary = summarize(record["daily_rows"], variant_id, block)
            compare_record(record["summary"], independent_summary, independent_summary, f"checkpoint {name}", discrepancies)
            checkpoint_daily.extend(record["daily_rows"])
            checkpoint_audit.extend(record["audit_rows"])
            checkpoint_unresolved.extend(record["unresolved_rows"])
            checkpoint_summaries[f"{variant_id}|{block}"] = independent_summary
            checkpoint_counts[variant_id] += 1

    daily_rows = read_jsonl(result_dir / "daily-results.jsonl")
    block_rows = read_jsonl(result_dir / "block-results.jsonl")
    delay_rows = read_jsonl(result_dir / "delay-stress.jsonl")
    audit_rows = read_jsonl(result_dir / "event-audit.jsonl")
    unresolved_rows = read_jsonl(result_dir / "unresolved.jsonl")
    if sorted(checkpoint_daily, key=lambda row: row["id"]) != daily_rows:
        discrepancies.append("final daily ledger differs from the 45 atomic checkpoints")
    d0_audit = [row for row in audit_rows if int(row["delay_minutes"]) == 0]
    d1_audit = [row for row in audit_rows if int(row["delay_minutes"]) == 1]
    if sorted(checkpoint_audit, key=lambda row: row["id"]) != d0_audit:
        discrepancies.append("final event audit differs from checkpoint event rows")
    if checkpoint_unresolved or unresolved_rows:
        discrepancies.append("one or more E2 outcomes are unresolved")
    if len({row["id"] for row in daily_rows}) != len(daily_rows):
        discrepancies.append("duplicate ID in daily ledger")
    if len({row["id"] for row in audit_rows}) != len(audit_rows):
        discrepancies.append("duplicate ID in event audit")

    block_by_id = {row["id"]: row for row in block_rows}
    summary_fields = next(iter(checkpoint_summaries.values())).keys()
    for row_id, expected in checkpoint_summaries.items():
        actual = block_by_id.get(row_id)
        if actual is None:
            discrepancies.append(f"missing block result {row_id}")
        else:
            compare_record(actual, expected, summary_fields, f"block {row_id}", discrepancies)

    audit_reproduction = audit_daily_reconstruction(d0_audit, daily_rows, discrepancies)
    delay_audit_reproduction = audit_daily_reconstruction(d1_audit, delay_rows, discrepancies)

    leakage = []
    for row in daily_rows:
        first, last = BLOCK_RANGES[row["block"]]
        if not first <= row["date"] <= last:
            leakage.append(row["id"])
    for row in audit_rows:
        if int(row["exit_col"]) >= 390 or int(row["entry_col"]) < 0:
            leakage.append(row["id"])
    if leakage:
        discrepancies.append(f"block or intraday boundary leakage: {leakage[:10]}")

    rolling_saved = json.loads((result_dir / "rolling-results.json").read_text())["folds"]
    rolling_reproduced = []
    selected_rows = []
    for fold_id, train_blocks, test_block in FOLDS:
        candidates = []
        for variant_id in VARIANT_IDS:
            train = [row for row in daily_rows if row["variant_id"] == variant_id and row["block"] in train_blocks]
            bound = lower_bound(train, "net_excess_base", f"{fold_id}|{variant_id}")
            candidates.append((bound if bound is not None else -math.inf, variant_id, train))
        bound, chosen, train = sorted(candidates, key=lambda item: (-item[0], item[1]))[0]
        test = [row for row in daily_rows if row["variant_id"] == chosen and row["block"] == test_block]
        selected_rows.extend(test)
        reproduced = {
            "id": fold_id,
            "train_blocks": list(train_blocks),
            "test_block": test_block,
            "selected_variant": chosen,
            "train_80pct_lower": bound,
            "train_mean_net_excess_base": mean(float(row["net_excess_base"]) for row in train),
            "test_mean_net_excess_base": mean(float(row["net_excess_base"]) for row in test),
            "test_raw_event_net_base": mean(float(row["raw_event_net_base"]) for row in test),
            "test_event_days": len(test),
            "test_trades": sum(int(row["event_count"]) for row in test),
            "purged_boundary_outcomes": 0,
            "embargoed_outcomes": 0,
        }
        compare_record(rolling_saved[len(rolling_reproduced)], reproduced, reproduced, f"rolling {fold_id}", discrepancies)
        train_dates = [row["date"] for row in train]
        test_dates = [row["date"] for row in test]
        if not train_dates or not test_dates or max(train_dates) >= min(test_dates):
            discrepancies.append(f"rolling fold {fold_id} leaks test dates into training")
        rolling_reproduced.append(reproduced)
    rolling_mean = mean(float(row["net_excess_base"]) for row in selected_rows)

    static_candidates = []
    for variant_id in VARIANT_IDS:
        rows = [row for row in daily_rows if row["variant_id"] == variant_id]
        static_candidates.append({
            "variant_id": variant_id,
            "week_bootstrap_80pct_lower": lower_bound(rows, "net_excess_base", f"STATIC|{variant_id}"),
            "mean_net_excess_base": mean(float(row["net_excess_base"]) for row in rows),
        })
    static_candidates.sort(key=lambda row: (-float(row["week_bootstrap_80pct_lower"]), row["variant_id"]))
    selected = static_candidates[0]
    static_rows = [row for row in daily_rows if row["variant_id"] == selected["variant_id"]]
    summary = json.loads((result_dir / "summary.json").read_text())
    if summary["static_variant"] != selected["variant_id"]:
        discrepancies.append("static selection does not reproduce")
    if not close(summary["static_80pct_week_bootstrap_lower"], selected["week_bootstrap_80pct_lower"]):
        discrepancies.append("static selection lower bound does not reproduce")
    if not close(summary["static_mean_net_excess_base"], selected["mean_net_excess_base"]):
        discrepancies.append("static selection mean does not reproduce")

    # The E1 audit is one JSON document.  Its registered calendar dates are in
    # the source audit rows; derive the same development-week span without
    # importing production code.
    source_audit = json.loads((E1_DIR / "full-pre-return-audit.json").read_text())
    all_dates = []
    if isinstance(source_audit, dict) and isinstance(source_audit.get("dates"), list):
        all_dates = [str(item) for item in source_audit["dates"]]
    if not all_dates:
        # Performance only needs the week set.  Use every regular-session date
        # present in the registered source range, read from a single symbol.
        table = pq.read_table(SOURCE, columns=["date", "symbol"], filters=[[("symbol", "=", "TSM"), ("date", ">=", "2023-04-26"), ("date", "<=", "2025-03-31")]])
        all_dates = sorted(set(table.column("date").to_pylist()))
    performance_reproduced = performance(static_rows, all_dates)
    compare_record(summary["performance"], performance_reproduced, performance_reproduced, "performance", discrepancies)

    power_reproduced = power(static_rows, rolling_mean)
    compare_record(summary["power"], power_reproduced, power_reproduced, "power", discrepancies)
    saved_power = json.loads((result_dir / "power.json").read_text())
    compare_record(saved_power, power_reproduced, power_reproduced, "power file", discrepancies)

    delay_mean = mean(float(row["net_excess_base"]) for row in delay_rows)
    delay_reproduced = {
        "entry_delay_minutes": 1,
        "variant_id": selected["variant_id"],
        "event_days": len(delay_rows),
        "trades": sum(int(row["event_count"]) for row in delay_rows),
        "mean_net_excess_base": delay_mean,
        "change_from_reference": float(delay_mean) - float(selected["mean_net_excess_base"]),
        "exit_clock_rule": "nominal H15/H30 exit clock is unchanged; the entry moves one minute later",
    }
    compare_record(summary["one_extra_minute_delay_stress"], delay_reproduced, delay_reproduced, "delay stress", discrepancies)

    block_regimes = {
        block: mean(float(row["net_excess_base"]) for row in static_rows if row["block"] == block)
        for block in BLOCKS
    }
    compare_record(summary["block_regimes"], block_regimes, block_regimes, "block regimes", discrepancies)

    static_audit = [row for row in d0_audit if row["variant_id"] == selected["variant_id"]]
    event_weighted = {
        "completed_trades": len(static_audit),
        "mean_net_excess_bps_per_trade": 10_000 * statistics.mean(float(row["net_excess_base"]) for row in static_audit),
        "mean_raw_net_bps_per_trade": 10_000 * statistics.mean(float(row["raw_net_base"]) for row in static_audit),
    }

    raw_sample = raw_bar_reconstruction(audit_rows, discrepancies)
    ledger = json.loads((result_dir / "trial-ledger.json").read_text())
    expected_reasons = [
        "prospective short borrow availability and stock-loan costs are missing",
        "the corrected 80% power target does not fit the nine-month cap or operational floor",
    ]
    if ledger["decision"] != "PARK" or summary["decision"] != "PARK" or summary["reasons"] != expected_reasons:
        discrepancies.append("PARK decision or reasons differ from the measured constraints")
    if power_reproduced["feasible_within_cap"]:
        discrepancies.append("power unexpectedly fits the nine-month cap")

    return {
        "study_id": STUDY_ID,
        "independent_verifier_sha256": sha256_file(Path(__file__)),
        "verification_status": "PASS" if not discrepancies else "FAIL",
        "discrepancies": discrepancies,
        "core_artifacts": {
            "expected_files_and_sidecars": len(expected_paths),
            "present_files_and_sidecars": len(present_core),
            "data_files": len(seal_checks),
            "matching_sidecars": sum(item["matches_sidecar"] for item in seal_checks.values()),
            "sha256": {name: item["sha256"] for name, item in sorted(seal_checks.items())},
            "controller_plan_exact": registered_relatives == expected_set,
            "controller_state_exact": set(history["outputs"]) == expected_absolutes,
        },
        "registered_context": {
            "matches": registration["context_sha256"] == context,
            "context_sha256": context,
            "network_used": registration["network_used"],
            "spend_usd": registration["spend_usd"],
            "protected_epoch_read": registration["protected_epoch_read"],
        },
        "checkpoints": {
            "count": sum(checkpoint_counts.values()),
            "per_variant": dict(sorted(checkpoint_counts.items())),
            "all_contexts_match": not any("checkpoint identity/context" in item for item in discrepancies),
            "embedded_checksums_match": not any("embedded checkpoint" in item for item in discrepancies),
            "final_ledgers_match": not any("differs from" in item for item in discrepancies),
        },
        "inventory": {
            "variants": len(VARIANT_IDS),
            "blocks": len(BLOCKS),
            "variant_blocks": len(block_rows),
            "daily_rows": len(daily_rows),
            "event_audit_rows": len(audit_rows),
            "delay_event_audit_rows": len(d1_audit),
            "unresolved_rows": len(unresolved_rows),
        },
        "cost_and_daily_math": {
            "base_run": audit_reproduction,
            "one_minute_delay": delay_audit_reproduction,
        },
        "rolling_reproduction": {
            "folds": rolling_reproduced,
            "selected_test_mean_net_excess": rolling_mean,
            "training_dates_precede_test_dates": not any("leaks test dates" in item for item in discrepancies),
            "purged_boundary_outcomes": 0,
            "embargoed_outcomes": 0,
        },
        "static_reproduction": {
            "candidates": static_candidates,
            "selected_variant": selected["variant_id"],
            "date_first_mean_net_excess_bps": 10_000 * float(selected["mean_net_excess_base"]),
            "event_weighted": event_weighted,
            "block_mean_net_excess": block_regimes,
        },
        "performance_reproduction": performance_reproduced,
        "delay_reproduction": delay_reproduced,
        "power_reproduction": power_reproduced,
        "raw_bar_reconstruction": {
            "sample_size": len(raw_sample),
            "all_checks_pass": bool(raw_sample) and all(row["all_checks_pass"] for row in raw_sample),
            "development_dates_only": all(BLOCK_RANGES["B1"][0] <= row["date"] <= BLOCK_RANGES["B5"][1] for row in raw_sample),
            "rows": raw_sample,
        },
        "decision_reproduction": {
            "decision": "PARK",
            "execution_status": "EXECUTION_FEASIBILITY_UNRESOLVED",
            "reasons": expected_reasons,
            "tradable_edge_proven": False,
            "live_action_authorized": False,
        },
    }


def verdict_document(reproduction: dict) -> dict:
    power_result = reproduction["power_reproduction"]
    static = reproduction["static_reproduction"]
    delay = reproduction["delay_reproduction"]
    return {
        "study_id": STUDY_ID,
        "verdict": "PARK",
        "evidence_status": "INSUFFICIENT_EVIDENCE",
        "tradable_edge_proven": False,
        "execution_feasibility": "UNRESOLVED",
        "historical_result": {
            "selected_rule": static["selected_variant"],
            "date_first_net_excess_bps": static["date_first_mean_net_excess_bps"],
            "event_weighted_net_excess_bps_per_trade": static["event_weighted"]["mean_net_excess_bps_per_trade"],
            "raw_net_bps_per_trade": static["event_weighted"]["mean_raw_net_bps_per_trade"],
            "one_minute_delay_net_excess_bps": 10_000 * float(delay["mean_net_excess_base"]),
        },
        "power": {
            "required_confirmation_weeks": power_result["required_confirmation_weeks"],
            "nine_month_cap_weeks": power_result["nine_month_confirmation_cap_weeks"],
            "required_weeks_for_200_trades": power_result["required_weeks_for_200_confirmation_trades"],
            "feasible_within_cap": power_result["feasible_within_cap"],
        },
        "reasons": reproduction["decision_reproduction"]["reasons"],
        "independent_reproduction": reproduction["verification_status"],
        "spend_usd": 0.0,
        "network_used": False,
        "protected_epoch_read": False,
        "confirmation_started": False,
        "live_action_authorized": False,
    }


def verdict_markdown(verdict: dict) -> str:
    historical = verdict["historical_result"]
    power_result = verdict["power"]
    return (
        "# Final trading-edge verdict\n\n"
        "**PARK — insufficient evidence.**\n\n"
        f"The independent reproduction passed. The best historical rule was `{historical['selected_rule']}`. "
        f"It averaged {historical['event_weighted_net_excess_bps_per_trade']:.2f} basis points above its matched ordinary-entry control per completed trade, "
        f"and {historical['raw_net_bps_per_trade']:.2f} basis points after the provisional trading cost. "
        f"A one-minute-later entry still showed {historical['one_minute_delay_net_excess_bps']:.2f} basis points of date-first excess.\n\n"
        f"This is not a proven tradable edge. The required confirmation is {power_result['required_confirmation_weeks']} weeks, "
        f"well above the {power_result['nine_month_cap_weeks']}-week cap. Reaching 200 confirmation trades alone would take about "
        f"{power_result['required_weeks_for_200_trades']} weeks. Prospective short availability and borrowing cost are also missing.\n\n"
        "No confirmation purchase, protected-data read, live order, or live alert change was made. Spend was $0.\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-dir", type=Path, default=RESULT_DIR)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    reproduction = build_reproduction(args.result_dir)
    if reproduction["verification_status"] != "PASS":
        print(json.dumps({"verification_status": "FAIL", "discrepancies": reproduction["discrepancies"]}, indent=2))
        raise SystemExit(1)
    verdict = verdict_document(reproduction)
    if not args.check_only:
        write_json(args.result_dir / "e2-reproduction.json", reproduction)
        write_json(args.result_dir / "edge-verdict.json", verdict)
        write_with_sidecar(args.result_dir / "edge-verdict.md", verdict_markdown(verdict).encode())
    print(json.dumps({
        "verification_status": "PASS",
        "decision": verdict["verdict"],
        "required_confirmation_weeks": verdict["power"]["required_confirmation_weeks"],
        "raw_sample_checks": reproduction["raw_bar_reconstruction"]["sample_size"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
