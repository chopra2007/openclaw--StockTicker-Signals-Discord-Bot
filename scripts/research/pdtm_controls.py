#!/usr/bin/env python3
"""Controls and placebos for TODO #106.

The research prompt requires every method to beat (a) a simple matched control
and (b) a random-direction placebo.  Both are defined here, frozen, before any
profit number exists.

A control must be SIMPLER than the method it challenges and must run on the
same dates with the same costs.  A control that gets a different universe, a
different cost or a different date range is not a control, it is a flattering
comparison.
"""

import numpy as np
import pandas as pd

from pdtm_methods import COL_LAST_SIGNAL, COL_OR, REWARD_RISK

PLACEBO_DRAWS = 10000
PLACEBO_SEED = 20260829


# ------------------------------------------------------- matched controls ----
def m1_control_signals(d, panel, relvol_min, reward_risk=REWARD_RISK):
    """M1's trigger with every context rule stripped out.

    Two completed minutes closing beyond the opening-range edge, and nothing
    else: no location, no market state, no relative strength, no room veto, no
    lower-volume retest.  This is deliberately close to the plain breakout this
    project already rejected — that is the point.  If M1 cannot beat it, M1's
    context rules are decoration.
    """
    o, h, l, c = panel.o, panel.h, panel.l, panel.c
    out = []
    for r in np.where(d.eligible.values)[0]:
        if d.relvol_or.values[r] < relvol_min:
            continue
        atr = d.atr20.values[r] * d.sess_open.values[r]
        hi, lo = d.or_high.values[r], d.or_low.values[r]
        for side in (1, -1):
            level = hi if side > 0 else lo
            opposite = lo if side > 0 else hi
            n_beyond = 0
            for j in range(COL_OR, COL_LAST_SIGNAL + 1):
                cj = c[r][j]
                if not np.isfinite(cj):
                    continue
                if (cj > level) if side > 0 else (cj < level):
                    n_beyond += 1
                else:
                    n_beyond = 0
                    continue
                if n_beyond < 2:
                    continue
                stop, ref = opposite, cj
                risk = side * (ref - stop)
                if risk <= 0 or risk > atr:
                    break
                out.append(dict(row=r, symbol=d.symbol.values[r], date=d.date.values[r],
                                sector=d.sector.values[r], method="M1-control",
                                side=side, confirm_min=j, stop=stop,
                                target=ref + side * reward_risk * risk,
                                risk_frac=risk / ref))
                break
    return pd.DataFrame(out)


def m2_control_signals(d, panel, relvol_min):
    """M2's shape anchored to TODAY's opening range instead of yesterday's
    value area, targeting the opening-range midpoint instead of yesterday's
    busiest price.

    Same trigger (push out, two closes back inside), same stop rule, same
    dates, same cost.  The only thing that changes is whether the level came
    from yesterday's completed auction.  If M2 cannot beat this, then
    "yesterday's agreed value" is not what is doing the work.
    """
    o, h, l, c = panel.o, panel.h, panel.l, panel.c
    out = []
    for r in np.where(d.eligible.values)[0]:
        if d.relvol_or.values[r] < relvol_min:
            continue
        atr = d.atr20.values[r] * d.sess_open.values[r]
        hi, lo = d.or_high.values[r], d.or_low.values[r]
        mid = (hi + lo) / 2.0
        for side in (-1, 1):
            edge = hi if side < 0 else lo
            pushed, extreme, n_back = False, np.nan, 0
            for j in range(COL_OR, COL_LAST_SIGNAL + 1):
                cj, hj, lj = c[r][j], h[r][j], l[r][j]
                if not np.isfinite(cj):
                    continue
                if not pushed:
                    if (hj > edge) if side < 0 else (lj < edge):
                        pushed, extreme = True, (hj if side < 0 else lj)
                    continue
                extreme = max(extreme, hj) if side < 0 else min(extreme, lj)
                if not ((cj < edge) if side < 0 else (cj > edge)):
                    n_back = 0
                    continue
                n_back += 1
                if n_back < 2:
                    continue
                stop, ref, target = extreme, cj, mid
                risk = side * (ref - stop)
                if (risk <= 0 or risk > atr or side * (target - ref) <= 0
                        or side * (target - ref) < risk):
                    pushed, n_back = False, 0
                    continue
                out.append(dict(row=r, symbol=d.symbol.values[r], date=d.date.values[r],
                                sector=d.sector.values[r], method="M2-control",
                                side=side, confirm_min=j, stop=stop, target=target,
                                risk_frac=risk / ref))
                break
    return pd.DataFrame(out)


# -------------------------------------------------------------- placebo -----
def flip_sides(signals: pd.DataFrame) -> pd.DataFrame:
    """The same signals with the direction reversed, keeping the stop and the
    target the same DISTANCE from the entry reference.

    Because the entry price is not known until the simulator runs, the mirror
    is built from the same reference the method used: the confirming bar's
    close.  So the flipped trade risks and targets exactly what the real trade
    did, in the opposite direction.
    """
    s = signals.copy()
    # reconstruct the reference from stop and risk_frac: risk = side*(ref-stop)
    risk = s.risk_frac.values
    side = s.side.values
    # ref = stop + side*risk*ref  ->  ref*(1 - side*risk) = stop
    ref = s.stop.values / (1.0 - side * risk)
    dist_stop = np.abs(ref - s.stop.values)
    dist_targ = np.abs(s.target.values - ref)
    s["side"] = -side
    s["stop"] = ref + np.where(s.side.values > 0, -1.0, 1.0) * dist_stop
    s["target"] = ref + np.where(s.side.values > 0, 1.0, -1.0) * dist_targ
    s["method"] = s.method.astype(str) + "-flipped"
    return s


