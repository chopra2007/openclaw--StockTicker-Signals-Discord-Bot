#!/usr/bin/env python3
"""TODO #103 - the trade-path engine.

Given a signal panel and a frozen policy, walks each trade minute by minute and
returns the exit that a real trader would have got. Nothing here chooses a
threshold; every number comes from the policy dictionary.

Frozen fill rules (see frozen-policy.md):
  * A minute with no bar cannot fill anything. No later bar is back-dated.
  * A bar whose open is already past the stop fills at that open.
  * A bar whose open is already past the target fills at that open.
  * A bar that touches both the target and the stop counts as the STOP.
  * A bar with zero volume cannot fill anything.
  * The time exit fills at the open of the first bar with volume at or after the
    maximum holding minute, searching forward at most TIME_EXIT_SEARCH minutes.
    If there is none, the trade is unresolvable and is reported, not counted.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

TIME_EXIT_SEARCH = 40  # minutes; past this the exit is not a 30-minute hold


def bar_lookup(bars):
    """(date, symbol) -> {minute: (open, high, low, close, volume)}"""
    b = bars.sort_values(["date", "symbol", "minute"])
    out = {}
    cols = b[["open", "high", "low", "close", "volume"]].to_numpy()
    keys = list(zip(b.date.to_numpy(), b.symbol.astype(str).to_numpy()))
    mins = b.minute.to_numpy()
    cur, d = None, None
    for i, k in enumerate(keys):
        if k != cur:
            cur = k
            d = out.setdefault(k, {})
        d[int(mins[i])] = cols[i]
    return out


def walk_trade(day_bars, side, entry_minute, entry_px, stop_px, target_px, hold):
    """Return (exit_price, exit_minute, exit_kind) or None if unresolvable."""
    last = entry_minute + hold
    # The maximum holding minute itself is the timed exit and nothing else. It
    # must not be scanned for a stop or target first: the trader is already out
    # at that bar's open, so a level touched later inside it never reaches him.
    for m in range(entry_minute + 1, last):
        bar = day_bars.get(m)
        if bar is None:
            continue
        o, h, lo, c, v = bar
        if v <= 0:
            continue
        if side > 0:
            if o <= stop_px:
                return o, m, "stop_gap"
            if o >= target_px:
                return o, m, "target_gap"
            hit_stop = lo <= stop_px
            hit_target = h >= target_px
        else:
            if o >= stop_px:
                return o, m, "stop_gap"
            if o <= target_px:
                return o, m, "target_gap"
            hit_stop = h >= stop_px
            hit_target = lo <= target_px
        if hit_stop:                      # stop wins every ambiguous bar
            return stop_px, m, "stop"
        if hit_target:
            return target_px, m, "target"
    for m in range(last, last + TIME_EXIT_SEARCH + 1):  # never silently dropped
        bar = day_bars.get(m)
        if bar is not None and bar[4] > 0:
            return bar[0], m, "time"
    return None


def run_rule(panel, lookup, policy, rule, cost_bps=None, entry_delay=0, hold=None,
             ignore_extreme_bar=False, price_lookup=None):
    """One frozen rule over one panel. Returns a trade-level DataFrame.

    `price_lookup` lets the identical trade list be repriced from the second
    feed without re-selecting anything.
    """
    per_side_cap = policy["per_side_cap"]
    target_k = policy["target_k"]
    stop_k = policy["stop_k"]
    hold = policy["hold_minutes"] if hold is None else hold
    cost = policy["cost_bps"] if cost_bps is None else cost_bps
    borrow_bps = policy["short_borrow_bps_per_hold"]
    entry_minute = (policy["entry_minute_confirmed"] if rule["confirmed"]
                    else policy["entry_minute_direct"]) + entry_delay
    prices = lookup if price_lookup is None else price_lookup

    el = panel[panel.eligible].copy()
    if ignore_extreme_bar:
        side_mask = (el.dev < 0) if rule["move"] == "down" else (el.dev > 0)
    else:
        side_mask = el.extreme_down if rule["move"] == "down" else el.extreme_up
    cand = el[side_mask].copy()
    if cand.empty:
        return pd.DataFrame()
    cand["abs_dev"] = cand.dev.abs()
    cand = cand.sort_values(["date", "abs_dev", "win_dollar_volume", "symbol"],
                            ascending=[True, False, False, True])
    cand["rank_side"] = cand.groupby("date").cumcount() + 1
    cand = cand[cand.rank_side <= per_side_cap]

    rows = []
    for r in cand.itertuples():
        day = lookup.get((r.date, r.symbol))
        pday = prices.get((r.date, r.symbol))
        if day is None or pday is None:
            continue

        if rule["confirmed"]:
            ok = True
            for m in (policy["stab_minute_1"], policy["stab_minute_2"]):
                bar = day.get(m)
                if bar is None or bar[4] <= 0:
                    ok = False
                    break
                if rule["move"] == "down" and bar[2] < r.win_low:
                    ok = False
                    break
                if rule["move"] == "up" and bar[1] > r.win_high:
                    ok = False
                    break
            if ok:
                last = day.get(policy["stab_minute_2"])
                turned = (last[3] > r.p1) if rule["move"] == "down" else (last[3] < r.p1)
                ok = bool(turned)
            if not ok:
                continue

        ebar = pday.get(entry_minute)
        if ebar is None or ebar[4] <= 0:
            continue
        entry_px = float(ebar[0])
        if entry_px <= 0:
            continue

        side = 1 if rule["direction"] == "long" else -1
        R = float(r.risk_unit)
        target_px = entry_px * (1 + side * target_k * R)
        stop_px = entry_px * (1 - side * stop_k * R)

        res = walk_trade(pday, side, entry_minute, entry_px, stop_px, target_px, hold)
        if res is None:
            rows.append({"date": r.date, "symbol": r.symbol, "unresolvable": True})
            continue
        exit_px, exit_min, kind = res
        gross = side * (exit_px / entry_px - 1.0) * 1e4
        net = gross - cost - (borrow_bps if side < 0 else 0.0)
        rows.append({
            "date": r.date, "symbol": r.symbol, "dev_bps": r.dev * 1e4,
            "extreme_bar_bps": r.extreme_bar * 1e4, "risk_unit_bps": R * 1e4,
            "side": side, "entry_minute": entry_minute, "entry_px": entry_px,
            "stop_px": stop_px, "target_px": target_px, "exit_px": exit_px,
            "exit_minute": exit_min, "exit_kind": kind,
            "gross_bps": gross, "net_bps": net,
            "stop_dist_frac": stop_k * R,
            "pre_entry_minute_dollar_volume": r.pre_entry_minute_dollar_volume,
            "win_dollar_volume": r.win_dollar_volume,
            "unresolvable": False,
        })
    return pd.DataFrame(rows)
