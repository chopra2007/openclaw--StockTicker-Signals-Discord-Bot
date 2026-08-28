#!/usr/bin/env python3
"""TODO #103 - the gate calculations, shared by development and the sealed run.

Nothing here selects a rule or tunes a threshold. It measures.
"""
import numpy as np
import pandas as pd

SEED = 20260828
BOOT = 50_000
BLOCK_DAYS = 5
FAMILY_ONE_SIDED = 0.99167


def _blocks(trades, col, block_days, transform=None):
    """Consecutive N-trading-day blocks; returns each block's (sum, count)."""
    dates = np.array(sorted(trades.date.unique()))
    chunks = [dates[i:i + block_days] for i in range(0, len(dates), block_days)]
    sums, counts = [], []
    grouped = {d: g[col].to_numpy() for d, g in trades.groupby("date")}
    for ch in chunks:
        v = np.concatenate([grouped[d] for d in ch if d in grouped]) \
            if any(d in grouped for d in ch) else np.array([])
        if transform is not None:
            v = transform(v)
        sums.append(v.sum())
        counts.append(len(v))
    return np.array(sums, dtype=float), np.array(counts, dtype=float)


def _block_bootstrap_mean(sums, counts, boot, seed):
    rng = np.random.default_rng(seed)
    n = len(sums)
    idx = rng.integers(0, n, size=(boot, n))
    s = sums[idx].sum(axis=1)
    c = counts[idx].sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(c > 0, s / c, np.nan)


def block_ci(trades, col="net_bps", alpha=0.05, boot=BOOT, seed=SEED,
             block_days=BLOCK_DAYS, transform=None, one_sided=None):
    """Confidence range for the mean, resampling whole five-trading-day blocks
    so trades on one day - and in one market week - are not treated as
    independent."""
    if trades.empty:
        return (np.nan, np.nan)
    sums, counts = _blocks(trades, col, block_days, transform)
    means = _block_bootstrap_mean(sums, counts, boot, seed)
    means = means[np.isfinite(means)]
    if means.size == 0:
        return (np.nan, np.nan)
    if one_sided is not None:
        return float(np.quantile(means, 1 - one_sided)), float("inf")
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def date_grouped_ci(trades, col="net_bps", alpha=0.05, boot=BOOT, seed=SEED):
    return block_ci(trades, col, alpha, boot, seed)


def win_rate_ci(trades, col="net_bps", alpha=0.05, boot=BOOT, seed=SEED + 1):
    return block_ci(trades, col, alpha, boot, seed,
                    transform=lambda v: (v > 0).astype(float))


def break_even_win_rate(trades, col="net_bps"):
    """The win rate this stage's own payoff shape needs to break even.

    avg_win * p - avg_loss * (1 - p) = 0  ->  p = avg_loss / (avg_win + avg_loss)
    """
    w = trades.loc[trades[col] > 0, col]
    losses = trades.loc[trades[col] <= 0, col]
    if w.empty or losses.empty:
        return np.nan
    aw, al = float(w.mean()), float(-losses.mean())
    return al / (aw + al)


def profit_factor(trades, col="net_bps"):
    won = trades.loc[trades[col] > 0, col].sum()
    lost = -trades.loc[trades[col] <= 0, col].sum()
    return float(won / lost) if lost > 0 else float("inf")


def concentration(trades, col="net_bps"):
    """Share of TOTAL POSITIVE profit contributed by the biggest stock and the
    biggest five dates. Computed on gross profit so a negative total does not
    invert the ratio."""
    pos = trades[trades[col] > 0]
    total = pos[col].sum()
    if total <= 0:
        return {"largest_stock_share": np.nan, "largest_five_dates_share": np.nan,
                "note": "no positive profit to share out"}
    by_sym = pos.groupby("symbol")[col].sum().sort_values(ascending=False)
    by_date = pos.groupby("date")[col].sum().sort_values(ascending=False)
    return {
        "largest_stock": str(by_sym.index[0]),
        "largest_stock_share": float(by_sym.iloc[0] / total),
        "largest_five_dates_share": float(by_date.head(5).sum() / total),
    }


def walk_forward_blocks(trades, n_blocks=5, col="net_bps"):
    if trades.empty:
        return []
    dates = np.array(sorted(trades.date.unique()))
    chunks = np.array_split(dates, n_blocks)
    out = []
    for i, ch in enumerate(chunks, 1):
        t = trades[trades.date.isin(ch)]
        out.append({
            "block": i,
            "first_date": str(ch[0]) if len(ch) else None,
            "last_date": str(ch[-1]) if len(ch) else None,
            "trades": int(len(t)),
            "mean_net_bps": float(t[col].mean()) if len(t) else np.nan,
            "profit_factor": profit_factor(t, col) if len(t) else np.nan,
        })
    return out


