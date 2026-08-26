"""MD4, MD5 and EM1 — the three remaining frozen cards.

Research-only. Imported by no production code.

MD4  After-close volatility snapshot, next-morning entry.
     Every option snapshot this project stores is captured AFTER the 1 p.m.
     Pacific close, so it is useless for a same-day decision but legitimately
     known before the NEXT morning's open. Signal = last night's implied
     volatility divided by the stock's recent realised volatility.
     PRE-REGISTERED DIRECTION, stated before running: high implied-to-realised
     = SHORT, low = LONG. This is a weak prior and the honest expectation is
     that it fails; it is recorded here so it cannot be chosen after the fact.

MD5  Attention surge - deliberate NEGATIVE CONTROL, pre-registered to show NO
     edge. If this one "passes", the harness is suspect and every other result
     in the run must be re-examined before being believed.

EM1  Expected-move containment calibration. Not a trade. Measures how often the
     stock actually stays inside the option-implied move, raw and after the
     project's 0.85 adjustment. Range behaviour is NOT option profit.

    python3 scripts/research/mmhl_md4_md5_em1.py
"""

from __future__ import annotations

import bisect
import json
import math
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "mmhl_daily"
OUT = ROOT / ".omc" / "research" / "multi-method-high-likelihood-trades"
DB = ROOT / "consensus.db"

COST = 0.0035
MAX_PER_DATE = 4
HOLD = 5
EM_ADJ = 0.85


def bars(tk):
    p = CACHE / f"{tk}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def wilson(k, n):
    if n == 0:
        return (0.0, 0.0)
    z, p = 1.96, k / n
    den = 1 + z * z / n
    cen = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (cen - half, cen + half)


def summarise(rows, key, label, datekey="entry_date"):
    if not rows:
        return {"label": label, "n": 0}
    v = [r[key] for r in rows]
    n = len(v)
    wins = sum(1 for x in v if x > 0)
    lo, hi = wilson(wins, n)
    byd = {}
    for r in rows:
        byd.setdefault(r[datekey], []).append(r[key])
    means = [statistics.mean(x) for x in byd.values()]
    if len(means) > 1:
        m = statistics.mean(means)
        se = statistics.stdev(means) / math.sqrt(len(means))
        clo, chi = m - 1.96 * se, m + 1.96 * se
    else:
        clo = chi = float("nan")
    g = sum(x for x in v if x > 0)
    l = -sum(x for x in v if x < 0)
    return {
        "label": label, "n": n, "dates": len(byd),
        "stocks": len({r["ticker"] for r in rows}),
        "win_rate": wins / n, "win_lo": lo, "win_hi": hi,
        "avg": statistics.mean(v), "avg_ci_lo": clo, "avg_ci_hi": chi,
        "profit_factor": (g / l) if l > 0 else float("inf"),
        "worst": min(v),
    }


def entry_exit(d, sig_date, hold=HOLD):
    """Enter at the open of the first session AFTER sig_date; exit `hold`
    sessions later at the close."""
    days = sorted(d)
    i = bisect.bisect_right(days, sig_date)
    if i + hold >= len(days):
        return None
    return d[days[i]][0], d[days[i + hold]][3], days[i]


def realised_vol(d, upto_date, win=20):
    days = sorted(d)
    i = bisect.bisect_right(days, upto_date)
    if i < win + 1:
        return None
    rets = []
    for j in range(i - win, i):
        pc = d[days[j - 1]][3]
        if pc > 0:
            rets.append(math.log(d[days[j]][3] / pc))
    if len(rets) < win * 0.8:
        return None
    return statistics.stdev(rets) * math.sqrt(252)


def run_md4(con):
    rows = con.execute("""SELECT snapshot_date, ticker, atm_iv FROM iv_snapshots
                          WHERE atm_iv IS NOT NULL AND atm_iv > 0""").fetchall()
    ev = []
    for sd, tk, iv in rows:
        d = bars(tk)
        if not d:
            continue
        rv = realised_vol(d, sd)
        if not rv or rv <= 0:
            continue
        ee = entry_exit(d, sd)
        if not ee:
            continue
        o, c, ed = ee
        if o <= 0:
            continue
        ratio = iv / rv
        ev.append({"ticker": tk, "sig_date": sd, "entry_date": ed,
                   "ratio": ratio, "raw": c / o - 1})
    if not ev:
        return {"note": "no MD4 events could be priced"}
    ratios = sorted(r["ratio"] for r in ev)
    hi_cut = ratios[int(len(ratios) * 0.8)]
    lo_cut = ratios[int(len(ratios) * 0.2)]
    # PRE-REGISTERED: high implied-to-realised = SHORT, low = LONG
    hi = [{**r, "net": -r["raw"] - COST} for r in ev if r["ratio"] >= hi_cut]
    lo = [{**r, "net": r["raw"] - COST} for r in ev if r["ratio"] <= lo_cut]

    def top4(rs, rev):
        byd = {}
        for r in rs:
            byd.setdefault(r["entry_date"], []).append(r)
        out = []
        for _k, v in byd.items():
            v.sort(key=lambda r: -r["ratio"] if rev else r["ratio"])
            out.extend(v[:MAX_PER_DATE])
        return out

    return {
        "events": len(ev),
        "high_cut": hi_cut, "low_cut": lo_cut,
        "HIGH_iv_rv_SHORT_all": summarise(hi, "net", "high implied/realised, short, after cost"),
        "LOW_iv_rv_LONG_all": summarise(lo, "net", "low implied/realised, long, after cost"),
        "HIGH_top4": summarise(top4(hi, True), "net", "high implied/realised, top 4/date"),
        "LOW_top4": summarise(top4(lo, False), "net", "low implied/realised, top 4/date"),
    }


