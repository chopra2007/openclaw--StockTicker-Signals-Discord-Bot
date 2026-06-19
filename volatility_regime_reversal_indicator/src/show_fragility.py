"""Descriptive 'market fragility / complacency gauge' readout — DISPLAY ONLY.

    python3 -m src.show_fragility

The Phase-3 detector came back NO-GO (see backtest/PHASE3-REPORT.md): the watch-state composite
does NOT reliably predict >=8% tops. But the same composite IS a robust complacency/calm gauge
(historically a HIGH reading precedes LOWER forward volatility, and that relationship transfers
across assets). This tool prints where that gauge stands today, as honest CONTEXT — it makes NO
predictive claim and fires NO alerts. It reads the stored panel (run `python3 -m src.run_update`
first to refresh the data); the reading is as-of the latest stored date.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import store
from .features import utils as U
from .signals import conditions_phase3 as C3

_SERIES = ["SPY", "RSP", "VIX", "VIX3M", "VVIX"]  # everything top_watch_state reads

# plain-English names for the 4 component legs (keys come from watch_state_components)
_LEG_LABELS = {
    "low_vrp_complacency": "cheap crash-insurance (complacency)",
    "vix_term_stress": "near-term vol stress (flat/inverted term)",
    "vvix_tail_hedge_demand": "vol-of-vol / tail-hedge demand",
    "breadth_narrowing": "breadth narrowing (mega-cap concentration)",
}


def _label(pct: float) -> str:
    if not np.isfinite(pct):
        return "n/a"
    if pct >= 0.80:
        return "ELEVATED COMPLACENCY (calm, fragile-leaning)"
    if pct >= 0.60:
        return "above-normal calm"
    if pct >= 0.40:
        return "NORMAL"
    if pct >= 0.20:
        return "below-normal (some stress)"
    return "STRESSED (low complacency)"


def current_reading(panel: pd.DataFrame) -> dict:
    """Latest fragility-gauge reading: the composite, its trailing-1y percentile, and each leg's
    latest percentile. All point-in-time (reuses the look-ahead-tested Phase-3 functions)."""
    gauge = C3.top_watch_state(panel)
    gauge_pct = U.trailing_percentile(gauge, 252)
    comps = C3.watch_state_components(panel)
    valid = gauge.dropna()
    if valid.empty:
        return {"asof": None, "gauge": float("nan"), "gauge_pct": float("nan"), "components": {}}
    asof = valid.index[-1]
    return {
        "asof": asof,
        "gauge": float(gauge.loc[asof]),
        "gauge_pct": float(gauge_pct.loc[asof]) if np.isfinite(gauge_pct.loc[asof]) else float("nan"),
        "components": {k: float(v.loc[asof]) for k, v in comps.items()},
    }


def main() -> None:
    panel = store.load_panel(_SERIES, start="2010-01-01")
    r = current_reading(panel)
    L: list[str] = []
    L.append("=== Market fragility / complacency gauge (DESCRIPTIVE ONLY) ===")
    if r["asof"] is None:
        L.append("No reading available (insufficient stored history).")
        print("\n".join(L)); return
    L.append(f"as of {r['asof'].date()}  (stored data; run `python3 -m src.run_update` to refresh)")
    L.append("HONEST CAVEAT: this is a COMPLACENCY gauge, NOT a validated crash predictor — the")
    L.append("Phase-3 top/bottom test was NO-GO. A high reading means the market is calm/complacent")
    L.append("(historically precedes MORE calm, only occasionally trouble). Use as context only.\n")
    L.append(f"OVERALL: {r['gauge']:.3f}  =  {r['gauge_pct']*100:.0f}th percentile of the past year"
             f"  ->  {_label(r['gauge_pct'])}")
    L.append("\nComponents (each = where it sits in its own past year; HIGH = more complacent/top-like):")
    for k, label in _LEG_LABELS.items():
        v = r["components"].get(k, float("nan"))
        bar = "#" * int(round(v * 20)) if np.isfinite(v) else ""
        L.append(f"  {label:42s} {v*100:5.0f}th  {bar}")
    print("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
