"""First-touch bracket engine for the todo-111-trading-edge-round2 mission.

Given entry signals, simulate the owner's exit rule on one-minute bars:

  long   trade: exit at the first touch of entry * (1 + target) or entry * (1 - stop)
  short  trade: exit at the first touch of entry * (1 - target) or entry * (1 + stop)
  neither touched inside the holding cap: exit at the close of the last bar in range

Honesty rules, all deliberately conservative:
  - Entry is the OPEN of the bar AFTER the signal bar. No signal bar is tradable.
  - Within one minute bar we only know open/high/low/close, never the path. If
    that bar could have touched both the target and the stop, the STOP is
    assumed to have come first.
  - A gap through a level fills at the bar's open, not at the level, so a
    gap-through loses more than the nominal stop. The realised return is
    recorded, never the nominal one.
  - Bars are stamped at the start of the minute (Databento convention).

Returns are GROSS: no commission, no spread, no slippage. That is the owner's
frozen instruction; costs are subtracted by the owner after a rule passes.
"""
from pathlib import Path

import numpy as np
import pandas as pd

MINUTES = Path("/home/openclaw/.openclaw/research-data/todo-111-round2/minutes")

TARGET_PCT = 1.0
STOP_PCT = 0.5
MAX_HOLD_TRADING_DAYS = 14

# 390 regular-session minutes a day; the feed also carries pre/post bars, so
# allow generous headroom and enforce the real cap on session dates instead.
_MAX_BARS = 14 * 960


def load(symbol, feed="equs"):
    """One symbol's minute bars, sorted, with a session-date column."""
    path = MINUTES / ("%s__%s.parquet" % (feed, symbol))
    if not path.exists():
        return None
    df = pd.read_parquet(path).sort_values("ts").reset_index(drop=True)
    # Eastern session date; the exchange runs on Eastern even though every
    # number the owner sees is labelled Pacific.
    df["date"] = df["ts"].dt.tz_convert("America/New_York").dt.date
    return df


_CHUNK = 512


def _first_touch(h, lo, i, end, tgt, stp, dirn):
    """Offsets of the first target touch and the first stop touch after entry.

    Walks forward in chunks and stops at the first chunk that contains a touch,
    because almost every trade resolves in the first day or two and scanning the
    whole 14-day window for all of them is wasted work. Whichever level is not
    found in that chunk can only be later, so -1 is returned for it; every
    caller only ever compares the two offsets.
    """
    a = i
    while a < end:
        b = a + _CHUNK
        if b > end:
            b = end
        hh = h[a:b]
        ll = lo[a:b]
        if dirn > 0:
            hit_t = hh >= tgt
            hit_s = ll <= stp
        else:
            hit_t = ll <= tgt
            hit_s = hh >= stp
        any_t = hit_t.any()
        any_s = hit_s.any()
        if any_t or any_s:
            off = a - i
            jt = off + int(np.argmax(hit_t)) if any_t else -1
            js = off + int(np.argmax(hit_s)) if any_s else -1
            return jt, js
        a = b
    return -1, -1


def simulate(df, entry_idx, direction, target_pct=TARGET_PCT, stop_pct=STOP_PCT,
             max_hold_days=MAX_HOLD_TRADING_DAYS):
    """Run the bracket for one symbol.

    entry_idx  indices of SIGNAL bars; the trade enters at the next bar's open
    direction  +1 long, -1 short, per signal
    Returns a DataFrame, one row per trade.
    """
    o = df["open"].to_numpy(np.float64)
    h = df["high"].to_numpy(np.float64)
    lo = df["low"].to_numpy(np.float64)
    c = df["close"].to_numpy(np.float64)
    ts = df["ts"].to_numpy()
    dates = df["date"].to_numpy()
    n = len(df)

    # Map each bar to an ordinal session number so the 14-trading-day cap can
    # be enforced on sessions, not on wall-clock days.
    uniq, session_no = np.unique(dates, return_inverse=True)

    rows = []
    for si, dirn in zip(np.asarray(entry_idx), np.asarray(direction)):
        i = int(si) + 1                       # enter on the NEXT bar's open
        if i >= n:
            continue
        entry = o[i]
        if not np.isfinite(entry) or entry <= 0:
            continue

        if dirn > 0:
            tgt = entry * (1.0 + target_pct / 100.0)
            stp = entry * (1.0 - stop_pct / 100.0)
        else:
            tgt = entry * (1.0 - target_pct / 100.0)
            stp = entry * (1.0 + stop_pct / 100.0)

        last_session = session_no[i] + max_hold_days - 1
        end = i + _MAX_BARS
        if end > n:
            end = n
        # trim to the holding cap measured in sessions
        seg_sessions = session_no[i:end]
        in_cap = seg_sessions <= last_session
        if not in_cap.all():
            end = i + int(np.argmin(in_cap))
        if end <= i:
            continue

        jt, js = _first_touch(h, lo, i, end, tgt, stp, dirn)

        if jt < 0 and js < 0:
            j = end - i - 1
            exit_price = c[i + j]
            outcome = "timeout"
        elif jt >= 0 and (js < 0 or jt < js):
            j = jt
            # A gap through the target would fill BETTER than the target. Never
            # claim that: a target exit is always recorded at the target price.
            exit_price = tgt
            outcome = "target"
        elif js >= 0 and (jt < 0 or js < jt):
            j = js
            op = o[i + j]
            # gap through the stop fills at the open, which is WORSE than the
            # stop; that worse price is what gets recorded
            if (dirn > 0 and op < stp) or (dirn < 0 and op > stp):
                exit_price = op
            else:
                exit_price = stp
            outcome = "stop"
        else:
            # same bar could have touched both: assume the stop came first
            j = js
            op = o[i + j]
            if (dirn > 0 and op < stp) or (dirn < 0 and op > stp):
                exit_price = op
            else:
                exit_price = stp
            outcome = "stop_ambiguous"

        ret = (exit_price - entry) / entry * 100.0 * (1 if dirn > 0 else -1)
        held = int(session_no[i + j] - session_no[i]) + 1
        rows.append((ts[i], ts[i + j], float(entry), float(exit_price),
                     int(dirn), outcome, float(ret), held))

    return pd.DataFrame(rows, columns=[
        "entry_ts", "exit_ts", "entry_px", "exit_px", "direction",
        "outcome", "return_pct", "holding_trading_days"])


def summarise(trades):
    """The four numbers the frozen gate reads, plus the outcome mix."""
    if trades.empty:
        return {"tradeCount": 0, "winRatePct": 0.0, "avgReturnPct": 0.0,
                "maxHoldingTradingDays": 0.0}
    wins = (trades["outcome"] == "target").sum()
    return {
        "tradeCount": int(len(trades)),
        "winRatePct": float(wins) / len(trades) * 100.0,
        "avgReturnPct": float(trades["return_pct"].mean()),
        "maxHoldingTradingDays": float(trades["holding_trading_days"].max()),
        "outcomeMix": {k: int(v) for k, v in trades["outcome"].value_counts().items()},
        "medianHoldingTradingDays": float(trades["holding_trading_days"].median()),
    }


def symbols(feed="equs"):
    return sorted(p.name.split("__")[1].replace(".parquet", "")
                  for p in MINUTES.glob("%s__*.parquet" % feed))
