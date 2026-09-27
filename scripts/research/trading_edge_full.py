#!/usr/bin/env python3
"""Dense, bounded full-prefix runner for the registered E1 study.

Imported by ``trading_edge_e1.py full``.  All reads pass through the registered
guard.  Controls are stored as per-date sufficient statistics rather than as a
repeated opportunity ledger; count and sums reproduce the required date-first
means exactly.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import numpy as np
import pandas as pd

import trading_edge_registration as R
import trading_edge_analysis as A
import trading_edge_e1 as E1
import trading_edge_source_audit as S


SEED = 20260925
PACIFIC = ZoneInfo("America/Los_Angeles")
SOURCE_CLOCK = ZoneInfo("America/New_York")
OPEN_MINUTE = 570
MAX_MINUTES = 390
HORIZONS = (5, 15, 25, 30, 60)
SOURCE_MANIFEST = Path(
    "/home/openclaw/.openclaw/research-data/databento/opening-auctions/"
    "selected60_2023-01_to_2026-08/manifest.json"
)
SPLIT_DATES = {"APH": "2024-06-12", "ANET": "2024-12-04"}
DEGRADED_DATES = {"2025-03-24"}
BOOTSTRAP_CHECKPOINT_VERSION = 1


def _json_line(row: dict) -> bytes:
    return (json.dumps(
        row,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    ) + "\n").encode()


def _json_default(value: object) -> object:
    """Convert NumPy scalar values while rejecting all other unknown types."""
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


class JsonlSink:
    def __init__(self, path: Path):
        self.path = path
        self.tmp = path.with_suffix(path.suffix + ".tmp")
        self.handle = self.tmp.open("wb")
        self.digest = hashlib.sha256()
        self.count = 0

    def write(self, row: dict) -> None:
        payload = _json_line(row)
        self.handle.write(payload)
        self.digest.update(payload)
        self.count += 1

    def close(self) -> tuple[int, str]:
        self.handle.close()
        os.replace(self.tmp, self.path)
        value = self.digest.hexdigest()
        self.path.with_suffix(self.path.suffix + ".sha256").write_text(
            f"{value}  {self.path.name}\n"
        )
        return self.count, value


def _write_json(path: Path, value: object) -> str:
    payload = (json.dumps(
        value,
        indent=2,
        sort_keys=True,
        allow_nan=False,
        default=_json_default,
    ) + "\n").encode()
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    path.with_suffix(path.suffix + ".sha256").write_text(f"{digest}  {path.name}\n")
    return digest


def _write_csv(path: Path, rows: list[dict]) -> str:
    fields = list(rows[0]) if rows else ["rank", "cell_id"]
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)
    digest = R.sha256_file(path)
    path.with_suffix(path.suffix + ".sha256").write_text(f"{digest}  {path.name}\n")
    return digest


def _bootstrap_checkpoint_context(
    result_dir: Path, prefix: str, draws: int, upstream_hashes: dict[str, str]
) -> str:
    source_paths = (
        Path(__file__).resolve(),
        Path(A.__file__).resolve(),
        Path(E1.__file__).resolve(),
        Path(S.__file__).resolve(),
        Path(R.__file__).resolve(),
    )
    registration = result_dir / "run-registration.json"
    record = {
        "version": BOOTSTRAP_CHECKPOINT_VERSION,
        "prefix": prefix,
        "draws": draws,
        "sources": {str(path): R.sha256_file(path) for path in source_paths},
        "registration_sha256": R.sha256_file(registration),
        "upstream": dict(sorted(upstream_hashes.items())),
    }
    payload = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _load_bootstrap_checkpoint(
    path: Path, context_sha256: str, cell_id: str, seed: int, draws: int
) -> tuple[dict, dict, dict | None] | None:
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    required = {
        "version", "context_sha256", "cell_id", "seed", "draws",
        "plain_bootstrap", "score_bootstrap", "market_bootstrap",
    }
    if (
        not isinstance(record, dict)
        or set(record) != required
        or record.get("version") != BOOTSTRAP_CHECKPOINT_VERSION
        or record.get("context_sha256") != context_sha256
        or record.get("cell_id") != cell_id
        or record.get("seed") != seed
        or record.get("draws") != draws
        or not isinstance(record.get("plain_bootstrap"), dict)
        or not isinstance(record.get("score_bootstrap"), dict)
        or not isinstance(record.get("market_bootstrap"), (dict, type(None)))
    ):
        return None
    return (
        record["plain_bootstrap"], record["score_bootstrap"],
        record["market_bootstrap"],
    )


def _write_bootstrap_checkpoint(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = (json.dumps(
        record, sort_keys=True, separators=(",", ":"), allow_nan=False,
        default=_json_default,
    ) + "\n").encode()
    try:
        with tmp.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _cell_bootstraps(
    cell_id: str,
    analysis_events: list[dict],
    score_events: list[dict],
    analysis_controls: list[dict],
    draws: int,
    checkpoint_dir: Path,
    context_sha256: str,
) -> tuple[dict, dict, dict | None]:
    seed = SEED + int(hashlib.sha256(cell_id.encode()).hexdigest()[:8], 16)
    checkpoint_path = checkpoint_dir / f"{cell_id}.json"
    saved = _load_bootstrap_checkpoint(
        checkpoint_path, context_sha256, cell_id, seed, draws
    )
    if saved is not None:
        return saved
    plain = A.week_cluster_bootstrap(
        analysis_events, analysis_controls, draws=draws, seed=seed
    )
    score = A.week_cluster_bootstrap(
        score_events, analysis_controls, draws=draws, seed=seed
    )
    market = None
    if any("signed_loo_panel_return" in row for row in analysis_events):
        try:
            market = A.week_cluster_bootstrap(
                analysis_events, analysis_controls, metric="market_adjusted",
                draws=draws, seed=seed,
            )
        except ValueError:
            market = None
    _write_bootstrap_checkpoint(checkpoint_path, {
        "version": BOOTSTRAP_CHECKPOINT_VERSION,
        "context_sha256": context_sha256,
        "cell_id": cell_id,
        "seed": seed,
        "draws": draws,
        "plain_bootstrap": plain,
        "score_bootstrap": score,
        "market_bootstrap": market,
    })
    return plain, score, market


def _calendar(first: str, last: str) -> tuple[list[str], np.ndarray, np.ndarray]:
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range(first, last)
    schedule = calendar.schedule.loc[sessions, ["open", "close"]]
    labels, lengths, closes = [], [], []
    for session, row in schedule.iterrows():
        labels.append(session.date().isoformat())
        opened = row["open"].to_pydatetime().astimezone(SOURCE_CLOCK)
        closed = row["close"].to_pydatetime().astimezone(SOURCE_CLOCK)
        open_minute = opened.hour * 60 + opened.minute
        close_minute = closed.hour * 60 + closed.minute
        if open_minute != OPEN_MINUTE:
            raise RuntimeError("unexpected regular-session open in source clock")
        lengths.append(close_minute - open_minute)
        closes.append(close_minute)
    return labels, np.asarray(lengths, dtype=np.int16), np.asarray(closes, dtype=np.int16)


@dataclass
class DensePanel:
    symbols: tuple[str, ...]
    dates: list[str]
    lengths: np.ndarray
    closes: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    row_counts: np.ndarray | None = None
    unexpected_symbol_days: set[tuple[str, str]] | None = None
    excluded_days: np.ndarray | None = None
    reference_reset_days: np.ndarray | None = None

    @classmethod
    def load(cls, symbols: tuple[str, ...], dates: list[str], lengths, closes):
        shape = (len(symbols), len(dates), MAX_MINUTES)
        arrays = [np.full(shape, np.nan, dtype=np.float32) for _ in range(5)]
        row_counts = np.zeros(shape, dtype=np.uint8)
        symbol_code = {symbol: index for index, symbol in enumerate(symbols)}
        date_code = {day: index for index, day in enumerate(dates)}
        batches = R.guarded_parquet_batches(
            R.PRIMARY_SOURCE, symbols, dates[0], dates[-1],
            ["minute", "open", "high", "low", "close", "volume"],
        )
        seen = 0
        for batch in batches:
            frame = batch.to_pandas()
            si = frame["symbol"].map(symbol_code).to_numpy(dtype=np.int32)
            di = frame["date"].astype(str).map(date_code).to_numpy(dtype=np.int32)
            mi = frame["minute"].to_numpy(dtype=np.int32) - OPEN_MINUTE
            known = (si >= 0) & (di >= 0)
            regular = (mi >= 0) & (mi < MAX_MINUTES)
            valid = known & regular
            si, di, mi = si[valid], di[valid], mi[valid]
            np.add.at(row_counts, (si, di, mi), 1)
            for array, column in zip(arrays, ("open", "high", "low", "close", "volume")):
                array[si, di, mi] = frame.loc[valid, column].to_numpy(dtype=np.float32)
            seen += int(valid.sum())
        if seen == 0:
            raise RuntimeError("registered source returned no full-prefix rows")
        return cls(symbols, dates, lengths, closes, *arrays, row_counts, set())

    def session_type(self, day_index: int) -> str:
        return "regular" if int(self.lengths[day_index]) == 390 else "shortened"


def _rolling_rvol(panel: DensePanel, window: int) -> tuple[np.ndarray, np.ndarray]:
    volume = panel.v[:, :, :window]
    complete = np.isfinite(volume).all(axis=2)
    totals = np.where(complete, np.nansum(volume, axis=2), np.nan)
    values = np.full_like(totals, np.nan, dtype=np.float32)
    status = np.full(totals.shape, "reference_session_count_wrong", dtype=object)
    for day in range(20, len(panel.dates)):
        current_ok = complete[:, day]
        prior_ok = complete[:, day - 20 : day].all(axis=1)
        denominator = np.nanmean(totals[:, day - 20 : day], axis=1)
        usable = current_ok & prior_ok & (denominator > 0)
        values[usable, day] = totals[usable, day] / denominator[usable]
        status[current_ok & ~prior_ok, day] = "one_or_more_exact_prior_windows_missing"
        status[~current_ok, day] = "current_exact_window_missing"
        status[current_ok & prior_ok & ~(denominator > 0), day] = "nonpositive_prior_mean"
        status[usable, day] = "available"
    return values, status


def _apply_reference_masks(panel: DensePanel, values: np.ndarray, status: np.ndarray) -> None:
    date_index = {day: index for index, day in enumerate(panel.dates)}
    symbol_index = {symbol: index for index, symbol in enumerate(panel.symbols)}
    for day in DEGRADED_DATES:
        if day not in date_index:
            continue
        start = date_index[day]
        stop = min(len(panel.dates), start + 21)
        values[:, start:stop] = np.nan
        status[:, start:stop] = "degraded_reference_reset"
    for symbol, day in SPLIT_DATES.items():
        if symbol not in symbol_index or day not in date_index:
            continue
        si, start = symbol_index[symbol], date_index[day]
        stop = min(len(panel.dates), start + 21)
        values[si, start:stop] = np.nan
        status[si, start:stop] = "split_reference_reset"


def _pre_return_mask_reason(symbol: str, day: str) -> str | None:
    if day in DEGRADED_DATES:
        return "PRE_RETURN_MASK_SOURCE_DEGRADED_DATE"
    if SPLIT_DATES.get(symbol) == day:
        return "PRE_RETURN_MASK_SPLIT_SESSION"
    return None


def _panel_audit_rows(panel: DensePanel, si: int) -> pd.DataFrame:
    """Rebuild the retained source rows needed by the pre-return audit."""
    counts = panel.row_counts[si] if panel.row_counts is not None else np.where(
        np.isfinite(panel.o[si]) | np.isfinite(panel.c[si]), 1, 0
    )
    di, mi = np.nonzero(counts)
    repeats = counts[di, mi].astype(int)
    di = np.repeat(di, repeats)
    mi = np.repeat(mi, repeats)
    rows = pd.DataFrame({
        "symbol": panel.symbols[si],
        "date": np.asarray(panel.dates, dtype=object)[di],
        "minute": mi + OPEN_MINUTE,
        "open": panel.o[si, di, mi],
        "close": panel.c[si, di, mi],
    })
    return rows


def _audit_panel(panel: DensePanel) -> tuple[dict, dict[tuple[str, str], str], dict]:
    """Run the source audit before any strategy return is calculated."""
    schedule = S.schedule_from_lengths(panel.dates, panel.lengths, open_minute=OPEN_MINUTE)
    actions = pd.DataFrame([
        {
            "symbol": symbol, "date": day, "action_type": "split",
            "source": "registered E1 pre-return action schedule",
            "value": None, "adjustment_compatible": False,
        }
        for symbol, day in sorted(SPLIT_DATES.items()) if day in schedule
    ])
    governed_reasons = {
        "DUPLICATE_SCHEDULED_MINUTES",
        "UNEXPECTED_SESSION_MINUTES",
        "SUSPECTED_SPLIT_DISCONTINUITY",
        "UNPROVEN_ACTION_ADJUSTMENT",
    }
    all_days = []
    raw_row_count = 0
    rules = None
    for si, symbol in enumerate(panel.symbols):
        frame = _panel_audit_rows(panel, si)
        if frame.empty:
            raise RuntimeError(f"source audit cannot identify an entirely absent symbol: {symbol}")
        result = S.audit_source_rows(
            frame, schedule, actions.loc[actions["symbol"] == symbol] if not actions.empty else None
        )
        raw_row_count += int(result.mask_record["raw_row_count"])
        all_days.extend(result.mask_record["symbol_days"])
        rules = result.mask_record["rules"]
    all_days.sort(key=lambda row: (row["date"], row["symbol"]))
    governed = {}
    gap_map = {}
    for row in all_days:
        key = (row["symbol"], row["date"])
        reasons = sorted(governed_reasons.intersection(row["reasons"]))
        if row["date"] in DEGRADED_DATES:
            reasons.append("SOURCE_MANIFEST_DEGRADED_DATE")
        if reasons:
            governed[key] = "+".join(sorted(set(reasons)))
        gap_map[key] = {
            "overnight_gap_bps": row["overnight_gap_bps"],
            "overnight_gap_bucket": row["overnight_gap_bucket"],
            "reference_reset": row["reference_reset"],
        }
    record = {
        "audit_version": S.AUDIT_VERSION,
        "created_at_pacific": datetime.now(PACIFIC).isoformat(timespec="seconds"),
        "source_manifest": str(SOURCE_MANIFEST),
        "source_manifest_sha256": R.sha256_file(SOURCE_MANIFEST),
        "runner_sha256": R.sha256_file(Path(__file__).resolve()),
        "source_audit_module_sha256": R.sha256_file(Path(S.__file__).resolve()),
        "rules": rules,
        "raw_rows_preserved": True,
        "raw_row_count": raw_row_count,
        "symbol_day_count": len(all_days),
        "audit_excluded_symbol_day_count": sum(bool(row["exclude"]) for row in all_days),
        "governed_excluded_symbol_day_count": len(governed),
        "governed_mask_policy": {
            "global_exclusion_reasons": sorted(governed_reasons),
            "source_manifest_degraded_dates": sorted(DEGRADED_DATES),
            "missing_scheduled_minutes": (
                "recorded here but handled causally by each event, entry, path, and exit check; "
                "a later missing minute cannot exclude an earlier observable event"
            ),
            "extreme_overnight_gap": "tagged and bucketed; not excluded by itself",
        },
        "governed_symbol_days": [
            {"symbol": symbol, "date": day, "reason": governed[(symbol, day)]}
            for symbol, day in sorted(governed, key=lambda key: (key[1], key[0]))
        ],
        "symbol_days": all_days,
    }
    return record, governed, gap_map


def _apply_audit_reference_masks(
    panel: DensePanel, values: np.ndarray, status: np.ndarray, audit_record: dict
) -> None:
    date_index = {day: index for index, day in enumerate(panel.dates)}
    symbol_index = {symbol: index for index, symbol in enumerate(panel.symbols)}
    for row in audit_record["symbol_days"]:
        if not row["reference_reset"]:
            continue
        si = symbol_index[row["symbol"]]
        start = date_index[row["date"]]
        stop = min(len(panel.dates), start + 21)
        values[si, start:stop] = np.nan
        status[si, start:stop] = "source_audit_reference_reset"


def _install_governed_masks(
    panel: DensePanel,
    audit_record: dict,
    governed_days: dict[tuple[str, str], str],
) -> None:
    """Install the single mask used by signals, controls, and references."""
    shape = (len(panel.symbols), len(panel.dates))
    excluded = np.zeros(shape, dtype=bool)
    resets = np.zeros(shape, dtype=bool)
    symbol_index = {symbol: index for index, symbol in enumerate(panel.symbols)}
    date_index = {day: index for index, day in enumerate(panel.dates)}
    for symbol, day in governed_days:
        if symbol in symbol_index and day in date_index:
            excluded[symbol_index[symbol], date_index[day]] = True
    for row in audit_record["symbol_days"]:
        if row["reference_reset"]:
            resets[symbol_index[row["symbol"]], date_index[row["date"]]] = True
    for day in DEGRADED_DATES:
        if day not in date_index:
            continue
        excluded[:, date_index[day]] = True
        resets[:, date_index[day]] = True
    for symbol, day in SPLIT_DATES.items():
        if symbol in symbol_index and day in date_index:
            excluded[symbol_index[symbol], date_index[day]] = True
            resets[symbol_index[symbol], date_index[day]] = True
    panel.excluded_days = excluded
    panel.reference_reset_days = resets


def _day_is_excluded(panel: DensePanel, si: int, di: int) -> bool:
    return bool(panel.excluded_days is not None and panel.excluded_days[si, di])


def _reference_window_is_clean(panel: DensePanel, si: int, start: int, stop: int) -> bool:
    if start < 0:
        return False
    if panel.reference_reset_days is None:
        return True
    return not bool(panel.reference_reset_days[si, start:stop].any())


def _overnight_gap(panel: DensePanel, si: int, di: int) -> tuple[float | None, str]:
    if di == 0 or not _reference_window_is_clean(panel, si, di - 1, di):
        return None, "unavailable"
    previous = panel.c[si, di - 1, int(panel.lengths[di - 1]) - 1]
    opened = panel.o[si, di, 0]
    if not (np.isfinite(previous) and previous > 0 and np.isfinite(opened)):
        return None, "unavailable"
    value = float(opened / previous - 1.0)
    if value <= -0.01:
        bucket = "down_1pct_or_more"
    elif value < -0.0025:
        bucket = "down_0.25_to_1pct"
    elif value <= 0.0025:
        bucket = "within_0.25pct"
    elif value < 0.01:
        bucket = "up_0.25_to_1pct"
    else:
        bucket = "up_1pct_or_more"
    return value, bucket


def _first_pullback_dense(panel: DensePanel, si: int, di: int, setting: dict, direction: str):
    if di < 15:
        return None, "FIRST_PULLBACK_REQUIRED_HISTORY_UNAVAILABLE", {}
    length = int(panel.lengths[di])
    if length < 45:
        return None, "FIRST_PULLBACK_REQUIRED_HISTORY_UNAVAILABLE", {}
    # DAILY_ATR_14 needs exactly 15 complete preceding sessions.
    if not _reference_window_is_clean(panel, si, di - 15, di):
        return None, "FIRST_PULLBACK_REQUIRED_HISTORY_UNAVAILABLE", {}
    daily = []
    for prior in range(di - 15, di):
        n = int(panel.lengths[prior])
        h, l, c = panel.h[si, prior, :n], panel.l[si, prior, :n], panel.c[si, prior, :n]
        if not (np.isfinite(h).all() and np.isfinite(l).all() and np.isfinite(c).all()):
            return None, "FIRST_PULLBACK_REQUIRED_HISTORY_UNAVAILABLE", {}
        daily.append((float(np.max(h)), float(np.min(l)), float(c[n - 1])))
    daily_ranges = [max(daily[index][0] - daily[index][1],
                        abs(daily[index][0] - daily[index - 1][2]),
                        abs(daily[index][1] - daily[index - 1][2]))
                    for index in range(1, 15)]
    daily_atr = float(np.mean(daily_ranges))
    # ATR_1M20 uses the prior session tail at the open and excludes its gap.
    prior_n = int(panel.lengths[di - 1])
    prior_h = panel.h[si, di - 1, :prior_n]
    prior_l = panel.l[si, di - 1, :prior_n]
    prior_c = panel.c[si, di - 1, :prior_n]
    current_h = panel.h[si, di, :45]
    current_l = panel.l[si, di, :45]
    current_c = panel.c[si, di, :45]
    current_o = panel.o[si, di, :45]
    current_v = panel.v[si, di, :45]
    if not all(np.isfinite(array).all() for array in (
        prior_h[-20:], prior_l[-20:], prior_c[-20:], current_h, current_l,
        current_c, current_o, current_v,
    )):
        return None, "FIRST_PULLBACK_REQUIRED_HISTORY_UNAVAILABLE", {}
    prior_tr = []
    for pos in range(prior_n - 20, prior_n):
        previous = prior_c[pos - 1] if pos > 0 else np.nan
        prior_tr.append(float(prior_h[pos] - prior_l[pos]) if not np.isfinite(previous)
                        else float(max(prior_h[pos] - prior_l[pos],
                                       abs(prior_h[pos] - previous),
                                       abs(prior_l[pos] - previous))))
    current_tr = []
    atr = {}
    for pos in range(45):
        previous = current_c[pos - 1] if pos > 0 else np.nan
        tr = float(current_h[pos] - current_l[pos]) if pos == 0 else float(max(
            current_h[pos] - current_l[pos], abs(current_h[pos] - previous),
            abs(current_l[pos] - previous)))
        current_tr.append(tr)
        atr[OPEN_MINUTE + pos] = float(np.mean((prior_tr + current_tr)[-20:]))
    frame = pd.DataFrame({
        "minute": np.arange(OPEN_MINUTE, OPEN_MINUTE + 45),
        "open": current_o, "high": current_h, "low": current_l,
        "close": current_c, "volume": current_v,
    }).set_index("minute")
    vwap_values = _vwap(current_h, current_l, current_c, current_v, 45)
    vwap = {OPEN_MINUTE + pos: float(value) if np.isfinite(value) else None
            for pos, value in enumerate(vwap_values)}
    minute, reason, details = E1._first_pullback_event(
        setting, direction, frame, list(range(OPEN_MINUTE, OPEN_MINUTE + length)),
        atr, daily_atr, vwap,
    )
    return ((minute - OPEN_MINUTE) if minute is not None else None), reason, details


def _vwap(h, l, c, v, length: int) -> np.ndarray:
    valid = np.isfinite(h[:length]) & np.isfinite(l[:length]) & np.isfinite(c[:length]) & np.isfinite(v[:length])
    prefix_valid = np.logical_and.accumulate(valid)
    typical = (h[:length] + l[:length] + c[:length]) / 3.0
    weighted = np.cumsum(np.where(valid, typical * v[:length], 0.0))
    volume = np.cumsum(np.where(valid, v[:length], 0.0))
    out = np.full(length, np.nan, dtype=np.float64)
    good = prefix_valid & (volume > 0)
    out[good] = weighted[good] / volume[good]
    return out


def _cross(previous: float, current: float, boundary: float, direction: str) -> bool:
    return previous <= boundary < current if direction == "long" else previous >= boundary > current


def _scan_day(panel: DensePanel, si: int, di: int, rvol5: float, rvol15: float):
    if _day_is_excluded(panel, si, di):
        return {}, {
            (setting["id"], direction): "PRE_RETURN_MASK_GOVERNED_DAY"
            for setting in R.SETTINGS for direction in ("long", "short")
        }
    length = int(panel.lengths[di])
    o, h, l, c, v = (array[si, di, :length].astype(float, copy=False)
                      for array in (panel.o, panel.h, panel.l, panel.c, panel.v))
    vwap = _vwap(h, l, c, v, length)
    results, reasons = {}, {}
    last_signal = min(length, 300)
    for setting in R.SETTINGS:
        sid, family = setting["id"], setting["family"]
        if family == "first_pullback":
            for direction in ("long", "short"):
                minute, reason, _details = _first_pullback_dense(
                    panel, si, di, setting, direction
                )
                if minute is None:
                    reasons[(sid, direction)] = reason
                else:
                    results[(sid, direction)] = minute
            continue
        if family == "late_continuation":
            previous_close = (
                panel.c[si, di - 1, int(panel.lengths[di - 1]) - 1]
                if di > 0 and _reference_window_is_clean(panel, si, di - 1, di)
                else np.nan
            )
            if not (np.isfinite(previous_close) and np.isfinite(c[:30]).all()):
                for direction in ("long", "short"):
                    reasons[(sid, direction)] = "LATE_DIRECTION_REFERENCE_UNAVAILABLE"
            else:
                actual = "long" if c[29] > previous_close else "short" if c[29] < previous_close else None
                for direction in ("long", "short"):
                    if direction == actual:
                        results[(sid, direction)] = length - 31
                    else:
                        reasons[(sid, direction)] = "LATE_DIRECTION_NOT_SELECTED"
            continue
        if family == "opening_range":
            size = int(setting["opening_minutes"])
            if not (np.isfinite(h[:size]).all() and np.isfinite(l[:size]).all() and np.isfinite(c[:size]).all()):
                for direction in ("long", "short"):
                    reasons[(sid, direction)] = "OPENING_RANGE_UNAVAILABLE"
                continue
            selected_rvol = rvol5 if size == 5 else rvol15
            gate = setting["opening_volume_gate"]
            if gate is not None and (not np.isfinite(selected_rvol) or selected_rvol < gate):
                reason = "OPENING_VOLUME_GATE_UNAVAILABLE" if not np.isfinite(selected_rvol) else "OPENING_VOLUME_GATE_FAILED"
                for direction in ("long", "short"):
                    reasons[(sid, direction)] = reason
                continue
            boundaries = {"long": float(np.max(h[:size])), "short": float(np.min(l[:size]))}
            for direction in ("long", "short"):
                found = None
                for pos in range(size, last_signal):
                    if not (np.isfinite(c[pos - 1]) and np.isfinite(c[pos])):
                        reasons[(sid, direction)] = "MISSING_BAR_BEFORE_FIRST_EVENT"
                        break
                    if _cross(c[pos - 1], c[pos], boundaries[direction], direction):
                        found = pos
                        break
                if found is None:
                    reasons.setdefault((sid, direction), "NO_FIRST_COMPLETED_CLOSE_CROSS")
                else:
                    results[(sid, direction)] = found
            continue
        if family == "failed_opening_range":
            if not (np.isfinite(h[:15]).all() and np.isfinite(l[:15]).all() and np.isfinite(c[:15]).all()):
                for direction in ("long", "short"):
                    reasons[(sid, direction)] = "OPENING_RANGE_UNAVAILABLE"
                continue
            high, low = float(np.max(h[:15])), float(np.min(l[:15]))
            for direction in ("long", "short"):
                outside, found = False, None
                for pos in range(15, last_signal):
                    if not np.isfinite(c[pos]):
                        reasons[(sid, direction)] = "MISSING_BAR_BEFORE_FIRST_EVENT"
                        break
                    if direction == "long":
                        if c[pos] < low:
                            outside = True
                        elif outside and c[pos] > low:
                            found = pos; break
                    else:
                        if c[pos] > high:
                            outside = True
                        elif outside and c[pos] < high:
                            found = pos; break
                if found is None:
                    reasons.setdefault((sid, direction), "NO_FAILED_OPENING_RANGE_RETURN")
                else:
                    results[(sid, direction)] = found
            continue
        if family == "high_low_breakout":
            if not np.isfinite(rvol5) or rvol5 < 1.5:
                reason = "OPENING5_RVOL_UNAVAILABLE" if not np.isfinite(rvol5) else "OPENING5_RVOL_FAILED"
                for direction in ("long", "short"):
                    reasons[(sid, direction)] = reason
                continue
            for direction in ("long", "short"):
                found = None
                for pos in range(15, last_signal):
                    prior = slice(0, pos)
                    if not (np.isfinite(h[prior]).all() and np.isfinite(l[prior]).all()
                            and np.isfinite(c[pos]) and np.isfinite(vwap[pos])):
                        continue
                    if setting["compression"]:
                        r3 = float(np.max(h[pos-3:pos]) - np.min(l[pos-3:pos]))
                        r7 = float(np.max(h[pos-7:pos]) - np.min(l[pos-7:pos]))
                        if r7 <= 0 or r3 / r7 > 0.60:
                            continue
                    crossed = c[pos] > np.max(h[prior]) and c[pos] > vwap[pos] if direction == "long" else c[pos] < np.min(l[prior]) and c[pos] < vwap[pos]
                    if crossed:
                        found = pos; break
                if found is None:
                    reasons[(sid, direction)] = "NO_FIRST_HIGH_LOW_BREAKOUT"
                else:
                    results[(sid, direction)] = found
            continue
        raise RuntimeError(f"unimplemented registered family: {family}")
    return results, reasons


def _pacific(day: str, minute: int) -> str:
    hour, value = divmod(minute, 60)
    instant = datetime.combine(date.fromisoformat(day), datetime.min.time()).replace(
        hour=hour, minute=value, tzinfo=SOURCE_CLOCK
    )
    return instant.astimezone(PACIFIC).isoformat(timespec="minutes")


def _block(day: str) -> str:
    for block_id, first, last in R.BLOCKS:
        if first <= day <= last:
            return block_id
    raise ValueError(day)


def _setting_map():
    return {setting["id"]: setting for setting in R.SETTINGS}


def _event_and_responses(panel, si, di, sid, direction, signal_pos, audit_gap=None):
    setting = _setting_map()[sid]
    symbol, day = panel.symbols[si], panel.dates[di]
    family = setting["family"]
    event_id = f"{sid}__{symbol}__{day}__{direction.upper()}"
    event = {
        "id": event_id, "setting_id": sid, "family": family, "symbol": symbol,
        "date": day, "block": _block(day), "direction": direction,
        "signal_minute": OPEN_MINUTE + signal_pos,
        "signal_completed_time_pacific": _pacific(day, OPEN_MINUTE + signal_pos + 1),
        "session_type": panel.session_type(di),
    }
    sign = 1 if direction == "long" else -1
    length = int(panel.lengths[di])
    gap_return, gap_bucket = _overnight_gap(panel, si, di)
    event["overnight_gap_return"] = gap_return
    event["overnight_gap_bucket"] = gap_bucket
    if audit_gap is not None:
        event["audit_overnight_gap_bps"] = audit_gap["overnight_gap_bps"]
        event["audit_overnight_gap_bucket"] = audit_gap["overnight_gap_bucket"]
    responses, censors = [], []
    for reference, delay in (("next_minute", 1), ("one_extra_minute", 2)):
        entry = signal_pos + delay
        if entry >= length or not np.isfinite(panel.o[si, di, entry]):
            censors.append({"id": f"{event_id}__{reference}__ENTRY", "kind": "outcome",
                            "event_id": event_id, "reason": "MISSING_REFERENCE_ENTRY_MINUTE"})
            continue
        entry_price = float(panel.o[si, di, entry])
        for horizon in setting["horizons_minutes"]:
            exit_pos = signal_pos + horizon
            rid = f"{event_id}__{reference}__H{horizon}"
            if exit_pos > length - 6 or not np.isfinite(panel.c[si, di, exit_pos]):
                censors.append({"id": rid, "kind": "outcome", "event_id": event_id,
                                "reason": "MISSING_OR_LATER_THAN_CLOSE_MINUS_FIVE"})
                continue
            path = slice(entry, exit_pos + 1)
            if not (np.isfinite(panel.h[si, di, path]).all() and np.isfinite(panel.l[si, di, path]).all()):
                censors.append({"id": rid, "kind": "outcome", "event_id": event_id,
                                "reason": "MISSING_PATH_INTERVAL"})
                continue
            exit_price = float(panel.c[si, di, exit_pos])
            gross = sign * (exit_price / entry_price - 1.0)
            floor = A.registered_cost_floor_bps(
                OPEN_MINUTE + entry, OPEN_MINUTE + exit_pos, OPEN_MINUTE
            )
            elapsed = exit_pos - entry + 1
            clock = f"TTC{length-entry}" if family == "late_continuation" else f"BIN{entry//15:02d}"
            group = "|".join((symbol, event["block"], str(elapsed), event["session_type"], clock))
            exact_group = "|".join((
                symbol, event["block"], str(elapsed), event["session_type"], f"MIN{entry:03d}"
            ))
            responses.append({
                "id": rid, "event_id": event_id, "cell_id": f"{sid}__{direction.upper()}__H{horizon}",
                "setting_id": sid, "family": family, "symbol": symbol, "date": day,
                "block": event["block"], "direction": direction, "reference": reference,
                "nominal_horizon_minutes": horizon, "elapsed_minutes": elapsed,
                "entry_col": entry, "exit_col": exit_pos, "entry_price": entry_price,
                "exit_price": exit_price, "signed_return": gross,
                "cost_floor_bps": floor, "raw_net_floor": gross - floor / 10000.0,
                "raw_net_20bps": gross - 0.002, "raw_net_twice_floor": gross - 2 * floor / 10000.0,
                "favorable_excursion": ((float(np.max(panel.h[si, di, path])) / entry_price - 1) if sign > 0 else (1 - float(np.min(panel.l[si, di, path])) / entry_price)),
                "adverse_excursion": ((float(np.min(panel.l[si, di, path])) / entry_price - 1) if sign > 0 else (1 - float(np.max(panel.h[si, di, path])) / entry_price)),
                "control_group_id": group,
                "exact_control_group_id": exact_group,
                "overnight_gap_return": gap_return,
                "overnight_gap_bucket": gap_bucket,
                "audit_overnight_gap_bps": (
                    audit_gap["overnight_gap_bps"] if audit_gap is not None else None
                ),
                "audit_overnight_gap_bucket": (
                    audit_gap["overnight_gap_bucket"] if audit_gap is not None else "UNAVAILABLE"
                ),
            })
    return event, responses, censors


def _market_loo(panel: DensePanel, horizons: set[int]) -> dict[int, np.ndarray]:
    presence = np.isfinite(panel.c).any(axis=2)
    eligible = np.zeros_like(presence)
    eligible[:, 1:] = presence[:, :-1]
    if panel.excluded_days is not None:
        eligible &= ~panel.excluded_days
    out = {}
    for horizon in sorted(horizons):
        width = MAX_MINUTES - horizon + 1
        entry = panel.o[:, :, :width].astype(np.float64)
        exit_price = panel.c[:, :, horizon - 1 :].astype(np.float64)
        returns = exit_price / entry - 1.0
        eligible3 = eligible[:, :, None]
        missing = eligible3 & ~np.isfinite(returns)
        complete = ~missing.any(axis=0)
        total = np.where(eligible3, returns, 0.0).sum(axis=0)
        count = eligible.sum(axis=0).astype(np.float64)
        values = np.full(returns.shape, np.nan, dtype=np.float32)
        for si in range(len(panel.symbols)):
            own = eligible[si, :, None]
            denominator = count[:, None] - own
            numerator = total - np.where(own, returns[si], 0.0)
            good = complete & own & (denominator > 0) & np.isfinite(returns[si])
            values[si][good] = (numerator[good] / np.broadcast_to(denominator, numerator.shape)[good]).astype(np.float32)
        out[horizon] = values
    return out


def _control_daily(panel: DensePanel, responses: list[dict], loo, sink: JsonlSink):
    requested = sorted({value for row in responses
                        for value in (row.get("control_group_id"),
                                      row.get("exact_control_group_id")) if value})
    symbol_index = {symbol: index for index, symbol in enumerate(panel.symbols)}
    stats = {}
    daily_by_group = {}
    for group in requested:
        symbol, block, elapsed_text, session_type, clock = group.split("|")
        si, elapsed = symbol_index[symbol], int(elapsed_text)
        daily = []
        for di, day in enumerate(panel.dates):
            if _block(day) != block or panel.session_type(di) != session_type:
                continue
            if _day_is_excluded(panel, si, di):
                continue
            length = int(panel.lengths[di])
            if clock.startswith("TTC"):
                entries = [length - int(clock[3:])]
            elif clock.startswith("MIN"):
                entries = [int(clock[3:])]
            else:
                start = int(clock[3:]) * 15
                entries = list(range(start, min(start + 15, length)))
            gross, residual, costs = [], [], []
            for entry in entries:
                exit_pos = entry + elapsed - 1
                if exit_pos > length - 6:
                    continue
                a, b = panel.o[si, di, entry], panel.c[si, di, exit_pos]
                if not (np.isfinite(a) and np.isfinite(b)):
                    continue
                value = float(b / a - 1.0)
                gross.append(value)
                market = loo[elapsed][si, di, entry]
                if np.isfinite(market):
                    residual.append(value - float(market))
                costs.append(8 if entry < 60 or exit_pos < 60 else 5)
            if not gross:
                continue
            row = {
                "id": f"{group}|{day}", "control_group_id": group, "symbol": symbol,
                "date": day, "block": block, "elapsed_minutes": elapsed,
                "session_type": session_type, "clock_match": clock,
                "opportunity_count": len(gross), "sum_raw_return": float(sum(gross)),
                "market_residual_count": len(residual),
                "sum_market_residual": float(sum(residual)),
                "sum_cost_floor_bps": int(sum(costs)),
                "daily_first_rule": "divide sums by counts, then weight dates equally",
            }
            # Exact-minute groups are a sensitivity check.  Their resolved mean
            # is attached to each response, while the persisted ledger stays at
            # the registered bin/time-to-close level to remain bounded.
            if not clock.startswith("MIN"):
                sink.write(row)
            daily.append(row)
        if daily:
            daily_by_group[group] = [(
                row["date"],
                row["sum_raw_return"] / row["opportunity_count"],
                (row["sum_market_residual"] / row["market_residual_count"]
                 if row["market_residual_count"] else None),
            ) for row in daily]
            stats[group] = {
                "raw": float(np.mean([r["sum_raw_return"] / r["opportunity_count"] for r in daily])),
                "cost_bps": float(np.mean([r["sum_cost_floor_bps"] / r["opportunity_count"] for r in daily])),
                "market": (float(np.mean([r["sum_market_residual"] / r["market_residual_count"]
                                          for r in daily if r["market_residual_count"]]))
                           if any(r["market_residual_count"] for r in daily) else None),
                "dates": len(daily),
            }
    return stats, daily_by_group


def _week(day: str) -> str:
    parsed = date.fromisoformat(day)
    monday = parsed.fromordinal(parsed.toordinal() - parsed.weekday())
    return monday.isoformat()


def _bootstrap_lower(values_by_week: dict[str, list[float]], seed: int) -> tuple[float | None, list[float]]:
    weeks = sorted(values_by_week)
    if len(weeks) < 2:
        return None, []
    rng = np.random.default_rng(seed)
    samples = []
    for _ in range(1000):
        chosen = rng.choice(weeks, size=len(weeks), replace=True)
        values = [value for week in chosen for value in values_by_week[week]]
        samples.append(float(np.mean(values)))
    return float(np.quantile(samples, 0.20)), samples


def _neighbor_ids(setting: dict) -> list[str]:
    family = setting["family"]
    if family == "opening_range":
        peers = [item for item in R.SETTINGS if item["family"] == family and item["opening_minutes"] == setting["opening_minutes"]]
        order = [item["id"] for item in peers]
        pos = order.index(setting["id"])
        return [order[index] for index in (pos - 1, pos + 1) if 0 <= index < len(order)]
    if family == "high_low_breakout":
        return [item["id"] for item in R.SETTINGS if item["family"] == family and item["id"] != setting["id"]]
    if family == "first_pullback":
        return [
            item["id"] for item in R.SETTINGS
            if item["family"] == family
            and item["id"] != setting["id"]
            and ((item["session_vwap_support"] != setting["session_vwap_support"])
                 + (item["impulse_anchored_vwap_support"]
                    != setting["impulse_anchored_vwap_support"]) == 1)
        ]
    return []


def _summaries(
    responses, control_stats, control_daily, loo, panel, sink, daily_sink, power_rows,
    bootstrap_draws: int, checkpoint_dir: Path, checkpoint_context: str,
):
    by_cell = defaultdict(list)
    symbol_index = {symbol: index for index, symbol in enumerate(panel.symbols)}
    date_index = {day: index for index, day in enumerate(panel.dates)}
    for row in responses:
        control = control_stats.get(row["control_group_id"])
        if control is None:
            continue
        sign = 1 if row["direction"] == "long" else -1
        row["control_gross_mean"] = sign * control["raw"]
        row["plain_gross_excess"] = row["signed_return"] - row["control_gross_mean"]
        exact_control = control_stats.get(row["exact_control_group_id"])
        row["exact_minute_control_gross_mean"] = (
            sign * exact_control["raw"] if exact_control is not None else None
        )
        row["exact_minute_plain_gross_excess"] = (
            row["signed_return"] - row["exact_minute_control_gross_mean"]
            if row["exact_minute_control_gross_mean"] is not None else None
        )
        control_net = sign * control["raw"] - control["cost_bps"] / 10000.0
        row["net_excess_floor"] = row["raw_net_floor"] - control_net
        row["net_excess_20bps"] = row["raw_net_20bps"] - (sign * control["raw"] - 0.002)
        row["net_excess_twice_floor"] = row["raw_net_twice_floor"] - (
            sign * control["raw"] - 2 * control["cost_bps"] / 10000.0
        )
        market = loo[row["elapsed_minutes"]][
            symbol_index[row["symbol"]], date_index[row["date"]], row["entry_col"]
        ]
        row["market_adjusted_excess"] = None
        if np.isfinite(market) and control["market"] is not None:
            row["signed_loo_panel_return"] = sign * float(market)
            row["market_adjusted_excess"] = sign * (row["signed_return"] / sign - float(market)) - sign * control["market"]
        if row["reference"] != "next_minute":
            continue
        by_cell[row["cell_id"]].append(row)
    summaries = {}
    for cell in R.CELLS:
        cid = cell["id"]
        rows = by_cell.get(cid, [])
        if not rows:
            summary = {"id": cid, "cell_id": cid, "event_count": 0,
                       "p_value": 1.0, "status": "unavailable_or_no_events"}
            summaries[cid] = summary; continue
        excess = np.asarray([row["plain_gross_excess"] for row in rows])
        raw = np.asarray([row["signed_return"] for row in rows])
        floors = np.asarray([row["cost_floor_bps"] / 10000 for row in rows])
        blocks = {block: [row["plain_gross_excess"] for row in rows if row["block"] == block]
                  for block, _, _ in R.BLOCKS}
        sign = 1 if cell["direction"] == "long" else -1
        analysis_events = []
        score_events = []
        analysis_controls = []
        for row in rows:
            base = {
                "cell_id": cid, "setting_id": cell["setting_id"], "family": cell["family"],
                "symbol": row["symbol"], "date": row["date"], "block": row["block"],
                "direction": row["direction"], "horizon_minutes": row["nominal_horizon_minutes"],
                "control_key": row["control_group_id"], "signed_return": row["signed_return"],
            }
            if "signed_loo_panel_return" in row:
                base["signed_loo_panel_return"] = row["signed_loo_panel_return"]
            analysis_events.append(base)
            score = dict(base)
            score["signed_return"] -= row["cost_floor_bps"] / 10000.0
            score_events.append(score)
        for group in sorted({row["control_group_id"] for row in rows}):
            for day, raw_mean, residual_mean in control_daily.get(group, []):
                control = {"control_key": group, "date": day, "signed_return": sign * raw_mean}
                if residual_mean is not None:
                    control["residual_return"] = sign * residual_mean
                analysis_controls.append(control)
        plain_bootstrap, score_bootstrap, market_bootstrap = _cell_bootstraps(
            cid, analysis_events, score_events, analysis_controls,
            bootstrap_draws, checkpoint_dir, checkpoint_context,
        )
        concentration = A.remove_top_three_positive_symbol_days(rows, "plain_gross_excess")
        top = [(item["symbol"], item["date"]) for item in concentration["removed_symbol_days"]]
        market_values = [row["market_adjusted_excess"] for row in rows if row["market_adjusted_excess"] is not None]
        date_plain = defaultdict(list)
        date_market = defaultdict(list)
        for row in rows:
            date_plain[row["date"]].append(row["plain_gross_excess"])
            if row["market_adjusted_excess"] is not None:
                date_market[row["date"]].append(row["market_adjusted_excess"])
        daily_plain = [{"date": day, "value": float(np.mean(values))}
                       for day, values in sorted(date_plain.items())]
        daily_market = [{"date": day, "value": float(np.mean(values))}
                        for day, values in sorted(date_market.items())]
        daily_values = np.asarray([row["value"] for row in daily_plain])
        if len(daily_values) >= 2 and np.std(daily_values, ddof=1) > 0:
            z_value = float(np.mean(daily_values) / (np.std(daily_values, ddof=1) / math.sqrt(len(daily_values))))
            p_value = float(1.0 - A.NormalDist().cdf(z_value)) if hasattr(A, "NormalDist") else float(0.5 * math.erfc(z_value / math.sqrt(2)))
        else:
            p_value = 1.0
        raw_by_date = defaultdict(list)
        values_by_date_symbol = defaultdict(list)
        for row in rows:
            raw_by_date[row["date"]].append(row["signed_return"])
            values_by_date_symbol[(row["date"], row["symbol"])].append(row["plain_gross_excess"])
        for day in sorted(date_plain):
            market_day = date_market.get(day, [])
            daily_sink.write({
                "id": f"{cid}|{day}", "cell_id": cid, "date": day,
                "week": _week(day), "block": _block(day),
                "event_count": len(date_plain[day]),
                "mean_raw_signed_return": float(np.mean(raw_by_date[day])),
                "mean_plain_gross_excess": float(np.mean(date_plain[day])),
                "mean_market_adjusted_excess": (
                    float(np.mean(market_day)) if market_day else None
                ),
            })
        weekly = defaultdict(list)
        for item in daily_plain:
            weekly[_week(item["date"])].append(item["value"])
        weekly_means = [float(np.mean(values)) for values in weekly.values()]
        symbols = sorted({row["symbol"] for row in rows})
        pairwise = []
        for left_index, left in enumerate(symbols):
            for right in symbols[left_index + 1:]:
                pairs = []
                for day in sorted(date_plain):
                    a = values_by_date_symbol.get((day, left))
                    b = values_by_date_symbol.get((day, right))
                    if a and b:
                        pairs.append((float(np.mean(a)), float(np.mean(b))))
                if len(pairs) >= 3:
                    x, y = np.asarray(pairs).T
                    if np.std(x) > 0 and np.std(y) > 0:
                        pairwise.append(float(np.corrcoef(x, y)[0, 1]))
        summary = {
            "id": cid, "cell_id": cid, "setting_id": cell["setting_id"], "family": cell["family"],
            "direction": cell["direction"], "horizon_minutes": cell["horizon_minutes"],
            "is_primary_horizon": cell["is_primary_horizon"], "event_count": len(rows),
            "distinct_dates": len({row["date"] for row in rows}),
            "distinct_symbols": len({row["symbol"] for row in rows}),
            "mean_raw_signed_return": float(raw.mean()),
            "mean_plain_gross_excess": float(excess.mean()),
            "mean_exact_minute_plain_gross_excess": (
                float(np.mean([row["exact_minute_plain_gross_excess"] for row in rows
                               if row["exact_minute_plain_gross_excess"] is not None]))
                if any(row["exact_minute_plain_gross_excess"] is not None for row in rows)
                else None
            ),
            "mean_raw_net_floor": float(np.mean([row["raw_net_floor"] for row in rows])),
            "mean_net_excess_floor": float(np.mean([row["net_excess_floor"] for row in rows])),
            "mean_net_excess_20bps": float(np.mean([row["net_excess_20bps"] for row in rows])),
            "mean_net_excess_twice_floor": float(np.mean([row["net_excess_twice_floor"] for row in rows])),
            "mean_market_adjusted_excess": float(np.mean(market_values)) if market_values else None,
            "market_adjusted_count": len(market_values),
            "block_mean_excess": {block: (float(np.mean(values)) if values else None) for block, values in blocks.items()},
            "positive_blocks": int(sum(bool(values) and np.mean(values) > 0 for values in blocks.values())),
            "top_three_symbol_days_removed": [f"{symbol}|{day}" for symbol, day in top],
            "mean_excess_after_top_three_removal": concentration["remaining_mean"],
            "plain_excess_80pct_week_bootstrap_lower": plain_bootstrap["lower_80"],
            "selection_score_80pct_week_bootstrap_lower": score_bootstrap["lower_80"],
            "market_adjusted_80pct_week_bootstrap_lower": (
                market_bootstrap["lower_80"] if market_bootstrap else None
            ),
            "bootstrap_draws": bootstrap_draws,
            "week_count": len(weekly_means),
            "weekly_mean_standard_deviation": (
                float(np.std(weekly_means, ddof=1)) if len(weekly_means) >= 2 else None
            ),
            "positive_week_count": int(sum(value > 0 for value in weekly_means)),
            "same_day_pairwise_symbol_correlation": (
                float(np.mean(pairwise)) if pairwise else None
            ),
            "same_day_pair_count": len(pairwise),
            "mean_event_cost_floor_bps": float(floors.mean() * 10000),
            "p_value": p_value,
            "status": "measured",
        }
        for metric, daily_rows in (("plain", daily_plain), ("market_adjusted", daily_market)):
            for item in A.power_day_week_estimates(daily_rows, "value"):
                power_rows.append({"id": f"{cid}|{metric}|{item['effect_bps']}",
                                   "cell_id": cid, "metric": metric, **item})
        summaries[cid] = summary
    adjusted = A.benjamini_hochberg_qvalues(
        [summaries[cell["id"]] for cell in R.CELLS]
    )
    for row in adjusted:
        summaries[row["cell_id"]] = row
        sink.write(row)
    return summaries


def _effective_variants(events: list[dict]) -> dict:
    rows = []
    attempted = []
    for setting in R.SETTINGS:
        for direction in ("long", "short"):
            attempted.append(f"{setting['id']}__{direction.upper()}")
    for event in events:
        item = dict(event)
        item["attempted_label"] = f"{event['setting_id']}__{event['direction'].upper()}"
        rows.append(item)
    analyzed = A.effective_variant_groups(
        rows, setting_field="attempted_label", attempted_settings=attempted
    )
    mapping = {}
    output = []
    for group in analyzed:
        group_id = group["decision_group"]
        labels = group["attempted_setting_ids"]
        output.append({
            "group_id": group_id,
            "decision_count": group["decision_count"],
            "attempted_labels": labels,
        })
        for label in labels:
            mapping[label] = group_id
    return {"groups": output, "label_to_group": mapping}


def _rank(summaries, effective):
    setting_by_id = _setting_map()
    candidates = []
    for cid, row in summaries.items():
        if not row.get("is_primary_horizon") or row.get("status") != "measured":
            continue
        setting = setting_by_id[row["setting_id"]]
        neighbors = _neighbor_ids(setting)
        neighbor_agrees = True if not neighbors else any(
            summaries.get(f"{neighbor}__{row['direction'].upper()}__H{row['horizon_minutes']}", {}).get("mean_plain_gross_excess", -math.inf) > 0
            for neighbor in neighbors
        )
        incremental = True
        if setting["family"] == "opening_range" and setting["opening_volume_gate"] is not None:
            off = f"OR{setting['opening_minutes']}_VOL_OFF__{row['direction'].upper()}__H{row['horizon_minutes']}"
            incremental = row["mean_plain_gross_excess"] > summaries.get(off, {}).get("mean_plain_gross_excess", math.inf)
        eligible = (
            row["mean_plain_gross_excess"] > 0
            and row["mean_raw_net_floor"] > 0
            and row["positive_blocks"] >= 3
            and (row["mean_excess_after_top_three_removal"] or -math.inf) > 0
            and neighbor_agrees and incremental
        )
        label = f"{row['setting_id']}__{row['direction'].upper()}"
        candidates.append({
            "cell_id": cid, "setting_id": row["setting_id"], "family": row["family"],
            "direction": row["direction"], "horizon_minutes": row["horizon_minutes"],
            "effective_group": effective["label_to_group"][label],
            "selection_score": row["selection_score_80pct_week_bootstrap_lower"],
            "eligible": eligible, "neighbor_agrees": neighbor_agrees,
            "volume_variant_improves_off": incremental,
        })
    candidates.sort(key=lambda row: (
        not row["eligible"],
        -(row["selection_score"] if row["selection_score"] is not None else -math.inf),
        row["setting_id"], row["direction"],
    ))
    analysis_candidates = [dict(
        row,
        decision_group=row["effective_group"],
        selection_lower_80=(row["selection_score"] if row["selection_score"] is not None else -1e9),
    ) for row in candidates]
    selected_rows = A.deterministic_top_five(analysis_candidates)
    selected = [row["cell_id"] for row in selected_rows]
    for rank, row in enumerate(candidates, 1):
        row["rank"] = rank
        row["selected_top_five"] = row["cell_id"] in selected
    return candidates, selected


def run_full(result_dir: Path, smoke: bool = False) -> dict:
    R.validate(result_dir)
    dates, lengths, closes = _calendar(R.DEVELOPMENT_FIRST, R.DEVELOPMENT_LAST)
    symbols = tuple(R.PERMITTED_SYMBOLS[:3]) if smoke else tuple(R.PERMITTED_SYMBOLS)
    if smoke:
        dates, lengths, closes = dates[:50], lengths[:50], closes[:50]
    panel = DensePanel.load(symbols, dates, lengths, closes)
    prefix = "smoke-full" if smoke else "full"
    audit_record, governed_days, audit_gaps = _audit_panel(panel)
    _install_governed_masks(panel, audit_record, governed_days)
    audit_sha = _write_json(result_dir / f"{prefix}-pre-return-audit.json", audit_record)
    event_sink = JsonlSink(result_dir / f"{prefix}-events.jsonl")
    censor_sink = JsonlSink(result_dir / f"{prefix}-censors.jsonl")
    rvol5, status5 = _rolling_rvol(panel, 5)
    rvol15, status15 = _rolling_rvol(panel, 15)
    _apply_reference_masks(panel, rvol5, status5)
    _apply_reference_masks(panel, rvol15, status15)
    _apply_audit_reference_masks(panel, rvol5, status5, audit_record)
    _apply_audit_reference_masks(panel, rvol15, status15, audit_record)
    events, responses = [], []
    censor_reasons = Counter()
    family_counts = Counter()
    for si, symbol in enumerate(panel.symbols):
        for di in range(20, len(panel.dates)):
            governed_reason = governed_days.get((symbol, panel.dates[di]))
            if governed_reason is not None:
                governed_reason = f"PRE_RETURN_MASK_{governed_reason}"
                for setting in R.SETTINGS:
                    for direction in ("long", "short"):
                        row = {
                            "id": f"{setting['id']}__{symbol}__{panel.dates[di]}__{direction.upper()}",
                            "kind": "event", "setting_id": setting["id"],
                            "family": setting["family"], "symbol": symbol,
                            "date": panel.dates[di], "direction": direction,
                            "reason": governed_reason,
                        }
                        censor_sink.write(row); censor_reasons[governed_reason] += 1
                continue
            found, reasons = _scan_day(panel, si, di, rvol5[si, di], rvol15[si, di])
            for setting in R.SETTINGS:
                for direction in ("long", "short"):
                    key = (setting["id"], direction)
                    if key not in found:
                        row = {"id": f"{setting['id']}__{symbol}__{panel.dates[di]}__{direction.upper()}",
                               "kind": "event", "setting_id": setting["id"], "family": setting["family"],
                               "symbol": symbol, "date": panel.dates[di], "direction": direction,
                               "reason": reasons[key]}
                        censor_sink.write(row); censor_reasons[row["reason"]] += 1
                        continue
                    event, produced, outcome_censors = _event_and_responses(
                        panel, si, di, setting["id"], direction, found[key],
                        (audit_gaps.get((symbol, panel.dates[di]))
                         if _reference_window_is_clean(panel, si, di - 1, di) else None),
                    )
                    event_sink.write(event); events.append(event); family_counts[event["family"]] += 1
                    responses.extend(produced)
                    for row in outcome_censors:
                        censor_sink.write(row); censor_reasons[row["reason"]] += 1
    event_count, event_sha = event_sink.close()

    needed_elapsed = {row["elapsed_minutes"] for row in responses}
    loo = _market_loo(panel, needed_elapsed)
    control_sink = JsonlSink(result_dir / f"{prefix}-control-daily.jsonl")
    control_stats, control_daily = _control_daily(panel, responses, loo, control_sink)
    control_count, control_sha = control_sink.close()

    bootstrap_draws = 100 if smoke else 1000
    checkpoint_dir = result_dir / f".{prefix}-bootstrap-checkpoints"
    checkpoint_context = _bootstrap_checkpoint_context(
        result_dir, prefix, bootstrap_draws,
        {"events": event_sha, "controls": control_sha},
    )
    power_rows = []
    cell_sink = JsonlSink(result_dir / f"{prefix}-cell-summaries.jsonl")
    daily_sink = JsonlSink(result_dir / f"{prefix}-daily-responses.jsonl")
    summaries = _summaries(
        responses, control_stats, control_daily, loo, panel, cell_sink, daily_sink,
        power_rows, bootstrap_draws, checkpoint_dir, checkpoint_context,
    )
    cell_count, cell_sha = cell_sink.close()
    daily_count, daily_sha = daily_sink.close()

    response_sink = JsonlSink(result_dir / f"{prefix}-responses.jsonl")
    for row in sorted(responses, key=lambda value: value["id"]):
        response_sink.write(row)
    response_count, response_sha = response_sink.close()
    censor_count, censor_sha = censor_sink.close()

    effective = _effective_variants(events)
    effective_sha = _write_json(result_dir / f"{prefix}-effective-variants.json", effective)
    power_sha = _write_json(result_dir / f"{prefix}-power-table.json", sorted(power_rows, key=lambda row: row["id"]))
    ranking, selected = _rank(summaries, effective)
    ranking_sha = _write_csv(result_dir / f"{prefix}-ranked-discovery.csv", ranking)
    ledger = {
        "registered_cells": 126, "attempted_cells": 126,
        "manual_changes_after_registration": 0, "abandoned_unregistered_ideas": 0,
        "selected_primary_cells": selected, "ranking_rule": "registered deterministic E1 rule",
        "first_pullback_status": (
            "unavailable because no symbol-day had every required scheduled input"
            if family_counts["first_pullback"] == 0 else "measured where complete"
        ),
        "bootstrap_draws_per_cell": bootstrap_draws,
    }
    ledger_sha = _write_json(result_dir / f"{prefix}-trial-ledger.json", ledger)
    coverage = {
        "open5": dict(sorted(Counter(status5[:, 20:].ravel()).items())),
        "open15": dict(sorted(Counter(status15[:, 20:].ravel()).items())),
    }
    artifacts = {
        f"{prefix}-pre-return-audit.json": audit_sha,
        f"{prefix}-events.jsonl": event_sha, f"{prefix}-responses.jsonl": response_sha,
        f"{prefix}-censors.jsonl": censor_sha, f"{prefix}-control-daily.jsonl": control_sha,
        f"{prefix}-cell-summaries.jsonl": cell_sha,
        f"{prefix}-daily-responses.jsonl": daily_sha,
        f"{prefix}-effective-variants.json": effective_sha,
        f"{prefix}-power-table.json": power_sha, f"{prefix}-ranked-discovery.csv": ranking_sha,
        f"{prefix}-trial-ledger.json": ledger_sha,
    }
    summary = {
        "study_id": R.STUDY_ID, "run_kind": "bounded smoke" if smoke else "full registered E1 prefix",
        "symbols": list(panel.symbols), "symbol_count": len(panel.symbols),
        "source_dates": {"first": dates[0], "last": dates[-1], "reference_sessions": 20},
        "measured_dates": {"first": dates[20], "last": dates[-1], "count": len(dates) - 20},
        "network_used": False, "spend_usd": 0.0,
        "runner_sha256": R.sha256_file(Path(__file__).resolve()),
        "pre_return_audit_sha256": audit_sha,
        "governed_excluded_symbol_days": len(governed_days),
        "events": event_count, "responses": response_count, "censors": censor_count,
        "control_daily_rows": control_count, "cell_summary_rows": cell_count,
        "daily_response_rows": daily_count,
        "event_counts_by_family": dict(sorted(family_counts.items())),
        "censor_reasons": dict(sorted(censor_reasons.items())),
        "opening_history_coverage": coverage,
        "families_unavailable": ([{
            "family": "first_pullback", "reason": ledger["first_pullback_status"]
        }] if family_counts["first_pullback"] == 0 else []),
        "selected_primary_cells": selected,
        "control_compaction_proof": {
            "stored_fields": ["date", "control_group_id", "opportunity_count", "sum_raw_return",
                              "market_residual_count", "sum_market_residual", "sum_cost_floor_bps"],
            "equivalence": "per-date sum/count exactly reproduces each daily mean; equal averaging of those daily means reproduces the registered date-first control mean",
        },
        "exact_minute_control_sensitivity": {
            "stored_on_each_response": [
                "exact_control_group_id", "exact_minute_control_gross_mean",
                "exact_minute_plain_gross_excess",
            ],
            "daily_exact_minute_rows_persisted": False,
            "reason": "the resolved sensitivity is retained without duplicating one daily row per event minute",
        },
        "artifact_sha256": artifacts,
    }
    _write_json(result_dir / f"{prefix}-summary.json", summary)
    if checkpoint_dir.exists():
        shutil.rmtree(checkpoint_dir)
    print(json.dumps({"summary": str(result_dir / f"{prefix}-summary.json"),
                      "events": event_count, "responses": response_count,
                      "controls": control_count, "selected": selected}, sort_keys=True))
    return summary
