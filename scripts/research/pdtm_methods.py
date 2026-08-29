#!/usr/bin/env python3
"""The three candidate share methods for TODO #106, as code.

Each function turns the panel into a table of signals.  A signal row says which
company-day, which minute CLOSED the confirmation, which direction, and where
the stop and target sit.  Nothing here reads a return.

Every threshold is a named constant at the top of its method and was fixed from
the development-period input distributions in `predictor-distributions.json`,
before any profit number existed.
"""

import numpy as np
import pandas as pd

from pdtm_common import MIN_OPEN, OR_KNOWN

COL_OR = OR_KNOWN - MIN_OPEN        # 15  -> 06:45 Pacific, range complete
COL_LAST_SIGNAL = 180               # 09:30 Pacific: no new signal after this
LAST_EXIT_MIN = 15 * 60 + 55 - MIN_OPEN

# ---------------------------------------------------------------- shared ----
RELVOL_MIN = None      # set by freeze_thresholds()
MKT_TOLERANCE = None
STOP_ATR_CAP = 1.0     # Qullamaggie: a structural stop wider than the average
                       # daily range is not a stop, it is a position
REWARD_RISK = 1.5      # frozen for M1 and M3


def eligible_mask(d):
    return d.eligible.values


def _iter_rows(d, panel, mask):
    rows = np.where(mask)[0]
    return rows


# ------------------------------------------------------- M1 continuation ----
def m1_signals(d, panel, relvol_min, mkt_tol, reward_risk=REWARD_RISK,
               retest_frac=0.25, disable=()):
    """Opening continuation after acceptance and a lower-volume retest.

    NOT the rejected plain breakout.  A plain breakout is one print through the
    opening-range high.  This needs, in order: the opening range already sitting
    outside yesterday's agreed value; two completed minutes accepting outside
    the range; a pullback on LOWER volume than the accepting minute; and a
    completed minute taking out that pullback's high.  It also needs the stock
    to be beating the 60-name composite and to have room to yesterday's extreme.
    """
    o, h, l, c, v = panel.o, panel.h, panel.l, panel.c, panel.v
    ret, mkt = d._ret, d._mkt
    out = []
    for r in np.where(d.eligible.values)[0]:
        if d.relvol_or.values[r] < relvol_min:
            continue
        m = d.mkt_or.values[r]
        for side in (1, -1):
            if side > 0:
                if ("location" not in disable and not d.above_prev_vah.values[r]) \
                        or ("state" not in disable and m < -mkt_tol):
                    continue
                level = d.or_high.values[r]
            else:
                if ("location" not in disable and not d.below_prev_val.values[r]) \
                        or ("state" not in disable and m > mkt_tol):
                    continue
                level = d.or_low.values[r]
            if not np.isfinite(level):
                continue
            sig = _m1_walk(r, side, level, d, o, h, l, c, v, ret, mkt,
                           reward_risk, retest_frac, disable)
            if sig:
                out.append(sig)
    return pd.DataFrame(out)


