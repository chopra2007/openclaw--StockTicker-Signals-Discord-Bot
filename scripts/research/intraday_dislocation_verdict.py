#!/usr/bin/env python3
"""TODO #103 - apply the twelve frozen development gates to the saved results.

Reads development-results.json and prints, for every rule, which gate failed
first. No gate is defined here that is not in frozen-policy.md section 12.
"""
import argparse
import json
from pathlib import Path

MIN_TRADES, MIN_DATES, MIN_SYMBOLS = 250, 100, 30
MIN_NET_BPS = 20.0
MIN_PROFIT_FACTOR = 1.30
MIN_BLOCKS_POSITIVE = 4
MIN_PF_AT_35 = 1.05
MAX_STOCK_SHARE = 0.15
MAX_FIVE_DATE_SHARE = 0.25
MAX_DRAWDOWN = 0.08
MIN_RETURN_OVER_DRAWDOWN = 1.0
EARLY_STOP_GROSS_BPS = 40.0


def gates(s):
    """Return the ordered list of (gate name, passed, detail)."""
    if s.get("trades", 0) == 0:
        return [("1 sample size", False, "no trades")]
    g = []
    g.append(("1 sample size",
              s["trades"] >= MIN_TRADES and s["dates"] >= MIN_DATES
              and s["symbols"] >= MIN_SYMBOLS,
              f"{s['trades']} trades / {s['dates']} dates / {s['symbols']} stocks"))
    g.append(("2 net average >= +20 bps", s["net_mean_bps"] >= MIN_NET_BPS,
              f"{s['net_mean_bps']:.2f} bps"))
    g.append(("3 profit factor >= 1.30", s["profit_factor"] >= MIN_PROFIT_FACTOR,
              f"{s['profit_factor']:.3f}"))
    lo = s["net_mean_ci95"][0]
    g.append(("4 95% lower bound above zero", lo is not None and lo > 0,
              f"lower bound {lo:.2f} bps"))
    g.append(("4b 99.167% one-sided lower bound above zero",
              s.get("net_mean_one_sided_99167_lower", float("-inf")) > 0,
              f"{s.get('net_mean_one_sided_99167_lower', float('nan')):.2f} bps"))
    wlo = s["win_rate_ci95"][0]
    be = s["break_even_win_rate"]
    g.append(("5 win-rate lower bound above break-even",
              wlo is not None and be is not None and wlo > be,
              f"win rate {s['win_rate']*100:.1f}% (lower bound {wlo*100:.1f}%) "
              f"vs break-even {be*100:.1f}%"))
    pos = sum(1 for b in s["walk_forward"]
              if b["trades"] > 0 and b["mean_net_bps"] > 0)
    g.append((f"6 positive in >= {MIN_BLOCKS_POSITIVE} of 5 blocks",
              pos >= MIN_BLOCKS_POSITIVE,
              f"{pos} of {len(s['walk_forward'])} blocks positive"))
    n35 = s.get("net_mean_bps_at_35bps_cost")
    p35 = s.get("profit_factor_at_35bps_cost")
    g.append(("7 survives 35 bps cost",
              n35 is not None and n35 > 0 and p35 is not None and p35 >= MIN_PF_AT_35,
              f"{n35:.2f} bps, profit factor {p35:.3f}"))
    d1 = s.get("net_mean_bps_entry_delay_1min")
    d2 = s.get("net_mean_bps_entry_delay_2min")
    g.append(("8 survives 1 and 2 minute entry delay",
              d1 is not None and d2 is not None and d1 > 0 and d2 > 0,
              f"+1 min {d1:.2f} bps, +2 min {d2:.2f} bps"))
    g.append(("9 beats both controls",
              bool(s.get("beats_control_same_date")) and bool(s.get("beats_control_same_stock")),
              f"same date {s.get('control_same_date_net_mean_bps', float('nan')):.2f} bps, "
              f"same stock {s.get('control_same_stock_net_mean_bps', float('nan')):.2f} bps"))
    c = s["concentration"]
    ss, fd = c.get("largest_stock_share"), c.get("largest_five_dates_share")
    g.append(("10 not concentrated",
              ss is not None and fd is not None
              and ss == ss and fd == fd and ss < MAX_STOCK_SHARE and fd < MAX_FIVE_DATE_SHARE,
              f"largest stock {ss if ss is None else f'{ss*100:.1f}%'}, "
              f"largest five dates {fd if fd is None else f'{fd*100:.1f}%'}"))
    pf = s["portfolio"]
    ok = (pf.get("annualised_return", -1) > 0
          and pf.get("max_drawdown", 1) <= MAX_DRAWDOWN
          and pf.get("return_over_drawdown", 0) >= MIN_RETURN_OVER_DRAWDOWN)
    g.append(("11 portfolio limits", ok,
              f"annual {pf.get('annualised_return', float('nan'))*100:.2f}%, "
              f"worst decline {pf.get('max_drawdown', float('nan'))*100:.2f}%, "
              f"ratio {pf.get('return_over_drawdown', float('nan')):.2f}"))
    x20 = s.get("xnys_net_mean_bps")
    x35 = s.get("xnys_net_mean_bps_at_35bps_cost")
    g.append(("12 same trades priced from the listing exchange",
              x20 is not None and x35 is not None and x20 > 0 and x35 > 0,
              f"20 bps {x20:.2f}, 35 bps {x35:.2f}"
              if x20 is not None else "not computed"))
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    data = json.loads(Path(a.results).read_text())

    best_gross = max((s.get("gross_mean_bps", float("-inf"))
                      for s in data["rules"].values()), default=float("-inf"))
    out = {"tag": data["tag"], "policy_sha256": data["policy_sha256"],
           "best_gross_mean_bps": best_gross,
           "early_stop_bar_bps": EARLY_STOP_GROSS_BPS,
           "early_stop_triggered": best_gross < EARLY_STOP_GROSS_BPS,
           "rules": {}}
    for name, s in data["rules"].items():
        g = gates(s)
        failed = [x[0] for x in g if not x[1]]
        out["rules"][name] = {
            "gates": [{"gate": n, "passed": bool(p), "detail": d} for n, p, d in g],
            "first_failed_gate": failed[0] if failed else None,
            "n_failed": len(failed),
            "passed_all": not failed,
        }
    Path(a.out).write_text(json.dumps(out, indent=2, default=float))

    print(f"best gross average across the six rules: {best_gross:.2f} bps "
          f"(early-stop bar {EARLY_STOP_GROSS_BPS:.0f} bps) -> "
          f"{'STOP' if out['early_stop_triggered'] else 'continue'}\n")
    for name, r in out["rules"].items():
        print(f"{name:34s} failed {r['n_failed']:2d} gates; "
              f"first: {r['first_failed_gate'] or 'NONE - passed all'}")


if __name__ == "__main__":
    main()
