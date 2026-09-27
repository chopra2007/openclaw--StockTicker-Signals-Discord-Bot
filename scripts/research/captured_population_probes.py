#!/usr/bin/env python3
"""Run two read-only checks on captured, non-panel records.

These checks describe associations in the stored population.  They do not
estimate a causal trading edge and they do not alter the research panel.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median, stdev
from zoneinfo import ZoneInfo


SCORE_CUTOFF = 80.0
TIMELY_MIN_SECONDS = 0.0
TIMELY_MAX_SECONDS = 60.0
BOOTSTRAP_SEED = 20260927
BOOTSTRAP_RESAMPLES = 5_000
SQLITE_DEADLINE_SECONDS = 30.0
SQLITE_PROGRESS_OPS = 1_000
ID_QUERY_CHUNK = 500
PACIFIC = ZoneInfo("America/Los_Angeles")

DECISION_ELIGIBLE_SQL = """
SELECT id, ticker, decision, final_score, recorded_at
FROM decision_snapshots
WHERE UPPER(TRIM(ticker)) NOT IN ({placeholders})
ORDER BY id
"""

OPTIONS_ELIGIBLE_SQL = """
SELECT id, ticker, detected_at, last_trade_ts
FROM options_flow
WHERE UPPER(TRIM(ticker)) NOT IN ({placeholders})
ORDER BY id
"""


def load_exclusions(mask_path: Path) -> tuple[str, ...]:
    masks = json.loads(mask_path.read_text(encoding="utf-8"))
    panel = masks["development"]["permitted_symbols"]
    aliases = masks["sealed"]["d107_symbols_and_aliases"]
    if len(panel) != 59:
        raise ValueError(f"masks.json has {len(panel)} panel symbols; expected 59")
    # The space form is a known alias that is not separately listed in masks.json.
    values = {str(value).strip().upper() for value in [*panel, *aliases, "BRK B"]}
    return tuple(sorted(values))


def open_read_only(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def install_deadline(
    conn: sqlite3.Connection,
    seconds: float,
    *,
    progress_ops: int = SQLITE_PROGRESS_OPS,
    clock=time.monotonic,
) -> None:
    if seconds < 0:
        raise ValueError("SQLite deadline must not be negative")
    deadline = clock() + seconds
    conn.set_progress_handler(lambda: int(clock() >= deadline), progress_ops)


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _stock_return(start: object, end: object) -> float | None:
    if not (_finite(start) and _finite(end)) or float(start) <= 0:
        return None
    return float(end) / float(start) - 1.0


def _summary(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "mean": None, "median": None, "positive_rate": None}
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "median": median(values),
        "positive_rate": sum(value > 0 for value in values) / len(values),
    }


def _percentile(sorted_values: list[float], proportion: float) -> float | None:
    if not sorted_values:
        return None
    position = (len(sorted_values) - 1) * proportion
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return sorted_values[low]
    weight = position - low
    return sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight


def date_clustered_mean_difference(
    observations: list[tuple[str, str, float]],
    treatment: str,
    comparison: str,
    *,
    seed: int,
    resamples: int,
) -> dict:
    """Resample whole dates, retaining every record on each selected date."""
    by_date: dict[str, dict[str, tuple[float, int]]] = defaultdict(dict)
    raw: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for date, group, value in observations:
        raw[date][group].append(value)
    for date, groups in raw.items():
        for group, values in groups.items():
            by_date[date][group] = (sum(values), len(values))

    dates = sorted(by_date)
    rng = random.Random(seed)
    differences: list[float] = []
    for _ in range(resamples):
        sums = {treatment: 0.0, comparison: 0.0}
        counts = {treatment: 0, comparison: 0}
        for _date_index in dates:
            sampled = by_date[dates[rng.randrange(len(dates))]]
            for group in (treatment, comparison):
                total, count = sampled.get(group, (0.0, 0))
                sums[group] += total
                counts[group] += count
        if counts[treatment] and counts[comparison]:
            differences.append(
                sums[treatment] / counts[treatment]
                - sums[comparison] / counts[comparison]
            )

    differences.sort()
    treatment_values = [v for _, g, v in observations if g == treatment]
    comparison_values = [v for _, g, v in observations if g == comparison]
    point = None
    if treatment_values and comparison_values:
        point = sum(treatment_values) / len(treatment_values) - sum(comparison_values) / len(comparison_values)
    standard_error = stdev(differences) if len(differences) > 1 else None
    threshold = 2.0 * standard_error if standard_error is not None else None
    verdict = "ADVANCE" if point is not None and threshold is not None and point > threshold else "PARK"
    return {
        "method": "date-clustered bootstrap; whole capture dates resampled with replacement",
        "date_clusters": len(dates),
        "requested_resamples": resamples,
        "usable_resamples": len(differences),
        "seed": seed,
        "mean_difference": point,
        "standard_error": standard_error,
        "two_standard_error_threshold": threshold,
        "two_standard_error_rule": "ADVANCE only when mean_difference > 2 * standard_error",
        "two_standard_error_verdict": verdict,
        "confidence_interval_95": [
            _percentile(differences, 0.025),
            _percentile(differences, 0.975),
        ],
    }


def _eligible_query(
    conn: sqlite3.Connection, template: str, exclusions: tuple[str, ...]
) -> list[sqlite3.Row]:
    sql = template.format(placeholders=", ".join("?" for _ in exclusions))
    return conn.execute(sql, exclusions).fetchall()


def _chunks(values: list[int], size: int = ID_QUERY_CHUNK):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def load_decision_outcomes(conn: sqlite3.Connection, eligible_ids: list[int]) -> dict[int, sqlite3.Row]:
    outcomes = {}
    for ids in _chunks(eligible_ids):
        placeholders = ", ".join("?" for _ in ids)
        sql = f"""
            SELECT id, outcome_price_at_alert, outcome_price_1h,
                   outcome_price_24h, outcome_price_5d, outcome_price_20d
            FROM decision_snapshots WHERE id IN ({placeholders})
        """
        outcomes.update({int(row["id"]): row for row in conn.execute(sql, ids)})
    return outcomes


def load_options_outcomes(conn: sqlite3.Connection, eligible_ids: list[int]) -> dict[int, sqlite3.Row]:
    outcomes = {}
    for ids in _chunks(eligible_ids):
        placeholders = ", ".join("?" for _ in ids)
        sql = f"""
            SELECT flow_id, market_date, close_0d, close_1d, close_5d,
                   bench_close_0d, bench_close_1d, bench_close_5d
            FROM options_flow_outcomes WHERE flow_id IN ({placeholders})
        """
        outcomes.update({int(row["flow_id"]): row for row in conn.execute(sql, ids)})
    return outcomes


def build_decision_probe(
    conn: sqlite3.Connection,
    exclusions: tuple[str, ...],
    *,
    seed: int,
    resamples: int,
) -> dict:
    rows = _eligible_query(conn, DECISION_ELIGIBLE_SQL, exclusions)
    outcomes = load_decision_outcomes(conn, [int(row["id"]) for row in rows])
    grouped: dict[str, list[float]] = {"score_at_least_80": [], "score_below_80": []}
    decisions: dict[str, Counter] = {key: Counter() for key in grouped}
    captured_counts = Counter()
    matured_counts = Counter()
    observations: list[tuple[str, str, float]] = []
    for row in rows:
        group = "score_at_least_80" if float(row["final_score"]) >= SCORE_CUTOFF else "score_below_80"
        captured_counts[group] += 1
        decisions[group][str(row["decision"])] += 1
        outcome = outcomes.get(int(row["id"]))
        if outcome is None:
            continue
        if _finite(outcome["outcome_price_5d"]):
            matured_counts[group] += 1
        value = _stock_return(outcome["outcome_price_at_alert"], outcome["outcome_price_5d"])
        if value is None:
            continue
        date = datetime.fromtimestamp(float(row["recorded_at"]), PACIFIC).date().isoformat()
        grouped[group].append(value)
        observations.append((date, group, value))

    return {
        "probe_id": "A_score_80_vs_other_captured_decisions",
        "population_label": "non-panel captured decision snapshots",
        "outcome_label": "five-session stock price move; not direction-adjusted trade performance",
        "pre_fixed_rule": "final_score >= 80",
        "captured_rows_after_exclusions": len(rows),
        "matured_five_session_rows": sum(matured_counts.values()),
        "usable_five_session_rows": sum(len(values) for values in grouped.values()),
        "groups": {
            key: {
                "captured_count": captured_counts[key],
                "matured_five_session_count": matured_counts[key],
                **_summary(values),
                "decision_counts_all_captured_rows": dict(sorted(decisions[key].items())),
            }
            for key, values in grouped.items()
        },
        "uncertainty": date_clustered_mean_difference(
            observations,
            "score_at_least_80",
            "score_below_80",
            seed=seed,
            resamples=resamples,
        ),
        "limitations": [
            "Decision labels do not reliably encode long versus short direction, so only positive stock moves are counted.",
            "The stored rows do not preserve the original narrative, the source-data as-of time, or the model version needed to reconstruct each score.",
            "This is a captured-population association check, not a causal estimate or a test on the sealed research panel.",
        ],
    }


def build_options_probe(
    conn: sqlite3.Connection,
    exclusions: tuple[str, ...],
    *,
    seed: int,
    resamples: int,
) -> dict:
    rows = _eligible_query(conn, OPTIONS_ELIGIBLE_SQL, exclusions)
    outcomes = load_options_outcomes(conn, [int(row["id"]) for row in rows])
    captured_tickers = {str(row["ticker"]) for row in rows}
    captured_dates = {str(row["market_date"]) for row in outcomes.values()}
    valid_timestamp_rows = 0
    invalid_timestamp_rows = 0
    horizon_values: dict[str, dict[str, list[float]]] = {
        "one_session": {"timely_0_to_60_seconds": [], "later_than_60_seconds": []},
        "five_session": {"timely_0_to_60_seconds": [], "later_than_60_seconds": []},
    }
    horizon_observations: dict[str, list[tuple[str, str, float]]] = {
        "one_session": [], "five_session": []
    }
    group_counts = Counter()
    matched_counts = Counter()
    usable_counts = defaultdict(Counter)
    for row in rows:
        if not (_finite(row["detected_at"]) and _finite(row["last_trade_ts"])):
            invalid_timestamp_rows += 1
            continue
        delay = float(row["detected_at"]) - float(row["last_trade_ts"])
        if delay < TIMELY_MIN_SECONDS:
            invalid_timestamp_rows += 1
            continue
        valid_timestamp_rows += 1
        group = "timely_0_to_60_seconds" if delay <= TIMELY_MAX_SECONDS else "later_than_60_seconds"
        group_counts[group] += 1
        outcome = outcomes.get(int(row["id"]))
        if outcome is None:
            continue
        matched_counts[group] += 1
        for horizon, stock_field, bench_field in (
            ("one_session", "close_1d", "bench_close_1d"),
            ("five_session", "close_5d", "bench_close_5d"),
        ):
            stock = _stock_return(outcome["close_0d"], outcome[stock_field])
            benchmark = _stock_return(outcome["bench_close_0d"], outcome[bench_field])
            if stock is None or benchmark is None:
                continue
            value = stock - benchmark
            usable_counts[group][horizon] += 1
            horizon_values[horizon][group].append(value)
            horizon_observations[horizon].append((str(outcome["market_date"]), group, value))

    horizons = {}
    for index, horizon in enumerate(("one_session", "five_session")):
        horizons[horizon] = {
            "groups": {
                group: _summary(values)
                for group, values in horizon_values[horizon].items()
            },
            "uncertainty": date_clustered_mean_difference(
                horizon_observations[horizon],
                "timely_0_to_60_seconds",
                "later_than_60_seconds",
                seed=seed + index + 1,
                resamples=resamples,
            ),
        }

    coverage = {}
    for group in ("timely_0_to_60_seconds", "later_than_60_seconds"):
        eligible = group_counts[group]
        matched = matched_counts[group]
        coverage[group] = {
            "eligible_count": eligible,
            "matched_outcome_count": matched,
            "outcome_coverage": matched / eligible if eligible else None,
            "usable_one_session_count": usable_counts[group]["one_session"],
            "usable_one_session_coverage": usable_counts[group]["one_session"] / eligible if eligible else None,
            "usable_five_session_count": usable_counts[group]["five_session"],
            "usable_five_session_coverage": usable_counts[group]["five_session"] / eligible if eligible else None,
        }

    return {
        "probe_id": "B_timely_vs_later_captured_options_flow",
        "population_label": "non-panel captured options-flow records with stored stock outcomes",
        "outcome_label": "market-adjusted stock returns; not option profit or loss",
        "pre_fixed_rule": "0 <= detected_at - last_trade_ts <= 60 seconds",
        "comparison_rule": "detected_at - last_trade_ts > 60 seconds",
        "eligible_rows_after_exclusions": len(rows),
        "matched_outcome_rows": len(outcomes),
        "eligible_tickers": len(captured_tickers),
        "matched_outcome_market_dates": len(captured_dates),
        "valid_timestamp_rows": valid_timestamp_rows,
        "invalid_or_negative_delay_rows_excluded": invalid_timestamp_rows,
        "timestamp_group_counts_before_outcome_availability": dict(sorted(group_counts.items())),
        "coverage_by_timing": coverage,
        "horizons": horizons,
        "limitations": [
            "The result measures stock returns after an options-flow record; it does not measure the option contract's profit or loss.",
            "The stored rows do not preserve source, provider, or receipt time, so the delay is not a complete end-to-end latency measure.",
            "The database contains selected captured flow rather than all market flow, so selection bias can drive differences.",
            "This is a captured-population association check, not a causal estimate or a test on the sealed research panel.",
        ],
    }


def build_report(
    db_path: Path,
    mask_path: Path,
    *,
    seed: int = BOOTSTRAP_SEED,
    resamples: int = BOOTSTRAP_RESAMPLES,
    sqlite_deadline_seconds: float = SQLITE_DEADLINE_SECONDS,
    sqlite_progress_ops: int = SQLITE_PROGRESS_OPS,
) -> dict:
    exclusions = load_exclusions(mask_path)
    mask_sha = hashlib.sha256(mask_path.read_bytes()).hexdigest()
    db_stat = db_path.resolve().stat()
    with open_read_only(db_path) as conn:
        install_deadline(conn, sqlite_deadline_seconds, progress_ops=sqlite_progress_ops)
        conn.execute("BEGIN")
        try:
            watermarks = {
                "decision_snapshots": dict(conn.execute(
                    "SELECT COUNT(*) AS row_count, MAX(id) AS max_id, "
                    "MAX(recorded_at) AS max_recorded_at FROM decision_snapshots"
                ).fetchone()),
                "options_flow": dict(conn.execute(
                    "SELECT COUNT(*) AS row_count, MAX(id) AS max_id, "
                    "MAX(detected_at) AS max_detected_at FROM options_flow"
                ).fetchone()),
                "options_flow_outcomes": dict(conn.execute(
                    "SELECT COUNT(*) AS row_count, MAX(flow_id) AS max_flow_id, "
                    "MAX(graded_at) AS max_graded_at FROM options_flow_outcomes"
                ).fetchone()),
            }
            schema_version = int(conn.execute("PRAGMA schema_version").fetchone()[0])
            decision = build_decision_probe(conn, exclusions, seed=seed, resamples=resamples)
            options = build_options_probe(conn, exclusions, seed=seed, resamples=resamples)
            conn.execute("COMMIT")
        except BaseException:
            conn.set_progress_handler(None, 0)
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.set_progress_handler(None, 0)
    return {
        "report_id": "TRADING_EDGE_CAPTURED_POPULATION_PROBES_V1",
        "status": "descriptive_non_panel_checks_only",
        "database_access": "SQLite read-only mode with query_only enabled",
        "database_snapshot": "one read transaction shared by both probes",
        "filter_enforcement": "two-phase allowlist: outcomes queried only by IDs selected after symbol exclusions",
        "sqlite_deadline_seconds": sqlite_deadline_seconds,
        "input_identity": {
            "database": {
                "path": str(db_path.resolve()),
                "device": db_stat.st_dev,
                "inode": db_stat.st_ino,
                "size_bytes": db_stat.st_size,
                "modified_time_ns": db_stat.st_mtime_ns,
                "schema_version": schema_version,
            },
            "watermarks": watermarks,
            "masks_sha256": mask_sha,
        },
        "mask_source": str(mask_path),
        "excluded_symbols": list(exclusions),
        "exclusion_count": len(exclusions),
        "probes": [decision, options],
    }


def write_report(report: dict, output_path: Path) -> tuple[Path, Path]:
    payload = (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    sidecar = output_path.with_name(output_path.name + ".sha256")
    sidecar.write_text(f"{digest}  {output_path.name}\n", encoding="ascii")
    return output_path, sidecar


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    default_dir = root / ".omc/research/trading-edge-discovery"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=root / "consensus.db")
    parser.add_argument("--masks", type=Path, default=default_dir / "masks.json")
    parser.add_argument("--output", type=Path, default=default_dir / "captured-population-probes.json")
    parser.add_argument("--resamples", type=int, default=BOOTSTRAP_RESAMPLES)
    parser.add_argument("--sqlite-deadline-seconds", type=float, default=SQLITE_DEADLINE_SECONDS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.resamples < 1:
        raise ValueError("--resamples must be positive")
    report = build_report(
        args.db,
        args.masks,
        resamples=args.resamples,
        sqlite_deadline_seconds=args.sqlite_deadline_seconds,
    )
    output, sidecar = write_report(report, args.output)
    print(json.dumps({"output": str(output), "sha256_sidecar": str(sidecar)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
