"""Cheap pre-screen for TODO #111 round 3.

Round 2 measured eleven entry triggers and rejected all eleven. The owner's
verdict was that all eleven were the same shape of idea: one condition, on one
chart, of one stock. Round 3 tests genuinely different MECHANISMS:

  - the two strategies the owner named by hand (the fifteen-minute opening
    range and the overnight range), which the narrowed rejected-family rule
    now allows;
  - two conditions that must agree;
  - the time of day used as the condition itself;
  - the character of the day so far - already trending, or going nowhere;
  - the stock's place in the whole group of sixty, not its own chart.

The rules that keep this honest are unchanged from round 2:

  1. Everything here runs on the DEVELOPMENT period only. The bars from
     DEV_END onward are dropped before anything is computed.
  2. Every idea's numbers are recorded whether it lives or dies.
  3. Entry is always the open of the bar AFTER the signal bar, and exits come
     from the frozen bracket engine. Returns are GROSS.

New in round 3: MATCHED baselines. Round 2's single baseline of 34.47% was
measured over every minute of the day. These families trade at particular
times, and the odds of a bracket are not the same at 09:45 as at 15:30 - a
trade opened late in the day has more overnight gaps inside its fourteen days.
So each family is scored against a baseline that trades the same window with
no trigger at all.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import todo_111_round2_bracket as B
import todo_111_round2_prescreen as P

OUT = Path("/home/openclaw/.openclaw/workspace/.omc/research")

DEV_END = P.DEV_END
LAST_SIGNAL = P.LAST_SIGNAL

# New York minutes-of-day.
OPEN_MIN = 9 * 60 + 30          # 09:30
OR_END = 9 * 60 + 45            # first fifteen minutes are 09:30 - 09:44
MID_MIN = 11 * 60               # 11:00, the "day so far" checkpoint
CLOSE_MIN = 16 * 60             # 16:00
LAST_ENTRY_MIN = 15 * 60 + 45   # no new signal after 15:45


def frame(sym, feed):
    """One symbol's development bars with everything the families need."""
    df = B.load(sym, feed)
    if df is None:
        return None
    df = df[df["ts"] < DEV_END].reset_index(drop=True)
    if len(df) < 5000:
        return None
    ny = df["ts"].dt.tz_convert("America/New_York")
    df["min"] = (ny.dt.hour * 60 + ny.dt.minute).to_numpy()
    # Session ordinal: 0, 1, 2 ... in date order, so "the session before" is
    # just one less and the overnight window can be keyed to the day it ends.
    _, df["day"] = np.unique(df["date"].to_numpy(), return_inverse=True)
    df["rth"] = (df["min"] >= OPEN_MIN) & (df["min"] < CLOSE_MIN)
    return df


def _first_per_day(mask, day):
    """Indices of the FIRST bar each session where the mask is true."""
    idx = np.flatnonzero(np.nan_to_num(mask, nan=0).astype(bool))
    if len(idx) == 0:
        return idx
    d = day[idx]
    keep = np.ones(len(idx), bool)
    keep[1:] = d[1:] != d[:-1]
    return idx[keep]


def _per_day(df, mask, col, how):
    """A per-session aggregate of one column over the masked bars, broadcast
    back onto every bar of that session."""
    s = df[col].where(mask)
    g = s.groupby(df["day"]).agg(how)
    return df["day"].map(g).to_numpy(np.float64)


def opening_range(df):
    """High and low of the first fifteen minutes, on every bar of the day."""
    m = df["min"].to_numpy()
    win = (m >= OPEN_MIN) & (m < OR_END)
    return _per_day(df, win, "high", "max"), _per_day(df, win, "low", "min")


