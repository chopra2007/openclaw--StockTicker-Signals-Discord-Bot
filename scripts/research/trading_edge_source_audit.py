#!/usr/bin/env python3
"""Deterministic, pre-return source audit for the registered E1 study.

The audit only inspects source bars, the expected session clock, and optional
corporate-action records.  It never calculates a strategy return, reads a
market-data file, uses the network, or removes a raw row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


AUDIT_VERSION = "TRADING_EDGE_SOURCE_AUDIT_V1"
GAP_BUCKETS = (
    (0, 200, "LT_2PCT"),
    (200, 500, "2_TO_5PCT"),
    (500, 1_000, "5_TO_10PCT"),
    (1_000, 2_000, "10_TO_20PCT"),
    (2_000, None, "GE_20PCT"),
)
EXTREME_GAP_BPS = 2_000
COMMON_SPLIT_FACTORS = (2.0, 3.0, 4.0, 5.0, 10.0)
SPLIT_FACTOR_RELATIVE_TOLERANCE = 0.01


@dataclass(frozen=True)
class SourceAuditResult:
    """Raw rows with annotations plus one governed record per symbol-day."""

    rows: pd.DataFrame
    symbol_days: pd.DataFrame
    mask_record: dict


def schedule_from_lengths(
    dates: Sequence[str], lengths: Sequence[int], open_minute: int = 570
) -> dict[str, tuple[int, ...]]:
    """Build exact scheduled minute labels from registered session lengths."""
    if len(dates) != len(lengths):
        raise ValueError("dates and lengths must have the same size")
    schedule = {}
    for raw_date, raw_length in zip(dates, lengths):
        length = int(raw_length)
        if length <= 0:
            raise ValueError("session length must be positive")
        day = _date_text(raw_date)
        if day in schedule:
            raise ValueError(f"duplicate scheduled date: {day}")
        schedule[day] = tuple(range(int(open_minute), int(open_minute) + length))
    return schedule


def gap_bucket(gap_bps: float | None) -> str:
    """Return the frozen absolute overnight-gap bucket."""
    if gap_bps is None or not np.isfinite(gap_bps):
        return "UNAVAILABLE"
    absolute = abs(float(gap_bps))
    for lower, upper, label in GAP_BUCKETS:
        if absolute >= lower and (upper is None or absolute < upper):
            return label
    raise AssertionError("registered gap buckets do not cover the value")


def excluded_symbol_days(mask_record: Mapping) -> set[tuple[str, str]]:
    """Expose the governed mask in the form used by the full-prefix runner."""
    return {
        (str(item["symbol"]), str(item["date"]))
        for item in mask_record.get("symbol_days", [])
        if item.get("exclude") is True
    }


def audit_source_rows(
    bars: pd.DataFrame,
    scheduled_minutes: Mapping[str, Iterable[int]],
    corporate_actions: pd.DataFrame | None = None,
) -> SourceAuditResult:
    """Audit bar coverage, overnight gaps, and source actions before returns.

    Required bar columns are ``symbol``, ``date``, ``minute``, ``open``, and
    ``close``.  Other columns and the original row order are retained exactly.
    Corporate actions need ``symbol``, ``date``, ``action_type``, and ``source``.
    ``adjustment_compatible=True`` is the only way an action is recorded without
    excluding its effective session.
    """
    required = {"symbol", "date", "minute", "open", "close"}
    missing = sorted(required - set(bars.columns))
    if missing:
        raise ValueError(f"bars missing required columns: {', '.join(missing)}")
    schedule = _normalise_schedule(scheduled_minutes)
    if not schedule:
        raise ValueError("scheduled_minutes cannot be empty")

    raw = bars.copy(deep=True)
    raw["_audit_row_id"] = np.arange(len(raw), dtype=np.int64)
    work = raw[["_audit_row_id", "symbol", "date", "minute", "open", "close"]].copy()
    work["symbol"] = work["symbol"].astype(str).str.upper().str.strip()
    work["date"] = work["date"].map(_date_text)
    work["minute"] = pd.to_numeric(work["minute"], errors="raise").astype(int)
    for column in ("open", "close"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    outside = sorted(set(work["date"]) - set(schedule))
    if outside:
        raise ValueError(f"bars contain dates outside the supplied schedule: {', '.join(outside)}")

    action_map = _normalise_actions(corporate_actions)
    records: list[dict] = []
    previous_close: dict[str, float] = {}
    epochs: dict[str, int] = {}
    grouped = {(symbol, day): frame for (symbol, day), frame in work.groupby(["symbol", "date"], sort=False)}
    symbols = sorted(work["symbol"].unique())

    for day in sorted(schedule):
        expected = schedule[day]
        expected_set = set(expected)
        first_minute, last_minute = expected[0], expected[-1]
        for symbol in symbols:
            frame = grouped.get((symbol, day))
            reasons: list[str] = []
            present: set[int] = set()
            duplicate_minutes: list[int] = []
            unexpected_minutes: list[int] = []
            first_open = last_close = np.nan
            raw_count = 0
            if frame is None:
                reasons.append("NO_SOURCE_ROWS")
            else:
                raw_count = len(frame)
                counts = frame["minute"].value_counts()
                present = set(int(value) for value in counts.index)
                duplicate_minutes = sorted(int(value) for value in counts[counts > 1].index)
                unexpected_minutes = sorted(present - expected_set)
                if duplicate_minutes:
                    reasons.append("DUPLICATE_SCHEDULED_MINUTES")
                if unexpected_minutes:
                    reasons.append("UNEXPECTED_SESSION_MINUTES")
                first_rows = frame.loc[frame["minute"] == first_minute, "open"]
                last_rows = frame.loc[frame["minute"] == last_minute, "close"]
                if len(first_rows) == 1:
                    first_open = float(first_rows.iloc[0])
                if len(last_rows) == 1:
                    last_close = float(last_rows.iloc[0])

            missing_minutes = sorted(expected_set - present)
            if missing_minutes:
                reasons.append("MISSING_SCHEDULED_MINUTES")
            coverage = (len(present & expected_set) / len(expected)) if expected else 0.0

            gap_bps = None
            prior = previous_close.get(symbol)
            if prior is not None and np.isfinite(prior) and prior > 0 and np.isfinite(first_open) and first_open > 0:
                gap_bps = (first_open / prior - 1.0) * 10_000.0
            bucket = gap_bucket(gap_bps)
            extreme_gap = gap_bps is not None and abs(gap_bps) >= EXTREME_GAP_BPS
            if extreme_gap:
                reasons.append("EXTREME_OVERNIGHT_GAP")

            suspected_factor = _suspected_split_factor(prior, first_open)
            if suspected_factor is not None:
                reasons.append("SUSPECTED_SPLIT_DISCONTINUITY")

            actions = action_map.get((symbol, day), [])
            unresolved_actions = [item for item in actions if not item["adjustment_compatible"]]
            if actions:
                reasons.append("KNOWN_CORPORATE_ACTION")
            if unresolved_actions:
                reasons.append("UNPROVEN_ACTION_ADJUSTMENT")

            reset = bool(unresolved_actions or suspected_factor is not None)
            if reset:
                epochs[symbol] = epochs.get(symbol, 0) + 1
            else:
                epochs.setdefault(symbol, 0)
            exclude = bool(missing_minutes or duplicate_minutes or unexpected_minutes or reset)
            ordered_reasons = sorted(set(reasons))
            records.append({
                "symbol": symbol,
                "date": day,
                "exclude": exclude,
                "reasons": ordered_reasons,
                "scheduled_minute_count": len(expected),
                "present_scheduled_minute_count": len(present & expected_set),
                "raw_row_count": raw_count,
                "coverage_ratio": coverage,
                "missing_minutes": missing_minutes,
                "duplicate_minutes": duplicate_minutes,
                "unexpected_minutes": unexpected_minutes,
                "overnight_gap_bps": gap_bps,
                "overnight_gap_bucket": bucket,
                "extreme_overnight_gap": extreme_gap,
                "suspected_split_factor": suspected_factor,
                "corporate_actions": actions,
                "reference_reset": reset,
                "reference_epoch": epochs[symbol],
            })
            if np.isfinite(last_close) and last_close > 0:
                previous_close[symbol] = last_close

    symbol_days = pd.DataFrame.from_records(records).sort_values(["date", "symbol"], kind="stable").reset_index(drop=True)
    annotations = symbol_days.set_index(["symbol", "date"])
    keys = pd.MultiIndex.from_arrays([work["symbol"], work["date"]])
    raw["_audit_exclude_symbol_day"] = annotations["exclude"].reindex(keys).to_numpy(dtype=bool)
    raw["_audit_reasons"] = annotations["reasons"].reindex(keys).map(tuple).to_numpy()
    raw["_audit_overnight_gap_bucket"] = annotations["overnight_gap_bucket"].reindex(keys).to_numpy()
    raw["_audit_reference_epoch"] = annotations["reference_epoch"].reindex(keys).to_numpy(dtype=int)

    mask_days = [_json_safe_record(row) for row in records]
    mask_days.sort(key=lambda item: (item["date"], item["symbol"]))
    mask_record = {
        "audit_version": AUDIT_VERSION,
        "rules": {
            "gap_buckets_bps": [
                {"minimum": lower, "maximum_exclusive": upper, "label": label}
                for lower, upper, label in GAP_BUCKETS
            ],
            "extreme_gap_bps": EXTREME_GAP_BPS,
            "split_factors": list(COMMON_SPLIT_FACTORS),
            "split_factor_relative_tolerance": SPLIT_FACTOR_RELATIVE_TOLERANCE,
            "action_policy": "exclude unless adjustment_compatible is explicitly true",
            "coverage_policy": "exclude any missing, duplicate, or unexpected scheduled minute",
        },
        "raw_rows_preserved": True,
        "raw_row_count": len(raw),
        "symbol_day_count": len(mask_days),
        "excluded_symbol_day_count": sum(bool(item["exclude"]) for item in mask_days),
        "symbol_days": mask_days,
    }
    return SourceAuditResult(rows=raw, symbol_days=symbol_days, mask_record=mask_record)


def _date_text(value) -> str:
    return pd.Timestamp(value).date().isoformat()


def _normalise_schedule(scheduled_minutes: Mapping[str, Iterable[int]]) -> dict[str, tuple[int, ...]]:
    result = {}
    for raw_day, raw_minutes in scheduled_minutes.items():
        day = _date_text(raw_day)
        minutes = tuple(sorted({int(value) for value in raw_minutes}))
        if not minutes:
            raise ValueError(f"scheduled date has no minutes: {day}")
        if day in result:
            raise ValueError(f"duplicate scheduled date: {day}")
        result[day] = minutes
    return result


def _normalise_actions(actions: pd.DataFrame | None) -> dict[tuple[str, str], list[dict]]:
    if actions is None or actions.empty:
        return {}
    required = {"symbol", "date", "action_type", "source"}
    missing = sorted(required - set(actions.columns))
    if missing:
        raise ValueError(f"corporate_actions missing required columns: {', '.join(missing)}")
    result: dict[tuple[str, str], list[dict]] = {}
    for raw in actions.to_dict("records"):
        compatible = raw.get("adjustment_compatible", False)
        item = {
            "action_type": str(raw["action_type"]),
            "source": str(raw["source"]),
            "value": _json_scalar(raw.get("value")),
            "adjustment_compatible": (
                False if pd.isna(compatible) else compatible is True or compatible == np.bool_(True)
            ),
        }
        key = (str(raw["symbol"]).upper().strip(), _date_text(raw["date"]))
        result.setdefault(key, []).append(item)
    for items in result.values():
        items.sort(key=lambda item: (item["action_type"], item["source"], str(item["value"])))
    return result


def _suspected_split_factor(previous_close: float | None, current_open: float) -> float | None:
    if previous_close is None or not np.isfinite(previous_close) or previous_close <= 0:
        return None
    if not np.isfinite(current_open) or current_open <= 0:
        return None
    scale = max(previous_close / current_open, current_open / previous_close)
    for factor in COMMON_SPLIT_FACTORS:
        if abs(scale / factor - 1.0) <= SPLIT_FACTOR_RELATIVE_TOLERANCE:
            return factor
    return None


def _json_safe_record(row: dict) -> dict:
    result = dict(row)
    value = result["overnight_gap_bps"]
    result["overnight_gap_bps"] = None if value is None or not np.isfinite(value) else float(value)
    return result


def _json_scalar(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value
