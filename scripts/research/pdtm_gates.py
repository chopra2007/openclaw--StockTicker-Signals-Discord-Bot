#!/usr/bin/env python3
"""Every proof gate in the TODO #106 research prompt, computed one way only.

Frozen before results.  A gate is a number and a threshold; nothing here
chooses a threshold.
"""

import numpy as np
import pandas as pd

RNG_SEED = 20260828
N_BOOT = 10000

# ---- gate thresholds, copied from the research prompt, Phase 6 -------------
GATES_DEV = dict(min_trades=300, min_days=100, min_stocks=30,
                 min_mean_net=0.0020, min_profit_factor=1.30)
GATES_SEALED = dict(min_trades=100, min_days=50, min_stocks=20,
                    min_mean_net=0.0020, min_profit_factor=1.20)
MAX_CONCENTRATION = 0.20
MAX_DIRECTION_SHARE = 0.80      # a method earning almost everything on one side
                                # has only been shown in half the world
MIN_RETURN_OVER_DRAWDOWN = 1.0
MIN_PROFITABLE_BLOCKS = 4
N_BLOCKS = 5


def boot_means(x, n=N_BOOT, seed=RNG_SEED, chunk=200):
    """Bootstrap means, drawn in chunks.

    Drawing all `n` resamples at once allocates n x len(x) numbers; on 80,000
    trades that is several gigabytes and killed an earlier run outright.
    Chunking gives identical statistics with bounded memory.
    """
    x = np.asarray(x, dtype=float)
    rng = np.random.default_rng(seed)
    out = np.empty(n, dtype=float)
    for i in range(0, n, chunk):
        k = min(chunk, n - i)
        idx = rng.integers(0, len(x), size=(k, len(x)))
        out[i:i + k] = x[idx].mean(axis=1)
    return out


def boot_ci(x, stat=np.mean, n=N_BOOT, seed=RNG_SEED, alpha=0.05):
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return (np.nan, np.nan)
    vals = boot_means(x, n=n, seed=seed)
    return tuple(np.percentile(vals, [100 * alpha / 2, 100 * (1 - alpha / 2)]))


def wilson(k, n, z=1.96):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def profit_factor(net):
    w = net[net > 0].sum()
    l = -net[net < 0].sum()
    return float(w / l) if l > 0 else np.inf


def breakeven_win_rate(net):
    """The win rate this method would need, given the size of its own average
    win and average loss, just to break even."""
    w = net[net > 0]
    l = net[net < 0]
    if len(w) == 0 or len(l) == 0:
        return np.nan
    aw, al = w.mean(), -l.mean()
    return float(al / (aw + al))


MAX_POSITION_NOTIONAL = 0.25    # no single position may exceed a quarter of the
                                # account.  Without it, a stop three basis points
                                # away implies a position worth many times the
                                # account - leverage no real account could take.


def equity_curve(trades, risk_frac=0.0025, max_concurrent_risk=0.01,
                 start_capital=1.0, max_notional=MAX_POSITION_NOTIONAL):
    """Account path with risk held against STARTING capital, never against
    current equity, so the run's own losses cannot pick its later trades.

    Each position risks `risk_frac` of starting capital between entry and its
    stop.  Positions open at the same moment are capped at
    `max_concurrent_risk` in total; the excess simply does not get taken.
    """
    t = trades.sort_values(["date", "entry_min"], ignore_index=True)
    stop_dist = np.abs(t.entry_px.values - t.stop.values) / t.entry_px.values
    stop_dist = np.where(stop_dist > 1e-6, stop_dist, np.nan)
    size = np.minimum(risk_frac / stop_dist, max_notional)  # fraction of capital
    pnl = np.zeros(len(t))
    open_risk = {}
    taken = np.zeros(len(t), dtype=bool)
    for i, (d, em, xm) in enumerate(zip(t.date, t.entry_min, t.exit_min)):
        if not np.isfinite(size[i]):
            continue
        cur = open_risk.setdefault(d, [])
        live = sum(r for (r, until) in cur if until >= em)
        if live + risk_frac > max_concurrent_risk + 1e-12:
            continue
        cur.append((risk_frac, xm))
        taken[i] = True
        pnl[i] = size[i] * t.net.values[i] * start_capital
    capped = np.isfinite(size) & (risk_frac / stop_dist > max_notional)
    eq = start_capital + np.cumsum(pnl)
    peak = np.maximum.accumulate(np.concatenate([[start_capital], eq]))[1:]
    dd = (peak - eq) / peak
    return t, pnl, eq, float(dd.max() if len(dd) else np.nan), taken, capped


