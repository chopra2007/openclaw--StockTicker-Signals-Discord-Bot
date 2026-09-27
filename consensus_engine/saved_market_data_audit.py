"""Read-only qualification checks for saved one-minute market-bar files.

The audit reports what the files contain and which source facts remain unknown.
It does not turn a trade-bar file into quote, correction, finality, membership,
or execution evidence.
"""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq


AUDIT_VERSION = "M91EP_SAVED_MARKET_DATA_AUDIT_V1"
REQUIRED_COLUMNS = ("date", "symbol", "minute", "open", "high", "low", "close", "volume")
REGULAR_MINUTES = (570, 959)
GAP_DEPENDENT_RULES = (
    "historical_bid_ask_execution",
    "original_availability",
    "corrections_and_finality",
    "point_in_time_membership",
    "historical_borrow",
    "complete_option_chain_execution",
)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _audit_one(path: Path) -> dict[str, object]:
    parquet = pq.ParquetFile(path)
    columns = tuple(parquet.schema_arrow.names)
    missing_columns = sorted(set(REQUIRED_COLUMNS) - set(columns))
    if missing_columns:
        raise ValueError(f"missing required columns: {missing_columns}")

    rows = 0
    nulls = {name: 0 for name in REQUIRED_COLUMNS}
    dates: set[str] = set()
    symbols: set[str] = set()
    symbols_by_date: dict[str, set[str]] = defaultdict(set)
    regular_counts: dict[tuple[str, str], int] = defaultdict(int)
    duplicate_keys = 0
    out_of_order_keys = 0
    outside_regular_session = 0
    nonpositive_prices = 0
    nonfinite_prices = 0
    invalid_ohlc = 0
    negative_volume = 0
    zero_volume = 0
    previous_key: tuple[str, str, int] | None = None
    minute_min: int | None = None
    minute_max: int | None = None

    for batch in parquet.iter_batches(batch_size=131_072, columns=list(REQUIRED_COLUMNS)):
        frame = batch.to_pandas()
        frame["date"] = frame["date"].astype(str)
        frame["symbol"] = frame["symbol"].astype(str)
        rows += len(frame)
        for name in REQUIRED_COLUMNS:
            nulls[name] += int(frame[name].isna().sum())

        dates.update(frame["date"].unique())
        symbols.update(frame["symbol"].unique())
        for date, values in frame.groupby("date", observed=True)["symbol"]:
            symbols_by_date[str(date)].update(values.unique())

        minute = frame["minute"]
        if len(frame):
            batch_min, batch_max = int(minute.min()), int(minute.max())
            minute_min = batch_min if minute_min is None else min(minute_min, batch_min)
            minute_max = batch_max if minute_max is None else max(minute_max, batch_max)
        regular = minute.between(*REGULAR_MINUTES)
        outside_regular_session += int((~regular).sum())
        grouped = frame.loc[regular].groupby(["date", "symbol"], observed=True)["minute"].nunique()
        for key, count in grouped.items():
            regular_counts[(str(key[0]), str(key[1]))] += int(count)

        duplicate_keys += int(frame.duplicated(["date", "symbol", "minute"]).sum())
        keys = frame[["date", "symbol", "minute"]]
        if len(keys):
            first = keys.iloc[0]
            first_key = (str(first["date"]), str(first["symbol"]), int(first["minute"]))
            if previous_key is not None:
                duplicate_keys += int(first_key == previous_key)
                out_of_order_keys += int(first_key < previous_key)
            date_values = keys["date"].to_numpy(dtype=str)
            symbol_values = keys["symbol"].to_numpy(dtype=str)
            minute_values = keys["minute"].to_numpy()
            same_date = date_values[1:] == date_values[:-1]
            same_symbol = symbol_values[1:] == symbol_values[:-1]
            out_of_order_keys += int((
                (date_values[1:] < date_values[:-1])
                | (same_date & (symbol_values[1:] < symbol_values[:-1]))
                | (same_date & same_symbol & (minute_values[1:] < minute_values[:-1]))
            ).sum())
            last = keys.iloc[-1]
            previous_key = (str(last["date"]), str(last["symbol"]), int(last["minute"]))

        prices = frame[["open", "high", "low", "close"]]
        numeric = prices.to_numpy(dtype=float)
        nonfinite_prices += int((~np.isfinite(numeric)).sum())
        nonpositive_prices += int((numeric <= 0).sum())
        invalid_ohlc += int((
            (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
            | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
        ).sum())
        negative_volume += int((frame["volume"] < 0).sum())
        zero_volume += int((frame["volume"] == 0).sum())

    expected = REGULAR_MINUTES[1] - REGULAR_MINUTES[0] + 1
    incomplete = {key: expected - count for key, count in regular_counts.items() if count != expected}
    per_date = [len(symbols_by_date[date]) for date in sorted(symbols_by_date)]
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": _file_sha256(path),
        "columns": list(columns),
        "rows": rows,
        "dates": len(dates),
        "first_date": min(dates),
        "last_date": max(dates),
        "symbols": len(symbols),
        "symbol_dates": len(regular_counts),
        "minute_range": [minute_min, minute_max],
        "median_symbols_per_date": float(np.median(per_date)),
        "minimum_symbols_per_date": min(per_date),
        "null_counts": nulls,
        "duplicate_keys": duplicate_keys,
        "out_of_order_keys": out_of_order_keys,
        "outside_regular_session_rows": outside_regular_session,
        "complete_390_minute_symbol_dates": sum(count == expected for count in regular_counts.values()),
        "incomplete_symbol_dates": len(incomplete),
        "missing_regular_minutes": sum(max(0, value) for value in incomplete.values()),
        "overfull_symbol_dates": sum(value < 0 for value in incomplete.values()),
        "nonfinite_prices": nonfinite_prices,
        "nonpositive_prices": nonpositive_prices,
        "invalid_ohlc_rows": invalid_ohlc,
        "negative_volume_rows": negative_volume,
        "zero_volume_rows": zero_volume,
    }


