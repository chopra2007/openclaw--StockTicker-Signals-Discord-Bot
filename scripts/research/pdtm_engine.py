#!/usr/bin/env python3
"""Trade simulator for TODO #106.  Frozen mechanics, no method logic.

Given a table of signals (which company-date, which minute, which direction,
stop and target), this walks the minute bars forward and returns the completed
trade.  It knows nothing about why a signal fired, and it never looks at a bar
before the entry minute.

Every rule here is written out in `mechanical-definitions.md` section 8.
"""

import numpy as np
import pandas as pd

from pdtm_common import MIN_OPEN

LAST_EXIT_MIN = 15 * 60 + 55 - MIN_OPEN   # 12:55 Pacific, column index 385

EXIT_STOP, EXIT_TARGET, EXIT_TIME, EXIT_NOBAR = 0, 1, 2, 3
EXIT_NAME = {0: "stop", 1: "target", 2: "time", 3: "no-exit-bar"}


def _first_bar_at_or_after(open_row, col):
    """Column of the first minute at or after `col` that really traded."""
    n = open_row.shape[0]
    while col < n:
        if np.isfinite(open_row[col]):
            return col
        col += 1
    return -1


OPEN_30_END = 30          # column 30 = 07:00 Pacific


def simulate(panel, signals: pd.DataFrame, cost_bps: float, entry_delay: int = 0,
             open_cost_bps: float = None) -> pd.DataFrame:
    """Walk every signal to its exit.

    signals needs: row (panel row index), confirm_min (column of the bar that
    CLOSED the confirmation), side (+1 long, -1 short), stop, target.
    Entry is the first real trade of the next minute after confirmation, plus
    `entry_delay` further minutes for the stress run.

    `open_cost_bps`, when given, is charged instead of `cost_bps` on any trade
    entered before 07:00 Pacific.  Spreads are widest in the first half hour by
    a margin nobody in this research could measure from a source they actually
    read, so the conservative response is to charge the harsh rate there rather
    than invent a number.
    """
    o, h, l, c = panel.o, panel.h, panel.l, panel.c
    n = len(signals)
    out = {k: np.full(n, np.nan) for k in
           ("entry_px", "exit_px", "gross", "net", "mfe", "mae", "cost_bps")}
    out["entry_min"] = np.full(n, -1, dtype=np.int32)
    out["exit_min"] = np.full(n, -1, dtype=np.int32)
    out["exit_kind"] = np.full(n, EXIT_NOBAR, dtype=np.int8)
    out["bars_held"] = np.zeros(n, dtype=np.int32)

    rows = signals.row.values
    cmin = signals.confirm_min.values
    side = signals.side.values
    stop = signals.stop.values
    targ = signals.target.values

    for i in range(n):
        r = rows[i]
        e = _first_bar_at_or_after(o[r], cmin[i] + 1 + entry_delay)
        if e < 0 or e > LAST_EXIT_MIN:
            continue
        px = float(o[r][e])
        s, st, tg = side[i], stop[i], targ[i]
        out["entry_px"][i] = px
        out["entry_min"][i] = e

        hi, lo, op, cl = h[r], l[r], o[r], c[r]
        exit_px, exit_min, kind = np.nan, -1, EXIT_NOBAR
        best, worst = px, px
        j = e
        while j <= LAST_EXIT_MIN:
            if np.isfinite(op[j]):
                bo, bh, bl = op[j], hi[j], lo[j]
                if s > 0:
                    best, worst = max(best, bh), min(worst, bl)
                    # a gap straight through the stop exits at the real print
                    if bo <= st:
                        exit_px, kind = bo, EXIT_STOP
                    elif bl <= st:                      # stop first when both hit
                        exit_px, kind = st, EXIT_STOP
                    elif bo >= tg:
                        exit_px, kind = bo, EXIT_TARGET
                    elif bh >= tg:
                        exit_px, kind = tg, EXIT_TARGET
                else:
                    best, worst = min(best, bl), max(worst, bh)
                    if bo >= st:
                        exit_px, kind = bo, EXIT_STOP
                    elif bh >= st:
                        exit_px, kind = st, EXIT_STOP
                    elif bo <= tg:
                        exit_px, kind = bo, EXIT_TARGET
                    elif bl <= tg:
                        exit_px, kind = tg, EXIT_TARGET
                if kind != EXIT_NOBAR:
                    exit_min = j
                    break
            j += 1

        if kind == EXIT_NOBAR:
            # ran out of time: leave at the last real trade at or before 12:55
            k = LAST_EXIT_MIN
            while k >= e and not np.isfinite(cl[k]):
                k -= 1
            if k < e:
                continue
            exit_px, exit_min, kind = float(cl[k]), k, EXIT_TIME

        g = s * (exit_px / px - 1.0)
        cb = cost_bps if (open_cost_bps is None or e >= OPEN_30_END) else open_cost_bps
        out["cost_bps"][i] = cb
        out["exit_px"][i] = exit_px
        out["exit_min"][i] = exit_min
        out["exit_kind"][i] = kind
        out["gross"][i] = g
        out["net"][i] = g - cb / 10000.0
        out["bars_held"][i] = exit_min - e
        out["mfe"][i] = s * (best / px - 1.0)
        out["mae"][i] = s * (worst / px - 1.0)

    res = signals.copy().reset_index(drop=True)
    for k, v in out.items():
        res[k] = v
    res["exit_reason"] = [EXIT_NAME[int(k)] for k in res.exit_kind]
    return res[np.isfinite(res.net.values)].reset_index(drop=True)


def one_position_per_symbol(trades: pd.DataFrame) -> pd.DataFrame:
    """Drop any signal that fired in a company while a position in that same
    company was still open.  Discarded, never queued."""
    trades = trades.sort_values(["symbol", "date", "entry_min"], ignore_index=True)
    keep = np.ones(len(trades), dtype=bool)
    open_until = {}
    for i, (sym, dt, em, xm) in enumerate(zip(trades.symbol, trades.date,
                                              trades.entry_min, trades.exit_min)):
        key = (sym, dt)
        if key in open_until and em <= open_until[key]:
            keep[i] = False
        else:
            open_until[key] = xm
    return trades[keep].reset_index(drop=True)