def _m1_walk(r, side, level, d, o, h, l, c, v, ret, mkt, reward_risk, retest_frac,
             disable=()):
    width = (d.or_high.values[r] - d.or_low.values[r])
    if width <= 0:
        return None
    atr = d.atr20.values[r] * d.sess_open.values[r]
    stage = 0            # 0 waiting for first close outside, 1 have one close,
                         # 2 accepted, 3 saw the lower-volume retest
    accept_vol = np.nan
    retest_high = retest_low = np.nan
    for j in range(COL_OR, COL_LAST_SIGNAL + 1):
        cj = c[r][j]
        if not np.isfinite(cj):
            continue
        beyond = (cj > level) if side > 0 else (cj < level)
        if stage == 0:
            if beyond:
                stage = 1
                accept_vol = v[r][j]
            continue
        if stage == 1:
            if beyond:
                stage = 2
                accept_vol = max(accept_vol, v[r][j])
            else:
                stage = 0
            continue
        if stage == 2:
            touched = (l[r][j] <= level + retest_frac * width) if side > 0 \
                else (h[r][j] >= level - retest_frac * width)
            if touched and ("retest_volume" in disable or v[r][j] < accept_vol):
                stage = 3
                retest_high, retest_low = h[r][j], l[r][j]
            continue
        if stage == 3:
            broke = (cj > retest_high) if side > 0 else (cj < retest_low)
            if not broke:
                # the retest keeps extending; track its extreme
                retest_high = max(retest_high, h[r][j])
                retest_low = min(retest_low, l[r][j])
                # a close back through the level kills the setup outright
                failed = (cj < level) if side > 0 else (cj > level)
                if failed:
                    return None
                continue
            # participation: the stock must be beating the composite
            stop = retest_low if side > 0 else retest_high
            ref = c[r][j]
            risk = side * (ref - stop)
            target = ref + side * reward_risk * risk
            obstacle = d.prev_high.values[r] if side > 0 else d.prev_low.values[r]
            bad = (("strength" not in disable and side * (ret[r][j] - mkt[r][j]) <= 0)
                   or risk <= 0 or risk > atr
                   or ("room" not in disable and np.isfinite(obstacle)
                       and side * (obstacle - target) < 0))
            if bad:
                # this particular attempt does not qualify; the day is not over
                stage, accept_vol = 2, max(accept_vol, v[r][j])
                continue
            return dict(row=r, symbol=d.symbol.values[r], date=d.date.values[r],
                        sector=d.sector.values[r], method="M1", side=side,
                        confirm_min=j, stop=stop, target=target,
                        risk_frac=risk / ref)
    return None


# ------------------------------------------------- M2 prior-value failure ----
def m2_signals(d, panel, relvol_min, mkt_tol):
    """A push past yesterday's agreed value that fails and comes back inside.

    Yesterday's value-area edge is the location.  The trade is toward
    yesterday's busiest price.  The trigger is a FAILED break, which is the
    opposite sign of M1 by construction, so the two cannot both fire the same
    way on the same setup.
    """
    o, h, l, c, v = panel.o, panel.h, panel.l, panel.c, panel.v
    ret, mkt = d._ret, d._mkt
    out = []
    for r in np.where(d.eligible.values)[0]:
        if d.relvol_or.values[r] < relvol_min:
            continue
        m = d.mkt_or.values[r]
        for side in (-1, 1):
            edge = d.prev_vah.values[r] if side < 0 else d.prev_val.values[r]
            poc = d.prev_poc.values[r]
            if not (np.isfinite(edge) and np.isfinite(poc)):
                continue
            if side < 0 and m > mkt_tol:
                continue
            if side > 0 and m < -mkt_tol:
                continue
            if side < 0 and not (poc < edge):
                continue
            if side > 0 and not (poc > edge):
                continue
            sig = _m2_walk(r, side, edge, poc, d, o, h, l, c, ret, mkt)
            if sig:
                out.append(sig)
    return pd.DataFrame(out)


