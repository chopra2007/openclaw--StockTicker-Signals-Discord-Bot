"""TODO #111 tournament — free-data trigger dates for the master weekly grid.

Builds the master weekly signal grid (frozen-matrix section 0.2) and flags
which of the nine free-data named triggers (section 0.10: V2, V0, C1, C2, C3,
U1, U2, D1, D2) fire on each grid date. S1/S2/E1/E2/T1/T2 are excluded on
purpose — they need option quotes, which this file never touches.

Reuses `load()` and `series()` from todo_111_condor_signal.py for the
already-frozen VRP/ATR%/calm computation. Everything else here (moving
averages, 12-month momentum, 60-session highs/lows, the 20-session range
break) is new because the existing script does not compute it.
"""
from __future__ import annotations
import json, os, sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from todo_111_condor_signal import load, series, DEV_START, DEV_END, OOS_START, OOS_END

OUT = "/home/openclaw/.openclaw/research-data/todo-111-tournament/trigger_dates.json"

EXPECTED_WEEKS = {"development": 418, "sealed": 242}
TRIGGER_CODES = ["V2", "V0", "C1", "C2", "C3", "U1", "U2", "D1", "D2"]
MIN_FIRE = 30


def weekly_grid(sig, days, start, end):
    """One session per ISO week: Wednesday, else Tuesday, else Thursday.
    Requires a complete free signal (d in sig), per section 0.2."""
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
    return picked


def raw_atr_pct(spy, days):
    """14-day ATR% for every session with >=14 prior true ranges. Independent
    of series()'s 500-session calm gate, because C2/C3/U2 need ATR% at
    offsets (D-5, D-1) that may fall just outside that gate."""
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
    return atrs


def percentile_cutoff(values, pctl):
    s = sorted(values)
    return s[int(pctl * (len(s) - 1))]


def sma(closes_by_idx, i, n):
    if i + 1 < n:
        return None
    window = closes_by_idx[i - n + 1:i + 1]
    return sum(window) / n