def overnight_range(df):
    """High and low of everything traded between yesterday's close and today's
    open. Bars after 16:00 belong to the NEXT session's overnight window, so
    they are keyed one session forward.

    This is the thin part of the tape. A bar exists only when a trade printed
    on this venue, and EQUS.MINI is about a fifth of the tape, so a quiet name
    can have five or six overnight bars for the whole night. Sessions with
    fewer than MIN_ON_BARS prints are skipped rather than guessed at.
    """
    MIN_ON_BARS = 4
    m = df["min"].to_numpy()
    day = df["day"].to_numpy()
    key = np.where(m < OPEN_MIN, day, np.where(m >= CLOSE_MIN, day + 1, -1))
    ok = key >= 0
    k = pd.Series(np.where(ok, key, -1))
    hi = df["high"].where(ok).groupby(k).max()
    lo = df["low"].where(ok).groupby(k).min()
    cnt = df["high"].where(ok).groupby(k).count()
    thin = cnt[cnt < MIN_ON_BARS].index
    hi.loc[hi.index.isin(thin)] = np.nan
    lo.loc[lo.index.isin(thin)] = np.nan
    d = pd.Series(day)
    return d.map(hi).to_numpy(np.float64), d.map(lo).to_numpy(np.float64)


def day_so_far(df):
    """The shape of the session up to 11:00: where it opened, how far it has
    travelled, and where it sits inside that travel.

    strength runs from 0 to 1. Near 1 the name has spent the morning climbing
    and is sitting at the top of its own range - a trend day. Near 0.5 it has
    gone nowhere and come back - a range day.
    """
    m = df["min"].to_numpy()
    win = (m >= OPEN_MIN) & (m <= MID_MIN)
    hi = _per_day(df, win, "high", "max")
    lo = _per_day(df, win, "low", "min")
    op = _per_day(df, (m >= OPEN_MIN) & (m < OPEN_MIN + 5), "open", "first")
    px = _per_day(df, (m >= MID_MIN - 2) & (m <= MID_MIN), "close", "last")
    span = hi - lo
    with np.errstate(invalid="ignore", divide="ignore"):
        strength = np.where(span > 0, (px - lo) / span, np.nan)
        width = np.where(op > 0, span / op, np.nan)
    return {"hi": hi, "lo": lo, "open": op, "mid_px": px,
            "strength": strength, "width": width}


def tradable(df):
    m = df["min"].to_numpy()
    ok = (m >= OR_END) & (m <= LAST_ENTRY_MIN)
    ok &= (df["ts"] < LAST_SIGNAL).to_numpy()
    return ok


# --- the mechanisms -------------------------------------------------------

def orb15_break(df, fade=False):
    """OWNER-NAMED. The high and the low of the first fifteen minutes after the
    open. The first time the price leaves that range, trade the break: above
    the high is a buy, below the low is a short.

    Reasoning: the first fifteen minutes is where the overnight news gets
    priced. Once the price leaves the box the crowd built there, the orders
    resting at its edge are gone and there is nothing holding it.
    """
    hi, lo = opening_range(df)
    c = df["close"].to_numpy(np.float64)
    up = c > hi
    dn = c < lo
    ok = tradable(df) & (up | dn)
    idx = _first_per_day(ok, df["day"].to_numpy())
    if len(idx) == 0:
        return idx, idx
    dirn = np.where(up[idx], 1.0, -1.0)
    return idx, -dirn if fade else dirn


def orb15_fade(df):
    """The same trigger traded the other way: the break is a false one and the
    price comes back into the box."""
    return orb15_break(df, fade=True)


def overnight_break(df, fade=False):
    """OWNER-NAMED. The high and low made between yesterday's close and today's
    open, traded on the first break of either side during regular hours.

    Reasoning: the overnight session is thin, so the levels it makes are the
    work of a few participants; regular hours either confirms them or does not.
    Data caveat, and it is a real one: this range is built from a handful of
    prints on a fifth of the tape.
    """
    hi, lo = overnight_range(df)
    c = df["close"].to_numpy(np.float64)
    up = c > hi
    dn = c < lo
    ok = tradable(df) & np.isfinite(hi) & (up | dn)
    idx = _first_per_day(ok, df["day"].to_numpy())
    if len(idx) == 0:
        return idx, idx
    dirn = np.where(up[idx], 1.0, -1.0)
    return idx, -dirn if fade else dirn


def overnight_fade(df):
    return overnight_break(df, fade=True)


_MARKET = {}


