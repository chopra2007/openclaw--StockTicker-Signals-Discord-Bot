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
from .signals import conditions_gamma as CG
from .signals import conditions_phase3 as C3
from .signals import conditions_phase4 as C4

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


def _gamma_reading(sqz_panel: pd.DataFrame) -> dict:
    """Latest dealer-gamma / dark-pool reading from the SQZ panel.

    Returns a dict with keys:
      asof, gex_pct (trailing-252 percentile of GEX, or nan),
      neg_gamma (bool flag), dix_pct (trailing-252 percentile of DIX, or nan).
    """
    gex = sqz_panel.get("SQZ_gex", pd.Series(dtype=float))
    dix = sqz_panel.get("SQZ_dix", pd.Series(dtype=float))
    if gex.empty or gex.dropna().empty:
        return {"asof": None, "gex_pct": float("nan"), "neg_gamma": None, "dix_pct": float("nan")}
    gex_pct = U.trailing_percentile(gex, 252)
    dix_pct = U.trailing_percentile(dix, 252)
    neg_gamma = CG.neg_gamma_regime(sqz_panel)
    asof = gex.dropna().index[-1]
    return {
        "asof": asof,
        "gex_pct": float(gex_pct.loc[asof]) if asof in gex_pct.index and np.isfinite(gex_pct.loc[asof]) else float("nan"),
        "neg_gamma": bool(neg_gamma.loc[asof]) if asof in neg_gamma.index else None,
        "dix_pct": float(dix_pct.loc[asof]) if asof in dix_pct.index and np.isfinite(dix_pct.loc[asof]) else float("nan"),
    }


def _breadth_reading(breadth_panel: pd.DataFrame) -> dict:
    """Latest same-day 90/90 state from the NYSE_BREADTH panel.

    Returns a dict with keys:
      asof, up_share (float 0-1), down_share (float 0-1), rows (int, total panel rows).
    """
    adv = breadth_panel.get("NYSE_BREADTH_adv_volume", pd.Series(dtype=float))
    dec = breadth_panel.get("NYSE_BREADTH_dec_volume", pd.Series(dtype=float))
    if adv.empty or adv.dropna().empty:
        return {"asof": None, "up_share": float("nan"), "down_share": float("nan"), "rows": 0}
    up_share = U.up_volume_share(adv, dec)
    down_share = U.down_volume_share(adv, dec)
    asof = adv.dropna().index[-1]
    return {
        "asof": asof,
        "up_share": float(up_share.loc[asof]) if asof in up_share.index and np.isfinite(up_share.loc[asof]) else float("nan"),
        "down_share": float(down_share.loc[asof]) if asof in down_share.index and np.isfinite(down_share.loc[asof]) else float("nan"),
        "rows": int(len(adv.dropna())),
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

    # ---- DEALER-GAMMA block (descriptive only — NOT a predictor (NO-GO)) --------
    L.append("\n--- DEALER-GAMMA  [descriptive only — NOT a predictor (NO-GO)] ---")
    try:
        sqz_panel = store.load_panel(["SQZ"], start="2010-01-01")
        g = _gamma_reading(sqz_panel)
        if g["asof"] is None:
            L.append("  data not yet collected (run `python3 -m src.run_update` to fetch SQZ)")
        else:
            L.append(f"  as of {g['asof'].date()}")
            if np.isfinite(g["gex_pct"]):
                gex_bar = "#" * int(round(g["gex_pct"] * 20))
                L.append(f"  GEX trailing-252 percentile:  {g['gex_pct']*100:5.0f}th  {gex_bar}")
            else:
                L.append("  GEX trailing-252 percentile:    n/a  (fewer than 252 trading days stored)")
            if g["neg_gamma"] is None:
                neg_str = "n/a"
            elif g["neg_gamma"]:
                neg_str = "ON  (negative dealer-gamma — amplifies moves, fragile-regime)"
            else:
                neg_str = "off (positive dealer-gamma — dampens moves, stable-regime)"
            L.append(f"  Negative-gamma regime flag:   {neg_str}")
            if np.isfinite(g["dix_pct"]):
                dix_bar = "#" * int(round(g["dix_pct"] * 20))
                L.append(f"  DIX dark-pool trailing-252:   {g['dix_pct']*100:5.0f}th  {dix_bar}")
            else:
                L.append("  DIX dark-pool trailing-252:     n/a  (fewer than 252 trading days stored)")
    except FileNotFoundError:
        L.append("  data not yet collected (SQZ.parquet missing — run `python3 -m src.run_update`)")

    # ---- SAME-DAY 90/90 STATE block (descriptive only — NOT a predictor (NO-GO)) -
    L.append("\n--- SAME-DAY 90/90 STATE  [descriptive only — NOT a predictor (NO-GO)] ---")
    L.append("  NOTE: trailing-percentile context still accruing (forward feed, ~6 rows as of")
    L.append("  2026-06-18 — not enough history for percentile ranks). Bare same-day state only.")
    try:
        breadth_panel = store.load_panel(["NYSE_BREADTH"], start="2010-01-01")
        b = _breadth_reading(breadth_panel)
        if b["asof"] is None:
            L.append("  data not yet collected (run `python3 -m src.run_update` to fetch NYSE_BREADTH)")
        else:
            L.append(f"  as of {b['asof'].date()}  ({b['rows']} trading days stored)")
            up_s = b["up_share"]
            dn_s = b["down_share"]
            if np.isfinite(up_s) and np.isfinite(dn_s):
                L.append(f"  NYSE up-volume share:   {up_s*100:5.1f}%  (90% threshold = THRUST day)")
                L.append(f"  NYSE down-volume share: {dn_s*100:5.1f}%  (90% threshold = PANIC day)")
                if up_s >= 0.90:
                    state = "THRUST (>= 90% up-volume — broad re-accumulation)"
                elif dn_s >= 0.90:
                    state = "PANIC  (>= 90% down-volume — capitulation washout)"
                else:
                    state = "NEITHER (no 90/90 extreme today)"
                L.append(f"  State: {state}")
            else:
                L.append("  volume shares unavailable (check NYSE_BREADTH columns)")
    except FileNotFoundError:
        L.append("  data not yet collected (NYSE_BREADTH.parquet missing — run `python3 -m src.run_update`)")

    print("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
