#!/usr/bin/env python3
"""Metrics, the 10-day block bootstrap, and the frozen gate checks."""

from __future__ import annotations

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# basic metrics
# --------------------------------------------------------------------------- #
def metrics(taken: pd.DataFrame, equity: pd.DataFrame, dates: list[str],
            policy: dict) -> dict:
    if taken is None or len(taken) == 0:
        return {"trades": 0}
    r = taken["net_return"].to_numpy(dtype=float)
    wins = r[r > 0]
    losses = r[r <= 0]
    avg_win = float(wins.mean()) if wins.size else 0.0
    avg_loss = float(-losses.mean()) if losses.size else 0.0
    win_rate = float((r > 0).mean())
    be = break_even_win_rate(avg_win, avg_loss)
    gains = float(wins.sum())
    pain = float(-losses.sum())

    syms = _stock_names(taken)
    prof_by_stock = _profit_by_stock(taken)
    prof_by_date = taken.groupby("date")["pnl"].sum()
    total_profit = float(taken["pnl"].sum())

    ann, mdd, sharpe = portfolio_stats(equity, dates, policy)
    return {
        "trades": int(len(taken)),
        "dates": int(taken["date"].nunique()),
        "stocks": int(len(syms)),
        "win_rate": win_rate,
        "break_even_win_rate": be,
        "win_minus_break_even": win_rate - be,
        "avg_net_return": float(r.mean()),
        "avg_net_market_adjusted_return": (
            float(taken["net_market_adjusted_return"].mean())
            if "net_market_adjusted_return" in taken else None),
        "avg_gross_return": float(taken["gross_return"].mean()),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": (gains / pain) if pain > 0 else float("inf"),
        "worst_5pct_avg_loss": float(np.mean(np.sort(r)[:max(1, len(r) // 20)])),
        "largest_loss": float(r.min()),
        "longest_losing_run": longest_losing_run(r),
        "total_pnl": total_profit,
        "annualised_return": ann,
        "max_drawdown": mdd,
        "return_over_drawdown": (ann / mdd) if mdd > 0 else float("inf"),
        "sharpe_date_based": sharpe,
        "max_stock_share_of_profit": _share(prof_by_stock, total_profit),
        "top5_date_share_of_profit": _share(
            prof_by_date.sort_values(ascending=False).head(5).sum(),
            total_profit, is_sum=True),
        "long_side": _side_metrics(taken, 1),
        "short_side": _side_metrics(taken, -1),
        "exit_reasons": taken["exit_reason"].value_counts().to_dict(),
        "final_equity": float(equity["equity"].iloc[-1]) if len(equity) else None,
    }


def _stock_names(taken):
    s = set()
    for r in taken.itertuples(index=False):
        if getattr(r, "legs", 1) == 2:
            s.add(r.long_symbol)
            s.add(r.short_symbol)
        else:
            s.add(r.symbol)
    return s


def _profit_by_stock(taken):
    acc: dict[str, float] = {}
    for r in taken.itertuples(index=False):
        if getattr(r, "legs", 1) == 2:
            acc[r.long_symbol] = acc.get(r.long_symbol, 0.0) + r.pnl / 2
            acc[r.short_symbol] = acc.get(r.short_symbol, 0.0) + r.pnl / 2
        else:
            acc[r.symbol] = acc.get(r.symbol, 0.0) + r.pnl
    return pd.Series(acc)


def _share(by, total, is_sum=False):
    if total <= 0:
        return None
    v = float(by) if is_sum else float(by.max())
    return v / total


def _side_metrics(taken, side):
    s = taken[taken["side"] == side]
    if len(s) == 0:
        return {"trades": 0}
    r = s["net_return"].to_numpy(dtype=float)
    return {"trades": int(len(s)), "avg_net_return": float(r.mean()),
            "win_rate": float((r > 0).mean()), "total_pnl": float(s["pnl"].sum())}


def break_even_win_rate(avg_win, avg_loss):
    if avg_win + avg_loss <= 0:
        return float("nan")
    return avg_loss / (avg_win + avg_loss)


def longest_losing_run(r):
    best = cur = 0
    for x in r:
        cur = cur + 1 if x <= 0 else 0
        best = max(best, cur)
    return int(best)


def portfolio_stats(equity: pd.DataFrame, dates: list[str], policy: dict):
    if equity is None or len(equity) == 0:
        return 0.0, 0.0, 0.0
    start = policy["portfolio"]["starting_capital"]
    eq = pd.Series(equity["equity"].to_numpy(), index=equity["date"])
    eq = eq.reindex(dates).ffill().fillna(start)
    n = len(dates)
    total = eq.iloc[-1] / start - 1.0
    years = n / 252.0
    ann = (1.0 + total) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    peak = eq.cummax()
    mdd = float(((peak - eq) / peak).max())
    dr = eq.pct_change().dropna()
    sharpe = (float(dr.mean() / dr.std(ddof=1)) * np.sqrt(252)
              if len(dr) > 2 and dr.std(ddof=1) > 0 else 0.0)
    return float(ann), mdd, sharpe


# --------------------------------------------------------------------------- #
# 10-market-day block bootstrap
# --------------------------------------------------------------------------- #
def block_bootstrap(taken: pd.DataFrame, dates: list[str], conf: float,
                    n_resamples: int, seed: int, block_len: int = 10) -> dict:
    """Resample consecutive 10-day date blocks so overlapping trades stay
    together.  Every trade whose ENTRY date is drawn keeps its whole path."""
    if taken is None or len(taken) == 0:
        return {}
    by_date: dict[str, np.ndarray] = {
        d: g["net_return"].to_numpy(dtype=float)
        for d, g in taken.groupby("date")
    }
    idx = {d: i for i, d in enumerate(dates)}
    order = [d for d in dates if d in by_date]
    n_dates = len(dates)
    n_blocks = int(np.ceil(n_dates / block_len))
    starts = np.arange(0, max(1, n_dates - block_len + 1))
    rng = np.random.default_rng(seed)

    date_arr = np.array(dates)
    pools = [by_date.get(d) for d in dates]

    avg, wmb = np.empty(n_resamples), np.empty(n_resamples)
    for k in range(n_resamples):
        s = rng.choice(starts, size=n_blocks, replace=True)
        chunks = []
        total = 0
        for st in s:
            for i in range(st, min(st + block_len, n_dates)):
                p = pools[i]
                if p is not None and p.size:
                    chunks.append(p)
                total += 1
                if total >= n_dates:
                    break
            if total >= n_dates:
                break
        if not chunks:
            avg[k] = np.nan
            wmb[k] = np.nan
            continue
        r = np.concatenate(chunks)
        avg[k] = r.mean()
        w = r[r > 0]
        l = r[r <= 0]
        aw = w.mean() if w.size else 0.0
        al = -l.mean() if l.size else 0.0
        be = al / (aw + al) if (aw + al) > 0 else np.nan
        wmb[k] = (r > 0).mean() - be

    lo_q = (1 - conf) / 2 * 100
    hi_q = (1 + conf) / 2 * 100
    return {
        "confidence": conf,
        "resamples": n_resamples,
        "seed": seed,
        "block_len": block_len,
        "avg_net_return_low": float(np.nanpercentile(avg, lo_q)),
        "avg_net_return_high": float(np.nanpercentile(avg, hi_q)),
        "win_minus_break_even_low": float(np.nanpercentile(wmb, lo_q)),
        "win_minus_break_even_high": float(np.nanpercentile(wmb, hi_q)),
    }


# --------------------------------------------------------------------------- #
# gates
# --------------------------------------------------------------------------- #
def check(gate_id, plain, ok, actual, threshold):
    return {"id": gate_id, "what": plain, "pass": bool(ok),
            "actual": actual, "threshold": threshold}


def random_direction_control(taken, seed, draws=10000):
    """Same trades, same sizes, coin-flip direction. Can only kill, never save."""
    if taken is None or len(taken) == 0:
        return {}
    g = taken["gross_return"].to_numpy(dtype=float)
    side = taken["side"].to_numpy(dtype=float)
    cost = taken["cost_frac"].to_numpy(dtype=float)
    base = g * side          # the return the rule's own direction produced
    rng = np.random.default_rng(seed)
    n = len(g)
    out = np.empty(draws)
    for k in range(draws):
        flip = rng.choice([-1.0, 1.0], size=n)
        out[k] = (base * flip - cost).mean()
    real = float(taken["net_return"].mean())
    return {"real_avg_net": real,
            "control_p99": float(np.percentile(out, 99)),
            "control_median": float(np.percentile(out, 50)),
            "beats_p99": bool(real > np.percentile(out, 99))}


def group_shares(taken, groups, group_of):
    """Share of total profit by industry group (Method 1 sector-bet check)."""
    if taken is None or len(taken) == 0:
        return {}
    tot = float(taken["pnl"].sum())
    if tot <= 0:
        return {"total_pnl": tot}
    acc = {}
    for r in taken.itertuples(index=False):
        g = group_of(r.symbol, groups)
        acc[g] = acc.get(g, 0.0) + float(r.pnl)
    shares = {k: v / tot for k, v in sorted(acc.items(), key=lambda x: -x[1])}
    return {"total_pnl": tot, "shares": shares,
            "max_share": max(shares.values()) if shares else None}


def dividend_contamination(taken):
    """Share of long entries that look like an ex-dividend drop, not a signal."""
    if taken is None or len(taken) == 0 or "score" not in taken:
        return {}
    longs = taken[taken["side"] == 1]
    if len(longs) == 0:
        return {"long_entries": 0}
    suspect = longs[(longs["score"] >= 0.0015) & (longs["score"] <= 0.0075)]
    return {"long_entries": int(len(longs)),
            "suspect_entries": int(len(suspect)),
            "share": float(len(suspect) / len(longs))}


# --------------------------------------------------------------------------- #
# gates
# --------------------------------------------------------------------------- #
def check(gate_id, plain, ok, actual, threshold):
    return {"id": gate_id, "what": plain, "pass": bool(ok),
            "actual": actual, "threshold": threshold}


def development_gates(res: dict, policy: dict) -> list:
    g = policy["gates"]["development"]
    m = res["fixed_notional"]          # equal dollars per trade
    c = res["compounding"]
    boot = res["bootstrap"]
    cost = res["normal_cost"]
    name = res["method"]
    out = []

    out.append(check("D1", "enough trades, dates and stocks",
                     m.get("trades", 0) >= g["min_trades"]
                     and m.get("dates", 0) >= g["min_dates"]
                     and m.get("stocks", 0) >= g["min_stocks"],
                     {"trades": m.get("trades"), "dates": m.get("dates"),
                      "stocks": m.get("stocks")},
                     {"trades": g["min_trades"], "dates": g["min_dates"],
                      "stocks": g["min_stocks"]}))
    out.append(check("D0", "gross edge at least twice the normal cost",
                     (m.get("avg_gross_return") or -1) >= 2 * cost,
                     m.get("avg_gross_return"), 2 * cost))
    if name == "M1":
        out.append(check("D0b",
                         "gross edge above the two feeds' own disagreement",
                         (m.get("avg_gross_return") or -1)
                         >= g["m1_untestable_below_gross"],
                         m.get("avg_gross_return"),
                         g["m1_untestable_below_gross"]))
    out.append(check("D2", "average net profit per trade",
                     (m.get("avg_net_return") or -1) >= g["min_avg_net_return"],
                     m.get("avg_net_return"), g["min_avg_net_return"]))
    out.append(check("D3", "profit factor",
                     (m.get("profit_factor") or 0) >= g["min_profit_factor"],
                     m.get("profit_factor"), g["min_profit_factor"]))
    out.append(check("D4", "low end of the profit range clears zero by a real margin",
                     (boot.get("avg_net_return_low") or -1)
                     > g["bootstrap_low_must_clear_zero_by"],
                     boot.get("avg_net_return_low"),
                     g["bootstrap_low_must_clear_zero_by"]))
    out.append(check("D5", "low end of win-rate-minus-break-even above zero",
                     (boot.get("win_minus_break_even_low") or -1) > 0,
                     boot.get("win_minus_break_even_low"), 0))
    blocks5 = res["five_blocks_avg_net"]
    out.append(check("D6", "positive in at least four of five time blocks",
                     sum(1 for b in blocks5 if b is not None and b > 0)
                     >= g["min_positive_blocks"],
                     blocks5, g["min_positive_blocks"]))
    h = res["harsh"]
    out.append(check("D7", "survives the harsh cost",
                     (h.get("avg_net_return") or -1) > 0
                     and (h.get("profit_factor") or 0) >= g["harsh_min_profit_factor"],
                     {"avg_net_return": h.get("avg_net_return"),
                      "profit_factor": h.get("profit_factor")},
                     {"avg_net_return": 0,
                      "profit_factor": g["harsh_min_profit_factor"]}))
    dl = res["delayed"]
    out.append(check("D8", "survives a delayed entry",
                     (dl.get("avg_net_return") or -1) > 0,
                     dl.get("avg_net_return"), 0))
    alt = res.get("independent_feed") or {}
    if name == "M1":
        cross = res.get("crossover_feed") or {}
        out.append(check("D9", "positive on the independent price record, "
                               "and when signal and payoff come from "
                               "different feeds",
                         (alt.get("avg_net_return") or -1) > 0
                         and (cross.get("avg_net_return") or -1) > 0,
                         {"rebuild_on_pillar": alt.get("avg_net_return"),
                          "signal_pillar_payoff_equs":
                              cross.get("avg_net_return")}, 0))
        gs = res.get("peer_group_shares") or {}
        out.append(check("D12", "not a sector bet in disguise",
                         (gs.get("max_share") is not None
                          and gs["max_share"] < g["max_peer_group_share_m1"]),
                         gs.get("max_share"), g["max_peer_group_share_m1"]))
    else:
        out.append(check("D9", "positive on the independent price record",
                         True, "not applicable: the daily methods have one "
                               "price record on this machine", None))
    out.append(check("D10", "profit is not concentrated",
                     (m.get("max_stock_share_of_profit") or 1) < g["max_stock_share"]
                     and (m.get("top5_date_share_of_profit") or 1)
                     < g["max_top5_date_share"],
                     {"max_stock": m.get("max_stock_share_of_profit"),
                      "top5_dates": m.get("top5_date_share_of_profit")},
                     {"max_stock": g["max_stock_share"],
                      "top5_dates": g["max_top5_date_share"]}))
    ok11 = True
    for path in (c, m):
        ok11 = ok11 and (
            (path.get("annualised_return") or 0) >= g["min_annual_return"]
            and (path.get("max_drawdown") or 1) <= g["max_drawdown"]
            and (path.get("return_over_drawdown") or 0)
            >= g["min_return_over_drawdown"]
            and (path.get("sharpe_date_based") or 0) >= g["min_sharpe"])
    out.append(check("D11", "account return, decline and Sharpe on both the "
                            "compounding and the equal-dollar path", ok11,
                     {"compounding": {k: c.get(k) for k in
                                      ("annualised_return", "max_drawdown",
                                       "return_over_drawdown",
                                       "sharpe_date_based")},
                      "fixed_notional": {k: m.get(k) for k in
                                         ("annualised_return", "max_drawdown",
                                          "return_over_drawdown",
                                          "sharpe_date_based")}},
                     {"annual": g["min_annual_return"],
                      "max_decline": g["max_drawdown"],
                      "return_over_decline": g["min_return_over_drawdown"],
                      "sharpe": g["min_sharpe"]}))
    both = m.get("long_side", {}), m.get("short_side", {})
    out.append(check("D13", "neither side loses money on its own",
                     all((s.get("trades", 0) == 0
                          or (s.get("avg_net_return") or -1) >= 0)
                         for s in both),
                     {"long": both[0], "short": both[1]}, 0))
    rc = res.get("random_control") or {}
    out.append(check("D14", "beats its own random-direction control",
                     bool(rc.get("beats_p99")),
                     {"real": rc.get("real_avg_net"),
                      "control_p99": rc.get("control_p99")}, "above the 99th"))
    out.append(check("D15", "still pays after the market's own move over the "
                            "same holding window is taken out",
                     (m.get("avg_net_market_adjusted_return") or -1)
                     >= g["market_adjusted_net_return_required"],
                     m.get("avg_net_market_adjusted_return"),
                     g["market_adjusted_net_return_required"]))
    out.append(check("D16", "the harsh cost still leaves a real profit, "
                            "not just break-even",
                     (h.get("avg_net_return") or -1)
                     >= g["harsh_min_avg_net_return"]
                     and (res.get("harsh_bootstrap", {})
                          .get("avg_net_return_low") or -1) > 0,
                     {"avg_net_return": h.get("avg_net_return"),
                      "bootstrap_low": res.get("harsh_bootstrap", {})
                      .get("avg_net_return_low")},
                     {"avg_net_return": g["harsh_min_avg_net_return"],
                      "bootstrap_low": 0}))
    vr = res.get("void_rate")
    out.append(check("D17", "not too many trades quietly dropped for missing "
                            "prices", vr is not None and vr <= g["max_void_rate"],
                     vr, g["max_void_rate"]))
    if name in ("M2", "M3"):
        cw = res.get("common_window") or {}
        out.append(check("D18", "also pays over the least survivor-biased "
                                "window (2023-2025)",
                         (cw.get("avg_net_return") or -1) > 0
                         and (cw.get("avg_net_market_adjusted_return") or -1) > 0,
                         {"avg_net_return": cw.get("avg_net_return"),
                          "market_adjusted":
                              cw.get("avg_net_market_adjusted_return"),
                          "trades": cw.get("trades")}, 0))
    return out


def evaluation_gates(res: dict, policy: dict) -> list:
    g = policy["gates"]["later_period"]
    m = res["fixed_notional"]
    c = res["compounding"]
    boot = res["bootstrap"]
    out = []
    out.append(check("L1", "enough trades, dates and stocks",
                     m.get("trades", 0) >= g["min_trades"]
                     and m.get("dates", 0) >= g["min_dates"]
                     and m.get("stocks", 0) >= g["min_stocks"],
                     {"trades": m.get("trades"), "dates": m.get("dates"),
                      "stocks": m.get("stocks")},
                     {"trades": g["min_trades"], "dates": g["min_dates"],
                      "stocks": g["min_stocks"]}))
    out.append(check("L2", "average net profit per trade",
                     (m.get("avg_net_return") or -1) >= g["min_avg_net_return"],
                     m.get("avg_net_return"), g["min_avg_net_return"]))
    out.append(check("L3", "profit factor",
                     (m.get("profit_factor") or 0) >= g["min_profit_factor"],
                     m.get("profit_factor"), g["min_profit_factor"]))
    out.append(check("L4", "low end of the profit range clears zero by a real margin",
                     (boot.get("avg_net_return_low") or -1)
                     > g["bootstrap_low_must_clear_zero_by"],
                     boot.get("avg_net_return_low"),
                     g["bootstrap_low_must_clear_zero_by"]))
    out.append(check("L5", "low end of win-rate-minus-break-even above zero",
                     (boot.get("win_minus_break_even_low") or -1) > 0,
                     boot.get("win_minus_break_even_low"), 0))
    halves = res["halves_avg_net"]
    out.append(check("L6", "positive in both halves",
                     all(h is not None and h > 0 for h in halves), halves, 0))
    out.append(check("L7", "survives harsh cost and delayed entry",
                     (res["harsh"].get("avg_net_return") or -1) > 0
                     and (res["delayed"].get("avg_net_return") or -1) > 0,
                     {"harsh": res["harsh"].get("avg_net_return"),
                      "delayed": res["delayed"].get("avg_net_return")}, 0))
    out.append(check("L8", "profit is not concentrated",
                     (m.get("max_stock_share_of_profit") or 1) < 0.15
                     and (m.get("top5_date_share_of_profit") or 1) < 0.25,
                     {"max_stock": m.get("max_stock_share_of_profit"),
                      "top5_dates": m.get("top5_date_share_of_profit")},
                     {"max_stock": 0.15, "top5_dates": 0.25}))
    ok9 = all(((p.get("max_drawdown") or 1) <= g["max_drawdown"]
               and (p.get("return_over_drawdown") or 0)
               >= g["min_return_over_drawdown"]) for p in (c, m))
    out.append(check("L9", "account decline and return over decline on both paths",
                     ok9,
                     {"compounding": {"max_decline": c.get("max_drawdown"),
                                      "return_over_decline":
                                          c.get("return_over_drawdown")},
                      "fixed_notional": {"max_decline": m.get("max_drawdown"),
                                         "return_over_decline":
                                             m.get("return_over_drawdown")}},
                     {"max_decline": g["max_drawdown"],
                      "return_over_decline": g["min_return_over_drawdown"]}))
    out.append(check("L11", "still pays after the market's own move over the "
                            "same holding window is taken out",
                     (m.get("avg_net_market_adjusted_return") or -1)
                     >= g["market_adjusted_net_return_required"],
                     m.get("avg_net_market_adjusted_return"),
                     g["market_adjusted_net_return_required"]))
    out.append(check("L12", "the harsh cost still leaves a profit",
                     (res["harsh"].get("avg_net_return") or -1)
                     >= g["harsh_min_avg_net_return"],
                     res["harsh"].get("avg_net_return"),
                     g["harsh_min_avg_net_return"]))
    out.append(check("L10", "the mechanism keeps the same sign and meaning",
                     (m.get("avg_net_return") or -1) > 0
                     and all((s.get("trades", 0) == 0
                              or (s.get("avg_net_return") or -1) >= 0)
                             for s in (m.get("long_side", {}),
                                       m.get("short_side", {}))),
                     {"long": m.get("long_side"), "short": m.get("short_side")},
                     "both sides non-negative"))
    return out