def summarise(trades: pd.DataFrame, label: str, years: float) -> dict:
    net = trades.net.values
    gross = trades.gross.values
    wins = net > 0
    pf = profit_factor(net)
    lo_wr, hi_wr = wilson(wins.sum(), len(net))
    be = breakeven_win_rate(net)
    lo_m, hi_m = boot_ci(net)
    t, pnl, eq, mdd, taken, capped = equity_curve(trades)
    total_ret = float(eq[-1] - 1.0) if len(eq) else np.nan
    ann = total_ret / years if years > 0 else np.nan

    blocks = np.array_split(np.argsort(trades.date.values, kind="stable"), N_BLOCKS)
    block_mean = [float(net[b].mean()) if len(b) else np.nan for b in blocks]

    prof = np.where(net > 0, net, 0.0).sum()
    def conc(keys):
        if prof <= 0:
            return np.nan
        s = pd.Series(np.where(net > 0, net, 0.0)).groupby(np.asarray(keys)).sum()
        return float(s.max() / prof)

    months = pd.to_datetime(trades.date).dt.strftime("%Y-%m").values
    taken_net = net[taken] if taken.any() else net[:0]
    out = dict(
        label=label, trades=int(len(net)), days=int(trades.date.nunique()),
        stocks=int(trades.symbol.nunique()),
        mean_gross=float(gross.mean()), mean_net=float(net.mean()),
        mean_net_ci=[float(lo_m), float(hi_m)],
        median_net=float(np.median(net)),
        win_rate=float(wins.mean()), win_rate_ci=[float(lo_wr), float(hi_wr)],
        breakeven_win_rate=float(be),
        avg_win=float(net[wins].mean()) if wins.any() else np.nan,
        avg_loss=float(net[~wins].mean()) if (~wins).any() else np.nan,
        profit_factor=float(pf),
        worst_1pct=float(np.percentile(net, 1)), worst_5pct=float(np.percentile(net, 5)),
        max_loss=float(net.min()),
        max_consecutive_losses=int(_max_run(net <= 0)),
        block_mean_net=block_mean,
        profitable_blocks=int(sum(1 for b in block_mean if b > 0)),
        concentration_stock=conc(trades.symbol.values),
        concentration_sector=conc(trades.sector.values) if "sector" in trades else np.nan,
        concentration_month=conc(months),
        positions_taken=int(taken.sum()),
        positions_hitting_the_size_cap=int((capped & taken).sum()),
        total_return=total_ret, annual_return=float(ann),
        max_account_decline=float(mdd),
        return_over_decline=float(ann / mdd) if mdd and mdd > 0 else np.nan,
        exit_mix={k: int(v) for k, v in trades.exit_reason.value_counts().items()},
        median_bars_held=float(trades.bars_held.median()),
        # the smaller list the owner's own risk caps would actually have allowed
        mean_net_risk_capped=float(taken_net.mean()) if len(taken_net) else np.nan,
        trades_risk_capped=int(len(taken_net)),
        # which side the profit came from
        concentration_direction=conc(trades.side.values),
        long_trades=int((trades.side > 0).sum()),
        short_trades=int((trades.side < 0).sum()),
        mean_net_long=float(net[trades.side.values > 0].mean()) if (trades.side > 0).any() else np.nan,
        mean_net_short=float(net[trades.side.values < 0].mean()) if (trades.side < 0).any() else np.nan,
        # entry before 07:00 Pacific is the half hour whose real spread nobody
        # in this research could measure from a source they actually read
        trades_first_30min=int((trades.entry_min < 30).sum()),
        mean_net_first_30min=float(net[trades.entry_min.values < 30].mean()) if (trades.entry_min < 30).any() else np.nan,
        mean_net_after_30min=float(net[trades.entry_min.values >= 30].mean()) if (trades.entry_min >= 30).any() else np.nan,
    )
    return out


def _max_run(mask):
    best = cur = 0
    for m in mask:
        cur = cur + 1 if m else 0
        best = max(best, cur)
    return best


def check(summary: dict, gates: dict) -> dict:
    """Which gates pass.  No gate is ever softened here."""
    s = summary
    r = {
        "sample_trades": s["trades"] >= gates["min_trades"],
        "sample_days": s["days"] >= gates["min_days"],
        "sample_stocks": s["stocks"] >= gates["min_stocks"],
        "mean_net_above_bar": s["mean_net"] >= gates["min_mean_net"],
        "mean_net_ci_above_zero": s["mean_net_ci"][0] > 0,
        "profit_factor": s["profit_factor"] >= gates["min_profit_factor"],
        "win_rate_ci_beats_breakeven": (np.isfinite(s["breakeven_win_rate"])
                                        and s["win_rate_ci"][0] > s["breakeven_win_rate"]),
        "blocks_profitable": s["profitable_blocks"] >= MIN_PROFITABLE_BLOCKS,
        "concentration_stock": (not np.isfinite(s["concentration_stock"])
                                or s["concentration_stock"] <= MAX_CONCENTRATION),
        "concentration_month": (not np.isfinite(s["concentration_month"])
                                or s["concentration_month"] <= MAX_CONCENTRATION),
        "concentration_direction": (not np.isfinite(s.get("concentration_direction", np.nan))
                                    or s["concentration_direction"] <= MAX_DIRECTION_SHARE),
        "return_over_decline": (np.isfinite(s["return_over_decline"])
                                and s["return_over_decline"] >= MIN_RETURN_OVER_DRAWDOWN),
        # the owner's own risk caps must not be what makes the method look good
        "risk_capped_mean_above_bar": (np.isfinite(s.get("mean_net_risk_capped", np.nan))
                                       and s["mean_net_risk_capped"] >= gates["min_mean_net"]),
        # the check that separates a real edge from three rising years
        "beats_the_drift_benchmark": bool(s.get("edge_over_drift", {}).get(
            "edge_clearly_above_zero", False)),
    }
    r["ALL"] = all(r.values())
    return r
