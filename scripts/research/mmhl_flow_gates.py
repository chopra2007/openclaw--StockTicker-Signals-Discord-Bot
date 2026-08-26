"""MD3 — unusual options flow, put through the full frozen gate battery.

Research-only. Imported by no production code.

Why this is not a rerun of the project's existing grading: that grading measured
a single win-rate gap, close-to-close, and used it to set a live alert
threshold. Close-to-close is NOT tradeable by this owner — the action window is
6:15-6:45 a.m. Pacific, and the close is 1 p.m. Pacific. This test enters at the
NEXT MORNING'S OPEN, which is both reachable and point-in-time honest, and then
asks whether the signal is actually profitable after costs.

  signal    a flow burst on day T: vol/OI >= 20, >= 500 contracts, >= $250k
  cluster   one event per ticker/date/side, its largest burst
  rank      by vol/OI, at most 4 per date
  entry     the official open of session T+1
  exit      the official close 5 sessions after entry
  direction CALL bursts long, PUT bursts short
  adjust    SPY-adjusted over the identical window
  cost      25 bps round trip + 10 bps opening-auction premium = 35 bps
  borrow    short side additionally stressed at 25 bps per 5-day hold (ASSUMED,
            not data — no borrow-cost source exists in this project)

    python3 scripts/research/mmhl_flow_gates.py
"""

from __future__ import annotations

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
BORROW_STRESS = 0.0025      # short side only, assumed
MAX_PER_DATE = 4
MIN_VOL_OI = 20.0
MIN_CONTRACTS = 500
MIN_PREMIUM = 250_000


def bars(tk: str) -> dict | None:
    p = CACHE / f"{tk}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def fwd(d: dict, date: str, entry_off: int, exit_off: int):
    """(entry open, exit close) using sessions after `date`. entry_off=1 means
    the next session's open."""
    days = sorted(d)
    import bisect
    i = bisect.bisect_left(days, date)
    if i >= len(days):
        return None
    ei, xi = i + entry_off, i + entry_off + exit_off
    if xi >= len(days):
        return None
    return d[days[ei]][0], d[days[xi]][3]


def events() -> list[dict]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT o.ticker, o.market_date, o.side, o.flow_id,
               f.vol_oi_ratio, f.volume, f.premium_usd
        FROM options_flow_outcomes o
        JOIN options_flow f ON f.id = o.flow_id
        WHERE f.vol_oi_ratio >= ? AND f.volume >= ? AND f.premium_usd >= ?
    """, (MIN_VOL_OI, MIN_CONTRACTS, MIN_PREMIUM)).fetchall()
    con.close()
    best: dict[tuple, dict] = {}
    for r in rows:
        k = (r["ticker"], r["market_date"], (r["side"] or "").upper())
        if k[2] not in ("CALL", "PUT"):
            continue
        cur = best.get(k)
        if cur is None or (r["vol_oi_ratio"] or 0) > cur["vol_oi"]:
            best[k] = {"ticker": k[0], "date": k[1], "side": k[2],
                       "vol_oi": r["vol_oi_ratio"] or 0.0}
    return list(best.values())


def wilson(k: int, n: int):
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
        byd.setdefault(r["date"], []).append(r[key])
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
        "label": label, "n": n,
        "dates": len(byd), "stocks": len({r["ticker"] for r in rows}),
        "win_rate": wins / n, "win_lo": lo, "win_hi": hi,
        "avg": statistics.mean(v), "avg_ci_lo": clo, "avg_ci_hi": chi,
        "profit_factor": (g / l) if l > 0 else float("inf"),
        "worst": min(v),
        "worst_5pct": statistics.mean(sorted(v)[:max(1, n // 20)]),
        "top_ticker_profit_share": (max(prof.values()) / tot) if tot > 0 else float("nan"),
    }


def main() -> int:
    spy = bars("SPY")
    if not spy:
        print("SPY daily bars missing — fetch them first.", file=sys.stderr)
        return 2

    ev = events()
    built, skipped = [], 0
    for e in ev:
        d = bars(e["ticker"])
        if not d:
            skipped += 1
            continue
        px = fwd(d, e["date"], 1, 5)
        bx = fwd(spy, e["date"], 1, 5)
        if not px or not bx:
            skipped += 1
            continue
        eo, xc = px
        beo, bxc = bx
        if eo <= 0 or beo <= 0:
            skipped += 1
            continue
        raw = xc / eo - 1
        bench = bxc / beo - 1
        sign = 1.0 if e["side"] == "CALL" else -1.0
        gross = sign * raw
        rel = sign * (raw - bench)
        short_extra = BORROW_STRESS if sign < 0 else 0.0
        built.append({**e,
                      "raw": raw, "bench": bench,
                      "gross": gross,
                      "net": gross - COST - short_extra,
                      "rel_gross": rel,
                      "rel_net": rel - COST - short_extra})

    by_date: dict[str, list[dict]] = {}
    for r in built:
        by_date.setdefault(r["date"], []).append(r)
    picked = []
    for dt, rs in by_date.items():
        rs.sort(key=lambda r: -r["vol_oi"])
        picked.extend(rs[:MAX_PER_DATE])

    res = {
        "events_after_filters": len(ev),
        "events_priced": len(built),
        "skipped_no_bars_or_window": skipped,
        "picked_top4_per_date": len(picked),
        "cost_applied": COST,
        "borrow_stress_short_side": BORROW_STRESS,
        "entry": "official open of session T+1",
        "exit": "official close 5 sessions after entry",
        "ALL_events": {
            "outright_net": summarise(built, "net", "all events, outright, after cost"),
            "spy_adjusted_net": summarise(built, "rel_net", "all events, SPY-adjusted, after cost"),
        },
        "TOP4_per_date": {
            "outright_net": summarise(picked, "net", "top 4/date, outright, after cost"),
            "spy_adjusted_net": summarise(picked, "rel_net", "top 4/date, SPY-adjusted, after cost"),
        },
        "BY_SIDE_top4": {
            "CALL": summarise([r for r in picked if r["side"] == "CALL"], "rel_net", "CALL, SPY-adj, net"),
            "PUT": summarise([r for r in picked if r["side"] == "PUT"], "rel_net", "PUT, SPY-adj, net"),
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "flow-gates-results.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
