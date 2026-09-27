#!/usr/bin/env python3
"""Deterministic analysis helpers for the registered E1 event-response study.

The functions in this module are deliberately data-source agnostic.  They
consume event outcomes and daily control aggregates that have already passed
the E1 masks.  They never read market data, use the network, or spend money.

Returns are decimal returns: one basis point is 0.0001.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from datetime import date
from statistics import mean, stdev
from typing import Iterable, Mapping, Sequence


BASIS_POINT = 0.0001
POWER_EFFECTS_BPS = (3, 5, 8, 12)
BOOTSTRAP_SEED = 20260925
BOOTSTRAP_DRAWS = 10_000
Z_ONE_SIDED_95 = 1.6448536269514722
Z_POWER_80 = 0.8416212335729143


def _finite(value: object, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _week(day: str) -> str:
    parsed = date.fromisoformat(day.split("#", 1)[0])
    year, week, _ = parsed.isocalendar()
    return f"{year:04d}-W{week:02d}"


def _cell_id(row: Mapping[str, object]) -> str:
    if row.get("cell_id"):
        return str(row["cell_id"])
    required = ("setting_id", "direction", "horizon_minutes")
    missing = [field for field in required if field not in row]
    if missing:
        raise KeyError(f"row needs cell_id or {', '.join(required)}")
    reference = str(row.get("reference", "next_minute"))
    return "__".join(
        (str(row["setting_id"]), str(row["direction"]),
         f"H{int(row['horizon_minutes'])}", reference)
    )


def _daily_control_means(
    controls: Iterable[Mapping[str, object]], value_field: str
) -> dict[str, float]:
    """Weight each available control date once for each control key."""
    by_key_date: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in controls:
        key = str(row["control_key"])
        day = str(row["date"])
        by_key_date[(key, day)].append(_finite(row[value_field], value_field))
    daily = defaultdict(list)
    for (key, _day), values in by_key_date.items():
        daily[key].append(mean(values))
    return {key: mean(values) for key, values in daily.items()}


def _date_first(
    rows: Iterable[Mapping[str, object]], value_field: str
) -> list[dict]:
    by_cell_date: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        by_cell_date[(_cell_id(row), str(row["date"]))].append(row)
    result = []
    for (cell_id, day), members in sorted(by_cell_date.items()):
        values = [_finite(row[value_field], value_field) for row in members]
        symbols = sorted({str(row["symbol"]) for row in members})
        blocks = sorted({str(row["block"]) for row in members})
        if len(blocks) != 1:
            raise ValueError(f"cell/date crosses development blocks: {cell_id} {day}")
        result.append({
            "cell_id": cell_id,
            "date": day,
            "week": _week(day),
            "block": blocks[0],
            "event_count": len(members),
            "symbol_count": len(symbols),
            "symbols": symbols,
            value_field: mean(values),
        })
    return result


def date_first_plain_excess(
    events: Iterable[Mapping[str, object]],
    daily_controls: Iterable[Mapping[str, object]],
) -> list[dict]:
    """Return daily cell observations after date-first ordinary controls.

    A control row may already be a daily aggregate.  Duplicate rows for the
    same key/date are safely averaged again.  Events without an available
    control mean are omitted rather than assigned a favorable value.
    """
    controls = _daily_control_means(daily_controls, "signed_return")
    enriched = []
    for row in events:
        key = str(row["control_key"])
        if key not in controls:
            continue
        item = dict(row)
        item["plain_control_mean"] = controls[key]
        item["plain_excess"] = (
            _finite(row["signed_return"], "signed_return") - controls[key]
        )
        enriched.append(item)
    daily = _date_first(enriched, "plain_excess")
    by_cell_date: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in enriched:
        by_cell_date[(_cell_id(row), str(row["date"]))].append(row)
    for row in daily:
        members = by_cell_date[(row["cell_id"], row["date"])]
        row["raw_signed_return"] = mean(
            _finite(item["signed_return"], "signed_return") for item in members
        )
        row["plain_control_mean"] = mean(
            _finite(item["plain_control_mean"], "plain_control_mean") for item in members
        )
    return daily


def leave_one_stock_out_residual_excess(
    events: Iterable[Mapping[str, object]],
    daily_controls: Iterable[Mapping[str, object]],
) -> list[dict]:
    """Return date-first market-adjusted information excess.

    Event rows need ``signed_loo_panel_return``.  Daily controls may provide
    ``residual_return`` directly, or the same signed return/panel pair.  A
    missing panel path remains unresolved and is not replaced with zero.
    """
    prepared_controls = []
    for row in daily_controls:
        item = dict(row)
        if "residual_return" not in item:
            if "signed_loo_panel_return" not in item:
                continue
            item["residual_return"] = (
                _finite(item["signed_return"], "signed_return")
                - _finite(item["signed_loo_panel_return"], "signed_loo_panel_return")
            )
        prepared_controls.append(item)
    controls = _daily_control_means(prepared_controls, "residual_return")
    enriched = []
    for row in events:
        key = str(row["control_key"])
        if key not in controls or "signed_loo_panel_return" not in row:
            continue
        event_residual = (
            _finite(row["signed_return"], "signed_return")
            - _finite(row["signed_loo_panel_return"], "signed_loo_panel_return")
        )
        item = dict(row)
        item["market_residual"] = event_residual
        item["market_control_mean_residual"] = controls[key]
        item["market_adjusted_excess"] = event_residual - controls[key]
        enriched.append(item)
    daily = _date_first(enriched, "market_adjusted_excess")
    by_cell_date: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in enriched:
        by_cell_date[(_cell_id(row), str(row["date"]))].append(row)
    for row in daily:
        members = by_cell_date[(row["cell_id"], row["date"])]
        row["market_residual"] = mean(
            _finite(item["market_residual"], "market_residual") for item in members
        )
        row["market_control_mean_residual"] = mean(
            _finite(item["market_control_mean_residual"], "market_control_mean_residual")
            for item in members
        )
    return daily


def five_block_summaries(
    daily_rows: Iterable[Mapping[str, object]], value_field: str
) -> list[dict]:
    """Summarize all five registered blocks per cell, including empty blocks."""
    materialized = list(daily_rows)
    cells = sorted({str(row.get("cell_id", "ALL")) for row in materialized}) or ["ALL"]
    grouped: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in materialized:
        grouped[(str(row.get("cell_id", "ALL")), str(row["block"]))].append(row)
    summaries = []
    for cell in cells:
        for block in ("B1", "B2", "B3", "B4", "B5"):
            rows = grouped.get((cell, block), [])
            values = [_finite(row[value_field], value_field) for row in rows]
            summary = {
                "block": block,
                "dates": len({str(row["date"]) for row in rows}),
                "observations": len(rows),
                "mean": mean(values) if values else None,
                "positive": mean(values) > 0 if values else None,
            }
            if cell != "ALL":
                summary["cell_id"] = cell
            summaries.append(summary)
    return summaries


def remove_top_three_positive_symbol_days(
    rows: Iterable[Mapping[str, object]], value_field: str
) -> dict:
    """Remove every row belonging to the three strongest positive symbol-days."""
    materialized = [dict(row) for row in rows]
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in materialized:
        grouped[(str(row["symbol"]), str(row["date"]))].append(
            _finite(row[value_field], value_field)
        )
    ranked = sorted(
        ((mean(values), symbol, day) for (symbol, day), values in grouped.items()
         if mean(values) > 0),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    removed = {(symbol, day) for _value, symbol, day in ranked[:3]}
    kept = [
        row for row in materialized
        if (str(row["symbol"]), str(row["date"])) not in removed
    ]
    kept_values = [_finite(row[value_field], value_field) for row in kept]
    return {
        "removed_symbol_days": [
            {"symbol": symbol, "date": day, "mean": value}
            for value, symbol, day in ranked[:3]
        ],
        "remaining_rows": kept,
        "remaining_mean": mean(kept_values) if kept_values else None,
        "remains_positive": mean(kept_values) > 0 if kept_values else None,
    }


def _percentile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot take a percentile of no values")
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def week_cluster_bootstrap(
    events: Sequence[Mapping[str, object]],
    daily_controls: Sequence[Mapping[str, object]],
    *,
    metric: str = "plain",
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = BOOTSTRAP_SEED,
) -> dict:
    """Resample whole calendar weeks jointly and recompute control means.

    The returned lower bound is the registered one-sided 80% bound, or the
    20th percentile of bootstrap means.
    """
    if draws <= 0:
        raise ValueError("draws must be positive")
    event_weeks = defaultdict(list)
    control_weeks = defaultdict(list)
    for row in events:
        event_weeks[_week(str(row["date"]))].append(row)
    for row in daily_controls:
        control_weeks[_week(str(row["date"]))].append(row)
    weeks = sorted(set(event_weeks) | set(control_weeks))
    if not weeks:
        raise ValueError("bootstrap needs at least one calendar week")
    analyzer = (
        date_first_plain_excess if metric == "plain"
        else leave_one_stock_out_residual_excess
        if metric == "market_adjusted"
        else None
    )
    value_field = "plain_excess" if metric == "plain" else "market_adjusted_excess"
    if analyzer is None:
        raise ValueError("metric must be plain or market_adjusted")

    observed_rows = analyzer(events, daily_controls)
    observed = mean([row[value_field] for row in observed_rows]) if observed_rows else None
    # The direct formulation copied every event and control row for every draw,
    # then rebuilt the same date groups.  Full E1 controls contain millions of
    # rows, making that mathematically correct approach impractically slow.
    # Reduce each week to the sufficient statistics used by the analyzers.  A
    # sampled week still counts once per selection, exactly as the replicate
    # date tags above did, without copying its underlying rows.
    control_value_field = "signed_return" if metric == "plain" else "residual_return"
    prepared_controls = []
    for row in daily_controls:
        item = row
        if metric == "market_adjusted" and "residual_return" not in item:
            if "signed_loo_panel_return" not in item:
                continue
            item = dict(item)
            item["residual_return"] = (
                _finite(item["signed_return"], "signed_return")
                - _finite(item["signed_loo_panel_return"], "signed_loo_panel_return")
            )
        prepared_controls.append(item)

    control_by_key_date: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in prepared_controls:
        control_by_key_date[(str(row["control_key"]), str(row["date"]))].append(
            _finite(row[control_value_field], control_value_field)
        )
    controls_by_week_values: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for (key, day), values in control_by_key_date.items():
        controls_by_week_values[_week(day)][key].append(mean(values))
    controls_by_week = {
        week: {
            key: (sum(values), len(values)) for key, values in keyed.items()
        }
        for week, keyed in controls_by_week_values.items()
    }

    possible_control_keys = {key for key, _day in control_by_key_date}
    event_group_values: dict[str, dict[tuple[str, str], dict[str, list[float]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    for row in events:
        key = str(row["control_key"])
        if key not in possible_control_keys:
            continue
        if metric == "plain":
            event_value = _finite(row["signed_return"], "signed_return")
        else:
            if "signed_loo_panel_return" not in row:
                continue
            event_value = (
                _finite(row["signed_return"], "signed_return")
                - _finite(row["signed_loo_panel_return"], "signed_loo_panel_return")
            )
        day = str(row["date"])
        event_group_values[_week(day)][(_cell_id(row), day)][key].append(event_value)
    event_groups = {
        week: {
            group: {
                key: (sum(values), len(values)) for key, values in keyed.items()
            }
            for group, keyed in groups.items()
        }
        for week, groups in event_group_values.items()
    }

    rng = random.Random(seed)
    boot_means = []
    for _ in range(draws):
        selected_counts: dict[str, int] = defaultdict(int)
        for selected in rng.choices(weeks, k=len(weeks)):
            selected_counts[selected] += 1
        sampled_control_totals: dict[str, list[float | int]] = defaultdict(
            lambda: [0.0, 0]
        )
        for selected, multiplicity in selected_counts.items():
            for key, (value_sum, value_count) in controls_by_week.get(selected, {}).items():
                sampled_control_totals[key][0] += value_sum * multiplicity
                sampled_control_totals[key][1] += value_count * multiplicity
        sampled_control_means = {
            key: total / count
            for key, (total, count) in sampled_control_totals.items()
        }

        daily_sum = 0.0
        daily_count = 0
        for selected, multiplicity in selected_counts.items():
            for groups in event_groups.get(selected, {}).values():
                total = 0
                excess_sum = 0.0
                for key, (value_sum, value_count) in groups.items():
                    if key not in sampled_control_means:
                        continue
                    total += value_count
                    excess_sum += value_sum - value_count * sampled_control_means[key]
                if total:
                    daily_sum += multiplicity * excess_sum / total
                    daily_count += multiplicity
        if daily_count:
            boot_means.append(daily_sum / daily_count)
    if not boot_means:
        raise ValueError("no bootstrap draw had resolved event and control rows")
    return {
        "metric": metric,
        "seed": seed,
        "draws_requested": draws,
        "draws_resolved": len(boot_means),
        "weeks": len(weeks),
        "observed_mean": observed,
        "lower_80": _percentile(boot_means, 0.20),
        "median": _percentile(boot_means, 0.50),
        "upper_80": _percentile(boot_means, 0.80),
    }


def power_day_week_estimates(
    daily_rows: Iterable[Mapping[str, object]], value_field: str
) -> list[dict]:
    """Estimate observations needed for 80% power at 3/5/8/12 basis points."""
    rows = list(daily_rows)
    daily_values = [_finite(row[value_field], value_field) for row in rows]
    by_week: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_week[_week(str(row["date"]))].append(_finite(row[value_field], value_field))
    weekly_values = [mean(values) for _week_id, values in sorted(by_week.items())]
    daily_sd = stdev(daily_values) if len(daily_values) >= 2 else None
    weekly_sd = stdev(weekly_values) if len(weekly_values) >= 2 else None
    multiplier = (Z_ONE_SIDED_95 + Z_POWER_80) ** 2

    def needed(sd_value: float | None, effect: float) -> int | None:
        if sd_value is None:
            return None
        if sd_value == 0:
            return 1
        return max(1, math.ceil(multiplier * (sd_value / effect) ** 2))

    return [{
        "effect_bps": effect_bps,
        "effect_decimal": effect_bps * BASIS_POINT,
        "observed_days": len(daily_values),
        "observed_weeks": len(weekly_values),
        "daily_standard_deviation": daily_sd,
        "weekly_standard_deviation": weekly_sd,
        "required_days": needed(daily_sd, effect_bps * BASIS_POINT),
        "required_weeks": needed(weekly_sd, effect_bps * BASIS_POINT),
        "alpha_one_sided": 0.05,
        "power": 0.80,
    } for effect_bps in POWER_EFFECTS_BPS]


def benjamini_hochberg_qvalues(
    rows: Iterable[Mapping[str, object]], *, p_field: str = "p_value"
) -> list[dict]:
    """Attach deterministic Benjamini-Hochberg diagnostic q-values."""
    materialized = [dict(row) for row in rows]
    indexed = []
    for index, row in enumerate(materialized):
        p_value = _finite(row[p_field], p_field)
        if not 0 <= p_value <= 1:
            raise ValueError("p-values must be between zero and one")
        indexed.append((p_value, str(row.get("cell_id", "")), index))
    indexed.sort(key=lambda item: (item[0], item[1], item[2]))
    count = len(indexed)
    running = 1.0
    q_by_index = {}
    for rank_index in range(count - 1, -1, -1):
        p_value, _cell, original = indexed[rank_index]
        rank = rank_index + 1
        running = min(running, p_value * count / rank)
        q_by_index[original] = min(1.0, running)
    for index, row in enumerate(materialized):
        row["bh_q_value"] = q_by_index[index]
    return materialized


def registered_cost_floor_bps(
    entry_minute: int, exit_minute: int, regular_open_minute: int
) -> int:
    """Return 8 bps if either leg is in the first hour, otherwise 5 bps."""
    first_hour = range(int(regular_open_minute), int(regular_open_minute) + 60)
    return 8 if int(entry_minute) in first_hour or int(exit_minute) in first_hour else 5


def registered_cost_stresses(floor_bps: int) -> dict[str, int]:
    floor = int(floor_bps)
    if floor not in (5, 8):
        raise ValueError("registered floor must be 5 or 8 basis points")
    return {"floor_bps": floor, "stress_20_bps": 20, "stress_twice_floor_bps": 2 * floor}


def actual_net_excess(
    event_returns: Iterable[float], event_costs_bps: Iterable[float],
    control_returns: Iterable[float], control_costs_bps: Iterable[float],
) -> float:
    """Charge each ledger once, then subtract control net from event net."""
    event_returns = [_finite(value, "event_return") for value in event_returns]
    event_costs = [_finite(value, "event_cost_bps") for value in event_costs_bps]
    control_returns = [_finite(value, "control_return") for value in control_returns]
    control_costs = [_finite(value, "control_cost_bps") for value in control_costs_bps]
    if not event_returns or not control_returns:
        raise ValueError("event and control ledgers must both be nonempty")
    if len(event_returns) != len(event_costs) or len(control_returns) != len(control_costs):
        raise ValueError("each return needs exactly one cost")
    event_net = mean(
        value - cost * BASIS_POINT for value, cost in zip(event_returns, event_costs)
    )
    control_net = mean(
        value - cost * BASIS_POINT for value, cost in zip(control_returns, control_costs)
    )
    return event_net - control_net


def effective_variant_groups(
    rows: Iterable[Mapping[str, object]],
    *,
    setting_field: str = "setting_id",
    decision_fields: Sequence[str] = ("symbol", "date", "direction", "signal_minute"),
    attempted_settings: Iterable[str] = (),
) -> list[dict]:
    """Group attempted settings that produced exactly the same decisions."""
    decisions: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    attempted = {str(setting) for setting in attempted_settings}
    for row in rows:
        setting = str(row[setting_field])
        attempted.add(setting)
        decisions[setting].add(tuple(str(row[field]) for field in decision_fields))
    signatures: dict[tuple[tuple[str, ...], ...], list[str]] = defaultdict(list)
    for setting in sorted(attempted):
        signatures[tuple(sorted(decisions[setting]))].append(setting)
    result = []
    ordered = sorted(signatures.items(), key=lambda item: item[1][0])
    for signature, labels in ordered:
        digest = hashlib.sha256(repr(signature).encode("utf-8")).hexdigest()[:12]
        result.append({
            "decision_group": f"DG_{digest}",
            "attempted_setting_ids": labels,
            "representative_setting_id": labels[0],
            "decision_count": len(signature),
        })
    return result


def deterministic_top_five(
    candidates: Iterable[Mapping[str, object]],
    *,
    score_field: str = "selection_lower_80",
) -> list[dict]:
    """Select up to five candidates with registered family/group caps."""
    eligible = [dict(row) for row in candidates if bool(row.get("eligible", True))]
    eligible.sort(key=lambda row: (
        -_finite(row[score_field], score_field),
        str(row["setting_id"]),
        str(row["direction"]),
    ))
    family_counts: dict[str, int] = defaultdict(int)
    used_groups = set()
    selected = []
    for row in eligible:
        family = str(row["family"])
        group = str(row["decision_group"])
        if family_counts[family] >= 2 or group in used_groups:
            continue
        row["selection_rank"] = len(selected) + 1
        selected.append(row)
        family_counts[family] += 1
        used_groups.add(group)
        if len(selected) == 5:
            break
    return selected
