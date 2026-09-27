#!/usr/bin/env python3
"""Run the registered E2 refinement for the sole E1 survivor.

The runner is offline and development-only.  It reuses the governed E1 bars,
events, masks, and quote-cost report.  Each variant/block result is an atomic
checkpoint, so a stopped run resumes without recalculating completed blocks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import NormalDist

import numpy as np


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[1]
E1_DIR = WORKSPACE / ".omc/research/trading-edge-discovery"
DEFAULT_OUTPUT = WORKSPACE / ".omc/research/trading-edge-e2"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import trading_edge_full as F  # noqa: E402
import trading_edge_registration as R  # noqa: E402


STUDY_ID = "TRADING_EDGE_E2_V1"
SURVIVOR = "OR15_VOL_2P5__SHORT__H30"
SETTING = "OR15_VOL_2P5"
SEED = 20260927
BOOTSTRAP_DRAWS = 2_000
BLOCKS = tuple(item[0] for item in R.BLOCKS)
FOLDS = (
    ("F1", ("B1",), "B2"),
    ("F2", ("B1", "B2"), "B3"),
    ("F3", ("B1", "B2", "B3"), "B4"),
    ("F4", ("B1", "B2", "B3", "B4"), "B5"),
)
EXIT_RULES = ("FIXED_H15", "FIXED_H30", "OR1_BRACKET_H30")
POPULATIONS = ("UNFILTERED", "ABS_GAP_LT2", "EARLY_1H")
VARIANTS = tuple(
    {
        "id": f"{exit_rule}__{population}",
        "exit_rule": exit_rule,
        "population": population,
        "previously_exposed": exit_rule == "FIXED_H15",
    }
    for exit_rule in EXIT_RULES
    for population in POPULATIONS
)


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_bytes(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with tmp.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    digest = hashlib.sha256(payload).hexdigest()
    _write_sidecar(path, digest)
    return digest


def _write_sidecar(path: Path, digest: str) -> None:
    sidecar = path.with_name(path.name + ".sha256")
    side_tmp = sidecar.with_name(f".{sidecar.name}.tmp.{os.getpid()}")
    side_tmp.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    os.replace(side_tmp, sidecar)


def write_json(path: Path, value: object) -> str:
    return _atomic_bytes(path, (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())


def write_jsonl(path: Path, rows: list[dict]) -> str:
    return _atomic_bytes(path, b"".join(_canonical(row) for row in sorted(rows, key=lambda r: r["id"])))


def _read_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def population_allows(population: str, entry_col: int, gap_bps: float | None) -> bool:
    if population == "UNFILTERED":
        return True
    if population == "EARLY_1H":
        return entry_col < 60  # strictly before 07:30 Pacific
    if population == "ABS_GAP_LT2":
        return gap_bps is not None and math.isfinite(gap_bps) and abs(gap_bps) < 200.0
    raise ValueError(f"unknown population: {population}")


def bracket_short(
    entry_price: float,
    opens: list[float],
    highs: list[float],
    lows: list[float],
    terminal_close: float,
    stop: float,
    target: float,
    *,
    same_minute: str = "stop_first",
) -> dict:
    """Resolve the registered short bracket without favorable interpolation."""
    if same_minute not in {"stop_first", "target_first"}:
        raise ValueError("same_minute must be stop_first or target_first")
    for index, (opened, high, low) in enumerate(zip(opens, highs, lows)):
        if not all(math.isfinite(x) for x in (opened, high, low)):
            return {"status": "unresolved", "reason": "MISSING_PATH"}
        if opened >= stop:
            return {"status": "resolved", "exit_price": opened, "exit_index": index, "reason": "GAP_STOP"}
        if opened <= target:
            return {"status": "resolved", "exit_price": target, "exit_index": index, "reason": "GAP_TARGET_CAPPED"}
        hit_stop, hit_target = high >= stop, low <= target
        if hit_stop and hit_target:
            price = stop if same_minute == "stop_first" else target
            return {"status": "resolved", "exit_price": price, "exit_index": index,
                    "reason": "SAME_MINUTE_STOP_FIRST" if same_minute == "stop_first" else "SAME_MINUTE_TARGET_FIRST"}
        if hit_stop:
            return {"status": "resolved", "exit_price": stop, "exit_index": index, "reason": "STOP"}
        if hit_target:
            return {"status": "resolved", "exit_price": target, "exit_index": index, "reason": "TARGET"}
    if not math.isfinite(terminal_close):
        return {"status": "unresolved", "reason": "MISSING_TERMINAL_CLOSE"}
    return {"status": "resolved", "exit_price": terminal_close, "exit_index": len(opens) - 1, "reason": "H30"}


def _quote_buckets(report: dict) -> list[dict]:
    rows = report["results"]["thirty_minute_buckets"]
    result = []
    for row in rows:
        hour, minute = map(int, row["bucket_start_pacific"].split(":"))
        result.append({**row, "start": (hour - 6) * 60 + minute - 30})
    return result


def _spread_at(entry_col: int, buckets: list[dict], field: str) -> float | None:
    starts = [row["start"] for row in buckets]
    eligible = [i for i, start in enumerate(starts) if start <= entry_col]
    if not eligible:
        return None
    row = buckets[max(eligible)]
    return float(row[field])


def round_trip_cost_bps(entry_col: int, exit_col: int, buckets: list[dict], field: str) -> float | None:
    entry = _spread_at(entry_col, buckets, field)
    exit_ = _spread_at(exit_col, buckets, field)
    if entry is None or exit_ is None:
        return None
    floor = 8.0 if entry_col < 60 or exit_col < 60 else 5.0
    # Crossing twice pays half the displayed spread at each leg.
    return max(floor, (entry + exit_) / 2.0)


def _week(day: str) -> str:
    year, week, _ = date.fromisoformat(day).isocalendar()
    return f"{year:04d}-W{week:02d}"


def _pacific_clock(column: int) -> str:
    total = 6 * 60 + 30 + column
    hour, minute = divmod(total, 60)
    return f"{hour:02d}:{minute:02d} Pacific"


def _mean_or_none(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def _lower_bound(rows: list[dict], field: str, seed_key: str, draws: int = BOOTSTRAP_DRAWS) -> float | None:
    by_week: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_week[row["week"]].append(float(row[field]))
    weeks = sorted(by_week)
    if not weeks:
        return None
    week_means = np.asarray([statistics.mean(by_week[w]) for w in weeks], dtype=float)
    seed = SEED + int(hashlib.sha256(seed_key.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    samples = rng.choice(week_means, size=(draws, len(weeks)), replace=True).mean(axis=1)
    return float(np.quantile(samples, 0.20))


def _summarize(rows: list[dict], variant_id: str, block: str) -> dict:
    values = [float(row["net_excess_base"]) for row in rows]
    primary = [float(row["net_excess_base_target_first"]) for row in rows]
    return {
        "variant_id": variant_id,
        "block": block,
        "event_days": len({row["date"] for row in rows}),
        "trades": sum(int(row["event_count"]) for row in rows),
        "weeks": len({row["week"] for row in rows}),
        "mean_net_excess_base": _mean_or_none(values),
        "mean_net_excess_base_target_first": _mean_or_none(primary),
        "mean_raw_event_net_base": _mean_or_none([float(row["raw_event_net_base"]) for row in rows]),
        "mean_raw_event_gross": _mean_or_none([float(row["raw_event_gross"]) for row in rows]),
        "mean_net_excess_p90": _mean_or_none([float(row["net_excess_p90"]) for row in rows]),
        "mean_net_excess_twice_floor": _mean_or_none([float(row["net_excess_twice_floor"]) for row in rows]),
        "mean_net_excess_20bps": _mean_or_none([float(row["net_excess_20bps"]) for row in rows]),
        "week_bootstrap_80pct_lower": _lower_bound(rows, "net_excess_base", f"{variant_id}|{block}"),
    }


def _streak(values: list[float], positive: bool) -> int:
    best = current = 0
    for value in values:
        matches = value > 0 if positive else value < 0
        current = current + 1 if matches else 0
        best = max(best, current)
    return best


def _performance(rows: list[dict], all_dates: list[str]) -> dict:
    ordered = sorted(rows, key=lambda row: row["date"])
    raw = [float(row["raw_event_net_base"]) for row in ordered]
    equity = peak = 0.0
    max_drawdown = 0.0
    underwater = recovery = 0
    for value in raw:
        equity += value
        if equity >= peak:
            peak = equity
            underwater = 0
        else:
            underwater += 1
            recovery = max(recovery, underwater)
            max_drawdown = min(max_drawdown, equity - peak)
    positive_sum = sum(value for value in raw if value > 0)
    negative_sum = -sum(value for value in raw if value < 0)
    active_weeks = {row["week"] for row in ordered}
    all_weeks = {_week(day) for day in all_dates}
    positive_dates = sorted(
        ((float(row["raw_event_net_base"]), row["date"]) for row in ordered if row["raw_event_net_base"] > 0),
        reverse=True,
    )
    total_positive = sum(value for value, _ in positive_dates)
    return {
        "common_position_dollars": 10_000,
        "mean_raw_gross_percent": 100 * (_mean_or_none([float(row["raw_event_gross"]) for row in ordered]) or 0.0),
        "mean_raw_net_percent": 100 * (_mean_or_none(raw) or 0.0),
        "mean_raw_net_dollars_per_10000": 10_000 * (_mean_or_none(raw) or 0.0),
        "max_additive_drawdown_percent": 100 * max_drawdown,
        "longest_recovery_trade_days": recovery,
        "longest_winning_trade_day_streak": _streak(raw, True),
        "longest_losing_trade_day_streak": _streak(raw, False),
        "profit_factor_on_trade_day_means": (positive_sum / negative_sum if negative_sum else None),
        "completed_trades": sum(int(row["event_count"]) for row in ordered),
        "turnover_legs": 2 * sum(int(row["event_count"]) for row in ordered),
        "active_weeks": len(active_weeks),
        "inactive_weeks": len(all_weeks - active_weeks),
        "top_three_positive_date_share": (
            sum(value for value, _ in positive_dates[:3]) / total_positive if total_positive else None
        ),
        "top_three_positive_dates": [day for _, day in positive_dates[:3]],
        "capacity_status": "UNRESOLVED_NO_DEPTH_OR_FILL_EVIDENCE",
    }


def _checkpoint_context() -> str:
    inputs = {
        "runner": sha256_file(Path(__file__)),
        "trading_edge_full": sha256_file(Path(F.__file__)),
        "trading_edge_registration": sha256_file(Path(R.__file__)),
        "e1_events": sha256_file(E1_DIR / "full-events.jsonl"),
        "e1_responses": sha256_file(E1_DIR / "full-responses.jsonl"),
        "e1_masks": sha256_file(E1_DIR / "full-pre-return-audit.json"),
        "quote_cost_report": sha256_file(E1_DIR / "quote-cost-report.json"),
        "source": sha256_file(R.PRIMARY_SOURCE),
    }
    return hashlib.sha256(_canonical(inputs)).hexdigest()


def load_checkpoint(path: Path, context: str, variant_id: str, block: str) -> dict | None:
    try:
        envelope = json.loads(path.read_text())
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(envelope, dict) or set(envelope) != {"checkpoint", "checkpoint_sha256"}:
        return None
    record = envelope.get("checkpoint")
    if not isinstance(record, dict):
        return None
    expected_record_digest = hashlib.sha256(_canonical(record)).hexdigest()
    if envelope.get("checkpoint_sha256") != expected_record_digest:
        return None
    if (record.get("version") != 1 or record.get("context_sha256") != context
            or record.get("variant_id") != variant_id or record.get("block") != block
            or not isinstance(record.get("summary"), dict)
            or not isinstance(record.get("daily_rows"), list)
            or not isinstance(record.get("audit_rows"), list)
            or not isinstance(record.get("unresolved_rows"), list)):
        return None
    # The JSON file is the single atomic checkpoint.  A crash after its rename
    # but before the derived sidecar write is recoverable: validate the record,
    # then repair the sidecar before accepting it.
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    sidecar = path.with_name(path.name + ".sha256")
    expected = f"{digest}  {path.name}\n"
    try:
        sidecar_ok = sidecar.read_text(encoding="utf-8") == expected
    except (FileNotFoundError, UnicodeDecodeError):
        sidecar_ok = False
    if not sidecar_ok:
        _write_sidecar(path, digest)
    return record


def write_checkpoint(path: Path, record: dict) -> None:
    envelope = {
        "checkpoint": record,
        "checkpoint_sha256": hashlib.sha256(_canonical(record)).hexdigest(),
    }
    _atomic_bytes(path, _canonical(envelope))


def checkpointed_block(path: Path, context: str, variant_id: str, block: str, compute) -> tuple[dict, bool]:
    saved = load_checkpoint(path, context, variant_id, block)
    if saved is not None:
        return saved, True
    result = compute()
    block_rows = result["daily_rows"]
    record = {
        "version": 1, "context_sha256": context, "variant_id": variant_id, "block": block,
        "summary": _summarize(block_rows, variant_id, block),
        "daily_rows": block_rows,
        "audit_rows": result["audit_rows"],
        "unresolved_rows": result["unresolved_rows"],
    }
    write_checkpoint(path, record)
    return record, False


def _load_e1_events() -> tuple[list[dict], tuple[str, ...]]:
    events = {}
    for row in _read_jsonl(E1_DIR / "full-events.jsonl"):
        if row.get("setting_id") == SETTING and row.get("direction") == "short":
            events[row["id"]] = row
    h30 = []
    for row in _read_jsonl(E1_DIR / "full-responses.jsonl"):
        if (row.get("cell_id") == SURVIVOR and row.get("reference") == "next_minute"):
            merged = dict(row)
            merged.update({f"event_{k}": v for k, v in events[row["event_id"]].items()})
            h30.append(merged)
    symbols = tuple(sorted({row["symbol"] for row in h30}))
    return sorted(h30, key=lambda r: r["id"]), symbols


def _path_result(panel, si: int, di: int, entry: int, exit_col: int, h15_exit_col: int,
                 exit_rule: str, same_minute: str) -> dict:
    entry_price = float(panel.o[si, di, entry])
    if not math.isfinite(entry_price):
        return {"status": "unresolved", "reason": "MISSING_ENTRY"}
    if exit_rule == "FIXED_H15":
        if h15_exit_col < entry or h15_exit_col >= int(panel.lengths[di]) or not math.isfinite(float(panel.c[si, di, h15_exit_col])):
            return {"status": "unresolved", "reason": "MISSING_H15"}
        return {"status": "resolved", "exit_price": float(panel.c[si, di, h15_exit_col]),
                "exit_index": h15_exit_col - entry, "reason": "H15"}
    if exit_rule == "FIXED_H30":
        if not math.isfinite(float(panel.c[si, di, exit_col])):
            return {"status": "unresolved", "reason": "MISSING_H30"}
        return {"status": "resolved", "exit_price": float(panel.c[si, di, exit_col]), "exit_index": exit_col - entry, "reason": "H30"}
    opening_high = float(np.max(panel.h[si, di, :15]))
    opening_low = float(np.min(panel.l[si, di, :15]))
    if not all(math.isfinite(x) for x in (opening_high, opening_low)) or opening_high <= opening_low:
        return {"status": "unresolved", "reason": "OPENING_RANGE_UNAVAILABLE"}
    path = slice(entry, exit_col + 1)
    result = bracket_short(
        entry_price,
        panel.o[si, di, path].astype(float).tolist(),
        panel.h[si, di, path].astype(float).tolist(),
        panel.l[si, di, path].astype(float).tolist(),
        float(panel.c[si, di, exit_col]),
        opening_high,
        opening_low - (opening_high - opening_low),
        same_minute=same_minute,
    )
    return result


def _outcome(panel, si: int, di: int, entry: int, exit_col: int, h15_exit_col: int, exit_rule: str,
             buckets: list[dict], same_minute: str = "stop_first") -> dict:
    result = _path_result(panel, si, di, entry, exit_col, h15_exit_col, exit_rule, same_minute)
    if result["status"] != "resolved":
        return result
    exit_actual = entry + int(result["exit_index"])
    entry_price = float(panel.o[si, di, entry])
    gross = 1.0 - float(result["exit_price"]) / entry_price
    base = round_trip_cost_bps(entry, exit_actual, buckets, "median_displayed_spread_bps")
    p90 = round_trip_cost_bps(entry, exit_actual, buckets, "p90_displayed_spread_bps")
    if base is None or p90 is None:
        return {"status": "unresolved", "reason": "QUOTE_COST_BUCKET_UNAVAILABLE"}
    floor = 8.0 if entry < 60 or exit_actual < 60 else 5.0
    return {
        "status": "resolved",
        "gross": gross,
        "exit_col": exit_actual,
        "exit_reason": result["reason"],
        "net_base": gross - base / 10_000.0,
        "net_p90": gross - p90 / 10_000.0,
        "net_twice_floor": gross - 2 * floor / 10_000.0,
        "net_20bps": gross - 20 / 10_000.0,
        "cost_base_bps": base,
        "cost_p90_bps": p90,
    }


def _common_h30_coverage(panel, si: int, di: int, entry: int, exit_col: int) -> bool:
    """Require the same complete comparison window for every exit variant."""
    if exit_col > int(panel.lengths[di]) - 6:
        return False
    return bool(
        np.isfinite(panel.o[si, di, entry])
        and np.isfinite(panel.c[si, di, exit_col])
        and np.isfinite(panel.h[si, di, entry : exit_col + 1]).all()
        and np.isfinite(panel.l[si, di, entry : exit_col + 1]).all()
    )


def _build_daily_rows(panel, events: list[dict], audit_gaps: dict, governed: dict,
                      variant: dict, buckets: list[dict], *, blocks: set[str] | None = None,
                      delay_minutes: int = 0) -> list[dict]:
    symbol_index = {value: i for i, value in enumerate(panel.symbols)}
    date_index = {value: i for i, value in enumerate(panel.dates)}
    # Common H30/OR15 coverage keeps all nine variants comparable.
    event_outcomes = []
    unresolved_rows = []
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for event in events:
        if blocks is not None and event["block"] not in blocks:
            continue
        si, di = symbol_index[event["symbol"]], date_index[event["date"]]
        base_entry, exit_col = int(event["entry_col"]), int(event["exit_col"])
        entry = base_entry + delay_minutes
        h15_exit_col = base_entry + 14
        gap = event.get("audit_overnight_gap_bps")
        if not population_allows(variant["population"], entry, gap):
            continue
        if not _common_h30_coverage(panel, si, di, entry, exit_col):
            unresolved_rows.append({
                "id": f"{variant['id']}|D{delay_minutes}|{event['id']}|COMMON_H30",
                "variant_id": variant["id"], "delay_minutes": delay_minutes,
                "event_id": event["id"], "symbol": event["symbol"], "date": event["date"],
                "block": event["block"], "reason": "COMMON_H30_COVERAGE_UNAVAILABLE",
            })
            continue
        if not np.isfinite(panel.h[si, di, :15]).all() or not np.isfinite(panel.l[si, di, :15]).all():
            continue
        primary = _outcome(panel, si, di, entry, exit_col, h15_exit_col, variant["exit_rule"], buckets)
        sensitivity = _outcome(
            panel, si, di, entry, exit_col, h15_exit_col, variant["exit_rule"], buckets, "target_first"
        )
        if primary["status"] != "resolved" or sensitivity["status"] != "resolved":
            unresolved_rows.append({
                "id": f"{variant['id']}|D{delay_minutes}|{event['id']}|OUTCOME",
                "variant_id": variant["id"], "delay_minutes": delay_minutes,
                "event_id": event["id"], "symbol": event["symbol"], "date": event["date"],
                "block": event["block"], "reason": primary.get("reason"),
                "target_first_reason": sensitivity.get("reason"),
            })
            continue
        key = (event["symbol"], event["block"], event["event_session_type"], entry // 15)
        item = {**event, "gap_bps": gap, "primary": primary, "sensitivity": sensitivity, "group": key}
        event_outcomes.append(item)
        groups[key].append(item)

    controls: dict[tuple, dict[str, float]] = {}
    for key in sorted(groups):
        symbol, block, session_type, bin_index = key
        si = symbol_index[symbol]
        daily: dict[str, list[dict]] = defaultdict(list)
        for di, day in enumerate(panel.dates):
            if (F._block(day) != block or (blocks is not None and block not in blocks)
                    or panel.session_type(di) != session_type or (symbol, day) in governed):
                continue
            gap_row = audit_gaps.get((symbol, day))
            gap = gap_row.get("overnight_gap_bps") if gap_row and not gap_row.get("reference_reset") else None
            start = bin_index * 15
            for entry in range(start, min(start + 15, int(panel.lengths[di]))):
                if not population_allows(variant["population"], entry, gap):
                    continue
                exit_col = entry + 29 - delay_minutes
                h15_exit_col = entry + 14 - delay_minutes
                if not _common_h30_coverage(panel, si, di, entry, exit_col):
                    continue
                if not np.isfinite(panel.h[si, di, :15]).all() or not np.isfinite(panel.l[si, di, :15]).all():
                    continue
                primary = _outcome(panel, si, di, entry, exit_col, h15_exit_col, variant["exit_rule"], buckets)
                sensitivity = _outcome(
                    panel, si, di, entry, exit_col, h15_exit_col,
                    variant["exit_rule"], buckets, "target_first"
                )
                if primary["status"] == "resolved" and sensitivity["status"] == "resolved":
                    daily[day].append({"primary": primary, "sensitivity": sensitivity})
        if not daily:
            continue
        fields = ("gross", "net_base", "net_p90", "net_twice_floor", "net_20bps")
        values = {}
        for field in fields:
            values[field] = statistics.mean(
                statistics.mean(row["primary"][field] for row in rows) for rows in daily.values()
            )
        values["net_base_target_first"] = statistics.mean(
            statistics.mean(row["sensitivity"]["net_base"] for row in rows) for rows in daily.values()
        )
        values["cost_base_bps"] = statistics.mean(
            statistics.mean(row["primary"]["cost_base_bps"] for row in rows) for rows in daily.values()
        )
        values["cost_p90_bps"] = statistics.mean(
            statistics.mean(row["primary"]["cost_p90_bps"] for row in rows) for rows in daily.values()
        )
        values["control_dates"] = len(daily)
        values["control_opportunities"] = sum(len(rows) for rows in daily.values())
        controls[key] = values

    by_date: dict[str, list[dict]] = defaultdict(list)
    audit_rows = []
    for event in event_outcomes:
        control = controls.get(event["group"])
        if control is None:
            unresolved_rows.append({
                "id": f"{variant['id']}|D{delay_minutes}|{event['event_id']}|CONTROL",
                "variant_id": variant["id"], "delay_minutes": delay_minutes,
                "event_id": event["event_id"], "symbol": event["symbol"], "date": event["date"],
                "block": event["block"], "reason": "MATCHED_CONTROL_UNAVAILABLE",
                "control_group": list(event["group"]),
            })
            continue
        primary, sensitivity = event["primary"], event["sensitivity"]
        audit_rows.append({
            "id": f"{variant['id']}|D{delay_minutes}|{event['event_id']}",
            "variant_id": variant["id"], "delay_minutes": delay_minutes,
            "event_id": event["event_id"], "symbol": event["symbol"], "date": event["date"],
            "block": event["block"], "entry_col": int(event["entry_col"]) + delay_minutes,
            "entry_time_pacific": _pacific_clock(int(event["entry_col"]) + delay_minutes),
            "exit_col": primary["exit_col"], "exit_time_pacific": _pacific_clock(primary["exit_col"]),
            "exit_reason": primary["exit_reason"],
            "target_first_exit_col": sensitivity["exit_col"],
            "target_first_exit_reason": sensitivity["exit_reason"],
            "gross_return": primary["gross"], "cost_base_bps": primary["cost_base_bps"],
            "cost_p90_bps": primary["cost_p90_bps"], "raw_net_base": primary["net_base"],
            "matched_control_group": list(event["group"]),
            "matched_control_dates": control["control_dates"],
            "matched_control_opportunities": control["control_opportunities"],
            "matched_control_net_base": control["net_base"],
            "matched_control_net_p90": control["net_p90"],
            "matched_control_cost_base_bps": control["cost_base_bps"],
            "matched_control_cost_p90_bps": control["cost_p90_bps"],
            "net_excess_base": primary["net_base"] - control["net_base"],
        })
        by_date[event["date"]].append({
            "raw_event_gross": primary["gross"],
            "raw_event_net_base": primary["net_base"],
            "net_excess_base": primary["net_base"] - control["net_base"],
            "net_excess_base_target_first": sensitivity["net_base"] - control["net_base_target_first"],
            "net_excess_p90": primary["net_p90"] - control["net_p90"],
            "net_excess_twice_floor": primary["net_twice_floor"] - control["net_twice_floor"],
            "net_excess_20bps": primary["net_20bps"] - control["net_20bps"],
        })
    rows = []
    for day, members in sorted(by_date.items()):
        block = F._block(day)
        row = {
            "id": f"{variant['id']}|{day}", "variant_id": variant["id"],
            "date": day, "week": _week(day), "block": block,
            "event_count": len(members),
        }
        for field in members[0]:
            row[field] = statistics.mean(item[field] for item in members)
        rows.append(row)
    return {"daily_rows": rows, "audit_rows": audit_rows, "unresolved_rows": unresolved_rows}


def _power(rows: list[dict], rolling_selected_mean: float | None) -> dict:
    by_week: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_week[row["week"]].append(float(row["net_excess_base"]))
    weekly = [statistics.mean(values) for values in by_week.values()]
    sigma = statistics.stdev(weekly) if len(weekly) >= 2 else None
    target_bps = max(3.0, 0.5 * max(0.0, (rolling_selected_mean or 0.0) * 10_000.0))
    finalist_count = 1
    z_alpha = NormalDist().inv_cdf(1.0 - 0.05 / finalist_count)
    z_power = NormalDist().inv_cdf(0.80)
    sensitivity = []
    for bps in (3, 5, 8, 12):
        required = None if sigma is None else math.ceil(((z_alpha + z_power) * sigma / (bps / 10_000.0)) ** 2)
        sensitivity.append({"effect_bps": bps, "required_weeks": required})
    target_required = None if sigma is None else math.ceil(((z_alpha + z_power) * sigma / (target_bps / 10_000.0)) ** 2)
    development_weeks = len(weekly)
    development_dates = len({row["date"] for row in rows})
    development_trades = sum(int(row["event_count"]) for row in rows)
    dates_per_week = development_dates / development_weeks if development_weeks else 0.0
    trades_per_week = development_trades / development_weeks if development_weeks else 0.0
    weeks_for_dates = math.ceil(60 / dates_per_week) if dates_per_week else None
    weeks_for_trades = math.ceil(200 / trades_per_week) if trades_per_week else None
    requirements = [value for value in (target_required, weeks_for_dates, weeks_for_trades) if value is not None]
    confirmation_weeks = max(requirements) if len(requirements) == 3 else None
    feasible = confirmation_weeks is not None and confirmation_weeks <= 39
    return {
        "one_sided_alpha": 0.05, "power": 0.80, "finalist_count": finalist_count,
        "target_bps": target_bps, "target_source": "50% of rolling-selected development excess, floored at 3 bps",
        "rolling_selected_mean_net_excess": rolling_selected_mean,
        "weekly_standard_deviation": sigma,
        "development_weeks": development_weeks, "development_event_days": development_dates,
        "development_trades": development_trades,
        "required_statistical_weeks_at_target": target_required,
        "required_weeks_for_60_confirmation_dates": weeks_for_dates,
        "required_weeks_for_200_confirmation_trades": weeks_for_trades,
        "required_confirmation_weeks": confirmation_weeks,
        "nine_month_confirmation_cap_weeks": 39, "feasible_within_cap": feasible,
        "operational_floor": {"trades": 200, "event_days": 60},
        "sensitivity": sensitivity,
    }


def run(output_dir: Path = DEFAULT_OUTPUT) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    context = _checkpoint_context()
    quote_report = json.loads((E1_DIR / "quote-cost-report.json").read_text())
    buckets = _quote_buckets(quote_report)
    events, symbols = _load_e1_events()
    dates, lengths, closes = F._calendar(R.DEVELOPMENT_FIRST, R.DEVELOPMENT_LAST)

    registration = {
        "study_id": STUDY_ID, "source_e1_survivor": SURVIVOR,
        "variants": list(VARIANTS), "variant_count": len(VARIANTS),
        "rolling_folds": [{"id": i, "train": list(t), "test": v} for i, t, v in FOLDS],
        "selection": "highest deterministic 80% whole-week bootstrap lower bound of base net excess; tie by variant id",
        "common_coverage": "all variants require a valid OR15 and complete H30 path",
        "filters_are_never_combined": True,
        "purge": "intraday outcomes cannot cross a development-block boundary",
        "embargo_minutes": 30,
        "costs": {
            "base": "max(5/8 bps floor, half entry median spread plus half exit median spread)",
            "sensitivities": ["p90 displayed spread", "twice floor", "20 bps"],
            "commission_usd": 0.0,
            "evidence_limit": "displayed spreads cover CRM/NOW/ORCL only and do not prove fills for the 35-symbol survivor set",
        },
        "portfolio_contract": {
            "standalone_only": True,
            "concurrency": "reported as separate trade observations; no portfolio netting",
            "sizing": "one common-sized position; $10,000 illustration in the report",
            "liquidity_and_capacity": "unresolved without depth and fill evidence",
            "tie_break": "stable variant id",
        },
        "short_borrow_rule": "missing prospective borrow and stock-loan cost evidence makes execution feasibility unresolved",
        "network_used": False, "spend_usd": 0.0, "protected_epoch_read": False,
        "context_sha256": context,
        "inputs": {name: sha256_file(E1_DIR / name) for name in (
            "full-events.jsonl", "full-responses.jsonl", "full-pre-return-audit.json", "quote-cost-report.json")},
        "runner_sha256": sha256_file(Path(__file__)),
    }
    write_json(output_dir / "run-registration.json", registration)
    write_json(output_dir / "variants.json", {"study_id": STUDY_ID, "variants": list(VARIANTS)})

    panel = F.DensePanel.load(symbols, dates, lengths, closes)
    _audit, governed, audit_gaps = F._audit_panel(panel)
    F._install_governed_masks(panel, _audit, governed)
    all_daily = []
    all_audit = []
    all_unresolved = []
    checkpoint_dir = output_dir / "checkpoints"
    for variant in VARIANTS:
        for block in BLOCKS:
            checkpoint_path = checkpoint_dir / f"{variant['id']}__{block}.json"
            # Calculate and commit one block at a time.  A restart accepts all
            # earlier blocks and resumes at the first missing/invalid one.
            block_record, _reused = checkpointed_block(
                checkpoint_path, context, variant["id"], block,
                lambda block=block: _build_daily_rows(
                    panel, events, audit_gaps, governed, variant, buckets, blocks={block}
                ),
            )
            all_daily.extend(block_record["daily_rows"])
            all_audit.extend(block_record["audit_rows"])
            all_unresolved.extend(block_record["unresolved_rows"])

    write_jsonl(output_dir / "daily-results.jsonl", all_daily)
    block_summaries = []
    for variant in VARIANTS:
        for block in BLOCKS:
            rows = [row for row in all_daily if row["variant_id"] == variant["id"] and row["block"] == block]
            block_summaries.append({"id": f"{variant['id']}|{block}", **_summarize(rows, variant["id"], block)})
    write_jsonl(output_dir / "block-results.jsonl", block_summaries)

    rolling = []
    selected_ids = []
    for fold_id, train_blocks, test_block in FOLDS:
        candidates = []
        for variant in VARIANTS:
            train = [row for row in all_daily if row["variant_id"] == variant["id"] and row["block"] in train_blocks]
            lower = _lower_bound(train, "net_excess_base", f"{fold_id}|{variant['id']}")
            candidates.append((lower if lower is not None else float("-inf"), variant["id"], train))
        lower, chosen, train = sorted(candidates, key=lambda item: (-item[0], item[1]))[0]
        test = [row for row in all_daily if row["variant_id"] == chosen and row["block"] == test_block]
        selected_ids.append(chosen)
        rolling.append({
            "id": fold_id, "train_blocks": list(train_blocks), "test_block": test_block,
            "selected_variant": chosen, "train_80pct_lower": lower,
            "train_mean_net_excess_base": _mean_or_none([row["net_excess_base"] for row in train]),
            "test_mean_net_excess_base": _mean_or_none([row["net_excess_base"] for row in test]),
            "test_raw_event_net_base": _mean_or_none([row["raw_event_net_base"] for row in test]),
            "test_event_days": len(test), "test_trades": sum(row["event_count"] for row in test),
            "purged_boundary_outcomes": 0, "embargoed_outcomes": 0,
        })
    write_json(output_dir / "rolling-results.json", {"folds": rolling})

    rolling_selected_rows = []
    for fold in rolling:
        rolling_selected_rows.extend([
            row for row in all_daily
            if row["variant_id"] == fold["selected_variant"] and row["block"] == fold["test_block"]
        ])
    rolling_selected_mean = _mean_or_none([
        row["net_excess_base"] for row in rolling_selected_rows
    ])

    # After the four rolling checks, freeze one unchanged rule using all five
    # development blocks and the same registered ranking statistic.
    static_candidates = []
    for variant in VARIANTS:
        rows = [row for row in all_daily if row["variant_id"] == variant["id"]]
        lower = _lower_bound(rows, "net_excess_base", f"STATIC|{variant['id']}")
        static_candidates.append((lower if lower is not None else float("-inf"), variant["id"]))
    static_lower, static_variant = sorted(static_candidates, key=lambda item: (-item[0], item[1]))[0]
    static_rows = [row for row in all_daily if row["variant_id"] == static_variant]
    static_mean = _mean_or_none([row["net_excess_base"] for row in static_rows])
    power = _power(static_rows, rolling_selected_mean)
    performance = _performance(static_rows, dates[20:])
    static_definition = next(row for row in VARIANTS if row["id"] == static_variant)
    delay_result = _build_daily_rows(
        panel, events, audit_gaps, governed, static_definition, buckets, delay_minutes=1
    )
    delay_rows = delay_result["daily_rows"]
    write_jsonl(output_dir / "delay-stress.jsonl", delay_rows)
    all_audit.extend(delay_result["audit_rows"])
    all_unresolved.extend(delay_result["unresolved_rows"])
    write_jsonl(output_dir / "event-audit.jsonl", all_audit)
    write_jsonl(output_dir / "unresolved.jsonl", all_unresolved)
    delay_mean = _mean_or_none([row["net_excess_base"] for row in delay_rows])
    delay_stress = {
        "entry_delay_minutes": 1,
        "variant_id": static_variant,
        "event_days": len(delay_rows),
        "trades": sum(int(row["event_count"]) for row in delay_rows),
        "mean_net_excess_base": delay_mean,
        "change_from_reference": (
            delay_mean - static_mean if delay_mean is not None and static_mean is not None else None
        ),
        "exit_clock_rule": "nominal H15/H30 exit clock is unchanged; the entry moves one minute later",
    }
    execution_status = "EXECUTION_FEASIBILITY_UNRESOLVED"
    decision = "PARK"
    reasons = ["prospective short borrow availability and stock-loan costs are missing"]
    if not power["feasible_within_cap"]:
        reasons.append("the corrected 80% power target does not fit the nine-month cap or operational floor")
    ledger = {
        "study_id": STUDY_ID, "registered_variants": 9, "attempted_variants": 9,
        "rolling_selections": selected_ids, "static_variant": static_variant,
        "manual_variants_added": 0, "filters_combined": 0,
        "previously_exposed_trials": [v["id"] for v in VARIANTS if v["previously_exposed"]],
        "short_execution_status": execution_status, "decision": decision, "reasons": reasons,
    }
    write_json(output_dir / "trial-ledger.json", ledger)
    write_json(output_dir / "power.json", power)
    summary = {
        "study_id": STUDY_ID, "e1_survivor": SURVIVOR, "variant_count": 9,
        "checkpoint_count": 45, "rolling_fold_count": 4,
        "static_variant": static_variant, "static_mean_net_excess_base": static_mean,
        "static_80pct_week_bootstrap_lower": static_lower,
        "execution_status": execution_status, "decision": decision, "reasons": reasons,
        "power": power, "performance": performance,
        "one_extra_minute_delay_stress": delay_stress,
        "event_audit_rows": len(all_audit), "unresolved_rows": len(all_unresolved),
        "block_regimes": {
            block: _mean_or_none([
                row["net_excess_base"] for row in static_rows if row["block"] == block
            ]) for block in BLOCKS
        },
        "network_used": False, "spend_usd": 0.0,
        "limitations": registration["costs"]["evidence_limit"],
    }
    write_json(output_dir / "summary.json", summary)
    report = (
        f"E2 tested all 9 registered variants for {SURVIVOR}.\n\n"
        f"The fixed rule selected from rolling development was {static_variant}. "
        f"Its date-first base net excess was {((static_mean or 0) * 10000):.2f} basis points per trade-day.\n\n"
        f"Decision: {decision}. Short-sale borrow availability and borrowing cost were not available, "
        "so historical short returns cannot be called executable. "
        f"Power within the nine-month confirmation cap: {'feasible' if power['feasible_within_cap'] else 'not feasible'}. "
        f"One-minute-later entry excess: {((delay_mean or 0) * 10000):.2f} basis points.\n"
    )
    _atomic_bytes(output_dir / "owner-report.txt", report.encode())
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir), sort_keys=True))


if __name__ == "__main__":
    main()
