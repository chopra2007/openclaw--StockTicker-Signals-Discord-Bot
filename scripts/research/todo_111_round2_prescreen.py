"""Cheap pre-screen for TODO #111 round 2.

Before any idea is registered as a candidate and tested properly, it has to show
that its entry trigger moves the target-first rate away from the unconditional
baseline. The baseline is about 34 in 100. The owner's bar is 60 in 100. An idea
that cannot even reach roughly 40 in 100 here can never reach 60, and it is
killed on the spot and written into the rejection ledger.

Two rules keep this honest:

  1. Every measurement here runs on the DEVELOPMENT period only. The period from
     DEV_END onward is sealed and is never read by this file.
  2. Every idea's numbers are recorded whether it lives or dies.

Entries are always taken on the open of the bar AFTER the signal bar, and exits
come from the frozen bracket engine. Returns are GROSS.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import todo_111_round2_bracket as B

OUT = Path("/home/openclaw/.openclaw/workspace/.omc/research")

# Everything before this date is for building ideas on. Everything on or after
# it is sealed and untouched until a rule has been frozen.
DEV_END = pd.Timestamp("2025-07-01", tz="UTC")

# A trade opened on the last development day would still be running three weeks
# later, so the last signal is taken three weeks before the seal. Nothing on or
# after DEV_END is ever read here, not even to close a trade.
LAST_SIGNAL = DEV_END - pd.Timedelta(days=21)

# The regular session only, and never the first 5 or last 15 minutes: the open
# is a different animal and the last quarter hour cannot hold a 14-day trade
# open without straddling the close.
FIRST_MIN = 9 * 60 + 35
LAST_MIN = 15 * 60 + 45


def features(df):
    """Everything the screens below need, computed once per symbol."""
    ny = df["ts"].dt.tz_convert("America/New_York")
    mins = (ny.dt.hour * 60 + ny.dt.minute).to_numpy()
    close = df["close"].to_numpy(np.float64)
    ret1 = np.zeros(len(close))
    ret1[1:] = np.diff(close) / close[:-1]
    s = pd.Series(ret1)
    vol = s.rolling(390, min_periods=200).std().to_numpy()
    volume = df["volume"].to_numpy(np.float64)
    vmed = pd.Series(volume).rolling(390, min_periods=200).median().to_numpy()
    ret15 = np.full(len(close), np.nan)
    ret15[15:] = close[15:] / close[:-15] - 1.0
    ret30 = np.full(len(close), np.nan)
    ret30[30:] = close[30:] / close[:-30] - 1.0
    # The half-hour range must EXCLUDE the current bar, or the current close can
    # never break out of a window that already contains it.
    hi30 = pd.Series(df["high"].to_numpy(np.float64)).rolling(30).max().shift(1).to_numpy()
    lo30 = pd.Series(df["low"].to_numpy(np.float64)).rolling(30).min().shift(1).to_numpy()
    tradable = (mins >= FIRST_MIN) & (mins <= LAST_MIN)
    tradable &= (df["ts"] < LAST_SIGNAL).to_numpy()
    return {"mins": mins, "close": close, "ret1": ret1, "vol": vol,
            "volume": volume, "vmed": vmed, "ret15": ret15, "ret30": ret30,
            "hi30": hi30, "lo30": lo30, "tradable": tradable}


def _ok(mask):
    return np.flatnonzero(np.nan_to_num(mask, nan=0).astype(bool))


# --- the idea families ----------------------------------------------------

def ignition(f, k=4.0, vmult=3.0):
    """A one-minute move far bigger than the name's normal minute, on far more
    volume than normal. Reasoning: that combination is information arriving -
    news, a block, an upgrade - and information is absorbed over minutes to
    hours, so the move continues. Trade WITH the move."""
    big = np.abs(f["ret1"]) > k * f["vol"]
    loud = f["volume"] > vmult * f["vmed"]
    hit = f["tradable"] & big & loud
    idx = _ok(hit)
    return idx, np.sign(f["ret1"][idx])


def ignition_fade(f, k=4.0, vmult=3.0):
    """The same trigger, traded the other way. Reasoning: a one-minute spike on
    heavy volume is often a liquidity event rather than news, and the price
    snaps back once the impatient order is finished."""
    idx, dirn = ignition(f, k, vmult)
    return idx, -dirn


def stretch_fade(f, k=3.0):
    """Fifteen minutes of one-way movement far beyond the name's normal
    fifteen. Reasoning: a crowd chasing a short move overshoots and the price
    reverts. Trade AGAINST the stretch."""
    scale = f["vol"] * np.sqrt(15.0)
    hit = f["tradable"] & (np.abs(f["ret15"]) > k * scale)
    idx = _ok(hit)
    return idx, -np.sign(f["ret15"][idx])


def stretch_run(f, k=3.0):
    """The same trigger, traded with the move instead - a short trend that
    keeps going."""
    idx, dirn = stretch_fade(f, k)
    return idx, -dirn


def range_break(f, pad=0.0005):
    """The price breaks clear of its own last half hour. Reasoning: a break of
    a well-defined recent range is where resting orders sit; once they are
    taken out there is nothing above until the next shelf."""
    close = f["close"]
    up = close > f["hi30"] * (1 + pad)
    dn = close < f["lo30"] * (1 - pad)
    hit = f["tradable"] & (up | dn)
    idx = _ok(hit)
    return idx, np.where(up[idx], 1.0, -1.0)


def squeeze_break(f, tight=0.5, pad=0.0002):
    """The last half hour was unusually QUIET, then the price leaves it.
    Reasoning: a quiet range means both sides are balanced; the first side to
    give way tends to keep giving way. Different from the plain break above
    because the quiet is the condition, not the break."""
    width = (f["hi30"] - f["lo30"]) / f["close"]
    normal = pd.Series(width).rolling(390, min_periods=200).median().to_numpy()
    quiet = width < tight * normal
    up = f["close"] > f["hi30"] * (1 + pad)
    dn = f["close"] < f["lo30"] * (1 - pad)
    hit = f["tradable"] & quiet & (up | dn)
    idx = _ok(hit)
    return idx, np.where(up[idx], 1.0, -1.0)


def half_hour_drift(f, k=2.0):
    """A steady half-hour move that is large but NOT a spike: the biggest single
    minute inside it is ordinary. Reasoning: steady one-way pressure is a large
    order being worked, and a worked order is not finished in half an hour."""
    scale = f["vol"] * np.sqrt(30.0)
    steady = np.abs(f["ret30"]) > k * scale
    calm = np.abs(f["ret1"]) < 2.0 * f["vol"]
    hit = f["tradable"] & steady & calm
    idx = _ok(hit)
    return idx, np.sign(f["ret30"][idx])


FAMILIES = {
    "ignition-continuation": ignition,
    "ignition-fade": ignition_fade,
    "stretch-fade": stretch_fade,
    "stretch-continuation": stretch_run,
    "half-hour-range-break": range_break,
    "quiet-range-break": squeeze_break,
    "worked-order-drift": half_hour_drift,
}


def screen(name, fn, feed="equs", symbols=None, cap_per_symbol=4000):
    frames = []
    for sym in (symbols or B.symbols(feed)):
        df = B.load(sym, feed)
        # The seal is literal: the sealed bars are dropped before anything here
        # can look at them.
        df = df[df["ts"] < DEV_END].reset_index(drop=True)
        f = features(df)
        idx, dirn = fn(f)
        if len(idx) == 0:
            continue
        if len(idx) > cap_per_symbol:
            step = len(idx) // cap_per_symbol + 1
            idx, dirn = idx[::step], dirn[::step]
        keep = dirn != 0
        tr = B.simulate(df, idx[keep], dirn[keep])
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
    results = []
    for name, fn in FAMILIES.items():
        t0 = time.time()
        r = screen(name, fn, feed)
        r["seconds"] = round(time.time() - t0, 1)
        results.append(r)
        print("%-24s %7d trades  target-first %5.2f%%  avg %+.4f%%  (%.0fs)"
              % (name, r.get("tradeCount", 0), r.get("winRatePct", 0.0),
                 r.get("avgReturnPct", 0.0), r["seconds"]), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / ("todo-111-round2-prescreen-%s.json" % feed)
    path.write_text(json.dumps(results, indent=2))
    print("wrote", path)


if __name__ == "__main__":
    main()