def _cross_check(paths: tuple[Path, Path], dates: Iterable[str]) -> dict[str, object]:
    sample_dates = tuple(dates)
    frames = []
    columns = ["date", "symbol", "minute", "close", "volume"]
    for path in paths:
        table = ds.dataset(path).to_table(
            columns=columns,
            filter=ds.field("date").isin(sample_dates),
        )
        frame = table.to_pandas()
        frame["date"] = frame["date"].astype(str)
        frame["symbol"] = frame["symbol"].astype(str)
        frames.append(frame)
    joined = frames[0].merge(
        frames[1], on=["date", "symbol", "minute"], suffixes=("_left", "_right")
    )
    close_bps = (joined["close_left"] / joined["close_right"] - 1.0).abs() * 10_000
    volume_ratio = joined["volume_left"] / joined["volume_right"].replace(0, np.nan)
    return {
        "method": "deterministic evenly spaced date sample",
        "sample_dates": list(sample_dates),
        "overlapping_rows": len(joined),
        "close_difference_bps_median": float(close_bps.median()),
        "close_difference_bps_p95": float(close_bps.quantile(0.95)),
        "close_difference_bps_p99": float(close_bps.quantile(0.99)),
        "volume_ratio_left_over_right_median": float(volume_ratio.median()),
    }


def _observed_dates(path: Path) -> set[str]:
    values: set[str] = set()
    for batch in pq.ParquetFile(path).iter_batches(batch_size=262_144, columns=["date"]):
        values.update(batch.column(0).to_pandas().astype(str).unique())
    return values


def audit_saved_market_data(paths: Iterable[Path], *, sample_date_count: int = 40) -> dict[str, object]:
    """Audit two saved, sorted one-minute OHLCV files without changing them."""
    resolved = tuple(Path(path).resolve() for path in paths)
    if len(resolved) != 2 or resolved[0] == resolved[1]:
        raise ValueError("exactly two different saved files are required")
    if sample_date_count < 1:
        raise ValueError("sample_date_count must be positive")

    files = tuple(_audit_one(path) for path in resolved)
    common_dates = sorted(_observed_dates(resolved[0]) & _observed_dates(resolved[1]))
    indexes = np.linspace(0, len(common_dates) - 1, min(sample_date_count, len(common_dates))).astype(int)
    sampled = tuple(common_dates[index] for index in indexes)
    cross = _cross_check(resolved, sampled)
    gaps = {
        rule: {"status": "GAP", "dependent_rules": "OFF_UNTESTED"}
        for rule in GAP_DEPENDENT_RULES
    }
    return {
        "version": AUDIT_VERSION,
        "mode": "READ_ONLY_OFFLINE_INVENTORY",
        "files": list(files),
        "cross_dataset_agreement": cross,
        "field_support": {
            "bar_native_ohlcv": "OBSERVED",
            "event_time": "MINUTE_START_FROM_SAVED_DATE_AND_MINUTE",
            "bid_ask": "ABSENT",
            "original_availability": "UNKNOWN",
            "corrections": "UNKNOWN",
            "finality": "UNKNOWN",
            "point_in_time_membership": "UNKNOWN",
            "adjustment_provenance": "NOT_PROVEN_BY_SAVED_PARQUET",
        },
        "gaps": gaps,
        "held_out_evaluation_run": False,
        "promotion_or_live_release": False,
        "network_used": False,
        "spend_usd": 0,
    }


__all__ = ["AUDIT_VERSION", "GAP_DEPENDENT_RULES", "audit_saved_market_data"]
