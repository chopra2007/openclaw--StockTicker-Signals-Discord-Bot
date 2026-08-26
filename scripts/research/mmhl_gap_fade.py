"""SD1 / MD1 — extreme overnight gap fade. Stage A development test.

Research-only. Imported by no production code.

Frozen rule (see .omc/research/multi-method-high-likelihood-trades/
frozen-method-cards.json — do not change anything here after reading a result):

  signal    gap = today's open / yesterday's close - 1
  qualify   |gap| >= the 99th percentile of that ticker's own trailing 250-day
            |gap| distribution, built ONLY from days before the decision date
  liquidity yesterday's close >= $5 and the trailing 20-day median dollar
            volume >= $50M, both from days before the decision date
  rank      by |gap|, at most 4 names per date
  entry     the official open
  exit      SD1 the same day's official close; MD1 the close 4 sessions later
  direction FADE, pre-registered: short an up-gap, buy a down-gap
  cost      25 bps round trip + 10 bps opening-auction premium = 35 bps

    python3 scripts/research/mmhl_gap_fade.py --period dev
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "mmhl_daily"
OUT = ROOT / ".omc" / "research" / "multi-method-high-likelihood-trades"

LOOKBACK = 250
PCTILE = 0.99
LIQ_DAYS = 20
MIN_PRICE = 5.0
MIN_DOLLAR_VOL = 50e6
MAX_PER_DATE = 4
COST = 0.0035          # 25 bps round trip + 10 bps opening-auction premium

PERIODS = {
    "dev":   ("2006-01-01", "2015-12-31"),
    "valid": ("2016-01-01", "2022-12-31"),
    "eval":  ("2023-01-01", "2026-08-24"),   # SEALED — run once, only after gates pass
}


def load() -> dict[str, dict]:
    out = {}
    for p in sorted(CACHE.glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        if len(d) > LOOKBACK + 50:
            out[p.stem] = d
    return out


def build(bars: dict[str, dict], lo: str, hi: str, shift: int = 0) -> list[dict]:
    """Every qualifying signal. `shift` > 0 moves the SIGNAL date forward that
    many sessions while keeping the outcome date — a placebo."""
    rows: list[dict] = []
    for tk, d in bars.items():
        dates = sorted(d)
        idx = {dt: i for i, dt in enumerate(dates)}
        for i in range(LOOKBACK, len(dates) - 5):
            dt = dates[i]
            if not (lo <= dt <= hi):
                continue
            o, _h, _l, c, _v = d[dt]
            prev_c = d[dates[i - 1]][3]
            if prev_c < MIN_PRICE or o <= 0 or prev_c <= 0:
                continue
            # liquidity, from days strictly before the decision date
            dv = [d[dates[j]][3] * d[dates[j]][4] for j in range(i - LIQ_DAYS, i)]
            if statistics.median(dv) < MIN_DOLLAR_VOL:
                continue
            # trailing |gap| distribution, days strictly before the decision date
            hist = []
            for j in range(i - LOOKBACK, i):
                pc = d[dates[j - 1]][3]
                if pc > 0:
                    hist.append(abs(d[dates[j]][0] / pc - 1))
            if len(hist) < LOOKBACK * 0.8:
                continue
            hist.sort()
            thresh = hist[min(int(len(hist) * PCTILE), len(hist) - 1)]

            si = i + shift                      # placebo shifts the signal only
            if si >= len(dates) - 5:
                continue
            sdt = dates[si]
            so = d[sdt][0]
            spc = d[dates[si - 1]][3]
            if spc <= 0:
                continue
            gap = so / spc - 1
            if abs(gap) < thresh or thresh <= 0:
                continue

            sign = 1.0 if gap > 0 else -1.0
            same_day = -sign * (c / o - 1)
            exit_i = i + 4
            multi = -sign * (d[dates[exit_i]][3] / o - 1)
            rows.append({
                "ticker": tk, "date": dt, "gap": gap, "abs_gap": abs(gap),
                "thresh": thresh, "open": o, "close": c,
                "sd1_gross": same_day, "md1_gross": multi,
                "sd1": same_day - COST, "md1": multi - COST,
                "day_move": abs(c / o - 1),
            })
    return rows


def top_n(rows: list[dict], n: int = MAX_PER_DATE) -> list[dict]:
    by_date: dict[str, list[dict]] = {}
    for r in rows:
        by_date.setdefault(r["date"], []).append(r)
    out = []
    for dt, rs in by_date.items():
        rs.sort(key=lambda r: -r["abs_gap"])
        out.extend(rs[:n])
    return out


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    z, p = 1.96, k / n
    den = 1 + z * z / n
    cen = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (cen - half, cen + half)


def date_block_ci(rows: list[dict], key: str) -> tuple[float, float]:
    """95% interval for the mean, grouped by date (dates are the independent unit)."""
    by_date: dict[str, list[float]] = {}
    for r in rows:
        by_date.setdefault(r["date"], []).append(r[key])
    means = [statistics.mean(v) for v in by_date.values()]
    if len(means) < 2:
        return (float("nan"), float("nan"))
    m = statistics.mean(means)
    se = statistics.stdev(means) / math.sqrt(len(means))
    return (m - 1.96 * se, m + 1.96 * se)


def report(rows: list[dict], key: str, label: str) -> dict:
    if not rows:
        return {"label": label, "n": 0}
    vals = [r[key] for r in rows]
    wins = sum(1 for v in vals if v > 0)
    n = len(vals)
    lo, hi = wilson(wins, n)
    clo, chi = date_block_ci(rows, key)
    gains = sum(v for v in vals if v > 0)
    losses = -sum(v for v in vals if v < 0)
    pf = (gains / losses) if losses > 0 else float("inf")
    prof: dict[str, float] = {}
    for r in rows:
        prof[r["ticker"]] = prof.get(r["ticker"], 0.0) + r[key]
    tot = sum(v for v in prof.values() if v > 0)
    top_share = (max(prof.values()) / tot) if tot > 0 else float("nan")
    return {
        "label": label, "n": n,
        "dates": len({r["date"] for r in rows}),
        "stocks": len({r["ticker"] for r in rows}),
        "win_rate": wins / n, "wins": wins,
        "win_lo": lo, "win_hi": hi,
        "avg": statistics.mean(vals),
        "avg_ci_lo": clo, "avg_ci_hi": chi,
        "median": statistics.median(vals),
        "profit_factor": pf,
        "worst": min(vals),
        "worst_5pct": statistics.mean(sorted(vals)[:max(1, n // 20)]),
        "top_ticker_profit_share": top_share,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="dev", choices=list(PERIODS))
    ap.add_argument("--placebo", type=int, default=0)
    args = ap.parse_args()

    if args.period == "eval":
        print("EVAL IS SEALED. Run only after every gate passes on dev+valid.",
              file=sys.stderr)
        return 2

    lo, hi = PERIODS[args.period]
    bars = load()
    print(f"tickers with usable history: {len(bars)}", file=sys.stderr)

    allrows = build(bars, lo, hi, shift=args.placebo)
    picked = top_n(allrows)

    # how selective is it? (kill condition: > 10% of ticker-days)
    total_days = sum(
        sum(1 for dt in d if lo <= dt <= hi) for d in bars.values())
    trigger_rate = len(allrows) / total_days if total_days else float("nan")

    res = {
        "period": args.period, "window": [lo, hi],
        "placebo_shift": args.placebo,
        "tickers_loaded": len(bars),
        "ticker_days_in_window": total_days,
        "signals_before_cap": len(allrows),
        "trigger_rate": trigger_rate,
        "picked": len(picked),
        "cost_applied": COST,
        "SD1_same_day": report(picked, "sd1", "SD1 same-day, after cost"),
        "MD1_four_day": report(picked, "md1", "MD1 four-day, after cost"),
        "SD1_gross": report(picked, "sd1_gross", "SD1 before cost"),
        "MD1_gross": report(picked, "md1_gross", "MD1 before cost"),
    }
    tag = f"{args.period}" + (f"-placebo{args.placebo}" if args.placebo else "")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"gapfade-{tag}.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
