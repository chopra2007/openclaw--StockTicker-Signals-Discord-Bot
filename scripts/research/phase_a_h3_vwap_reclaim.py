#!/usr/bin/env python3
"""Phase A test for H3 -- first-pullback / VWAP reclaim continuation.

Pre-registered hypothesis (do not edit without bumping the version --
see .omc/research/short-duration-scanner-phaseA/hypotheses-v1.md):

  Setup: stock has a same-morning directional catalyst, gaps/opens in that
  direction, then dips and closes at least one 1-minute bar on the WRONG
  side of its regular-session VWAP within the first 30 minutes.
  Entry trigger: price reclaims VWAP (closes back on the correct side) with
  volume on the reclaim bar at or above the 5-minute rolling average volume.
  Claim: the reclaim resumes the catalyst direction over the following
  30-60 minutes more often, and by more, than catalyst-direction stocks that
  NEVER dipped below VWAP at all (the "no-pullback" control).

Read-only against consensus.db and the live/historical Schwab price API.
Writes nothing back to the production database.

Reuses from the sibling H1 script (phase_a_h1_gap_continuation.py):
  - load_catalyst_candidates(): same-morning-catalyst ticker/day rows,
    deduped to the earliest alert per ticker+day ("one setup, one sample").
  - daily_prior_close(): the true prior REGULAR-SESSION close from daily
    bars -- minute bars only start at 07:00 ET on the day itself, so there
    is no earlier intraday bar to read a "prior close" from.
  - minute_bars(): extended-hours 1-minute bars for one calendar day. Schwab
    returns the WHOLE session (07:00-19:59 ET) regardless of the requested
    start/end for intraday intervals (verified live 2026-08-22, commit
    c4b0cbd) -- H1 already handles this by requesting a throwaway 1-hour
    window and slicing the returned frame to the target day; H3 needs the
    same whole-day frame (premarket not used here, but the regular session
    from 09:30 on is), so the identical function is reused as-is.
  - LOOKBACK_DAYS=40: regular-session-only minute bars are reliable back to
    ~47-49 days, but extended_hours=True bars (the code path minute_bars()
    uses) are less reliable at that distance for some tickers (AMD/INTC/MU
    returned zero rows at 46-47 days back). 40 days keeps the sample inside
    the range verified clean for every ticker tested.

Design decisions specific to H3 (documented up front, not tuned after
seeing results -- see hypotheses-v1.md's "no post-hoc rule changes" note):

  - VWAP: standard volume-weighted average of typical price (High+Low+Close)/3,
    cumulative from the 09:30 open, recomputed each bar. Regular session only
    (09:30-16:00 ET) -- extended-hours volume is excluded from the VWAP calc
    itself, matching how the hypothesis is written ("volume-weighted average
    price" during the regular session it dips against).
  - "First 30 minutes" = the first 30 one-minute bars of the regular session
    (09:30 through 09:59 inclusive).
  - "5-minute rolling average volume" = the trailing rolling mean of the
    PRECEDING 5 bars (pandas .rolling(5, min_periods=1).mean().shift(1)) --
    excludes the reclaim bar's own volume from its own average, so the
    reclaim bar's volume is compared against what came before it, not
    against a window that already contains it.
  - Reclaim search window: any bar after the dip bar, through the rest of
    the regular session. H3's entry trigger (unlike H1's "first 5 minutes")
    states no explicit search-window bound, so none is imposed here.
  - Entry/confirmation price for BOTH groups is the CLOSE of the bar that
    confirms the state: the reclaim bar's close for the treatment group, and
    the close of the 30th bar (last bar of the "never dipped" window) for
    the control group. This keeps the two groups symmetric -- both are
    priced at the moment their group membership first becomes knowable,
    not before. The forward-move window is measured from the NEXT bar
    onward, so the confirmation bar's own move isn't double-counted into
    the "remaining move" figure.
  - T+5min floor: H3's kill criteria says "fails the T+5min floor" without
    restating a number. The only floor value stated anywhere in
    hypotheses-v1.md is H2's explicit "30%-of-total-move floor used as the
    general 'edge survives delivery delay' bar for every hypothesis here" --
    that shared number is applied here unchanged, not invented for this run.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
import time
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# --- import the sibling H1 script as a module (no package/__init__.py here) ---
_H1_PATH = Path(__file__).resolve().parent / "phase_a_h1_gap_continuation.py"
_spec = importlib.util.spec_from_file_location("phase_a_h1_gap_continuation", _H1_PATH)
h1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h1)  # noqa: E402 -- gives us h1.load_catalyst_candidates,
# h1.daily_prior_close, h1.minute_bars, h1._connect, h1.ET, h1.LOOKBACK_DAYS

ET = h1.ET
LOOKBACK_DAYS = h1.LOOKBACK_DAYS  # 40 days -- see module docstring above
MIN_SAMPLE_FLOOR = h1.MIN_SAMPLE_FLOOR  # 20
REMAINING_MOVE_FLOOR_PCT = 30.0  # H2's stated shared T+5min floor (see docstring)
PRIMARY_HORIZON_MIN = 60  # upper end of H3's stated 30-60min holding window,
# matching H1's 60-minute primary horizon for direct comparability

REGULAR_OPEN = dtime(9, 30)
REGULAR_CLOSE = dtime(16, 0)


def _regular_session(bars):
    return bars[(bars.index.time >= REGULAR_OPEN) & (bars.index.time < REGULAR_CLOSE)]


def _forward_outcome(regular, ref_idx: int, ref_ts, direction: str,
                      horizon_minutes: int = PRIMARY_HORIZON_MIN) -> dict | None:
    """Forward move from the bar AFTER ref_idx (the confirmation bar) through
    horizon_minutes later. Returns None if there is no forward bar data at all
    (e.g. confirmation happened too close to the end of the available window)
    -- mirrors H1's behavior of dropping candidates it cannot score rather
    than fabricating a partial figure."""
    entry_price = float(regular["Close"].iloc[ref_idx])
    horizon_ts = ref_ts + timedelta(minutes=horizon_minutes)
    t5_ts = ref_ts + timedelta(minutes=5)
    forward = regular.iloc[ref_idx + 1:]
    forward = forward[forward.index <= horizon_ts]
    if forward.empty:
        return None
    end_price = float(forward["Close"].iloc[-1])
    at_t5 = forward[forward.index <= t5_ts]
    price_at_t5 = float(at_t5["Close"].iloc[-1]) if not at_t5.empty else entry_price

    if direction == "long":
        total_move = end_price - entry_price
        move_at_t5 = price_at_t5 - entry_price
        continued = end_price > entry_price
    else:
        total_move = entry_price - end_price
        move_at_t5 = entry_price - price_at_t5
        continued = end_price < entry_price

    remaining_after_t5 = total_move - move_at_t5
    remaining_pct_of_total = (
        round(remaining_after_t5 / total_move * 100.0, 1)
        if abs(total_move) > 1e-9 else None
    )
    return {
        "entry_price": entry_price,
        "price_at_t5": round(price_at_t5, 4),
        "end_price_horizon": end_price,
        "total_move_pct_of_entry": round(total_move / entry_price * 100.0, 3),
        "continued_horizon": continued,
        "remaining_move_pct_of_total_after_t5": remaining_pct_of_total,
    }


def evaluate_candidate(ticker: str, day, direction: str, gap_pct: float) -> dict | None:
    """Classify one ticker/day into one of three groups and (for reclaim /
    control) score the forward outcome. Returns None only when there isn't
    even enough regular-session bar data to classify the setup at all."""
    bars = h1.minute_bars(ticker, day)
    if bars is None or bars.empty:
        return None
    regular = _regular_session(bars).sort_index()
    if len(regular) < 5:
        return None

    typical_price = (regular["High"] + regular["Low"] + regular["Close"]) / 3.0
    cum_pv = (typical_price * regular["Volume"]).cumsum()
    cum_vol = regular["Volume"].cumsum().replace(0, float("nan"))
    vwap = cum_pv / cum_vol
    avg_vol_5 = regular["Volume"].rolling(5, min_periods=1).mean().shift(1)

    n_first30 = min(30, len(regular))
    base = {"ticker": ticker, "day": str(day), "direction": direction,
            "gap_pct": round(gap_pct, 2)}

    if direction == "long":
        wrong_side = regular["Close"].iloc[:n_first30] < vwap.iloc[:n_first30]
    else:
        wrong_side = regular["Close"].iloc[:n_first30] > vwap.iloc[:n_first30]
    dip_positions = [i for i, v in enumerate(wrong_side.tolist()) if bool(v)]

    if not dip_positions:
        ref_idx = n_first30 - 1
        ref_ts = regular.index[ref_idx]
        outcome = _forward_outcome(regular, ref_idx, ref_ts, direction)
        return {**base, "group": "control_no_dip", "dipped": False,
                "triggered": False, "reclaim_time": None, "outcome": outcome}

    dip_idx = dip_positions[0]
    reclaim_idx = None
    for i in range(dip_idx + 1, len(regular)):
        vwap_i = vwap.iloc[i]
        avgvol_i = avg_vol_5.iloc[i]
        if vwap_i != vwap_i or avgvol_i != avgvol_i:  # NaN guard
            continue
        close_i = regular["Close"].iloc[i]
        vol_i = regular["Volume"].iloc[i]
        correct_side = (close_i > vwap_i) if direction == "long" else (close_i < vwap_i)
        if correct_side and vol_i >= avgvol_i:
            reclaim_idx = i
            break

    if reclaim_idx is None:
        return {**base, "group": "dip_no_reclaim", "dipped": True,
                "triggered": False, "reclaim_time": None, "outcome": None}

    reclaim_ts = regular.index[reclaim_idx]
    outcome = _forward_outcome(regular, reclaim_idx, reclaim_ts, direction)
    return {**base, "group": "reclaim", "dipped": True, "triggered": True,
            "reclaim_time": reclaim_ts.isoformat(), "outcome": outcome}


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def _continuation_rate(records: list[dict]) -> tuple[int, int]:
    hits = sum(1 for r in records if r["outcome"]["continued_horizon"])
    return hits, len(records)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                         help="cap the number of catalyst candidates probed (for a quick run)")
    parser.add_argument("--out", type=Path, default=ROOT / ".omc" / "research"
                         / "short-duration-scanner-phaseA" / "h3_results.json")
    args = parser.parse_args()

    since_ts = time.time() - LOOKBACK_DAYS * 86400
    conn = h1._connect()
    try:
        candidates = h1.load_catalyst_candidates(conn, since_ts)
    finally:
        conn.close()
    print(f"loaded {len(candidates)} catalyst-tagged ticker/day candidates from the last "
          f"{LOOKBACK_DAYS} days")
    if args.limit:
        candidates = candidates[: args.limit]

    all_results = []
    for i, row in enumerate(candidates):
        ticker = row["ticker"].upper()
        alert_dt = datetime.fromtimestamp(row["first_alert_at"], ET)
        day = alert_dt.date()
        prior = h1.daily_prior_close(ticker, day)
        if prior is None:
            continue
        gap, _prior_close = prior
        if gap == 0:
            continue  # no implied direction to test against
        direction = "long" if gap > 0 else "short"
        print(f"[{i+1}/{len(candidates)}] {ticker} {day} gap={gap:.2f}% dir={direction} "
              f"-- probing minute bars")
        result = evaluate_candidate(ticker, day, direction, gap)
        if result is not None:
            result["catalyst_type"] = row["catalyst_type"]
            all_results.append(result)

    reclaim = [r for r in all_results if r["group"] == "reclaim"]
    control = [r for r in all_results if r["group"] == "control_no_dip"]
    dip_no_reclaim = [r for r in all_results if r["group"] == "dip_no_reclaim"]

    reclaim_scored = [r for r in reclaim if r["outcome"] is not None]
    control_scored = [r for r in control if r["outcome"] is not None]

    reclaim_remaining = [r["outcome"]["remaining_move_pct_of_total_after_t5"]
                         for r in reclaim_scored
                         if r["outcome"]["remaining_move_pct_of_total_after_t5"] is not None]
    control_remaining = [r["outcome"]["remaining_move_pct_of_total_after_t5"]
                         for r in control_scored
                         if r["outcome"]["remaining_move_pct_of_total_after_t5"] is not None]

    reclaim_hits, reclaim_n = _continuation_rate(reclaim_scored)
    control_hits, control_n = _continuation_rate(control_scored)

    summary = {
        "generated_at_pacific": datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(),
        "lookback_days": LOOKBACK_DAYS,
        "primary_horizon_minutes": PRIMARY_HORIZON_MIN,
        "remaining_move_floor_pct": REMAINING_MOVE_FLOOR_PCT,
        "min_sample_floor": MIN_SAMPLE_FLOOR,
        "catalyst_candidate_count": len(candidates),
        "evaluated_count": len(all_results),
        "counts": {
            "reclaim_triggered": len(reclaim),
            "reclaim_scored": len(reclaim_scored),
            "control_no_dip": len(control),
            "control_scored": len(control_scored),
            "dip_no_reclaim_never_triggered": len(dip_no_reclaim),
        },
        "reclaim_continuation_rate": f"{reclaim_hits}/{reclaim_n}" if reclaim_n else "0/0",
        "control_continuation_rate": f"{control_hits}/{control_n}" if control_n else "0/0",
        "reclaim_median_remaining_move_pct_after_t5": _median(reclaim_remaining),
        "control_median_remaining_move_pct_after_t5": _median(control_remaining),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        **summary,
        "results": all_results,
    }, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"wrote {len(all_results)} evaluated candidates to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