def _m2_walk(r, side, edge, poc, d, o, h, l, c, ret, mkt):
    atr = d.atr20.values[r] * d.sess_open.values[r]
    # Yesterday's value-area edge is known before today opens, so a push past it
    # during the opening range is a real, observed push - and it is the most
    # common shape the sources describe (open beyond yesterday's value, fail
    # back into it).  Seed the walk from the opening range rather than pretend
    # the first fifteen minutes did not happen.
    or_hi, or_lo = d.or_high.values[r], d.or_low.values[r]
    pushed = (or_hi > edge) if side < 0 else (or_lo < edge)
    extreme = (or_hi if side < 0 else or_lo) if pushed else np.nan
    n_back = 0
    for j in range(COL_OR, COL_LAST_SIGNAL + 1):
        cj, hj, lj = c[r][j], h[r][j], l[r][j]
        if not np.isfinite(cj):
            continue
        if not pushed:
            # side -1 means the failed push was UPWARD, above the value-area top
            if (hj > edge) if side < 0 else (lj < edge):
                pushed = True
                extreme = hj if side < 0 else lj
            continue
        extreme = max(extreme, hj) if side < 0 else min(extreme, lj)
        back_inside = (cj < edge) if side < 0 else (cj > edge)
        if not back_inside:
            n_back = 0
            continue
        n_back += 1
        if n_back < 2:                      # two closes back inside, not one
            continue
        stop = extreme
        ref = cj
        risk = side * (ref - stop)
        target = poc
        bad = (side * (ret[r][j] - mkt[r][j]) <= 0
               or risk <= 0 or risk > atr
               or side * (target - ref) <= 0
               or side * (target - ref) < risk)   # not worth one unit of its own risk
        if bad:
            pushed, n_back = False, 0
            continue
        return dict(row=r, symbol=d.symbol.values[r], date=d.date.values[r],
                    sector=d.sector.values[r], method="M2", side=side,
                    confirm_min=j, stop=stop, target=target,
                    risk_frac=risk / ref)
    return None


# --------------------------------------- M3 opening-range failed extension ----
def m3_signals(d, panel, relvol_min, ext_frac, level_set="fib"):
    """Price extends out of the opening range, fails, and comes back inside.

    `level_set` picks the target:
      'fib'  -> 61.8% back across the opening range from the broken edge
      'mid'  -> the midpoint of the opening range          (control)
      'even' -> 50% back across the range, i.e. the same as 'mid' by
                construction, and 75%/25% for the wider variant (control)
    The Fibonacci numbers are not treated as special; this is the comparison
    the research prompt requires.
    """
    o, h, l, c, v = panel.o, panel.h, panel.l, panel.c, panel.v
    out = []
    for r in np.where(d.eligible.values)[0]:
        if d.relvol_or.values[r] < relvol_min:
            continue
        for side in (1, -1):
            sig = _m3_walk(r, side, d, o, h, l, c, ext_frac, level_set)
            if sig:
                out.append(sig)
    return pd.DataFrame(out)


def _m3_walk(r, side, d, o, h, l, c, ext_frac, level_set):
    hi, lo = d.or_high.values[r], d.or_low.values[r]
    width = hi - lo
    if not (np.isfinite(width) and width > 0):
        return None
    atr = d.atr20.values[r] * d.sess_open.values[r]
    # side = -1 : the failed extension was UPWARD, so the trade is short
    edge = hi if side < 0 else lo
    trigger = edge + (-side) * ext_frac * width
    extended = False
    extreme = np.nan
    for j in range(COL_OR, COL_LAST_SIGNAL + 1):
        cj, hj, lj = c[r][j], h[r][j], l[r][j]
        if not np.isfinite(cj):
            continue
        if not extended:
            if (hj >= trigger) if side < 0 else (lj <= trigger):
                extended = True
                extreme = hj if side < 0 else lj
            continue
        extreme = max(extreme, hj) if side < 0 else min(extreme, lj)
        back_inside = (cj < edge) if side < 0 else (cj > edge)
        if not back_inside:
            continue
        stop = extreme
        ref = cj
        risk = side * (ref - stop)
        if risk <= 0 or risk > atr:
            extended = False
            continue
        if level_set == "fib":
            target = hi - 0.618 * width if side < 0 else lo + 0.618 * width
        elif level_set == "mid":
            target = (hi + lo) / 2.0
        elif level_set == "even":
            target = hi - 0.75 * width if side < 0 else lo + 0.75 * width
        else:
            raise ValueError(level_set)
        if side * (target - ref) <= 0:
            extended = False
            continue
        return dict(row=r, symbol=d.symbol.values[r], date=d.date.values[r],
                    sector=d.sector.values[r], method=f"M3-{level_set}",
                    side=side, confirm_min=j, stop=stop, target=target,
                    risk_frac=risk / ref)
    return None
