#!/usr/bin/env python3
"""Frozen mechanical definitions for TODO #106, as code.

Every definition here was written before any profit number was computed.  The
prose version lives in
`.omc/research/professional-day-trader-methods/mechanical-definitions.md`
and must agree with this file line for line.

Nothing here looks at a future bar.  Where a field is stamped at minute `t` it
uses bars up to and including `t-1` unless the docstring says otherwise.
"""

import numpy as np
import pandas as pd

from pdtm_common import MIN_OPEN, N_MIN, OR_LAST, Panel, ffill_close

# --------------------------------------------------------------- constants --
BIN_BPS = 10.0          # price-bin width for a volume profile, in basis points
BIN_FLOOR = 0.01        # never finer than one cent
VALUE_AREA_FRAC = 0.70  # share of session volume inside the value area


def bin_width(ref_price):
    """Frozen price-bin width: 10 basis points of the session's first trade,
    rounded to a cent, never below a cent."""
    w = np.round(ref_price * BIN_BPS / 10000.0, 2)
    return np.maximum(w, BIN_FLOOR)


def _profile_one(low, high, vol, lo_edge, width, nbins):
    """Spread each minute's volume uniformly over the price bins its
    low-to-high range touches.

    One-minute bars do not say how volume was distributed among prices inside
    the minute, so this is an approximation and is labelled as one everywhere.
    The allocation rule is frozen: uniform across touched bins, inclusive.
    """
    ok = np.isfinite(low) & np.isfinite(high) & (vol > 0)
    if not ok.any():
        return np.zeros(nbins, dtype=np.float64)
    # +1e-9 absorbs binary-float error so a price exactly on a bin edge lands
    # in the bin above it rather than one below
    lo = np.clip(np.floor((low[ok] - lo_edge) / width + 1e-9).astype(np.int64), 0, nbins - 1)
    hi = np.clip(np.floor((high[ok] - lo_edge) / width + 1e-9).astype(np.int64), 0, nbins - 1)
    v = vol[ok].astype(np.float64)
    span = (hi - lo + 1).astype(np.float64)
    share = v / span
    # scatter-add over the touched span, without a python loop per bar:
    # +share at the first bin, -share just past the last, then cumulative sum
    ends = hi + 1
    tail = np.zeros(nbins + 1, dtype=np.float64)
    np.add.at(tail, lo, share)
    np.add.at(tail, ends, -share)
    return np.cumsum(tail[:-1])


def value_area(prof, lo_edge, width, frac=VALUE_AREA_FRAC):
    """Point of control and value-area edges, standard market-profile rule:
    start at the busiest bin, then repeatedly absorb whichever neighbouring
    PAIR of bins holds more volume, until `frac` of the session is inside."""
    total = prof.sum()
    if total <= 0:
        return np.nan, np.nan, np.nan
    poc = int(prof.argmax())
    target = total * frac
    lo = hi = poc
    got = prof[poc]
    n = len(prof)
    while got < target and (lo > 0 or hi < n - 1):
        below = prof[max(lo - 2, 0):lo].sum() if lo > 0 else -1.0
        above = prof[hi + 1:min(hi + 3, n)].sum() if hi < n - 1 else -1.0
        if above >= below:
            hi = min(hi + 2, n - 1)
        else:
            lo = max(lo - 2, 0)
        got = prof[lo:hi + 1].sum()
    return (lo_edge + (poc + 0.5) * width,
            lo_edge + (hi + 1) * width,
            lo_edge + lo * width)