def run_md5(con):
    rows = con.execute("""
        SELECT date(captured_at,'unixepoch') d, ticker, MAX(mentions) m
        FROM apewisdom_mentions GROUP BY d, ticker""").fetchall()
    hist = {}
    for d, tk, m in rows:
        hist.setdefault(tk, []).append((d, float(m or 0)))
    ev = []
    for tk, series in hist.items():
        b = bars(tk)
        if not b or len(series) < 15:
            continue
        series.sort()
        vals = [v for _d, v in series]
        for i in range(14, len(series)):
            d, v = series[i]
            base = vals[max(0, i - 14):i]
            if len(base) < 10:
                continue
            mu = statistics.mean(base)
            sd_ = statistics.stdev(base) if len(base) > 1 else 0.0
            if sd_ <= 0:
                continue
            z = (v - mu) / sd_
            if z < 2.0:
                continue
            ee = entry_exit(b, d)
            if not ee:
                continue
            o, c, ed = ee
            if o <= 0:
                continue
            ev.append({"ticker": tk, "entry_date": ed, "z": z,
                       "net": (c / o - 1) - COST})
    byd = {}
    for r in ev:
        byd.setdefault(r["entry_date"], []).append(r)
    pick = []
    for _k, v in byd.items():
        v.sort(key=lambda r: -r["z"])
        pick.extend(v[:MAX_PER_DATE])
    return {
        "events": len(ev),
        "PRE_REGISTERED_EXPECTATION": "NO EDGE. A pass here means the harness is suspect.",
        "all": summarise(ev, "net", "attention surge, long, after cost"),
        "top4": summarise(pick, "net", "attention surge, top 4/date, after cost"),
    }


def run_em1(con):
    rows = con.execute("""SELECT snapshot_date, ticker, spot, straddle_em, expiry
                          FROM iv_snapshots
                          WHERE straddle_em IS NOT NULL AND straddle_em > 0
                            AND spot > 0 AND expiry IS NOT NULL""").fetchall()
    raw_in = adj_in = n = 0
    up_break = dn_break = 0
    horizons = []
    for sd, tk, spot, em, expiry in rows:
        d = bars(tk)
        if not d:
            continue
        days = sorted(d)
        i = bisect.bisect_left(days, expiry)
        if i >= len(days):
            continue
        # the actual close on (or first session after) the expiry date
        close = d[days[i]][3]
        move = close - spot
        n += 1
        horizons.append((days[i], sd))
        if abs(move) <= em:
            raw_in += 1
        if abs(move) <= em * EM_ADJ:
            adj_in += 1
        if move > em:
            up_break += 1
        elif move < -em:
            dn_break += 1
    if n == 0:
        return {"note": "no EM1 observations could be priced"}
    rl, rh = wilson(raw_in, n)
    al, ah = wilson(adj_in, n)
    return {
        "observations": n,
        "raw_straddle_containment": raw_in / n,
        "raw_ci": [rl, rh],
        "adjusted_0_85_containment": adj_in / n,
        "adjusted_ci": [al, ah],
        "upside_breaches": up_break / n,
        "downside_breaches": dn_break / n,
        "asymmetry_note": "upside minus downside breach rate",
        "asymmetry": (up_break - dn_break) / n,
        "explicit_non_claim": ("Neither figure is assumed to be a 68% probability. "
                               "Containment is NOT option or credit-spread profit."),
    }


def main() -> int:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    res = {
        "cost_applied": COST,
        "hold_sessions": HOLD,
        "MD4_after_close_vol_snapshot": run_md4(con),
        "MD5_attention_NEGATIVE_CONTROL": run_md5(con),
        "EM1_expected_move_calibration": run_em1(con),
    }
    con.close()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "md4-md5-em1-results.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
