"""MD2 — before-open versus after-close earnings, timing split.

Research-only. Imported by no production code.

Literature: Lyle, Stephan & Yohn (SSRN 3064160) find companies reporting BEFORE
the open get a ~36% weaker immediate price reaction than after-close reporters,
then keep drifting for about four days, because almost nobody has had time to
read the numbers.

Frozen rule:
  split     BMO (report before 09:30 ET) vs AMC (report at/after 16:00 ET).
            Reports timestamped inside the session are AMBIGUOUS and dropped -
            the timestamp cannot be trusted.
  entry     the official open of the first session after the report is public
            (BMO: the same day. AMC: the next day.)
  direction continuation of the initial reaction = the sign of the opening gap
  exit      the official close 4 sessions after entry
  rank      by absolute earnings surprise, at most 4 per date
  liquidity prior close >= $5, 20-day median dollar volume >= $50M
  cost      35 bps

    python3 scripts/research/mmhl_earnings_timing.py
"""

from __future__ import annotations

import bisect
import json
import math
import statistics
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
CACHE = ROOT / "data" / "mmhl_daily"
EARN = ROOT / "data" / "mmhl_earnings"
OUT = ROOT / ".omc" / "research" / "multi-method-high-likelihood-trades"

COST = 0.0035
LIQ_DAYS = 20
MIN_PRICE = 5.0
MIN_DOLLAR_VOL = 50e6
MAX_PER_DATE = 4
HOLD = 4


def bars(tk):
    p = CACHE / f"{tk}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def earnings(tk: str):
    EARN.mkdir(parents=True, exist_ok=True)
    p = EARN / f"{tk}.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    import yfinance as yf
    try:
        df = yf.Ticker(tk).get_earnings_dates(limit=100)
    except Exception:
        return None
    if df is None or len(df) == 0:
        return None
    out = []
    for ts, row in df.iterrows():
        try:
            ts = ts.tz_convert("America/New_York")
        except Exception:
            continue
        sur = row.get("Surprise(%)")
        out.append({
            "date": ts.strftime("%Y-%m-%d"),
            "hhmm": ts.strftime("%H:%M"),
            "surprise": None if sur is None or (isinstance(sur, float) and math.isnan(sur)) else float(sur),
        })
    p.write_text(json.dumps(out))
    return out


def classify(hhmm: str) -> str:
    h, m = int(hhmm[:2]), int(hhmm[3:])
    mins = h * 60 + m
    if mins < 9 * 60 + 30:
        return "BMO"
    if mins >= 16 * 60:
        return "AMC"
    return "AMBIGUOUS"


def wilson(k, n):
    if n == 0:
        return (0.0, 0.0)
    z, p = 1.96, k / n
    den = 1 + z * z / n
    cen = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (cen - half, cen + half)


def summarise(rows, key, label):
    if not rows:
        return {"label": label, "n": 0}
    v = [r[key] for r in rows]
    n = len(v)
    wins = sum(1 for x in v if x > 0)
    lo, hi = wilson(wins, n)
    byd = {}
    for r in rows:
        byd.setdefault(r["entry_date"], []).append(r[key])
    means = [statistics.mean(x) for x in byd.values()]
    if len(means) > 1:
        m = statistics.mean(means)
        se = statistics.stdev(means) / math.sqrt(len(means))
        clo, chi = m - 1.96 * se, m + 1.96 * se
    else:
        clo = chi = float("nan")
    g = sum(x for x in v if x > 0)
    l = -sum(x for x in v if x < 0)
    prof = {}
    for r in rows:
        prof[r["ticker"]] = prof.get(r["ticker"], 0.0) + r[key]
    tot = sum(x for x in prof.values() if x > 0)
    return {
        "label": label, "n": n, "dates": len(byd),
        "stocks": len({r["ticker"] for r in rows}),
        "win_rate": wins / n, "win_lo": lo, "win_hi": hi,
        "avg": statistics.mean(v), "avg_ci_lo": clo, "avg_ci_hi": chi,
        "profit_factor": (g / l) if l > 0 else float("inf"),
        "worst": min(v),
        "worst_5pct": statistics.mean(sorted(v)[:max(1, n // 20)]),
        "top_ticker_profit_share": (max(prof.values()) / tot) if tot > 0 else float("nan"),
    }


def main() -> int:
    tickers = sorted(p.stem for p in CACHE.glob("*.json") if not p.name.startswith("_"))
    events, counts = [], {"BMO": 0, "AMC": 0, "AMBIGUOUS": 0, "no_earnings": 0}

    for i, tk in enumerate(tickers, 1):
        d = bars(tk)
        if not d:
            continue
        es = earnings(tk)
        if not es:
            counts["no_earnings"] += 1
            continue
        time.sleep(0.05)
        days = sorted(d)
        for e in es:
            kind = classify(e["hhmm"])
            counts[kind] = counts.get(kind, 0) + 1
            if kind == "AMBIGUOUS":
                continue
            # first session whose open is after the report is public
            j = bisect.bisect_left(days, e["date"])
            if kind == "AMC":
                j = bisect.bisect_right(days, e["date"])
            if j < LIQ_DAYS + 1 or j + HOLD >= len(days):
                continue
            ed = days[j]
            o = d[ed][0]
            prev_c = d[days[j - 1]][3]
            if o <= 0 or prev_c < MIN_PRICE:
                continue
            dv = [d[days[k]][3] * d[days[k]][4] for k in range(j - LIQ_DAYS, j)]
            if statistics.median(dv) < MIN_DOLLAR_VOL:
                continue
            gap = o / prev_c - 1
            if gap == 0:
                continue
            sign = 1.0 if gap > 0 else -1.0
            exit_c = d[days[j + HOLD]][3]
            gross = sign * (exit_c / o - 1)
            events.append({
                "ticker": tk, "kind": kind, "entry_date": ed,
                "gap": gap, "surprise": e["surprise"],
                "abs_surprise": abs(e["surprise"]) if e["surprise"] is not None else -1.0,
                "gross": gross, "net": gross - COST,
            })
        if i % 50 == 0:
            print(f"[{i}/{len(tickers)}] events={len(events)}", file=sys.stderr)

    def top4(rows):
        byd = {}
        for r in rows:
            byd.setdefault(r["entry_date"], []).append(r)
        out = []
        for _dt, rs in byd.items():
            rs.sort(key=lambda r: -r["abs_surprise"])
            out.extend(rs[:MAX_PER_DATE])
        return out

    bmo = [r for r in events if r["kind"] == "BMO"]
    amc = [r for r in events if r["kind"] == "AMC"]

    res = {
        "classification_counts": counts,
        "events_priced": len(events),
        "cost_applied": COST,
        "hold_sessions": HOLD,
        "BMO_all": summarise(bmo, "net", "before-open reporters, all, after cost"),
        "AMC_all": summarise(amc, "net", "after-close reporters, all, after cost"),
        "BMO_top4_by_surprise": summarise(top4(bmo), "net", "before-open, top 4/date by surprise"),
        "AMC_top4_by_surprise": summarise(top4(amc), "net", "after-close, top 4/date by surprise"),
        "BMO_all_gross": summarise(bmo, "gross", "before-open, all, BEFORE cost"),
        "AMC_all_gross": summarise(amc, "gross", "after-close, all, BEFORE cost"),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "earnings-timing-results.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
