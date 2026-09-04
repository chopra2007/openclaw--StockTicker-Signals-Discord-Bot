"""TODO #111 iron-condor signal dates — frozen, free, no option data needed.

Computes the pre-entry signal from daily SPY closes and daily VIX only, so the
entry days are fixed before a single dollar of Databento credit is spent.

Signal, evaluated at the close of a signal session D:
  implied  = VIX(D) / 100                      (annualised, 30-day options-implied)
  realised = stdev(last 20 daily log returns of SPY, through D) * sqrt(252)
  VRP      = implied - realised                (annualised volatility points)
  ATR%     = 14-day average true range of SPY / close, through D
  calm     = ATR% <= 90th percentile of the trailing 500 sessions before D

Entry is the NEXT session at 10:00 exchange time. All inputs use data at or
before D, so nothing is known that a trader on D would not have known.
"""
from __future__ import annotations
import json, math, statistics, sys
from datetime import date

SPY = "/home/openclaw/.openclaw/workspace/data/mmhl_daily/SPY.json"
VIX = "/home/openclaw/.openclaw/research-data/todo-111-condor/vix_daily.json"

DEV_START, DEV_END = "2014-01-01", "2021-12-31"
OOS_START, OOS_END = "2022-01-01", "2026-08-31"
ATR_PCTL = 0.90
ATR_LOOKBACK = 500


def load():
    spy = json.load(open(SPY))          # date -> [open, high, low, close, volume]
    vix = json.load(open(VIX))
    days = sorted(d for d in spy if d in vix)
    return spy, vix, days


def series(spy, vix, days):
    """Per-session dict of the frozen inputs; None until the window fills."""
    out = {}
    trs, atrs = [], {}
    for i, d in enumerate(days):
        o, h, l, c, _ = spy[d]
        if i:
            pc = spy[days[i - 1]][3]
            tr = max(h - l, abs(h - pc), abs(l - pc))
        else:
            tr = h - l
        trs.append(tr)
        if len(trs) >= 14:
            atrs[d] = sum(trs[-14:]) / 14 / c
    for i, d in enumerate(days):
        if i < 20 or d not in atrs:
            continue
        rets = [math.log(spy[days[j]][3] / spy[days[j - 1]][3]) for j in range(i - 19, i + 1)]
        realised = statistics.stdev(rets) * math.sqrt(252)
        implied = vix[d] / 100.0
        prior = [atrs[x] for x in days[max(0, i - ATR_LOOKBACK):i] if x in atrs]
        if len(prior) < 250:
            continue
        cutoff = sorted(prior)[int(ATR_PCTL * (len(prior) - 1))]
        out[d] = dict(vrp=implied - realised, implied=implied, realised=realised,
                      atr_pct=atrs[d], atr_cutoff=cutoff, calm=atrs[d] <= cutoff,
                      close=spy[d][3])
    return out


def signal_dates(sig, days, theta, start, end):
    """One entry a week: the Wednesday signal session, else Tuesday, else Thursday."""
    weeks = {}
    for d in days:
        if not (start <= d <= end) or d not in sig:
            continue
        y, w, wd = date.fromisoformat(d).isocalendar()
        if wd in (2, 3, 4):
            weeks.setdefault((y, w), {})[wd] = d
    picked = []
    for key in sorted(weeks):
        for wd in (3, 2, 4):
            if wd in weeks[key]:
                picked.append(weeks[key][wd])
                break
    return [d for d in picked if sig[d]["vrp"] >= theta and sig[d]["calm"]]


if __name__ == "__main__":
    spy, vix, days = load()
    sig = series(spy, vix, days)
    print(f"sessions with a full signal: {len(sig)}")
    print(f"{'theta':>6} {'dev':>6} {'untouched':>10}")
    for theta in (0.00, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06):
        dv = signal_dates(sig, days, theta, DEV_START, DEV_END)
        oo = signal_dates(sig, days, theta, OOS_START, OOS_END)
        print(f"{theta:6.2f} {len(dv):6d} {len(oo):10d}")
    if len(sys.argv) > 1:  # write the frozen list for a chosen theta
        theta = float(sys.argv[1])
        out = {"theta": theta, "atr_percentile": ATR_PCTL, "atr_lookback": ATR_LOOKBACK,
               "development": {"start": DEV_START, "end": DEV_END,
                               "dates": signal_dates(sig, days, theta, DEV_START, DEV_END)},
               "untouched": {"start": OOS_START, "end": OOS_END,
                             "dates": signal_dates(sig, days, theta, OOS_START, OOS_END)}}
        p = "/home/openclaw/.openclaw/research-data/todo-111-condor/signal_dates.json"
        json.dump(out, open(p, "w"), indent=1)
        print("wrote", p, len(out["development"]["dates"]), len(out["untouched"]["dates"]))
