"""Portfolio-level falsification of TODO #96 (put-flow morning shortlist).

Answers a question the isolated trade-by-trade backtest cannot: what happens
when up to four new pair positions open every trading day and each stays open
for four sessions, so several positions overlap and the same stock can repeat?

Reads the FROZEN policy at `.omc/research/put-flow-portfolio-audit/
frozen-portfolio-policy.json` (hashed before this script ever ran) and the 181
frozen, already-priced TODO #96 trades. Builds a day-by-day dollar equity
curve for a capped-at-16-concurrent-pairs portfolio, a no-stacking control,
four annualized borrow-stress cases, the seven frozen pass/fail gates, and a
four-row entry/exit timing falsification matrix.

Nothing here can change TODO #96's candidate rule, ranking, entry time, hold
length, pair direction or 0.25% cost rule. No network calls.

    python3 scripts/research/put_flow_portfolio_audit.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = ROOT / ".omc" / "research" / "put-flow-portfolio-audit" / "frozen-portfolio-policy.json"
DEFAULT_TRADES = ROOT / ".omc" / "research" / "extreme-put-flow-morning-shortlist" / "exact-entry-trades.csv"
BARS_DIR = ROOT / "data" / "put_flow_bars"
OUT_DIR = ROOT / ".omc" / "research" / "put-flow-portfolio-audit"


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

def load_policy(path: Path) -> dict:
    policy = json.loads(path.read_text())
    sha_path = path.with_suffix(".sha256")
    if sha_path.exists():
        expected = sha_path.read_text().strip()
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(
                f"REFUSING TO RUN: {path} does not match its frozen hash "
                f"({sha_path}). expected={expected} actual={actual}. "
                "The policy must not be edited after it was hashed."
            )
    return policy


def load_trades(path: Path) -> list[dict]:
    with path.open() as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["rank"] = int(r["rank"])
        for k in ("stock_entry_px", "stock_exit_px", "spy_entry_px", "spy_exit_px",
                   "stock_ret", "spy_ret", "pair_net", "short_only_net"):
            r[k] = float(r[k])
    return rows


_bars_cache: dict[str, dict] = {}
_daily_cache: dict[str, dict] = {}


def load_bars5m(ticker: str) -> dict:
    if ticker not in _bars_cache:
        p = BARS_DIR / f"{ticker.replace('/', '_')}.bars5m.json"
        _bars_cache[ticker] = json.loads(p.read_text()) if p.exists() else {}
    return _bars_cache[ticker]


def load_daily(ticker: str) -> dict:
    if ticker not in _daily_cache:
        p = BARS_DIR / f"{ticker.replace('/', '_')}.daily.json"
        _daily_cache[ticker] = json.loads(p.read_text()) if p.exists() else {}
    return _daily_cache[ticker]


def mark_at(ticker: str, day: str, hhmm: str) -> float | None:
    """The exact 5-minute bar OPEN price at `hhmm` (Eastern) on `day`.

    No forward fill, no last-known price, no later snapshot. A missing bar
    at exactly this clock time returns None -- the caller must treat that as
    a hard error for a required intermediate mark, per the frozen policy.
    """
    session = load_bars5m(ticker).get(day)
    if not session:
        return None
    px = session.get(hhmm)
    return px if px and px > 0 else None


def close_at(ticker: str, day: str) -> float | None:
    row = load_daily(ticker).get(day)
    if not row:
        return None
    px = row[0]
    return px if px and px > 0 else None


def build_calendar(spy_bars: dict) -> list[str]:
    return sorted(d for d, bars in spy_bars.items() if "09:35" in bars)


# --------------------------------------------------------------------------
# admission (overflow rule)
# --------------------------------------------------------------------------

def admit_positions(trades: list[dict], cap: int, no_stacking: bool) -> tuple[list[dict], list[dict]]:
    """Apply the frozen overflow rule. Returns (admitted, overflow_rejected)."""
    ordered = sorted(trades, key=lambda t: (t["entry_date"], t["rank"]))
    open_positions: list[dict] = []   # admitted, not yet freed
    admitted: list[dict] = []
    rejected: list[dict] = []
    open_tickers: set[str] = set()

    for t in ordered:
        d = t["entry_date"]
        # free slots: anything whose exit_date is on or before this entry_date
        still_open = []
        for p in open_positions:
            if p["exit_date"] <= d:
                if no_stacking:
                    open_tickers.discard(p["ticker"])
            else:
                still_open.append(p)
        open_positions = still_open

        if no_stacking and t["ticker"] in open_tickers:
            rejected.append({**t, "overflow_reason": "ticker_already_open_no_stacking"})
            continue
        if len(open_positions) >= cap:
            rejected.append({**t, "overflow_reason": "capacity_full"})
            continue

        open_positions.append(t)
        admitted.append(t)
        if no_stacking:
            open_tickers.add(t["ticker"])

    return admitted, rejected


# --------------------------------------------------------------------------
# position pricing (per-day marks, cost, borrow)
# --------------------------------------------------------------------------

def position_daily_marks(t: dict, leg_notional: float, cost_pct: float,
                          borrow_annual_pct: float, mark_hhmm: str) -> dict[str, float]:
    """cum_value(d) for every trading day the position is open, at `mark_hhmm`.

    cum_value(d) = short_leg_pnl(d) + long_leg_pnl(d) - one_time_cost - borrow_accrued(d)
    where short_leg_pnl(d) = leg_notional * (1 - stock_px(d)/stock_entry_px)
          long_leg_pnl(d)  = leg_notional * (spy_px(d)/spy_entry_px - 1)
    """
    ticker = t["ticker"]
    entry_date, exit_date = t["entry_date"], t["exit_date"]
    stock_entry_px = t["stock_entry_px"]
    spy_entry_px = t["spy_entry_px"]
    borrow_rate = borrow_annual_pct / 100.0
    entry_dt = _date(entry_date)

    stock_bars = load_bars5m(ticker)
    spy_bars = load_bars5m("SPY")
    days = sorted(d for d in stock_bars if entry_date <= d <= exit_date)
    marks: dict[str, float] = {}
    for d in days:
        if d == exit_date:
            stock_px = t["stock_exit_px"] if mark_hhmm == "09:35" else mark_at(ticker, d, mark_hhmm)
            spy_px = t["spy_exit_px"] if mark_hhmm == "09:35" else mark_at("SPY", d, mark_hhmm)
        else:
            stock_px = mark_at(ticker, d, mark_hhmm)
            spy_px = mark_at("SPY", d, mark_hhmm)
        if stock_px is None or spy_px is None:
            raise ValueError(
                f"missing required {mark_hhmm} mark for {ticker} on {d} "
                f"(position {entry_date}->{exit_date}); refusing to fill it"
            )
        days_held = (_date(d) - entry_dt).days
        short_pnl = leg_notional * (1 - stock_px / stock_entry_px)
        long_pnl = leg_notional * (spy_px / spy_entry_px - 1)
        cost = leg_notional * cost_pct
        borrow_charge = leg_notional * borrow_rate * days_held / 365.0
        marks[d] = short_pnl + long_pnl - cost - borrow_charge
    return marks


def _date(s: str):
    from datetime import date
    y, m, d = (int(x) for x in s.split("-"))
    return date(y, m, d)


# --------------------------------------------------------------------------
# portfolio build
# --------------------------------------------------------------------------

def build_portfolio(admitted: list[dict], calendar: list[str], capital: float,
                     leg_notional: float, cost_pct: float, borrow_pct: float,
                     mark_hhmm: str = "09:35") -> dict:
    per_position_marks = {}
    for t in admitted:
        key = (t["ticker"], t["entry_date"], t["rank"])
        per_position_marks[key] = position_daily_marks(t, leg_notional, cost_pct, borrow_pct, mark_hhmm)

    equity_rows = []
    running_peak = capital
    max_dd = 0.0
    prev_equity = capital
    banked_cash = 0.0   # realized P&L of positions that have already exited, carried forward
    for d in calendar:
        # P&L accrues on the exit day too (that is when the trade realizes),
        # but CAPACITY is freed on the exit morning before any new entrant is
        # admitted (the overflow rule frees exit-day slots before checking new
        # entries) -- so capacity/exposure use an exclusive-of-exit window
        # while dollar P&L uses the inclusive window. Using the inclusive
        # window for capacity too would double-count a pair's $6,250 legs on
        # its own exit day against the very slot its exit just freed.
        pnl_open = [t for t in admitted if t["entry_date"] <= d <= t["exit_date"]]
        capacity_open = [t for t in admitted if t["entry_date"] <= d < t["exit_date"]]
        entries_today = [t for t in admitted if t["entry_date"] == d]
        exits_today = [t for t in admitted if t["exit_date"] == d]
        # a position's realized P&L is banked as cash starting the day AFTER
        # its own exit, so equity keeps reflecting it once the pair is closed
        for t in exits_today:
            key = (t["ticker"], t["entry_date"], t["rank"])
            banked_cash += per_position_marks[key][t["exit_date"]]
        equity = capital + banked_cash + sum(
            per_position_marks[(t["ticker"], t["entry_date"], t["rank"])].get(d, 0.0)
            for t in pnl_open if t["exit_date"] != d
        )
        running_peak = max(running_peak, equity)
        dd = (running_peak - equity) / capital
        max_dd = max(max_dd, dd)
        daily_ret = (equity / prev_equity - 1.0) if prev_equity else 0.0
        gross = 2 * leg_notional * len(capacity_open)
        turnover = 2 * leg_notional * (len(entries_today) + len(exits_today))
        equity_rows.append({
            "date": d, "equity": equity, "open_pairs": len(capacity_open),
            "gross_exposure": gross, "net_exposure": 0.0,
            "turnover": turnover, "drawdown_pct": 100 * dd, "daily_return_pct": 100 * daily_ret,
        })
        prev_equity = equity

    # realized per-position P&L = final cum_value on exit_date
    positions = []
    for t in admitted:
        key = (t["ticker"], t["entry_date"], t["rank"])
        realized = per_position_marks[key][t["exit_date"]]
        days_held = (_date(t["exit_date"]) - _date(t["entry_date"])).days
        positions.append({
            **t, "leg_notional": leg_notional, "realized_pnl": realized,
            "days_held": days_held, "borrow_pct": borrow_pct,
        })

    gross_win = sum(p["realized_pnl"] for p in positions if p["realized_pnl"] > 0)
    gross_loss = -sum(p["realized_pnl"] for p in positions if p["realized_pnl"] < 0)
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    final_equity = equity_rows[-1]["equity"] if equity_rows else capital
    cumulative_net_return_pct = 100 * (final_equity - capital) / capital

    daily_rets = [r["daily_return_pct"] / 100 for r in equity_rows]

    return {
        "positions": positions,
        "equity_rows": equity_rows,
        "gross_win": gross_win, "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "final_equity": final_equity,
        "cumulative_net_return_pct": cumulative_net_return_pct,
        "max_drawdown_pct": 100 * max_dd,
        "daily_returns": daily_rets,
    }


def bootstrap_daily_return_range(daily_rets: list[float], seed: int, draws: int) -> tuple[float, float]:
    nonzero_or_all = daily_rets
    if len(nonzero_or_all) < 2:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    n = len(nonzero_or_all)
    means = []
    for _ in range(draws):
        pick = [nonzero_or_all[rng.randrange(n)] for _ in range(n)]
        means.append(statistics.fmean(pick))
    means.sort()
    lo = means[int(0.025 * len(means))]
    hi = means[int(0.975 * len(means)) - 1]
    return lo, hi


def concentration(positions: list[dict]) -> dict:
    gross_win = sum(p["realized_pnl"] for p in positions if p["realized_pnl"] > 0)
    by_ticker = defaultdict(float)
    by_date = defaultdict(float)
    for p in positions:
        if p["realized_pnl"] > 0:
            by_ticker[p["ticker"]] += p["realized_pnl"]
            by_date[p["entry_date"]] += p["realized_pnl"]
    top_ticker = max(by_ticker, key=by_ticker.get) if by_ticker else None
    top_date = max(by_date, key=by_date.get) if by_date else None
    return {
        "gross_winning_profit": gross_win,
        "top_ticker": top_ticker,
        "top_ticker_share_pct": 100 * by_ticker[top_ticker] / gross_win if top_ticker and gross_win else 0.0,
        "top_entry_date": top_date,
        "top_entry_date_share_pct": 100 * by_date[top_date] / gross_win if top_date and gross_win else 0.0,
        "by_ticker_pct": {k: 100 * v / gross_win for k, v in by_ticker.items()} if gross_win else {},
        "by_entry_date_pct": {k: 100 * v / gross_win for k, v in by_date.items()} if gross_win else {},
    }


def halves_check(positions: list[dict]) -> dict:
    dates_sorted = sorted({p["entry_date"] for p in positions})
    mid = len(dates_sorted) // 2
    early_dates = set(dates_sorted[:mid])
    late_dates = set(dates_sorted[mid:])
    early_pnl = sum(p["realized_pnl"] for p in positions if p["entry_date"] in early_dates)
    late_pnl = sum(p["realized_pnl"] for p in positions if p["entry_date"] in late_dates)
    return {"early_dates": len(early_dates), "late_dates": len(late_dates),
            "early_pnl": early_pnl, "late_pnl": late_pnl,
            "both_positive": early_pnl > 0 and late_pnl > 0}


# --------------------------------------------------------------------------
# timing falsification matrix (trade-level, not portfolio-level)
# --------------------------------------------------------------------------

def retime_trade(t: dict, entry_hhmm: str, exit_hhmm: str, exit_kind: str, cost_pct: float) -> dict | None:
    ticker = t["ticker"]
    entry_date, exit_date = t["entry_date"], t["exit_date"]
    if exit_kind == "5m_bar_open":
        s_in = mark_at(ticker, entry_date, entry_hhmm)
        s_out = mark_at(ticker, exit_date, exit_hhmm)
        b_in = mark_at("SPY", entry_date, entry_hhmm)
        b_out = mark_at("SPY", exit_date, exit_hhmm)
    else:  # daily_close: entry at 09:30 bar open, exit at daily close
        s_in = mark_at(ticker, entry_date, entry_hhmm)
        s_out = close_at(ticker, exit_date)
        b_in = mark_at("SPY", entry_date, entry_hhmm)
        b_out = close_at("SPY", exit_date)
    if not all(v and v > 0 for v in (s_in, s_out, b_in, b_out)):
        return None
    stock_ret = s_out / s_in - 1.0
    spy_ret = b_out / b_in - 1.0
    return {"stock_ret": stock_ret, "spy_ret": spy_ret,
            "pair_net": spy_ret - stock_ret - cost_pct}


def timing_matrix(trades: list[dict], policy: dict) -> dict:
    cost_pct = policy["cost_rule"]["round_trip_cost_pct"]
    rows = {}
    for row in policy["timing_falsification_matrix"]["rows"]:
        vals = []
        skipped = 0
        for t in trades:
            r = retime_trade(t, row["entry_time_et"],
                              row["exit_time_et"] if row["exit_price_kind"] == "5m_bar_open" else "",
                              row["exit_price_kind"], cost_pct)
            if r is None:
                skipped += 1
                continue
            vals.append(r["pair_net"])
        wins = sum(1 for v in vals if v > 0)
        gross_win = sum(v for v in vals if v > 0)
        gross_loss = -sum(v for v in vals if v < 0)
        rows[row["label"]] = {
            "trades_priced": len(vals), "trades_skipped_missing_price": skipped,
            "avg_pct": 100 * statistics.fmean(vals) if vals else None,
            "win_rate_pct": 100 * wins / len(vals) if vals else None,
            "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win else None),
        }
    return rows


# --------------------------------------------------------------------------
# gates
# --------------------------------------------------------------------------

def run_gates(port0: dict, port20: dict, no_stack0: dict, no_stack20: dict, policy: dict) -> list[dict]:
    seed = policy["gates"]["seed_for_bootstrap"]
    draws = policy["gates"]["bootstrap_draws"]
    gates = []

    def add(n, name, required, results: dict):
        gates.append({"n": n, "name": name, "required": required, "cases": results})

    def both_pass(fn):
        r0 = fn(port0)
        r20 = fn(port20)
        return {"borrow_0pct": r0, "borrow_20pct": r20}, (r0["pass"] and r20["pass"])

    def g1(p):
        v = p["cumulative_net_return_pct"]
        return {"actual_pct": v, "pass": v > 0}
    res, ok = both_pass(g1)
    add(1, "Final cumulative net return above zero", "> 0%", res); gates[-1]["pass"] = ok

    def g2(p):
        v = p["max_drawdown_pct"]
        return {"actual_pct": v, "pass": v <= 10.0}
    res, ok = both_pass(g2)
    add(2, "Maximum drawdown", "<= 10% of starting capital", res); gates[-1]["pass"] = ok

    def g3(p):
        v = p["profit_factor"]
        return {"actual": v, "pass": v >= 1.25}
    res, ok = both_pass(g3)
    add(3, "Portfolio profit factor", ">= 1.25", res); gates[-1]["pass"] = ok

    def g4(p):
        lo, hi = bootstrap_daily_return_range(p["daily_returns"], seed, draws)
        return {"low_pct": 100 * lo, "high_pct": 100 * hi, "pass": lo > 0}
    res, ok = both_pass(g4)
    add(4, "Average daily return 95% range above zero", "low end > 0%", res); gates[-1]["pass"] = ok

    def g5(p):
        h = halves_check(p["positions"])
        return {**h, "pass": h["both_positive"]}
    res, ok = both_pass(g5)
    add(5, "Both time halves profitable", "both > 0", res); gates[-1]["pass"] = ok

    def g6(p):
        c = concentration(p["positions"])
        ok_ = c["top_ticker_share_pct"] < 10.0 and c["top_entry_date_share_pct"] < 10.0
        return {**c, "pass": ok_}
    res, ok = both_pass(g6)
    add(6, "No concentration (ticker or entry date < 10% of profit)", "both < 10%", res); gates[-1]["pass"] = ok

    def g7_pair(p0, p20):
        v0, v20 = p0["cumulative_net_return_pct"], p20["cumulative_net_return_pct"]
        return {"borrow_0pct": {"actual_pct": v0, "pass": v0 > 0},
                "borrow_20pct": {"actual_pct": v20, "pass": v20 > 0}}
    res = g7_pair(no_stack0, no_stack20)
    ok = res["borrow_0pct"]["pass"] and res["borrow_20pct"]["pass"]
    add(7, "Survives no-stacking control", "> 0% under both borrow cases", res); gates[-1]["pass"] = ok

    return gates


# --------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--policy", default=str(DEFAULT_POLICY))
    p.add_argument("--trades", default=str(DEFAULT_TRADES))
    p.add_argument("--out-dir", default=str(OUT_DIR))
    args = p.parse_args()

    policy_path = Path(args.policy)
    policy = load_policy(policy_path)
    trades = load_trades(Path(args.trades))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    capital = policy["starting_capital"]
    leg_notional = capital * policy["leg_fraction_of_starting_capital"]
    cost_pct = policy["cost_rule"]["round_trip_cost_pct"]
    cap = policy["max_concurrent_pairs"]

    spy_bars = load_bars5m("SPY")
    calendar = build_calendar(spy_bars)

    admitted, overflow = admit_positions(trades, cap, no_stacking=False)
    admitted_ns, overflow_ns = admit_positions(trades, cap, no_stacking=True)

    borrow_cases = policy["borrow_stress_cases_annualized_pct"]
    portfolios = {}
    portfolios_ns = {}
    for b in borrow_cases:
        portfolios[b] = build_portfolio(admitted, calendar, capital, leg_notional, cost_pct, b)
        portfolios_ns[b] = build_portfolio(admitted_ns, calendar, capital, leg_notional, cost_pct, b)

    gates = run_gates(portfolios[0], portfolios[20], portfolios_ns[0], portfolios_ns[20], policy)

    tm = timing_matrix(trades, policy)

    # ---- write positions.csv (primary portfolio, one row per borrow case) ----
    pos_fields = ["borrow_pct", "ticker", "market_date", "entry_date", "exit_date", "rank",
                  "leg_notional", "days_held", "realized_pnl", "stock_ret", "spy_ret", "pair_net"]
    with (out_dir / "positions.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=pos_fields)
        w.writeheader()
        for b in borrow_cases:
            for pos in portfolios[b]["positions"]:
                w.writerow({k: pos.get(k) for k in pos_fields})

    # ---- equity-curve.csv (all borrow cases, primary and no-stacking) ----
    eq_fields = ["variant", "borrow_pct", "date", "equity", "open_pairs", "gross_exposure",
                 "net_exposure", "turnover", "drawdown_pct", "daily_return_pct"]
    with (out_dir / "equity-curve.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=eq_fields)
        w.writeheader()
        for variant, port_set in (("primary", portfolios), ("no_stacking", portfolios_ns)):
            for b in borrow_cases:
                for row in port_set[b]["equity_rows"]:
                    w.writerow({"variant": variant, "borrow_pct": b, **row})

    # ---- concentration.json ----
    concentration_out = {
        str(b): concentration(portfolios[b]["positions"]) for b in borrow_cases
    }
    (out_dir / "concentration.json").write_text(json.dumps(concentration_out, indent=2) + "\n")

    # ---- borrow-cases.json ----
    borrow_out = {
        str(b): {
            "final_equity": portfolios[b]["final_equity"],
            "cumulative_net_return_pct": portfolios[b]["cumulative_net_return_pct"],
            "max_drawdown_pct": portfolios[b]["max_drawdown_pct"],
            "profit_factor": portfolios[b]["profit_factor"],
            "gross_win": portfolios[b]["gross_win"],
            "gross_loss": portfolios[b]["gross_loss"],
        } for b in borrow_cases
    }
    borrow_out["no_stacking"] = {
        str(b): {
            "final_equity": portfolios_ns[b]["final_equity"],
            "cumulative_net_return_pct": portfolios_ns[b]["cumulative_net_return_pct"],
            "max_drawdown_pct": portfolios_ns[b]["max_drawdown_pct"],
            "profit_factor": portfolios_ns[b]["profit_factor"],
        } for b in borrow_cases
    }
    (out_dir / "borrow-cases.json").write_text(json.dumps(borrow_out, indent=2) + "\n")

    # ---- timing-matrix.json ----
    (out_dir / "timing-matrix.json").write_text(json.dumps(tm, indent=2) + "\n")

    # ---- gates.json ----
    gates_out = {
        "gates": gates,
        "all_pass": all(g["pass"] for g in gates),
        "overflow_count_primary": len(overflow),
        "overflow_count_no_stacking": len(overflow_ns),
        "admitted_primary": len(admitted),
        "admitted_no_stacking": len(admitted_ns),
        "total_source_trades": len(trades),
        "peak_gross_exposure_pct_of_capital": max(
            (100 * r["gross_exposure"] / capital for r in portfolios[0]["equity_rows"]), default=0.0),
    }
    (out_dir / "gates.json").write_text(json.dumps(gates_out, indent=2, default=str) + "\n")

    # ---- overflow detail (kept alongside gates for audit trail) ----
    (out_dir / "overflow-rejections.json").write_text(json.dumps({
        "primary": [{"ticker": o["ticker"], "entry_date": o["entry_date"], "rank": o["rank"],
                      "reason": o["overflow_reason"]} for o in overflow],
        "no_stacking": [{"ticker": o["ticker"], "entry_date": o["entry_date"], "rank": o["rank"],
                          "reason": o["overflow_reason"]} for o in overflow_ns],
    }, indent=2) + "\n")

    print(json.dumps({
        "policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        "admitted_primary": len(admitted), "overflow_primary": len(overflow),
        "admitted_no_stacking": len(admitted_ns), "overflow_no_stacking": len(overflow_ns),
        "gates_all_pass": gates_out["all_pass"],
        "peak_gross_exposure_pct": gates_out["peak_gross_exposure_pct_of_capital"],
        "cum_return_0pct_borrow": portfolios[0]["cumulative_net_return_pct"],
        "cum_return_20pct_borrow": portfolios[20]["cumulative_net_return_pct"],
        "max_dd_0pct_borrow": portfolios[0]["max_drawdown_pct"],
        "max_dd_20pct_borrow": portfolios[20]["max_drawdown_pct"],
        "profit_factor_0pct_borrow": portfolios[0]["profit_factor"],
        "profit_factor_20pct_borrow": portfolios[20]["profit_factor"],
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