def build(spy, vix, days, sig):
    atr = raw_atr_pct(spy, days)
    closes = [spy[d][3] for d in days]
    idx = {d: i for i, d in enumerate(days)}

    # Rolling helper caches, built once over the whole date index.
    atr250_cutoff75, atr250_cutoff50 = {}, {}   # C2 top-25%, U2 <=median
    range20_ratio = {}                            # C3's own metric, per date
    range20_cutoff20 = {}                          # C3 bottom-20% of trailing 250 of that metric
    mom12m = {}                                    # U1/D1's trailing 12-month total return
    mom_cutoff_top3, mom_cutoff_bot3 = {}, {}

    atr_dates = sorted(atr)
    for i, d in enumerate(atr_dates):
        prior = [atr[atr_dates[j]] for j in range(max(0, i - 250), i)]
        if len(prior) >= 250:
            atr250_cutoff75[d] = percentile_cutoff(prior, 0.75)
            atr250_cutoff50[d] = percentile_cutoff(prior, 0.50)

    for i, d in enumerate(days):
        if i >= 19:  # 20-session window ending at index i (through D-1 uses i-1)
            window = closes[i - 19:i + 1]
            range20_ratio[d] = (max(window) - min(window)) / closes[i]

    r_dates = sorted(range20_ratio)
    for i, d in enumerate(r_dates):
        prior = [range20_ratio[r_dates[j]] for j in range(max(0, i - 250), i)]
        if len(prior) >= 250:
            range20_cutoff20[d] = percentile_cutoff(prior, 0.20)

    for i, d in enumerate(days):
        if i >= 252:
            mom12m[d] = closes[i] / closes[i - 252] - 1

    m_dates = sorted(mom12m)
    LOOKBACK_5Y = 5 * 252
    for i, d in enumerate(m_dates):
        prior = [mom12m[m_dates[j]] for j in range(max(0, i - LOOKBACK_5Y), i)]
        if len(prior) >= 250:  # same minimum-history bar used elsewhere in this file
            mom_cutoff_top3[d] = percentile_cutoff(prior, 2 / 3)
            mom_cutoff_bot3[d] = percentile_cutoff(prior, 1 / 3)

    signal = {}
    triggers = {c: [] for c in TRIGGER_CODES}

    for d in sig:
        i = idx[d]
        s = sig[d]
        close_d = s["close"]
        atr_d = s["atr_pct"]

        d5 = days[i - 5] if i >= 5 else None
        atr_d5 = atr.get(d5) if d5 else None

        sma20 = sma(closes, i, 20)
        sma50 = sma(closes, i, 50)

        window60 = closes[max(0, i - 59):i + 1]
        is_high60 = close_d == max(window60)
        is_low60 = close_d == min(window60)

        entry_idx = i + 1
        entry_day = days[entry_idx] if entry_idx < len(days) else None
        cap14 = days[min(entry_idx + 14, len(days) - 1)] if entry_day else None
        cap7 = days[min(entry_idx + 7, len(days) - 1)] if entry_day else None

        row = dict(vrp=s["vrp"], implied=s["implied"], realised=s["realised"],
                   atr_pct=atr_d, calm=s["calm"], close=close_d,
                   sma20=sma20, sma50=sma50, mom12m=mom12m.get(d),
                   range20_ratio=range20_ratio.get(d),
                   entry_day=entry_day, cap_day_14=cap14, cap_day_7=cap7)
        signal[d] = row

        v2 = s["vrp"] >= 0.02 and s["calm"]
        v0 = s["vrp"] >= 0.00 and s["calm"]
        c1 = s["vrp"] <= 0.00 and s["calm"]

        c2 = False
        if atr_d5 is not None and d in atr250_cutoff75:
            c2 = atr_d > atr_d5 and atr_d >= atr250_cutoff75[d]

        c3 = False
        if i >= 1:
            d_prev = days[i - 1]  # the range window and its percentile are measured through D-1
            ret_d = closes[i] / closes[i - 1] - 1
            if d_prev in range20_cutoff20:
                c3 = (range20_ratio[d_prev] <= range20_cutoff20[d_prev]) and (abs(ret_d) >= 1.5 * atr_d)

        u1 = d1 = False
        if sma50 is not None and d in mom_cutoff_top3:
            u1 = close_d > sma50 and sma20 > sma50 and mom12m[d] >= mom_cutoff_top3[d]
            d1 = close_d < sma50 and sma20 < sma50 and mom12m[d] <= mom_cutoff_bot3[d]

        u2 = is_high60 and (d in atr250_cutoff50 and atr_d <= atr250_cutoff50[d])
        d2 = is_low60

        fired = dict(V2=v2, V0=v0, C1=c1, C2=c2, C3=c3, U1=u1, U2=u2, D1=d1, D2=d2)
        for code, flag in fired.items():
            if flag:
                triggers[code].append(d)

    return signal, triggers


def main():
    spy, vix, days = load()
    sig = series(spy, vix, days)

    grid = {
        "development": weekly_grid(sig, days, DEV_START, DEV_END),
        "sealed": weekly_grid(sig, days, OOS_START, OOS_END),
    }
    for role, dates in grid.items():
        expected = EXPECTED_WEEKS[role]
        if len(dates) != expected:
            print(f"WARNING: {role} grid has {len(dates)} weeks, expected {expected}")
        else:
            print(f"{role} grid: {len(dates)} weeks (matches spec)")

    signal, triggers_all = build(spy, vix, days, sig)

    grid_set = {"development": set(grid["development"]), "sealed": set(grid["sealed"])}
    triggers = {}
    counts = {}
    for code, dates in triggers_all.items():
        dev = sorted(d for d in dates if d in grid_set["development"])
        sea = sorted(d for d in dates if d in grid_set["sealed"])
        triggers[code] = {"development": dev, "sealed": sea}
        counts[code] = {"development": len(dev), "sealed": len(sea)}

    out = {
        "generated": date.today().isoformat(),
        "grid": grid,
        "signal": {d: signal[d] for d in signal if d in grid_set["development"] or d in grid_set["sealed"]},
        "triggers": triggers,
        "counts": counts,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1)
    print("wrote", OUT)

    print(f"\n{'trigger':>8} {'development':>12} {'sealed':>8}")
    thin = []
    for code in TRIGGER_CODES:
        dv, se = counts[code]["development"], counts[code]["sealed"]
        print(f"{code:>8} {dv:12d} {se:8d}")
        if dv < MIN_FIRE or se < MIN_FIRE:
            thin.append(code)
    if thin:
        print(f"\nFLAG (fewer than {MIN_FIRE} dates on one side): {', '.join(thin)}")
    else:
        print(f"\nAll triggers clear the {MIN_FIRE}-date bar on both sides.")


if __name__ == "__main__":
    main()
