#!/usr/bin/env python3
"""Build the bounded CRM/NOW/ORCL displayed-spread report.

This is a descriptive report over the stored September 2026 quote files.  It
does not estimate fills, slippage, market impact, or costs for other stocks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import date, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow.parquet as pq


REPORT_VERSION = "TRADING_EDGE_QUOTE_COST_REPORT_V1"
SYMBOLS = ("CRM", "NOW", "ORCL")
START_DATE = date(2026, 9, 1)
END_DATE = date(2026, 9, 25)
PACIFIC = ZoneInfo("America/Los_Angeles")
REGULAR_OPEN = time(6, 30)
FIRST_HOUR_END = time(7, 30)
REGULAR_CLOSE = time(13, 0)
LAG_MIN_SECONDS = -15.0
LAG_MAX_SECONDS = 60.0
SOURCE_COLUMNS = (
    "market_date",
    "captured_at_utc",
    "ticker",
    "bid",
    "ask",
    "quote_time",
)
FILE_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})\.parquet$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_session_dates() -> list[str]:
    """Return weekdays in scope, excluding the known 2026 Labor Day closure."""
    labor_day = date(2026, 9, 7)
    result = []
    current = START_DATE
    while current <= END_DATE:
        if current.weekday() < 5 and current != labor_day:
            result.append(current.isoformat())
        current += timedelta(days=1)
    return result


def source_files(source_dir: Path) -> list[Path]:
    """Select only date-named parquet files inside the registered date range."""
    selected = []
    for path in source_dir.iterdir():
        match = FILE_PATTERN.match(path.name)
        if not path.is_file() or match is None:
            continue
        file_date = date.fromisoformat(match.group(1))
        if START_DATE <= file_date <= END_DATE:
            selected.append(path)
    if not selected:
        raise ValueError(f"no September 1-25 quote parquet files found in {source_dir}")
    return sorted(selected)


def read_selected_quotes(files: list[Path]) -> tuple[pd.DataFrame, list[dict]]:
    """Read only the required columns and three symbols from each parquet file."""
    frames = []
    fingerprints = []
    for path in files:
        table = pq.read_table(
            path,
            columns=list(SOURCE_COLUMNS),
            filters=[("ticker", "in", list(SYMBOLS))],
        )
        frame = table.to_pandas()
        frame["_source_file"] = path.name
        frames.append(frame)
        fingerprints.append({
            "file": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "selected_rows": len(frame),
        })
    return pd.concat(frames, ignore_index=True), fingerprints


def quote_time_unit(values: pd.Series) -> str:
    numeric = pd.to_numeric(values, errors="coerce").dropna().abs()
    if numeric.empty:
        raise ValueError("quote_time contains no numeric values")
    median = float(numeric.median())
    if 1_000_000_000 <= median < 100_000_000_000:
        return "s"
    if 1_000_000_000_000 <= median < 100_000_000_000_000:
        return "ms"
    raise ValueError(f"quote_time magnitude is not a supported Unix time: {median}")


def rounded(value: float) -> float:
    return round(float(value), 8)


def spread_summary(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {"row_count": 0, "median_displayed_spread_bps": None, "p90_displayed_spread_bps": None}
    return {
        "row_count": len(frame),
        "median_displayed_spread_bps": rounded(frame["displayed_spread_bps"].median()),
        "p90_displayed_spread_bps": rounded(frame["displayed_spread_bps"].quantile(0.90)),
    }


def build_report(quotes: pd.DataFrame, fingerprints: list[dict]) -> dict:
    missing_columns = sorted(set(SOURCE_COLUMNS) - set(quotes.columns))
    if missing_columns:
        raise ValueError(f"quote rows missing columns: {', '.join(missing_columns)}")

    frame = quotes.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    unexpected = sorted(set(frame["ticker"]) - set(SYMBOLS))
    if unexpected:
        raise ValueError(f"unexpected ticker rows survived parquet filter: {', '.join(unexpected)}")
    frame["captured_utc"] = pd.to_datetime(frame["captured_at_utc"], utc=True, errors="coerce")
    unit = quote_time_unit(frame["quote_time"])
    frame["provider_quote_utc"] = pd.to_datetime(
        pd.to_numeric(frame["quote_time"], errors="coerce"), unit=unit, utc=True, errors="coerce"
    )
    frame["captured_pacific"] = frame["captured_utc"].dt.tz_convert(PACIFIC)
    frame["lag_seconds"] = (frame["captured_utc"] - frame["provider_quote_utc"]).dt.total_seconds()
    frame["bid"] = pd.to_numeric(frame["bid"], errors="coerce")
    frame["ask"] = pd.to_numeric(frame["ask"], errors="coerce")

    valid_clock = frame["captured_utc"].notna() & frame["provider_quote_utc"].notna()
    positive = (frame["bid"] > 0) & (frame["ask"] > 0)
    noncrossed = frame["ask"] >= frame["bid"]
    positive_noncrossed = positive & noncrossed
    local_minutes = (
        frame["captured_pacific"].dt.hour * 60
        + frame["captured_pacific"].dt.minute
        + frame["captured_pacific"].dt.second / 60.0
    )
    open_minute = REGULAR_OPEN.hour * 60 + REGULAR_OPEN.minute
    first_hour_end_minute = FIRST_HOUR_END.hour * 60 + FIRST_HOUR_END.minute
    close_minute = REGULAR_CLOSE.hour * 60 + REGULAR_CLOSE.minute
    regular_session = valid_clock & local_minutes.between(open_minute, close_minute, inclusive="left")
    lag_window = frame["lag_seconds"].between(LAG_MIN_SECONDS, LAG_MAX_SECONDS, inclusive="both")
    included = positive_noncrossed & regular_session & lag_window
    selected = frame.loc[included].copy()
    selected["displayed_spread_bps"] = (
        10_000.0 * (selected["ask"] - selected["bid"]) / ((selected["ask"] + selected["bid"]) / 2.0)
    )
    selected["bucket"] = selected["captured_pacific"].dt.floor("30min").dt.strftime("%H:%M")

    first_hour = selected[
        (selected["captured_pacific"].dt.hour * 60 + selected["captured_pacific"].dt.minute)
        < first_hour_end_minute
    ]
    buckets = []
    for bucket, group in selected.groupby("bucket", sort=True):
        buckets.append({"bucket_start_pacific": bucket, **spread_summary(group)})

    by_symbol = []
    for symbol in SYMBOLS:
        symbol_rows = selected[selected["ticker"] == symbol]
        symbol_first = symbol_rows[
            (symbol_rows["captured_pacific"].dt.hour * 60 + symbol_rows["captured_pacific"].dt.minute)
            < first_hour_end_minute
        ]
        by_symbol.append({
            "symbol": symbol,
            "regular_session": spread_summary(symbol_rows),
            "first_regular_session_hour": spread_summary(symbol_first),
        })

    present_dates = sorted({item["file"][:-8] for item in fingerprints})
    expected_dates = expected_session_dates()
    per_file = []
    for item in fingerprints:
        file_rows = frame[frame["_source_file"] == item["file"]]
        valid_rows = selected[selected["_source_file"] == item["file"]]
        capture_times = file_rows["captured_pacific"].dropna()
        per_file.append({
            "file": item["file"],
            "selected_symbol_rows": len(file_rows),
            "included_regular_session_rows": len(valid_rows),
            "first_capture_pacific": capture_times.min().isoformat() if not capture_times.empty else None,
            "last_capture_pacific": capture_times.max().isoformat() if not capture_times.empty else None,
        })

    market_date_mismatch = (
        frame["market_date"].astype(str) != frame["_source_file"].str.removesuffix(".parquet")
    )
    return {
        "report_version": REPORT_VERSION,
        "scope": {
            "symbols": list(SYMBOLS),
            "start_date": START_DATE.isoformat(),
            "end_date": END_DATE.isoformat(),
            "timezone": "America/Los_Angeles",
            "regular_session_pacific": "06:30-13:00",
            "first_hour_pacific": "06:30-07:30",
            "lag_seconds_inclusive": [LAG_MIN_SECONDS, LAG_MAX_SECONDS],
            "spread_formula": "10000 * (ask - bid) / ((ask + bid) / 2)",
            "session_and_bucket_clock": "captured_at_utc converted with ZoneInfo('America/Los_Angeles')",
            "provider_quote_time_unit_detected": unit,
        },
        "source_files": fingerprints,
        "completeness": {
            "expected_session_dates": expected_dates,
            "present_file_dates": present_dates,
            "missing_session_dates": sorted(set(expected_dates) - set(present_dates)),
            "file_count": len(fingerprints),
            "selected_symbol_rows": len(frame),
            "invalid_timestamp_rows": int((~valid_clock).sum()),
            "nonpositive_quote_rows": int((~positive).sum()),
            "crossed_quote_rows": int((positive & ~noncrossed).sum()),
            "market_date_filename_mismatch_rows": int(market_date_mismatch.sum()),
            "positive_noncrossed_regular_session_rows": int((positive_noncrossed & regular_session).sum()),
            "regular_session_rows_outside_lag_window": int((positive_noncrossed & regular_session & ~lag_window).sum()),
            "included_rows": len(selected),
            "per_file": per_file,
        },
        "results": {
            "regular_session_overall": spread_summary(selected),
            "first_regular_session_hour": spread_summary(first_hour),
            "by_symbol": by_symbol,
            "thirty_minute_buckets": buckets,
        },
        "limitations": [
            "Displayed bid-ask spread is descriptive and is not a realized fill, slippage, market-impact, or round-trip cost.",
            "The collector saved poll-start time before its network request and did not save response-completion time, so exact quote availability is unknown.",
            "The lag filter describes provider quote time versus poll start; it does not turn poll start into receipt time.",
            "The three stocks do not establish costs for the other stocks in the research panel.",
            "Quote-size units, venue, quote conditions, and provider version were not stored, so these rows cannot prove fill capacity.",
            "Missing and partial dates are reported as gaps; no rows are invented or filled.",
        ],
    }


def write_report(report: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, output)
    digest = hashlib.sha256(payload).hexdigest()
    sidecar = output.with_name(output.name + ".sha256")
    sidecar.write_text(f"{digest}  {output.name}\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("/home/openclaw/.openclaw/research-data/todo-109/stock_quotes"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".omc/research/trading-edge-discovery/quote-cost-report.json"),
    )
    args = parser.parse_args()
    files = source_files(args.source_dir)
    quotes, fingerprints = read_selected_quotes(files)
    write_report(build_report(quotes, fingerprints), args.output)
    print(json.dumps({"output": str(args.output), "files": len(files), "selected_rows": len(quotes)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