def portfolio(trades, start_equity=100_000.0, risk_frac=0.0025,
              max_position=10_000.0, max_concurrent=4, max_gross_frac=0.40,
              max_open_risk_frac=0.01, capacity_frac=0.05, all_dates=None):
    """Run the trades as one real account, overlapping, not as isolated averages."""
    if trades.empty:
        return {"note": "no trades"}
    t = trades.sort_values(["date", "entry_minute"]).copy()
    equity = start_equity
    curve, rejected, funded, notionals = [], 0, 0, []
    for date, day in t.groupby("date", sort=True):
        open_positions = []      # (exit_minute, notional, risk_dollars)
        day_pnl = 0.0
        gross_open = 0.0
        risk_open = 0.0
        for r in day.itertuples():
            open_positions = [p for p in open_positions if p[0] > r.entry_minute]
            gross_open = sum(p[1] for p in open_positions)
            risk_open = sum(p[2] for p in open_positions)
            if len(open_positions) >= max_concurrent:
                rejected += 1
                continue
            stop_dist = float(r.stop_dist_frac)
            if not np.isfinite(stop_dist) or stop_dist <= 0:
                rejected += 1
                continue
            notional = min(max_position, risk_frac * equity / stop_dist)
            # capacity: never more than 1% of the dollar volume printed in the
            # last COMPLETED minute before entry (frozen-policy.md section 10).
            # Using the whole 30-minute window here would have loosened the cap
            # by roughly thirty times.
            notional = min(notional, capacity_frac * float(r.pre_entry_minute_dollar_volume))
            risk_dollars = notional * stop_dist
            if gross_open + notional > max_gross_frac * equity:
                rejected += 1
                continue
            if risk_open + risk_dollars > max_open_risk_frac * equity:
                rejected += 1
                continue
            if notional < 500:
                rejected += 1
                continue
            funded += 1
            notionals.append(notional)
            day_pnl += notional * float(r.net_bps) / 1e4
            open_positions.append((int(r.exit_minute), notional, risk_dollars))
        equity += day_pnl
        curve.append({"date": date, "equity": equity, "pnl": day_pnl})
    c = pd.DataFrame(curve)
    if all_dates is not None:
        # Days with no trade are still days the account was open. Leaving them
        # out would annualise a 672-day span over only its 523 trading days.
        c = (c.set_index("date")
             .reindex(sorted(all_dates))
             .assign(pnl=lambda x: x.pnl.fillna(0.0))
             .assign(equity=lambda x: x.equity.ffill().fillna(start_equity))
             .reset_index().rename(columns={"index": "date"}))
    peak = c.equity.cummax()
    dd = (c.equity / peak - 1.0)
    n_days = len(c)
    total = c.equity.iloc[-1] / start_equity - 1.0
    ann = (1 + total) ** (252 / n_days) - 1 if n_days > 0 else np.nan
    mdd = float(-dd.min())
    return {
        "trading_days": int(n_days),
        "final_equity": float(c.equity.iloc[-1]),
        "total_return": float(total),
        "annualised_return": float(ann),
        "max_drawdown": mdd,
        "return_over_drawdown": float(ann / mdd) if mdd > 0 else float("inf"),
        "signals_generated": int(len(t)),
        "trades_funded": int(funded),
        "rejected_by_limits": int(rejected),
        "median_position_usd": float(np.median(notionals)) if notionals else 0.0,
        "mean_position_usd": float(np.mean(notionals)) if notionals else 0.0,
        "profit_per_funded_trade_usd": float(
            (c.equity.iloc[-1] - start_equity) / funded) if funded else float("nan"),
        "annual_profit_usd_on_100k": float(ann * start_equity),
        "daily_pnl_std": float(c.pnl.std()),
    }


def summarise(trades, label, all_dates=None, capacity_frac=0.05):
    if trades is None or trades.empty:
        return {"rule": label, "trades": 0, "note": "no trades"}
    t = trades[~trades.unresolvable.fillna(False)] if "unresolvable" in trades else trades
    be = break_even_win_rate(t)
    lo, hi = date_grouped_ci(t)
    fam_lo, _ = block_ci(t, one_sided=FAMILY_ONE_SIDED)
    wlo, whi = win_rate_ci(t)
    losses = t.loc[t.net_bps <= 0, "net_bps"]
    wins = t.loc[t.net_bps > 0, "net_bps"]
    # longest losing run in date-then-minute order
    seq = (t.sort_values(["date", "entry_minute"]).net_bps <= 0).to_numpy()
    run = best = 0
    for x in seq:
        run = run + 1 if x else 0
        best = max(best, run)
    return {
        "rule": label,
        "trades": int(len(t)),
        "dates": int(t.date.nunique()),
        "symbols": int(t.symbol.nunique()),
        "unresolvable": int(trades.unresolvable.fillna(False).sum())
        if "unresolvable" in trades else 0,
        "gross_mean_bps": float(t.gross_bps.mean()),
        "net_mean_bps": float(t.net_bps.mean()),
        "net_mean_ci95": [lo, hi],
        "net_mean_one_sided_99167_lower": fam_lo,
        "profit_factor": profit_factor(t),
        "win_rate": float((t.net_bps > 0).mean()),
        "win_rate_ci95": [wlo, whi],
        "break_even_win_rate": be,
        "avg_win_bps": float(wins.mean()) if len(wins) else np.nan,
        "avg_loss_bps": float(losses.mean()) if len(losses) else np.nan,
        "worst_5pct_mean_bps": float(t.net_bps.quantile(0.05)),
        "worst_5pct_tail_mean_bps": float(t.net_bps[t.net_bps <= t.net_bps.quantile(0.05)].mean()),
        "largest_loss_bps": float(t.net_bps.min()),
        "longest_losing_run": int(best),
        "exit_mix": {k: int(v) for k, v in t.exit_kind.value_counts().items()},
        "concentration": concentration(t),
        "walk_forward": walk_forward_blocks(t),
        "portfolio": portfolio(t, all_dates=all_dates, capacity_frac=capacity_frac),
    }
