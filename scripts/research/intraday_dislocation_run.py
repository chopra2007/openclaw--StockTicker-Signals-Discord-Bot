#!/usr/bin/env python3
"""TODO #103 - run the six frozen rules and every gate check.

Refuses to run unless the frozen policy file's hash matches its recorded
fingerprint, so no result can be produced from a policy that was edited after
the fact.

Local files only. No network.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from intraday_dislocation_common import RES_DIR  # noqa: E402
from intraday_dislocation_engine import bar_lookup, run_rule  # noqa: E402
from intraday_dislocation_gates import SEED, profit_factor, summarise  # noqa: E402

POLICY_MD = RES_DIR / "frozen-policy.md"
POLICY_SHA = RES_DIR / "frozen-policy.sha256"
POLICY_JSON = RES_DIR / "frozen-policy.json"

RULES = {
    "1_direct_reversal_down_buy":
        {"move": "down", "direction": "long", "confirmed": False},
    "2_direct_reversal_up_short":
        {"move": "up", "direction": "short", "confirmed": False},
    "3_confirmed_reversal_down_buy":
        {"move": "down", "direction": "long", "confirmed": True},
    "4_confirmed_reversal_up_short":
        {"move": "up", "direction": "short", "confirmed": True},
    "5_continuation_down_short":
        {"move": "down", "direction": "short", "confirmed": False},
    "6_continuation_up_buy":
        {"move": "up", "direction": "long", "confirmed": False},
}


def check_policy():
    got = hashlib.sha256(POLICY_MD.read_bytes()).hexdigest()
    want = POLICY_SHA.read_text().split()[0].strip()
    if got != want:
        raise SystemExit(
            f"FROZEN POLICY MISMATCH\n  recorded {want}\n  actual   {got}\n"
            "The policy file changed after it was frozen. No result may be produced.")
    return json.loads(POLICY_JSON.read_text())


def build_controls(panel, trades, rule, policy, seed=SEED):
    """Two frozen comparison groups, one matched row per real trade.

    A: a NON-extreme stock on the SAME DATE, same sign of move, nearest trailing
       residual scale.
    B: the SAME STOCK on an EARLIER date where it was eligible and non-extreme,
       same sign of move, nearest market move then nearest trailing scale.
    Both are then traded by the identical rule machinery.
    """
    rng = np.random.default_rng(seed)
    el = panel[panel.eligible].copy()
    sign = -1 if rule["move"] == "down" else 1
    quiet = el[(np.sign(el.dev) == sign) & (el.dev.abs() < el.extreme_bar)]
    if quiet.empty or trades.empty:
        return pd.DataFrame(), pd.DataFrame()

    by_date = {d: g for d, g in quiet.groupby("date")}
    by_symbol = {sym: g.sort_values("date") for sym, g in quiet.groupby("symbol")}
    src = panel.set_index(["date", "symbol"])

    rows_a, rows_b, used_a, used_b = [], [], set(), set()
    for t in trades.itertuples():
        try:
            base = src.loc[(t.date, t.symbol)]
        except KeyError:
            continue
        pool = by_date.get(t.date)
        if pool is not None:
            pool = pool[~pool.symbol.isin([t.symbol])]
            pool = pool[[(t.date, s) not in used_a for s in pool.symbol]]
            if not pool.empty:
                pick = pool.iloc[(pool.resid_scale - base.resid_scale).abs()
                                 .to_numpy().argmin()]
                used_a.add((pick.date, pick.symbol))
                rows_a.append(pick)
        pool = by_symbol.get(t.symbol)
        if pool is not None:
            pool = pool[pool.date < t.date]
            pool = pool[[(d, t.symbol) not in used_b for d in pool.date]]
            if not pool.empty:
                d1 = (pool.mkt_r - base.mkt_r).abs().to_numpy()
                d2 = (pool.resid_scale - base.resid_scale).abs().to_numpy()
                pick = pool.iloc[np.lexsort((d2, d1))[0]]
                used_b.add((pick.date, pick.symbol))
                rows_b.append(pick)
    mk = lambda rows: (pd.DataFrame(rows).reset_index(drop=True)
                       if rows else pd.DataFrame())
    return mk(rows_a), mk(rows_b)


def trade_controls(ctrl, lookup, policy, rule):
    if ctrl.empty:
        return pd.DataFrame()
    c = ctrl.copy()
    c["extreme_down"] = rule["move"] == "down"
    c["extreme_up"] = rule["move"] == "up"
    pol = dict(policy)
    pol["per_side_cap"] = 10_000
    return run_rule(c, lookup, pol, rule)


def run_all(panel, bars, policy, tag, pillar_bars=None, all_dates=None):
    lookup = bar_lookup(bars)
    plookup = bar_lookup(pillar_bars) if pillar_bars is not None else None
    results, trades_out = {}, {}
    for name, rule in RULES.items():
        t = run_rule(panel, lookup, policy, rule)
        trades_out[name] = t
        s = summarise(t, name, all_dates=all_dates,
                      capacity_frac=policy["capacity_frac_of_pre_entry_minute"])
        if t.empty:
            results[name] = s
            continue
        live = t[~t.unresolvable.fillna(False)]

        for c in policy["cost_scenarios_bps"]:
            alt = live.copy()
            alt["net_bps"] = (alt.gross_bps - c
                              - np.where(alt.side < 0,
                                         policy["short_borrow_bps_per_hold"], 0.0))
            s[f"net_mean_bps_at_{int(c)}bps_cost"] = float(alt.net_bps.mean())
            s[f"profit_factor_at_{int(c)}bps_cost"] = profit_factor(alt)

        for d in (1, 2):
            dt = run_rule(panel, lookup, policy, rule, entry_delay=d)
            s[f"net_mean_bps_entry_delay_{d}min"] = (
                float(dt.net_bps.mean()) if not dt.empty else np.nan)
            s[f"trades_entry_delay_{d}min"] = int(len(dt))

        ht = run_rule(panel, lookup, policy, rule, hold=policy["hold_minutes_stress"])
        s[f"net_mean_bps_hold_{policy['hold_minutes_stress']}min_STRESS_ONLY"] = (
            float(ht.net_bps.mean()) if not ht.empty else np.nan)

        ca, cb = build_controls(panel, live, rule, policy)
        for label, ctrl in (("same_date", ca), ("same_stock", cb)):
            ct = trade_controls(ctrl, lookup, policy, rule)
            s[f"control_{label}_trades"] = int(len(ct))
            s[f"control_{label}_net_mean_bps"] = (
                float(ct.net_bps.mean()) if not ct.empty else np.nan)
            s[f"beats_control_{label}"] = bool(
                not ct.empty and live.net_bps.mean() > ct.net_bps.mean())

        if plookup is not None:
            pt = run_rule(panel, lookup, policy, rule, price_lookup=plookup)
            if not pt.empty:
                pl = pt[~pt.unresolvable.fillna(False)]
                s["xnys_trades"] = int(len(pl))
                s["xnys_net_mean_bps"] = float(pl.net_bps.mean())
                alt = pl.copy()
                alt["net_bps"] = (alt.gross_bps - 35.0
                                  - np.where(alt.side < 0,
                                             policy["short_borrow_bps_per_hold"], 0.0))
                s["xnys_net_mean_bps_at_35bps_cost"] = float(alt.net_bps.mean())
        results[name] = s
    return results, trades_out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default=str(RES_DIR / "panel-dev.parquet"))
    ap.add_argument("--bars", default=str(RES_DIR / "bars-equs.parquet"))
    ap.add_argument("--out", default=str(RES_DIR / "development-results.json"))
    ap.add_argument("--trades-out", default=str(RES_DIR / "development-trades.parquet"))
    ap.add_argument("--tag", default="development")
    ap.add_argument("--allow-sealed", action="store_true")
    a = ap.parse_args()

    policy = check_policy()
    panel = pd.read_parquet(a.panel)
    if not a.allow_sealed and panel.date.max() > policy["development_last_date"]:
        raise SystemExit("panel contains profit-sealed dates and --allow-sealed was not given")

    bars = pd.read_parquet(a.bars)
    bars["symbol"] = bars.symbol.astype(str)
    keep = set(panel.date.unique())
    bars = bars[bars.date.isin(keep)]
    pillar = pd.read_parquet(RES_DIR / "bars-pillar.parquet")
    pillar["symbol"] = pillar.symbol.astype(str)
    pillar = pillar[pillar.date.isin(keep)]

    results, trades = run_all(panel, bars, policy, a.tag, pillar_bars=pillar,
                              all_dates=sorted(panel.date.unique()))
    out = {
        "tag": a.tag,
        "policy_sha256": POLICY_SHA.read_text().split()[0].strip(),
        "panel_first_date": panel.date.min(),
        "panel_last_date": panel.date.max(),
        "rules": results,
    }
    Path(a.out).write_text(json.dumps(out, indent=2, default=float))
    allt = pd.concat([t.assign(rule=k) for k, t in trades.items() if not t.empty],
                     ignore_index=True)
    allt.to_parquet(a.trades_out, index=False)

    print(f"{'rule':34s} {'n':>5s} {'gross':>8s} {'net':>8s} {'PF':>6s} {'win%':>6s}")
    for k, s in results.items():
        if s.get("trades", 0) == 0:
            print(f"{k:34s} {'0':>5s}")
            continue
        print(f"{k:34s} {s['trades']:5d} {s['gross_mean_bps']:8.2f} "
              f"{s['net_mean_bps']:8.2f} {s['profit_factor']:6.2f} "
              f"{s['win_rate']*100:6.1f}")


if __name__ == "__main__":
    main()