def market_move(df):
    """The whole group's half-hour move at each of this name's bars. Built once
    by todo_111_round2_market_move.py; the median of all sixty names, so one
    name's news cannot move the yardstick."""
    if "s" not in _MARKET:
        m = pd.read_parquet(P.MARKET_PATH)
        _MARKET["s"] = pd.Series(m["market_ret30"].to_numpy(),
                                 index=pd.DatetimeIndex(m["ts"]))
    return _MARKET["s"].reindex(pd.DatetimeIndex(df["ts"])).to_numpy()


def orb15_with_market(df):
    """TWO CONDITIONS THAT MUST AGREE. The name breaks its opening range AND
    the other fifty-nine are moving the same way at that minute.

    Reasoning: a break that the whole group is not backing is one name's own
    business and can be reversed by a single seller; a break that the group is
    pushing has the market behind it. Nothing in round 2 required two things
    to line up.
    """
    idx, dirn = orb15_break(df)
    if len(idx) == 0:
        return idx, dirn
    mkt = market_move(df)[idx]
    agree = np.isfinite(mkt) & (np.sign(mkt) == dirn) & (np.abs(mkt) > 0.0005)
    return idx[agree], dirn[agree]


def orb15_wide_day(df):
    """THE CHARACTER OF THE DAY. Take the opening-range break only on days when
    the morning range is unusually wide for this name - at least 1.5 times its
    own recent normal.

    Reasoning: a bracket needs a 1% move before a 0.5% one. On a quiet day
    neither level is reached and the trade times out; on a day that is already
    moving twice as much as usual, both levels are live. This asks whether the
    kind of day matters more than the trigger does.
    """
    idx, dirn = orb15_break(df)
    if len(idx) == 0:
        return idx, dirn
    d = day_so_far(df)
    m = df["min"].to_numpy()
    win = (m >= OPEN_MIN) & (m < OR_END)
    with np.errstate(invalid="ignore", divide="ignore"):
        or_width = (_per_day(df, win, "high", "max")
                    - _per_day(df, win, "low", "min")) / d["open"]
    # The opening range is compared against this name's own recent opening
    # ranges, one number per session, never against its whole morning.
    per_day = pd.Series(or_width).groupby(df["day"]).first()
    norm = df["day"].map(
        per_day.rolling(20, min_periods=10).median().shift(1)).to_numpy(np.float64)
    wide = np.isfinite(norm) & (or_width > 1.5 * norm)
    return idx[wide[idx]], dirn[wide[idx]]


def trend_day_continuation(df):
    """THE TIME OF DAY AS THE CONDITION. At 11:00 exactly, look at what the
    session has done so far. If the name has climbed all morning and is sitting
    in the top quarter of its own morning range, buy; bottom quarter, short.
    No other trigger, and no other time of day.

    Reasoning: a name that has held one direction for ninety minutes is being
    accumulated or distributed by someone who is not finished. Round 2 never
    used the clock as a reason to trade.
    """
    d = day_so_far(df)
    m = df["min"].to_numpy()
    at_mid = (m >= MID_MIN - 2) & (m <= MID_MIN)
    s = d["strength"]
    ok = at_mid & np.isfinite(s) & ((s > 0.75) | (s < 0.25))
    ok &= (df["ts"] < LAST_SIGNAL).to_numpy()
    idx = _first_per_day(ok, df["day"].to_numpy())
    if len(idx) == 0:
        return idx, idx
    return idx, np.where(s[idx] > 0.5, 1.0, -1.0)


def range_day_fade(df):
    """THE CHARACTER OF THE DAY, THE OTHER WAY. If by 11:00 the name has gone
    nowhere - it sits in the middle of a morning range it has crossed and
    re-crossed - then the first time it touches the day's high after 11:00,
    short it; the first time it touches the day's low, buy it.

    Reasoning: on a day with no direction the extremes are where the two sides
    keep turning it around. This is the mirror of the trend-day idea, and
    seeing both move is the test of whether the day's character does anything.
    """
    d = day_so_far(df)
    m = df["min"].to_numpy()
    s = d["strength"]
    quiet = np.isfinite(s) & (s > 0.35) & (s < 0.65)
    after = (m > MID_MIN) & (m <= LAST_ENTRY_MIN)
    c = df["close"].to_numpy(np.float64)
    at_hi = c >= d["hi"]
    at_lo = c <= d["lo"]
    ok = quiet & after & (at_hi | at_lo) & (df["ts"] < LAST_SIGNAL).to_numpy()
    idx = _first_per_day(ok, df["day"].to_numpy())
    if len(idx) == 0:
        return idx, idx
    return idx, np.where(at_hi[idx], -1.0, 1.0)


