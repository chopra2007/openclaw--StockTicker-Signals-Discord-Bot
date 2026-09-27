#!/usr/bin/env python3
"""Register and validate the sealed E1 trading-edge experiment.

This file does not calculate returns.  It freezes the permitted development
slice and provides the only approved path for opening rows in later E1 code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo


WORKSPACE = Path(__file__).resolve().parents[2]
RESULT_DIR = WORKSPACE / ".omc/research/trading-edge-discovery"
PLAN = WORKSPACE / ".omc/plans/trading-edge-execution-roadmap-2026-09-25.md"
PRIMARY_SOURCE = (
    WORKSPACE / ".omc/research/professional-day-trader-methods/bars-equs-allmin.parquet"
)
COMPARISON_SOURCE = (
    WORKSPACE / ".omc/research/professional-day-trader-methods/bars-pillar-allmin.parquet"
)
PACIFIC = ZoneInfo("America/Los_Angeles")

STUDY_ID = "TRADING_EDGE_E1_V1"
DEVELOPMENT_FIRST = "2023-03-28"
DEVELOPMENT_LAST = "2025-03-31"
PERMITTED_SYMBOLS = (
    "TSM", "JPM", "ORCL", "LLY", "V", "GS", "CAT", "BAC", "XOM", "UNH",
    "JNJ", "CRM", "DELL", "GEV", "MA", "BE", "IBM", "NOW", "GE", "CVX",
    "GLW", "ABBV", "C", "COHR", "MS", "HD", "KO", "PG", "ANET", "VRT",
    "MRK", "WFC", "APH", "MCD", "VZ", "TMO", "BA", "TJX", "AXP", "UBER",
    "RTX", "PM", "ABT", "SCHW", "ACN", "SNOW", "ETN", "PFE", "NEE", "T",
    "DIS", "WELL", "SPGI", "SHW", "COP", "NEM", "DHR", "MCK", "CIEN",
)
D107_SYMBOLS = ("GOOGL", "AMZN", "META", "AVGO", "BRK.B", "IWM", "GLD", "VXX")
RESERVED_DATES = (
    "2025-04-30", "2025-06-02", "2025-07-03", "2025-08-05",
    "2025-09-05", "2025-10-07", "2025-11-06", "2025-12-09",
    "2026-01-09", "2026-02-11", "2026-03-16", "2026-04-16",
    "2026-05-18", "2026-06-18", "2026-07-22", "2026-08-21",
)
BLOCKS = (
    ("B1", "2023-03-28", "2023-06-30"),
    ("B2", "2023-07-03", "2023-12-29"),
    ("B3", "2024-01-02", "2024-06-28"),
    ("B4", "2024-07-01", "2024-12-31"),
    ("B5", "2025-01-02", "2025-03-31"),
)


def _settings() -> list[dict]:
    settings = []
    for opening_minutes in (5, 15):
        for volume_gate in (None, 1.5, 2.0, 2.5):
            gate_id = "OFF" if volume_gate is None else str(volume_gate).replace(".", "P")
            settings.append({
                "id": f"OR{opening_minutes}_VOL_{gate_id}",
                "family": "opening_range",
                "opening_minutes": opening_minutes,
                "opening_volume_gate": volume_gate,
                "primary_horizon_minutes": 30,
                "horizons_minutes": [5, 15, 30, 60],
            })
    for compression in (False, True):
        settings.append({
            "id": f"HILO_COMPRESSION_{'ON' if compression else 'OFF'}",
            "family": "high_low_breakout",
            "compression": compression,
            "opening_five_minute_rvol_min": 1.5,
            "spy_relative_strength": False,
            "primary_horizon_minutes": 30,
            "horizons_minutes": [5, 15, 30, 60],
        })
    settings.append({
        "id": "FAILED_OR15", "family": "failed_opening_range",
        "opening_minutes": 15, "intrabar_fast_variant": False,
        "primary_horizon_minutes": 30, "horizons_minutes": [5, 15, 30, 60],
    })
    for mandatory_vwap in (True, False):
        for impulse_avwap in (False, True):
            settings.append({
                "id": (
                    f"FIRST_PULLBACK_VWAP_{'MANDATORY' if mandatory_vwap else 'RELAXED'}"
                    f"_IMPULSE_AVWAP_{'ON' if impulse_avwap else 'OFF'}"
                ),
                "family": "first_pullback",
                "session_vwap_support": "mandatory" if mandatory_vwap else "relaxed",
                "impulse_anchored_vwap_support": impulse_avwap,
                "window_pacific": "06:38-07:15",
                "primary_horizon_minutes": 30,
                "horizons_minutes": [5, 15, 30, 60],
            })
    settings.append({
        "id": "LATE_CONTINUATION", "family": "late_continuation",
        "reference_entry": "30 minutes before actual close",
        "terminal_exit": "5 minutes before actual close",
        "primary_horizon_minutes": 25, "horizons_minutes": [5, 15, 25],
    })
    return settings


SETTINGS = tuple(_settings())


def _cells() -> list[dict]:
    cells = []
    for setting in SETTINGS:
        for direction in ("long", "short"):
            for horizon in setting["horizons_minutes"]:
                cells.append({
                    "id": f"{setting['id']}__{direction.upper()}__H{horizon}",
                    "setting_id": setting["id"],
                    "family": setting["family"],
                    "direction": direction,
                    "horizon_minutes": horizon,
                    "is_primary_horizon": horizon == setting["primary_horizon_minutes"],
                })
    return cells


CELLS = tuple(_cells())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_symbol(symbol: str) -> str:
    compact = "".join(ch for ch in symbol.upper().strip() if ch.isalnum())
    if compact == "BRKB":
        return "BRK.B"
    return compact


def assert_permitted_row_request(
    symbols: Iterable[str], start_date: str, end_date: str
) -> tuple[str, ...]:
    """Reject a row request before any market-data reader is constructed."""
    requested = tuple(sorted({canonical_symbol(symbol) for symbol in symbols}))
    if not requested:
        raise ValueError("at least one symbol is required")
    sealed = sorted(set(requested) & set(D107_SYMBOLS))
    if sealed:
        raise PermissionError(f"D-107 symbols are sealed: {', '.join(sealed)}")
    unknown = sorted(set(requested) - set(PERMITTED_SYMBOLS))
    if unknown:
        raise PermissionError(f"symbols are outside the registered E1 universe: {', '.join(unknown)}")
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if start > end:
        raise ValueError("start_date is after end_date")
    if start < date.fromisoformat(DEVELOPMENT_FIRST) or end > date.fromisoformat(DEVELOPMENT_LAST):
        raise PermissionError(
            f"E1 row reads are restricted to {DEVELOPMENT_FIRST} through {DEVELOPMENT_LAST}"
        )
    if set(RESERVED_DATES) & {start_date, end_date}:
        raise PermissionError("request touches an M9.1ER reserved date")
    return requested


def guarded_parquet_batches(
    source: Path,
    symbols: Sequence[str],
    start_date: str,
    end_date: str,
    columns: Sequence[str],
    batch_size: int = 65_536,
):
    """Yield only registered rows; the mask is checked before a scan exists."""
    permitted = assert_permitted_row_request(symbols, start_date, end_date)
    source = source.resolve()
    if source not in {PRIMARY_SOURCE.resolve(), COMPARISON_SOURCE.resolve()}:
        raise PermissionError("source is outside the registered E1 source set")

    import pyarrow.dataset as ds

    requested_columns = list(dict.fromkeys([*columns, "symbol", "date"]))
    predicate = (
        ds.field("symbol").isin(list(permitted))
        & (ds.field("date") >= start_date)
        & (ds.field("date") <= end_date)
    )
    scanner = ds.dataset(source, format="parquet").scanner(
        columns=requested_columns, filter=predicate, batch_size=batch_size
    )
    yield from scanner.to_batches()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _file_record(path: Path) -> dict:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def build_masks(registered_at: str) -> dict:
    return {
        "study_id": STUDY_ID,
        "mask_enforcement": "validate request before constructing any row reader",
        "development": {
            "first_date": DEVELOPMENT_FIRST,
            "last_date": DEVELOPMENT_LAST,
            "permitted_symbols": list(PERMITTED_SYMBOLS),
        },
        "sealed": {
            "d107_symbols_and_aliases": list(D107_SYMBOLS),
            "legacy_time_window": {"first_date": "2025-07-01", "last_date_exclusive": "2026-08-22"},
            "older_panel_profit_window": {"first_date": "2025-12-01", "last_date": "2026-08-21"},
            "m9_1er_reserved_dates": list(RESERVED_DATES),
            "exposure_ambiguity_exclusion": {
                "first_date": "2026-08-22", "last_instant": registered_at
            },
            "prospective_confirmation_epoch": {
                "first_instant": registered_at,
                "status": "sealed until development-only rules and endpoint are frozen",
                "permitted_pre_endpoint_reads": "health counts only; no returns, plots, tuning, or labels",
            },
        },
    }


def build_registration(registered_at: str, source_fingerprints: dict, masks_sha256: str) -> dict:
    return {
        "study_id": STUDY_ID,
        "registered_at_pacific": registered_at,
        "timezone": "America/Los_Angeles",
        "purpose": "development-only event-response study; no trading simulation",
        "spend_usd": 0.0,
        "network_used": False,
        "development_prefix": {"first_date": DEVELOPMENT_FIRST, "last_date": DEVELOPMENT_LAST},
        "development_blocks": [
            {"id": block_id, "first_date": first, "last_date": last}
            for block_id, first, last in BLOCKS
        ],
        "universe": {"count": len(PERMITTED_SYMBOLS), "symbols": list(PERMITTED_SYMBOLS)},
        "settings": list(SETTINGS),
        "cells": list(CELLS),
        "counts": {
            "development_blocks": len(BLOCKS),
            "permitted_symbols": len(PERMITTED_SYMBOLS),
            "settings": len(SETTINGS),
            "directional_horizon_cells": len(CELLS),
        },
        "rules": {
            "directions": ["long", "short"],
            "first_15_horizons_minutes": [5, 15, 30, 60],
            "late_horizons_minutes": [5, 15, 25],
            "headline_event": "first eligible occurrence per setting, symbol, day, and direction",
            "entry_reference": "next scheduled minute open after completed trigger bar",
            "missing_next_minute": "no entry",
            "stops_sizing_allocation": "not part of E1",
            "cost_floor_bps_round_trip": {"first_regular_session_hour": 8, "otherwise": 5},
            "cost_stresses_bps": [20, "twice time-of-day floor"],
        },
        "fingerprints": {
            "masks_sha256": masks_sha256,
            "sources_sha256": {
                item["role"]: item["sha256"] for item in source_fingerprints["sources"]
            },
            "code_and_plan": {
                "registration_script": _file_record(Path(__file__).resolve()),
                "execution_roadmap": _file_record(PLAN),
            },
        },
    }


def _write_artifact(path: Path, value: object) -> str:
    payload = _json_bytes(value)
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    path.with_suffix(path.suffix + ".sha256").write_text(f"{digest}  {path.name}\n")
    return digest


def register(result_dir: Path = RESULT_DIR, now: datetime | None = None) -> None:
    result_dir.mkdir(parents=True, exist_ok=True)
    registration_path = result_dir / "run-registration.json"
    if registration_path.exists():
        validate(result_dir)
        print(f"registration already valid: {registration_path}")
        return

    instant = (now or datetime.now(PACIFIC)).astimezone(PACIFIC).isoformat(timespec="seconds")
    sources = {
        "study_id": STUDY_ID,
        "sources": [
            {"role": "primary", **_file_record(PRIMARY_SOURCE)},
            {"role": "geometry_sensitivity_only", **_file_record(COMPARISON_SOURCE)},
        ],
    }
    masks_sha = _write_artifact(result_dir / "masks.json", build_masks(instant))
    _write_artifact(result_dir / "source-fingerprints.json", sources)
    registration = build_registration(instant, sources, masks_sha)
    registration["git_head_at_registration"] = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=WORKSPACE, capture_output=True, text=True, check=True
    ).stdout.strip()
    _write_artifact(registration_path, registration)
    validate(result_dir)
    print(f"registered {STUDY_ID}: {registration_path}")


def _load(path: Path) -> dict:
    with path.open("rb") as handle:
        return json.load(handle)


def _check_sidecar(path: Path) -> None:
    expected = path.with_suffix(path.suffix + ".sha256").read_text().split()[0]
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"fingerprint mismatch: {path}")


def validate(result_dir: Path = RESULT_DIR) -> None:
    paths = [
        result_dir / "masks.json",
        result_dir / "source-fingerprints.json",
        result_dir / "run-registration.json",
    ]
    for path in paths:
        _check_sidecar(path)

    masks, sources, registration = map(_load, paths)
    registered_at = registration["registered_at_pacific"]
    if masks != build_masks(registered_at):
        raise ValueError("masks.json does not match the registered mask")
    expected_registration = build_registration(registered_at, sources, sha256_file(paths[0]))
    registered_policy = {
        key: value for key, value in registration.items() if key != "git_head_at_registration"
    }
    if registered_policy != expected_registration:
        raise ValueError("run-registration.json does not match the frozen E1 policy")
    if len(PERMITTED_SYMBOLS) != 59 or "BRK.B" in PERMITTED_SYMBOLS:
        raise ValueError("registered universe is not the exact 59-name permitted set")
    if len(SETTINGS) != 16 or len(CELLS) != 126:
        raise ValueError("registered settings/cell counts are wrong")
    if registration["counts"] != {
        "development_blocks": 5,
        "permitted_symbols": 59,
        "settings": 16,
        "directional_horizon_cells": 126,
    }:
        raise ValueError("registration count summary is wrong")
    if registration["fingerprints"]["masks_sha256"] != sha256_file(paths[0]):
        raise ValueError("registration points to a different masks.json")
    for item in sources["sources"]:
        source_path = Path(item["path"])
        if source_path.stat().st_size != item["bytes"] or sha256_file(source_path) != item["sha256"]:
            raise ValueError(f"source changed after registration: {source_path}")
    code = registration["fingerprints"]["code_and_plan"]
    if code["registration_script"]["sha256"] != sha256_file(Path(__file__).resolve()):
        raise ValueError("registration code changed after registration")
    if code["execution_roadmap"]["sha256"] != sha256_file(PLAN):
        raise ValueError("execution roadmap changed after registration")
    print(
        "VALID: 59 symbols, 5 blocks, 16 settings, 126 cells; "
        "all masks and source fingerprints match"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("register", "validate"))
    parser.add_argument("--result-dir", type=Path, default=RESULT_DIR)
    args = parser.parse_args()
    if args.command == "register":
        register(args.result_dir)
    else:
        validate(args.result_dir)


if __name__ == "__main__":
    main()