def session_profiles(p: Panel, sess: pd.DataFrame) -> pd.DataFrame:
    """POC, value-area high and value-area low for every session in `p`.

    Built from that session's own completed bars only.  A session's profile is
    therefore known in full only after its close, which is exactly how it is
    used: as YESTERDAY's location for today's decisions.
    """
    order = {(s, d): i for i, (s, d) in enumerate(zip(p.idx.symbol, p.idx.date))}
    rows = np.array([order[(s, d)] for s, d in zip(sess.symbol, sess.date)])
    lows, highs, vols = p.l[rows], p.h[rows], p.v[rows]
    ref = sess.sess_open.values
    widths = bin_width(ref)
    out = np.full((len(sess), 3), np.nan)
    for i in range(len(sess)):
        lo_edge, hi_edge, w = sess.sess_low.values[i], sess.sess_high.values[i], widths[i]
        if not np.isfinite(lo_edge) or not np.isfinite(hi_edge) or w <= 0:
            continue
        nb = int((hi_edge - lo_edge) / w) + 1
        if nb <= 0 or nb > 20000:
            continue
        prof = _profile_one(lows[i], highs[i], vols[i], lo_edge, w, nb)
        out[i] = value_area(prof, lo_edge, w)
    return pd.DataFrame(out, columns=["poc", "vah", "val"], index=sess.index)


# ------------------------------------------------------------- composites --
def composites(p: Panel, sess: pd.DataFrame):
    """Per symbol-date-minute return since that stock's own opening print, and
    the leave-one-out mean of the same across (a) all 60 names and (b) the
    stock's own sector.

    This is the project's ONLY intraday market and sector reference: the local
    minute files contain no index fund and no sector fund at all.  It is a
    60-large-cap composite, and is never called an index or a market internal.
    """
    c = ffill_close(p)
    op = sess.sess_open.values.astype(np.float32)[:, None]
    ret = c / op - 1.0                                    # (n, 390)

    dates = sess.date.values
    dcode, _ = pd.factorize(dates)
    n_d = dcode.max() + 1
    finite = np.isfinite(ret)
    r0 = np.where(finite, ret, 0.0)

    tot = np.zeros((n_d, N_MIN), dtype=np.float64)
    cnt = np.zeros((n_d, N_MIN), dtype=np.float64)
    np.add.at(tot, dcode, r0)
    np.add.at(cnt, dcode, finite)
    mkt = (tot[dcode] - r0) / np.maximum(cnt[dcode] - finite, 1)
    mkt = np.where(cnt[dcode] - finite > 0, mkt, np.nan)

    scode, _ = pd.factorize(sess.sector.values.astype(str) + "|" + dates.astype(str))
    n_s = scode.max() + 1
    tot_s = np.zeros((n_s, N_MIN), dtype=np.float64)
    cnt_s = np.zeros((n_s, N_MIN), dtype=np.float64)
    np.add.at(tot_s, scode, r0)
    np.add.at(cnt_s, scode, finite)
    peers = cnt_s[scode] - finite
    sec = np.where(peers > 0, (tot_s[scode] - r0) / np.maximum(peers, 1), np.nan)
    return ret.astype(np.float32), mkt.astype(np.float32), sec.astype(np.float32), peers.astype(np.int16)


def cum_volume(p: Panel):
    """Volume traded so far today, counting only bars that have already closed.

    Column `t` holds the total over minutes MIN_OPEN .. t-1, so a rule reading
    it at minute `t` never uses the volume of the bar it is standing in.
    """
    cv = np.cumsum(p.v, axis=1)
    out = np.zeros_like(cv)
    out[:, 1:] = cv[:, :-1]
    return out


def relative_volume(p: Panel, sess: pd.DataFrame, cv: np.ndarray, window: int = 20):
    """Today's completed volume at each minute divided by the median completed
    volume at the SAME minute over the previous `window` sessions of the same
    stock.  Yesterday is the newest session in the window; today is excluded.
    """
    sym = sess.symbol.values
    out = np.full(cv.shape, np.nan, dtype=np.float32)
    for s in pd.unique(sym):
        m = np.where(sym == s)[0]
        block = cv[m]
        med = np.full_like(block, np.nan)
        for i in range(window, len(m)):
            med[i] = np.median(block[i - window:i], axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[m] = np.where(med > 0, block / med, np.nan)
    return out
