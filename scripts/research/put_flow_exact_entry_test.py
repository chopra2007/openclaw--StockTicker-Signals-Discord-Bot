"""The exact 6:35 a.m. Pacific entry test — the build gate for the PUT-flow shortlist.

Reads the FROZEN candidate list, prices every trade at the real first print at
or after 6:35 a.m. Pacific, and runs the eight pass/fail gates arithmetically.
Nothing here can retune a threshold: every number below is fixed by the build
prompt.

The trade: equal dollars SHORT the stock and LONG SPY.
  net = SPY return - stock return - 25 bps round-trip cost

    python3 scripts/research/put_flow_exact_entry_test.py
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import sys
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from grade_options_flow import ETF_TICKERS  # noqa: E402
from research.put_flow_freeze_candidates import (  # noqa: E402
    MIN_PREMIUM_USD, MIN_VOL_OI, MIN_VOLUME, sort_key,
)

PT = ZoneInfo("America/Los_Angeles")
OUT_DIR = ROOT / ".omc" / "research" / "extreme-put-flow-morning-shortlist"
CACHE_DIR = ROOT / "data" / "put_flow_bars"

BENCHMARK = "SPY"
ENTRY_BAR_ET = "09:35"          # 6:35 a.m. Pacific
HOLD_SESSIONS = 4               # exit is 4 trading sessions after entry
ROUND_TRIP_COST = 0.0025        # 25 bps for the complete round trip
BOOTSTRAP_DRAWS = 10_000
BOOTSTRAP_SEED = 20260824

# Frozen borrow rule — see frozen-borrow-rule.md. Written before any result.
HTB_MIN_PRICE = 5.0
HTB_MIN_MEDIAN_DOLLAR_VOL = 50_000_000.0
HTB_LOOKBACK_SESSIONS = 20


# --------------------------------------------------------------------------
# bars
# --------------------------------------------------------------------------

def load_bars(ticker: str, kind: str) -> dict | None:
    path = CACHE_DIR / f"{ticker.replace('/', '_')}.{kind}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def price_at_entry(bars5m: dict, day: str) -> float | None:
    """First trade price at or after 9:35 a.m. Eastern on `day`.

    The 9:35 bar's OPEN is exactly that print. If that bar is missing (a halt,
    a gap in the feed), fall back to the open of the next bar that session, so a
    single missing bar does not silently become a fabricated price.
    """
    session = bars5m.get(day)
    if not session:
        return None
    times = sorted(t for t in session if t >= ENTRY_BAR_ET)
    if not times:
        return None
    px = session[times[0]]
    return px if px and px > 0 else None


# --------------------------------------------------------------------------
# trading calendar (taken from SPY's own regular-session bars)
# --------------------------------------------------------------------------

def build_calendar(spy_5m: dict) -> list[str]:
    return sorted(d for d, bars in spy_5m.items() if any(t >= ENTRY_BAR_ET for t in bars))


def next_session(cal: list[str], day: str, n: int = 1) -> str | None:
    i = bisect_right(cal, day) + (n - 1)
    return cal[i] if 0 <= i < len(cal) else None


def session_plus(cal: list[str], day: str, n: int) -> str | None:
    try:
        i = cal.index(day)
    except ValueError:
        return None
    return cal[i + n] if i + n < len(cal) else None


# --------------------------------------------------------------------------
# hard-to-borrow screen (point in time)
# --------------------------------------------------------------------------

def easy_to_borrow(daily: dict | None, signal_date: str) -> tuple[bool, str]:
    if not daily:
        return False, "no_daily_bars"
    days = sorted(d for d in daily if d <= signal_date)
    if not days:
        return False, "no_prior_bars"
    close = daily[days[-1]][0]
    if not close or close < HTB_MIN_PRICE:
        return False, f"price_under_{HTB_MIN_PRICE:g}"
    window = days[-HTB_LOOKBACK_SESSIONS:]
    dollar_vol = [daily[d][0] * daily[d][1] for d in window]
    if not dollar_vol:
        return False, "no_volume"
    med = statistics.median(dollar_vol)
    if med < HTB_MIN_MEDIAN_DOLLAR_VOL:
        return False, "thin_dollar_volume"
    return True, ""


# --------------------------------------------------------------------------
# pricing one candidate
# --------------------------------------------------------------------------

def price_trade(cand: dict, cal: list[str], spy_5m: dict,
                bars_cache: dict) -> dict:
    """Fill in entry/exit prices and results, or a reason it could not be priced."""
    out = dict(cand)
    tk = cand["ticker"]
    out["entry_date"] = entry_date = next_session(cal, cand["market_date"])
    out["exit_date"] = exit_date = session_plus(cal, entry_date, HOLD_SESSIONS) if entry_date else None
    if not entry_date or not exit_date:
        out["skip_reason"] = "window_not_elapsed"
        return out

    stock_5m = bars_cache.get(tk)
    if stock_5m is None:
        stock_5m = load_bars(tk, "bars5m")
        bars_cache[tk] = stock_5m
    if not stock_5m:
        out["skip_reason"] = "no_stock_bars"
        return out

    s_in = price_at_entry(stock_5m, entry_date)
    s_out = price_at_entry(stock_5m, exit_date)
    b_in = price_at_entry(spy_5m, entry_date)
    b_out = price_at_entry(spy_5m, exit_date)
    if not all(v and v > 0 for v in (s_in, s_out, b_in, b_out)):
        out["skip_reason"] = "missing_entry_or_exit_print"
        return out

    stock_ret = s_out / s_in - 1.0
    bench_ret = b_out / b_in - 1.0
    out.update({
        "stock_entry_px": s_in, "stock_exit_px": s_out,
        "spy_entry_px": b_in, "spy_exit_px": b_out,
        "stock_ret": stock_ret, "spy_ret": bench_ret,
        "pair_net": bench_ret - stock_ret - ROUND_TRIP_COST,
        "short_only_net": -stock_ret - ROUND_TRIP_COST,
        "skip_reason": "",
    })
    return out


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------

def wilson_lower(wins: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    p = wins / n
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return (centre - margin) / d


def date_bootstrap(values_by_date: dict[str, list[float]], draws: int = BOOTSTRAP_DRAWS
                   ) -> tuple[float, float]:
    """95% range for the AVERAGE, resampling whole dates.

    Two trades on the same morning share that morning's market, so they are not
    independent. Resampling dates (not trades) keeps that honest.
    """
    dates = list(values_by_date)
    if len(dates) < 2:
        return float("nan"), float("nan")
    rng = random.Random(BOOTSTRAP_SEED)
    means = []
    for _ in range(draws):
        pick = [dates[rng.randrange(len(dates))] for _ in dates]
        vals = [v for d in pick for v in values_by_date[d]]
        if vals:
            means.append(statistics.fmean(vals))
    means.sort()
    lo = means[int(0.025 * len(means))]
    hi = means[int(0.975 * len(means)) - 1]
    return lo, hi


def summarise(trades: list[dict], key: str = "pair_net") -> dict:
    vals = [t[key] for t in trades]
    if not vals:
        return {"trades": 0}
    wins = sum(1 for v in vals if v > 0)
    gross_win = sum(v for v in vals if v > 0)
    gross_loss = -sum(v for v in vals if v < 0)
    by_date = defaultdict(list)
    for t in trades:
        by_date[t["market_date"]].append(t[key])
    lo, hi = date_bootstrap(by_date)

    by_stock = defaultdict(float)
    for t in trades:
        if t[key] > 0:
            by_stock[t["ticker"]] += t[key]
    top_share = (max(by_stock.values()) / gross_win) if gross_win > 0 and by_stock else 1.0

    dates_sorted = sorted(by_date)
    mid = len(dates_sorted) // 2
    halves = {}
    for label, ds in (("early", dates_sorted[:mid]), ("late", dates_sorted[mid:])):
        hv = [v for d in ds for v in by_date[d]]
        halves[label] = {
            "trades": len(hv),
            "avg_pct": 100 * statistics.fmean(hv) if hv else None,
            "win_rate_pct": 100 * sum(1 for v in hv if v > 0) / len(hv) if hv else None,
            "dates": len(ds),
        }

    return {
        "trades": len(vals),
        "signal_dates": len(by_date),
        "distinct_stocks": len({t["ticker"] for t in trades}),
        "avg_pct": 100 * statistics.fmean(vals),
        "median_pct": 100 * statistics.median(vals),
        "win_rate_pct": 100 * wins / len(vals),
        "wins": wins,
        "win_rate_lower_95_pct": 100 * wilson_lower(wins, len(vals)),
        "date_boot_95_low_pct": 100 * lo,
        "date_boot_95_high_pct": 100 * hi,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "top_stock_profit_share_pct": 100 * top_share,
        "top_stock": max(by_stock, key=by_stock.get) if by_stock else None,
        "halves": halves,
    }


# --------------------------------------------------------------------------
# controls
# --------------------------------------------------------------------------

def build_controls(db_path: Path, selected_keys: set, dates: set) -> dict[str, list[dict]]:
    """Two same-date comparison groups, built from the same stored rows.

    - `middle_ranked`: qualifying extreme-PUT events on the same morning that
      ranked BELOW the top four, so they were not picked.
    - `no_signal`: single-stock flow events on the same morning that never
      qualified as extreme PUT flow at all.
    """
    import sqlite3
    from grade_options_flow import cluster_events, excess_move
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(
            """SELECT o.*, f.vol_oi_ratio, f.volume, f.premium_usd
               FROM options_flow_outcomes o JOIN options_flow f ON f.id = o.flow_id""")]
    finally:
        conn.close()
    rows = [r for r in rows
            if r["ticker"] not in ETF_TICKERS and excess_move(r, 5) is not None
            and r["market_date"] in dates]
    clustered = cluster_events(rows)

    def qualifies(r):
        return ((r.get("side") or "").upper() == "PUT"
                and (r.get("vol_oi_ratio") or 0) >= MIN_VOL_OI
                and (r.get("volume") or 0) >= MIN_VOLUME
                and (r.get("premium_usd") or 0) >= MIN_PREMIUM_USD)

    by_date_q = defaultdict(list)
    no_signal = []
    for r in clustered:
        if qualifies(r):
            by_date_q[r["market_date"]].append(r)
        else:
            no_signal.append(r)

    middle = []
    for d, rs in by_date_q.items():
        ranked = sorted(rs, key=sort_key)
        for r in ranked[4:8]:      # the next four down the same list
            if (r["ticker"], r["market_date"]) not in selected_keys:
                middle.append(r)

    ns_by_date = defaultdict(list)
    for r in no_signal:
        ns_by_date[r["market_date"]].append(r)
    ns_capped = []
    for d, rs in ns_by_date.items():
        ns_capped += sorted(rs, key=sort_key)[:4]

    return {"middle_ranked": middle, "no_signal": ns_capped}


# --------------------------------------------------------------------------
# gates
# --------------------------------------------------------------------------

def run_gates(s: dict, controls: dict) -> list[dict]:
    g = []

    def add(n, name, required, actual, ok):
        g.append({"gate": n, "name": name, "required": required,
                  "actual": actual, "pass": bool(ok)})

    add(1, "Enough trades, dates and stocks",
        ">=150 trades, >=40 dates, >=50 stocks",
        f"{s['trades']} trades, {s['signal_dates']} dates, {s['distinct_stocks']} stocks",
        s["trades"] >= 150 and s["signal_dates"] >= 40 and s["distinct_stocks"] >= 50)
    add(2, "Average net result", ">= +1.00%", f"{s['avg_pct']:+.3f}%", s["avg_pct"] >= 1.00)
    add(3, "Win rate", ">= 57%, lower estimate > 50%",
        f"{s['win_rate_pct']:.1f}% (lower {s['win_rate_lower_95_pct']:.1f}%)",
        s["win_rate_pct"] >= 57.0 and s["win_rate_lower_95_pct"] > 50.0)
    add(4, "Date-grouped 95% range above zero", "low end > 0",
        f"{s['date_boot_95_low_pct']:+.3f}% to {s['date_boot_95_high_pct']:+.3f}%",
        s["date_boot_95_low_pct"] > 0)
    e, l = s["halves"]["early"], s["halves"]["late"]
    add(5, "Both time halves positive", "both averages > 0",
        f"early {e['avg_pct']:+.3f}%, late {l['avg_pct']:+.3f}%",
        (e["avg_pct"] or 0) > 0 and (l["avg_pct"] or 0) > 0)
    add(6, "Profit factor", ">= 1.25", f"{s['profit_factor']:.3f}", s["profit_factor"] >= 1.25)
    add(7, "No stock dominates the profit", "top stock < 10% of gross profit",
        f"{s['top_stock_profit_share_pct']:.1f}% ({s['top_stock']})",
        s["top_stock_profit_share_pct"] < 10.0)

    # Each control exists on its own subset of mornings, so the selected group is
    # re-averaged over exactly those mornings. Comparing the 53-date selected
    # average against a 26-date control would compare different markets, not
    # different picks.
    parts, beats = [], True
    for name in ("middle_ranked", "no_signal"):
        c = controls.get(f"{name}_summary", {})
        m = controls.get(f"{name}_matched_selected", {})
        if not c or not m:
            beats = False
            parts.append(f"{name}: control could not be built")
            continue
        beats = beats and m["avg_pct"] > c["avg_pct"]
        parts.append(
            f"{name} {c['avg_pct']:+.3f}% (n={c['trades']}, {c['signal_dates']} dates) "
            f"vs selected on the same dates {m['avg_pct']:+.3f}% (n={m['trades']})")
    add(8, "Same-date controls do not explain it",
        "selected beats both middle-ranked and no-signal, averaged over the same mornings",
        "; ".join(parts), beats)
    return g


# --------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=str(ROOT / "consensus.db"))
    p.add_argument("--out-dir", default=str(OUT_DIR))
    args = p.parse_args()
    out_dir = Path(args.out_dir)

    with (out_dir / "frozen-candidates.csv").open() as fh:
        cands = list(csv.DictReader(fh))
    for c in cands:
        c["vol_oi_ratio"] = float(c["vol_oi_ratio"])
        c["rank"] = int(c["rank"])
        c["flow_id"] = int(c["flow_id"])

    spy_5m = load_bars(BENCHMARK, "bars5m")
    if not spy_5m:
        print("no SPY 5-minute bars — run put_flow_fetch_bars.py first", file=sys.stderr)
        return 1
    cal = build_calendar(spy_5m)
    bars_cache: dict = {}

    # Point-in-time borrow screen first, so a dropped name is never priced.
    daily_cache: dict = {}
    kept, dropped = [], []
    for c in cands:
        daily = daily_cache.get(c["ticker"])
        if daily is None:
            daily = load_bars(c["ticker"], "daily")
            daily_cache[c["ticker"]] = daily
        ok, why = easy_to_borrow(daily, c["market_date"])
        (kept if ok else dropped).append({**c, "htb_reason": why})

    priced = [price_trade(c, cal, spy_5m, bars_cache) for c in kept]
    trades = [t for t in priced if not t["skip_reason"]]
    unpriced = [t for t in priced if t["skip_reason"]]

    pair = summarise(trades, "pair_net")
    short_only = summarise(trades, "short_only_net")

    selected_keys = {(t["ticker"], t["market_date"]) for t in trades}
    raw_controls = build_controls(Path(args.db), selected_keys,
                                  {c["market_date"] for c in cands})
    controls: dict = {}
    for name, rows in raw_controls.items():
        cc = []
        for r in rows:
            daily = daily_cache.get(r["ticker"]) or load_bars(r["ticker"], "daily")
            daily_cache[r["ticker"]] = daily
            ok, _ = easy_to_borrow(daily, r["market_date"])
            if not ok:
                continue
            if r["ticker"] not in bars_cache:
                bars_cache[r["ticker"]] = load_bars(r["ticker"], "bars5m")
            t = price_trade({"ticker": r["ticker"], "market_date": r["market_date"],
                             "contract_symbol": r.get("contract_symbol"),
                             "vol_oi_ratio": r.get("vol_oi_ratio") or 0.0},
                            cal, spy_5m, bars_cache)
            if not t["skip_reason"]:
                cc.append(t)
        controls[name] = cc
        controls[f"{name}_summary"] = summarise(cc, "pair_net") if cc else {}
        ctrl_dates = {t["market_date"] for t in cc}
        matched = [t for t in trades if t["market_date"] in ctrl_dates]
        controls[f"{name}_matched_selected"] = summarise(matched, "pair_net") if matched else {}

    gates = run_gates(pair, controls)
    all_pass = all(g["pass"] for g in gates)
    # The unhedged short is graded separately and never inherits the pair's pass.
    # Gate 8 is a pair-trade comparison, so only gates 1-7 apply to it.
    short_gates = [g for g in run_gates(short_only, controls) if g["gate"] != 8]

    result = {
        "generated_at_pacific": datetime.now(PT).isoformat(),
        "frozen_fingerprint": json.loads(
            (out_dir / "frozen-candidates-meta.json").read_text())["fingerprint_sha256"],
        "rule": {
            "entry": "first print at or after 6:35 a.m. Pacific, next session",
            "exit": f"first print at or after 6:35 a.m. Pacific, {HOLD_SESSIONS} sessions later",
            "cost_round_trip_pct": 100 * ROUND_TRIP_COST,
            "borrow_cost_included": False,
            "borrow_note": "see frozen-borrow-rule.md — no reliable historical "
                           "borrow feed exists here; hard-to-borrow names are "
                           "excluded, not charged",
            "price_source": "Schwab /pricehistory 5-minute bars (no paid data bought)",
        },
        "candidates_frozen": len(cands),
        "dropped_hard_to_borrow": len(dropped),
        "dropped_reasons": dict(sorted(
            defaultdict(int, {r: sum(1 for d in dropped if d["htb_reason"] == r)
                              for r in {d["htb_reason"] for d in dropped}}).items())),
        "unpriced": len(unpriced),
        "unpriced_reasons": {r: sum(1 for u in unpriced if u["skip_reason"] == r)
                             for r in {u["skip_reason"] for u in unpriced}},
        "pair_trade": pair,
        "unhedged_short": short_only,
        "unhedged_short_gates": short_gates,
        "unhedged_short_verdict": "PASS" if all(g["pass"] for g in short_gates) else "FAIL",
        "unhedged_short_gates_failed": [g["gate"] for g in short_gates if not g["pass"]],
        "controls": {k: v for k, v in controls.items()
                     if k.endswith("_summary") or k.endswith("_matched_selected")},
        "gates": gates,
        "verdict": "PASS" if all_pass else "FAIL",
        "gates_failed": [g["gate"] for g in gates if not g["pass"]],
    }

    (out_dir / "exact-entry-results.json").write_text(json.dumps(result, indent=2, default=str) + "\n")

    fields = ["market_date", "rank", "ticker", "contract_symbol", "vol_oi_ratio",
              "entry_date", "exit_date", "stock_entry_px", "stock_exit_px",
              "spy_entry_px", "spy_exit_px", "stock_ret", "spy_ret",
              "pair_net", "short_only_net"]
    with (out_dir / "exact-entry-trades.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for t in trades:
            w.writerow(t)

    print(json.dumps({k: v for k, v in result.items() if k != "controls"},
                     indent=2, default=str))
    return 0 if all_pass else 2


if __name__ == "__main__":
    sys.exit(main())
