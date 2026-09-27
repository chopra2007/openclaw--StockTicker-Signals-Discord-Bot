#!/usr/bin/env python3
"""Run the registered three-symbol E1 event-response pilot.

The pilot is intentionally small.  It reads 20 reference sessions and 30
development sessions for CRM, NOW, and ORCL.  It does not rank settings,
simulate a portfolio, access the network, or read the protected epoch.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[1]
RESULT_DIR = WORKSPACE / ".omc/research/trading-edge-discovery"
REGISTRATION_MODULE = HERE / "trading_edge_registration.py"
PILOT_SYMBOLS = ("CRM", "NOW", "ORCL")
REFERENCE_SESSION_COUNT = 20
PILOT_SESSION_COUNT = 30
SOURCE_CLOCK = ZoneInfo("America/New_York")
PACIFIC = ZoneInfo("America/Los_Angeles")


def _load_registration_module():
    spec = importlib.util.spec_from_file_location("trading_edge_registration", REGISTRATION_MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = _load_registration_module()


@contextmanager
def _exclusive_full_run(result_dir: Path):
    """Prevent two full/smoke controllers from writing the same artifacts."""
    result_dir.mkdir(parents=True, exist_ok=True)
    path = result_dir / ".trading-edge-e1-full.lock"
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another trading-edge E1 full or smoke run is active") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()}\n")
        handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write_json(path: Path, value: object) -> str:
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    path.with_suffix(path.suffix + ".sha256").write_text(f"{digest}  {path.name}\n")
    return digest


def _write_jsonl(path: Path, rows: Iterable[dict]) -> tuple[int, str]:
    ordered = sorted(rows, key=lambda row: row["id"])
    payload = b"".join(_canonical_json(row) for row in ordered)
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    path.with_suffix(path.suffix + ".sha256").write_text(f"{digest}  {path.name}\n")
    return len(ordered), digest


def pilot_sessions() -> tuple[list[str], list[str], pd.DataFrame]:
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range(R.DEVELOPMENT_FIRST, "2023-07-31")
    needed = REFERENCE_SESSION_COUNT + PILOT_SESSION_COUNT
    if len(sessions) < needed:
        raise RuntimeError("exchange calendar does not contain the required pilot sessions")
    selected = sessions[:needed]
    labels = [stamp.date().isoformat() for stamp in selected]
    schedule = calendar.schedule.loc[selected, ["open", "close"]].copy()
    schedule.index = labels
    return labels[:REFERENCE_SESSION_COUNT], labels[REFERENCE_SESSION_COUNT:], schedule


def _session_minutes(schedule_row: pd.Series) -> list[int]:
    opened = schedule_row["open"].to_pydatetime().astimezone(SOURCE_CLOCK)
    closed = schedule_row["close"].to_pydatetime().astimezone(SOURCE_CLOCK)
    start = opened.hour * 60 + opened.minute
    stop = closed.hour * 60 + closed.minute
    return list(range(start, stop))


def _pacific_instant(day: str, source_minute: int) -> str:
    hour, minute = divmod(source_minute, 60)
    instant = datetime.combine(date.fromisoformat(day), datetime.min.time()).replace(
        hour=hour, minute=minute, tzinfo=SOURCE_CLOCK
    )
    return instant.astimezone(PACIFIC).isoformat(timespec="minutes")


def _load_bars(first_date: str, last_date: str) -> pd.DataFrame:
    batches = R.guarded_parquet_batches(
        R.PRIMARY_SOURCE,
        PILOT_SYMBOLS,
        first_date,
        last_date,
        ["minute", "open", "high", "low", "close", "volume"],
    )
    frames = [batch.to_pandas() for batch in batches]
    if not frames:
        raise RuntimeError("the registered source returned no pilot rows")
    bars = pd.concat(frames, ignore_index=True)
    bars["date"] = bars["date"].astype(str)
    bars["symbol"] = bars["symbol"].astype(str)
    bars["minute"] = bars["minute"].astype(int)
    bars = bars.sort_values(["symbol", "date", "minute"], kind="stable")
    if set(bars.symbol.unique()) != set(PILOT_SYMBOLS):
        raise RuntimeError("CRM/NOW/ORCL coverage is incomplete in the registered source")
    return bars


def _day_frames(bars: pd.DataFrame) -> dict[tuple[str, str], pd.DataFrame]:
    return {
        (symbol, day): frame.set_index("minute").sort_index()
        for (symbol, day), frame in bars.groupby(["symbol", "date"], sort=True)
    }


def _complete(frame: pd.DataFrame | None, minutes: list[int], columns: tuple[str, ...]) -> bool:
    if frame is None or not set(minutes).issubset(frame.index):
        return False
    return bool(np.isfinite(frame.loc[minutes, list(columns)].to_numpy(dtype=float)).all())


def _rvol(
    frames: dict[tuple[str, str], pd.DataFrame], symbol: str, day: str,
    prior_days: list[str], opening_minutes: list[int]
) -> float | None:
    return _rvol_status(frames, symbol, day, prior_days, opening_minutes)[0]


def _rvol_status(
    frames: dict[tuple[str, str], pd.DataFrame], symbol: str, day: str,
    prior_days: list[str], opening_minutes: list[int]
) -> tuple[float | None, str]:
    current = frames.get((symbol, day))
    if len(prior_days) != 20:
        return None, "reference_session_count_wrong"
    if not _complete(current, opening_minutes, ("volume",)):
        return None, "current_exact_window_missing"
    totals = []
    for prior in prior_days:
        frame = frames.get((symbol, prior))
        if not _complete(frame, opening_minutes, ("volume",)):
            return None, "one_or_more_exact_prior_windows_missing"
        totals.append(float(frame.loc[opening_minutes, "volume"].sum()))
    denominator = float(np.mean(totals))
    if denominator <= 0:
        return None, "nonpositive_prior_mean"
    return float(current.loc[opening_minutes, "volume"].sum()) / denominator, "available"


def _daily_atr14(
    frames: dict[tuple[str, str], pd.DataFrame], symbol: str,
    prior_days: list[str], schedule: pd.DataFrame
) -> float | None:
    if len(prior_days) < 15:
        return None
    selected = prior_days[-15:]
    daily = []
    for day in selected:
        frame = frames.get((symbol, day))
        minutes = _session_minutes(schedule.loc[day])
        if not _complete(frame, minutes, ("high", "low", "close")):
            return None
        daily.append((
            float(frame.loc[minutes, "high"].max()),
            float(frame.loc[minutes, "low"].min()),
            float(frame.loc[minutes[-1], "close"]),
        ))
    ranges = []
    for index in range(1, len(daily)):
        high, low, _ = daily[index]
        previous_close = daily[index - 1][2]
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return float(np.mean(ranges)) if len(ranges) == 14 else None


def _true_ranges(frame: pd.DataFrame, minutes: list[int]) -> dict[int, float] | None:
    if not _complete(frame, minutes, ("high", "low", "close")):
        return None
    out = {}
    previous_close = None
    for minute in minutes:
        row = frame.loc[minute]
        high, low, close = float(row.high), float(row.low), float(row.close)
        out[minute] = high - low if previous_close is None else max(
            high - low, abs(high - previous_close), abs(low - previous_close)
        )
        previous_close = close
    return out


def _minute_atr_series(
    frames: dict[tuple[str, str], pd.DataFrame], symbol: str, day: str,
    prior_day: str, schedule: pd.DataFrame
) -> dict[int, float | None]:
    current_minutes = _session_minutes(schedule.loc[day])
    prior_minutes = _session_minutes(schedule.loc[prior_day])
    current = frames.get((symbol, day))
    previous = frames.get((symbol, prior_day))
    current_tr = _true_ranges(current, current_minutes) if current is not None else None
    prior_tr = _true_ranges(previous, prior_minutes) if previous is not None else None
    if current_tr is None or prior_tr is None:
        return {minute: None for minute in current_minutes}
    prior_tail = [prior_tr[minute] for minute in prior_minutes]
    running = []
    result = {}
    for minute in current_minutes:
        window = (prior_tail + running + [current_tr[minute]])[-20:]
        result[minute] = float(np.mean(window)) if len(window) == 20 else None
        running.append(current_tr[minute])
    return result


def _vwap_series(frame: pd.DataFrame, minutes: list[int], start_minute: int | None = None):
    selected = [minute for minute in minutes if start_minute is None or minute >= start_minute]
    weighted = 0.0
    volume = 0.0
    result = {}
    for minute in selected:
        if not _complete(frame, [minute], ("high", "low", "close", "volume")):
            result[minute] = None
            continue
        row = frame.loc[minute]
        shares = float(row.volume)
        weighted += ((float(row.high) + float(row.low) + float(row.close)) / 3.0) * shares
        volume += shares
        result[minute] = weighted / volume if volume > 0 else None
    return result


def _crossed(previous: float, current: float, boundary: float, direction: str) -> bool:
    return (
        previous <= boundary < current if direction == "long"
        else previous >= boundary > current
    )


def _opening_range_events(
    setting: dict, frame: pd.DataFrame, minutes: list[int], rvol: float | None
) -> tuple[dict[str, int], dict[str, str]]:
    size = setting["opening_minutes"]
    opening = minutes[:size]
    if not _complete(frame, opening, ("high", "low", "close")):
        return {}, {side: "OPENING_RANGE_UNAVAILABLE" for side in ("long", "short")}
    gate = setting["opening_volume_gate"]
    if gate is not None and (rvol is None or rvol < gate):
        reason = "OPENING_VOLUME_GATE_UNAVAILABLE" if rvol is None else "OPENING_VOLUME_GATE_FAILED"
        return {}, {side: reason for side in ("long", "short")}
    high = float(frame.loc[opening, "high"].max())
    low = float(frame.loc[opening, "low"].min())
    found, reasons = {}, {}
    scan = [minute for minute in minutes[size:] if minute < minutes[0] + 300]
    previous_minute = opening[-1]
    for minute in scan:
        if not _complete(frame, [previous_minute, minute], ("close",)):
            previous_minute = minute
            continue
        previous, current = float(frame.loc[previous_minute, "close"]), float(frame.loc[minute, "close"])
        if "long" not in found and _crossed(previous, current, high, "long"):
            found["long"] = minute
        if "short" not in found and _crossed(previous, current, low, "short"):
            found["short"] = minute
        previous_minute = minute
    for side in ("long", "short"):
        if side not in found:
            reasons[side] = "NO_FIRST_COMPLETED_CLOSE_CROSS"
    return found, reasons


def _high_low_events(
    setting: dict, frame: pd.DataFrame, minutes: list[int], opening5_rvol: float | None,
    vwap: dict[int, float | None]
) -> tuple[dict[str, int], dict[str, str]]:
    if opening5_rvol is None or opening5_rvol < 1.5:
        reason = "OPENING5_RVOL_UNAVAILABLE" if opening5_rvol is None else "OPENING5_RVOL_FAILED"
        return {}, {side: reason for side in ("long", "short")}
    found = {}
    for position in range(15, len(minutes)):
        minute = minutes[position]
        if minute >= minutes[0] + 300 or not _complete(frame, minutes[: position + 1], ("high", "low", "close")):
            continue
        prior = minutes[:position]
        current = float(frame.loc[minute, "close"])
        prior_high = float(frame.loc[prior, "high"].max())
        prior_low = float(frame.loc[prior, "low"].min())
        current_vwap = vwap.get(minute)
        if current_vwap is None:
            continue
        compression_pass = True
        if setting["compression"]:
            preceding3, preceding7 = prior[-3:], prior[-7:]
            short_range = float(frame.loc[preceding3, "high"].max() - frame.loc[preceding3, "low"].min())
            long_range = float(frame.loc[preceding7, "high"].max() - frame.loc[preceding7, "low"].min())
            compression_pass = long_range > 0 and short_range / long_range <= 0.60
        if not compression_pass:
            continue
        if "long" not in found and current > prior_high and current > current_vwap:
            found["long"] = minute
        if "short" not in found and current < prior_low and current < current_vwap:
            found["short"] = minute
    return found, {side: "NO_FIRST_HIGH_LOW_BREAKOUT" for side in ("long", "short") if side not in found}


def _failed_opening_range_events(
    frame: pd.DataFrame, minutes: list[int]
) -> tuple[dict[str, int], dict[str, str]]:
    opening = minutes[:15]
    if not _complete(frame, opening, ("high", "low", "close")):
        return {}, {side: "OPENING_RANGE_UNAVAILABLE" for side in ("long", "short")}
    high = float(frame.loc[opening, "high"].max())
    low = float(frame.loc[opening, "low"].min())
    outside = {"long": False, "short": False}
    found = {}
    for minute in minutes[15:]:
        if minute >= minutes[0] + 300 or not _complete(frame, [minute], ("close",)):
            continue
        close = float(frame.loc[minute, "close"])
        if close < low:
            outside["long"] = True
        elif outside["long"] and "long" not in found and close > low:
            found["long"] = minute
        if close > high:
            outside["short"] = True
        elif outside["short"] and "short" not in found and close < high:
            found["short"] = minute
    return found, {side: "NO_FAILED_OPENING_RANGE_RETURN" for side in ("long", "short") if side not in found}


def _vwap_crosses(frame: pd.DataFrame, minutes: list[int], vwap: dict[int, float | None]) -> int | None:
    sides = []
    for minute in minutes:
        value = vwap.get(minute)
        if value is None or not _complete(frame, [minute], ("close",)):
            return None
        close = float(frame.loc[minute, "close"])
        sides.append(1 if close > value else -1 if close < value else 0)
    return sum(a * b == -1 for a, b in zip(sides, sides[1:]))


def _first_pullback_event(
    setting: dict, direction: str, frame: pd.DataFrame, minutes: list[int],
    atr: dict[int, float | None], daily_atr: float | None,
    vwap: dict[int, float | None]
) -> tuple[int | None, str, dict]:
    sign = 1 if direction == "long" else -1
    scan = [minute for minute in minutes if minutes[0] + 8 <= minute < minutes[0] + 45]
    if daily_atr is None or not scan or not _complete(frame, minutes[:45], ("open", "high", "low", "close", "volume")):
        return None, "FIRST_PULLBACK_REQUIRED_HISTORY_UNAVAILABLE", {}
    origin = float(frame.loc[minutes[0], "open"])
    extreme = origin
    extreme_pos = 0
    confirmation = None
    frozen_atr = None
    for pos in range(0, 45):
        minute = minutes[pos]
        candidate = float(frame.loc[minute, "high" if sign > 0 else "low"])
        stricter = candidate > extreme if sign > 0 else candidate < extreme
        if stricter:
            extreme, extreme_pos, confirmation = candidate, pos, None
        if pos < extreme_pos + 2:
            continue
        first, second = minutes[extreme_pos + 1], minutes[extreme_pos + 2]
        c0 = float(frame.loc[minutes[extreme_pos], "close"])
        c1, c2 = float(frame.loc[first, "close"]), float(frame.loc[second, "close"])
        toward = c1 < c0 and c2 < c1 if sign > 0 else c1 > c0 and c2 > c1
        if pos == extreme_pos + 2 and toward:
            candidate_atr = atr.get(second)
            selected_vwap = vwap.get(second)
            distance = sign * (extreme - origin)
            if (candidate_atr is not None and candidate_atr > 0 and selected_vwap is not None
                    and distance >= 0.40 * candidate_atr
                    and distance >= 0.15 * daily_atr
                    and sign * (extreme - selected_vwap) >= 0.25 * candidate_atr):
                confirmation, frozen_atr = extreme_pos + 2, candidate_atr
                break
    if confirmation is None or frozen_atr is None:
        return None, "NO_ELIGIBLE_TWO_BAR_CONFIRMED_IMPULSE", {}

    pullback_start = None
    for pos in range(extreme_pos + 1, confirmation + 1):
        current, previous = minutes[pos], minutes[pos - 1]
        began = (
            float(frame.loc[current, "low"]) < float(frame.loc[previous, "low"])
            if sign > 0 else
            float(frame.loc[current, "high"]) > float(frame.loc[previous, "high"])
        )
        if began:
            pullback_start = pos
            break
    reversal_pos = None
    boundary = None
    pullback_extreme = None
    for pos in range(confirmation + 1, 45):
        if pullback_start is None:
            current, previous = minutes[pos], minutes[pos - 1]
            began = (
                float(frame.loc[current, "low"]) < float(frame.loc[previous, "low"])
                if sign > 0 else
                float(frame.loc[current, "high"]) > float(frame.loc[previous, "high"])
            )
            if not began:
                continue
            pullback_start = pos
        relevant = minutes[pullback_start : pos + 1]
        pullback_extreme = (
            float(frame.loc[relevant, "low"].min()) if sign > 0
            else float(frame.loc[relevant, "high"].max())
        )
        impulse_distance = sign * (extreme - origin)
        retracement = sign * (extreme - pullback_extreme) / impulse_distance
        if retracement > 0.70:
            return None, "FIRST_STRUCTURE_INVALIDATED_DEEP_PULLBACK", {}
        current, previous = minutes[pos], minutes[pos - 1]
        row = frame.loc[current]
        directional_bar = (
            float(row.close) > float(row.open) and float(row.close) > float(frame.loc[previous, "close"])
            if sign > 0 else
            float(row.close) < float(row.open) and float(row.close) < float(frame.loc[previous, "close"])
        )
        if reversal_pos is None and retracement >= 0.20 and directional_bar:
            reversal_pos = pos
            buffer = max(0.01, 0.03 * frozen_atr)
            boundary = float(row.high) + buffer if sign > 0 else float(row.low) - buffer
            continue
        if reversal_pos is None or pos <= reversal_pos:
            continue
        previous_close = float(frame.loc[previous, "close"])
        current_close = float(row.close)
        if not _crossed(previous_close, current_close, boundary, direction):
            continue
        impulse_minutes = minutes[: extreme_pos + 1]
        pullback_minutes = minutes[pullback_start : pos + 1]
        impulse_rate = float(frame.loc[impulse_minutes, "volume"].sum()) / (60 * len(impulse_minutes))
        pullback_rate = float(frame.loc[pullback_minutes, "volume"].sum()) / (60 * len(pullback_minutes))
        ratio = pullback_rate / impulse_rate if impulse_rate > 0 else math.inf
        retracement = sign * (extreme - pullback_extreme) / (sign * (extreme - origin))
        if not (0.20 <= retracement <= 0.65 and ratio <= 0.80):
            continue
        session_vwap = vwap.get(current)
        support_ok = False
        if session_vwap is not None:
            slope_base = vwap.get(current - 3)
            crosses = _vwap_crosses(frame, minutes[: pos + 1], vwap)
            support_ok = (
                sign * (current_close - session_vwap) > 0
                and abs(pullback_extreme - session_vwap) <= 0.15 * frozen_atr
                and sign * (pullback_extreme - session_vwap) >= -0.10 * frozen_atr
                and slope_base is not None and sign * (session_vwap - slope_base) > 0
                and crosses is not None and crosses <= 3
            )
        if setting["session_vwap_support"] == "mandatory" and not support_ok:
            continue
        if setting["impulse_anchored_vwap_support"]:
            anchored = _vwap_series(frame, minutes[: pos + 1], minutes[0]).get(current)
            if anchored is None or not (
                sign * (current_close - anchored) > 0
                and abs(pullback_extreme - anchored) <= 0.15 * frozen_atr
                and sign * (pullback_extreme - anchored) >= -0.10 * frozen_atr
            ):
                continue
        return current, "", {
            "impulse_origin": origin,
            "impulse_extreme": extreme,
            "impulse_extreme_minute": minutes[extreme_pos],
            "impulse_confirmed_minute": minutes[confirmation],
            "frozen_atr_1m20": frozen_atr,
            "frozen_daily_atr14": daily_atr,
            "pullback_extreme": pullback_extreme,
            "retracement": retracement,
            "volume_rate_ratio": ratio,
            "reversal_boundary": boundary,
        }
    return None, "NO_FIRST_PULLBACK_COMPLETED_CLOSE_TRIGGER", {}


def _late_event(
    frame: pd.DataFrame, minutes: list[int], previous_close: float | None, direction: str
) -> tuple[int | None, str]:
    if previous_close is None or not _complete(frame, minutes[:30], ("close",)):
        return None, "LATE_DIRECTION_REFERENCE_UNAVAILABLE"
    first30_close = float(frame.loc[minutes[29], "close"])
    actual_direction = "long" if first30_close > previous_close else "short" if first30_close < previous_close else None
    if actual_direction != direction:
        return None, "LATE_DIRECTION_NOT_SELECTED"
    signal_minute = minutes[-31]
    return signal_minute, ""


def _block(day: str) -> str:
    for block_id, first, last in R.BLOCKS:
        if first <= day <= last:
            return block_id
    raise ValueError(f"day outside registered blocks: {day}")


def _session_type(minutes: list[int]) -> str:
    return "regular" if len(minutes) == 390 else "shortened"


def _event_outcomes(
    event: dict, frame: pd.DataFrame, minutes: list[int], setting: dict
) -> tuple[list[dict], list[dict]]:
    outcomes, censors = [], []
    sign = 1 if event["direction"] == "long" else -1
    for reference_name, delay in (("next_minute", 1), ("one_extra_minute", 2)):
        entry_minute = event["signal_minute"] + delay
        if entry_minute not in minutes or not _complete(frame, [entry_minute], ("open",)):
            censors.append({
                "id": f"{event['id']}__{reference_name}__ENTRY",
                "kind": "outcome", "event_id": event["id"], "reference": reference_name,
                "reason": "MISSING_REFERENCE_ENTRY_MINUTE",
            })
            continue
        entry_price = float(frame.loc[entry_minute, "open"])
        for horizon in setting["horizons_minutes"]:
            exit_minute = event["signal_minute"] + 1 + horizon - 1
            outcome_id = f"{event['id']}__{reference_name}__H{horizon}"
            if exit_minute not in minutes or not _complete(frame, [exit_minute], ("close",)):
                censors.append({
                    "id": outcome_id, "kind": "outcome", "event_id": event["id"],
                    "reference": reference_name, "horizon_minutes": horizon,
                    "reason": "MISSING_OR_AFTER_SESSION_EXIT",
                })
                continue
            path = [minute for minute in minutes if entry_minute <= minute <= exit_minute]
            if not _complete(frame, path, ("high", "low", "close")):
                censors.append({
                    "id": outcome_id, "kind": "outcome", "event_id": event["id"],
                    "reference": reference_name, "horizon_minutes": horizon,
                    "reason": "MISSING_PATH_INTERVAL",
                })
                continue
            exit_price = float(frame.loc[exit_minute, "close"])
            high = float(frame.loc[path, "high"].max())
            low = float(frame.loc[path, "low"].min())
            outcomes.append({
                "id": outcome_id,
                "event_id": event["id"],
                "setting_id": event["setting_id"],
                "family": event["family"],
                "symbol": event["symbol"],
                "date": event["date"],
                "block": event["block"],
                "direction": event["direction"],
                "reference": reference_name,
                "entry_minute": entry_minute,
                "entry_time_pacific": _pacific_instant(event["date"], entry_minute),
                "entry_price": entry_price,
                "horizon_minutes": horizon,
                "exit_minute": exit_minute,
                "exit_time_pacific": _pacific_instant(event["date"], exit_minute + 1),
                "exit_price": exit_price,
                "signed_return": sign * (exit_price / entry_price - 1.0),
                "favorable_excursion": (
                    (high / entry_price - 1.0) if sign > 0 else (1.0 - low / entry_price)
                ),
                "adverse_excursion": (
                    (low / entry_price - 1.0) if sign > 0 else (1.0 - high / entry_price)
                ),
                "control_key": _control_key(event, reference_name, horizon, entry_minute, minutes),
            })
    return outcomes, censors


def _control_key(event: dict, reference: str, horizon: int, entry_minute: int, minutes: list[int]) -> str:
    if event["family"] == "late_continuation":
        clock = f"TTC{minutes[-1] + 1 - entry_minute}"
    else:
        clock = f"BIN{(entry_minute - minutes[0]) // 15:02d}"
    return "|".join((
        event["symbol"], event["block"], event["direction"], str(horizon),
        _session_type(minutes), reference, clock,
    ))


def _build_controls(
    outcomes: list[dict], frames: dict[tuple[str, str], pd.DataFrame],
    pilot_days: list[str], schedule: pd.DataFrame
) -> list[dict]:
    requested = {}
    for outcome in outcomes:
        requested[outcome["control_key"]] = outcome
    controls = []
    for key, template in sorted(requested.items()):
        symbol = template["symbol"]
        sign = 1 if template["direction"] == "long" else -1
        for day in pilot_days:
            if _block(day) != template["block"]:
                continue
            minutes = _session_minutes(schedule.loc[day])
            if _session_type(minutes) != key.split("|")[4]:
                continue
            frame = frames.get((symbol, day))
            clock = key.split("|")[-1]
            if clock.startswith("TTC"):
                time_to_close = int(clock[3:])
                entry_candidates = [minutes[-1] + 1 - time_to_close]
            else:
                bin_number = int(clock[3:])
                start = minutes[0] + 15 * bin_number
                entry_candidates = list(range(start, min(start + 15, minutes[-1] + 1)))
            for entry_minute in entry_candidates:
                exit_minute = entry_minute + template["horizon_minutes"] - 1
                if (frame is None or entry_minute not in frame.index or exit_minute not in frame.index):
                    continue
                entry = float(frame.at[entry_minute, "open"])
                exit_price = float(frame.at[exit_minute, "close"])
                if not (math.isfinite(entry) and math.isfinite(exit_price)):
                    continue
                controls.append({
                    "id": hashlib.sha256(
                        f"{key}|{day}|{entry_minute}".encode()
                    ).hexdigest()[:24],
                    "control_key": key,
                    "symbol": symbol,
                    "date": day,
                    "block": template["block"],
                    "direction": template["direction"],
                    "reference": template["reference"],
                    "horizon_minutes": template["horizon_minutes"],
                    "entry_minute": entry_minute,
                    "exit_minute": exit_minute,
                    "signed_return": sign * (exit_price / entry - 1.0),
                    "daily_weighting_stage": "average opportunities within date and control key first",
                })
    return controls


def run_pilot(result_dir: Path = RESULT_DIR) -> dict:
    R.validate(result_dir)
    reference_days, pilot_days, schedule = pilot_sessions()
    all_days = reference_days + pilot_days
    bars = _load_bars(all_days[0], all_days[-1])
    frames = _day_frames(bars)

    events, outcomes, censors = [], [], []
    opening_history_coverage = {"open5": Counter(), "open15": Counter()}
    settings_by_id = {setting["id"]: setting for setting in R.SETTINGS}
    day_position = {day: index for index, day in enumerate(all_days)}
    for symbol in PILOT_SYMBOLS:
        for day in pilot_days:
            position = day_position[day]
            prior20 = all_days[position - 20 : position]
            prior_day = all_days[position - 1]
            minutes = _session_minutes(schedule.loc[day])
            frame = frames.get((symbol, day))
            if frame is None:
                for setting in R.SETTINGS:
                    for direction in ("long", "short"):
                        censors.append({
                            "id": f"{setting['id']}__{symbol}__{day}__{direction.upper()}",
                            "kind": "event", "setting_id": setting["id"], "symbol": symbol,
                            "date": day, "direction": direction, "reason": "SESSION_MISSING",
                        })
                continue
            opening5 = minutes[:5]
            opening15 = minutes[:15]
            rvol5, rvol5_status = _rvol_status(frames, symbol, day, prior20, opening5)
            rvol15, rvol15_status = _rvol_status(frames, symbol, day, prior20, opening15)
            opening_history_coverage["open5"][rvol5_status] += 1
            opening_history_coverage["open15"][rvol15_status] += 1
            daily_atr = _daily_atr14(frames, symbol, prior20, schedule)
            minute_atr = _minute_atr_series(frames, symbol, day, prior_day, schedule)
            vwap = _vwap_series(frame, minutes)
            previous_frame = frames.get((symbol, prior_day))
            previous_minutes = _session_minutes(schedule.loc[prior_day])
            previous_close = (
                float(previous_frame.loc[previous_minutes[-1], "close"])
                if _complete(previous_frame, [previous_minutes[-1]], ("close",)) else None
            )

            for setting in R.SETTINGS:
                family = setting["family"]
                details_by_side = defaultdict(dict)
                if family == "opening_range":
                    selected_rvol = rvol5 if setting["opening_minutes"] == 5 else rvol15
                    found, reasons = _opening_range_events(setting, frame, minutes, selected_rvol)
                elif family == "high_low_breakout":
                    found, reasons = _high_low_events(setting, frame, minutes, rvol5, vwap)
                elif family == "failed_opening_range":
                    found, reasons = _failed_opening_range_events(frame, minutes)
                elif family == "first_pullback":
                    found, reasons = {}, {}
                    for direction in ("long", "short"):
                        minute, reason, details = _first_pullback_event(
                            setting, direction, frame, minutes, minute_atr, daily_atr, vwap
                        )
                        if minute is None:
                            reasons[direction] = reason
                        else:
                            found[direction] = minute
                            details_by_side[direction] = details
                elif family == "late_continuation":
                    found, reasons = {}, {}
                    for direction in ("long", "short"):
                        minute, reason = _late_event(frame, minutes, previous_close, direction)
                        if minute is None:
                            reasons[direction] = reason
                        else:
                            found[direction] = minute
                else:
                    raise RuntimeError(f"unimplemented registered family: {family}")

                for direction in ("long", "short"):
                    event_id = f"{setting['id']}__{symbol}__{day}__{direction.upper()}"
                    if direction not in found:
                        censors.append({
                            "id": event_id, "kind": "event", "setting_id": setting["id"],
                            "family": family, "symbol": symbol, "date": day,
                            "direction": direction, "reason": reasons[direction],
                        })
                        continue
                    event = {
                        "id": event_id,
                        "setting_id": setting["id"],
                        "family": family,
                        "symbol": symbol,
                        "date": day,
                        "block": _block(day),
                        "direction": direction,
                        "signal_minute": found[direction],
                        "signal_completed_time_pacific": _pacific_instant(day, found[direction] + 1),
                        "session_type": _session_type(minutes),
                        "details": details_by_side[direction],
                    }
                    events.append(event)
                    event_outcomes, outcome_censors = _event_outcomes(
                        event, frame, minutes, settings_by_id[event["setting_id"]]
                    )
                    outcomes.extend(event_outcomes)
                    censors.extend(outcome_censors)

    controls = _build_controls(outcomes, frames, pilot_days, schedule)
    result_dir.mkdir(parents=True, exist_ok=True)
    artifact_specs = (
        ("pilot-events.jsonl", events),
        ("pilot-responses.jsonl", outcomes),
        ("pilot-controls.jsonl", controls),
        ("pilot-censors.jsonl", censors),
    )
    fingerprints = {}
    row_counts = {}
    for name, rows in artifact_specs:
        count, digest = _write_jsonl(result_dir / name, rows)
        fingerprints[name] = digest
        row_counts[name] = count

    family_event_counts = Counter(event["family"] for event in events)
    setting_event_counts = Counter(event["setting_id"] for event in events)
    direction_event_counts = Counter(event["direction"] for event in events)
    event_censor_reasons = Counter(
        row["reason"] for row in censors if row["kind"] == "event"
    )
    unavailable_families = []
    first_pullback_unavailable = event_censor_reasons["FIRST_PULLBACK_REQUIRED_HISTORY_UNAVAILABLE"]
    if family_event_counts["first_pullback"] == 0 and first_pullback_unavailable:
        unavailable_families.append({
            "family": "first_pullback",
            "reason": (
                "faithful impulse, ATR, VWAP, and pullback geometry requires uninterrupted "
                "scheduled one-minute history; the primary bar source has missing intervals"
            ),
            "censored_attempts": first_pullback_unavailable,
        })
    summary = {
        "study_id": R.STUDY_ID,
        "run_kind": "three-symbol 30-session deterministic pilot",
        "source": "registered primary EQUS.MINI one-minute bars",
        "runner_sha256": R.sha256_file(Path(__file__).resolve()),
        "registration_sha256": R.sha256_file(result_dir / "run-registration.json"),
        "network_used": False,
        "spend_usd": 0.0,
        "symbols": list(PILOT_SYMBOLS),
        "reference_sessions": {"count": 20, "first": reference_days[0], "last": reference_days[-1]},
        "pilot_sessions": {"count": 30, "first": pilot_days[0], "last": pilot_days[-1]},
        "timezone_for_displayed_instants": "America/Los_Angeles",
        "families_attempted": sorted({setting["family"] for setting in R.SETTINGS}),
        "families_unavailable": unavailable_families,
        "opening_history_coverage": {
            window: dict(sorted(counts.items()))
            for window, counts in opening_history_coverage.items()
        },
        "event_counts_by_family": dict(sorted(family_event_counts.items())),
        "event_counts_by_setting": dict(sorted(setting_event_counts.items())),
        "event_counts_by_direction": dict(sorted(direction_event_counts.items())),
        "event_censor_reasons": dict(sorted(event_censor_reasons.items())),
        "row_counts": row_counts,
        "artifact_sha256": fingerprints,
        "notes": [
            "First eligible event only per setting, symbol, day, and direction.",
            "Responses are movement measurements, not verified fills or portfolio profit.",
            "Control rows are ordinary same-symbol opportunities grouped for later daily-first weighting.",
            "No ranking or setting selection is performed by this pilot.",
        ],
    }
    _write_json(result_dir / "pilot-summary.json", summary)
    print(json.dumps({
        "pilot_summary": str(result_dir / "pilot-summary.json"),
        "events": len(events),
        "responses": len(outcomes),
        "controls": len(controls),
        "censors": len(censors),
        "families_unavailable": summary["families_unavailable"],
    }, sort_keys=True))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("pilot", "full"))
    parser.add_argument("--result-dir", type=Path, default=RESULT_DIR)
    parser.add_argument("--smoke", action="store_true", help="run a bounded full-path smoke")
    args = parser.parse_args()
    if args.command == "pilot":
        if args.smoke:
            parser.error("--smoke is only valid with the full command")
        run_pilot(args.result_dir)
    else:
        from trading_edge_full import run_full
        with _exclusive_full_run(args.result_dir):
            run_full(args.result_dir, smoke=args.smoke)


if __name__ == "__main__":
    main()
