#!/usr/bin/env python3
"""Independently verify the registered E1 result and write its proof package.

This program intentionally does not import the E1 event, response, summary, or
ranking implementation. It reads the persisted ledgers, reconstructs a fixed
raw-bar sample through the registered read guard, and recomputes the selected
cell's arithmetic and deterministic ranking.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import random
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import numpy as np
import pandas as pd


WORKSPACE = Path(__file__).resolve().parents[2]
RESULT_DIR = WORKSPACE / ".omc/research/trading-edge-discovery"
REGISTRATION_PATH = Path(__file__).resolve().with_name("trading_edge_registration.py")
CANDIDATE_ID = "OR15_VOL_2P5__SHORT__H30"
OPEN_MINUTE = 570
SEED = 20260925
TOLERANCE = 2e-15
FULL_ARTIFACTS = (
    "full-pre-return-audit.json",
    "full-events.jsonl",
    "full-responses.jsonl",
    "full-censors.jsonl",
    "full-control-daily.jsonl",
    "full-cell-summaries.jsonl",
    "full-daily-responses.jsonl",
    "full-effective-variants.json",
    "full-power-table.json",
    "full-ranked-discovery.csv",
    "full-trial-ledger.json",
    "full-summary.json",
)
PROOF_ARTIFACTS = (
    "full-market-adjusted-ranking.csv",
    "e1-independent-reconstruction.json",
    "e1-owner-report.md",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_sidecar(path: Path) -> str:
    digest = sha256_file(path)
    sidecar = path.with_suffix(path.suffix + ".sha256")
    sidecar.write_text(f"{digest}  {path.name}\n")
    return digest


def write_json(path: Path, value: object) -> str:
    payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)
    return _write_sidecar(path)


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> str:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)
    return _write_sidecar(path)


def write_text(path: Path, value: str) -> str:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value)
    os.replace(temporary, path)
    return _write_sidecar(path)


def read_jsonl(path: Path) -> Iterable[dict]:
    with path.open() as handle:
        for line in handle:
            yield json.loads(line)


def verify_sidecar(path: Path) -> dict:
    sidecar = path.with_suffix(path.suffix + ".sha256")
    expected = sidecar.read_text().strip().split()[0]
    actual = sha256_file(path)
    return {"sha256": actual, "matches_sidecar": actual == expected}


def count_unique_ids(path: Path) -> dict:
    seen: set[str] = set()
    count = 0
    duplicates: list[str] = []
    for row in read_jsonl(path):
        count += 1
        row_id = str(row["id"])
        if row_id in seen and len(duplicates) < 10:
            duplicates.append(row_id)
        seen.add(row_id)
    return {
        "rows": count,
        "unique_ids": len(seen),
        "duplicate_ids": duplicates,
    }


def mean(values: Iterable[float]) -> float:
    return statistics.mean(list(values))


def iso_week(day: str) -> str:
    year, week, _ = date.fromisoformat(day).isocalendar()
    return f"{year:04d}-W{week:02d}"


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def week_bootstrap(
    event_rows: list[dict], control_rows: dict[str, list[dict]], *,
    subtract_event_cost: bool = False, market_adjusted: bool = False,
) -> dict:
    sign = -1
    control_by_week: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for group, rows in control_rows.items():
        for row in rows:
            if market_adjusted:
                count = int(row["market_residual_count"])
                if not count:
                    continue
                value = sign * float(row["sum_market_residual"]) / count
            else:
                value = sign * float(row["sum_raw_return"]) / int(row["opportunity_count"])
            control_by_week[iso_week(row["date"])][group].append(value)
    control_stats = {
        week: {group: (sum(values), len(values)) for group, values in groups.items()}
        for week, groups in control_by_week.items()
    }

    global_market_control = {}
    if market_adjusted:
        for group, rows in control_rows.items():
            values = [
                sign * float(row["sum_market_residual"]) / int(row["market_residual_count"])
                for row in rows if int(row["market_residual_count"])
            ]
            if values:
                global_market_control[group] = mean(values)

    event_by_week = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for row in event_rows:
        group = row["control_group_id"]
        if market_adjusted:
            if row["market_adjusted_excess"] is None or group not in global_market_control:
                continue
            event_residual = float(row["market_adjusted_excess"]) + global_market_control[group]
            value = event_residual
        else:
            value = float(row["signed_return"])
            if subtract_event_cost:
                value -= float(row["cost_floor_bps"]) / 10000.0
        event_by_week[iso_week(row["date"])][(CANDIDATE_ID, row["date"])][group].append(value)
    event_stats = {
        week: {
            group_id: {
                control_key: (sum(values), len(values))
                for control_key, values in keyed.items()
            }
            for group_id, keyed in groups.items()
        }
        for week, groups in event_by_week.items()
    }

    weeks = sorted(set(control_by_week) | set(event_by_week))
    seed = SEED + int(hashlib.sha256(CANDIDATE_ID.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    boot_means: list[float] = []
    for _ in range(1000):
        selected = Counter(rng.choices(weeks, k=len(weeks)))
        totals: dict[str, list[float | int]] = defaultdict(lambda: [0.0, 0])
        for week, multiplicity in selected.items():
            for group, (value_sum, value_count) in control_stats.get(week, {}).items():
                totals[group][0] += value_sum * multiplicity
                totals[group][1] += value_count * multiplicity
        control_means = {
            group: float(value_sum) / int(value_count)
            for group, (value_sum, value_count) in totals.items()
        }
        daily_sum = 0.0
        daily_count = 0
        for week, multiplicity in selected.items():
            for keyed in event_stats.get(week, {}).values():
                row_sum = 0.0
                row_count = 0
                for group, (value_sum, value_count) in keyed.items():
                    if group not in control_means:
                        continue
                    row_sum += value_sum - value_count * control_means[group]
                    row_count += value_count
                if row_count:
                    daily_sum += multiplicity * row_sum / row_count
                    daily_count += multiplicity
        if daily_count:
            boot_means.append(daily_sum / daily_count)
    return {
        "seed": seed,
        "draws": len(boot_means),
        "lower_80": percentile(boot_means, 0.20),
        "median": percentile(boot_means, 0.50),
        "upper_80": percentile(boot_means, 0.80),
    }


def market_adjusted_ranking(summaries: dict[str, dict]) -> list[dict]:
    rows = [
        {
            "cell_id": row["cell_id"],
            "market_adjusted_80pct_week_bootstrap_lower": row.get(
                "market_adjusted_80pct_week_bootstrap_lower"
            ),
            "market_adjusted_count": int(row.get("market_adjusted_count", 0)),
            "bh_q_value": float(row["bh_q_value"]),
        }
        for row in summaries.values()
        if row.get("is_primary_horizon") and row.get("status") == "measured"
    ]
    rows.sort(key=lambda row: (
        row["market_adjusted_80pct_week_bootstrap_lower"] is None,
        -(
            row["market_adjusted_80pct_week_bootstrap_lower"]
            if row["market_adjusted_80pct_week_bootstrap_lower"] is not None
            else -math.inf
        ),
        row["cell_id"],
    ))
    return [{"rank": index, **row} for index, row in enumerate(rows, 1)]


def neighbor_ids(setting: dict, settings: list[dict]) -> list[str]:
    family = setting["family"]
    if family == "opening_range":
        peers = [
            row for row in settings
            if row["family"] == family
            and row["opening_minutes"] == setting["opening_minutes"]
        ]
        ordered = [row["id"] for row in peers]
        position = ordered.index(setting["id"])
        return [ordered[index] for index in (position - 1, position + 1)
                if 0 <= index < len(ordered)]
    if family == "high_low_breakout":
        return [row["id"] for row in settings
                if row["family"] == family and row["id"] != setting["id"]]
    if family == "first_pullback":
        return [
            row["id"] for row in settings
            if row["family"] == family and row["id"] != setting["id"]
            and (
                (row["session_vwap_support"] != setting["session_vwap_support"])
                + (row["impulse_anchored_vwap_support"]
                   != setting["impulse_anchored_vwap_support"])
                == 1
            )
        ]
    return []


def reproduce_selection(
    summaries: dict[str, dict], registration: dict, effective: dict,
) -> tuple[list[dict], list[str]]:
    settings = registration["settings"]
    setting_by_id = {row["id"]: row for row in settings}
    candidates = []
    for row in summaries.values():
        if not row.get("is_primary_horizon") or row.get("status") != "measured":
            continue
        setting = setting_by_id[row["setting_id"]]
        neighbors = neighbor_ids(setting, settings)
        neighbor_agrees = True if not neighbors else any(
            summaries.get(
                f"{neighbor}__{row['direction'].upper()}__H{row['horizon_minutes']}", {}
            ).get("mean_plain_gross_excess", -math.inf) > 0
            for neighbor in neighbors
        )
        incremental = True
        if setting["family"] == "opening_range" and setting["opening_volume_gate"] is not None:
            off_id = (
                f"OR{setting['opening_minutes']}_VOL_OFF__"
                f"{row['direction'].upper()}__H{row['horizon_minutes']}"
            )
            incremental = (
                row["mean_plain_gross_excess"]
                > summaries[off_id]["mean_plain_gross_excess"]
            )
        gates = {
            "plain_excess_positive": row["mean_plain_gross_excess"] > 0,
            "raw_net_positive": row["mean_raw_net_floor"] > 0,
            "at_least_three_positive_blocks": row["positive_blocks"] >= 3,
            "positive_after_top_three_removal": (
                row["mean_excess_after_top_three_removal"] or -math.inf
            ) > 0,
            "neighbor_agrees": neighbor_agrees,
            "volume_variant_improves_off": incremental,
        }
        label = f"{row['setting_id']}__{row['direction'].upper()}"
        candidates.append({
            "cell_id": row["cell_id"],
            "setting_id": row["setting_id"],
            "family": row["family"],
            "direction": row["direction"],
            "effective_group": effective["label_to_group"][label],
            "selection_score": row["selection_score_80pct_week_bootstrap_lower"],
            "eligible": all(gates.values()),
            "gates": gates,
        })
    candidates.sort(key=lambda row: (
        not row["eligible"],
        -(row["selection_score"] if row["selection_score"] is not None else -math.inf),
        row["setting_id"],
        row["direction"],
    ))
    selected = []
    family_counts: Counter[str] = Counter()
    used_groups = set()
    for row in candidates:
        if not row["eligible"]:
            continue
        if family_counts[row["family"]] >= 2 or row["effective_group"] in used_groups:
            continue
        selected.append(row["cell_id"])
        family_counts[row["family"]] += 1
        used_groups.add(row["effective_group"])
        if len(selected) == 5:
            break
    return candidates, selected


def power_estimates(daily: list[float], weekly: list[float]) -> dict:
    multiplier = (1.6448536269514722 + 0.8416212335729143) ** 2
    daily_sd = statistics.stdev(daily)
    weekly_sd = statistics.stdev(weekly)
    return {
        str(effect): {
            "required_days": math.ceil(multiplier * (daily_sd / (effect / 10000)) ** 2),
            "required_weeks": math.ceil(multiplier * (weekly_sd / (effect / 10000)) ** 2),
        }
        for effect in (3, 5, 8, 12)
    }


def _load_registration_module():
    spec = importlib.util.spec_from_file_location("e1_registered_reader", REGISTRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def deterministic_sample(rows: list[dict], size: int = 10) -> list[dict]:
    return sorted(
        rows,
        key=lambda row: (hashlib.sha256(row["id"].encode()).hexdigest(), row["id"]),
    )[:size]


def reconstruct_raw_sample(rows: list[dict], events: dict[str, dict]) -> list[dict]:
    registration = _load_registration_module()
    sample = deterministic_sample(rows)
    calendar = xcals.get_calendar("XNYS")
    sessions = [
        stamp.date().isoformat()
        for stamp in calendar.sessions_in_range(
            registration.DEVELOPMENT_FIRST, registration.DEVELOPMENT_LAST
        )
    ]
    session_index = {day: index for index, day in enumerate(sessions)}
    by_symbol = defaultdict(list)
    for row in sample:
        by_symbol[row["symbol"]].append(row)
    frames = {}
    for symbol, symbol_rows in by_symbol.items():
        first = min(sessions[session_index[row["date"]] - 20] for row in symbol_rows)
        last = max(row["date"] for row in symbol_rows)
        batches = registration.guarded_parquet_batches(
            registration.PRIMARY_SOURCE,
            [symbol],
            first,
            last,
            ["minute", "open", "high", "low", "close", "volume"],
        )
        frame = pd.concat([batch.to_pandas() for batch in batches], ignore_index=True)
        frame["date"] = frame["date"].astype(str)
        frame["minute"] = frame["minute"].astype(int)
        for column in ("open", "high", "low", "close", "volume"):
            frame[column] = frame[column].astype(np.float32)
        for day, day_frame in frame.groupby("date"):
            frames[(symbol, day)] = day_frame.set_index("minute").sort_index()

    output = []
    for row in sample:
        symbol = row["symbol"]
        day = row["date"]
        day_position = session_index[day]
        prior_days = sessions[day_position - 20:day_position]
        frame = frames[(symbol, day)]
        opening_minutes = list(range(OPEN_MINUTE, OPEN_MINUTE + 15))
        prior_sums = np.asarray([
            frames[(symbol, prior)].loc[opening_minutes, "volume"].to_numpy(
                dtype=np.float32
            ).sum(dtype=np.float32)
            for prior in prior_days
        ], dtype=np.float32)
        current_sum = frame.loc[opening_minutes, "volume"].to_numpy(
            dtype=np.float32
        ).sum(dtype=np.float32)
        rvol = float(np.float32(current_sum / np.nanmean(prior_sums)))
        opening_low = float(frame.loc[opening_minutes, "low"].min())
        signal_position = None
        for position in range(15, min(len(frame), 300)):
            previous = float(frame.loc[OPEN_MINUTE + position - 1, "close"])
            current = float(frame.loc[OPEN_MINUTE + position, "close"])
            if previous >= opening_low > current:
                signal_position = position
                break
        if signal_position is None:
            raise AssertionError(f"sampled signal did not reconstruct: {row['id']}")
        entry_position = signal_position + 1
        exit_position = signal_position + 30
        entry_price = float(frame.loc[OPEN_MINUTE + entry_position, "open"])
        exit_price = float(frame.loc[OPEN_MINUTE + exit_position, "close"])
        signed_return = -(exit_price / entry_price - 1.0)
        path = frame.loc[
            OPEN_MINUTE + entry_position:OPEN_MINUTE + exit_position
        ]
        favorable = 1.0 - float(path["low"].min()) / entry_price
        adverse = 1.0 - float(path["high"].max()) / entry_price
        cost_floor = 8 if entry_position < 60 or exit_position < 60 else 5
        completed_minute = OPEN_MINUTE + signal_position + 1
        completed = datetime.combine(
            date.fromisoformat(day), datetime.min.time()
        ).replace(
            hour=completed_minute // 60,
            minute=completed_minute % 60,
            tzinfo=ZoneInfo("America/New_York"),
        ).astimezone(ZoneInfo("America/Los_Angeles")).isoformat(timespec="minutes")
        event = events[row["event_id"]]
        checks = {
            "volume_gate_at_least_2_5": rvol >= 2.5,
            "first_close_cross_position": signal_position == row["entry_col"] - 1,
            "signal_minute": OPEN_MINUTE + signal_position == event["signal_minute"],
            "completed_time_pacific": completed == event["signal_completed_time_pacific"],
            "entry_position": entry_position == row["entry_col"],
            "exit_position": exit_position == row["exit_col"],
            "entry_price": math.isclose(entry_price, row["entry_price"], rel_tol=0, abs_tol=1e-12),
            "exit_price": math.isclose(exit_price, row["exit_price"], rel_tol=0, abs_tol=1e-12),
            "signed_return": math.isclose(signed_return, row["signed_return"], rel_tol=0, abs_tol=1e-15),
            "favorable_excursion": math.isclose(favorable, row["favorable_excursion"], rel_tol=0, abs_tol=1e-15),
            "adverse_excursion": math.isclose(adverse, row["adverse_excursion"], rel_tol=0, abs_tol=1e-15),
            "cost_floor": cost_floor == row["cost_floor_bps"],
        }
        output.append({
            "id": row["id"],
            "symbol": symbol,
            "date": day,
            "rvol_15": rvol,
            "opening_low": opening_low,
            "signal_position": signal_position,
            "entry_position": entry_position,
            "exit_position": exit_position,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "signed_return": signed_return,
            "cost_floor_bps": cost_floor,
            "checks": checks,
            "all_checks_pass": all(checks.values()),
        })
    return output


def _maximum_error(pairs: Iterable[tuple[float, float]]) -> float:
    return max(abs(left - right) for left, right in pairs)


def build_reconstruction(result_dir: Path) -> tuple[dict, list[dict]]:
    source_checks = {
        name: verify_sidecar(result_dir / name) for name in FULL_ARTIFACTS
    }
    if not all(row["matches_sidecar"] for row in source_checks.values()):
        raise AssertionError("one or more full E1 artifacts fail their SHA-256 sidecar")

    inventory = {
        name: count_unique_ids(result_dir / name)
        for name in (
            "full-events.jsonl",
            "full-responses.jsonl",
            "full-control-daily.jsonl",
            "full-daily-responses.jsonl",
            "full-cell-summaries.jsonl",
        )
    }
    if any(row["duplicate_ids"] for row in inventory.values()):
        raise AssertionError("a persisted E1 ledger contains duplicate IDs")

    registration = json.loads((result_dir / "run-registration.json").read_text())
    effective = json.loads((result_dir / "full-effective-variants.json").read_text())
    summaries = {
        row["cell_id"]: row for row in read_jsonl(result_dir / "full-cell-summaries.jsonl")
    }
    candidate_summary = summaries[CANDIDATE_ID]

    candidate_rows = []
    event_ids = set()
    for row in read_jsonl(result_dir / "full-responses.jsonl"):
        if row["cell_id"] == CANDIDATE_ID and row["reference"] == "next_minute":
            candidate_rows.append(row)
            event_ids.add(row["event_id"])
    events = {
        row["id"]: row for row in read_jsonl(result_dir / "full-events.jsonl")
        if row["id"] in event_ids
    }
    groups = {row["control_group_id"] for row in candidate_rows}
    controls: dict[str, list[dict]] = defaultdict(list)
    for row in read_jsonl(result_dir / "full-control-daily.jsonl"):
        if row["control_group_id"] in groups:
            controls[row["control_group_id"]].append(row)
    if set(controls) != groups:
        raise AssertionError("one or more candidate control groups are unresolved")

    sign = -1
    control_raw = {
        group: mean(
            float(row["sum_raw_return"]) / int(row["opportunity_count"])
            for row in rows
        )
        for group, rows in controls.items()
    }
    control_cost = {
        group: mean(
            float(row["sum_cost_floor_bps"]) / int(row["opportunity_count"])
            for row in rows
        )
        for group, rows in controls.items()
    }
    raw = [float(row["signed_return"]) for row in candidate_rows]
    plain = [
        float(row["signed_return"]) - sign * control_raw[row["control_group_id"]]
        for row in candidate_rows
    ]
    raw_net = [
        float(row["signed_return"]) - float(row["cost_floor_bps"]) / 10000.0
        for row in candidate_rows
    ]
    net_floor = [
        (
            float(row["signed_return"]) - float(row["cost_floor_bps"]) / 10000.0
        ) - (
            sign * control_raw[row["control_group_id"]]
            - control_cost[row["control_group_id"]] / 10000.0
        )
        for row in candidate_rows
    ]
    net_20 = [
        (float(row["signed_return"]) - 0.002)
        - (sign * control_raw[row["control_group_id"]] - 0.002)
        for row in candidate_rows
    ]
    net_twice = [
        (
            float(row["signed_return"])
            - 2 * float(row["cost_floor_bps"]) / 10000.0
        ) - (
            sign * control_raw[row["control_group_id"]]
            - 2 * control_cost[row["control_group_id"]] / 10000.0
        )
        for row in candidate_rows
    ]

    by_block = defaultdict(list)
    by_day = defaultdict(list)
    by_symbol_day = defaultdict(list)
    for row, value in zip(candidate_rows, plain):
        by_block[row["block"]].append(value)
        by_day[row["date"]].append(value)
        by_symbol_day[(row["symbol"], row["date"])].append(value)
    strongest = sorted(
        ((mean(values), symbol, day)
         for (symbol, day), values in by_symbol_day.items() if mean(values) > 0),
        key=lambda item: (-item[0], item[1], item[2]),
    )[:3]
    removed = {(symbol, day) for _, symbol, day in strongest}
    remaining = [
        value for row, value in zip(candidate_rows, plain)
        if (row["symbol"], row["date"]) not in removed
    ]

    daily_saved = [
        row for row in read_jsonl(result_dir / "full-daily-responses.jsonl")
        if row["cell_id"] == CANDIDATE_ID
    ]
    daily_plain = [float(row["mean_plain_gross_excess"]) for row in daily_saved]
    daily_market = [
        float(row["mean_market_adjusted_excess"]) for row in daily_saved
        if row["mean_market_adjusted_excess"] is not None
    ]
    plain_by_week = defaultdict(list)
    market_by_week = defaultdict(list)
    for row in daily_saved:
        plain_by_week[row["week"]].append(float(row["mean_plain_gross_excess"]))
        if row["mean_market_adjusted_excess"] is not None:
            market_by_week[row["week"]].append(float(row["mean_market_adjusted_excess"]))
    weekly_plain = [mean(values) for values in plain_by_week.values()]
    weekly_market = [mean(values) for values in market_by_week.values()]

    plain_bootstrap = week_bootstrap(candidate_rows, controls)
    score_bootstrap = week_bootstrap(candidate_rows, controls, subtract_event_cost=True)
    market_bootstrap = week_bootstrap(candidate_rows, controls, market_adjusted=True)

    candidates, selected = reproduce_selection(summaries, registration, effective)
    persisted_ranking = list(csv.DictReader((result_dir / "full-ranked-discovery.csv").open()))
    ranking_matches = all(
        persisted_ranking[index]["cell_id"] == row["cell_id"]
        and persisted_ranking[index]["eligible"] == str(row["eligible"])
        and float(persisted_ranking[index]["selection_score"]) == row["selection_score"]
        and int(persisted_ranking[index]["rank"]) == index + 1
        and (persisted_ranking[index]["selected_top_five"] == "True")
        == (row["cell_id"] in selected)
        for index, row in enumerate(candidates)
    )

    ordered_p = sorted(
        enumerate(summaries.values()),
        key=lambda item: (item[1]["p_value"], item[1]["cell_id"], item[0]),
    )
    q_values = {}
    running = 1.0
    for reverse_index in range(len(ordered_p) - 1, -1, -1):
        original, row = ordered_p[reverse_index]
        running = min(running, row["p_value"] * len(ordered_p) / (reverse_index + 1))
        q_values[original] = min(1.0, running)
    summary_list = list(summaries.values())
    max_q_error = max(
        abs(q_values[index] - row["bh_q_value"])
        for index, row in enumerate(summary_list)
    )

    reconstructed = {
        "event_count": len(candidate_rows),
        "distinct_dates": len(by_day),
        "distinct_symbols": len({row["symbol"] for row in candidate_rows}),
        "mean_raw_signed_return": mean(raw),
        "mean_event_cost_floor_bps": mean(
            float(row["cost_floor_bps"]) for row in candidate_rows
        ),
        "mean_raw_net_floor": mean(raw_net),
        "mean_plain_gross_excess": mean(plain),
        "mean_net_excess_floor": mean(net_floor),
        "mean_net_excess_20bps": mean(net_20),
        "mean_net_excess_twice_floor": mean(net_twice),
        "block_mean_excess": {
            block: mean(values) for block, values in sorted(by_block.items())
        },
        "positive_blocks": sum(mean(values) > 0 for values in by_block.values()),
        "top_three_symbol_days_removed": [
            {"symbol": symbol, "date": day, "mean_excess": value}
            for value, symbol, day in strongest
        ],
        "mean_excess_after_top_three_removal": mean(remaining),
        "plain_bootstrap": plain_bootstrap,
        "selection_score_bootstrap": score_bootstrap,
        "market_adjusted_bootstrap": market_bootstrap,
        "plain_power": power_estimates(daily_plain, weekly_plain),
        "market_adjusted_power": power_estimates(daily_market, weekly_market),
        "plain_observed_days": len(daily_plain),
        "plain_observed_weeks": len(weekly_plain),
        "market_adjusted_events": sum(
            row["market_adjusted_excess"] is not None for row in candidate_rows
        ),
        "market_adjusted_days": len(daily_market),
        "market_adjusted_weeks": len(weekly_market),
    }
    errors = {
        "plain_response_rows": _maximum_error(
            zip(plain, (float(row["plain_gross_excess"]) for row in candidate_rows))
        ),
        "floor_net_response_rows": _maximum_error(
            zip(net_floor, (float(row["net_excess_floor"]) for row in candidate_rows))
        ),
        "20bps_net_response_rows": _maximum_error(
            zip(net_20, (float(row["net_excess_20bps"]) for row in candidate_rows))
        ),
        "twice_floor_net_response_rows": _maximum_error(
            zip(net_twice, (float(row["net_excess_twice_floor"]) for row in candidate_rows))
        ),
        "daily_plain_rows": max(
            abs(
                float(row["mean_plain_gross_excess"])
                - mean(by_day[row["date"]])
            ) for row in daily_saved
        ),
        "bh_q_values": max_q_error,
    }
    summary_comparisons = {
        "mean_raw_signed_return": abs(
            reconstructed["mean_raw_signed_return"]
            - candidate_summary["mean_raw_signed_return"]
        ),
        "mean_event_cost_floor_bps": abs(
            reconstructed["mean_event_cost_floor_bps"]
            - candidate_summary["mean_event_cost_floor_bps"]
        ),
        "mean_raw_net_floor": abs(
            reconstructed["mean_raw_net_floor"]
            - candidate_summary["mean_raw_net_floor"]
        ),
        "mean_plain_gross_excess": abs(
            reconstructed["mean_plain_gross_excess"]
            - candidate_summary["mean_plain_gross_excess"]
        ),
        "mean_excess_after_top_three_removal": abs(
            reconstructed["mean_excess_after_top_three_removal"]
            - candidate_summary["mean_excess_after_top_three_removal"]
        ),
        "plain_bootstrap_lower": abs(
            plain_bootstrap["lower_80"]
            - candidate_summary["plain_excess_80pct_week_bootstrap_lower"]
        ),
        "selection_bootstrap_lower": abs(
            score_bootstrap["lower_80"]
            - candidate_summary["selection_score_80pct_week_bootstrap_lower"]
        ),
        "market_bootstrap_lower": abs(
            market_bootstrap["lower_80"]
            - candidate_summary["market_adjusted_80pct_week_bootstrap_lower"]
        ),
    }
    if max(errors.values()) > TOLERANCE or max(summary_comparisons.values()) > TOLERANCE:
        raise AssertionError("independent arithmetic does not reproduce the persisted result")
    if not ranking_matches or selected != [CANDIDATE_ID]:
        raise AssertionError("independent selection does not reproduce the persisted result")

    sample = reconstruct_raw_sample(candidate_rows, events)
    if not all(row["all_checks_pass"] for row in sample):
        raise AssertionError("one or more raw-bar reconstructions failed")

    candidate_rank = next(
        index for index, row in enumerate(candidates, 1) if row["cell_id"] == CANDIDATE_ID
    )
    candidate_gates = next(
        row["gates"] for row in candidates if row["cell_id"] == CANDIDATE_ID
    )
    market_ranking = market_adjusted_ranking(summaries)
    report = {
        "report_id": "TRADING_EDGE_E1_INDEPENDENT_RECONSTRUCTION_V1",
        "method": {
            "production_event_or_summary_functions_used": False,
            "registration_used_only_for_constants_and_guarded_raw_bar_reads": True,
            "candidate": CANDIDATE_ID,
            "raw_sample_rule": "ten smallest SHA-256 hashes of candidate response IDs",
            "numeric_tolerance": TOLERANCE,
        },
        "source_artifacts": source_checks,
        "row_inventory": inventory,
        "candidate": {
            "reconstructed": reconstructed,
            "summary_absolute_errors": summary_comparisons,
            "ledger_absolute_errors": errors,
            "eligibility_gates": candidate_gates,
            "all_eligibility_gates_pass": all(candidate_gates.values()),
            "neighbor_2p0_plain_excess": summaries[
                "OR15_VOL_2P0__SHORT__H30"
            ]["mean_plain_gross_excess"],
            "volume_off_plain_excess": summaries[
                "OR15_VOL_OFF__SHORT__H30"
            ]["mean_plain_gross_excess"],
            "bh_q_value": candidate_summary["bh_q_value"],
            "same_day_pair_count": candidate_summary["same_day_pair_count"],
            "same_day_pairwise_symbol_correlation": candidate_summary[
                "same_day_pairwise_symbol_correlation"
            ],
        },
        "selection": {
            "primary_cells": len(candidates),
            "eligible_cells": sum(row["eligible"] for row in candidates),
            "selected_cells": selected,
            "candidate_rank": candidate_rank,
            "persisted_ranking_matches": ranking_matches,
        },
        "market_adjusted_ranking": {
            "rows": len(market_ranking),
            "candidate_rank": next(
                row["rank"] for row in market_ranking if row["cell_id"] == CANDIDATE_ID
            ),
        },
        "raw_bar_reconstructions": sample,
        "all_checks_pass": True,
    }
    return report, market_ranking


def owner_report(report: dict) -> str:
    row = report["candidate"]["reconstructed"]
    power = row["plain_power"]
    return f"""# E1 trading-edge result