def placebo_distribution(real_net, flipped_net, n=PLACEBO_DRAWS, seed=PLACEBO_SEED):
    """Mean net return when the direction of every trade is decided by a coin
    flip, `n` times over.

    `real_net` and `flipped_net` must be aligned: element i of each is the same
    signal traded the real way and the mirrored way.  A rule whose own
    direction cannot beat a coin flip has not shown a direction edge.
    """
    real_net = np.asarray(real_net, dtype=float)
    flipped_net = np.asarray(flipped_net, dtype=float)
    assert len(real_net) == len(flipped_net)
    rng = np.random.default_rng(seed)
    means = np.empty(n, dtype=float)
    for i in range(0, n, 200):          # chunked: see boot_means
        k = min(200, n - i)
        picks = rng.random((k, len(real_net))) < 0.5
        means[i:i + k] = np.where(picks, real_net, flipped_net).mean(axis=1)
    real_mean = real_net.mean()
    return dict(
        placebo_mean=float(means.mean()),
        placebo_p05=float(np.percentile(means, 5)),
        placebo_p95=float(np.percentile(means, 95)),
        real_mean=float(real_mean),
        share_of_coin_flips_beating_the_rule=float((means >= real_mean).mean()),
    )


# ------------------------------------------------- drift benchmark (Q8) -----
DRIFT_PEERS = 20      # peers per signal; deterministic, see drift_benchmark


def drift_benchmark(panel, d, signals: pd.DataFrame, simulate, cost_bps,
                    open_cost_bps=None, max_peers=DRIFT_PEERS):
    """The check that separates an edge from three rising years.

    For every real trade, take the SAME direction at the SAME minute on the
    SAME date with the SAME stop and target distances, on every other eligible
    company that day — chosen by nothing at all.  Charge identical costs.

    A rule that is more often long than short, in a market that rose for three
    years, collects a positive average from drift alone.  Flipping long and
    short cannot detect that: in a rising market the mirrored version loses
    *because* it is mostly short.  This benchmark can, because it holds
    direction, timing and geometry fixed and removes only the selection.

    `max_peers` caps how many companies each signal is compared against, taken
    in a fixed order so the choice is deterministic and repeatable.  Twenty per
    signal still gives tens of thousands of benchmark trades, which is far more
    than the mean needs to settle, and it keeps the whole run inside this box's
    memory.
    """
    if len(signals) == 0:
        return pd.DataFrame()
    # hoist every column out of the loop: `d.sector` inside a million-iteration
    # loop goes through pandas attribute lookup each time and dominates runtime
    elig = d.eligible.values
    dates = d.date.values
    syms = d.symbol.values
    sectors = d.sector.values
    closes = panel.c
    by_date = {}
    for i in range(len(elig)):
        if elig[i]:
            by_date.setdefault(dates[i], []).append((i, syms[i]))

    rows = []
    for s in signals.itertuples():
        peers = by_date.get(s.date, [])
        if max_peers is not None and len(peers) > max_peers:
            peers = peers[:max_peers]
        for r, sym in peers:
            if sym == s.symbol:
                continue
            ref = closes[r][s.confirm_min]
            if not np.isfinite(ref):
                continue
            risk = s.risk_frac * ref
            # keep the same reward-to-risk the real trade used
            real_ref = s.stop / (1.0 - s.side * s.risk_frac)
            rr = abs(s.target - real_ref) / max(abs(real_ref - s.stop), 1e-12)
            rows.append(dict(row=r, symbol=sym, date=s.date,
                             sector=sectors[r], method="drift",
                             side=s.side, confirm_min=s.confirm_min,
                             stop=ref - s.side * risk,
                             target=ref + s.side * rr * risk,
                             risk_frac=s.risk_frac))
    if not rows:
        return pd.DataFrame()
    return simulate(panel, pd.DataFrame(rows), cost_bps, open_cost_bps=open_cost_bps)


def edge_over_drift(real_net, drift_net, n=PLACEBO_DRAWS, seed=PLACEBO_SEED):
    """The method's average profit minus the drift benchmark's, with a range.

    If this difference is not clearly above zero, the method found the market,
    not an edge, whatever the raw gates say.
    """
    real_net = np.asarray(real_net, dtype=float)
    drift_net = np.asarray(drift_net, dtype=float)
    from pdtm_gates import boot_means
    a = boot_means(real_net, n=n, seed=seed)
    b = boot_means(drift_net, n=n, seed=seed + 1)
    diff = a - b
    return dict(
        method_mean_net=float(real_net.mean()),
        drift_mean_net=float(drift_net.mean()),
        drift_trades=int(len(drift_net)),
        edge_over_drift=float(real_net.mean() - drift_net.mean()),
        edge_ci=[float(np.percentile(diff, 2.5)), float(np.percentile(diff, 97.5))],
        edge_clearly_above_zero=bool(np.percentile(diff, 2.5) > 0),
    )