def baseline_break_window(df):
    """MATCHED BASELINE for every family that trades between 09:45 and 15:45.
    No trigger at all: one entry a day, at a minute picked by the calendar
    rather than by anything observed, direction alternating."""
    m = df["min"].to_numpy()
    ok = tradable(df) & (m == 11 * 60 + 30)
    idx = _first_per_day(ok, df["day"].to_numpy())
    if len(idx) == 0:
        return idx, idx
    return idx, np.where(np.arange(len(idx)) % 2 == 0, 1.0, -1.0)


def baseline_mid(df):
    """MATCHED BASELINE for the two 11:00 families: enter at 11:00 every day,
    direction alternating, nothing observed."""
    m = df["min"].to_numpy()
    ok = (m >= MID_MIN - 2) & (m <= MID_MIN) & (df["ts"] < LAST_SIGNAL).to_numpy()
    idx = _first_per_day(ok, df["day"].to_numpy())
    if len(idx) == 0:
        return idx, idx
    return idx, np.where(np.arange(len(idx)) % 2 == 0, 1.0, -1.0)


FAMILIES = {
    "baseline-1130-no-trigger": baseline_break_window,
    "baseline-1100-no-trigger": baseline_mid,
    "orb15-break": orb15_break,
    "orb15-fade": orb15_fade,
    "overnight-break": overnight_break,
    "overnight-fade": overnight_fade,
    "orb15-plus-market-agrees": orb15_with_market,
    "orb15-on-wide-day": orb15_wide_day,
    "trend-day-continuation": trend_day_continuation,
    "range-day-fade": range_day_fade,
}


def screen(name, fn, feed="equs", symbols=None):
    frames = []
    for sym in (symbols or B.symbols(feed)):
        df = frame(sym, feed)
        if df is None:
            continue
        idx, dirn = fn(df)
        if len(idx) == 0:
            continue
        keep = np.asarray(dirn) != 0
        tr = B.simulate(df, np.asarray(idx)[keep], np.asarray(dirn)[keep])
        tr["symbol"] = sym
        frames.append(tr)
    if not frames:
        return {"family": name, "tradeCount": 0}
    allt = pd.concat(frames, ignore_index=True)
    out = {"family": name, "feed": feed, "period": "development",
           "devEnd": str(DEV_END.date()), "costBasis": "gross_no_costs",
           "exitPriceResolution": "one_minute"}
    out.update(B.summarise(allt))
    longs, shorts = allt[allt["direction"] > 0], allt[allt["direction"] < 0]
    out["long"] = B.summarise(longs) if len(longs) else None
    out["short"] = B.summarise(shorts) if len(shorts) else None
    return out


def main():
    feed = sys.argv[1] if len(sys.argv) > 1 else "equs"
    only = sys.argv[2:] or None
    results = []
    for name, fn in FAMILIES.items():
        if only and name not in only:
            continue
        t0 = time.time()
        r = screen(name, fn, feed)
        r["seconds"] = round(time.time() - t0, 1)
        results.append(r)
        print("%-26s %7d trades  target-first %5.2f%%  avg %+.4f%%  (%.0fs)"
              % (name, r.get("tradeCount", 0), r.get("winRatePct", 0.0),
                 r.get("avgReturnPct", 0.0), r["seconds"]), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    tag = feed if not only else feed + "-" + "-".join(only)[:40]
    path = OUT / ("todo-111-round3-prescreen-%s.json" % tag)
    path.write_text(json.dumps(results, indent=2))
    print("wrote", path)


if __name__ == "__main__":
    main()