E1 found one entry rule to carry into the next research stage: `{CANDIDATE_ID}`. It looks for a downward break after the first 15 minutes when opening volume is at least 2.5 times its recent norm. This is an exploratory result. It is not proof of a durable trading edge.

The rule produced {row['event_count']} responses across {row['distinct_dates']} dates and {row['distinct_symbols']} stocks. Its average return above the ordinary-entry comparison was {row['mean_plain_gross_excess'] * 10000:.3f} basis points. Its average raw return after the estimated time-of-day trading cost was {row['mean_raw_net_floor'] * 10000:.3f} basis points. Four of five time blocks were positive. Removing the three strongest stock-days left {row['mean_excess_after_top_three_removal'] * 10000:.3f} basis points.

The uncertainty is still large. The plain weekly lower bound was {row['plain_bootstrap']['lower_80'] * 10000:+.3f} basis points, but the cost-penalized selection lower bound was {row['selection_score_bootstrap']['lower_80'] * 10000:+.3f} basis points. The market-adjusted lower bound was {row['market_adjusted_bootstrap']['lower_80'] * 10000:+.3f} basis points. The adjusted probability value was {report['candidate']['bh_q_value']:.4f}, so the result does not establish statistical significance after accounting for all tested cells.

Power is the main limit. The plain analysis has {row['plain_observed_days']} days and {row['plain_observed_weeks']} weeks. Even a 12-basis-point effect is estimated to need about {power['12']['required_days']} days or {power['12']['required_weeks']} weeks. The market-adjusted check covers only {row['market_adjusted_events']} events across {row['market_adjusted_days']} dates, and there were not enough same-day stock pairs to estimate their shared movement reliably.

The correct next use is controlled E2 research with real quote, fill, short-availability, and cost checks. This result does not authorize live alerts, live trading, order placement, or use of owner capital.
"""


def generate(result_dir: Path) -> dict:
    report, market_ranking = build_reconstruction(result_dir)
    write_csv(
        result_dir / "full-market-adjusted-ranking.csv",
        market_ranking,
        [
            "rank",
            "cell_id",
            "market_adjusted_80pct_week_bootstrap_lower",
            "market_adjusted_count",
            "bh_q_value",
        ],
    )
    write_json(result_dir / "e1-independent-reconstruction.json", report)
    write_text(result_dir / "e1-owner-report.md", owner_report(report))
    return verify_proof_artifacts(result_dir)


def verify_proof_artifacts(result_dir: Path) -> dict:
    checks = {name: verify_sidecar(result_dir / name) for name in PROOF_ARTIFACTS}
    report = json.loads((result_dir / "e1-independent-reconstruction.json").read_text())
    ranking = list(csv.DictReader((result_dir / "full-market-adjusted-ranking.csv").open()))
    sample = report["raw_bar_reconstructions"]
    sample_ids = [row["id"] for row in sample]
    expected_order = sorted(
        sample_ids,
        key=lambda row_id: (hashlib.sha256(row_id.encode()).hexdigest(), row_id),
    )
    return {
        "sidecars_match": all(row["matches_sidecar"] for row in checks.values()),
        "artifact_checks": checks,
        "reconstruction_all_checks_pass": report["all_checks_pass"],
        "sample_count": len(sample),
        "sample_order_is_deterministic": sample_ids == expected_order,
        "sample_checks_pass": all(row["all_checks_pass"] for row in sample),
        "market_ranking_rows": len(ranking),
        "market_ranks_are_sequential": [int(row["rank"]) for row in ranking]
        == list(range(1, len(ranking) + 1)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("generate", "verify"))
    parser.add_argument("--result-dir", type=Path, default=RESULT_DIR)
    args = parser.parse_args()
    result = generate(args.result_dir) if args.command == "generate" else verify_proof_artifacts(args.result_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if all(value for key, value in result.items() if isinstance(value, bool)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
